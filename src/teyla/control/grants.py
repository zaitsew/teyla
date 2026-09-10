"""Grants: the capability list, turned into decisions a hook can make in milliseconds.

The manifest declares capabilities as strings. The run engine writes them, once,
into `grants.json` in the run directory and puts that path in `TEYLA_GRANTS`.
Every tool call the harness makes then goes through `decide()` here, from the
`PreToolUse` hook, and gets one of: allow, deny.

Five schemes, and each is enforced by a different piece of evidence:

    fs.write:runs/**       the Write/Edit target path, resolved through symlinks
    shell:git push         the verb of every segment of a Bash command, plus every
                           redirection target in it, checked against `fs.write:`
    net:*                  the host of a WebFetch/WebSearch URL
    send:telegram          a budget, spent by anything that looks like a send
    tool:mcp__loco__*      the tool name, for MCP and any other non-built-in tool
    tool:Agent             sub-agents (`Task`), which are not free by default
    tool:Skill:<name>      one named skill; `tool:Skill:*` for all of them

Built-in read-only tools (Read, Grep, Glob, ...) are always allowed: a routine
that cannot read cannot draft, and reading inside a repo the human already
opened is not the risk this file exists to manage. Everything else is denied
unless something above grants it.

Four things this file refuses regardless of what was granted, because each one
turns a narrow grant into a broad one:

* **Writes to the control plane's own files.** `grants.json`, `actions.jsonl`
  and friends, anywhere, and anything under `~/.teyla`. A run that can rewrite
  its own grants has none; a run that can rewrite its own action log has no
  receipt. See `state.CONTROL_BASENAMES`.
* **Environment-assignment prefixes** (`FOO=1 cmd`) unless `shell:env` is
  granted, and `PATH=`, `GIT_CONFIG*`, `LD_*`, `DYLD_*` even then. `GIT_CONFIG_KEY_0=alias.push
  GIT_CONFIG_VALUE_0='!curl…|sh' git push` is a `shell:git push` grant turned
  into arbitrary execution, and it reads as an ordinary push.
* **Process substitution** (`>(…)`, `<(…)`), which is a command hiding inside
  what looks like a filename.
* **Redirection to a path no `fs.write:` grant covers.** `echo x > ~/.ssh/authorized_keys`
  is a write, whatever the verb in front of it says.

The hole that remains, stated rather than papered over: a `net:` grant can
exfiltrate anything the run can read, and a `shell:` grant broad enough to run
an interpreter (or `cp`, or `tee`) can still write where redirection is refused.
Grant both narrowly.
"""
from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import pathlib
import re
import shlex

from . import state as S

# Built-in tools that only read. Always allowed.
#
# `Task`, `Skill` and `SlashCommand` are deliberately NOT here. Each one starts
# something that makes its own tool calls, and "read-only" was never true of them:
# a sub-agent inherits the session, not the grant list, so treating `Task` as a
# read is a hole the width of the whole tool surface.
READ_ONLY_TOOLS = frozenset({
    "Read", "Grep", "Glob", "LS", "NotebookRead", "TodoWrite", "TodoRead",
    "BashOutput", "KillShell", "KillBash", "ExitPlanMode", "AskUserQuestion",
})

# Tools that spawn a sub-agent. Allowed only under `tool:Agent` or `tool:Task`.
AGENT_TOOLS = frozenset({"Task", "Agent"})

# Tools that load a named procedure. Allowed only under `tool:Skill:<name>`.
SKILL_TOOLS = frozenset({"Skill"})

# Built-in tools that write to the filesystem. Governed by `fs.write:`.
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "Update"})

# Built-in tools that reach the network. Governed by `net:`.
NET_TOOLS = frozenset({"WebFetch", "WebSearch"})

BASH_TOOLS = frozenset({"Bash", "BashTool"})

# A deliberately coarse net over "this call puts something in front of another
# human". Coarse in the safe direction: a false positive costs one explicit
# `send:` grant in the manifest, a false negative costs a message you did not
# approve. See docs/CONTROL-PLANE.md.
SEND_RE = re.compile(
    r"send|post_message|postmessage|\bpost\b|email|mail|notify|publish|tweet|"
    r"\bdm\b|sms|telegram|slack|whatsapp|reply|broadcast",
    re.I,
)

# Shell metacharacters that hide the verb from a leading-token check. A command
# containing one is only allowed under an explicit `shell:*`.
_OPAQUE_RE = re.compile(r"\$\(|`|\$\{[^}]*\}")

# Process substitution. Refused outright, `shell:*` included: `>(sh)` is a command
# wearing a filename, and there is no reading of it that a grant list can check.
_PROCSUB_RE = re.compile(r"[<>]\(")

# Tokens that separate one command from the next. `&` belongs here as much as `&&`
# does — `cmd & evil` backgrounds the granted half and runs the other one, and a
# splitter that only knows `&&` sees one granted command.
SEGMENT_OPERATORS = frozenset({"&&", "||", "&", ";", "|", "|&", ";;", "\n"})

# Redirections whose target is written to. `<` is a read and is not here.
WRITE_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>", ">&"})
READ_REDIRECTS = frozenset({"<", "<<", "<<<", "<&", "<>"})

# Environment prefixes that are refused even when `shell:env` is granted, because
# each one redirects what the *granted* verb afterwards actually executes.
FORBIDDEN_ENV_PREFIXES = ("PATH", "GIT_CONFIG", "LD_", "DYLD_", "BASH_ENV", "ENV",
                          "IFS", "SHELL", "PYTHONPATH", "PYTHONSTARTUP", "NODE_OPTIONS")

_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")

ALLOW = "allow"
DENY = "deny"


# --- building ---------------------------------------------------------------------


def build(routine, *, run_id: str, run_dir, grants_path, state_path, actions_path) -> dict:
    """The grants document written next to the run. Self-contained on purpose: the hook
    reads this file and nothing else, so it keeps working if the manifest is edited
    mid-run, and the receipt can quote exactly what was granted."""
    from .manifest import group_capabilities

    grouped = group_capabilities(routine.capabilities)
    return {
        "version": 1,
        "run_id": run_id,
        "routine": routine.ref,
        "product": routine.product,
        "repo": str(routine.repo),
        "gate": routine.gate,
        "capabilities": list(routine.capabilities),
        "grants": grouped,
        "caps": dict(routine.caps),
        "run_dir": str(run_dir),
        "grants_path": str(grants_path),
        "state": str(state_path),
        "actions": str(actions_path),
    }


def load(path) -> dict:
    return json.loads(pathlib.Path(path).read_text())


# --- matching primitives ------------------------------------------------------------


def _norm(p: str) -> str:
    return str(p).replace(os.sep, "/")


def _glob_re(pattern: str) -> re.Pattern:
    """Compile one glob, path-aware: `*` and `?` stop at `/`, only `**` crosses it.

    `fnmatch` does not make that distinction, which is how `fs.write:*.md` came to
    match `.claude/rules/pwn.md` — a grant meant for the top level quietly covering
    every markdown file in the tree, rule files included."""
    out = ["(?s)\\A"]
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if pattern.startswith("**", i):
                # `**/` may match nothing at all, so `a/**/b` also matches `a/b`.
                if pattern.startswith("**/", i):
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
            continue
        if c == "?":
            out.append("[^/]")
            i += 1
            continue
        if c == "[":
            j = pattern.find("]", i + 1)
            if j != -1:
                body = pattern[i + 1:j]
                body = body.replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = j + 1
                continue
        out.append(re.escape(c))
        i += 1
    out.append("\\Z")
    return re.compile("".join(out))


_GLOB_CACHE: dict[str, re.Pattern] = {}


def glob_match(candidate: str, pattern: str) -> bool:
    """One path against one glob, with `*` confined to a single path segment."""
    rx = _GLOB_CACHE.get(pattern)
    if rx is None:
        rx = _GLOB_CACHE[pattern] = _glob_re(pattern)
    return bool(rx.match(candidate))


def resolve_target(target, repo) -> pathlib.Path:
    """The path a write would really land on: absolute, with every symlink in it
    followed. `os.path.realpath` resolves the components that exist and leaves the
    rest alone, which is what a not-yet-created file needs."""
    t = pathlib.Path(str(target)).expanduser()
    repo = pathlib.Path(str(repo)).expanduser()
    base = t if t.is_absolute() else (repo / t)
    return pathlib.Path(os.path.realpath(str(base)))


def path_matches(target, patterns, repo) -> bool:
    """Does `target` fall under any `fs.write:` pattern?

    The path is resolved through symlinks first, then matched against the pattern
    both relative to the repo root and absolute, so `runs/**` and `/tmp/scratch/**`
    both work. A pattern that is *not* absolute only ever matches inside the repo:
    a relative-looking path that resolves out of the tree is a symlink escape, and
    `runs/**` was never a grant to write wherever `runs/x` happens to point."""
    ok, _ = write_target_ok(target, patterns, repo)
    return ok


def write_target_ok(target, patterns, repo) -> tuple[bool, str]:
    """`path_matches` with the reason attached, and the two absolute refusals in
    front of it: the control plane's own files, and `~/.teyla`."""
    if not str(target or "").strip():
        return False, "no path to check against `fs.write:`"
    repo_p = pathlib.Path(str(repo)).expanduser()
    try:
        real = resolve_target(target, repo_p)
    except (OSError, ValueError) as e:
        return False, f"{target!r} could not be resolved ({e})"

    if S.is_control_path(target) or S.is_control_path(real):
        return False, (f"{target} is a control-plane file — the run's own grants, counters, "
                       f"action log or receipt. No grant covers these, by design")

    if not patterns:
        return False, "no `fs.write:` capability is granted for this run"

    try:
        repo_real = pathlib.Path(os.path.realpath(str(repo_p)))
    except (OSError, ValueError):
        repo_real = repo_p
    try:
        rel = _norm(real.relative_to(repo_real))
        inside = True
    except ValueError:
        rel, inside = None, False

    for raw in patterns:
        pat = _norm(str(raw)).strip()
        if not pat:
            continue
        if pat in ("*", "**", "**/*"):
            return True, f"`fs.write:{raw}` covers everything"
        absolute = pat.startswith("/") or pat.startswith("~")
        if pat.startswith("~"):
            pat = _norm(str(pathlib.Path(pat).expanduser()))
        candidates = [_norm(real)] if absolute else ([rel] if inside else [])
        for c in candidates:
            if c is None:
                continue
            if glob_match(c, pat):
                return True, f"{target} is within `fs.write:{raw}`"
            # `runs/**` also names the directory `runs` itself.
            if pat.endswith("/**") and (c == pat[:-3] or glob_match(c, pat[:-3])):
                return True, f"{target} is within `fs.write:{raw}`"

    granted = ", ".join(str(p) for p in patterns) or "(none)"
    if not inside and not any(str(p).strip().startswith(("/", "~")) for p in patterns):
        return False, (f"{target} resolves to {real}, outside the repo {repo_real} — "
                       f"the `fs.write:` grants [{granted}] are all repo-relative")
    return False, f"{target} is outside the `fs.write:` grants [{granted}]"


# --- reading a shell command --------------------------------------------------------


def tokenize(command: str) -> list[str]:
    """One command string -> words and operators, quotes respected.

    `shlex` with `punctuation_chars` is the only stdlib thing that knows `&&` from
    `&`, and it keeps `>`/`>>`/`<(` as their own tokens, which is what the
    redirection and process-substitution checks below need."""
    lexer = shlex.shlex(command or "", punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # An unbalanced quote. Fall back to a dumb split; the caller fails closed
        # on anything it cannot read a verb from anyway.
        return (command or "").split()


def split_segments(command: str) -> list[list[str]]:
    """The command, cut at every separator, as a list of token lists. Every one of
    them has to be granted — that is the whole point of splitting."""
    out: list[list[str]] = []
    cur: list[str] = []
    for tok in tokenize(command):
        if tok in SEGMENT_OPERATORS:
            if cur:
                out.append(cur)
            cur = []
            continue
        cur.append(tok)
    if cur:
        out.append(cur)
    return out


def _unquote(tok: str) -> str:
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        return tok[1:-1]
    return tok


def segment_parts(tokens) -> tuple[list[str], list[str], list[str]]:
    """One segment -> `(env assignments, write-redirection targets, words)`.

    The words are what a `shell:` grant is matched against; the redirection targets
    are handed to the `fs.write:` check. File-descriptor targets (`2>&1`) are not
    files and are dropped."""
    assigns: list[str] = []
    redirects: list[str] = []
    words: list[str] = []
    i, n = 0, len(tokens)
    leading = True
    while i < n:
        tok = tokens[i]
        if leading and _ASSIGN_RE.match(tok):
            assigns.append(tok)
            i += 1
            continue
        if tok in WRITE_REDIRECTS or tok in READ_REDIRECTS:
            # `2>file` lexes as `2`, `>`, `file`: the fd digit is not a word.
            if words and words[-1].isdigit():
                words.pop()
            target = _unquote(tokens[i + 1]) if i + 1 < n else ""
            if tok in WRITE_REDIRECTS and target and not target.isdigit() and target != "-":
                redirects.append(target)
            i += 2
            continue
        leading = False
        words.append(tok)
        i += 1
    return assigns, redirects, words


# The only variables a redirection target may be written in terms of. A step is
# *supposed* to write its reversal to `$TEYLA_UNDO`, so the check has to be able to
# read that; expanding anything else would let the command choose its own target
# name and hand the checker a different string from the one the shell will use.
EXPANDABLE = ("TEYLA_UNDO", "TEYLA_RUN_DIR", "TEYLA_REPO", "TEYLA_RUN_ID")


def expand_target(target: str, env=None) -> str | None:
    """A redirection target with the known `TEYLA_*` variables filled in. `None` if
    anything else in it is still unresolved — an unresolvable target is one the
    checker cannot vouch for, and it is refused rather than guessed at."""
    if env is None:
        env = os.environ
    out = target or ""
    if "$" not in out:
        return out
    for name in EXPANDABLE:
        value = env.get(name)
        if not value:
            continue
        out = out.replace(f"${{{name}}}", str(value)).replace(f"${name}", str(value))
    return None if "$" in out else out


def _env_prefix_problem(assigns) -> str | None:
    for a in assigns:
        m = _ASSIGN_RE.match(a)
        name = m.group(1) if m else a
        for bad in FORBIDDEN_ENV_PREFIXES:
            if name == bad or name.startswith(bad):
                return (f"the segment sets {name}=, which changes what the verb after it actually "
                        f"runs (PATH/GIT_CONFIG*/LD_*/DYLD_* and friends are refused even under "
                        f"`shell:env`)")
    return None


def shell_allowed(command: str, patterns, *, fs_write=(), repo=".", env=None) -> tuple[bool, str]:
    """Every segment of a Bash command must be matched by some `shell:` grant, and
    every path it redirects into must be matched by an `fs.write:` grant.

    A grant is matched token-wise against the head of the segment: `shell:git push`
    matches `git push origin main` and not `git commit`. `shell:*` grants every
    verb, including the opaque forms (command substitution) that are otherwise
    refused because they hide the verb this check depends on — but it does not
    grant process substitution, and it does not exempt a redirection from
    `fs.write:`."""
    command = command or ""

    if _PROCSUB_RE.search(command):
        return False, ("command uses process substitution (`>(...)` / `<(...)`), which runs a "
                       "command where a filename is expected. Refused under every grant")

    star = any(str(p).strip() == "*" for p in patterns or ())
    if not patterns:
        return False, "no `shell:` capability is granted for this run"
    env_granted = any(str(p).strip() == "env" for p in patterns or ()) or star

    if not star and _OPAQUE_RE.search(command):
        return False, "command uses substitution ($(...), backticks, ${...}), which hides the verb — needs `shell:*`"

    segments = split_segments(command)
    if not segments:
        return False, "empty command"

    for seg in segments:
        assigns, redirects, words = segment_parts(seg)

        problem = _env_prefix_problem(assigns)
        if problem:
            return False, problem
        if assigns and not env_granted:
            names = ", ".join(a.split("=", 1)[0] for a in assigns)
            return False, (f"the segment sets {names} before its verb; an environment prefix can "
                           f"redirect what that verb does, so it needs `shell:env`")

        for target in redirects:
            resolved = expand_target(target, env)
            if resolved is None:
                return False, (f"redirection writes to {target}, which contains a variable this "
                               f"check cannot resolve — an unverifiable write target is refused")
            ok, why = write_target_ok(resolved, list(fs_write or ()), repo)
            if not ok:
                return False, f"redirection writes to {target}: {why}"

        if not words:
            if redirects or assigns:
                continue  # a bare `> file` segment: the write was already checked
            return False, f"cannot read a verb from segment {' '.join(seg)!r}"

        if star:
            continue
        toks = [_unquote(w) for w in words]
        ok = False
        for pat in patterns:
            want = str(pat).split()
            if not want or want == ["env"]:
                continue
            if len(toks) < len(want):
                continue
            if all(fnmatch.fnmatch(toks[i], want[i]) for i in range(len(want))):
                ok = True
                break
        if not ok:
            verb = " ".join(toks[:2])
            granted = ", ".join(str(p) for p in patterns)
            return False, f"`{verb}` is not matched by any `shell:` grant ({granted})"

    return True, ("shell:*, with every redirection checked against `fs.write:`" if star
                  else "a shell grant matched every segment, and every redirection was within `fs.write:`")


def leading_tokens(segment: str) -> list[str]:
    """The verb of one command segment, for logging. Assignments and redirections
    are stripped. Not a security check — `shell_allowed` is."""
    segs = split_segments(segment)
    if not segs:
        return []
    _, _, words = segment_parts(segs[0])
    return [_unquote(w) for w in words]


def tool_matches(tool_name: str, patterns) -> bool:
    return any(fnmatch.fnmatch(tool_name, str(p)) for p in patterns or [])


def net_allowed(url: str, patterns) -> tuple[bool, str]:
    if not patterns:
        return False, "no `net:` capability is granted for this run"
    if any(str(p).strip() == "*" for p in patterns):
        return True, "net:*"
    host = ""
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)", str(url or ""), re.I)
    if m:
        host = m.group(1).split("@")[-1].split(":")[0]
    if not host:
        return False, f"cannot read a host from {url!r}"
    for pat in patterns:
        pat = str(pat).strip()
        if fnmatch.fnmatch(host, pat) or host == pat or host.endswith("." + pat):
            return True, f"net grant {pat} matched host {host}"
    return False, f"host {host} is not matched by any `net:` grant ({', '.join(patterns)})"


def looks_like_send(tool_name: str, command: str = "") -> bool:
    return bool(SEND_RE.search(tool_name or "") or SEND_RE.search(command or ""))


def _names_a_control_file(command: str) -> str | None:
    """Does a Bash command mention the control plane's own state at all?

    Deliberately coarse: a shell command can reach a file in more ways than a
    checker can enumerate (`cd`, a variable, a relative path, `find -exec`), so the
    test is whether the string names one of these at all, not whether this
    particular invocation would write to it. A false positive costs one renamed
    scratch file; a false negative costs the receipt its meaning."""
    text = command or ""
    for name in S.CONTROL_BASENAMES:
        if name in text:
            return name
    home = str(S.home())
    for needle in (home, "~/.teyla", "$TEYLA_HOME", "${TEYLA_HOME}", "$TEYLA_GRANTS", "${TEYLA_GRANTS}"):
        if needle and needle in text:
            return needle
    return None


# --- counters ---------------------------------------------------------------------


ZERO_STATE = {"writes": 0, "sends": 0, "calls": 0, "denied": 0}


def read_state(path) -> dict:
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return dict(ZERO_STATE)
    if not isinstance(data, dict):
        return dict(ZERO_STATE)
    for k in ZERO_STATE:
        data.setdefault(k, 0)
    return data


def write_state(path, state: dict) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state))


@contextlib.contextmanager
def state_transaction(path):
    """Read-modify-write the counter file under an exclusive `flock`.

    Two tool calls in flight at once — which is the normal case, the harness runs
    them in parallel — were both reading `writes: 4`, both deciding they were under
    a cap of 5, and both writing `5`. The cap leaked one call per race. The lock is
    held for the whole read-decide-write, not just the write, because it is the
    decision that has to be serialised, not the bytes."""
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = p.with_name(p.name + ".lock")
    fd = None
    try:
        fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        fd = None
    try:
        if fd is not None:
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
        st = read_state(p)
        yield st
        try:
            write_state(p, st)
        except OSError:
            pass
    finally:
        if fd is not None:
            try:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            os.close(fd)


# --- the decision -------------------------------------------------------------------


def decide(tool_name: str, tool_input: dict, doc: dict, state: dict) -> tuple[str, str, dict]:
    """One tool call -> (ALLOW|DENY, reason, counter deltas).

    Pure: it reads the grants document and the current counters and returns what
    should happen. The hook does the I/O and turns this into an exit code, so the
    whole decision table is testable without a subprocess or a transcript."""
    grants = doc.get("grants") or {}
    caps = doc.get("caps") or {}
    repo = doc.get("repo") or "."
    tool_input = tool_input or {}
    delta: dict = {}

    fs_write = grants.get("fs.write") or []
    shell = grants.get("shell") or []
    net = grants.get("net") or []
    send = grants.get("send") or []
    tools = grants.get("tool") or []

    # 1. writes
    if tool_name in WRITE_TOOLS:
        target = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("notebook_path") or ""
        if not target:
            return DENY, f"{tool_name}: no file_path in the tool input to check against `fs.write:`", delta
        ok, why = write_target_ok(target, fs_write, repo)
        if not ok:
            return DENY, f"{tool_name}: {why}", delta
        limit = caps.get("max_writes")
        if limit is not None and state.get("writes", 0) >= limit:
            return DENY, f"write cap reached: max_writes={limit}", delta
        delta["writes"] = 1
        return ALLOW, f"{tool_name}: {why}", delta

    # 2. shell
    if tool_name in BASH_TOOLS:
        command = tool_input.get("command") or ""
        named = _names_a_control_file(command)
        if named:
            return DENY, (f"Bash: the command names {named}, which is control-plane state "
                          f"(the run's grants, counters, action log or receipt). Refused under "
                          f"every grant"), delta
        ok, why = shell_allowed(command, shell, fs_write=fs_write, repo=repo)
        if not ok:
            return DENY, f"Bash: {why}", delta
        if looks_like_send(tool_name="", command=command):
            ok_send, why_send, d = _spend_send(send, caps, state, what=f"Bash command {command[:60]!r}")
            if not ok_send:
                return DENY, why_send, delta
            delta.update(d)
        return ALLOW, f"Bash: {why}", delta

    # 2b. sub-agents and skills. Neither is read-only, and a sub-agent that inherited
    # the session without inheriting the grant list is the whole tool surface again.
    if tool_name in AGENT_TOOLS:
        if not (tool_matches("Agent", tools) or tool_matches("Task", tools)):
            granted = ", ".join(tools) or "(none)"
            return DENY, (f"{tool_name} starts a sub-agent, which is not covered by any `tool:` "
                          f"grant [{granted}] — grant `tool:Agent` to allow it"), delta
        return ALLOW, f"{tool_name} matched a `tool:Agent` grant", delta

    if tool_name in SKILL_TOOLS:
        name = str(tool_input.get("skill") or tool_input.get("name") or "").strip()
        if not name:
            return DENY, "Skill: no skill name in the tool input to check against `tool:Skill:<name>`", delta
        want = f"Skill:{name}"
        for p in tools:
            p = str(p).strip()
            if p in ("Skill", "Skill:*") or fnmatch.fnmatch(want, p):
                return ALLOW, f"Skill {name!r} matched the `tool:{p}` grant", delta
        granted = ", ".join(tools) or "(none)"
        return DENY, (f"the skill {name!r} is not matched by any `tool:` grant [{granted}] — "
                      f"grant `tool:Skill:{name}`, or `tool:Skill:*` for all of them"), delta

    # 3. network
    if tool_name in NET_TOOLS:
        url = tool_input.get("url") or tool_input.get("query") or ""
        if tool_name == "WebSearch":
            if not net:
                return DENY, "WebSearch: no `net:` capability is granted for this run", delta
            return ALLOW, "WebSearch: `net:` granted", delta
        ok, why = net_allowed(url, net)
        return (ALLOW, f"WebFetch: {why}", delta) if ok else (DENY, f"WebFetch: {why}", delta)

    # 4. always-allowed read-only built-ins
    if tool_name in READ_ONLY_TOOLS:
        return ALLOW, f"{tool_name} is read-only", delta

    # 5. everything else — MCP tools, plugin tools, anything unrecognised
    if not tool_matches(tool_name, tools):
        granted = ", ".join(tools) or "(none)"
        return DENY, f"{tool_name} is not matched by any `tool:` grant [{granted}]", delta
    if looks_like_send(tool_name):
        ok_send, why_send, d = _spend_send(send, caps, state, what=tool_name)
        if not ok_send:
            return DENY, why_send, delta
        delta.update(d)
    return ALLOW, f"{tool_name} matched a `tool:` grant", delta


def _spend_send(send_grants, caps, state, *, what: str) -> tuple[bool, str, dict]:
    if not send_grants:
        return False, f"{what} looks like a send and no `send:` capability is granted for this run", {}
    limit = caps.get("max_sends")
    if limit is not None and state.get("sends", 0) >= limit:
        return False, f"send cap reached: max_sends={limit}", {}
    return True, "", {"sends": 1}

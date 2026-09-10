"""Grants: the capability list, turned into decisions a hook can make in milliseconds.

The manifest declares capabilities as strings. The run engine writes them, once,
into `grants.json` in the run directory and puts that path in `TEYLA_GRANTS`.
Every tool call the harness makes then goes through `decide()` here, from the
`PreToolUse` hook, and gets one of: allow, deny.

Five schemes, and each is enforced by a different piece of evidence:

    fs.write:runs/**       the Write/Edit target path, resolved against the repo
    shell:git push         the leading verb of every segment of a Bash command
    net:*                  the host of a WebFetch/WebSearch URL
    send:telegram          a budget, spent by anything that looks like a send
    tool:mcp__loco__*      the tool name, for MCP and any other non-built-in tool

Built-in read-only tools (Read, Grep, Glob, ...) are always allowed: a routine
that cannot read cannot draft, and reading inside a repo the human already
opened is not the risk this file exists to manage. Everything else is denied
unless something above grants it. That is the whole security model, and it is
worth being explicit that it has two known holes, both documented rather than
papered over: a `shell:` grant can write files a `fs.write:` grant would refuse
(via redirection), and a `net:` grant can exfiltrate anything the run can read.
Grant both narrowly.
"""
from __future__ import annotations

import fnmatch
import json
import os
import pathlib
import re
import shlex

# Built-in tools that only read. Always allowed.
READ_ONLY_TOOLS = frozenset({
    "Read", "Grep", "Glob", "LS", "NotebookRead", "TodoWrite", "TodoRead",
    "BashOutput", "KillShell", "KillBash", "ExitPlanMode", "AskUserQuestion",
    "Task", "SlashCommand", "Skill",
})

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

_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\||\n")

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


def path_matches(target, patterns, repo) -> bool:
    """Does `target` fall under any `fs.write:` pattern?

    Patterns are matched against the path relative to the repo root, and against the
    absolute path, so both `runs/**` and `/tmp/scratch/**` work. Matching is fnmatch,
    which means `*` crosses `/` — write `runs/**`, and read `runs/*` as meaning the
    same thing rather than one level."""
    if not patterns:
        return False
    t = pathlib.Path(str(target)).expanduser()
    repo = pathlib.Path(str(repo)).expanduser()
    try:
        t_abs = t if t.is_absolute() else (repo / t)
        t_abs = pathlib.Path(os.path.normpath(str(t_abs)))
    except (OSError, ValueError):
        return False
    try:
        rel = _norm(t_abs.relative_to(repo))
    except ValueError:
        rel = None

    for pat in patterns:
        pat = _norm(str(pat)).strip()
        if pat in ("*", "**", "**/*"):
            return True
        if pat.startswith("~"):
            pat = _norm(str(pathlib.Path(pat).expanduser()))
        candidates = [_norm(t_abs)]
        if rel is not None:
            candidates.append(rel)
        for c in candidates:
            if fnmatch.fnmatch(c, pat):
                return True
            # `runs/**` should also match the directory `runs` itself and `runs/x`
            if pat.endswith("/**") and (c == pat[:-3] or fnmatch.fnmatch(c, pat[:-3] + "/*")):
                return True
    return False


def split_segments(command: str) -> list[str]:
    return [s.strip() for s in _SEGMENT_SPLIT_RE.split(command or "") if s.strip()]


def leading_tokens(segment: str) -> list[str]:
    """The verb of one command segment, with leading `VAR=value` assignments and any
    `env`/`sudo`-style prefix stripped, so `FOO=1 git push` is still `git push`."""
    try:
        toks = shlex.split(segment)
    except ValueError:
        toks = segment.split()
    while toks and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]):
        toks.pop(0)
    return toks


def shell_allowed(command: str, patterns) -> tuple[bool, str]:
    """Every segment of a Bash command must be matched by some `shell:` grant.

    A grant is matched token-wise against the head of the segment: `shell:git push`
    matches `git push origin main` and not `git commit`. `shell:*` grants everything,
    including the opaque forms (command substitution) that are otherwise refused
    because they hide the verb this check depends on."""
    if not patterns:
        return False, "no `shell:` capability is granted for this run"
    if any(str(p).strip() == "*" for p in patterns):
        return True, "shell:*"
    if _OPAQUE_RE.search(command or ""):
        return False, "command uses substitution ($(...), backticks, ${...}), which hides the verb — needs `shell:*`"

    segments = split_segments(command)
    if not segments:
        return False, "empty command"
    for seg in segments:
        toks = leading_tokens(seg)
        if not toks:
            return False, f"cannot read a verb from segment {seg!r}"
        ok = False
        for pat in patterns:
            want = str(pat).split()
            if not want:
                continue
            if len(toks) < len(want):
                continue
            if all(fnmatch.fnmatch(toks[i], want[i]) for i in range(len(want))):
                ok = True
                break
        if not ok:
            verb = " ".join(toks[:2])
            return False, f"`{verb}` is not matched by any `shell:` grant ({', '.join(patterns)})"
    return True, "shell grant matched every segment"


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


# --- counters ---------------------------------------------------------------------


def read_state(path) -> dict:
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return {"writes": 0, "sends": 0, "calls": 0, "denied": 0}
    for k in ("writes", "sends", "calls", "denied"):
        data.setdefault(k, 0)
    return data


def write_state(path, state: dict) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state))


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
        if not path_matches(target, fs_write, repo):
            granted = ", ".join(fs_write) or "(none)"
            return DENY, f"{tool_name} to {target} is outside the `fs.write:` grants [{granted}]", delta
        limit = caps.get("max_writes")
        if limit is not None and state.get("writes", 0) >= limit:
            return DENY, f"write cap reached: max_writes={limit}", delta
        delta["writes"] = 1
        return ALLOW, f"{tool_name} to {target} is within `fs.write:`", delta

    # 2. shell
    if tool_name in BASH_TOOLS:
        command = tool_input.get("command") or ""
        ok, why = shell_allowed(command, shell)
        if not ok:
            return DENY, f"Bash: {why}", delta
        if looks_like_send(tool_name="", command=command):
            ok_send, why_send, d = _spend_send(send, caps, state, what=f"Bash command {command[:60]!r}")
            if not ok_send:
                return DENY, why_send, delta
            delta.update(d)
        return ALLOW, f"Bash: {why}", delta

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

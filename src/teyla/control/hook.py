"""The `PreToolUse` hook: the only place a capability is actually enforced.

Claude Code runs this before every tool call, feeding the call on stdin as JSON
(`tool_name`, `tool_input`, `cwd`, `session_id`, ...). The contract used here is
the documented one: **exit 0 allows the call, exit 2 blocks it and shows stderr
to the model**, and any other non-zero is a non-blocking error. So every path
below ends in exactly one of 0 or 2 — there is no third answer, and "the hook
crashed" must not become "the tool ran".

Four states, in order:

1. `~/.teyla/KILL` exists       -> exit 2, with the reason. Nothing else is read.
2. `TEYLA_GRANTS` is not set,
   and no run is in flight      -> exit 0, silently. This is an ordinary session,
                                   not a routine run, and the hook must be invisible.
3. `TEYLA_GRANTS` is not set,
   but a run *is* in flight     -> exit 2. A session with no grants while a run is
                                   running is not an ordinary session; it is a way
                                   out of one. See "the nested session" below.
4. `TEYLA_GRANTS` is set        -> load the grants, decide, count, log, exit 0 or 2.

Fail closed inside state 4 and only there. If the grants file is unreadable or
the payload will not parse, a run that was explicitly launched under grants gets
its tool call blocked rather than waved through; an ordinary session, which
never reaches state 4, is untouched by any of it.

**The nested session.** An agent under grants can spawn its own `claude -p`. That
child inherits the environment, so it inherits `TEYLA_GRANTS` and stays governed —
the common case is covered. What state 3 catches is the child that arrives without
it: launched with a scrubbed environment, or through some other path into the same
machine. It cannot distinguish that child from an unrelated session the human
started while a routine happened to be running, so it refuses both and says why.
That is the trade, and it is the safe side of it.

Every decision — allow and deny alike — is appended to `actions.jsonl`, **HMAC
signed** with a key under `~/.teyla` that no grant can reach. That file is what
the receipt's "actions taken" is built from; unsigned, a run that could append to
it could write its own history.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

from . import grants as G
from . import state as S

EXIT_ALLOW = 0
EXIT_BLOCK = 2


def _log(doc: dict, record: dict) -> None:
    path = doc.get("actions")
    if not path:
        return
    try:
        S.append_signed_jsonl(pathlib.Path(path), record)
    except OSError:
        pass


def main(stdin=None, stderr=None) -> int:
    stderr = stderr or sys.stderr

    reason = S.kill_reason()
    if reason is not None:
        print(f"teyla: KILL SWITCH IS ON — every tool call is denied.\n  reason: {reason}\n"
              f"  clear it with: teyla kill off", file=stderr)
        return EXIT_BLOCK

    grants_path = os.environ.get("TEYLA_GRANTS")
    if not grants_path:
        live = S.active_runs()
        if live:
            print("teyla: a run is active but this session has no grants.\n"
                  f"  in flight: {', '.join(live)}\n"
                  "  A tool call with no TEYLA_GRANTS while a routine is running cannot be told\n"
                  "  apart from a routine escaping its own grants, so it is refused. Wait for the\n"
                  "  run to finish, or stop it with: teyla kill on --reason \"...\"",
                  file=stderr)
            return EXIT_BLOCK
        return EXIT_ALLOW

    try:
        doc = G.load(grants_path)
    except (OSError, ValueError) as e:
        print(f"teyla: TEYLA_GRANTS={grants_path} could not be read ({e}); refusing the call.", file=stderr)
        return EXIT_BLOCK

    raw = (stdin or sys.stdin).read()
    try:
        payload = json.loads(raw)
    except ValueError:
        print("teyla: could not parse the PreToolUse payload; refusing the call.", file=stderr)
        _log(doc, {"ts": S.stamp(), "tool": "?", "decision": "deny", "reason": "unparseable payload"})
        return EXIT_BLOCK

    tool_name = payload.get("tool_name") or "?"
    tool_input = payload.get("tool_input") or {}

    # The decision and the counter update happen under one lock. Two parallel tool
    # calls both reading `writes: 4` and both deciding they were under a cap of 5 is
    # how a cap leaks one call per race.
    state_path = doc.get("state")
    if state_path:
        with G.state_transaction(state_path) as st:
            decision, why, delta = G.decide(tool_name, tool_input, doc, st)
            st["calls"] = st.get("calls", 0) + 1
            for k, v in delta.items():
                st[k] = st.get(k, 0) + v
            if decision == G.DENY:
                st["denied"] = st.get("denied", 0) + 1
            counters = {"writes": st.get("writes", 0), "sends": st.get("sends", 0)}
    else:
        st = dict(G.ZERO_STATE)
        decision, why, delta = G.decide(tool_name, tool_input, doc, st)
        counters = {"writes": st.get("writes", 0), "sends": st.get("sends", 0)}

    _log(doc, {
        "ts": S.stamp(),
        "run_id": doc.get("run_id"),
        "tool": tool_name,
        "decision": decision,
        "reason": why,
        "detail": _detail(tool_name, tool_input),
        "counters": counters,
    })

    if decision == G.ALLOW:
        return EXIT_ALLOW
    print(f"teyla: blocked by the routine's capability grants.\n  {why}\n"
          f"  routine: {doc.get('routine')}  run: {doc.get('run_id')}\n"
          f"  granted: {', '.join(doc.get('capabilities') or []) or '(nothing)'}", file=stderr)
    return EXIT_BLOCK


def _detail(tool_name: str, tool_input: dict) -> str:
    """One short, non-secret line naming what the call was about — a path, a verb, a
    host. Never the file content or the full command: `actions.jsonl` ends up in a
    receipt, and a receipt that quotes payloads is a new place for secrets to live."""
    if tool_name in G.WRITE_TOOLS:
        return str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if tool_name in G.BASH_TOOLS:
        toks = G.leading_tokens((tool_input.get("command") or "").split("\n")[0])
        return " ".join(toks[:3])
    if tool_name in G.NET_TOOLS:
        return str(tool_input.get("url") or "")[:120]
    return ""


if __name__ == "__main__":  # pragma: no cover - exercised through the sh wrapper
    sys.exit(main())

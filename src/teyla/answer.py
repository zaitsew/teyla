"""`teyla answer <id-prefix> <text...> [--json] [--dry]` — deliver an answer to the session that asked.

Tried in order, and the first that works is reported as `via`:

1. Codex: `codex exec resume <session> <text>` in the session's own directory, started detached
   (a model run outlives any timeout here), via `codex-resume`. If it fails to start,
   `codex queue --thread <session> --message <text>`, via `codex-queue`: that exits 0 but the
   message waits until the session is opened in the Codex app.
2. Claude Code and the Claude desktop app: `claude --bg --resume <cliSessionId> [--permission-mode M] <text>`
   in the session's directory (worktree if it still exists), via `claude-bg`.
3. Fallback `opened`: the text goes to the clipboard and the session's link is opened.

On success the item is marked done with the note "answered in Teyla via <via>". `--dry` prints
the commands and runs nothing. Every subprocess goes through `run`, so tests replace one function.
"""
from __future__ import annotations

import json
import os
import pathlib
import shlex
import subprocess
import sys
import time

from . import asks
from .adapters import claude_code, codex

TIMEOUT = 30
DETACH_WAIT_S = 3.0
PERMISSION_MODES = ("acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")
OPENABLE = ("claude://", "codex://", "https://")
QUEUE_DETAIL = "waits until the session is opened"


def run(cmd: list[str], cwd: str | None = None, input_text: str | None = None, timeout: int = TIMEOUT,
        detach: str | None = None) -> tuple[int, str]:
    """(exit code, last line of output). 127 = no such program, 124 = timed out. With `detach`
    (a log path) the command is started on its own and left running: it is reported as started
    once it has stayed up for a few seconds, or by its exit code when it dies sooner."""
    try:
        if detach:
            pathlib.Path(detach).parent.mkdir(parents=True, exist_ok=True)
            with open(detach, "ab") as log:
                p = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True)
            end = time.monotonic() + DETACH_WAIT_S
            while time.monotonic() < end:
                code = p.poll()
                if code is not None:
                    return code, _tail(pathlib.Path(detach).read_text(errors="replace"))
                time.sleep(0.1)
            return 0, f"started, log {detach}"
        r = subprocess.run(cmd, cwd=cwd, input=input_text, capture_output=True, text=True, timeout=timeout)
        return r.returncode, _tail(r.stdout + "\n" + r.stderr)
    except FileNotFoundError:
        return 127, f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]}: timed out after {timeout}s"
    except OSError as e:
        return 126, str(e)


def _tail(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[-1][:300] if lines else ""


def _dir(*candidates) -> str | None:
    for c in candidates:
        if c and os.path.isdir(str(c)):
            return str(c)
    return None


def _flag_text(text: str) -> list[str]:
    return ["--", text] if text.startswith("-") else [text]


# --- where a session lives --------------------------------------------------------------------

def codex_cwd(sid: str) -> str | None:
    """The working directory in the first record of the session's rollout (live or archived)."""
    for f in codex.locate(sid):
        try:
            for o in asks.iter_jsonl(f):
                if o.get("type") == "session_meta":
                    p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
                    return _dir(p.get("cwd"))
                break
        except OSError:
            continue
    return None


def claude_meta(cli_id: str) -> dict:
    """The desktop app's record for this Claude session, or {} (a plain Claude Code session)."""
    root = asks.desktop_root()
    if os.path.isdir(root):
        for d in asks._desktop_sessions(root):
            if str(d.get("cliSessionId") or "") == cli_id:
                return d
    return {}


def claude_cwd(cli_id: str, meta: dict) -> str | None:
    found = _dir(meta.get("worktreePath"), meta.get("cwd"), meta.get("originCwd"))
    if found or meta:
        return found
    import glob
    for f in glob.glob(os.path.join(claude_code.DEFAULT_ROOT, "*", f"{cli_id}.jsonl")):
        ana = asks.scan_claude(f)
        return _dir((ana or {}).get("cwd"))
    return None


# --- the plan ---------------------------------------------------------------------------------

def open_target(a: asks.Ask) -> str:
    if a.harness == "codex" and a.session:
        return f"codex://threads/{a.session}"
    return a.link if a.link.startswith(OPENABLE) else ""


def plan(a: asks.Ask, text: str) -> list[dict]:
    """Ordered attempts for this item. A step is {via, cmd, cwd, detach?, detail?}."""
    steps: list[dict] = []
    if a.harness == "codex" and a.session:
        cwd = codex_cwd(a.session) or str(pathlib.Path.home())
        steps.append({"via": "codex-resume", "cmd": ["codex", "exec", "resume", a.session, *_flag_text(text)],
                      "cwd": cwd, "detach": str(asks.state.home() / "answer.log")})
        steps.append({"via": "codex-queue", "cmd": ["codex", "queue", "--thread", a.session, "--message", text],
                      "cwd": None, "detail": QUEUE_DETAIL})
    elif a.harness in ("claude-desktop", "claude-code") and a.session:
        meta = claude_meta(a.session)
        cwd = claude_cwd(a.session, meta)
        if cwd:
            mode = meta.get("permissionMode")
            cmd = ["claude", "--bg", "--resume", a.session]
            if mode in PERMISSION_MODES:
                cmd += ["--permission-mode", mode]
            steps.append({"via": "claude-bg", "cmd": cmd + _flag_text(text), "cwd": cwd})
    target = open_target(a)
    if target:
        steps.append({"via": "opened", "cmd": ["open", target], "cwd": None, "copy": True})
    return steps


def describe(step: dict) -> str:
    c = " ".join(shlex.quote(x) for x in step["cmd"])
    if step.get("copy"):
        c = "pbcopy < <answer>; " + c
    return (f"(cd {shlex.quote(step['cwd'])} && {c})" if step.get("cwd") else c)


def execute(step: dict, text: str) -> tuple[bool, str]:
    if step.get("copy"):
        code, out = run(["pbcopy"], input_text=text)
        if code != 0:
            return False, f"could not copy the answer: {out}"
        code, out = run(step["cmd"])
        return code == 0, ("answer copied; paste it into the session" if code == 0 else out)
    code, out = run(step["cmd"], cwd=step.get("cwd"), detach=step.get("detach"))
    return code == 0, (step.get("detail") or out) if code == 0 else (out or f"exit {code}")


def answer(a: asks.Ask, text: str, dry: bool = False, now: float | None = None) -> dict:
    steps = plan(a, text)
    base = {"ok": False, "via": "", "detail": "", "id": a.id}
    if not steps:
        base["detail"] = f"nothing to deliver to: {a.harness} items have no session (see: {a.link})"
        return base
    if dry:
        return {"ok": True, "via": steps[0]["via"], "detail": "would run: " + "  ||  ".join(describe(s) for s in steps),
                "id": a.id, "dry": True}
    failures = []
    for s in steps:
        ok, detail = execute(s, text)
        if ok:
            _mark_done(a.id, s["via"], now)
            return {"ok": True, "via": s["via"], "detail": detail, "id": a.id}
        failures.append(f"{s['via']}: {detail}")
    base["detail"] = "; ".join(failures)
    return base


def _mark_done(ask_id: str, via: str, now: float | None) -> None:
    now = asks._now() if now is None else now
    st = asks.load_state()
    st["done"][ask_id] = {"ts": asks._iso(now), "note": f"answered in Teyla via {via}"}
    st["snoozed"].pop(ask_id, None)
    asks.save_state(st, now=now)


# --- CLI --------------------------------------------------------------------------------------

def cmd_answer(args) -> int:
    words = list(args.words or [])
    if len(words) < 2 or not " ".join(words[1:]).strip():
        print("usage: teyla answer <id-prefix> <text...> [--json] [--dry]", file=sys.stderr)
        return 64
    a, err = asks.resolve(words[0], asks.collect(max(asks.DEFAULT_DAYS, 365)))
    if a is None:
        res = {"ok": False, "via": "", "detail": err, "id": ""}
    else:
        res = answer(a, " ".join(words[1:]).strip(), dry=args.dry)
    if args.json:
        print(json.dumps(res))
    else:
        print(res["detail"] if args.dry or not res["ok"] else f"answered {res['id']} via {res['via']}: {res['detail']}",
              file=sys.stdout if res["ok"] else sys.stderr)
    return 0 if res["ok"] else 1


def register(sp):
    q = sp.add_parser("answer", help="answer a question from `teyla asks` inside the session that asked it")
    q.set_defaults(fn=cmd_answer)
    q.add_argument("words", nargs="*", help="<id-prefix> <text...>")
    q.add_argument("--json", action="store_true")
    q.add_argument("--dry", action="store_true", help="print the commands it would run, run nothing")
    return q

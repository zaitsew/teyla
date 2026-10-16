"""Raw events from a Claude Code transcript or a Codex rollout: the asks, the sub-agent spawns,
the edits and the shell commands, each with the output that came back.

The adapters reduce a transcript to counts; Session Reel needs the records themselves, so this
module reads them again with `adapters.iter_jsonl`. Session metadata (id, cwd, span, title, cost)
still comes from the adapters, so the two never disagree about what a session is.

Nothing here is redacted: events are raw. `teyla.reel.story` is the only consumer, and every string
it takes from an event goes through `teyla.reel.redact` first.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
import re
from pathlib import Path

from ..adapters import claude_code, codex, human_text, iter_jsonl, strip_reminders, text_of

OUTPUT_KEEP = 20_000  # characters of a command's output kept (the tail: results come last)


@dataclasses.dataclass
class Event:
    kind: str                  # ask | agent | edit | command
    at: _dt.datetime | None = None
    t: float = 0.0             # seconds since the session started (set by `finish`)
    text: str = ""             # ask: the message; agent: its description; command: the command line
    tool: str = ""             # tool name; for an agent, its type
    model: str = ""            # agent: the model it was given
    path: str = ""             # edit: the file as the log wrote it
    hunks: list = dataclasses.field(default_factory=list)   # edit: [(old text, new text)]
    new_file: bool = False     # edit: a Write
    output: str = ""           # command: its output (tail)
    exit_code: int | None = None
    failed: bool = False       # the tool reported an error


@dataclasses.dataclass
class SessionInfo:
    sid: str
    harness: str               # "claude" | "codex"
    path: str
    cwd: str | None
    started: str
    ended: str
    title: str | None = None
    cost_usd: float | None = None
    batch: bool = False
    sidechain: bool = False


def parse_ts(ts) -> _dt.datetime | None:
    try:
        d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def finish(events: list[Event], started: str | None) -> list[Event]:
    """Order by time and set `t` (seconds since `started`, or the first event)."""
    t0 = parse_ts(started) or next((e.at for e in events if e.at), None)
    events.sort(key=lambda e: e.at or t0 or _dt.datetime.min.replace(tzinfo=_dt.timezone.utc))
    for e in events:
        e.t = max(0.0, (e.at - t0).total_seconds()) if e.at and t0 else 0.0
    return events


def _tail(text: str) -> str:
    return text[-OUTPUT_KEEP:] if len(text) > OUTPUT_KEEP else text


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict):
            if isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif isinstance(b.get("output"), str):
                parts.append(b["output"])
    return "\n".join(parts)


# --- Claude Code --------------------------------------------------------------------------

def read_claude(path: str) -> list[Event]:
    events: list[Event] = []
    pending: dict[str, Event] = {}  # tool_use id -> the event its result completes
    asked = False
    for o in iter_jsonl(path):
        if o.get("isSidechain"):
            continue
        at = parse_ts(o.get("timestamp"))
        t = o.get("type")
        msg = o.get("message") if isinstance(o.get("message"), dict) else {}
        content = msg.get("content")
        if t == "assistant":
            for b in content if isinstance(content, list) else []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                ev = _claude_tool(b, at)
                if ev:
                    events.append(ev)
                    if b.get("id"):
                        pending[b["id"]] = ev
        elif t == "user":
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        ev = pending.pop(b.get("tool_use_id"), None)
                        if ev is not None:
                            _claude_result(ev, b)
                continue
            if asked or o.get("isMeta"):
                continue
            txt = text_of(content).strip()
            h = human_text(txt) if txt else None
            if h:
                asked = True
                events.append(Event("ask", at, text=h))
    return events


def _claude_tool(b: dict, at) -> Event | None:
    name = b.get("name") or ""
    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
    if name == "Bash":
        return Event("command", at, text=str(inp.get("command") or ""), tool="Bash")
    if name in ("Agent", "Task"):
        return Event("agent", at, text=str(inp.get("description") or ""), tool=str(inp.get("subagent_type") or ""),
                     model=str(inp.get("model") or ""))
    if name == "Edit":
        return Event("edit", at, tool=name, path=str(inp.get("file_path") or ""),
                     hunks=[(str(inp.get("old_string") or ""), str(inp.get("new_string") or ""))])
    if name == "MultiEdit":
        hunks = [(str(e.get("old_string") or ""), str(e.get("new_string") or ""))
                 for e in inp.get("edits") or [] if isinstance(e, dict)]
        return Event("edit", at, tool=name, path=str(inp.get("file_path") or ""), hunks=hunks)
    if name == "Write":
        return Event("edit", at, tool=name, path=str(inp.get("file_path") or ""),
                     hunks=[("", str(inp.get("content") or ""))], new_file=True)
    return None


def _claude_result(ev: Event, block: dict) -> None:
    text = _result_text(block.get("content"))
    err = bool(block.get("is_error"))
    ev.failed = err
    if ev.kind == "command":
        ev.output = _tail(text)
        m = re.match(r"Exit code (\d+)", text)
        ev.exit_code = int(m.group(1)) if m else (1 if err else 0)


# --- Codex --------------------------------------------------------------------------------

_SHELLS = {"shell", "shell_command", "exec_command", "local_shell", "exec"}
_JS_STR = r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`'
_JS_EXEC = re.compile(r"tools\.exec_command\(\s*\{\s*cmd\s*:\s*(" + _JS_STR + ")")
_JS_PATCH = re.compile(r"tools\.apply_patch\(\s*(" + _JS_STR + ")")
_JSON_START = re.compile(r'\[?\{"(?:chunk_id|i|exit_code|output|wall_time_seconds)"')
_ESC = {"n": "\n", "t": "\t", "r": "\r", "b": "", "f": "", "0": ""}


def _js_string(lit: str) -> str | None:
    if lit[0] == '"':
        try:
            return json.loads(lit)
        except ValueError:
            pass
    body = lit[1:-1]
    return re.sub(r"\\(u[0-9a-fA-F]{4}|.)", lambda m: chr(int(m.group(1)[1:], 16)) if len(m.group(1)) == 5
                  else _ESC.get(m.group(1), m.group(1)), body)


def _argv_command(cmd) -> str:
    """`["bash", "-lc", "pytest -q"]` -> `pytest -q`; a plain list is joined."""
    if isinstance(cmd, list):
        parts = [str(x) for x in cmd]
        if len(parts) >= 3 and os.path.basename(parts[0]) in ("bash", "sh", "zsh") and parts[1] in ("-c", "-lc", "-ic", "-l"):
            return parts[2]
        return " ".join(parts)
    return str(cmd or "")


def parse_patch(patch: str, at) -> list[Event]:
    """Codex `apply_patch` text (`*** Update File: …`) as one edit event per file."""
    events: list[Event] = []
    cur = None
    old: list[str] = []
    new: list[str] = []

    def flush():
        if cur is not None:
            cur.hunks = [("\n".join(old), "\n".join(new))] if (old or new) else []
            events.append(cur)

    for line in patch.splitlines():
        m = re.match(r"\*\*\* (Update|Add|Delete) File: (.+)$", line)
        if m:
            flush()
            old, new = [], []
            cur = Event("edit", at, tool="apply_patch", path=m.group(2).strip(), new_file=(m.group(1) == "Add"))
            continue
        if cur is None or line.startswith(("*** Begin", "*** End", "*** Move to")):
            continue
        if line.startswith("@@"):
            continue
        if line.startswith("+"):
            new.append(line[1:])
        elif line.startswith("-"):
            old.append(line[1:])
        elif line.startswith(" "):
            old.append(line[1:])
            new.append(line[1:])
    flush()
    return events


def _codex_output(ev_list: list[Event], raw) -> None:
    """Attach a tool output to the command events of one call."""
    text = raw if isinstance(raw, str) else _result_text(raw)
    commands = [e for e in ev_list if e.kind == "command"]
    if not commands:
        return
    per_index: dict[int, dict] = {}
    exit_code, out = None, text
    parsed = None
    try:
        parsed = json.loads(text)
    except ValueError:
        pass
    if isinstance(parsed, dict) and isinstance(parsed.get("metadata"), dict):   # older `shell` tool
        exit_code = parsed["metadata"].get("exit_code")
        out = str(parsed.get("output") or "")
        if len(commands) == 1:
            commands[0].output = _tail(out)
            commands[0].exit_code = exit_code if isinstance(exit_code, int) else None
            commands[0].failed = bool(exit_code)
        return
    else:
        m = re.search(r"Exit code:\s*(-?\d+)", text)
        if m:
            exit_code = int(m.group(1))
    # The exec wrapper prints one JSON blob per call (or an array of {"i", "value"} for several).
    dec = json.JSONDecoder()
    for m in _JSON_START.finditer(text):
        try:
            data, _end = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            val = item.get("value") if isinstance(item.get("value"), dict) else item
            if isinstance(item.get("i"), int):
                per_index[item["i"]] = val
            elif "exit_code" in val and len(commands) == 1:
                per_index[0] = val
    if per_index:
        for i, ev in enumerate(commands):
            val = per_index.get(i)
            if val:
                ev.exit_code = val.get("exit_code") if isinstance(val.get("exit_code"), int) else None
                ev.output = _tail(str(val.get("output") or ""))
                ev.failed = bool(ev.exit_code)
        return
    if len(commands) == 1:
        e = commands[0]
        e.output = _tail(out)
        e.exit_code = exit_code if isinstance(exit_code, int) else None
        e.failed = bool(e.exit_code)


def read_codex(path: str) -> list[Event]:
    events: list[Event] = []
    calls: dict[str, list[Event]] = {}
    asked = False
    for o in iter_jsonl(path):
        if o.get("type") != "response_item" or not isinstance(o.get("payload"), dict):
            continue
        p = o["payload"]
        at = parse_ts(o.get("timestamp"))
        pt = p.get("type")
        if pt == "message" and p.get("role") == "user":
            if asked:
                continue
            txt = codex._text_of(p.get("content")).strip()
            clean = strip_reminders(codex.strip_injected(txt)) if txt else ""
            if clean.startswith("# AGENTS.md instructions") or "<INSTRUCTIONS>" in clean[:300]:
                continue   # the repo's instructions, handed to the model as a user message
            h = human_text(clean) if clean else None
            if h:
                asked = True
                events.append(Event("ask", at, text=h))
        elif pt in ("function_call", "local_shell_call", "custom_tool_call"):
            made = _codex_call(p, at)
            if made:
                events.extend(made)
                if p.get("call_id"):
                    calls[p["call_id"]] = made
        elif pt in ("function_call_output", "custom_tool_call_output"):
            made = calls.pop(p.get("call_id"), None)
            if made:
                _codex_output(made, p.get("output"))
    return events


def _codex_call(p: dict, at) -> list[Event]:
    name = (p.get("name") or "").rsplit(".", 1)[-1]
    pt = p.get("type")
    if pt == "local_shell_call":
        act = p.get("action") if isinstance(p.get("action"), dict) else {}
        return [Event("command", at, text=_argv_command(act.get("command")), tool="shell")]
    if pt == "custom_tool_call":
        raw = p.get("input")
        raw = raw if isinstance(raw, str) else ""
        if name == "apply_patch":
            return parse_patch(raw, at)
        if name == "exec":   # the desktop app's JavaScript wrapper around its tools
            found = [(m.start(), "command", m.group(1)) for m in _JS_EXEC.finditer(raw)]
            found += [(m.start(), "patch", m.group(1)) for m in _JS_PATCH.finditer(raw)]
            out: list[Event] = []
            for _pos, kind, lit in sorted(found):
                s = _js_string(lit)
                if s is None:
                    continue
                out.extend([Event("command", at, text=s, tool="exec_command")] if kind == "command" else parse_patch(s, at))
            return out
        return []
    try:
        args = json.loads(p.get("arguments") or "{}")
    except ValueError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    if name in _SHELLS:
        cmd = args.get("command", args.get("cmd"))
        return [Event("command", at, text=_argv_command(cmd), tool=name)] if cmd else []
    if name == "apply_patch":
        patch = args.get("input") or args.get("patch") or ""
        return parse_patch(str(patch), at)
    if name == "spawn_agent":
        desc = str(args.get("task_name") or "").replace("_", " ").strip()
        return [Event("agent", at, text=desc, tool=str(args.get("agent_type") or ""), model=str(args.get("model") or ""))]
    return []


# --- sessions -----------------------------------------------------------------------------

def info_of(s, harness: str) -> SessionInfo:
    """A SessionInfo from an adapter Session."""
    from ..pricing import cost_usd
    cost = 0.0
    priced = False
    for model, row in s.usage.items():
        c = cost_usd(model, dict(row))
        if c is not None:
            cost += c
            priced = True
    return SessionInfo(sid=s.sid, harness=harness, path=s.path, cwd=s.cwd, started=s.first or "", ended=s.last or s.first or "",
                       title=s.title, cost_usd=round(cost, 2) if priced else None, batch=bool(s.batch), sidechain=bool(s.sidechain))


def events_of(info: SessionInfo) -> list[Event]:
    raw = read_claude(info.path) if info.harness == "claude" else read_codex(info.path)
    return finish(raw, info.started)


def resolve(prefix: str) -> SessionInfo:
    """The one session whose id starts with `prefix`, Claude Code or Codex. Raises LookupError."""
    prefix = prefix.strip()
    found = [(claude_code, "claude", f) for f in claude_code.locate(prefix)]
    found += [(codex, "codex", f) for f in codex.locate(prefix)]
    if not found:
        raise LookupError(f"no session starts with {prefix!r}")
    if len(found) > 1:
        ids = ", ".join(sorted(Path(f).stem.split("-", 6)[-1][:12] if h == "codex" else Path(f).stem[:12] for _m, h, f in found))
        raise LookupError(f"{prefix!r} matches {len(found)} sessions ({ids}); give more of the id")
    mod, harness, f = found[0]
    s = claude_code.parse(f) if harness == "claude" else codex.parse(f, codex._load_titles(codex.DEFAULT_INDEX))
    if s is None:
        raise LookupError(f"{f} holds no session")
    return info_of(s, harness)


def discover(since_s: float | None) -> list[SessionInfo]:
    """Sessions of both harnesses with activity since `since_s` seconds ago (None: all), newest last."""
    import time
    from ..adapters import since_epoch
    out: list[SessionInfo] = []
    cutoff = (time.time() - since_s) if since_s else None
    days = None if since_s is None else max(1, int(since_s // 86400) + 1)
    for mod, harness in ((claude_code, "claude"), (codex, "codex")):
        try:
            sessions = mod.load(since=since_epoch(days))
        except FileNotFoundError:
            continue
        for s in sessions:
            info = info_of(s, harness)
            last = parse_ts(info.ended)
            if cutoff is not None and (last is None or last.timestamp() < cutoff):
                continue
            out.append(info)
    out.sort(key=lambda i: i.started)
    return out

"""Codex CLI adapter: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl (+ archived_sessions).

Each rollout file is a flat JSONL log of typed records (`session_meta`, `turn_context`,
`event_msg`, `response_item`, ...). There is no separate "session" object — the session_meta
record at the top carries the id and cwd, turn_context records carry the active model for each
turn, and event_msg/token_count records carry a *cumulative* token-usage snapshot for the whole
session so far (not a per-turn delta). We keep the last such snapshot and attribute it to the
last model seen — if a session switches models mid-way the split is approximate, but this is a
personal usage monitor, not a billing system.

User turns are `response_item` records with `type: message, role: user`; injected turns that are
one whole `<tag>...</tag>` block (`<environment_context>`, `<recommended_plugins>`,
`<user_action>`, ...) are filtered out — Codex writes those, the human did not type them.

`session_meta` carries `source` / `originator`: `exec` / `codex_exec` is `codex exec` (and
`codex review`), a non-interactive run whose prompt a script or another agent wrote. Those
sessions are `batch`: counted, but their prompts are not human turns.

Subagents show up only when the model calls the `spawn_agent` tool (name may be namespaced,
e.g. `collaboration.spawn_agent`) — its `task_name` argument becomes the AgentCall description.
Most sessions have none of these; that is expected, Codex only recently grew this.

`~/.codex/session_index.jsonl` holds `{id, thread_name, updated_at}` records used only to backfill
a human-readable title when a session doesn't already have one.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re

from . import AgentCall, Session, Turn, human_text, is_correction, is_retry, stale, turn_end_candidate
from ..connectors import classify_result, parse_mcp_tool

NAME = "codex"
DEFAULT_ROOT = os.path.expanduser("~/.codex/sessions")
DEFAULT_ARCHIVE_ROOT = os.path.expanduser("~/.codex/archived_sessions")
DEFAULT_INDEX = os.path.expanduser("~/.codex/session_index.jsonl")


BATCH_SOURCES = ("exec",)
BATCH_ORIGINATORS = ("codex_exec",)
KNOWN_BLOCKS = {"environment_context", "recommended_plugins", "in-app-browser-context", "user_instructions",
                "user_action", "turn_aborted", "user_shell_command"}
_BLOCK_RE = re.compile(r"\s*<([a-z][a-z0-9_-]*)(?:\s[^>]*)?>.*?</\1>\s*", re.S)


def strip_injected(txt: str) -> str:
    """The message minus the harness-written `<tag>...</tag>` blocks it opens with. Codex's
    desktop app sends `<recommended_plugins>…</recommended_plugins>` and
    `<environment_context>…</environment_context>` as one user message with two parts; the
    0.11 test wanted a single block and let all 11 of them through as human turns in 2026-09.
    `<in-app-browser-context>` (a hyphen) precedes a real question and is cut off it.

    A message made only of blocks is injected whatever the tags (0.11's rule, for any
    number of blocks). Blocks in front of real text are cut only when Codex is known to
    write them: a person who pastes `<config>…</config>` before a question keeps it."""
    pos, blocks = 0, []
    while True:
        m = _BLOCK_RE.match(txt, pos)
        if not m:
            break
        blocks.append((m.group(1), pos, m.end()))
        pos = m.end()
    if not txt[pos:].strip():
        return ""
    cut = 0
    for tag, start, end in blocks:
        if tag not in KNOWN_BLOCKS:
            break
        cut = end
    return txt[cut:].strip()


def is_injected(txt: str) -> bool:
    """A user-role message made only of harness-written `<tag>...</tag>` blocks."""
    return txt.startswith("<environment_context>") or not strip_injected(txt)


def _load_titles(index_path: str) -> dict:
    titles = {}
    if not os.path.isfile(index_path):
        return titles
    with open(index_path, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            sid = o.get("id")
            name = o.get("thread_name")
            if sid and name:
                titles[sid] = name
    return titles


def _text_of(content) -> str:
    parts = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") in ("input_text", "output_text", "text"):
            parts.append(b.get("text", ""))
    return "\n".join(parts)


def load(root: str | None = None, archive_root: str | None = None,
         index_path: str = DEFAULT_INDEX, since: float | None = None, **kw) -> list[Session]:
    root = root or DEFAULT_ROOT  # at call time, so tests and callers that move DEFAULT_ROOT are obeyed
    archive_root = archive_root or DEFAULT_ARCHIVE_ROOT
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    titles = _load_titles(index_path)
    files = _rollouts(root, since)
    if os.path.isdir(archive_root):
        files += _rollouts(archive_root, since)
    sessions = []
    for f in files:
        s = parse(f, titles)
        if s is not None:
            sessions.append(s)
    return sessions


def _bucket_end(parts: list[str]) -> float | None:
    """Latest POSIX time a YYYY[/MM[/DD]] bucket can cover, with a day of slack for the local
    date in the path; None when the path is not a date bucket."""
    try:
        nums = [int(x) for x in parts]
        if len(nums) == 1:
            end = _dt.datetime(nums[0] + 1, 1, 1)
        elif len(nums) == 2:
            end = _dt.datetime(nums[0] + (nums[1] == 12), nums[1] % 12 + 1, 1)
        elif len(nums) == 3:
            end = _dt.datetime(*nums) + _dt.timedelta(days=1)
        else:
            return None
    except ValueError:
        return None
    return (end + _dt.timedelta(days=1)).replace(tzinfo=_dt.timezone.utc).timestamp()


def _rollouts(root: str, since: float | None) -> list[str]:
    """rollout-*.jsonl under root, sorted. With a window, whole YYYY/MM/DD directories that end
    before it are never walked, and a rollout last written before it is never opened."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        prefix = [] if rel == "." else rel.split(os.sep)
        if since is not None:
            dirnames[:] = [d for d in dirnames
                           if (end := _bucket_end(prefix + [d])) is None or not stale(end, since)]
        for name in filenames:
            if not (name.startswith("rollout-") and name.endswith(".jsonl")):
                continue
            f = os.path.join(dirpath, name)
            try:
                if stale(os.stat(f).st_mtime, since):
                    continue
            except OSError:
                continue
            out.append(f)
    return sorted(out)


def parse(f: str, titles: dict | None = None) -> Session | None:
    titles = titles or {}
    fallback_sid = os.path.basename(f)[:-6]
    s = Session(harness=NAME, project="?", sid=fallback_sid, path=f, size=os.path.getsize(f))
    current_model = None
    last_total_usage = None  # cumulative snapshot, keyed to current_model at the time it arrived
    last_usage_model = None
    pending_calls: dict = {}  # call_id -> {server, tool, turn_index}, until its function_call_output arrives
    last_text = None  # (ts, text) of the latest assistant message, until a tool call or a human turn follows
    with open(f, errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            ts = o.get("timestamp")
            if ts:
                s.first = s.first or ts
                s.last = ts
            payload = o.get("payload")
            if not isinstance(payload, dict):
                continue

            if t == "session_meta":
                sid = payload.get("session_id") or payload.get("id")
                if sid:
                    s.sid = sid
                cwd = payload.get("cwd")
                if cwd:
                    s.cwd = cwd
                    s.project = cwd
                src = payload.get("source")
                # `source` is a dict for a spawned agent — {"subagent": "review"} for `codex
                # review`, {"subagent": {"thread_spawn": …}} for spawn_agent — and its prompt
                # was written by the parent agent even when the parent was a person's session.
                if (src in BATCH_SOURCES or payload.get("originator") in BATCH_ORIGINATORS
                        or (isinstance(src, dict) and "subagent" in src)):
                    s.batch = True

            elif t == "turn_context":
                model = payload.get("model")
                if model:
                    current_model = model
                    s.models[model] += 1

            elif t == "event_msg":
                etype = payload.get("type")
                if etype == "token_count":
                    info = payload.get("info")
                    total = (info or {}).get("total_token_usage")
                    if total:
                        last_total_usage = total
                        last_usage_model = current_model

            elif t == "response_item":
                ptype = payload.get("type")
                if ptype == "message":
                    role = payload.get("role")
                    txt = _text_of(payload.get("content")).strip()
                    if role == "assistant":
                        s.assistant_turns += 1
                        if txt:
                            last_text = (ts, txt)
                    elif role == "user":
                        clean = strip_injected(txt).strip() if txt else ""
                        h = human_text(clean) if clean else None
                        # A bare "continue" is a retry to the turn counts but an approval to
                        # A15 (review of the #60 merge).
                        reply = h or (clean if clean and is_retry(clean) else None)
                        if reply:
                            ending = turn_end_candidate(last_text[1]) if last_text else None
                            if ending:
                                s.turn_ends.append((last_text[0], ending, reply[:200]))
                            last_text = None
                        if h:
                            s.user_turns.append(Turn(ts, h[:1500], is_correction(h)))
                    # role == "developer": injected instructions/skill text, not a human turn.
                elif ptype == "function_call":
                    last_text = None  # the turn went on after the message: it did not end there
                    name = (payload.get("name") or "").rsplit(".", 1)[-1]
                    if name:
                        s.tools[name] += 1
                        if name == "spawn_agent":
                            args = {}
                            try:
                                args = json.loads(payload.get("arguments") or "{}")
                            except Exception:
                                pass
                            s.agents.append(AgentCall(args.get("model"), "spawn_agent", args.get("task_name")))
                        parsed = parse_mcp_tool(name)
                        call_id = payload.get("call_id")
                        if parsed and call_id:
                            server, tool = parsed
                            pending_calls[call_id] = dict(server=server, tool=tool, turn_index=len(s.user_turns))
                elif ptype == "function_call_output":
                    call = pending_calls.pop(payload.get("call_id"), None)
                    if call is not None:
                        # Codex's function_call_output carries no is_error flag; classify on the
                        # output text alone (a plain string here, unlike Claude Code's content blocks).
                        result = classify_result(False, payload.get("output"))
                        s.connector_calls.append(dict(server=call["server"], tool=call["tool"],
                                                       turn_index=call["turn_index"], result=result))

    if last_total_usage:
        model_key = last_usage_model or current_model or "?"
        u = s.usage[model_key]
        u["input_tokens"] += last_total_usage.get("input_tokens", 0) or 0
        u["cache_read_input_tokens"] += last_total_usage.get("cached_input_tokens", 0) or 0
        u["cache_creation_input_tokens"] += last_total_usage.get("cache_write_input_tokens", 0) or 0
        # reasoning_output_tokens is a detail/breakdown of output_tokens (OpenAI reports it as a
        # sub-count of the completion), not an addition to it -- adding it here double-counts.
        u["output_tokens"] += last_total_usage.get("output_tokens", 0) or 0

    if not s.title:
        s.title = titles.get(s.sid)

    if not s.first:
        return None
    return s

"""Codex CLI adapter: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl (+ archived_sessions).

Each rollout file is a flat JSONL log of typed records (`session_meta`, `turn_context`,
`event_msg`, `response_item`, ...). There is no separate "session" object — the session_meta
record at the top carries the id and cwd, turn_context records carry the active model for each
turn, and event_msg/token_count records carry a *cumulative* token-usage snapshot for the whole
session so far (not a per-turn delta). We keep the last such snapshot and attribute it to the
last model seen — if a session switches models mid-way the split is approximate, but this is a
personal usage monitor, not a billing system.

User turns are `response_item` records with `type: message, role: user`; injected
`<environment_context>...</environment_context>` turns are filtered out (that is Codex's
environment-context re-injection, not something the human typed).

Subagents show up only when the model calls the `spawn_agent` tool (name may be namespaced,
e.g. `collaboration.spawn_agent`) — its `task_name` argument becomes the AgentCall description.
Most sessions have none of these; that is expected, Codex only recently grew this.

`~/.codex/session_index.jsonl` holds `{id, thread_name, updated_at}` records used only to backfill
a human-readable title when a session doesn't already have one.
"""
from __future__ import annotations

import glob
import json
import os

from . import CORRECTION_RE, AgentCall, Session, Turn
from ..connectors import classify_result, parse_mcp_tool

NAME = "codex"
DEFAULT_ROOT = os.path.expanduser("~/.codex/sessions")
DEFAULT_ARCHIVE_ROOT = os.path.expanduser("~/.codex/archived_sessions")
DEFAULT_INDEX = os.path.expanduser("~/.codex/session_index.jsonl")


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


def load(root: str = DEFAULT_ROOT, archive_root: str = DEFAULT_ARCHIVE_ROOT,
         index_path: str = DEFAULT_INDEX, **kw) -> list[Session]:
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    titles = _load_titles(index_path)
    files = sorted(glob.glob(os.path.join(root, "**", "rollout-*.jsonl"), recursive=True))
    if os.path.isdir(archive_root):
        files += sorted(glob.glob(os.path.join(archive_root, "**", "rollout-*.jsonl"), recursive=True))
    sessions = []
    for f in files:
        s = parse(f, titles)
        if s is not None:
            sessions.append(s)
    return sessions


def parse(f: str, titles: dict | None = None) -> Session | None:
    titles = titles or {}
    fallback_sid = os.path.basename(f)[:-6]
    s = Session(harness=NAME, project="?", sid=fallback_sid, path=f, size=os.path.getsize(f))
    current_model = None
    last_total_usage = None  # cumulative snapshot, keyed to current_model at the time it arrived
    last_usage_model = None
    pending_calls: dict = {}  # call_id -> {server, tool, turn_index}, until its function_call_output arrives
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
                    elif role == "user":
                        if txt and not txt.startswith("<environment_context>"):
                            s.user_turns.append(
                                Turn(ts, txt[:1500], bool(CORRECTION_RE.search(txt[:600])))
                            )
                    # role == "developer": injected instructions/skill text, not a human turn.
                elif ptype == "function_call":
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

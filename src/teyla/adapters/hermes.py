"""Hermes agent (Nous Research) adapter: ~/.hermes/state.db, table `sessions` (+ `messages`,
`session_model_usage`, `async_delegations`).

Unlike Codex/Grok, Hermes keeps one SQLite database for everything (`hermes sessions ...`
manages it directly — see `hermes sessions --help`) rather than a per-session file, so
`DEFAULT_ROOT` here is the database file itself and `os.path.isfile` is the existence check.
`~/.hermes/sessions/` (a directory) and `~/.hermes/logs/` exist but are empty / free-form process
logs, not a session store — `hermes dump`/`hermes sessions stats` both point at state.db.

Never touches `~/.hermes/auth.json`, `.env`, or any secret store — only state.db, opened
read-only.

Table shapes actually observed on this machine (`pragma table_info`):
  sessions              -- one row per session: id, source, model, started_at/ended_at (epoch
                           seconds), token/tool-call counters, cwd, title.
  messages              -- one row per message: session_id, role, content (plain text), tool_name,
                           timestamp, token_count.
  session_model_usage   -- one row per (session_id, model, task): lets a session's tokens split
                           across models/tasks (e.g. a `title_generation` call on a different
                           model than the chat itself) more accurately than the sessions table's
                           single `model` column.
  async_delegations     -- background/subagent dispatch records (origin_session, parent_session_id,
                           task_json). None exist on this machine yet, so this path is exercised
                           only defensively; `task_json` is parsed best-effort for a `model` field.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3

from . import CORRECTION_RE, AgentCall, Session, Turn

NAME = "hermes"
DEFAULT_ROOT = os.path.expanduser("~/.hermes/state.db")


def _iso(epoch) -> str | None:
    if not epoch:
        return None
    try:
        return _dt.datetime.fromtimestamp(float(epoch), tz=_dt.timezone.utc).isoformat()
    except Exception:
        return None


def load(root: str = DEFAULT_ROOT, **kw) -> list[Session]:
    if not os.path.isfile(root):
        raise FileNotFoundError(root)
    con = sqlite3.connect(f"file:{root}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        sessions = []
        for row in con.execute("SELECT * FROM sessions"):
            s = _session_from_row(con, row)
            if s is not None:
                sessions.append(s)
        return sessions
    finally:
        con.close()


def _session_from_row(con: sqlite3.Connection, row: sqlite3.Row) -> Session | None:
    sid = row["id"]
    cwd = row["cwd"] or row["git_repo_root"]
    s = Session(harness=NAME, project=cwd or row["session_key"] or "?", sid=sid,
                path=DEFAULT_ROOT, size=0)
    s.cwd = cwd
    s.title = row["title"]
    s.first = _iso(row["started_at"])
    s.last = _iso(row["ended_at"]) or _iso(row["last_activity_at"]) or s.first
    if not s.first:
        return None

    try:
        for u in con.execute(
            "SELECT model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens "
            "FROM session_model_usage WHERE session_id = ?", (sid,),
        ):
            model = u["model"] or row["model"] or "?"
            s.models[model] += 1
            c = s.usage[model]
            c["input_tokens"] += u["input_tokens"] or 0
            c["output_tokens"] += u["output_tokens"] or 0
            c["cache_read_input_tokens"] += u["cache_read_tokens"] or 0
            c["cache_creation_input_tokens"] += u["cache_write_tokens"] or 0
    except sqlite3.OperationalError:
        pass
    if not s.usage and row["model"]:
        s.models[row["model"]] += 1
        c = s.usage[row["model"]]
        c["input_tokens"] += row["input_tokens"] or 0
        c["output_tokens"] += row["output_tokens"] or 0
        c["cache_read_input_tokens"] += row["cache_read_tokens"] or 0
        c["cache_creation_input_tokens"] += row["cache_write_tokens"] or 0

    try:
        for m in con.execute(
            "SELECT role, content, tool_name, timestamp FROM messages "
            "WHERE session_id = ? ORDER BY timestamp", (sid,),
        ):
            role = m["role"]
            if role == "assistant":
                s.assistant_turns += 1
                if m["tool_name"]:
                    s.tools[m["tool_name"]] += 1
            elif role == "tool":
                if m["tool_name"]:
                    s.tools[m["tool_name"]] += 1
            elif role == "user":
                txt = (m["content"] or "").strip()
                if txt:
                    ts = _iso(m["timestamp"])
                    s.user_turns.append(Turn(ts, txt[:1500], bool(CORRECTION_RE.search(txt[:600]))))
            # role == "system": the injected system prompt, not a human turn.
    except sqlite3.OperationalError:
        pass

    try:
        for d in con.execute(
            "SELECT task_json FROM async_delegations WHERE origin_session = ? OR parent_session_id = ?",
            (sid, sid),
        ):
            task = {}
            try:
                task = json.loads(d["task_json"] or "{}")
            except Exception:
                pass
            s.agents.append(AgentCall(task.get("model"), "async_delegation", task.get("description")))
    except sqlite3.OperationalError:
        pass

    return s

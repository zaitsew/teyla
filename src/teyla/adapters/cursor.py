"""Cursor (the macOS app) adapter: one SQLite store for every agent/chat session.

    ~/Library/Application Support/Cursor/User/globalStorage/state.vscdb

Table `cursorDiskKV` (key, value) holds the sessions. Inspected on this machine, Cursor 3.19.7,
2026-09-14:

  composerData:<composerId>        one JSON per session ("composer"): name, createdAt and
                                   lastUpdatedAt (epoch ms), unifiedMode ("agent"/"ask"),
                                   modelConfig.modelName (e.g. "grok-4.6"),
                                   workspaceIdentifier.uri.fsPath (the cwd),
                                   contextTokensUsed / promptTokenBreakdown (a context-window
                                   snapshot, not cumulative spend — not read as usage),
                                   fullConversationHeadersOnly (one {bubbleId, type} per turn).
  bubbleId:<composerId>:<bubbleId> one JSON per turn: type 1 = user, 2 = assistant; createdAt
                                   (ISO string); text; toolFormerData.name on tool-call turns;
                                   tokenCount {inputTokens, outputTokens} — 0/0 on every turn
                                   inspected, so per-message usage is not available.
  composerHeaders                  a table indexing the same composers (composerId, workspaceId,
                                   createdAt, lastUpdatedAt, isArchived, isSubagent).

Per-workspace `workspaceStorage/*/state.vscdb` files carry editor state only (their
cursorDiskKV is empty). `~/.cursor/projects/<slug>/agent-transcripts/<id>/<id>.jsonl` exists
for some sessions but is pruned periodically (`.agent-data-cleanup-*` markers), so the store
is the source. Cursor exposes no per-message token counts anywhere in it, so `usage` is left
empty — like Grok — rather than guessed from a context-window snapshot.

Opened read-only (`mode=ro`) while the app may be running; a locked or absent store raises
FileNotFoundError / returns nothing rather than failing the report.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3

from . import CORRECTION_RE, Session, Turn

NAME = "cursor"
DEFAULT_ROOT = os.path.expanduser("~/Library/Application Support/Cursor/User/globalStorage/state.vscdb")


def _iso_ms(ms) -> str | None:
    try:
        return _dt.datetime.fromtimestamp(int(ms) / 1000, tz=_dt.timezone.utc).isoformat()
    except Exception:
        return None


def load(root: str = DEFAULT_ROOT, **kw) -> list[Session]:
    if not os.path.isfile(root):
        raise FileNotFoundError(root)
    con = sqlite3.connect(f"file:{root}?mode=ro", uri=True)
    try:
        con.execute("select 1 from cursorDiskKV limit 1")
    except sqlite3.OperationalError:
        con.close()
        return []
    try:
        out = []
        for key, value in con.execute("select key, value from cursorDiskKV where key like 'composerData:%'"):
            s = parse(key, value, con, root)
            if s is not None:
                out.append(s)
        return out
    finally:
        con.close()


def parse(key: str, value, con: sqlite3.Connection, root: str) -> Session | None:
    try:
        d = json.loads(value)
    except Exception:
        return None
    cid = d.get("composerId") or key.split(":", 1)[-1]
    cwd = ((d.get("workspaceIdentifier") or {}).get("uri") or {}).get("fsPath")
    s = Session(harness=NAME, project=cwd or "?", sid=cid, path=root, size=len(value) if isinstance(value, (str, bytes)) else 0)
    s.cwd = cwd
    s.title = d.get("name") or None
    s.first = _iso_ms(d.get("createdAt"))
    s.last = _iso_ms(d.get("lastUpdatedAt")) or s.first
    model = (d.get("modelConfig") or {}).get("modelName")
    if model:
        s.models[model] += 1
    bubbles = []
    for bkey, bval in con.execute("select key, value from cursorDiskKV where key like ?", (f"bubbleId:{cid}:%",)):
        try:
            b = json.loads(bval)
        except Exception:
            continue
        bubbles.append(b)
        s.size += len(bval) if isinstance(bval, (str, bytes)) else 0
    bubbles.sort(key=lambda b: str(b.get("createdAt") or ""))
    for b in bubbles:
        t = b.get("type")
        ts = b.get("createdAt") if isinstance(b.get("createdAt"), str) else None
        if t == 1:
            txt = (b.get("text") or "").strip()
            if txt:
                s.user_turns.append(Turn(ts, txt[:1500], len(txt) < 800 and bool(CORRECTION_RE.search(txt))))
        elif t == 2:
            s.assistant_turns += 1
            tool = (b.get("toolFormerData") or {}).get("name")
            if tool:
                s.tools[tool] += 1
            m = (b.get("modelInfo") or {}).get("modelName")
            if m and m not in s.models:
                s.models[m] += 1
    if not s.first:
        return None
    return s

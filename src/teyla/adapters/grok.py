"""Grok CLI adapter: $GROK_HOME/sessions/<urlencoded-cwd>/<session-uuid>/... (GROK_HOME defaults
to ~/.grok).

Layout, one directory per cwd the CLI was ever run from (its path is that cwd, percent-encoded),
containing:
  prompt_history.jsonl   -- flat, append-only log of every prompt typed in *any* session under
                             this cwd: {timestamp, session_id, prompt, is_bash}. This is the
                             cleanest source of "what did the human actually type" — no injected
                             system/environment turns to filter out.
  <session-uuid>/         -- one directory per session: summary.json (id, cwd, created_at,
                             updated_at, current_model_id, git info), signals.json (per-session
                             counters: modelsUsed, toolCallCount, compactionCount, ...), and
                             chat_history.jsonl (full transcript incl. tool_calls).
  session_search.sqlite   -- an FTS index over session content, no usage/token data. Not read here.

A newer layout also seen on disk drops the urlencoded-cwd container: a session directory sits
directly under the sessions root, named by a hash rather than an encoded path, and carries a
`.cwd` file instead of leaning on its parent directory's name for the cwd. Both layouts are
handled here; a `.cwd` file, when present, always wins over a name-derived guess.

Grok does not expose per-message input/output token counts anywhere in these files (checked
summary.json, signals.json and chat_history.jsonl — none of them carry a usage block), so
`usage` is left empty rather than guessing from `contextTokensUsed` (a context-window snapshot,
not cumulative spend). Tool-call names come from `chat_history.jsonl`'s assistant `tool_calls`,
which is the only place they're broken out by name.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse

from . import CORRECTION_RE, AgentCall, Session, Turn

NAME = "grok"
GROK_HOME = os.environ.get("GROK_HOME") or os.path.expanduser("~/.grok")
DEFAULT_ROOT = os.path.join(GROK_HOME, "sessions")

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def _load_json(path: str) -> dict:
    try:
        with open(path, errors="replace") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _prompts_by_session(prompt_history: str) -> dict:
    by_sid: dict = {}
    if not os.path.isfile(prompt_history):
        return by_sid
    with open(prompt_history, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            sid = o.get("session_id")
            if not sid:
                continue
            by_sid.setdefault(sid, []).append((o.get("timestamp"), o.get("prompt") or ""))
    return by_sid


def _dir_size(path: str) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for name in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total


def _is_session_dir(path: str) -> bool:
    return os.path.isfile(os.path.join(path, "summary.json")) or os.path.isfile(
        os.path.join(path, "chat_history.jsonl"))


def _cwd_from_dotfile(path: str) -> str | None:
    fp = os.path.join(path, ".cwd")
    if not os.path.isfile(fp):
        return None
    try:
        with open(fp, errors="replace") as fh:
            v = fh.read().strip()
        return v or None
    except OSError:
        return None


def load(root: str = DEFAULT_ROOT, **kw) -> list[Session]:
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    sessions = []
    for entry in sorted(os.listdir(root)):
        entry_path = os.path.join(root, entry)
        if not os.path.isdir(entry_path):
            continue  # session_search.sqlite and friends

        if _is_session_dir(entry_path):
            # Newer layout: a hash-named session dir lives directly under root, cwd comes from
            # its own .cwd file (the dir name itself isn't a decodable path).
            cwd_guess = _cwd_from_dotfile(entry_path) or urllib.parse.unquote(entry)
            s = parse(entry_path, entry, cwd_guess, [])
            if s is not None:
                sessions.append(s)
            continue

        cwd_guess = urllib.parse.unquote(entry)
        prompts_by_sid = _prompts_by_session(os.path.join(entry_path, "prompt_history.jsonl"))
        for sub in sorted(os.listdir(entry_path)):
            subpath = os.path.join(entry_path, sub)
            if not os.path.isdir(subpath):
                continue
            sub_cwd_guess = _cwd_from_dotfile(subpath) or cwd_guess
            s = parse(subpath, sub, sub_cwd_guess, prompts_by_sid.get(sub, []))
            if s is not None:
                sessions.append(s)
    return sessions


def parse(subpath: str, sid: str, cwd_guess: str, prompts: list) -> Session | None:
    summary = _load_json(os.path.join(subpath, "summary.json"))
    signals = _load_json(os.path.join(subpath, "signals.json"))
    info = summary.get("info") or {}
    cwd = info.get("cwd") or cwd_guess

    s = Session(harness=NAME, project=cwd, sid=sid, path=subpath, size=_dir_size(subpath))
    s.cwd = cwd
    s.compactions = signals.get("compactionCount") or 0

    model = signals.get("primaryModelId") or summary.get("current_model_id")
    for m in (signals.get("modelsUsed") or ([model] if model else [])):
        s.models[m] += 1

    # Timestamps come from three places that don't agree: summary.json's created_at/updated_at/
    # last_active_at, any timestamp fields signals.json carries, and the prompt log. Taking the
    # min/max across all of them (rather than letting the last prompt processed clobber s.last)
    # avoids a spurious zero-duration session when the human's last typed prompt lands well
    # before the assistant's final tool call.
    ts_candidates = [v for src in (summary, signals) for v in src.values()
                      if isinstance(v, str) and _TS_RE.match(v)]

    chat = os.path.join(subpath, "chat_history.jsonl")
    if os.path.isfile(chat):
        with open(chat, errors="replace") as fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") != "assistant":
                    continue
                s.assistant_turns += 1
                for tc in o.get("tool_calls") or []:
                    if not isinstance(tc, dict):
                        continue
                    name = tc.get("name")
                    if not name:
                        continue
                    s.tools[name] += 1
                    if name == "spawn_subagent":
                        try:
                            args = json.loads(tc.get("arguments") or "{}")
                        except Exception:
                            args = {}
                        s.agents.append(AgentCall(None, "grok-subagent", args.get("description")))

    for ts, prompt in sorted(prompts, key=lambda p: p[0] or ""):
        txt = (prompt or "").strip()
        if not txt:
            continue
        s.user_turns.append(Turn(ts, txt[:1500], bool(CORRECTION_RE.search(txt[:600]))))
        if ts:
            ts_candidates.append(ts)

    if ts_candidates:
        s.first = min(ts_candidates)
        s.last = max(ts_candidates)

    if not s.first:
        return None
    # One-prompt sessions launched from scratch/temp dirs or by another program are batch calls
    # (a Claude session consulting Grok, a pipeline using the CLI), not a human at the keyboard.
    # monitor.py counts them and their tools but excludes their turns from correction metrics.
    if len(s.user_turns) <= 1:
        s.batch = True
    return s

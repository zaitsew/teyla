"""Claude Code adapter: ~/.claude/projects/<slug>/<session>.jsonl"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re

from . import CORRECTION_RE, TOKEN_KEYS, AgentCall, Session, Turn, is_noise_turn, text_of
from ..connectors import classify_result, parse_mcp_tool

NAME = "claude-code"
DEFAULT_ROOT = os.path.expanduser("~/.claude/projects")
REPO_HINT = "repos/"

# Gaps between consecutive assistant/user records longer than this are treated as "away from the
# session", not active work (a lunch break, a context switch, a session resumed days later).
ACTIVE_GAP_CEILING_S = 30 * 60


def _parse_ts(ts: str):
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def load(root: str = DEFAULT_ROOT, repo_names: list[str] | None = None) -> list[Session]:
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    sessions = []
    for f in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
        s = parse(f, repo_names)
        if s is not None:
            sessions.append(s)
    return sessions


def parse(f: str, repo_names: list[str] | None = None) -> Session | None:
    slug = os.path.basename(os.path.dirname(f))
    s = Session(harness=NAME, project=slug, sid=os.path.basename(f)[:-6], path=f, size=os.path.getsize(f))
    pending_calls: dict = {}  # tool_use_id -> {server, tool, turn_index}, until its tool_result arrives
    active_prev = None  # last assistant/user timestamp seen, kept only to sum gaps — never a list
    with open(f, errors="replace") as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            ts = o.get("timestamp")
            if ts:
                s.first = s.first or ts
                s.last = ts
            if ts and t in ("assistant", "user"):
                cur = _parse_ts(ts)
                if cur is not None:
                    if active_prev is not None:
                        gap = (cur - active_prev).total_seconds()
                        if 0 <= gap <= ACTIVE_GAP_CEILING_S:
                            s.active_hours += gap / 3600.0
                    active_prev = cur
            if o.get("cwd") and not s.cwd:
                s.cwd = o["cwd"]
            if o.get("isSidechain"):
                s.sidechain = True
            if t == "custom-title":
                s.title = o.get("customTitle") or o.get("title")
            elif t == "pr-link":
                s.pr_links += 1
            elif t == "system" and o.get("subtype") == "compact_boundary":
                s.compactions += 1
            if repo_names:
                for r in repo_names:
                    if f"{REPO_HINT}{r}" in line:
                        s.repos[r] += 1
            if t == "assistant":
                m = o.get("message", {})
                s.assistant_turns += 1
                model = m.get("model", "?")
                s.models[model] += 1
                u = m.get("usage") or {}
                for k in TOKEN_KEYS:
                    s.usage[model][k] += u.get(k, 0) or 0
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        name = b.get("name")
                        s.tools[name] += 1
                        inp = b.get("input", {}) or {}
                        if _touches_governance(name, inp):
                            s.gov_edits += 1
                        if name in ("Agent", "Task"):
                            s.agents.append(AgentCall(inp.get("model"), inp.get("subagent_type"), inp.get("description")))
                        elif name == "Skill":
                            s.skills[inp.get("skill")] += 1
                        elif name == "Read":
                            fp = str(inp.get("file_path") or "")
                            if fp.endswith("SKILL.md"):
                                s.skills_read[os.path.basename(os.path.dirname(fp))] += 1
                        parsed = parse_mcp_tool(name or "")
                        if parsed and b.get("id"):
                            server, tool = parsed
                            pending_calls[b["id"]] = dict(server=server, tool=tool, turn_index=len(s.user_turns))
            elif t == "user":
                m = o.get("message", {})
                c = m.get("content")
                if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                    for b in c:
                        if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                            continue
                        call = pending_calls.pop(b.get("tool_use_id"), None)
                        if call is None:
                            continue
                        result = classify_result(bool(b.get("is_error")), b.get("content"))
                        s.connector_calls.append(dict(server=call["server"], tool=call["tool"],
                                                       turn_index=call["turn_index"], result=result))
                    continue
                txt = text_of(c).strip()
                if not txt or o.get("isMeta") or is_noise_turn(txt):
                    continue
                s.user_turns.append(Turn(ts, txt[:1500], len(txt) < 800 and bool(CORRECTION_RE.search(txt))))
    s.active_hours = round(s.active_hours, 2)
    if not s.first:
        return None
    return s


_WRITE_RE = re.compile(r"(>>?\s*[^|]*CLAUDE\.md|sed -i|write_text|tee |open\([^)]*['\"]w)")


def _touches_governance(name: str, inp: dict) -> bool:
    """True when a tool call writes the global instructions file. Reads (grep, cat) do not count."""
    target = os.path.expanduser("~/.claude/CLAUDE.md")
    if name in ("Edit", "Write", "MultiEdit"):
        fp = str(inp.get("file_path", ""))
        return fp.endswith(".claude/CLAUDE.md") or fp == target
    if name == "Bash":
        cmd = str(inp.get("command", ""))
        return ".claude/CLAUDE.md" in cmd and bool(_WRITE_RE.search(cmd))
    return False

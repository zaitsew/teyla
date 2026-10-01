"""Claude Code adapter: ~/.claude/projects/<slug>/<session>.jsonl"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import re

from . import CACHE_1H_KEY, ERROR_LOOP, HANDOFF_CONTEXT, LONG_CONTEXT, TOKEN_KEYS, AgentCall, Session, Turn, human_text, is_correction, is_retry, local_day, stale, strip_reminders, text_of, turn_end_candidate
from ..connectors import classify_result, parse_mcp_tool

NAME = "claude-code"
DEFAULT_ROOT = os.path.expanduser("~/.claude/projects")
REPO_HINT = "repos/"

# Gaps between consecutive assistant/user records longer than this are treated as "away from the
# session", not active work (a lunch break, a context switch, a session resumed days later).
ACTIVE_GAP_CEILING_S = 30 * 60

# `entrypoint` on each record says how the session was started. `sdk-cli` is `claude -p` /
# `--print`: a script or another agent handing Claude one prompt, never a human at the keyboard.
# (`cli` is the terminal, `claude-desktop` the app; both are interactive.) The Agent SDKs
# stamp their own `sdk-*` value; only `sdk-cli` and `claude-desktop` were seen on the machine
# this was written on (233 of 233 transcripts in 2026-09 were `claude-desktop`), so the
# prefix, not a list, decides — a new SDK must not make its prompts human turns.
BATCH_ENTRYPOINT_PREFIX = "sdk-"


def _parse_ts(ts: str):
    try:
        return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def load(root: str | None = None, repo_names: list[str] | None = None, since: float | None = None,
         **kw) -> list[Session]:
    root = DEFAULT_ROOT if root is None else root  # at call time, so tests and callers that move it are obeyed
    if not os.path.isdir(root):
        raise FileNotFoundError(root)
    sessions = []
    for f in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
        # A transcript is appended to as the session runs: last written before the window means
        # it started before the window too.
        try:
            if stale(os.stat(f).st_mtime, since):
                continue
        except OSError:
            continue
        s = parse(f, repo_names)
        if s is not None:
            sessions.append(s)
    return sessions


def _usage_row(u: dict) -> dict:
    row = {k: u.get(k, 0) or 0 for k in TOKEN_KEYS}
    row[CACHE_1H_KEY] = ((u.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0)
    return row


def _add_usage(target: dict, per_message: dict) -> None:
    for model, row in per_message.values():
        for k, v in row.items():
            if v:
                target[model][k] += v


def _add_reread(target, per_message: dict) -> None:
    for model, row in per_message.values():
        ctx = row["input_tokens"] + row["cache_read_input_tokens"] + row["cache_creation_input_tokens"]
        if ctx > LONG_CONTEXT:
            target[model] += ctx - HANDOFF_CONTEXT


# ~/repos/<name>/… or ~/.worktrees/<name>/<branch>/… inside a tool call's path or command.
_REPO_PATH_RE = re.compile(r"/(?:repos|\.worktrees)/([A-Za-z0-9._-]+)")


def _touched(inp: dict) -> list[str]:
    text = " ".join(str(inp.get(k) or "") for k in ("file_path", "path", "command", "notebook_path"))
    return [r for r in _REPO_PATH_RE.findall(text) if r not in (".", "..")]


def _subagent_usage(f: str) -> dict:
    """model -> token row for every message in <session>/subagents/*.jsonl, one row per message id."""
    per_message: dict = {}
    for sf in sorted(glob.glob(os.path.join(f[:-len(".jsonl")], "subagents", "*.jsonl"))):
        try:
            fh = open(sf, errors="replace")
        except OSError:
            continue
        with fh:
            for n, line in enumerate(fh):
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") != "assistant":
                    continue
                m = o.get("message", {})
                per_message[(sf, m.get("id") or n)] = (m.get("model", "?"), _usage_row(m.get("usage") or {}))
    return per_message


def parse(f: str, repo_names: list[str] | None = None) -> Session | None:
    slug = os.path.basename(os.path.dirname(f))
    s = Session(harness=NAME, project=slug, sid=os.path.basename(f)[:-6], path=f, size=os.path.getsize(f))
    pending_calls: dict = {}  # tool_use_id -> {server, tool, turn_index}, until its tool_result arrives
    active_prev = None  # last assistant/user timestamp seen, kept only to sum gaps — never a list
    last_text = None  # (ts, text) of the agent's latest text block, until a tool call or a human turn follows
    after_error = False  # the last assistant record was an API error
    # Claude Code writes one record per content block: a reply with text and three tool calls is
    # four records, each carrying the same message id and usage. Summing per record counted output
    # 2.85x over 2026-09 (102M vs 36M tokens). Usage is keyed by message id, the last record wins
    # (in subagent files the records of one message carry growing counts).
    per_message: dict = {}
    failed_in_a_row = 0  # tool results that came back is_error, since the last one that did not
    loop_keys: set = set()
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
            if str(o.get("entrypoint") or "").startswith(BATCH_ENTRYPOINT_PREFIX):
                s.batch = True
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
                # `isApiErrorMessage`: a synthetic "API Error: Can't reach the API server" turn.
                # The human's next "Try again" is a retry, not a turn (see adapters.is_retry).
                after_error = bool(o.get("isApiErrorMessage"))
                model = m.get("model", "?")
                key = m.get("id") or ("line", s.assistant_turns, ts)
                if key not in per_message:
                    s.assistant_turns += 1
                    s.models[model] += 1
                    if failed_in_a_row >= ERROR_LOOP:
                        loop_keys.add(key)
                per_message[key] = (model, _usage_row(m.get("usage") or {}))
                said = text_of(m.get("content"))
                if said.strip():
                    last_text = (ts, said)
                for b in m.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        last_text = None  # the turn went on after the text: it did not end there
                        name = b.get("name")
                        s.tools[name] += 1
                        inp = b.get("input", {}) or {}
                        s.touched_repos.update(_touched(inp))
                        if _touches_governance(name, inp):
                            s.gov_edits += 1
                            # The write's own date, not the session's start, and local like the
                            # ack day it is compared with (review of #68, P2).
                            if ts and local_day(ts) not in s.gov_days:
                                s.gov_days.append(local_day(ts))
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
                    results = [b for b in c if isinstance(b, dict) and b.get("type") == "tool_result"]
                    failed_in_a_row = failed_in_a_row + 1 if all(b.get("is_error") for b in results) else 0
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
                if not txt or o.get("isMeta"):
                    continue
                h = human_text(txt, after_error)
                after_error = False
                # A bare "continue" is a retry to the turn counts but an approval to A15: it
                # still answers the question the agent ended on (review of the #60 merge).
                # The reminder block Claude Code appends to a prompt is not part of the reply:
                # "continue" + <system-reminder>…</system-reminder> is still "continue".
                bare = strip_reminders(txt)
                reply = h if h is not None else (bare if is_retry(bare) else None)
                if reply is not None:
                    ending = turn_end_candidate(last_text[1]) if last_text else None
                    if ending:
                        s.turn_ends.append((last_text[0], ending, reply[:200]))
                    last_text = None
                if h is None:
                    continue
                s.user_turns.append(Turn(ts, h[:1500], is_correction(h)))
    s.active_hours = round(s.active_hours, 2)
    if not s.first:
        return None
    _add_usage(s.usage, per_message)
    _add_usage(s.loop_usage, {k: v for k, v in per_message.items() if k in loop_keys})
    _add_reread(s.reread_excess, per_message)
    subs = _subagent_usage(f)
    _add_usage(s.usage, subs)
    _add_usage(s.sub_usage, subs)
    _add_reread(s.reread_excess, subs)
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

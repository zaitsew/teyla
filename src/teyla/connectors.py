"""`teyla connectors` — per-MCP-connector usage: the corporate equivalent of the model ladder.

A "connector" is one MCP server (Jira, a messaging tool, a file store, ...). Adapters
(claude_code.py, and codex.py where it has function_call/function_call_output pairs) already
match every `mcp__<server>__<tool>` call to its result and record it on `Session.connector_calls`
as `{server, tool, turn_index, result}` — never the arguments or the result content, a
classification only (error | empty | ok). This module turns that into the view a connector-heavy
session actually needs: sessions, calls, read/write split, empty/error rate, how many calls pile
up between human turns (the "round-trip tail"), which tools it spends its calls on, and how much
of that is pure rediscovery (list/search/schema/lookup) rather than work.

Case study: docs/case-studies/2026-09-09-corporate-pm-work-report.md §C and its feedback file's
"Add: a connector view" / "Skill use ≠ Skill-tool invocation".
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .adapters import Session

# A tool name counts as a write if it contains any of these (case-insensitive, substring).
WRITE_RE = re.compile(r"create|update|post|send|comment|transition|delete|put|patch|write|add|move|assign", re.I)

# "Rediscovery" tools: the agent re-deriving something stable (an id, a field map, a schema)
# instead of using a cached fact. Same list backs the connectors table and advice rule C2.
REDISCOVERY_RE = re.compile(r"list|search|get_fields|schema|transitions|lookup|find_user|resolve", re.I)


def parse_mcp_tool(name: str) -> tuple[str, str] | None:
    """`mcp__<server>__<tool>` -> (server, tool). Server is the segment between `mcp__` and the
    next `__`; the tool is everything after that (may itself contain `__`). None for anything
    that is not an MCP tool call."""
    if not name or not name.startswith("mcp__"):
        return None
    rest = name[len("mcp__"):]
    if "__" not in rest:
        return None
    server, tool = rest.split("__", 1)
    if not server or not tool:
        return None
    return server, tool


def _text_of(content) -> str:
    """Extract plain text from a tool_result's `content`, which is either a string (Codex's
    `output`) or a list of content blocks (Claude Code)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
    return "\n".join(parts)


def classify_result(is_error: bool, content) -> str:
    """error | empty | ok. `is_error` wins outright; otherwise empty content, or a short string
    that reads like "nothing found", is empty; everything else counts as ok. This is a heuristic,
    not ground truth — see advise() C3 and the case study's "Error vs empty" note."""
    if is_error:
        return "error"
    text = _text_of(content).strip()
    if not text:
        return "empty"
    if len(text) < 40:
        low = text.lower()
        if "no results" in low or "not found" in low or "[]" in low:
            return "empty"
    return "ok"


def _percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolation percentile (numpy's default method), no third-party dependency."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * pct
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return float(s[f])
    return s[f] + (s[c] - s[f]) * (k - f)


def metrics(sessions: "list[Session]", days: int | None = None) -> dict:
    """Per-connector (MCP server) usage across `sessions`. Reads only `Session.connector_calls`;
    never surfaces tool arguments or raw results, names and a result classification only."""
    if days:
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        sessions = [s for s in sessions if (s.first or "")[:19] >= cutoff]

    calls_by_server = defaultdict(list)  # server -> [(sid, tool, turn_index, result), ...]
    sessions_by_server = defaultdict(set)
    for s in sessions:
        for c in s.connector_calls or []:
            calls_by_server[c["server"]].append((s.sid, c["tool"], c["turn_index"], c["result"]))
            sessions_by_server[c["server"]].add(s.sid)

    connectors = {}
    for server, calls in calls_by_server.items():
        n = len(calls)
        tools = Counter(tool for _, tool, _, _ in calls)
        write = sum(1 for _, tool, _, _ in calls if WRITE_RE.search(tool))
        empty = sum(1 for _, _, _, r in calls if r == "empty")
        error = sum(1 for _, _, _, r in calls if r == "error")
        rediscovery_tools = Counter({t: cnt for t, cnt in tools.items() if REDISCOVERY_RE.search(t)})
        rediscovery_calls = sum(rediscovery_tools.values())
        # A segment is everything one connector did between two consecutive human turns: group
        # this connector's calls by (session, turn_index) and count each group's size.
        seg = defaultdict(int)
        for sid, _, turn_index, _ in calls:
            seg[(sid, turn_index)] += 1
        seg_sizes = sorted(seg.values())
        connectors[server] = dict(
            sessions=len(sessions_by_server[server]),
            calls=n,
            read=n - write, write=write,
            write_share=round(write / n, 3) if n else 0.0,
            empty=empty, empty_rate=round(empty / n, 3) if n else 0.0,
            error=error, error_rate=round(error / n, 3) if n else 0.0,
            segment_median=_percentile(seg_sizes, 0.5),
            segment_p95=_percentile(seg_sizes, 0.95),
            segment_max=max(seg_sizes) if seg_sizes else None,
            n_segments=len(seg_sizes),
            top_tools=tools.most_common(8),
            rediscovery_share=round(rediscovery_calls / n, 3) if n else 0.0,
            rediscovery_top=rediscovery_tools.most_common(5),
        )
    return dict(days=days, n_sessions=len(sessions), connectors=connectors)


def advise(m: dict) -> list[dict]:
    """C1-C4: the connector-shaped findings. Same {id, severity, title, evidence, action} shape
    as advise.py's A1-A11, so `teyla connectors` and `teyla monitor` findings read the same way."""
    F = []
    for server, c in (m.get("connectors") or {}).items():
        if c.get("calls"):
            if (c.get("segment_p95") or 0) > 25:
                F.append(dict(
                    id="C1", severity="high", title=f"{server}: round-trip tail",
                    evidence=f"p95 {c['segment_p95']:.0f} calls per human turn (max {c.get('segment_max')}, "
                             f"median {c.get('segment_median')}) across {c.get('n_segments')} segments",
                    action="The agent searches blind — give that job a saved query or a facts file."))
            if c.get("rediscovery_share", 0) > 0.4:
                F.append(dict(
                    id="C2", severity="medium", title=f"{server}: identity/lookup tools dominate",
                    evidence=f"{int(c['rediscovery_share']*100)}% of {c['calls']} calls are "
                             f"list/search/lookup/schema tools",
                    action="Cache person→id / field maps in a facts file."))
            empty_or_error = c.get("empty_rate", 0) + c.get("error_rate", 0)
            if empty_or_error > 0.25:
                F.append(dict(
                    id="C3", severity="medium", title=f"{server}: high empty-or-error rate",
                    evidence=f"{int(empty_or_error*100)}% of {c['calls']} calls came back empty or errored",
                    action="Check the connector's search defaults; count only, cannot distinguish error from empty."))
            if c["calls"] < 10 and c.get("error_rate", 0) > 0.4:
                F.append(dict(
                    id="C4", severity="low", title=f"{server}: barely used and failing",
                    evidence=f"{c['calls']} calls, {int(c['error_rate']*100)}% errored",
                    action="Decide: invest or take it off the ladder."))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(F, key=lambda f: order[f["severity"]])


# --- CLI --------------------------------------------------------------------

def render_table(m: dict) -> str:
    rows = sorted(m.get("connectors", {}).items(), key=lambda kv: -kv[1]["calls"])
    if not rows:
        return "No connector (mcp__*) calls in this window."
    L = [f"{'connector':24} {'sess':>5} {'calls':>6} {'write%':>7} {'empty%':>7} {'error%':>7} "
         f"{'p50/turn':>9} {'p95/turn':>9}  top tools"]
    for server, c in rows:
        top = ", ".join(f"{t}×{n}" for t, n in c["top_tools"])
        L.append(f"{server[:24]:24} {c['sessions']:5} {c['calls']:6} {c['write_share']*100:6.0f}% "
                  f"{c['empty_rate']*100:6.0f}% {c['error_rate']*100:6.0f}% "
                  f"{c['segment_median'] or 0:9.1f} {c['segment_p95'] or 0:9.1f}  {top}")
        if c["rediscovery_top"]:
            rt = ", ".join(f"{t}×{n}" for t, n in c["rediscovery_top"])
            L.append(f"{'':24}   rediscovery {c['rediscovery_share']*100:.0f}% of calls: {rt}")
    return "\n".join(L)


def cmd_connectors(args):
    from .adapters import load_all
    ss = [s for s in load_all() if not s.sidechain]
    if getattr(args, "project", None):
        ss = [s for s in ss if args.project in s.project or (s.cwd and args.project in s.cwd)]
    m = metrics(ss, getattr(args, "days", None))
    if args.json:
        print(json.dumps(m, indent=2, ensure_ascii=False))
        return
    print(render_table(m))
    findings = advise(m)
    if findings:
        print()
        for f in findings:
            print(f"[{f['severity']}] {f['id']} {f['title']}\n    {f['evidence']}\n    → {f['action']}")


def register(sp):
    """Add `teyla connectors` to an argparse subparsers object. Not wired from cli.py yet —
    call `connectors.register(sp)` next to the other `sp.add_parser(...)` calls in main()."""
    q = sp.add_parser("connectors", help="per-connector (MCP server) usage: read/write, empty/error rate, round-trip segments")
    q.set_defaults(fn=cmd_connectors)
    q.add_argument("--days", type=int, default=None, help="report window in days (default: all)")
    q.add_argument("--json", action="store_true")
    q.add_argument("--project", help="filter sessions by project/cwd substring")
    return q

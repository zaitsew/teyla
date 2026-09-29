"""`teyla grok-cost` — what Grok CLI sessions cost, at list price.

An orchestrating agent runs `teyla grok-cost --last --cwd <repo>` the moment a `grok -p` lane ends
and gets one line: dollars, model calls, tokens, tools, context, effort, title. The default view is
the week by project. Both rank by dollars (costUsdTicks, 1e10 = $1): cached reads are most of the
raw token count and make a token share say nothing about what was spent.

The reader is `adapters.grok.session_costs`; this module only groups and prints.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import defaultdict

from .adapters import since_epoch
from .adapters import grok

TOP_SESSIONS = 20
# advice thresholds (A13, A14)
PROJECT_SHARE = 0.5
PROJECT_FLOOR_USD = 10.0   # a $3 week where one project is 100% is not a finding
SESSION_USD = 10.0

_TMP_PREFIXES = ("/tmp", "/private/tmp", "/var/folders", "/private/var/folders")
_EMPTY_SUFFIX = "-grok-empty"


def project_of(cwd: str, home: str | None = None) -> str:
    """The name a cwd is grouped under: ~/.worktrees/<repo>/<branch>[/...] and
    ~/repos/<repo>[/...] are <repo>; a temp directory named <repo>-grok-empty is <repo> (Frank starts
    its grok children in one, so they read no repo context) and any other temp directory is "tmp";
    anything else under $HOME is its first component (~/ops is "ops"); $HOME itself is "~"; a path
    outside $HOME stays as it is."""
    home = (home or os.path.expanduser("~")).rstrip("/")
    c = (cwd or "").rstrip("/")
    temps = _TMP_PREFIXES + (tempfile.gettempdir(),)
    if any(c == t or c.startswith(t + "/") for t in temps):
        leaf = c.rsplit("/", 1)[-1]
        if leaf.endswith(_EMPTY_SUFFIX) and len(leaf) > len(_EMPTY_SUFFIX):
            return leaf[:-len(_EMPTY_SUFFIX)]
        return "tmp"
    if c == home:
        return "~"
    if c.startswith(home + "/"):
        parts = c[len(home) + 1:].split("/")
        if parts[0] in (".worktrees", "repos") and len(parts) > 1:
            return parts[1]
        return parts[0]
    return c or "unknown"


def _tok(n: float) -> str:
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.0f}k" if n >= 1e3 else str(int(n))


def _usd(x: float) -> str:
    return f"${x:,.2f}"


def line(c: grok.SessionCost) -> str:
    """The one line an orchestrator reads after a lane ends."""
    title = " ".join(c.title.split())[:70]
    if not c.turns:
        return (f"$0.00 · no billed turn (API error, or still running) · effort {c.effort or '-'} · "
                f"{c.model or '-'} · {c.sid[:8]} · {title}")
    ctx = f"ctx {_tok(c.context)}" if c.context else "ctx -"
    return (f"{_usd(c.usd)} · {c.calls} calls · in {_tok(c.input)} ({c.cached_pct:.0f}% cached) · out {_tok(c.output)} · "
            f"{c.tool_calls} tools · {ctx} · effort {c.effort or '-'} · {c.model or '-'} · {c.sid[:8]} · {title}")


def by_project(rows: list[grok.SessionCost]) -> list[dict]:
    agg: dict = defaultdict(lambda: dict(sessions=0, usd=0.0, calls=0, input=0, cached=0, output=0))
    for c in rows:
        if not c.turns:
            continue  # never billed: a probe, an API error
        a = agg[project_of(c.cwd)]
        a["sessions"] += 1
        for k in ("calls", "input", "cached", "output"):
            a[k] += getattr(c, k)
        a["usd"] += c.usd
    total = sum(a["usd"] for a in agg.values())
    out = []
    for name, a in agg.items():
        out.append(dict(project=name, share=(a["usd"] / total if total else 0.0),
                        cached_pct=min(100.0, 100.0 * a["cached"] / a["input"]) if a["input"] else 0.0, **a))
    return sorted(out, key=lambda r: -r["usd"])


def top_sessions(rows: list[grok.SessionCost], n: int = TOP_SESSIONS) -> list[grok.SessionCost]:
    return sorted((c for c in rows if c.turns), key=lambda c: -c.usd)[:n]


def project_table(rows: list[dict]) -> str:
    total = sum(r["usd"] for r in rows)
    ti = sum(r["input"] for r in rows)
    tc = sum(r["cached"] for r in rows)
    L = [f"{'project':24} {'sessions':>8} {'$ list':>10} {'%':>5} {'calls':>7} {'input':>8} {'cached':>7} {'output':>8}"]
    def one(name, r_sessions, usd, share, calls, inp, cached_pct, out):
        return (f"{name[:24]:24} {r_sessions:>8} {_usd(usd):>10} {share * 100:>4.0f}% {calls:>7} "
                f"{_tok(inp):>8} {cached_pct:>6.0f}% {_tok(out):>8}")
    for r in rows:
        L.append(one(r["project"], r["sessions"], r["usd"], r["share"], r["calls"], r["input"], r["cached_pct"], r["output"]))
    if rows:
        L.append(one("total", sum(r["sessions"] for r in rows), total, 1.0, sum(r["calls"] for r in rows), ti,
                     min(100.0, 100.0 * tc / ti) if ti else 0.0, sum(r["output"] for r in rows)))
    return "\n".join(L)


def session_table(rows: list[grok.SessionCost]) -> str:
    L = [f"{'day':10} {'sid':8} {'project':18} {'$ list':>9} {'calls':>6} {'input':>7} {'cached':>6} {'output':>7}  title"]
    for c in rows:
        L.append(f"{c.day:10} {c.sid[:8]:8} {project_of(c.cwd)[:18]:18} {_usd(c.usd):>9} {c.calls:>6} "
                 f"{_tok(c.input):>7} {c.cached_pct:>5.0f}% {_tok(c.output):>7}  {' '.join(c.title.split())[:50]}")
    return "\n".join(L)


def cmd_grok_cost(args) -> int:
    cwd = os.path.abspath(os.path.expanduser(args.cwd)) if args.cwd else None
    try:
        if args.session:
            rows = grok.session_costs(session=args.session, cwd=cwd)
            if not rows:
                print(f"no Grok session with an id starting {args.session}", file=sys.stderr)
                return 1
            exact = [c for c in rows if c.sid == args.session]
            if exact:
                rows = exact
            if len(rows) > 1:
                print(f"{len(rows)} sessions match {args.session}; give more of the id, e.g. "
                      + ", ".join(c.sid for c in rows[:3]), file=sys.stderr)
                return 1
            return _one(rows[0], args.json)
        if args.last:
            rows = grok.session_costs(since=since_epoch(args.days), cwd=cwd, last=True)
            if not rows:
                print("no Grok session found" + (f" under {cwd}" if cwd else ""), file=sys.stderr)
                return 1
            return _one(rows[0], args.json)
        days = args.days or 7
        rows = grok.session_costs(since=since_epoch(days), cwd=cwd)
    except FileNotFoundError as e:
        print(f"no Grok sessions at {e.args[0]}", file=sys.stderr)
        return 1
    if args.by == "session":
        top = top_sessions(rows)
        if args.json:
            print(json.dumps([c.to_dict() for c in top], indent=2))
        else:
            print(f"Grok sessions, last {days} days, top {TOP_SESSIONS} by list-price cost")
            print(session_table(top))
        return 0
    table = by_project(rows)
    if args.json:
        print(json.dumps(dict(days=days, total_usd=round(sum(r["usd"] for r in table), 2),
                              projects=[{**r, "usd": round(r["usd"], 2)} for r in table]), indent=2))
    else:
        print(f"Grok cost, last {days} days, by project (list price; ranked by $, not tokens)")
        print(project_table(table))
    return 0


def _one(c: grok.SessionCost, as_json: bool) -> int:
    print(json.dumps(c.to_dict(), indent=2) if as_json else line(c))
    return 0


# ---- the finding `teyla monitor` / `teyla advise` show -------------------------------------

def week(days: int = 7, root: str | None = None, rows: list | None = None) -> dict | None:
    """The numbers advise() needs, or None when Grok is not on this machine or billed nothing.
    `rows` reuses cost rows already read for a longer window (the monitor's headless section)."""
    if rows is not None:
        since = since_epoch(days)
        rows = [c for c in rows if grok._epoch(c.created) >= since]
    else:
        try:
            rows = grok.session_costs(root=root, since=since_epoch(days))
        except FileNotFoundError:
            return None
    projects = by_project(rows)
    if not projects:
        return None
    top = top_sessions(rows, 1)[0]
    return dict(days=days, total_usd=sum(r["usd"] for r in projects),
                top_project=projects[0]["project"], top_project_usd=projects[0]["usd"],
                top_project_share=projects[0]["share"],
                top_session=dict(sid=top.sid[:8], project=project_of(top.cwd), usd=top.usd, day=top.day))


def advise(w: dict | None) -> list[dict]:
    F = []
    if not w:
        return F
    if w["top_project_share"] > PROJECT_SHARE and w["total_usd"] >= PROJECT_FLOOR_USD:
        F.append(dict(id="A13", severity="medium", title="One project is most of the week's Grok cost",
                      evidence=f"{w['top_project']} is {_usd(w['top_project_usd'])} of {_usd(w['total_usd'])} "
                               f"({w['top_project_share'] * 100:.0f}%) of Grok list-price cost, last {w['days']} days",
                      action="run `teyla grok-cost --by session --cwd <path>`; if that is one loop or one big lane, split or cap it."))
    s = w["top_session"]
    if s["usd"] > SESSION_USD:
        F.append(dict(id="A14", severity="medium", title="A single Grok session cost more than $10",
                      evidence=f"{s['project']} {s['sid']} {s['day']}: {_usd(s['usd'])} list price",
                      action="run `teyla grok-cost --session <id>`; end long `grok -p` lanes at a merge, not after hours of context re-reads."))
    return F


def register(sp):
    q = sp.add_parser("grok-cost", help="what Grok CLI sessions cost at list price: the last one, or the week by project")
    q.set_defaults(fn=cmd_grok_cost)
    g = q.add_mutually_exclusive_group()
    g.add_argument("--last", action="store_true", help="one line for the most recent session (with --cwd: the latest under that path)")
    g.add_argument("--session", metavar="ID", help="one line for the session whose id starts with ID")
    q.add_argument("--cwd", metavar="PATH", help="only sessions run in PATH or below it")
    q.add_argument("--days", type=int, help="window in days (default 7; with --last, unlimited)")
    q.add_argument("--by", choices=["project", "session"], default="project", help="roll-up: by project (default) or the top 20 sessions")
    q.add_argument("--json", action="store_true")
    return q

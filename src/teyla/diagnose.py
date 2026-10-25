"""The diagnosis behind `teyla start`: what the last N days of agent sessions cost and where it leaks.

Everything is read from this machine's own session stores (Claude Code, Codex, and the other adapters)
and nothing leaves it: no network, no write. Dollars are API list price. A subscription bills
differently, and the diagnosis says so in one line, because list price is still what makes two models
and two harnesses comparable.

`collect()` loads the sessions and subagent lanes once; `diagnose()` turns them into the numbers and
`offers.build()` prices the fixes from the same data.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
from collections import Counter, defaultdict

from . import pricing
from .adapters import LONG_CONTEXT

SUBSCRIPTION_NOTE = "List price is what these tokens would cost through the API; a subscription bills differently."
EMPTY_MESSAGE = ("No agent sessions found yet in ~/.claude or ~/.codex. "
                 "Use Claude Code or Codex for a day, then run `teyla start` again.")


@dataclasses.dataclass
class Inputs:
    """What one pass over the machine found; reused by the diagnosis and by every offer's saving."""
    days: int
    sessions: list          # adapters.Session, every harness
    rows: list              # spend.session_rows
    units: list             # lanes.scan: one per subagent call (Claude Code)


def collect(days: int = 30) -> Inputs:
    from . import lanes, spend
    from .adapters import load_all, since_epoch
    sessions = load_all(since=since_epoch(days))
    rows = spend.session_rows(days, sessions=sessions)
    try:
        units = lanes.scan(days)
    except Exception:  # noqa: BLE001 — a subagent store that cannot be read leaves the lane offers without a figure
        units = []
    return Inputs(days=days, sessions=sessions, rows=rows, units=units)


def _family_usd(usage_by_model: dict, family: str) -> float:
    return sum(pricing.cost_usd(m, u) or 0.0 for m, u in usage_by_model.items() if pricing.family(m) == family)


def waiting_asks() -> int:
    """Open questions an agent session left for the human, without writing anything: the ask store
    is passed in, so the PR check and the duplicate collapse stay in memory."""
    from . import asks
    try:
        items = asks.collect(fetch=False, st=asks.load_state())
        return sum(1 for a in items if a.status == "open")
    except Exception:  # noqa: BLE001 — a missing source is not a finding
        return 0


def diagnose(days: int = 30, inputs: Inputs | None = None, with_asks: bool = True) -> dict:
    inp = inputs or collect(days)
    rows = inp.rows
    kept = {(r["harness"], r["sid"]) for r in rows}
    total = sum(r["usd"] for r in rows)
    by_harness, by_model = Counter(), Counter()
    for r in rows:
        by_harness[r["harness"]] += r["usd"]
        for m, v in r["by_model"].items():
            by_model[m] += v
    # The cost of context: what the cache parts of every priced message come to. Grok is priced from
    # its own bill and has no parts, so it counts in the total but not in this share.
    parts = Counter()
    sub_usage: dict = defaultdict(Counter)
    long_sessions, long_usd = 0, 0.0
    codex_output_usd = 0.0
    days_seen = set()
    usd_of = {(r["harness"], r["sid"]): r["usd"] for r in rows}
    for s in inp.sessions:
        if (s.harness, s.sid) not in kept:
            continue
        for m, u in s.usage.items():
            p = pricing.cost_parts(m, u)
            if p:
                parts.update(p)
                if s.harness == "codex":
                    codex_output_usd += p["output"]
        for m, u in s.sub_usage.items():
            sub_usage[m].update(u)
        if sum(s.reread_excess.values()) > 0:
            long_sessions += 1
            long_usd += usd_of[(s.harness, s.sid)]
    for r in rows:
        days_seen.update(r.get("day_usd") or {})
    priced_total = sum(parts.values())
    context_usd = parts["cache_read"] + parts["cache_write"]
    sub_total = sum(r["sub_usd"] for r in rows)
    opus_sub = _family_usd(sub_usage, "opus")
    out = dict(
        days=days,
        empty=not rows,
        total_usd=round(total, 2),
        by_harness={h: round(v, 2) for h, v in by_harness.most_common() if v >= 0.005},
        by_model={m: round(v, 2) for m, v in by_model.most_common() if v >= 0.005},
        context_usd=round(context_usd, 2),
        context_share=round(context_usd / priced_total, 3) if priced_total else 0.0,
        cache_read_usd=round(parts["cache_read"], 2),
        cache_write_usd=round(parts["cache_write"], 2),
        codex_output_usd=round(codex_output_usd, 2),
        long_context_tokens=LONG_CONTEXT,
        long_sessions=long_sessions,
        long_sessions_usd=round(long_usd, 2),
        subagent_usd=round(sub_total, 2),
        subagent_opus_usd=round(opus_sub, 2),
        subagent_opus_share=round(opus_sub / sub_total, 3) if sub_total else 0.0,
        waiting_asks=waiting_asks() if (with_asks and rows) else 0,
        sessions=len(rows),
        active_days=len(days_seen),
        window_start=(_dt.date.today() - _dt.timedelta(days=days)).isoformat(),
        note=SUBSCRIPTION_NOTE,
    )
    return out

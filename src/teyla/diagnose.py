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
from .adapters import LONG_CONTEXT, local_day

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


def count_sessions(days: int) -> int | None:
    """About how many session files `collect` will read: the Claude Code and Codex transcripts written
    inside the window. A directory listing only, so the progress line can name a number first."""
    import glob
    import os
    from .adapters import claude_code, codex, since_epoch, stale
    since = since_epoch(days)
    try:
        n = 0
        for f in glob.glob(os.path.join(claude_code.DEFAULT_ROOT, "*", "*.jsonl")):
            try:
                n += 0 if stale(os.stat(f).st_mtime, since) else 1
            except OSError:
                continue
        if os.path.isdir(codex.DEFAULT_ROOT):
            n += len(codex._rollouts(codex.DEFAULT_ROOT, since))
        return n
    except Exception:  # noqa: BLE001 — a count is only for the progress line
        return None


def collect(days: int = 30) -> Inputs:
    from . import lanes, spend
    from .adapters import load_all, since_epoch
    sessions = load_all(since=since_epoch(days))
    rows = spend.session_rows(days, sessions=sessions)
    try:
        units = lanes.scan(days, want_tokens=False)
    except Exception:  # noqa: BLE001 — a subagent store that cannot be read leaves the lane offers without a figure
        units = []
    return Inputs(days=days, sessions=sessions, rows=rows, units=units)


def window_start(days: int) -> str:
    """The first local calendar day of a `days`-day window that ends today: 30 days is 30 calendar days,
    today included, so a 30-day window never shows more than 30 active days."""
    return (_dt.date.today() - _dt.timedelta(days=max(1, days) - 1)).isoformat()


def _window_usage(day_usage: dict, since: str) -> dict:
    """model -> token row summed over the days of `day_usage` (day -> model -> row) from `since` on."""
    out: dict = defaultdict(Counter)
    for day, per_model in day_usage.items():
        if day >= since:
            for m, u in per_model.items():
                out[m].update(u)
    return out


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
    """Totals for the last `days` calendar days (`window_start`). A session that was resumed counts only
    the turns sent inside the window, taken from each message's own timestamp (Claude Code). A harness
    whose transcript has no per-message time (Codex, Hermes, Grok) books a whole session on the day it was
    last active."""
    inp = inputs or collect(days)
    since = window_start(days)
    by_harness, by_model = Counter(), Counter()
    parts = Counter()
    sub_usage: dict = defaultdict(Counter)
    long_ids, long_usd = set(), 0.0
    codex_output_usd = 0.0
    days_seen: set = set()
    total, sub_total, n_sessions = 0.0, 0.0, 0
    rows = {(r["harness"], r["sid"]): r for r in inp.rows}
    for key, r in rows.items():
        in_win = {d: v for d, v in (r.get("day_usd") or {}).items() if d >= since}
        if not in_win:
            continue
        n_sessions += 1
        days_seen.update(in_win)
        usd = sum(in_win.values())
        total += usd
        by_harness[r["harness"]] += usd
        for d, mm in (r.get("day_model_usd") or {}).items():
            if d >= since:
                for m, v in mm.items():
                    by_model[m] += v
        for d, mm in (r.get("sub_day_model_usd") or {}).items():
            if d >= since:
                sub_total += sum(mm.values())
    for s in inp.sessions:
        r = rows.get((s.harness, s.sid))
        if r is None:
            continue
        split = s.day_usage or {local_day(s.last or s.first): s.usage}
        for m, u in _window_usage(split, since).items():
            p = pricing.cost_parts(m, u)
            if p:
                parts.update(p)
                if s.harness == "codex":
                    codex_output_usd += p["output"]
        for m, u in _window_usage(s.sub_day_usage or {}, since).items():
            sub_usage[m].update(u)
        if any((d or local_day(s.last)) >= since for _m, _c, _r, d in s.long_msgs):
            long_ids.add((s.harness, s.sid))
            long_usd += sum(v for d, v in (r.get("day_usd") or {}).items() if d >= since)
    priced_total = sum(parts.values())
    context_usd = parts["cache_read"] + parts["cache_write"]
    opus_sub = _family_usd(sub_usage, "opus")
    return dict(
        days=days,
        empty=not n_sessions,
        total_usd=round(total, 2),
        by_harness={h: round(v, 2) for h, v in by_harness.most_common() if v >= 0.005},
        by_model={m: round(v, 2) for m, v in by_model.most_common() if v >= 0.005},
        context_usd=round(context_usd, 2),
        context_share=round(context_usd / priced_total, 3) if priced_total else 0.0,
        cache_read_usd=round(parts["cache_read"], 2),
        cache_write_usd=round(parts["cache_write"], 2),
        codex_output_usd=round(codex_output_usd, 2),
        long_context_tokens=LONG_CONTEXT,
        long_sessions=len(long_ids),
        long_sessions_usd=round(long_usd, 2),
        subagent_usd=round(sub_total, 2),
        subagent_opus_usd=round(opus_sub, 2),
        subagent_opus_share=round(opus_sub / sub_total, 3) if sub_total else 0.0,
        waiting_asks=waiting_asks() if (with_asks and n_sessions) else 0,
        sessions=n_sessions,
        active_days=len(days_seen),
        window_start=since,
        note=SUBSCRIPTION_NOTE,
    )

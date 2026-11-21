"""One definition of "what did it cost, over which days", shared by `teyla spend`, `teyla monitor` and
`teyla lanes`.

Before this module the three commands each decided for themselves. `monitor` kept the sessions that
*started* in the window and priced their whole life; `spend` split every session by the local day of
each message; `lanes` cut at an instant `days * 24 h` ago and counted a message twice when its request
id differed. Over the same seven days they printed $1,334, $1,786 and a subagent total that was $64
higher than spend's. Now all three use these rules:

- **Prices:** `pricing.cost_usd`, the single table (`pricing.PRICES` plus `~/.teyla/prices.json`).
- **Window:** the last `days` local days, today included. A message counts when its own local day is
  in the window, whichever session holds it (`WINDOW_RULE`). A harness without per-message times
  books the whole session on the day it was last active.
- **Population:** one message id is one message (the last record of it wins); a session that is a
  sidechain is not counted on its own.
- **No price:** a model the table does not know costs nothing in the total and is named on its own
  line, with its tokens, in every command (`UNPRICED`): never silently $0.
"""
from __future__ import annotations

import datetime as _dt
from collections import Counter, defaultdict

from . import pricing

WINDOW_RULE = ("window: the last {days} local days ({first} to {last}), counted by the local day of each "
               "message; one message id is one message")
UNPRICED = "unpriced: {model} — {tokens:,} tokens (no list price in the table; not in the total)"
_TOKENS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def window(days: int, today: _dt.date | None = None) -> list[str]:
    """The last `days` local days, oldest first, today included."""
    today = today or _dt.date.today()
    return [(today - _dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def window_rule(days: int, today: _dt.date | None = None) -> str:
    span = window(days, today)
    return WINDOW_RULE.format(days=days, first=span[0], last=span[-1])


def tokens_of(usage: dict) -> int:
    """All tokens of a usage row; the 1-hour cache share is a subset of the cache writes, not extra."""
    return sum(int(usage.get(k, 0) or 0) for k in _TOKENS)


def cutoff_utc(days: int, now: _dt.datetime | None = None) -> str:
    """The UTC instant `days` ago as an ISO prefix. Used only to choose which sessions to open, never
    to cut a total: the window above does that."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return (now - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")


def candidates(sessions, days: int, now: _dt.datetime | None = None) -> list:
    """The sessions that may hold a message of the window: active at or after the cutoff `days + 1`
    days ago (one more day than asked: a message of the oldest local day can sit in a session whose
    last activity is before the UTC cutoff), and not a sidechain. The exact cut is `window()`."""
    cut = cutoff_utc(days + 1, now)
    return [s for s in sessions if not s.sidechain and (s.last or s.first or "")[:19] >= cut]


def _day_split(split: dict | None, fallback: dict, s) -> dict:
    if split:
        return split
    from .adapters import local_day
    return {local_day(s.last or s.first): fallback} if fallback else {}


def day_usage(s) -> dict:
    """day -> model -> token row for everything the session spent, subagents included."""
    return _day_split(s.day_usage, s.usage, s)


def sub_day_usage(s) -> dict:
    """day -> model -> token row for the session's subagents alone."""
    return _day_split(s.sub_day_usage, {}, s)


def in_window(split: dict, days: set[str] | None) -> dict:
    """model -> summed token row over the days of `split` that are in `days` (None: every day)."""
    out: dict = defaultdict(Counter)
    for d, models in split.items():
        if days is not None and d not in days:
            continue
        for model, row in models.items():
            out[model].update({k: v for k, v in row.items() if v})
    return out


def session_usage(s, days: int | None, today: _dt.date | None = None) -> dict:
    """model -> token row of the session's messages inside the window (days None: the whole session)."""
    return in_window(day_usage(s), set(window(days, today)) if days else None)


def price(model: str, usage: dict) -> float | None:
    """The one price lookup: dollars at list price, or None when the table has no row for the model."""
    return pricing.cost_usd(model, usage)


class Ledger:
    """A running total in dollars that remembers every model it could not price."""

    def __init__(self) -> None:
        self.usd = 0.0
        self.unpriced: Counter = Counter()

    def add(self, model: str, row: dict) -> float:
        c = price(model, row)
        if c is None:
            self.unpriced[model] += tokens_of(row)
            return 0.0
        self.usd += c
        return c

    def lines(self) -> list[str]:
        return unpriced_lines(self.unpriced)


def unpriced_lines(unpriced: dict) -> list[str]:
    """One `unpriced: <model> — N tokens` line per model that carried tokens, largest first."""
    return [UNPRICED.format(model=m, tokens=n) for m, n in sorted(unpriced.items(), key=lambda kv: (-kv[1], kv[0])) if n > 0]

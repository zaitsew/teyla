"""Which beats make the reel: candidates in, at most `n` out.

A candidate is a beat that has not been rendered (and so not redacted) yet: its group, its time,
a score and a `render` that returns the Beat or None when redaction drops it. Selection works on
that metadata alone, so redaction runs only on beats that can be shown, and a beat that
redaction drops is replaced by the next one in line (`story.build` loops on `pick`).

Rules (docs/reel.md): keep the ask and the last commit or PR; then take beats round by round in
this order, one from each group per round: failed tests, passed tests, PRs, reviews, commits, the
largest edits, lanes. Inside a group the pick is spread over the session time (the first, the
last, then the middles), except edits, which go by size. Shell commands only fill what is left,
and never more than two.
"""
from __future__ import annotations

import dataclasses
from typing import Callable

ORDER = ("test_fail", "test_pass", "pr", "review", "commit", "edit", "lane")
CAPS = {"test_fail": 3, "test_pass": 3, "pr": 3, "review": 1, "commit": 4, "edit": 4, "lane": 3}
MAX_COMMANDS = 2


@dataclasses.dataclass(eq=False)
class Cand:
    group: str                      # ask | test_fail | test_pass | pr | review | commit | edit | lane | command
    t: float
    score: float = 0.0
    key: str = ""                   # edits: the file, so one file is shown once
    render: Callable | None = None  # () -> Beat | None


def bisect_order(m: int) -> list[int]:
    """0..m-1 so that every prefix is spread out: the ends, then the middles."""
    if m <= 0:
        return []
    out = [0] if m == 1 else [0, m - 1]
    spans = [(0, m - 1)]
    while spans:
        nxt = []
        for lo, hi in spans:
            mid = (lo + hi) // 2
            if lo < mid < hi:
                out.append(mid)
                nxt += [(lo, mid), (mid, hi)]
            elif hi - lo > 2:
                nxt.append((lo, hi))
        spans = nxt
    return out


def _group_order(group: str, items: list[Cand]) -> list[Cand]:
    items = sorted(items, key=lambda c: c.t)
    if group == "edit":
        seen, out = set(), []
        for c in sorted(items, key=lambda c: (-c.score, c.t)):
            if c.key in seen:
                continue
            seen.add(c.key)
            out.append(c)
        return out
    return [items[i] for i in bisect_order(len(items))]


def max_beats(seconds: float) -> int:
    """How many beats fit in `seconds`: 2.5 s title card, 3 s end card, about 3.2 s a beat."""
    return max(3, int((seconds - 5.5) / 3.2))


def pick(cands: list[Cand], n: int, excluded=frozenset()) -> list[Cand]:
    """At most `n` candidates, ordered by time."""
    pool = [c for c in cands if id(c) not in excluded]
    chosen: list[Cand] = [c for c in pool if c.group == "ask"][:1]
    tail = [c for c in pool if c.group in ("commit", "pr")]
    if tail:
        chosen.append(max(tail, key=lambda c: c.t))
    queues = {g: [c for c in _group_order(g, [c for c in pool if c.group == g]) if c not in chosen] for g in ORDER}
    taken = {g: 0 for g in ORDER}
    taken.update({g: sum(1 for c in chosen if c.group == g) for g in ORDER})
    progress = True
    while len(chosen) < n and progress:
        progress = False
        for g in ORDER:
            if len(chosen) >= n:
                break
            if queues[g] and taken[g] < CAPS[g]:
                chosen.append(queues[g].pop(0))
                taken[g] += 1
                progress = True
    if len(chosen) < n:   # the caps held something back and nothing else is left: let them go
        for g in ORDER:
            while queues[g] and len(chosen) < n:
                chosen.append(queues[g].pop(0))
    commands = sorted((c for c in pool if c.group == "command"), key=lambda c: (-c.score, c.t))
    for c in commands[:MAX_COMMANDS]:
        if len(chosen) < n:
            chosen.append(c)
    return sorted(chosen, key=lambda c: (c.group != "ask", c.t))

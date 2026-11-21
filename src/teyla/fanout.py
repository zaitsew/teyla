"""Run one slow call per item concurrently, keep the order, and say what is still running.

`teyla products` (a `./check.sh usage` per repo) and `teyla reviews` (a `gh` call per repo) are sweeps over
every repo on the machine. Done one after another they take minutes on a loaded Mac and print nothing until
the end. `pmap` runs them in a small pool, returns the results in the order of the items, and writes one
progress line to stderr when stderr is a terminal. Each call carries its own timeout; `pmap` never kills a
thread, so a call without one can still hold the sweep.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")

WORKERS = 6


def _tty() -> bool:
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def _say(text: str) -> None:
    print("\r" + text + "\033[K", end="", file=sys.stderr, flush=True)


def pmap(fn: Callable[[T], R], items: Sequence[T], *, workers: int = WORKERS, label: str = "",
         name: Callable[[T], str] | None = None, progress: bool | None = None) -> list[R]:
    """`[fn(x) for x in items]`, concurrently, in item order. `fn` returns a status instead of raising; an
    exception that escapes is re-raised after the pool drains. `progress` None: only on a terminal."""
    items = list(items)
    show = (_tty() if progress is None else progress) and len(items) > 1
    results: list = [None] * len(items)
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items) or 1))) as pool:
        futs = {pool.submit(fn, x): i for i, x in enumerate(items)}
        for f in as_completed(futs):
            i = futs[f]
            results[i] = f.result()
            done += 1
            if show:
                _say(f"{label} {done}/{len(items)}" + (f" (last: {name(items[i])})" if name else ""))
    if show:
        _say("")
    return results

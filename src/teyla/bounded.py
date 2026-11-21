"""Run independent checks side by side, each with its own time limit.

`teyla storage` and `teyla doctor` are lists of unrelated probes (git over many worktrees,
`ps`, `simctl`, a transcript parse). Run one after another, the slowest machine decides the
total, and one stuck probe hangs the whole command. `run` starts them on a small pool; a probe
that has not answered after `timeout` seconds is reported as such and left behind (its thread
is a daemon, so it never keeps the process alive), and the others still print.

Threads, not processes: every probe here is a subprocess wait or a file read.
"""
from __future__ import annotations

import queue
import threading
from typing import Any, Callable, NamedTuple


class Outcome(NamedTuple):
    value: Any = None
    timed_out: bool = False
    error: BaseException | None = None

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.error is None


def unanswered(name: str, secs: float | None) -> str:
    """The one sentence every command prints for a probe that ran out of time."""
    return f"{name} did not answer in {secs:g} s"


def run(tasks: dict[str, Callable[[], Any]], timeout: float | None, workers: int = 6,
        limits: dict[str, float | None] | None = None) -> dict[str, Outcome]:
    """Call every task, at most `workers` at a time, each limited to `timeout` seconds from its own
    start (None = no limit; `limits` overrides it per task). The result has the tasks' order. An
    exception is returned, not raised."""
    names = list(tasks)
    results: dict[str, Outcome] = {}
    todo: queue.Queue = queue.Queue()
    for n in names:
        todo.put(n)

    def one(name: str) -> None:
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["value"] = tasks[name]()
            except BaseException as e:  # noqa: BLE001 — handed back to the caller, never lost
                box["error"] = e

        t = threading.Thread(target=target, daemon=True, name=f"bounded-{name}")
        t.start()
        t.join((limits or {}).get(name, timeout))
        if t.is_alive():
            results[name] = Outcome(timed_out=True)
        elif "error" in box:
            results[name] = Outcome(error=box["error"])
        else:
            results[name] = Outcome(value=box.get("value"))

    def worker() -> None:
        while True:
            try:
                name = todo.get_nowait()
            except queue.Empty:
                return
            one(name)

    pool = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, min(workers, len(names))))]
    for p in pool:
        p.start()
    for p in pool:
        p.join()
    return {n: results[n] for n in names}

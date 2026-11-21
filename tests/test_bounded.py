"""`bounded.run`: independent probes side by side, a stuck one reported and left behind."""
from __future__ import annotations

import threading

from teyla import bounded


def test_results_keep_the_order_of_the_tasks():
    out = bounded.run({"a": lambda: 1, "b": lambda: 2, "c": lambda: 3}, timeout=5, workers=2)
    assert list(out) == ["a", "b", "c"]
    assert [o.value for o in out.values()] == [1, 2, 3]
    assert all(o.ok for o in out.values())


def test_a_stuck_task_times_out_and_the_others_still_answer():
    stop = threading.Event()
    out = bounded.run({"slow": lambda: stop.wait(30), "fast": lambda: "done"}, timeout=0.2)
    stop.set()
    assert out["slow"].timed_out and not out["slow"].ok
    assert out["fast"].value == "done"


def test_an_exception_is_returned_not_raised():
    def boom():
        raise ValueError("no")
    out = bounded.run({"boom": boom, "fine": lambda: 1}, timeout=5)
    assert isinstance(out["boom"].error, ValueError)
    assert out["fine"].ok


def test_limits_override_the_default_for_one_task():
    stop = threading.Event()
    out = bounded.run({"waits": lambda: (stop.wait(0.3), "late")[1], "capped": lambda: stop.wait(30)},
                      timeout=None, limits={"capped": 0.1})
    stop.set()
    assert out["waits"].value == "late"
    assert out["capped"].timed_out


def test_no_tasks_is_an_empty_result():
    assert bounded.run({}, timeout=1) == {}


def test_the_sentence_names_the_probe_and_the_limit():
    assert bounded.unanswered("memory", 20) == "memory did not answer in 20 s"
    assert bounded.unanswered("memory", 0.5) == "memory did not answer in 0.5 s"

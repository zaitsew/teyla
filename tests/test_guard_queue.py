"""The guard's wait queue: first come, first served, priority first, dead tickets ignored."""
from __future__ import annotations

import json
import signal

import pytest

from teyla import load
from test_load import Clock, Sink, procs, snap

NOW = 1_000_000.0
CALM = {"settle_s": 0}
ME, OLDER, OLDEST = 4001, 4002, 4003


def _alive(dead=()):
    return lambda pid: pid not in dead


def _ticket(kind, pid, ts, priority=False, deadline=None):
    d = load.queue_dir(kind)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{int(ts * 1000):015d}-{pid}-x.json"
    p.write_text(json.dumps({"pid": pid, "kind": kind, "ts": ts, "priority": priority,
                             "deadline": ts + 900 if deadline is None else deadline}))
    return p


def _wait(kind="build", timeout=60, snap_obj=None, priority=False, alive=None, clock=None, **kw):
    clock = clock or Clock()
    out, err = Sink(), Sink()
    s = snap_obj or snap()
    code = load.wait(kind, CALM, timeout, poll_s=15, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: s,
                     out=out, err=err, priority=priority, wall=lambda: NOW + clock.t, alive=alive or _alive(), **kw)
    return code, out, err, clock


def _left(kind):
    return list(load.queue_dir(kind).glob("*.json"))


def test_the_oldest_ticket_is_admitted_and_a_newer_waiter_keeps_waiting():
    older = _ticket("build", OLDER, NOW - 30)
    code, out, err, _ = _wait()
    assert code == 3                                               # held behind the older waiter
    assert "2nd in line (1 ahead)" in err.text
    assert "waiting for a build slot" in err.text
    assert _left("build") == [older]                               # its own ticket is gone, the older one stays


def test_the_waiter_goes_in_when_the_older_ticket_leaves():
    older = _ticket("build", OLDER, NOW - 30)
    older.unlink()
    code, out, err, _ = _wait()
    assert code == 0 and out.text == "" and _left("build") == []


def test_a_dead_pid_ticket_does_not_block_and_is_removed():
    dead = _ticket("build", OLDER, NOW - 30)
    code, _, _, _ = _wait(alive=_alive({OLDER}))
    assert code == 0 and not dead.exists()


def test_a_ticket_past_its_own_deadline_is_ignored_and_removed():
    stale = _ticket("build", OLDER, NOW - 5000, deadline=NOW - 100)
    code, _, _, _ = _wait()
    assert code == 0 and not stale.exists()


def test_a_priority_waiter_goes_ahead_of_older_normal_tickets():
    normal = _ticket("build", OLDER, NOW - 30)
    code, _, _, _ = _wait(priority=True)
    assert code == 0 and _left("build") == [normal]


def test_priority_tickets_keep_arrival_order():
    first = _ticket("build", OLDER, NOW - 30, priority=True)
    code, _, err, _ = _wait(priority=True)
    assert code == 3 and "2nd in line (1 ahead)" in err.text and _left("build") == [first]


def test_position_counts_everyone_ahead_and_kinds_are_separate():
    _ticket("build", OLDER, NOW - 30)
    _ticket("build", OLDEST, NOW - 20)
    _ticket("sim", 4009, NOW - 90)                                 # another kind: not ahead
    _, _, err, _ = _wait()
    assert "3rd in line (2 ahead)" in err.text
    assert load.position_text("build", 0) == "waiting for a build slot: 1st in line (0 ahead)"
    assert load.position_text("lane", 10) == "waiting for a lane slot: 11th in line (10 ahead)"


def test_the_ticket_is_removed_on_timeout_when_the_machine_is_busy():
    code, out, _, _ = _wait(snap_obj=snap(procs=procs(builds=3)))
    assert code == 3 and "builds already run" in out.text and _left("build") == []


def test_the_ticket_is_removed_when_the_wait_raises():
    def boom():
        raise RuntimeError("snapshot exploded")
    clock = Clock()
    with pytest.raises(RuntimeError):
        load.wait("build", CALM, 60, clock=clock.now, sleeper=clock.sleep, snap_fn=boom, out=Sink(), err=Sink(),
                  wall=lambda: NOW, alive=_alive())
    assert _left("build") == []


def test_sigterm_ends_the_wait_through_system_exit_and_the_handler_is_restored():
    before = signal.getsignal(signal.SIGTERM)
    with load._term_as_exit():
        handler = signal.getsignal(signal.SIGTERM)
        with pytest.raises(SystemExit):
            handler(signal.SIGTERM, None)                          # called directly: nothing is killed
    assert signal.getsignal(signal.SIGTERM) == before


def test_a_waiter_without_a_ticket_still_races_so_a_mixed_install_does_not_deadlock():
    _ticket("build", OLDER, NOW - 30)
    code, _, _, _ = _wait(queue=False)
    assert code == 0


def test_an_unwritable_queue_lets_the_waiter_through_as_before(monkeypatch):
    monkeypatch.setattr(load, "take_ticket", lambda *a, **k: None)
    _ticket("build", OLDER, NOW - 30)
    code, _, _, _ = _wait()
    assert code == 0


def test_queue_lengths_show_only_live_tickets():
    _ticket("build", OLDER, NOW - 30)
    _ticket("build", OLDEST, NOW - 20)
    _ticket("lane", 4010, NOW - 20)
    assert load.queue_lengths(NOW, _alive({OLDEST})) == {"build": 1, "lane": 1}
    assert load.queue_lengths(NOW + 5000, _alive()) == {}          # past every deadline

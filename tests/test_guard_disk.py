"""Free disk in the machine guard (2026-10-11).

The disk went from 16 GB to 1 GB free in one morning of agent work and the Mac hung without a panic
report: APFS swap shares the container, so a full disk leaves memory pressure nowhere to go. The guard
looked at RAM, swap, load and the compressor, never at the disk. Now a low disk is BUSY, a very low
one CRITICAL (heavy work refused, the alert written), and the minute tick runs the temp sweep itself."""
from __future__ import annotations

import pytest

from teyla import guard, load, storage, storage_sweep

from test_guard import Clock, Machine, conf

GIB = load.GIB


def snap(free_gb: float | None) -> load.Snapshot:
    return load.Snapshot(time="2026-10-11T09:00:00+02:00", ram_bytes=24 * GIB, ncpu=10, load1=1.0, load5=1.0,
                         load15=1.0, swap_used_bytes=0, pressure=1, compressor_bytes=GIB,
                         disk_free_bytes=None if free_gb is None else int(free_gb * GIB))


@pytest.mark.parametrize("free_gb,level", [(None, load.OK), (100, load.OK), (24, load.BUSY), (9.5, load.CRITICAL)])
def test_free_disk_sets_the_verdict(free_gb, level):
    v = load.assess(snap(free_gb), conf())
    assert v.level == level
    if level != load.OK:
        assert "free on disk" in v.reasons[0]


def test_thresholds_come_from_config():
    assert load.assess(snap(24), conf(disk_warn_gb=20)).level == load.OK
    assert load.assess(snap(14), conf(disk_crit_gb=15)).level == load.CRITICAL


def test_a_critical_disk_refuses_heavy_work_and_says_how_to_free_it():
    ok, msg = load.admit("build", snap(1.0), conf())
    assert not ok
    assert "free on disk" in msg and "teyla storage sweep`" in msg
    assert load.admit("build", snap(50), conf())[0]


def test_the_report_and_the_recorder_carry_the_disk(tmp_path):
    s = snap(12.3)
    v = load.assess(s, conf())
    assert "disk: 12.3 GB free" in load.render(s, v)
    path = tmp_path / "load.tsv"
    load.record(s, v, path=path)
    assert load.read_records(path=path)[0]["disk_free_bytes"] == s.disk_free_bytes


def test_a_row_recorded_before_the_disk_column_still_reads(tmp_path):
    s = snap(50)
    old = "\t".join(load.record_fields(s, load.assess(s, conf()))[:load._MIN_COLUMNS])
    path = tmp_path / "load.tsv"
    path.write_text("#" + "\t".join(load.COLUMNS[:load._MIN_COLUMNS]) + "\n" + old + "\n")
    rows = load.read_records(path=path)
    assert len(rows) == 1 and rows[0]["disk_free_bytes"] is None


# --- the tick sweeps --------------------------------------------------------------------------------------

@pytest.fixture
def sweeps(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / "storage.log")
    runs = []

    def fake_run(temp_only=False, **k):
        runs.append(temp_only)
        return {"busy": False, "total": 3 * GIB, "free_after": 21 * GIB, "lines": ["done: removed 3.0G"]}
    monkeypatch.setattr(storage_sweep, "run", fake_run)
    monkeypatch.setattr(storage_sweep, "write_log", lambda lines: None)
    return runs


def tick_at(monkeypatch, clock, free_gb, dry=False, **kw):
    monkeypatch.setattr(load, "disk_free", lambda: int(free_gb * GIB))
    return guard.tick(conf(**kw), Machine(clock).env("darwin"), dry=dry)


def test_under_the_urgent_threshold_the_tick_sweeps_in_full_every_6_hours_and_temp_every_15_minutes(sweeps, monkeypatch):
    clock = Clock()
    res = tick_at(monkeypatch, clock, 8)
    assert sweeps == [False] and any("full sweep removed 3.0 GB" in l for l in res["lines"])
    assert res["verdict"].level == load.CRITICAL
    clock.advance(5)
    tick_at(monkeypatch, clock, 8)
    assert sweeps == [False], "a second sweep within 15 minutes"
    clock.advance(11)
    res = tick_at(monkeypatch, clock, 8)
    assert sweeps == [False, True] and any("temp sweep removed" in l for l in res["lines"])
    clock.advance(6 * 60)
    tick_at(monkeypatch, clock, 8)
    assert sweeps == [False, True, False], "the full sweep is due again after 6 hours"


def test_no_sweep_with_room_left_when_off_or_dry(sweeps, monkeypatch):
    clock = Clock()
    tick_at(monkeypatch, clock, 40)
    tick_at(monkeypatch, clock, 8, disk_sweep=False)
    res = tick_at(monkeypatch, clock, 8, dry=True)
    assert sweeps == [] and any("would run the full sweep" in l for l in res["lines"])

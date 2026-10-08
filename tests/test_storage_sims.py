"""`teyla storage sims` — idle iOS simulators are shut down, old matching devices are deleted.

`xcrun simctl` is faked (every call goes through `storage_sims.simctl`), the process list is
handed in, the clock is a number. Nothing here runs a real simulator or touches the real HOME:
device directories are built under tmp_path, and `storage.LOG_PATH` is repointed.
"""
from __future__ import annotations

import argparse
import json
import os
import time

import pytest

from teyla import storage, storage_sims

NOW = 1_800_000_000.0
MIN = 60


def udid(n: int) -> str:
    return f"{n:08X}-0000-4000-8000-000000000000"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / "storage.log")


class FakeSim:
    """A stand-in for `xcrun simctl`: `list devices -j`, `shutdown`, `delete`."""

    def __init__(self, devices, fail_shutdown=()):
        self.devices = {d[0]: {"udid": d[0], "name": d[1], "state": d[2]} for d in devices}
        self.fail_shutdown = set(fail_shutdown)
        self.calls = []

    def __call__(self, *args, timeout=60):
        self.calls.append(args)
        if args[:3] == ("list", "devices", "-j"):
            return 0, json.dumps({"devices": {"com.example.SimRuntime.iOS-27-0": list(self.devices.values())}})
        if args[0] == "shutdown":
            if args[1] in self.fail_shutdown:
                return 1, ""
            self.devices[args[1]]["state"] = "Shutdown"
            return 0, ""
        if args[0] == "delete":
            self.devices.pop(args[1], None)
            return 0, ""
        return 1, ""

    def verbs(self, verb):
        return [c[1] for c in self.calls if c[0] == verb]


def install(monkeypatch, *devices, **kw) -> FakeSim:
    sim = FakeSim(devices, **kw)
    monkeypatch.setattr(storage_sims, "simctl", sim)
    return sim


def seed_idle_since(n: int, when: float):
    d = storage.state_dir("sims")
    d.mkdir(parents=True, exist_ok=True)
    (d / udid(n)).write_text(f"{int(when)}\n")


def cfg(**kw):
    return {"storage": kw}


# --- in use or idle -------------------------------------------------------------------------

def test_a_process_naming_the_udid_means_in_use():
    u = udid(1)
    assert storage_sims.in_use(u, [f"xcodebuild test -destination id={u} -scheme App"])
    assert storage_sims.in_use(u, [f"xcrun simctl launch {u.lower()} com.example.app"])  # case does not matter


def test_the_simulators_own_runtime_and_a_log_stream_do_not_count():
    u = udid(1)
    runtime = f"/Users/me/Library/Developer/CoreSimulator/Devices/{u}/data/Containers/x/app"
    procs = [runtime,
             f"launchd_sim /Library/Developer/CoreSimulator/Volumes/iOS/RuntimeRoot/sbin/launchd_sim {u}",
             f"/Library/Developer/CoreSimulator/Volumes/iOS/x.simruntime/Contents/Resources/RuntimeRoot/bin/y {u}",
             f"/usr/bin/log stream --device {u} --level debug"]
    assert not storage_sims.in_use(u, procs)
    assert storage_sims.in_use(u, procs + [f"xctest -d {u}"])


def test_status_reports_in_use_idle_and_unknown():
    devs = [(udid(1), "Phone A", "Booted"), (udid(2), "Phone B", "Booted"), (udid(3), "Phone C", "Shutdown")]
    listing = [{"udid": u, "name": n, "state": s, "runtime": "r"} for u, n, s in devs]
    st = storage_sims.status(NOW, listing, [f"xcodebuild id={udid(1)}"], record=False)
    assert [(r["name"], r["in_use"]) for r in st["booted"]] == [("Phone A", True), ("Phone B", False)]
    lines = storage_sims.render_status(st)
    assert lines[0].startswith("in use") and lines[1].startswith("idle 0m")
    unknown = storage_sims.status(NOW, listing, None, record=False)
    assert all(r["in_use"] is None for r in unknown["booted"]) and "ps failed" in unknown["error"]
    assert storage_sims.render_status(storage_sims.status(NOW, [], [], record=False)) == ["no simulators booted"]


def test_simctl_missing_is_an_error_not_a_crash(monkeypatch):
    monkeypatch.setattr(storage_sims, "simctl", lambda *a, **k: (127, ""))
    assert storage_sims.devices() is None
    assert storage_sims.render_status(storage_sims.status(NOW, None, [], record=False)) == ["xcrun simctl is not available"]


# --- idle tracking across runs ----------------------------------------------------------------

def _listing(*pairs):
    return [{"udid": udid(n), "name": f"Phone {n}", "state": "Booted", "runtime": "r"} for n in pairs]


def test_first_idle_time_is_remembered_between_runs():
    devs = _listing(1)
    assert storage_sims.status(NOW, devs, [])["booted"][0]["idle_min"] == 0
    assert (storage.state_dir("sims") / udid(1)).read_text().strip() == str(int(NOW))
    later = storage_sims.status(NOW + 42 * MIN, devs, [])["booted"][0]
    assert later["idle_min"] == 42 and later["in_use"] is False


def test_use_resets_the_clock_and_a_device_that_is_gone_is_forgotten():
    devs = _listing(1, 2)
    storage_sims.status(NOW, devs, [])
    busy = storage_sims.status(NOW + 40 * MIN, devs, [f"xcodebuild id={udid(1)}"])
    assert not (storage.state_dir("sims") / udid(1)).exists(), "use clears the remembered idle time"
    assert busy["booted"][0]["idle_min"] == 0
    again = storage_sims.status(NOW + 50 * MIN, devs, [])
    assert again["booted"][0]["idle_min"] == 0, "idle is counted from the moment use stopped"
    assert again["booted"][1]["idle_min"] == 50
    storage_sims.status(NOW + 60 * MIN, _listing(2), [])
    assert not (storage.state_dir("sims") / udid(1)).exists(), "shut down elsewhere: forgotten"


def test_unknown_process_list_neither_records_nor_clears_state():
    devs = _listing(1)
    storage_sims.status(NOW, devs, [])
    storage_sims.status(NOW + 100 * MIN, devs, None)
    assert (storage.state_dir("sims") / udid(1)).read_text().strip() == str(int(NOW))


# --- reap ---------------------------------------------------------------------------------------

def test_reap_shuts_down_what_idled_past_the_limit_and_leaves_the_rest(monkeypatch):
    sim = install(monkeypatch, (udid(1), "Phone 1", "Booted"), (udid(2), "Phone 2", "Booted"))
    seed_idle_since(1, NOW - 31 * MIN)
    seed_idle_since(2, NOW - 29 * MIN)
    res = storage_sims.reap(cfg(), now=NOW, procs=[])
    assert sim.verbs("shutdown") == [udid(1)]
    assert res["shutdown"] == [udid(1)] and res["lines"][0].startswith("shut down")
    assert not (storage.state_dir("sims") / udid(1)).exists()
    assert "sims shut down" in (storage.LOG_PATH).read_text()


def test_the_limits_come_from_config(monkeypatch):
    sim = install(monkeypatch, (udid(1), "Phone 1", "Booted"))
    seed_idle_since(1, NOW - 11 * MIN)
    storage_sims.reap(cfg(sim_idle_min="10"), now=NOW, procs=[])
    assert sim.verbs("shutdown") == [udid(1)]


def test_over_the_cap_the_longest_idle_go_first_even_before_the_limit(monkeypatch):
    sim = install(monkeypatch, *[(udid(n), f"Phone {n}", "Booted") for n in range(1, 6)])
    for n, minutes in zip(range(1, 6), (5, 25, 10, 20, 15)):
        seed_idle_since(n, NOW - minutes * MIN)
    storage_sims.reap(cfg(sim_max_booted=3), now=NOW, procs=[])
    assert sim.verbs("shutdown") == [udid(2), udid(4)], "25 and 20 minutes idle, in that order, down to three booted"


def test_an_in_use_simulator_is_never_shut_down_even_over_the_cap(monkeypatch):
    sim = install(monkeypatch, *[(udid(n), f"Phone {n}", "Booted") for n in range(1, 5)])
    for n in range(1, 5):
        seed_idle_since(n, NOW - 90 * MIN)
    busy = [f"xcodebuild test id={udid(n)}" for n in (1, 2, 3)]
    storage_sims.reap(cfg(sim_max_booted=1), now=NOW, procs=busy)
    assert sim.verbs("shutdown") == [udid(4)]


def test_a_failed_shutdown_does_not_count_against_the_cap(monkeypatch):
    sim = install(monkeypatch, *[(udid(n), f"Phone {n}", "Booted") for n in range(1, 5)], fail_shutdown=[udid(1)])
    for n, minutes in zip(range(1, 5), (20, 15, 10, 5)):
        seed_idle_since(n, NOW - minutes * MIN)
    res = storage_sims.reap(cfg(sim_max_booted=3), now=NOW, procs=[])
    assert sim.verbs("shutdown") == [udid(1), udid(2)], "the failure leaves four booted, so the next one goes too"
    assert any(line.startswith("could not shut down") for line in res["lines"])


def test_an_unknown_process_list_shuts_nothing_down(monkeypatch):
    sim = install(monkeypatch, (udid(1), "Phone 1", "Booted"))
    seed_idle_since(1, NOW - 600 * MIN)
    storage_sims.reap(cfg(), now=NOW, procs=None)
    assert sim.verbs("shutdown") == []


def test_dry_reap_says_what_it_would_do(monkeypatch):
    sim = install(monkeypatch, (udid(1), "Phone 1", "Booted"))
    seed_idle_since(1, NOW - 31 * MIN)
    res = storage_sims.reap(cfg(), dry=True, now=NOW, procs=[])
    assert sim.verbs("shutdown") == [] and res["lines"][0].startswith("would shut down")
    assert not storage.LOG_PATH.exists()


# --- pruning devices ----------------------------------------------------------------------------

def make_device(n: int, age_days: float, prefs_age_days: float | None = None):
    root = storage_sims.devices_root() / udid(n)
    (root / "data" / "Library" / "Preferences").mkdir(parents=True)
    plist = root / "device.plist"
    plist.write_text("x")
    (root / "data" / "blob").write_bytes(b"0" * 2048)
    t = NOW - age_days * 86400
    os.utime(plist, (t, t))
    prefs = root / "data" / "Library" / "Preferences"
    p = NOW - (prefs_age_days if prefs_age_days is not None else age_days) * 86400
    os.utime(prefs, (p, p))
    return root


def test_an_empty_pattern_never_deletes_anything(monkeypatch):
    sim = install(monkeypatch, (udid(1), "Task one", "Shutdown"))
    make_device(1, age_days=400)
    res = storage_sims.reap(cfg(), now=NOW, procs=[])
    assert sim.verbs("delete") == [] and res["pruned"] == []
    assert storage_sims.settings(cfg())["prune_pattern"] == ""


def test_only_shut_down_old_devices_matching_the_pattern_are_deleted(monkeypatch):
    sim = install(monkeypatch,
                  (udid(1), "Task one", "Shutdown"),        # matches, old: deleted
                  (udid(2), "Task two", "Shutdown"),        # matches, 1 day old: kept
                  (udid(3), "My phone", "Shutdown"),        # hand-made: kept
                  (udid(4), "Task four", "Booted"),         # matches but booted: kept
                  (udid(5), "Old Task", "Shutdown"),        # the pattern is anchored at the name's start
                  (udid(6), "Task six", "Shutdown"))        # matches, old, but a process names it
    for n, age in ((1, 5), (2, 1), (3, 90), (4, 90), (5, 90), (6, 90)):
        make_device(n, age_days=age)
    res = storage_sims.reap(cfg(sim_prune_pattern="Task ", sim_prune_days=3), now=NOW,
                            procs=[f"xcodebuild -destination id={udid(6)}"])
    assert sim.verbs("delete") == [udid(1)]
    assert res["pruned"][0]["bytes"] > 0
    assert "deleted" in res["lines"][-1] and "unused 5d" in res["lines"][-1]


def test_a_device_written_to_recently_is_not_unused(monkeypatch):
    sim = install(monkeypatch, (udid(1), "Task one", "Shutdown"))
    make_device(1, age_days=30, prefs_age_days=1)   # an app wrote its preferences yesterday
    storage_sims.reap(cfg(sim_prune_pattern="Task "), now=NOW, procs=[])
    assert sim.verbs("delete") == []


def test_prune_days_zero_and_a_bad_regex_delete_nothing(monkeypatch):
    sim = install(monkeypatch, (udid(1), "Task one", "Shutdown"))
    make_device(1, age_days=30)
    storage_sims.reap(cfg(sim_prune_pattern="Task ", sim_prune_days=0), now=NOW, procs=[])
    res = storage_sims.reap(cfg(sim_prune_pattern="(unclosed"), now=NOW, procs=[])
    assert sim.verbs("delete") == [] and "not a valid regex" in res["lines"][-1]


def test_dry_prune_deletes_nothing_and_unknown_processes_delete_nothing(monkeypatch):
    sim = install(monkeypatch, (udid(1), "Task one", "Shutdown"))
    make_device(1, age_days=30)
    res = storage_sims.reap(cfg(sim_prune_pattern="Task "), dry=True, now=NOW, procs=[])
    assert res["lines"][-1].startswith("would delete") and sim.verbs("delete") == []
    storage_sims.reap(cfg(sim_prune_pattern="Task "), now=NOW, procs=None)
    assert sim.verbs("delete") == []


# --- the CLI --------------------------------------------------------------------------------------

def _args(**kw):
    base = dict(action="sims", reap=False, dry=False, json=False, quiet=False)
    return argparse.Namespace(**{**base, **kw})


def test_cli_status_and_json(monkeypatch, capsys):
    install(monkeypatch, (udid(1), "Phone 1", "Booted"))
    monkeypatch.setattr(storage, "process_commands", lambda: [])
    assert storage_sims.cmd_sims(_args(), {}) == 0
    assert "Phone 1" in capsys.readouterr().out
    storage_sims.cmd_sims(_args(json=True), {})
    assert json.loads(capsys.readouterr().out)["booted"][0]["udid"] == udid(1)


def test_cli_reap_quiet_prints_nothing_when_nothing_happened(monkeypatch, capsys):
    install(monkeypatch, (udid(1), "Phone 1", "Booted"))
    monkeypatch.setattr(storage, "process_commands", lambda: [])
    storage_sims.cmd_sims(_args(reap=True, quiet=True), {})
    assert capsys.readouterr().out == ""
    storage_sims.cmd_sims(_args(reap=True), {})
    assert "nothing to shut down" in capsys.readouterr().out


def test_the_subcommands_parse_and_dispatch(monkeypatch, capsys):
    p = argparse.ArgumentParser()
    storage.register(p.add_subparsers())
    ns = p.parse_args(["storage", "sims", "--reap", "--dry"])
    assert ns.action == "sims" and ns.reap and ns.dry
    ns = p.parse_args(["storage", "sweep", "--temp", "--dry", "--quiet"])
    assert ns.action == "sweep" and ns.temp and ns.dry and ns.quiet
    install(monkeypatch)
    monkeypatch.setattr(storage, "process_commands", lambda: [])
    assert storage.cmd_storage(p.parse_args(["storage", "sims"])) == 0
    assert "no simulators booted" in capsys.readouterr().out


def test_simctl_tries_the_usual_xcode_once_when_the_default_has_no_simctl(monkeypatch):
    seen = []

    class R:
        def __init__(self, rc): self.returncode, self.stdout = rc, "out"

    def fake_run(cmd, **kw):
        seen.append((kw.get("env") or {}).get("DEVELOPER_DIR"))
        return R(1 if len(seen) == 1 else 0)

    monkeypatch.setattr(storage_sims.shutil, "which", lambda n: "/usr/bin/xcrun")
    monkeypatch.setattr(storage_sims.subprocess, "run", fake_run)
    monkeypatch.setattr(storage_sims.os.path, "isdir", lambda p: p == storage_sims.DEFAULT_DEVELOPER_DIR)
    monkeypatch.delenv("DEVELOPER_DIR", raising=False)
    assert storage_sims.simctl("list") == (0, "out")
    assert seen == [None, storage_sims.DEFAULT_DEVELOPER_DIR]


def test_time_is_not_needed_for_status(monkeypatch):
    # `now` defaults to the wall clock: a status call with a fake listing must still work.
    st = storage_sims.status(devs=_listing(1), procs=[], record=False)
    assert abs(st["booted"][0]["since"] - time.time()) < 5

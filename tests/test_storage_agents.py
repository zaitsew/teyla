"""The optional launchd agents (`storage.sims_agent`, `storage.sweep_agent`, `guard.agent`), `teyla uninstall`
removing them, and the free-disk figure in doctor's summary line.

launchctl is never called: `_load`, `_unload` and `loaded` are replaced by recorders, and every
path routine_install writes is moved under a tmp HOME (the optional agents' paths follow the
weekly's, so they move with it).
"""
from __future__ import annotations

import pathlib
import plistlib

import pytest

from teyla import config, doctor, routine_install as ri, storage, uninstall

GIB = 1024 ** 3


class Home(type(pathlib.Path())):
    """A Path that also carries the recorded launchctl calls."""


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = Home(tmp_path / "home")
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    for name, rel in (("PLIST_PATH", "Library/LaunchAgents/com.zaitsew.teyla.weekly.plist"), ("WRAPPER_PATH", ".teyla/weekly.sh"),
                      ("DAILY_PLIST_PATH", "Library/LaunchAgents/com.zaitsew.teyla.daily.plist"), ("DAILY_WRAPPER_PATH", ".teyla/daily.sh"),
                      ("LOG_PATH", "Library/Logs/teyla-weekly.log"), ("DAILY_LOG_PATH", "Library/Logs/teyla-daily.log"),
                      ("STAMP_PATH", ".teyla/weekly.last"), ("DAILY_STAMP_PATH", ".teyla/daily.last")):
        monkeypatch.setattr(ri, name, home / rel)
    monkeypatch.setattr(ri, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    monkeypatch.setattr(ri, "sys", type("S", (), {"platform": "darwin", "argv": ["teyla"]}))
    calls = {"load": [], "unload": [], "loaded": set()}
    monkeypatch.setattr(ri, "_load", lambda plist, label: calls["load"].append(label) or f"loaded {label}")
    monkeypatch.setattr(ri, "_unload", lambda plist, label: calls["unload"].append(label) or f"unloaded {label}")
    monkeypatch.setattr(ri, "loaded", lambda label: (label in calls["loaded"], None, "0" if label in calls["loaded"] else None))
    monkeypatch.setattr(ri.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launchctl called")))
    home.calls = calls
    return home


def paths(label):
    return ri.optional_paths(label)


# --- defaults: nothing optional is written -------------------------------------------------------

def test_by_default_no_optional_agent_exists_and_the_weekly_does_not_sweep(home):
    lines = ri.install()
    assert not any(paths(label)["plist"].exists() for label in ri.OPTIONAL_LABELS)
    assert "storage sweep" not in ri.WRAPPER_PATH.read_text()
    assert home.calls["load"] == [ri.DAILY_LABEL, ri.LABEL] and home.calls["unload"] == []
    assert not ri.is_stale()
    assert not any(word in line for line in lines for word in ("sims", "sweep", "load.plist"))
    status = "\n".join(ri.status())
    assert all(f"{label}: off" in status for label in ri.OPTIONAL_LABELS)
    assert "off ([guard] agent = false)" in status and "off ([storage] sims_agent = false)" in status
    # the storage agents are opt-in and silent; the guard's gets one INFO line saying how to turn it on
    (level, name, detail, fix), = ri.optional_checks()
    assert (level, name) == ("INFO", "routine:load") and fix == "teyla config set guard.agent=true && teyla routine install"


# --- sims_agent --------------------------------------------------------------------------------------

def test_sims_agent_writes_an_interval_plist_and_a_wrapper(home):
    ri.install()
    config.set_value("storage.sims_agent", "true")
    assert ri.is_stale(), "switching it on makes `routine install --if-stale` act"
    lines = ri.install()
    p = paths(ri.SIMS_LABEL)
    plist = plistlib.loads(p["plist"].read_bytes())
    assert plist["Label"] == "com.zaitsew.teyla.sims" and plist["StartInterval"] == 600
    assert plist["ProgramArguments"] == ["/bin/bash", str(p["wrapper"])] and plist["RunAtLoad"] is False
    assert plist["StandardOutPath"] == str(p["log"]) == str(home / "Library/Logs/teyla-sims.log")
    assert "PATH" in plist["EnvironmentVariables"]
    text = p["wrapper"].read_text()
    assert '"$TEYLA" storage sims --reap --quiet' in text and 'TEYLA="/opt/tools/bin/teyla"' in text
    assert str(p["stamp"]) in text and p["wrapper"].stat().st_mode & 0o111
    assert ri.SIMS_LABEL in home.calls["load"] and any("sims.plist" in line for line in lines)
    assert not paths(ri.SWEEP_LABEL)["plist"].exists()
    assert not ri.is_stale()


def test_the_sims_wrapper_goes_stale_with_the_binary_or_the_env(home):
    config.set_value("storage.sims_agent", "true")
    ri.install()
    assert not ri.is_stale()
    config.set_value("env.HTTPS_PROXY", "http://127.0.0.1:9000")
    assert ri.is_stale()
    ri.install()
    assert "HTTPS_PROXY" in paths(ri.SIMS_LABEL)["wrapper"].read_text() and not ri.is_stale()


# --- guard.agent: the load recorder -------------------------------------------------------------------

def test_the_guard_agent_ticks_every_minute_from_the_guard_table(home):
    ri.install()
    config.set_value("storage.sims_agent", "true")        # another table's flag must not switch it on
    assert not ri.optional_enabled(ri.LOAD_LABEL)
    config.set_value("guard.agent", "true")
    assert ri.optional_enabled(ri.LOAD_LABEL) and ri.is_stale()
    lines = ri.install()
    p = paths(ri.LOAD_LABEL)
    plist = plistlib.loads(p["plist"].read_bytes())
    assert plist["Label"] == "com.zaitsew.teyla.load" and plist["StartInterval"] == 60 and plist["RunAtLoad"] is False
    assert plist["ProgramArguments"] == ["/bin/bash", str(p["wrapper"])]
    assert plist["StandardOutPath"] == str(home / "Library/Logs/teyla-load.log")
    text = p["wrapper"].read_text()
    assert p["wrapper"] == home / ".teyla" / "load.sh" and p["stamp"] == home / ".teyla" / "load.last"
    assert '"$TEYLA" guard tick --quiet' in text and 'TEYLA="/opt/tools/bin/teyla"' in text
    assert "because [guard] agent is on" in text and str(p["stamp"]) in text and p["wrapper"].stat().st_mode & 0o111
    assert ri.LOAD_LABEL in home.calls["load"] and any("load.plist" in line for line in lines)
    assert not ri.is_stale()
    assert "storage sweep" not in ri.WRAPPER_PATH.read_text()


def test_the_guard_agent_goes_stale_with_the_env_and_is_removed_when_switched_off(home):
    config.set_value("guard.agent", "true")
    ri.install()
    assert not ri.is_stale()
    config.set_value("env.HTTPS_PROXY", "http://127.0.0.1:9000")
    assert ri.is_stale()
    ri.install()
    p = paths(ri.LOAD_LABEL)
    assert "HTTPS_PROXY" in p["wrapper"].read_text() and not ri.is_stale()
    p["stamp"].write_text("2026-01-01T00:00:00Z\n")
    config.set_value("guard.agent", "false")
    assert ri.is_stale()
    ri.install()
    assert home.calls["unload"] == [ri.LOAD_LABEL]
    assert not p["plist"].exists() and not p["wrapper"].exists() and not p["stamp"].exists()
    assert not ri.is_stale()
    assert ri.optional_checks()[0][0] == "INFO", "off and gone again: only the suggestion"


def test_the_guard_agent_follows_the_storage_agents_in_safe_mode(home, monkeypatch):
    """All three do local work only, so a work Mac (safe mode) keeps them as configured."""
    monkeypatch.setenv("TEYLA_SAFE", "1")
    config.set_value("guard.agent", "true")
    ri.install()
    assert paths(ri.LOAD_LABEL)["plist"].exists() and ri.LOAD_LABEL in home.calls["load"]
    assert not ri.is_stale()


def test_doctor_rows_for_the_guard_agent(home):
    config.set_value("guard.agent", "true")
    assert ri.optional_checks()[0][:2] == ("FIX", "routine:load") and "[guard] agent is on" in ri.optional_checks()[0][2]
    ri.install()
    home.calls["loaded"].add(ri.LOAD_LABEL)
    level, name, detail, fix = ri.optional_checks()[0]
    assert (level, name, fix) == ("OK", "routine:load", None) and "every 1 min" in detail
    assert f"{ri.LOAD_LABEL}: on" in "\n".join(ri.status())
    config.set_value("guard.agent", "false")
    assert ri.optional_checks()[0][0] == "WARN" and "[guard] agent is off" in ri.optional_checks()[0][2]


def test_a_machine_with_the_guard_agent_off_has_no_doctor_problem_from_it(home):
    rows = [doctor._check(*row) for row in ri.optional_checks()]
    assert rows and all(r["level"] == "INFO" for r in rows)
    assert doctor._problems(rows) == []


# --- sweep_agent -------------------------------------------------------------------------------------

def test_sweep_agent_runs_the_temp_sweep_hourly_and_the_full_one_weekly(home):
    config.set_value("storage.sweep_agent", "true")
    assert ri.is_stale()
    ri.install()
    p = paths(ri.SWEEP_LABEL)
    plist = plistlib.loads(p["plist"].read_bytes())
    assert plist["Label"] == "com.zaitsew.teyla.sweep" and plist["StartInterval"] == 3600
    assert '"$TEYLA" storage sweep --temp --quiet' in p["wrapper"].read_text()
    weekly = ri.WRAPPER_PATH.read_text()
    assert weekly.rstrip().endswith('"$TEYLA" storage sweep --quiet') and "digest --write" in weekly
    assert not paths(ri.SIMS_LABEL)["plist"].exists() and not ri.is_stale()


def test_switching_an_agent_off_unloads_and_removes_it(home):
    config.set_value("storage.sims_agent", "true")
    config.set_value("storage.sweep_agent", "true")
    ri.install()
    p_sims, p_sweep = paths(ri.SIMS_LABEL), paths(ri.SWEEP_LABEL)
    p_sims["stamp"].write_text("2026-01-01T00:00:00Z\n")
    config.set_value("storage.sims_agent", "false")
    config.set_value("storage.sweep_agent", "false")
    assert ri.is_stale()
    lines = ri.install()
    assert sorted(home.calls["unload"]) == sorted([ri.SIMS_LABEL, ri.SWEEP_LABEL])
    for p in (p_sims, p_sweep):
        assert not p["plist"].exists() and not p["wrapper"].exists()
    assert not p_sims["stamp"].exists()
    assert "storage sweep" not in ri.WRAPPER_PATH.read_text() and any(line.startswith("removed") for line in lines)
    assert not ri.is_stale()


def test_install_dry_names_the_optional_files(home):
    config.set_value("storage.sims_agent", "true")
    out = ri.install(dry=True)
    assert any(str(paths(ri.SIMS_LABEL)["plist"]) in line for line in out)
    assert not paths(ri.SIMS_LABEL)["plist"].exists() and home.calls["load"] == []


# --- status and doctor ---------------------------------------------------------------------------------

def test_status_and_doctor_rows_for_an_enabled_agent(home):
    config.set_value("storage.sims_agent", "true")
    assert ri.optional_checks()[0][:2] == ("FIX", "routine:sims") and "not installed" in ri.optional_checks()[0][2]
    ri.install()
    assert ri.optional_checks()[0][0] == "FIX" and "not loaded" in ri.optional_checks()[0][2]
    home.calls["loaded"].add(ri.SIMS_LABEL)
    level, name, detail, fix = ri.optional_checks()[0]
    assert (level, name, fix) == ("OK", "routine:sims", None) and "every 10 min" in detail
    status = "\n".join(ri.status())
    assert f"{ri.SIMS_LABEL}: on" in status and "loaded: yes" in status and "every 10 min" in status


def test_doctor_warns_about_an_agent_left_installed_after_it_was_switched_off(home):
    config.set_value("storage.sweep_agent", "true")
    ri.install()
    config.set_value("storage.sweep_agent", "false")
    (level, name, detail, fix), = [r for r in ri.optional_checks() if r[1] == "routine:sweep"]
    assert (level, name) == ("WARN", "routine:sweep") and "is off" in detail and "teyla routine install" in fix
    assert "OFF in config but still installed" in "\n".join(ri.status())


# --- uninstall ------------------------------------------------------------------------------------------

def test_uninstall_removes_the_optional_agents_and_their_logs(home, monkeypatch):
    monkeypatch.setattr(uninstall, "_launchctl_list", lambda: f"-\t0\t{ri.SIMS_LABEL}\n")
    monkeypatch.setattr(uninstall, "_claude_bin", lambda: None)
    agents = home / "Library" / "LaunchAgents"
    logs = home / "Library" / "Logs"
    agents.mkdir(parents=True)
    logs.mkdir(parents=True)
    for label in ri.OPTIONAL_LABELS:
        (agents / f"{label}.plist").write_text("<plist/>")
    for n in ("teyla-sims.log", "teyla-sweep.log", "teyla-load.log"):
        (logs / n).write_text("x")
    steps = uninstall.plan(home)
    targets = {(s.verb, s.target) for s in steps if s.fn}
    for label in ri.OPTIONAL_LABELS:
        assert ("remove", str(agents / f"{label}.plist")) in targets
    assert ("unload", ri.SIMS_LABEL) in targets and ("unload", ri.SWEEP_LABEL) not in targets, "unload only what is loaded"
    assert ("remove", str(logs / "teyla-load.log")) in targets and ("remove", str(agents / f"{ri.LOAD_LABEL}.plist")) in targets
    assert ("remove", str(logs / "teyla-sims.log")) in targets and ("remove", str(logs / "teyla-sweep.log")) in targets
    kept = {s.target for s in uninstall.plan(home, keep_data=True) if s.fn}
    assert str(home / ".teyla" / "sims.sh") not in kept   # nothing to remove: the file does not exist
    (home / ".teyla" / "sims.sh").write_text("#!/bin/sh\n")
    (home / ".teyla" / "load.sh").write_text("#!/bin/sh\n")
    kept = {s.target for s in uninstall.plan(home, keep_data=True) if s.fn}
    assert str(home / ".teyla" / "sims.sh") in kept and str(home / ".teyla" / "load.sh") in kept


# --- doctor's summary line shows the free disk even when all is well ------------------------------------

def disk_row(free, level="OK"):
    return doctor._check(level, "storage:disk", f"{storage.human(free)} free", None, free=free)


def test_summary_line_carries_free_space_when_all_is_clear():
    cs = [doctor._check("OK", "a", "fine"), disk_row(64 * GIB)]
    assert doctor.summary_line(cs) == "teyla: disk 64 GB free"
    assert doctor.render(cs).splitlines()[-1] == "all clear (disk 64 GB free)"


def test_summary_line_keeps_problems_first_and_the_disk_after_them():
    cs = [doctor._check("WARN", "a", "x"), doctor._check("FIX", "version", "old", "teyla update"), disk_row(12 * GIB)]
    assert doctor.summary_line(cs) == "teyla: 1 fix(es), 1 warning(s), update available, disk 12 GB free — run `teyla doctor`"
    low = [disk_row(3.5 * GIB, "WARN")]
    assert doctor.summary_line(low) == "teyla: 1 warning(s), disk 3.5 GB free — run `teyla doctor`"
    assert doctor.render(low).splitlines()[-1] == doctor.summary_line(low)


def test_summary_line_without_a_disk_row_is_as_before():
    assert doctor.summary_line([doctor._check("OK", "a", "fine")]) == ""
    assert doctor.summary_line([doctor._check("WARN", "a", "x")]) == "teyla: 1 warning(s) — run `teyla doctor`"
    assert doctor.summary_line([doctor._check("OK", "storage:disk", "ok", None, free="lots")]) == ""


def test_storage_doctor_check_carries_the_free_bytes(monkeypatch):
    monkeypatch.setattr(storage, "disk", lambda path=None: {"total": 500 * GIB, "used": 436 * GIB, "free": 64 * GIB, "free_fraction": 0.128})
    monkeypatch.setattr(storage, "scan", lambda **k: {"worktrees": []})
    rows = storage.doctor_checks({})
    disk = next(r for r in rows if r["name"] == "storage:disk")
    assert disk["free"] == 64 * GIB and disk["level"] == "WARN"   # 12.8% is under the 15% line
    monkeypatch.setattr(storage, "disk", lambda path=None: {"total": 500 * GIB, "used": 300 * GIB, "free": 200 * GIB, "free_fraction": 0.4})
    row = next(r for r in storage.doctor_checks({}) if r["name"] == "storage:disk")
    assert row["level"] == "OK" and row["free"] == 200 * GIB
    # and doctor keeps it on the row it builds
    assert doctor._check(row["level"], row["name"], row["detail"], row["fix"], free=row["free"])["free"] == 200 * GIB

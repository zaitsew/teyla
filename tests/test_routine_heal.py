"""The 2026-10-10 incident: a test reached the real launchd, and nothing put the agents back.

A runs_root test isolated one path of routine_install; its install() rewrote the real daily.sh and
removed the real sims, sweep and load agents. Doctor reported FIX every morning after, and the next
day the Mac filled its disk and hung with no guard running. These tests pin both halves: the suite
cannot reach the real launchd, and `routine catch-up` repairs what doctor would only report."""
import pathlib

import pytest

from teyla import config, routine_install as ri


def test_a_test_without_its_own_fixture_cannot_touch_the_real_home(monkeypatch):
    """No local fixture at all: the conftest net alone keeps install() in tmp and off launchd."""
    real = pathlib.Path.home()
    for name, value in vars(ri).items():
        if isinstance(value, pathlib.Path):
            assert not value.is_relative_to(real), f"routine_install.{name} points into the real home: {value}"
    monkeypatch.setattr(ri, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    monkeypatch.setattr(ri.sys, "platform", "darwin")
    lines = ri.install()
    assert any(l.startswith("NOT LOADED") for l in lines), lines
    assert not any(l.startswith("loaded ") for l in lines), lines


def test_the_suite_refuses_a_real_launchctl_write():
    with pytest.raises(AssertionError, match="real launchctl"):
        ri.subprocess.run(["launchctl", "bootout", "gui/501/com.zaitsew.teyla.load"])


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    for name, rel in (("PLIST_PATH", "Library/LaunchAgents/com.zaitsew.teyla.weekly.plist"), ("WRAPPER_PATH", ".teyla/weekly.sh"),
                      ("DAILY_PLIST_PATH", "Library/LaunchAgents/com.zaitsew.teyla.daily.plist"), ("DAILY_WRAPPER_PATH", ".teyla/daily.sh"),
                      ("LOG_PATH", "Library/Logs/teyla-weekly.log"), ("DAILY_LOG_PATH", "Library/Logs/teyla-daily.log"),
                      ("STAMP_PATH", ".teyla/weekly.last"), ("DAILY_STAMP_PATH", ".teyla/daily.last")):
        monkeypatch.setattr(ri, name, home / rel)
    monkeypatch.setattr(ri, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    monkeypatch.setattr(ri.sys, "platform", "darwin")
    monkeypatch.setattr(ri, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(ri, "_unload", lambda plist, label: f"unloaded {label}")
    monkeypatch.delenv("TEYLA_IN_ROUTINE", raising=False)
    return home


def test_catch_up_reinstalls_an_agent_whose_plist_was_deleted(home):
    config.set_value("guard.agent", "true")
    ri.install()
    plist = ri.optional_paths(ri.LOAD_LABEL)["plist"]
    plist.unlink()  # what the leaking test did
    assert ri.is_stale()
    assert not any("REPAIR" in l for l in ri.catch_up()), "only the CLI's catch-up heals"
    dry = ri.catch_up(dry=True, heal=True)
    assert any(l.startswith("REPAIR") and "would run" in l for l in dry) and not plist.exists()
    lines = ri.catch_up(heal=True)
    assert plist.exists() and any(l == f"REPAIR: loaded {ri.LOAD_LABEL}" for l in lines), lines
    assert not ri.is_stale()
    assert not any("REPAIR" in l for l in ri.catch_up(heal=True)), "a current install is left alone"


def test_wrappers_are_replaced_not_rewritten_in_place(home):
    """bash reads a running script by offset; the daily wrapper's own catch-up rewrites it."""
    ri.install()
    before = ri.DAILY_WRAPPER_PATH.stat().st_ino
    ri.DAILY_WRAPPER_PATH.write_text(ri.DAILY_WRAPPER_PATH.read_text().replace("policy sync", "policy-sync"))
    ri.install(if_stale=True)
    assert ri.DAILY_WRAPPER_PATH.stat().st_ino != before
    assert ri.DAILY_WRAPPER_PATH.stat().st_mode & 0o777 == 0o755
    assert not list(ri.DAILY_WRAPPER_PATH.parent.glob(".*.tmp"))

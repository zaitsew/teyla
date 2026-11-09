"""`teyla crash --pull` / `--device`: TestFlight device crashes, the hourly agent and the freshness rule.

Every call goes through a fake Client. No network, no real key, no real ~/.teyla.
"""
from __future__ import annotations

import datetime as dt
import json
import plistlib
import uuid

import pytest

from teyla import cli, config, crash_feed, doctor, net, review, review_asc
from teyla import routine_install as ri

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
LOG = """Exception Type:  EXC_BAD_ACCESS (SIGSEGV)
Termination Reason: SIGNAL 11 Segmentation fault: 11

Thread 0 name:  Dispatch queue: com.apple.main-thread
0   libswiftCore.dylib  0x1 swift_retain + 8

Thread 0 Crashed:
0   Recipes  0x100 Feed.render() + 40
1   Recipes  0x200 closure #1 in Feed.body + 12

Thread 1:
0   libsystem  0x3 mach_msg + 8
"""


class Fake:
    """Answers by URL fragment; records every URL it was asked for."""

    def __init__(self, routes, boom=None):
        self.routes, self.boom, self.urls = routes, boom, []

    def get_json(self, url):
        self.urls.append(url)
        if self.boom:
            raise self.boom
        for frag, payload in self.routes:
            if frag in url:
                return payload
        return {"data": []}

    def get_bytes(self, url):
        return b"\x89PNG"


def crash_item(sid="c-1", when="2026-11-08T10:00:00.000Z", **a):
    attrs = {"createdDate": when, "email": "tester@example.com", "comment": "It closed.", "deviceModel": "iPhone16,2",
             "osVersion": "27.0", "buildNumber": "42", "appPlatform": "IOS", "buildBundleId": "com.example.recipes"}
    attrs.update(a)
    return {"type": "betaFeedbackCrashSubmissions", "id": sid, "attributes": attrs}


def routes(crashes=(), shots=(), upload="2026-11-08T08:00:00.000Z", app_id="777"):
    return [("/v1/apps?filter", {"data": [{"id": app_id}]}),
            ("betaFeedbackCrashSubmissions?limit", {"data": list(crashes)}),
            ("/crashLog", {"data": {"attributes": {"logText": LOG}}}),
            ("betaFeedbackScreenshotSubmissions", {"data": list(shots)}),
            ("/v1/builds", {"data": [{"attributes": {"uploadedDate": upload}}]})]


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "code_root", lambda: tmp_path / "repos")
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: False)
    monkeypatch.setattr(net, "_allow_once", False)
    d = tmp_path / "repos" / "recipes"
    (d / ".git").mkdir(parents=True)
    (d / "teyla.toml").write_text('[product]\nname = "recipes"\n[release]\napple_bundle_id = "com.example.recipes"\n')
    return home


@pytest.fixture
def conn(env):
    c = review.connect()
    yield c
    c.close()


def test_a_pull_stores_the_crash_without_the_email_and_finds_the_app_by_bundle_id(env, conn):
    fake = Fake(routes([crash_item()]))
    rep = crash_feed.pull(fake, conn, NOW)
    assert rep["errors"] == 0 and rep["apps"][0]["new_crashes"] == 1 and rep["apps"][0]["status"] == "ok"
    assert any("filter[bundleId]=com.example.recipes" in u for u in fake.urls)
    assert any(u.endswith("/v1/betaFeedbackCrashSubmissions/c-1/crashLog") for u in fake.urls)
    st = crash_feed.load()
    (cid, rec), = st["crashes"].items()
    assert cid == str(uuid.uuid5(review_asc.NAMESPACE, "testflight-crash:c-1"))
    assert rec["device"] == "iPhone16,2 27.0" and rec["build"] == "42" and rec["product"] == "recipes"
    assert rec["summary"]["exception"].startswith("EXC_BAD_ACCESS") and rec["summary"]["frames"][0].endswith("Feed.render() + 40")
    assert "tester@example.com" not in crash_feed.state_path().read_text()
    assert (crash_feed.store_dir() / rec["log"]).read_text() == LOG
    assert oct(crash_feed.state_path().stat().st_mode & 0o777) == "0o600"


def test_a_second_pull_adds_no_crash_and_asks_for_no_second_log(env, conn):
    crash_feed.pull(Fake(routes([crash_item()])), conn, NOW)
    fake = Fake(routes([crash_item()]))
    rep = crash_feed.pull(fake, conn, NOW + dt.timedelta(hours=1))
    assert rep["apps"][0]["new_crashes"] == 0 and rep["apps"][0]["crashes"] == 1
    assert not any("/crashLog" in u for u in fake.urls)


def test_screenshot_feedback_of_the_same_pull_reaches_the_review_queue(env, conn):
    shot = {"id": "s-1", "attributes": {"createdDate": "2026-11-08T11:00:00.000Z", "comment": "Label unreadable.",
                                        "buildBundleId": "com.example.recipes",
                                        "screenshots": [{"url": "https://images.example.com/s.png?sig=1"}]}}
    rep = crash_feed.pull(Fake(routes(shots=[shot])), conn, NOW)
    assert rep["apps"][0]["new_screenshots"] == 1
    assert [r["source"] for r in review.list_rows(conn, None, None, True)] == ["testflight"]
    assert crash_feed.load()["apps"]["com.example.recipes"]["newest_submission"].startswith("2026-11-08T11:00")


def test_a_refused_call_is_recorded_not_raised_and_keeps_the_last_good_numbers(env, conn):
    crash_feed.pull(Fake(routes([crash_item()])), conn, NOW)
    rep = crash_feed.pull(Fake([], boom=review_asc.AscError("App Store Connect answered 401")), conn, NOW + dt.timedelta(hours=1))
    assert rep["errors"] == 1
    rec = crash_feed.load()["apps"]["com.example.recipes"]
    assert "401" in rec["last_error"] and rec["crash_count"] == 1 and rec["last_pull"] == "2026-11-09T12:00:00Z"


def test_the_app_id_in_teyla_toml_wins_over_the_lookup(env, conn, tmp_path):
    (tmp_path / "repos" / "recipes" / "teyla.toml").write_text(
        '[product]\nname = "recipes"\n[release]\napple_bundle_id = "com.example.recipes"\napple_app_id = "555"\n')
    fake = Fake(routes())
    crash_feed.pull(fake, conn, NOW)
    assert not any("filter[bundleId]" in u for u in fake.urls) and any("/v1/apps/555/" in u for u in fake.urls)


def rec(**kw):
    base = {"product": "recipes", "last_pull": "2026-11-09T11:30:00Z", "newest_submission": "2026-11-08T10:00:00Z",
            "newest_upload": "2026-11-08T08:00:00Z"}
    base.update(kw)
    return base


def test_the_freshness_rule():
    assert crash_feed.freshness(rec(), NOW)[0] == "ok"
    # the agent stopped: the last good pull is 5 h old
    assert crash_feed.freshness(rec(last_pull="2026-11-09T07:00:00Z", last_error="Apple answered 401"), NOW)[0] == "pull-stale"
    # a build 1 day old, submissions seen before, the newest 30 days old
    st, text = crash_feed.freshness(rec(newest_submission="2026-10-10T10:00:00Z"), NOW)
    assert st == "may-be-frozen" and "feed may be frozen" in text and "30 d" in text
    # a quiet app with no recent build is not flagged, and neither is one that never returned a submission
    assert crash_feed.freshness(rec(newest_submission="2026-10-10T10:00:00Z", newest_upload="2026-10-20T08:00:00Z"), NOW)[0] == "ok"
    assert crash_feed.freshness(rec(newest_submission=""), NOW)[0] == "ok"
    assert crash_feed.freshness({"product": "x"}, NOW)[0] == "never"


def test_doctor_warns_on_a_frozen_feed_and_says_nothing_before_any_pull(env, conn, monkeypatch):
    assert crash_feed.doctor_row(NOW) is None
    crash_feed.pull(Fake(routes([crash_item(when="2026-10-01T10:00:00.000Z")])), conn, NOW)
    level, detail, fix = crash_feed.doctor_row(NOW)
    assert level == "WARN" and "may be frozen" in detail and "teyla crash" in fix
    monkeypatch.setattr(crash_feed, "_now", lambda: NOW)
    assert doctor._device_feed_check()["level"] == "WARN"


def test_crash_device_prints_device_crashes_apart_from_mac_panics(env, conn, capsys):
    crash_feed.pull(Fake(routes([crash_item()])), conn, NOW)
    assert cli.main(["crash", "--device", "--days", "3650"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Device crashes") and "recipes" in out and "EXC_BAD_ACCESS" in out and "kernel panic" not in out
    assert "tester@example.com" not in out
    assert cli.main(["crash", "--device", "--days", "3650", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["crashes"][0]["device"] == "iPhone16,2 27.0"


def test_the_default_report_adds_a_device_section_only_when_a_feed_exists(env, conn, capsys):
    cli.main(["crash"])
    assert "Device crashes" not in capsys.readouterr().out
    crash_feed.pull(Fake(routes([crash_item()])), conn, NOW)
    cli.main(["crash", "--days", "3650"])
    assert "Device crashes (TestFlight" in capsys.readouterr().out


def test_pull_in_safe_mode_makes_no_call_and_exits_zero_when_quiet(env, monkeypatch, capsys):
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    monkeypatch.setattr(review_asc, "Client", lambda cfg: (_ for _ in ()).throw(AssertionError("network used")))
    assert cli.main(["crash", "--pull", "--quiet"]) == 0
    quiet = capsys.readouterr()
    assert quiet.out == "" and quiet.err == ""
    assert cli.main(["crash", "--pull"]) == 1
    assert "safe mode" in capsys.readouterr().err


def test_pull_without_a_key_is_quiet_and_exits_zero_under_quiet(env, monkeypatch, capsys):
    monkeypatch.setenv("TEYLA_ASC_DIR", str(env / "none"))
    monkeypatch.delenv("ASC_KEY_ID", raising=False)
    assert cli.main(["crash", "--pull", "--quiet"]) == 0
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""
    assert cli.main(["crash", "--pull"]) == 1


def test_the_cli_pull_runs_the_fake_client_and_prints_counts(env, monkeypatch, capsys):
    monkeypatch.setattr(review_asc, "load_config", lambda *a, **k: {"ASC_KEY_ID": "K", "ASC_ISSUER_ID": "I", "ASC_KEY_PATH": "/x"})
    monkeypatch.setattr(review_asc, "Client", lambda cfg: Fake(routes([crash_item()])))
    assert cli.main(["crash", "--pull"]) == 0
    assert "recipes: 1 new crash(es), 0 new screenshot(s)" in capsys.readouterr().out


# --- the hourly agent -----------------------------------------------------------------------------------

@pytest.fixture
def agent_home(tmp_path, monkeypatch):
    home = tmp_path / "ahome"
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
    loads = []
    monkeypatch.setattr(ri, "_load", lambda plist, label: loads.append(label) or f"loaded {label}")
    monkeypatch.setattr(ri, "_unload", lambda plist, label: f"unloaded {label}")
    monkeypatch.setattr(ri, "loaded", lambda label: (label in loads, None, "0" if label in loads else None))
    monkeypatch.setattr(ri.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("launchctl called")))
    return home, loads


def test_the_feed_agent_is_off_by_default_and_hourly_when_asked(agent_home):
    home, loads = agent_home
    assert not ri.optional_enabled(ri.CRASHFEED_LABEL)
    ri.install()
    assert ri.CRASHFEED_LABEL not in loads and not ri.is_stale()
    assert f"{ri.CRASHFEED_LABEL}: off ([crash] feed_agent = false)" in ri.status()
    config.set_value("crash.feed_agent", "true")
    assert ri.is_stale()
    ri.install()
    p = ri.optional_paths(ri.CRASHFEED_LABEL)
    plist = plistlib.loads(p["plist"].read_bytes())
    assert plist["StartInterval"] == 3600 and plist["Label"] == "com.zaitsew.teyla.crashfeed"
    assert '"$TEYLA" crash --pull --quiet' in p["wrapper"].read_text() and ri.CRASHFEED_LABEL in loads
    assert not ri.is_stale() and ri.every(ri.CRASHFEED_LABEL) == "every 60 min"
    config.set_value("crash.feed_agent", "false")
    ri.install()
    assert not p["plist"].exists() and not p["wrapper"].exists()

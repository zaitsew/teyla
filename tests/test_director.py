"""`teyla digest director`: the weekly director brief. Inputs are stubbed; the only file written is the brief.
No network call, no real ~/.teyla, no launchd."""
from __future__ import annotations

import datetime as dt
import json
import plistlib

import pytest

from teyla import cli, config, digest, director, expiry, routine_install as ri, scoreboard, slots

NOW = dt.datetime(2026, 11, 11, 12, 0, tzinfo=dt.timezone.utc).timestamp()   # ISO week 2026-W46


def metric(value, source="src", **extra):
    return {"value": value, "source": source, **extra}


def missing(reason):
    return {"value": "not_measured", "source": "", "reason": reason}


METRICS = {
    "posts_published": metric(2, "growth ledger"),
    "sale_attempts": metric(3, "growth ledger", breakdown={"posts": 2, "marketing": 1, "icp_meetings": 0}),
    "conversations": missing("no growth ledger yet"),
    "first_value": missing("no focus product"),
    "open_decisions": metric(4, "asks", over_14_days=1, by_age={"0-7": 3, "8-14": 0, "15+": 1},
                             oldest=[{"id": "a1", "product": "alpha", "age_days": 20, "title": "Pick a font"}],
                             design_picks=metric(1, "design cards",
                                                 cards=[{"product": "beta", "decision": "d1", "title": "Onboarding", "age_days": 2}])),
    "builds_to_try": metric(1, "testflight", builds=[{"product": "alpha", "platform": "iOS", "build": "7", "uploaded": "2026-11-10"}]),
}
SLOTS = {"version": 1, "generated": "x", "limit": 2, "in_flight": 3, "over_limit": True, "no_contract": [{"product": "gamma"}],
         "slots": [{"product": p, "age_days": 1, "overdue": False, "waits_at": {"kind": "gate", "text": "gate one"}}
                   for p in ("alpha", "beta", "delta")]}
QUESTIONS = [
    {"id": "q1", "product": "alpha", "age_days": 30, "outcome": "default", "default": "Use option A", "default_source": "stated"},
    {"id": "q2", "product": "beta", "age_days": 20, "outcome": "drop", "default": "", "default_source": "none"},
    {"id": "q3", "product": "beta", "age_days": 16, "outcome": "keep", "default": "", "default_source": "none"},
]


@pytest.fixture(autouse=True)
def machine(tmp_path, monkeypatch):
    monkeypatch.setattr(director, "_now", lambda: NOW)
    monkeypatch.setattr(config, "TEYLA_DIR", tmp_path / "teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "teyla" / "config.toml")
    monkeypatch.setattr(scoreboard, "snapshot", lambda now=None: {"metrics": json.loads(json.dumps(METRICS))})
    monkeypatch.setattr(scoreboard, "hard_dates", lambda today: [{"name": "launch", "date": "2026-12-01", "days_left": 20}])
    monkeypatch.setattr(slots, "snapshot", lambda now=None: json.loads(json.dumps(SLOTS)))
    monkeypatch.setattr(expiry, "candidates", lambda days, product="", now=None: json.loads(json.dumps(QUESTIONS)))

    def no_apply(*a, **k):
        raise AssertionError("expiry.apply was called")
    monkeypatch.setattr(expiry, "apply", no_apply)
    return tmp_path


def run(capsys, *argv):
    assert cli.main(["digest", "director", *argv]) == 0
    return capsys.readouterr().out


def test_default_path_gets_the_brief(capsys, machine):
    out = run(capsys)
    path = machine / "teyla" / "director" / "2026-W46.md"
    assert f"wrote {path}" in out and path.exists()
    assert path.read_text().startswith("# Director brief — 2026-W46 (2026-11-09 to 2026-11-15)")


def test_out_overrides_the_path(capsys, machine):
    target = machine / "elsewhere" / "brief.md"
    run(capsys, "--out", str(target))
    assert target.exists() and not (machine / "teyla" / "director").exists()


def test_every_section_in_order_and_short(capsys):
    text = run(capsys, "--stdout")
    heads = [l for l in text.splitlines() if l.startswith("## ")]
    assert heads == ["## Hard dates", "## Outcomes this week", "## Sprint slots", "## Open decisions", "## Builds to try",
                     "## Questions past 14 days", "## Next two sprints"]
    assert "Nothing here was changed." in text
    assert "- launch: 2026-12-01, 20 days left" in text
    assert "| Conversations | not_measured | no growth ledger yet |" in text
    assert "3 of 2 in flight" in text and "WARN: 3 sprints in flight" in text and "Active without a contract: gamma" in text
    assert "4 waiting on you, 1 older than 14 days." in text and "Design picks waiting: 1" in text
    assert "alpha iOS build 7" in text
    assert "3 open: 1 default, 1 drop, 1 keep" in text and "- q1, alpha, 30d, default, default: Use option A (stated)" in text
    assert "Closing them needs an explicit yes; this brief changes nothing." in text
    assert "1. …" in text and "2. …" in text and "teyla brief <product> --goal" in text
    assert len(text.splitlines()) < 120


def test_no_hard_dates_says_how_to_add_them(capsys, monkeypatch):
    monkeypatch.setattr(scoreboard, "hard_dates", lambda today: [])
    assert "`[dates]` in ~/.teyla/config.toml" in run(capsys, "--stdout")


@pytest.mark.parametrize("target,name", [(scoreboard, "snapshot"), (slots, "snapshot"), (expiry, "candidates"),
                                         (scoreboard, "hard_dates")])
def test_a_raising_input_is_not_measured_and_the_rest_renders(capsys, monkeypatch, target, name):
    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(target, name, boom)
    text = run(capsys, "--stdout")
    assert "not_measured: OSError" in text
    assert text.count("## ") == 7 and "## Next two sprints" in text
    d = director.assemble(NOW)
    assert list(d["errors"].values()) == ["OSError"]


def test_stdout_writes_nothing(capsys, machine):
    run(capsys, "--stdout")
    assert not (machine / "teyla").exists()


def test_json_keys_and_no_file(capsys, machine):
    d = json.loads(run(capsys, "--json"))
    assert set(d) == {"version", "generated", "week", "start", "end", "hard_dates", "outcomes", "slots", "expiry", "errors"}
    assert d["week"] == "2026-W46" and d["errors"] == {} and len(d["expiry"]) == 3
    assert not (machine / "teyla").exists()


def test_quiet_writes_and_prints_nothing(capsys, machine):
    assert run(capsys, "--quiet") == ""
    assert (machine / "teyla" / "director" / "2026-W46.md").exists()


def test_plain_digest_is_unchanged(capsys, machine):
    assert cli.main(["digest"]) == 1
    assert "no digest yet" in capsys.readouterr().out
    digest.digest_path().parent.mkdir(parents=True, exist_ok=True)
    digest.digest_path().write_text("teyla weekly: nothing needs you this week.\n")
    assert cli.main(["digest"]) == 0
    assert "nothing needs you" in capsys.readouterr().out
    assert not (machine / "teyla" / "director").exists()


# --- the Monday routine ---------------------------------------------------------------------------------

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


def test_the_director_agent_is_off_by_default_and_runs_mondays_0730(agent_home):
    home, loads = agent_home
    label = ri.DIRECTOR_LABEL
    p = ri.optional_paths(label)
    assert not ri.optional_enabled(label)
    ri.install()
    assert label not in loads and not p["plist"].exists() and not ri.is_stale()
    assert f"{label}: off ([digest] director = false)" in ri.status()
    config.set_value("digest.director", "true")
    assert ri.is_stale()
    ri.install()
    plist = plistlib.loads(p["plist"].read_bytes())
    assert plist["StartCalendarInterval"] == {"Weekday": 1, "Hour": 7, "Minute": 30}
    assert '"$TEYLA" digest director --quiet' in p["wrapper"].read_text() and label in loads
    assert not ri.is_stale() and ri.every(label) == "Mondays at 07:30"
    # the daily-calendar agent keeps its plist without a Weekday key
    config.set_value("growth.daily", "true")
    ri.install()
    growth = plistlib.loads(ri.optional_paths(ri.GROWTH_LABEL)["plist"].read_bytes())
    assert growth["StartCalendarInterval"] == {"Hour": 6, "Minute": 30} and ri.every(ri.GROWTH_LABEL) == "daily at 06:30"
    config.set_value("digest.director", "false")
    config.set_value("growth.daily", "false")
    ri.install()
    assert not p["plist"].exists() and not p["wrapper"].exists()

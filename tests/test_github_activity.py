"""GitHub's contribution calendar as an activity graph: parsing, the window, the cache, and the relay's glimpse."""
from __future__ import annotations

import json

import pytest

from teyla import config, github_activity as ga, relay


def answer(days: list[tuple[str, int, str]]) -> str:
    weeks = [{"contributionDays": [{"date": d, "contributionCount": c, "contributionLevel": lvl} for d, c, lvl in days]}]
    return json.dumps({"data": {"viewer": {"login": "someone", "contributionsCollection": {
        "contributionCalendar": {"weeks": weeks}}}}})


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path))
    monkeypatch.delenv(config.SAFE_ENV, raising=False)
    return tmp_path


def test_parse_maps_levels_and_drops_damaged_days():
    out = answer([("2026-11-11", 12, "FOURTH_QUARTILE"), ("2026-11-10", 0, "NONE"), ("2026-11-12", 3, "WHAT")])
    days = ga.parse(out)
    assert days == [{"day": "2026-11-10", "count": 0, "level": 0}, {"day": "2026-11-11", "count": 12, "level": 4},
                    {"day": "2026-11-12", "count": 3, "level": 0}]
    assert ga.parse("not json") is None
    assert ga.parse(json.dumps({"data": {}})) is None


def test_fetch_asks_for_the_window_from_its_first_monday():
    seen = []

    def runner(cmd):
        seen.append(cmd)
        return 0, answer([("2026-11-12", 1, "FIRST_QUARTILE")]), ""

    assert ga.fetch("2026-11-12", 2, runner) == [{"day": "2026-11-12", "count": 1, "level": 1}]
    cmd = seen[0]
    assert cmd[:3] == ["gh", "api", "graphql"]
    assert "from=2026-11-02T00:00:00Z" in cmd and "to=2026-11-12T23:59:59Z" in cmd
    assert ga.fetch("2026-11-12", 2, lambda c: (1, "", "auth")) is None


def test_graph_fills_the_window_and_counts_today_and_the_streak():
    rows = [{"day": "2026-11-10", "count": 5, "level": 2}, {"day": "2026-11-11", "count": 7, "level": 3}]
    g = ga.graph(rows, "2026-11-12", 2, at=100)
    assert g["source"] == "github" and g["start"] == "2026-11-02" and len(g["days"]) == 11
    assert g["today_count"] == 0 and g["streak"] == 2 and g["longest"] == 2 and g["total"] == 12
    assert g["week_count"] == 12 and g["at"] == 100


def test_the_cache_serves_within_ten_minutes_and_refetches_after(home):
    calls = []

    def runner(cmd):
        calls.append(cmd)
        return 0, answer([("2026-11-12", len(calls), "FIRST_QUARTILE")]), ""

    a = ga.activity("2026-11-12", 2, now=1000, runner=runner)
    b = ga.activity("2026-11-12", 2, now=1000 + ga.CACHE_S - 1, runner=runner)
    assert len(calls) == 1 and a["today_count"] == b["today_count"] == 1
    c = ga.activity("2026-11-12", 2, now=1000 + ga.CACHE_S + 1, runner=runner)
    assert len(calls) == 2 and c["today_count"] == 2
    assert (home / "github-activity.json").exists()


def test_a_failed_call_keeps_the_last_cache_and_nothing_means_none(home):
    assert ga.activity("2026-11-12", 2, now=0, runner=lambda c: (1, "", "")) is None
    ga.activity("2026-11-12", 2, now=0, runner=lambda c: (0, answer([("2026-11-12", 4, "SECOND_QUARTILE")]), ""))
    g = ga.activity("2026-11-12", 2, now=10_000, runner=lambda c: (1, "", "down"))
    assert g["today_count"] == 4 and g["at"] == 0


def test_safe_mode_never_calls_and_serves_the_cache(monkeypatch):
    monkeypatch.setenv(config.SAFE_ENV, "1")

    def runner(cmd):
        raise AssertionError("no call in safe mode")

    assert ga.activity("2026-11-12", 2, now=0, runner=runner) is None


def test_a_new_day_refetches_even_inside_the_ten_minutes():
    calls = []

    def runner(cmd):
        calls.append(cmd)
        return 0, answer([("2026-11-12", 1, "FIRST_QUARTILE"), ("2026-11-13", 2, "FIRST_QUARTILE")]), ""

    ga.activity("2026-11-12", 2, now=0, runner=runner)
    g = ga.activity("2026-11-13", 2, now=60, runner=runner)
    assert len(calls) == 2 and g["today_count"] == 2


def test_relay_github_view_is_counts_only():
    g = ga.graph([{"day": "2026-11-12", "count": 9, "level": 4}], "2026-11-12", relay.ACTIVITY_WEEKS, at=5)
    view = relay.github_view("2026-11-12", 0, source=lambda today, weeks, now: g)
    assert view["today_count"] == 9 and view["at"] == 5
    assert set(view["days"][0]) == {"day", "count", "level"}
    assert len(view["days"]) <= 7 * relay.ACTIVITY_WEEKS
    assert relay.github_view("2026-11-12", 0, source=lambda *a: None) is None

    def boom(*a):
        raise RuntimeError("x")

    assert relay.github_view("2026-11-12", 0, source=boom) is None


def test_a_53_week_window_asks_for_one_year_at_most_and_the_cache_then_serves():
    seen = []

    def runner(cmd):
        seen.append(cmd)
        return 0, answer([("2026-11-12", 2, "FIRST_QUARTILE")]), ""

    g = ga.activity("2026-11-12", 53, now=0, runner=runner)
    assert "from=2025-11-13T00:00:00Z" in seen[0]
    assert g["start"] == "2025-11-10" and g["days"][0]["count"] == 0 and g["today_count"] == 2
    ga.activity("2026-11-12", 53, now=60, runner=runner)
    assert len(seen) == 1

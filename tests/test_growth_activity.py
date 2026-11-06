"""`teyla growth activity` and the +1 kinds of `teyla growth log`. Pure functions on ledger rows with a fixed today;
the CLI tests run in a tmp TEYLA_HOME."""
from __future__ import annotations

import datetime as dt
import json
import time

import pytest

from teyla import cli, growth
from tests.test_growth import env  # noqa: F401  (the tmp TEYLA_HOME fixture with invented products)

TODAY = "2026-11-04"          # a Wednesday


def row(day, kind="comment", ev="attempt", **kw):
    return {"ev": ev, "day": day, "kind": kind, **kw}


def test_the_kinds_and_the_attempt_mapping():
    assert growth.ACTIVITY_KINDS == ("post", "comment", "reply", "email", "dm", "call", "meeting", "icp-meeting",
                                     "ad", "outreach", "response")
    want = {"post": "post", "ad": "marketing", "outreach": "marketing", "comment": "marketing", "reply": "marketing",
            "email": "marketing", "dm": "marketing", "call": "marketing", "meeting": "marketing",
            "icp-meeting": "icp", "response": None}
    for kind, expect in want.items():
        assert growth.attempt_kind(row(TODAY, kind)) == expect, kind
    assert growth.attempt_kind({"ev": "published", "day": TODAY}) == "post"


def test_tally_adds_n_and_skips_rows_without_a_product():
    rows = [row(TODAY, "email", product="alpha", n=3), row(TODAY, "email", product="alpha"),
            row(TODAY, "comment"), row(TODAY, "response", product="alpha"),
            row(TODAY, "dm", product="alpha", n=2, by="agent")]
    t = growth.tally(rows, ["alpha"])["alpha"]
    assert t["marketing"] == 4 and t["claimed"] == 2 and t["posts"] == 0


def test_activity_counts_published_and_attempts_but_not_claims_or_responses():
    rows = [{"ev": "published", "day": TODAY}, row(TODAY, "comment", n=2), row(TODAY, "response"),
            row(TODAY, "meeting", by="agent"), row("2026-11-03", "call"), row("2026-11-02", "icp-meeting"),
            {"ev": "draft", "day": TODAY}, row("2000-01-01", "post"), row("2026-11-05", "post")]
    a = growth.activity(rows, TODAY, 2)
    assert a["total"] == 5 and a["today_count"] == 3 and a["claimed"] == 1
    assert a["by_kind"] == {"post": 1, "comment": 2, "call": 1, "icp-meeting": 1}
    assert a["outcomes"] == {"meetings": 2, "responses": 1}
    assert a["days"][-1] == {"day": TODAY, "count": 3, "level": a["days"][-1]["level"], "kinds": {"post": 1, "comment": 2}}


def test_window_is_iso_weeks_ending_today():
    a = growth.activity([], TODAY, 3)
    assert a["start"] == "2026-10-19" and a["days"][0]["day"] == "2026-10-19" and a["days"][-1]["day"] == TODAY
    assert len(a["days"]) == 17 and a["weeks"] == 3 and a["version"] == 1
    assert growth.activity([], TODAY, 1)["start"] == "2026-11-02"


def test_levels_by_quartile_and_streaks():
    counts = [1, 2, 3, 4, 5, 6, 7, 8]
    assert growth.activity_levels(counts) == {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4}
    assert growth.activity_levels([2, 2, 2]) == {2: 1}
    assert growth.activity_levels([1, 5]) == {1: 1, 5: 3}
    assert growth.activity_levels([0]) == {}
    # streak: today empty, yesterday and the day before count; longest is an earlier run of 3.
    days = ["2026-10-20", "2026-10-21", "2026-10-22", "2026-11-02", "2026-11-03"]
    a = growth.activity([row(d) for d in days], TODAY, 3)
    assert a["streak"] == 2 and a["longest"] == 3 and a["week_count"] == 2
    a = growth.activity([row(d) for d in days] + [row(TODAY)], TODAY, 3)
    assert a["streak"] == 3
    assert all(x["level"] == 0 for x in a["days"] if not x["count"])
    assert growth.activity([row("2026-11-01")], TODAY, 3)["streak"] == 0


def test_json_contract_keys():
    a = growth.activity([row(TODAY)], TODAY, 2)
    assert list(a) == ["version", "today", "weeks", "start", "days", "total", "today_count", "week_count", "streak",
                       "longest", "by_kind", "outcomes", "claimed", "kinds"]
    assert set(a["days"][0]) == {"day", "count", "level", "kinds"} and a["kinds"] == list(growth.ACTIVITY_KINDS)


def test_render_fits_and_has_the_parts():
    a = growth.activity([row(TODAY, "post"), row("2026-11-03", "comment", n=4), row(TODAY, "response")], TODAY, 53)
    text = growth.render_activity(a)
    lines = text.splitlines()
    assert lines[0] == "activity: 5 in the last 53 weeks · today 1 · streak 2 days (longest 2)"
    assert [l[:3] for l in lines[2:9]] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert max(len(l) for l in lines[:9]) <= 100
    assert "by kind: post 1, comment 4" in text and "outcomes: meetings held 0 · responses 1" in text
    assert "not counted" not in text
    assert "not counted" in growth.render_activity(growth.activity([row(TODAY, by="agent")], TODAY, 2))


def log(*argv):
    return cli.main(["growth", "log", *argv])


def test_log_accepts_new_kinds_optional_product_count_and_day(env, capsys):  # noqa: F811
    assert log("--kind", "comment") == 0
    assert log("--kind", "email", "--product", "alpha", "--count", "3") == 0
    yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    assert log("--kind", "dm", "--day", yesterday) == 0
    rows = growth.Store().ledger()
    assert [r["kind"] for r in rows] == ["comment", "email", "dm"]
    assert "product" not in rows[0] and "n" not in rows[0] and rows[1]["n"] == 3 and rows[1]["product"] == "alpha"
    assert rows[2]["day"] == yesterday
    assert growth.attempt_rows(growth.Store())["alpha"]["marketing"] == 3
    capsys.readouterr()
    assert log("--kind", "comment", "--product", "alhpa") == 2
    assert "did you mean alpha" in capsys.readouterr().err


@pytest.mark.parametrize("count", ["0", "51", "-1"])
def test_log_refuses_a_count_out_of_range(env, count, capsys):  # noqa: F811
    assert log("--kind", "post", "--count", count) == 2
    assert "--count" in capsys.readouterr().err and growth.Store().ledger() == []


def test_log_day_bounds(env, capsys):  # noqa: F811
    today = dt.date.today()
    oldest = (today - dt.timedelta(days=7)).isoformat()
    assert log("--kind", "post", "--day", oldest) == 0
    assert growth.Store().ledger()[-1]["day"] == oldest
    for bad in ((today + dt.timedelta(days=1)).isoformat(), (today - dt.timedelta(days=8)).isoformat(), "yesterday"):
        assert log("--kind", "post", "--day", bad) == 2, bad
        assert "--day" in capsys.readouterr().err
    assert len(growth.Store().ledger()) == 1


def test_log_from_an_agent_session_is_a_claim(env, monkeypatch, capsys):  # noqa: F811
    from teyla import startup
    monkeypatch.setattr(startup, "in_agent_session", lambda: True)
    assert log("--kind", "comment") == 0
    assert growth.Store().ledger()[0]["by"] == "agent"
    assert "claimed" in capsys.readouterr().out


def test_activity_command_text_and_json(env, capsys):  # noqa: F811
    assert log("--kind", "meeting", "--count", "2") == 0
    capsys.readouterr()
    assert cli.main(["growth", "activity", "--json", "--weeks", "4"]) == 0
    a = json.loads(capsys.readouterr().out)
    assert a["weeks"] == 4 and a["total"] == 2 and a["outcomes"]["meetings"] == 2 and a["today_count"] == 2
    assert cli.main(["growth", "activity"]) == 0
    assert capsys.readouterr().out.startswith("activity: 2 in the last 53 weeks")
    assert cli.main(["growth", "activity", "--weeks", "54"]) == 2

"""Spend control that acts: config thresholds, budgets, the alert file and its dedupe, the banner
line, advice A20 and `teyla spend --by-day`. All data is invented; time is pinned to UTC."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import subprocess
import time
from collections import Counter

import pytest

from teyla import config, monitor, pricing, spend
from teyla.adapters import AgentCall, Session, claude_code
from teyla.advise import advise

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "session-start.sh"
UTC = _dt.timezone.utc


@pytest.fixture(autouse=True)
def _utc_and_list_prices(monkeypatch, tmp_path):
    old_tz = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", tmp_path / "no-prices.json")
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    yield home
    if old_tz is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old_tz
    time.tzset()


def _row(**kw):
    r = dict(harness="claude-code", sid="abcdef123456", project="demo", cwd="/nowhere", first="2026-10-07T10:00:00Z",
             last="2026-10-07T12:00:00Z", usd=0.0, by_model={}, sub_usd=0.0, top_tier_sub_saving=0.0,
             reread_usd=0.0, loop_usd=0.0, inherited_agents=0, agents=0, prs=0, batch=False, repos=[],
             day_usd={}, day_model_usd={}, sub_day_model_usd={}, sub_calls=[])
    r.update(kw)
    return r


def _day_row(sid, project, day, usd, model="claude-fable-5-1"):
    return _row(sid=sid, project=project, usd=usd, day_usd={day: usd}, day_model_usd={day: {model: usd}})


NOW = _dt.datetime(2026, 10, 8, 7, 0, tzinfo=UTC)  # yesterday is 2026-10-07


# --- config instead of constants ---------------------------------------------------------------

def test_defaults_are_the_old_constants():
    assert spend.setting("alert_session_usd") == 250.0 and spend.setting("w1_usd") == 15.0
    assert spend.budgets() == (0.0, {})


def test_config_overrides_thresholds_and_budgets(_utc_and_list_prices):
    for kv in ("spend.alert_session_usd=100", "spend.w1_usd=5", "spend.daily_budget_usd=300",
               "spend.budget.alpha=40", "spend.budget.my.app=12.5"):
        k, v = kv.split("=")
        assert config.set_value(k, v).startswith("set ")
    cfg = config.load()
    assert spend.setting("alert_session_usd", cfg) == 100.0 and spend.setting("w1_usd", cfg) == 5.0
    assert spend.budgets(cfg) == (300.0, {"alpha": 40.0, "my.app": 12.5})
    # a threshold the owner set is the one the rules use
    rows = [_row(usd=120.0)]
    assert spend.alerts(rows, None, now=NOW, cfg=cfg) == ["session demo abcdef12 2026-10-07 cost $120 (claude-code)"]
    assert spend.alerts(rows, None, now=NOW, cfg=config.load(pathlib.Path("/nonexistent.toml"))) == []
    assert [f["id"] for f in spend.findings([_row(usd=8.0)], outcome_of=lambda r: False)] == ["W1"]
    # it is a number or nothing; a typo does not silently turn a check off
    assert "invalid" in config.set_value("spend.alert_session_usd", "lots")


def test_budget_table_form_and_bad_values(_utc_and_list_prices):
    config.CONFIG_PATH.write_text('[spend]\ndaily_budget_usd = "x"\n[spend.budget]\nalpha = 40\nbeta = -3\n')
    assert spend.budgets() == (0.0, {"alpha": 40.0})
    assert config.set_value("spend.alert_session_usd", "90").startswith("set ")  # the table survives a rewrite
    assert spend.budgets()[1] == {"alpha": 40.0}


# --- budget alerts -----------------------------------------------------------------------------

def _budget_rows():
    return [_day_row("s1aaaaaaaaaa", "alpha", "2026-10-07", 60.0),
            _day_row("s2bbbbbbbbbb", "alpha", "2026-10-07", 30.0, model="claude-sonnet-5-5"),
            _day_row("s3cccccccccc", "alpha", "2026-10-07", 20.0),
            _day_row("s4dddddddddd", "alpha", "2026-10-07", 5.0),
            _day_row("s5eeeeeeeeee", "beta", "2026-10-07", 70.0),
            _day_row("s6ffffffffff", "beta", "2026-10-08", 200.0)]  # today: not yesterday's


def test_project_budget_alert_names_amount_budget_top_sessions_and_model():
    cfg = {"spend": {"budget.alpha": 100, "budget.beta": 100}}
    out = spend.alert_items(_budget_rows(), None, now=NOW, cfg=cfg)
    assert [a["key"] for a in out] == ["budget:alpha:2026-10-07"]  # beta's $70 is under, today's $200 is not counted
    text = out[0]["text"]
    assert "project alpha" in text and "$115" in text and "$100 a day" in text and "2026-10-07" in text
    assert "s1aaaaaa $60, s2bbbbbb $30, s3cccccc $20" in text and "s4dddddd" not in text  # top 3 only
    assert "top model claude-fable-5-1 $85" in text
    assert out[0]["usd"] == 115.0


def test_total_budget_alert_names_projects_sessions_and_model():
    out = spend.alert_items(_budget_rows(), None, now=NOW, cfg={"spend": {"daily_budget_usd": 150}})
    assert len(out) == 1 and out[0]["key"] == "budget:*:2026-10-07"
    text = out[0]["text"]
    assert "all projects cost $185" in text and "over its $150 a day" in text
    assert "beta $70" in text and "alpha $115" in text
    assert "s5eeeeee $70" in text and "top model claude-fable-5-1" in text
    assert spend.alert_items(_budget_rows(), None, now=NOW, cfg={"spend": {"daily_budget_usd": 200}}) == []
    assert spend.alert_items(_budget_rows(), None, now=NOW, cfg={"spend": {}}) == []  # unset = off


def test_yesterday_is_the_local_calendar_day(monkeypatch):
    monkeypatch.setenv("TZ", "Etc/GMT-9")  # UTC+9: 2026-10-07 22:00Z is already the 8th locally
    time.tzset()
    now = _dt.datetime(2026, 10, 8, 23, 0, tzinfo=UTC)  # 2026-10-09 08:00 local: yesterday = the 8th
    rows = [_day_row("sxxxxxxxxxxx", "alpha", "2026-10-08", 90.0), _day_row("syyyyyyyyyyy", "alpha", "2026-10-07", 900.0)]
    out = spend.alert_items(rows, None, now=now, cfg={"spend": {"budget.alpha": 50}})
    assert len(out) == 1 and "$90 on 2026-10-08" in out[0]["text"]


# --- the same alert is not said twice ----------------------------------------------------------

def _a(usd, key="session:claude-code:abc"):
    return dict(key=key, usd=usd, text=f"session abc cost ${usd:.0f}")


def test_dedupe_quiet_next_day_unless_it_grew_a_quarter():
    d1, d2, d3 = _dt.date(2026, 10, 1), _dt.date(2026, 10, 2), _dt.date(2026, 10, 3)
    new, shown, st = spend.dedupe([_a(300)], d1)
    assert len(new) == 1 and len(shown) == 1
    # the next day, same session: nothing
    new, shown, st2 = spend.dedupe([_a(300)], d2, st)
    assert new == [] and shown == []
    # +24% of what was reported: still nothing; +25%: reported again, and the new amount is the baseline
    assert spend.dedupe([_a(372)], d2, st)[0] == []
    new, shown, st3 = spend.dedupe([_a(375)], d2, st)
    assert len(new) == 1 and st3["session:claude-code:abc"]["usd"] == 375
    # a quiet day does not break the streak: day 3 is still the same alert
    assert spend.dedupe([_a(310)], d3, st2)[0] == []
    # but not forever: after a day on which it was not true, it is news again
    new, _, _ = spend.dedupe([_a(300)], _dt.date(2026, 10, 6), st2)
    assert len(new) == 1


def test_dedupe_same_day_rerun_keeps_showing_but_does_not_renotify():
    d = _dt.date(2026, 10, 1)
    _, _, st = spend.dedupe([_a(300)], d)
    new, shown, _ = spend.dedupe([_a(310)], d, st)
    assert new == [] and [a["usd"] for a in shown] == [310]


def test_dedupe_forgets_old_keys():
    _, _, st = spend.dedupe([_a(300)], _dt.date(2026, 9, 1))
    _, _, st = spend.dedupe([], _dt.date(2026, 10, 1), st)
    assert st == {}


# --- the alert file ----------------------------------------------------------------------------

def test_alert_file_is_written_overwritten_and_removed(_utc_and_list_prices, capsys):
    f = spend.alerts_path()
    assert f == config.TEYLA_DIR / "spend.alert"
    d1, d2 = _dt.date(2026, 10, 1), _dt.date(2026, 10, 2)
    (config.TEYLA_DIR / "spend.alerts").write_text("2026-09-30\told format\n")
    new = spend.run_alert([_a(300), _a(80, key="budget:x:y")], d1)
    assert len(new) == 2 and f.read_text() == "session abc cost $300\nsession abc cost $80\n"
    assert not (config.TEYLA_DIR / "spend.alerts").exists()
    assert (f.stat().st_mode & 0o077) == 0
    state = json.loads(spend.state_path().read_text())
    assert spend.state_path().parent == config.TEYLA_DIR / "state" and "session:claude-code:abc" in state
    # tomorrow the same session is quiet: the file goes away, it is not left stale
    spend.run_alert([_a(300)], d2)
    assert not f.exists()
    # --no-write prints and touches nothing
    capsys.readouterr()
    spend.run_alert([_a(500, key="other")], d2, write=False)
    assert "teyla spend alert: session abc cost $500" in capsys.readouterr().out
    assert not f.exists() and "other" not in json.loads(spend.state_path().read_text())


def test_cmd_alert_end_to_end_with_no_write(monkeypatch, capsys):
    monkeypatch.setattr(spend, "session_rows", lambda days: [_row(usd=400.0, last=_dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))])
    monkeypatch.setattr(spend, "actions_usage", lambda: None)
    from teyla import providers
    monkeypatch.setattr(providers, "read", lambda days: {})
    notified = []
    monkeypatch.setattr(spend, "notify", lambda lines: notified.append(lines) or True)
    ns = argparse.Namespace(alert=True, by_day=False, no_write=True, no_notify=False)
    assert spend.cmd_spend(ns) == 0
    assert "cost $400" in capsys.readouterr().out and not spend.alerts_path().exists() and notified == []
    ns.no_write = False
    spend.cmd_spend(ns)
    assert "cost $400" in spend.alerts_path().read_text() and len(notified) == 1


# --- the session-start banner ------------------------------------------------------------------

def _hook(home, cwd):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["sh", str(HOOK)], cwd=cwd, env=env, capture_output=True, text=True, timeout=5)


def test_banner_shows_the_first_alert_line_and_a_count(_utc_and_list_prices, tmp_path):
    home = _utc_and_list_prices
    assert _hook(home, tmp_path).stdout == ""
    spend.alerts_path().write_text("budget: project alpha cost $115 on 2026-10-07, over its $100 a day\nsession demo abc cost $300\n")
    out = _hook(home, tmp_path).stdout
    assert out == "teyla: spend alert — budget: project alpha cost $115 on 2026-10-07, over its $100 a day (+1 more)\n"
    spend.alerts_path().write_text("session demo abc cost $300\n")
    assert _hook(home, tmp_path).stdout == "teyla: spend alert — session demo abc cost $300\n"
    # the line is not "new once": it stays until the daily run removes the file
    assert _hook(home, tmp_path).stdout.count("\n") == 1
    spend.alerts_path().unlink()
    assert _hook(home, tmp_path).stdout == ""


def test_banner_ignores_an_alert_file_the_daily_job_stopped_refreshing(_utc_and_list_prices, tmp_path):
    spend.alerts_path().write_text("session demo abc cost $300\n")
    old = time.time() - 3 * 86400
    os.utime(spend.alerts_path(), (old, old))
    assert _hook(_utc_and_list_prices, tmp_path).stdout == ""


# --- A20 ---------------------------------------------------------------------------------------

def _agent_session(sid, project="demo", explicit=0, inherited=0, model="claude-fable-5-1", sub_model=None, sub_out=0):
    s = Session(harness="claude-code", project=project, sid=sid, path=f"/tmp/{sid}.jsonl", size=1000)
    s.first, s.last, s.cwd = "2026-10-07T10:00:00Z", "2026-10-07T11:00:00Z", f"/Users/me/repos/{project}"
    s.usage["claude-fable-5-1"] = Counter(input_tokens=10, output_tokens=10)
    for _ in range(explicit):
        s.agents.append(AgentCall(model, "general-purpose", "work"))
    for _ in range(inherited):
        s.agents.append(AgentCall(None, "general-purpose", "work"))
    if sub_model:
        s.sub_usage[sub_model] = Counter(output_tokens=sub_out)
    return s


def _a20(sessions):
    return [f for f in advise(monitor.metrics(sessions)) if f["id"] == "A20"]


def test_a20_fires_on_explicit_top_tier_calls_with_the_number():
    s = _agent_session("s1", explicit=5, inherited=7, sub_model="claude-fable-5-1", sub_out=1_000_000)
    s2 = _agent_session("s2", explicit=0, inherited=0, sub_model="claude-sonnet-5-5", sub_out=1_000_000)
    F = _a20([s, s2])
    assert len(F) == 1 and F[0]["id"] == "A20"
    ev = F[0]["evidence"]
    assert "5 of 12 subagent calls" in ev and "42%" in ev and "threshold 30%" in ev
    assert "83%" in ev and "$50 of $60" in ev  # the top tier ran $50 of the project's $60 subagent cost
    assert "claude-fable-5-1×5" in ev
    assert "volume tier" in F[0]["action"] and "review and design" in F[0]["action"]


def test_a20_thresholds_and_inherited_models():
    assert _a20([_agent_session("s", explicit=3, inherited=7)]) == []      # 30% is not more than 30%
    assert len(_a20([_agent_session("s", explicit=4, inherited=7)])) == 1  # 4 of 11
    assert _a20([_agent_session("s", explicit=5, inherited=4)]) == []      # 9 calls: under the minimum
    assert _a20([_agent_session("s", inherited=20)]) == []                 # inheriting is A1's business, not A20's
    assert _a20([_agent_session("s", explicit=20, model="sonnet")]) == []  # an explicit mid tier is what we want
    assert _a20([_agent_session("s", explicit=20, model="haiku")]) == []
    assert len(_a20([_agent_session("s", explicit=20, model="fable")])) == 1  # an alias resolves too
    assert len(_a20([_agent_session("s", explicit=20, model="claude-fable-5-1-20260101")])) == 1


def test_a20_is_counted_per_project_and_summed_across_sessions():
    sessions = [_agent_session(f"a{i}", "alpha", explicit=1, inherited=1) for i in range(6)] + \
               [_agent_session(f"b{i}", "beta", inherited=2) for i in range(6)]
    F = _a20(sessions)
    assert len(F) == 1 and "alpha" in F[0]["title"] and "6 of 12" in F[0]["evidence"]  # beta's 12 inherited calls dilute nothing


def test_a20_threshold_and_extra_models_come_from_config(_utc_and_list_prices):
    s = _agent_session("s", explicit=3, inherited=7)
    assert _a20([s]) == []
    config.set_value("spend.a20_share", "0.2")
    assert len(_a20([s])) == 1
    config.set_value("spend.a20_share", None); config.set_value("spend.a20_min_calls", "20")
    assert _a20([_agent_session("s", explicit=10, inherited=2)]) == []
    config.set_value("spend.a20_min_calls", None)
    # an alias the owner counts as top tier whatever the price table says
    opus = _agent_session("s", explicit=12, model="opus")
    assert _a20([opus]) == []
    config.set_value("spend.a20_models", "opus")
    assert len(_a20([opus])) == 1


def test_top_tier_resolution_and_the_no_ladder_fallback(monkeypatch):
    assert pricing.is_top_tier("fable") and pricing.is_top_tier("gpt-6-astra")
    assert not pricing.is_top_tier("sonnet[1m]") and not pricing.is_top_tier(None) and not pricing.is_top_tier("nonsense")
    assert pricing.explicit_tier("opus") == "volume" and pricing.explicit_tier("fable") == "orchestrate"
    # a provider with no orchestrate row has no ladder: its most expensive family is the top
    table = {"acme-big": (5, 5, 1, 30, "volume", False), "acme-small": (1, 1, 0.1, 5, "triage", False)}
    monkeypatch.setattr(pricing, "effective_prices", lambda: table)
    assert pricing.is_top_tier("acme-big") and not pricing.is_top_tier("acme-small")


def test_redact_keeps_a20_but_hides_the_project():
    m = monitor.metrics([_agent_session("s", "secret-project", explicit=12)])
    r = monitor.redact(m)
    assert "secret-project" not in json.dumps(r) and [f["id"] for f in advise(r)].count("A20") == 1
    assert any("p01" in f["title"] for f in advise(r) if f["id"] == "A20")


# --- per-day cost from the transcripts, and --by-day ---------------------------------------------

def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _reply(ts, mid, out, model):
    return {"type": "assistant", "timestamp": ts, "message": {
        "id": mid, "role": "assistant", "model": model, "usage": {"input_tokens": 0, "output_tokens": out},
        "content": [{"type": "text", "text": "ok"}]}}


def _fixture(tmp_path):
    root = tmp_path / "projects"
    d = root / "-Users-me-repos-alpha"
    _write(str(d / "s1.jsonl"), [
        {"type": "user", "timestamp": "2026-10-06T12:00:00Z", "cwd": "/Users/me/repos/alpha",
         "message": {"role": "user", "content": "go"}},
        _reply("2026-10-06T12:01:00Z", "m1", 1_000_000, "claude-fable-5-1"),   # $50 on the 6th
        _reply("2026-10-07T00:30:00Z", "m2", 200_000, "claude-fable-5-1"),     # $10 on the 7th: past midnight
    ])
    _write(str(d / "s1" / "subagents" / "agent-a.jsonl"), [
        _reply("2026-10-07T09:00:00Z", "a1", 1_000_000, "claude-sonnet-5-5"),  # $10 volume
    ])
    _write(str(d / "s1" / "subagents" / "agent-b.jsonl"), [
        _reply("2026-10-07T09:05:00Z", "b1", 100_000, "claude-fable-5-1"),     # $5 orchestrate
    ])
    _write(str(d / "s1" / "subagents" / "agent-c.jsonl"), [
        _reply("2026-10-07T09:06:00Z", "c1", 100_000, "claude-sonnet-5-5"),    # $1 volume, a second call
        _reply("2026-10-07T09:07:00Z", "c2", 100_000, "claude-haiku-4-5"),     # $0.5 triage, same file
    ])
    _write(str(root / "-Users-me-repos-beta" / "s2.jsonl"), [
        {"type": "user", "timestamp": "2026-10-07T15:00:00Z", "cwd": "/Users/me/repos/beta",
         "message": {"role": "user", "content": "go"}},
        _reply("2026-10-07T15:01:00Z", "m3", 100_000, "claude-opus-5-5"),      # $2 on the 7th
    ])
    return str(root)


def test_adapter_splits_cost_by_the_day_each_message_was_sent(tmp_path):
    s = next(s for s in claude_code.load(root=_fixture(tmp_path)) if s.sid == "s1")
    assert s.day_usage["2026-10-06"]["claude-fable-5-1"]["output_tokens"] == 1_000_000
    assert s.day_usage["2026-10-07"]["claude-fable-5-1"]["output_tokens"] == 300_000  # 200k + the subagent's 100k
    assert set(s.sub_day_usage) == {"2026-10-07"}
    assert sorted(s.sub_calls) == [("2026-10-07", "claude-fable-5-1"), ("2026-10-07", "claude-sonnet-5-5"),
                                   ("2026-10-07", "claude-sonnet-5-5")]
    assert s.to_dict()["day_usage"]["2026-10-06"]["claude-fable-5-1"]["output_tokens"] == 1_000_000


def test_by_day_aggregates_total_subagent_cost_and_calls_by_tier(tmp_path):
    rows = spend.session_rows(3650, sessions=claude_code.load(root=_fixture(tmp_path)), grok_rows=[])
    out = {r["day"]: r for r in spend.by_day(3, rows, today=_dt.date(2026, 10, 8))}
    assert list(out) == ["2026-10-06", "2026-10-07", "2026-10-08"]
    assert out["2026-10-06"]["total_usd"] == 50.0 and out["2026-10-06"]["sub_usd"] == 0.0
    assert out["2026-10-06"]["top_share"] is None
    d7 = out["2026-10-07"]
    assert d7["total_usd"] == 10 + 10 + 5 + 1 + 0.5 + 2   # main + three subagent files + the other project
    assert d7["sub_usd"] == 16.5
    assert d7["tiers"]["orchestrate"] == dict(usd=5.0, calls=1)
    assert d7["tiers"]["volume"] == dict(usd=11.0, calls=2)
    assert d7["tiers"]["triage"] == dict(usd=0.5, calls=0)  # its cost counts; the call was booked on the model that wrote most of its file
    assert d7["top_share"] == round(5 / 16.5, 3) and d7["sessions"] == 2
    assert out["2026-10-08"]["total_usd"] == 0.0


def test_by_day_books_a_model_without_a_price_as_unknown_and_grok_by_its_day():
    row = _row(day_usd={"2026-10-07": 3.0}, sub_day_model_usd={"2026-10-07": {"mystery-model": 3.0}},
               sub_calls=[("2026-10-07", "mystery-model")])
    grok = _row(sid="g", harness="grok", day_usd={"2026-10-07": 7.0})
    d = spend.by_day(1, [row, grok], today=_dt.date(2026, 10, 7))[0]
    assert d["total_usd"] == 10.0 and d["tiers"]["unknown"] == dict(usd=3.0, calls=1)


def test_by_day_cli_json_and_table(monkeypatch, capsys, tmp_path):
    rows = spend.session_rows(3650, sessions=claude_code.load(root=_fixture(tmp_path)), grok_rows=[])
    monkeypatch.setattr(spend, "session_rows", lambda days: rows)
    monkeypatch.setattr(spend._dt, "date", type("D", (_dt.date,), {"today": classmethod(lambda c: _dt.date(2026, 10, 8))}))
    ns = argparse.Namespace(alert=False, by_day=True, days=3, json=True)
    assert spend.cmd_spend(ns) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["days"] == 3 and [r["day"] for r in data["rows"]] == ["2026-10-06", "2026-10-07", "2026-10-08"]
    ns.json = False
    spend.cmd_spend(ns)
    out = capsys.readouterr().out
    assert "2026-10-07" in out and "top-tier share" in out and "orchestrate" in out

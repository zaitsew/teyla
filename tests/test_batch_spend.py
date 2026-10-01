"""Headless volume in every harness (monitor.headless), advice A17/A18, and the report section.
Sessions are built in memory; the harness-error test reads a fake HOME in tmp_path."""
from __future__ import annotations

import datetime as dt
import json
import time
import types
from collections import Counter

import pytest

from teyla import advise as advise_mod, grokcost, health
from teyla.adapters import Session
from teyla.monitor import headless, metrics
from teyla.report import markdown

NOW = dt.datetime(2026, 9, 29, 18, 0, tzinfo=dt.timezone.utc)


def _s(harness, cwd, days_ago, batch=True, usage=None, sid=None):
    s = Session(harness=harness, project=cwd, sid=sid or f"{harness}-{cwd}-{days_ago}-{id(object())}", path="/x")
    s.cwd = cwd
    s.first = s.last = (NOW - dt.timedelta(days=days_ago, hours=1)).isoformat()
    s.batch = batch
    for model, u in (usage or {}).items():
        s.usage[model] = Counter(u)
    return s


def _many(harness, cwd, n, days_ago, **kw):
    return [_s(harness, cwd, days_ago, sid=f"{harness}-{cwd}-{days_ago}-{i}", **kw) for i in range(n)]


def test_headless_counts_prices_and_says_when_tokens_are_unknown():
    frank = "/private/tmp/frank-grok-empty"  # grok-cost's project_of: <repo>-grok-empty is <repo>
    ss = (_many("grok", frank, 1500, 1) + _many("grok", frank, 100, 10)
          + _many("codex", "/private/tmp/loco-review", 3, 2, usage={"gpt-6-astra": {"output_tokens": 100_000}})
          + _many("claude-code", "/private/tmp/x", 2, 3)                   # no usage recorded
          + [_s("claude-code", "/private/tmp/x", 1, batch=False)])         # interactive: not headless
    grok_rows = [types.SimpleNamespace(sid=s.sid, usd=0.05, turns=1) for s in ss if s.harness == "grok"]
    rows = {(r["harness"], r["project"]): r for r in headless(ss, 29, grok_rows=grok_rows, now=NOW)}
    f = rows[("grok", "frank")]
    assert (f["calls"], f["calls_7d"], f["calls_prev_7d"]) == (1600, 1500, 100)
    assert f["per_day_7d"] == pytest.approx(214.3, abs=0.1) and f["per_day_window"] == pytest.approx(55.2, abs=0.1)
    assert f["usd"] == pytest.approx(80.0) and f["cost_note"] == "list price" and f["doubled"]
    c = rows[("codex", "tmp")]
    assert c["calls"] == 3 and c["usd"] > 0 and c["cost_note"] == "API-equivalent"
    k = rows[("claude-code", "tmp")]
    assert k["calls"] == 2 and k["usd"] == 0 and k["cost_note"] == "calls, tokens unknown"
    assert sum(r["calls"] for r in rows.values()) == 1605  # the interactive session is not counted


def test_headless_without_grok_cost_rows_is_explicit_and_a_short_window_never_doubles():
    ss = _many("grok", "/private/tmp/frank-grok-empty", 300, 1)
    [r] = headless(ss, 7, now=NOW)
    assert r["cost_note"] == "calls, tokens unknown" and r["usd"] == 0
    assert r["window_days"] == 7 and not r["doubled"]  # no "week before" inside a 7-day window


def test_a17_fires_on_volume_or_doubling_and_names_project_and_harness():
    m = {"headless": [
        dict(harness="grok", project="frank", calls=14380, calls_7d=3189, calls_prev_7d=3041, per_day_7d=455.6,
             per_day_window=495.9, window_days=29, usd=1097.71, cost_note="list price", doubled=False),
        dict(harness="grok", project="loco", calls=310, calls_7d=175, calls_prev_7d=74, per_day_7d=25.0,
             per_day_window=10.7, window_days=29, usd=199.6, cost_note="list price", doubled=True),
        dict(harness="codex", project="teyla", calls=29, calls_7d=26, calls_prev_7d=0, per_day_7d=3.7,
             per_day_window=1.0, window_days=29, usd=58.1, cost_note="API-equivalent", doubled=False),
    ], "tokens": {}, "subagents": {}}
    fs = [f for f in advise_mod.advise(m) if f["id"] == "A17"]
    assert [f["title"] for f in fs] == ["frank drives grok headless volume", "loco drives grok headless volume"]
    assert "455.6 headless calls/day" in fs[0]["evidence"] and "$1,098 list price" in fs[0]["evidence"]
    assert "175 headless calls this week, 74 the week before" in fs[1]["evidence"]
    assert all(f["severity"] == "medium" for f in fs)


def test_a18_is_high_while_still_failing():
    m = {"tokens": {}, "subagents": {}, "harness_errors": [
        dict(harness="grok", kind="quota", day="2026-09-29", message="API error (status 402 Payment Required): Grok Build usage balance exhausted",
             count=236, still_failing=True, fix="Grok Build balance exhausted — top up"),
        dict(harness="claude", kind="quota", day="2026-09-08", message="You've hit your session limit", count=1,
             still_failing=False, fix="wait"),
    ]}
    fs = [f for f in advise_mod.advise(m) if f["id"] == "A18"]
    assert [(f["severity"], f["title"]) for f in fs] == [("high", "grok returned quota/balance errors"),
                                                        ("medium", "claude returned quota/balance errors (recovered)")]
    assert "×236" in fs[0]["evidence"] and fs[0]["action"].startswith("Grok Build balance exhausted")


def test_window_errors_from_the_harness_records(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".grok" / "logs").mkdir(parents=True)
    (home / ".codex" / "sessions").mkdir(parents=True)
    monkeypatch.delenv("CODEX_HOME", raising=False); monkeypatch.delenv("GROK_HOME", raising=False)
    now = dt.datetime.now(dt.timezone.utc)
    fail = {"status_code": 402, "message": "API error (status 402 Payment Required): Grok Build usage balance exhausted"}
    (home / ".grok" / "logs" / "unified.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"ts": (now - dt.timedelta(hours=3)).isoformat(), "msg": "shell.turn.inference_done", "ctx": {}},
        {"ts": (now - dt.timedelta(hours=1)).isoformat(), "msg": "shell.turn.inference_failed", "ctx": fail}]) + "\n")
    day = home / ".codex" / "sessions" / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
    day.mkdir(parents=True)
    (day / "rollout-x.jsonl").write_text(json.dumps({"timestamp": now.isoformat(), "type": "event_msg", "payload": {
        "type": "token_count", "rate_limits": {"primary": {"used_percent": 100.0}, "secondary": {"used_percent": 60.0},
                                               "plan_type": "plus", "rate_limit_reached_type": "primary"}}}) + "\n")
    rows = {r["harness"]: r for r in health.window_errors(7, home=home)}
    assert set(rows) == {"grok", "codex"}
    assert rows["grok"]["still_failing"] and rows["grok"]["kind"] == "quota"
    assert rows["codex"]["message"] == "usage limit reached (primary)" and rows["codex"]["still_failing"]


def test_report_has_the_headless_section():
    ss = _many("grok", "/private/tmp/frank-grok-empty", 30, 1) + [_s("claude-code", "/private/tmp/x", 1, batch=False)]
    m = metrics(ss, 29)
    m["headless"] = headless(ss, 29, now=dt.datetime.now(dt.timezone.utc))
    text = markdown(m, [])
    assert "## Headless calls by harness and project" in text
    assert "| grok | frank | 4.3 | 1 | 30 | 0 | 30 | calls, tokens unknown |" in text


def test_grok_week_reuses_rows_of_a_longer_window():
    now = dt.datetime.now(dt.timezone.utc)
    mk = lambda days, usd, cwd="/private/tmp/frank-grok-empty": types.SimpleNamespace(  # noqa: E731
        sid=f"s{days}{usd}", cwd=cwd, created=(now - dt.timedelta(days=days)).isoformat(), usd=usd, turns=1,
        calls=1, input=10, cached=5, output=1, day=(now - dt.timedelta(days=days)).strftime("%Y-%m-%d"))
    w = grokcost.week(rows=[mk(1, 30.0), mk(2, 2.0, "/private/tmp/x"), mk(20, 500.0)])
    assert w["total_usd"] == pytest.approx(32.0) and w["top_project"] == "frank"


def test_share_redacts_headless_project_names():
    from teyla.monitor import redact
    ss = _many("grok", "/private/tmp/frank-grok-empty", 3, 1)
    m = metrics(ss, 29)
    m["headless"] = headless(ss, 29, now=dt.datetime.now(dt.timezone.utc))
    r = redact(m)
    assert [h["project"] for h in r["headless"]] == ["h01"] and "frank" not in json.dumps(r["headless"])


def test_a18_a_later_unrelated_error_does_not_hide_a_quota_failure(tmp_path, monkeypatch):
    """Grok answered 402, then a connection reset; no call succeeded. Still failing (review of #69, P2;
    already resolved by the #66 merge, this pins it for A18)."""
    home = tmp_path / "home"
    (home / ".grok" / "logs").mkdir(parents=True)
    monkeypatch.delenv("CODEX_HOME", raising=False); monkeypatch.delenv("GROK_HOME", raising=False)
    now = dt.datetime.now(dt.timezone.utc)
    rec = lambda h, ctx: {"ts": (now - dt.timedelta(hours=h)).isoformat(), "msg": "shell.turn.inference_failed", "ctx": ctx}  # noqa: E731
    (home / ".grok" / "logs" / "unified.jsonl").write_text("\n".join(json.dumps(r) for r in [
        rec(3, {"status_code": 402, "message": "API error (status 402 Payment Required): balance exhausted"}),
        rec(1, {"message": "connection reset by peer"})]) + "\n")
    [row] = health.window_errors(7, home=home)
    assert row["harness"] == "grok" and row["kind"] == "quota" and row["still_failing"]


def test_a18_a_limit_event_newer_than_a_cleared_quota_error_is_still_failing(tmp_path, monkeypatch):
    """Old quota error, a success, then Codex reports the limit reached again: exhausted now, not
    "recovered" because the old error's kind matched (review of #69, P2)."""
    home = tmp_path / "home"
    (home / ".codex" / "sessions").mkdir(parents=True)
    monkeypatch.delenv("CODEX_HOME", raising=False); monkeypatch.delenv("GROK_HOME", raising=False)
    now = dt.datetime.now(dt.timezone.utc)
    at = lambda h: (now - dt.timedelta(hours=h)).isoformat()  # noqa: E731
    win = {"primary": {"used_percent": 100.0}, "secondary": {"used_percent": 60.0}, "plan_type": "plus"}
    day = home / ".codex" / "sessions" / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
    day.mkdir(parents=True)
    (day / "rollout-x.jsonl").write_text("\n".join(json.dumps(r, separators=(",", ":")) for r in [  # compact: the scan greps bytes
        {"timestamp": at(5), "type": "event_msg", "payload": {"type": "error", "message": "You've hit your usage limit."}},
        {"timestamp": at(3), "type": "event_msg", "payload": {"type": "token_count", "rate_limits": dict(win, primary={"used_percent": 20.0})}},
        {"timestamp": at(1), "type": "event_msg", "payload": {"type": "token_count", "rate_limits": dict(win, rate_limit_reached_type="primary")}},
    ]) + "\n")
    [row] = health.window_errors(7, home=home)
    assert row["message"] == "usage limit reached (primary)" and row["still_failing"]


def test_doubling_needs_the_floor_in_the_previous_week():
    [r] = headless(_many("codex", "/private/tmp/a", 100, 1), 29, now=NOW)  # 100 this week, none before
    assert (r["calls_7d"], r["calls_prev_7d"]) == (100, 0) and not r["doubled"]
    [r] = headless(_many("codex", "/private/tmp/a", 200, 1) + _many("codex", "/private/tmp/a", 100, 10), 29, now=NOW)
    assert r["doubled"]


def test_a_cost_known_for_some_calls_is_marked_partial():
    ss = (_many("codex", "/private/tmp/a", 1, 1, usage={"gpt-6-astra": {"output_tokens": 100_000}})
          + _many("codex", "/private/tmp/a", 9, 2, usage={}))          # no usage: cost unknown
    [r] = headless(ss, 29, now=NOW)
    assert r["usd"] > 0 and r["cost_partial"] and r["cost_note"] == "API-equivalent, partial: 1 of 10 calls costed"
    ss = _many("codex", "/private/tmp/a", 3, 1, usage={"gpt-6-astra": {"output_tokens": 100_000}})
    [r] = headless(ss, 29, now=NOW)
    assert not r["cost_partial"] and r["cost_note"] == "API-equivalent"

"""The console's Money section: cash from the owner's list, list price from the sessions, kept apart."""
from __future__ import annotations

import datetime as dt
import json
import stat

import pytest

from teyla import console, console_money as cm, providers, spend, subs

NOW = dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.timezone.utc).timestamp()


def iso(days_ago: float) -> str:
    return (dt.datetime.fromtimestamp(NOW, dt.timezone.utc) - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S")


def row(project="alpha", usd=10.0, days_ago=1.0, model="model-a", sub=2.0):
    day = (dt.date.fromtimestamp(NOW) - dt.timedelta(days=int(days_ago))).isoformat()
    return {"harness": "claude-code", "sid": "s" + project + str(days_ago), "project": project, "usd": usd,
            "sub_usd": sub, "by_model": {model: usd}, "first": iso(days_ago), "last": iso(days_ago),
            "day_usd": {day: usd}, "day_model_usd": {day: {model: usd}}, "sub_day_model_usd": {}, "sub_calls": []}


def bills(day_usd=5.0):
    today = dt.datetime.fromtimestamp(NOW, dt.timezone.utc).date()
    return {"openai": {"daily": {"grp": {today.isoformat(): day_usd,
                                         (today - dt.timedelta(days=10)).isoformat(): 3.0}}},
            "anthropic": {"skipped": "no anthropic-admin-key in the Keychain"}}


def actions():
    return [{"account": "acct", "plan": "free", "minutes": 120, "included": 2000, "share": 0.06, "paid_usd": 0.0,
             "top_repos": ["alpha"], "macos_minutes": {}},
            {"account": "org", "plan": None, "minutes": 30, "included": None, "share": None, "paid_usd": 1.5,
             "top_repos": [], "macos_minutes": {}}]


def listed(*items):
    for name, fields in items:
        subs.add(name, **fields)


# --- cash --------------------------------------------------------------------------------------------------

def test_no_file_means_a_null_headline_that_says_how_to_add(monkeypatch):
    sec = cm.section(NOW)
    assert sec["headline"]["value"] is None
    assert "teyla subs add" in sec["headline"]["detail"]
    assert sec["subscriptions"] == [] and sec["credits"] == [] and sec["credits_total_usd"] is None
    assert sec["spend"]["days7"]["list_usd"] is None and sec["by_product"] is None
    assert "usage" in sec["notes"]


def test_the_forecast_adds_priced_rows_and_names_the_rest():
    listed(("Alpha", {"monthly_usd": 200, "category": "ai", "credits_usd": 200, "renews": "2026-11-20"}),
           ("Beta", {"monthly_usd": 20.5, "category": "tool", "renews": "2026-11-06"}),
           ("Gamma", {"category": "cloud", "note": "price unknown"}),
           ("Delta", {"monthly_usd": 1, "category": "domain", "renews": "2027-06-01"}))
    sec = cm.section(NOW)
    assert sec["headline"] == {"label": "Cash per month", "value": 221.5,
                               "detail": "3 of 4 subscriptions priced; no price for Gamma"}
    f = sec["forecast"]
    assert f["unpriced"] == ["Gamma"] and f["by_category"] == {"ai": 200.0, "tool": 20.5, "cloud": 0.0, "domain": 1.0}
    assert [r["name"] for r in f["renewals"]] == ["Beta", "Alpha"]           # soonest first, Delta is too far
    assert f["renewals"][0]["days"] == 2
    assert sec["credits"] == [{"name": "Alpha", "credits_usd": 200.0, "monthly_usd": 200.0}]
    assert sec["credits_total_usd"] == 200.0
    names = [c["name"] for c in sec["cloud"]]
    assert names == ["Gamma", "Delta"]                                        # cloud and domain rows, no usage yet


def test_a_broken_file_gives_a_null_headline_with_the_reason_and_the_rest_still_loads():
    subs.path().parent.mkdir(parents=True, exist_ok=True)
    subs.path().write_text("not toml [[")
    cm.config.write_private(cm.cache_path(), json.dumps(cm.aggregate([row()], NOW, None, None) | {"notes": {}}))
    sec = cm.section(NOW)
    assert sec["headline"]["value"] is None and "not valid TOML" in sec["headline"]["detail"]
    assert "subscriptions" in sec["notes"]
    assert sec["spend"]["days7"]["list_usd"] == 10.0


# --- list price and billed ---------------------------------------------------------------------------------

def test_aggregate_splits_the_two_windows_by_product_model_and_day():
    rows = [row("alpha", 10, 1, "model-a"), row("alpha", 4, 20, "model-b"), row("beta", 6, 3, "model-a"),
            row("old", 99, 45, "model-c")]
    u = cm.aggregate(rows, NOW, bills(), actions())
    assert u["windows"]["days7"] == {"list_usd": 16.0, "sub_usd": 4.0, "sessions": 2, "billed_usd": 5.0}
    assert u["windows"]["days30"]["list_usd"] == 20.0 and u["windows"]["days30"]["billed_usd"] == 8.0
    assert u["by_product"][0] == {"name": "alpha", "days7_usd": 10.0, "days30_usd": 14.0, "sessions": 2}
    assert {m["model"] for m in u["by_model"]} == {"model-a", "model-b"}         # the 45-day row is outside both
    assert len(u["by_day"]) == 30 and u["by_day"][-1]["day"] == "2026-11-04"
    assert sum(d["list_usd"] for d in u["by_day"]) == 20.0
    assert u["providers"]["openai"]["billed_usd_30d"] == 8.0
    assert u["providers"]["anthropic"] == {"billed_usd_30d": None, "reason": "no anthropic-admin-key in the Keychain"}


def test_billed_is_null_when_no_provider_could_be_read():
    u = cm.aggregate([row()], NOW, {"openai": {"skipped": "no key"}}, None)
    assert u["windows"]["days7"]["billed_usd"] is None                  # $0 would claim a read that never happened
    assert u["actions"] is None


def test_actions_sum_minutes_and_leave_an_unknown_quota_null():
    u = cm.aggregate([], NOW, None, actions())
    a = u["actions"]
    assert a["minutes_used"] == 150 and a["minutes_included"] == 2000 and a["paid_usd"] == 1.5
    assert [x["account"] for x in a["accounts"]] == ["acct", "org"]
    only_unknown = cm.aggregate([], NOW, None, [actions()[1]])["actions"]
    assert only_unknown["minutes_included"] is None


def test_list_price_never_reaches_the_cash_figures():
    listed(("Alpha", {"monthly_usd": 20, "category": "ai"}))
    cm.config.write_private(cm.cache_path(), json.dumps(cm.aggregate([row(usd=5000)], NOW, bills(), actions())))
    sec = cm.section(NOW)
    assert sec["headline"]["value"] == 20.0 and sec["forecast"]["monthly_usd"] == 20.0
    assert sec["spend"]["days7"]["list_usd"] == 5000.0
    assert "Not cash" in sec["spend"]["label"]
    names = [c["name"] for c in sec["cloud"]]
    assert "GitHub Actions (acct)" in names
    actions_row = next(c for c in sec["cloud"] if c["name"] == "GitHub Actions (org)")
    assert actions_row["monthly_usd"] is None and actions_row["metered_usd"] == 1.5
    assert actions_row["detail"] == "30 minutes used this month"


def test_section_makes_no_network_call_and_scans_no_sessions(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("section() must read caches only")
    monkeypatch.setattr(spend, "session_rows", boom)
    monkeypatch.setattr(spend, "actions_usage", boom)
    monkeypatch.setattr(providers, "read", boom)
    assert cm.section(NOW)["headline"]["label"] == "Cash per month"


# --- the cache ---------------------------------------------------------------------------------------------

def fake_compute(calls):
    def compute(now, **kw):
        calls.append(now)
        return cm.aggregate([row()], now, None, None), {}
    return compute


def test_prepare_writes_a_private_cache_and_skips_a_fresh_one_unless_forced(monkeypatch):
    calls = []
    monkeypatch.setattr(cm, "compute", fake_compute(calls))
    assert cm.prepare(NOW) is True
    assert stat.S_IMODE(cm.cache_path().stat().st_mode) == 0o600
    assert cm.prepare(NOW + 60) is False and len(calls) == 1
    assert cm.prepare(NOW + 60, force=True) is True and len(calls) == 2
    assert cm.prepare(NOW + 60 + cm.USAGE_MAX_AGE_S + 1) is True
    assert cm.read_usage()["windows"]["days7"]["list_usd"] == 10.0


def test_a_failed_scan_keeps_the_last_good_numbers(monkeypatch):
    cm.config.write_private(cm.cache_path(), json.dumps(cm.aggregate([row()], NOW, None, None)))
    monkeypatch.setattr(spend, "session_rows", lambda days: (_ for _ in ()).throw(OSError("disk")))
    monkeypatch.setattr(providers, "read", lambda days: {})
    monkeypatch.setattr(spend, "actions_usage", lambda: None)
    assert cm.prepare(NOW + 10 * 3600) is False
    assert cm.read_usage()["windows"]["days7"]["list_usd"] == 10.0


def test_compute_with_a_failing_scan_nulls_the_spend_and_says_why(monkeypatch):
    monkeypatch.setattr(spend, "session_rows", lambda days: (_ for _ in ()).throw(OSError("disk")))
    usage, notes = cm.compute(NOW, bills={}, actions=None)
    assert "OSError" in notes["spend"]
    assert usage["windows"]["days7"]["list_usd"] is None and usage["by_product"] is None
    cm.config.write_private(cm.cache_path(), json.dumps({**usage, "notes": notes}))
    sec = cm.section(NOW)
    assert "usage.spend" in sec["notes"] and sec["spend"]["days7"]["list_usd"] is None


def test_compute_reads_each_source_on_its_own(monkeypatch):
    monkeypatch.setattr(spend, "session_rows", lambda days: [row()])
    monkeypatch.setattr(providers, "read", lambda days: bills())
    monkeypatch.setattr(spend, "actions_usage", lambda: (_ for _ in ()).throw(RuntimeError("no gh")))
    usage, notes = cm.compute(NOW)
    assert "RuntimeError" in notes["actions"] and usage["actions"] is None
    assert usage["windows"]["days7"]["list_usd"] == 10.0 and usage["windows"]["days7"]["billed_usd"] == 5.0


def test_a_corrupt_or_old_cache_reads_as_missing():
    assert cm.read_usage() is None
    cm.cache_path().parent.mkdir(parents=True, exist_ok=True)
    cm.cache_path().write_text("{not json")
    assert cm.read_usage() is None
    cm.cache_path().write_text(json.dumps({"version": 0}))
    assert cm.read_usage() is None


# --- compact and the console -------------------------------------------------------------------------------

def test_compact_is_small_and_passes_an_error_through():
    listed(("Alpha", {"monthly_usd": 20, "renews": "2026-11-10"}), ("Beta", {}))
    c = cm.compact(cm.section(NOW))
    assert c["monthly_usd"] == 20.0 and c["unpriced"] == 1
    assert c["next_renewal"] == {"name": "Alpha", "renews": "2026-11-10", "days": 6}
    assert c["list_usd_7d"] is None and c["headline"]["label"] == "Cash per month"
    assert cm.compact({"error": "boom"}) == {"error": "boom"}


def test_the_console_prepares_the_money_cache_when_refreshing(monkeypatch):
    seen = []
    monkeypatch.setattr(cm, "prepare", lambda now=None, force=False: seen.append(force) or True)
    monkeypatch.setattr(console, "SECTIONS", {"money": "console_money"})
    console.build(NOW, force=True)
    console.build(NOW)
    assert seen == [True, False]


def test_a_failing_prepare_does_not_stop_the_section(monkeypatch):
    monkeypatch.setattr(cm, "prepare", lambda now=None, force=False: (_ for _ in ()).throw(OSError("full")))
    monkeypatch.setattr(console, "SECTIONS", {"money": "console_money"})
    rep = console.build(NOW)
    assert rep["money"]["headline"]["label"] == "Cash per month"

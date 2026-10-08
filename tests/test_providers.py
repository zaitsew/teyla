"""teyla.providers: the OpenAI and Anthropic cost APIs (W7), read through a fake `get`."""
from __future__ import annotations

import datetime as _dt
import urllib.parse

from teyla import providers, spend

TODAY = _dt.date(2026, 10, 1)


def _epoch(day: str) -> int:
    return int(_dt.datetime.fromisoformat(day).replace(tzinfo=_dt.timezone.utc).timestamp())


def _query(url: str) -> dict:
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def test_openai_daily_follows_pages_and_names_projects():
    calls = []

    def get(url, headers):
        calls.append(url)
        assert headers["Authorization"] == "Bearer sk-admin-x"
        if "/projects" in url:
            return {"data": [{"id": "proj_a", "name": "app-b"}]}
        if "page" not in _query(url):
            return {"data": [{"start_time": _epoch("2026-09-29"), "results": [
                        {"project_id": "proj_a", "amount": {"value": 1.5}},
                        {"project_id": "proj_a", "amount": {"value": 0.5}},
                        {"project_id": "proj_b", "amount": {"value": 3}}]}],
                    "has_more": True, "next_page": "p2"}
        return {"data": [{"start_time": _epoch("2026-09-30"), "results": [
                    {"project_id": None, "amount": {"value": 0.25}}]}], "has_more": False}

    out = providers.openai_daily("sk-admin-x", _dt.date(2026, 9, 17), get)
    assert out == {"app-b": {"2026-09-29": 2.0}, "proj_b": {"2026-09-29": 3.0},
                   "default project": {"2026-09-30": 0.25}}
    q = _query(calls[1])
    assert q["start_time"] == [str(_epoch("2026-09-17"))] and q["group_by"] == ["project_id"]
    assert _query(calls[2])["page"] == ["p2"]


def test_openai_daily_groups_by_id_when_projects_cannot_be_listed():
    def get(url, headers):
        if "/projects" in url:
            raise OSError("403")
        return {"data": [{"start_time": _epoch("2026-09-30"),
                          "results": [{"project_id": "proj_a", "amount": {"value": 1}}]}]}

    assert providers.openai_daily("k", TODAY, get) == {"proj_a": {"2026-09-30": 1.0}}


def test_openai_projects_sharing_a_name_keep_their_own_series():
    def get(url, headers):
        if "/projects" in url:
            return {"data": [{"id": "proj_a", "name": "app-b"}, {"id": "proj_b", "name": "app-b"},
                             {"id": "proj_c", "name": "app-a"}]}
        return {"data": [{"start_time": _epoch("2026-09-30"), "results": [
            {"project_id": p, "amount": {"value": 1}} for p in ("proj_a", "proj_b", "proj_c")]}]}

    assert set(providers.openai_daily("k", TODAY, get)) == {"app-b (proj_a)", "app-b (proj_b)", "app-a"}


def test_a_bill_past_the_page_cap_is_an_error_not_a_partial_bill():
    def get(url, headers):
        return {"data": [], "has_more": True, "next_page": "again"}

    out = providers.read(7, TODAY, key_of=lambda s: "k", get=get)
    assert out["openai"]["error"].startswith("RuntimeError: more than 20 pages")
    assert out["anthropic"]["error"].startswith("RuntimeError")


def test_anthropic_daily_converts_cents_and_pages():
    calls = []

    def get(url, headers):
        calls.append(url)
        assert headers["x-api-key"] == "sk-ant-admin-x"
        if "page" not in _query(url):
            return {"data": [{"starting_at": "2026-09-30T00:00:00Z", "results": [
                        {"workspace_id": "wrkspc_1", "amount": "1234.5"},
                        {"workspace_id": None, "amount": "50"}]}],
                    "has_more": True, "next_page": "n2"}
        return {"data": [{"starting_at": "2026-10-01T00:00:00Z",
                          "results": [{"workspace_id": "wrkspc_1", "amount": "100"}]}], "has_more": False}

    out = providers.anthropic_daily("sk-ant-admin-x", _dt.date(2026, 9, 17), _dt.date(2026, 10, 2), get)
    assert out == {"wrkspc_1": {"2026-09-30": 12.345, "2026-10-01": 1.0}, "default workspace": {"2026-09-30": 0.5}}
    q = _query(calls[0])
    assert q["starting_at"] == ["2026-09-17T00:00:00Z"] and q["ending_at"] == ["2026-10-02T00:00:00Z"]
    assert q["group_by[]"] == ["workspace_id"] and _query(calls[1])["page"] == ["n2"]


def _series(values: dict[int, float]) -> dict[str, float]:
    """{days back from TODAY: usd} -> {YYYY-MM-DD: usd}."""
    return {(TODAY - _dt.timedelta(days=b)).isoformat(): v for b, v in values.items()}


def test_spikes_need_twice_the_median_and_a_floor():
    flat = {b: 1.0 for b in range(1, 15)}
    bills = {"openai": {"daily": {
        "app-b": _series({**flat, 0: 5.0}),          # 5x the median, $4 over: a spike
        "app-a": _series({**flat, 0: 2.5}),         # 2.5x but only $1.50 over: below the floor
        "app-c": _series({**{b: 10.0 for b in range(1, 15)}, 0: 18.0}),  # $8 over but under 2x
    }}, "anthropic": {"skipped": "no anthropic-admin-key in the Keychain"}}
    out = providers.spikes(bills, 7, TODAY)
    assert [(s["group"], s["day"]) for s in out] == [("app-b", "2026-10-01")]
    assert out[0]["median"] == 1.0 and out[0]["excess"] == 4.0


def test_spikes_look_only_inside_the_window_and_sort_by_excess():
    series = _series({9: 50.0, 3: 9.0, 1: 30.0})   # day 9 is history; new spend has median 0
    out = providers.spikes({"openai": {"daily": {"app-d": series}}}, 7, TODAY)
    assert [s["day"] for s in out] == ["2026-09-30", "2026-09-28"]
    assert out[0]["excess"] == 30.0


def test_totals_sum_the_window_only_and_drop_pennies():
    bills = {"openai": {"daily": {"app-b": _series({0: 1.0, 6: 2.0, 7: 100.0}), "tiny": _series({0: 0.004})}},
             "anthropic": {"error": "HTTPError: 401"}}
    # anthropic was not read: no "$0 billed" line, the coverage line says why
    assert providers.totals(bills, 7, TODAY) == {"openai": {"app-b": 3.0}}


def test_read_skips_missing_keys_safe_mode_and_survives_errors(monkeypatch):
    def get(url, headers):
        if "anthropic" in url:
            raise OSError("down")
        return {"data": []}

    keys = {"openai-admin-key": "sk-admin-x", "anthropic-admin-key": "sk-ant-admin-x"}
    out = providers.read(7, TODAY, key_of=keys.get, get=get)
    assert out["openai"] == {"daily": {}} and out["anthropic"]["error"] == "OSError: down"

    out = providers.read(7, TODAY, key_of=lambda s: None, get=get)
    assert out == {"openai": {"skipped": "no openai-admin-key in the Keychain"},
                   "anthropic": {"skipped": "no anthropic-admin-key in the Keychain"}}

    monkeypatch.setattr("teyla.net.gate", lambda *a, **k: False)
    calls = []
    out = providers.read(7, TODAY, key_of=keys.get, get=lambda u, h: calls.append(u))
    assert out["openai"] == {"skipped": "safe mode"} and not calls


def test_read_asks_for_the_window_plus_the_spike_baseline():
    seen = []
    providers.read(7, TODAY, key_of=lambda s: "k" if s == "anthropic-admin-key" else None,
                   get=lambda u, h: seen.append(_query(u)) or {"data": []})
    assert seen[0]["starting_at"] == ["2026-09-17T00:00:00Z"] and seen[0]["ending_at"] == ["2026-10-02T00:00:00Z"]


def test_the_suite_never_reads_the_real_keychain():
    assert providers.read(7, TODAY)["openai"] == {"skipped": "no openai-admin-key in the Keychain"}


def test_report_carries_w7_and_says_what_it_could_not_read():
    bills = {"openai": {"daily": {"app-b": _series({**{b: 1.0 for b in range(1, 15)}, 0: 40.0})}},
             "anthropic": {"skipped": "no anthropic-admin-key in the Keychain"}}
    today = _dt.datetime.now(_dt.timezone.utc).date()
    # report() reads "today" itself; shift the fixture onto the real date.
    shift = (today - TODAY).days
    bills["openai"]["daily"]["app-b"] = {(_dt.date.fromisoformat(d) + _dt.timedelta(days=shift)).isoformat(): v
                                        for d, v in bills["openai"]["daily"]["app-b"].items()}
    rep = spend.report(7, rows=[], actions=[], bills=bills)
    w7 = [f for f in rep["findings"] if f["id"] == "W7"]
    assert w7 and w7[0]["usd"] == 39.0 and "openai app-b" in w7[0]["evidence"]
    assert "W7: anthropic not read (no anthropic-admin-key in the Keychain)" in rep["coverage"]
    assert rep["providers"]["openai"] == {"app-b": 46.0}
    assert "openai billed (products, all keys): $46" in spend.render(rep)
    assert "anthropic billed" not in spend.render(rep)
    # product spikes are not part of the sessions' total, so not of its waste share
    assert rep["waste_usd"] == 0 and rep["product_waste_usd"] == 39.0
    assert spend.summary_line(rep).startswith("spend 7d: $0.00 API-equivalent, $0.00 of it waste, plus $39 of product API spikes")


def test_alert_names_a_spike():
    s = dict(provider="openai", group="app-b", day="2026-10-01", usd=40.0, median=1.0, excess=39.0)
    assert spend.alerts([], [], spikes=[s]) == ["openai app-b spent $40 on 2026-10-01 (median $1.00)"]

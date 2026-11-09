"""`teyla spend` and `teyla spend --by-day` add up the same window, and `--session` shows one session.
All data is invented; time is pinned to a timezone that is not UTC."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import time
from collections import Counter, defaultdict

import pytest

from teyla import config, pricing, providers, spend
from teyla.adapters import Session, local_day

NOW = _dt.datetime.now(_dt.timezone.utc)
REAL_SESSION_ROWS = spend.session_rows


@pytest.fixture(autouse=True)
def _tz_and_prices(monkeypatch, tmp_path):
    old = os.environ.get("TZ")
    monkeypatch.setenv("TZ", "Pacific/Auckland")  # far from UTC, so a UTC day and a local day differ
    time.tzset()
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", tmp_path / "no-prices.json")
    monkeypatch.setattr(config, "TEYLA_DIR", tmp_path / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / ".teyla" / "config.toml")
    monkeypatch.setattr(providers, "read", lambda days, **k: {})
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


def _iso(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ago(days: float) -> str:
    return _iso(NOW - _dt.timedelta(days=days))


def _session(sid, spans, sub=None, cwd="/work/demo", model="claude-fable-5-1"):
    """spans: [(timestamp, output tokens)] sent by the session; sub: the same for its subagents.
    A million output tokens of Fable 5.1 cost $50 at list price."""
    s = Session(harness="claude-code", project="p", sid=sid, path="x", cwd=cwd)
    s.day_usage, s.sub_day_usage = defaultdict(lambda: defaultdict(Counter)), defaultdict(lambda: defaultdict(Counter))
    stamps = []
    for ts, out in spans:
        stamps.append(ts)
        s.usage[model]["output_tokens"] += out
        s.day_usage[local_day(ts)][model]["output_tokens"] += out
    for ts, out, m in sub or []:
        stamps.append(ts)
        s.usage[m]["output_tokens"] += out
        s.sub_usage[m]["output_tokens"] += out
        s.day_usage[local_day(ts)][m]["output_tokens"] += out
        s.sub_day_usage[local_day(ts)][m]["output_tokens"] += out
        s.sub_calls.append((local_day(ts), m))
    s.first, s.last = min(stamps), max(stamps)
    return s


def _rows(sessions):
    return REAL_SESSION_ROWS(30, sessions=sessions, grok_rows=[])


def _both(sessions, days, monkeypatch):
    """The two totals over the same sessions: `teyla spend` and the sum of `--by-day`."""
    rows = _rows(sessions)
    monkeypatch.setattr(spend, "session_rows", lambda d: [r for r in rows if r["last"][:19] >= spend._cutoff(d)])
    rep = spend.report(days, with_actions=False, bills={})
    by = spend.by_day(days, rows)
    return rep, by


def test_a_session_resumed_inside_the_window_books_only_its_window_part(monkeypatch):
    s = _session("resumed", [(_ago(20), 1_000_000), (_ago(1), 200_000)])  # $50 before the window, $10 in it
    rep, by = _both([s], 7, monkeypatch)
    assert rep["total_usd"] == pytest.approx(10.0)
    assert round(rep["total_usd"], 2) == round(sum(d["total_usd"] for d in by), 2)
    assert rep["session_usd"] == pytest.approx(60.0)          # the whole life stays visible, and is named
    assert rep["by_harness"] == {"claude-code": pytest.approx(10.0)}
    assert sum(rep["by_model"].values()) == pytest.approx(10.0)


def test_subagent_cost_is_in_both_totals_once(monkeypatch):
    s = _session("lanes", [(_ago(1), 100_000)], sub=[(_ago(1), 100_000, "claude-sonnet-5-5")])
    rep, by = _both([s], 7, monkeypatch)
    assert rep["total_usd"] == pytest.approx(round(sum(d["total_usd"] for d in by), 2), abs=0.005)
    assert rep["sub_usd"] == pytest.approx(sum(d["sub_usd"] for d in by), abs=0.005)
    assert rep["sub_usd"] > 0 and rep["total_usd"] > rep["sub_usd"]


def test_a_message_on_the_oldest_local_day_counts_in_both(monkeypatch):
    days = 7
    oldest = _dt.date.today() - _dt.timedelta(days=days - 1)
    edge = _dt.datetime.combine(oldest, _dt.time(0, 30)).astimezone(_dt.timezone.utc)   # 00:30 local, the evening before in UTC
    before = edge - _dt.timedelta(hours=1)                                               # 23:30 local, one day out
    assert local_day(_iso(edge)) == oldest.isoformat() and local_day(_iso(before)) != oldest.isoformat()
    s = _session("edge", [(_iso(before), 100_000), (_iso(edge), 200_000), (_iso(NOW), 100_000)])
    rep, by = _both([s], days, monkeypatch)
    assert rep["total_usd"] == pytest.approx(10 + 5)          # the edge message and today's, not the one before
    assert by[0]["day"] == oldest.isoformat() and by[0]["total_usd"] == 10.0
    assert round(rep["total_usd"], 2) == round(sum(d["total_usd"] for d in by), 2)


def test_the_cli_prints_one_total_for_spend_and_by_day(monkeypatch, capsys):
    s = _session("resumed", [(_ago(20), 1_000_000), (_ago(1), 200_000), (_ago(2), 300_000)])
    rows = _rows([s])
    monkeypatch.setattr(spend, "session_rows", lambda d: rows)
    monkeypatch.setattr(spend, "actions_usage", lambda: None)
    spend.cmd_spend(argparse.Namespace(alert=False, by_day=False, days=14, json=True, no_actions=True))
    a = json.loads(capsys.readouterr().out)
    spend.cmd_spend(argparse.Namespace(alert=False, by_day=True, days=14, json=True))
    b = json.loads(capsys.readouterr().out)
    assert round(a["total_usd"], 2) == b["total_usd"] == 25.0
    spend.cmd_spend(argparse.Namespace(alert=False, by_day=False, days=14, json=False, no_actions=True))
    assert "window total $25" in capsys.readouterr().out


def test_fable_5_2_is_priced_at_its_own_row_in_both_totals(monkeypatch):
    # One million cache-read tokens: $0.20 on the 5.2 row, $0.25 on 5.1, $1.00 on the bare fable row.
    s = Session(harness="claude-code", project="p", sid="f52", path="x", cwd="/work/demo", first=_ago(1), last=_ago(1))
    s.usage["claude-fable-5-2"]["cache_read_input_tokens"] = 1_000_000
    s.day_usage[local_day(_ago(1))]["claude-fable-5-2"]["cache_read_input_tokens"] = 1_000_000
    rep, by = _both([s], 7, monkeypatch)
    assert rep["total_usd"] == pytest.approx(0.20) and rep["by_model"] == {"claude-fable-5-2": pytest.approx(0.20)}
    assert sum(d["total_usd"] for d in by) == pytest.approx(0.20, abs=0.005)


# --- --session -------------------------------------------------------------------------------

def _cli(monkeypatch, sessions, key, capsys, json_out=False, days=None):
    rows = _rows(sessions)
    monkeypatch.setattr(spend, "session_rows", lambda d: rows)
    code = spend.cmd_spend(argparse.Namespace(alert=False, by_day=False, session=key, days=days, json=json_out))
    out = capsys.readouterr()
    return code, out.out, out.err


def _two(monkeypatch):
    a = _session("aaaa1111-0000", [(_ago(3), 100_000), (_ago(1), 100_000)],
                 sub=[(_ago(1), 100_000, "claude-sonnet-5-5")], cwd="/work/alpha")
    b = _session("aaaa2222-0000", [(_ago(1), 100_000)], cwd="/work/beta")
    c = _session("bbbb3333-0000", [(_ago(1), 100_000)], cwd="/work/gamma")
    return [a, b, c]


def test_session_by_full_id_and_by_prefix(monkeypatch, capsys):
    for key in ("aaaa1111-0000", "aaaa1", "bbbb"):
        code, out, _ = _cli(monkeypatch, _two(monkeypatch), key, capsys)
        assert code == 0 and "API list price; subscription use and billed spend differ." in out
    code, out, _ = _cli(monkeypatch, _two(monkeypatch), "aaaa1", capsys)
    assert "/work/alpha" in out and "by model:" in out and "by local day:" in out and "subagents: 1 calls, sonnet" in out
    assert "claude-code" in out and "alpha" in out


def test_session_ambiguous_prefix_lists_matches_and_exits_2(monkeypatch, capsys):
    code, out, err = _cli(monkeypatch, _two(monkeypatch), "aaaa", capsys)
    assert code == 2 and out == "" and "aaaa1111-0000" in err and "aaaa2222-0000" in err and "bbbb3333" not in err


def test_session_unknown_id_exits_1_with_a_message(monkeypatch, capsys):
    code, out, err = _cli(monkeypatch, _two(monkeypatch), "zzzz", capsys, days=5)
    assert code == 1 and out == "" and "no session" in err and "5 days" in err


def test_session_json_keys_and_split(monkeypatch, capsys):
    code, out, _ = _cli(monkeypatch, _two(monkeypatch), "aaaa1", capsys, json_out=True)
    d = json.loads(out)
    assert code == 0
    assert {"id", "harness", "project", "cwd", "first", "last", "total_usd", "session_usd", "subagents_usd", "by_model",
            "by_day", "subagent_count", "subagent_by_family", "prs", "note"} <= set(d)
    assert d["id"] == "aaaa1111-0000" and d["harness"] == "claude-code" and d["cwd"] == "/work/alpha"
    assert d["subagent_count"] == 1 and set(d["subagent_by_family"]) == {"sonnet"}
    assert d["total_usd"] == pytest.approx(d["session_usd"] + d["subagents_usd"])
    assert sum(d["by_day"].values()) == pytest.approx(d["total_usd"], abs=0.001)
    assert sum(d["by_model"].values()) == pytest.approx(d["total_usd"])
    assert d["note"] == "API list price; subscription use and billed spend differ."


# --- review fixes ------------------------------------------------------------------------------

@pytest.mark.parametrize("flags", [["--days", "0"], ["--days", "-3", "--by-day"], ["--days", "x"], ["--session", "ab", "--days", "0"]])
def test_days_below_one_is_refused_by_the_parser(flags, capsys):
    p = argparse.ArgumentParser()
    spend.register(p.add_subparsers())
    with pytest.raises(SystemExit) as e:
        p.parse_args(["spend", *flags])
    assert e.value.code == 2 and "--days must be a whole number of at least 1" in capsys.readouterr().err


def test_window_waste_never_exceeds_the_window_total(monkeypatch):
    # $50 spent 20 days ago, $1 today, no outcome: a W1 finding of $51 over the session life.
    s = _session("idle-resumed", [(_ago(20), 1_000_000), (_ago(0.1), 20_000)], cwd="/work/demo")
    rows = _rows([s])
    monkeypatch.setattr(spend, "session_rows", lambda d: rows)
    real = spend.findings
    monkeypatch.setattr(spend, "findings", lambda rows, actions=None, **k: real(rows, actions, outcome_of=lambda r: False, **k))
    rep = spend.report(7, with_actions=False, bills={})
    assert rep["total_usd"] == pytest.approx(1.0)
    assert any(f["id"] == "W1" for f in rep["findings"])
    assert rep["waste_usd"] == pytest.approx(1.0) and rep["waste_usd"] <= rep["total_usd"]
    assert "(100%)" in spend.summary_line(rep) and "$51" not in spend.summary_line(rep)

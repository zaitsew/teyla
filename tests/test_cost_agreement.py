"""`teyla spend`, `teyla monitor` and `teyla lanes` over one small invented corpus must print the same
dollars: one price table, one window (the last N local days, by the day of each message), one message id
is one message, and a model with no price is named, never $0. tests/fixtures/cost-corpus holds the
transcripts; every expected number below is worked out by hand from them.

The clock is fixed: 2026-11-20 12:00 UTC, time zone UTC, a 7-day window = local days 2026-11-14 .. 2026-11-20.
Prices used (USD per 1M tokens: input / cache write 5 min / cache read / output):
    claude-sonnet-5-5  2 / 2.5 / 0.2 / 10      (a 1-hour cache write bills at 2x input = 4)
    claude-opus-5-5    4 / 5   / 0.2 / 20
    gpt-6.1-sol        2 / 2.5 / 0.1 / 10
    mystery-model-1, gpt-9-prototype: no price
"""
from __future__ import annotations

import datetime as _dt
import os
import pathlib
import time

import pytest

from teyla import costing, lanes, monitor, pricing, spend
from teyla.adapters import claude_code, codex

CORPUS = pathlib.Path(__file__).parent / "fixtures" / "cost-corpus"
NOW = _dt.datetime(2026, 11, 20, 12, 0, tzinfo=_dt.timezone.utc)
TODAY = NOW.date()
DAYS = 7

# --- the numbers, by hand -------------------------------------------------------------------------
# Session A (Claude Code, Sonnet). a-m1 is on 11-12, outside the window: not counted. a-m2 is written
# twice with one id; the last record counts: 1,000,000 in, 100,000 out, 500,000 cache read, 200,000 cache
# write, all of it the 1-hour kind.
#   input  1,000,000 x 2 / 1e6              = 2.00
#   output   100,000 x 10 / 1e6             = 1.00
#   read     500,000 x 0.2 / 1e6            = 0.10
#   write    200,000 x (2 x 2) / 1e6        = 0.80   (1-hour write = 2 x input)
A_MAIN = 3.90
# Its subagent 1 (Opus): a-s0 is on 11-10, outside the window. a-s1 is written twice under two request ids,
# one message: 100,000 in, 50,000 out, 1,000,000 read.
#   input  100,000 x 4 / 1e6   = 0.40
#   output  50,000 x 20 / 1e6  = 1.00
#   read 1,000,000 x 0.2 / 1e6 = 0.20
A_SUB = 1.60
# Its subagent 2 uses mystery-model-1: 7,000 in + 3,000 out = 10,000 tokens, no price: $0 and named.
# Session B (and its subagent) is entirely on 11-01: not in the window at all.
# Session C (Sonnet): c-m1 10,000 in + 2,000 out = 0.02 + 0.02 = 0.04; c-m2 4,000 out = 0.04.
C_MAIN = 0.08
# Codex gpt-6.1-sol, booked whole on the day it was last active (11-18): 300,000 in, 100,000 cached, 20,000 out.
#   input  300,000 x 2 / 1e6   = 0.60
#   read   100,000 x 0.1 / 1e6 = 0.01
#   output  20,000 x 10 / 1e6  = 0.20
CODEX = 0.81
# Codex gpt-9-prototype (no price) 5,000 in + 1,000 out = 6,000 tokens; the Codex session of 11-02 is outside.
TOTAL = A_MAIN + A_SUB + C_MAIN + CODEX          # 3.90 + 1.60 + 0.08 + 0.81 = 6.39
SUB = A_SUB                                        # 1.60
CLAUDE = A_MAIN + A_SUB + C_MAIN                   # 5.58
# Tokens in the window, all models: A main 1,800,000 + opus 1,150,000 + mystery 10,000 + C 16,000
# + codex sol 420,000 + codex gpt-9 6,000 = 3,402,000.
TOKENS = 3_402_000
UNPRICED = {"mystery-model-1": 10_000, "gpt-9-prototype": 6_000}


@pytest.fixture(autouse=True)
def _fixed_world(monkeypatch, tmp_path):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", tmp_path / "no-prices.json")
    orig_window, orig_cutoff = costing.window, costing.cutoff_utc
    monkeypatch.setattr(costing, "window", lambda days, today=None: orig_window(days, today or TODAY))
    monkeypatch.setattr(costing, "cutoff_utc", lambda days, now=None: orig_cutoff(days, now or NOW))
    monkeypatch.setattr(spend, "_cutoff", lambda days: orig_cutoff(days, NOW))
    yield
    time.tzset()


@pytest.fixture
def sessions():
    out = claude_code.load(root=str(CORPUS / "claude"))
    out += codex.load(root=str(CORPUS / "codex"), archive_root="", index_path=str(CORPUS / "no-index.jsonl"))
    return out


def test_the_corpus_loads_as_expected(sessions):
    assert sorted(s.sid for s in sessions) == ["cdx-1", "cdx-2", "cdx-3", "sess-a", "sess-b", "sess-c"]


def test_spend_total_subagents_and_unpriced(sessions):
    wide = spend.session_rows(DAYS + 1, sessions=sessions, grok_rows=[])
    win = spend.window_totals(wide, DAYS, TODAY)
    assert win["total_usd"] == pytest.approx(TOTAL)                                         # 6.39
    assert win["sub_usd"] == pytest.approx(SUB)                                             # 1.60
    assert win["by_harness"]["claude-code"] == pytest.approx(CLAUDE)                        # 5.58
    assert win["by_harness"]["codex"] == pytest.approx(CODEX)                               # 0.81
    assert win["unpriced"] == UNPRICED
    text = spend.render(dict(spend.report(DAYS, rows=wide, actions=[], bills={}), top_sessions=[]))
    assert "unpriced: mystery-model-1 — 10,000 tokens" in text
    assert "unpriced: gpt-9-prototype — 6,000 tokens" in text
    assert "window: the last 7 local days (2026-11-14 to 2026-11-20)" in text


def test_monitor_cost_and_tokens_equal_spend(sessions):
    m = monitor.metrics(sessions, DAYS)
    assert m["cost_estimate_usd"] == pytest.approx(TOTAL, abs=0.005)                        # 6.39: the same number as spend
    assert costing.tokens_of(m["tokens"]) == TOKENS             # the 1-hour cache share is a subset of the writes
    assert m["cost_unpriced_tokens"] == UNPRICED and m["cost_models_unknown"] == ["gpt-9-prototype", "mystery-model-1"]
    from teyla import report
    md = report.markdown(m, [])
    assert "unpriced: mystery-model-1 — 10,000 tokens" in md and "unpriced: gpt-9-prototype — 6,000 tokens" in md
    assert "| API-equivalent cost (list prices; on a subscription this is what you would have paid) | $6 |" in md


def test_lanes_total_equals_the_subagent_part_of_spend(sessions):
    rep = lanes.report(DAYS, root=str(CORPUS / "claude"), ledger=CORPUS / "no-ledger.tsv", now=NOW)
    assert rep["units"] == 2                                                               # agent-1 and agent-2; agent-9 is outside
    assert rep["total_usd"] == pytest.approx(SUB)                                           # 1.60: one a-s1, a-s0 and the retry not counted
    rows = {r["model"]: r for r in rep["rows"]}
    assert rows["claude-opus-5-5"]["units"] == 1 and rows["claude-opus-5-5"]["total_usd"] == pytest.approx(1.6)
    assert rows["mystery-model-1"]["total_usd"] == 0
    assert rep["unpriced"] == {"mystery-model-1": 10_000}
    text = lanes.render(rep)
    assert "unpriced: mystery-model-1 — 10,000 tokens" in text
    assert "window: the last 7 local days (2026-11-14 to 2026-11-20)" in text
    wide = spend.session_rows(DAYS + 1, sessions=sessions, grok_rows=[])
    assert rep["total_usd"] == pytest.approx(spend.window_totals(wide, DAYS, TODAY)["sub_usd"])


def test_a_session_outside_the_window_is_in_none_of_them(sessions):
    # b-m1 would be $50 and agent-9 $40 if the window leaked; the 11-02 Codex session $27.
    wide = spend.session_rows(DAYS + 1, sessions=sessions, grok_rows=[])
    assert not any(r["sid"] in ("sess-b", "cdx-3") for r in wide)
    assert all(u["agent"] != "agent-9" for u in lanes.scan(DAYS, root=str(CORPUS / "claude"), now=NOW))


def test_an_unpriced_model_is_a_line_not_a_silent_zero():
    ledger = costing.Ledger()
    assert ledger.add("claude-sonnet-5-5", {"input_tokens": 1_000_000}) == pytest.approx(2.0)
    assert ledger.add("mystery-model-1", {"input_tokens": 3, "output_tokens": 4}) == 0.0
    assert ledger.add("<synthetic>", {}) == 0.0                                            # no tokens: no line
    assert ledger.lines() == ["unpriced: mystery-model-1 — 7 tokens (no list price in the table; not in the total)"]


def test_gpt_6_1_terra_has_a_price():
    # It was missing: `teyla monitor` printed "unknown: gpt-6.1-terra" while `teyla models` listed $1 / $5.
    assert pricing.cost_usd("gpt-6.1-terra", {"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(6.0)

"""monitor.metrics() shape + advise() A1 (subagent inherit) finding, built from hand-rolled Sessions."""
from __future__ import annotations

from collections import Counter

from teyla.adapters import AgentCall, Session, Turn
from teyla.advise import advise
from teyla.monitor import metrics


def _session(sid, model="claude-sonnet-5", n_agents_inherit=0, n_agents_model=0, corr=False):
    s = Session(harness="claude-code", project="demo", sid=sid, path=f"/tmp/{sid}.jsonl", size=1000)
    s.first = "2026-01-01T00:00:00Z"
    s.last = "2026-01-01T01:00:00Z"
    s.cwd = "/Users/me/repos/demo"
    s.models[model] = 3
    s.usage[model] = Counter(input_tokens=1000, output_tokens=500,
                              cache_read_input_tokens=100, cache_creation_input_tokens=0)
    s.tools["Bash"] = 2
    s.user_turns = [Turn("2026-01-01T00:00:00Z", "do the thing", corr),
                    Turn("2026-01-01T00:30:00Z", "no, not like that", True)]
    for _ in range(n_agents_inherit):
        s.agents.append(AgentCall(None, "general-purpose", "read some files"))
    for _ in range(n_agents_model):
        s.agents.append(AgentCall("claude-haiku-4", "general-purpose", "summarize"))
    return s


def test_metrics_shape():
    sessions = [_session("s1"), _session("s2", model="claude-haiku-4")]
    m = metrics(sessions)
    assert m["n_sessions"] == 2
    for key in ("tokens", "by_model", "by_project", "by_harness", "by_day", "cost_estimate_usd",
                "user_turns", "corrections", "correction_rate", "subagents", "subagent_inherit_rate",
                "output_by_tier", "orchestrator_share", "cache_read_ratio", "giant_sessions",
                "skills", "tools", "correction_samples", "wrong_root"):
        assert key in m, key
    assert m["user_turns"] == 4
    assert m["corrections"] == 2
    assert m["tokens"]["output_tokens"] == 1000
    assert m["by_harness"]["claude-code"] == 2


def test_metrics_days_filter_excludes_old_sessions():
    import datetime as dt
    old = _session("old")
    old.first = old.last = "2020-01-01T00:00:00+00:00"
    recent = _session("recent")
    now = dt.datetime.now(dt.timezone.utc)
    recent.first = recent.last = now.isoformat()
    m = metrics([old, recent], days=7)
    assert m["n_sessions"] == 1


def test_advise_a1_subagent_inherit_finding():
    # 12 subagent calls, all inheriting the orchestrator's model with no override -> A1 fires.
    sessions = [_session(f"s{i}", n_agents_inherit=1) for i in range(12)]
    m = metrics(sessions)
    assert m["subagents"]["inherit"] == 12
    findings = advise(m)
    ids = [f["id"] for f in findings]
    assert "A1" in ids
    a1 = next(f for f in findings if f["id"] == "A1")
    assert a1["severity"] == "high"
    assert "12" in a1["evidence"]


def test_advise_a1_absent_when_mostly_model_set():
    # 12 subagent calls but all with an explicit model override -> inherit rate is 0, A1 must not fire.
    sessions = [_session(f"s{i}", n_agents_model=1) for i in range(12)]
    m = metrics(sessions)
    findings = advise(m)
    assert "A1" not in [f["id"] for f in findings]


def test_advise_a1_absent_below_threshold():
    # Only 3 subagent calls total, all inherited -> below the >=10 threshold, A1 must not fire.
    sessions = [_session(f"s{i}", n_agents_inherit=1) for i in range(3)]
    m = metrics(sessions)
    findings = advise(m)
    assert "A1" not in [f["id"] for f in findings]


# --- A3: giant sessions must key off active_hours, not wall span --------------------------

def test_giant_sessions_excludes_resumed_session_with_low_active_hours():
    # Resumed three weeks later: wall span is huge (`hours`), but active_hours (the sum of
    # in-session gaps under 30 minutes) stays tiny, size is small, and there are no compactions
    # -> must NOT be classified as a giant session.
    s = _session("resumed")
    s.first = "2026-01-01T00:00:00+00:00"
    s.last = "2026-01-22T00:00:00+00:00"  # 21 days later
    s.active_hours = 0.3
    s.size = 50_000
    s.compactions = 0
    m = metrics([s])
    assert m["giant_sessions"] == []


def test_giant_sessions_includes_session_with_high_active_hours():
    s = _session("busy")
    s.first = "2026-01-01T00:00:00+00:00"
    s.last = "2026-01-01T13:00:00+00:00"
    s.active_hours = 13.0  # over the 12-hour active threshold
    s.size = 50_000
    s.compactions = 0
    m = metrics([s])
    assert len(m["giant_sessions"]) == 1
    g = m["giant_sessions"][0]
    assert g["active_hours"] == 13.0
    assert g["hours"] == 13.0  # wall span still reported alongside


def test_advise_a3_evidence_reports_both_span_and_active_hours():
    s = _session("busy2")
    s.first = "2026-01-01T00:00:00+00:00"
    s.last = "2026-01-05T00:00:00+00:00"  # 4-day wall span
    s.active_hours = 15.0
    s.size = 50_000
    m = metrics([s])
    findings = advise(m)
    a3 = next(f for f in findings if f["id"] == "A3")
    assert "span h" in a3["evidence"]
    assert "active h" in a3["evidence"]
    assert "15.0 active h" in a3["evidence"]


# --- A8: policy_status None (not installed) must not count as missing ---------------------

def test_advise_a8_fires_only_for_explicit_false_not_none():
    m = metrics([_session("s1")])
    findings = advise(m, policy_status={"policy-file": True, "claude-code": True,
                                         "codex": False, "grok": None})
    a8 = next(f for f in findings if f["id"] == "A8")
    assert "codex" in a8["evidence"]
    assert "grok" not in a8["evidence"]


def test_advise_a8_absent_when_only_not_installed_harnesses_are_missing():
    m = metrics([_session("s1")])
    findings = advise(m, policy_status={"policy-file": True, "claude-code": True, "grok": None})
    assert "A8" not in [f["id"] for f in findings]


# --- A12: connector-heavy work suppresses A2/A4 and fires instead --------------------------

def _connector_heavy_session():
    s = _session("connector-heavy", model="claude-fable-5")  # orchestrate-tier, per pricing.PRICES
    # Drive orchestrator_share and cache_read_ratio well above the A2/A4 thresholds.
    s.usage["claude-fable-5"] = Counter(input_tokens=1000, output_tokens=2_000_000,
                                         cache_read_input_tokens=400_000_000, cache_creation_input_tokens=0)
    s.tools = Counter({"mcp__jira__search": 40, "mcp__jira__read": 30, "Bash": 10, "Read": 10})
    return s


def _use_builtin_prices_only(monkeypatch, tmp_path):
    # A real ~/.teyla/prices.json (written by `teyla models --write-prices`) may exist on the
    # machine running the suite and may not agree with pricing.PRICES's tier for a given model
    # (e.g. models.dev doesn't know POLICY.md's orchestrate/volume/triage split). Point the
    # override path at an empty tmp file so these tests see only the built-in table.
    from teyla import pricing
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", tmp_path / "no-prices.json")


def test_advise_a12_fires_and_suppresses_a2_a4_when_connector_heavy(monkeypatch, tmp_path):
    _use_builtin_prices_only(monkeypatch, tmp_path)
    m = metrics([_connector_heavy_session()])
    assert m["connector_share"] > 0.5
    findings = advise(m)
    ids = [f["id"] for f in findings]
    assert "A12" in ids
    assert "A2" not in ids
    assert "A4" not in ids
    a12 = next(f for f in findings if f["id"] == "A12")
    assert "77" in a12["evidence"] and "%" in a12["evidence"]


def test_advise_a2_a4_fire_normally_when_not_connector_heavy(monkeypatch, tmp_path):
    _use_builtin_prices_only(monkeypatch, tmp_path)
    s = _connector_heavy_session()
    s.tools = Counter({"Bash": 40, "Read": 30, "mcp__jira__search": 5})  # connector share well under 0.5
    m = metrics([s])
    assert m["connector_share"] < 0.5
    findings = advise(m)
    ids = [f["id"] for f in findings]
    assert "A12" not in ids
    assert "A2" in ids
    assert "A4" in ids


# --- A3: one human turn is one logical unit — size alone cannot make it giant -----------------

def test_giant_sessions_exempts_single_turn_session_on_size_alone():
    s = _session("autonomous")
    s.size = 20_000_000  # 20 MB, but one human turn, under an hour, no compactions
    s.active_hours = 0.9
    s.compactions = 0
    s.user_turns = s.user_turns[:1]
    assert s.n_user == 1
    assert metrics([s])["giant_sessions"] == []


def test_giant_sessions_keeps_single_turn_session_that_ran_long_or_compacted():
    long_run = _session("long"); long_run.size = 20_000_000; long_run.active_hours = 13.0; long_run.compactions = 0
    long_run.user_turns = long_run.user_turns[:1]
    compacted = _session("compacted"); compacted.size = 500; compacted.active_hours = 0.5; compacted.compactions = 3
    compacted.user_turns = compacted.user_turns[:1]
    multi = _session("multi"); multi.size = 20_000_000; multi.active_hours = 0.9; multi.compactions = 0  # two turns
    sids = {g["sid"] for g in metrics([long_run, compacted, multi])["giant_sessions"]}
    assert sids == {"long", "compacte", "multi"}  # sids are cut to 8 chars; the two-turn 20 MB one is giant on size

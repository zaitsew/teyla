"""teyla grok-cost against a tiny synthetic sessions tree (the record shapes are the real ones)."""
from __future__ import annotations

import datetime as dt
import json
import os
import urllib.parse

import pytest

from teyla import grokcost
from teyla.adapters import grok
from teyla.cli import main

NOW = dt.datetime.now(dt.timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - dt.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")


def _turn(sid, cost_usd, calls=2, inp=1000, cached=600, out=50):
    usage = {"inputTokens": inp, "outputTokens": out, "totalTokens": inp + out, "cachedReadTokens": cached,
             "reasoningTokens": 5, "modelCalls": calls, "costUsdTicks": int(cost_usd * 1e10),
             "modelUsage": {"grok-4.7-build": {"inputTokens": inp, "costUsdTicks": int(cost_usd * 1e10)}}}
    return {"timestamp": 1790000000, "method": "_x.ai/session/update", "params": {"sessionId": sid, "update": {
        "sessionUpdate": "turn_completed", "stop_reason": "end_turn", "usage": usage}}}


def _session(root, cwd, sid, days_ago, turns=(), title="a lane", tools=7, context=50_000, noise=True):
    d = root / urllib.parse.quote(cwd, safe="") / sid
    os.makedirs(d)
    (d / "summary.json").write_text(json.dumps({
        "info": {"id": sid, "cwd": cwd}, "created_at": _iso(days_ago), "generated_title": title,
        "current_model_id": "grok-4.7", "reasoning_effort": "high"}))
    (d / "signals.json").write_text(json.dumps({"toolCallCount": tools, "contextTokensUsed": context}))
    lines = []
    if noise:  # streamed chunks and a failed turn: neither is a usage-bearing turn_completed
        lines.append({"params": {"update": {"sessionUpdate": "agent_message_chunk", "text": "turn_completed"}}})
        lines.append({"params": {"update": {"sessionUpdate": "turn_completed", "stop_reason": "error",
                                            "agent_result": "API error (status 402)"}}})
    lines += [_turn(sid, c) for c in turns]
    (d / "updates.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return d


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    home = "/Users/me"
    monkeypatch.setenv("HOME", home)
    _session(root, f"{home}/repos/frank", "aaaa1111-0000", 1, turns=(1.5, 2.5))
    _session(root, f"{home}/.worktrees/frank/lane-a", "aaaa2222-0000", 2, turns=(3.0,))
    _session(root, f"{home}/repos/loco", "bbbb1111-0000", 1, turns=(12.0,), title="big lane")
    _session(root, "/private/tmp/claude-501/x/scratchpad/grok-empty", "cccc1111-0000", 3, turns=(0.5,))
    _session(root, f"{home}/repos/frank", "dddd1111-0000", 30, turns=(99.0,))          # outside the week
    _session(root, f"{home}/repos/frank", "eeee1111-0000", 0.1, turns=())             # errored, no usage
    return root


def test_read_usage_sums_only_usage_bearing_turn_completed(store):
    u = grok.read_usage(str(store / urllib.parse.quote("/Users/me/repos/frank", safe="") / "aaaa1111-0000"))
    assert u["turns"] == 2 and u["calls"] == 4
    assert u["ticks"] == int(1.5e10) + int(2.5e10)
    assert u["input"] == 2000 and u["cached"] == 1200 and u["output"] == 100


def test_last_under_cwd(store):
    (c,) = grok.session_costs(root=str(store), cwd="/Users/me/repos/frank", last=True)
    assert c.sid == "eeee1111-0000"  # newest by write time, billed or not
    (c,) = grok.session_costs(root=str(store), cwd="/Users/me/repos/loco", last=True)
    assert c.usd == pytest.approx(12.0) and c.tool_calls == 7 and c.context == 50_000
    assert c.effort == "high" and c.title == "big lane" and c.cached_pct == 60.0


def test_cwd_matches_path_or_below_only(store):
    rows = grok.session_costs(root=str(store), cwd="/Users/me/repos")
    assert {c.sid[:4] for c in rows} == {"aaaa", "bbbb", "dddd", "eeee"}
    assert not grok.session_costs(root=str(store), cwd="/Users/me/rep")  # a prefix of a name is not a parent


def test_project_of_collapses_worktrees_repos_and_temp():
    p = lambda c: grokcost.project_of(c, home="/Users/me")
    assert p("/Users/me/.worktrees/frank/lane-a") == "frank"
    assert p("/Users/me/.worktrees/frank/lane-a/sub") == "frank"
    assert p("/Users/me/repos/frank") == "frank"
    assert p("/Users/me/repos/frank/.claude/worktrees/x") == "frank"
    assert p("/private/var/folders/x/T/frank-grok-empty") == "frank"
    assert p("/private/tmp/claude-501/x/scratchpad/grok-empty") == "tmp"
    assert p("/private/tmp/claude-501/scratch") == "tmp"
    assert p("/Users/me/ops/startup") == "ops"
    assert p("/opt/thing") == "/opt/thing"


def test_by_project_ranks_by_dollars_and_skips_unbilled(store):
    from teyla.adapters import since_epoch
    rows = grok.session_costs(root=str(store), since=since_epoch(7))
    t = grokcost.by_project(rows)
    assert [r["project"] for r in t] == ["loco", "frank", "tmp"]
    frank = t[1]
    assert frank["usd"] == pytest.approx(7.0) and frank["sessions"] == 2  # the errored and the 30-day one are out
    assert sum(r["share"] for r in t) == pytest.approx(1.0)
    assert t[0]["share"] == pytest.approx(12 / 19.5)


def test_cli_last_line_and_json(store, monkeypatch, capsys):
    monkeypatch.setattr(grok, "DEFAULT_ROOT", str(store))
    assert main(["grok-cost", "--last", "--cwd", "/Users/me/repos/loco"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("$12.00 · 2 calls · in 1k (60% cached) · out 50 · 7 tools · ctx 50k · effort high · grok-4.7 · bbbb1111")
    assert out.endswith("big lane") and "\n" not in out
    assert main(["grok-cost", "--last", "--cwd", "/Users/me/repos/loco", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["usd"] == 12.0


def test_cli_unbilled_last_says_so(store, monkeypatch, capsys):
    monkeypatch.setattr(grok, "DEFAULT_ROOT", str(store))
    assert main(["grok-cost", "--last", "--cwd", "/Users/me/repos/frank"]) == 0
    assert "no billed turn" in capsys.readouterr().out


def test_cli_week_by_project_and_by_session(store, monkeypatch, capsys):
    monkeypatch.setattr(grok, "DEFAULT_ROOT", str(store))
    assert main(["grok-cost", "--days", "7"]) == 0
    out = capsys.readouterr().out
    rows = [l.split() for l in out.splitlines()[2:]]
    assert [r[0] for r in rows] == ["loco", "frank", "tmp", "total"]
    assert rows[0][2] == "$12.00" and rows[-1][2] == "$19.50"
    assert main(["grok-cost", "--by", "session", "--json"]) == 0
    top = json.loads(capsys.readouterr().out)
    assert [t["sid"][:4] for t in top] == ["bbbb", "aaaa", "aaaa", "cccc"] and len(top) == 4


def test_cli_session_prefix_and_missing(store, monkeypatch, capsys):
    monkeypatch.setattr(grok, "DEFAULT_ROOT", str(store))
    assert main(["grok-cost", "--session", "aaaa2222"]) == 0
    assert capsys.readouterr().out.startswith("$3.00 · 2 calls")
    assert main(["grok-cost", "--session", "aaaa"]) == 1  # two match
    assert main(["grok-cost", "--session", "zzzz"]) == 1


def test_missing_store_is_an_error_not_a_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(grok, "DEFAULT_ROOT", str(tmp_path / "nope"))
    assert main(["grok-cost"]) == 1
    assert grokcost.week(root=str(tmp_path / "nope")) is None


def test_advice_project_share_and_expensive_session(store):
    w = grokcost.week(root=str(store))
    assert w["top_project"] == "loco" and w["top_project_share"] == pytest.approx(12 / 19.5)
    ids = {f["id"] for f in grokcost.advise(w)}
    assert ids == {"A13", "A14"}  # 62% of the week, and one $12 session
    calm = dict(w, top_project_share=0.4, top_session=dict(w["top_session"], usd=9.99))
    assert grokcost.advise(calm) == []
    assert grokcost.advise(dict(w, total_usd=4.0, top_session=dict(w["top_session"], usd=3.0))) == []  # a small week is not a finding
    assert grokcost.advise(None) == []

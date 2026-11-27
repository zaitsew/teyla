"""A Codex orchestrator and the agents it spawned: each rollout keyed by its own id, `teyla spend --session`
splitting the orchestrator from its workers, `teyla lanes` listing the workers by role and model.
All data is invented; the home directory is never read."""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os

import pytest

from teyla import lanes, pricing, spend
from teyla.adapters import codex

PARENT = "aaaa1111-0000-4000-8000-000000000001"
KID1 = "aaaa2222-0000-4000-8000-000000000002"
KID2 = "aaaa3333-0000-4000-8000-000000000003"
OTHER = "bbbb1111-0000-4000-8000-000000000004"
NOW = _dt.datetime.now(_dt.timezone.utc)
TS = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rollout(root, sid, meta, model, out_tokens, user="do it"):
    day = root / f"{NOW:%Y}" / f"{NOW:%m}" / f"{NOW:%d}"
    day.mkdir(parents=True, exist_ok=True)
    recs = [{"type": "session_meta", "timestamp": TS, "payload": dict(meta, cwd="/work/app")}]
    if model:
        recs.append({"type": "turn_context", "timestamp": TS, "payload": {"model": model}})
    recs.append({"type": "response_item", "timestamp": TS, "payload": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": user}]}})
    recs.append({"type": "response_item", "timestamp": TS, "payload": {
        "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "done"}]}})
    recs.append({"type": "event_msg", "timestamp": TS, "payload": {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 0, "output_tokens": out_tokens}}}})
    stamp = f"{NOW:%Y-%m-%dT%H-%M-%S}"
    (day / f"rollout-{stamp}-{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in recs) + "\n")


def _kid(parent, sid, role, nick):
    return {"session_id": parent, "id": sid, "parent_thread_id": parent, "thread_source": "subagent",
            "agent_nickname": nick, "agent_role": role, "originator": "Codex Desktop",
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent, "depth": 1}}}}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(pricing, "OVERRIDE_PATH", tmp_path / "no-prices.json")
    root = tmp_path / "sessions"
    _rollout(root, PARENT, {"session_id": PARENT, "id": PARENT, "originator": "Codex Desktop"}, "gpt-6.2-astra", 10_000)
    _rollout(root, KID1, _kid(PARENT, KID1, "volume", "Ada"), "gpt-6.1-sol", 40_000)
    _rollout(root, KID2, _kid(PARENT, KID2, "scout", "Bo"), None, 20_000)   # no turn_context: role -> model
    _rollout(root, OTHER, {"id": OTHER, "originator": "Codex Desktop"}, "gpt-6.2-astra", 5_000)
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "scout.toml").write_text('name = "scout"\nmodel = "gpt-6-luna"\n')
    monkeypatch.setattr(codex, "DEFAULT_ROOT", str(root))
    monkeypatch.setattr(codex, "DEFAULT_ARCHIVE_ROOT", "")
    monkeypatch.setattr(codex, "DEFAULT_INDEX", str(tmp_path / "none.jsonl"))
    monkeypatch.setattr(codex, "DEFAULT_AGENTS_DIR", str(agents))
    real = spend.session_rows
    monkeypatch.setattr(spend, "session_rows",
                        lambda days=7, sessions=None, grok_rows=None: real(days, sessions=codex.load(), grok_rows=[]))
    return root


def test_each_rollout_has_its_own_id_and_names_its_parent(store):
    by = {s.sid: s for s in codex.load()}
    assert set(by) == {PARENT, KID1, KID2, OTHER}
    assert by[PARENT].parent_sid is None
    assert by[KID1].parent_sid == PARENT and by[KID1].agent_role == "volume" and by[KID1].agent_nickname == "Ada"
    assert by[OTHER].parent_sid is None


def test_spawn_agent_records_the_role(tmp_path):
    f = tmp_path / "rollout-2026-01-01T00-00-00-cccc.jsonl"
    recs = [{"type": "session_meta", "timestamp": TS, "payload": {"id": "cccc", "cwd": "/work/app"}},
            {"type": "response_item", "timestamp": TS, "payload": {
                "type": "function_call", "name": "collaboration.spawn_agent",
                "arguments": json.dumps({"agent_type": "volume", "task_name": "evidence"})}}]
    f.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    s = codex.parse(str(f))
    assert [(a.model, a.role, a.desc) for a in s.agents] == [(None, "volume", "evidence")]


def test_session_splits_orchestrator_from_workers(store, capsys):
    rows = {r["sid"]: r for r in spend.session_rows(7)}
    assert len(rows) == 4 and rows[KID1]["role"] == "volume" and rows[KID1]["parent_sid"] == PARENT
    d = spend.session_detail(rows[PARENT], [rows[KID1], rows[KID2]])
    own, wk = rows[PARENT]["usd"], rows[KID1]["usd"] + rows[KID2]["usd"]
    assert d["orchestrator_usd"] == pytest.approx(own) and d["workers_usd"] == pytest.approx(wk)
    assert d["total_usd"] == pytest.approx(own + wk) and d["session_usd"] == pytest.approx(own)
    assert d["workers_share"] == pytest.approx(wk / (own + wk))
    models = {w["nickname"]: w["model"] for w in d["workers"]}
    assert models == {"Ada": "gpt-6.1-sol", "Bo": "gpt-6-luna"}
    text = spend.render_session(d)
    assert "orchestrator $" in text and "workers $" in text and "Ada" in text and "gpt-6-luna" in text


def test_a_prefix_of_one_parent_and_its_children_is_not_ambiguous(store, capsys):
    args = argparse.Namespace(session="aaaa", days=7, json=True)
    assert spend.cmd_session(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["id"] == PARENT and len(out["workers"]) == 2
    # a worker's id resolves to its parent; a prefix shared by two unrelated sessions still exits 2
    assert spend.cmd_session(argparse.Namespace(session=KID1[:8], days=7, json=True)) == 0
    assert json.loads(capsys.readouterr().out)["id"] == PARENT
    assert spend.cmd_session(argparse.Namespace(session="a", days=7, json=True)) == 0
    capsys.readouterr()
    assert spend.cmd_session(argparse.Namespace(session="", days=7, json=True)) == 1


def test_unrelated_sessions_sharing_a_prefix_stay_ambiguous(store, capsys):
    _rollout(store, "aaaa9999-0000-4000-8000-000000000009", {"id": "aaaa9999-0000-4000-8000-000000000009"}, "gpt-6.2-astra", 1)
    assert spend.cmd_session(argparse.Namespace(session="aaaa", days=7, json=False)) == 2


def test_lanes_lists_codex_workers_by_role_and_model(store, tmp_path):
    rep = lanes.report(7, codex_root=str(store), agents_dir=codex.DEFAULT_AGENTS_DIR, ledger=tmp_path / "none.tsv")
    got = {(r["type"], r["model"], r["units"]) for r in rep["rows"]}
    assert got == {("codex/volume", "gpt-6.1-sol", 1), ("codex/scout", "gpt-6-luna", 1)}
    assert "codex/volume" in lanes.render(rep)

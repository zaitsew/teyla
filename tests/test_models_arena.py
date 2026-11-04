"""teyla models arena: a pasted snapshot, the one GET behind --refresh, and the bot check Teyla does not pass.
A tmp HOME and a fake page; nothing reads the real ~/.teyla or the network."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from teyla import cli, config, models_arena as arena, net

TODAY = dt.date(2026, 11, 4)
POLICY_LADDER = {"anthropic": {"orchestrate": ["Orbit Large 2"], "volume": ["Orbit Mid 1.5 (default worker)"], "triage": []}}


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    (tmp_path / ".teyla").mkdir()
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "TEYLA_DIR", tmp_path / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / ".teyla" / "config.toml")
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    monkeypatch.setattr(net, "_allow_once", False)
    return tmp_path


def paste(entries, as_of="2026-11-03", **kw):
    p = arena.snapshot_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(as_of=as_of, source="pasted", entries=entries, **kw)))


ENTRIES = [dict(model="Orbit Mid 1.5", score=1400, cost=0.3, pareto=True),
           dict(model="Orbit Large 2", score=1500, cost=2.0, pareto=True),
           dict(model="Delta Small 3", score=1300, cost=0.1, pareto=False),
           dict(model="Nova 9", score=1450, cost=0.9, pareto=True), dict(score=1)]


def test_nothing_pasted_and_nothing_fetched_says_how_to_paste():
    b = arena.load(TODAY)
    assert b["entries"] == [] and "arena.json" in b["note"]


def test_a_pasted_snapshot_loads_and_drops_rows_without_a_model():
    paste(ENTRIES)
    b = arena.load(TODAY)
    assert b["as_of"] == "2026-11-03" and len(b["entries"]) == 4 and b["stale"] is False


def test_an_old_snapshot_is_stale_and_a_broken_one_is_nothing():
    paste(ENTRIES, as_of="2026-09-01")
    assert arena.load(TODAY)["stale"] is True
    arena.snapshot_path().write_text("{not json")
    assert arena.load(TODAY)["entries"] == []
    paste(ENTRIES, as_of="soon")
    assert arena.load(TODAY)["entries"] == []


def test_the_shortlist_puts_pareto_first_marks_the_ladder_and_decides_nothing():
    paste(ENTRIES)
    rows = arena.shortlist(arena.load(TODAY), POLICY_LADDER)
    assert [r["model"] for r in rows] == ["Orbit Large 2", "Nova 9", "Orbit Mid 1.5", "Delta Small 3"]
    assert {r["model"]: r["in_ladder"] for r in rows} == {"Orbit Large 2": True, "Nova 9": False, "Orbit Mid 1.5": True,
                                                          "Delta Small 3": False}
    assert all(r["status"] == "candidate, not a decision" for r in rows)


CHALLENGE = "<html><head><title>Just a moment...</title></head><body>Enable JavaScript and cookies to continue</body></html>"


def test_a_bot_check_reads_nothing_and_says_so(monkeypatch):
    monkeypatch.setattr(arena, "_get", lambda url: (403, {"cf-mitigated": "challenge"}, CHALLENGE))
    rep = arena.refresh(TODAY)
    assert rep["status"] == "blocked" and rep["http"] == 403 and "snapshot" not in rep
    b = arena.load(TODAY)
    assert b["entries"] == [] and "bot check" in b["note"] and b["last_fetch"]["status"] == "blocked"


def test_a_challenge_page_with_status_200_is_still_a_bot_check(monkeypatch):
    monkeypatch.setattr(arena, "_get", lambda url: (200, {}, CHALLENGE))
    assert arena.refresh(TODAY)["status"] == "blocked"


def test_a_blocked_fetch_leaves_the_pasted_snapshot_in_charge(monkeypatch):
    paste(ENTRIES)
    monkeypatch.setattr(arena, "_get", lambda url: (403, {}, CHALLENGE))
    arena.refresh(TODAY)
    assert len(arena.load(TODAY)["entries"]) == 4


def page(rows):
    return '<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"rows": rows}}) + "</script></html>"


def test_a_page_with_embedded_json_rows_is_read(monkeypatch):
    rows = [dict(modelName=f"Model {i}", score=1000 + i, costPerTask=i / 10) for i in range(5)]
    monkeypatch.setattr(arena, "_get", lambda url: (200, {}, page(rows)))
    rep = arena.refresh(TODAY)
    assert rep["status"] == "ok" and len(rep["snapshot"]["entries"]) == 5
    assert arena.load(TODAY)["source"] == "fetched"


def test_a_page_with_no_table_is_unreadable_not_guessed(monkeypatch):
    monkeypatch.setattr(arena, "_get", lambda url: (200, {}, "<html><body><div>chart</div></body></html>"))
    assert arena.refresh(TODAY)["status"] == "unreadable"
    monkeypatch.setattr(arena, "_get", lambda url: (200, {}, page([dict(model="A", score=1)])))
    assert arena.refresh(TODAY)["status"] == "unreadable"


def test_a_network_error_is_a_status(monkeypatch):
    def boom(url):
        raise OSError("no route")
    monkeypatch.setattr(arena, "_get", boom)
    assert arena.refresh(TODAY)["status"] == "offline"


def test_safe_mode_refuses_before_any_request(monkeypatch):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    called = []
    monkeypatch.setattr(arena, "_get", lambda url: called.append(url))
    assert arena.refresh(TODAY)["status"] == "safe_mode" and not called
    assert not arena.fetched_path().exists()


def test_the_cli_prints_the_shortlist_and_json(monkeypatch, capsys):
    paste(ENTRIES)
    monkeypatch.setattr("teyla.policy.POLICY", arena.snapshot_path().parent / "no-policy.md")
    assert cli.main(["models", "arena"]) == 0
    out = capsys.readouterr().out
    assert "candidate, not a decision" in out and "Nothing switches by itself" in out
    assert cli.main(["models", "arena", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["shortlist"][0]["status"] == "candidate, not a decision"


def test_the_cli_exits_1_with_nothing_to_show(capsys, monkeypatch):
    monkeypatch.setattr("teyla.policy.POLICY", arena.snapshot_path().parent / "no-policy.md")
    assert cli.main(["models", "arena"]) == 1
    assert "paste a snapshot" in capsys.readouterr().out


def test_a_one_token_ladder_name_keeps_its_provider_word():
    ladder = {"xai": {"orchestrate": ["Grok 4.7"], "volume": ["Grok 4.7 (build-fast)"], "triage": []}}
    assert arena.in_ladder("Grok 4.7", ladder) is True
    assert arena.in_ladder("Nova 4.7", ladder) is False
    assert arena.in_ladder("Claude Opus 5.5", {"a": {"orchestrate": ["Opus 5.5"]}}) is True


def test_a_safe_mode_refusal_keeps_stdout_valid_json(monkeypatch, capsys):
    paste(ENTRIES)
    monkeypatch.setattr("teyla.policy.POLICY", arena.snapshot_path().parent / "no-policy.md")
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert cli.main(["models", "arena", "--refresh", "--json"]) == 0
    cap = capsys.readouterr()
    assert json.loads(cap.out)["attempt"]["status"] == "safe_mode" and cap.err.strip()

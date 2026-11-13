"""`teyla brief slots`: the sprint slots. Contracts are real files under a tmp TEYLA_DIR; asks, design cards,
the testflight cache and the session stores are stubbed. No network call, no real ~/.teyla."""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from teyla import asks, brief, cli, config, design_cycle, slots, testflight
from teyla.ui import Style

NOW = dt.datetime(2026, 11, 11, 12, 0, tzinfo=dt.timezone.utc).timestamp()
PLAIN = Style(env={"NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def machine(tmp_path, monkeypatch):
    monkeypatch.setattr(slots, "_now", lambda: NOW)
    monkeypatch.setattr(brief, "_now", lambda: dt.datetime.fromtimestamp(NOW, dt.timezone.utc))
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    monkeypatch.setattr(config, "TEYLA_DIR", tmp_path / "teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "teyla" / "config.toml")
    st = {"asks": [], "cards": [], "builds": None, "recent": []}
    monkeypatch.setattr(asks, "collect", lambda *a, **k: list(st["asks"]))
    monkeypatch.setattr(design_cycle, "open_cards", lambda: list(st["cards"]))
    monkeypatch.setattr(testflight, "load_cache", lambda now=None: (st["builds"], 3600.0))
    monkeypatch.setattr(slots, "recent_products", lambda now: list(st["recent"]))
    return st


def contract(product, *, hours_ago=2.0, hours=8.0, gates=("gate one",), closed=False, goal="Ship the thing"):
    started = dt.datetime.fromtimestamp(NOW - hours_ago * 3600, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = brief.briefs_dir() / product
    d.mkdir(parents=True, exist_ok=True)
    c = {"product": product, "started": started, "goal": goal, "slice": "", "platform": "ios", "usd": 10.0,
         "hours": hours, "gates": list(gates), "repo": "/x", "sessions": []}
    if closed:
        c["closed"] = started
    (d / "c.toml").write_text(brief.dumps(c))
    (d / "active").write_text("c.toml\n")


def ask(id_, product, days_ago=3.0, title="Pick a font"):
    return asks.Ask(id=id_, kind="question", product=product, title=title, question="Which?", context="", options=[],
                    when=NOW - days_ago * 86400, archived=False, link="", pr="", harness="claude-code", status="open")


def card(product, title="Onboarding look"):
    return {"repo": pathlib.Path("/nope") / product, "product": product, "decision": "d1", "title": title}


def build_rows(product):
    return [{"product": product, "payload": {"platforms": [{"platform": "IOS",
             "newest_uploaded": {"build": "7", "uploaded": "2026-11-10T08:00:00Z"},
             "newest_installable": {"build": "7"}}]}}]


def run(capsys, *argv):
    assert cli.main(["brief", "slots", *argv]) == 0
    return capsys.readouterr().out


def test_no_contracts(capsys):
    out = run(capsys)
    assert "0 of 2 in flight" in out and "No sprint contract is open" in out and "WARN" not in out


def test_two_contracts_no_warning():
    contract("alpha"); contract("beta")
    s = slots.snapshot(NOW)
    assert s["in_flight"] == 2 and s["over_limit"] is False and s["limit"] == 2
    assert "WARN" not in slots.render(s, PLAIN)


def test_three_contracts_warn():
    for p in ("alpha", "beta", "gamma"):
        contract(p)
    s = slots.snapshot(NOW)
    text = slots.render(s, PLAIN)
    assert s["over_limit"] is True and s["in_flight"] == 3
    assert "WARN  3 sprints in flight; the limit is two. Close one with `teyla brief <product> --close`" in text


def test_closed_contract_not_counted():
    contract("alpha"); contract("beta", closed=True)
    assert slots.snapshot(NOW)["in_flight"] == 1


def test_overdue_contract_still_counted():
    contract("alpha", hours_ago=30, hours=8)
    s = slots.snapshot(NOW)
    row = s["slots"][0]
    assert s["in_flight"] == 1 and row["overdue"] is True and row["hours_elapsed"] == 30.0
    assert "overdue: 30h elapsed of 8h" in slots.render(s, PLAIN)


def test_waits_at_kinds_and_order(machine):
    contract("alpha")
    machine["cards"] = [card("alpha")]
    machine["asks"] = [ask("a1", "alpha", 2), ask("a2", "alpha", 9, "Old one"), ask("a3", "other")]
    machine["builds"] = build_rows("alpha")
    row = slots.snapshot(NOW)["slots"][0]
    assert [w["kind"] for w in row["waiting"]] == ["gate", "decision", "question", "build"]
    assert row["waits_at"] == {"kind": "gate", "text": "gates: gate one"}
    q = row["waiting"][2]
    assert q["count"] == 2 and q["age_days"] == 9 and "Old one" in q["text"]
    text = slots.render(slots.snapshot(NOW), PLAIN)
    assert "waits at: gates: gate one" in text and "also: build 7 on" in text


def test_each_kind_alone_and_agents_working(machine):
    contract("alpha", gates=())
    assert slots.snapshot(NOW)["slots"][0]["waits_at"]["kind"] == "agents"
    machine["asks"] = [ask("a1", "alpha")]
    assert slots.snapshot(NOW)["slots"][0]["waits_at"]["kind"] == "question"
    machine["cards"] = [card("alpha")]
    assert slots.snapshot(NOW)["slots"][0]["waits_at"]["kind"] == "decision"
    machine["builds"] = build_rows("beta")                       # another product's build does not count
    assert [w["kind"] for w in slots.snapshot(NOW)["slots"][0]["waiting"]] == ["decision", "question"]


def test_no_contract_list_and_note(machine):
    contract("alpha"); contract("beta")
    machine["recent"] = [{"product": "alpha", "last_active": NOW - 600}, {"product": "fixer", "last_active": NOW - 3600}]
    s = slots.snapshot(NOW)
    assert [r["product"] for r in s["no_contract"]] == ["fixer"] and s["over_limit"] is False
    text = slots.render(s, PLAIN)
    assert "Also active, no contract" in text and 'teyla brief <product> --goal "..." --gate "..."' in text
    assert "Note: 2 contracts and 1 sessions without one" in text and "WARN" not in text


def test_no_note_within_limit(machine):
    contract("alpha")
    machine["recent"] = [{"product": "fixer", "last_active": NOW - 60}]
    assert "Note:" not in slots.render(slots.snapshot(NOW), PLAIN)


def test_config_limit_override():
    for p in ("alpha", "beta", "gamma"):
        contract(p)
    config.CONFIG_PATH.write_text("[slots]\nlimit = 3\n")
    s = slots.snapshot(NOW)
    assert s["limit"] == 3 and s["over_limit"] is False
    config.CONFIG_PATH.write_text("[slots]\nlimit = 1\n")
    assert slots.snapshot(NOW)["over_limit"] is True


def test_brief_product_unchanged(capsys):
    contract("alpha")
    assert cli.main(["brief", "alpha"]) == 0
    assert "Sprint contract: alpha" in capsys.readouterr().out
    assert cli.main(["brief", "beta"]) == 1
    assert "no active sprint contract" in capsys.readouterr().out


def test_json_shape(capsys, machine):
    contract("alpha", gates=("g1", "g2"))
    machine["recent"] = [{"product": "fixer", "last_active": NOW - 60}]
    d = json.loads(run(capsys, "--json"))
    assert set(d) == {"version", "generated", "limit", "in_flight", "over_limit", "slots", "no_contract"}
    assert d["version"] == 1 and d["limit"] == 2 and d["over_limit"] is False
    assert set(d["slots"][0]) == {"product", "started", "age_days", "goal", "gates", "hours", "hours_elapsed",
                                  "overdue", "waits_at", "waiting"}
    assert d["slots"][0]["gates"] == ["g1", "g2"] and d["slots"][0]["age_days"] == 0
    assert d["no_contract"] == [{"product": "fixer", "last_active": "2026-11-11T11:59:00Z"}]


def test_writes_nothing(capsys, machine, tmp_path):
    contract("alpha"); contract("beta"); contract("gamma", hours_ago=40)
    machine["asks"] = [ask("a1", "alpha")]
    before = {p: p.read_bytes() for p in (tmp_path / "teyla").rglob("*") if p.is_file()}
    run(capsys); run(capsys, "--json")
    after = {p: p.read_bytes() for p in (tmp_path / "teyla").rglob("*") if p.is_file()}
    assert before == after


def test_cli_sessions_reads_recent_transcripts_only(tmp_path):
    import os
    d = tmp_path / "proj-a"
    d.mkdir()
    fresh, old = d / "s1.jsonl", d / "s2.jsonl"
    fresh.write_text('{"type": "summary"}\n{"cwd": "/work/app-a", "type": "user"}\n')
    old.write_text('{"cwd": "/work/app-b"}\n')
    now = 2_000_000_000.0
    os.utime(fresh, (now - 3600, now - 3600))
    os.utime(old, (now - 3 * 86400, now - 3 * 86400))
    assert slots.cli_sessions(now, str(tmp_path)) == [("/work/app-a", "s1", now - 3600)]

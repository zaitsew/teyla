"""`teyla product show`: one product's page. Asks and session rows are built by hand; the registry and the
notes are real files in the tmp TEYLA_HOME that conftest gives every test."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from teyla import asks, cli, figures, notes, product_page, registry

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone.utc).timestamp()
TODAY = dt.date.fromtimestamp(NOW)


@pytest.fixture(autouse=True)
def machine(monkeypatch):
    monkeypatch.setattr(figures, "now", lambda: NOW)
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    state = {"asks": [], "rows": ([], {})}
    monkeypatch.setattr(asks, "collect", lambda *a, **k: list(state["asks"]))
    monkeypatch.setattr(product_page, "load_rows", lambda days=30: state["rows"])
    # spend.by_day counts "today" as the real today; the rows below are dated from this one.
    from teyla import spend
    real = spend.by_day
    monkeypatch.setattr(spend, "by_day", lambda days=7, rows=None, today=None: real(days, rows, TODAY))
    return state


def ask(id_, product, *, days_ago=1.0, kind="question", question="Which font?", title="A session"):
    return asks.Ask(id=id_, kind=kind, product=product, title=title, question=question, context="", options=[],
                    when=NOW - days_ago * 86400, archived=False, link=f"claude://x/{id_}", pr="", harness="claude-code")


def register(**products):
    reg = registry.load()
    for pid, fields in products.items():
        reg["product"][pid] = {**registry.new_product(pid, stage="building"), **fields}
    registry.save(reg)


def row(sid, cwd, days_ago, usd, harness="claude-code", model="claude-sonnet-5-5"):
    day = (TODAY - dt.timedelta(days=days_ago)).isoformat()
    last = f"{day}T10:00:00Z"
    return dict(harness=harness, sid=sid, project="x", cwd=cwd, first=last, last=last, usd=usd, by_model={model: usd},
                sub_usd=0.0, top_tier_sub_saving=0.0, reread_usd=0.0, loop_usd=0.0, inherited_agents=0, agents=0,
                prs=0, batch=False, repos=[], day_usd={day: usd}, day_model_usd={day: {model: usd}},
                sub_day_model_usd={}, sub_calls=[])


def show(capsys, *argv):
    code = cli.main(["product", "show", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


# --- the facts ------------------------------------------------------------------------------------

def test_the_json_carries_the_product_its_questions_notes_sessions_and_spend(machine, capsys, tmp_path):
    repo = tmp_path / "app-a"
    (repo / ".git").mkdir(parents=True)
    register(**{"app-a": {"name": "App A", "stage": "beta", "primary": "ios", "focus": True, "aliases": ["appa"],
                          "repos": [str(repo)]}, "app-b": {"name": "App B"}})
    machine["asks"] = [ask("aaa00001", "app-a", days_ago=3, question="Ship 1.2 or wait?"),
                       ask("bbb00002", "app-b", question="Not this product")]
    notes.add("dark mode for App A", "app-a")
    notes.add("belongs elsewhere", "app-b")
    machine["rows"] = ([row("s1", str(repo), 0, 2.5), row("s2", str(repo / "ios"), 10, 4.0, harness="codex", model="gpt-6-1-sol"),
                        row("s3", str(tmp_path / "elsewhere"), 1, 99.0)],
                       {"s1": "Fix the login", "s2": "Add a widget", "s3": "Other work"})
    code, out, err = show(capsys, "app-a", "--json")
    assert code == 0 and err == ""
    page = json.loads(out)
    assert page["version"] == 1 and page["generated"] == "2026-10-25T12:00:00Z"
    assert page["product"] == {"id": "app-a", "name": "App A", "stage": "beta", "focus": True, "primary": "ios",
                               "repos": [str(repo)], "aliases": ["appa"], "registered": True}
    assert [a["id"] for a in page["asks"]] == ["aaa00001"]
    assert page["asks"][0] == {"id": "aaa00001", "age_s": 3 * 86400, "severity": "normal",
                               "question": "Ship 1.2 or wait?", "link": "claude://x/aaa00001"}
    assert [n["text"] for n in page["notes"]] == ["dark mode for App A"]
    assert page["notes"][0]["id"] and "created" in page["notes"][0] and page["notes"][0]["age_s"] >= 0
    assert [s["id"] for s in page["sessions"]] == ["s1", "s2"]                     # newest first, the other repo left out
    assert page["sessions"][0] == {"id": "s1", "at": f"{TODAY}T10:00:00Z", "harness": "claude-code",
                                   "model": "claude-sonnet-5-5", "cost_usd": 2.5, "title": "Fix the login"}
    assert page["spend"] == {"days_7": 2.5, "days_30": 6.5}


def test_critical_questions_come_first_and_a_muted_one_is_left_out(machine, capsys):
    register(**{"app-a": {}, "old": {"stage": "parked"}})
    machine["asks"] = [ask("aaa00001", "app-a", days_ago=9), ask("aaa00002", "app-a", days_ago=1, kind="blocked"),
                       ask("ooo00003", "old")]
    _, out, _ = show(capsys, "app-a", "--json", "--quick")
    assert [(a["id"], a["severity"]) for a in json.loads(out)["asks"]] == [("aaa00002", "critical"), ("aaa00001", "normal")]
    _, out, _ = show(capsys, "old", "--json", "--quick")
    assert json.loads(out)["asks"] == []


def test_quick_skips_the_session_read(machine, capsys, monkeypatch):
    register(**{"app-a": {}})
    monkeypatch.setattr(product_page, "load_rows", lambda days=30: pytest.fail("--quick must not read sessions"))
    code, out, _ = show(capsys, "app-a", "--json", "--quick")
    page = json.loads(out)
    assert code == 0 and page["sessions"] is None and page["spend"] is None


def test_a_product_with_nothing_has_empty_lists_and_zero_spend(machine, capsys):
    register(**{"app-a": {}})
    _, out, _ = show(capsys, "app-a", "--json")
    page = json.loads(out)
    assert page["asks"] == [] and page["notes"] == [] and page["sessions"] == []
    assert page["spend"] == {"days_7": 0.0, "days_30": 0.0}


def test_only_the_ten_newest_sessions_are_listed(machine, capsys, tmp_path):
    repo = tmp_path / "app-a"
    (repo / ".git").mkdir(parents=True)
    register(**{"app-a": {"repos": [str(repo)]}})
    machine["rows"] = ([row(f"s{i}", str(repo), i, 1.0) for i in range(12)], {})
    _, out, _ = show(capsys, "app-a", "--json")
    page = json.loads(out)
    assert [s["id"] for s in page["sessions"]] == [f"s{i}" for i in range(10)]
    assert page["spend"]["days_30"] == 12.0 and page["spend"]["days_7"] == 7.0


def test_the_unassigned_bucket_has_a_page(machine, capsys):
    register(**{"app-a": {}})
    machine["asks"] = [ask("uuu00001", "unassigned")]
    code, out, _ = show(capsys, "unassigned", "--json", "--quick")
    page = json.loads(out)
    assert code == 0 and page["product"]["name"] == "Unassigned" and page["product"]["registered"] is False
    assert [a["id"] for a in page["asks"]] == ["uuu00001"]


# --- the text -------------------------------------------------------------------------------------

def test_the_text_page_lists_each_part(machine, capsys, tmp_path):
    repo = tmp_path / "app-a"
    (repo / ".git").mkdir(parents=True)
    register(**{"app-a": {"name": "App A", "stage": "beta", "primary": "ios", "focus": True, "repos": [str(repo)]}})
    machine["asks"] = [ask("aaa00001", "app-a", days_ago=3, question="Ship 1.2 or wait?")]
    notes.add("dark mode", "app-a")
    machine["rows"] = ([row("s1", str(repo), 0, 2.5)], {"s1": "Fix the login"})
    code, out, _ = show(capsys, "app-a")
    assert code == 0
    assert out.splitlines()[0] == "App A  (app-a)  beta, focus, primary ios"
    for part in ("Waiting on you (1)", "aaa00001", "Ship 1.2 or wait?", "Notes (1)", "dark mode",
                 "Recent sessions (1)", "Fix the login", "$2.50 in 7 days"):
        assert part in out


def test_the_quick_text_page_says_what_it_left_out(machine, capsys):
    register(**{"app-a": {}})
    _, out, _ = show(capsys, "app-a", "--quick")
    assert "Waiting on you (0)" in out and "left out (--quick)" in out


# --- refusals -------------------------------------------------------------------------------------

def test_an_unknown_id_exits_2_with_one_line(machine, capsys):
    register(**{"app-a": {}})
    for argv in (["nope"], ["nope", "--json"]):
        code, out, err = show(capsys, *argv)
        assert code == 2 and out == ""
        assert err.strip() == "teyla: no product 'nope'; `teyla product` lists the registered ones."


def test_a_registry_that_does_not_parse_is_refused(machine, capsys):
    registry.path().parent.mkdir(parents=True, exist_ok=True)
    registry.path().write_text("[product.x\n")
    code, _, err = show(capsys, "x")
    assert code == 1 and err.startswith("teyla:")

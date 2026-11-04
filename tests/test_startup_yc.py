"""The YC sheet (docs/STARTUP.md): 15 boxes, drafts that check nothing, a confirm only a person can make, and the
promise that a count is never a percent. No network, no real ~/.teyla."""
from __future__ import annotations

import datetime as dt
import json
import stat
import time

import pytest

from teyla import cli, growth, portfolio, registry, startup, startup_yc

from test_startup import NOW, TODAY, attempt_rows, block

ANSWER_BOXES = [b[0] for b in startup_yc.BOXES if b[2] == "answer"]
READY_USAGE = {"users_total": "6", "wau": "3", "retained_7d": "3"}
READY_LEDGER = attempt_rows({"kind": "post"}, {"kind": "icp-meeting"})


def confirmed(*boxes, status="confirmed"):
    return {b: {"text": "https://demo.example.com/x" if b == "demo" else f"answer for {b}", "status": status,
                "by": "owner", "at": "2026-11-04T09:00:00Z"} for b in boxes}


def sheet(answers, **kw):
    kw.setdefault("usage", READY_USAGE)
    kw.setdefault("ledger", READY_LEDGER)
    b = block(**kw)
    return startup_yc.sheet("app", b, answers), b


def test_all_fifteen_checked_says_apply_with_the_link():
    sh, _ = sheet(confirmed(*ANSWER_BOXES))
    assert sh["checked"] == 15 and sh["verdict"] == "apply" and sh["apply_url"] == "https://www.ycombinator.com/apply"
    text = startup_yc.render_sheet(sh, "App")
    assert "Apply. 15 of 15 checked. https://www.ycombinator.com/apply" in text


def test_fourteen_checked_names_the_next_box_and_never_prints_a_percent():
    answers = confirmed(*ANSWER_BOXES)
    del answers["who"]
    sh, _ = sheet(answers)
    assert sh["checked"] == 14 and sh["verdict"] != "apply" and sh["next_box"] == "who" and sh["apply_url"] is None
    text = startup_yc.render_sheet(sh, "App")
    assert "14 of 15 checked. Next: who" in text and 'teyla startup yc answer app who' in text
    assert "%" not in text.split("YC facts")[0]                                          # YC's own sentences are quoted below that line
    assert "does not mean you may not apply" in text


def test_a_true_zero_checks_pay_when_money_is_off_and_revenue_never_blocks():
    sh, b = sheet({})
    rows = {r["id"]: r for r in sh["boxes"]}
    assert b["metrics"]["money"]["enabled"] is False
    assert rows["pay"]["checked"] and rows["pay"]["evidence"].startswith("$0")
    assert rows["using"]["checked"] and rows["talked"]["checked"]
    on = {r["id"]: r for r in sheet({}, money=True)[0]["boxes"]}
    assert on["pay"]["checked"] is False                                                 # money on, nothing printed: not known
    paid = {r["id"]: r for r in sheet({}, money=True, usage={**READY_USAGE, "paying_users": "0", "revenue_30d_usd": "0"})[0]["boxes"]}
    assert paid["pay"]["checked"] and "0 payers" in paid["pay"]["evidence"]               # a real $0 with money on


def test_using_needs_a_fresh_probe_and_talked_needs_a_person_to_have_logged_it():
    stale = {r["id"]: r for r in sheet({}, age=9)[0]["boxes"]}
    assert stale["using"]["checked"] is False and stale["using"]["command"] == "teyla portfolio --refresh"
    claimed = attempt_rows({"kind": "icp-meeting", "by": "agent"})
    agent = {r["id"]: r for r in sheet({}, ledger=claimed)[0]["boxes"]}
    assert agent["talked"]["checked"] is False and "logged yourself" in agent["talked"]["need"]


def test_boxes_with_a_prerequisite_need_the_rung_and_the_answer():
    answers = confirmed("customer", "sell", "demo", "first_live")
    rows = {r["id"]: r for r in sheet(answers, usage={"usage_probe": "needs_key"}, ledger=[], install=False)[0]["boxes"]}
    assert not rows["customer"]["checked"] and "Used must be met" in rows["customer"]["need"]
    assert not rows["sell"]["checked"] and "Tried must be met" in rows["sell"]["need"]
    assert not rows["demo"]["checked"] and "Built must be met" in rows["demo"]["need"]
    ok = {r["id"]: r for r in sheet(answers)[0]["boxes"]}
    assert all(ok[b]["checked"] for b in ("customer", "sell", "demo", "first_live"))


def test_a_draft_checks_nothing():
    rows = {r["id"]: r for r in sheet(confirmed("building", status="draft"))[0]["boxes"]}
    assert rows["building"]["checked"] is False and rows["building"]["need"] == "Confirm the draft"
    assert rows["building"]["command"] == "teyla startup yc confirm app building"


def test_the_commit_box_is_marked_as_added_by_teyla():
    sh, _ = sheet({})
    assert [b["id"] for b in sh["boxes"] if b["origin"] == "teyla"] == ["commit"]
    assert len(sh["boxes"]) == 15 and len(startup_yc.BOX_IDS) == 15


def test_yc_facts_older_than_90_days_warn():
    sh = startup_yc.sheet("app", block(usage=READY_USAGE), {}, today=dt.date(2027, 2, 2))      # day 90
    assert sh["facts"]["stale"] is False and "WARNING" not in startup_yc.render_sheet(sh, "App")
    late = startup_yc.sheet("app", block(usage=READY_USAGE), {}, today=dt.date(2027, 2, 3))    # day 91
    assert late["facts"]["stale"] is True and late["facts"]["age_days"] == 91
    assert "WARNING: these facts are 91 days old" in startup_yc.render_sheet(late, "App")
    assert startup_yc.facts_stale(dt.date(2026, 11, 4)) is False
    assert any("$500,000" in x for x in startup_yc.FACTS)


def test_the_sheet_is_for_venture_products_only():
    b = block(rp={"type": "indie"})
    assert b["yc"] == {"eligible": False, "checked": 0, "total": 15, "next_box": None}


# --- the answers store and the commands --------------------------------------------------------------------------

@pytest.fixture
def venture(monkeypatch):
    """`app` in the registry and in a fake portfolio the commands read."""
    registry.save({"product": {"app": registry.new_product("app")}, "assign": {}})
    b = block(usage=READY_USAGE, ledger=READY_LEDGER)
    monkeypatch.setattr(startup, "_view", lambda now: [{"id": "app", "title": "App", "startup": b}])
    return b


def test_an_answer_from_a_person_is_confirmed_and_stored_privately(venture, capsys):
    assert cli.main(["startup", "yc", "answer", "app", "building", "A", "tool", "for", "X"]) == 0
    a = startup_yc.load_answers("app")["building"]
    assert (a["text"], a["status"], a["by"]) == ("A tool for X", "confirmed", "owner")
    path = startup_yc.answers_path("app")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert startup_yc.summary("app", venture)["checked"] == 4        # building, plus using, pay and talked from the records
    assert "answer saved and confirmed" in capsys.readouterr().out


def test_an_answer_with_quotes_and_line_breaks_survives_the_file(venture):
    text = 'He said "yes"\nand a \\ backslash, and a tab\there'
    assert cli.main(["startup", "yc", "answer", "app", "need", text]) == 0
    assert startup_yc.load_answers("app")["need"]["text"] == text


def test_an_agent_writes_a_draft_and_cannot_confirm_it(venture, monkeypatch, capsys):
    monkeypatch.setenv("CODEX_THREAD_ID", "t1")
    assert cli.main(["startup", "yc", "answer", "app", "goal", "Ten", "paying", "teams"]) == 0
    a = startup_yc.load_answers("app")["goal"]
    assert (a["status"], a["by"]) == ("draft", "agent")
    assert "checks nothing" in capsys.readouterr().out
    assert startup_yc.summary("app", venture)["checked"] == 3        # using, pay, talked: the draft adds nothing
    rows = {r["id"]: r for r in startup_yc.rows("app", venture, startup_yc.load_answers("app"))}
    assert rows["goal"]["checked"] is False
    assert cli.main(["startup", "yc", "confirm", "app", "goal"]) == 1
    assert "only the owner confirms" in capsys.readouterr().err
    assert startup_yc.load_answers("app")["goal"]["status"] == "draft"
    monkeypatch.delenv("CODEX_THREAD_ID")
    assert cli.main(["startup", "yc", "confirm", "app", "goal"]) == 0
    assert startup_yc.load_answers("app")["goal"] == {**a, "status": "confirmed", "by": "owner", "at": startup_yc.load_answers("app")["goal"]["at"]}
    rows = {r["id"]: r for r in startup_yc.rows("app", venture, startup_yc.load_answers("app"))}
    assert rows["goal"]["checked"] is True


def test_an_agent_cannot_replace_an_answer_the_owner_confirmed(venture, monkeypatch, capsys):
    assert cli.main(["startup", "yc", "answer", "app", "why_you", "Because"]) == 0
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["startup", "yc", "answer", "app", "why_you", "Something else"]) == 1
    assert startup_yc.load_answers("app")["why_you"]["text"] == "Because"


def test_answers_to_auto_boxes_unknown_boxes_and_bad_demo_links_are_refused(venture, capsys):
    assert cli.main(["startup", "yc", "answer", "app", "pay", "$0"]) == 2
    assert cli.main(["startup", "yc", "answer", "app", "nope", "x"]) == 2
    assert cli.main(["startup", "yc", "answer", "app", "demo", "see my screen"]) == 2
    assert cli.main(["startup", "yc", "answer", "app", "demo", "https://demo.example.com/x"]) == 0
    assert cli.main(["startup", "yc", "answer", "app", "building", "x" * 2001]) == 2
    assert cli.main(["startup", "yc", "confirm", "app", "building"]) == 1                 # nothing to confirm
    assert startup_yc.load_answers("app").keys() == {"demo"}


def test_the_sheet_command_and_export(venture, capsys):
    assert cli.main(["startup", "yc"]) == 0                                                # no id: the focus product
    out = capsys.readouterr().out
    assert "YC sheet: App (app)" in out and "3 of 15 checked" in out
    assert cli.main(["startup", "yc", "app", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["checked"] == 3 and data["next_box"] == "building" and len(data["boxes"]) == 15
    cli.main(["startup", "yc", "answer", "app", "building", "A calm inbox"])
    capsys.readouterr()
    assert cli.main(["startup", "yc", "export", "app"]) == 0
    md = capsys.readouterr().out
    assert md.startswith("# App: YC interview answers") and "## What are you building?\n\nA calm inbox" in md
    assert "_Not ready: An answer._" in md and "$0" in md


def test_the_sheet_refuses_a_product_that_is_not_a_venture(monkeypatch, capsys):
    registry.save({"product": {"app": registry.new_product("app")}, "assign": {}})
    b = block(rp={"type": "indie"})
    monkeypatch.setattr(startup, "_view", lambda now: [{"id": "app", "title": "App", "startup": b}])
    assert cli.main(["startup", "yc", "app"]) == 1
    assert "for venture products" in capsys.readouterr().err
    assert cli.main(["startup", "yc", "answer", "app", "building", "x"]) == 1
    assert cli.main(["startup", "yc", "ghost"]) == 2

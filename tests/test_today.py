"""`teyla today`: the daily screen. Asks are built by hand and `asks.collect` is replaced; the registry,
the notes and the cache are real files in the tmp TEYLA_HOME that conftest gives every test."""
from __future__ import annotations

import datetime as dt
import io
import json
import re

import pytest

from teyla import asks, cli, figures, notes, registry, spend, today
from teyla import changes as changes_mod
from teyla.ui import Style

REAL_COMPUTE_SPEND = figures.compute_spend            # the autouse fixture replaces the module attribute
NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone.utc).timestamp()
ESC = re.compile(r"\033\[")


class TTY(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def machine(monkeypatch):
    """A machine with sessions, a fixed clock, no real process and no slow count."""
    monkeypatch.setattr(figures, "now", lambda: NOW)
    monkeypatch.setattr(figures, "has_sessions", lambda: True)
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    state = {"spawned": 0, "computed": 0, "asks": []}
    monkeypatch.setattr(figures, "spawn_refresh", lambda: state.__setitem__("spawned", state["spawned"] + 1) or True)

    def compute(at=None, rows=None):
        state["computed"] += 1
        return {"this_week": 200.0, "last_week": 100.0, "at": NOW}
    monkeypatch.setattr(figures, "compute_spend", compute)
    monkeypatch.setattr(asks, "collect", lambda *a, **k: list(state["asks"]))
    return state


def ask(id_, product, *, days_ago=1.0, kind="question", question="Which font?", title="A session"):
    return asks.Ask(id=id_, kind=kind, product=product, title=title, question=question, context="", options=[],
                    when=NOW - days_ago * 86400, archived=False, link=f"claude://x/{id_}", pr="", harness="claude-code")


def register(**products):
    reg = registry.load()
    for pid, fields in products.items():
        reg["product"][pid] = {**registry.new_product(pid, stage="building"), **fields}
    registry.save(reg)


def cache_spend(this=200.0, last=100.0, age=30.0):
    figures.write_cache(spend={"this_week": this, "last_week": last, "at": NOW - age})


def run(capsys, *argv):
    assert cli.main(["today", *argv]) == 0
    out = capsys.readouterr()
    return out.out, out.err


# --- the questions ----------------------------------------------------------------------------------

def test_questions_are_grouped_by_product_focus_first_unassigned_last(machine, capsys):
    register(atlas={"name": "Atlas"}, cellar={"name": "Cellar", "focus": True}, lens={"name": "Lens"})
    machine["asks"] = [ask("aaa00001", "unassigned", days_ago=9), ask("aaa00002", "lens", days_ago=7),
                       ask("aaa00003", "atlas", days_ago=5), ask("aaa00004", "cellar", days_ago=1)]
    cache_spend()
    out, _ = run(capsys)
    heads = [ln.strip() for ln in out.splitlines() if " waiting" in ln and not ln.startswith("    ")]
    assert heads == ["Cellar  1 waiting  [building]", "Lens  1 waiting  [building]",
                         "Atlas  1 waiting  [building]", "Unassigned  1 waiting"]
    assert "Waiting on you: 4 questions in 4 products" in out


def test_a_product_shows_three_questions_then_the_rest_as_a_count(machine, capsys):
    register(atlas={"name": "Atlas"})
    machine["asks"] = [ask(f"aaa0000{i}", "atlas", days_ago=10 - i, question=f"Question {i}") for i in range(1, 7)]
    cache_spend()
    out, _ = run(capsys)
    shown = [ln for ln in out.splitlines() if re.match(r"    aaa0000\d", ln)]
    assert len(shown) == 3 and "+3 more" in out
    assert "Atlas  6 waiting" in out


def test_critical_questions_come_first_inside_a_product_then_the_oldest(machine, capsys):
    register(atlas={"name": "Atlas"})
    machine["asks"] = [ask("old00001", "atlas", days_ago=20, question="Which colour?"),
                       ask("mid00002", "atlas", days_ago=10, question="Which icon?"),
                       ask("blk00003", "atlas", days_ago=2, kind="blocked", question="Sign in to continue"),
                       ask("sec00004", "atlas", days_ago=1, question="A token leaked in the log")]
    cache_spend()
    out, _ = run(capsys)
    ids = re.findall(r"^    ([a-z]{3}\d{5})", out, re.M)
    assert ids == ["blk00003", "sec00004", "old00001"]
    assert re.search(r"blk00003\s+2d critical", out)


def test_a_parked_product_stays_quiet_unless_a_question_is_critical(machine, capsys):
    register(atlas={"name": "Atlas", "stage": "parked"})
    machine["asks"] = [ask("aaa00001", "atlas", question="Which colour?")]
    cache_spend()
    out, _ = run(capsys)
    assert "Waiting on you: nothing." in out


def test_the_screen_stays_near_25_lines_with_many_products(machine, capsys):
    for i in range(12):
        register(**{f"p{i}": {"name": f"Product {i}"}})
        machine["asks"] += [ask(f"q{i:02d}0000{j}", f"p{i}", days_ago=j + i) for j in range(5)]
    for i in range(4):
        notes.add(f"note {i}")
    cache_spend()
    out, _ = run(capsys)
    assert 15 <= len(out.splitlines()) <= 27, len(out.splitlines())
    assert re.search(r"\+\d+ more in \d+ other products: teyla asks", out)
    total = int(re.search(r"Waiting on you: (\d+) questions", out).group(1))
    assert total == 60


def test_an_empty_machine_says_nothing_waits(machine, capsys):
    cache_spend()
    out, _ = run(capsys)
    assert "Waiting on you: nothing." in out and "Inbox: empty." in out
    assert "Next: Nothing needs you today." in out


# --- the Inbox ------------------------------------------------------------------------------------

def test_the_inbox_shows_its_count_and_the_newest_three(machine, capsys, monkeypatch):
    clock = iter(range(5))
    monkeypatch.setattr(notes, "_now", lambda: dt.datetime.fromtimestamp(NOW - 86400 * (5 - next(clock)), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    for t in ("first", "second", "third", "fourth", "fifth"):
        notes.add(t)
    cache_spend()
    out, _ = run(capsys)
    assert "Inbox: 5 notes with no product yet  teyla notes --inbox" in out
    texts = [ln.split("  ")[-1] for ln in out.splitlines() if re.match(r"    n[a-z2-7]{6}\s", ln)]
    assert texts == ["fifth", "fourth", "third"]


def test_a_note_filed_under_a_product_leaves_the_inbox(machine, capsys):
    register(atlas={"name": "Atlas"})
    n = notes.add("an idea")
    notes.link(n["id"], "atlas")
    cache_spend()
    out, _ = run(capsys)
    assert "Inbox: empty." in out


# --- the spend ------------------------------------------------------------------------------------

def test_spend_is_this_week_against_last_week_with_a_percentage(machine, capsys):
    cache_spend(this=412.0, last=380.0)
    out, _ = run(capsys)
    assert "Spend: $412 in the last 7 days, $380 in the 7 before (+8%). API list price." in out
    cache_spend(this=50.0, last=100.0)
    out, _ = run(capsys)
    assert "(-50%)" in out


def test_no_percentage_when_last_week_cost_nothing(machine, capsys):
    cache_spend(this=12.5, last=0.0)
    out, _ = run(capsys)
    assert "Spend: $12 in the last 7 days, $0.00 in the 7 before." in out


def test_a_fresh_cache_is_read_and_nothing_is_counted(machine, capsys):
    cache_spend(age=60)
    run(capsys)
    assert machine["computed"] == 0 and machine["spawned"] == 0


def test_a_stale_cache_is_shown_and_refreshed_in_the_background(machine, capsys):
    cache_spend(age=3 * 3600)
    out, _ = run(capsys)
    assert "$200" in out and machine["computed"] == 0 and machine["spawned"] == 1


def test_no_cache_counts_once_in_the_foreground_and_says_so(machine, capsys):
    out, err = run(capsys)
    assert machine["computed"] == 1 and "Counting two weeks of sessions" in err
    assert "Spend: $200 in the last 7 days, $100 in the 7 before (+100%)." in out
    run(capsys)
    assert machine["computed"] == 1                                # the second run reads the cache


def test_fresh_counts_again_even_with_a_cache(machine, capsys):
    cache_spend(age=60)
    run(capsys, "--fresh")
    assert machine["computed"] == 1


def test_a_failed_count_leaves_the_spend_line_out_and_the_rest_in(machine, capsys, monkeypatch):
    monkeypatch.setattr(figures, "compute_spend", lambda *a, **k: (_ for _ in ()).throw(OSError("unreadable")))
    machine["asks"] = [ask("aaa00001", "atlas")]
    out, err = run(capsys)
    assert "could not count the spend (OSError)" in err
    assert "Waiting on you: 1 question" in out and "Spend: not counted yet" in out


def test_without_sessions_there_is_no_count_and_the_screen_says_so(machine, capsys, monkeypatch):
    monkeypatch.setattr(figures, "has_sessions", lambda: False)
    out, err = run(capsys)
    assert "Spend: no agent sessions found yet." in out and machine["computed"] == 0 and err == ""


def test_today_keeps_the_question_count_in_the_cache_for_the_welcome(machine, capsys):
    machine["asks"] = [ask("aaa00001", "atlas"), ask("aaa00002", "atlas")]
    cache_spend()
    run(capsys)
    q, age = figures.cached("questions", NOW)
    assert q["waiting"] == 2 and age == 0


def test_the_background_refresh_writes_both_figures_and_releases_its_lock(machine, capsys, monkeypatch):
    machine["asks"] = [ask("aaa00001", "atlas")]
    figures._lock().touch()
    assert cli.main(["today", "--refresh-cache"]) == 0
    assert capsys.readouterr().out == ""
    c = figures.read_cache()
    assert c["spend"]["this_week"] == 200.0 and c["questions"]["waiting"] == 1
    assert not figures._lock().exists()


def test_the_real_week_arithmetic_sums_seven_days_against_the_seven_before():
    today_ = dt.date.today()
    days = {(today_ - dt.timedelta(days=i)).isoformat(): 10.0 for i in range(0, 7)}           # this week: 70
    days.update({(today_ - dt.timedelta(days=i)).isoformat(): 5.0 for i in range(7, 14)})     # the week before: 35
    days[(today_ - dt.timedelta(days=20)).isoformat()] = 999.0                               # outside both
    rows = [{"day_usd": days, "sub_day_model_usd": {}, "sub_calls": []}]
    got = REAL_COMPUTE_SPEND(NOW, rows=rows)
    assert got["this_week"] == 70.0 and got["last_week"] == 35.0


# --- the suggestion: its three branches and the two around them --------------------------------------

OFFERS = [{"id": "O1", "title": "Compact earlier", "low": 100.0, "high": 240.0},
          {"id": "O2", "title": "Sonnet for subagents", "low": 20.0, "high": 90.0},
          {"id": "O5", "title": "One rules file", "low": 0.0, "high": 0.0}]


def group(product, name, *rows):
    return {"product": product, "name": name, "asks": [dict(id=f"{product}{i}", age_s=a, critical=c, question="q", link="")
                                                       for i, (a, c) in enumerate(rows)]}


def test_branch_one_an_unapplied_offer_with_the_biggest_saving():
    s = today.suggest([group("atlas", "Atlas", (86400 * 9, True))], 3, OFFERS)
    assert s == {"kind": "offer", "text": "Apply O1, Compact earlier: it saves about $100-$240 a month.",
                 "command": "teyla apply O1"}


def test_an_offer_without_a_dollar_saving_is_not_a_suggestion():
    s = today.suggest([], 0, [OFFERS[2]])
    assert s["kind"] == "none"


def test_branch_two_the_oldest_critical_question_when_no_offer_is_open():
    gs = [group("atlas", "Atlas", (86400 * 3, True), (86400 * 30, False)),
          group("lens", "Lens", (86400 * 8, True), (86400 * 2, True))]
    s = today.suggest(gs, 4, [])
    assert s == {"kind": "critical", "text": "Answer the oldest critical question: Lens, 8d old.",
                 "command": "teyla asks --product lens"}


def test_branch_three_the_inbox_when_nothing_is_critical():
    s = today.suggest([group("atlas", "Atlas", (86400, False))], 1, [])
    assert s == {"kind": "inbox", "text": "Put the 1 note in your Inbox under a product.", "command": "teyla notes --inbox"}
    assert today.suggest([], 4, [])["text"] == "Put the 4 notes in your Inbox under a product."


def test_then_the_oldest_question_and_then_nothing():
    gs = [group("atlas", "Atlas", (86400 * 2, False)), group("lens", "Lens", (86400 * 5, False))]
    s = today.suggest(gs, 0, [])
    assert s["kind"] == "question" and "Lens, 5d old" in s["text"] and s["command"] == "teyla asks --product lens"
    assert today.suggest([], 0, []) == {"kind": "none", "text": "Nothing needs you today.", "command": ""}


def test_a_biggest_saving_offer_wins_over_critical_questions_on_the_screen(machine, capsys):
    machine["asks"] = [ask("blk00001", "atlas", kind="blocked", days_ago=9)]
    cache_spend()
    figures.record_start({"diagnosis": {}, "offers": [{"id": "O1", "title": "Compact earlier", "applies": True,
                                                         "saving_usd_month": {"low": 100, "high": 240}}]}, False)
    out, _ = run(capsys)
    assert "Next: Apply O1, Compact earlier: it saves about $100-$240 a month." in out
    assert out.rstrip().endswith("teyla apply O1")


def test_an_offer_already_applied_is_not_suggested_again(machine, capsys):
    cache_spend()
    figures.record_start({"diagnosis": {}, "offers": [{"id": "O1", "title": "Compact earlier", "applies": True,
                                                         "saving_usd_month": {"low": 100, "high": 240}}]}, False)
    changes_mod.log_path().write_text(json.dumps({"id": "c1", "offer": "O1", "kind": "json"}) + "\n")
    out, _ = run(capsys)
    assert "Apply O1" not in out


# --- --json ---------------------------------------------------------------------------------------

def test_json_has_the_shape_the_mac_app_and_the_web_page_read(machine, capsys):
    register(atlas={"name": "Atlas", "focus": True})
    machine["asks"] = [ask(f"aaa0000{i}", "atlas", days_ago=i) for i in range(1, 6)]
    notes.add("an idea")
    cache_spend(this=412.0, last=380.0)
    out, _ = run(capsys, "--json")
    j = json.loads(out)
    assert set(j) == {"version", "generated", "sessions", "questions", "notes", "spend", "suggestion"}
    assert j["version"] == 1 and j["sessions"] is True and j["generated"].endswith("Z")
    assert j["questions"]["waiting"] == 5
    (g,) = j["questions"]["products"]
    assert set(g) == {"product", "name", "stage", "focus", "count", "asks"}
    assert g["product"] == "atlas" and g["focus"] is True and g["count"] == 5 and len(g["asks"]) == 5
    assert set(g["asks"][0]) == {"id", "age_s", "critical", "question", "link"}
    assert j["notes"]["inbox"] == 1 and set(j["notes"]["newest"][0]) == {"id", "text", "created", "age_s"}
    assert j["spend"]["this_week"] == 412.0 and j["spend"]["last_week"] == 380.0 and j["spend"]["change_pct"] == 8
    assert j["spend"]["source"] == "cache" and set(j["spend"]) == {"this_week", "last_week", "change_pct", "as_of", "source", "note"}
    assert set(j["suggestion"]) == {"kind", "text", "command"} and j["suggestion"]["kind"] == "inbox"


def test_json_never_waits_for_the_count_and_reports_null_spend(machine, capsys):
    out, err = run(capsys, "--json")
    assert json.loads(out)["spend"] is None
    assert machine["computed"] == 0 and machine["spawned"] == 1 and err == ""


# --- colour ---------------------------------------------------------------------------------------

def test_colour_follows_the_terminal(machine):
    machine["asks"] = [ask("blk00001", "atlas", kind="blocked")]
    cache_spend()
    snap = today.snapshot(NOW)
    env = {"TERM": "xterm-256color", "COLORFGBG": "15;0"}
    assert ESC.search(today.render(snap, Style(TTY(), env)))
    for plain in ({**env, "NO_COLOR": "1"}, {"TERM": "dumb"}):
        assert not ESC.search(today.render(snap, Style(TTY(), plain)))


def test_piped_output_has_no_escape_codes(machine, capsys):
    machine["asks"] = [ask("blk00001", "atlas", kind="blocked")]
    cache_spend()
    out, _ = run(capsys)
    assert not ESC.search(out)

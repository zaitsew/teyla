"""`teyla startup` (docs/STARTUP.md): the ladder per type, the three kinds of "no number", claimed attempts, snapshots,
the focus product, and the portfolio block. Nothing here reaches the network, a probe or the real ~/.teyla."""
from __future__ import annotations

import datetime
import json
import pathlib
import stat
import time

import pytest

from teyla import cli, corrections, growth, portfolio, products, registry, startup

NOW = time.mktime((2026, 11, 4, 9, 0, 0, 0, 0, -1))
DAY = 86400
TODAY = growth.day_of(NOW)
SENTINEL = "zz-sentinel-customer-words-zz"


def ago(days: int) -> str:
    return growth.day_of(NOW - days * DAY)


def attempt_rows(*rows, product="app"):
    return [{"ev": "attempt", "product": product, "day": TODAY, **r} for r in rows]


def block(*, usage=None, age=0.0, install=True, money=False, ai=None, ledger=(), rp=None, snaps=(), pid="app"):
    """The startup block of one product from fake caches. `usage` are the counters its probe printed (None: no probe),
    `age` the probe's age in days."""
    rp = {"stage": "building", **(rp or {})}
    repos = [pathlib.Path("/code") / pid]
    caches = {pid: usage} if usage is not None else {}
    ages = {pid: NOW - age * DAY} if usage is not None else {}
    att = growth.tally(list(ledger), [pid], TODAY)[pid]
    f = startup.facts(NOW, pid=pid, rp=rp, repos=repos, usage=caches, ages=ages, money_enabled=money, can_install=install,
                      ai_cost_30d=ai, attempts=att)
    return startup.evaluate(NOW, f, rp, list(snaps), pid)


def status(b, rung):
    return next(r["status"] for r in b["rungs"] if r["id"] == rung)


def test_out_of_order_achievements_stay_visible_and_stage_is_the_unbroken_run():
    b = block(usage={"users_total": "26", "wau": "5", "retained_7d": "1"})
    assert [r["status"] for r in b["rungs"][:3]] == ["met", "missing", "met"]       # built, tried, used
    assert b["stage"] == "built" and b["stage_title"] == "Built"
    assert b["next"]["rung"] == "tried" and b["next"]["command"] == "teyla growth"
    assert b["metrics"]["usage"]["external"] == 25                                   # 26 accounts minus the owner


def test_no_probe_is_unknown_and_zero_is_a_real_zero():
    none = block()
    assert status(none, "used") == "unknown" and none["metrics"]["usage"]["external"] is None
    assert none["as_of"] is None and none["stale"] is False
    zero = block(usage={"users_total": "1", "wau": "1", "retained_7d": "0"})
    assert status(zero, "used") == "missing" and zero["metrics"]["usage"]["external"] == 0
    # A probe that prints words and no number is also unknown, not zero.
    words = block(usage={"usage_probe": "needs_key"})
    assert status(words, "used") == "unknown" and words["as_of"] is None


def test_a_stale_probe_earns_nothing():
    ledger = attempt_rows({"kind": "post"})
    fresh = block(usage={"users_total": "26"}, age=6, ledger=ledger)
    old = block(usage={"users_total": "26"}, age=8, ledger=ledger)
    assert (status(fresh, "used"), fresh["stage"]) == ("met", "used")
    assert status(old, "used") == "stale" and old["stage"] == "tried" and old["stale"] is True
    assert old["next"]["rung"] == "used" and "8 days old" in old["next"]["text"]
    assert old["next"]["command"] == "teyla portfolio --refresh"


def test_external_people_are_assumed_unless_the_probe_prints_them():
    assumed = block(usage={"users_total": "5", "wau": "3", "retained_7d": "2"})["metrics"]["usage"]
    assert (assumed["external"], assumed["wau"], assumed["retained_7d"], assumed["external_assumed"]) == (4, 2, 1, True)
    explicit = block(usage={"users_total": "5", "external_users": "2", "external_wau": "1", "external_retained_7d": "0"})["metrics"]["usage"]
    assert (explicit["external"], explicit["wau"], explicit["retained_7d"], explicit["external_assumed"]) == (2, 1, 0, False)
    assert block(usage={"users_total": "0"})["metrics"]["usage"]["external"] == 0         # never below zero


def test_personal_ladder_has_no_sale_rungs_and_keeps_after_30_days():
    rp = {"type": "personal"}
    new = block(usage={"wau": "1"}, rp=rp)
    assert [r["id"] for r in new["rungs"]] == ["built", "used_by_me", "kept"]
    assert (status(new, "used_by_me"), status(new, "kept")) == ("met", "unknown")        # no snapshot 30 days old yet
    kept = block(usage={"wau": "1"}, rp=rp, snaps=[{"id": "app", "day": ago(31), "wau": 2}])
    assert status(kept, "kept") == "met" and kept["stage"] == "kept" and kept["next"] is None
    lapsed = block(usage={"wau": "1"}, rp=rp, snaps=[{"id": "app", "day": ago(31), "wau": 0}])
    assert status(lapsed, "kept") == "missing"
    assert kept["metrics"]["usage"]["wau"] == 1 and kept["metrics"]["usage"]["external"] is None   # the owner counts here


def test_an_agent_claimed_attempt_does_not_count_and_shows_as_claimed():
    ledger = attempt_rows({"kind": "post", "by": "agent"}, {"kind": "icp-meeting", "by": "agent"})
    b = block(ledger=ledger)
    assert status(b, "tried") == "missing" and b["metrics"]["sales"]["claimed"] == 2
    assert b["metrics"]["marketing"]["posts"] == 0 and b["metrics"]["sales"]["icp_meetings"] == 0
    assert "logged by an agent" in b["next"]["text"]
    own = block(ledger=ledger + attempt_rows({"kind": "post"}))                       # an older row has no `by`
    assert status(own, "tried") == "met" and own["metrics"]["marketing"]["posts"] == 1
    assert own["metrics"]["marketing"]["posts_7d"] == 1 and own["metrics"]["sales"]["claimed"] == 2
    published = block(ledger=[{"ev": "published", "product": "app", "day": TODAY, "by": "agent"}])
    assert status(published, "tried") == "met"                                        # a recorded URL always counts


def test_money_off_skips_the_paid_rungs_and_money_on_reads_the_probe():
    off = block(usage={"users_total": "9", "retained_7d": "5"}, ledger=attempt_rows({"kind": "ad"}))
    assert [status(off, r) for r in ("paid", "repeating")] == ["not_applicable"] * 2
    assert off["stage"] == "retained" and off["next"]["rung"] == "growing"           # skips the rungs that do not apply
    on = block(usage={"users_total": "9", "retained_7d": "5"}, ledger=attempt_rows({"kind": "ad"}), money=True)
    assert status(on, "paid") == "unknown" and on["stage"] == "retained"             # money on, no number printed
    paid = block(usage={"users_total": "9", "retained_7d": "5", "paying_users": "1", "revenue_30d_usd": "20"},
                 ledger=attempt_rows({"kind": "ad"}), money=True)
    assert (status(paid, "paid"), status(paid, "repeating")) == ("met", "missing")
    three = block(usage={"paying_users": "3", "revenue_30d_usd": "20"}, money=True)
    assert status(three, "repeating") == "met"
    windows = block(usage={"paying_users": "1", "revenue_30d_usd": "20"}, money=True,
                    snaps=[{"id": "app", "day": ago(30), "revenue_30d_usd": 15}])
    assert status(windows, "repeating") == "met"


def test_indie_sustains_when_revenue_beats_ai_cost():
    rp = {"type": "indie"}
    usage = {"users_total": "9", "paying_users": "2", "revenue_30d_usd": "40"}
    assert status(block(usage=usage, money=True, ai=12.5, rp=rp), "sustaining") == "met"
    assert status(block(usage=usage, money=True, ai=60.0, rp=rp), "sustaining") == "missing"
    assert status(block(usage=usage, money=True, ai=None, rp=rp), "sustaining") == "unknown"
    assert block(rp=rp)["rungs"][-1]["id"] == "sustaining"


def test_growth_needs_four_weeks_of_snapshots():
    usage = {"users_total": "14", "external_wau": "13"}
    none = block(usage=usage)
    assert status(none, "growing") == "unknown" and none["metrics"]["growth"] == {"weekly_pct": None, "weeks": 0, "on": "wau"}
    short = block(usage=usage, snaps=[{"id": "app", "day": ago(20), "external_wau": 5}])
    assert short["metrics"]["growth"]["weekly_pct"] is None and short["metrics"]["growth"]["weeks"] == 2
    good = block(usage=usage, snaps=[{"id": "app", "day": ago(28), "external_wau": 10}])
    g = good["metrics"]["growth"]
    assert g["weekly_pct"] == 6.8 and g["weeks"] == 4 and status(good, "growing") == "met"
    flat = block(usage=usage, snaps=[{"id": "app", "day": ago(28), "external_wau": 13}])
    assert status(flat, "growing") == "missing"
    revenue = block(usage={"revenue_30d_usd": "30", "paying_users": "1"}, money=True,
                    snaps=[{"id": "app", "day": ago(28), "revenue_30d_usd": 10}])
    assert revenue["metrics"]["growth"]["on"] == "revenue" and revenue["metrics"]["growth"]["weekly_pct"] > 30


def test_a_parked_product_keeps_its_rungs_and_says_parked():
    live = block(usage={"users_total": "26"})
    parked = block(usage={"users_total": "26"}, rp={"stage": "parked"})
    assert parked["parked"] is True and live["parked"] is False
    assert parked["rungs"] == live["rungs"] and parked["stage"] == live["stage"]
    assert "parked" in startup._line({"id": "app", "startup": parked})


def test_an_unset_type_uses_the_venture_ladder_and_says_so():
    b = block()
    assert (b["type"], b["type_set"]) == ("venture", False)
    assert [r["id"] for r in b["rungs"]] == list(startup.LADDERS["venture"])
    assert block(rp={"type": "open-source"})["rungs"][-1]["id"] == "retained"


def test_the_focus_product_is_outside_weekly_users_then_retained_then_id():
    def item(pid, wau, ret, **kw):
        b = block(usage={"external_wau": str(wau), "external_retained_7d": str(ret), "users_total": "9"} if wau is not None else None,
                  pid=pid, **kw)
        return {"id": pid, "title": pid, "startup": b}
    items = [item("b", 4, 1), item("a", 4, 2), item("c", 9, 0, rp={"type": "personal"}), item("d", 9, 0, rp={"stage": "parked"}),
             item("e", None, 0)]
    assert startup.focus_of(items) == "a"                                             # personal and parked are out; 4 = 4, retained 2 > 1
    assert startup.focus_of([items[2], items[3]]) is None
    rep = startup.report(NOW, items)
    assert rep["focus"] == "a" and rep["version"] == 1 and sum(rep["counts"].values()) == 5


def test_snapshots_one_row_per_product_per_day_private_and_trimmed(tmp_path):
    old = {"day": ago(401), "id": "app", "wau": 1}
    startup.write_snapshots(NOW - 2 * DAY, [old, {"day": ago(2), "id": "app", "wau": 1}])
    startup.write_snapshots(NOW, [{"day": TODAY, "id": "app", "wau": 2}])
    startup.write_snapshots(NOW, [{"day": TODAY, "id": "app", "wau": 3}])              # replaces today's row
    rows = startup.read_snapshots()["app"]
    assert [r["wau"] for r in rows] == [1, 3] and rows[-1]["day"] == TODAY
    assert stat.S_IMODE(startup.snapshots_path().stat().st_mode) == 0o600


def test_refresh_records_a_snapshot_only_from_a_fresh_probe(tmp_path, monkeypatch):
    d = tmp_path / "repos" / "app"
    (d / ".git").mkdir(parents=True)
    reg = {"product": {"app": {"name": "App", "repos": [str(d)], "paths": [], "aliases": [], "stage": "live", "primary": "", "focus": False}},
           "assign": {}}
    products.write_cache({"app": ("ok", {"users_total": "6", "wau": "3"})})
    startup.record_snapshots(time.time(), reg)
    row = startup.read_snapshots()["app"][0]
    assert (row["external_users"], row["wau"], row["external_wau"]) == (5, 3, 2)
    assert portfolio.load_usage_ages()["app"] > 0
    startup.record_snapshots(time.time() + 8 * DAY, reg)                               # the probe is now 8 days old
    assert len(startup.read_snapshots()["app"]) == 1


# --- the portfolio ----------------------------------------------------------------------------------------------

def reg_of(tmp_path, **ptype):
    d = tmp_path / "repos" / "app"
    (d / ".git").mkdir(parents=True, exist_ok=True)
    return {"product": {"app": {"name": "App", "repos": [str(d)], "paths": [], "aliases": [], "stage": "building",
                                "primary": "", "focus": False, **ptype}}, "assign": {}}


def build(tmp_path, usage=None, **ptype):
    return portfolio.build(NOW, reg=reg_of(tmp_path, **ptype), prods=[], ask_rows=[], tasks=[], bl={}, ledger=None,
                           cache=portfolio.load_cache(), usage=usage if usage is not None else {"app": {"users_total": "4"}})


def test_the_portfolio_carries_a_startup_block_with_no_answer_text(tmp_path):
    from teyla import startup_yc
    startup_yc.save_answers("app", {"building": {"text": SENTINEL, "status": "confirmed", "by": "owner", "at": "x"}})
    pf = build(tmp_path)
    s = pf["products"][0]["startup"]
    assert s["type"] == "venture" and s["yc"] == {"eligible": True, "checked": 2, "total": 15, "next_box": "customer"}   # building + pay ($0, money off)
    text = json.dumps(pf) + json.dumps(startup.report(NOW, pf["products"]))
    assert SENTINEL not in text
    assert set(s) == {"type", "type_set", "stage", "stage_title", "parked", "as_of", "stale", "next", "rungs", "metrics", "yc"}


def test_a_failing_startup_block_leaves_the_portfolio_whole(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no")
    monkeypatch.setattr(startup, "block_for", boom)
    pf = build(tmp_path)
    assert pf["products"][0]["startup"] is None and pf["products"][0]["id"] == "app"
    monkeypatch.undo()
    monkeypatch.setattr(startup, "context", boom)
    assert build(tmp_path)["products"][0]["startup"] is None


def test_the_ledger_is_read_once_per_build(tmp_path, monkeypatch):
    reads = []
    real = growth.Store.ledger
    monkeypatch.setattr(growth.Store, "ledger", lambda self: (reads.append(1), real(self))[1])
    reg = reg_of(tmp_path)
    for n in ("two", "three"):
        reg["product"][n] = dict(reg["product"]["app"])
    portfolio.build(NOW, reg=reg, prods=[], ask_rows=[], tasks=[], bl={}, ledger=None, cache=portfolio.load_cache(), usage={})
    assert len(reads) == 1


# --- registry, growth, detection --------------------------------------------------------------------------------

def test_product_set_type_validates_and_clears(tmp_path):
    reg = reg_of(tmp_path)
    assert registry.set_field(reg, "app", "type", "personal") == "app: type = personal"
    assert reg["product"]["app"]["type"] == "personal"
    with pytest.raises(ValueError):
        registry.set_field(reg, "app", "type", "startup")
    assert "cleared" in registry.set_field(reg, "app", "type", "")
    assert "type" not in reg["product"]["app"]
    registry.set_field(reg, "app", "type", "open-source")
    registry.save(reg)
    assert registry.load()["product"]["app"]["type"] == "open-source"
    assert 'type = "open-source"' in registry.path().read_text()


def test_growth_log_from_an_agent_is_claimed_and_does_not_count(monkeypatch, capsys):
    registry.save({"product": {"app": registry.new_product("app")}, "assign": {}})
    assert cli.main(["growth", "log", "--product", "app", "--kind", "post"]) == 0
    monkeypatch.setenv("CLAUDECODE", "1")
    assert cli.main(["growth", "log", "--product", "app", "--kind", "icp-meeting"]) == 0
    assert "claimed by an agent" in capsys.readouterr().out
    rows = growth.Store().ledger()
    assert "by" not in rows[0] and rows[1]["by"] == "agent"
    r = growth.attempt_rows(growth.Store())["app"]
    assert (r["posts"], r["icp_meetings"], r["claimed"]) == (1, 0, 1)
    monkeypatch.delenv("CLAUDECODE")
    assert cli.main(["growth", "sale-attempts", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)["app"]
    assert shown["claimed"] == 1 and shown["posts"] == 1 and "type" not in shown


def test_a_personal_product_is_never_not_tried_yet(monkeypatch):
    registry.save({"product": {"mine": {**registry.new_product("mine"), "type": "personal"}, "sale": registry.new_product("sale")},
                   "assign": {}})
    store = growth.Store()
    assert growth.products_not_tried(store) == ["sale"]
    rows = growth.attempt_rows(store)
    assert growth.product_term("mine", rows) == 0.0 and growth.product_term("sale", rows) == 1.0
    text = growth.render_attempts(rows)
    assert "personal, not for sale" in text and "mine" in text


@pytest.mark.parametrize("var", ["CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_CI",
                                 "GROK_SESSION_ID", "GROK_AGENT", "AI_AGENT"])
def test_each_harness_variable_marks_an_agent_session(monkeypatch, var):
    assert startup.in_agent_session() is False
    monkeypatch.setenv(var, "1")
    assert startup.in_agent_session() is True


def test_variables_a_person_can_export_do_not_mark_an_agent(monkeypatch):
    for var in ("CODEX_HOME", "GROK_HOME", "CLAUDE_CODE_ENTRYPOINT"):
        monkeypatch.setenv(var, "x")
    monkeypatch.setenv("CLAUDECODE", "0")
    assert startup.in_agent_session() is False
    assert startup.in_agent_session({"CODEX_THREAD_ID": "t"}) is True


def test_usage_rows_carry_the_time_of_their_probe():
    products.write_cache({"App": ("ok", {"wau": "3"})})
    ages = portfolio.load_usage_ages()
    assert abs(ages["app"] - time.time()) < 5
    products.write_cache({"App": ("timeout", {})})                                    # a failed probe keeps the good row, and its time
    assert abs(portfolio.load_usage_ages()["app"] - ages["app"]) < 1


def test_the_startup_commands_print_for_a_person(tmp_path, monkeypatch, capsys):
    pf = build(tmp_path, usage={"app": {"users_total": "26", "wau": "5"}}, stage="live")
    monkeypatch.setattr(startup, "_view", lambda now: pf["products"])
    assert cli.main(["startup"]) == 0
    out = capsys.readouterr().out
    assert "Focus: app" in out and "next Tried" in out and "%" not in out
    assert cli.main(["startup", "show", "app"]) == 0
    assert "Used" in capsys.readouterr().out
    assert cli.main(["startup", "show", "app", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stage"] == "built"
    assert cli.main(["startup", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["focus"] == "app"
    assert cli.main(["startup", "show", "nope"]) == 2


def test_a_product_teyla_cannot_see_is_unknown_not_unbuilt():
    b = block(install=False, rp={"stage": "building"}, usage=None)
    # the default: a known platform with no build
    assert status(b, "built") == "missing" and b["stage_title"] == "Not built"
    rp = {"stage": "building"}
    repos = [pathlib.Path("/code/app")]
    f = startup.facts(NOW, pid="app", rp=rp, repos=repos, usage={}, ages={}, money_enabled=False, can_install=False,
                      ai_cost_30d=None, attempts=growth.tally([], ["app"], TODAY)["app"], install_known=False)
    seen = startup.evaluate(NOW, f, rp, [], "app")
    assert status(seen, "built") == "unknown"
    assert seen["stage_title"] == "Not known"
    assert seen["next"]["text"] == "Teyla cannot tell whether it can be installed."


def test_accounts_prove_a_product_is_built():
    b = block(install=False, usage={"users_total": "2"})
    assert status(b, "built") == "met"


def test_an_external_counter_in_one_repo_does_not_hide_another_repo():
    rp = {"stage": "live"}
    repos = [pathlib.Path("/code/a"), pathlib.Path("/code/b")]
    usage = {"a": {"external_users": "0"}, "b": {"users_total": "10"}}
    f = startup.facts(NOW, pid="app", rp=rp, repos=repos, usage=usage, ages={"a": NOW, "b": NOW}, money_enabled=False,
                      can_install=True, ai_cost_30d=None, attempts=growth.tally([], ["app"], TODAY)["app"])
    assert f["usage"]["external"] == 9
    assert f["usage"]["assumed"] is True


def test_overlapping_revenue_windows_do_not_earn_repeating():
    def snap(days):
        day = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=days)).isoformat()
        return {"id": "app", "day": day, "revenue_30d_usd": 10}
    usage = {"revenue_30d_usd": "10", "paying_users": "1"}
    assert status(block(usage=usage, money=True, snaps=[snap(27)]), "repeating") == "missing"
    assert status(block(usage=usage, money=True, snaps=[snap(30)]), "repeating") == "met"


def test_the_startup_commands_start_no_refresh(monkeypatch):
    from teyla import backlog, console, portfolio, state
    called = []
    monkeypatch.setattr(portfolio, "spawn_refresh", lambda *a, **k: called.append("portfolio"))
    monkeypatch.setattr(console, "spawn_refresh", lambda *a, **k: called.append("console") or True)
    monkeypatch.setattr(backlog, "spawn_refresh", lambda *a, **k: called.append("backlog"))
    monkeypatch.setattr(state, "_spawn_refresh", lambda: called.append("spend"))
    monkeypatch.setattr(portfolio, "enabled", lambda *a, **k: True)
    monkeypatch.setattr(state, "backlog_enabled", lambda: True)
    startup._view(NOW)
    assert called == []


def test_outside_accounts_alone_prove_a_product_is_built():
    b = block(install=False, usage={"external_users": "5"})
    assert status(b, "built") == "met"

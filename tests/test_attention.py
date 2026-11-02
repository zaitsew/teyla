"""`teyla attention` (docs/COMMANDS.md): one read-only list of what is wrong on this backend now.
Every source is faked or fed a temp home; nothing here reaches the network, the real ~/.teyla or a real process list."""
from __future__ import annotations

import datetime as dt
import json
import time

import pytest

from teyla import attention, cli, doctor, load, net, offers, portfolio, registry, reviews, schedules, storage

NOW = 1_800_000_000.0
DAY = 86400


def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="seconds")


def entry(**kw):
    e = {"id": "launchd:com.example.job", "source": "launchd", "name": "com.example.job", "verdict": "OK",
         "cadence": "1d", "last_run": dt.datetime.fromtimestamp(NOW - 3600, dt.timezone.utc), "last_exit": 0, "note": ""}
    e.update(kw)
    return e


def run_schedules(monkeypatch, entries):
    monkeypatch.setattr(schedules, "collect", lambda *a, **k: (entries, []))
    monkeypatch.setattr(schedules, "apply_registry", lambda es, reg, now: es)
    monkeypatch.setattr(schedules, "load_registry", lambda: {})
    monkeypatch.setattr(schedules, "forget_ignored", lambda *a, **k: None)
    return attention.source_schedules(NOW, {})


# --- the contract of one item --------------------------------------------------------------------------------

def test_an_item_has_the_documented_shape_and_a_short_title():
    it = attention.item("x:1", "disk", "one two three four five six seven eight nine ten eleven twelve", "d" * 400)
    assert set(it) == {"id", "kind", "title", "detail", "product", "severity", "facts", "actions"}
    assert len(it["title"].split()) <= 11 and it["title"].endswith("…")
    assert len(it["detail"]) <= attention.DETAIL_CHARS


def test_an_unknown_kind_or_severity_is_refused():
    with pytest.raises(AssertionError):
        attention.item("x", "mystery", "t", "d")
    with pytest.raises(AssertionError):
        attention.item("x", "disk", "t", "d", severity="loud")


# --- schedules -----------------------------------------------------------------------------------------------

def test_healthy_schedules_give_no_item_and_only_a_count(monkeypatch):
    items, quiet = run_schedules(monkeypatch, [entry(), entry(id="launchd:b", name="b")])
    assert items == [] and quiet == {"schedules": 2}


def test_a_failing_a_stale_and_a_vanished_task_each_become_one_row(monkeypatch):
    items, quiet = run_schedules(monkeypatch, [
        entry(id="launchd:f", name="f", verdict="FAILING", last_exit=1, note="exit 1"),
        entry(id="launchd:s", name="s", verdict="STALE", note="last ran 3 days ago"),
        entry(id="claude-desktop:gone", source="claude-desktop", name="gone", verdict="VANISHED", last_run=None),
        entry(id="launchd:ok", name="ok"),
        entry(id="launchd:u", name="u", verdict="UNKNOWN")])
    assert [i["kind"] for i in items] == ["schedule"] * 3 and quiet["schedules"] == 1 and quiet["schedules_unverified"] == 1
    by = {i["id"]: i for i in items}
    assert "is failing" in by["schedule:launchd:f"]["title"] and "last exit 1" in by["schedule:launchd:f"]["detail"].lower()
    assert by["schedule:launchd:f"]["actions"] == []                         # no pause command exists: no action is invented
    forget = by["schedule:claude-desktop:gone"]["actions"][0]
    assert forget["command"] == ["schedules", "forget", "claude-desktop:gone"] and forget["destructive"] is True


def test_problems_from_the_last_full_github_check_are_read_with_their_age(tmp_path, monkeypatch):
    p = tmp_path / "problems"
    p.write_text("schedule|github:example/app:weekly|FAILING\tlast run failed\nschedule|launchd:x|FAILING\tnot a github row\n")
    monkeypatch.setattr(schedules, "problems_path", lambda: p)
    import os
    os.utime(p, (NOW - 2 * 3600, NOW - 2 * 3600))
    rows = attention._problems_file_items(NOW)
    assert len(rows) == 1 and rows[0]["id"] == "schedule:github:example/app:weekly"
    assert "2 h ago" in rows[0]["detail"] and "is failing" in rows[0]["title"]


# --- portfolio: P1s and builds -------------------------------------------------------------------------------

class FakeRepo:
    name = "app-a"


def run_portfolio(monkeypatch, *, products, prs=(), checked=None, github=True):
    cache = {"github": {"x": 1} if github else {}, "checked": checked if checked is not None else
             {"github": iso(NOW - 3600), "stores": iso(NOW - 3600), "activity": iso(NOW)}}
    monkeypatch.setattr(portfolio, "load_cache", lambda: cache)
    monkeypatch.setattr(registry, "load", lambda: {"product": {p["id"]: object() for p in products}})
    from teyla import backlog
    monkeypatch.setattr(backlog, "view", lambda *a, **k: {})
    monkeypatch.setattr(reviews, "load_ledger", lambda path: {})
    monkeypatch.setattr(portfolio, "build", lambda *a, **k: {"products": products})
    monkeypatch.setattr(portfolio, "product_repos", lambda spec: [FakeRepo()])
    monkeypatch.setattr(portfolio, "_slugs", lambda repos, canon: {"example/app-a"})
    monkeypatch.setattr(portfolio, "merged_pr_states", lambda *a, **k: list(prs))
    return attention.source_portfolio(NOW, {})


def product(state="current", stage="live", primary="ios"):
    return {"id": "app-a", "title": "App A", "stage": stage, "primary": primary,
            "platforms": [{"platform": "ios", "state": state, "detail": "build 12 is two builds behind"}]}


def pr(n, state="open_p1", p1=1):
    return {"slug": "example/app-a", "number": n, "title": "Fix", "merged_at": NOW - 2 * DAY, "state": state, "p1": p1}


def test_merged_prs_with_an_open_p1_are_one_row_per_product(monkeypatch):
    items, _ = run_portfolio(monkeypatch, products=[product()], prs=[pr(7, p1=2), pr(5), pr(9, state="reviewed", p1=0)])
    p1 = [i for i in items if i["kind"] == "p1"]
    assert len(p1) == 1 and p1[0]["id"] == "p1:app-a" and p1[0]["product"] == "app-a"
    assert "2 merged PRs" in p1[0]["title"] and "#5, #7" in p1[0]["detail"] and "3 open P1" in p1[0]["detail"]
    assert "#9" not in p1[0]["detail"] and "GitHub read 1 h ago" in p1[0]["detail"]


def test_a_primary_build_that_is_behind_or_blocked_is_a_row_and_a_current_one_is_a_count(monkeypatch):
    items, quiet = run_portfolio(monkeypatch, products=[product(state="behind")])
    assert [i["kind"] for i in items] == ["build"] and "ios build is behind" in items[0]["title"] and quiet == {"builds": 0}
    items, quiet = run_portfolio(monkeypatch, products=[product(state="current")])
    assert items == [] and quiet == {"builds": 1}


def test_a_parked_product_and_a_product_without_a_ledger_hit_stay_quiet(monkeypatch):
    items, _ = run_portfolio(monkeypatch, products=[product(state="blocked", stage="parked")], prs=[pr(3)])
    assert items == []


def test_a_cache_that_was_never_read_or_is_old_says_so(monkeypatch):
    items, _ = run_portfolio(monkeypatch, products=[], checked={"github": "", "stores": iso(NOW - 3 * DAY)})
    got = {i["id"]: i for i in items}
    assert got["unknown:portfolio-github"]["kind"] == "unknown" and "never read" in got["unknown:portfolio-github"]["title"]
    assert "3 d old" in got["unknown:portfolio-stores"]["title"]
    assert got["unknown:portfolio-github"]["severity"] == "info"
    assert got["unknown:portfolio-github"]["actions"][0]["command"] == ["portfolio", "--refresh"]


# --- disk ----------------------------------------------------------------------------------------------------

GB = 1024 ** 3


def run_disk(monkeypatch, free, total_swept):
    monkeypatch.setattr(storage, "disk", lambda: {"total": 500 * GB, "used": 500 * GB - free, "free": free, "free_fraction": free / (500 * GB)})
    from teyla import storage_sweep
    monkeypatch.setattr(storage_sweep, "sweepable", lambda cfg=None: [{"name": "x", "bytes": total_swept, "items": 3}])
    return attention.source_disk(NOW, {})


def test_plenty_of_disk_is_a_count_not_a_row(monkeypatch):
    items, quiet = run_disk(monkeypatch, 300 * GB, 5 * GB)
    assert items == [] and quiet == {"disk": "300 GB free"}


def test_low_disk_names_the_sweep_size_and_offers_the_sweep_with_its_preview(monkeypatch):
    items, _ = run_disk(monkeypatch, 8 * GB, 4 * GB)
    it = items[0]
    assert it["kind"] == "disk" and it["severity"] == "act" and "8.0 GB free" in it["title"] and "4.0 GB" in it["detail"]
    a = it["actions"][0]
    assert a["command"] == ["storage", "sweep"] and a["preview"] == ["storage", "sweep", "--dry"] and a["destructive"] is True


def test_a_sweep_that_would_give_back_almost_nothing_is_not_offered(monkeypatch):
    items, _ = run_disk(monkeypatch, 8 * GB, 100 * 1024)
    assert items[0]["actions"] == [] and "almost nothing" in items[0]["detail"]


# --- the machine guard ---------------------------------------------------------------------------------------

def run_guard(monkeypatch, level, reasons=()):
    monkeypatch.setattr(load, "guard_conf", lambda cfg=None: {"enabled": True})
    monkeypatch.setattr(load, "safe_snapshot", lambda *a, **k: object())
    monkeypatch.setattr(load, "assess", lambda snap, conf=None, trend=None: load.Verdict(level, list(reasons)))
    return attention.source_guard(NOW, {})


def test_the_guard_is_a_row_only_at_critical(monkeypatch):
    items, quiet = run_guard(monkeypatch, "BUSY", ["load 9"])
    assert items == [] and quiet == {"guard": "busy"}
    items, quiet = run_guard(monkeypatch, load.CRITICAL, ["swap 95% used", "load 120"])
    assert [i["kind"] for i in items] == ["guard"] and "swap 95% used" in items[0]["title"] and items[0]["severity"] == "act"


def test_an_unreadable_process_table_is_an_unknown_row_not_a_calm_guard(monkeypatch):
    monkeypatch.setattr(load, "guard_conf", lambda cfg=None: {"enabled": True})
    monkeypatch.setattr(load, "safe_snapshot", lambda *a, **k: None)
    items, _ = attention.source_guard(NOW, {})
    assert items[0]["kind"] == "unknown" and items[0]["id"] == "unknown:guard"


# --- doctor --------------------------------------------------------------------------------------------------

def write_doctor(tmp_path, monkeypatch, checks, at):
    p = tmp_path / "doctor.json"
    p.write_text(json.dumps({"at": iso(at), "checks": checks}))
    monkeypatch.setattr(doctor, "DOCTOR_JSON", p)


def test_doctor_fix_rows_need_you_and_warn_rows_do_not_and_machine_rows_are_left_to_their_own_source(tmp_path, monkeypatch):
    write_doctor(tmp_path, monkeypatch, [
        {"level": "FIX", "name": "hooks:claude", "detail": "hook not wired", "fix": "teyla hook install"},
        {"level": "WARN", "name": "policy:ack", "detail": "changed", "fix": "teyla policy ack"},
        {"level": "WARN", "name": "storage:disk", "detail": "low", "fix": ""},
        {"level": "OK", "name": "python", "detail": "3.12", "fix": ""}], NOW - 3600)
    items, quiet = attention.source_doctor(NOW, {})
    assert [(i["kind"], i["severity"]) for i in items] == [("doctor", "act"), ("doctor", "info")]
    assert items[0]["facts"] == [{"label": "Fix", "text": "teyla hook install"}] and items[0]["actions"] == []
    assert quiet == {"doctor": "2 to look at"}


def test_a_clean_recent_doctor_is_ok_and_an_old_one_says_how_old(tmp_path, monkeypatch):
    write_doctor(tmp_path, monkeypatch, [{"level": "OK", "name": "python", "detail": "", "fix": ""}], NOW - 60)
    assert attention.source_doctor(NOW, {}) == ([], {"doctor": "ok"})
    write_doctor(tmp_path, monkeypatch, [], NOW - 5 * DAY)
    items, _ = attention.source_doctor(NOW, {})
    assert items[0]["kind"] == "unknown" and "5 d" in items[0]["title"]


def test_a_missing_or_corrupt_doctor_file_is_an_unknown_row(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor, "DOCTOR_JSON", tmp_path / "none.json")
    assert attention.source_doctor(NOW, {})[0][0]["kind"] == "unknown"
    (tmp_path / "bad.json").write_text("{not json")
    monkeypatch.setattr(doctor, "DOCTOR_JSON", tmp_path / "bad.json")
    assert attention.source_doctor(NOW, {})[0][0]["kind"] == "unknown"


# --- offers --------------------------------------------------------------------------------------------------

def fake_offer(id_="O1", applies=True, undo="teyla undo O1 puts it back."):
    return offers.Offer(id=id_, title="Compact earlier", change={"summary": "Sets one key."}, saving_usd_month=None, basis="",
                        benefit=None, tradeoff="Older context is summarised sooner.", undo=undo, applies=applies, short="a short one")


def test_an_open_offer_shows_its_tradeoff_its_undo_and_a_preview_first_apply(monkeypatch):
    from teyla import figures
    monkeypatch.setattr(figures, "onboarded", lambda: False)
    monkeypatch.setattr(offers, "build", lambda with_savings=False: [fake_offer(), fake_offer("O2", applies=False)])
    items, quiet = attention.source_offers(NOW, {})
    assert len(items) == 1 and items[0]["kind"] == "offer" and items[0]["severity"] == "info" and quiet == {"offers": 1}
    assert [f["label"] for f in items[0]["facts"]] == ["Trade-off", "Undo"]
    a = items[0]["actions"][0]
    assert a["command"] == ["apply", "O1", "--yes"] and a["preview"] == ["apply", "O1", "--dry"] and a["destructive"] is False


def test_an_offer_without_an_undo_is_confirmed_as_destructive(monkeypatch):
    from teyla import figures
    monkeypatch.setattr(figures, "onboarded", lambda: False)
    monkeypatch.setattr(offers, "build", lambda with_savings=False: [fake_offer(undo="Remove it by hand.")])
    assert attention.source_offers(NOW, {})[0][0]["actions"][0]["destructive"] is True


def test_offers_the_owner_answered_are_quiet(monkeypatch):
    from teyla import figures
    monkeypatch.setattr(figures, "onboarded", lambda: True)
    assert attention.source_offers(NOW, {}) == ([], {"offers": "answered"})


# --- the report ----------------------------------------------------------------------------------------------

def src(items=(), quiet=None):
    return lambda now, cfg: (list(items), dict(quiet or {}))


def test_healthy_sources_give_an_empty_list_and_the_quiet_counts():
    rep = attention.collect(NOW, sources={"a": src(quiet={"schedules": 4}), "b": src(quiet={"doctor": "ok"})}, cfg={})
    assert rep["items"] == [] and rep["quiet"] == {"schedules": 4, "doctor": "ok"} and rep["version"] == attention.VERSION
    assert rep["generated"].startswith("2027-01-15")
    assert attention.render_text(rep).startswith("Nothing needs you here.")


def test_a_source_that_raises_becomes_an_unknown_row_never_a_calm_report():
    def boom(now, cfg):
        raise RuntimeError("gh exploded")
    rep = attention.collect(NOW, sources={"portfolio": boom, "disk": src(quiet={"disk": "50 GB free"})}, cfg={})
    assert [i["kind"] for i in rep["items"]] == ["unknown"] and rep["items"][0]["id"] == "unknown:portfolio"
    assert "gh exploded" in rep["items"][0]["detail"] and rep["items"][0]["severity"] == "act"
    assert "Nothing needs you" not in attention.render_text(rep)


def test_a_source_that_does_not_answer_in_time_becomes_an_unknown_row():
    def slow(now, cfg):
        time.sleep(2)
        return [], {}
    t = time.monotonic()
    rep = attention.collect(NOW, sources={"guard": slow, "disk": src()}, cfg={}, timeout=0.2)
    assert time.monotonic() - t < 1.5
    assert rep["items"][0]["id"] == "unknown:guard" and "did not answer" in rep["items"][0]["detail"]


def test_act_rows_come_before_info_rows_and_the_worst_kind_first():
    a = attention.item("o", "offer", "An offer", "d", severity="info")
    b = attention.item("d", "disk", "Disk low", "d")
    c = attention.item("g", "guard", "Guard critical", "d")
    rep = attention.collect(NOW, sources={"x": src([a, b, c])}, cfg={})
    assert [i["kind"] for i in rep["items"]] == ["guard", "disk", "offer"]


def test_the_collection_runs_with_the_network_closed_whatever_safe_mode_says(monkeypatch):
    seen = []
    net.allow_for_this_command(True)
    assert net.allowed() is True
    attention.collect(NOW, sources={"x": lambda now, cfg: (seen.append(net.allowed()) or [], {})}, cfg={})
    assert seen == [False] and net.allowed() is True


def test_offline_restores_the_previous_state_even_after_an_error():
    with pytest.raises(ValueError):
        with net.offline():
            assert net.allowed() is False
            raise ValueError
    assert net._offline is False


# --- the actions are commands that exist ---------------------------------------------------------------------

def parses(argv):
    ns = cli.build_parser().parse_args(argv)
    return ns


def test_every_action_and_preview_the_sources_can_emit_parses_with_the_real_cli(monkeypatch):
    from teyla import figures
    monkeypatch.setattr(figures, "onboarded", lambda: False)
    monkeypatch.setattr(offers, "build", lambda with_savings=False: [fake_offer()])
    out = []
    out += run_schedules(monkeypatch, [entry(id="launchd:gone", name="gone", verdict="VANISHED", last_run=None)])[0]
    out += run_disk(monkeypatch, 8 * GB, 4 * GB)[0]
    out += attention.source_offers(NOW, {})[0]
    out += run_portfolio(monkeypatch, products=[], checked={"github": "", "stores": ""})[0]
    cmds = [(a["command"], a["preview"]) for i in out for a in i["actions"]]
    assert len(cmds) == 5            # forget, sweep, apply, and one refresh per cache that was never read
    for command, preview in cmds:
        parses(command)
        if preview:
            parses(preview)


def test_every_action_with_a_preview_has_a_preview_that_differs_from_the_command(monkeypatch):
    items = run_disk(monkeypatch, 8 * GB, 4 * GB)[0]
    for i in items:
        for a in i["actions"]:
            assert a["preview"] is None or a["preview"] != a["command"]


def test_no_action_charges_money_sends_a_message_deploys_or_submits(monkeypatch):
    banned = {"release", "submit", "deploy", "publish", "send", "buy", "testflight", "play"}
    from teyla import figures
    monkeypatch.setattr(figures, "onboarded", lambda: False)
    monkeypatch.setattr(offers, "build", lambda with_savings=False: [fake_offer()])
    out = run_disk(monkeypatch, 8 * GB, 4 * GB)[0] + attention.source_offers(NOW, {})[0]
    for i in out:
        for a in i["actions"]:
            assert not banned & set(a["command"][:1])


# --- output --------------------------------------------------------------------------------------------------

def test_the_text_output_lists_the_command_the_preview_and_the_warning(capsys):
    it = attention.item("disk:free", "disk", "Disk is low: 8 GB free", "5% free.",
                        actions=[attention.action("Free space", ["storage", "sweep"], ["storage", "sweep", "--dry"], destructive=True)])
    text = attention.render_text({"items": [it], "quiet": {"schedules": 3}})
    assert "1 need you" in text and "teyla storage sweep" in text and "preview: teyla storage sweep --dry" in text
    assert "[cannot be undone]" in text and "schedules 3" in text


def test_the_json_flag_prints_one_document(monkeypatch, capsys):
    monkeypatch.setattr(attention, "SOURCES", {"a": src(quiet={"x": 1})})
    assert cli.main(["attention", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["items"] == [] and doc["quiet"] == {"x": 1}

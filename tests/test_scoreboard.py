"""`teyla today score`: the outcome scoreboard. The clock is fixed (Wednesday of ISO week 2026-W46, Monday 9 Nov
to Sunday 15 Nov); the ledger, usage batches, registry and testflight cache are real files under tmp paths;
asks and design cards are built by hand. No network call, no real ~/.teyla."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib

import pytest

from teyla import asks, cli, config, design_cycle, net, productize, registry, scoreboard, testflight, today, usage
from teyla.ui import Style

NOW = dt.datetime(2026, 11, 11, 12, 0).timestamp()       # local time, so the local week is the same everywhere
MON, SUN, LAST_SUN = "2026-11-09", "2026-11-15", "2026-11-08"
INSTALL_A = "11111111-1111-4111-8111-111111111111"
INSTALL_B = "22222222-2222-4222-8222-222222222222"
PLAIN = Style(env={"NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def machine(tmp_path, monkeypatch):
    monkeypatch.setattr(scoreboard, "_now", lambda: NOW)
    monkeypatch.setattr(asks, "_now", lambda: NOW)
    monkeypatch.setattr(config, "TEYLA_DIR", tmp_path / "teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "teyla" / "config.toml")
    state = {"asks": [], "cards": []}
    monkeypatch.setattr(asks, "collect", lambda *a, **k: list(state["asks"]))
    monkeypatch.setattr(design_cycle, "open_cards", lambda: list(state["cards"]))
    return state


def ledger(*rows):
    p = pathlib.Path(os.environ["TEYLA_HOME"]) / "growth" / "ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def ask(id_, product="atlas", *, days_ago=1.0, kind="question", question="Which font?", status="open"):
    return asks.Ask(id=id_, kind=kind, product=product, title="A session", question=question, context="", options=[],
                    when=NOW - days_ago * 86400, archived=False, link="", pr="", harness="claude-code", status=status)


def register(**products):
    reg = registry.load()
    for pid, fields in products.items():
        reg["product"][pid] = {**registry.new_product(pid, stage="building"), **fields}
    registry.save(reg)


def batch(product, install, *events, name):
    d = usage.product_dir(product)
    d.mkdir(parents=True, exist_ok=True)
    evs = [{"t": 1_790_000_000, "k": k, "id": i, "r": r, "b": "1"} for k, i, r in events]
    (d / f"{name}.json").write_text(json.dumps({"v": 1, "id": name, "install": install,
                                                "sent": "2026-11-10T10:00:00Z", "events": evs}))


def tf_row(product="atlas", platform="IOS", *, uploaded="2026-11-09T09:00:00Z", build="120", inst="120"):
    return {"product": product, "repo": "/x", "bundle_id": "com.example.a", "verdict": "current", "error": None,
            "platforms": [], "payload": {"platforms": [{
                "platform": platform,
                "newest_uploaded": {"version": "1.0", "build": build, "uploaded": uploaded},
                "newest_installable": {"version": "1.0", "build": inst} if inst else None,
                "behind": 0, "blockers": []}]}}


def metrics():
    return scoreboard.snapshot(NOW)["metrics"]


def tf_args(**flags):
    return argparse.Namespace(**{"paths": [], "json": False, "quiet": False, "china": False, **flags})


# --- ledger metrics ---------------------------------------------------------------------------------

def test_ledger_metrics_with_data():
    ledger({"ev": "published", "day": MON, "product": "a"}, {"ev": "published", "day": SUN, "product": "a", "n": 2},
           {"ev": "attempt", "kind": "dm", "day": MON, "product": "a"},
           {"ev": "attempt", "kind": "icp-meeting", "day": "2026-11-10", "product": "b"},
           {"ev": "attempt", "kind": "call", "day": "2026-11-10", "product": "b"},
           {"ev": "attempt", "kind": "response", "day": "2026-11-10", "product": "b"},
           {"ev": "attempt", "kind": "dm", "day": MON, "product": "a", "by": "agent"})
    m = metrics()
    assert m["posts_published"] == {"value": 3, "source": "growth ledger"}
    s = m["sale_attempts"]
    assert s["value"] == 6 and s["breakdown"] == {"posts": 3, "marketing": 2, "icp_meetings": 1}
    assert s["claimed_by_agents"] == 1
    c = m["conversations"]
    assert c["value"] == 2 and c["replies"] == 1
    assert c["with_next_step"]["value"] == "not_measured" and "next-step" in c["with_next_step"]["reason"]


def test_week_boundary_last_sunday_and_next_monday_do_not_count():
    ledger({"ev": "published", "day": LAST_SUN, "product": "a"}, {"ev": "published", "day": "2026-11-16", "product": "a"},
           {"ev": "attempt", "kind": "call", "day": LAST_SUN, "product": "a"})
    m = metrics()
    assert m["posts_published"]["value"] == 0 and m["sale_attempts"]["value"] == 0 and m["conversations"]["value"] == 0


def test_no_ledger_is_not_measured_with_a_reason():
    m = metrics()
    for k in ("posts_published", "sale_attempts", "conversations"):
        assert m[k]["value"] == "not_measured" and "no growth ledger" in m[k]["reason"]


# --- first value ------------------------------------------------------------------------------------

def test_first_value_no_focus_product():
    register(atlas={"name": "Atlas"})
    fv = metrics()["first_value"]
    assert fv["value"] == "not_measured" and fv["reason"] == "no focus product: set one with `teyla product core <id>`"


def test_first_value_task_not_set_and_no_usage():
    register(atlas={"name": "Atlas", "focus": True}, lens={"name": "Lens", "focus": True, "first_value": "first-pour"})
    fv = metrics()["first_value"]
    assert fv["value"] == "not_measured"
    assert "teyla product set atlas first_value=<task>" in fv["reason"]
    assert "lens: no usage captured" in fv["reason"]


def test_first_value_counts_distinct_installs_with_a_successful_task():
    register(atlas={"name": "Atlas", "focus": True, "first_value": "first-pour"}, lens={"name": "Lens", "focus": True})
    batch("atlas", INSTALL_A, ("task", "first-pour", "success"), name="b1")
    batch("atlas", INSTALL_A, ("task", "first-pour", "success"), name="b2")       # same install again
    batch("atlas", INSTALL_B, ("task", "first-pour", "cancel"), ("task", "other", "success"), name="b3")
    fv = metrics()["first_value"]
    assert fv["value"] == 1 and fv["measured_products"] == 1 and fv["focus_products"] == 2
    assert "not people" in fv["source"]
    rows = {r["product"]: r for r in fv["products"]}
    assert rows["atlas"]["value"] == 1 and rows["lens"]["value"] == "not_measured"
    batch("atlas", INSTALL_B, ("task", "first-pour", "success"), name="b4")
    assert metrics()["first_value"]["value"] == 2


def test_set_first_value_through_the_registry():
    register(atlas={"name": "Atlas"})
    reg = registry.load()
    assert registry.set_field(reg, "atlas", "first_value", "first-pour") == "atlas: first_value = first-pour"
    registry.save(reg)
    assert registry.load()["product"]["atlas"]["first_value"] == "first-pour"
    registry.set_field(reg, "atlas", "first_value", "")
    assert "first_value" not in reg["product"]["atlas"]


# --- decisions --------------------------------------------------------------------------------------

def test_open_decisions_empty_is_zero_and_has_no_age():
    od = metrics()["open_decisions"]
    assert od["value"] == 0 and od["oldest_days"] is None and od["by_age"] == {"0-7": 0, "8-14": 0, "15+": 0}
    assert od["decision_minutes"]["value"] == "not_measured" and "deciding" in od["decision_minutes"]["reason"]
    assert od["design_picks"]["value"] == 0


def test_open_decisions_ages_critical_and_filters(machine):
    register(atlas={"name": "Atlas"}, old={"name": "Old", "stage": "parked"})
    machine["asks"] = [ask("a1", days_ago=3), ask("a2", days_ago=10), ask("a3", days_ago=20, question="A token leaked"),
                       ask("r1", kind="reminder", days_ago=30), ask("r2", kind="report", days_ago=30),
                       ask("d1", days_ago=30, status="done"),
                       ask("p1", "old", days_ago=40)]            # parked and not critical: muted
    od = metrics()["open_decisions"]
    assert od["value"] == 3 and od["oldest_days"] == 20 and od["over_14_days"] == 1 and od["critical"] == 1
    assert od["by_age"] == {"0-7": 1, "8-14": 1, "15+": 1}
    assert [x["id"] for x in od["oldest"]] == ["a3", "a2", "a1"]


def test_a_muted_product_is_not_counted_but_a_critical_ask_in_it_is(machine):
    register(old={"name": "Old", "stage": "parked"})
    machine["asks"] = [ask("p1", "old"), ask("p2", "old", question="The payment failed")]
    assert metrics()["open_decisions"]["value"] == 1


def test_design_picks_age_comes_from_the_options_file(machine, tmp_path):
    repo = tmp_path / "atlas"
    folder = design_cycle.folder(repo, "d1")
    folder.mkdir(parents=True)
    opts = folder / "options.yaml"
    opts.write_text("options: []\n")
    os.utime(opts, (NOW - 5 * 86400, NOW - 5 * 86400))
    machine["cards"] = [{"repo": repo, "product": "atlas", "decision": "d1", "title": "Home layout"},
                        {"repo": tmp_path / "lens", "product": "lens", "decision": "d2", "title": "Icon"}]
    dp = metrics()["open_decisions"]["design_picks"]
    assert dp["value"] == 2
    assert dp["cards"][0] == {"product": "atlas", "decision": "d1", "title": "Home layout", "age_days": 5}
    assert dp["cards"][1]["age_days"] == "not_measured"


# --- builds -----------------------------------------------------------------------------------------

def test_builds_no_cache():
    b = metrics()["builds_to_try"]
    assert b["value"] == "not_measured" and b["reason"] == "run `teyla testflight` once (it asks App Store Connect)"


def test_builds_fresh_cache_lists_recent_installable_builds_only():
    testflight.write_cache([tf_row("atlas"), tf_row("lens", "MAC_OS", uploaded="2026-11-01T09:00:00Z"),
                            tf_row("cellar", build="121", inst="120"), tf_row("vine", inst=None)], now=NOW - 3600)
    b = metrics()["builds_to_try"]
    assert b["value"] == 1 and b["stale"] is False
    assert b["builds"] == [{"product": "atlas", "platform": "iOS", "build": "120", "uploaded": "2026-11-09"}]
    assert "1h old" in b["source"] and "Teyla records no verdict" in b["source"]


def test_builds_stale_cache_is_still_shown_and_marked():
    testflight.write_cache([tf_row("atlas", uploaded="2026-11-09T09:00:00Z")], now=NOW - 60 * 3600)
    b = metrics()["builds_to_try"]
    assert b["value"] == 1 and b["stale"] is True
    text = scoreboard.render(scoreboard.snapshot(NOW), PLAIN)
    assert "2d old" in text and "STALE" in text


def test_the_cache_writer_runs_on_text_json_and_quiet_but_not_china(monkeypatch, capsys):
    monkeypatch.setattr(net, "gate", lambda *a, **k: True)
    monkeypatch.setattr(testflight, "run", lambda paths=None: [{**tf_row(), "lines": ["atlas  iOS"]}])
    monkeypatch.setattr(testflight, "run_china", lambda paths=None: [])
    path = testflight.cache_path()
    testflight.cmd_testflight(tf_args(china=True))
    assert not path.exists()
    for flags in ({}, {"json": True}, {"quiet": True}):
        path.unlink(missing_ok=True)
        testflight.cmd_testflight(tf_args(**flags))
        doc = json.loads(path.read_text())
        assert doc["version"] == 1 and doc["generated"].endswith("Z") and "lines" not in doc["rows"][0]
        assert not list(path.parent.glob("*.tmp"))
    capsys.readouterr()
    rows, age = testflight.load_cache()
    assert rows[0]["product"] == "atlas" and age is not None and age >= 0


def test_no_rows_writes_no_cache(monkeypatch):
    monkeypatch.setattr(net, "gate", lambda *a, **k: True)
    monkeypatch.setattr(testflight, "run", lambda paths=None: [])
    testflight.cmd_testflight(tf_args())
    assert not testflight.cache_path().exists()


def test_refresh_runs_the_live_check_through_the_gate(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(net, "gate", lambda what, *a, **k: calls.append(what) or True)
    monkeypatch.setattr(testflight, "run", lambda paths=None: [tf_row("atlas", uploaded="2026-11-10T09:00:00Z")])
    # the cache is stamped with the real clock, so the age is read against the real clock too
    monkeypatch.setattr(scoreboard, "_now", lambda: NOW)
    assert cli.main(["today", "score", "--refresh", "--json"]) == 0
    assert len(calls) == 1
    assert testflight.cache_path().exists()
    assert json.loads(capsys.readouterr().out)["metrics"]["builds_to_try"]["source"].startswith("teyla testflight cache")


def test_refresh_refused_by_safe_mode_still_shows_the_cache(monkeypatch, capsys):
    monkeypatch.setattr(net, "gate", lambda *a, **k: False)
    monkeypatch.setattr(testflight, "run", lambda paths=None: pytest.fail("the check must not run"))
    assert cli.main(["today", "score", "--refresh", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["metrics"]["builds_to_try"]["value"] == "not_measured"


# --- dates ------------------------------------------------------------------------------------------

def test_hard_dates_come_from_config_and_are_omitted_when_none():
    assert scoreboard.hard_dates(dt.date(2026, 11, 11)) == []
    assert "days left" not in scoreboard.render(scoreboard.snapshot(NOW), PLAIN)
    config.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.CONFIG_PATH.write_text('[dates]\nrace = "2026-12-01"\nbad = "soon"\nlaunch = "2026-11-21"\n')
    assert scoreboard.hard_dates(dt.date(2026, 11, 11)) == [
        {"name": "launch", "date": "2026-11-21", "days_left": 10}, {"name": "race", "date": "2026-12-01", "days_left": 20}]
    assert "launch          10 days left" in scoreboard.render(scoreboard.snapshot(NOW), PLAIN)


# --- the command ------------------------------------------------------------------------------------

def test_json_keys_and_week(capsys):
    assert cli.main(["today", "score", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert set(d) == {"version", "generated", "week", "start", "end", "metrics", "hard_dates"}
    assert (d["week"], d["start"], d["end"]) == ("2026-W46", MON, SUN)
    assert list(d["metrics"]) == ["posts_published", "sale_attempts", "conversations", "first_value",
                                  "open_decisions", "builds_to_try"]
    for m in d["metrics"].values():
        assert "value" in m and "source" in m
        assert m["value"] != "not_measured" or m["reason"]


def test_text_screen_is_short_and_prints_not_measured_literally(capsys, machine):
    register(atlas={"name": "Atlas", "focus": True})
    machine["asks"] = [ask("a1", days_ago=3), ask("a2", days_ago=9), ask("a3", days_ago=20), ask("a4", days_ago=1)]
    testflight.write_cache([tf_row("atlas")], now=NOW - 3600)
    ledger({"ev": "published", "day": MON, "product": "a"})
    assert cli.main(["today", "score"]) == 0
    out = capsys.readouterr().out
    assert len(out.splitlines()) <= 24, out
    assert "Scoreboard  2026-W46" in out and "not_measured" in out
    assert "Posts           1" in out and "Oldest decisions" in out
    assert out.index("20d  A session") < out.index("9d  A session")
    assert "build 120  uploaded 2026-11-09" in out


def test_score_writes_nothing(machine, capsys):
    register(atlas={"name": "Atlas", "focus": True, "first_value": "t"})
    ledger({"ev": "published", "day": MON, "product": "a"})
    machine["asks"] = [ask("a1")]
    roots = [pathlib.Path(os.environ["TEYLA_HOME"]), config.TEYLA_DIR]

    def tree():
        return {str(p): p.read_bytes() for r in roots for p in r.rglob("*") if p.is_file()}
    before = tree()
    assert cli.main(["today", "score"]) == 0 and cli.main(["today", "score", "--json"]) == 0
    capsys.readouterr()
    assert tree() == before


def test_plain_today_is_unchanged_and_rejects_other_views(capsys):
    with pytest.raises(SystemExit):
        cli.main(["today", "nonsense"])
    capsys.readouterr()
    p = argparse.ArgumentParser()
    today.register(p.add_subparsers())
    ns = p.parse_args(["today"])
    assert ns.view is None and ns.fn is today.cmd_today and ns.json is False and ns.fresh is False


def test_a_run_scoped_to_paths_leaves_the_cache_alone(monkeypatch, capsys):
    monkeypatch.setattr(net, "gate", lambda *a, **k: True)
    monkeypatch.setattr(productize, "find_manifests", lambda paths=None: ["/x/teyla.toml"])
    testflight.write_cache([tf_row("atlas"), tf_row("lens")], now=NOW - 3600)
    monkeypatch.setattr(testflight, "run", lambda paths=None: [{**tf_row("lens"), "lines": ["lens  iOS"]}])
    testflight.cmd_testflight(tf_args(paths=["/x"]))
    capsys.readouterr()
    rows, _ = testflight.load_cache()
    assert {r["product"] for r in rows} == {"atlas", "lens"}


def test_a_cache_of_only_errors_is_not_measured():
    testflight.write_cache([{**tf_row("atlas"), "verdict": "error", "payload": None}], now=NOW - 3600)
    b = metrics()["builds_to_try"]
    assert b["value"] == "not_measured" and "every row was an error" in b["reason"]


def test_an_error_row_is_counted_as_unread():
    testflight.write_cache([tf_row("atlas"), {**tf_row("lens"), "verdict": "error", "payload": None}], now=NOW - 3600)
    b = metrics()["builds_to_try"]
    assert b["value"] == 1 and b["unread_products"] == 1

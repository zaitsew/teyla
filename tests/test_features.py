"""`teyla features`: the pack catalog, the checklist, turning packs on and off, and the reminders doctor shows
when a pack's problem appears. Every machine here is a fake HOME; launchd and the plugin clone are stubbed."""
from __future__ import annotations

import json

import pytest

from teyla import cli, config, features, figures, offers, routine_install


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    from teyla import plugin_install
    calls = {"routine": 0, "plugin": 0}

    def routine(*a, **k):
        calls["routine"] += 1
        return ["stub: routine installed"]

    def plugin(source, plugins_dir=None):
        calls["plugin"] += 1
        return ["stub: plugin installed"]
    monkeypatch.setattr(routine_install, "install", routine)
    monkeypatch.setattr(plugin_install, "install", plugin)
    monkeypatch.setattr(features.sys, "platform", "darwin")
    return calls


def _run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def _row(pack_id, checks=None):
    return next(r for r in features.rows(checks) if r["id"] == pack_id)


# --- the catalog -----------------------------------------------------------------------------------

def test_every_offer_belongs_to_exactly_one_pack():
    ids = [o for p in features.PACKS for o in p.offers]
    assert sorted(ids) == [f"O{n}" for n in range(1, 8)] and len(ids) == len(set(ids))
    assert len({p.id for p in features.PACKS}) == len(features.PACKS)


def test_every_command_a_pack_names_is_a_teyla_command():
    names = set(cli._commands(cli.build_parser()))
    for p in features.PACKS:
        for c in p.commands:
            assert c.split()[0] == "teyla" and c.split()[1] in names, f"{p.id}: {c}"


def test_every_switch_is_a_config_key():
    for p in features.PACKS:
        for k in list(p.switches) + list(p.quiet_when_unchosen):
            table, key = k.split(".", 1)
            assert key in config.DEFAULTS[table], k


def test_list_shows_both_kinds(fake_home, capsys):
    code, out, _ = _run(["features"], capsys)
    assert code == 0 and "Automatic" in out and "Toolkit" in out
    for p in features.PACKS:
        assert p.title in out
    d = json.loads(_run(["features", "--json"], capsys)[1])
    assert [r["id"] for r in d] == [p.id for p in features.PACKS]


# --- state -----------------------------------------------------------------------------------------

def test_a_fresh_mac_has_the_guard_off_although_its_default_is_on(fake_home):
    assert _row("load")["status"] == features.OFF
    assert all(not w["what"].startswith("guard.enabled") for w in _row("load")["parts"])


def test_a_guard_switched_off_by_hand_counts(fake_home):
    config.set_value("guard.enabled", "false")
    assert any(w["what"].startswith("guard.enabled") and not w["done"] for w in _row("load")["parts"])


def test_a_toolkit_pack_is_on_once_chosen(fake_home):
    assert _row("design")["status"] == features.OFF
    features.record_choice(["design"])
    assert _row("design")["status"] == features.ON


def test_first_run_suggests_the_core_packs(fake_home):
    picked = [r["id"] for r in features.rows() if r["suggested"]]
    assert set(features.CORE) <= set(picked) and "design" not in picked


# --- on and off ------------------------------------------------------------------------------------

def test_on_load_sets_the_switches_installs_the_plugin_and_the_agents(fake_home, capsys, _stubs):
    code, out, _ = _run(["features", "on", "load", "--yes"], capsys)
    assert code == 0, out
    cfg = config.load()
    assert cfg["guard"]["agent"] is True and _stubs["routine"] == 1 and _stubs["plugin"] == 1
    assert "load" in features.chosen()


def test_on_dry_writes_nothing(fake_home, capsys, _stubs):
    code, out, _ = _run(["features", "on", "disk", "--dry"], capsys)
    assert code == 0 and "storage.sims_agent = true" in out and "--dry" in out
    assert not config.CONFIG_PATH.exists() and _stubs["routine"] == 0


def test_on_without_a_terminal_and_without_yes_refuses(fake_home, capsys):
    code, _, err = _run(["features", "on", "disk"], capsys)
    assert code == 1 and "--yes" in err and not config.CONFIG_PATH.exists()


def test_on_no_offers_leaves_the_offers_alone(fake_home, capsys):
    fake_home.settings.write_text('{"model": "opus"}\n')
    code, out, _ = _run(["features", "on", "cost", "--yes", "--no-offers"], capsys)
    assert code == 0 and "autoCompactWindow" not in fake_home.settings.read_text()
    assert config.load()["hooks"]["context_budget"] is True


def test_on_cost_applies_its_offers_and_off_undoes_them(fake_home, capsys):
    fake_home.settings.write_text('{\n  "model": "opus",\n  "theme": "dark"\n}\n')
    before = fake_home.settings.read_bytes()
    assert _run(["features", "on", "cost", "--yes"], capsys)[0] == 0
    assert json.loads(fake_home.settings.read_text())["autoCompactWindow"] == 335000
    assert _run(["features", "off", "cost"], capsys)[0] == 0
    assert fake_home.settings.read_bytes() == before
    assert config.load()["hooks"]["context_budget"] is False and "cost" not in features.chosen()


def test_off_quiet_mutes_the_reminder(fake_home, capsys):
    _run(["features", "off", "load", "--quiet"], capsys)
    assert "load" in features.muted()
    checks = [{"level": "WARN", "name": "machine:load", "detail": "x"}]
    assert not features.nudges(checks)


def test_an_unknown_pack_is_a_usage_error(fake_home, capsys):
    code, _, err = _run(["features", "on", "nope"], capsys)
    assert code == 2 and "the packs are" in err


def test_choose_records_and_changes_nothing_else(fake_home, capsys, _stubs):
    assert _run(["features", "choose", "design", "ship"], capsys)[0] == 0
    assert features.chosen() == ["design", "ship"] and _stubs["routine"] == 0


# --- quiet hooks for packs left out ----------------------------------------------------------------

def test_quiet_unchosen_writes_only_keys_still_at_their_default(fake_home):
    rs = features.rows()
    features.quiet_unchosen(["cost"], rs)
    cfg = config.load()
    assert cfg["guard"]["enabled"] is False and cfg["intent"]["enabled"] is False


def test_quiet_unchosen_keeps_a_key_the_person_set(fake_home):
    config.set_value("guard.enabled", "true")
    features.quiet_unchosen(["cost"], features.rows())
    assert config.load()["guard"]["enabled"] is True


def test_quiet_unchosen_leaves_a_pack_that_is_partly_on(fake_home):
    config.set_value("guard.agent", "true")
    rs = features.rows()
    assert next(r for r in rs if r["id"] == "load")["status"] == features.PARTLY
    features.quiet_unchosen(["cost"], rs)
    assert "enabled" not in (config._read(config.CONFIG_PATH).get("guard") or {})


# --- reminders -------------------------------------------------------------------------------------

def test_critical_load_reminds_of_the_machine_guard(fake_home):
    rows = features.nudges([{"level": "WARN", "name": "machine:load", "detail": "swap 60%"}])
    assert [r["name"] for r in rows] == ["feature:load"]
    assert "CRITICAL" in rows[0]["detail"] and rows[0]["fix"].startswith("teyla features on load")


def test_a_panic_is_named_before_the_load(fake_home):
    rows = features.nudges([{"level": "WARN", "name": "machine:load", "detail": ""},
                            {"level": "WARN", "name": "machine:crash", "detail": ""}])
    assert "kernel panic" in rows[0]["detail"]


def test_a_low_disk_reminds_of_disk_cleanup(fake_home):
    rows = features.nudges([{"level": "WARN", "name": "storage:disk", "detail": "9.1 GB free (4%)"}])
    assert rows[0]["name"] == "feature:disk" and "9.1 GB free" in rows[0]["detail"] and "(4%)" not in rows[0]["detail"]


def test_no_reminder_once_the_pack_is_on(fake_home):
    config.set_value("storage.sims_agent", "true")
    config.set_value("storage.sweep_agent", "true")
    for label in (routine_install.SIMS_LABEL, routine_install.SWEEP_LABEL):
        p = routine_install.optional_paths(label)["plist"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("<plist/>")
    assert not features.nudges([{"level": "WARN", "name": "storage:disk", "detail": "9 GB free"}])


def test_priced_token_waste_reminds_of_the_cost_pack(fake_home):
    figures.record_start({"diagnosis": {"days": 30}, "offers": [
        {"id": "O1", "title": "t", "applies": True, "saving_usd_month": {"low": 40, "high": 90}}]}, False)
    rows = features.nudges([])
    assert rows[0]["name"] == "feature:cost" and "$90" in rows[0]["detail"]


def test_doctor_carries_the_reminders(fake_home, monkeypatch):
    from teyla import doctor
    monkeypatch.setattr(doctor, "_load_check", lambda cfg: doctor._check("WARN", "machine:load", "swap 60%", "teyla load"))
    cs = doctor.checks(scan_repos=True)
    assert any(c["name"] == "feature:load" and c["level"] == "WARN" for c in cs)


# --- the checklist ---------------------------------------------------------------------------------

def test_pick_toggles_and_enter_accepts(fake_home, capsys):
    rs = features.rows()
    answers = iter(["1 3", "x", ""])
    picked = features.pick(rs, lambda prompt: next(answers))
    first = {r["id"] for r in rs if r["suggested"]}
    assert set(picked) == first ^ {rs[0]["id"], rs[2]["id"]}
    assert "type a number" in capsys.readouterr().out


def test_pick_quit_is_none(fake_home):
    assert features.pick(features.rows(), lambda prompt: "q") is None


def test_offers_still_build_with_the_catalog(fake_home):
    assert {o.id for o in offers.build(with_savings=False, home=fake_home.home)} == set(features.OFFER_PACK)


def test_a_partly_on_pack_reminds_only_when_its_problem_is_acute(fake_home):
    config.set_value("guard.agent", "true")                     # load: partly on, and acute
    config.set_value("hooks.context_budget", "true")            # cost: partly on, not acute
    figures.record_start({"diagnosis": {"days": 30}, "offers": [
        {"id": "O1", "title": "t", "applies": True, "saving_usd_month": {"low": 40, "high": 90}}]}, False)
    names = [r["name"] for r in features.nudges([{"level": "WARN", "name": "machine:load", "detail": ""}])]
    assert names == ["feature:load"]

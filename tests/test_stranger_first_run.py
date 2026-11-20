"""A stranger's first run: a machine with no ~/ops, no ~/repos, no sessions, no POLICY.md and maybe a Codex app but no
Codex CLI. Doctor must not call opt-in features faults, `teyla start` must still show the packs, and the quick start
must install the release. Everything runs in a temporary HOME."""
from __future__ import annotations

import json

import pytest

from teyla import cli, config, doctor, features, health, load, plugin_install, policy, routine_install, spend, update


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(config, "HOME", h)
    monkeypatch.setattr(config, "TEYLA_DIR", h / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", h / ".teyla" / "config.toml")
    monkeypatch.setattr(update, "CHECK_PATH", h / ".teyla" / "update-check.json")
    monkeypatch.setattr(doctor, "DOCTOR_JSON", h / ".teyla" / "doctor.json")
    monkeypatch.setattr(doctor, "DOCTOR_SUMMARY", h / ".teyla" / "doctor.summary")
    monkeypatch.setattr(policy, "HOME", h)
    monkeypatch.setattr(policy, "POLICY", h / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "BASE_PATH", h / ".teyla" / "policy-base.md")
    monkeypatch.setattr(policy, "CONFLICT_PATH", h / ".teyla" / "policy-merge-conflict.md")
    monkeypatch.setattr(policy, "CLAUDE_GLOBAL", h / ".claude" / "CLAUDE.md")
    monkeypatch.setattr(policy, "ACK_PATH", h / ".teyla" / "ack.json")
    monkeypatch.setattr(policy, "TARGETS", {
        "claude-code": h / ".claude" / "CLAUDE.md", "codex": h / ".codex" / "AGENTS.md",
        "grok": h / ".grok" / "AGENTS.md", "hermes": h / ".hermes" / "SOUL.md"})
    for name, rel in (("PLIST_PATH", "LaunchAgents/weekly.plist"), ("WRAPPER_PATH", ".teyla/weekly.sh"),
                      ("DAILY_PLIST_PATH", "LaunchAgents/daily.plist"), ("DAILY_WRAPPER_PATH", ".teyla/daily.sh"),
                      ("LOG_PATH", "Logs/teyla-weekly.log"), ("DAILY_LOG_PATH", "Logs/teyla-daily.log"),
                      ("STAMP_PATH", ".teyla/weekly.last"), ("DAILY_STAMP_PATH", ".teyla/daily.last")):
        monkeypatch.setattr(routine_install, name, h / rel)
    monkeypatch.setattr(plugin_install, "PLUGINS_DIR", h / ".claude" / "plugins")
    monkeypatch.setattr(health, "HOME", h)
    from teyla import harness
    from teyla.adapters import claude_code, codex, cursor, grok, hermes
    monkeypatch.setattr(harness, "HOME", h)
    for mod, sub in ((claude_code, ".claude/projects"), (codex, ".codex/sessions"), (grok, ".grok/sessions"),
                     (hermes, ".hermes/sessions"), (cursor, ".cursor/sessions")):
        if getattr(mod, "DEFAULT_ROOT", None):
            monkeypatch.setattr(mod, "DEFAULT_ROOT", str(h / sub))
    monkeypatch.setattr(routine_install, "loaded", lambda label: (False, None, None))
    monkeypatch.setattr(update, "check", lambda refresh=False, max_age_hours=24: dict(
        latest="9.9.9", newer=False, method="uv tool", checked="2026-11-20T10:00:00", reachable=True))
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)

    def no_network(*a, **k):
        raise AssertionError("network call in a test")
    monkeypatch.setattr(update.urllib.request, "urlopen", no_network)
    return h


def _by_name(cs):
    return {c["name"]: c for c in cs}


# --- INS-2: opt-in features that are off are INFO, never FIX ----------------------------------------

def test_a_fresh_install_has_no_fix_and_exits_zero(home, monkeypatch, capsys):
    (home / ".claude" / "projects").mkdir(parents=True)          # Claude Code is there and signed in, nothing of Teyla's yet
    (home / ".claude" / ".credentials.json").write_text("{}")
    for var in ("GROK_HOME", "CODEX_HOME"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    cs = doctor.checks(scan_repos=False)
    fixes = [c["name"] for c in cs if c["level"] == "FIX"]
    assert fixes == [], [(c['name'], c['detail'], c['fix']) for c in cs if c['level'] == 'FIX']
    by = _by_name(cs)
    for name in ("routine:daily", "routine:weekly"):
        assert by[name]["level"] == "INFO" and by[name]["detail"] == "off (pack daily — `teyla start` to turn on)"
    assert by["policy:file"]["level"] == "INFO" and "off (pack policy" in by["policy:file"]["detail"]
    assert by["plugin"]["level"] == "INFO" and "off (pack" in by["plugin"]["detail"]
    assert "fix(es)" not in doctor.summary_line(cs)
    assert doctor.cmd_doctor(type("A", (), {"refresh": False, "no_repos": True, "json": False, "quiet": False})()) == 0
    assert "fix(es)" not in capsys.readouterr().out


def test_a_feature_that_was_chosen_and_is_broken_stays_a_fix(home, monkeypatch):
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    config.set_value("features.chosen", "daily,policy")
    by = _by_name(doctor.checks(scan_repos=False))
    assert by["routine:daily"]["level"] == "FIX" and by["routine:weekly"]["level"] == "FIX"
    assert by["policy:file"]["level"] == "FIX"


def test_a_policy_file_that_exists_but_is_not_wired_is_still_a_fix(home, monkeypatch):
    (home / ".codex").mkdir()
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("# policy\n")
    by = _by_name(doctor.checks(scan_repos=False))
    assert by["policy:file"]["level"] == "OK"
    assert by["policy:codex"]["level"] == "FIX"


# --- INS-4: no ~/ops or ~/repos on a stranger's Mac -------------------------------------------------

def test_doctor_does_not_present_default_folders_as_facts(home):
    by = _by_name(doctor.checks(scan_repos=True))
    detail = by["config"]["detail"]
    assert "ops_root: not used until you set it" in detail and "runs_root" not in detail
    assert by["repos"]["level"] == "INFO" and "code_root" in by["repos"]["detail"] and "config.toml" in by["repos"]["detail"]


def test_an_owner_with_a_config_sees_the_same_config_line(home):
    config.CONFIG_PATH.write_text('code_root = "~/code"\nops_root = "~/things"\n')
    detail = _by_name(doctor.checks(scan_repos=False))["config"]["detail"]
    assert detail.startswith(f"{config.CONFIG_PATH}: code_root=") and "ops_root=" in detail and "runs_root=" in detail


# --- INS-5: a Codex app without its CLI -------------------------------------------------------------

def _codex_app(tmp_path, monkeypatch, executed):
    app = tmp_path / "Codex.app" / "codex"
    app.parent.mkdir(parents=True)
    app.write_text("#!/bin/sh\n")
    app.chmod(0o755)
    monkeypatch.setitem(health.APP_BINARY, "codex", str(app))
    monkeypatch.setattr(health, "version", lambda binary: executed.append(binary) or ("1.0.0", None))
    return app


def test_a_codex_binary_only_inside_an_app_is_one_info_line_and_never_run(home, tmp_path, monkeypatch):
    executed: list = []
    _codex_app(tmp_path, monkeypatch, executed)
    assert health.app_only("codex") and "codex" not in health.active_names()
    cs = doctor.checks(scan_repos=False)
    by = _by_name(cs)
    assert by["harness:codex"]["level"] == "INFO"
    assert by["harness:codex"]["detail"].startswith("Codex app found, CLI not set up — optional")
    assert "health:codex" not in by and "absent on this machine" not in by["harness:codex"]["detail"]
    assert executed == []


def test_a_codex_home_makes_the_app_binary_count_again(home, tmp_path, monkeypatch):
    _codex_app(tmp_path, monkeypatch, [])
    (home / ".codex").mkdir()
    assert not health.app_only("codex") and "codex" in health.active_names()


# --- INS-7: the machine's own tools by absolute path ------------------------------------------------

def test_load_calls_system_tools_by_absolute_path(monkeypatch):
    seen = []
    monkeypatch.setattr(load, "run_command", lambda cmd, timeout=60: seen.append(cmd) or (0, ""))
    monkeypatch.setattr(load.os, "access", lambda p, mode: p in ("/usr/sbin/sysctl", "/usr/bin/vm_stat", "/bin/ps"))
    for tool in ("sysctl", "vm_stat", "ps"):
        load.run_system([tool, "-n", "x"])
    assert [c[0] for c in seen] == ["/usr/sbin/sysctl", "/usr/bin/vm_stat", "/bin/ps"] and seen[0][1:] == ["-n", "x"]
    load.run_system(["other-tool"])
    assert seen[-1] == ["other-tool"]                              # a tool that is in no system folder stays as named
    assert load.snapshot.__defaults__[0] is load.run_system


def test_unknown_ram_is_said_in_words():
    snap = load.Snapshot(time="2026-11-20T10:00:00+01:00", ram_bytes=None, ncpu=None, load1=None, load5=None, load15=None,
                         swap_total_bytes=None, swap_used_bytes=None, pressure=None, compressor_bytes=None,
                         disk_free_bytes=None, swapout_bytes=None, pageout_bytes=None, procs=load.classify([]))
    text = load.render(snap, load.assess(snap, None))
    mem = next(line for line in text.splitlines() if line.startswith("memory:"))
    assert "?" not in mem and "RAM unknown (sysctl hw.memsize gave no answer)" in mem


# --- INS-8: spend with no sessions ------------------------------------------------------------------

def _empty_report():
    return dict(days=7, window=dict(first="2026-11-14", last="2026-11-20"), total_usd=0.0, session_usd=0.0, sub_usd=0.0,
                waste_usd=0.0, product_waste_usd=0.0, by_harness={}, by_model={}, findings=[], actions=None,
                subagent_mix={}, top_sessions=[], sessions=0,
                coverage=["W7: openai not read (no openai-admin-key in the Keychain)"], providers={})


def test_spend_without_sessions_is_one_line():
    assert spend.render(_empty_report()) == "No sessions yet in the window."


def test_spend_json_keeps_its_shape_with_zeros(home, monkeypatch, capsys):
    monkeypatch.setattr(spend, "report", lambda days, with_actions=True: _empty_report())
    assert cli.main(["spend", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["sessions"] == 0 and d["total_usd"] == 0 and d["by_model"] == {} and d["top_sessions"] == []


def test_the_admin_key_lines_are_labelled_optional_and_w7_is_named():
    rep = _empty_report()
    rep["sessions"] = 1
    rep["by_model"] = {"m": 1.0}
    rep["top_sessions"] = [dict(usd=1.0, harness="claude-code", project="p", sid="s")]
    text = spend.render(rep)
    assert "W7 product API billing: openai not read" in text and "optional" in text
    assert "(the same diff on two branches)" in text


# --- INS-1: `teyla start` with no sessions still shows the packs ------------------------------------

def test_start_with_no_sessions_names_the_packs_that_need_no_history(home, capsys, monkeypatch):
    from teyla import diagnose
    monkeypatch.setattr(diagnose, "collect", lambda days: diagnose.Inputs(days=days, sessions=[], rows=[], units=[]))
    monkeypatch.setattr(diagnose, "count_sessions", lambda days: 0)
    assert cli.main(["start"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(diagnose.EMPTY_MESSAGE)
    for pack in features.PACKS:
        assert (f"{pack.title} ({pack.id})" in out) == (not pack.needs_history)
    assert "`teyla features`" in out and "`teyla features on <pack>`" in out


def test_only_the_cost_pack_needs_history():
    assert [p.id for p in features.PACKS if p.needs_history] == ["cost"]

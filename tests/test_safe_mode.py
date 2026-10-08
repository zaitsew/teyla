"""Safe mode (`[safe] enabled = true`, TEYLA_SAFE=1): the work-laptop switch. Every path is
monkeypatched into tmp_path; every network entry point is stubbed to fail loudly, so a test
that passes proves the call was never made."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

import pytest

import teyla
from teyla import cli, config, doctor, models, net, platform, plugin_install, policy, products, routine_install, routines, update

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "session-start.sh"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.setattr(update, "CHECK_PATH", home / ".teyla" / "update-check.json")
    monkeypatch.setattr(doctor, "DOCTOR_JSON", home / ".teyla" / "doctor.json")
    monkeypatch.setattr(doctor, "DOCTOR_SUMMARY", home / ".teyla" / "doctor.summary")
    monkeypatch.setattr(policy, "HOME", home)
    monkeypatch.setattr(policy, "POLICY", home / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "BASE_PATH", home / ".teyla" / "policy-base.md")
    monkeypatch.setattr(policy, "CONFLICT_PATH", home / ".teyla" / "policy-merge-conflict.md")
    monkeypatch.setattr(policy, "CLAUDE_GLOBAL", home / ".claude" / "CLAUDE.md")
    monkeypatch.setattr(policy, "ACK_PATH", home / ".teyla" / "ack.json")
    monkeypatch.setattr(policy, "TARGETS", {
        "claude-code": home / ".claude" / "CLAUDE.md", "codex": home / ".codex" / "AGENTS.md",
        "grok": home / ".grok" / "AGENTS.md", "hermes": home / ".hermes" / "SOUL.md"})
    for name, rel in (("PLIST_PATH", "LaunchAgents/weekly.plist"), ("WRAPPER_PATH", ".teyla/weekly.sh"),
                      ("DAILY_PLIST_PATH", "LaunchAgents/daily.plist"), ("DAILY_WRAPPER_PATH", ".teyla/daily.sh"),
                      ("LOG_PATH", "Logs/teyla-weekly.log"), ("DAILY_LOG_PATH", "Logs/teyla-daily.log"),
                      ("STAMP_PATH", ".teyla/weekly.last"), ("DAILY_STAMP_PATH", ".teyla/daily.last")):
        monkeypatch.setattr(routine_install, name, home / rel)
    monkeypatch.setattr(plugin_install, "PLUGINS_DIR", home / ".claude" / "plugins")
    monkeypatch.setattr(models, "MODELS_DEV_CACHE", home / ".hermes" / "models_dev_cache.json")
    monkeypatch.setattr(models, "MODELS_DEV_FALLBACK", home / ".teyla" / "models_dev.json")

    def no_network(*a, **k):
        raise AssertionError("network call in a test")
    monkeypatch.setattr(update.urllib.request, "urlopen", no_network)
    return home


def safe_on():
    assert config.set_value("safe.enabled", "true").startswith("set")


# --- the switch --------------------------------------------------------------------------

def test_config_set_writes_typed_values_and_safe_mode_reads_them(_home, monkeypatch):
    assert not config.safe_mode()
    safe_on()
    assert "enabled = true" in config.CONFIG_PATH.read_text()  # a TOML boolean, not "true"
    assert config.load()["safe"]["enabled"] is True and config.safe_mode()
    config.set_value("products.repos", "teyla, ~/work/x")
    assert config.load()["products"]["repos"] == ["teyla", "~/work/x"]
    assert 'repos = ["teyla", "~/work/x"]' in config.CONFIG_PATH.read_text()
    config.set_value("safe.enabled", "false")
    assert not config.safe_mode()
    monkeypatch.setenv("TEYLA_SAFE", "1")
    assert config.safe_mode()


def test_env_cannot_switch_off_what_config_switched_on(monkeypatch):
    safe_on()
    monkeypatch.setenv("TEYLA_SAFE", "0")
    assert config.safe_mode()


def test_config_write_force_keeps_safe_and_products(_home):
    safe_on()
    config.set_value("products.repos", "teyla")
    config.write(code_root="~/work", force=True)
    cfg = config.load()
    assert cfg["safe"]["enabled"] is True and cfg["products"]["repos"] == ["teyla"] and cfg["code_root"] == "~/work"


def test_gate_refuses_with_one_line_naming_the_setting_unless_allowed(capsys):
    assert net.gate("x")
    safe_on()
    assert not net.gate("fetching x")
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1 and "safe.enabled" in err and "--allow-network" in err
    net.allow_for_this_command()
    assert net.gate("fetching x")


# --- update: no check, no install, unless --allow-network --------------------------------

def test_update_check_is_offline_in_safe_mode_and_serves_the_last_record(_home):
    safe_on()
    rec = update.check(refresh=True)
    assert rec["latest"] is None and rec["safe"] and "safe mode" in rec["note"]
    assert not update.CHECK_PATH.exists(), "an offline record is never written back"
    update.CHECK_PATH.write_text(json.dumps({"repo": "zaitsew/teyla", "latest": "v99.0.0", "checked": "2026-09-01T00:00:00+00:00"}))
    rec = update.check(refresh=True)
    assert rec["latest"] == "v99.0.0" and rec["newer"] and rec["from_cache"]


def test_teyla_update_refuses_in_safe_mode_and_runs_with_allow_network(_home, monkeypatch, capsys):
    safe_on()
    assert cli.main(["update", "--check"]) == 1
    assert "--allow-network" in capsys.readouterr().err
    calls = []

    class _Resp:
        def read(self): return json.dumps({"tag_name": "v0.0.1"}).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: (calls.append(req.full_url), _Resp())[1])
    assert cli.main(["update", "--check", "--allow-network"]) == 0
    assert calls and "up to date" in capsys.readouterr().out


def test_install_source_keeps_the_work_extra(monkeypatch):
    monkeypatch.setattr(update, "truststore_available", lambda: True)
    assert update.install_source("zaitsew/teyla", "v1.0.0") == "teyla[work] @ git+https://github.com/zaitsew/teyla@v1.0.0"
    monkeypatch.setattr(update, "truststore_available", lambda: False)
    assert update.install_source("zaitsew/teyla", "v1.0.0") == "git+https://github.com/zaitsew/teyla@v1.0.0"


def test_pyproject_has_the_work_extra():
    import tomllib
    py = ROOT / "pyproject.toml"
    extras = tomllib.loads(py.read_text())["project"]["optional-dependencies"]
    assert any(d.startswith("truststore") for d in extras["work"])


# --- the routines: daily never self-updates, weekly files under ops_root -------------------

def test_daily_wrapper_has_no_update_in_safe_mode_and_goes_stale_when_it_flips(_home, monkeypatch):
    monkeypatch.setattr(routine_install, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(routine_install, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    routine_install.install()
    daily = routine_install.DAILY_WRAPPER_PATH
    assert '"$TEYLA" update --quiet' in daily.read_text()
    assert not routine_install.is_stale()
    safe_on()
    assert routine_install.is_stale(), "switching safe mode on must make doctor ask for a rewrite"
    routine_install.install()
    text = daily.read_text()
    assert "update --quiet" not in text and "teyla doctor --quiet" in text and "storage clean --auto" in text
    assert not routine_install.is_stale()


def test_weekly_wrapper_files_reports_under_config_ops_root(_home, monkeypatch, tmp_path):
    monkeypatch.setattr(routine_install, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(routine_install, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    config.set_value("ops_root", str(tmp_path / "work-ops"))
    routine_install.install()
    assert f'OUT_DIR="{tmp_path / "work-ops" / "runs"}/' in routine_install.WRAPPER_PATH.read_text()
    (tmp_path / "work-ops" / pathlib.Path(*config._LEGACY_RUNS)).mkdir(parents=True)
    assert config.runs_root() == tmp_path / "work-ops" / pathlib.Path(*config._LEGACY_RUNS)
    assert routine_install.is_stale()


# --- the session-start hook ------------------------------------------------------------

def _run_hook(home: pathlib.Path, extra_env: dict | None = None) -> list[str]:
    bin_dir = home / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "teyla"
    fake.write_text('#!/bin/sh\necho "$*" >> "$HOME/calls"\n')
    fake.chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", **(extra_env or {})}
    r = subprocess.run(["sh", str(HOOK)], cwd=home, env=env, capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    calls = home / "calls"
    deadline = time.time() + 5
    while time.time() < deadline:  # the hook backgrounds its work
        if calls.exists() and "catch-up" in calls.read_text():
            break
        time.sleep(0.05)
    return calls.read_text().splitlines() if calls.exists() else []


def test_hook_checks_for_updates_outside_safe_mode(_home):
    calls = _run_hook(_home)
    assert calls[0] == "update --check --quiet" and any(c.startswith("doctor") for c in calls)


def test_hook_never_calls_update_in_safe_mode(_home):
    safe_on()
    calls = _run_hook(_home)
    assert calls and not any(c.startswith("update") for c in calls)
    assert calls[0] == "doctor --quiet" and "routine catch-up --quiet" in calls


def test_hook_honours_teyla_safe_env(_home):
    calls = _run_hook(_home, {"TEYLA_SAFE": "1"})
    assert calls and not any(c.startswith("update") for c in calls)


# --- products: check.sh runs only where the allowlist says ---------------------------------

def _repo(root: pathlib.Path, name: str) -> pathlib.Path:
    r = root / name
    (r / ".git").mkdir(parents=True)
    (r / "check.sh").write_text(f'case "$1" in usage) touch "{r}/ran"; echo users=1 ;; esac\n')
    return r


def test_products_uses_code_root_and_the_allowlist(_home, tmp_path):
    root = tmp_path / "work"
    a, b = _repo(root, "a"), _repo(root, "b")
    config.set_value("code_root", str(root))
    out = products.table()
    assert (a / "ran").exists() and (b / "ran").exists(), "no allowlist, not safe: today's behaviour"
    (a / "ran").unlink(); (b / "ran").unlink()
    config.set_value("products.repos", "a")
    out = products.table()
    assert (a / "ran").exists() and not (b / "ran").exists()
    assert not any(line.startswith("b ") for line in out.splitlines()), "the list replaces the walk"
    (a / "ran").unlink()
    products.table([str(b)])
    assert (b / "ran").exists(), "outside safe mode an explicit path still runs"


def test_products_in_safe_mode_runs_nothing_off_the_list(_home, tmp_path):
    root = tmp_path / "work"
    a, b = _repo(root, "a"), _repo(root, "b")
    config.set_value("code_root", str(root))
    safe_on()
    out = products.table()
    assert not (a / "ran").exists() and not (b / "ran").exists()
    assert out.count("not allowed") >= 2
    products.table([str(b)])
    assert not (b / "ran").exists(), "naming a repo does not put it on the list"
    config.set_value("products.repos", str(b))
    products.table([str(b)])
    assert (b / "ran").exists()


# --- routines --------------------------------------------------------------------------

def test_routines_issues_refused_in_safe_mode(_home, monkeypatch, capsys):
    safe_on()
    monkeypatch.setattr(routines, "open_issues", lambda r: (_ for _ in ()).throw(AssertionError("gh called")))
    assert cli.main(["routines", "--issues"]) == 1
    assert "--issues" in capsys.readouterr().err


def test_github_actions_routine_does_not_call_gh_in_safe_mode(monkeypatch):
    safe_on()
    monkeypatch.setattr(routines.shutil, "which", lambda n: "/usr/bin/gh")
    monkeypatch.setattr(routines.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gh ran")))
    assert routines.loaded_state({"kind": "github-actions", "label": "ci.yml"}) == "unknown"


def test_find_manifests_walks_config_code_root(tmp_path):
    root = tmp_path / "work"
    r = root / "p"
    (r / ".git").mkdir(parents=True)
    (r / "teyla.toml").write_text('[product]\nname = "p"\n')
    config.set_value("code_root", str(root))
    assert routines.find_manifests() == [r / "teyla.toml"]


# --- plugin: commands instead of registry edits; rmtree only inside the cache ---------------

def _marketplace(tmp_path: pathlib.Path, version: str = "1.0.0") -> pathlib.Path:
    m = tmp_path / "mkt"
    (m / ".claude-plugin").mkdir(parents=True)
    (m / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "mk", "plugins": [{"name": "pl", "source": "./pl"}]}))
    (m / "pl" / ".claude-plugin").mkdir(parents=True)
    (m / "pl" / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "pl", "version": version}))
    return m


def test_plugin_install_in_safe_mode_prints_claude_commands_and_writes_nothing(_home, tmp_path):
    safe_on()
    lines = plugin_install.install(str(_marketplace(tmp_path)))
    text = "\n".join(lines)
    assert "plugin marketplace add" in text and "plugin install pl@mk" in text
    assert not plugin_install.PLUGINS_DIR.exists()
    lines = plugin_install.install("zaitsew/teyla")  # no clone: nothing to reach
    assert any("plugin install teyla@teyla" in l for l in lines)
    assert any("plugin uninstall teyla" in l for l in plugin_install.uninstall("teyla"))


def test_plugin_refresh_in_safe_mode_prints_update_commands(_home):
    pd = plugin_install.PLUGINS_DIR
    pd.mkdir(parents=True)
    reg = {"version": 2, "plugins": {"teyla@teyla": [{"installPath": str(pd / "cache" / "teyla" / "teyla" / "0.0.1"), "version": "0.0.1"}]}}
    (pd / "installed_plugins.json").write_text(json.dumps(reg))
    safe_on()
    text = "\n".join(plugin_install.refresh())
    assert "plugin marketplace update teyla" in text and "plugin update teyla@teyla" in text
    assert json.loads((pd / "installed_plugins.json").read_text()) == reg


def test_uninstall_never_removes_an_install_path_outside_the_cache(_home, tmp_path):
    victim = tmp_path / "precious"
    victim.mkdir()
    (victim / "keep.txt").write_text("x")
    pd = plugin_install.PLUGINS_DIR
    pd.mkdir(parents=True)
    (pd / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {"x@y": [{"installPath": str(victim)}]}}))
    lines = plugin_install.uninstall("x")
    assert (victim / "keep.txt").exists() and any(l.startswith("kept") for l in lines)


def test_refresh_never_removes_an_old_install_path_outside_the_cache(_home, tmp_path):
    victim = tmp_path / "precious"
    victim.mkdir()
    pd = plugin_install.PLUGINS_DIR
    pd.mkdir(parents=True)
    (pd / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"teyla@teyla": [{"installPath": str(victim), "version": "0.0.1"}]}}))
    plugin_install.refresh()
    assert victim.exists()


def test_install_refuses_a_version_that_escapes_the_cache(_home, tmp_path):
    with pytest.raises(plugin_install.InstallError, match="outside"):
        plugin_install.install(str(_marketplace(tmp_path, version="../../../../escape")))


# --- models ----------------------------------------------------------------------------

def test_credentials_never_query_the_keychain_in_safe_mode(monkeypatch):
    safe_on()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr(models.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("security ran")))
    assert models.credentials()["anthropic"] is False
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "present")
    assert models.credentials()["anthropic"] is True


def test_models_refresh_does_not_fetch_in_safe_mode(_home, monkeypatch):
    safe_on()
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetched")))
    data, source = models.load_models_dev_catalogue(refresh=True)
    assert data == {} and source is None


# --- platform --------------------------------------------------------------------------

def test_platform_probes_are_skipped_in_safe_mode(monkeypatch):
    safe_on()
    cfg = {"server": {"provider": "digitalocean", "host": "10.0.0.1"}, "domain": {"name": "example.com"}}
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("probe ran"))  # noqa: E731
    monkeypatch.setattr(platform, "_ssh_ok", boom)
    monkeypatch.setattr(platform, "_resolves", boom)
    rows = platform.checks(cfg)
    assert next(r for r in rows if r["resource"] == "server")["state"] == platform.OK


# --- policy init --work ---------------------------------------------------------------

def test_policy_init_work_writes_the_work_template_and_turns_safe_mode_on(_home, capsys):
    assert cli.main(["policy", "init", "--work", "--owner", "Ann"]) == 0
    text = policy.POLICY.read_text()
    assert policy.is_work(text) and "Owner: Ann." in text
    assert "`grok -p`" not in text and "Second opinions across providers" not in text
    assert "| xAI |" not in text and "| OpenAI |" not in text
    assert policy.BASE_PATH.read_text() == text
    assert config.safe_mode()
    assert policy.refresh() == ["template unchanged since last refresh"], "work policy merges against the work template"


def test_policy_init_work_over_a_home_policy_needs_force_and_backs_up(_home):
    assert policy.init(owner="Ann").startswith("wrote")
    msg = policy.init(owner="Ann", work=True)
    assert msg.startswith("exists") and "--work --force" in msg
    assert policy.init(owner="Ann", work=True, force=True).startswith("wrote")
    assert policy.is_work()
    assert list(policy.POLICY.parent.glob("POLICY.md.bak-*"))


def test_hermes_block_follows_the_variant(_home):
    policy.init(owner="Ann", work=True)
    soul = policy.TARGETS["hermes"]
    soul.parent.mkdir(parents=True)
    soul.write_text("# Soul\n")
    policy.sync()
    assert "cross-provider" not in soul.read_text() and "same-provider" in soul.read_text()


# --- doctor ---------------------------------------------------------------------------

def test_doctor_shows_safe_line_and_stays_offline(_home, monkeypatch):
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    update.CHECK_PATH.write_text(json.dumps({"repo": "zaitsew/teyla", "latest": "v0.0.1", "checked": now}))
    lines = doctor.checks(scan_repos=False)  # served from that record: no network
    assert next(c for c in lines if c["name"] == "safe")["detail"] == "off"
    update.CHECK_PATH.unlink()
    safe_on()
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9000")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(update, "truststore_available", lambda: False)
    cs = doctor.checks(refresh_update=True, scan_repos=False)
    by = {c["name"]: c for c in cs}
    assert by["safe"]["detail"] == "on (network off, no auto-update, no repo commands)"
    assert by["version"]["level"] == "INFO" and "safe mode" in by["version"]["detail"]
    assert by["network"]["level"] == "INFO" and "teyla[work]" in by["network"]["fix"]
    assert any(line.split()[:3] == ["INFO", "safe", "on"] for line in doctor.render(cs).splitlines())


# --- caught in review: fail closed, and no stale managed policy copies ------------------------

def test_invalid_boolean_is_rejected_and_nothing_is_written(_home, capsys):
    msg = config.set_value("safe.enabled", "treu")
    assert msg.startswith("invalid safe.enabled") and not config.CONFIG_PATH.exists()
    assert cli.main(["config", "set", "safe.enabled=treu"]) == 1
    assert not config.CONFIG_PATH.exists()
    assert config.set_value("storage.idle_days", "three").startswith("invalid")


def test_unparseable_safe_value_fails_closed_and_doctor_names_it(_home, monkeypatch):
    config.CONFIG_PATH.write_text('[safe]\nenabled = "treu"\n')
    assert config.safe_mode(), "a typo must not switch safe mode off"
    by = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    assert by["safe:setting"]["level"] == "FIX" and "safe.enabled=true" in by["safe:setting"]["fix"]
    assert by["safe"]["detail"].startswith("on")
    config.CONFIG_PATH.write_text('[safe]\nenabled = false\n')
    assert not config.safe_mode() and config.safe_setting_invalid() is None
    monkeypatch.setenv("TEYLA_SAFE", "treu")
    assert config.safe_mode()
    monkeypatch.setenv("TEYLA_SAFE", "0")
    assert not config.safe_mode()


def test_hook_fails_closed_on_an_unparseable_safe_value(_home):
    config.CONFIG_PATH.write_text('[safe]\nenabled = "treu"\n')
    calls = _run_hook(_home)
    assert calls and not any(c.startswith("update") for c in calls)


def test_policy_sync_replaces_a_home_hermes_section_after_switching_to_work(_home):
    soul = policy.TARGETS["hermes"]
    soul.parent.mkdir(parents=True)
    soul.write_text("# Soul\n\nBe kind.\n")
    policy.init(owner="Ann")
    policy.sync()
    soul.write_text(soul.read_text() + "\n## Mine\nkeep this\n")
    assert "cross-provider" in soul.read_text() and policy.status()["hermes"] is True
    policy.init(owner="Ann", work=True, force=True)
    assert policy.status()["hermes"] is False, "a home-variant section is not wired for a work policy"
    assert any("replaced the policy section" in l for l in policy.sync())
    text = soul.read_text()
    assert "cross-provider" not in text and "same-provider" in text
    assert text.count(policy.HERMES_MARK) == 1 and "Be kind." in text and "## Mine\nkeep this" in text
    assert policy.status()["hermes"] is True and policy.sync() == ["already in sync"]


def test_policy_sync_rewrites_the_cursor_skill_after_switching_to_work(_home, monkeypatch):
    skill = _home / ".cursor" / "skills" / "teyla-policy" / "SKILL.md"
    skill.parent.parent.mkdir(parents=True)
    monkeypatch.setitem(policy.TARGETS, "cursor", skill)
    policy.init(owner="Ann")
    policy.sync()
    assert "`grok -p`" in skill.read_text()
    policy.init(owner="Ann", work=True, force=True)
    assert policy.status()["cursor"] is False
    policy.sync()
    assert policy.is_work(skill.read_text()) and "`grok -p`" not in skill.read_text()


# --- caught in review, round two ---------------------------------------------------------

def test_policy_init_work_without_force_over_a_home_policy_exits_nonzero(_home, capsys):
    policy.init(owner="Ann")
    assert cli.main(["policy", "init", "--work", "--owner", "Ann"]) == 1
    out, err = capsys.readouterr()
    assert "FAILED — work policy" in err and "--force" in err
    assert "safe mode on" in out and config.safe_mode(), "safe mode still goes on: it only ever does less"
    assert not policy.is_work()


def test_policy_init_work_exits_nonzero_when_safe_mode_cannot_be_written(_home, monkeypatch, capsys):
    monkeypatch.setattr(config, "set_value", lambda *a, **k: "invalid safe.enabled: disk says no; nothing written")
    assert cli.main(["policy", "init", "--work", "--owner", "Ann"]) == 1
    out, err = capsys.readouterr()
    assert "FAILED — safe mode" in err and "safe mode on" not in out
    assert policy.is_work(), "the policy half still happened; only the failed step is reported"


def test_write_policy_on_a_work_policy_updates_only_listed_providers(_home, monkeypatch, capsys):
    policy.init(owner="Ann", work=True)
    monkeypatch.setattr(models, "credentials", lambda: {"anthropic": True, "openai": True, "xai": True, "google": False})
    monkeypatch.setattr(models, "_cli_ids_by_provider", lambda used, days: {"openai": ["gpt-x"], "xai": ["grok-x"]})
    models.write_policy()
    table = models.parse_ladder(policy.POLICY.read_text())
    assert set(table) == {"anthropic"}, "a model refresh must not widen the approved-provider list"
    assert cli.main(["models", "--write-policy", "--add-provider", "openai"]) == 0
    assert "approved-provider list" in capsys.readouterr().out
    assert set(models.parse_ladder(policy.POLICY.read_text())) == {"anthropic", "openai"}
    assert cli.main(["models", "--write-policy", "--add-provider", "mistral"]) == 2


def test_write_policy_on_a_home_policy_still_covers_every_provider(_home, monkeypatch):
    policy.init(owner="Ann")
    monkeypatch.setattr(models, "credentials", lambda: {"anthropic": True, "openai": True, "xai": True, "google": False})
    monkeypatch.setattr(models, "_cli_ids_by_provider", lambda used, days: {})
    models.write_policy()
    assert set(models.parse_ladder(policy.POLICY.read_text())) == {"anthropic", "openai", "xai"}


# --- caught in review, round three: an unreadable config, and the control plane --------------

BROKEN = 'code_root = "~/work"\n[env]\nSSL_CERT_FILE = "/unterminated\n[safe]\nenabled = false\n'


def test_a_config_that_does_not_parse_forces_safe_mode_on(_home):
    config.CONFIG_PATH.write_text(BROKEN)
    assert config.safe_mode() and not net.allowed()
    by = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    assert by["safe:setting"]["level"] == "FIX" and "does not parse" in by["safe:setting"]["detail"]
    assert by["safe"]["detail"].startswith("on")


def test_a_config_that_does_not_parse_is_never_rewritten(_home):
    config.CONFIG_PATH.write_text(BROKEN)
    assert config.set_value("safe.enabled", "true").startswith("invalid config")
    assert cli.main(["config", "set", "products.repos=a"]) == 1
    assert config.write(force=True).startswith("invalid config")
    assert config.CONFIG_PATH.read_text() == BROKEN, "[env] and the roots must survive a typo"


def test_a_config_behind_an_unreadable_directory_forces_safe_mode_on(_home, monkeypatch, tmp_path):
    # Path.exists() is False when stat is refused, so an exists() precheck read this as "no
    # config": safe mode off, network allowed (caught in review, round four, P1).
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "config.toml").write_text("[safe]\nenabled = true\n")
    monkeypatch.setattr(config, "CONFIG_PATH", locked / "config.toml")
    locked.chmod(0o000)
    try:
        if os.access(locked, os.R_OK | os.X_OK):
            pytest.skip("running as a user that ignores directory permissions")
        assert config.safe_mode() and not net.allowed()
        assert config.parse_error() is not None
    finally:
        locked.chmod(0o755)


def test_a_missing_config_is_still_safe_mode_off(_home):
    assert not config.CONFIG_PATH.exists()
    assert config.parse_error() is None and not config.safe_mode()


def _control_repo(tmp_path, monkeypatch):
    from tests.test_control import MANIFEST
    repos = tmp_path / "repos"
    repo = repos / "demo"
    repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(MANIFEST)
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "teyla-home"))
    monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    return repo


def test_teyla_run_needs_allow_network_and_the_allowlist_in_safe_mode(_home, tmp_path, monkeypatch):
    from teyla.control import engine
    repo = _control_repo(tmp_path, monkeypatch)
    safe_on()
    out = []
    assert engine.run("demo:digest", out=out.append) == 1
    assert "REFUSED" in out[-1] and "--allow-network" in out[-1]
    assert not (repo / "runs").exists(), "refused before anything was created"
    net.allow_for_this_command()
    out.clear()
    assert engine.run("demo:digest", out=out.append) == 1 and "products" in out[-1]
    config.set_value("products.repos", str(repo))
    out.clear()
    assert engine.run("demo:digest", out=out.append) == 0
    assert not any("REFUSED" in line for line in out), "with both, the draft runs as before (gate A stops at the inbox)"


def test_a_refused_approval_leaves_the_item_pending(_home, tmp_path, monkeypatch):
    # Refused inside the act step, the approval was recorded anyway and the retry with
    # --allow-network said "already approve" (caught in review, round four, P2).
    from teyla.control import engine, inbox, state as S
    repo = _control_repo(tmp_path, monkeypatch)
    safe_on()
    config.set_value("products.repos", str(repo))
    net.allow_for_this_command()
    assert engine.run("demo:digest", out=lambda *_: None) == 0
    [rid] = [k for k, v in S.fold_inbox().items() if not v.get("decision")]
    net.allow_for_this_command(False)
    args = type("A", (), {"id": rid, "note": None})()
    assert inbox.cmd_approve(args) == 1
    assert not S.inbox_item(rid).get("decision"), "refused, so still pending"
    assert not (repo / "acted.txt").exists()
    net.allow_for_this_command()
    assert inbox.cmd_approve(args) == 0
    assert S.inbox_item(rid)["decision"] == "approved" and (repo / "acted.txt").exists()


def test_agent_steps_need_an_approved_provider_in_safe_mode(_home, tmp_path, monkeypatch):
    from teyla.control import harness as H
    repo = _control_repo(tmp_path, monkeypatch)
    safe_on()
    net.allow_for_this_command()
    config.set_value("products.repos", str(repo))
    policy.init(owner="Ann")
    assert "not the work policy" in H.safe_refusal(repo, "claude")
    policy.init(owner="Ann", work=True, force=True)
    assert H.safe_refusal(repo, "claude") is None
    assert "openai is not in the ladder" in H.safe_refusal(repo, "codex")
    assert "xai" in H.safe_refusal(repo, "grok")
    monkeypatch.setattr(H, "_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("codex started")))
    step = type("S", (), {"harness": "codex"})()
    r = H.run_agent_step(step, cwd=repo, env={}, timeout_s=5, grants={}, caps={}, prompt="x")
    assert not r.ok and "ladder" in r.error


def test_triggers_are_not_installed_and_installed_ones_are_flagged_in_safe_mode(_home, tmp_path, monkeypatch):
    from teyla.control import triggers
    _control_repo(tmp_path, monkeypatch)
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    monkeypatch.setattr(triggers, "LAUNCH_AGENTS", agents)
    safe_on()
    ns = type("A", (), {"ref": "demo:digest", "no_load": True})()
    assert triggers.cmd_install(ns) == 1 and not list(agents.iterdir())
    (agents / "com.teyla.demo.digest.plist").write_text("<plist/>")
    by = [c for c in doctor.checks(scan_repos=False) if c["name"] == "control:trigger"]
    assert by and by[0]["level"] == "FIX" and "com.teyla.demo.digest" in by[0]["fix"]


# --- the plugin follows the pin: hooks must not be newer than the CLI -------------------------

def _known(home, source):
    pd = home / ".claude" / "plugins"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "known_marketplaces.json").write_text(json.dumps({"teyla": {"source": source}}))
    (pd / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"teyla@teyla": [{"installPath": str(pd / "cache"), "version": teyla.__version__}]}}))


def _plugin_checks(home, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    return {c["name"]: c for c in doctor.checks(scan_repos=False)}


def test_pinned_safe_mode_adds_the_marketplace_at_the_tag(_home):
    safe_on()
    assert plugin_install.pin_ref() is None  # safe, but no pin
    assert any("plugin marketplace add zaitsew/teyla" in l and "#" not in l for l in plugin_install.install("zaitsew/teyla"))
    config.set_value("update.pin", "0.15.0")
    assert plugin_install.pin_ref() == "v0.15.0"
    text = "\n".join(plugin_install.install("zaitsew/teyla"))
    assert "plugin marketplace add zaitsew/teyla#v0.15.0" in text and "plugin install teyla@teyla" in text
    config.set_value("update.pin", "v0.15.0")
    assert plugin_install.pin_ref() == "v0.15.0"  # a leading v is not doubled
    assert "zaitsew/teyla#v0.15.0" in "\n".join(plugin_install.install("zaitsew/teyla"))
    assert "#" not in "\n".join(plugin_install.install("someone/else"))  # the pin is Teyla's, not every repo's


def test_pin_does_nothing_outside_safe_mode_or_for_a_sha(_home):
    config.set_value("update.pin", "0.15.0")
    assert plugin_install.pin_ref() is None  # safe mode off: unchanged
    safe_on()
    config.set_value("update.pin", "b90e2a0f1c2d")
    assert plugin_install.pin_ref() is None and plugin_install.pin_is_sha()
    assert "#" not in "\n".join(plugin_install.install("zaitsew/teyla"))


def test_pinned_refresh_re_adds_the_marketplace_instead_of_pulling_main(_home):
    pd = plugin_install.PLUGINS_DIR
    pd.mkdir(parents=True)
    (pd / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"teyla@teyla": [{"installPath": str(pd / "cache"), "version": "0.0.1"}]}}))
    safe_on()
    config.set_value("update.pin", "0.15.0")
    text = "\n".join(plugin_install.refresh())
    assert "marketplace remove teyla" in text and "marketplace add zaitsew/teyla#v0.15.0" in text
    assert "marketplace update" not in text


def test_doctor_warns_when_the_plugin_does_not_follow_the_pin(_home, monkeypatch):
    safe_on()
    config.set_value("update.pin", "0.15.0")
    _known(_home, {"source": "github", "repo": "zaitsew/teyla"})
    c = _plugin_checks(_home, monkeypatch)["plugin:pin"]
    assert c["level"] == "WARN" and "main" in c["detail"] and "v0.15.0" in c["detail"]
    assert "marketplace remove teyla" in c["fix"] and "zaitsew/teyla#v0.15.0" in c["fix"]
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": "v0.14.0"})
    assert "v0.14.0" in _plugin_checks(_home, monkeypatch)["plugin:pin"]["detail"]


def test_doctor_is_quiet_when_the_plugin_follows_the_pin(_home, monkeypatch):
    safe_on()
    config.set_value("update.pin", "0.15.0")
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": "v0.15.0"})
    assert "plugin:pin" not in _plugin_checks(_home, monkeypatch)


def test_doctor_plugin_pin_needs_a_pin_and_a_readable_registry(_home, monkeypatch):
    safe_on()
    _known(_home, {"source": "github", "repo": "zaitsew/teyla"})
    assert "plugin:pin" not in _plugin_checks(_home, monkeypatch)  # safe mode, no pin
    config.set_value("update.pin", "0.15.0")
    (plugin_install.PLUGINS_DIR / "known_marketplaces.json").write_text("{not json")
    assert "plugin:pin" not in _plugin_checks(_home, monkeypatch)  # garbled: no line, no crash
    (plugin_install.PLUGINS_DIR / "known_marketplaces.json").write_text("[]")
    assert "plugin:pin" not in _plugin_checks(_home, monkeypatch)
    (plugin_install.PLUGINS_DIR / "known_marketplaces.json").unlink()
    assert "plugin:pin" not in _plugin_checks(_home, monkeypatch)  # missing


def test_doctor_says_a_sha_pin_cannot_pin_the_plugin(_home, monkeypatch):
    safe_on()
    config.set_value("update.pin", "b90e2a0f1c2d")
    _known(_home, {"source": "github", "repo": "zaitsew/teyla"})
    c = _plugin_checks(_home, monkeypatch)["plugin:pin"]
    assert c["level"] == "WARN" and "commit sha" in c["detail"]


def test_doctor_plugin_fix_names_the_pinned_tag(_home, monkeypatch):
    safe_on()
    config.set_value("update.pin", "0.15.0")
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": "v0.15.0"})
    pd = plugin_install.PLUGINS_DIR
    (pd / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"teyla@teyla": [{"installPath": str(pd / "cache"), "version": "0.0.1"}]}}))
    fix = _plugin_checks(_home, monkeypatch)["plugin"]["fix"]
    assert "marketplace remove teyla" in fix and "add zaitsew/teyla#v0.15.0" in fix and "marketplace update" not in fix
    (pd / "installed_plugins.json").unlink()
    fix = _plugin_checks(_home, monkeypatch)["plugin"]["fix"]
    assert "add zaitsew/teyla#v0.15.0" in fix


def test_pinned_install_over_an_unpinned_marketplace_removes_it_first(_home):
    # `marketplace add` refuses a registered name, which would keep the old ref (Codex review, P2)
    safe_on()
    config.set_value("update.pin", "0.15.0")
    _known(_home, {"source": "github", "repo": "zaitsew/teyla"})
    text = "\n".join(plugin_install.install("zaitsew/teyla"))
    assert text.index("marketplace remove teyla") < text.index("marketplace add zaitsew/teyla#v0.15.0")
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": "v0.15.0"})
    assert "marketplace remove" not in "\n".join(plugin_install.install("zaitsew/teyla"))


def test_pinned_refresh_re_pins_a_current_version_that_follows_main(_home):
    # the right version on the wrong ref is stale: the next marketplace update pulls main (Codex review, P2)
    safe_on()
    config.set_value("update.pin", "0.15.0")
    _known(_home, {"source": "github", "repo": "zaitsew/teyla"})
    text = "\n".join(plugin_install.refresh())
    assert "marketplace add zaitsew/teyla#v0.15.0" in text and "already" not in text
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": "v0.15.0"})
    assert "already" in "\n".join(plugin_install.refresh())


def test_policy_sync_quiet_is_local_only_in_safe_mode(_home, monkeypatch):
    """The daily routine runs `policy sync --quiet`, safe mode included: it reads and writes files
    and never opens a socket."""
    import socket
    safe_on()

    def no_socket(*a, **k):
        raise AssertionError("socket opened by policy sync")
    monkeypatch.setattr(socket.socket, "connect", no_socket)
    monkeypatch.setattr(socket, "create_connection", no_socket)
    (_home / ".codex").mkdir()
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("# P\n")
    policy.CLAUDE_GLOBAL.parent.mkdir(parents=True)
    policy.CLAUDE_GLOBAL.write_text("# Mine\n\n- a rule\n")
    assert cli.main(["policy", "sync", "--quiet"]) in (0, None)
    assert "- a rule" in (_home / ".codex" / "AGENTS.md").read_text()
    codex = _home / ".codex" / "AGENTS.md"
    codex.write_text(codex.read_text() + "- hand edit\n")
    assert cli.main(["policy", "sync", "--quiet"]) in (0, None)
    assert len(policy.pending_edits()) == 1

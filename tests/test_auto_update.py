"""`safe.auto_update`: in safe mode, `teyla update` (and only it) may look up and install the latest
published release. Everything else stays closed; a pin wins; the plugin is left to a banner line.
GitHub is a stub keyed by URL, installers are a stub `_run`, every path lives in tmp_path."""
from __future__ import annotations

import argparse
import json

import pytest

from teyla import __version__, config, digest, doctor, models, net, plugin_install, policy, routine_install, update
from teyla import cli

SHA = "d" * 40
NEXT = "99.0.0"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.setattr(update, "CHECK_PATH", home / ".teyla" / "update-check.json")
    monkeypatch.setattr(update, "INSTALLED_PATH", home / ".teyla" / "installed.json")
    monkeypatch.setattr(doctor, "DOCTOR_JSON", home / ".teyla" / "doctor.json")
    monkeypatch.setattr(doctor, "DOCTOR_SUMMARY", home / ".teyla" / "doctor.summary")
    monkeypatch.setattr(policy, "HOME", home)
    monkeypatch.setattr(policy, "POLICY", home / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "BASE_PATH", home / ".teyla" / "policy-base.md")
    monkeypatch.setattr(policy, "CONFLICT_PATH", home / ".teyla" / "policy-merge-conflict.md")
    monkeypatch.setattr(policy, "PROPOSED_PATH", home / ".teyla" / "policy-proposed.md")
    monkeypatch.setattr(policy, "CLAUDE_GLOBAL", home / ".claude" / "CLAUDE.md")
    monkeypatch.setattr(policy, "ACK_PATH", home / ".teyla" / "ack.json")
    for name, rel in (("PLIST_PATH", "LaunchAgents/weekly.plist"), ("WRAPPER_PATH", ".teyla/weekly.sh"),
                      ("DAILY_PLIST_PATH", "LaunchAgents/daily.plist"), ("DAILY_WRAPPER_PATH", ".teyla/daily.sh"),
                      ("LOG_PATH", "Logs/weekly.log"), ("DAILY_LOG_PATH", "Logs/daily.log"),
                      ("STAMP_PATH", ".teyla/weekly.last"), ("DAILY_STAMP_PATH", ".teyla/daily.last")):
        monkeypatch.setattr(routine_install, name, home / rel)
    monkeypatch.setattr(plugin_install, "PLUGINS_DIR", home / ".claude" / "plugins")
    monkeypatch.setattr(models, "MODELS_DEV_CACHE", home / ".hermes" / "models_dev_cache.json")
    monkeypatch.setattr(models, "MODELS_DEV_FALLBACK", home / ".teyla" / "models_dev.json")
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    monkeypatch.setenv("TEYLA_IN_ROUTINE", "daily")
    monkeypatch.setattr(net, "_allow_once", False)

    def no_network(*a, **k):
        raise AssertionError("network call in a test")
    monkeypatch.setattr(update.urllib.request, "urlopen", no_network)
    return home


class _Resp:
    def __init__(self, payload): self.payload = payload
    def read(self): return json.dumps(self.payload).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def github(monkeypatch, tag=f"v{NEXT}") -> list[str]:
    urls = []

    def urlopen(req, timeout=10, context=None):
        url = req.full_url
        urls.append(url)
        if url.endswith("/releases/latest"):
            return _Resp({"tag_name": tag})
        if "/releases/tags/" in url:
            return _Resp({"tag_name": url.rsplit("/", 1)[1]})
        if "/commits/" in url:
            return _Resp({"sha": SHA})
        raise AssertionError(f"unexpected GitHub call {url}")
    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    return urls


def installer(monkeypatch, reports: str = NEXT):
    ran, asked = [], []

    def run(cmd, cwd=None):
        ran.append(cmd)
        if cmd[-1].count("@") and "git+" in cmd[-1]:
            asked.append(cmd[-1].rsplit("@", 1)[1])
        return (0, reports) if cmd[-1] == "--version" else (0, "ok")
    monkeypatch.setattr(update, "_run", run)
    monkeypatch.setattr(update, "installed_commit", lambda method: asked[-1] if asked else None)
    monkeypatch.setattr(update.shutil, "which", lambda name: f"/opt/bin/{name}")
    monkeypatch.setattr(update, "install_method", lambda: ("uv-tool", None))
    monkeypatch.setattr(update, "post_update", lambda quiet=False: ["(post-update stubbed)"])
    return ran


def args(**kw):
    base = dict(check=False, force=False, wire=False, quiet=True)
    base.update(kw)
    return argparse.Namespace(**base)


def safe_on(auto: bool = False):
    assert config.set_value("safe.enabled", "true").startswith("set")
    if auto:
        assert config.set_value("safe.auto_update", "true").startswith("set")


# --- the network ---------------------------------------------------------------------------

def test_safe_mode_without_the_flag_makes_no_network_call_from_the_daily_path(capsys):
    safe_on()
    assert not config.safe_auto_update()
    assert update.cmd_update(args()) == 1            # refused, and urlopen would have raised
    assert "--allow-network" in capsys.readouterr().err
    assert cli.main(["update", "--quiet"]) == 1


def test_with_the_flag_only_the_update_command_reaches_github_for_the_release(_home, monkeypatch):
    safe_on(auto=True)
    assert config.safe_auto_update()
    urls = github(monkeypatch)
    ran = installer(monkeypatch)
    assert update.cmd_update(args()) == 0
    assert urls and all(u.startswith("https://api.github.com/repos/zaitsew/teyla/") for u in urls)
    assert any(u.endswith("/releases/latest") for u in urls) and any("/commits/" in u for u in urls)
    install = next(c for c in ran if c[1:3] == ["tool", "install"])
    assert install[-1].endswith(f"git+https://github.com/zaitsew/teyla@{SHA}")
    assert json.loads(update.INSTALLED_PATH.read_text())["version"] == NEXT
    # the scope ended with the command
    assert not net.allowed()
    n = len(urls)
    for what in ("models.dev", "gh api"):
        assert not net.gate(what, quiet=True)
    update.check(refresh=True)                       # doctor's and the hook's lookup stays offline
    doctor.checks(refresh_update=True, scan_repos=False)
    assert len(urls) == n


def test_a_build_that_reports_another_version_is_still_rolled_back_under_auto_update(_home, monkeypatch, capsys):
    safe_on(auto=True)
    github(monkeypatch)
    installer(monkeypatch, reports="98.0.0")
    assert update.cmd_update(args(quiet=False)) == 1
    assert "reports version 98.0.0" in capsys.readouterr().out


def test_the_flag_does_nothing_outside_safe_mode_and_needs_an_explicit_true(_home):
    config.set_value("safe.auto_update", "true")
    assert not config.safe_auto_update()             # safe mode is off
    safe_on()
    assert config.safe_auto_update()
    config.set_value("safe.auto_update", "false")
    assert not config.safe_auto_update()
    config.CONFIG_PATH.write_text('[safe]\nenabled = true\nauto_update = "treu"\n')
    assert config.safe_mode() and not config.safe_auto_update()


def test_the_scope_is_not_leaked_by_an_exception(monkeypatch):
    safe_on(auto=True)
    with pytest.raises(RuntimeError):
        with net.update_scope():
            assert net.allowed()
            raise RuntimeError("boom")
    assert not net.allowed()


def test_the_daily_wrapper_carries_the_update_line_only_with_the_flag(_home):
    safe_on()
    assert routine_install._update_line() == routine_install.SAFE_UPDATE_LINE
    config.set_value("safe.auto_update", "true")
    assert routine_install._update_line() == routine_install.UPDATE_LINE
    stale = _home / ".teyla" / "daily.sh"
    stale.write_text("# .last\nspend --alert storage clean policy sync\n" + routine_install.SAFE_UPDATE_LINE)
    assert routine_install._wrapper_stale(stale, "teyla")  # switched on after the wrapper was written


# --- the pin wins ----------------------------------------------------------------------------

def test_a_pin_wins_over_auto_update_and_doctor_says_how_to_clear_it(_home, monkeypatch):
    safe_on(auto=True)
    config.set_value("update.pin", "0.12.0")
    github(monkeypatch, tag="v0.12.0")
    installer(monkeypatch, reports="0.12.0")
    update.cmd_update(args())
    assert update.update_settings()[1] == "0.12.0"
    assert update.CHECK_PATH.exists() and json.loads(update.CHECK_PATH.read_text())["latest"] == "v0.12.0"
    by = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    assert by["safe:auto-update-pin"]["level"] == "WARN"
    assert "teyla config set update.pin=" in by["safe:auto-update-pin"]["fix"]
    assert "0.12.0" in by["safe:auto-update-pin"]["detail"]
    assert by["safe:auto-update"]["level"] == "INFO"


def test_clearing_the_pin_with_an_empty_value_removes_the_key(_home, capsys):
    config.set_value("update.pin", "0.12.0")
    config.set_value("update.python", "3.12")
    assert cli.main(["config", "set", "update.pin="]) == 0
    text = config.CONFIG_PATH.read_text()
    assert "pin" not in text and 'python = "3.12"' in text
    assert update.update_settings()[1] is None
    assert cli.main(["config", "set", "update.pin="]) == 1   # nothing to clear: said so, exit 1


# --- doctor -------------------------------------------------------------------------------------

def test_doctor_shows_auto_update_without_a_pin_warning(_home):
    safe_on(auto=True)
    by = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    assert by["safe:auto-update"] == {**by["safe:auto-update"], "level": "INFO", "detail": "safe mode: auto-update on (releases only)"}
    assert "safe:auto-update-pin" not in by
    assert "auto-update on (releases only)" in by["version"]["detail"]
    assert by["safe"]["detail"] == config.SAFE_SUMMARY_AUTO


def test_doctor_does_not_mention_auto_update_when_it_is_off(_home):
    safe_on()
    by = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    assert "safe:auto-update" not in by and by["safe"]["detail"] == config.SAFE_SUMMARY
    assert "update checks off in safe mode" in by["version"]["detail"]


# --- config ----------------------------------------------------------------------------------------

def test_config_write_force_keeps_the_flag(_home):
    safe_on(auto=True)
    config.write(code_root="~/work", force=True)
    cfg = config.load()
    assert cfg["safe"]["auto_update"] is True and cfg["safe"]["enabled"] is True and cfg["code_root"] == "~/work"
    assert "auto_update = true" in config.CONFIG_PATH.read_text()
    assert config.load(_home / "nothing")["safe"]["auto_update"] is False   # the default


# --- the plugin: a banner line, never a hand-edit ------------------------------------------------------

def _known(home, source):
    pd = home / ".claude" / "plugins"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "known_marketplaces.json").write_text(json.dumps({"teyla": {"source": source}}))
    (pd / "installed_plugins.json").write_text(json.dumps(
        {"version": 2, "plugins": {"teyla@teyla": [{"installPath": str(pd / "cache"), "version": __version__}]}}))


def test_the_plugin_follows_the_cli_release_tag_not_main(_home):
    safe_on()
    assert plugin_install.follow_ref() is None                    # no auto-update, no pin
    config.set_value("safe.auto_update", "true")
    assert plugin_install.follow_ref() == f"v{__version__}"
    config.set_value("update.pin", "0.15.0")
    assert plugin_install.follow_ref() == "v0.15.0"               # the pin wins here too
    config.set_value("update.pin", None)
    text = "\n".join(plugin_install.install("zaitsew/teyla"))
    assert f"plugin marketplace add zaitsew/teyla#v{__version__}" in text


def test_auto_update_leaves_a_banner_line_with_the_exact_plugin_commands(_home):
    safe_on(auto=True)
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": "v0.0.1"})
    key, text = plugin_install.lag_banner_item()
    assert "v0.0.1" in text and f"v{__version__}" in text
    assert "/plugin marketplace remove teyla" in text and f"/plugin marketplace add zaitsew/teyla#v{__version__}" in text
    assert "/plugin install teyla@teyla" in text
    path = digest.write_banner_items([])
    assert path and text in path.read_text()
    # the generic doctor rows about the same thing are replaced, not doubled
    rows = [{"level": "WARN", "name": "plugin:pin", "detail": "x"}, {"level": "FIX", "name": "plugin", "detail": "y"},
            {"level": "WARN", "name": "other", "detail": "z"}]
    body = digest.write_banner_items(rows).read_text()
    assert "plugin:pin" not in body and "other WARN" in body and text in body


def test_the_banner_line_is_quiet_when_the_plugin_is_current_or_there_is_nothing_to_compare(_home):
    safe_on(auto=True)
    assert plugin_install.lag_banner_item() is None                           # no marketplace registered
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": f"v{__version__}"})
    assert plugin_install.lag_banner_item() is None                           # already at the tag
    _known(_home, {"source": "directory", "path": "/somewhere"})
    assert plugin_install.lag_banner_item() is None                           # a local source is not a tag
    _known(_home, {"source": "github", "repo": "zaitsew/teyla"})
    assert "main" in plugin_install.lag_banner_item()[1]                      # unpinned: follows main
    config.set_value("safe.auto_update", "false")
    assert plugin_install.lag_banner_item() is None                           # opt-in only


def test_doctor_names_the_plugin_lag_with_the_repin_commands(_home):
    safe_on(auto=True)
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": "v0.0.1"})
    by = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    c = by["plugin:pin"]
    assert c["level"] == "WARN" and "auto-update" in c["detail"] and "v0.0.1" in c["detail"]
    assert f"zaitsew/teyla#v{__version__}" in c["fix"] and "marketplace remove teyla" in c["fix"]


def test_post_update_never_edits_the_plugin_registry_in_safe_mode(_home):
    safe_on(auto=True)
    _known(_home, {"source": "github", "repo": "zaitsew/teyla", "ref": "v0.0.1"})
    pd = plugin_install.PLUGINS_DIR
    before = {p.name: p.read_text() for p in pd.glob("*.json")}
    lines = plugin_install.refresh(force=True)
    assert {p.name: p.read_text() for p in pd.glob("*.json")} == before
    text = "\n".join(lines)
    assert "marketplace remove teyla" in text and f"marketplace add zaitsew/teyla#v{__version__}" in text

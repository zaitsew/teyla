"""teyla.update / teyla.doctor / teyla.config / policy.refresh — the self-maintenance layer.
Every path is monkeypatched into tmp_path; GitHub is never reached (urlopen is stubbed)."""
from __future__ import annotations

import json
import pathlib

import pytest

import teyla
from teyla import config, doctor, policy, update, routine_install, plugin_install


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
    monkeypatch.setattr(routine_install, "PLIST_PATH", home / "LaunchAgents" / "weekly.plist")
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", home / ".teyla" / "weekly.sh")
    monkeypatch.setattr(routine_install, "DAILY_PLIST_PATH", home / "LaunchAgents" / "daily.plist")
    monkeypatch.setattr(routine_install, "DAILY_WRAPPER_PATH", home / ".teyla" / "daily.sh")
    monkeypatch.setattr(plugin_install, "PLUGINS_DIR", home / ".claude" / "plugins")
    monkeypatch.delenv("TEYLA_REPO", raising=False)
    return home


# --- the three version strings agree ---------------------------------------------

def test_versions_agree():
    root = pathlib.Path(teyla.__file__).resolve().parents[2]
    py = root / "pyproject.toml"
    if not py.exists():
        pytest.skip("not a checkout")
    import tomllib
    assert tomllib.loads(py.read_text())["project"]["version"] == teyla.__version__
    assert json.loads((teyla.plugin_dir() / ".claude-plugin" / "plugin.json").read_text())["version"] == teyla.__version__


# --- config --------------------------------------------------------------------------

def test_config_defaults_and_overrides(_home, monkeypatch):
    assert config.load()["update"]["repo"] == "zaitsew/teyla"
    assert config.write(code_root="~/work", ops_root="~/o") .startswith("wrote")
    assert config.write() .startswith("exists")
    c = config.load()
    assert c["code_root"] == "~/work" and c["update"]["channel"] == "release"
    monkeypatch.setenv("TEYLA_REPO", "someone/fork")
    assert config.load()["update"]["repo"] == "someone/fork"


# --- update ------------------------------------------------------------------------------

def test_version_compare():
    assert update.is_newer("v0.7.1", "0.7.0")
    assert not update.is_newer("v0.7.0", "0.7.0")
    assert not update.is_newer(None, "0.7.0")
    assert update.is_newer("v1.0", "0.9.9")


class _Resp:
    def __init__(self, payload): self.payload = payload
    def read(self): return json.dumps(self.payload).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_check_hits_releases_then_caches(_home, monkeypatch):
    calls = []
    def fake_urlopen(req, timeout=10):
        calls.append(req.full_url)
        return _Resp({"tag_name": "v9.9.9"})
    monkeypatch.setattr(update.urllib.request, "urlopen", fake_urlopen)
    rec = update.check(refresh=True)
    assert rec["latest"] == "v9.9.9" and rec["newer"] is True and rec["note"] == "releases/latest"
    assert update.CHECK_PATH.exists()
    rec2 = update.check(refresh=False)
    assert rec2["latest"] == "v9.9.9" and len(calls) == 1, "second call served from the cache"


def test_check_falls_back_to_tags_and_survives_offline(_home, monkeypatch):
    def fake_urlopen(req, timeout=10):
        if req.full_url.endswith("/releases/latest"):
            raise update.urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return _Resp([{"name": "v0.1.0"}, {"name": "v0.10.0"}, {"name": "v0.9.0"}])
    monkeypatch.setattr(update.urllib.request, "urlopen", fake_urlopen)
    rec = update.check(refresh=True)
    assert rec["latest"] == "v0.10.0" and rec["note"] == "tags"

    def offline(req, timeout=10):
        raise update.urllib.error.URLError("no network")
    monkeypatch.setattr(update.urllib.request, "urlopen", offline)
    rec = update.check(refresh=True)
    assert rec["latest"] is None and rec["newer"] is False


def test_install_method_detects_checkout():
    method, root = update.install_method()
    assert method in ("checkout", "uv-tool", "pipx", "pip")
    if method == "checkout":
        assert (root / "pyproject.toml").exists()


def test_upgrade_refuses_dirty_checkout(tmp_path):
    import subprocess
    repo = tmp_path / "co"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "dirty.txt").write_text("x")
    lines = update.upgrade("v1.0.0", "o/r", "checkout", repo)
    assert lines and lines[0].startswith("SKIP")


# --- policy refresh: three-way merge ------------------------------------------------------

def _tpl(monkeypatch, tmp_path, text):
    t = tmp_path / "POLICY.tpl.md"
    t.write_text(text)
    monkeypatch.setattr(policy, "TEMPLATE", t)
    return t


def test_refresh_records_base_first_then_merges_cleanly(_home, monkeypatch, tmp_path):
    _tpl(monkeypatch, tmp_path, "# Policy\nOwner: {{owner}}.\n\n## 1\nold line\n\n## 2\nkeep\n")
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("# Policy\nOwner: Ada.\n\n## 1\nold line\n\n## 2\nkeep\nmy own addition\n")
    out = policy.refresh()
    assert "recorded template base" in out[0] and "1 line(s)" in out[0]
    assert policy.BASE_PATH.read_text() == "# Policy\nOwner: Ada.\n\n## 1\nold line\n\n## 2\nkeep\n"
    assert policy.refresh() == ["template unchanged since last refresh"]
    # upstream changes section 1; the owner's addition in section 2 survives
    _tpl(monkeypatch, tmp_path, "# Policy\nOwner: {{owner}}.\n\n## 1\nnew line\n\n## 2\nkeep\n")
    out = policy.refresh(dry=True)
    assert out[0].startswith("would merge")
    assert "my own addition" in policy.POLICY.read_text() and "new line" not in policy.POLICY.read_text()
    out = policy.refresh()
    assert out[0].startswith("merged")
    text = policy.POLICY.read_text()
    assert "new line" in text and "my own addition" in text and "Owner: Ada." in text
    assert policy.BASE_PATH.read_text() == "# Policy\nOwner: Ada.\n\n## 1\nnew line\n\n## 2\nkeep\n"
    assert list(policy.POLICY.parent.glob("POLICY.md.bak-*")), "old file backed up"


def test_refresh_conflict_leaves_policy_untouched(_home, monkeypatch, tmp_path):
    _tpl(monkeypatch, tmp_path, "# P\nOwner: {{owner}}.\n\n## 1\nline A\n")
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("# P\nOwner: Ada.\n\n## 1\nline A\n")
    policy.refresh()
    policy.POLICY.write_text("# P\nOwner: Ada.\n\n## 1\nline MINE\n")
    _tpl(monkeypatch, tmp_path, "# P\nOwner: {{owner}}.\n\n## 1\nline THEIRS\n")
    out = policy.refresh()
    assert "conflict" in out[0]
    assert policy.POLICY.read_text() == "# P\nOwner: Ada.\n\n## 1\nline MINE\n"
    assert "<<<<<<<" in policy.CONFLICT_PATH.read_text()
    assert policy.resolved().startswith("base moved")
    assert not policy.CONFLICT_PATH.exists()
    assert policy.BASE_PATH.read_text() == "# P\nOwner: Ada.\n\n## 1\nline THEIRS\n"


def test_refresh_applies_when_no_local_edits(_home, monkeypatch, tmp_path):
    _tpl(monkeypatch, tmp_path, "Owner: {{owner}}.\nv1\n")
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("Owner: Ada.\nv1\n")
    policy.refresh()
    _tpl(monkeypatch, tmp_path, "Owner: {{owner}}.\nv2\n")
    assert policy.refresh()[0].startswith("applied")
    assert policy.POLICY.read_text() == "Owner: Ada.\nv2\n"


def test_repos_status(tmp_path):
    root = tmp_path / "repos"
    for name, files in (("a", ["CLAUDE.md"]), ("b", ["AGENTS.md", "CLAUDE.md"]), ("c", []), ("d", ["AGENTS.md"])):
        d = root / name; (d / ".git").mkdir(parents=True)
        for f in files:
            (d / f).write_text(f"# {name} {f}\n")
    (root / "notrepo").mkdir()
    st = dict((n, s) for s, n in policy.repos_status(root))
    assert st == {"a": "missing", "b": "differ", "c": "none", "d": "missing"}


# --- routine staleness ------------------------------------------------------------------

def test_wrapper_stale_detects_moved_binary(_home):
    w = routine_install.WRAPPER_PATH
    w.parent.mkdir(parents=True, exist_ok=True)
    w.write_text('#!/bin/bash\nTEYLA="/old/place/teyla"\n')
    assert routine_install._wrapper_stale(w, "/new/place/teyla")
    assert not routine_install._wrapper_stale(w, "/old/place/teyla")
    assert routine_install._wrapper_stale(routine_install.DAILY_WRAPPER_PATH, "/x")
    assert routine_install.is_stale()


# --- plugin refresh --------------------------------------------------------------------------

def test_plugin_refresh_brings_cache_to_package_version(_home):
    pd = plugin_install.PLUGINS_DIR
    (pd / "cache" / "teyla" / "teyla" / "0.1.0").mkdir(parents=True)
    (pd / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": {"teyla@teyla": [
        {"scope": "user", "installPath": str(pd / "cache" / "teyla" / "teyla" / "0.1.0"), "version": "0.1.0",
         "installedAt": "2026-01-01T00:00:00.000Z", "lastUpdated": "2026-01-01T00:00:00.000Z"}]}}))
    assert plugin_install.installed_version() == "0.1.0"
    lines = plugin_install.refresh()
    assert any("0.1.0 -> " + teyla.__version__ in l for l in lines)
    assert plugin_install.installed_version() == teyla.__version__
    new = pd / "cache" / "teyla" / "teyla" / teyla.__version__
    assert (new / "hooks" / "session-start.sh").exists()
    assert not (pd / "cache" / "teyla" / "teyla" / "0.1.0").exists()
    assert plugin_install.refresh() == [f"teyla@teyla: already {teyla.__version__}"]


def test_plugin_refresh_when_not_installed(_home):
    assert "not installed" in plugin_install.refresh()[0]


# --- doctor --------------------------------------------------------------------------

def test_doctor_names_fixes_and_writes_summary(_home, monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10: _Resp({"tag_name": "v99.0.0"}))
    cs = doctor.checks(refresh_update=True, scan_repos=False)
    by = {c["name"]: c for c in cs}
    assert by["version"]["level"] == "FIX" and by["version"]["fix"] == "teyla update"
    assert by["policy:file"]["level"] == "FIX"
    doctor.write_state(cs)
    s = doctor.DOCTOR_SUMMARY.read_text()
    assert s.startswith("teyla:") and "fix(es)" in s and "update available" in s
    assert json.loads(doctor.DOCTOR_JSON.read_text())["checks"]
    assert "→ teyla update" in doctor.render(cs, quiet=True)


def test_doctor_all_clear_summary_is_empty():
    cs = [doctor._check("OK", "a", "fine"), doctor._check("INFO", "b", "absent")]
    assert doctor.summary_line(cs) == ""
    assert doctor.render(cs).endswith("all clear")

"""teyla.update / teyla.doctor / teyla.config / policy.refresh — the self-maintenance layer.
Every path is monkeypatched into tmp_path; GitHub is never reached (urlopen is stubbed)."""
from __future__ import annotations

import json
import os
import pathlib

import pytest

import teyla
from teyla import config, doctor, policy, update, routine_install, plugin_install, remind


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
    monkeypatch.setattr(routine_install, "LOG_PATH", home / "Logs" / "teyla-weekly.log")
    monkeypatch.setattr(routine_install, "DAILY_LOG_PATH", home / "Logs" / "teyla-daily.log")
    monkeypatch.setattr(routine_install, "STAMP_PATH", home / ".teyla" / "weekly.last")
    monkeypatch.setattr(routine_install, "DAILY_STAMP_PATH", home / ".teyla" / "daily.last")
    monkeypatch.setattr(plugin_install, "PLUGINS_DIR", home / ".claude" / "plugins")
    monkeypatch.setattr(remind, "REMINDERS_PATH", home / ".teyla" / "reminders.toml")
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
    def fake_urlopen(req, timeout=10, context=None):
        calls.append(req.full_url)
        return _Resp({"tag_name": "v9.9.9", "sha": "a" * 40})
    monkeypatch.setattr(update.urllib.request, "urlopen", fake_urlopen)
    rec = update.check(refresh=True)
    assert rec["latest"] == "v9.9.9" and rec["newer"] is True and rec["note"] == "releases/latest"
    assert rec["sha"] == "a" * 40 and calls[-1].endswith("/commits/v9.9.9"), "the tag is resolved to its commit"
    assert json.loads(update.CHECK_PATH.read_text())["sha"] == "a" * 40
    rec2 = update.check(refresh=False)
    assert rec2["latest"] == "v9.9.9" and len(calls) == 2, "second call served from the cache"


def test_check_never_falls_back_to_tags_and_survives_offline(_home, monkeypatch):
    urls = []
    def fake_urlopen(req, timeout=10, context=None):
        urls.append(req.full_url)
        if req.full_url.endswith("/releases/latest"):
            raise update.urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return _Resp([{"name": "v0.1.0"}, {"name": "v0.10.0"}, {"name": "v0.9.0"}])
    monkeypatch.setattr(update.urllib.request, "urlopen", fake_urlopen)
    rec = update.check(refresh=True)
    assert rec["latest"] is None and rec["reachable"] is True and not rec["newer"]
    assert not any(u.endswith("/tags") for u in urls), "a bare v* tag is never an update source"

    def offline(req, timeout=10, context=None):
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


@pytest.mark.parametrize("code", [255, 128, -9])
def test_refresh_treats_a_merge_file_error_as_an_error_not_conflicts(_home, monkeypatch, tmp_path, code):
    # caught in review, P2: exit 255 (and anything above 127) was reported as "255 conflict(s)" and
    # its empty stdout written to the conflict file.
    import subprocess
    _tpl(monkeypatch, tmp_path, "# P\nOwner: {{owner}}.\n\n## 1\nline A\n")
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("# P\nOwner: Ada.\n\n## 1\nline A\n")
    policy.refresh()
    mine = "# P\nOwner: Ada.\n\n## 1\nline MINE\n"
    policy.POLICY.write_text(mine)
    _tpl(monkeypatch, tmp_path, "# P\nOwner: {{owner}}.\n\n## 1\nline THEIRS\n")
    real = subprocess.run

    def fake(argv, *a, **k):
        if "merge-file" in list(argv):
            return subprocess.CompletedProcess(argv, code, "", "fatal: could not read file")
        return real(argv, *a, **k)
    monkeypatch.setattr(subprocess, "run", fake)
    out = policy.refresh()
    assert len(out) == 1 and "failed" in out[0] and "conflict(s)" not in out[0]
    assert policy.POLICY.read_text() == mine
    assert not policy.CONFLICT_PATH.exists()


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
    # a CLAUDE.md that imports AGENTS.md is one source of truth, not a difference — with or
    # without Claude-only lines after the import
    for name, claude in (("e", "@AGENTS.md\n"), ("f", "<!-- teyla:cloud-import:start -->\n@AGENTS.md\n<!-- teyla:cloud-import:end -->\n\nClaude-only note.\n")):
        d = root / name; (d / ".git").mkdir(parents=True)
        (d / "AGENTS.md").write_text("# guide\n")
        (d / "CLAUDE.md").write_text(claude)
    st = dict((n, s) for s, n in policy.repos_status(root))
    assert st == {"a": "missing", "b": "differ", "c": "none", "d": "missing", "e": "ok", "f": "ok"}
    assert "already linked" in policy.sync_repo(str(root / "e"))


def test_an_agents_import_inside_a_code_fence_is_not_a_link(tmp_path):
    # caught in review, P2: Claude Code does not expand imports in code, so a fenced example of the
    # line neither links the files nor makes divergent text "consistent".
    root = tmp_path / "repos"
    cases = {
        "fenced": "# notes\n\n```md\n@AGENTS.md\n```\n\nDivergent text.\n",
        "tilde": "~~~\n@AGENTS.md\n~~~\nDivergent.\n",
        "unclosed": "Intro\n````\n```\n@AGENTS.md\n```\nstill inside\n",
        "after_fence": "```\nexample\n```\n@AGENTS.md\nreal import\n",
        "live": "@AGENTS.md\n\n```\n@AGENTS.md\n```\n",
    }
    for name, claude in cases.items():
        d = root / name; (d / ".git").mkdir(parents=True)
        (d / "AGENTS.md").write_text("# guide\n")
        (d / "CLAUDE.md").write_text(claude)
    st = dict((n, s) for s, n in policy.repos_status(root))
    assert st == {"fenced": "differ", "tilde": "differ", "unclosed": "differ", "after_fence": "ok", "live": "ok"}
    assert "already linked" not in policy.sync_repo(str(root / "fenced"), dry=True)
    assert "already linked" in policy.sync_repo(str(root / "live"), dry=True)


# --- routine staleness ------------------------------------------------------------------

def test_wrapper_stale_detects_moved_binary(_home):
    w = routine_install.WRAPPER_PATH
    w.parent.mkdir(parents=True, exist_ok=True)
    w.write_text('#!/bin/bash\ndate > ~/.teyla/weekly.last\nTEYLA="/old/place/teyla"\n'
                 f'OUT_DIR="{routine_install._runs_root()}/$(date +%F)"\n"$TEYLA" digest --write\n')
    assert routine_install._wrapper_stale(w, "/new/place/teyla")
    assert not routine_install._wrapper_stale(w, "/old/place/teyla")
    assert routine_install._wrapper_stale(routine_install.DAILY_WRAPPER_PATH, "/x")
    assert routine_install.is_stale()
    # a wrapper from before catch-up never stamps, so it is stale whatever binary it names
    w.write_text('#!/bin/bash\nTEYLA="/old/place/teyla"\n')
    assert routine_install._wrapper_stale(w, "/old/place/teyla")


# --- catch-up: the run launchd skipped because the Mac was off ------------------------------

def _local(y, m, d, hh, mm):
    import datetime
    return datetime.datetime(y, m, d, hh, mm).astimezone()


def test_last_due_follows_the_plist_schedule():
    # Saturday 10:00 → the weekly was due Friday 20:45, the daily today 07:00
    now = _local(2026, 9, 19, 10, 0)
    assert routine_install.last_due(routine_install.LABEL, now) == _local(2026, 9, 18, 20, 45)
    assert routine_install.last_due(routine_install.DAILY_LABEL, now) == _local(2026, 9, 19, 7, 0)
    # Friday 06:59: the weekly was last due a week ago, the daily yesterday; at 07:00 sharp the daily is due now
    now = _local(2026, 9, 18, 6, 59)
    assert routine_install.last_due(routine_install.LABEL, now) == _local(2026, 9, 11, 20, 45)
    assert routine_install.last_due(routine_install.DAILY_LABEL, now) == _local(2026, 9, 17, 7, 0)
    assert routine_install.last_due(routine_install.DAILY_LABEL, _local(2026, 9, 18, 7, 0)) == _local(2026, 9, 18, 7, 0)
    # the weekly is due at 20:45 sharp, not a minute before
    assert routine_install.last_due(routine_install.LABEL, _local(2026, 9, 18, 20, 44)) == _local(2026, 9, 11, 20, 45)
    assert routine_install.last_due(routine_install.LABEL, _local(2026, 9, 18, 20, 45)) == _local(2026, 9, 18, 20, 45)


def _install_fake_job(home, label, marker, *, installed_at):
    import os
    plist, wrapper, log, stamp = routine_install._job(label)
    for f in (plist, wrapper):
        f.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text(f'#!/bin/bash\ndate -u +%FT%TZ > "{stamp}"\necho ran-{label} >> "{marker}"\nTEYLA="/x/teyla"\n')
    plist.write_text("<plist/>")
    os.utime(plist, (installed_at.timestamp(), installed_at.timestamp()))
    return plist, wrapper, log, stamp


def test_missed_and_catch_up_run_the_skipped_weekly(_home, monkeypatch):
    monkeypatch.delenv("TEYLA_IN_ROUTINE", raising=False)
    marker = _home / "ran.txt"
    # installed Friday 2026-09-11 16:55, due Friday 20:45, the Mac was off and booted Saturday 10:00: never started
    _install_fake_job(_home, routine_install.LABEL, marker, installed_at=_local(2026, 9, 11, 16, 55))
    now = _local(2026, 9, 12, 10, 0)
    assert routine_install.missed(routine_install.LABEL, now) == _local(2026, 9, 11, 20, 45)
    # the daily has no plist here → not a missed run, just not installed
    assert routine_install.missed(routine_install.DAILY_LABEL, now) is None
    lines = routine_install.catch_up(dry=True, now=now)
    assert any("MISSED 2026-09-11 20:45" in l and "would run" in l for l in lines)
    assert not marker.exists()
    lines = routine_install.catch_up(now=now)
    assert marker.read_text().strip() == f"ran-{routine_install.LABEL}"
    assert any("ran weekly.sh now, exit 0" in l for l in lines)
    assert "catch-up: the run due 2026-09-11 20:45" in routine_install.LOG_PATH.read_text()
    # the wrapper stamped itself, so a second catch-up (or doctor) sees it as on schedule
    assert routine_install.last_started(routine_install.LABEL) is not None
    assert routine_install.missed(routine_install.LABEL) is None
    assert routine_install.catch_up(dry=True, now=_local(2026, 9, 13, 9, 0))[1].endswith("on schedule")


def test_not_missed_before_the_first_due_minute_or_when_stamped(_home):
    marker = _home / "ran.txt"
    plist, wrapper, log, stamp = _install_fake_job(_home, routine_install.DAILY_LABEL, marker,
                                                   installed_at=_local(2026, 9, 14, 8, 0))
    # installed after today's 07:00: the schedule has not had a chance yet
    assert routine_install.missed(routine_install.DAILY_LABEL, _local(2026, 9, 14, 12, 0)) is None
    # next morning at 09:00 with no stamp: missed
    assert routine_install.missed(routine_install.DAILY_LABEL, _local(2026, 9, 15, 9, 0)) == _local(2026, 9, 15, 7, 0)
    import datetime
    stamp.write_text(_local(2026, 9, 15, 7, 0).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    assert routine_install.missed(routine_install.DAILY_LABEL, _local(2026, 9, 15, 9, 0)) is None


def test_a_reinstall_does_not_hide_a_missed_run(_home, monkeypatch):
    """`teyla update` rewrites the plists on every release; the weekly missed on its day and
    reinstalled that night must still read as missed — seen 2026-09-15 (when the weekly was a Monday one)."""
    import datetime, os
    marker = _home / "ran.txt"
    plist, wrapper, log, stamp = _install_fake_job(_home, routine_install.LABEL, marker, installed_at=_local(2026, 9, 11, 16, 55))
    assert routine_install.missed(routine_install.LABEL, _local(2026, 9, 12, 10, 0)) == _local(2026, 9, 11, 20, 45)
    # a reinstall Saturday 00:11, the night after: plist mtime is now after the due minute
    later = _local(2026, 9, 12, 0, 11)
    os.utime(plist, (later.timestamp(), later.timestamp()))
    # without evidence of an earlier install this reads as "not yet due"...
    assert routine_install.missed(routine_install.LABEL, later) is None
    # ...but install() records the first install once, and then the miss is visible
    stamp.with_suffix(".installed").write_text(
        _local(2026, 9, 11, 16, 55).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    assert routine_install.missed(routine_install.LABEL, later) == _local(2026, 9, 11, 20, 45)
    # an earlier start is evidence too, even without the marker
    stamp.with_suffix(".installed").unlink()
    (stamp).write_text(_local(2026, 9, 4, 20, 45).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")
    assert routine_install.missed(routine_install.LABEL, later) == _local(2026, 9, 11, 20, 45)


def test_install_marks_first_install_once(_home, monkeypatch):
    monkeypatch.setenv("HOME", str(_home))
    monkeypatch.setattr(routine_install, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(routine_install, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    routine_install.install()
    m = routine_install.STAMP_PATH.with_suffix(".installed")
    first = m.read_text()
    assert first.endswith("Z\n") and routine_install.DAILY_STAMP_PATH.with_suffix(".installed").exists()
    routine_install.install()
    assert m.read_text() == first


def test_upgrade_retries_after_a_corrupt_uv_cache_and_restores_the_old_version(monkeypatch):
    calls = []
    def fake_run(cmd, cwd=None):
        calls.append(cmd)
        if cmd[1:3] == ["cache", "clean"]:
            return 0, ""
        if cmd[-1] == "--version":
            return 0, "0.10.0"
        if SHA in cmd[-1] and len([c for c in calls if SHA in c[-1]]) == 1:
            return 1, "Git operation failed\nerror: unable to read sha1 file of src/teyla/platform.py"
        return 0, "Installed 1 executable: teyla"
    SHA = "b" * 40
    monkeypatch.setattr(update, "_run", fake_run)
    monkeypatch.setattr(update, "installed_commit", lambda method: SHA)  # the commit check passes
    monkeypatch.setattr(update.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else "/x/teyla")
    lines = update.upgrade("v0.10.0", "zaitsew/teyla", "uv-tool", python="3.13", sha=SHA)
    assert any("uv cache clean teyla" in l for l in lines) and lines[-1].startswith("installed v0.10.0")
    assert [c[1:3] for c in calls] == [["tool", "install"], ["cache", "clean"], ["tool", "install"], ["--version"]]
    # a build that fails for another reason, with the binary gone, puts the installed version back
    calls.clear()
    def fail_run(cmd, cwd=None):
        calls.append(cmd)
        return (0, "ok") if f"@v{update.__version__}" in cmd[-1] else (1, "error: some other build failure")
    monkeypatch.setattr(update, "_run", fail_run)
    monkeypatch.setattr(update.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(update.pathlib.Path, "home", classmethod(lambda cls: pathlib.Path("/nonexistent")))
    lines = update.upgrade("v9.9.9", "zaitsew/teyla", "uv-tool", python="3.13", sha=SHA)
    assert lines[0].startswith("FAIL: upgrade via uv-tool") and lines[-1].startswith("restored ")
    assert calls[-1][-1].endswith(f"@v{update.__version__}")


def test_catch_up_never_reruns_the_wrapper_that_called_it(_home, monkeypatch):
    marker = _home / "ran.txt"
    _install_fake_job(_home, routine_install.DAILY_LABEL, marker, installed_at=_local(2026, 9, 1, 7, 0))
    monkeypatch.setenv("TEYLA_IN_ROUTINE", routine_install.DAILY_LABEL)
    lines = routine_install.catch_up(now=_local(2026, 9, 15, 7, 1))
    assert any("this is it" in l for l in lines) and not marker.exists()


def test_doctor_warns_on_a_missed_run(_home, monkeypatch):
    if not hasattr(routine_install, "loaded"):
        return
    monkeypatch.setattr(routine_install.sys, "platform", "darwin")
    monkeypatch.setattr(routine_install, "loaded", lambda label: (True, None, "0"))
    monkeypatch.setattr(routine_install, "_wrapper_stale", lambda *a, **k: False)
    monkeypatch.setattr(routine_install, "missed",
                        lambda label, now=None: _local(2026, 9, 11, 20, 45) if label == routine_install.LABEL else None)
    monkeypatch.setattr(routine_install, "last_started", lambda label: _local(2026, 9, 14, 7, 0))
    for f in (routine_install.PLIST_PATH, routine_install.DAILY_PLIST_PATH):
        f.parent.mkdir(parents=True, exist_ok=True); f.write_text("<plist/>")
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: _Resp({"tag_name": "v0.0.0"}))
    by = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    assert by["routine:weekly"]["level"] == "WARN" and by["routine:weekly"]["fix"] == "teyla routine catch-up"
    assert "2026-09-11 20:45" in by["routine:weekly"]["detail"]
    assert by["routine:daily"]["level"] == "OK" and "last started 2026-09-14 07:00" in by["routine:daily"]["detail"]


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
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: _Resp({"tag_name": "v99.0.0"}))
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


# --- remind: dated to-dos that surface through doctor ---------------------------------

def test_remind_add_list_done_roundtrip(_home):
    assert remind.load() == []
    assert remind.add("renew the thing", "2027-03-11", how="run the script").startswith("added")
    assert remind.add("second thing", "2026-10-01").startswith("added")
    rs = remind.load()
    assert [r["what"] for r in rs] == ["renew the thing", "second thing"]
    assert rs[0]["how"] == "run the script" and rs[1]["how"] == ""
    text = remind.render_list(rs, today=__import__("datetime").date(2026, 9, 12))
    assert "renew the thing" in text and "run the script" in text and "2027-03-11" in text
    assert remind.done(1).startswith("done: renew the thing")
    assert [r["what"] for r in remind.load()] == ["second thing"]
    assert remind.done(5).startswith("no reminder")


def test_remind_add_rejects_a_bad_date(_home):
    assert remind.add("x", "not-a-date").startswith("bad date")
    assert remind.load() == []


def test_remind_due_checks_warn_within_30_days_and_fix_once_overdue(_home):
    import datetime as dt
    today = dt.date(2026, 9, 12)
    remind.add("expires soon", "2026-09-20", how="do the thing")            # +8d: WARN
    remind.add("expires later", "2027-03-11", how="do the other thing")     # +180d: nothing
    remind.add("already late", "2026-09-01", how="fix it now")              # -11d: FIX
    remind.add("no fix recorded", "2026-09-05")                              # -7d: FIX, no how
    rows = remind.due_checks(today=today)
    by = {r["name"]: r for r in rows}
    assert by["expires soon"]["level"] == "WARN" and by["expires soon"]["fix"] == "do the thing"
    assert by["expires later"]["level"] == "OK", "tracked, but not due within 30 days — OK, not silence"
    assert by["already late"]["level"] == "FIX" and "11d overdue" in by["already late"]["detail"]
    assert by["already late"]["fix"] == "fix it now"
    assert by["no fix recorded"]["level"] == "FIX" and by["no fix recorded"]["fix"] == "no fix recorded — teyla remind list"


def test_doctor_surfaces_reminders_as_warn_and_fix(_home, monkeypatch):
    import datetime as dt
    today = dt.date.today()
    soon = (today + dt.timedelta(days=10)).isoformat()
    past = (today - dt.timedelta(days=3)).isoformat()
    remind.add("apple secret expiring", soon, how="run the rotation script")
    remind.add("overdue thing", past, how="handle it")
    cs = doctor.checks(refresh_update=True, scan_repos=False)
    by = {c["name"]: c for c in cs}
    assert by["remind:apple secret expiring"]["level"] == "WARN"
    assert by["remind:apple secret expiring"]["fix"] == "run the rotation script"
    assert by["remind:overdue thing"]["level"] == "FIX"
    assert by["remind:overdue thing"]["fix"] == "handle it"
    assert any(c["level"] == "FIX" for c in cs)


# --- config [env]: the environment launchd and the session hook cannot inherit -------------

def test_config_env_applied_with_setdefault_semantics(_home, monkeypatch):
    config.CONFIG_PATH.write_text('code_root = "~/work"\n\n[env]\nSSL_CERT_FILE = "~/.teyla/ca.pem"\nHTTPS_PROXY = "http://127.0.0.1:9000"\n')
    monkeypatch.setenv("HOME", str(_home))  # `~` in [env] values expands against this home
    # setenv first so teardown restores the original (absent) state; apply_env below sets it for real
    monkeypatch.setenv("SSL_CERT_FILE", "placeholder"); del os.environ["SSL_CERT_FILE"]
    monkeypatch.setenv("HTTPS_PROXY", "http://shell-wins:1")
    applied = config.apply_env()
    assert applied == ["SSL_CERT_FILE"]
    assert os.environ["SSL_CERT_FILE"] == str(_home / ".teyla" / "ca.pem")
    assert os.environ["HTTPS_PROXY"] == "http://shell-wins:1", "a variable the shell set is never overridden"


def test_config_set_edits_one_key_and_keeps_the_rest(_home):
    assert config.write(code_root="~/work").startswith("wrote")
    assert config.set_value("env.SSL_CERT_FILE", "~/.teyla/ca.pem").startswith("set env.SSL_CERT_FILE")
    assert config.set_value("update.python", "3.12").startswith("set")
    assert config.set_value("code_root", "~/src").startswith("set")
    c = config.load()
    assert c["env"] == {"SSL_CERT_FILE": "~/.teyla/ca.pem"}
    assert c["update"] == {"repo": "zaitsew/teyla", "channel": "release", "python": "3.12"}
    assert c["code_root"] == "~/src" and c["ops_root"] == "~/ops"
    assert config.set_value("env.SSL_CERT_FILE", None).startswith("unset")
    assert config.load()["env"] == {}
    assert config.set_value("nope.x", "1").startswith("unknown table")
    assert config.set_value("bogus", "1").startswith("unknown key")
    # --force rewrites roots but keeps the [env] block: it is the local adaptation
    config.set_value("env.HTTPS_PROXY", "http://127.0.0.1:9000")
    assert config.write(code_root="~/again", force=True).startswith("wrote")
    c = config.load()
    assert c["code_root"] == "~/again" and c["env"] == {"HTTPS_PROXY": "http://127.0.0.1:9000"}
    assert "config.toml" in config.show()


def test_routine_install_writes_config_env_into_both_plists_and_wrappers(_home, monkeypatch):
    config.CONFIG_PATH.write_text('[env]\nSSL_CERT_FILE = "~/.teyla/ca.pem"\n')
    monkeypatch.setenv("HOME", str(_home))
    monkeypatch.setattr(routine_install, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(routine_install, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    lines = routine_install.install()
    assert any(l.startswith("wrote") for l in lines)
    ca = str(_home / ".teyla" / "ca.pem")
    for plist in (routine_install.PLIST_PATH, routine_install.DAILY_PLIST_PATH):
        text = plist.read_text()
        assert "<key>PATH</key>" in text and "/opt/tools/bin" in text, f"{plist.name} must carry PATH"
        assert f"<key>SSL_CERT_FILE</key>\n        <string>{ca}</string>" in text
    for wrapper in (routine_install.WRAPPER_PATH, routine_install.DAILY_WRAPPER_PATH):
        text = wrapper.read_text()
        assert "export PATH=" in text and f"export SSL_CERT_FILE={ca}" in text
    assert not routine_install.is_stale()
    # a new [env] entry makes the wrappers stale, so `update`'s `routine install --if-stale` rewrites them
    config.set_value("env.HTTPS_PROXY", "http://127.0.0.1:9000")
    assert routine_install.is_stale()
    routine_install.install(if_stale=True)
    assert "HTTPS_PROXY" in routine_install.PLIST_PATH.read_text()
    assert not routine_install.is_stale()
    # removing an entry is a change too: the block is compared whole, not as a substring
    config.set_value("env.HTTPS_PROXY", None)
    assert routine_install.is_stale()
    routine_install.install(if_stale=True)
    assert "HTTPS_PROXY" not in routine_install.DAILY_WRAPPER_PATH.read_text() and not routine_install.is_stale()
    assert any("current" in l for l in routine_install.status() if "wrapper:" in l)


# --- update pins the interpreter it runs on ------------------------------------------------

def test_upgrade_passes_python_pin_to_uv_and_pipx(_home, monkeypatch):
    import sys
    seen = []
    monkeypatch.setattr(update, "_run", lambda cmd, cwd=None: (0, "1.2.3") if cmd[-1] == "--version" else (seen.append(cmd), (0, ""))[1])
    monkeypatch.setattr(update.shutil, "which", lambda name: f"/opt/bin/{name}")
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    sha = "c" * 40
    monkeypatch.setattr(update, "installed_commit", lambda method: sha)  # the commit check passes
    lines = update.upgrade("v1.2.3", "o/r", "uv-tool", sha=sha)
    assert seen[-1][:5] == ["/opt/bin/uv", "tool", "install", "--force", "--python"] and seen[-1][5] == running
    assert seen[-1][-1].endswith(f"@{sha}"), "installed by commit, not by tag"
    assert lines == [f"installed v1.2.3 (cccccccccccc) via uv-tool on python {running}"]
    # [update] python in config wins over the running interpreter
    config.CONFIG_PATH.write_text('[update]\npython = "3.12"\n')
    assert update.python_spec() == "3.12"
    update.upgrade("v1.2.3", "o/r", "uv-tool", sha=sha)
    assert seen[-1][4:6] == ["--python", "3.12"]
    update.upgrade("v1.2.3", "o/r", "pipx", sha=sha)
    assert seen[-1][:3] == ["/opt/bin/pipx", "install", "--force"] and seen[-1][3] == "--python"
    assert seen[-1][4].endswith("python3.12"), "pipx wants an executable (name or path), not a version spec"


def test_check_records_interpreter_and_trust(_home, monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: _Resp({"tag_name": "v0.0.1"}))
    rec = update.check(refresh=True)
    assert rec["python"].count(".") == 2 and rec["python_pin"] and rec["executable"]
    assert rec["trust"].startswith(("truststore", "SSL_CERT_FILE=", "SSL_CERT_DIR=", "openssl default"))


def test_explain_tls_error_names_the_two_proxy_shapes():
    assert update.explain_tls_error(None) is None
    assert update.explain_tls_error("tags: no network") is None
    assert "update.python=3.12" in update.explain_tls_error("[SSL: CERTIFICATE_VERIFY_FAILED] Basic Constraints of CA cert not marked critical")
    assert "SSL_CERT_FILE" in update.explain_tls_error("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate")


# --- doctor: the update source being unreachable is a FIX, and a failure is not cached all day ----

def test_doctor_unreachable_update_source_is_a_fix_with_network_facts(_home, monkeypatch):
    def offline(req, timeout=10, context=None):
        raise update.urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate")
    monkeypatch.setattr(update.urllib.request, "urlopen", offline)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9000")
    cs = doctor.checks(refresh_update=True, scan_repos=False)
    by = {c["name"]: c for c in cs}
    assert by["version"]["level"] == "WARN" and "see network" in by["version"]["detail"]
    assert by["network"]["level"] == "FIX"
    d = by["network"]["detail"]
    assert "UNREACHABLE" in d and "via proxy http://127.0.0.1:9000" in d and "python 3." in d and "trust:" in d
    assert "checked 20" in d and "not retried" not in d, "a fresh failure says when it was checked"
    assert "SSL_CERT_FILE" in by["network"]["fix"]
    assert "fix(es)" in doctor.summary_line(cs)
    # second doctor without --refresh within 15 min: served from the cache and labelled so
    cs2 = doctor.checks(refresh_update=False, scan_repos=False)
    by2 = {c["name"]: c for c in cs2}
    assert "cached" in by2["network"]["detail"] and "not retried" in by2["network"]["detail"]


def test_failed_check_is_retried_after_fifteen_minutes_but_success_is_cached_a_day(_home, monkeypatch):
    import datetime as dt
    calls = []
    def offline(req, timeout=10, context=None):
        calls.append(1); raise update.urllib.error.URLError("no network")
    monkeypatch.setattr(update.urllib.request, "urlopen", offline)
    rec = update.check(refresh=True)
    assert rec["latest"] is None and rec["from_cache"] is False
    assert update.check(refresh=False)["from_cache"] is True and len(calls) == 1, "fresh failure served from cache"
    old = json.loads(update.CHECK_PATH.read_text())
    old["checked"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=16)).isoformat(timespec="seconds")
    update.CHECK_PATH.write_text(json.dumps(old))
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: _Resp({"tag_name": "v0.0.1"}))
    rec = update.check(refresh=False)
    assert rec["latest"] == "v0.0.1" and rec["from_cache"] is False, "a 16-minute-old failure is retried"
    old = json.loads(update.CHECK_PATH.read_text())
    old["checked"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=20)).isoformat(timespec="seconds")
    update.CHECK_PATH.write_text(json.dumps(old))
    assert update.check(refresh=False)["from_cache"] is True, "a 20-hour-old success is still good"


def test_doctor_network_ok_line_and_python_pin_drift(_home, monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: _Resp({"tag_name": "v0.0.1"}))
    monkeypatch.delenv("HTTPS_PROXY", raising=False); monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.setattr(update.urllib.request, "getproxies", lambda: {})
    config.CONFIG_PATH.write_text('[update]\npython = "2.7"\n')
    cs = doctor.checks(refresh_update=True, scan_repos=False)
    by = {c["name"]: c for c in cs}
    assert by["network"]["level"] == "OK" and "reachable" in by["network"]["detail"] and "no proxy" in by["network"]["detail"]
    assert "update pins 2.7" in by["network"]["detail"]
    assert by["network:python"]["level"] == "WARN" and "update.python=" in by["network:python"]["fix"]


def test_reachable_repo_without_a_release_is_not_unreachable(_home, monkeypatch):
    def no_release(req, timeout=10, context=None):
        if req.full_url.endswith("/releases/latest"):
            raise update.urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return _Resp([])
    monkeypatch.setattr(update.urllib.request, "urlopen", no_release)
    rec = update.check(refresh=True)
    assert rec["latest"] is None and rec["reachable"] is True
    by = {c["name"]: c for c in doctor.checks(refresh_update=False, scan_repos=False)}
    assert by["network"]["level"] == "WARN" and "no published release" in by["network"]["detail"]
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: (_ for _ in ()).throw(update.urllib.error.URLError("down")))
    assert update.check(refresh=True)["reachable"] is False


def test_explicit_ssl_cert_file_wins_over_truststore(_home, monkeypatch, tmp_path):
    import ssl, sys, types
    fake = types.ModuleType("truststore")
    fake.SSLContext = lambda proto: "TRUSTSTORE"
    monkeypatch.setitem(sys.modules, "truststore", fake)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False); monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert update.ssl_context() == "TRUSTSTORE" and update.trust_source().startswith("truststore")
    bundle = tmp_path / "ca.pem"; bundle.write_text("")
    monkeypatch.setenv("SSL_CERT_FILE", str(bundle))
    assert isinstance(update.ssl_context(), ssl.SSLContext), "the bundle the person chose is used, not the OS store"
    assert update.trust_source() == f"SSL_CERT_FILE={bundle}"


def test_update_force_reinstalls_on_the_pinned_interpreter_when_the_lookup_fails(_home, monkeypatch, capsys):
    import argparse
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: (_ for _ in ()).throw(
        update.urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] Basic Constraints of CA cert not marked critical")))
    monkeypatch.setattr(update, "install_method", lambda: ("uv-tool", None))
    monkeypatch.setattr(update.shutil, "which", lambda name: f"/opt/bin/{name}")
    seen = []
    monkeypatch.setattr(update, "_run", lambda cmd, cwd=None: (seen.append(cmd), (0, ""))[1])
    import sys
    pin = "3.11" if f"{sys.version_info.major}.{sys.version_info.minor}" == "3.12" else "3.12"  # must differ from the runner
    config.CONFIG_PATH.write_text(f'[update]\npython = "{pin}"\n')
    args = argparse.Namespace(check=False, force=False, wire=False, quiet=False)
    assert update.cmd_update(args) == 1 and not seen, "without --force: report and stop"
    out = capsys.readouterr().out
    assert "update.python=3.12" in out
    args.force = True
    assert update.cmd_update(args) == 0
    assert seen[-1][:6] == ["/opt/bin/uv", "tool", "install", "--force", "--python", pin]
    assert seen[-1][-1].endswith(f"@v{teyla.__version__}"), "the installed version's tag, since the latest is unknown"


def test_doctor_reports_the_policy_detectors_the_policy_declares(_home, monkeypatch):
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: _Resp({"tag_name": "v0.0.0"}))
    policy.POLICY.parent.mkdir(parents=True, exist_ok=True)
    policy.POLICY.write_text("# P\n## 10. GitHub Actions are off — the laptop is the gate\n<!-- teyla:detect no-such -->\n")
    by = {}
    for c in doctor.checks(scan_repos=False):
        by.setdefault(c["name"], []).append(c)
    levels = sorted(c["level"] for c in by["policy:detect"])
    assert levels == ["OK", "WARN"]
    assert any("active: no-actions" in c["detail"] for c in by["policy:detect"])
    assert any("no-such" in c["detail"] for c in by["policy:detect"])


def test_weekly_plist_fires_fridays_2045_and_a_monday_plist_is_stale(_home, monkeypatch):
    """The weekly moved from Monday 07:30 to Friday 20:45. The plist is filled from SCHEDULE, and
    an already-installed Monday plist (current wrapper, current binary) must be seen as stale and
    rewritten by `routine install --if-stale`, which is what `teyla update` runs."""
    import plistlib
    monkeypatch.setenv("HOME", str(_home))
    monkeypatch.setattr(routine_install, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(routine_install, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    routine_install.install()
    fires = plistlib.loads(routine_install.PLIST_PATH.read_bytes())["StartCalendarInterval"]
    assert fires == {"Weekday": 5, "Hour": 20, "Minute": 45}
    assert routine_install.SCHEDULE[routine_install.LABEL] == dict(hour=20, minute=45, weekday=5)
    assert not routine_install.is_stale()
    # the plist an earlier release wrote: same label, wrapper and env, other schedule
    old = routine_install.PLIST_PATH.read_bytes().replace(
        b"<integer>5</integer>", b"<integer>1</integer>").replace(
        b"<integer>20</integer>", b"<integer>7</integer>").replace(b"<integer>45</integer>", b"<integer>30</integer>")
    routine_install.PLIST_PATH.write_bytes(old)
    assert plistlib.loads(old)["StartCalendarInterval"] == {"Weekday": 1, "Hour": 7, "Minute": 30}
    assert routine_install.is_stale()
    assert any("STALE" in l for l in routine_install.status() if "plist:" in l and "weekly" in l)
    routine_install.install(if_stale=True)
    assert plistlib.loads(routine_install.PLIST_PATH.read_bytes())["StartCalendarInterval"] == fires
    assert not routine_install.is_stale()


def test_routine_install_dry_writes_and_loads_nothing(_home, monkeypatch):
    """`routine install --dry` used to install for real (only catch-up read --dry)."""
    monkeypatch.setattr(routine_install.sys, "platform", "darwin")
    ran = []
    monkeypatch.setattr(routine_install.subprocess, "run", lambda *a, **k: ran.append(a) or None)
    lines = routine_install.install(dry=True)
    assert ran == []
    assert not routine_install.PLIST_PATH.exists() and not routine_install.DAILY_WRAPPER_PATH.exists()
    assert any(l.startswith("would write") for l in lines) and any("would load" in l for l in lines)


def test_a_plist_under_a_moved_home_is_never_bootstrapped(tmp_path, monkeypatch):
    """gui/<uid> is the real account's launchd: a throwaway HOME's plist carries the real label, and
    bootstrapping it replaced the real jobs (2026-10-01)."""
    ran = []
    monkeypatch.setattr(routine_install.subprocess, "run", lambda *a, **k: ran.append(a) or None)
    plist = tmp_path / "Library" / "LaunchAgents" / f"{routine_install.LABEL}.plist"
    plist.parent.mkdir(parents=True); plist.write_text("<plist/>")
    out = routine_install._load(plist, routine_install.LABEL)
    assert out.startswith("NOT LOADED") and ran == []


def test_doctor_says_why_a_generated_agents_md_is_stale(_home, monkeypatch):
    """~/.codex/AGENTS.md carries a copy of ~/.claude/CLAUDE.md; a day-old copy is "not wired",
    with the reason and the existing fix, not a bare "not wired"."""
    import os
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout=10, context=None: _Resp({"tag_name": "v0.0.0"}))
    (_home / ".codex").mkdir()
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("# P\n\n## 7. Merging\n")
    policy.CLAUDE_GLOBAL.parent.mkdir(parents=True)
    policy.CLAUDE_GLOBAL.write_text("# Mine\n\n@~/.agents/POLICY.md\n\n- merge into me/app without asking\n")
    policy.sync()
    by = {c["name"]: c for c in doctor.checks(refresh_update=False, scan_repos=False)}
    assert by["policy:codex"]["level"] == "OK"
    policy.CLAUDE_GLOBAL.write_text(policy.CLAUDE_GLOBAL.read_text() + "- and me/lib\n")
    os.utime(_home / ".codex" / "AGENTS.md", (1, 1))
    by = {c["name"]: c for c in doctor.checks(refresh_update=False, scan_repos=False)}
    assert by["policy:codex"]["level"] == "FIX" and by["policy:codex"]["fix"] == "teyla policy sync"
    assert by["policy:codex"]["detail"] == "not wired: ~/.codex/AGENTS.md is older than ~/.claude/CLAUDE.md"

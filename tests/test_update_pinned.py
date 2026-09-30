"""`teyla update` installs only a published release, by the commit its tag resolves to, verifies
the version it built, and honours `[update] pin` and `[update] channel`. GitHub is a stub keyed
by URL; installers are a stub `_run`; every path lives in tmp_path."""
from __future__ import annotations

import argparse
import json

import pytest

from teyla import __version__, config, doctor, policy, routine_install, update

SHA = "d" * 40


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
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
    monkeypatch.setattr(routine_install, "DAILY_WRAPPER_PATH", home / ".teyla" / "daily.sh")
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", home / ".teyla" / "weekly.sh")
    monkeypatch.setattr(routine_install, "DAILY_PLIST_PATH", home / "LaunchAgents" / "daily.plist")
    monkeypatch.setattr(routine_install, "PLIST_PATH", home / "LaunchAgents" / "weekly.plist")
    monkeypatch.setattr(routine_install, "DAILY_STAMP_PATH", home / ".teyla" / "daily.last")
    monkeypatch.setattr(routine_install, "STAMP_PATH", home / ".teyla" / "weekly.last")
    monkeypatch.setattr(routine_install, "DAILY_LOG_PATH", home / "Logs" / "daily.log")
    monkeypatch.setattr(routine_install, "LOG_PATH", home / "Logs" / "weekly.log")
    monkeypatch.delenv("TEYLA_IN_ROUTINE", raising=False)
    return home


class _Resp:
    def __init__(self, payload): self.payload = payload
    def read(self): return json.dumps(self.payload).encode()
    def __enter__(self): return self
    def __exit__(self, *a): return False


def github(monkeypatch, releases: dict, commits: dict, latest: str | None = None) -> list[str]:
    """Stub api.github.com: `releases` tag -> release json, `commits` ref -> sha."""
    urls = []

    def urlopen(req, timeout=10, context=None):
        url = req.full_url
        urls.append(url)
        if url.endswith("/releases/latest"):
            if latest is None:
                raise update.urllib.error.HTTPError(url, 404, "nf", {}, None)
            return _Resp(releases[latest])
        if "/releases/tags/" in url:
            tag = url.rsplit("/", 1)[1]
            if tag not in releases:
                raise update.urllib.error.HTTPError(url, 404, "nf", {}, None)
            return _Resp(releases[tag])
        if "/commits/" in url:
            ref = url.rsplit("/", 1)[1]
            if ref not in commits:
                raise update.urllib.error.HTTPError(url, 422, "no commit", {}, None)
            return _Resp({"sha": commits[ref]})
        raise AssertionError(f"unexpected GitHub call {url}")
    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    return urls


def installer(monkeypatch, reports: str):
    """Stub every subprocess: installs succeed, `teyla --version` answers `reports`."""
    ran = []

    def run(cmd, cwd=None):
        ran.append(cmd)
        if cmd[-1] == "--version":
            return 0, reports
        return 0, "ok"
    monkeypatch.setattr(update, "_run", run)
    monkeypatch.setattr(update.shutil, "which", lambda name: f"/opt/bin/{name}")
    monkeypatch.setattr(update, "install_method", lambda: ("uv-tool", None))
    monkeypatch.setattr(update, "post_update", lambda quiet=False: ["(post-update stubbed)"])
    return ran


def args(**kw):
    base = dict(check=False, force=False, wire=False, quiet=False)
    base.update(kw)
    return argparse.Namespace(**base)


# --- release only, by commit, verified ---------------------------------------------------

def test_draft_release_is_not_a_release(monkeypatch):
    github(monkeypatch, {"v99.0.0": {"tag_name": "v99.0.0", "draft": True}}, {}, latest="v99.0.0")
    assert update.check(refresh=True)["latest"] is None


def test_update_installs_the_release_by_its_commit_and_records_both(_home, monkeypatch):
    github(monkeypatch, {"v99.0.0": {"tag_name": "v99.0.0"}}, {"v99.0.0": SHA}, latest="v99.0.0")
    ran = installer(monkeypatch, "99.0.0")
    assert update.cmd_update(args()) == 0
    install = next(c for c in ran if c[1:3] == ["tool", "install"])
    assert install[-1].endswith(f"git+https://github.com/zaitsew/teyla@{SHA}")
    rec = json.loads(update.CHECK_PATH.read_text())
    assert rec["latest"] == "v99.0.0" and rec["sha"] == SHA
    assert json.loads(update.INSTALLED_PATH.read_text()) == {"version": "99.0.0", "tag": "v99.0.0", "sha": SHA}


def test_a_build_that_reports_another_version_is_rolled_back(_home, monkeypatch, capsys):
    github(monkeypatch, {"v99.0.0": {"tag_name": "v99.0.0"}}, {"v99.0.0": SHA}, latest="v99.0.0")
    ran = installer(monkeypatch, "98.0.0")
    assert update.cmd_update(args()) == 1
    out = capsys.readouterr().out
    assert "reports version 98.0.0, expected 99.0.0" in out and f"restored {__version__}" in out
    installs = [c for c in ran if c[1:3] == ["tool", "install"]]
    assert installs[-1][-1].endswith(f"@v{__version__}"), "the running version goes back"
    assert not update.INSTALLED_PATH.exists()


def test_restore_uses_the_recorded_commit_when_there_is_one(_home, monkeypatch):
    update.INSTALLED_PATH.write_text(json.dumps({"version": __version__, "tag": f"v{__version__}", "sha": "e" * 40}))
    ran = installer(monkeypatch, "x")
    update.restore("zaitsew/teyla", "uv-tool", "3.12")
    assert ran[-1][-1].endswith("@" + "e" * 40)


def test_no_commit_no_install(_home, monkeypatch, capsys):
    github(monkeypatch, {"v99.0.0": {"tag_name": "v99.0.0"}}, {}, latest="v99.0.0")
    ran = installer(monkeypatch, "99.0.0")
    assert update.cmd_update(args()) == 1
    assert "not installing an unpinned ref" in capsys.readouterr().out
    assert not [c for c in ran if c[1:3] == ["tool", "install"]]


def test_a_git_checkout_is_never_fast_forwarded(tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr(update, "_run", lambda cmd, cwd=None: (ran.append(cmd), (0, ""))[1])
    lines = update.upgrade("v99.0.0", "zaitsew/teyla", "checkout", tmp_path, sha=SHA)
    assert lines[0].startswith("SKIP") and f"git -C {tmp_path} pull --ff-only" in lines[0]
    assert ran == []


# --- update.pin ---------------------------------------------------------------------------

def test_pin_to_a_version_installs_exactly_that_release(_home, monkeypatch):
    config.set_value("update.pin", "0.1.0")
    urls = github(monkeypatch, {"v0.1.0": {"tag_name": "v0.1.0"}, "v99.0.0": {"tag_name": "v99.0.0"}},
                  {"v0.1.0": SHA}, latest="v99.0.0")
    rec = update.check(refresh=True)
    assert rec["latest"] == "v0.1.0" and rec["pin"] == "0.1.0" and rec["newer"], "a pin below the running version still applies"
    assert not any(u.endswith("/releases/latest") for u in urls)
    ran = installer(monkeypatch, "0.1.0")
    assert update.cmd_update(args()) == 0
    assert next(c for c in ran if c[1:3] == ["tool", "install"])[-1].endswith(f"@{SHA}")


def test_pin_to_a_sha_installs_that_commit_once(_home, monkeypatch):
    config.set_value("update.pin", SHA[:10])
    github(monkeypatch, {}, {SHA[:10]: SHA})
    rec = update.check(refresh=True)
    assert rec["latest"] is None and rec["sha"] == SHA and rec["newer"]
    ran = installer(monkeypatch, "7.7.7")
    assert update.cmd_update(args()) == 0
    assert json.loads(update.INSTALLED_PATH.read_text())["sha"] == SHA
    assert next(c for c in ran if c[1:3] == ["tool", "install"])[-1].endswith(f"@{SHA}")


def test_every_installer_reinstalls_the_exact_commit(monkeypatch):
    # review of #64, P1: `pip install --upgrade` keeps an installed build of the same version.
    monkeypatch.setattr(update.shutil, "which", lambda name: f"/opt/bin/{name}")
    assert "--force-reinstall" in update._installer("pip", "3.12", "src")
    assert "--reinstall" in update._installer("uv-tool", "3.12", "src")


def _pip_installer(monkeypatch, version: str | None, commit: str):
    """Stub a pip install: `import teyla` reports `version` (None: it fails), the installed
    distribution's direct_url.json says `commit`."""
    ran = []

    def run(cmd, cwd=None):
        ran.append(cmd)
        if cmd[-1] == update._COMMIT_PROBE:
            return 0, commit
        if "print(teyla.__version__)" in cmd[-1]:
            return (0, version) if version else (1, "ImportError")
        return 0, "ok"
    monkeypatch.setattr(update, "_run", run)
    monkeypatch.setattr(update, "install_method", lambda: ("pip", None))
    monkeypatch.setattr(update, "post_update", lambda quiet=False: ["(post-update stubbed)"])
    return ran


def test_a_sha_pin_that_did_not_land_is_rolled_back_not_recorded(_home, monkeypatch, capsys):
    # review of #64, P1: the installer kept another build; recording the pin would freeze that.
    config.set_value("update.pin", SHA)
    github(monkeypatch, {}, {SHA: SHA})
    ran = _pip_installer(monkeypatch, __version__, "e" * 40)
    assert update.cmd_update(args()) == 1
    out = capsys.readouterr().out
    assert f"asked for {SHA[:12]} but the installed build is {'e' * 12}" in out and "restored" in out
    assert not update.INSTALLED_PATH.exists()
    assert ran[-1][-1].endswith(f"@v{__version__}"), "the running version goes back"


def test_a_sha_pin_that_does_not_run_is_rolled_back(_home, monkeypatch, capsys):
    # review of #64, P2: a build whose version probe fails is not a successful install.
    config.set_value("update.pin", SHA)
    github(monkeypatch, {}, {SHA: SHA})
    _pip_installer(monkeypatch, None, SHA)
    assert update.cmd_update(args()) == 1
    out = capsys.readouterr().out
    assert "reports version (none)" in out and "restored" in out
    assert not update.INSTALLED_PATH.exists()


def test_a_version_pin_is_met_by_the_release_commit_not_the_version_number(_home, monkeypatch):
    # review of #64, P1: a build of main that says the pinned version is not that release.
    config.set_value("update.pin", __version__)
    tag = f"v{__version__}"
    github(monkeypatch, {tag: {"tag_name": tag}}, {tag: SHA})
    monkeypatch.setattr(update, "_dist_commit", lambda: "e" * 40)
    assert update.check(refresh=True)["newer"], "same version, another commit: install the release"
    monkeypatch.setattr(update, "_dist_commit", lambda: None)
    assert update.check(refresh=True)["newer"], "unknown provenance does not meet a pin"
    monkeypatch.setattr(update, "_dist_commit", lambda: SHA)
    assert not update.check(refresh=True)["newer"]


def test_doctor_shows_the_pin(_home, monkeypatch):
    config.set_value("update.pin", "0.1.0")
    github(monkeypatch, {"v0.1.0": {"tag_name": "v0.1.0"}}, {"v0.1.0": SHA})
    by = {c["name"]: c for c in doctor.checks(refresh_update=True, scan_repos=False)}
    assert "pinned to 0.1.0" in by["update"]["detail"] and "update.pin=" in by["update"]["fix"]
    assert by["version"]["level"] == "FIX" and "pinned" in by["version"]["detail"]


def test_config_write_force_keeps_the_pin(_home):
    config.set_value("update.pin", "0.1.0")
    config.write(force=True)
    assert config.load()["update"]["pin"] == "0.1.0"


# --- update.channel -----------------------------------------------------------------------

def test_channel_none_means_no_routine_update_but_by_hand_works(_home, monkeypatch):
    config.set_value("update.channel", "none")
    monkeypatch.setattr(routine_install, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(routine_install, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    routine_install.install()
    assert "update --quiet" not in routine_install.DAILY_WRAPPER_PATH.read_text()
    monkeypatch.setenv("TEYLA_IN_ROUTINE", routine_install.DAILY_LABEL)
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    assert update.cmd_update(args(quiet=True)) == 0, "a stale wrapper that still calls update does nothing"
    monkeypatch.delenv("TEYLA_IN_ROUTINE")
    github(monkeypatch, {"v99.0.0": {"tag_name": "v99.0.0"}}, {"v99.0.0": SHA}, latest="v99.0.0")
    installer(monkeypatch, "99.0.0")
    assert update.cmd_update(args()) == 0


def test_unknown_channel_is_refused_and_doctor_names_the_fix(_home, monkeypatch, capsys):
    config.set_value("update.channel", "main")
    assert update.cmd_update(args()) == 1
    assert "release, none" in capsys.readouterr().out
    github(monkeypatch, {"v0.0.1": {"tag_name": "v0.0.1"}}, {"v0.0.1": SHA}, latest="v0.0.1")
    by = {c["name"]: c for c in doctor.checks(refresh_update=True, scan_repos=False)}
    assert by["update"]["level"] == "FIX" and "update.channel=release" in by["update"]["fix"]


# --- policy template changes in safe mode are proposed, not merged --------------------------

def _template(tmp_path, monkeypatch):
    t = tmp_path / "POLICY.tmpl.md"
    monkeypatch.setattr(policy, "TEMPLATE", t)
    return t


def test_safe_mode_policy_refresh_writes_a_proposal_and_touches_nothing(_home, tmp_path, monkeypatch):
    t = _template(tmp_path, monkeypatch)
    t.write_text("Owner: {{owner}}. Edit here.\n\n## A\none\n\n## B\ntwo\n")
    policy.init(owner="Ann")
    policy.refresh()  # records the base
    policy.POLICY.write_text(policy.POLICY.read_text().replace("two", "two, my edit"))
    local, base = policy.POLICY.read_text(), policy.BASE_PATH.read_text()
    t.write_text("Owner: {{owner}}. Edit here.\n\n## A\none, upstream\n\n## B\ntwo\n")
    config.set_value("safe.enabled", "true")
    lines = policy.refresh()
    assert "proposed" in lines[0] and "diff -u" in lines[0]
    assert policy.POLICY.read_text() == local and policy.BASE_PATH.read_text() == base
    proposed = policy.PROPOSED_PATH.read_text()
    assert "one, upstream" in proposed and "two, my edit" in proposed
    by = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    assert by["policy:template"]["level"] == "FIX" and "diff -u" in by["policy:template"]["fix"]
    policy.POLICY.write_text(proposed)
    assert "policy-proposed.md removed" in policy.resolved()
    assert not policy.PROPOSED_PATH.exists()


def test_outside_safe_mode_policy_refresh_still_merges(_home, tmp_path, monkeypatch):
    t = _template(tmp_path, monkeypatch)
    t.write_text("Owner: {{owner}}. Edit here.\n\n## A\none\n")
    policy.init(owner="Ann")
    policy.refresh()
    t.write_text("Owner: {{owner}}. Edit here.\n\n## A\none, upstream\n")
    assert policy.refresh()[0].startswith("applied")
    assert "one, upstream" in policy.POLICY.read_text() and not policy.PROPOSED_PATH.exists()


def test_safe_mode_a_failing_merge_proposes_nothing(_home, tmp_path, monkeypatch):
    # review of #64, P2: `git merge-file` erroring (255, empty stdout) is not "255 conflicts".
    import subprocess
    t = _template(tmp_path, monkeypatch)
    t.write_text("Owner: {{owner}}. Edit here.\n\n## A\none\n")
    policy.init(owner="Ann")
    policy.refresh()
    policy.POLICY.write_text(policy.POLICY.read_text() + "\nmy edit\n")
    t.write_text("Owner: {{owner}}. Edit here.\n\n## A\none, upstream\n")
    policy.PROPOSED_PATH.write_text("an earlier proposal\n")
    config.set_value("safe.enabled", "true")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 255, "", "fatal: boom"))
    lines = policy.refresh()
    assert "failed: fatal: boom" in lines[0] and "nothing proposed" in lines[0]
    assert policy.PROPOSED_PATH.read_text() == "an earlier proposal\n"

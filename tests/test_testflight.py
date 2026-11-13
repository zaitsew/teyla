"""teyla.testflight — did the build reach a person.

The release tool is faked by monkeypatching subprocess.run; platform.toml and teyla.toml live
under tmp_path. Nothing here reaches the network or the real ~/.teyla."""
from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

from teyla import cli, config, net, platform, productize, testflight

TOOL_BODY = "#!/bin/sh\n"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(platform, "PLATFORM_PATH", home / ".teyla" / "platform.toml")
    monkeypatch.setattr(config, "code_root", lambda: tmp_path / "repos")
    monkeypatch.delenv(config.SAFE_ENV, raising=False)
    monkeypatch.setattr(net, "_allow_once", False)
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: False)
    (tmp_path / "repos").mkdir()
    return home


def platform_toml(tmp_path, *, tool=True, tester="me@example.com"):
    t = tmp_path / "release-tool"
    t.write_text(TOOL_BODY)
    t.chmod(0o755)
    body = "[apple]\n"
    if tool:
        body += f'release_tool = "{t}"\n'
    if tester:
        body += f'tester = "{tester}"\n'
    platform.PLATFORM_PATH.write_text(body)
    return t


def product(tmp_path, name="app-a", *, bundle="com.example.app", ios='"testflight-internal"', root=None):
    d = (root or tmp_path / "repos") / name
    (d / ".git").mkdir(parents=True)
    body = f'[product]\nname = "{name}"\n'
    if ios is not None:
        body += f"[productize.distribution]\nios = {ios}\n"
    if bundle:
        body += f'[release]\napple_bundle_id = "{bundle}"\n'
    (d / "teyla.toml").write_text(body)
    return d


def plat(platform_="IOS", *, behind=0, up=("1.9.0", "120"), inst=("1.9.0", "120"), blockers=()):
    return {
        "platform": platform_,
        "newest_uploaded": None if up is None else {"version": up[0], "build": up[1],
                                                   "uploaded": "2026-10-12T09:30:00Z", "processing": "VALID"},
        "newest_installable": None if inst is None else {"version": inst[0], "build": inst[1], "via": ["Internal"]},
        "behind": behind,
        "blockers": list(blockers),
    }


def payload(*plats, found=True):
    return {"bundle_id": "com.example.app", "tester": "me@example.com", "tester_found": found,
            "platforms": list(plats)}


def territories(chn=False, *others):
    """The `availability` JSON: CHN as given, plus any other territory ids that are available."""
    return {"bundle_id": "com.example.app",
            "territories": [{"territory": "CHN", "available": chn}] +
                           [{"territory": t, "available": True} for t in others]}


def fake_tool(monkeypatch, out=None, *, rc=0, stderr="", raises=None, calls=None, avail=None):
    """`beta reached` answers `out`; `availability` answers `avail` (CHN excluded by default)."""
    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw))
        if raises:
            raise raises
        which = avail if cmd[1] == "availability" and avail is not None else \
            territories(False, "USA") if cmd[1] == "availability" else out
        text = which if isinstance(which, str) else json.dumps(which)
        return subprocess.CompletedProcess(cmd, rc, stdout=text, stderr=stderr)
    monkeypatch.setattr(testflight.subprocess, "run", run)


def go(capsys, *argv):
    rc = cli.main(["testflight", *argv])
    return rc, capsys.readouterr()


def test_current(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    calls = []
    fake_tool(monkeypatch, payload(plat()), calls=calls)
    rc, cap = go(capsys)
    assert rc == 0
    assert cap.out.strip() == "app-a  iOS    1.9.0 (120) uploaded 2026-10-12; you can install 120 — current"
    cmd, kw = calls[0]
    assert cmd[1:] == ["beta", "reached", "--bundle-id", "com.example.app", "--email", "me@example.com", "--json"]
    assert kw["timeout"] == testflight.TIMEOUT_S


def test_behind_lists_blockers(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat(behind=2, inst=("1.8.0", "118"),
                                        blockers=["120: processing", "119: in no group with you"])))
    rc, cap = go(capsys)
    assert rc == 1
    assert cap.out.strip() == ("app-a  iOS    1.9.0 (120) uploaded 2026-10-12; you can install 118 "
                               "— 2 behind: 120: processing; 119: in no group with you")


def test_nothing_installable(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat("MAC_OS", behind=1, inst=None, blockers=["120: expired"])))
    rc, cap = go(capsys)
    assert rc == 1
    assert "macOS" in cap.out and "you can install nothing" in cap.out and "120: expired" in cap.out


def test_newer_expired_builds_are_not_behind(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat(behind=2, inst=("1.8.0", "118"),
                                        blockers=["120: expired", "119: expired"])))
    rc, cap = go(capsys)
    assert rc == 0
    assert cap.out.strip().endswith("you can install 118 — current; 2 newer expired")


def test_expired_and_processing_counts_only_the_processing_one(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat(behind=2, inst=("1.8.0", "118"),
                                        blockers=["120: processing", "119: expired"])))
    rc, cap = go(capsys)
    assert rc == 1
    assert "— 1 behind: 120: processing; 119: expired" in cap.out


def test_two_platforms_one_behind_fails(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat(), plat("MAC_OS", behind=1, inst=("1.8.0", "9"), blockers=["10: processing"])))
    rc, cap = go(capsys)
    assert rc == 1
    assert len(cap.out.strip().splitlines()) == 2


def test_tester_not_found(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(found=False))
    rc, cap = go(capsys)
    assert rc == 1
    assert "tester is not on the team" in cap.out


@pytest.mark.parametrize("kw", [
    dict(rc=3, stderr="boom: bad key\n"),
    dict(out="not json"),
    dict(out={"unexpected": 1}),
    dict(raises=subprocess.TimeoutExpired("x", 60)),
    dict(raises=PermissionError(13, "Permission denied")),
])
def test_tool_failures_are_one_line(tmp_path, monkeypatch, capsys, kw):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, kw.pop("out", ""), **kw)
    rc, cap = go(capsys)
    assert rc == 1
    assert len(cap.out.strip().splitlines()) == 1 and "Traceback" not in cap.out + cap.err
    assert cap.out.startswith("app-a  ")


def test_nonzero_exit_names_the_tool_message(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, "", rc=2, stderr="ASC auth failed\n")
    _, cap = go(capsys)
    assert "exited 2: ASC auth failed" in cap.out


def test_missing_bundle_id(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, bundle=None)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    rc, cap = go(capsys)
    assert rc == 1
    assert "no bundle id" in cap.out and "apple_bundle_id" in cap.out


def test_tool_unset_missing_and_tester_unset(tmp_path, monkeypatch, capsys):
    product(tmp_path)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    platform_toml(tmp_path, tool=False)
    rc, cap = go(capsys)
    assert rc == 1 and "no release tool" in cap.out
    platform.PLATFORM_PATH.write_text('[apple]\nrelease_tool = "/nonexistent/tool"\ntester = "me@example.com"\n')
    rc, cap = go(capsys)
    assert rc == 1 and "is not at /nonexistent/tool" in cap.out
    platform_toml(tmp_path, tester="")
    rc, cap = go(capsys)
    assert rc == 1 and "no tester" in cap.out
    platform.PLATFORM_PATH.unlink()
    rc, cap = go(capsys)
    assert rc == 1 and "no release tool" in cap.out


def test_scope(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, "shipped", ios='"app-store"', bundle="com.example.shipped")
    product(tmp_path, "mac-only", ios=None, bundle="com.example.mac")        # bundle id alone is enough
    product(tmp_path, "web-only", ios='"none"', bundle=None)                  # out of scope
    product(tmp_path, "dev-only", ios='"xcode"', bundle=None)                 # out of scope
    seen = []
    fake_tool(monkeypatch, payload(plat()), calls=seen)
    rc, cap = go(capsys)
    assert rc == 0
    assert sorted(c[0][4] for c in seen if c[0][1] == "beta") == ["com.example.mac", "com.example.shipped"]
    assert "web-only" not in cap.out and "dev-only" not in cap.out


def test_testflight_without_bundle_id_is_in_scope(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, bundle=None)
    rc, cap = go(capsys)
    assert rc == 1 and cap.out.startswith("app-a  no bundle id")


def test_no_product_in_scope_exits_zero(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, ios='"none"', bundle=None)
    rc, cap = go(capsys)
    assert rc == 0 and "no product ships" in cap.out


def test_path_argument(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    other = product(tmp_path, "elsewhere", root=tmp_path / "other")
    product(tmp_path, "app-a")
    seen = []
    fake_tool(monkeypatch, payload(plat()), calls=seen)
    rc, cap = go(capsys, str(other))
    assert rc == 0 and len(seen) == 1 and cap.out.startswith("elsewhere  ")
    rc, cap = go(capsys, str(tmp_path / "missing"))
    assert rc == 2 and "no teyla.toml" in cap.err


def test_json_shape(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, "app-a", bundle="com.example.a")
    product(tmp_path, "app-b", bundle=None)
    pl = payload(plat(behind=1, inst=("1.8.0", "118"), blockers=["120: processing"]))
    fake_tool(monkeypatch, pl)
    rc, cap = go(capsys, "--json")
    assert rc == 1
    data = json.loads(cap.out)
    assert [d["product"] for d in data] == ["app-a", "app-b"]
    a, b = data
    assert a["verdict"] == "behind" and a["bundle_id"] == "com.example.a" and a["payload"] == pl
    assert a["platforms"] == [{"platform": "IOS", "verdict": "behind", "behind": 1}]
    assert b["verdict"] == "error" and b["error"] and b["payload"] is None
    assert set(a) == {"product", "repo", "bundle_id", "verdict", "error", "platforms", "payload"}


def test_json_current(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat()))
    rc, cap = go(capsys, "--json")
    assert rc == 0 and json.loads(cap.out)[0]["verdict"] == "current"


def test_safe_mode_refuses_without_allow_network(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run in safe mode"))
    rc, cap = go(capsys)
    assert rc == 1 and "safe mode is on" in cap.err and cap.out == ""
    fake_tool(monkeypatch, payload(plat()))
    rc, cap = go(capsys, "--allow-network")
    assert rc == 0 and "current" in cap.out


def test_parse_exposes_release_table(tmp_path):
    d = product(tmp_path)
    assert productize.parse(d / "teyla.toml")["release"] == {"apple_bundle_id": "com.example.app"}


def test_templates_carry_the_new_keys():
    import teyla
    t = teyla.templates_dir()
    assert "tester" in (t / "platform" / "platform.toml").read_text()
    assert "apple_bundle_id" in (t / "repo" / "teyla.toml").read_text()


def test_a_declared_platform_with_no_build_is_none_not_a_pass(tmp_path, monkeypatch):
    platform_toml(tmp_path)
    d = product(tmp_path)
    (d / "teyla.toml").write_text((d / "teyla.toml").read_text().replace(
        'ios = "testflight-internal"\n', 'ios = "testflight-internal"\nmacos = "testflight"\n'))
    fake_tool(monkeypatch, payload(plat("IOS")))
    rows = testflight.run()
    assert rows[0]["verdict"] == "none"
    assert [(p["platform"], p["verdict"]) for p in rows[0]["platforms"]] == [("IOS", "current"), ("MAC_OS", "none")]
    assert testflight.exit_code(rows) == 1
    assert "macOS" in testflight.render_text(rows) and "nothing uploaded" in testflight.render_text(rows)


def test_a_named_teyla_toml_that_does_not_parse_is_an_error(tmp_path, monkeypatch):
    platform_toml(tmp_path)
    d = product(tmp_path)
    (d / "teyla.toml").write_text("[product\nname = ")
    fake_tool(monkeypatch, payload(plat("IOS")))
    rows = testflight.run([str(d)])
    assert [r["verdict"] for r in rows] == ["error"] and "does not parse" in rows[0]["error"]
    assert testflight.exit_code(rows) == 1
    assert testflight.run() == []          # the sweep leaves it to `teyla productize`


# --- --quiet: the problems file the banner and the digest read ---------------------------------

@pytest.fixture
def problems(tmp_path, monkeypatch, _env):
    monkeypatch.setattr(config, "TEYLA_DIR", _env / ".teyla")
    return _env / ".teyla" / "testflight.problems"


def test_quiet_writes_one_line_per_platform_that_is_not_current(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat(), plat("MAC_OS", behind=2, inst=("1.8.0", "9"), up=("1.9.0", "120"),
                                                blockers=["120: processing"])))
    rc, cap = go(capsys, "--quiet")
    assert rc == 1 and cap.out == "" and cap.err == ""
    rows = [ln.split("\t") for ln in problems.read_text().splitlines()]
    assert rows == [["testflight|app-a|MAC_OS|behind", "app-a macOS: 2 behind — 120: processing"]]


def test_quiet_line_for_ios_behind_and_removed_when_current(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat(behind=2, inst=("1.8.0", "118"), blockers=["120: processing"])))
    rc, cap = go(capsys, "--quiet")
    assert rc == 1 and cap.out == ""
    assert problems.read_text() == "testflight|app-a|IOS|behind\tapp-a iOS: 2 behind — 120: processing\n"
    fake_tool(monkeypatch, payload(plat()))
    rc, cap = go(capsys, "--quiet")
    assert rc == 0 and cap.out == "" and not problems.exists()


def test_quiet_error_and_nothing_installable_rows(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, "", rc=2, stderr="ASC auth failed\n")
    rc, cap = go(capsys, "--quiet")
    assert rc == 1 and cap.out == ""
    # the same broken tool also fails the availability read: that is its own line, never a pass
    first, second = [ln.split("\t") for ln in problems.read_text().splitlines()]
    assert first[0] == "testflight|app-a|error" and first[1].startswith("app-a: the release tool exited 2")
    assert second[0] == "testflight|app-a|CHN|error" and "could not read App Store availability" in second[1]
    fake_tool(monkeypatch, payload(plat("MAC_OS", behind=1, inst=None, blockers=["120: expired"])))
    go(capsys, "--quiet")
    # the manifest also declares iOS, which the tool said nothing about: no build at all
    assert problems.read_text().splitlines() == [
        "testflight|app-a|MAC_OS|none\tapp-a macOS: none installable — 120: expired",
        "testflight|app-a|IOS|none\tapp-a iOS: none installable"]


def test_quiet_in_safe_mode_does_nothing_and_exits_zero(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    problems.write_text("testflight|app-a|IOS|behind\told answer\n")
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    rc, cap = go(capsys, "--quiet")
    assert rc == 0 and cap.out == "" and cap.err == ""
    assert problems.read_text().startswith("testflight|app-a|IOS|behind")   # not asked, so left as it was


def test_quiet_with_no_product_in_scope_removes_the_file(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    problems.write_text("testflight|x|IOS|behind\told\n")
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    rc, cap = go(capsys, "--quiet")
    assert rc == 0 and cap.out == "" and not problems.exists()


# --- --china: POLICY §15, no product stays available in China mainland ------------------------------

def test_china_available_prints_one_line_with_the_fix(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, "app-a", bundle="com.example.a")
    product(tmp_path, "app-b", bundle="com.example.b")
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        chn = cmd[3] == "com.example.a"
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(territories(chn, "USA")), stderr="")
    monkeypatch.setattr(testflight.subprocess, "run", run)
    rc, cap = go(capsys, "--china")
    assert rc == 1
    lines = cap.out.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("app-a  ")
    assert "CHN" in lines[0] and "POLICY \u00a715" in lines[0] and "exclude CHN" in lines[0] and "app-wide" in lines[0]
    assert [c[1:] for c in calls] == [["availability", "--bundle-id", "com.example.a", "--json"],
                                      ["availability", "--bundle-id", "com.example.b", "--json"]]


def test_china_excluded_is_silent(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat()), avail=territories(False, "USA", "FRA"))
    rc, cap = go(capsys, "--china")
    assert rc == 0 and cap.out == "" and cap.err == ""
    # a tool that lists only the territories that are on, with no CHN entry at all, is also a pass
    fake_tool(monkeypatch, payload(plat()), avail={"territories": [{"territory": "USA", "available": True}]})
    rc, cap = go(capsys, "--china")
    assert rc == 0 and cap.out == ""


def test_china_reads_only_available_true(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat()), avail={"territories": [{"territory": "chn", "available": "false"}]})
    rc, cap = go(capsys, "--china")
    assert rc == 0 and cap.out == ""


@pytest.mark.parametrize("kw", [
    dict(avail="not json"),
    dict(avail={"unexpected": 1}),
    dict(rc=2, stderr="unknown command: availability\n"),
    dict(raises=subprocess.TimeoutExpired("x", 60)),
])
def test_china_unreadable_is_a_problem_not_a_pass(tmp_path, monkeypatch, capsys, kw):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat()), **kw)
    rc, cap = go(capsys, "--china")
    assert rc == 1
    assert len(cap.out.strip().splitlines()) == 1 and "could not read App Store availability" in cap.out


def test_china_no_bundle_id_is_an_error_line(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, bundle=None)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    rc, cap = go(capsys, "--china")
    assert rc == 1 and "no bundle id" in cap.out


def test_china_json(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat()), avail=territories(True))
    rc, cap = go(capsys, "--china", "--json")
    data = json.loads(cap.out)
    assert rc == 1 and [d["verdict"] for d in data] == ["china"] and "lines" not in data[0]


def test_china_safe_mode_refuses(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run in safe mode"))
    rc, cap = go(capsys, "--china")
    assert rc == 1 and "safe mode is on" in cap.err and cap.out == ""


def test_quiet_adds_china_lines_to_the_problems_file(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat()), avail=territories(True, "USA"))
    rc, cap = go(capsys, "--quiet")
    assert rc == 1 and cap.out == ""
    key, text = problems.read_text().rstrip("\n").split("\t")
    assert key == "testflight|app-a|CHN" and "China mainland" in text and "exclude CHN" in text
    fake_tool(monkeypatch, payload(plat()), avail=territories(False, "USA"))
    rc, cap = go(capsys, "--quiet")
    assert rc == 0 and not problems.exists()


def test_china_with_quiet_writes_the_problems_file_and_prints_nothing(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(plat()), avail=territories(True, "USA"))
    rc, cap = go(capsys, "--china", "--quiet")
    assert rc == 1 and cap.out == ""
    assert problems.read_text().startswith("testflight|app-a|CHN\t")


# --- store lag: the store build is current in TestFlight but older than the sources on main ----------

REAL_RUN = subprocess.run   # fake_tool replaces subprocess.run for every module; git must stay real
TODAY = "2026-11-03"
OLD = "2026-10-26T09:00:00Z"   # the upload
STORE_TARGET = '''
[[release.store_target]]
platform = "macos"
scheme = "AppStore"
project = "apps/mac/App.xcodeproj"
paths = ["apps/mac/App", ":(exclude)apps/mac/App/Core/Cli.swift"]
'''


def git(repo, *args, when=None):
    env = {**__import__("os").environ, "GIT_CONFIG_GLOBAL": "/dev/null"}
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    r = REAL_RUN(["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@example.com",
                  "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout


def commit(repo, rel, when, text="x"):
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text + when)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", f"change {rel}", when=when)


def store_repo(tmp_path, *, target=STORE_TARGET):
    """A real git repo on `main` with a product manifest, first committed on 1 October."""
    d = product(tmp_path, bundle="com.example.app", ios=None)
    (d / ".git").rmdir()
    git(d, "init", "-b", "main")
    with (d / "teyla.toml").open("a") as f:
        f.write(target)
    commit(d, "README.md", "2026-10-01T09:00:00Z")
    return d


def lag_tool(monkeypatch, out, calls=None):
    """The release tool answers `out`; every git command goes through for real."""
    def run(cmd, **kw):
        if cmd[0] == "git":
            return REAL_RUN(cmd, **kw)
        if calls is not None:
            calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(out), stderr="")
    monkeypatch.setattr(testflight.subprocess, "run", run)
    monkeypatch.setattr(testflight, "_today", lambda: __import__("datetime").date.fromisoformat(TODAY))


def mac(uploaded=OLD, **kw):
    p = plat("MAC_OS", up=("0.32.0", "1"), inst=("0.32.0", "1"), **kw)
    if p["newest_uploaded"]:
        p["newest_uploaded"]["uploaded"] = uploaded
    return p


def test_store_lag_warns_with_the_release_command(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path)
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    calls = []
    lag_tool(monkeypatch, payload(plat(), mac()), calls)
    rc, cap = go(capsys)
    assert rc == 1
    lines = cap.out.strip().splitlines()
    assert lines[0].startswith("app-a  iOS    ") and lines[0].endswith("— current")
    assert lines[1].endswith("— current")                                   # TestFlight itself is fine
    assert lines[2].startswith("app-a  WARN macOS store build uploaded 2026-10-26 lags main; AppStore changed 2026-11-02")
    assert "change apps/mac/App/Home.swift" in lines[2]
    assert lines[2].endswith(f"Release: cd {d} && {tmp_path / 'release-tool'} release --platform macos "
                             "--project apps/mac/App.xcodeproj --scheme AppStore --bundle-id com.example.app")
    assert len(calls) == 1 and calls[0][1:3] == ["beta", "reached"]       # no extra call to Apple


def test_store_lag_is_stale_in_json_and_quiet_problems(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    d = store_repo(tmp_path)
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys, "--json")
    row = json.loads(cap.out)[0]
    assert rc == 1 and row["verdict"] == "stale"
    assert row["platforms"][0]["verdict"] == "stale" and row["platforms"][0]["lag"]["uploaded"] == "2026-10-26"
    rc, cap = go(capsys, "--quiet")
    assert rc == 1 and cap.out == ""
    key, text = [l for l in problems.read_text().splitlines() if "MAC_OS" in l][0].split("\t")
    assert key == "testflight|app-a|MAC_OS|stale"
    assert text.startswith("app-a macOS: macOS store build uploaded 2026-10-26 lags main") and "--platform macos" in text


def test_upload_newer_than_the_change_is_current(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path)
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac(uploaded="2026-11-03T08:00:00Z")))
    rc, cap = go(capsys)
    assert rc == 0 and "WARN" not in cap.out


def test_a_change_inside_the_grace_period_does_not_warn(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path)
    commit(d, "apps/mac/App/Home.swift", "2026-10-28T10:00:00Z")           # 2 days after the upload, grace 3
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)
    assert rc == 0 and "WARN" not in cap.out
    commit(d, "apps/mac/App/Home.swift", "2026-10-30T10:00:00Z")           # 4 days after
    rc, cap = go(capsys)
    assert rc == 1 and "WARN" in cap.out


def test_grace_days_can_be_set_per_target(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path, target=STORE_TARGET + "grace_days = 0\n")
    commit(d, "apps/mac/App/Home.swift", "2026-10-27T10:00:00Z")           # one day after
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)
    assert rc == 1 and "WARN" in cap.out


def test_changes_outside_the_target_sources_do_not_warn(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path)
    commit(d, "README.md", "2026-11-02T10:00:00Z")
    commit(d, "apps/mac/Tools/make.py", "2026-11-02T11:00:00Z")
    commit(d, "apps/mac/App/Core/Cli.swift", "2026-11-02T12:00:00Z")      # excluded from the store target
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)
    assert rc == 0 and "WARN" not in cap.out


def test_the_default_paths_are_the_projects_folder(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path, target=STORE_TARGET.split("paths")[0])
    commit(d, "apps/mac/Tools/make.py", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)
    assert rc == 1 and "WARN" in cap.out


def test_a_merge_counts_when_it_landed_not_when_its_commits_were_written(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path)
    git(d, "checkout", "-b", "feature")
    commit(d, "apps/mac/App/Home.swift", "2026-10-20T10:00:00Z")           # written before the upload
    git(d, "checkout", "main")
    git(d, "merge", "--no-ff", "-m", "Merge feature", "feature", when="2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)
    assert rc == 1 and "AppStore changed 2026-11-02" in cap.out


def test_frozen_for_thirty_days_does_not_warn(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path, target=STORE_TARGET + 'frozen = "2026-10-04: nobody opened the Mac app"\n')
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)                                                   # 30 days from 2026-10-04 is 2026-11-03
    assert rc == 0 and "WARN" not in cap.out


def test_frozen_for_less_than_thirty_days_still_warns(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path, target=STORE_TARGET + 'frozen = "2026-10-05: nobody opened the Mac app"\n')
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)                                                   # 29 days
    assert rc == 1 and "WARN" in cap.out


def test_frozen_now_is_silent_from_its_date_and_says_so(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path, target=STORE_TARGET + 'frozen = "2026-10-30: the owner stopped using it"\nfrozen_now = true\n')
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)                                                   # 4 days, no 30-day wait
    assert rc == 0 and "WARN" not in cap.out
    assert "app-a  macOS store build frozen since 2026-10-30: the owner stopped using it; lag not checked" in cap.out


def test_frozen_now_before_its_date_still_warns(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path, target=STORE_TARGET + 'frozen = "2026-12-01: planned"\nfrozen_now = true\n')
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)
    assert rc == 1 and "WARN" in cap.out and "frozen since" not in cap.out


def test_a_frozen_target_is_in_the_json_and_not_a_problem(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path, target=STORE_TARGET + 'frozen = "2026-10-04: nobody opened the Mac app"\n')
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac()))
    rows = testflight.run([str(d)])
    mac_entry = [p for p in rows[0]["platforms"] if p["platform"] == "MAC_OS"][0]
    assert mac_entry["frozen"] == {"since": "2026-10-04", "reason": "nobody opened the Mac app"}
    assert "lag" not in mac_entry and testflight.problem_lines(rows) == []


def test_a_frozen_target_with_no_upload_stays_in_the_json(tmp_path, monkeypatch):
    platform_toml(tmp_path)
    d = store_repo(tmp_path, target=STORE_TARGET + 'frozen = "2026-10-04: nobody opened the Mac app"\n')
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(plat()))                                 # the tool lists iOS only
    rows = testflight.run([str(d)])
    mac_entry = [p for p in rows[0]["platforms"] if p["platform"] == "MAC_OS"]
    assert mac_entry and mac_entry[0]["frozen"]["since"] == "2026-10-04"
    assert rows[0]["verdict"] == "current"


def test_frozen_now_needs_frozen_and_a_bool(tmp_path):
    base = {"platform": "macos", "scheme": "S", "project": "apps/mac/S.xcodeproj"}
    _, err = testflight.store_targets({"release": {"store_target": [{**base, "frozen_now": True}]}})
    assert err and "needs `frozen" in err
    _, err = testflight.store_targets({"release": {"store_target": [{**base, "frozen": "2026-11-01: x", "frozen_now": "yes"}]}})
    assert err and "true or false" in err


def test_no_upload_on_the_platform_warns(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path)
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(plat()))                                 # the tool lists iOS only
    rc, cap = go(capsys)
    assert rc == 1
    assert "app-a  WARN no macOS build uploaded; AppStore changed 2026-11-02" in cap.out
    assert "--platform macos" in cap.out


def test_no_upload_and_no_source_change_is_not_a_finding(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    store_repo(tmp_path)
    lag_tool(monkeypatch, payload(plat()))
    rc, cap = go(capsys)
    assert rc == 0 and "macOS" not in cap.out


def test_a_platform_behind_in_testflight_keeps_its_own_verdict(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = store_repo(tmp_path)
    commit(d, "apps/mac/App/Home.swift", "2026-11-02T10:00:00Z")
    lag_tool(monkeypatch, payload(mac(behind=1, blockers=["2: processing"])))
    rc, cap = go(capsys, "--json")
    row = json.loads(cap.out)[0]
    assert rc == 1 and row["verdict"] == "behind" and "lag" in row["platforms"][0]


@pytest.mark.parametrize("target", [
    '\n[[release.store_target]]\nplatform = "macos"\nscheme = "AppStore"\n',                 # no project
    '\n[[release.store_target]]\nplatform = "linux"\nscheme = "A"\nproject = "p.xcodeproj"\n',
    STORE_TARGET + 'grace_days = "3"\n',
    STORE_TARGET.replace('paths = ["apps/mac/App", ', 'paths = [1, '),
])
def test_a_bad_store_target_is_an_error_row_not_a_silent_pass(tmp_path, monkeypatch, capsys, target):
    platform_toml(tmp_path)
    store_repo(tmp_path, target=target)
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)
    assert rc == 1 and cap.out.startswith("app-a  ") and "app-a/teyla.toml: `" in cap.out and "WARN" not in cap.out


def test_git_that_cannot_answer_is_silent(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = product(tmp_path, bundle="com.example.app", ios=None)             # `.git` is an empty directory
    with (d / "teyla.toml").open("a") as f:
        f.write(STORE_TARGET)
    lag_tool(monkeypatch, payload(mac()))
    rc, cap = go(capsys)
    assert rc == 0 and "WARN" not in cap.out

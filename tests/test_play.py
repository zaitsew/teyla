"""teyla.play — did the Android build reach a person.

The release tool is faked by monkeypatching subprocess.run; platform.toml and teyla.toml live
under tmp_path. Nothing here reaches the network or the real ~/.teyla."""
from __future__ import annotations

import datetime as dt
import json
import subprocess

import pytest

from teyla import cli, config, digest, net, platform, play, productize

TODAY = dt.date(2026, 10, 15)
PKG = "com.example.app"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(platform, "PLATFORM_PATH", home / ".teyla" / "platform.toml")
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "code_root", lambda: tmp_path / "repos")
    monkeypatch.delenv(config.SAFE_ENV, raising=False)
    monkeypatch.setattr(net, "_allow_once", False)
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: False)
    (tmp_path / "repos").mkdir()
    return home


def platform_toml(tmp_path, *, tool=True):
    t = tmp_path / "play-tool"
    t.write_text("#!/bin/sh\n")
    t.chmod(0o755)
    platform.PLATFORM_PATH.write_text("[android]\n" + (f'release_tool = "{t}"\n' if tool else ""))
    return t


def product(tmp_path, name="app-a", *, package=PKG, android='"play-internal"'):
    d = tmp_path / "repos" / name
    (d / ".git").mkdir(parents=True, exist_ok=True)
    body = f'[product]\nname = "{name}"\n'
    if android is not None:
        body += f"[productize.distribution]\nandroid = {android}\n"
    if package:
        body += f'[release]\nandroid_package = "{package}"\n'
    (d / "teyla.toml").write_text(body)
    return d


def rel(code, status="completed", name=None):
    return {"name": name or f"1.9.0 ({code})", "status": status, "version_codes": [code], "user_fraction": None}


def payload(internal=(), closed=(), beta=(), production=()):
    return {"package": PKG, "tracks": [
        {"track": "internal", "label": "internal testing", "releases": list(internal)},
        {"track": "alpha", "label": "closed testing", "releases": list(closed)},
        {"track": "beta", "label": "open testing", "releases": list(beta)},
        {"track": "production", "label": "production", "releases": list(production)}]}


def fake_tool(monkeypatch, out=None, *, rc=0, stderr="", raises=None, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw))
        if raises:
            raise raises
        text = out if isinstance(out, str) else json.dumps(out)
        return subprocess.CompletedProcess(cmd, rc, stdout=text, stderr=stderr)
    monkeypatch.setattr(play.subprocess, "run", run)


def go(capsys, *argv):
    capsys.readouterr()
    rc = cli.main(["play", *argv])
    return rc, capsys.readouterr()


# --- the report --------------------------------------------------------------------------------

def test_current_runs_the_tool_with_status_json(tmp_path, monkeypatch, capsys):
    tool = platform_toml(tmp_path)
    product(tmp_path)
    calls = []
    fake_tool(monkeypatch, payload(internal=[rel(14)]), calls=calls)
    rc, cap = go(capsys)
    assert rc == 0
    assert cap.out == 'app-a  internal code 14 "1.9.0 (14)" completed; no closed test — current\n'
    assert calls[0][0] == [str(tool), "status", "--package", PKG, "--json"]


def test_newest_code_wins_across_releases(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(internal=[rel(12), rel(15, "draft"), rel(13)]))
    rc, cap = go(capsys)
    assert rc == 1 and "code 15" in cap.out and "draft" in cap.out
    assert "testers cannot install it" in cap.out


def test_nothing_on_the_internal_track_is_none(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload())
    rc, cap = go(capsys)
    assert rc == 1 and "nothing on the internal track" in cap.out
    assert play.run()[0]["verdict"] == "none"


def test_halted_is_behind(tmp_path, monkeypatch):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(internal=[rel(14, "halted")]))
    assert play.run()[0]["verdict"] == "behind"


def test_the_closed_test_clock_starts_when_first_seen(tmp_path, monkeypatch):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(internal=[rel(14)], closed=[rel(14)]))
    first = play.run(today=TODAY)[0]
    assert first["closed"] == {"code": 14, "name": "1.9.0 (14)", "status": "completed", "days_seen": 0}
    assert "closed test code 14" in first["lines"][0] and "seen 0 of 14 days" in first["lines"][0]
    later = play.run(today=TODAY + dt.timedelta(days=9))[0]
    assert later["closed"]["days_seen"] == 9 and "seen 9 of 14 days" in later["lines"][0]
    assert later["verdict"] == "current"                 # a young closed test is reported, not a problem
    assert json.loads(play.seen_path().read_text()) == {PKG: TODAY.isoformat()}


def test_the_clock_restarts_when_the_closed_track_empties(tmp_path, monkeypatch):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(internal=[rel(14)], closed=[rel(14)]))
    play.run(today=TODAY)
    fake_tool(monkeypatch, payload(internal=[rel(14)], closed=[rel(14, "draft")]))
    play.run(today=TODAY + dt.timedelta(days=3))
    assert json.loads(play.seen_path().read_text()) == {}
    fake_tool(monkeypatch, payload(internal=[rel(14)], closed=[rel(14)]))
    assert play.run(today=TODAY + dt.timedelta(days=5))[0]["closed"]["days_seen"] == 0


def test_an_older_live_closed_release_keeps_the_clock_while_a_newer_one_is_a_draft(tmp_path, monkeypatch):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(internal=[rel(15)], closed=[rel(14)]))
    play.run(today=TODAY)
    fake_tool(monkeypatch, payload(internal=[rel(15)], closed=[rel(14), rel(15, "draft")]))
    row = play.run(today=TODAY + dt.timedelta(days=4))[0]
    assert row["closed"]["days_seen"] == 4 and row["closed"]["code"] == 15


def test_a_public_product_without_a_closed_test_is_behind(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, android='"play"')
    fake_tool(monkeypatch, payload(internal=[rel(14)]))
    rc, cap = go(capsys)
    assert rc == 1 and "no closed test (a personal account needs 14 days before production)" in cap.out
    fake_tool(monkeypatch, payload(internal=[rel(14)], closed=[rel(14, "draft")]))
    rc, cap = go(capsys)
    assert rc == 1 and "closed test draft: the 14-day clock is not running" in cap.out
    fake_tool(monkeypatch, payload(internal=[rel(14)], closed=[rel(14)]))
    assert go(capsys)[0] == 0


def test_play_internal_does_not_need_a_closed_test(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(internal=[rel(14)]))
    assert go(capsys)[0] == 0


# --- errors ------------------------------------------------------------------------------------

@pytest.mark.parametrize("kw", [dict(raises=subprocess.TimeoutExpired("x", 1)),
                                dict(raises=FileNotFoundError(2, "No such file or directory")),
                                dict(out="not json"), dict(out={"package": PKG})])
def test_tool_failures_are_one_line(tmp_path, monkeypatch, capsys, kw):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, **kw)
    rc, cap = go(capsys)
    assert rc == 1 and cap.err == "" and len(cap.out.strip().splitlines()) == 1


def test_nonzero_exit_names_the_tool_message(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, "", rc=2, stderr="error: service account has no access\n       run play check\n")
    rc, cap = go(capsys)
    assert rc == 1 and "the release tool exited 2: service account has no access" in cap.out and "run play check" not in cap.out


def test_missing_package_and_tool_config(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, package=None)                          # in scope by its distribution alone
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    rc, cap = go(capsys)
    assert rc == 1 and "no package: add `[release] android_package" in cap.out
    product(tmp_path)
    platform_toml(tmp_path, tool=False)
    rc, cap = go(capsys)
    assert rc == 1 and "no release tool: set `[android] release_tool`" in cap.out
    platform.PLATFORM_PATH.write_text('[android]\nrelease_tool = "/nonexistent/play"\n')
    rc, cap = go(capsys)
    assert rc == 1 and "is not at /nonexistent/play" in cap.out


# --- scope and arguments -----------------------------------------------------------------------

def test_scope(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, "a", android='"play-internal"', package=None)
    product(tmp_path, "b", android='"pwa"', package=None)
    product(tmp_path, "c", android=None, package="com.example.c")
    product(tmp_path, "d", android='"apk-sideload"', package=None)
    fake_tool(monkeypatch, payload(internal=[rel(1)]))
    assert sorted(r["product"] for r in play.run()) == ["a", "c"]


def test_no_product_in_scope_exits_zero(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path, android='"pwa"', package=None)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    rc, cap = go(capsys)
    assert rc == 0 and "no product ships through Google Play" in cap.out


def test_path_argument_and_unknown_path(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    d = product(tmp_path)
    product(tmp_path, "app-b", package="com.example.b")
    fake_tool(monkeypatch, payload(internal=[rel(1)]))
    rc, cap = go(capsys, str(d))
    assert rc == 0 and cap.out.count("\n") == 1 and cap.out.startswith("app-a")
    rc, cap = go(capsys, str(tmp_path / "nowhere"))
    assert rc == 2 and "no teyla.toml" in cap.err


def test_a_named_teyla_toml_that_does_not_parse_is_an_error(tmp_path, monkeypatch):
    platform_toml(tmp_path)
    d = product(tmp_path)
    (d / "teyla.toml").write_text("[product\nname = ")
    rows = play.run([str(d)])
    assert [r["verdict"] for r in rows] == ["error"] and "does not parse" in rows[0]["error"]
    assert play.run() == []                                   # the sweep leaves it to `teyla productize`


def test_json_shape(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(internal=[rel(14, "draft")]))
    rc, cap = go(capsys, "--json")
    out = json.loads(cap.out)
    assert rc == 1 and out[0]["product"] == "app-a" and out[0]["package"] == PKG
    assert out[0]["verdict"] == "behind" and out[0]["internal"]["status"] == "draft" and "lines" not in out[0]


def test_safe_mode_refuses_without_allow_network(tmp_path, monkeypatch, capsys):
    platform_toml(tmp_path)
    product(tmp_path)
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run in safe mode"))
    rc, cap = go(capsys)
    assert rc == 1 and "safe mode is on" in cap.err and cap.out == ""
    fake_tool(monkeypatch, payload(internal=[rel(14)]))
    rc, cap = go(capsys, "--allow-network")
    assert rc == 0 and "current" in cap.out


def test_templates_carry_the_new_keys():
    import teyla
    t = teyla.templates_dir()
    assert "release_tool" in (t / "platform" / "platform.toml").read_text().split("[android]")[1]
    assert "android_package" in (t / "repo" / "teyla.toml").read_text()


# --- --quiet: the problems file the banner and the digest read ---------------------------------

@pytest.fixture
def problems(_env):
    return _env / ".teyla" / "play.problems"


def test_quiet_writes_one_line_per_product_that_is_not_current(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, payload(internal=[rel(14, "draft")]))
    rc, cap = go(capsys, "--quiet")
    assert rc == 1 and cap.out == "" and cap.err == ""
    assert problems.read_text() == ("play|app-a|behind\tapp-a Play: internal draft: "
                                    "testers cannot install it\n")
    fake_tool(monkeypatch, payload(internal=[rel(14)]))
    rc, cap = go(capsys, "--quiet")
    assert rc == 0 and cap.out == "" and not problems.exists()


def test_quiet_error_and_none_rows(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    fake_tool(monkeypatch, "", rc=2, stderr="auth failed\n")
    go(capsys, "--quiet")
    key, text = problems.read_text().rstrip("\n").split("\t")
    assert key == "play|app-a|error" and text == "app-a Play: the release tool exited 2: auth failed"
    fake_tool(monkeypatch, payload())
    go(capsys, "--quiet")
    assert problems.read_text() == "play|app-a|none\tapp-a Play: no internal release\n"


def test_quiet_in_safe_mode_does_nothing_and_exits_zero(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    product(tmp_path)
    problems.write_text("play|app-a|behind\told answer\n")
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    rc, cap = go(capsys, "--quiet")
    assert rc == 0 and cap.out == "" and cap.err == ""
    assert problems.read_text().startswith("play|app-a|behind")


def test_quiet_with_no_product_in_scope_removes_the_file(tmp_path, monkeypatch, capsys, problems):
    platform_toml(tmp_path)
    problems.write_text("play|x|behind\told\n")
    fake_tool(monkeypatch, raises=AssertionError("the tool must not run"))
    rc, cap = go(capsys, "--quiet")
    assert rc == 0 and cap.out == "" and not problems.exists()


def test_the_banner_and_the_digest_read_the_play_problems(tmp_path, problems):
    problems.write_text("play|app-a|behind\tapp-a Play: internal draft: testers cannot install it\n")
    assert digest.play_items() == [("play|app-a|behind", "app-a Play: internal draft: testers cannot install it")]
    path = digest.write_banner_items(checks=[], today=dt.date(2026, 10, 15))
    assert "play|app-a|behind" in [ln.split("\t")[0] for ln in path.read_text().splitlines()]
    cands = {c["id"]: c for c in digest.problem_file_candidates()}
    assert cands["play"]["text"].startswith("1 Google Play product not current: app-a Play: internal draft")
    assert cands["play"]["step"] == "teyla play" and cands["play"]["cmd"] is True


def test_the_daily_routine_runs_it_after_testflight_and_before_doctor():
    from teyla import routine_install
    t = routine_install.DAILY_WRAPPER_TEMPLATE
    assert "teyla play --quiet || true" in t
    assert t.index("teyla testflight --quiet") < t.index("teyla play --quiet") < t.index("teyla doctor --quiet")


def test_platform_warns_while_the_android_release_tool_is_unset(tmp_path):
    ks = tmp_path / "upload.jks"
    ks.write_text("x")
    cfg = {"android": {"play_console": True, "keystore": str(ks)}}
    r = platform._check_android(cfg)
    assert r["state"] == platform.WARN and "release_tool" in r["todo"]
    cfg["android"]["release_tool"] = str(tmp_path / "absent")
    assert platform._check_android(cfg)["state"] == platform.WARN
    tool = platform_toml(tmp_path)
    cfg["android"]["release_tool"] = str(tool)
    assert platform._check_android(cfg)["state"] == platform.OK
    tool.chmod(0o644)
    assert platform._check_android(cfg)["state"] == platform.WARN

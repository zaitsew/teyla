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


def fake_tool(monkeypatch, out=None, *, rc=0, stderr="", raises=None, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw))
        if raises:
            raise raises
        text = out if isinstance(out, str) else json.dumps(out)
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
    assert sorted(c[0][4] for c in seen) == ["com.example.mac", "com.example.shipped"]
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

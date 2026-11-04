"""The Mac side of the shared review channel (src/teyla/review_channel.py). `ssh` and `rsync` are replaced by
small local programs on PATH that run the command against a folder in a tmp dir, so the real command strings
go through a real shell and an odd folder name has the chance to do harm."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import stat
import sys
import textwrap

import pytest

from teyla import cli, review, review_channel, routine_install as ri, schedules

ROOT = pathlib.Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\n" + b"1" * 40
COMMENT = "A tester wrote this private sentence."
ID1, ID2, ID3 = ("3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11", "8a1d2e33-0c4f-4b6a-8e7d-5f9a0b1c2d3e",
                 "c2b7e9a4-1d3f-4a85-b6c0-7e8f9a0b1c2d")

SSH = '''#!{py}
import json, os, subprocess, sys
a = sys.argv[1:]
i = 0
while i < len(a) and a[i] == "-o":
    i += 2
assert a[i] == "--", a
target, cmd = a[i + 1], " ".join(a[i + 2:])
open(os.environ["FAKE_LOG"], "a").write(json.dumps({{"tool": "ssh", "target": target, "cmd": cmd}}) + "\\n")
if os.environ.get("FAKE_FAIL") == "ssh":
    sys.exit(255)
sys.exit(subprocess.run(["sh", "-c", cmd]).returncode)
'''

RSYNC = '''#!{py}
import json, os, shlex, shutil, sys
a, pos, i = sys.argv[1:], [], 0
while i < len(a):
    if a[i] == "-e":
        i += 2
    elif a[i].startswith("-"):
        i += 1
    else:
        pos.append(a[i]); i += 1
src, dst = pos
host, path = src.split(":", 1)
path = shlex.split(path)[0]
open(os.environ["FAKE_LOG"], "a").write(json.dumps({{"tool": "rsync", "target": host, "path": path}}) + "\\n")
if os.environ.get("FAKE_FAIL") == "rsync":
    sys.exit(23)
for here, dirs, files in os.walk(path):
    dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(here, d))]
    rel = os.path.relpath(here, path)
    os.makedirs(os.path.join(dst, rel), exist_ok=True)
    for f in files:
        p = os.path.join(here, f)
        if not os.path.islink(p):
            shutil.copyfile(p, os.path.join(dst, rel, f))
'''


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A fake server folder, fake ssh and rsync, a config file, and a HOME for the key files."""
    server = tmp_path / "server"
    (server / "ready").mkdir(parents=True)
    (server / "keys").mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for name, body in (("ssh", SSH), ("rsync", RSYNC)):
        f = bin_ / name
        f.write_text(body.format(py=sys.executable))
        f.chmod(0o755)
    log = tmp_path / "calls.log"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.delenv("FAKE_FAIL", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    notes: list[int] = []
    monkeypatch.setattr(review_channel, "notify", lambda n: notes.append(n))
    cfg = review_channel.config_path()
    cfg.write_text(f'ssh = "tester@example.com"\nroot = "{server}"\n')

    class W:
        pass
    w = W()
    w.tmp, w.server, w.log, w.home, w.notes, w.cfg = tmp_path, server, log, home, notes, cfg
    w.calls = lambda: [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return w


def put(w, slug, cid, product=None, png=PNG, sha=None, comment=COMMENT):
    d = w.server / "ready" / slug / cid
    d.mkdir(parents=True)
    body = {"v": 1, "id": cid, "created": "2026-11-04T10:00:00Z",
            "app": {"bundle_id": f"com.example.{slug}", "product": product or slug, "name": "Sample", "version": "1.0", "build": "3"},
            "screen": "sample.list", "comment": {"text": comment, "input": "text", "language": "en"},
            "screenshot": {"file": "capture.png", "width": 10, "height": 10, "scale": 1,
                           "sha256": sha or hashlib.sha256(png).hexdigest()}}
    (d / "capture.json").write_text(json.dumps(body))
    (d / "capture.png").write_bytes(png)
    return d


def pull(capsys, *extra):
    code = cli.main(["review", "pull", "--channel", *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


def inbox():
    c = review.connect()
    try:
        return {r["id"]: dict(r) for r in c.execute("SELECT * FROM captures")}
    finally:
        c.close()


# --- config -------------------------------------------------------------------------------------

def test_an_absent_config_says_what_is_missing_and_exits_2(world, capsys):
    world.cfg.unlink()
    code, out, err = pull(capsys)
    assert code == 2 and "review-channel.toml" in err and 'ssh  = "user@host"' in err and 'root = "/path/to/data"' in err
    assert world.calls() == []


@pytest.mark.parametrize("text", [
    'ssh = "-oProxyCommand=evil"\nroot = "/srv/x"\n',
    'ssh = "a@b; touch /tmp/x"\nroot = "/srv/x"\n',
    'ssh = "a@b"\nroot = "/srv/x y"\n',
    'ssh = "a@b"\nroot = "/srv/x;rm"\n',
    'ssh = "a@b"\nroot = "/srv/../etc"\n',
    'ssh = "a@b"\nroot = "relative"\n',
    'ssh = "a@b"\n',
])
def test_a_config_that_could_reach_a_shell_is_refused(world, capsys, text):
    world.cfg.write_text(text)
    code, _, err = pull(capsys)
    assert code == 2 and err
    assert world.calls() == []


# --- the pull -----------------------------------------------------------------------------------

def test_a_pull_imports_marks_the_source_and_deletes_after(world, capsys, monkeypatch):
    a, b = put(world, "alpha", ID1), put(world, "beta", ID2)
    seen = {}

    def note(n):
        world.notes.append(n)
        seen["still_on_server"] = a.exists() and b.exists()
        seen["in_inbox"] = sorted(inbox())
    monkeypatch.setattr(review_channel, "notify", note)
    code, out, err = pull(capsys, "--json")
    rep = json.loads(out)
    assert code == 0 and rep["added"] == 2 and sorted(rep["imported"]) == sorted([ID1, ID2]) and rep["deleted"] == 2
    assert seen == {"still_on_server": True, "in_inbox": sorted([ID1, ID2])}      # the notice comes before the deletes
    assert world.notes == [2]
    assert not a.exists() and not b.exists()
    assert {r["source"] for r in inbox().values()} == {"channel"}
    assert COMMENT not in out + err


def test_review_list_shows_that_the_sender_is_unverified(world, capsys):
    put(world, "alpha", ID1)
    pull(capsys)
    assert cli.main(["review", "list"]) == 0
    listing = capsys.readouterr().out
    assert "unverified" in listing and ID1[:8] in listing


def test_the_comment_is_never_printed(world, capsys):
    put(world, "alpha", ID1)
    for flags in ((), ("--json",)):
        code, out, err = pull(capsys, *flags)
        assert COMMENT not in out + err
    put(world, "alpha", ID2, png=PNG + b"x", sha="0" * 64)     # a refused one: still no comment in the report
    code, out, err = pull(capsys)
    assert code == 1 and COMMENT not in out + err


def test_a_refused_capture_stays_on_the_server_and_the_run_exits_1(world, capsys):
    good = put(world, "alpha", ID1)
    bad = put(world, "alpha", ID2, sha="0" * 64)
    mismatch = put(world, "beta", ID3, product="alpha")
    code, out, err = pull(capsys, "--json")
    rep = json.loads(out)
    assert code == 1 and rep["imported"] == [ID1] and len(rep["skipped"]) == 2
    assert not good.exists() and bad.exists() and mismatch.exists()
    assert set(inbox()) == {ID1}


def test_a_failed_rsync_deletes_nothing(world, capsys, monkeypatch):
    d = put(world, "alpha", ID1)
    monkeypatch.setenv("FAKE_FAIL", "rsync")
    code, out, err = pull(capsys, "--json")
    assert code == 1 and json.loads(out)["error"] is True
    assert d.exists() and inbox() == {} and world.notes == []
    assert not any("rm -rf" in c.get("cmd", "") for c in world.calls())


def test_a_failed_delete_keeps_the_capture_and_the_next_pass_clears_it(world, capsys, monkeypatch):
    d = put(world, "alpha", ID1)
    real_delete = review_channel.Remote.delete
    monkeypatch.setattr(review_channel.Remote, "delete", lambda self, items: list(items))
    code, out, err = pull(capsys, "--json")
    assert code == 1 and d.exists() and set(inbox()) == {ID1} and world.notes == [1]
    monkeypatch.setattr(review_channel.Remote, "delete", real_delete)
    code, out, err = pull(capsys, "--json")
    rep = json.loads(out)
    assert code == 0 and rep["added"] == 0 and rep["known"] == 1 and rep["deleted"] == 1 and not d.exists()
    assert world.notes == [1]                                    # a known capture raises no second notice


def test_odd_folder_names_neither_import_nor_run_nor_delete(world, capsys):
    evil = ["x; touch PWNED1", "$(touch PWNED2)", "`touch PWNED3`", "a b", "--help", "ALPHA", "x'y"]
    kept = []
    for n in evil:                                               # as product folders
        d = world.server / "ready" / n / ID1
        d.mkdir(parents=True)
        (d / "capture.json").write_text("{}")
        kept.append(world.server / "ready" / n)
    for n in evil:                                               # as capture folders under a good product
        d = world.server / "ready" / "alpha" / n
        d.mkdir(parents=True)
        (d / "capture.json").write_text("{}")
        kept.append(d)
    link = world.server / "ready" / "alpha" / ID2
    link.symlink_to(world.tmp)
    kept.append(link)
    code, out, err = pull(capsys, "--json")
    assert code == 1 and json.loads(out)["imported"] == []
    assert all(k.exists() or k.is_symlink() for k in kept)
    assert not list(world.tmp.glob("PWNED*")) and not list(world.server.rglob("PWNED*"))
    assert inbox() == {}
    cmds = [c["cmd"] for c in world.calls() if c["tool"] == "ssh"]
    assert cmds == []                                            # nothing imported, so no delete was built


def test_a_delete_names_only_the_folders_the_inbox_holds(world, capsys):
    put(world, "alpha", ID1)
    refused = put(world, "alpha", ID2, sha="0" * 64)
    pull(capsys)
    cmds = [c["cmd"] for c in world.calls() if c["tool"] == "ssh"]
    assert len(cmds) == 1 and cmds[0].startswith("rm -rf -- ")
    assert f"/ready/alpha/{ID1}" in cmds[0] and ID2 not in cmds[0]
    assert refused.exists()


def test_the_remote_command_cannot_be_built_from_an_odd_name():
    r = review_channel.Remote("a@b", "/srv/x")
    for slug, cid in (("a b", ID1), ("alpha", "../x"), ("alpha", ID1.upper()), ("-r", ID1), ("alpha/..", ID1)):
        with pytest.raises(ValueError):
            r.ready_path(slug, cid)
    assert r.ready_path("alpha", ID1) == f"/srv/x/ready/alpha/{ID1}"


def test_rsync_and_ssh_get_the_configured_host_and_root(world, capsys):
    put(world, "alpha", ID1)
    pull(capsys)
    calls = world.calls()
    assert calls[0] == {"tool": "rsync", "target": "tester@example.com", "path": f"{world.server}/ready/"}
    assert all(c["target"] == "tester@example.com" for c in calls)


def test_a_second_pass_with_nothing_new_is_quiet(world, capsys):
    code, out, err = pull(capsys, "--json")
    assert code == 0 and json.loads(out)["added"] == 0 and world.notes == []


def test_the_notification_script_carries_only_a_count():
    assert "1 new tester capture:" in review_channel.notice_script(1)
    assert "3 new tester captures" in review_channel.notice_script(3)


# --- keys ---------------------------------------------------------------------------------------

def _server_module():
    spec = importlib.util.spec_from_file_location("rc_server_for_keys", ROOT / "packages" / "review-channel" / "server.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_key_add_stores_the_secret_privately_and_the_hash_on_the_server(world, capsys):
    keys = world.server / "keys" / "keys.txt"
    keys.write_text(f"{'a' * 64} beta\n")
    assert cli.main(["review", "channel", "key", "add", "alpha"]) == 0
    out = capsys.readouterr()
    path = world.home / ".config" / "teyla" / "review-channel" / "alpha.key"
    assert out.out.strip() == str(path)
    secret = path.read_text().strip()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    for text in (out.out, out.err, world.log.read_text()):
        assert secret not in text
    lines = keys.read_text().splitlines()
    assert f"{'a' * 64} beta" in lines
    assert f"{hashlib.sha256(secret.encode()).hexdigest()} alpha" in lines
    assert _server_module().Keys(str(keys)).lookup(hashlib.sha256(secret.encode()).hexdigest()) == "alpha"
    assert not list((world.server / "keys").glob(".keys.*"))


def test_key_add_works_with_no_keys_file_yet(world, capsys):
    assert cli.main(["review", "channel", "key", "add", "alpha"]) == 0
    assert len((world.server / "keys" / "keys.txt").read_text().splitlines()) == 1


def test_key_add_twice_needs_rotate_and_rotate_replaces_the_line(world, capsys):
    cli.main(["review", "channel", "key", "add", "alpha"])
    path = world.home / ".config" / "teyla" / "review-channel" / "alpha.key"
    first = path.read_text()
    capsys.readouterr()
    assert cli.main(["review", "channel", "key", "add", "alpha"]) == 1
    assert path.read_text() == first
    assert cli.main(["review", "channel", "key", "add", "alpha", "--rotate"]) == 0
    second = path.read_text()
    assert second != first
    lines = (world.server / "keys" / "keys.txt").read_text().splitlines()
    assert [ln for ln in lines if ln.endswith(" alpha")] == [f"{hashlib.sha256(second.strip().encode()).hexdigest()} alpha"]


def test_key_revoke_removes_the_line_and_the_local_secret(world, capsys):
    cli.main(["review", "channel", "key", "add", "alpha"])
    cli.main(["review", "channel", "key", "add", "beta"])
    capsys.readouterr()
    assert cli.main(["review", "channel", "key", "revoke", "alpha"]) == 0
    keys = (world.server / "keys" / "keys.txt").read_text().splitlines()
    assert len(keys) == 1 and keys[0].endswith(" beta")
    assert not (world.home / ".config" / "teyla" / "review-channel" / "alpha.key").exists()
    assert (world.home / ".config" / "teyla" / "review-channel" / "beta.key").exists()


def test_a_server_that_refuses_the_key_leaves_nothing_behind(world, capsys, monkeypatch):
    monkeypatch.setenv("FAKE_FAIL", "ssh")
    assert cli.main(["review", "channel", "key", "add", "alpha"]) == 1
    assert not (world.home / ".config" / "teyla" / "review-channel" / "alpha.key").exists()


def test_key_path_prints_the_path_and_never_the_secret(world, capsys):
    assert cli.main(["review", "channel", "key", "path", "alpha"]) == 1
    capsys.readouterr()
    cli.main(["review", "channel", "key", "add", "alpha"])
    capsys.readouterr()
    assert cli.main(["review", "channel", "key", "path", "alpha"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.endswith("/review-channel/alpha.key") and len(out) < 200


@pytest.mark.parametrize("product", ["Alpha", "a b", "../x", "x;y", ""])
def test_a_product_that_is_not_a_slug_is_refused(world, capsys, product):
    for verb in ("add", "revoke", "path"):
        assert cli.main(["review", "channel", "key", verb, product]) == 2
    assert world.calls() == []


# --- the hourly agent ---------------------------------------------------------------------------

def test_install_writes_an_hourly_agent_that_teyla_schedules_lists(world):
    lines = review_channel.agent_install(load=lambda plist, label: f"loaded {label}")
    plist, wrapper = review_channel.plist_path(), review_channel.wrapper_path()
    assert plist.is_file() and wrapper.is_file() and stat.S_IMODE(wrapper.stat().st_mode) == 0o755
    import plistlib
    data = plistlib.loads(plist.read_bytes())
    assert data["Label"] == review_channel.LABEL and data["StartInterval"] == 3600 and data["RunAtLoad"] is True
    assert data["ProgramArguments"] == ["/bin/bash", str(wrapper)]
    assert "review pull --channel" in wrapper.read_text() and review_channel.LABEL in wrapper.read_text()
    assert any("loaded" in ln for ln in lines) or sys.platform != "darwin"
    rows = schedules.read_launchd(plist.parent, listing="", disabled=set())
    assert [r for r in rows if r["id"] == f"launchd:{review_channel.LABEL}" and r["cadence"]]
    out = review_channel.agent_uninstall(unload=lambda plist, label: f"unloaded {label}")
    assert not plist.exists() and not wrapper.exists() and out


def test_install_without_a_config_refuses_and_exits_2(world, capsys):
    world.cfg.unlink()
    assert cli.main(["review", "channel", "install"]) == 2
    assert "review-channel.toml" in capsys.readouterr().err
    assert not review_channel.plist_path().exists()


def test_uninstall_when_nothing_is_installed_is_quiet(world, capsys):
    assert cli.main(["review", "channel", "uninstall"]) == 0
    assert "not installed" in capsys.readouterr().out


def test_an_unknown_channel_command_prints_usage_and_exits_2(world, capsys):
    assert cli.main(["review", "channel", "frobnicate"]) == 2
    assert "key add" in capsys.readouterr().err

"""The Mac side of the shared review channel (src/teyla/review_channel.py). `ssh` and `rsync` are replaced by
small local programs on PATH that run the command against a folder in a tmp dir, so the real command strings
go through a real shell and an odd folder name has the chance to do harm."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import sqlite3
import stat
import sys
import textwrap
import time

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


def test_a_date_that_falls_off_the_calendar_does_not_stop_the_pull():
    assert review._created("0001-01-01T00:00:00+01:00") is None


def test_a_rotation_the_server_refuses_keeps_the_working_key(world, monkeypatch):
    rc = review_channel
    path = rc.key_path("alpha")
    rc._write_secret(path, "old-secret")

    class Refused:
        returncode = 1

    monkeypatch.setattr(rc.Remote, "keys_edit", lambda self, slug, line: Refused())
    with pytest.raises(rc.ChannelError):
        rc.key_add(rc.Remote("deploy@example.com", "/data"), "alpha", rotate=True)
    assert path.read_text().strip() == "old-secret"
    assert not path.with_name(path.name + ".new").exists()


def test_a_second_key_change_for_one_product_is_refused(world, monkeypatch):
    rc = review_channel
    path = rc.key_path("alpha")
    rc._write_secret(path, "old-secret")
    called = []
    monkeypatch.setattr(rc.Remote, "keys_edit", lambda self, slug, line: called.append(line))
    with rc._key_lock(path):
        with pytest.raises(rc.ChannelError, match="another key change"):
            rc.key_add(rc.Remote("deploy@example.com", "/data"), "alpha", rotate=True)
        with pytest.raises(rc.ChannelError, match="another key change"):
            rc.key_revoke(rc.Remote("deploy@example.com", "/data"), "alpha")
    assert called == []
    assert path.read_text().strip() == "old-secret"


def _aged(conn, cid, **fields):
    for k, v in fields.items():
        conn.execute(f"UPDATE captures SET {k} = ? WHERE id = ?", (v, cid))


def _one_capture(world, capsys, n=1):
    cid = f"{n:08x}-0000-4000-8000-000000000000"
    put(world, "alpha", cid)
    assert pull(capsys)[0] == 0
    conn = review.connect()
    return conn, cid, pathlib.Path(conn.execute("SELECT dir FROM captures WHERE id = ?", (cid,)).fetchone()["dir"])


@pytest.mark.parametrize("status,field,days,gone", [
    ("new", "imported_at", 91, True), ("new", "imported_at", 89, False),
    ("triaged", "imported_at", 91, True),
    ("open", "imported_at", 400, False),
    ("rejected", "closed_at", 31, True), ("rejected", "closed_at", 29, False),
    ("done", "closed_at", 31, True),
])
def test_retention_keeps_the_promise_in_the_notice(world, capsys, status, field, days, gone):
    conn, cid, folder = _one_capture(world, capsys)
    now = time.time()
    _aged(conn, cid, status=status)
    _aged(conn, cid, **{field: review._iso(now - days * 86400)})
    rep = review.prune_channel(conn, now)
    assert rep["deleted"] == (1 if gone else 0)
    assert folder.exists() is not gone
    assert (conn.execute("SELECT 1 FROM captures WHERE id = ?", (cid,)).fetchone() is None) is gone


def test_closing_starts_the_clock_and_reopening_stops_it(world, capsys):
    conn, cid, _ = _one_capture(world, capsys)
    conn.execute("UPDATE captures SET status = 'done' WHERE id = ?", (cid,))
    assert conn.execute("SELECT closed_at FROM captures WHERE id = ?", (cid,)).fetchone()[0]
    conn.execute("UPDATE captures SET status = 'triaged' WHERE id = ?", (cid,))
    assert conn.execute("SELECT closed_at FROM captures WHERE id = ?", (cid,)).fetchone()[0] is None


def test_a_capture_closed_before_the_clock_existed_starts_it_now(world, capsys):
    conn, cid, folder = _one_capture(world, capsys)
    conn.execute("UPDATE captures SET status = 'rejected' WHERE id = ?", (cid,))
    conn.execute("UPDATE captures SET closed_at = NULL WHERE id = ?", (cid,))
    now = time.time()
    assert review.prune_channel(conn, now)["deleted"] == 0
    assert folder.exists()
    assert review.prune_channel(conn, now + 31 * 86400)["deleted"] == 1


def test_a_held_capture_and_another_source_are_not_pruned(world, capsys):
    conn, cid, folder = _one_capture(world, capsys)
    now = time.time()
    _aged(conn, cid, imported_at=review._iso(now - 200 * 86400), lease_owner="lane", lease_expires=now + 60)
    assert review.prune_channel(conn, now)["deleted"] == 0
    _aged(conn, cid, lease_owner=None, lease_expires=None, source="relay")
    assert review.prune_channel(conn, now)["deleted"] == 0
    assert folder.exists()


def test_a_row_pointing_outside_the_inbox_deletes_nothing(world, capsys, tmp_path):
    conn, cid, _ = _one_capture(world, capsys)
    outside = tmp_path / "precious"
    outside.mkdir()
    now = time.time()
    _aged(conn, cid, dir=str(outside), imported_at=review._iso(now - 200 * 86400))
    rep = review.prune_channel(conn, now)
    assert rep == {"deleted": 0, "kept": [cid]}
    assert outside.exists()


def test_an_old_inbox_gains_the_column(tmp_path):
    db = tmp_path / "queue.db"
    old = sqlite3.connect(db)
    old.executescript(review.SCHEMA.replace("lease_expires REAL,\n  closed_at     TEXT,\n  opened_at     TEXT", "lease_expires REAL"))
    old.close()
    conn = review.connect(db)
    assert {"closed_at", "opened_at"} <= {r["name"] for r in conn.execute("PRAGMA table_info(captures)")}


def test_a_capture_opened_once_is_not_never_opened(world, capsys):
    conn, cid, folder = _one_capture(world, capsys)
    now = time.time()
    conn.execute("UPDATE captures SET status = 'open' WHERE id = ?", (cid,))
    conn.execute("UPDATE captures SET status = 'new' WHERE id = ?", (cid,))
    _aged(conn, cid, imported_at=review._iso(now - 200 * 86400))
    assert review.prune_channel(conn, now)["deleted"] == 0
    assert folder.exists()


def test_a_folder_that_cannot_move_keeps_the_row_for_the_next_pass(world, capsys, monkeypatch):
    conn, cid, folder = _one_capture(world, capsys)
    now = time.time()
    _aged(conn, cid, imported_at=review._iso(now - 200 * 86400))

    def refuse(*a):
        raise PermissionError("no")

    with monkeypatch.context() as m:
        m.setattr(review.os, "rename", refuse)
        assert review.prune_channel(conn, now) == {"deleted": 0, "kept": [cid]}
    assert folder.exists()
    assert review.prune_channel(conn, now)["deleted"] == 1
    assert not folder.exists()


def test_a_pass_finishes_the_trash_a_dead_pass_left(world, capsys):
    conn, _, _ = _one_capture(world, capsys)
    left = review.captures_root() / ".retention" / "dead-pass"
    left.mkdir(parents=True)
    review.prune_channel(conn)
    assert not left.exists()


def test_a_missing_folder_does_not_keep_the_row_for_ever(world, capsys):
    conn, cid, folder = _one_capture(world, capsys)
    now = time.time()
    _aged(conn, cid, imported_at=review._iso(now - 200 * 86400))
    shutil.rmtree(folder)
    assert review.prune_channel(conn, now)["deleted"] == 1


def test_what_an_old_inbox_already_held_counts_as_opened(tmp_path):
    db = tmp_path / "queue.db"
    old = sqlite3.connect(db)
    old.executescript(review.SCHEMA.replace("lease_expires REAL,\n  closed_at     TEXT,\n  opened_at     TEXT", "lease_expires REAL"))
    old.execute("INSERT INTO captures (id, product, source, created_at, imported_at, data, dir) "
                "VALUES ('a', 'p', 'channel', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '{}', '/x')")
    old.commit()
    old.close()
    conn = review.connect(db)
    assert conn.execute("SELECT opened_at FROM captures WHERE id = 'a'").fetchone()[0] == "2026-01-01T00:00:00Z"


def test_a_pass_that_died_before_its_commit_gives_the_folder_back(world, capsys):
    conn, cid, folder = _one_capture(world, capsys)
    now = time.time()
    _aged(conn, cid, imported_at=review._iso(now - 200 * 86400))
    conn.execute("UPDATE captures SET lease_owner = 'lane', lease_expires = ? WHERE id = ?", (now + 60, cid))
    trash = review.captures_root() / ".retention"
    trash.mkdir()
    folder.rename(trash / cid)
    assert review.prune_channel(conn, now) == {"deleted": 0, "kept": []}
    assert folder.exists() and not (trash / cid).exists()
    assert conn.execute("SELECT lease_owner FROM captures WHERE id = ?", (cid,)).fetchone()[0] == "lane"


def test_a_restore_with_nowhere_to_go_deletes_nothing(world, capsys):
    conn, cid, folder = _one_capture(world, capsys)
    trash = review.captures_root() / ".retention"
    (trash / cid).mkdir(parents=True)
    (trash / cid / "kept.txt").write_text("x")
    assert review.prune_channel(conn)["kept"] == [cid]
    assert folder.exists() and (trash / cid / "kept.txt").exists()


def test_the_new_columns_and_the_backfill_land_together(tmp_path):
    db = tmp_path / "queue.db"
    old = sqlite3.connect(db)
    old.executescript(review.SCHEMA.replace("lease_expires REAL,\n  closed_at     TEXT,\n  opened_at     TEXT", "lease_expires REAL"))
    old.execute("INSERT INTO captures (id, product, source, created_at, imported_at, data, dir) "
                "VALUES ('a', 'p', 'channel', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', '{}', '/x')")
    old.execute("CREATE TRIGGER boom BEFORE UPDATE ON captures BEGIN SELECT RAISE(ABORT, 'died here'); END")
    old.commit()
    with pytest.raises(sqlite3.IntegrityError):
        review.connect(db)
    assert "opened_at" not in {r[1] for r in old.execute("PRAGMA table_info(captures)")}
    old.execute("DROP TRIGGER boom")
    old.commit()
    old.close()
    assert review.connect(db).execute("SELECT opened_at FROM captures").fetchone()[0] == "2026-01-01T00:00:00Z"


def test_a_lease_taken_after_the_list_was_read_wins(world, capsys):
    conn, cid, folder = _one_capture(world, capsys)
    now = time.time()
    _aged(conn, cid, imported_at=review._iso(now - 200 * 86400))

    class Racing:
        """The other process takes its lease between the list and the claim."""
        def __init__(self, inner):
            self.inner = inner

        def execute(self, sql, *a):
            if sql == "BEGIN IMMEDIATE":
                self.inner.execute("UPDATE captures SET lease_owner = 'lane', lease_expires = ? WHERE id = ?",
                                   (now + 60, cid))
            return self.inner.execute(sql, *a)

    assert review.prune_channel(Racing(conn), now)["deleted"] == 0
    assert folder.exists()
    assert conn.execute("SELECT lease_owner FROM captures WHERE id = ?", (cid,)).fetchone()[0] == "lane"


def test_safe_mode_still_removes_what_is_past_retention(world, capsys, monkeypatch):
    conn, cid, folder = _one_capture(world, capsys)
    _aged(conn, cid, imported_at=review._iso(time.time() - 200 * 86400))
    monkeypatch.setattr(review_channel.net, "gate", lambda *a, **k: False)
    assert pull(capsys)[0] == 1
    assert not folder.exists()


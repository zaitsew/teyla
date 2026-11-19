"""`teyla storage offload`: the move to an external drive, its refusals, its rollback and its recovery.

A drive is a folder under tmp_path whose device number is faked (`volumes._dev`); the copy, the rename and the
link are real, on the real tmp filesystem. Nothing touches a real drive or the real HOME. Examples use `External`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil

import pytest

from teyla import config, storage, storage_offload as so, volumes

DERIVED = "Library/Developer/Xcode/DerivedData"
GRADLE = ".gradle/caches"
SIMS = "Library/Developer/CoreSimulator/Devices"


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    drive = (tmp_path / "External").resolve()
    drive.mkdir()
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.toml")

    def fake_dev(p):
        real = os.path.realpath(p)
        if not os.path.exists(real):
            raise FileNotFoundError(p)
        return 2 if real == str(drive) or real.startswith(str(drive) + os.sep) else 1

    monkeypatch.setattr(volumes, "_dev", fake_dev)
    monkeypatch.setattr(so, "busy", lambda key: "")
    monkeypatch.setattr(so, "_ownership_disabled", lambda v: False)
    monkeypatch.setattr(so, "_sim_count", lambda: 3)
    return type("W", (), {"home": home, "drive": drive, "tmp": tmp_path})


def tree(root: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return root


def derived(w, files=None) -> pathlib.Path:
    return tree(w.home / DERIVED, files or {"App-abc/Build/a.o": "aaa", "App-abc/info.plist": "plist", "ModuleCache/m": "m" * 500})


def args(w, **kw):
    base = dict(to=str(w.drive), apply=False, only="", with_app_data=False, keep=False, undo=None, recover=False,
                finalize=False, delete_drive_copy=False)
    return argparse.Namespace(**{**base, **kw})


def snapshot(root: pathlib.Path) -> dict:
    return {str(p.relative_to(root)): (p.read_text() if p.is_file() else None) for p in sorted(root.rglob("*"))}


def run(w, capsys, **kw) -> tuple[int, str]:
    rc = so.cmd_offload(args(w, **kw), {})
    return rc, capsys.readouterr().out


# --- dry run -------------------------------------------------------------------------------------------------

def test_a_dry_run_lists_and_changes_nothing(world, capsys):
    src = derived(world)
    before = snapshot(src)
    rc, out = run(world, capsys)
    assert rc == 0 and "dry run" in out and "Xcode DerivedData" in out and "to move" in out
    assert "not present" in out                                       # the paths this machine does not have
    assert not src.is_symlink() and snapshot(src) == before
    assert not (world.drive / "teyla").exists() and not so._journal_path().exists()


def test_without_a_drive_there_is_a_usage_line_and_no_change(world, capsys):
    derived(world)
    rc, out = run(world, capsys, to=None)
    assert rc == 2 and "usage" in out and not so._journal_path().exists()


def test_a_folder_that_is_not_the_drive_itself_is_refused(world, capsys):
    sub = world.drive / "sub"
    sub.mkdir()
    rc, out = run(world, capsys, to=str(sub))
    assert rc == 2 and "not the mount point" in out
    rc, out = run(world, capsys, to=str(world.tmp / "internal"))
    assert rc == 2 and "not a folder" in out
    plain = world.tmp / "plain"
    plain.mkdir()
    rc, out = run(world, capsys, to=str(plain))
    assert rc == 2 and "not a mounted drive" in out


def test_an_unfinished_offload_blocks_a_new_one(world, capsys):
    derived(world)
    so._save([{"id": "x", "path": "p", "key": "derived", "dest": "d", "aside": "a", "state": "asided", "keep": False}])
    rc, out = run(world, capsys, apply=True)
    assert rc == 2 and "--recover" in out


# --- the move -------------------------------------------------------------------------------------------------

def test_apply_moves_the_folder_and_leaves_a_link(world, capsys):
    src = derived(world)
    before = snapshot(src)
    rc, out = run(world, capsys, apply=True, only="xcode-derived-data")
    assert rc == 0 and "moved" in out
    dest = world.drive / "teyla" / "xcode-derived-data"
    assert src.is_symlink() and os.path.realpath(src) == str(dest)
    assert snapshot(dest) == before and snapshot(src) == before
    assert [p.name for p in src.parent.iterdir()] == ["DerivedData"]            # no aside folder is left
    assert not so._journal_path().exists()


def test_only_the_named_candidate_moves(world, capsys):
    derived(world)
    tree(world.home / GRADLE, {"modules/x": "x"})
    run(world, capsys, apply=True, only="gradle-caches")
    assert (world.home / GRADLE).is_symlink() and not (world.home / DERIVED).is_symlink()


def test_a_path_that_is_already_a_link_is_skipped(world, capsys):
    target = tree(world.drive / "elsewhere", {"a": "1"})
    p = world.home / DERIVED
    p.parent.mkdir(parents=True)
    p.symlink_to(target)
    rc, out = run(world, capsys, apply=True)
    assert rc == 0 and "already a symlink" in out and os.path.realpath(p) == str(target)


def test_keep_retains_the_original_until_finalize(world, capsys):
    src = derived(world)
    rc, out = run(world, capsys, apply=True, keep=True, only="xcode-derived-data")
    assert rc == 0 and "kept the original" in out
    (aside,) = [p for p in src.parent.iterdir() if so.ASIDE in p.name]
    assert aside.is_dir() and src.is_symlink() and so.problems()[0]["level"] == "INFO"
    rc, out = run(world, capsys, finalize=True)
    assert rc == 0 and "deleted the original" in out and not aside.exists() and so.problems() == []


def test_the_original_is_never_deleted_before_the_smoke_check(world, monkeypatch, capsys):
    src = derived(world)
    seen = {}

    def smoke(key, path, before):
        seen["aside"] = [p.name for p in pathlib.Path(path).parent.iterdir() if so.ASIDE in p.name]
        return ""
    monkeypatch.setattr(so, "smoke", smoke)
    run(world, capsys, apply=True, only="xcode-derived-data")
    assert len(seen["aside"]) == 1 and src.is_symlink()


def test_a_failed_smoke_check_restores_the_original(world, monkeypatch, capsys):
    src = derived(world)
    before = snapshot(src)
    monkeypatch.setattr(so, "smoke", lambda *a: "it does not work")
    rc, out = run(world, capsys, apply=True, only="xcode-derived-data")
    assert rc == 1 and "smoke check failed" in out and "the original is back" in out
    assert not src.is_symlink() and snapshot(src) == before
    assert not (world.drive / "teyla" / "xcode-derived-data").exists() and not so._journal_path().exists()
    assert [p.name for p in src.parent.iterdir()] == ["DerivedData"]


def test_a_copy_that_differs_is_not_switched_to(world, monkeypatch, capsys):
    src = derived(world)
    before = snapshot(src)
    real = so._copy

    def lossy(a, b):
        real(a, b)
        next(p for p in pathlib.Path(b).rglob("*") if p.is_file()).unlink()
    monkeypatch.setattr(so, "_copy", lossy)
    rc, out = run(world, capsys, apply=True, only="xcode-derived-data")
    assert rc == 1 and "copy differs" in out and snapshot(src) == before and not src.is_symlink()
    assert not list((world.drive / "teyla").glob("*"))


def test_a_same_size_file_with_other_content_names_is_caught_by_the_manifest(world, monkeypatch, capsys):
    src = derived(world, {"a": "xx", "b": "yy"})
    real = so._copy

    def swapped(a, b):
        real(a, b)
        (pathlib.Path(b) / "a").rename(pathlib.Path(b) / "c")               # same count, same bytes, other name
    monkeypatch.setattr(so, "_copy", swapped)
    rc, out = run(world, capsys, apply=True, only="xcode-derived-data")
    assert rc == 1 and "copy differs" in out and not src.is_symlink()


def test_a_writer_that_starts_mid_copy_fails_the_move(world, monkeypatch, capsys):
    src = derived(world)
    real = so._copy

    def writer(a, b):
        real(a, b)
        (pathlib.Path(a) / "new-file").write_text("written during the copy")
    monkeypatch.setattr(so, "_copy", writer)
    rc, out = run(world, capsys, apply=True, only="xcode-derived-data")
    assert rc == 1 and "something is writing to it" in out and not src.is_symlink() and (src / "new-file").exists()


def test_a_process_that_starts_at_the_switch_fails_the_move(world, monkeypatch, capsys):
    src = derived(world)
    calls = iter(["", "a running process uses it (xcodebuild)"])
    monkeypatch.setattr(so, "busy", lambda key: next(calls, "a running process uses it (xcodebuild)"))
    rc, out = run(world, capsys, apply=True, only="xcode-derived-data")
    assert rc == 1 and "in use at the moment of the switch" in out and not src.is_symlink()
    assert not (world.drive / "teyla" / "xcode-derived-data").exists()


def test_a_failing_link_rolls_back_to_the_original(world, monkeypatch, capsys):
    src = derived(world)
    before = snapshot(src)
    monkeypatch.setattr(so.os, "symlink", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(OSError):
        run(world, capsys, apply=True, only="xcode-derived-data")
    assert snapshot(src) == before and not src.is_symlink() and not so._journal_path().exists()


def test_an_interrupt_rolls_back_and_is_raised_again(world, monkeypatch):
    src = derived(world)
    before = snapshot(src)

    def boom(*a):
        raise KeyboardInterrupt
    monkeypatch.setattr(so, "smoke", boom)
    with pytest.raises(KeyboardInterrupt):
        so.cmd_offload(args(world, apply=True, only="xcode-derived-data"), {})
    assert snapshot(src) == before and not src.is_symlink()


def test_a_second_offload_does_not_wait_for_the_first(world, capsys):
    import fcntl
    derived(world)
    lock = storage.state_dir("offload.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        rc, out = run(world, capsys, apply=True)
    assert rc == 2 and "another" in out and not (world.home / DERIVED).is_symlink()


def test_linux_uses_cp_and_never_asks_diskutil(world, monkeypatch, capsys):
    monkeypatch.setattr(so.sys, "platform", "linux")
    monkeypatch.setattr(so.shutil, "which", lambda n: None)
    src = derived(world)
    rc, out = run(world, capsys, apply=True, only="xcode-derived-data")
    assert rc == 0 and src.is_symlink()


def test_ownership_check_is_darwin_only_and_bounded(world, monkeypatch):
    import plistlib
    monkeypatch.undo()                                    # drop the fixture's stub
    monkeypatch.setattr(so.sys, "platform", "linux")
    monkeypatch.setattr(volumes, "_bounded", lambda *a, **k: pytest.fail("a command ran"))
    assert so._ownership_disabled("/Volumes/External") is False
    monkeypatch.setattr(so.sys, "platform", "darwin")
    monkeypatch.setattr(volumes, "_bounded", lambda cmd, *a, **k: plistlib.dumps({"GlobalPermissionsEnabled": False}).decode())
    assert so._ownership_disabled("/Volumes/External") is True
    monkeypatch.setattr(volumes, "_bounded", lambda *a, **k: plistlib.dumps({"GlobalPermissionsEnabled": True}).decode())
    assert so._ownership_disabled("/Volumes/External") is False
    monkeypatch.setattr(volumes, "_bounded", lambda *a, **k: None)
    assert so._ownership_disabled("/Volumes/External") is None


# --- refusals --------------------------------------------------------------------------------------------------

def reason(w, name="Xcode DerivedData") -> str:
    row = next(r for r in so.plan(str(w.drive)) if r.name == name)
    assert row.status == "refused", row.reason
    return row.reason


def test_a_git_repository_is_never_moved(world):
    derived(world, {"ok": "1"})
    (world.home / DERIVED / "pkg" / ".git").mkdir(parents=True)
    assert "git repository" in reason(world)


def test_a_path_inside_a_repository_is_never_moved(world):
    derived(world)
    (world.home / ".git").mkdir()
    assert "inside a git repository" in reason(world)


@pytest.mark.parametrize("name", ["gradle.properties", "release.keystore", "debug.jks", "adbkey", "adbkey.pub", ".env", ".env.local"])
def test_a_file_that_may_be_a_secret_is_refused(world, name):
    tree(world.home / GRADLE, {"modules/x": "x", f"deep/{name}": "s"})
    assert "may be a secret" in reason(world, "Gradle caches")


def test_simulators_and_virtual_devices_need_an_explicit_yes(world):
    tree(world.home / SIMS, {"AAAA/data": "d"})
    assert "--with-app-data" in reason(world, "iOS simulators")
    row = next(r for r in so.plan(str(world.drive), with_app_data=True) if r.name == "iOS simulators")
    assert row.status == "move"


def test_a_busy_path_is_refused(world, monkeypatch):
    derived(world)
    monkeypatch.setattr(so, "busy", lambda key: "a running process uses it (xcodebuild)")
    assert "in use" in reason(world)


def test_the_process_check_names_what_it_found_and_unknown_counts_as_in_use(monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(storage, "process_commands", lambda: ["/bin/zsh", "/usr/bin/xcodebuild -scheme X"])
    assert "xcodebuild" in so.busy("derived")
    monkeypatch.setattr(storage, "process_commands", lambda: ["/bin/zsh", "java -cp x org.gradle.launcher.daemon.bootstrap.GradleDaemon"])
    assert "GradleDaemon" in so.busy("gradle")
    monkeypatch.setattr(storage, "process_commands", lambda: ["/bin/zsh"])
    assert so.busy("derived") == ""
    monkeypatch.setattr(storage, "process_commands", lambda: None)
    assert "unknown" in so.busy("derived")
    monkeypatch.setattr(storage, "process_commands", lambda: [])
    monkeypatch.setattr(storage, "booted_simulators", lambda: ["AAAA"])
    assert "simulator is booted" in so.busy("sim") and so.busy("derived") == ""


def test_a_drive_with_ownership_disabled_or_unknown_is_refused(world, monkeypatch):
    derived(world)
    monkeypatch.setattr(so, "_ownership_disabled", lambda v: True)
    assert "ownership is disabled" in reason(world)
    monkeypatch.setattr(so, "_ownership_disabled", lambda v: None)
    assert "did not say" in reason(world)


def test_a_drive_you_cannot_write_to_is_refused(world, monkeypatch):
    derived(world)
    monkeypatch.setattr(so.os, "access", lambda p, m: False)
    assert "not writable" in reason(world)


def test_a_drive_without_room_is_refused(world, monkeypatch):
    derived(world)
    monkeypatch.setattr(so.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(100, 99, 1))
    assert "not enough room" in reason(world)


def test_a_source_on_the_same_device_as_the_drive_is_refused(world, monkeypatch):
    derived(world)
    monkeypatch.setattr(volumes, "_dev", lambda p: 1)
    assert "same device" in reason(world)


def test_an_existing_destination_is_never_overwritten(world):
    derived(world)
    (world.drive / "teyla" / "xcode-derived-data").mkdir(parents=True)
    assert "exists already" in reason(world)


def test_a_tree_that_cannot_be_read_is_refused(world):
    src = derived(world)
    (src / "locked").mkdir()
    (src / "locked" / "f").write_text("x")
    os.chmod(src / "locked", 0)
    try:
        if os.access(src / "locked", os.R_OK):
            pytest.skip("running as a user that ignores permissions")
        assert "cannot read" in reason(world)
    finally:
        os.chmod(src / "locked", 0o755)


# --- undo, recover, finalize -----------------------------------------------------------------------------------

def test_undo_copies_back_and_removes_the_link(world, capsys):
    src = derived(world)
    before = snapshot(src)
    run(world, capsys, apply=True, only="xcode-derived-data")
    rc, out = run(world, capsys, undo=str(src))
    assert rc == 0 and not src.is_symlink() and snapshot(src) == before
    assert (world.drive / "teyla" / "xcode-derived-data").exists()              # the drive copy stays by default


def test_undo_can_delete_the_drive_copy_and_refuses_a_plain_folder(world, capsys):
    src = derived(world)
    rc, out = run(world, capsys, undo=str(src))
    assert rc == 2 and "not a symlink" in out
    run(world, capsys, apply=True, only="xcode-derived-data")
    rc, out = run(world, capsys, undo=str(src), delete_drive_copy=True)
    assert rc == 0 and not (world.drive / "teyla" / "xcode-derived-data").exists()


def test_a_failed_undo_leaves_the_link_in_place(world, monkeypatch, capsys):
    src = derived(world)
    run(world, capsys, apply=True, only="xcode-derived-data")

    def broken(a, b):
        os.makedirs(b)
        raise so.Failed("disk full")
    monkeypatch.setattr(so, "_copy", broken)
    rc, out = run(world, capsys, undo=str(src))
    assert rc == 1 and src.is_symlink() and not os.path.lexists(str(src) + ".teyla-undo.partial")


def entry(world, state, **kw):
    path = str(world.home / DERIVED)
    e = {"id": "e1", "path": path, "key": "derived", "dest": str(world.drive / "teyla" / "xcode-derived-data"),
         "aside": path + so.ASIDE + "20260101-000000", "state": state, "keep": False}
    e.update(kw)
    so._save([e])
    return e


def test_recover_after_a_crash_at_each_step(world, capsys):
    p = world.home / DERIVED
    # copying: the original is intact, a partial copy is left
    derived(world)
    e = entry(world, "copying")
    tree(pathlib.Path(e["dest"] + ".partial"), {"x": "1"})
    rc, out = run(world, capsys, recover=True)
    assert rc == 0 and not os.path.exists(e["dest"] + ".partial") and p.is_dir() and not so._journal_path().exists()
    # copied: the copy is in place, the original is intact
    e = entry(world, "copied")
    tree(pathlib.Path(e["dest"]), {"x": "1"})
    run(world, capsys, recover=True)
    assert not os.path.exists(e["dest"]) and p.is_dir()
    # asided: the original is renamed away and there is no link: the case `--undo` cannot see
    shutil.rmtree(p)
    e = entry(world, "asided")
    tree(pathlib.Path(e["aside"]), {"App/a": "orig"})
    tree(pathlib.Path(e["dest"]), {"App/a": "orig"})
    run(world, capsys, recover=True)
    assert (p / "App" / "a").read_text() == "orig" and not os.path.exists(e["aside"]) and not os.path.exists(e["dest"])
    # linked, smoke check not done: the link goes, the original comes back
    shutil.rmtree(p)
    e = entry(world, "linked")
    tree(pathlib.Path(e["aside"]), {"App/a": "orig"})
    tree(pathlib.Path(e["dest"]), {"App/a": "orig"})
    p.symlink_to(e["dest"])
    run(world, capsys, recover=True)
    assert not p.is_symlink() and (p / "App" / "a").read_text() == "orig" and not os.path.exists(e["dest"])
    # smoked: the smoke check had passed, the original is deleted
    shutil.rmtree(p)
    e = entry(world, "smoked")
    tree(pathlib.Path(e["aside"]), {"a": "1"})
    tree(pathlib.Path(e["dest"]), {"a": "1"})
    p.symlink_to(e["dest"])
    run(world, capsys, recover=True)
    assert p.is_symlink() and not os.path.exists(e["aside"]) and os.path.exists(e["dest"])


def test_recover_leaves_a_kept_original_alone_and_says_nothing_to_recover(world, capsys):
    rc, out = run(world, capsys, recover=True)
    assert rc == 0 and "nothing to recover" in out
    e = entry(world, "kept")
    tree(pathlib.Path(e["aside"]), {"a": "1"})
    run(world, capsys, recover=True)
    assert os.path.exists(e["aside"]) and so.journal()[0]["state"] == "kept"


def test_finalize_keeps_the_original_when_the_link_is_gone(world, capsys):
    e = entry(world, "kept")
    tree(pathlib.Path(e["aside"]), {"a": "1"})
    rc, out = run(world, capsys, finalize=True)
    assert rc == 0 and "link is gone" in out and os.path.exists(e["aside"]) and so.journal()


# --- doctor and zero change -----------------------------------------------------------------------------------------

def test_doctor_says_nothing_without_a_journal_and_names_an_unfinished_offload(world):
    assert so.problems() == [] and [r for r in storage.doctor_checks(config.load()) if r["name"] == "storage:offload"] == []
    entry(world, "asided")
    rows = [r for r in storage.doctor_checks(config.load()) if r["name"] == "storage:offload"]
    assert [r["level"] for r in rows] == ["WARN"] and "--recover" in rows[0]["fix"]


def test_nothing_is_written_on_a_machine_that_never_runs_offload(world, capsys):
    derived(world)
    storage.doctor_checks(config.load())
    volumes.problems(config.load())
    assert not so._journal_path().exists() and not storage.state_dir("offload.lock").exists()
    assert not (world.drive / "teyla").exists()


def test_the_scan_digest_tells_apart_what_counts_do_not(world):
    a = tree(world.tmp / "a", {"x": "1", "y": "2"})
    b = tree(world.tmp / "b", {"x": "1", "z": "2"})
    assert so.scan_tree(str(a)) != so.scan_tree(str(b)) and so.scan_tree(str(a)) == so.scan_tree(str(a))
    (a / "l").symlink_to("x")
    (b / "l").symlink_to("z")
    assert so.scan_tree(str(a)).links == 1


def test_the_command_is_registered():
    import argparse as ap
    sp = ap.ArgumentParser().add_subparsers()
    storage.register(sp)
    parser = sp.choices["storage"]
    ns = parser.parse_args(["offload", "--to", "/Volumes/External", "--apply", "--keep", "--with-app-data", "--only", "gradle-caches"])
    assert (ns.action, ns.to, ns.apply, ns.keep, ns.with_app_data, ns.only) == ("offload", "/Volumes/External", True, True, True, "gradle-caches")
    assert parser.parse_args(["offload", "--undo", "~/x"]).undo == "~/x" and parser.parse_args(["offload", "--recover"]).recover

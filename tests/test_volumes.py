"""External drives: heavy folders that are symlinks to another device, and what each surface says.

Nothing here touches a real drive or the real HOME. A drive is a folder under tmp_path whose device number is
faked (`volumes._dev`); "absent" is a path that does not exist. Examples use `/Volumes/External`.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import time

import pytest

from teyla import config, load, storage, storage_sims, storage_sweep, volumes

REPO = pathlib.Path(__file__).resolve().parent.parent
HOOK = REPO / "plugin" / "hooks" / "session-start.sh"
SIMS = "Library/Developer/CoreSimulator/Devices"
DERIVED = "Library/Developer/Xcode/DerivedData"
GRADLE = ".gradle/caches"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A tmp home, a drive on another (faked) device, and a path where a drive used to be."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / "storage.log")
    drive = (tmp_path / "External").resolve()
    drive.mkdir()
    gone = tmp_path / "Absent"                    # never created
    cfg_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)

    def fake_dev(p):
        real = os.path.realpath(p)
        if not os.path.exists(real):
            raise FileNotFoundError(p)
        return 2 if real == str(drive) or real.startswith(str(drive) + os.sep) else 1

    monkeypatch.setattr(volumes, "_dev", fake_dev)

    def configure(volumes_=(), required=()):
        q = lambda xs: "[%s]" % ", ".join(f'"{x}"' for x in xs)
        cfg_file.write_text(f"[storage]\nvolumes = {q(volumes_)}\nvolumes_required = {q(required)}\n")
        return config.load()

    return type("W", (), {"home": home, "drive": drive, "gone": gone, "configure": staticmethod(configure),
                          "tmp": tmp_path})


def link(home: pathlib.Path, rel: str, target: pathlib.Path) -> pathlib.Path:
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.symlink_to(target)
    return p


def on_drive(world, name: str) -> pathlib.Path:
    d = world.drive / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- A: no drive, no change ---------------------------------------------------------------------------

def test_zero_config_and_plain_folders_change_nothing(world):
    for _, rel, _k in volumes.HEAVY:
        (world.home / rel).mkdir(parents=True)                       # plain folders, as most machines have
    cfg = config.load()
    assert volumes.links(cfg, remember=True) == []
    assert volumes.volume_rows(cfg) == [] and volumes.problems(cfg, with_advice=True) == []
    assert volumes.broken(cfg) == [] and volumes.refusal("build", cfg) == "" and volumes.refusal("sim", cfg) == ""
    volumes.write_hook_file(cfg)
    assert not volumes.hook_file().exists() and not volumes.state_path().exists()
    assert load.volume_refusal("build") == ""
    assert [r for r in storage.doctor_checks(cfg) if r["name"].startswith(("storage:link", "storage:volume"))] == []
    assert all("volume" not in r for r in storage.caches(sizes=False, cfg=cfg))
    rep = {"disk": {"total": 10 * 1024 ** 3, "free": 5 * 1024 ** 3, "free_fraction": 0.5}, "settings": storage.settings({}),
           "worktrees": [], "artifacts": [], "derived": [], "volumes": volumes.volume_rows(cfg)}
    out = storage.render(rep, [], [], [])
    assert out.count("disk ") == 1 and "external" not in out


def test_a_plain_folder_is_never_reported_even_next_to_links(world):
    (world.home / DERIVED).mkdir(parents=True)
    link(world.home, SIMS, on_drive(world, "Devices"))
    assert [l.name for l in volumes.links(config.load(), remember=True)] == ["iOS simulators"]


def test_a_link_that_stays_on_the_internal_disk_is_ignored(world):
    other = world.tmp / "elsewhere"
    other.mkdir()
    link(world.home, SIMS, other)
    assert volumes.links(config.load(), remember=True) == []
    assert not volumes.state_path().exists()


def test_default_config_has_the_keys():
    assert config.DEFAULTS["storage"]["volumes"] == [] and config.DEFAULTS["storage"]["volumes_required"] == []


# --- B: detection without config ----------------------------------------------------------------------

def test_a_link_to_another_device_is_on_its_mount_point_without_config(world):
    link(world.home, SIMS, on_drive(world, "ios"))
    (l,) = volumes.links(config.load(), remember=True)
    assert (l.status, l.volume, l.absent) == ("ok", str(world.drive), False)


def test_a_dangling_link_is_reported_on_any_machine(world):
    link(world.home, SIMS, world.gone / "Devices")
    link(world.home, DERIVED, world.gone / "DerivedData")
    ls = volumes.links(config.load(), remember=True)
    assert [(l.status, l.absent, l.volume) for l in ls] == [("dangling", True, str(world.gone))] * 2
    assert not os.path.lexists(world.gone) and os.path.islink(world.home / SIMS)    # nothing made, nothing removed


def test_a_missing_target_on_an_attached_drive_is_not_an_absent_drive(world):
    link(world.home, SIMS, world.drive / "no-such-folder")
    (l,) = volumes.links(config.load())
    assert (l.status, l.absent, l.volume) == ("dangling", False, str(world.drive))


def test_a_relative_link_is_read_as_written(world):
    p = world.home / SIMS
    p.parent.mkdir(parents=True)
    p.symlink_to(os.path.relpath(on_drive(world, "Devices"), p.parent))
    assert [l.status for l in volumes.links(config.load())] == ["ok"]


def test_a_symlinked_parent_covers_the_paths_below_it(world):
    """`~/.gradle` itself is the link: caches and wrapper are both on the drive."""
    gradle = on_drive(world, "gradle")
    (gradle / "caches").mkdir()
    (gradle / "wrapper").mkdir()
    link(world.home, ".gradle", gradle)
    ls = {l.name: l for l in volumes.links(config.load())}
    assert {n: l.status for n, l in ls.items()} == {"Gradle caches": "ok", "Gradle wrapper": "ok"}
    assert ls["Gradle caches"].link_at == str(world.home / ".gradle")
    (world.home / ".gradle").unlink()
    link(world.home, ".gradle", world.gone / "gradle")
    assert sorted((l.name, l.status) for l in volumes.links(config.load())) == [("Gradle caches", "dangling"), ("Gradle wrapper", "dangling")]


def test_a_stub_folder_is_not_a_drive(world):
    stub = world.tmp / "stub"
    stub.mkdir()
    assert volumes.attached(str(stub)) is False and volumes.attached(str(world.drive)) is True


def test_a_folder_where_a_link_was_is_replaced_while_the_drive_is_away(world):
    """The failure itself: the drive went away, a tool deleted the link and made a folder."""
    cfg = config.load()
    p = link(world.home, SIMS, world.gone / "Devices")
    assert volumes.links(cfg, remember=True)[0].status == "dangling"
    p.unlink()
    p.mkdir()
    (l,) = volumes.links(cfg, remember=True)
    assert (l.status, l.target, l.absent) == ("replaced", "", True)
    (row,) = volumes.problems(cfg)
    assert row["level"] == "WARN" and "fills the internal disk" in row["detail"]
    assert volumes.refusal("sim", cfg) and not volumes.refusal("build", cfg)
    p.rmdir()                                                        # still replaced when it is gone altogether
    assert volumes.links(cfg, remember=True)[0].status == "replaced"


def test_a_replaced_path_is_forgotten_once_the_drive_is_back(world):
    p = link(world.home, SIMS, on_drive(world, "Devices"))
    volumes.links(config.load(), remember=True)
    p.unlink()
    p.mkdir()
    # the drive is attached: a real folder where a link was is the owner's business again
    assert volumes.links(config.load(), remember=True) == [] and not volumes.state_path().exists()


# --- config adds to it --------------------------------------------------------------------------------

def test_listed_drives_are_shown_without_links(world):
    cfg = world.configure([world.drive, world.gone])
    rows = {r["volume"]: r for r in volumes.volume_rows(cfg)}
    assert rows[str(world.drive)]["attached"] and not rows[str(world.gone)]["attached"] and rows[str(world.gone)]["links"] == []
    (note,) = volumes.problems(cfg)
    assert note["level"] == "INFO" and str(world.gone) in note["detail"]


def test_a_listed_drive_names_a_dangling_target_under_it(world):
    link(world.home, SIMS, world.gone / "deep" / "Devices")
    (l,) = volumes.links(world.configure([world.gone]))
    assert l.volume == str(world.gone) and l.absent


# --- C: an absent drive is a normal state --------------------------------------------------------------

def test_an_absent_drive_is_one_info_note_and_never_a_fix(world):
    link(world.home, SIMS, world.gone / "Devices")
    link(world.home, GRADLE, world.gone / "caches")
    rows = volumes.problems(config.load())
    assert [(r["level"], r["name"]) for r in rows] == [("INFO", "storage:volume")]
    assert "2 paths point into it" in rows[0]["detail"] and "Do not recreate these paths on the internal disk" in rows[0]["detail"]


def test_a_required_drive_fails_doctor_once_per_path(world):
    link(world.home, SIMS, world.gone / "Devices")
    link(world.home, GRADLE, world.gone / "caches")
    rows = volumes.problems(world.configure(required=[world.gone]))
    assert [(r["level"], r["name"]) for r in rows] == [("FIX", "storage:link")] * 2
    assert "required and not attached" in rows[0]["detail"] and "do not recreate" in rows[0]["fix"].lower()


def test_an_attached_drive_is_ok_and_a_missing_target_on_it_warns(world):
    link(world.home, SIMS, on_drive(world, "Devices"))
    assert [(r["level"], r["name"]) for r in volumes.problems(config.load())] == [("OK", "storage:volume")]
    link(world.home, GRADLE, world.drive / "no-caches")
    assert sorted(r["level"] for r in volumes.problems(config.load())) == ["WARN"]


def test_doctor_checks_carry_the_rows_and_write_the_hook_file(world):
    link(world.home, SIMS, world.gone / "Devices")
    rows = storage.doctor_checks(config.load())
    assert [r["level"] for r in rows if r["name"] == "storage:volume"] == ["INFO"]
    assert volumes.hook_file().read_text() == f"{world.gone}\t{world.home / SIMS}\tdangling\n"
    (world.home / SIMS).unlink()                 # a remembered link that is gone while the drive is away: replaced
    storage.doctor_checks(config.load())
    assert volumes.hook_file().read_text() == f"{world.gone}\t{world.home / SIMS}\treplaced\n"
    link(world.home, SIMS, on_drive(world, "Devices"))   # the drive is back: nothing to say, file removed
    storage.doctor_checks(config.load())
    assert not volumes.hook_file().exists()


def test_the_report_has_a_disk_line_per_drive_and_keeps_its_own(world):
    link(world.home, SIMS, on_drive(world, "Devices"))
    link(world.home, GRADLE, world.gone / "caches")
    rep = {"disk": {"total": 460 * 1024 ** 3, "free": 135 * 1024 ** 3, "free_fraction": 0.29},
           "settings": storage.settings({}), "worktrees": [], "artifacts": [], "derived": [],
           "volumes": volumes.volume_rows(config.load())}
    out = storage.render(rep, [], [], []).splitlines()
    disks = [l for l in out if l.startswith("disk")]
    assert len(disks) == 3 and disks[0].startswith("disk    135.0G free of 460.0G")
    assert any("not attached" in d and str(world.gone) in d for d in disks)
    assert any(f"disk    {world.drive}  " in d and " free of " in d for d in disks)
    assert any(l.startswith("paths on external volumes") for l in out)
    assert any(l.strip().startswith("DANGLING") for l in out) and any(l.strip().startswith("ok") for l in out)


def test_cache_rows_through_a_link_are_external_not_internal(world):
    payload = on_drive(world, "caches")
    (payload / "blob").write_bytes(b"x" * 3_000_000)
    link(world.home, GRADLE, payload)
    (world.home / ".npm").mkdir()
    (world.home / ".npm" / "blob").write_bytes(b"x" * 2_000_000)
    rows = {r["name"]: r for r in storage.caches(sizes=True, cfg=config.load())}
    g = rows["Gradle caches"]
    assert g["bytes"] is None and g["volume"] == str(world.drive) and g["external_bytes"] >= 3_000_000
    assert rows["npm cache"]["bytes"] >= 2_000_000 and "volume" not in rows["npm cache"]
    rep = {"disk": {"total": 1, "free": 1, "free_fraction": 1.0}, "settings": storage.settings({}), "worktrees": [],
           "artifacts": [], "derived": []}
    assert f"on {world.drive}" in storage.render(rep, list(rows.values()), [], [])


def test_a_dangling_cache_link_has_no_row(world):
    link(world.home, GRADLE, world.gone / "caches")
    assert "Gradle caches" not in {r["name"] for r in storage.caches(sizes=False, cfg=config.load())}


# --- the macOS-only advice ------------------------------------------------------------------------------

def test_advice_is_empty_off_macos(world, monkeypatch):
    monkeypatch.setattr(volumes.sys, "platform", "linux")
    monkeypatch.setattr(volumes, "_bounded", lambda *a, **k: pytest.fail("a command ran"))
    assert volumes.advice(str(world.drive)) == []


def test_advice_on_macos_names_ownership_and_spotlight(world, monkeypatch):
    import plistlib
    monkeypatch.setattr(volumes.sys, "platform", "darwin")
    answers = {"diskutil": plistlib.dumps({"GlobalPermissionsEnabled": False}).decode(), "mdutil": "x:\n\tIndexing enabled.\n"}
    monkeypatch.setattr(volumes, "_bounded", lambda cmd, *a, **k: answers[cmd[0]])
    got = volumes.advice(str(world.drive))
    assert len(got) == 2 and "enableOwnership" in got[0] and "Spotlight" in got[1]
    answers.update(diskutil=plistlib.dumps({"GlobalPermissionsEnabled": True}).decode(), mdutil="Indexing disabled.")
    assert volumes.advice(str(world.drive)) == []
    monkeypatch.setattr(volumes, "_bounded", lambda *a, **k: None)           # a hung or failed command: silence
    assert volumes.advice(str(world.drive)) == []


def test_a_hung_command_is_cut_off_and_not_waited_for():
    t = time.monotonic()
    assert volumes._bounded(["sleep", "30"], 0.3) is None
    assert time.monotonic() - t < 5


# --- load ---------------------------------------------------------------------------------------------

def test_load_refuses_only_the_kind_whose_path_dangles(world):
    link(world.home, SIMS, world.gone / "Devices")
    msg = volumes.refusal("sim", config.load())
    assert msg.startswith("teyla guard: sim refused — ") and str(world.gone) in msg
    assert "Do not recreate these paths on the internal disk" in msg
    assert volumes.refusal("build", config.load()) == "" and volumes.refusal("lane", config.load()) == ""
    link(world.home, GRADLE, world.gone / "caches")
    assert "~/" + GRADLE in volumes.refusal("build", config.load())


def _args(**kw):
    base = dict(replay=False, day=None, days=7, admit=None, wait=False, kind="build", json=False, quiet=False,
                record=False, timeout=None, cwd=None)
    return argparse.Namespace(**{**base, **kw})


def test_load_admit_exits_2_with_the_reason_and_logs_it(world, monkeypatch, capsys):
    link(world.home, GRADLE, world.gone / "caches")
    monkeypatch.setattr(load, "decisions_path", lambda: world.tmp / "decisions.tsv")
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None: pytest.fail("the drive check comes before the snapshot"))
    assert load.cmd_load(_args(admit="build")) == 2
    assert "build refused" in capsys.readouterr().out
    assert "refused" in (world.tmp / "decisions.tsv").read_text()


def test_a_wait_notices_a_drive_that_leaves_mid_wait(world, monkeypatch, capsys):
    monkeypatch.setattr(load, "decisions_path", lambda: world.tmp / "decisions.tsv")
    refusals = iter(["", "teyla guard: build refused — gone"])
    monkeypatch.setattr(load, "volume_refusal", lambda kind, cfg=None: next(refusals))
    busy = load.Decision(False, "teyla guard: build refused — busy", "BUSY", "busy")
    monkeypatch.setattr(load, "decide_leased", lambda *a, **k: busy)
    clock = iter(range(0, 1000, 20))
    rc = load.wait("build", {}, 600, poll_s=0, clock=lambda: next(clock), sleeper=lambda s: None, snap_fn=lambda: object(),
                   trend_fn=lambda s: None, cwd="")
    assert rc == 2 and "refused — gone" in capsys.readouterr().out


# --- sims and sweep -----------------------------------------------------------------------------------

def test_sims_reap_never_calls_simctl_through_a_dangling_link(world, monkeypatch):
    link(world.home, SIMS, world.gone / "Devices")
    monkeypatch.setattr(storage_sims, "simctl", lambda *a, **k: pytest.fail("simctl ran"))
    res = storage_sims.reap(config.load())
    assert res["shutdown"] == [] and "not attached" in res["lines"][0]
    assert not os.path.exists(world.gone) and os.path.islink(world.home / SIMS)


def test_sweep_skips_simulators_and_derived_data_through_dangling_links(world, monkeypatch):
    link(world.home, SIMS, world.gone / "Devices")
    link(world.home, DERIVED, world.gone / "DerivedData")
    ctx = storage_sweep.make_ctx(config.load(), dry=False)
    monkeypatch.setattr(storage_sims, "devices", lambda: pytest.fail("simctl ran"))
    assert "not attached" in storage_sweep.simulators(ctx).skipped
    assert "not attached" in storage_sweep.derived_data(ctx).skipped
    assert os.path.islink(world.home / SIMS) and os.path.islink(world.home / DERIVED)
    assert not os.path.lexists(world.gone)


def _old_derived(root: pathlib.Path, name: str, ws: str, ctx) -> pathlib.Path:
    import plistlib
    d = root / name
    (d / "Build").mkdir(parents=True)
    (d / "info.plist").write_bytes(plistlib.dumps({"WorkspacePath": ws}))
    old = ctx.now - 40 * 86400
    for p in (d / "Build", d / "info.plist", d):
        os.utime(p, (old, old))
    return d


def test_sweep_ages_out_derived_data_through_a_symlinked_root_and_keeps_the_link(world):
    payload = on_drive(world, "DerivedData")
    ctx = storage_sweep.make_ctx(config.load(), dry=False)
    ctx.procs = []
    old = _old_derived(payload, "Old-abc", "/x/old", ctx)
    fresh = _old_derived(payload, "Fresh-def", "/x/fresh", ctx)
    os.utime(fresh / "info.plist", (ctx.now, ctx.now))
    root = link(world.home, DERIVED, payload)
    res = storage_sweep.derived_data(ctx)
    assert res.items == 1 and not old.exists() and fresh.exists()
    assert os.path.islink(root) and root.is_dir()


def test_sims_prune_deletes_a_lane_simulator_through_a_symlinked_root(world, monkeypatch):
    root = on_drive(world, "Devices")
    u = "AAAAAAAA-0000-4000-8000-000000000001"
    (root / u).mkdir()
    (root / u / "device.plist").write_text("x")
    old = 1_700_000_000
    for p in (root / u / "device.plist", root / u):
        os.utime(p, (old, old))
    through = link(world.home, SIMS, root)
    calls = []
    monkeypatch.setattr(storage_sims, "simctl", lambda *a, **k: calls.append(a) or (0, ""))
    rows = storage_sims.prune("^lane-", 3, [{"udid": u, "name": "lane-x", "state": "Shutdown"}], [], 1_800_000_000.0,
                              root=through)
    assert [r["deleted"] for r in rows] == [True] and calls == [("delete", u)]
    assert os.path.islink(through)


# --- the session-start hook ---------------------------------------------------------------------------

def _hook(home: pathlib.Path, lines: str | None) -> str:
    f = home / ".teyla" / "volumes.list"
    f.parent.mkdir(exist_ok=True)
    f.unlink(missing_ok=True)
    if lines is not None:
        f.write_text(lines)
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    return subprocess.run(["sh", str(HOOK)], env=env, cwd=str(home), capture_output=True, text=True, timeout=30).stdout


def test_hook_names_the_absent_drive_and_the_instruction(world):
    p = world.home / SIMS
    out = _hook(world.home, f"{world.gone}\t{p}\tdangling\n{world.gone}\t{world.home / GRADLE}\tdangling\n")
    (line,) = [l for l in out.splitlines() if "not attached" in l]
    assert str(world.gone) in line and "2 path(s)" in line and "Do not recreate these paths on the internal disk" in line
    assert out.splitlines()[0] == line                            # first, before everything else


def test_hook_is_silent_without_a_file_or_when_the_paths_are_reachable(world):
    assert "not attached" not in _hook(world.home, None)           # a machine with no drive
    assert "not attached" not in _hook(world.home, "")
    target = on_drive(world, "Devices")
    p = link(world.home, SIMS, target)
    assert "not attached" not in _hook(world.home, f"{world.drive}\t{p}\tdangling\n")   # the drive is back
    assert "not attached" not in _hook(world.home, f"{world.gone}\t{p}\tbogus-no-tab")


def test_hook_flags_a_replaced_path_while_the_drive_is_gone(world):
    p = world.home / SIMS
    p.mkdir(parents=True)                                          # a real folder where the link was
    assert "not attached" in _hook(world.home, f"{world.gone}\t{p}\treplaced\n")
    assert "not attached" not in _hook(world.home, f"{world.drive}\t{p}\treplaced\n")

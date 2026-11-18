"""External volumes: `[storage] volumes`, the links that point into them, and what each surface says.

Nothing here touches a real drive or the real HOME. A volume is a folder under tmp_path; "absent"
is a configured path that does not exist; the links are symlinks built in a tmp home.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess

import pytest

from teyla import config, load, storage, storage_sims, storage_sweep, volumes

REPO = pathlib.Path(__file__).resolve().parent.parent
HOOK = REPO / "plugin" / "hooks" / "session-start.sh"
SIMS = "Library/Developer/CoreSimulator/Devices"
DERIVED = "Library/Developer/Xcode/DerivedData"
GRADLE = ".gradle/caches"


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A tmp home, an attached volume and an absent one."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / "storage.log")
    drive = tmp_path / "drive"
    drive.mkdir()
    gone = tmp_path / "gone-drive"        # never created: "not attached"
    cfg_file = tmp_path / "config.toml"
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)

    def configure(*vols):
        cfg_file.write_text("[storage]\nvolumes = [%s]\n" % ", ".join(f'"{v}"' for v in vols))
        return config.load()

    return type("W", (), {"home": home, "drive": drive, "gone": gone, "configure": staticmethod(configure),
                          "tmp": tmp_path})


def link(home: pathlib.Path, rel: str, target: pathlib.Path) -> pathlib.Path:
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.symlink_to(target)
    return p


# --- config -------------------------------------------------------------------------------------------

def test_no_volumes_is_todays_behaviour(world):
    assert volumes.configured({}) == []
    assert volumes.configured({"storage": {"volumes": []}}) == []
    assert volumes.links({"storage": {}}) == []
    assert volumes.problems({"storage": {}}) == []
    assert volumes.refusal("build", {"storage": {}}) == ""
    assert volumes.volume_rows({"storage": {}}) == []


def test_configured_normalises(world):
    cfg = {"storage": {"volumes": ["~/d/", "/Volumes/x/", "/Volumes/x", "relative", " ", "/"]}}
    assert volumes.configured(cfg) == [str(world.home / "d"), "/Volumes/x"]
    assert volumes.configured({"storage": {"volumes": "/a, /b"}}) == ["/a", "/b"]   # a hand-edited string


def test_default_config_has_the_key():
    assert config.DEFAULTS["storage"]["volumes"] == []


# --- links --------------------------------------------------------------------------------------------

def test_attached_link_is_ok(world):
    (world.drive / "Devices").mkdir()
    link(world.home, SIMS, world.drive / "Devices")
    ls = volumes.links(world.configure(world.drive), remember=True)
    assert [(l.name, l.status, l.volume) for l in ls] == [("iOS simulators", "ok", str(world.drive))]
    assert volumes.broken(world.configure(world.drive)) == []


def test_dangling_link_when_the_volume_is_absent(world):
    link(world.home, SIMS, world.gone / "Devices")
    link(world.home, DERIVED, world.gone / "DerivedData")
    link(world.home, GRADLE, world.gone / "caches")
    cfg = world.configure(world.gone)
    assert sorted(l.status for l in volumes.links(cfg)) == ["dangling"] * 3
    assert not os.path.lexists(world.gone)                       # nothing created the target
    assert os.path.islink(world.home / SIMS)                     # and nothing removed the link


def test_a_link_to_a_missing_folder_on_an_attached_volume_dangles(world):
    link(world.home, SIMS, world.drive / "no-such-folder")
    assert [l.status for l in volumes.links(world.configure(world.drive))] == ["dangling"]


def test_a_relative_link_is_read_as_written(world):
    (world.home / "ext").mkdir()
    p = world.home / SIMS
    p.parent.mkdir(parents=True)
    p.symlink_to(os.path.relpath(world.drive / "Devices", p.parent))
    (world.drive / "Devices").mkdir()
    assert [l.status for l in volumes.links(world.configure(world.drive))] == ["ok"]


def test_links_into_other_places_are_ignored(world):
    other = world.tmp / "elsewhere"
    other.mkdir()
    link(world.home, SIMS, other)
    (world.home / DERIVED).mkdir(parents=True)                   # a real folder nobody ever linked
    assert volumes.links(world.configure(world.drive), remember=True) == []


def test_a_folder_where_a_link_was_is_replaced(world):
    """The failure itself: the drive went away, a tool deleted the link and made a folder."""
    target = world.drive / "Devices"
    target.mkdir()
    p = link(world.home, SIMS, target)
    cfg = world.configure(world.drive)
    assert volumes.links(cfg, remember=True)[0].status == "ok"   # seen once: remembered
    p.unlink()
    p.mkdir()
    (l,) = volumes.links(cfg, remember=True)
    assert (l.status, l.target) == ("replaced", "")
    (row,) = volumes.problems(cfg)
    assert row["level"] == "FIX" and "now a folder or missing" in row["detail"]
    p.rmdir()                                                    # and gone altogether
    assert volumes.links(cfg, remember=True)[0].status == "replaced"


def test_a_volume_dropped_from_config_forgets_its_links(world):
    target = world.drive / "Devices"
    target.mkdir()
    p = link(world.home, SIMS, target)
    volumes.links(world.configure(world.drive), remember=True)
    p.unlink()
    p.mkdir()
    assert volumes.links(world.configure(), remember=True) == []


def test_a_stub_under_volumes_is_not_a_drive(world, monkeypatch):
    stub = world.tmp / "Volumes" / "Drive"
    stub.mkdir(parents=True)
    monkeypatch.setattr(volumes, "MOUNT_PREFIX", str(world.tmp / "Volumes"))
    assert volumes.attached(str(stub)) is False                  # a folder, not a mount point
    monkeypatch.setattr(os.path, "ismount", lambda p: True)
    assert volumes.attached(str(stub)) is True


# --- report -------------------------------------------------------------------------------------------

def test_rows_and_lines(world):
    (world.drive / "Devices").mkdir()
    link(world.home, SIMS, world.drive / "Devices")
    link(world.home, GRADLE, world.gone / "caches")
    rows = volumes.volume_rows(world.configure(world.drive, world.gone))
    text = "\n".join(volumes.render(rows))
    assert f"disk    {world.drive}  " in text and " free of " in text
    assert f"disk    {world.gone}  not attached — 1 path(s) point into it; do not recreate them on the internal disk" in text
    assert "ok       ~/" + SIMS in text and "DANGLING ~/" + GRADLE in text


def test_the_report_has_one_disk_line_per_volume_and_keeps_its_own(world):
    link(world.home, GRADLE, world.gone / "caches")
    rep = {"disk": {"total": 460 * 1024 ** 3, "free": 135 * 1024 ** 3, "free_fraction": 0.29},
           "settings": storage.settings({}), "worktrees": [], "artifacts": [], "derived": [],
           "volumes": volumes.volume_rows(world.configure(world.drive, world.gone))}
    out = storage.render(rep, [], [], []).splitlines()
    disks = [l for l in out if l.startswith("disk")]
    assert len(disks) == 3 and disks[0].startswith("disk    135.0G free of 460.0G")
    assert "not attached" in disks[2]
    assert any(l.startswith("paths on external volumes") for l in out)


def test_no_volumes_no_extra_lines(world):
    rep = {"disk": {"total": 10 * 1024 ** 3, "free": 5 * 1024 ** 3, "free_fraction": 0.5}, "settings": storage.settings({}),
           "worktrees": [], "artifacts": [], "derived": [], "volumes": []}
    out = storage.render(rep, [], [], [])
    assert out.count("disk ") == 1 and "external" not in out


def test_cache_rows_through_a_link_are_external_not_internal(world, monkeypatch):
    payload = world.drive / "caches"
    payload.mkdir()
    (payload / "blob").write_bytes(b"x" * 3_000_000)
    link(world.home, GRADLE, payload)
    internal = world.home / ".npm"
    internal.mkdir()
    (internal / "blob").write_bytes(b"x" * 2_000_000)
    cfg = world.configure(world.drive)
    rows = {r["name"]: r for r in storage.caches(sizes=True, cfg=cfg)}
    g = rows["Gradle caches"]
    assert g["bytes"] is None and g["volume"] == str(world.drive) and g["external_bytes"] >= 3_000_000
    assert rows["npm cache"]["bytes"] >= 2_000_000 and "volume" not in rows["npm cache"]
    rep = {"disk": {"total": 1, "free": 1, "free_fraction": 1.0}, "settings": storage.settings({}), "worktrees": [],
           "artifacts": [], "derived": []}
    text = storage.render(rep, list(rows.values()), [], [])
    assert f"on {world.drive}" in text
    # without the config the same link is measured as before: du does not follow it
    assert "volume" not in {r["name"]: r for r in storage.caches(sizes=True, cfg={})}["Gradle caches"]


def test_a_dangling_cache_link_has_no_row(world):
    link(world.home, GRADLE, world.gone / "caches")
    assert "Gradle caches" not in {r["name"] for r in storage.caches(sizes=False, cfg=world.configure(world.gone))}


# --- doctor -------------------------------------------------------------------------------------------

def test_doctor_rows(world):
    link(world.home, SIMS, world.gone / "Devices")
    link(world.home, GRADLE, world.gone / "caches")
    rows = volumes.problems(world.configure(world.gone, world.drive))
    fixes = [r for r in rows if r["level"] == "FIX"]
    assert len(fixes) == 2 and all(r["name"] == "storage:link" for r in fixes)
    assert "dangles" in fixes[0]["detail"] and str(world.gone) in fixes[0]["detail"]
    assert "do not recreate ~/" + SIMS in fixes[0]["fix"]
    assert [r["level"] for r in rows if r["name"] == "storage:volume"] == ["OK"]   # the attached drive, no links


def test_doctor_warns_about_an_absent_volume_nothing_points_into(world):
    (row,) = volumes.problems(world.configure(world.gone))
    assert row["level"] == "WARN" and "is not attached" in row["detail"]


def test_storage_doctor_checks_include_the_volume_rows_and_write_the_hook_file(world):
    link(world.home, SIMS, world.gone / "Devices")
    cfg = world.configure(world.gone)
    rows = storage.doctor_checks(cfg)
    assert [r["level"] for r in rows if r["name"] == "storage:link"] == ["FIX"]
    assert (storage.state_dir().parent / "volumes.list").read_text() == f"{world.gone}\t1\n"
    storage.doctor_checks(world.configure())
    assert not (storage.state_dir().parent / "volumes.list").exists()


# --- load ---------------------------------------------------------------------------------------------

def test_load_refuses_only_the_kind_whose_path_dangles(world):
    link(world.home, SIMS, world.gone / "Devices")
    cfg = world.configure(world.gone)
    msg = volumes.refusal("sim", cfg)
    assert msg.startswith("teyla guard: sim refused — ") and str(world.gone) in msg
    assert "Do not recreate these paths on the internal disk" in msg
    assert volumes.refusal("build", cfg) == "" and volumes.refusal("lane", cfg) == ""
    link(world.home, GRADLE, world.gone / "caches")
    assert "~/" + GRADLE in volumes.refusal("build", cfg)


def _args(**kw):
    base = dict(replay=False, day=None, days=7, admit=None, wait=False, kind="build", json=False, quiet=False,
                record=False, timeout=None, cwd=None)
    return argparse.Namespace(**{**base, **kw})


def test_load_admit_exits_2_with_the_reason_and_logs_it(world, monkeypatch, capsys):
    link(world.home, GRADLE, world.gone / "caches")
    world.configure(world.gone)
    monkeypatch.setattr(load, "decisions_path", lambda: world.tmp / "decisions.tsv")
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None: pytest.fail("the volume check comes before the snapshot"))
    assert load.cmd_load(_args(admit="build")) == 2
    assert "build refused" in capsys.readouterr().out
    assert "refused" in (world.tmp / "decisions.tsv").read_text()
    assert load.cmd_load(_args(wait=True, kind="build", timeout=0)) == 2     # --wait does not poll on it


def test_load_without_the_config_is_unchanged(world, monkeypatch):
    link(world.home, GRADLE, world.gone / "caches")             # a dangling link, but no volume configured
    assert load.volume_refusal("build") == ""


# --- sims and sweep -----------------------------------------------------------------------------------

def test_sims_reap_never_calls_simctl_through_a_dangling_link(world, monkeypatch):
    link(world.home, SIMS, world.gone / "Devices")
    cfg = world.configure(world.gone)
    monkeypatch.setattr(storage_sims, "simctl", lambda *a, **k: pytest.fail("simctl ran"))
    res = storage_sims.reap(cfg)
    assert res["shutdown"] == [] and "not attached" in res["lines"][0]
    assert not os.path.exists(world.gone) and os.path.islink(world.home / SIMS)


def test_sweep_skips_simulators_and_derived_data_through_dangling_links(world, monkeypatch):
    link(world.home, SIMS, world.gone / "Devices")
    link(world.home, DERIVED, world.gone / "DerivedData")
    cfg = world.configure(world.gone)
    ctx = storage_sweep.make_ctx(cfg, dry=False)
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
    payload = world.drive / "DerivedData"
    payload.mkdir()
    ctx = storage_sweep.make_ctx(world.configure(world.drive), dry=False)
    ctx.procs = []
    old = _old_derived(payload, "Old-abc", "/x/old", ctx)
    fresh = _old_derived(payload, "Fresh-def", "/x/fresh", ctx)
    os.utime(fresh / "info.plist", (ctx.now, ctx.now))
    root = link(world.home, DERIVED, payload)
    res = storage_sweep.derived_data(ctx)
    assert res.items == 1 and not old.exists() and fresh.exists()
    assert os.path.islink(root) and root.is_dir()                  # the link itself stays, and so does its target


def test_sims_prune_deletes_a_lane_simulator_through_a_symlinked_root(world, monkeypatch):
    root = world.drive / "Devices"
    root.mkdir()
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
    assert os.path.islink(through)                                # simctl deletes the device, never the link


# --- the session-start hook ---------------------------------------------------------------------------

def _hook(home: pathlib.Path, lines: str) -> str:
    (home / ".teyla").mkdir(exist_ok=True)
    (home / ".teyla" / "volumes.list").write_text(lines)
    env = {"HOME": str(home), "PATH": os.environ["PATH"]}
    return subprocess.run(["sh", str(HOOK)], env=env, cwd=str(home), capture_output=True, text=True, timeout=30).stdout


def test_hook_names_the_absent_volume_and_the_instruction(world):
    out = _hook(world.home, f"{world.gone}\t3\n")
    (line,) = [l for l in out.splitlines() if "not attached" in l]
    assert str(world.gone) in line and "3 path(s)" in line and "Do not recreate these paths on the internal disk" in line
    assert out.splitlines()[0] == line                            # first, before everything else


def test_hook_is_silent_when_attached_or_nothing_points_into_it(world):
    assert "not attached" not in _hook(world.home, f"{world.drive}\t3\n")
    assert "not attached" not in _hook(world.home, f"{world.gone}\t0\n")
    assert "not attached" not in _hook(world.home, "")
    assert "not attached" not in _hook(world.home, f"{world.gone}\tmany\n")

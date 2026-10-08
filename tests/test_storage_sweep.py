"""`teyla storage sweep` — each category on a tmp tree, in dry and apply mode.

Every category takes a `Ctx`, so the tests hand it fakes for what the machine would answer: the
process list, `du`, the tools on PATH and what they print (docker, uv, pgrep), the simulator
list, the free space and the clock. HOME is tmp_path, so nothing here touches the real one.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import time

import pytest

from teyla import storage, storage_sims, storage_sweep as sw

NOW = time.time()
H = 3600
DAY = 86400
GIB = 1024 ** 3


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / "storage.log")


def age(path, seconds: float):
    """Set mtime of `path` (and everything inside it) `seconds` before NOW."""
    t = NOW - seconds
    paths = [path]
    if os.path.isdir(path):
        for dirpath, dirnames, filenames in os.walk(path):
            paths += [os.path.join(dirpath, n) for n in dirnames + filenames]
    for p in reversed(paths):   # children first: touching a child moves its parent's mtime
        os.utime(p, (t, t), follow_symlinks=False)


def fake_du(path) -> int:
    p = pathlib.Path(path)
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


class Runner:
    """Records and answers every external command; `answers` maps a command prefix to (rc, output)."""

    def __init__(self, answers=None, tools=()):
        self.answers = answers or {}
        self.tools = set(tools)
        self.calls = []

    def run(self, cmd, timeout=600):
        self.calls.append(list(cmd))
        best = None
        for prefix, ans in self.answers.items():
            if list(cmd[:len(prefix)]) == list(prefix) and (best is None or len(prefix) > len(best)):
                best = prefix
        return self.answers[best] if best else (1, "")

    def have(self, name):
        return name in self.tools

    def ran(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


def make_ctx(tmp_path, dry=False, free=100 * GIB, procs=(), runner=None, tmp_roots=None, **cfg) -> sw.Ctx:
    runner = runner or Runner()
    return sw.Ctx(cfg=sw.settings({"storage": cfg}), now=NOW, home=tmp_path / "home", dry=dry, free=free,
                  tmp_roots=tmp_roots if tmp_roots is not None else [tmp_path / "tmp"],
                  procs=None if procs is None else list(procs), run=runner.run, have=runner.have, du=fake_du)


def derived_dir(root: pathlib.Path, name="dd", seconds=2 * DAY, size=1024) -> pathlib.Path:
    """An Xcode DerivedData-shaped folder, with a notes file Xcode did not write."""
    d = root / name
    (d / "Build" / "Products").mkdir(parents=True)
    (d / "Build" / "Products" / "app.o").write_bytes(b"0" * size)
    (d / "Logs").mkdir()
    (d / "Logs" / "build.log").write_text("log")
    (d / "info.plist").write_text("<plist/>")
    (d / "notes.md").write_text("keep me")
    age(d, seconds)
    return d


# --- settings ---------------------------------------------------------------------------------

def test_settings_defaults_and_garbage():
    s = sw.settings({})
    assert (s["temp_hours"], s["release_days"], s["sim_days"], s["derived_days"], s["grok_days"], s["log_days"],
            s["docker_days"], s["log_max_mb"], s["urgent_free_gb"]) == (24, 3, 7, 14, 14, 14, 7, 50, 20)
    assert s["docker_repos"] == [] and s["sim_pattern"] == ""
    s = sw.settings({"storage": {"sweep_temp_hours": "6", "sweep_grok_days": "soon", "docker_superseded_repos": "a/, b/c"}})
    assert s["temp_hours"] == 6 and s["grok_days"] == 14 and s["docker_repos"] == ["a/", "b/c"]


# --- temp builds --------------------------------------------------------------------------------

def test_idle_temp_derived_data_goes_but_only_what_xcode_wrote(tmp_path):
    root = tmp_path / "tmp"
    d = derived_dir(root / "session-1")
    res = sw.temp_builds(make_ctx(tmp_path, dry=True))
    assert d.joinpath("Build").exists() and res.bytes > 0 and res.lines[0].startswith("would remove")
    res = sw.temp_builds(make_ctx(tmp_path))
    assert not (d / "Build").exists() and not (d / "Logs").exists() and not (d / "info.plist").exists()
    assert (d / "notes.md").read_text() == "keep me" and d.exists(), "the notes keep their folder"
    assert res.bytes >= 1024 and "removed" in res.lines[0]


def test_a_folder_that_held_only_xcode_output_is_removed_with_it(tmp_path):
    root = tmp_path / "tmp"
    d = derived_dir(root, name="only")
    (d / "notes.md").unlink()
    age(d, 2 * DAY)   # the unlink touched the folder
    sw.temp_builds(make_ctx(tmp_path))
    assert not d.exists()


def test_recent_or_in_use_or_checkout_temp_builds_stay(tmp_path):
    root = tmp_path / "tmp"
    recent = derived_dir(root, "recent", seconds=2 * H)
    used = derived_dir(root, "used")
    checkout = derived_dir(root / "clone", "dd")
    (root / "clone" / ".git").mkdir()
    nested = derived_dir(root, "nested")
    (nested / "Build" / "SourcePackages" / "checkouts" / "pkg" / ".git").mkdir(parents=True)
    age(nested, 2 * DAY)
    res = sw.temp_builds(make_ctx(tmp_path, procs=[f"xcodebuild -derivedDataPath {used}"]))
    assert res.items == 0
    for d in (recent, used, checkout, nested):
        assert (d / "Build").exists(), d.name


def test_unknown_process_list_removes_no_temp_build(tmp_path):
    d = derived_dir(tmp_path / "tmp")
    sw.temp_builds(make_ctx(tmp_path, procs=None))
    assert (d / "Build").exists()


def test_a_process_may_name_a_folder_with_or_without_the_private_prefix(tmp_path):
    ctx = make_ctx(tmp_path, procs=["xcodebuild -derivedDataPath /tmp/x/dd"])
    assert ctx.named("/private/tmp/x/dd") and ctx.named("/tmp/x/dd") and not ctx.named("/private/tmp/y/dd")
    assert make_ctx(tmp_path, procs=None).named("/anything"), "unknown process list: assume in use"


def test_under_the_urgent_threshold_two_hours_idle_is_enough(tmp_path):
    d = derived_dir(tmp_path / "tmp", seconds=3 * H)
    assert sw.temp_builds(make_ctx(tmp_path, free=50 * GIB)).items == 0 and (d / "Build").exists()
    res = sw.temp_builds(make_ctx(tmp_path, free=5 * GIB))
    assert res.items == 1 and not (d / "Build").exists() and "under 20 GB free" in res.lines[0]


def test_xcresult_bundles_go_only_when_they_hold_nothing_else(tmp_path):
    root = tmp_path / "tmp"
    good = root / "a.xcresult"
    (good / "Data").mkdir(parents=True)
    (good / "Info.plist").write_text("x")
    extra = root / "b.xcresult"
    (extra / "Data").mkdir(parents=True)
    (extra / "Info.plist").write_text("x")
    (extra / "mine.txt").write_text("not xcode's")
    for p in (good, extra):
        age(p, 2 * DAY)
    sw.temp_builds(make_ctx(tmp_path))
    assert not good.exists() and extra.exists()


def test_big_builds_get_their_own_line_and_small_ones_share_one(tmp_path, monkeypatch):
    monkeypatch.setattr(sw, "SMALL_BUILD", 2000)
    root = tmp_path / "tmp"
    big = derived_dir(root, "big", size=5000)
    s1, s2 = derived_dir(root, "s1", size=100), derived_dir(root, "s2", size=100)
    res = sw.temp_builds(make_ctx(tmp_path, dry=True))
    assert len(res.lines) == 2 and any("2 small temp build folders" in line for line in res.lines)
    assert any(str(big.name) in line for line in res.lines)
    sw.temp_builds(make_ctx(tmp_path))
    assert not any((d / "Build").exists() for d in (big, s1, s2))


def test_someone_elses_build_directory_is_not_touched(tmp_path):
    d = derived_dir(tmp_path / "tmp")
    ctx = make_ctx(tmp_path)
    ctx.uid = os.getuid() + 1
    assert sw.temp_builds(ctx).items == 0 and (d / "Build").exists()


# --- release leftovers --------------------------------------------------------------------------

def test_export_leftovers_go_when_they_hold_only_what_xcodebuild_writes(tmp_path):
    root = tmp_path / "tmp"
    good = root / "XcodeDistPipeline.~~~abc123"
    for sub in ("Packages", "Root", "Symbols", "entitlements~~~Z9y8x7"):
        (good / sub).mkdir(parents=True)
    (good / "Root" / "app").write_bytes(b"0" * 500)
    foreign = root / "XcodeDistPipeline.~~~def456"
    (foreign / "Root").mkdir(parents=True)
    (foreign / "mine.txt").write_text("x")
    other = root / "XcodeDistPipeline.keep"
    other.mkdir()
    for p in (good, foreign, other):
        age(p, 5 * DAY)
    res = sw.release_leftovers(make_ctx(tmp_path, dry=True))
    assert good.exists() and res.bytes == 500 and "1 export leftovers" in res.lines[0]
    sw.release_leftovers(make_ctx(tmp_path))
    assert not good.exists() and foreign.exists() and other.exists()


def test_fresh_export_leftover_stays(tmp_path):
    d = tmp_path / "tmp" / "XcodeDistPipeline.~~~abc123"
    (d / "Root").mkdir(parents=True)
    age(d, 1 * H)
    assert sw.release_leftovers(make_ctx(tmp_path)).items == 0 and d.exists()


# --- simulators ----------------------------------------------------------------------------------

def test_sweep_simulators_use_the_prune_pattern_and_their_own_age(tmp_path, monkeypatch):
    udid = "0000000A-0000-4000-8000-000000000000"
    dev = tmp_path / "home" / "Library" / "Developer" / "CoreSimulator" / "Devices" / udid
    (dev / "data" / "Library" / "Preferences").mkdir(parents=True)
    (dev / "device.plist").write_text("x")
    (dev / "data" / "blob").write_bytes(b"0" * 700)
    age(dev, 10 * DAY)
    calls = []

    def simctl(*args, timeout=60):
        calls.append(args)
        if args[0] == "list":
            return 0, json.dumps({"devices": {"r": [{"udid": udid, "name": "Task one", "state": "Shutdown"}]}})
        return 0, ""

    monkeypatch.setattr(storage_sims, "simctl", simctl)
    assert sw.simulators(make_ctx(tmp_path)).skipped, "empty pattern: nothing is deleted"
    res = sw.simulators(make_ctx(tmp_path, dry=True, sim_prune_pattern="Task "))
    assert res.bytes >= 700 and "would delete simulator Task one" in res.lines[0]
    assert not [c for c in calls if c[0] == "delete"]
    res = sw.simulators(make_ctx(tmp_path, sim_prune_pattern="Task ", sweep_sim_days=30))
    assert res.items == 0, "10 days old is under sweep_sim_days = 30"
    res = sw.simulators(make_ctx(tmp_path, sim_prune_pattern="Task "))
    assert res.items == 1 and ("delete", udid) in [tuple(c[:2]) for c in calls]


# --- DerivedData ---------------------------------------------------------------------------------

def test_old_derived_data_goes_and_shared_caches_stay(tmp_path):
    root = tmp_path / "home" / "Library" / "Developer" / "Xcode" / "DerivedData"
    old = derived_dir(root, "Old-abc", seconds=20 * DAY)
    new = derived_dir(root, "New-abc", seconds=2 * DAY)
    used = derived_dir(root, "Used-abc", seconds=20 * DAY)
    shared = root / "ModuleCache.noindex"
    shared.mkdir()
    (shared / "m").write_text("x")
    age(shared, 90 * DAY)
    link = root / "Link-abc"
    link.symlink_to(old)
    ctx = make_ctx(tmp_path, dry=True, procs=[f"xcodebuild -derivedDataPath {used}"])
    res = sw.derived_data(ctx)
    assert old.exists() and res.items == 1 and "Old-abc" in res.lines[0]
    sw.derived_data(make_ctx(tmp_path, procs=[f"xcodebuild -derivedDataPath {used}"]))
    assert not old.exists()
    assert new.exists() and used.exists() and shared.exists()


def test_derived_data_written_inside_recently_or_with_an_edited_package_stays(tmp_path):
    root = tmp_path / "home" / "Library" / "Developer" / "Xcode" / "DerivedData"
    recent = derived_dir(root, "Recent-abc", seconds=20 * DAY)
    log = recent / "Logs" / "build.log"
    os.utime(log, (NOW - DAY, NOW - DAY))       # info.plist is old, a file inside is not
    edited = derived_dir(root, "Edited-abc", seconds=20 * DAY)
    pkg = edited / "SourcePackages" / "checkouts" / "lib"
    (pkg / ".git").mkdir(parents=True)
    age(edited, 20 * DAY)
    clean = derived_dir(root, "Clean-abc", seconds=20 * DAY)
    (clean / "SourcePackages" / "checkouts" / "lib" / ".git").mkdir(parents=True)
    age(clean, 20 * DAY)
    r = Runner({("git", "-C", str(pkg), "status"): (0, " M Sources/lib.swift\n"), ("git", "-C"): (0, "")})
    res = sw.derived_data(make_ctx(tmp_path, runner=r))
    assert recent.exists() and edited.exists() and not clean.exists()
    assert any("uncommitted changes" in x for x in res.lines)


# --- codex runtimes --------------------------------------------------------------------------------

def test_codex_runtime_install_leftovers(tmp_path):
    root = tmp_path / "home" / ".cache" / "codex-runtimes"
    old, new, named, other = (root / n for n in ("codex-runtime-install-a", "codex-runtime-install-b",
                                                  "codex-runtime-install-c", "codex-runtime-1"))
    for d in (old, new, named, other):
        d.mkdir(parents=True)
        (d / "f").write_bytes(b"0" * 100)
    for d in (old, named, other):
        age(d, 5 * DAY)
    age(new, 1 * H)
    res = sw.codex_runtimes(make_ctx(tmp_path, dry=True, procs=[f"codex {named}/bin"]))
    assert res.items == 1 and res.bytes == 100 and old.exists()
    sw.codex_runtimes(make_ctx(tmp_path, procs=[f"codex {named}/bin"]))
    assert not old.exists() and new.exists() and named.exists() and other.exists()


# --- package caches ---------------------------------------------------------------------------------

def test_package_caches_run_each_tool_only_when_present_and_only_when_not_dry(tmp_path):
    runner = Runner({("uv",): (0, ""), ("npm",): (3, "")}, tools={"uv", "npm"})
    res = sw.package_caches(make_ctx(tmp_path, dry=True, runner=runner))
    assert runner.calls == [] and res.lines == ["would run: uv cache prune", "would run: npm cache verify"]
    cache = tmp_path / "home" / ".cache" / "uv"
    cache.mkdir(parents=True)
    (cache / "blob").write_bytes(b"0" * 900)
    shrink = Runner({("uv",): (0, ""), ("npm",): (3, "")}, tools={"uv", "npm"})
    orig = shrink.run

    def run_and_free(cmd, timeout=600):
        if cmd[0] == "uv":
            (cache / "blob").write_bytes(b"0" * 100)
        return orig(cmd, timeout)

    shrink.run = run_and_free
    res = sw.package_caches(make_ctx(tmp_path, runner=shrink))
    assert [c[0] for c in shrink.calls] == ["uv", "npm"], "pnpm is not installed: skipped"
    assert res.bytes == 800 and "uv cache prune: ok" in res.lines[0] and "npm cache verify: failed (exit 3)" in res.lines[1]


# --- docker ------------------------------------------------------------------------------------------

def image_line(iid, created, tagged, size, *tags):
    return (0, f"sha256:{iid}|{created}|{tagged}|{size}|{' '.join(tags)}")


def docker_runner(images, used=(), prune_out="Total reclaimed space: 1.5GB"):
    answers = {("docker", "info"): (0, ""), ("docker", "ps", "-aq"): (0, "c1\n" if used else ""),
               ("docker", "inspect"): (0, "\n".join(f"sha256:{u}" for u in used)),
               ("docker", "images", "-q"): (0, "\n".join(f"sha256:{i[0]}" for i in images)),
               ("docker", "image", "prune"): (0, prune_out), ("docker", "builder", "prune"): (0, "Total reclaimed space: 500MB"),
               ("docker", "rmi"): (0, "")}
    for iid, created, tagged, size, *tags in images:
        answers[("docker", "image", "inspect", "--format", "{{.Id}}|{{.Created}}|{{.Metadata.LastTagTime}}|{{.Size}}|"
                 "{{join .RepoTags \" \"}}", f"sha256:{iid}")] = image_line(iid, created, tagged, size, *tags)
    return Runner(answers, tools={"docker"})


def iso(seconds_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S.123456789Z", time.gmtime(NOW - seconds_ago))


def go_time(seconds_ago):
    return time.strftime("%Y-%m-%d %H:%M:%S.56 +0000 UTC", time.gmtime(NOW - seconds_ago))


REPO = "registry.example.com/vendor/db"


def test_docker_not_installed_or_not_running_is_skipped_never_started(tmp_path):
    assert "not installed" in sw.docker(make_ctx(tmp_path)).skipped
    r = Runner({("docker", "info"): (1, "")}, tools={"docker"})
    res = sw.docker(make_ctx(tmp_path, runner=r))
    assert "not running" in res.skipped and r.calls == [["docker", "info"]]


def test_docker_dry_runs_nothing_destructive(tmp_path):
    r = docker_runner([])
    res = sw.docker(make_ctx(tmp_path, dry=True, runner=r))
    assert res.lines[0].startswith("would run: docker image prune")
    assert not r.ran("docker", "image", "prune") and not r.ran("docker", "builder", "prune")


def test_docker_prunes_and_reports_what_it_reclaimed(tmp_path):
    r = docker_runner([])
    res = sw.docker(make_ctx(tmp_path, runner=r))
    assert ["docker", "builder", "prune", "-f", "--filter", "until=168h"] in r.calls
    assert ["docker", "image", "prune", "-f", "--filter", "until=168h"] in r.calls, "a fresh dangling image stays"
    assert res.bytes == 1_500_000_000 + 500_000_000


def test_superseded_images_go_only_for_configured_repositories(tmp_path):
    images = [("new", iso(1 * DAY), go_time(1 * DAY), 300, f"{REPO}:v3"),
              ("old", iso(60 * DAY), go_time(30 * DAY), 200, f"{REPO}:v2"),
              ("busy", iso(90 * DAY), go_time(40 * DAY), 150, f"{REPO}:v1"),
              ("recent", iso(10 * DAY), go_time(2 * DAY), 120, f"{REPO}:v2b"),
              ("unreadable", iso(70 * DAY), "garbage", 110, f"{REPO}:v0"),
              ("other-new", iso(1 * DAY), go_time(1 * DAY), 90, "docker.io/library/app:2"),
              ("other-old", iso(99 * DAY), go_time(60 * DAY), 80, "docker.io/library/app:1")]
    r = docker_runner(images, used=["busy"])
    unset = sw.docker(make_ctx(tmp_path, runner=r))
    assert not r.ran("docker", "rmi"), "no repository is configured: no tag is removed"
    r = docker_runner(images, used=["busy"])
    res = sw.docker(make_ctx(tmp_path, dry=True, runner=r, docker_superseded_repos=["registry.example.com/vendor/"]))
    assert res.items == 1 and res.bytes == 200 and "superseded docker image " + f"{REPO}:v2" in res.lines[-1]
    assert not r.ran("docker", "rmi")
    r = docker_runner(images, used=["busy"])
    res = sw.docker(make_ctx(tmp_path, runner=r, docker_superseded_repos=["registry.example.com/vendor"]))
    assert r.ran("docker", "rmi") == [["docker", "rmi", f"{REPO}:v2"]]
    assert res.items == 1 and unset.items == 0


def test_two_tags_of_the_newest_image_and_a_same_second_pair_are_not_superseded(tmp_path):
    t = iso(40 * DAY)
    images = [("a", t, go_time(30 * DAY), 10, f"{REPO}:latest", f"{REPO}:v2"),
              ("b", t, go_time(30 * DAY), 10, f"{REPO}:v2-rc")]
    r = docker_runner(images)
    sw.docker(make_ctx(tmp_path, runner=r, docker_superseded_repos=["registry.example.com/"]))
    assert not r.ran("docker", "rmi")


def test_if_containers_cannot_be_inspected_no_image_is_removed(tmp_path):
    images = [("new", iso(1 * DAY), go_time(1 * DAY), 300, f"{REPO}:v3"), ("old", iso(60 * DAY), go_time(30 * DAY), 200, f"{REPO}:v2")]
    r = docker_runner(images, used=["old"])
    r.answers[("docker", "inspect")] = (1, "")
    sw.docker(make_ctx(tmp_path, runner=r, docker_superseded_repos=["registry.example.com/"]))
    assert not r.ran("docker", "rmi")


# --- grok sessions -----------------------------------------------------------------------------------

def grok_tree(tmp_path):
    root = tmp_path / "home" / ".grok" / "sessions"
    old = root / "proj" / "sess-old"
    resumed = root / "proj" / "sess-resumed"
    fresh = root / "proj" / "sess-fresh"
    for d in (old, resumed, fresh):
        d.mkdir(parents=True)
        (d / "log.jsonl").write_bytes(b"0" * 4000)
        (d / "sub").mkdir()
        (d / "sub" / "more").write_text("m")
    age(old, 30 * DAY)
    age(resumed, 30 * DAY)
    os.utime(resumed / "sub" / "more", (NOW - 1 * H, NOW - 1 * H))   # written to an hour ago
    age(fresh, 1 * H)
    return root, old, resumed, fresh


def test_grok_sessions_are_archived_then_removed_and_the_archive_lists_them(tmp_path):
    import tarfile
    root, old, resumed, fresh = grok_tree(tmp_path)
    runner = Runner({("pgrep",): (1, "")})
    res = sw.grok_sessions(make_ctx(tmp_path, dry=True, runner=runner))
    assert old.exists() and res.items == 1 and "would archive 1 grok session dirs" in res.lines[0]
    assert not (tmp_path / "home" / ".grok" / "sessions-archive").exists()
    res = sw.grok_sessions(make_ctx(tmp_path, runner=runner))
    assert not old.exists() and resumed.exists() and fresh.exists()
    archives = list((tmp_path / "home" / ".grok" / "sessions-archive").glob("*.tar.gz"))
    assert len(archives) == 1 and (archives[0].stat().st_mode & 0o777) == 0o600
    with tarfile.open(archives[0]) as tf:
        names = {m.name for m in tf}
    assert {"proj/sess-old", "proj/sess-old/log.jsonl", "proj/sess-old/sub/more"} <= names
    assert not any("resumed" in n or "fresh" in n for n in names)
    assert "archived 1 grok session dirs" in res.lines[0] and res.bytes > 0


def test_nothing_is_removed_when_the_archive_does_not_verify(tmp_path, monkeypatch):
    root, old, *_ = grok_tree(tmp_path)
    monkeypatch.setattr(sw, "archive_sessions", lambda *a, **k: False)
    res = sw.grok_sessions(make_ctx(tmp_path, runner=Runner({("pgrep",): (1, "")})))
    assert old.exists() and "archive failed" in res.lines[0] and res.bytes == 0


def test_archive_sessions_fails_when_a_listed_file_is_missing_from_the_archive(tmp_path, monkeypatch):
    root, old, *_ = grok_tree(tmp_path)
    real_open = sw.tarfile.open

    class Dropping:
        """Reads the archive back as if one member never made it in."""
        def __init__(self, tf): self.tf = tf
        def __enter__(self): self.tf.__enter__(); return self
        def __exit__(self, *a): return self.tf.__exit__(*a)
        def __iter__(self): return (m for m in self.tf if not m.name.endswith("more"))

    def opener(*a, **k):
        tf = real_open(*a, **k)
        return Dropping(tf) if k.get("mode") == "r:gz" or (len(a) > 1 and a[1] == "r:gz") else tf

    monkeypatch.setattr(sw.tarfile, "open", opener)
    assert sw.archive_sessions(root, ["proj/sess-old"], tmp_path / "out" / "a.tar.gz") is False
    monkeypatch.setattr(sw.tarfile, "open", real_open)
    assert sw.archive_sessions(root, ["proj/sess-old"], tmp_path / "out" / "b.tar.gz") is True


def test_a_session_written_to_after_the_archive_began_is_put_back(tmp_path):
    root, old, *_ = grok_tree(tmp_path)
    mark = NOW - 10 * DAY   # the archive "began" 10 days ago: everything in old/ is older than that, except...
    os.utime(old / "log.jsonl", (NOW - 5 * DAY, NOW - 5 * DAY))
    removed, kept = sw.remove_archived(root, ["proj/sess-old"], mark, "t")
    assert (removed, kept) == (0, 1) and (old / "log.jsonl").exists(), "written after the mark: left in place"
    removed, kept = sw.remove_archived(root, ["proj/sess-old"], NOW, "t")
    assert (removed, kept) == (1, 0) and not old.exists()
    assert not list(root.glob(".teyla-sweep-*")), "the aside folder is gone"


def test_grok_running_means_no_archive_and_no_grok_dir_means_nothing(tmp_path):
    res = sw.grok_sessions(make_ctx(tmp_path))
    assert res.items == 0 and not res.skipped
    root, old, *_ = grok_tree(tmp_path)
    res = sw.grok_sessions(make_ctx(tmp_path, runner=Runner({("pgrep",): (0, "123\n")})))
    assert res.skipped == "grok is running" and old.exists()


# --- logs ------------------------------------------------------------------------------------------------

def test_old_claude_cli_logs_go_and_empty_folders_with_them(tmp_path):
    root = tmp_path / "home" / "Library" / "Caches" / "claude-cli-nodejs"
    old, new = root / "proj" / "old.log", root / "proj2" / "new.log"
    for f in (old, new):
        f.parent.mkdir(parents=True)
        f.write_bytes(b"0" * 300)
    age(old, 30 * DAY)
    age(new, 1 * DAY)
    res = sw.claude_logs(make_ctx(tmp_path, dry=True))
    assert old.exists() and res.bytes == 300 and res.items == 1
    sw.claude_logs(make_ctx(tmp_path))
    assert not old.exists() and not old.parent.exists() and new.exists() and root.exists()


def test_big_logs_are_cut_to_their_last_20000_lines_in_place(tmp_path):
    logs = tmp_path / "home" / "Library" / "Logs"
    logs.mkdir(parents=True)
    big, small, other = logs / "a-routine.log", logs / "small.log", logs / "notes.txt"
    big.write_text("".join(f"line {i:06d}\n" for i in range(150_000)))   # ~1.6 MB
    small.write_text("tiny\n")
    other.write_text("".join(f"x{i}\n" for i in range(300_000)))
    inode = big.stat().st_ino
    before = big.stat().st_size
    res = sw.routine_logs(make_ctx(tmp_path, dry=True, sweep_log_max_mb=1))
    assert big.stat().st_size == before and res.items == 1 and "would trim a-routine.log" in res.lines[0]
    res = sw.routine_logs(make_ctx(tmp_path, sweep_log_max_mb=1))
    lines = big.read_text().splitlines()
    assert len(lines) == 20000 and lines[0] == "line 130000" and lines[-1] == "line 149999"
    assert big.stat().st_ino == inode, "trimmed in place: the writer's descriptor stays valid"
    assert small.read_text() == "tiny\n" and len(other.read_text().splitlines()) == 300_000
    assert res.bytes == before - big.stat().st_size


# --- the run -------------------------------------------------------------------------------------------------

def test_temp_mode_runs_only_the_temp_categories_and_is_silent_when_idle(tmp_path):
    runner = Runner(tools={"uv"})
    ctx = make_ctx(tmp_path, runner=runner)
    rep = sw.run(temp_only=True, ctx=ctx)
    assert [c["name"] for c in rep["categories"]] == ["temp builds", "release leftovers"]
    assert rep["lines"] == [] and runner.calls == []


def test_a_full_dry_run_touches_nothing_and_reports_every_category(tmp_path):
    d = derived_dir(tmp_path / "tmp")
    rep = sw.run(ctx=make_ctx(tmp_path, dry=True))
    assert [c["name"] for c in rep["categories"]] == [n for n, _, _ in sw.CATEGORIES]
    assert (d / "Build").exists() and rep["dry"] and rep["total"] > 0
    assert rep["lines"][0].startswith("start:") and any(line.startswith("done (dry)") for line in rep["lines"])
    assert any(line.startswith("simulators: skipped") for line in rep["lines"])
    assert sw.sweepable(ctx=make_ctx(tmp_path, dry=True)) == [{"name": "temp builds", "bytes": rep["total"], "items": 1}]


def test_a_failing_category_does_not_stop_the_others(tmp_path, monkeypatch):
    def boom(ctx):
        raise RuntimeError("nope")

    monkeypatch.setattr(sw, "CATEGORIES", (("a", boom, True), ("b", lambda c: sw.Result("b", bytes=5), True)))
    rep = sw.run(ctx=make_ctx(tmp_path, dry=True))
    assert rep["total"] == 5 and any("a: skipped — failed: RuntimeError" in line for line in rep["lines"])


def test_one_sweep_at_a_time_and_a_dead_owners_lock_is_taken_over(tmp_path, monkeypatch):
    lock = storage.state_dir("sweep.lock")
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()))
    rep = sw.run(ctx=make_ctx(tmp_path))
    assert rep["busy"] and "another sweep is running" in rep["lines"][0] and rep["categories"] == []
    assert sw.run(temp_only=True, ctx=make_ctx(tmp_path))["lines"] == [], "the hourly run stays quiet"
    (lock / "pid").write_text("2147483646")
    rep = sw.run(ctx=make_ctx(tmp_path))
    assert not rep["busy"] and not lock.exists(), "taken over, then released"


def test_a_lock_without_a_pid_yet_is_a_sweep_starting_unless_it_is_stale(tmp_path):
    lock = storage.state_dir("sweep.lock")
    lock.mkdir(parents=True)
    rep = sw.run(ctx=make_ctx(tmp_path))
    assert rep["busy"] and lock.exists(), "a second sweep must not remove a lock just made"
    old = time.time() - 2 * sw.LOCK_GRACE_S
    os.utime(lock, (old, old))
    rep = sw.run(ctx=make_ctx(tmp_path))
    assert not rep["busy"] and not lock.exists()


def test_trim_log_leaves_a_file_that_grew_after_the_snapshot(tmp_path, monkeypatch):
    log = tmp_path / "r.log"
    log.write_bytes(b"".join(b"line %d\n" % i for i in range(50)))
    real_tail = sw._tail

    def tail_then_append(path, keep_lines=sw.KEEP_LOG_LINES):
        t = real_tail(path, keep_lines)
        with path.open("ab") as f:
            f.write(b"written during the trim\n")
        return t

    monkeypatch.setattr(sw, "_tail", tail_then_append)
    assert sw.trim_log(log, keep_lines=5) == 0
    assert log.read_bytes().endswith(b"written during the trim\n") and b"line 0\n" in log.read_bytes()


def test_cmd_sweep_logs_a_real_run_but_not_a_dry_one(tmp_path, capsys):
    args = argparse.Namespace(action="sweep", dry=True, temp=False, json=False, quiet=False)
    ctxs = [make_ctx(tmp_path, dry=True), make_ctx(tmp_path)]
    import teyla.storage_sweep as mod
    orig = mod.make_ctx
    try:
        mod.make_ctx = lambda cfg=None, dry=False, now=None: ctxs.pop(0)
        assert sw.cmd_sweep(args, {}) == 0
        assert "done (dry)" in capsys.readouterr().out and not sw.log_path().exists()
        args.dry = False
        sw.cmd_sweep(args, {})
        assert "done: removed" in capsys.readouterr().out
        text = sw.log_path().read_text()
        assert sw.log_path() == tmp_path / "home" / "Library" / "Logs" / "teyla-sweep.log" and "start:" in text
        mod.make_ctx = lambda cfg=None, dry=False, now=None: make_ctx(tmp_path)
        args.quiet = True
        sw.cmd_sweep(args, {})
        assert capsys.readouterr().out == ""
        args.quiet, args.json = False, True
        sw.cmd_sweep(args, {})
        assert json.loads(capsys.readouterr().out)["dry"] is False
    finally:
        mod.make_ctx = orig


def test_the_storage_report_lists_sweepable_bytes_and_booted_simulators(tmp_path):
    rep = {"disk": {"free": 10 * GIB, "total": 100 * GIB, "free_fraction": 0.1}, "settings": storage.settings({}),
           "worktrees": [], "artifacts": [], "derived": []}
    sim_status = {"booted": [{"udid": "0000000A-0000-4000-8000-000000000000", "name": "Phone", "in_use": False, "idle_min": 42}],
                  "error": None}
    text = storage.render(rep, [], ["Phone"], [], sim_status, [{"name": "temp builds", "bytes": 3 * GIB, "items": 2}])
    assert "sweepable" in text and "3.0G  temp builds (2)" in text
    assert "booted simulators (1" in text and "idle 42m" in text
    assert "simulator(s) booted" not in text, "the plain RAM line is replaced by the section"
    plain = storage.render(rep, [], ["Phone"], [])
    assert "sweepable" not in plain and "1 simulator(s) booted" in plain

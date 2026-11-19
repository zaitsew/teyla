"""`teyla storage offload`: move the heavy folders to an external drive, one at a time, and leave a symlink.

    teyla storage offload --to /Volumes/External                 # dry run: what would move, what is refused and why
    teyla storage offload --to /Volumes/External --apply         # move, one path at a time
    teyla storage offload --undo ~/.gradle/caches                # copy a moved path back and remove the link
    teyla storage offload --recover | --finalize                 # finish or roll back after a crash; delete kept originals

Candidates are the fixed list in `volumes.HEAVY` under the home folder: no other path can be named. Nothing is
read or written unless the command is run, and a machine that never runs it sees no change.

The protocol per path (nothing runs in parallel, and each step is journaled in `~/.teyla/state/offload.json`
before it happens, so a crash leaves a state `--recover` can read):

    1. refuse the path if anything uses it, if it sits in a git repository, holds a file that may be a secret,
       holds a mount point, is already a link, or if the drive is not a writable, ownership-enabled mount on
       another device with room for it. An answer that could not be read counts as "unknown", and unknown refuses.
    2. copy to `<drive>/teyla/<name>.partial` (`ditto` on macOS, `cp -a` elsewhere); never over an existing path.
    3. verify: the same count of files, folders and links, the same bytes, and the same digest of every relative
       path, type, size and link target; and the source scanned again: a writer that started mid-copy fails it.
    4. rename the copy into place, then the original aside (`<path>.teyla-offload-<time>`), then make the symlink.
    5. smoke check for that kind through the link.
    6. only then delete the original (`--keep` keeps it until `--finalize`).

Any failure before step 6 restores the original: the link is removed, the original renamed back, the copy deleted.
The original is never deleted before the smoke check passes.
"""
from __future__ import annotations

import contextlib
import datetime
import fnmatch
import hashlib
import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys

from . import storage, volumes

# HEAVY name -> (slug on the drive, kind of smoke check, may hold app data that exists nowhere else)
KINDS = {
    "iOS simulators": ("ios-simulators", "sim", True),
    "Xcode DerivedData": ("xcode-derived-data", "derived", False),
    "Android SDK": ("android-sdk", "sdk", False),
    "Android virtual devices": ("android-avd", "avd", True),
    "Gradle caches": ("gradle-caches", "gradle", False),
    "Gradle wrapper": ("gradle-wrapper", "gradle", False),
}
SECRETS = ("gradle.properties", "*.keystore", "*.jks", "adbkey*", ".env*", "*.p8", "*.p12")
BUSY_COMMANDS = ("xcodebuild", "swift-build", "swift-frontend", "swift-test", "XCBBuildService", "SWBBuildService",
                 "qemu-system", "gradlew", "GradleDaemon", "GradleWrapperMain", "org.gradle.launcher", "/emulator/emulator",
                 "kotlin-compiler", "KotlinCompileDaemon")
ASIDE = ".teyla-offload-"
SPACE_MARGIN = 1.1
SMOKE_TIMEOUT_S = 30
MOD = 1 << 128


class Refused(Exception):
    pass


class Failed(Exception):
    pass


def _tag(path: str) -> str:
    return volumes._short(path)


# --- reading a tree ------------------------------------------------------------------------------------------

class Tree:
    """What a tree holds, in constant memory: counts, bytes, and an order-independent digest of every entry."""

    def __init__(self):
        self.files = self.dirs = self.links = self.bytes = 0
        self.digest = 0
        self.tdigest = 0                  # file mtimes: only comparable between two scans of the same tree
        self.escapes: list[str] = []
        self.secrets: list[str] = []
        self.git: list[str] = []
        self.mounts: list[str] = []

    def key(self):
        return (self.files, self.dirs, self.links, self.bytes, self.digest)

    def __eq__(self, other):
        return isinstance(other, Tree) and self.key() == other.key()

    def unchanged_since(self, other: "Tree") -> bool:
        """Same manifest and the same modification times: nothing was written in between."""
        return self == other and self.tdigest == other.tdigest

    def add_time(self, rel: str, mtime_ns: int):
        h = hashlib.sha1(f"{rel}\0{mtime_ns}".encode("utf-8", "surrogateescape")).digest()
        self.tdigest = (self.tdigest + int.from_bytes(h[:16], "big")) % MOD

    def add(self, rel: str, kind: str, size: int, link: str = ""):
        h = hashlib.sha1(f"{rel}\0{kind}\0{size}\0{link}".encode("utf-8", "surrogateescape")).digest()
        self.digest = (self.digest + int.from_bytes(h[:16], "big")) % MOD


def scan_tree(root: str) -> Tree:
    """Walk `root` without following links. Anything that cannot be read raises Refused: unknown is not "unused"."""
    t = Tree()
    try:
        dev = os.lstat(root).st_dev
    except OSError as e:
        raise Refused(f"cannot read {_tag(root)}: {e.strerror or e}")
    stack = [("", root)]
    while stack:
        rel, d = stack.pop()
        try:
            it = list(os.scandir(d))
        except OSError as e:
            raise Refused(f"cannot read {_tag(d)}: {e.strerror or e}")
        for e in it:
            r = f"{rel}/{e.name}" if rel else e.name
            try:
                st = e.stat(follow_symlinks=False)
            except OSError as err:
                raise Refused(f"cannot read {_tag(e.path)}: {err.strerror or err}")
            if any(fnmatch.fnmatch(e.name, p) for p in SECRETS) and len(t.secrets) < 3:
                t.secrets.append(r)
            if e.is_symlink():
                t.links += 1
                target = os.readlink(e.path)
                t.add(r, "l", 0, target)
                if not os.path.isabs(target) and len(t.escapes) < 3:
                    inside = os.path.normpath(os.path.join(d, target))
                    if os.path.commonpath([inside, root]) != os.path.normpath(root):
                        t.escapes.append(r)
            elif e.is_dir(follow_symlinks=False):
                if st.st_dev != dev and len(t.mounts) < 3:
                    t.mounts.append(r)
                if e.name == ".git" and len(t.git) < 3:
                    t.git.append(r)
                t.dirs += 1
                t.add(r, "d", 0)
                stack.append((r, e.path))
            else:
                t.files += 1
                t.bytes += st.st_size
                t.add(r, "f", st.st_size)
                t.add_time(r, st.st_mtime_ns)
                if e.name == ".git" and len(t.git) < 3:
                    t.git.append(r)
    return t


# --- the journal -----------------------------------------------------------------------------------------------

def _journal_path() -> pathlib.Path:
    return storage.state_dir("offload.json")


def journal() -> list[dict]:
    try:
        return list(json.loads(_journal_path().read_text()).get("entries", []))
    except (OSError, ValueError):
        return []


def _save(entries: list[dict]) -> None:
    p = _journal_path()
    if not entries:
        p.unlink(missing_ok=True)
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"entries": entries}, indent=1))
    os.replace(tmp, p)


@contextlib.contextmanager
def _lock():
    """One offload at a time on this machine; a second one refuses instead of waiting."""
    try:
        import fcntl
    except ImportError:                                   # no flock: the journal check still refuses a second run
        yield
        return
    p = storage.state_dir("offload.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Refused("another `teyla storage offload` is running")
        yield


# --- the checks -------------------------------------------------------------------------------------------------

def _procs() -> list[str] | None:
    return storage.process_commands()


def _booted_sims() -> list[str] | None:
    """Names of booted simulators; None when simctl did not answer (storage.booted_simulators() turns that into "none")."""
    if not shutil.which("xcrun"):
        return []
    out = volumes._bounded(["xcrun", "simctl", "list", "devices", "booted", "-j"], SMOKE_TIMEOUT_S)
    if out is None:
        return None
    try:
        devs = json.loads(out).get("devices") or {}
    except ValueError:
        return None
    return [d.get("name", "?") for v in devs.values() for d in v if d.get("state") == "Booted"]


def busy(key: str) -> str:
    """Why the path is in use, "" when nothing is; a process list that cannot be read answers "unknown"."""
    if key == "sim":
        try:
            booted = _booted_sims()
        except Exception:
            booted = None
        if booted is None:
            return "could not list the booted simulators (unknown counts as in use)"
        if booted:
            return "a simulator is booted"
    procs = _procs()
    if procs is None:
        return "could not list the processes (unknown counts as in use)"
    for line in procs:
        for token in BUSY_COMMANDS:
            if token in line:
                return f"a running process uses it ({token})"
    return ""


def _ownership_disabled(volume: str) -> bool | None:
    """True when the volume ignores file owners; None when macOS did not answer in time. False off macOS."""
    if sys.platform != "darwin":
        return False
    out = volumes._bounded(["diskutil", "info", "-plist", volume], volumes.ADVICE_TIMEOUT_S)
    if out is None:
        return None
    try:
        return plistlib.loads(out.encode()).get("GlobalPermissionsEnabled") is False
    except Exception:
        return None


def check_target(to: str, size: int = 0) -> str:
    """Why the drive cannot take the data, "" when it can."""
    if not os.path.isdir(to):
        return f"{to} is not a folder"
    if not volumes.attached(to):
        return f"{to} is not a mounted drive on another device than the home folder"
    if volumes.mount_point(to) != os.path.realpath(to):
        return f"{to} is not the mount point of the drive ({volumes.mount_point(to)} is)"
    if not os.access(to, os.W_OK):
        return f"{to} is not writable by you"
    owned = _ownership_disabled(to)
    if owned is None:
        return "macOS did not say whether ownership is enabled on the drive (diskutil timed out)"
    if owned:
        return "ownership is disabled on the drive: `sudo diskutil enableOwnership` first (docs/LOW-ON-DISK.md)"
    if size:
        try:
            free = shutil.disk_usage(to).free
        except OSError as e:
            return f"cannot read the free space of {to}: {e.strerror or e}"
        if free < size * SPACE_MARGIN:
            return f"not enough room: needs {storage.human(int(size * SPACE_MARGIN))}, {storage.human(free)} free"
    return ""


def _in_git(path: str) -> bool:
    p = os.path.dirname(os.path.realpath(path))
    while p not in ("", os.sep):
        if os.path.exists(os.path.join(p, ".git")):
            return True
        p = os.path.dirname(p)
    return False


class Row:
    def __init__(self, name, key, slug, app_data, path):
        self.name, self.key, self.slug, self.app_data, self.path = name, key, slug, app_data, path
        self.status = "move"        # move | skip | refused
        self.reason = ""
        self.tree: Tree | None = None

    @property
    def size(self) -> int:
        return self.tree.bytes if self.tree else 0

    def dest(self, to: str) -> str:
        return os.path.join(to, "teyla", self.slug)


def plan(to: str, *, with_app_data: bool = False, only: str = "", root: pathlib.Path | None = None) -> list[Row]:
    rows = []
    base = root or volumes.home()
    for name, rel, _kinds in volumes.HEAVY:
        slug, key, app_data = KINDS[name]
        if only and only not in (slug, key, name.lower()):
            continue
        r = Row(name, key, slug, app_data, str(base / rel))
        rows.append(r)
        if not os.path.lexists(r.path):
            r.status, r.reason = "skip", "not present"
            continue
        if volumes._first_link(base, rel):
            r.status, r.reason = "skip", "already a symlink"
            continue
        if app_data and not with_app_data:
            r.status, r.reason = "refused", "may hold app data that exists nowhere else: pass --with-app-data to move it"
            continue
        try:
            r.tree = scan_tree(r.path)
        except Refused as e:
            r.status, r.reason = "refused", str(e)
            continue
        why = (("inside a git repository" if _in_git(r.path) else "")
               or (f"contains a git repository ({r.tree.git[0]})" if r.tree.git else "")
               or (f"holds a file that may be a secret ({r.tree.secrets[0]})" if r.tree.secrets else "")
               or (f"holds a relative symlink that leaves the folder ({r.tree.escapes[0]}); it would break on the drive" if r.tree.escapes else "")
               or (f"holds a mount point ({r.tree.mounts[0]})" if r.tree.mounts else "")
               or ("is on the same device as the drive" if volumes._same_device(r.path, to) else "")
               or check_target(to, r.tree.bytes)
               or ("the destination exists already" if os.path.lexists(r.dest(to)) else ""))
        if not why and (b := busy(key)):
            why = f"in use: {b}"
        if why:
            r.status, r.reason = "refused", why
    return rows


# --- smoke checks -----------------------------------------------------------------------------------------------

def _sim_count() -> int | None:
    out = volumes._bounded(["xcrun", "simctl", "list", "devices", "-j"], SMOKE_TIMEOUT_S)
    if out is None:
        return None
    try:
        return sum(len(v) for v in json.loads(out).get("devices", {}).values())
    except ValueError:
        return None


def _listing(path: str) -> list[str]:
    return sorted(os.listdir(path))


def baseline(key: str, path: str):
    """What the smoke check compares against, read before the path is touched."""
    if key == "sim":
        return _sim_count()
    if key == "avd":
        return _listing(path)
    return None


def smoke(key: str, path: str, before) -> str:
    """"" when the path works through its new link, else why not."""
    try:
        names = _listing(path)
        if key == "sim":
            now = _sim_count()
            return "" if now is not None and now == before else f"simctl lists {now} devices, {before} before"
        if key == "avd":
            return "" if names == before else "the list of virtual devices changed"
        if key == "sdk":
            adb = os.path.join(path, "platform-tools", "adb")
            if os.path.exists(adb) and volumes._bounded([adb, "version"], SMOKE_TIMEOUT_S) is None:
                return "adb does not run"
            return ""
        if key == "gradle":
            probe = os.path.join(path, f".teyla-probe-{os.getpid()}")
            with open(probe, "w") as f:
                f.write("x")
            os.unlink(probe)
            return ""
        if names:
            os.stat(os.path.join(path, names[0]), follow_symlinks=False)
        return ""
    except OSError as e:
        return f"{e.strerror or e}"


# --- the move ------------------------------------------------------------------------------------------------------

def _copy(src: str, dst: str) -> None:
    if sys.platform == "darwin" and shutil.which("ditto"):
        cmd = ["ditto", src, dst]
    else:
        cmd = ["cp", "-a", src, dst]
    r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0:
        raise Failed(f"copy failed: {r.stderr.decode('utf-8', 'replace').strip()[:200]}")


def _rm(p: str) -> None:
    if os.path.islink(p):
        os.unlink(p)
    elif os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=False)
    elif os.path.lexists(p):
        os.unlink(p)


def _link_works(path: str, dest: str) -> bool:
    """The link at `path` points at `dest`, which is there and readable (a pulled drive makes this False)."""
    try:
        return os.path.islink(path) and os.path.realpath(path) == os.path.realpath(dest) and os.path.isdir(dest) \
            and bool(_listing(dest) is not None)
    except OSError:
        return False


def _missing_on_drive(aside: str, dest: str) -> str:
    """The first path of the kept original that the drive copy no longer has ("" when all are there). New files
    and changed contents are fine: the copy has been in use."""
    stack = [""]
    try:
        while stack:
            rel = stack.pop()
            for ent in os.scandir(os.path.join(aside, rel)):
                r = os.path.join(rel, ent.name)
                d = os.path.join(dest, r)
                if ent.is_symlink():
                    ok = os.path.islink(d)
                elif ent.is_dir(follow_symlinks=False):
                    ok = os.path.isdir(d) and not os.path.islink(d)
                    if ok:
                        stack.append(r)
                else:                                   # a dangling link is not a file with data
                    ok = os.path.isfile(d) and not os.path.islink(d)
                if not ok:
                    return r
    except OSError as err:
        return f"(cannot read: {err.strerror or err})"
    return ""


def _dest_intact(e: dict) -> bool:
    """The drive copy still has the manifest the original had when it was copied."""
    try:
        return _link_works(e["path"], e["dest"]) and list(scan_tree(e["dest"]).key()) == list(e["tree"])
    except (Refused, KeyError, TypeError):
        return False


def _tree_is_whole(p: str, e: dict) -> bool:
    """`p` still has the manifest the original had when it was copied (a half-deleted original does not)."""
    try:
        return list(scan_tree(p).key()) == list(e["tree"])
    except (Refused, OSError, KeyError, TypeError):
        return False


def _recover_entry(e: dict) -> list[str]:
    """Return the path to a working state from wherever the journal says it stopped. The original is only
    ever removed when the drive copy is proven intact."""
    path, aside, dest, state = e["path"], e["aside"], e["dest"], e["state"]
    out = []
    if state == "undoing":
        stage = e["stage"]
        if os.path.islink(path):
            _rm(stage)
            out.append(f"{_tag(path)} is still linked to the drive; removed the half-made copy")
        elif not os.path.lexists(path) and os.path.isdir(stage):
            os.rename(stage, path)
            out.append(f"finished moving {_tag(path)} back to the internal disk (the copy had been verified)")
        elif not os.path.lexists(path):
            os.symlink(dest, path)
            out.append(f"restored the link {_tag(path)} -> the drive")
        else:
            out.append(f"{_tag(path)} is back on the internal disk")
    elif state == "copying-back":
        _rm(e["stage"])
        out.append(f"removed the half-made copy of {_tag(path)}; it is still linked to the drive")
    elif state in ("copying",):
        _rm(dest + ".partial")
        out.append(f"removed the unfinished copy of {_tag(path)}; the original was never touched")
    elif state in ("copied",):
        _rm(dest)
        out.append(f"removed the copy of {_tag(path)}; the original was never touched")
    elif state == "smoked" and os.path.lexists(aside) and not _dest_intact(e) and not _tree_is_whole(aside, e):
        e["stuck"] = True
        out.append(f"{_tag(path)}: neither the original ({_tag(aside)}) nor the drive copy is whole; "
                   "nothing was deleted. Keep both and sort it out by hand")
    elif state in ("asiding", "asided", "linked") or (state == "smoked" and os.path.lexists(aside) and not _dest_intact(e)):
        if os.path.islink(path):
            os.unlink(path)
        if not os.path.lexists(path) and os.path.exists(aside):
            os.rename(aside, path)
        if os.path.lexists(path) and not os.path.islink(path):
            _rm(dest)                                   # the original is back: the copy is not needed
            out.append(f"restored {_tag(path)} from its original and removed the copy on the drive")
        else:
            out.append(f"could not restore {_tag(path)}: no original found; the copy on the drive was left in place")
    elif state == "smoked":
        if os.path.lexists(aside):
            _rm(aside)
            out.append(f"deleted the original of {_tag(path)} (the drive copy matches it)")
        else:
            out.append(f"the original of {_tag(path)} was already deleted; the copy on the drive is the only one")
    return out


def _forget(entries: list[dict], e: dict) -> list[dict]:
    return [x for x in entries if x is not e and x.get("id") != e.get("id")]


def move_one(row: Row, to: str, *, keep: bool = False, say=print) -> None:
    """Move one path. Raises Failed after restoring the original."""
    path, dest = row.path, row.dest(to)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    e = {"id": f"{row.slug}-{stamp}", "path": path, "key": row.key, "dest": dest, "aside": f"{path}{ASIDE}{stamp}",
         "state": "copying", "keep": keep}
    # Checks that must not leave a journal entry: a rollback only removes what this run made.
    try:
        before = scan_tree(path)
    except Refused as err:
        raise Failed(str(err))
    if before.escapes:
        raise Failed(f"it holds a relative symlink that leaves the folder ({before.escapes[0]})")
    if os.path.lexists(dest) or os.path.lexists(dest + ".partial"):
        raise Failed("the destination exists already")
    e["tree"] = list(before.key())
    entries = journal() + [e]
    _save(entries)

    def step(state: str):
        e["state"] = state
        _save(entries)
    try:
        base = baseline(row.key, path)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        say(f"  copying {storage.human(before.bytes)} …")
        _copy(path, dest + ".partial")
        if not scan_tree(path).unchanged_since(before):
            raise Failed("the source changed while it was copied: something is writing to it")
        if scan_tree(dest + ".partial") != before:
            raise Failed("the copy differs from the original (files, bytes or names)")
        why = check_target(to)
        if why:
            raise Failed(f"the drive changed during the copy: {why}")
        os.rename(dest + ".partial", dest)
        step("copied")
        why = busy(row.key)
        if why:
            raise Failed(f"in use at the moment of the switch: {why}")
        step("asiding")
        os.rename(path, e["aside"])
        step("asided")
        if not scan_tree(e["aside"]).unchanged_since(before):
            raise Failed("the source changed while it was copied: something is writing to it")
        os.symlink(dest, path)
        step("linked")
        why = smoke(row.key, path, base)
        if why:
            raise Failed(f"the smoke check failed: {why}")
        step("smoked")
    except BaseException as err:
        _save(entries)
        for line in _recover_entry(e):
            say(f"  {line}")
        _save(_forget(entries, e))
        if isinstance(err, (Failed, Refused)):
            raise Failed(str(err))
        raise
    if keep:
        e["state"] = "kept"
        _save(entries)
        say(f"  kept the original as {_tag(e['aside'])} until `teyla storage offload --finalize`")
        return
    _rm(e["aside"])
    _save(_forget(entries, e))


def undo(path: str, *, delete_drive_copy: bool = False, say=print) -> int:
    path = os.path.expanduser(path)
    if not os.path.islink(path):
        pending = [e for e in journal() if e["path"] == path]
        say(f"{_tag(path)} is not a symlink" + ("; an offload of it is unfinished: run `teyla storage offload --recover`"
                                                  if pending else ""))
        return 2
    src = os.path.realpath(path)
    stage = path + ".teyla-undo.partial"
    try:
        before = scan_tree(src)
    except Refused as e:
        say(f"refused: {e}")
        return 2
    free = shutil.disk_usage(os.path.dirname(path)).free
    if free < before.bytes * SPACE_MARGIN:
        say(f"refused: not enough room on the internal disk: needs {storage.human(int(before.bytes * SPACE_MARGIN))}, "
            f"{storage.human(free)} free")
        return 2
    keys = [KINDS[n][1] for n, rel, _k in volumes.HEAVY if str(volumes.home() / rel) == path]
    why = next((b for b in (busy(k) for k in keys) if b), "")
    if why:
        say(f"refused: in use: {why}")
        return 2
    if os.path.lexists(stage):
        say(f"refused: {_tag(stage)} exists already: remove it, it is a copy a crash left")
        return 2
    entry = {"id": f"undo-{os.path.basename(path)}", "path": path, "key": "", "dest": src, "aside": "", "stage": stage,
             "state": "copying-back", "keep": False}
    entries = journal() + [entry]
    try:
        _save(entries)
        say(f"  copying {storage.human(before.bytes)} back …")
        _copy(src, stage)
        if not scan_tree(src).unchanged_since(before) or scan_tree(stage) != before:
            raise Failed("the copy differs from the original, or the drive copy changed")
        entry["state"] = "undoing"
        _save(entries)
        os.unlink(path)
        os.rename(stage, path)
    except (Failed, Refused, OSError) as e:
        _rm(stage)
        if not os.path.lexists(path):
            os.symlink(src, path)
        _save(_forget(entries, entry))
        say(f"failed, nothing changed: {e}")
        return 1
    _save(_forget(entries, entry))
    say(f"moved {_tag(path)} back to the internal disk; the copy on the drive is {src}")
    if delete_drive_copy:
        try:
            changed = not scan_tree(src).unchanged_since(before)
        except Refused:
            changed = True
        if changed:
            say(f"kept {src}: it changed after it was copied")
        else:
            _rm(src)
            say(f"deleted {src}")
    return 0


def recover(say=print) -> int:
    entries = journal()
    if not entries:
        say("nothing to recover")
        return 0
    rest = []
    for e in entries:
        if e["state"] == "kept":
            rest.append(e)
            continue
        if e["state"] == "smoked" and e.get("keep") and _dest_intact(e):
            e["state"] = "kept"
            rest.append(e)
            say(f"kept the original of {_tag(e['path'])} as {_tag(e['aside'])} (--keep); `--finalize` deletes it")
            continue
        for line in _recover_entry(e):
            say(line)
        if e.get("stuck"):                      # nothing was resolved: keep the entry so doctor keeps naming it
            rest.append(e)
    _save(rest)
    return 0


def finalize(say=print) -> int:
    entries = journal()
    kept = [e for e in entries if e["state"] == "kept"]
    if not kept:
        say("no kept originals")
        return 0
    rest = [e for e in entries if e["state"] != "kept"]
    for e in kept:
        path = e["path"]
        why = "" if _link_works(path, e["dest"]) else "the link is gone or the drive copy is not there"
        if not why and e["key"] in ("sim", "avd"):
            gone = _missing_on_drive(e["aside"], e["dest"])
            why = f"the drive copy lacks {gone} that the original has" if gone else ""
        elif not why:
            why = smoke(e["key"], path, None)
        if why:
            say(f"kept {_tag(e['aside'])}: {why}; run `teyla storage offload --undo {_tag(path)}` or restore it by hand")
            rest.append(e)
            continue
        _rm(e["aside"])
        say(f"deleted the original {_tag(e['aside'])} ({_tag(path)} works through its link)")
    _save(rest)
    return 0


def problems() -> list[dict]:
    """Doctor rows: nothing unless an offload left something behind."""
    out = []
    for e in journal():
        if e["state"] == "kept":
            out.append({"level": "INFO", "name": "storage:offload",
                        "detail": f"{_tag(e['aside'])} is kept: the original of {_tag(e['path'])}, which now lives on a drive",
                        "fix": "teyla storage offload --finalize deletes it"})
        else:
            out.append({"level": "WARN", "name": "storage:offload",
                        "detail": f"an offload of {_tag(e['path'])} stopped at '{e['state']}'",
                        "fix": "teyla storage offload --recover"})
    return out


# --- the command ----------------------------------------------------------------------------------------------------

def render(rows: list[Row], to: str, apply: bool) -> list[str]:
    lines = [f"offload to {to} ({'moving' if apply else 'dry run: nothing moves; --apply moves'})"]
    total = 0
    for r in rows:
        size = storage.human(r.size) if r.tree else "-"
        verb = {"move": "move   ", "skip": "skip   ", "refused": "refused"}[r.status]
        tail = f"  -> {r.dest(to)}" if r.status == "move" else f"  ({r.reason})"
        lines.append(f"  {verb} {size:>8}  {r.name}  {_tag(r.path)}{tail}")
        if r.status == "move":
            total += r.size
    n = sum(1 for r in rows if r.status == "move")
    lines.append(f"{n} to move, {storage.human(total)} would leave the internal disk" if n else "nothing to move")
    return lines


def cmd_offload(args, cfg) -> int:
    if getattr(args, "recover", False):
        try:
            with _lock():
                return recover()
        except Refused as e:
            print(f"refused: {e}")
            return 2
    if getattr(args, "finalize", False):
        try:
            with _lock():
                return finalize()
        except Refused as e:
            print(f"refused: {e}")
            return 2
    if getattr(args, "undo", None):
        try:
            with _lock():
                return undo(args.undo, delete_drive_copy=getattr(args, "delete_drive_copy", False))
        except Refused as e:
            print(f"refused: {e}")
            return 2
    to = getattr(args, "to", None)
    if not to:
        print("usage: teyla storage offload --to <mount point of the drive> [--apply]   (dry run without --apply)")
        return 2
    to = os.path.realpath(os.path.expanduser(to))
    unfinished = [e for e in journal() if e["state"] != "kept"]
    if unfinished:
        print(f"an earlier offload stopped at '{unfinished[0]['state']}': run `teyla storage offload --recover` first")
        return 2
    why = check_target(to)
    if why:
        print(f"refused: {why}")
        return 2
    rows = plan(to, with_app_data=getattr(args, "with_app_data", False), only=getattr(args, "only", "") or "")
    for line in render(rows, to, args.apply):
        print(line)
    if not args.apply:
        return 0
    try:
        with _lock():
            for r in rows:
                if r.status != "move":
                    continue
                print(f"{r.name}:")
                try:
                    move_one(r, to, keep=getattr(args, "keep", False))
                except Failed as e:
                    print(f"  failed, the original is back: {e}")
                    return 1
                print(f"  moved: {storage.human(r.size)} off the internal disk")
    except Refused as e:
        print(f"refused: {e}")
        return 2
    return 0

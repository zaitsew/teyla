"""`teyla storage sweep` — the disk space agent work leaves behind in places no repo owns.

    teyla storage sweep [--dry] [--json] [--quiet]     everything below
    teyla storage sweep --temp                          only the temp build output (hourly)

`teyla storage clean` covers finished worktrees and build output inside repos; `storage sims`
covers idle simulators. This sweeps the rest, each category with its own age and process check
(no global "is anything building" gate: agents build around the clock):

- temp builds      Xcode DerivedData and .xcresult folders in /tmp, $TMPDIR and session scratchpads
                   idle >= sweep_temp_hours (24); only the parts Xcode wrote go, never anything
                   inside a git checkout. Under sweep_urgent_free_gb (20) free, 2 hours is enough.
- release leftovers  XcodeDistPipeline.* folders `xcodebuild -exportArchive` leaves in $TMPDIR,
                   idle >= sweep_release_days (3)
- simulators       devices named by storage.sim_prune_pattern, shut down and unused >= sweep_sim_days
                   (7); with the pattern empty (the default) none
- DerivedData      ~/Library/Developer/Xcode/DerivedData/<project> idle >= sweep_derived_days (14);
                   a folder without info.plist is a cache every project shares and stays
- codex runtimes   ~/.cache/codex-runtimes/codex-runtime-install-* an update left, >= sweep_codex_days (2)
- package caches   `uv cache prune`, `pnpm store prune`, `npm cache verify`, each its own tool
- docker           dangling images and build cache older than sweep_docker_days (7), and — for
                   repositories listed in storage.docker_superseded_repos only — tags a newer image
                   of the same repository replaced and no container uses; only if the daemon runs
- grok sessions    ~/.grok/sessions/<project>/<session> idle >= sweep_grok_days (14): tarred into
                   ~/.grok/sessions-archive/, the originals removed only after the archive is read
                   back and lists every file; skipped while grok is running
- claude cli logs  ~/Library/Caches/claude-cli-nodejs files older than sweep_log_days (14)
- routine logs     ~/Library/Logs/<sweep_log_glob> files over sweep_log_max_mb (50) cut to their last
                   20000 lines

Never touched: agent transcripts, the Trash, iOS runtimes, model caches, Docker volumes, worktrees.
`--dry` removes and runs nothing. When `ps` cannot list processes, nothing that needs "no process
uses it" is removed. One sweep runs at a time. The log is ~/Library/Logs/teyla-sweep.log.
"""
from __future__ import annotations

import calendar
import collections
import contextlib
import dataclasses
import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import tarfile
import time
from typing import Callable

from . import config, storage, storage_sims

GIB = 1024 ** 3
KEEP_LOG_LINES = 20000
# Xcode's own output inside a DerivedData folder; anything else in the same directory stays.
DD_PARTS = ("Build", "Logs", "Index.noindex", "ModuleCache.noindex", "CompilationCache.noindex",
            "SDKStatCaches.noindex", "SDKExplicitPrecompiledModules", "SourcePackages", "info.plist")
SMALL_BUILD = 100 * 1024 ** 2   # a temp build folder smaller than this shares one log line with the rest
MAX_FIND_DEPTH = 7
EXPORT_NAME = re.compile(r"XcodeDistPipeline\.~~~[A-Za-z0-9]{6}")
EXPORT_INSIDE = re.compile(r"Packages|Root|Symbols|entitlements~~~[A-Za-z0-9]{6}")
RESULT_BUNDLE_INSIDE = {"Info.plist", "Data"}


def settings(cfg: dict | None = None) -> dict:
    ci = storage.conf_int
    return {"temp_hours": ci(cfg, "sweep_temp_hours", 24), "release_days": ci(cfg, "sweep_release_days", 3),
            "urgent_free_gb": ci(cfg, "sweep_urgent_free_gb", 20), "sim_days": ci(cfg, "sweep_sim_days", 7),
            "derived_days": ci(cfg, "sweep_derived_days", 14), "codex_days": ci(cfg, "sweep_codex_days", 2),
            "grok_days": ci(cfg, "sweep_grok_days", 14), "log_days": ci(cfg, "sweep_log_days", 14),
            "docker_days": ci(cfg, "sweep_docker_days", 7), "log_max_mb": ci(cfg, "sweep_log_max_mb", 50),
            "log_glob": storage.conf_str(cfg, "sweep_log_glob", "*.log") or "*.log",
            "sim_pattern": storage.conf_str(cfg, "sim_prune_pattern", ""),
            "docker_repos": storage.conf_list(cfg, "docker_superseded_repos")}


def log_path() -> pathlib.Path:
    return pathlib.Path.home() / "Library" / "Logs" / "teyla-sweep.log"


# --- the context: everything a category reads from the machine --------------------------------

def _tool_path() -> str:
    """launchd starts jobs with a bare PATH; the package managers live in user directories."""
    home = pathlib.Path.home()
    extra = [str(home / ".local" / "bin"), str(home / ".bun" / "bin")]
    nvm = sorted((home / ".nvm" / "versions" / "node").glob("*/bin"))
    if nvm:
        extra.append(str(nvm[-1]))
    extra += ["/opt/homebrew/bin", "/usr/local/bin"]
    have = os.environ.get("PATH", "").split(os.pathsep)
    return os.pathsep.join(have + [p for p in extra if p not in have])


def run_command(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "PATH": _tool_path()})
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError as e:
        return 127, str(e)
    return r.returncode, r.stdout + r.stderr


def have_tool(name: str) -> bool:
    return shutil.which(name, path=_tool_path()) is not None


def default_tmp_roots() -> list[pathlib.Path]:
    roots = []
    for p in (pathlib.Path("/tmp"), pathlib.Path(os.environ.get("TMPDIR") or "/tmp")):
        real = pathlib.Path(os.path.realpath(p))
        if real.is_dir() and real not in roots:
            roots.append(real)
    return roots


@dataclasses.dataclass
class Ctx:
    cfg: dict
    now: float
    home: pathlib.Path
    dry: bool
    free: int
    tmp_roots: list
    procs: list | None
    run: Callable = run_command
    have: Callable = have_tool
    du: Callable = storage.du
    uid: int = dataclasses.field(default_factory=os.getuid)

    def named(self, path) -> bool:
        """A live process names `path` on its command line (as /tmp/x or /private/tmp/x). Unknown
        process list: assume yes."""
        if self.procs is None:
            return True
        p = str(path)
        needles = {p, p.removeprefix("/private")}
        return any(n in line for n in needles for line in self.procs)

    def size(self, *paths) -> int:
        return sum(self.du(p) for p in paths)


def make_ctx(cfg: dict | None = None, dry: bool = False, now: float | None = None) -> Ctx:
    return Ctx(cfg=settings(cfg), now=time.time() if now is None else now, home=pathlib.Path.home(), dry=dry,
               free=storage.disk()["free"], tmp_roots=default_tmp_roots(), procs=storage.process_commands())


@dataclasses.dataclass
class Result:
    name: str
    bytes: int = 0
    items: int = 0
    lines: list = dataclasses.field(default_factory=list)
    skipped: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def _fmt(n: int) -> str:
    return storage.human(n)


def _verb(ctx: Ctx, did: str, would: str) -> str:
    return would if ctx.dry else did


# --- small file helpers -------------------------------------------------------------------------

def _rm(path) -> bool:
    """Remove a file, link or tree. A symlink is unlinked, never followed."""
    p = pathlib.Path(path)
    try:
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)
        return not os.path.lexists(p)
    except OSError:
        return False


def _any_newer(path, cutoff: float, include_self: bool = True) -> bool:
    """Something at or under `path` changed after `cutoff`."""
    if include_self and storage._mtime(path) > cutoff:
        return True
    for dirpath, dirnames, filenames in os.walk(path):
        for n in dirnames + filenames:
            try:
                if os.lstat(os.path.join(dirpath, n)).st_mtime > cutoff:
                    return True
            except OSError:
                pass
    return False


def idle(ctx: Ctx, d, minutes: float) -> bool:
    """Nothing under `d` changed for `minutes` and no live process names it."""
    return not _any_newer(d, ctx.now - minutes * 60) and not ctx.named(d)


def only_has(d, allowed) -> bool:
    try:
        names = os.listdir(d)
    except OSError:
        return False
    if isinstance(allowed, (set, frozenset)):
        return all(n in allowed for n in names)
    return all(allowed.fullmatch(n) for n in names)


def in_checkout(d, parts) -> bool:
    """A .git in `d` or any directory above it, or anywhere inside any of `parts`."""
    p = pathlib.Path(d)
    if any((x / ".git").exists() for x in (p, *p.parents)):
        return True
    for part in parts:
        for _, dirnames, filenames in os.walk(part):
            if ".git" in dirnames or ".git" in filenames:
                return True
    return False


def _age_days(ctx: Ctx, path) -> float:
    m = storage._mtime(path)
    return (ctx.now - m) / 86400 if m else 0.0


# --- temp builds ------------------------------------------------------------------------------

def _temp_candidates(roots, uid: int) -> list[pathlib.Path]:
    """`*.xcresult` and `Build` directories owned by `uid` under the roots, down to depth 7. A
    match is not descended into; .git, node_modules, *.noindex and *.xcarchive are never entered."""
    found, seen = [], set()
    for root in roots:
        root = str(root)
        base = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, _ in os.walk(root):
            depth = dirpath.rstrip(os.sep).count(os.sep) - base
            keep = []
            for n in dirnames:
                full = os.path.join(dirpath, n)
                if n in (".git", "node_modules") or n.endswith((".noindex", ".xcarchive")) or os.path.islink(full):
                    continue
                try:
                    mine = os.lstat(full).st_uid == uid
                except OSError:
                    continue
                if mine and (n.endswith(".xcresult") or n == "Build"):
                    if full not in seen:
                        seen.add(full)
                        found.append(pathlib.Path(full))
                    continue
                if depth + 1 < MAX_FIND_DEPTH:
                    keep.append(n)
            dirnames[:] = keep
    return found


def temp_builds(ctx: Ctx) -> Result:
    r = Result("temp builds")
    hours = 2 if ctx.free < ctx.cfg["urgent_free_gb"] * GIB else ctx.cfg["temp_hours"]
    minutes = hours * 60
    if hours != ctx.cfg["temp_hours"]:
        r.lines.append(f"under {ctx.cfg['urgent_free_gb']} GB free: temp build output idle {hours}h goes")
    small, small_dirs = [], []

    def gone(label: str, parts: list) -> None:
        size = ctx.size(*parts)
        if ctx.dry:
            r.lines.append(f"would remove {label} ({_fmt(size)})")
        elif all([_rm(p) for p in parts]):
            r.lines.append(f"removed {label} ({_fmt(size)})")
        else:
            r.lines.append(f"could not remove all of {label}")
            return
        r.bytes += size
        r.items += 1

    for p in _temp_candidates(ctx.tmp_roots, ctx.uid):
        if p.name.endswith(".xcresult"):
            d = p
            if not ((d / "Info.plist").is_file() and (d / "Data").is_dir() and only_has(d, RESULT_BUNDLE_INSIDE)):
                continue
            parts = [d]
        else:
            d = p.parent
            if not ((p / "Intermediates.noindex").is_dir() or (p / "Products").is_dir()):
                continue
            if not ((d / "Logs").is_dir() or (d / "info.plist").is_file()):
                continue
            parts = [d / x for x in DD_PARTS if os.path.lexists(d / x)]
        if not os.path.lexists(d) or in_checkout(d, parts) or not idle(ctx, d, minutes):
            continue
        # xcodebuild drops hundreds of tiny ResultBundle_*.xcresult into $TMPDIR: those share one
        # line, anything from 100 MB up gets its own.
        if ctx.size(*parts) >= SMALL_BUILD:
            gone(f"temp build {str(d).removeprefix('/private')}", parts)
            if not ctx.dry:
                with contextlib.suppress(OSError):
                    d.rmdir()   # gone only if Xcode's parts were all it held
        else:
            small += parts
            small_dirs.append(d)
    if small:
        gone(f"{len(small_dirs)} small temp build folders", small)
        if not ctx.dry:
            for d in small_dirs:
                with contextlib.suppress(OSError):
                    d.rmdir()
    return r


# --- release leftovers ----------------------------------------------------------------------

def release_leftovers(ctx: Ctx) -> Result:
    r = Result("release leftovers")
    days = 2 / 24 if ctx.free < ctx.cfg["urgent_free_gb"] * GIB else ctx.cfg["release_days"]
    left = []
    for root in ctx.tmp_roots:
        try:
            entries = sorted(pathlib.Path(root).iterdir())
        except OSError:
            continue
        for d in entries:
            if (EXPORT_NAME.fullmatch(d.name) and d.is_dir() and not d.is_symlink() and only_has(d, EXPORT_INSIDE)
                    and not in_checkout(d, [d]) and idle(ctx, d, days * 1440)):
                left.append(d)
    if left:
        size = ctx.size(*left)
        r.bytes, r.items = size, len(left)
        label = f"{len(left)} export leftovers ({_fmt(size)})"
        if ctx.dry:
            r.lines.append(f"would remove {label}")
        else:
            ok = sum(_rm(d) for d in left)
            r.lines.append(f"removed {label}" if ok == len(left) else f"removed {ok} of {label}")
    return r


# --- simulators -----------------------------------------------------------------------------

def simulators(ctx: Ctx) -> Result:
    r = Result("simulators")
    if not ctx.cfg["sim_pattern"]:
        r.skipped = "storage.sim_prune_pattern is empty: no device is ever deleted"
        return r
    devs = storage_sims.devices()
    if devs is None:
        r.skipped = "no simulators available"
        return r
    rows = storage_sims.prune(ctx.cfg["sim_pattern"], ctx.cfg["sim_days"], devs, ctx.procs, ctx.now, dry=ctx.dry,
                              root=ctx.home / "Library" / "Developer" / "CoreSimulator" / "Devices", du=ctx.du)
    for p in rows:
        if "error" in p:
            r.skipped = p["error"]
            continue
        if ctx.dry or p["deleted"]:
            r.bytes += p["bytes"]
            r.items += 1
        r.lines.append(f"{_verb(ctx, 'deleted' if p['deleted'] else 'could not delete', 'would delete')} simulator "
                       f"{p['name']} ({_fmt(p['bytes'])}), unused {p['idle_days']}d")
    return r


# --- Xcode DerivedData ----------------------------------------------------------------------

def derived_data(ctx: Ctx) -> Result:
    r = Result("DerivedData")
    root = ctx.home / "Library" / "Developer" / "Xcode" / "DerivedData"
    if not root.is_dir():
        return r
    for d in sorted(root.iterdir()):
        info = d / "info.plist"
        # info.plist is rewritten whenever the project is opened or a build starts, so a folder a
        # live build uses is never old. Without one it is a cache every project shares.
        if d.is_symlink() or not d.is_dir() or not info.is_file() or _age_days(ctx, info) < ctx.cfg["derived_days"]:
            continue
        if ctx.named(d):
            continue
        size = ctx.size(d)
        if ctx.dry or _rm(d):
            r.bytes += size
            r.items += 1
            r.lines.append(f"{_verb(ctx, 'removed', 'would remove')} DerivedData {d.name} ({_fmt(size)})")
        else:
            r.lines.append(f"could not remove DerivedData {d.name}")
    return r


# --- codex runtimes -------------------------------------------------------------------------

def codex_runtimes(ctx: Ctx) -> Result:
    r = Result("codex runtimes")
    root = ctx.home / ".cache" / "codex-runtimes"
    if not root.is_dir():
        return r
    for d in sorted(root.glob("codex-runtime-install-*")):
        if d.is_symlink() or not d.is_dir() or _age_days(ctx, d) < ctx.cfg["codex_days"] or ctx.named(d):
            continue
        size = ctx.size(d)
        if ctx.dry or _rm(d):
            r.bytes += size
            r.items += 1
            r.lines.append(f"{_verb(ctx, 'removed', 'would remove')} codex {d.name} ({_fmt(size)})")
    return r


# --- package caches -------------------------------------------------------------------------

PACKAGE_TOOLS = (("uv", ["uv", "cache", "prune"], ".cache/uv"),
                 ("pnpm", ["pnpm", "store", "prune"], "Library/pnpm"),
                 ("npm", ["npm", "cache", "verify"], ".npm"))


def package_caches(ctx: Ctx) -> Result:
    r = Result("package caches")
    for tool, cmd, rel in PACKAGE_TOOLS:
        if not ctx.have(tool):
            continue
        if ctx.dry:
            r.lines.append(f"would run: {' '.join(cmd)}")
            continue
        before = ctx.du(ctx.home / rel)
        rc, _ = ctx.run(cmd, 600)
        r.items += 1
        if rc == 0:
            freed = max(0, before - ctx.du(ctx.home / rel))
            r.bytes += freed
            r.lines.append(f"{' '.join(cmd)}: ok" + (f" ({_fmt(freed)})" if freed else ""))
        else:
            r.lines.append(f"{' '.join(cmd)}: failed (exit {rc})")
    return r


# --- docker ---------------------------------------------------------------------------------

_UNITS = {"B": 1, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9, "TB": 10 ** 12}


def _reclaimed(out: str) -> int:
    m = re.search(r"reclaimed space:\s*([\d.]+)\s*([kKMGT]?B)", out, re.I)
    return int(float(m.group(1)) * _UNITS.get(m.group(2).upper(), 1)) if m else 0


def _parse_time(text: str) -> float | None:
    """`2026-08-07 20:16:48.56 +0000 UTC`, or RFC 3339 `2026-08-07T20:16:48.5Z`, as epoch seconds (UTC)."""
    t = (text or "").strip().split(".")[0].split(" +")[0].replace("T", " ").rstrip("Z").strip()
    try:
        return float(calendar.timegm(_dt.datetime.strptime(t, "%Y-%m-%d %H:%M:%S").timetuple()))
    except ValueError:
        return None


def _repo_listed(repo: str, listed: list[str]) -> bool:
    return any((repo + "/").startswith(p.rstrip("/") + "/") for p in listed)


def superseded_images(ctx: Ctx) -> list[dict]:
    """Tags of the configured repositories that a newer image of the same repository replaced,
    that no container (running or stopped) uses, and that were pulled or tagged >= sweep_docker_days
    ago. Unreadable timestamps keep the image."""
    listed = ctx.cfg["docker_repos"]
    if not listed:
        return []
    rc, cids = ctx.run(["docker", "ps", "-aq"], 60)
    used = set()
    if rc == 0 and cids.split():
        rc2, out = ctx.run(["docker", "inspect", "--format", "{{.Image}}", *cids.split()], 60)
        if rc2 != 0:
            return []   # cannot tell what a container uses: touch nothing
        used = set(out.split())
    elif rc != 0:
        return []
    rc, ids = ctx.run(["docker", "images", "-q", "--no-trunc"], 60)
    if rc != 0:
        return []
    rows = []
    for i in sorted(set(ids.split())):
        # One inspect per image: a single image without a field fails a whole batch.
        rc, line = ctx.run(["docker", "image", "inspect", "--format",
                            "{{.Id}}|{{.Created}}|{{.Metadata.LastTagTime}}|{{.Size}}|{{join .RepoTags \" \"}}", i], 60)
        parts = line.strip().split("|")
        if rc != 0 or len(parts) != 5:
            continue
        iid, created, tagged, size, tags = parts
        c = _parse_time(created)
        if c is None:
            continue
        try:
            size_n = int(size)
        except ValueError:
            size_n = 0
        for tag in tags.split():
            rows.append({"repo": tag.rsplit(":", 1)[0], "created": c, "id": iid, "tagged": tagged, "size": size_n, "tag": tag})
    rows.sort(key=lambda x: (x["repo"], -x["created"]))
    out, kept, last = [], None, None
    cutoff = ctx.now - ctx.cfg["docker_days"] * 86400
    for x in rows:
        if x["repo"] != last:
            last, kept = x["repo"], x   # the newest of a repository stays
            continue
        if x["id"] == kept["id"] or x["created"] == kept["created"]:
            continue   # another tag of the newest image, or as new as it: neither replaced the other
        if not _repo_listed(x["repo"], listed) or x["id"] in used:
            continue
        t = _parse_time(x["tagged"])
        if t is None or t > cutoff:
            continue
        out.append(x)
    return out


def docker(ctx: Ctx) -> Result:
    r = Result("docker")
    if not ctx.have("docker"):
        r.skipped = "docker is not installed"
        return r
    if ctx.run(["docker", "info"], 10)[0] != 0:
        r.skipped = "the docker daemon is not running (never started by a sweep)"
        return r
    until = f"{ctx.cfg['docker_days'] * 24}h"
    if ctx.dry:
        r.lines.append(f"would run: docker image prune (dangling), docker builder prune --filter until={until}")
    else:
        for label, cmd in (("images", ["docker", "image", "prune", "-f"]),
                           ("build cache", ["docker", "builder", "prune", "-f", "--filter", f"until={until}"])):
            rc, out = ctx.run(cmd, 600)
            n = _reclaimed(out)
            r.bytes += n
            r.lines.append(f"docker {label}: " + (f"reclaimed {_fmt(n)}" if rc == 0 else f"failed (exit {rc})"))
    for x in superseded_images(ctx):
        if ctx.dry:
            r.bytes += x["size"]
            r.items += 1
            r.lines.append(f"would remove superseded docker image {x['tag']} ({_fmt(x['size'])})")
        elif ctx.run(["docker", "rmi", x["tag"]], 120)[0] == 0:
            r.bytes += x["size"]
            r.items += 1
            r.lines.append(f"removed superseded docker image {x['tag']} ({_fmt(x['size'])})")
    return r


# --- grok sessions: archive, never delete -------------------------------------------------------

def grok_candidates(root: pathlib.Path, now: float, days: int) -> list[str]:
    """`<project>/<session>` directories under `root` where nothing changed for `days`."""
    cutoff = now - days * 86400
    out = []
    try:
        projects = sorted(p for p in root.iterdir() if p.is_dir() and not p.is_symlink() and not p.name.startswith("."))
    except OSError:
        return []
    for proj in projects:
        for sess in sorted(proj.iterdir()):
            if sess.is_dir() and not sess.is_symlink() and not _any_newer(sess, cutoff):
                out.append(f"{proj.name}/{sess.name}")
    return out


def archive_sessions(root: pathlib.Path, rels: list[str], dest: pathlib.Path) -> bool:
    """Tar `rels` (relative to `root`) into `dest`, then read it back: it must open, decompress to
    the end, and list every file and directory it was meant to hold."""
    try:
        config.private_dir(dest.parent)   # session transcripts: this user only
        want = set()
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as tf:
            for rel in rels:
                tf.add(root / rel, arcname=rel)
                for dirpath, dirnames, filenames in os.walk(root / rel):
                    for n in dirnames + filenames:
                        want.add(os.path.relpath(os.path.join(dirpath, n), root))
                want.add(rel)
        with tarfile.open(dest, "r:gz") as tf:
            have = {m.name.rstrip("/") for m in tf}   # reading the headers decompresses every byte
        return want <= have
    except (OSError, tarfile.TarError, EOFError):
        return False


def remove_archived(root: pathlib.Path, rels: list[str], mark: float, tag: str) -> tuple[int, int]:
    """(removed, kept). Each session is renamed out of grok's reach first, then looked at: one written
    to since the archive began (`mark`) goes back untouched."""
    aside = root / f".teyla-sweep-{tag}"
    aside.mkdir(exist_ok=True)
    removed = kept = 0
    for rel in rels:
        t = aside / rel.replace("/", "_")
        try:
            os.rename(root / rel, t)
        except OSError:
            kept += 1
            continue
        if _any_newer(t, mark, include_self=False):
            os.rename(t, root / rel)
            kept += 1
        else:
            removed += _rm(t)
    with contextlib.suppress(OSError):
        aside.rmdir()
    return removed, kept


def grok_sessions(ctx: Ctx, mark: float | None = None) -> Result:
    r = Result("grok sessions")
    root = ctx.home / ".grok" / "sessions"
    if not root.is_dir():
        return r
    if ctx.run(["pgrep", "-x", "grok"], 10)[0] == 0:
        r.skipped = "grok is running"
        return r
    rels = grok_candidates(root, ctx.now, ctx.cfg["grok_days"])
    if not rels:
        return r
    size = ctx.size(*(root / x for x in rels))
    r.items = len(rels)
    archive_dir = ctx.home / ".grok" / "sessions-archive"
    if ctx.dry:
        r.bytes = size
        r.lines.append(f"would archive {len(rels)} grok session dirs ({_fmt(size)}) into {archive_dir}/")
        return r
    started = time.time() if mark is None else mark
    tgz = archive_dir / f"{time.strftime('%F-%H%M%S')}-{os.getpid()}.tar.gz"
    if not archive_sessions(root, rels, tgz):
        _rm(tgz)
        r.items = 0
        r.lines.append("grok archive failed; sessions left in place")
        return r
    removed, kept = remove_archived(root, rels, started, str(os.getpid()))
    arch = ctx.du(tgz)
    r.items = removed
    r.bytes = max(0, size - arch) if removed == len(rels) else 0
    r.lines.append(f"archived {len(rels)} grok session dirs ({_fmt(size)}) into {tgz} ({_fmt(arch)}); "
                   f"{removed} removed, {kept} resumed meanwhile and left in place")
    return r


# --- logs -----------------------------------------------------------------------------------

def claude_logs(ctx: Ctx) -> Result:
    r = Result("claude cli logs")
    cutoff = ctx.now - ctx.cfg["log_days"] * 86400
    for root in (ctx.home / "Library" / "Caches" / "claude-cli-nodejs", ctx.home / ".cache" / "claude-cli-nodejs"):
        if not root.is_dir():
            continue
        old = []
        for dirpath, _, filenames in os.walk(root):
            for n in filenames:
                p = os.path.join(dirpath, n)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if st.st_mtime < cutoff:
                    old.append((p, st.st_size))
        if not old:
            continue
        size = sum(s for _, s in old)
        if ctx.dry:
            r.bytes += size
            r.items += len(old)
            r.lines.append(f"would remove {len(old)} claude-cli logs older than {ctx.cfg['log_days']}d ({_fmt(size)})")
            continue
        freed = 0
        for p, s in old:
            try:
                os.unlink(p)
                freed += s
                r.items += 1
            except OSError:
                pass
        for dirpath, _, _ in os.walk(root, topdown=False):
            if dirpath != str(root):
                with contextlib.suppress(OSError):
                    os.rmdir(dirpath)   # only an empty one goes
        r.bytes += freed
        r.lines.append(f"removed claude-cli logs older than {ctx.cfg['log_days']}d ({_fmt(freed)})")
    return r


def _tail(path: pathlib.Path, keep_lines: int = KEEP_LOG_LINES) -> collections.deque:
    with path.open("rb") as f:
        return collections.deque(f, maxlen=keep_lines)


def trim_log(path: pathlib.Path, keep_lines: int = KEEP_LOG_LINES, dry: bool = False) -> int:
    """Cut `path` to its last `keep_lines` lines in place (the writer keeps its descriptor). Returns
    the bytes freed (with dry, the bytes that would be)."""
    before = path.stat().st_size
    tail = _tail(path, keep_lines)
    freed = max(0, before - sum(len(x) for x in tail))
    if not dry and freed:
        with path.open("r+b") as f:
            f.seek(0)
            f.writelines(tail)
            f.truncate()
    return freed


def routine_logs(ctx: Ctx) -> Result:
    r = Result("routine logs")
    logs = ctx.home / "Library" / "Logs"
    if not logs.is_dir():
        return r
    limit = ctx.cfg["log_max_mb"] * 1024 ** 2
    for f in sorted(logs.glob(ctx.cfg["log_glob"])):
        try:
            if f.is_symlink() or not f.is_file() or f.stat().st_size <= limit:
                continue
            size = f.stat().st_size
            freed = trim_log(f, dry=ctx.dry)
        except OSError:
            continue
        r.bytes += freed
        r.items += 1
        r.lines.append(f"{_verb(ctx, 'trimmed', 'would trim')} {f.name} ({_fmt(size)}) to its last {KEEP_LOG_LINES} lines"
                       + ("" if ctx.dry else f", {_fmt(freed)} freed"))
    return r


# --- the run ----------------------------------------------------------------------------------

# (name, function, part of --temp)
CATEGORIES = (("temp builds", temp_builds, True), ("release leftovers", release_leftovers, True),
              ("simulators", simulators, False), ("DerivedData", derived_data, False),
              ("codex runtimes", codex_runtimes, False), ("package caches", package_caches, False),
              ("docker", docker, False), ("grok sessions", grok_sessions, False),
              ("claude cli logs", claude_logs, False), ("routine logs", routine_logs, False))


class Busy(Exception):
    pass


@contextlib.contextmanager
def lock():
    """One sweep at a time: two would pick the same Grok sessions. A lock whose process is gone is taken over."""
    d = storage.state_dir("sweep.lock")
    d.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            d.mkdir()
            break
        except FileExistsError:
            try:
                pid = int((d / "pid").read_text().strip())
                os.kill(pid, 0)
            except (OSError, ValueError):
                _rm(d)   # no readable pid or no such process
                continue
            raise Busy(f"another sweep is running (pid {pid}, {d})") from None
    else:
        raise Busy(f"another sweep holds {d}")
    try:
        (d / "pid").write_text(str(os.getpid()))
        yield
    finally:
        _rm(d)


def run(cfg: dict | None = None, dry: bool = False, temp_only: bool = False, ctx: Ctx | None = None) -> dict:
    """Sweep. Returns {"dry", "temp_only", "free_before", "free_after", "total", "categories", "lines"}.
    A dry run touches nothing and takes no lock."""
    ctx = ctx or make_ctx(cfg, dry=dry)
    dry = ctx.dry
    lines, results = [], []

    def go():
        for name, fn, in_temp in CATEGORIES:
            if temp_only and not in_temp:
                continue
            try:
                res = fn(ctx)
            except Exception as e:  # noqa: BLE001 — one category must never stop the others
                res = Result(name, skipped=f"failed: {type(e).__name__}: {e}")
            results.append(res)
            lines.extend(res.lines)
            if res.skipped and not temp_only:
                lines.append(f"{name}: skipped — {res.skipped}")

    busy = ""
    if dry:
        go()
    else:
        try:
            with lock():
                go()
        except Busy as e:
            busy = str(e)
    total = sum(r.bytes for r in results)
    free_after = ctx.free if dry else storage.disk()["free"]
    out = []
    if busy:
        if not temp_only:
            out.append(busy + "; exiting")
    else:
        quiet_temp = temp_only and not total and not lines   # the hourly run says nothing when it did nothing
        if not quiet_temp:
            out.append(f"start: {_fmt(ctx.free)} free" + (" (dry)" if dry else "") + (" (--temp)" if temp_only else ""))
        out += lines
        if dry:
            out.append(f"done (dry): would free about {_fmt(total)}; {_fmt(ctx.free)} free now")
        elif not quiet_temp:
            out.append(f"done: removed {_fmt(total)}; {_fmt(free_after)} free, was {_fmt(ctx.free)}")
        if not temp_only:
            out.append("not touched: transcripts, the Trash, iOS runtimes, model caches, Docker volumes, worktrees "
                       "(see `teyla storage`)")
    return {"dry": dry, "temp_only": temp_only, "busy": bool(busy), "free_before": ctx.free, "free_after": free_after,
            "total": total, "categories": [r.as_dict() for r in results], "lines": out}


def write_log(lines: list[str]) -> None:
    if not lines:
        return
    stamp = time.strftime("%F %T")
    try:
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as f:
            f.writelines(f"{stamp} {line}\n" for line in lines)
    except OSError:
        pass


def sweepable(cfg: dict | None = None, ctx: Ctx | None = None) -> list[dict]:
    """A dry full sweep: [{name, bytes, items}] for each category that has something to give back."""
    rep = run(cfg, dry=True, ctx=ctx)
    return [{"name": c["name"], "bytes": c["bytes"], "items": c["items"]} for c in rep["categories"] if c["bytes"] or c["items"]]


# --- CLI ----------------------------------------------------------------------------------------

def cmd_sweep(args, cfg: dict) -> int:
    dry = getattr(args, "dry", False)
    rep = run(cfg, dry=dry, temp_only=getattr(args, "temp", False))
    if not dry:
        write_log(rep["lines"])
    if args.json:
        print(json.dumps(rep, indent=2))
    elif not args.quiet:
        for line in rep["lines"]:
            print(line)
    return 0

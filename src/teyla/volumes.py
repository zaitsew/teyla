"""External volumes: heavy folders that live on a drive that may not be attached.

Simulators, DerivedData, the Android SDK and the Gradle caches are often moved to an external
drive and left behind as symlinks. When the drive is absent the link dangles, and a tool that sees
"No such file" under it may delete the link and recreate the folder on the internal disk, which
then fills up without a sound. This module finds those links, says which dangle, and names the
drive, so that `teyla storage`, `teyla doctor`, the session-start hook and `teyla load` can report
the absence instead of a failing build discovering it.

It needs no config. A heavy path that is a symlink (or sits under one) is looked at; a plain folder
never is, so a machine with no drive sees no change at all. A link whose target is missing dangles on
any machine; a link whose target is on another device is "on <mount point>". Config only adds to that,
in `~/.teyla/config.toml`:

    [storage]
    volumes          = ["/Volumes/External"]   # also shown in `teyla storage`, attached or not
    volumes_required = ["/Volumes/External"]   # a drive that never leaves: its absence fails `teyla doctor`

An absent drive is a normal state for a laptop that leaves the desk: by default the hook and doctor say so
(exit 0) and only `teyla load --admit sim|build` refuses, for the kinds whose path dangles. Nothing in this
module writes to a heavy path, deletes a link or creates a folder; it writes `~/.teyla/volumes.list` (the
hook's input) and `~/.teyla/state/volumes.json` (the links it has seen), and only when there is a link.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import plistlib
import subprocess
import sys

from . import storage

# (name, path under the home folder, the `teyla load` kinds that cannot start without it).
HEAVY = (
    ("iOS simulators", "Library/Developer/CoreSimulator/Devices", ("sim",)),
    ("Xcode DerivedData", "Library/Developer/Xcode/DerivedData", ("build",)),
    ("Android SDK", "Library/Android/sdk", ("build",)),
    ("Android virtual devices", ".android/avd", ()),
    ("Gradle caches", ".gradle/caches", ("build",)),
    ("Gradle wrapper", ".gradle/wrapper", ("build",)),
)

OK, DANGLING, REPLACED = "ok", "dangling", "replaced"
DO_NOT = "Do not recreate these paths on the internal disk"
ADVICE_TIMEOUT_S = 8     # `diskutil` hung for minutes behind a system dialog: every macOS-only check is bounded


@dataclasses.dataclass
class Link:
    name: str
    path: str            # the heavy path, as the tools see it
    link_at: str         # the symlink on the way to it (the path itself, or a parent such as ~/.gradle)
    target: str          # where the heavy path points ("" when there is no link any more)
    volume: str          # the drive: its mount point, or the first missing folder when it is absent
    status: str          # ok | dangling | replaced
    absent: bool = False  # the drive is not there, rather than a target missing on a drive that is
    required: bool = False
    kinds: tuple = ()


def home() -> pathlib.Path:
    return pathlib.Path.home()


def _norm(v: str) -> str:
    return os.path.normpath(os.path.expanduser(v))


def _volume_list(cfg: dict | None, key: str) -> list[str]:
    out: list[str] = []
    for v in storage.conf_list(cfg, key):
        p = _norm(v)
        if os.path.isabs(p) and p != os.sep and p not in out:
            out.append(p)
    return out


def configured(cfg: dict | None = None) -> list[str]:
    """`[storage] volumes` and `volumes_required`: absolute, `~` expanded, no duplicates."""
    return list(dict.fromkeys(_volume_list(cfg, "volumes") + _volume_list(cfg, "volumes_required")))


def required(cfg: dict | None = None) -> list[str]:
    return _volume_list(cfg, "volumes_required")


def _inside(path: str, volume: str) -> bool:
    return path == volume or path.startswith(volume + os.sep)


def _dev(path: str) -> int:
    return os.stat(path).st_dev


def _same_device(a: str, b: str) -> bool:
    try:
        return _dev(a) == _dev(b)
    except OSError:
        return True      # unknown: not external


def mount_point(path: str) -> str:
    """The top of the filesystem `path` is on: climb while the parent has the same device. No `/Volumes`
    is assumed, so it works for /media/<user>/<drive> on Linux as it does for a macOS volume."""
    p = os.path.realpath(path)
    try:
        dev = _dev(p)
        while True:
            parent = os.path.dirname(p)
            if parent == p or _dev(parent) != dev:
                return p
            p = parent
    except OSError:
        return p


def attached(volume: str) -> bool:
    """The volume is there: a folder on a device other than the home folder's. A stub folder an agent made
    on the internal disk by `mkdir -p` through a dangling link is a folder, not a drive."""
    return os.path.isdir(volume) and not _same_device(volume, str(home()))


def _first_link(root: pathlib.Path, rel: str) -> str:
    """The first symlink on the way from `root` down to `root/rel`, itself included ("" when there is none)."""
    p = str(root)
    for part in rel.split("/"):
        p = os.path.join(p, part)
        if os.path.islink(p):
            return p
    return ""


def _target(path: str) -> str:
    """The link's target as written, made absolute, without resolving anything (the drive may be gone)."""
    raw = os.readlink(path)
    return os.path.normpath(raw if os.path.isabs(raw) else os.path.join(os.path.dirname(path), raw))


def _missing_volume(target: str) -> tuple[str, bool]:
    """(the drive a missing target was on, whether the drive itself is gone). The nearest folder that exists
    decides: on another device it is the drive and only the target is missing; on the home device the drive is
    the first folder that does not exist below it."""
    parts = target.split(os.sep)
    for i in range(len(parts), 0, -1):
        cand = os.sep.join(parts[:i]) or os.sep
        if os.path.exists(cand):
            if not _same_device(cand, str(home())):
                return mount_point(cand), False
            nxt = os.sep.join(parts[:i + 1]) if i < len(parts) else target
            return nxt, True
    return target, True


def state_path() -> pathlib.Path:
    return storage.state_dir() / "volumes.json"


def _remembered() -> dict:
    try:
        d = json.loads(state_path().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(rec: dict, before: dict) -> None:
    if rec == before:
        return
    try:
        f = state_path()
        if not rec:
            f.unlink(missing_ok=True)
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rec, indent=1, sort_keys=True))
    except OSError:
        pass


def links(cfg: dict | None = None, root: pathlib.Path | None = None, remember: bool = False) -> list[Link]:
    """Every heavy path that is a symlink to another device or to nothing (or sits under one), with its state.

    A link seen before (`remember=True` keeps a record in `~/.teyla/state/volumes.json`) that is now a plain
    folder while its drive is absent is `replaced`: the failure this module exists to catch, after the fact.
    No symlink on a heavy path and no record: an empty list, after a few `lstat` calls."""
    root = root or home()
    vols, req = configured(cfg), required(cfg)
    seen = _remembered() if remember else {}
    out: list[Link] = []
    now: dict = {}
    for name, rel, kinds in HEAVY:
        p = str(root / rel)
        at = _first_link(root, rel)
        if not at:
            v = seen.get(p)
            if v and not attached(v["volume"]):
                out.append(Link(name, p, v.get("link_at", p), "", v["volume"], REPLACED, True,
                                any(_inside(v["volume"], r) for r in req), kinds))
                now[p] = v                        # replaced stays replaced until the link is back or the drive is
            continue
        rest = os.path.relpath(p, at)
        target = _target(at) if rest == "." else os.path.normpath(os.path.join(_target(at), rest))
        cfg_vol = next((v for v in vols if _inside(target, v)), "")
        if os.path.exists(p):
            if cfg_vol:
                vol = cfg_vol
            elif _same_device(p, str(home())):
                continue                          # a link that stays on the internal disk is nobody's business
            else:
                vol = mount_point(p)
            link = Link(name, p, at, target, vol, OK, False)
        else:
            vol, gone = _missing_volume(target)
            if cfg_vol:
                vol, gone = cfg_vol, not attached(cfg_vol)
            link = Link(name, p, at, target, vol, DANGLING, gone)
        link.required = any(_inside(link.volume, r) for r in req)
        link.kinds = kinds
        out.append(link)
        now[p] = {"volume": link.volume, "link_at": at}
    if remember:
        _save(now, seen)
    return out


def broken(cfg: dict | None = None, kind: str | None = None, root: pathlib.Path | None = None) -> list[Link]:
    """The links that are not ok; with `kind`, only those a `teyla load --kind <kind>` needs."""
    return [l for l in links(cfg, root=root, remember=True) if l.status != OK and (kind is None or kind in l.kinds)]


def volume_rows(cfg: dict | None = None, root: pathlib.Path | None = None) -> list[dict]:
    """One row per drive that is configured or that a heavy path points into: its disk figures when attached,
    and the links into it. Empty when there is nothing to show (no config, no link)."""
    ls = links(cfg, root=root, remember=True)
    names = list(dict.fromkeys(configured(cfg) + [l.volume for l in ls]))
    rows = []
    for v in names:
        mine = [l for l in ls if l.volume == v]
        row = {"volume": v, "attached": attached(v), "links": [dataclasses.asdict(l) for l in mine]}
        if row["attached"]:
            try:
                row["disk"] = storage.disk(pathlib.Path(v))
            except OSError:
                row["attached"] = False
        rows.append(row)
    return rows


def external(path: str, cfg: dict | None = None) -> str:
    """The drive `path` is on when it is (or sits under) a symlink to another device, else "": its size is
    not internal usage. A dangling path has no drive to name: "" ."""
    if not os.path.exists(path):
        return ""
    p, linked = path, False
    while p not in ("", os.sep) and not linked:
        linked = os.path.islink(p)
        p = os.path.dirname(p)
    if not linked:
        return ""
    real = os.path.realpath(path)
    vol = next((v for v in configured(cfg) if _inside(real, v)), "")
    if vol:
        return vol
    return "" if _same_device(path, str(home())) else mount_point(path)


def _short(p: str) -> str:
    return p.replace(str(home()), "~", 1)


def render(rows: list[dict]) -> list[str]:
    """The `disk` lines and the link table of `teyla storage`."""
    L = []
    for r in rows:
        n = len(r["links"])
        if r["attached"]:
            d = r["disk"]
            L.append(f"disk    {r['volume']}  {storage.human(d['free'])} free of {storage.human(d['total'])} ({d['free_fraction']:.0%})")
        else:
            L.append(f"disk    {r['volume']}  not attached — {n} path(s) point into it; {DO_NOT.lower()}")
    if any(r["links"] for r in rows):
        L.append("")
        L.append("paths on external volumes (their size is not internal usage)")
        for r in rows:
            for l in r["links"]:
                what = {OK: "ok", DANGLING: "DANGLING", REPLACED: "REPLACED"}[l["status"]]
                to = f" -> {l['target']}" if l["target"] else "  (was a link; now a folder or missing)"
                L.append(f"  {what:8} {_short(l['path'])}{to}  [on {r['volume']}]")
    return L


def _bounded(cmd: list[str], secs: float = ADVICE_TIMEOUT_S) -> str | None:
    """Stdout of `cmd`, or None on any failure or after `secs`. The child is killed and not waited for: a
    `diskutil` stuck behind a system dialog does not answer a kill either."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return None
    try:
        out, _ = proc.communicate(timeout=secs)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        return None
    return out.decode("utf-8", "replace") if proc.returncode == 0 else None


def advice(volume: str) -> list[str]:
    """macOS-only hints for an attached drive, each bounded to `ADVICE_TIMEOUT_S`; nothing elsewhere or on any
    failure. Ownership off makes files written by one user unreadable to another; Spotlight indexing a
    drive of build output slows it for nothing."""
    if sys.platform != "darwin":
        return []
    out = []
    raw = _bounded(["diskutil", "info", "-plist", volume])
    if raw:
        try:
            if plistlib.loads(raw.encode()).get("GlobalPermissionsEnabled") is False:
                out.append(f"ownership is off on {volume}: run `sudo diskutil enableOwnership {volume}` yourself, "
                           f"then `sudo chown` the volume root to your user (Teyla never runs sudo)")
        except (ValueError, plistlib.InvalidFileException):
            pass
    raw = _bounded(["mdutil", "-s", volume])
    if raw and "Indexing enabled" in raw:
        out.append(f"Spotlight indexes {volume}: `sudo mdutil -i off {volume}` (it only slows a drive of build output)")
    return out


def _plural(n: int) -> str:
    return f"{n} path" + ("" if n == 1 else "s")


def problems(cfg: dict | None = None, root: pathlib.Path | None = None, with_advice: bool = False) -> list[dict]:
    """Doctor rows. An absent drive is a normal state: one INFO note per drive (exit 0), unless the drive is
    in `volumes_required`, then one FIX per path. A target missing on an attached drive, and a path replaced
    by a folder while its drive is away, are WARN (FIX when required). Nothing when there is nothing to say."""
    out = []
    for r in volume_rows(cfg, root):
        ls = [Link(**{k: (tuple(v) if k == "kinds" else v) for k, v in l.items()}) for l in r["links"]]
        bad = [l for l in ls if l.status != OK]
        for l in bad:
            if l.status == REPLACED:
                out.append({"level": "FIX" if l.required else "WARN", "name": "storage:link",
                            "detail": f"{_short(l.path)} was a link into {l.volume} and is now a folder or missing: it fills the "
                                      "internal disk",
                            "fix": f"attach {l.volume}, move the data back and restore the link"})
            elif not l.absent:
                out.append({"level": "FIX" if l.required else "WARN", "name": "storage:link",
                            "detail": f"{_short(l.path)} -> {l.target} dangles: {l.volume} is attached but the target is missing",
                            "fix": f"restore the target; {DO_NOT.lower()}: {_short(l.path)}"})
            elif l.required:
                out.append({"level": "FIX", "name": "storage:link",
                            "detail": f"{_short(l.path)} -> {l.target} dangles: {l.volume} is required and not attached",
                            "fix": f"attach {l.volume}; {DO_NOT.lower()}: {_short(l.path)}"})
        loose = [l for l in bad if l.absent and l.status == DANGLING and not l.required]
        if loose or (not r["attached"] and not r["links"]):
            out.append({"level": "INFO", "name": "storage:volume",
                        "detail": f"{r['volume']} is not attached"
                                  + (f"; {_plural(len(loose))} point into it. {DO_NOT}" if loose else ""),
                        "fix": (f"attach {r['volume']} when you are at the desk; builds that need these paths are refused until then"
                                if loose else None)})
        if r["attached"] and r["links"] and not bad:
            out.append({"level": "OK", "name": "storage:volume",
                        "detail": f"{r['volume']} attached, {_plural(len(ls))} point into it", "fix": None})
        if with_advice and r["attached"] and r["links"]:
            out += [{"level": "INFO", "name": "storage:volume-advice", "detail": a, "fix": None} for a in advice(r["volume"])]
    return out


def refusal(kind: str, cfg: dict | None = None, root: pathlib.Path | None = None) -> str:
    """The message that refuses `teyla load --admit <kind>`, or "" when the paths that kind needs are fine."""
    bad = broken(cfg, kind, root)
    if not bad:
        return ""
    vols = sorted({l.volume for l in bad})
    lines = [f"teyla guard: {kind} refused — {', '.join(vols)} is not available and {_plural(len(bad))} this needs "
             f"point into it: {', '.join(_short(l.path) for l in bad)}.",
             f"{DO_NOT}: the build would refill it. Attach the drive and retry."]
    lines.append("Not using the drive any more: replace each link with a real folder yourself "
                 "(and remove the drive from [storage] volumes if you listed it).")
    return "\n".join(lines)


def hook_file() -> pathlib.Path:
    return storage.state_dir().parent / "volumes.list"


def write_hook_file(cfg: dict | None = None, root: pathlib.Path | None = None) -> None:
    """`~/.teyla/volumes.list` for the session-start hook: `<volume><TAB><path><TAB>dangling|replaced` for each
    path whose drive is absent. The hook tests the path itself, live, so a stale file never reports a drive that
    is back. The file is removed when there is nothing to say. Never raises."""
    try:
        f = hook_file()
        rows = [l for l in links(cfg, root=root, remember=True) if l.absent and l.status != OK]
        if not rows:
            f.unlink(missing_ok=True)
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(f"{l.volume}\t{l.path}\t{l.status}\n" for l in rows))
    except OSError:
        pass

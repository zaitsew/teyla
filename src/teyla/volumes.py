"""External volumes: heavy folders that live on a drive that may not be attached.

Simulators, DerivedData, the Android SDK and the Gradle caches are often moved to an external
drive and left behind as symlinks. When the drive is absent the link dangles, and a tool that sees
"No such file" under it may delete the link and recreate the folder on the internal disk, which
then fills up without a sound. This module names the volumes, finds the links, and says which are
dangling, so that `teyla storage`, `teyla doctor`, the session-start hook and `teyla load` can
report the absence instead of a failing build discovering it.

Config, in `~/.teyla/config.toml`:

    [storage]
    volumes = ["/Volumes/<name>"]

Empty or missing: nothing here does anything. Nothing in this module writes to a heavy path, deletes
a link or creates a folder; the one file it writes is `~/.teyla/volumes.list`, the hook's input.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib

from . import storage

# Under this prefix a folder only counts as an attached volume when it is a mount point: an agent
# that runs `mkdir -p` through a dangling link leaves an empty stub behind, and a stub is not a drive.
MOUNT_PREFIX = "/Volumes"

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


@dataclasses.dataclass
class Link:
    name: str
    path: str          # the heavy path, as the tools see it
    target: str        # where the link points ("" when it is not a link any more)
    volume: str
    status: str        # ok | dangling | replaced
    kinds: tuple = ()


def home() -> pathlib.Path:
    return pathlib.Path.home()


def configured(cfg: dict | None = None) -> list[str]:
    """`[storage] volumes`: absolute paths, `~` expanded, no trailing slash, no duplicates."""
    out: list[str] = []
    for v in storage.conf_list(cfg, "volumes"):
        p = os.path.normpath(os.path.expanduser(v))
        if os.path.isabs(p) and p != os.sep and p not in out:
            out.append(p)
    return out


def attached(volume: str) -> bool:
    """The volume is there: a folder, and under /Volumes a mount point too."""
    if not os.path.isdir(volume):
        return False
    if volume.startswith(MOUNT_PREFIX + os.sep):
        return os.path.ismount(volume)
    return True


def _inside(path: str, volume: str) -> bool:
    return path == volume or path.startswith(volume + os.sep)


def _target(path: str) -> str:
    """The link's target as written, made absolute, without resolving anything (the volume may be gone)."""
    raw = os.readlink(path)
    return os.path.normpath(raw if os.path.isabs(raw) else os.path.join(os.path.dirname(path), raw))


def state_path() -> pathlib.Path:
    return storage.state_dir() / "volumes.json"


def _remembered() -> dict:
    try:
        d = json.loads(state_path().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def links(cfg: dict | None = None, root: pathlib.Path | None = None, remember: bool = False) -> list[Link]:
    """Every heavy path that points into a configured volume, with its state.

    A link that was seen before (`remember=True` keeps a record in `~/.teyla/state/volumes.json`) and is
    now a real folder, or gone, is `replaced`: the failure this module exists to catch, after the fact."""
    vols = configured(cfg)
    if not vols:
        return []
    root = root or home()
    seen = _remembered() if remember else {}
    now: dict = {}
    out: list[Link] = []
    for name, rel, kinds in HEAVY:
        p = str(root / rel)
        vol = target = ""
        if os.path.islink(p):
            target = _target(p)
            vol = next((v for v in vols if _inside(target, v)), "")
        elif p in seen and seen[p].get("volume") in vols:
            vol, target = seen[p]["volume"], ""
        if not vol:
            continue
        if target:
            status = OK if os.path.exists(p) and attached(vol) else DANGLING
            now[p] = {"volume": vol, "target": target}
        else:
            status = REPLACED
        out.append(Link(name, p, target, vol, status, kinds))
    if remember:
        # Keep what was seen until the link is back or the volume leaves the config: a replaced path stays replaced.
        keep = {k: v for k, v in seen.items() if v.get("volume") in vols and not os.path.islink(k)}
        _save({**keep, **now})
    return out


def _save(rec: dict) -> None:
    try:
        f = state_path()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(rec, indent=1, sort_keys=True))
    except OSError:
        pass


def broken(cfg: dict | None = None, kind: str | None = None, root: pathlib.Path | None = None) -> list[Link]:
    """The links that are not ok; with `kind`, only those a `teyla load --kind <kind>` needs."""
    return [l for l in links(cfg, root=root, remember=True) if l.status != OK and (kind is None or kind in l.kinds)]


def volume_rows(cfg: dict | None = None, root: pathlib.Path | None = None) -> list[dict]:
    """One row per configured volume: its disk figures when attached, and the links into it."""
    ls = links(cfg, root=root, remember=True)
    rows = []
    for v in configured(cfg):
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
    """The configured volume `path` is a link into ("" when it is not): its size is not internal usage."""
    if not os.path.islink(path):
        return ""
    target = _target(path)
    return next((v for v in configured(cfg) if _inside(target, v)), "")


def render(rows: list[dict]) -> list[str]:
    """The `disk` lines and the link table of `teyla storage`."""
    short = lambda p: p.replace(str(home()), "~", 1)
    L = []
    for r in rows:
        n = len(r["links"])
        if r["attached"]:
            d = r["disk"]
            L.append(f"disk    {r['volume']}  {storage.human(d['free'])} free of {storage.human(d['total'])} ({d['free_fraction']:.0%})")
        else:
            L.append(f"disk    {r['volume']}  not attached — {n} path(s) point into it; do not recreate them on the internal disk")
    if any(r["links"] for r in rows):
        L.append("")
        L.append("paths on external volumes (their size is not internal usage)")
        for r in rows:
            for l in r["links"]:
                what = {OK: "ok", DANGLING: "DANGLING", REPLACED: "REPLACED"}[l["status"]]
                to = f" -> {l['target']}" if l["target"] else "  (was a link into the volume; now a folder or missing)"
                L.append(f"  {what:8} {short(l['path'])}{to}")
    return L


def _plural(n: int) -> str:
    return f"{n} path" + ("" if n == 1 else "s")


def problems(cfg: dict | None = None, root: pathlib.Path | None = None) -> list[dict]:
    """Doctor rows: one FIX per path that is dangling or replaced, one WARN for an absent volume that
    nothing points into (yet), one OK per attached volume. Nothing when no volume is configured."""
    out = []
    short = lambda p: p.replace(str(home()), "~", 1)
    for r in volume_rows(cfg, root):
        bad = [l for l in r["links"] if l["status"] != OK]
        if not r["attached"] and not r["links"]:
            out.append({"level": "WARN", "name": "storage:volume", "detail": f"{r['volume']} is not attached",
                        "fix": f"attach {r['volume']}, or remove it from [storage] volumes"})
        for l in bad:
            if l["status"] == REPLACED:
                out.append({"level": "FIX", "name": "storage:link",
                            "detail": f"{short(l['path'])} was a link into {r['volume']} and is now a folder or missing: "
                                      "it fills the internal disk",
                            "fix": f"attach {r['volume']}, move the data back and restore the link"})
            else:
                out.append({"level": "FIX", "name": "storage:link",
                            "detail": f"{short(l['path'])} -> {l['target']} dangles: {r['volume']} is not attached",
                            "fix": f"attach {r['volume']}; do not recreate {short(l['path'])} on the internal disk"})
        if r["attached"] and not bad:
            out.append({"level": "OK", "name": "storage:volume",
                        "detail": f"{r['volume']} attached, {_plural(len(r['links']))} point into it", "fix": None})
    return out


def refusal(kind: str, cfg: dict | None = None, root: pathlib.Path | None = None) -> str:
    """The message that refuses `teyla load --admit <kind>`, or "" when the paths that kind needs are fine."""
    bad = broken(cfg, kind, root)
    if not bad:
        return ""
    short = lambda p: p.replace(str(home()), "~", 1)
    vols = sorted({l.volume for l in bad})
    lines = [f"teyla guard: {kind} refused — {', '.join(vols)} is not attached and {_plural(len(bad))} this needs "
             f"point into it: {', '.join(short(l.path) for l in bad)}.",
             "Do not recreate these paths on the internal disk: the build would refill it. Attach the drive and retry."]
    lines.append("Not using the drive any more: remove it from [storage] volumes in ~/.teyla/config.toml, "
                 "then replace each link with a real folder yourself.")
    return "\n".join(lines)


def write_hook_file(cfg: dict | None = None, root: pathlib.Path | None = None) -> None:
    """`~/.teyla/volumes.list` for the session-start hook: `<volume>\\t<paths pointing into it>` per line.
    The hook tests whether each volume is there itself, live, so a stale file never cries wolf. The file
    is removed when no volume is configured. Never raises."""
    try:
        f = storage.state_dir().parent / "volumes.list"
        vols = configured(cfg)
        if not vols:
            f.unlink(missing_ok=True)
            return
        ls = links(cfg, root=root, remember=True)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("".join(f"{v}\t{sum(1 for l in ls if l.volume == v)}\n" for v in vols))
    except OSError:
        pass

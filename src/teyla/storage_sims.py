"""`teyla storage sims` — iOS simulators that nobody is using.

    teyla storage sims [--json]               one line per booted simulator: in use, or idle for N min
    teyla storage sims --reap [--dry]         shut down the idle ones; delete matching shut-down devices

Parallel agents boot a simulator per task and never shut it down. Every booted runtime keeps
well over a hundred processes alive (SpringBoard, the daemons behind it) and drains the battery
on its own, so a handful of them can push a laptop's load average into the hundreds.

A simulator is *in use* while any process other than its own runtime names its UDID on its
command line: `xcodebuild`/`xctest` (`id=<UDID>`), `simctl spawn/install/launch`, a screenshot
script. A `log stream` alone (a simulator panel watching it) does not count. When `ps` cannot
answer, nothing is in use *or* idle: the answer is "unknown" and nothing is shut down or deleted.

The first time an idle simulator is seen is remembered in `~/.teyla/state/sims/<udid>`; it is shut
down once it has been idle `storage.sim_idle_min` minutes (default 30). When more than
`storage.sim_max_booted` (default 3) are booted, idle ones go at once, longest idle first.
Shutting down loses nothing on disk, and `xcodebuild test` boots its destination again by itself.

Devices whose name matches `storage.sim_prune_pattern` (a regex matched at the start of the name;
default empty = nothing is ever deleted) and that stayed shut down, untouched and named by no
process for `storage.sim_prune_days` (default 3) are deleted: agents create one per task and
never reuse it. Only shut-down devices and only matching names — a hand-made simulator is never
touched. Every `xcrun simctl` call goes through `simctl()`.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import time

from . import storage

DEFAULT_DEVELOPER_DIR = "/Applications/Xcode.app/Contents/Developer"
UDID = re.compile(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}")
# A command line that names the UDID without using the simulator: the runtime itself runs from
# .../Devices/<udid>/ and the simruntime, and `log stream` only watches.
NOT_USING = ("simruntime", "launchd_sim", "log stream")
_FETCH = object()   # "ask the machine"; None means "asked, and it could not answer"


def settings(cfg: dict | None = None) -> dict:
    return {"idle_min": storage.conf_int(cfg, "sim_idle_min", 30),
            "max_booted": storage.conf_int(cfg, "sim_max_booted", 3),
            "prune_pattern": storage.conf_str(cfg, "sim_prune_pattern", ""),
            "prune_days": storage.conf_int(cfg, "sim_prune_days", 3)}


# --- the one place that runs simctl -------------------------------------------------------

def simctl(*args: str, timeout: int = 60) -> tuple[int, str]:
    """(exit code, stdout) of `xcrun simctl <args>`. 127 when there is no `xcrun`, 124 on a timeout.
    A machine whose `xcode-select` points at the command line tools has no simctl: the usual Xcode
    location is tried once before giving up."""
    if not shutil.which("xcrun"):
        return 127, ""

    def go(env):
        try:
            r = subprocess.run(["xcrun", "simctl", *args], capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return 124, ""
        except OSError:
            return 127, ""
        return r.returncode, r.stdout

    rc, out = go(None)
    if rc != 0 and rc not in (124, 127) and not os.environ.get("DEVELOPER_DIR") and os.path.isdir(DEFAULT_DEVELOPER_DIR):
        rc, out = go({**os.environ, "DEVELOPER_DIR": DEFAULT_DEVELOPER_DIR})
    return rc, out


def devices() -> list[dict] | None:
    """Every simulator device: {udid, name, state, runtime}. None when simctl cannot list them."""
    rc, out = simctl("list", "devices", "-j")
    if rc != 0:
        return None
    try:
        data = json.loads(out or "{}")
    except ValueError:
        return None
    rows = []
    for runtime, devs in (data.get("devices") or {}).items():
        for d in devs or []:
            udid = d.get("udid")
            if isinstance(udid, str) and UDID.fullmatch(udid):  # it becomes a file name
                rows.append({"udid": udid, "name": str(d.get("name", "?")), "state": str(d.get("state", "")),
                             "runtime": str(runtime)})
    return rows


def devices_root() -> pathlib.Path:
    return pathlib.Path.home() / "Library" / "Developer" / "CoreSimulator" / "Devices"


# --- in use or idle -----------------------------------------------------------------------

def named_by_process(udid: str, procs: list[str]) -> bool:
    u = udid.lower()
    return any(u in line.lower() for line in procs)


def in_use(udid: str, procs: list[str]) -> bool:
    """A process other than the simulator's own runtime (or a `log stream`) names the UDID."""
    u = udid.lower()
    for line in procs:
        low = line.lower()
        if u not in low or f"devices/{u}" in low or any(x in low for x in NOT_USING):
            continue
        return True
    return False


def _first_idle(udid: str, now: float, record: bool) -> float:
    f = storage.state_dir("sims") / udid
    try:
        return float(f.read_text().strip())
    except (OSError, ValueError):
        pass
    if record:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"{int(now)}\n")
        except OSError:
            pass
    return now


def _forget(udid: str) -> None:
    try:
        (storage.state_dir("sims") / udid).unlink()
    except OSError:
        pass


def status(now: float | None = None, devs=_FETCH, procs=_FETCH, record: bool = True) -> dict:
    """{"booted": [{udid, name, runtime, in_use, idle_min}], "error": str | None}. `in_use` is None
    when the process list is unknown. `record` keeps the first-idle time in the state dir and
    forgets devices that are no longer booted."""
    now = time.time() if now is None else now
    devs = devices() if devs is _FETCH else devs
    if devs is None:
        return {"booted": [], "error": "xcrun simctl is not available"}
    procs = storage.process_commands() if procs is _FETCH else procs
    booted = [d for d in devs if d["state"] == "Booted"]
    rows = []
    for d in booted:
        row = {"udid": d["udid"], "name": d["name"], "runtime": d["runtime"], "in_use": None, "idle_min": 0, "since": now}
        if procs is not None:
            row["in_use"] = in_use(d["udid"], procs)
            if row["in_use"]:
                if record:
                    _forget(d["udid"])
            else:
                row["since"] = _first_idle(d["udid"], now, record)
                row["idle_min"] = max(0, int((now - row["since"]) // 60))
        rows.append(row)
    if record:
        keep = {d["udid"] for d in booted}
        try:
            for f in storage.state_dir("sims").iterdir():
                if f.name not in keep:
                    f.unlink(missing_ok=True)
        except OSError:
            pass
    return {"booted": rows, "error": None if procs is not None or not booted else "could not list processes (ps failed)"}


def render_status(st: dict) -> list[str]:
    if st.get("error") and not st["booted"]:
        return [st["error"]]
    if not st["booted"]:
        return ["no simulators booted"]
    out = []
    for r in st["booted"]:
        what = "in use  " if r["in_use"] else ("unknown " if r["in_use"] is None else f"idle {r['idle_min']}m")
        out.append(f"{what:8} {r['udid']}  {r['name']}")
    if st.get("error"):
        out.append(st["error"])
    return out


# --- shutting down and deleting -----------------------------------------------------------

def prune(pattern: str, days: int, devs: list[dict] | None, procs: list[str] | None, now: float,
          dry: bool = False, root: pathlib.Path | None = None, du=None) -> list[dict]:
    """Shut-down devices whose name matches `pattern`, unused for `days`, named by no process.
    Empty pattern, days <= 0, an unknown device or process list: nothing."""
    if not pattern or days <= 0 or devs is None or procs is None:
        return []
    try:
        rx = re.compile(pattern)
    except re.error:
        return [{"error": f"storage.sim_prune_pattern is not a valid regex: {pattern!r}"}]
    root = root or devices_root()
    du = du or storage.du
    out = []
    for d in devs:
        if d["state"] != "Shutdown" or not rx.match(d["name"]):
            continue
        dev = root / d["udid"]
        plist = dev / "device.plist"
        if not plist.is_file() or named_by_process(d["udid"], procs):
            continue
        # Anything written anywhere in the device (app containers included) makes it recent.
        newest = storage.newest_mtime(dev, limit=now - days * 86400)
        idle = (now - newest) / 86400
        if idle < days:
            continue
        row = {"udid": d["udid"], "name": d["name"], "idle_days": int(idle), "bytes": du(dev), "deleted": False}
        if not dry:
            row["deleted"] = simctl("delete", d["udid"], timeout=300)[0] == 0
        out.append(row)
    return out


def reap(cfg: dict | None = None, dry: bool = False, now: float | None = None, devs=_FETCH, procs=_FETCH,
         prune_days: int | None = None) -> dict:
    """Shut down idle simulators, then prune matching old devices. Returns the status, the lines
    describing what was (or, with dry, would be) done, and the pruned devices."""
    s = settings(cfg)
    now = time.time() if now is None else now
    devs = devices() if devs is _FETCH else devs
    procs = storage.process_commands() if procs is _FETCH else procs
    st = status(now, devs, procs, record=True)
    lines, shut = [], []
    if devs is None:
        return {"status": st, "lines": [st["error"]], "shutdown": [], "pruned": []}
    count = len(st["booted"])
    # Longest idle first; past the cap anything idle goes, otherwise only past the idle limit.
    idle = sorted((r for r in st["booted"] if r["in_use"] is False), key=lambda r: (-r["idle_min"], r["since"], r["udid"]))
    for r in idle:
        if not (r["idle_min"] >= s["idle_min"] or count > s["max_booted"]):
            continue
        label = f"{r['udid']} ({r['name']}), idle {r['idle_min']}m, {count} booted"
        if dry:
            lines.append(f"would shut down {label}")
        elif simctl("shutdown", r["udid"], timeout=120)[0] == 0:
            lines.append(f"shut down {label}")
            storage._log(f"sims shut down {r['udid']} {r['name']}")
            _forget(r["udid"])
        else:
            lines.append(f"could not shut down {r['udid']} ({r['name']})")
            continue
        shut.append(r["udid"])
        count -= 1
    days = s["prune_days"] if prune_days is None else prune_days
    pruned = prune(s["prune_pattern"], days, devs, procs, now, dry=dry)
    for p in pruned:
        if "error" in p:
            lines.append(p["error"])
        elif dry:
            lines.append(f"would delete {p['udid']} ({p['name']}), {storage.human(p['bytes'])}, unused {p['idle_days']}d")
        elif p["deleted"]:
            lines.append(f"deleted {p['udid']} ({p['name']}), {storage.human(p['bytes'])}, unused {p['idle_days']}d")
            storage._log(f"sims deleted {p['bytes']} {p['udid']} {p['name']}")
        else:
            lines.append(f"could not delete {p['udid']} ({p['name']})")
    return {"status": st, "lines": lines, "shutdown": shut, "pruned": [p for p in pruned if "error" not in p]}


# --- CLI ------------------------------------------------------------------------------------

def cmd_sims(args, cfg: dict) -> int:
    if getattr(args, "reap", False):
        res = reap(cfg, dry=getattr(args, "dry", False))
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            stamp = time.strftime("%F %T")
            for line in res["lines"] if args.quiet else res["lines"] or ["nothing to shut down"]:
                print(f"{stamp} {line}")
        return 0
    st = status()
    if args.json:
        print(json.dumps(st, indent=2))
    else:
        for line in render_status(st):
            print(line)
    return 0

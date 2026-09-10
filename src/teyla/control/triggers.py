"""`teyla triggers` — clock triggers as launchd agents.

    ~/Library/LaunchAgents/com.teyla.<product>.<routine>.plist

One plist per clock routine, invoking `teyla run <product>:<routine>`. Same
load/unload approach as `routine_install.py`: `launchctl bootstrap gui/<uid>`,
falling back to the older `launchctl load`, and `bootout` to remove — because on
current macOS the first is the supported spelling and the second is what actually
works on some machines, and guessing wrong silently leaves the job unloaded.

`StartCalendarInterval` takes an array of dicts, one per weekday, each with
`Hour`/`Minute`/`Weekday`. Seven days means no `Weekday` key at all, which is
launchd's own spelling for "every day" and avoids seven near-identical entries.

**Timezone.** launchd fires on *local* time and has no timezone field. A routine
declaring `tz = "Europe/Madrid"` on a machine set to another zone will fire at the
wrong hour, so `install` says so instead of pretending. The `tz` is still recorded
in the manifest and the receipt; it is the intent, and the plist is the
approximation.

Only `clock` triggers install. `event` and `webhook` parse in the manifest and are
refused here by name — see docs/CONTROL-PLANE.md, "Not built".
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

from . import state as S
from .manifest import DAY_ORDER, DAY_TO_LAUNCHD, ManifestError, load as load_manifest

LAUNCH_AGENTS = pathlib.Path.home() / "Library" / "LaunchAgents"

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>WorkingDirectory</key>
    <string>{repo}</string>
    <key>StartCalendarInterval</key>
{schedule}
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""


def teyla_bin() -> str:
    return shutil.which("teyla") or os.path.abspath(sys.argv[0])


def log_path(routine) -> pathlib.Path:
    return pathlib.Path.home() / "Library" / "Logs" / f"{routine.launchd_label}.log"


def plist_path(routine) -> pathlib.Path:
    return LAUNCH_AGENTS / f"{routine.launchd_label}.plist"


def _schedule_xml(at: str, days) -> str:
    hour, _, minute = at.partition(":")
    entries = []
    days = tuple(days or DAY_ORDER)
    if len(set(days)) >= 7:
        entries.append((int(hour), int(minute), None))
    else:
        for d in days:
            entries.append((int(hour), int(minute), DAY_TO_LAUNCHD[d]))
    lines = ["    <array>"]
    for h, m, wd in entries:
        lines.append("        <dict>")
        lines.append(f"            <key>Hour</key>\n            <integer>{h}</integer>")
        lines.append(f"            <key>Minute</key>\n            <integer>{m}</integer>")
        if wd is not None:
            lines.append(f"            <key>Weekday</key>\n            <integer>{wd}</integer>")
        lines.append("        </dict>")
    lines.append("    </array>")
    return "\n".join(lines)


def plist_for(routine, *, binary: str | None = None) -> str:
    """The plist text for a clock routine. Pure — no launchctl, no filesystem — so the
    generated XML is testable on any machine, including one with no launchd at all."""
    if routine.trigger.type != "clock":
        raise ManifestError(
            f"{routine.ref}: only `clock` triggers install as launchd agents; "
            f"this one is {routine.trigger.type!r} (event and webhook triggers are not built)"
        )
    argv = [binary or teyla_bin(), "run", routine.ref]
    args = "\n".join(f"        <string>{a}</string>" for a in argv)
    return PLIST_TEMPLATE.format(
        label=routine.launchd_label, args=args, repo=routine.repo,
        schedule=_schedule_xml(routine.trigger.at, routine.trigger.days),
        log=log_path(routine),
    )


# --- discovery -----------------------------------------------------------------------


def all_clock_routines() -> list:
    out = []
    for man in S.find_product_manifests():
        try:
            for r in load_manifest(man):
                if r.trigger.type == "clock":
                    out.append(r)
        except ManifestError:
            continue
    return out


def _launchctl_list() -> str:
    try:
        return subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def is_loaded(label: str, listing: str | None = None) -> bool:
    text = _launchctl_list() if listing is None else listing
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2] == label:
            return True
    return False


# --- commands -------------------------------------------------------------------------


def cmd_list(args) -> int:
    routines = all_clock_routines()
    if not routines:
        roots = ", ".join(str(p) for p in S.repo_roots())
        print(f"no clock-triggered control-plane routines found under {roots}")
        return 0
    listing = _launchctl_list()
    print(f"{'routine':38} {'at':6} {'tz':18} {'days':20} {'plist':7} loaded")
    for r in routines:
        p = plist_path(r)
        print(f"{r.ref[:38]:38} {r.trigger.at:6} {str(r.trigger.tz)[:18]:18} "
              f"{','.join(r.trigger.days)[:20]:20} {'yes' if p.exists() else 'no':7} "
              f"{'yes' if is_loaded(r.launchd_label, listing) else 'no'}")
    unsupported = []
    for man in S.find_product_manifests():
        try:
            for r in load_manifest(man):
                if r.trigger.type in ("event", "webhook"):
                    unsupported.append(f"{r.ref} ({r.trigger.type})")
        except ManifestError:
            continue
    if unsupported:
        print(f"\nnot installable — event/webhook triggers are not built: {', '.join(unsupported)}")
    return 0


def cmd_install(args) -> int:
    from .engine import resolve
    routine = resolve(args.ref)
    if routine.trigger.type != "clock":
        print(f"{routine.ref}: trigger type {routine.trigger.type!r} cannot be installed. "
              f"Only `clock` triggers are built; event and webhook triggers are not.")
        return 1

    path = plist_path(routine)
    path.parent.mkdir(parents=True, exist_ok=True)
    log_path(routine).parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plist_for(routine))
    print(f"wrote {path}")

    local_tz = _local_tz_name()
    if routine.trigger.tz and local_tz and routine.trigger.tz != local_tz:
        print(f"  WARNING: the routine declares tz={routine.trigger.tz} and this machine is on "
              f"{local_tz}. launchd fires on local time and has no timezone field, so this job "
              f"will fire at {routine.trigger.at} {local_tz}, not {routine.trigger.at} {routine.trigger.tz}.")

    if getattr(args, "no_load", False):
        print("  --no-load: not loading it")
        return 0
    uid = os.getuid()
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(path)], capture_output=True, text=True)
    if r.returncode == 0:
        print(f"loaded via launchctl bootstrap gui/{uid}")
    else:
        r2 = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
        if r2.returncode == 0:
            print("loaded via launchctl load (bootstrap failed, fell back)")
        else:
            print(f"NOT LOADED — bootstrap: {r.stderr.strip()!r}; load: {r2.stderr.strip()!r}")
            return 1
    print(f"to remove: teyla triggers uninstall {routine.ref}")
    return 0


def cmd_uninstall(args) -> int:
    from .engine import resolve
    routine = resolve(args.ref)
    path = plist_path(routine)
    uid = os.getuid()
    r = subprocess.run(["launchctl", "bootout", f"gui/{uid}", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
    if path.exists():
        path.unlink()
        print(f"removed {path}")
    else:
        print(f"no plist at {path}")
    print(f"unloaded {routine.launchd_label}")
    return 0


def _local_tz_name() -> str | None:
    link = pathlib.Path("/etc/localtime")
    try:
        if link.is_symlink():
            target = str(link.resolve())
            if "/zoneinfo/" in target:
                return target.split("/zoneinfo/", 1)[1]
    except OSError:
        pass
    return None

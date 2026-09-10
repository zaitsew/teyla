"""`teyla routine install` / `teyla routine status` — Teyla's own weekly routine.

Installs a launchd agent that runs Teyla's own weekly checks (monitor,
routines, products) unattended, writing into the ops run-artifact layout.
This is Teyla eating its own dogfood: the tool that audits whether other
routines are loaded needs to be a routine itself.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

LABEL = "com.zaitsew.teyla.weekly"
PLIST_PATH = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
WRAPPER_PATH = pathlib.Path.home() / ".teyla" / "weekly.sh"
LOG_PATH = pathlib.Path.home() / "Library" / "Logs" / "teyla-weekly.log"
OUT_ROOT = pathlib.Path.home() / "ops" / "startup" / "os" / "ai-dev" / "runs"

PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{wrapper}</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""

WRAPPER_TEMPLATE = """#!/usr/bin/env bash
# Written by `teyla routine install`. Runs Teyla's weekly checks and files
# their output under the ops run-artifact layout for the Monday digest.
set -uo pipefail

TEYLA="{teyla_bin}"
OUT_DIR="$HOME/ops/startup/os/ai-dev/runs/$(date +%F)"
mkdir -p "$OUT_DIR"

"$TEYLA" monitor --days 7 --out "$OUT_DIR/monitor.md"
"$TEYLA" routines > "$OUT_DIR/routines.md" 2>&1
"$TEYLA" products > "$OUT_DIR/products.md" 2>&1
"$TEYLA" models > "$OUT_DIR/models.md" 2>&1
"""


def _teyla_bin() -> str:
    found = shutil.which("teyla")
    if found:
        return found
    return os.path.abspath(sys.argv[0])


def install() -> list[str]:
    lines = []
    teyla_bin = _teyla_bin()

    WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    WRAPPER_PATH.write_text(WRAPPER_TEMPLATE.format(teyla_bin=teyla_bin))
    WRAPPER_PATH.chmod(0o755)
    lines.append(f"wrote {WRAPPER_PATH}")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(PLIST_TEMPLATE.format(label=LABEL, wrapper=WRAPPER_PATH, log=LOG_PATH))
    lines.append(f"wrote {PLIST_PATH}")

    uid = os.getuid()
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)], capture_output=True, text=True)
    if r.returncode == 0:
        lines.append(f"loaded via launchctl bootstrap gui/{uid}")
    else:
        r2 = subprocess.run(["launchctl", "load", str(PLIST_PATH)], capture_output=True, text=True)
        if r2.returncode == 0:
            lines.append("loaded via launchctl load (bootstrap failed, fell back)")
        else:
            lines.append(f"NOT LOADED — bootstrap: {r.stderr.strip()!r}; load: {r2.stderr.strip()!r}")

    lines.append(f"to remove: launchctl bootout gui/{uid} {PLIST_PATH}  &&  rm {PLIST_PATH}")
    return lines


def status() -> list[str]:
    lines = []
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    found = None
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2] == LABEL:
            found = parts
            break
    if found:
        pid, exit_code = found[0], found[1]
        lines.append(f"loaded: yes (pid {pid}, last exit {exit_code})" if pid != "-" else f"loaded: yes (last exit {exit_code})")
    else:
        lines.append("loaded: no")
    lines.append(f"plist: {PLIST_PATH} ({'exists' if PLIST_PATH.exists() else 'missing'})")
    lines.append(f"wrapper: {WRAPPER_PATH} ({'exists' if WRAPPER_PATH.exists() else 'missing'})")
    if LOG_PATH.exists():
        tail = LOG_PATH.read_text(errors="replace").splitlines()[-10:]
        lines.append(f"last log lines ({LOG_PATH}):")
        lines.extend(f"  {t}" for t in tail)
    else:
        lines.append(f"log: {LOG_PATH} (missing — has not run yet)")
    return lines

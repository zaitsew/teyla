"""`teyla routine install` / `teyla routine status` — Teyla's own weekly routine.

Installs a launchd agent that runs Teyla's own weekly checks (monitor,
routines, products) unattended, writing into the ops run-artifact layout.
This is Teyla eating its own dogfood: the tool that audits whether other
routines are loaded needs to be a routine itself.

A launchd StartCalendarInterval fires on the minute, or on the next wake if the Mac was
asleep — and never, if the Mac was *off* at that minute. On a laptop that is the common
case: the weekly installed on 2026-09-11 was due Monday 2026-09-14 07:30 and the Mac
booted at 15:28, so `launchctl print` showed `runs = 0` while `doctor` said "loaded".
`teyla routine catch-up` is the anacron half: each wrapper stamps `~/.teyla/<job>.last`
when it starts, and catch-up runs any job whose stamp is older than its last due time.
It is called by the daily wrapper (so a missed Monday runs on Tuesday) and by the
plugin's session-start hook (so it runs the first time you open a session after a boot).
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

# The daily agent: `teyla update` (a newer release → install + re-wire) then `teyla doctor`,
# whose one-line summary the session-start hook shows. 07:00 local, before the weekly one.
DAILY_LABEL = "com.zaitsew.teyla.daily"
DAILY_PLIST_PATH = pathlib.Path.home() / "Library" / "LaunchAgents" / f"{DAILY_LABEL}.plist"
DAILY_WRAPPER_PATH = pathlib.Path.home() / ".teyla" / "daily.sh"
DAILY_LOG_PATH = pathlib.Path.home() / "Library" / "Logs" / "teyla-daily.log"

# Written by each wrapper as its first line of work: "launchd (or catch-up) started me at".
STAMP_PATH = pathlib.Path.home() / ".teyla" / "weekly.last"
DAILY_STAMP_PATH = pathlib.Path.home() / ".teyla" / "daily.last"

# What the plists say, kept here so catch-up and doctor compute "due" from the same numbers.
# launchd Weekday: 0 = Sunday … 6 = Saturday; None = every day.
SCHEDULE = {
    DAILY_LABEL: dict(hour=7, minute=0, weekday=None),
    LABEL: dict(hour=7, minute=30, weekday=1),
}

DAILY_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
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
        <key>Hour</key>
        <integer>7</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
{env_plist}    </dict>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
"""

DAILY_WRAPPER_TEMPLATE = """#!/usr/bin/env bash
# Written by `teyla routine install`. Daily: pull a newer Teyla release if there is one
# (which re-wires policy, plugin and these wrappers), then refresh the doctor summary the
# session-start hook shows. Exit status is doctor's: 0 clean, 1 something needs you.
set -uo pipefail
{env_sh}
echo "== $(date -u +%FT%TZ) teyla daily"
date -u +%FT%TZ > "{stamp}"
export TEYLA_IN_ROUTINE="{label}"
TEYLA="{teyla_bin}"
"$TEYLA" update --quiet
# `update` may have replaced the binary in place; call it by name from here on.
teyla doctor --quiet
# Refresh ~/.teyla/routines/<product>.line, the one-liners the session-start hook shows.
teyla routines >/dev/null 2>&1
# A weekly that launchd skipped (the Mac was off at its minute) runs now instead of never.
teyla routine catch-up --quiet
# Finished worktrees and idle build output go, when storage.auto_clean is on; silent otherwise.
teyla storage clean --auto --quiet
"""

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
    <key>EnvironmentVariables</key>
    <dict>
{env_plist}    </dict>
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
{env_sh}
echo "== $(date -u +%FT%TZ) teyla weekly"
date -u +%FT%TZ > "{stamp}"
export TEYLA_IN_ROUTINE="{label}"
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


def _wrapper_stale(path: pathlib.Path, teyla_bin: str, env: dict[str, str] | None = None) -> bool:
    """True when the wrapper does not exist, names a teyla binary other than the current one, or
    (when `env` is given) does not export exactly the environment config says it should."""
    if not path.exists():
        return True
    text = path.read_text()
    if env is not None and _env_block_of(text) != _env_sh(env):
        return True
    if ".last" not in text:
        # Written before catch-up existed: it never stamps, so a missed run could never be seen.
        return True
    if path == DAILY_WRAPPER_PATH and "storage clean" not in text:
        # Written before `teyla storage`: the daily would never clean.
        return True
    for line in text.splitlines():
        if line.startswith('TEYLA="'):
            return line[len('TEYLA="'):-1] != teyla_bin
    return True


def _path_for_launchd(teyla_bin: str) -> str:
    """A PATH launchd can use: the teyla binary's dir, uv/pipx homes, git, and the system dirs."""
    home = pathlib.Path.home()
    cands = [str(pathlib.Path(teyla_bin).parent), str(home / ".local" / "bin"),
             "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c); out.append(c)
    return ":".join(out)


def launchd_env(teyla_bin: str) -> dict[str, str]:
    """The environment both agents run with: PATH first, then ~/.teyla/config.toml [env].
    Regenerated from config on every install, so a variable added there (SSL_CERT_FILE for a
    TLS-inspecting proxy, HTTPS_PROXY, ...) survives the update that rewrites these files —
    the plist is the only place a launchd job can get it from, /bin/bash reads no rc."""
    from . import config
    env = {"PATH": _path_for_launchd(teyla_bin)}
    for k, v in config.env_vars().items():
        if k == "PATH":
            env["PATH"] = v + ":" + env["PATH"]
        else:
            env[k] = v
    return env


def _xml(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _env_plist(env: dict[str, str]) -> str:
    return "".join(f"        <key>{_xml(k)}</key>\n        <string>{_xml(v)}</string>\n" for k, v in env.items())


ENV_BEGIN, ENV_END = "# teyla-env begin (from ~/.teyla/config.toml; rewritten by `teyla routine install`)", "# teyla-env end"


def _env_sh(env: dict[str, str]) -> str:
    """The wrapper's env block, delimited so staleness compares the whole block: a removed
    entry must count as a change, and a substring test would not see it."""
    import shlex
    return "\n".join([ENV_BEGIN, *(f"export {k}={shlex.quote(v)}" for k, v in env.items()), ENV_END])


def _env_block_of(text: str) -> str | None:
    a, b = text.find(ENV_BEGIN), text.find(ENV_END)
    if a < 0 or b < 0 or b < a:
        return None
    return text[a:b + len(ENV_END)]


def is_stale() -> bool:
    teyla_bin = _teyla_bin()
    env = launchd_env(teyla_bin)
    return (_wrapper_stale(WRAPPER_PATH, teyla_bin, env) or _wrapper_stale(DAILY_WRAPPER_PATH, teyla_bin, env)
            or not PLIST_PATH.exists() or not DAILY_PLIST_PATH.exists())


def _load(plist: pathlib.Path, label: str) -> str:
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"], capture_output=True, text=True)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], capture_output=True, text=True)
    if r.returncode == 0:
        return f"loaded {label} via launchctl bootstrap gui/{uid}"
    r2 = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True)
    if r2.returncode == 0:
        return f"loaded {label} via launchctl load (bootstrap failed, fell back)"
    return f"NOT LOADED {label} — bootstrap: {r.stderr.strip()!r}; load: {r2.stderr.strip()!r}"


def install(if_stale: bool = False) -> list[str]:
    lines = []
    teyla_bin = _teyla_bin()
    if if_stale and not is_stale():
        return ["routines current (wrappers name the current binary and the configured env, both plists present)"]
    env = launchd_env(teyla_bin)
    env_plist, env_sh = _env_plist(env), _env_sh(env)

    DAILY_WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAILY_WRAPPER_PATH.write_text(DAILY_WRAPPER_TEMPLATE.format(teyla_bin=teyla_bin, env_sh=env_sh,
                                                                stamp=DAILY_STAMP_PATH, label=DAILY_LABEL))
    DAILY_WRAPPER_PATH.chmod(0o755)
    lines.append(f"wrote {DAILY_WRAPPER_PATH}")
    DAILY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAILY_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DAILY_PLIST_PATH.write_text(DAILY_PLIST_TEMPLATE.format(label=DAILY_LABEL, wrapper=DAILY_WRAPPER_PATH,
                                                            log=DAILY_LOG_PATH, env_plist=env_plist))
    lines.append(f"wrote {DAILY_PLIST_PATH}")
    if sys.platform == "darwin":
        lines.append(_load(DAILY_PLIST_PATH, DAILY_LABEL))
    else:
        lines.append("not macOS: add to cron yourself: 0 7 * * * bash " + str(DAILY_WRAPPER_PATH))

    WRAPPER_PATH.parent.mkdir(parents=True, exist_ok=True)
    WRAPPER_PATH.write_text(WRAPPER_TEMPLATE.format(teyla_bin=teyla_bin, env_sh=env_sh, stamp=STAMP_PATH, label=LABEL))
    WRAPPER_PATH.chmod(0o755)
    lines.append(f"wrote {WRAPPER_PATH}")

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(PLIST_TEMPLATE.format(label=LABEL, wrapper=WRAPPER_PATH, log=LOG_PATH, env_plist=env_plist))
    lines.append(f"wrote {PLIST_PATH}")

    if sys.platform == "darwin":
        lines.append(_load(PLIST_PATH, LABEL))
    else:
        lines.append("not macOS: add to cron yourself: 30 7 * * 1 bash " + str(WRAPPER_PATH))
    _mark_installed(DAILY_LABEL)
    _mark_installed(LABEL)
    uid = os.getuid()
    lines.append(f"to remove: launchctl bootout gui/{uid}/{LABEL}; launchctl bootout gui/{uid}/{DAILY_LABEL}; rm {PLIST_PATH} {DAILY_PLIST_PATH}")
    return lines


def _job(label: str) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    """(plist, wrapper, log, stamp) for a label."""
    if label == DAILY_LABEL:
        return DAILY_PLIST_PATH, DAILY_WRAPPER_PATH, DAILY_LOG_PATH, DAILY_STAMP_PATH
    return PLIST_PATH, WRAPPER_PATH, LOG_PATH, STAMP_PATH


def last_due(label: str, now: "datetime.datetime | None" = None) -> "datetime.datetime":
    """The most recent minute at which launchd should have started this job, in local time."""
    import datetime
    sched = SCHEDULE[label]
    now = now or datetime.datetime.now().astimezone()
    due = now.replace(hour=sched["hour"], minute=sched["minute"], second=0, microsecond=0)
    if due > now:
        due -= datetime.timedelta(days=1)
    if sched["weekday"] is not None:
        # launchd counts Sunday as 0; Python's weekday() counts Monday as 0.
        want = (sched["weekday"] - 1) % 7
        due -= datetime.timedelta(days=(due.weekday() - want) % 7)
    return due


def last_started(label: str) -> "datetime.datetime | None":
    """When the job last started: the stamp its wrapper writes, else the log's mtime for a wrapper
    written before stamps existed, else None (never)."""
    import datetime
    _, _, log, stamp = _job(label)
    if stamp.exists():
        try:
            return datetime.datetime.fromisoformat(stamp.read_text().strip().replace("Z", "+00:00")).astimezone()
        except ValueError:
            pass
    if log.exists() and log.stat().st_size > 0:
        return datetime.datetime.fromtimestamp(log.stat().st_mtime).astimezone()
    return None


def first_installed(label: str) -> "datetime.datetime | None":
    """When this job was first installed: `~/.teyla/<job>.installed`, written once by
    `install()` and never rewritten — a reinstall (every `teyla update` rewrites the wrappers)
    must not look like a fresh schedule and hide a missed run. Before that file exists, the
    earliest evidence wins: a previous start, else the plist's mtime."""
    import datetime
    plist, _, _, stamp = _job(label)
    marker = stamp.with_suffix(".installed")
    if marker.exists():
        try:
            return datetime.datetime.fromisoformat(marker.read_text().strip().replace("Z", "+00:00")).astimezone()
        except ValueError:
            pass
    started = last_started(label)
    if started is not None:
        return started
    return datetime.datetime.fromtimestamp(plist.stat().st_mtime).astimezone() if plist.exists() else None


def _mark_installed(label: str) -> None:
    import datetime
    _, _, _, stamp = _job(label)
    marker = stamp.with_suffix(".installed")
    if not marker.exists():
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")


def missed(label: str, now: "datetime.datetime | None" = None) -> "datetime.datetime | None":
    """The due time launchd skipped, or None. A job is missed when it was installed before the
    last due minute and nothing started it at or after that minute — the shape a laptop that
    was off at 07:30 leaves behind (asleep, launchd fires on wake; off, it does not fire at all)."""
    plist, wrapper, _, _ = _job(label)
    if not plist.exists() or not wrapper.exists():
        return None
    due = last_due(label, now)
    installed = first_installed(label)
    if installed is not None and installed > due:
        return None  # the schedule has not had its first chance yet
    started = last_started(label)
    if started is not None and started >= due:
        return None
    return due


def catch_up(dry: bool = False, now: "datetime.datetime | None" = None) -> list[str]:
    """Run every job launchd skipped, daily first. Output goes to the job's own log, as it would
    under launchd. The wrapper that is calling us (TEYLA_IN_ROUTINE) is never re-run."""
    lines = []
    calling = os.environ.get("TEYLA_IN_ROUTINE", "")
    for label in (DAILY_LABEL, LABEL):
        due = missed(label, now)
        if due is None:
            lines.append(f"{label}: on schedule")
            continue
        if label == calling:
            lines.append(f"{label}: running now (this is it)")
            continue
        _, wrapper, log, _ = _job(label)
        if dry:
            lines.append(f"{label}: MISSED {due:%Y-%m-%d %H:%M} — would run {wrapper}")
            continue
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a") as fh:
            fh.write(f"== catch-up: the run due {due:%Y-%m-%d %H:%M} did not start (Mac off or asleep); running now\n")
            fh.flush()
            r = subprocess.run(["/bin/bash", str(wrapper)], stdout=fh, stderr=subprocess.STDOUT, text=True,
                               env={**os.environ, "TEYLA_IN_ROUTINE": label})
        lines.append(f"{label}: MISSED {due:%Y-%m-%d %H:%M} — ran {wrapper.name} now, exit {r.returncode}, log {log}")
    return lines


def loaded(label: str) -> tuple[bool, str | None, str | None]:
    """(loaded, pid, last exit) from `launchctl list`."""
    if sys.platform != "darwin":
        return False, None, None
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2] == label:
            return True, (parts[0] if parts[0] != "-" else None), parts[1]
    return False, None, None


def status() -> list[str]:
    lines = []
    teyla_bin = _teyla_bin()
    env = launchd_env(teyla_bin)
    for label, plist, wrapper, log in ((DAILY_LABEL, DAILY_PLIST_PATH, DAILY_WRAPPER_PATH, DAILY_LOG_PATH),
                                       (LABEL, PLIST_PATH, WRAPPER_PATH, LOG_PATH)):
        ok, pid, code = loaded(label)
        lines.append(f"{label}: loaded: {'yes' if ok else 'no'}" + (f" (pid {pid})" if pid else "") + (f" (last exit {code})" if code else ""))
        lines.append(f"  plist: {plist} ({'exists' if plist.exists() else 'missing'})")
        stale = _wrapper_stale(wrapper, teyla_bin, env)
        lines.append(f"  wrapper: {wrapper} ({'missing' if not wrapper.exists() else ('STALE — names another binary or an outdated [env]; run `teyla routine install`' if stale else 'current')})")
        started, due = last_started(label), last_due(label)
        skipped = missed(label)
        lines.append(f"  last started: {started:%Y-%m-%d %H:%M} · last due: {due:%Y-%m-%d %H:%M}" if started
                     else f"  last started: never · last due: {due:%Y-%m-%d %H:%M}")
        if skipped:
            lines.append(f"  MISSED the run due {skipped:%Y-%m-%d %H:%M} (the Mac was off or asleep at that minute) — teyla routine catch-up")
        if log.exists():
            tail = log.read_text(errors="replace").splitlines()[-6:]
            lines.append(f"  last log lines ({log}):")
            lines.extend(f"    {t}" for t in tail)
        else:
            lines.append(f"  log: {log} (missing — has not run yet)")
    return lines

"""`teyla guard` — the machine guard running by itself.

    teyla guard tick [--quiet] [--dry]     one pass: record, alert, reap idle JVM build daemons
    teyla guard status                     the last recorded rows, the alert, the guard's state

`tick` is what the optional `com.zaitsew.teyla.load` launchd agent runs every minute
(`teyla config set guard.agent=true && teyla routine install`). It is cheap (one `sysctl`, one `ps`; no
`simctl`, no `lsof`) and it never raises: any failure goes to stderr and the exit status is 0.

1. Record. `load.snapshot()` + `load.assess()` -> one line in `~/.teyla/load.tsv`.

2. Alert (`guard.alert`, default true). While the verdict is CRITICAL, `~/.teyla/load.alert` holds one
   line for the next session to read ("machine CRITICAL since 20:21 — swap 11.7 GB = 45% of RAM; ...
   Do not start builds or boot simulators; run teyla load.") and the three apps holding the most RSS.
   The "since" time survives consecutive CRITICAL ticks (`~/.teyla/state/guard-alert.json`). The file goes
   away after three consecutive ticks that are not CRITICAL, so a verdict that flaps does not flap the
   file. Entering CRITICAL posts one macOS notification, at most one per 30 minutes; not in safe mode, not
   off macOS, never blocking longer than 5 s. The session-start hook shows the file while it is under
   5 minutes old: a stale alert from a dead agent must not cry wolf.

3. Reap (`guard.gradle_idle_min`, default 30; 0 = off). A Gradle daemon is idle when no Gradle client
   (`gradlew`, `GradleWrapperMain`, `gradle`) runs and its CPU is ~0; a Kotlin compile daemon, when no
   Gradle client and no `kotlinc` runs and its CPU is ~0. The first time a daemon is seen idle is kept in
   `~/.teyla/state/guard/<pid>` (with its start time, so a recycled pid starts over). Idle for the limit:
   it is stopped with the sequence `storage procs --kill` uses (re-check pid, start time and command,
   SIGTERM, a grace period, SIGKILL only if it is still the same process) and the line
   `guard stopped <kind> daemon pid <pid> <GB> idle <min>m` goes to `~/.teyla/storage.log`. Only the
   current user's Gradle/Kotlin daemons are ever touched. A daemon an IDE keeps for itself is reaped too
   once idle; the IDE starts a new one on its next build. `--dry` reports and changes nothing at all.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
from typing import Callable

from . import config, load, storage, storage_procs

ALERT_NAME = "load.alert"
ALERT_STATE = "guard-alert.json"
OK_TICKS_TO_CLEAR = 3
NOTIFY_EVERY_S = 1800
NOTIFY_TIMEOUT_S = 5
CPU_IDLE_PCT = 1.0
START_TOLERANCE_S = 5
GUARD_STATE = "guard"       # ~/.teyla/state/guard/<pid>
MAX_REASONS = 4
NOTIFY_TITLE = "Teyla: machine overloaded"


# --- the machine, behind objects tests replace ----------------------------------------------------

@dataclasses.dataclass
class Env:
    run: Callable = storage_procs.run_command           # ps, sysctl (the snapshot)
    notify_run: Callable = storage_procs.run_command    # osascript
    ctx: storage_procs.Ctx = dataclasses.field(default_factory=storage_procs.Ctx)   # the signalling of daemons
    now: Callable[[], float] = time.time
    platform: str = sys.platform


def alert_path() -> pathlib.Path:
    from .corrections import teyla_home
    return teyla_home() / ALERT_NAME


def _alert_state_path() -> pathlib.Path:
    return storage.state_dir() / ALERT_STATE


# --- the alert ----------------------------------------------------------------------------------------

_THRESHOLD = re.compile(r"\s*\((?:critical|warn) ≥ [^)]*\)$")


def alert_text(snap: load.Snapshot, verdict: load.Verdict, since: float) -> str:
    """The alert file: the one line a session reads, then the top apps by RSS."""
    reasons = [_THRESHOLD.sub("", r) for r in verdict.reasons[:MAX_REASONS]]
    when = dt.datetime.fromtimestamp(since).strftime("%H:%M")
    first = (f"machine CRITICAL since {when} — " + "; ".join(reasons)
             + ". Do not start builds or boot simulators; run teyla load.")
    lines = [first] + [f"  {name} {load.gb(rss)}" for name, rss in snap.procs.top[:3]]
    return "\n".join(lines) + "\n"


def _write_atomic(path: pathlib.Path, text: str) -> None:
    config.private_dir(path.parent)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _read_state() -> dict:
    try:
        d = json.loads(_alert_state_path().read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _num_or_none(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def notification_text(verdict: load.Verdict, since: float) -> str:
    reasons = [_THRESHOLD.sub("", r) for r in verdict.reasons[:2]]
    text = f"CRITICAL since {dt.datetime.fromtimestamp(since):%H:%M}: " + "; ".join(reasons)
    return text if len(text) <= 160 else text[:159] + "…"


def _notify(env: Env, text: str) -> None:
    env.notify_run(["osascript", "-e",
                    f'display notification "{_applescript(text)}" with title "{NOTIFY_TITLE}"'], NOTIFY_TIMEOUT_S)


def _alert_on(conf: dict) -> bool:
    v = (conf or {}).get("alert", config.DEFAULTS["guard"]["alert"])
    return v if isinstance(v, bool) else True


def update_alert(snap: load.Snapshot, verdict: load.Verdict, conf: dict, env: Env) -> list[str]:
    """Write, keep or remove the alert file, and post the notification on entering CRITICAL.
    Returns what it did, one line each."""
    path, did = alert_path(), []
    if not _alert_on(conf):
        if path.exists():
            path.unlink(missing_ok=True)
            did.append(f"removed {path} (guard.alert is off)")
        # Forget the incident too: alerts switched back on later start a new one, with its own
        # "since" and its own notification.
        _alert_state_path().unlink(missing_ok=True)
        return did
    now = env.now()
    st = _read_state()
    since, ok, notified = _num_or_none(st.get("since")), int(st.get("ok") or 0), _num_or_none(st.get("notified"))
    if verdict.level == load.CRITICAL:
        entering = since is None
        if entering:
            since = now
        ok = 0
        _write_atomic(path, alert_text(snap, verdict, since))
        did.append(f"alert {'written' if entering else 'kept'}: {path}")
        if entering and (notified is None or now - notified >= NOTIFY_EVERY_S):
            if env.platform == "darwin" and not config.safe_mode():
                _notify(env, notification_text(verdict, since))
                notified = now
                did.append("notification posted")
    elif since is not None or path.exists():
        ok += 1
        if ok >= OK_TICKS_TO_CLEAR:
            path.unlink(missing_ok=True)
            since, ok = None, 0
            did.append(f"alert removed after {OK_TICKS_TO_CLEAR} ticks below CRITICAL")
    new = {"since": since, "ok": ok, "notified": notified}
    if new != {k: st.get(k) for k in new}:
        _write_atomic(_alert_state_path(), json.dumps(new) + "\n")
    return did


# --- idle JVM build daemons ------------------------------------------------------------------------------

def idle_limit_min(conf: dict) -> float:
    return load._num(conf, "gradle_idle_min")


def _state_file(pid: int) -> pathlib.Path:
    return storage.state_dir(GUARD_STATE) / str(pid)


def _first_idle(pid: int, start: float, now: float, record: bool) -> float:
    """When this daemon was first seen idle. The file holds `<epoch> <start epoch>`; a file whose start
    time is not this process's (a recycled pid) is ignored."""
    f = _state_file(pid)
    try:
        first, was = (float(x) for x in f.read_text().split())
        if abs(was - start) <= START_TOLERANCE_S and first <= now:
            return first
    except (OSError, ValueError):
        pass
    if record:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(f"{int(now)} {int(start)}\n")
        except OSError:
            pass
    return now


def _forget(pid: int) -> None:
    try:
        _state_file(pid).unlink()
    except OSError:
        pass


def _forget_others(keep: set[int]) -> None:
    try:
        for f in storage.state_dir(GUARD_STATE).iterdir():
            if not (f.name.isdigit() and int(f.name) in keep):
                f.unlink(missing_ok=True)
    except OSError:
        pass


def idle_daemons(snap: load.Snapshot, conf: dict, now: float, record: bool = True) -> list[dict]:
    """[{pid, kind, rss_bytes, idle_min, start}] for the daemons idle at least `guard.gradle_idle_min`.
    Updates the first-idle files (`record`): a busy daemon, and one that is gone, is forgotten."""
    p = snap.procs
    limit = idle_limit_min(conf)
    clients = any(d.kind == "gradle" for d in p.drivers)
    out, seen = [], set()
    for d in p.daemons:
        seen.add(d.pid)
        busy = clients or d.etime_s is None or d.cpu is None or d.cpu >= CPU_IDLE_PCT or (d.kind == "kotlin" and p.kotlinc > 0)
        if busy:
            if record:
                _forget(d.pid)
            continue
        start = now - d.etime_s
        idle_min = max(0, int((now - _first_idle(d.pid, start, now, record)) // 60))
        if limit > 0 and idle_min >= limit:
            out.append({"pid": d.pid, "kind": d.kind, "rss_bytes": d.rss_bytes, "idle_min": idle_min, "start": start})
    if record:
        _forget_others(seen)
    return out


def _lstart_epoch(lstart: str) -> float | None:
    try:
        return time.mktime(time.strptime(" ".join(lstart.split()), "%a %b %d %H:%M:%S %Y"))
    except (ValueError, OverflowError):
        return None


def _is_daemon(row: dict, kind: str, start: float) -> bool:
    """The pid still runs the tracked process: a JVM daemon of this kind, started when the idle clock says."""
    parsed = load.parse_row(f"{row['pid']} {row['ppid']} {row['rss_kb']} 0.0 00:01 {row['command']}")
    began = _lstart_epoch(row["lstart"])
    return (parsed is not None and load._daemon_kind(parsed) == kind
            and began is not None and abs(began - start) <= START_TOLERANCE_S + 2)


def _still_idle(rows: list[dict], env: Env, lines: list[str]) -> list[dict]:
    """Look again right before the signal: a build may have started on the daemon since the
    snapshot the idle clock came from. Any doubt (ps fails) means nobody is stopped."""
    fresh = load.snapshot(env.run)
    if fresh is None:
        lines.append("skipped the daemons: the process table could not be read again")
        return []
    p = fresh.procs
    if any(d.kind == "gradle" for d in p.drivers):
        lines.append("skipped the daemons: a Gradle build started")
        return []
    now = {d.pid: d for d in p.daemons}
    keep = []
    for r in rows:
        g, d = r["_guard"], now.get(r["_guard"]["pid"])
        if d is None or d.cpu is None or d.cpu >= CPU_IDLE_PCT or (g["kind"] == "kotlin" and p.kotlinc > 0):
            _forget(g["pid"])
            lines.append(f"skipped {g['kind']} daemon pid {g['pid']}: busy again")
            continue
        keep.append(r)
    return keep


def reap(idle: list[dict], env: Env, dry: bool = False) -> list[str]:
    """Stop the idle daemons (or, with `dry`, say which)."""
    lines, rows = [], []
    for d in idle:
        label = f"{d['kind']} daemon pid {d['pid']} ({load.gb(d['rss_bytes'])}), idle {d['idle_min']}m"
        if dry:
            lines.append(f"would stop {label}")
            continue
        row = storage_procs.lookup(env.ctx, d["pid"])
        if row is None or row["uid"] != env.ctx.uid or not _is_daemon(row, d["kind"], d["start"]):
            _forget(d["pid"])
            lines.append(f"skipped {label}: no longer the same JVM daemon of this user")
            continue
        row["_guard"] = d
        rows.append(row)
    if not rows:
        return lines
    rows = _still_idle(rows, env, lines)
    if not rows:
        return lines
    killed, problems = storage_procs.terminate(env.ctx, rows)
    for r, how in killed:
        d = r["_guard"]
        lines.append(f"stopped {d['kind']} daemon pid {d['pid']} ({load.gb(d['rss_bytes'])}), idle {d['idle_min']}m ({how})")
        storage._log(f"guard stopped {d['kind']} daemon pid {d['pid']} {d['rss_bytes'] / load.GIB:.1f}GB idle {d['idle_min']}m")
        _forget(d["pid"])
    return lines + problems


# --- one tick ---------------------------------------------------------------------------------------------

def tick(conf: dict | None = None, env: Env | None = None, dry: bool = False) -> dict:
    """One pass. Returns {"verdict": Verdict | None, "lines": [what was done], "snapshot": Snapshot | None}.
    Raises only what the runners raise; `cmd_tick` swallows everything."""
    conf = conf if conf is not None else load.guard_conf()
    env = env or Env()
    res: dict = {"verdict": None, "lines": [], "snapshot": None}
    if not load.enabled(conf):
        return res
    now = env.now()
    snap = load.snapshot(env.run, now=dt.datetime.fromtimestamp(now).astimezone())
    if snap is None:
        res["lines"].append("could not read the process table (ps failed); nothing changed")
        return res
    verdict = load.assess(snap, conf)
    res.update(verdict=verdict, snapshot=snap)
    if dry:
        res["lines"].append("dry run: nothing is recorded, written or stopped")
    else:
        load.record(snap, verdict)
        res["lines"] += update_alert(snap, verdict, conf, env)
    if idle_limit_min(conf) > 0:
        res["lines"] += reap(idle_daemons(snap, conf, now, record=not dry), env, dry=dry)
    return res


def cmd_tick(args, env: Env | None = None) -> int:
    try:
        res = tick(env=env, dry=args.dry)
    except Exception as e:  # noqa: BLE001 — the guard must never fail the agent that runs it
        print(f"teyla guard: {type(e).__name__}: {e}", file=sys.stderr)
        return 0
    stamp = time.strftime("%F %T")
    if not args.quiet and res["verdict"] is not None:
        print(res["verdict"].line())
    for line in res["lines"]:
        print(f"{stamp} {line}")
    return 0


# --- status ------------------------------------------------------------------------------------------------

def _row_line(r: dict) -> str:
    swap = f"swap {load.gb(r['swap_used_bytes'])}/{load.gb(r['ram_bytes'])}" if r["swap_used_bytes"] is not None else "swap ?"
    load1 = "?" if r["load1"] is None else f"{r['load1']:.1f}"
    return (f"{r['time']}  {r['level']:8} {swap}  load {load1}  sims {r['sims']}  builds {r['builds']}"
            f"  daemons {load.gb(r['daemon_rss_bytes'])}")


def status_lines(n: int = 5, now: float | None = None) -> list[str]:
    now = time.time() if now is None else now
    rows = load.read_records()[-n:]
    out = [f"last {len(rows)} row(s) of {load.record_path()}:"] if rows else [f"no rows yet in {load.record_path()}"]
    out += [f"  {_row_line(r)}" for r in rows]
    path = alert_path()
    try:
        first = path.read_text().splitlines()[0]
        out.append(f"alert: {path} ({int(now - path.stat().st_mtime)}s old): {first}")
    except (OSError, IndexError):
        out.append(f"alert: none ({path} does not exist)")
    st = _read_state()
    since = _num_or_none(st.get("since"))
    out.append("state: " + (f"CRITICAL since {dt.datetime.fromtimestamp(since):%H:%M}, {int(st.get('ok') or 0)}/{OK_TICKS_TO_CLEAR} ticks below CRITICAL"
                            if since is not None else "not in an alert"))
    conf = load.guard_conf()
    out.append(f"config: enabled={load.enabled(conf)} agent={config.truthy(conf.get('agent'))} alert={_alert_on(conf)}"
               f" gradle_idle_min={load._num(conf, 'gradle_idle_min'):g}")
    return out


def cmd_status(args) -> int:
    for line in status_lines():
        print(line)
    return 0


def cmd_guard(args) -> int:
    return cmd_tick(args) if args.action == "tick" else cmd_status(args)


def register(sp):
    q = sp.add_parser("guard", help="the machine guard running by itself: `tick` (the load agent's pass) and `status`",
                      description=__doc__.split("\n\n")[0])
    q.set_defaults(fn=cmd_guard)
    q.add_argument("action", choices=["tick", "status"])
    q.add_argument("--quiet", action="store_true", help="tick: print only what was done (the agent's mode)")
    q.add_argument("--dry", action="store_true", help="tick: report what would be done; record, write and stop nothing")
    return q

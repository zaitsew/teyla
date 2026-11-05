"""`teyla storage apps` — quit the apps you listed when memory is tight and you have not used them for hours.

    teyla storage apps [--json]                running foreground apps: memory, hours since last in front, status
    teyla storage apps --quit [--dry] [--json] a manual pass: quit every eligible listed app now, tight or not
    teyla storage apps --report [--days N]     from the journal: per app, quits, memory freed (default 7 days)

Off unless you ask. In `[guard]`: `apps_quit = "off" | "dry" | "on"`, `apps_quit_list` (names, `.app`
folder names or bundle ids, case-insensitive), `apps_quit_idle_h` (4), `apps_quit_every_min` (5). `dry`
does everything but the quit, so a week of `would-quit` rows shows what `on` would have done. An empty list quits nothing.

An app is *eligible* only when ALL of this holds:

- it is a running Foreground app (`lsappinfo list`; menu-bar and background processes never count) with a bundle id;
- it matches the list, and it is not in the protected set that no setting changes: Finder, Teyla, Claude,
  ChatGPT, Codex, Terminal, iTerm2, Ghostty, Xcode, Simulator, Cursor, Zed, Google Chrome, Safari, Firefox, Arc;
- it is not in front, and it has been idle for `apps_quit_idle_h` hours. Idle is the time since it was last
  in front, or since the tick first saw it, whichever is later (`~/.teyla/state/app-front.json`). An app
  that stops running is forgotten, so a relaunch starts the clock over;
- a quit request was not already refused for it: an app that stayed (an unsaved-changes dialog is the usual
  reason) is not asked again until it has been in front;
- Docker (`com.docker.docker`, `com.electron.dockerdesktop`) runs no container: `docker ps -q` exits 0
  with no output within 5 s. A failure or a timeout means skip.

`guard tick` calls it every minute when the mode is not `off` (step 7 of its docstring). The tick quits
only while memory is tight: the kernel pressure is warn or worse, or the compressor holds
`guard.compressor_crit_pct` of RAM, or the swap-out rate reaches `guard.swapout_mb_s`. A full disk or a
high CPU load does not count: quitting an app frees no disk. At most one app goes per
`apps_quit_every_min` minutes, the eligible one with the largest memory (physical footprint, all of the
app's processes). `--quit` ignores the memory and the pause, and waits up to 5 s to see which apps went.

A quit is `NSRunningApplication.terminate`, the same request as Cmd-Q: never a signal, never forced, and
no Automation prompt. AppKit is loaded only when an app is quit. The tick does not wait: it records the
request, and the next tick journals `quit` (the app is gone) or `still-running`. Off macOS nothing runs.

Dry mode keeps its total honest: an app that was reported `would-quit` counts as gone until it comes to
the front, so it is not counted again and again. After a week of dry mode, one notification says how
many apps it would have quit and how much memory that is.

`~/.teyla/app-quit.tsv` has one row per event: time, mode (`dry`, `on`, `manual`), action (`would-quit`,
`quit`, `still-running`, `skipped-docker`), app, memory bytes, idle minutes, reason. A tick where nothing
happened writes nothing. Nothing leaves the machine.
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

MODES = ("off", "dry", "on")
STATE_NAME = "app-front.json"
JOURNAL_NAME = "app-quit.tsv"
JOURNAL_COLUMNS = ["time", "mode", "action", "app", "memory_bytes", "idle_min", "reason"]
JOURNAL_MAX_BYTES = 1024 * 1024
ACTIONS = ("would-quit", "quit", "still-running", "skipped-docker")
DRY_REPORT_AFTER_S = 7 * 86400
DOCKER_TIMEOUT_S = 5
LSAPPINFO_TIMEOUT_S = 10
MANUAL_WAIT_STEPS = 10          # x 0.5 s: how long `--quit` waits to see which apps went
DOCKER_BUNDLES = ("com.docker.docker", "com.electron.dockerdesktop")
NOTIFY_TITLE = "Teyla"

# Never quit, whatever the list says. Matched against the display name, the `.app` folder name and the bundle id.
PROTECTED_NAMES = frozenset({
    "finder", "teyla", "claude", "chatgpt", "codex", "terminal", "iterm", "iterm2", "ghostty", "xcode",
    "simulator", "cursor", "zed", "google chrome", "safari", "firefox", "arc"})
PROTECTED_BUNDLES = frozenset(b.lower() for b in (
    "com.apple.finder", "com.anthropic.claudefordesktop", "com.openai.chat", "com.openai.codex",
    "com.apple.Terminal", "com.googlecode.iterm2", "com.mitchellh.ghostty", "com.apple.dt.Xcode",
    "com.apple.iphonesimulator", "com.todesktop.230313mzl4w4u92", "dev.zed.Zed", "com.google.Chrome",
    "com.apple.Safari", "org.mozilla.firefox", "company.thebrowser.Browser"))

LISTED, PROTECTED, NOT_LISTED, IN_FRONT, NOT_IDLE = "listed", "protected", "not listed", "in front", "not idle yet"


# --- the machine, behind objects tests replace -----------------------------------------------

def quit_bundle(bundle_id: str) -> str:
    """Ask the running app with this bundle id to quit, like Cmd-Q (`NSRunningApplication.terminate`).
    Returns "requested", "not-running" or "failed"; it does not wait. AppKit is loaded here and nowhere else."""
    if sys.platform != "darwin" or not bundle_id:
        return "failed"
    try:
        import ctypes
        import ctypes.util
        objc = ctypes.CDLL(ctypes.util.find_library("objc"))
        ctypes.CDLL("/System/Library/Frameworks/AppKit.framework/AppKit")
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def msg(restype, argtypes):
            return ctypes.CFUNCTYPE(restype, ctypes.c_void_p, ctypes.c_void_p, *argtypes)(("objc_msgSend", objc))

        sel = objc.sel_registerName
        name = msg(ctypes.c_void_p, [ctypes.c_char_p])(objc.objc_getClass(b"NSString"), sel(b"stringWithUTF8String:"),
                                                       bundle_id.encode())
        found = msg(ctypes.c_void_p, [ctypes.c_void_p])(objc.objc_getClass(b"NSRunningApplication"),
                                                        sel(b"runningApplicationsWithBundleIdentifier:"), name)
        if not found or not msg(ctypes.c_ulong, [])(found, sel(b"count")):
            return "not-running"
        app = msg(ctypes.c_void_p, [ctypes.c_ulong])(found, sel(b"objectAtIndex:"), 0)
        return "requested" if msg(ctypes.c_bool, [])(app, sel(b"terminate")) else "failed"
    except Exception:  # noqa: BLE001 — a failing quit is "not done", never a crash of the guard
        return "failed"


@dataclasses.dataclass
class Ctx:
    run: Callable = storage_procs.run_command      # lsappinfo, ps, docker
    quit_app: Callable[[str], str] = quit_bundle
    now: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    platform: str = sys.platform


# --- settings --------------------------------------------------------------------------------------

def settings(conf: dict | None) -> dict:
    """The `[guard]` keys of this feature. A mode that is not off, dry or on reads as off; a list given as a
    comma-separated string works too."""
    conf = conf or {}
    d = config.DEFAULTS["guard"]
    mode = str(conf.get("apps_quit", d["apps_quit"])).strip().lower()
    names = conf.get("apps_quit_list", d["apps_quit_list"])
    if isinstance(names, str):
        names = names.split(",")
    names = [str(n).strip() for n in names if str(n).strip()] if isinstance(names, (list, tuple)) else []
    idle_h, every = load._num(conf, "apps_quit_idle_h"), load._num(conf, "apps_quit_every_min")
    return {"mode": mode if mode in MODES else "off", "list": names,
            "idle_h": idle_h if idle_h > 0 else d["apps_quit_idle_h"],
            "every_min": every if every >= 0 else d["apps_quit_every_min"]}


def mode(conf: dict | None) -> str:
    return settings(conf)["mode"]


def state_path() -> pathlib.Path:
    return storage.state_dir(STATE_NAME)


def journal_path() -> pathlib.Path:
    from .corrections import teyla_home
    return teyla_home() / JOURNAL_NAME


# --- the running apps ----------------------------------------------------------------------------------

_HEADER = re.compile(r'^\s*\d+\)\s+"(.*)"\s+ASN:\S+?:\s*(\(in front\))?')
_BUNDLE_ID = re.compile(r'^\s*bundleID="([^"]*)"')
_BUNDLE_PATH = re.compile(r'^\s*bundle path="([^"]*)"')
_PID = re.compile(r'^\s*pid = (\d+)\b.*?\btype="(\w+)"')


@dataclasses.dataclass
class App:
    name: str              # the display name
    bundle_id: str | None
    path: str              # the bundle path
    folder: str            # the outermost `.app` folder's name, without ".app"
    pid: int
    front: bool

    @property
    def key(self) -> str:
        return self.bundle_id or self.folder


def _outer_folder(path: str) -> str:
    """"/Applications/Docker.app/Contents/MacOS/Docker Desktop.app" -> "Docker": the app the memory is counted under."""
    i = path.find(".app")
    return path[:i].rsplit("/", 1)[-1] if i >= 0 else path.rstrip("/").rsplit("/", 1)[-1]


def parse_lsappinfo(text: str) -> list[App]:
    """The Foreground apps of `lsappinfo list`. An entry starts ` 1) "Name" ASN:0x0-0x2002: `, and the one in
    front carries `(in front)` there; the indented lines hold `bundleID=`, `bundle path=` and `pid = N ... type=`."""
    out, cur = [], None

    def close():
        if cur and cur.get("pid") and cur.get("type") == "Foreground" and cur.get("path"):
            out.append(App(cur["name"], cur.get("bundle_id"), cur["path"], _outer_folder(cur["path"]), cur["pid"], cur["front"]))

    for line in text.splitlines():
        m = _HEADER.match(line)
        if m:
            close()
            cur = {"name": m.group(1), "front": bool(m.group(2))}
            continue
        if cur is None:
            continue
        for rx, key in ((_BUNDLE_ID, "bundle_id"), (_BUNDLE_PATH, "path")):
            m = rx.match(line)
            if m:
                cur[key] = m.group(1)
        m = _PID.match(line)
        if m:
            cur["pid"], cur["type"] = int(m.group(1)), m.group(2)
    close()
    return out


def running_apps(ctx: Ctx) -> list[App] | None:
    """One `lsappinfo list`. None when it fails: nothing is known, so nothing changes."""
    rc, out = ctx.run(["lsappinfo", "list"], LSAPPINFO_TIMEOUT_S)
    return parse_lsappinfo(out) if rc == 0 and out.strip() else None


def memory_by_folder(ctx: Ctx) -> dict[str, int]:
    """{lower-case `.app` folder name: physical footprint of all its processes}: the `ps` rows folded by
    `load.Row.name` (a helper counts under its app; "Docker Desktop" inside Docker.app is "Docker")."""
    rc, out = ctx.run(["ps", "-Ao", load.PS_FORMAT], 15)
    if rc != 0:
        return {}
    by: dict[str, int] = {}
    for r in load.with_footprints(load.parse_ps(out)):
        by[r.name.lower()] = by.get(r.name.lower(), 0) + r.rss_bytes
    return by


# --- who may be quit -------------------------------------------------------------------------------

def _ids(app: App) -> set[str]:
    ids = {app.name.strip().lower(), app.folder.strip().lower()}
    if app.bundle_id:
        ids.add(app.bundle_id.strip().lower())
    return ids


def is_protected(app: App) -> bool:
    ids = _ids(app)
    return bool(ids & PROTECTED_NAMES or ids & PROTECTED_BUNDLES or any(i.startswith("teyla") for i in ids))


def is_listed(app: App, names: list[str]) -> bool:
    ids = _ids(app)
    for n in names:
        n = n.strip().lower()
        if n in ids or (n.endswith(".app") and n[:-4] in ids):
            return True
    return False


@dataclasses.dataclass
class Row:
    app: App
    status: str
    memory: int
    idle_s: float | None       # None: the tick never saw this app
    ent: dict
    eligible: bool = False


def _idle_s(ent: dict, now: float) -> float | None:
    if not ent:
        return None
    return max(0.0, now - max(ent.get("first_seen") or 0, ent.get("last_front") or 0))


def classify(apps: list[App], state: dict, s: dict, mem: dict, now: float) -> list[Row]:
    """One row per app, status first-match: in front, protected, not listed, not idle yet, listed. `eligible`
    is `listed` and no refusal, no pending request and no dry-run "gone" mark on it, and a bundle id to quit by."""
    rows = []
    for a in apps:
        ent = (state.get("apps") or {}).get(a.key) or {}
        idle = _idle_s(ent, now)
        if a.front:
            status = IN_FRONT
        elif is_protected(a):
            status = PROTECTED
        elif not is_listed(a, s["list"]):
            status = NOT_LISTED
        elif idle is None or idle < s["idle_h"] * 3600:
            status = NOT_IDLE
        else:
            status = LISTED
        ok = (status == LISTED and bool(a.bundle_id) and not ent.get("held") and not ent.get("dry_gone")
              and not ent.get("pending"))
        rows.append(Row(a, status, mem.get(a.folder.lower(), 0), idle, ent, ok))
    return rows


# --- memory is tight ---------------------------------------------------------------------------------

def tight_reason(snap, trend, conf: dict | None) -> str | None:
    """Why memory is tight right now, or None. Only memory counts: kernel pressure of warn or worse, the
    compressor at `guard.compressor_crit_pct` of RAM, or the swap-out rate at `guard.swapout_mb_s`. Disk and
    CPU load do not: quitting an app frees neither."""
    if snap is None:
        return None
    if snap.pressure is not None and snap.pressure >= 2:
        return f"memory pressure is {'critical' if snap.pressure >= 4 else 'warn'} (level {snap.pressure})"
    if snap.compressor_bytes is not None and snap.ram_bytes:
        pct, at = snap.compressor_bytes * 100.0 / snap.ram_bytes, load._num(conf, "compressor_crit_pct")
        if pct >= at:
            return f"compressor {load.gb(snap.compressor_bytes)} = {pct:.0f}% of RAM (≥ {at:g}%)"
    rate, at = getattr(trend, "swapout_mb_s", None), load._num(conf, "swapout_mb_s")
    if rate is not None and at > 0 and rate >= at:
        return f"swap-out {rate:.0f} MB/s (≥ {at:g} MB/s)"
    return None


# --- state and journal ------------------------------------------------------------------------------

def load_state(path: pathlib.Path | None = None) -> dict:
    try:
        d = json.loads((path or state_path()).read_text())
    except (OSError, ValueError):
        return {"apps": {}}
    if not isinstance(d, dict):
        return {"apps": {}}
    if not isinstance(d.get("apps"), dict):
        d["apps"] = {}
    d["apps"] = {k: v for k, v in d["apps"].items() if isinstance(v, dict)}
    return d


def save_state(state: dict, path: pathlib.Path | None = None) -> None:
    path = path or state_path()
    config.private_dir(path.parent)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(state, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


_UNSAFE = re.compile(r"[\t\r\n]+")


def journal(rows: list[dict], now: float, path: pathlib.Path | None = None) -> None:
    """Append rows {mode, action, app, memory, idle_min, reason} to the journal. Never raises."""
    when = dt.datetime.fromtimestamp(now).astimezone().isoformat(timespec="seconds")
    for r in rows:
        try:
            fields = [when, r["mode"], r["action"], r["app"], str(int(r.get("memory") or 0)),
                      str(int(r.get("idle_min") or 0)), r.get("reason") or ""]
            load._append(path or journal_path(), JOURNAL_COLUMNS, [_UNSAFE.sub(" ", f) for f in fields], JOURNAL_MAX_BYTES)
        except Exception:  # noqa: BLE001
            pass


def read_journal(since: float | None = None, path: pathlib.Path | None = None) -> list[dict]:
    out = []
    try:
        lines = (path or journal_path()).read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        cells = line.split("\t")
        if line.startswith("#") or len(cells) != len(JOURNAL_COLUMNS):
            continue
        rec = dict(zip(JOURNAL_COLUMNS, cells))
        try:
            rec["ts"] = dt.datetime.fromisoformat(rec["time"]).timestamp()
            rec["memory_bytes"], rec["idle_min"] = int(rec["memory_bytes"]), int(rec["idle_min"])
        except ValueError:
            continue
        if since is None or rec["ts"] >= since:
            out.append(rec)
    return out


# --- observing -----------------------------------------------------------------------------------------

def _row(m: str, action: str, ent: dict, memory: int, idle_s: float | None, reason: str) -> dict:
    return {"mode": m, "action": action, "app": ent.get("name") or "?", "memory": memory,
            "idle_min": int((idle_s or 0) // 60), "reason": reason}


def observe(apps: list[App], state: dict, now: float) -> list[dict]:
    """Bring the state up to date with the running apps; returns the journal rows this resolves: a quit that
    was requested last time is `quit` when the app is gone, `still-running` (and never asked again until it
    has been in front) when it is not. An app that stops running is forgotten; so is one whose pid changed."""
    old, live = state.get("apps") or {}, {}
    by_key = {a.key: a for a in apps}
    rows = []
    for key, ent in old.items():
        p = ent.get("pending")
        if not p:
            continue
        a = by_key.get(key)
        gone = a is None or a.pid != ent.get("pid")
        rows.append({"mode": p.get("mode", "on"), "action": "quit" if gone else "still-running", "app": ent.get("name") or key,
                     "memory": p.get("memory", 0), "idle_min": p.get("idle_min", 0), "reason": p.get("reason", "")})
        ent.pop("pending", None)
        if not gone:
            ent["held"] = True
    for a in apps:
        ent = old.get(a.key)
        if not ent or ent.get("pid") != a.pid:
            ent = {"first_seen": now, "last_front": None, "pid": a.pid}
        ent["name"] = a.name
        if a.front:
            ent["last_front"] = now
            ent.pop("held", None)
            ent.pop("dry_gone", None)
        live[a.key] = ent
    state["apps"] = live
    return rows


def docker_idle(ctx: Ctx) -> bool:
    """True only when `docker ps -q` exits 0 with empty output within 5 s. Anything else means "may be busy"."""
    rc, out = ctx.run(["docker", "ps", "-q"], DOCKER_TIMEOUT_S)
    return rc == 0 and not out.strip()


def _is_docker(a: App) -> bool:
    return (a.bundle_id or "").lower() in DOCKER_BUNDLES


def _label(r: dict) -> str:
    return f"{r['app']} ({load.gb(r['memory'])}, idle {r['idle_min'] // 60}h{r['idle_min'] % 60:02d}m)"


def _line(r: dict) -> str:
    verb = {"would-quit": "would quit", "quit": "quit", "still-running": "still running after the quit request",
            "skipped-docker": "skipped, Docker may be running containers"}[r["action"]]
    return f"apps: {verb} {_label(r)}" + (f": {r['reason']}" if r["reason"] and r["action"] in ("would-quit", "quit") else "")


def _quit_one(row: Row, ctx: Ctx, m: str, why: str, now: float, real: bool, out: list[dict]) -> bool:
    """Act on one eligible app in mode `m`: Docker gate, then request the quit (`on`, `manual`) or only say so
    (`dry`). Returns True when the app was dealt with (a quit requested or a would-quit recorded)."""
    a, ent = row.app, row.ent
    idle = row.idle_s
    if _is_docker(a):
        if not docker_idle(ctx):
            ent["docker_skip"] = now
            out.append(_row(m, "skipped-docker", ent, row.memory, idle, "docker ps did not answer with no containers"))
            return False
    if m == "dry":
        ent["dry_gone"] = True
        out.append(_row(m, "would-quit", ent, row.memory, idle, why))
        return True
    if not real:
        out.append(_row("dry", "would-quit", ent, row.memory, idle, why))
        return True
    res = ctx.quit_app(a.bundle_id)
    if res == "requested":
        ent["pending"] = {"mode": m, "memory": row.memory, "idle_min": int((idle or 0) // 60), "reason": why, "at": now}
        return True
    ent["held"] = True                                     # refused or not found: no retry until it is in front
    out.append(_row(m, "still-running", ent, row.memory, idle, f"the quit request was not accepted ({res})"))
    return False


def _docker_recently_skipped(row: Row, now: float, every_min: float) -> bool:
    return _is_docker(row.app) and 0 <= now - (row.ent.get("docker_skip") or -1e12) < every_min * 60


def tick(conf: dict | None, snap, trend, ctx: Ctx | None = None, notify: Callable[[str], None] | None = None,
         dry: bool = False) -> list[str]:
    """One pass from `guard tick`. Returns what it did, one line each. `dry` is `guard tick --dry`: it computes
    and says what would happen, and writes, journals, notifies and quits nothing. Mode `off` returns at once, with no
    subprocess. Otherwise the pass costs one `lsappinfo`; `ps` and `docker` run only when an app may go."""
    s = settings(conf)
    ctx = ctx or Ctx()
    if s["mode"] == "off" or ctx.platform != "darwin":
        return []
    now = ctx.now()
    apps = running_apps(ctx)
    if apps is None:
        return ["apps: `lsappinfo list` failed; nothing changed"]
    state = load_state()
    rows = observe(apps, state, now)
    m = s["mode"]
    if m == "dry" and not state.get("dry_since"):
        state["dry_since"] = now
    why = tight_reason(snap, trend, conf)
    pause = s["every_min"] * 60
    last = state.get("last_action")
    paused = isinstance(last, (int, float)) and 0 <= now - last < pause
    if why and s["list"] and not paused:
        mem = memory_by_folder(ctx)
        cands = sorted((r for r in classify(apps, state, s, mem, now) if r.eligible),
                       key=lambda r: (-r.memory, -(r.idle_s or 0), r.app.name))
        for row in cands:
            if _docker_recently_skipped(row, now, s["every_min"]):
                continue
            if _quit_one(row, ctx, m, why, now, real=not dry, out=rows):
                state["last_action"] = now
                break
    if m == "dry" and not dry and notify and not state.get("dry_notified") and now - state.get("dry_since", now) >= DRY_REPORT_AFTER_S:
        n, freed = would_totals(read_journal(state.get("dry_since")))
        notify(f"Teyla: in a week it would have quit {n} apps, {freed / load.GIB:.1f} GB. See: teyla storage apps --report")
        state["dry_notified"] = True
    if not dry:
        if rows:
            journal(rows, now)
        save_state(state)
    return [_line(r) for r in rows]


def would_totals(rows: list[dict]) -> tuple[int, int]:
    """(count, bytes) of the `would-quit` rows."""
    w = [r for r in rows if r["action"] == "would-quit"]
    return len(w), sum(r["memory_bytes"] for r in w)


# --- the commands -------------------------------------------------------------------------------------------

def hours(idle_s: float | None) -> str:
    return "-" if idle_s is None else f"{idle_s / 3600:.1f}"


def render(rows: list[Row], s: dict, why: str | None, known: bool) -> list[str]:
    head = (f"mode: {s['mode']}  ·  memory: " + ("unknown" if not known else f"tight ({why})" if why else "not tight")
            + f"  ·  idle limit {s['idle_h']:g} h, one app per {s['every_min']:g} min, {len(s['list'])} listed")
    out = [head, f"{'app':28} {'memory':>9} {'hours':>6}  status"]
    for r in sorted(rows, key=lambda r: -r.memory):
        out.append(f"{r.app.name[:28]:28} {load.gb(r.memory) if r.memory else '-':>9} {hours(r.idle_s):>6}  {r.status}"
                   + ("" if r.status != LISTED or r.eligible else " (waiting: asked already, or marked gone)"))
    return out


def report(days: int, now: float | None = None, path: pathlib.Path | None = None) -> dict:
    """Per app, from the journal: quits and memory freed, would-quits and memory it would have freed."""
    now = time.time() if now is None else now
    rows = read_journal(now - days * 86400, path)
    per: dict[str, dict] = {}
    for r in rows:
        if r["action"] not in ("quit", "would-quit"):
            continue
        a = per.setdefault(r["app"], {"app": r["app"], "quits": 0, "freed": 0, "would_quits": 0, "would_free": 0})
        k, b = ("quits", "freed") if r["action"] == "quit" else ("would_quits", "would_free")
        a[k] += 1
        a[b] += r["memory_bytes"]
    apps = sorted(per.values(), key=lambda a: -(a["freed"] + a["would_free"]))
    return {"days": days, "apps": apps,
            "total": {"quits": sum(a["quits"] for a in apps), "freed": sum(a["freed"] for a in apps),
                      "would_quits": sum(a["would_quits"] for a in apps), "would_free": sum(a["would_free"] for a in apps)}}


def render_report(rep: dict) -> list[str]:
    if not rep["apps"]:
        return [f"no quits or would-quits in the last {rep['days']} days ({journal_path()})"]
    out = [f"last {rep['days']} days, from {journal_path()}", f"{'app':28} {'quits':>5} {'freed':>9} {'would-quit':>10} {'would-free':>10}"]
    for a in rep["apps"]:
        out.append(f"{a['app'][:28]:28} {a['quits']:>5} {load.gb(a['freed']):>9} {a['would_quits']:>10} {load.gb(a['would_free']):>10}")
    t = rep["total"]
    out.append(f"{'total':28} {t['quits']:>5} {load.gb(t['freed']):>9} {t['would_quits']:>10} {load.gb(t['would_free']):>10}")
    return out


def manual_pass(conf: dict | None, ctx: Ctx, dry: bool) -> dict:
    """`--quit`: every eligible listed app, now, whatever the memory and the pause. Waits up to 5 s to see which
    went; journals `quit` / `still-running` itself. `dry` reports only: nothing is written or quit."""
    s = settings(conf)
    apps = running_apps(ctx)
    if apps is None:
        return {"lines": ["`lsappinfo list` failed; nothing changed"], "rows": []}
    now = ctx.now()
    state = load_state()
    rows = observe(apps, state, now)
    cands = sorted((r for r in classify(apps, state, s, memory_by_folder(ctx), now) if r.eligible),
                   key=lambda r: (-r.memory, -(r.idle_s or 0), r.app.name))
    why = "manual pass"
    asked = []
    for row in cands:
        if _quit_one(row, ctx, "manual", why, now, real=not dry, out=rows):
            asked.append(row)
    if asked and not dry:
        for _ in range(MANUAL_WAIT_STEPS):
            left = running_apps(ctx)
            if left is not None and not any(r.app.key in {a.key for a in left} for r in asked):
                break
            ctx.sleep(0.5)
        later = running_apps(ctx)
        if later is not None:
            rows += observe(later, state, ctx.now())
        # observe() resolved the requests it saw; a failed second read leaves them pending for the next tick.
    if not dry:
        if rows:
            journal(rows, now)
        save_state(state)
    lines = [_line(r) for r in rows] or ["nothing is eligible: no listed app is idle long enough, or none is listed"]
    return {"lines": lines, "rows": rows}


def cmd_apps(args, cfg: dict, ctx: Ctx | None = None) -> int:
    ctx = ctx or Ctx()
    conf = load.guard_conf(cfg)
    s = settings(conf)
    if getattr(args, "report", False):
        rep = report(max(1, int(getattr(args, "days", 7) or 7)))
        print(json.dumps(rep, indent=2) if args.json else "\n".join(render_report(rep)))
        return 0
    if ctx.platform != "darwin":
        print("teyla storage apps works on macOS only")
        return 0
    if getattr(args, "quit", False):
        res = manual_pass(conf, ctx, dry=bool(getattr(args, "dry", False)))
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            for line in res["lines"]:
                print(line)
        return 0
    apps = running_apps(ctx)
    if apps is None:
        print("`lsappinfo list` failed")
        return 1
    state = load_state()
    observe(apps, state, ctx.now())                    # in memory only: the table writes nothing
    snap = load.safe_snapshot(ctx.run)
    trend = load.current_trend(snap, conf) if snap else None
    why = tight_reason(snap, trend, conf)
    rows = classify(apps, state, s, memory_by_folder(ctx), ctx.now())
    if args.json:
        print(json.dumps({"mode": s["mode"], "tight": why, "apps": [
            {"name": r.app.name, "bundle_id": r.app.bundle_id, "memory_bytes": r.memory,
             "hours_idle": None if r.idle_s is None else round(r.idle_s / 3600, 2), "status": r.status} for r in rows]}, indent=2))
    else:
        print("\n".join(render(rows, s, why, snap is not None)))
    return 0

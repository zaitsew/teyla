"""`teyla load` — how loaded this machine is right now, a verdict, a recorder and a wait-for-a-slot.

    teyla load [--json] [--record] [--quiet]     snapshot + verdict; exit 0 OK, 1 BUSY, 2 CRITICAL
    teyla load --admit build|sim|lane            silent exit 0 when allowed; the refusal and exit 2 when not
    teyla load --wait --kind build|sim|lane      poll until a slot is free (exit 0) or the timeout (exit 3)

On 2026-10-09 a 24 GB Mac kernel-panicked while agents ran ~36 Claude Code sessions, 17 Codex
sessions, three booted simulators, parallel `xcodebuild`s, Gradle/Kotlin daemons, a VM and Chrome:
the compressor held ~12 GB, swap was 11 of 12 GB, the load average passed 500. Nothing on the
machine knew; each agent saw only its own task. This module is the foundation of a machine guard:
other parts (an admission hook, a recorder agent, crash forensics) import it.

The snapshot is cheap on purpose: ONE `sysctl` and ONE `ps` call, no `simctl`, no `lsof`
(`snapshot()` runs in well under 150 ms). Every field that cannot be read is None, and a None
never triggers a verdict. `snapshot()` returns None when `ps` fails: "unknown", and the callers
that gate work (`--admit`, `--wait`) then let the work through: the guard fails open, it must never
block work because of its own bug.

Process classes, matched on the executable (or the interpreted script of `node x.js`), never on
other arguments, and counted once: a wrapper and its child of the same kind (`node codex.js` and
the native `codex` it starts, `gradlew` and the JVM it starts) are one.

    sims        booted simulators = `launchd_sim` processes (UDIDs from `/Devices/<UDID>/` when shown)
    builds      drivers: `xcodebuild`, `swift-build|test|package`, `gradle`, `gradlew`,
                `GradleWrapperMain`, `cargo build|test`; the compilers they fan out into
                (`swift-frontend`, `clang`, `ld`, `SWBBuildService`, `XCBBuildService`) are counted
                and weighed separately
    daemons     JVM build daemons: Gradle (`GradleDaemon`) and Kotlin (`KotlinCompileDaemon`)
    agents      Claude Code, Codex and Grok processes; `lanes` = the headless ones
                (`codex exec`, `grok -p`, `claude -p`)
    browsers    Chrome renderers, and all of Chrome
    vms         `com.apple.Virtualization.*` and `qemu-system-*`
    top         the eight apps holding the most RSS (an app's helpers fold into the app)

Verdict (`assess`). CRITICAL when memory pressure is 4, swap used >= `guard.swap_crit_pct` of RAM, the
one-minute load >= `guard.load_crit_per_core` x cores, or the compressor >= `guard.compressor_crit_pct`
of RAM. BUSY for the warn thresholds of the same four, or more booted simulators than
`guard.max_sims`, or more build drivers than `guard.max_builds`.

Admission (`admit`). Any kind is refused at CRITICAL. `build` is also refused while `guard.max_builds`
drivers run, `sim` while `guard.max_sims` simulators are booted, `lane` while `guard.max_lanes` headless
lanes run. A cap of 0 means no cap. The refusal is written for an AI agent to read: why, with the
numbers, then what to do instead.

Recorder (`record`, `read_records`). One TSV line per snapshot in `~/.teyla/load.tsv` (`TEYLA_HOME`
moves it), a `#` header first. Past ~2 MB the file is rewritten with its newest half, atomically.
`--json`, `--quiet` and `--record` never exit non-zero because of the load; the text report does,
so a script can branch on it.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import fcntl
import json
import os
import pathlib
import re
import sys
import time
from typing import Callable

from . import config
from .storage_procs import parse_etime, run_command

GIB = 1024 ** 3
KIB = 1024
OK, BUSY, CRITICAL = "OK", "BUSY", "CRITICAL"
EXIT = {OK: 0, BUSY: 1, CRITICAL: 2}
EXIT_TIMEOUT = 3
KINDS = ("build", "sim", "lane")

SYSCTL_KEYS = ["hw.memsize", "hw.ncpu", "vm.loadavg", "vm.swapusage",
               "kern.memorystatus_vm_pressure_level", "vm.compressor_bytes_used"]
PS_FORMAT = "pid=,ppid=,rss=,pcpu=,etime=,command="
TOP_N = 8
RECORD_MAX_BYTES = 2 * 1024 * 1024
PROGRESS_EVERY_S = 60


# --- the shapes -------------------------------------------------------------------------------

@dataclasses.dataclass
class Daemon:
    pid: int
    kind: str                  # "gradle" | "kotlin"
    rss_bytes: int
    etime_s: int | None


@dataclasses.dataclass
class Driver:
    pid: int
    kind: str                  # "xcodebuild" | "swift" | "gradle" | "cargo"
    rss_bytes: int
    etime_s: int | None


@dataclasses.dataclass
class Vm:
    pid: int
    name: str
    rss_bytes: int


@dataclasses.dataclass
class Procs:
    sims: int = 0
    sim_udids: list = dataclasses.field(default_factory=list)
    drivers: list = dataclasses.field(default_factory=list)       # [Driver]; builds = len(drivers)
    compilers: int = 0
    compiler_rss_bytes: int = 0
    daemons: list = dataclasses.field(default_factory=list)       # [Daemon]
    claude: int = 0
    codex: int = 0
    grok: int = 0
    lanes: int = 0
    chrome_renderers: int = 0
    chrome_renderer_rss_bytes: int = 0
    chrome_rss_bytes: int = 0
    vms: list = dataclasses.field(default_factory=list)           # [Vm]
    top: list = dataclasses.field(default_factory=list)           # [[app name, rss bytes]], largest first

    @property
    def builds(self) -> int:
        return len(self.drivers)

    @property
    def daemon_rss_bytes(self) -> int:
        return sum(d.rss_bytes for d in self.daemons)

    @property
    def vm_rss_bytes(self) -> int:
        return sum(v.rss_bytes for v in self.vms)


@dataclasses.dataclass
class Snapshot:
    time: str                                  # ISO, local, with offset
    ram_bytes: int | None = None
    ncpu: int | None = None
    load1: float | None = None
    load5: float | None = None
    load15: float | None = None
    swap_total_bytes: int | None = None
    swap_used_bytes: int | None = None
    pressure: int | None = None                # 1 normal, 2 warn, 4 critical
    compressor_bytes: int | None = None
    procs: Procs = dataclasses.field(default_factory=Procs)

    def to_json(self) -> dict:
        d = dataclasses.asdict(self)
        p = d["procs"]
        p.update(builds=self.procs.builds, daemon_rss_bytes=self.procs.daemon_rss_bytes,
                 vm_rss_bytes=self.procs.vm_rss_bytes)
        return d


@dataclasses.dataclass
class Verdict:
    level: str
    reasons: list = dataclasses.field(default_factory=list)       # the critical ones first
    n_critical: int = 0                                           # how many of `reasons` are critical

    @property
    def exit_code(self) -> int:
        return EXIT[self.level]

    def line(self) -> str:
        return f"load: {self.level}" + (" — " + "; ".join(self.reasons) if self.reasons else "")

    def to_json(self) -> dict:
        return {"level": self.level, "reasons": list(self.reasons)}


# --- configuration -----------------------------------------------------------------------------

def guard_conf(cfg: dict | None = None) -> dict:
    """The `[guard]` table with defaults filled in."""
    cfg = cfg if cfg is not None else config.load()
    table = cfg.get("guard")
    return {**config.DEFAULTS["guard"], **(table if isinstance(table, dict) else {})}


def _num(conf: dict | None, key: str) -> float:
    """A numeric setting; a missing or mistyped one falls back to its default."""
    v = (conf or {}).get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        v = config.DEFAULTS["guard"][key]
    return v


def enabled(conf: dict | None) -> bool:
    v = (conf or {}).get("enabled", config.DEFAULTS["guard"]["enabled"])
    return v if isinstance(v, bool) else True


# --- sysctl ------------------------------------------------------------------------------------

_UNITS = {"K": KIB, "M": KIB ** 2, "G": KIB ** 3, "T": KIB ** 4}
_SWAP = re.compile(r"total\s*=\s*([\d.]+)\s*([KMGT])\s+used\s*=\s*([\d.]+)\s*([KMGT])", re.I)
_LOAD = re.compile(r"^\{\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\}$")


def _int(text: str) -> int | None:
    try:
        return int(text.strip())
    except ValueError:
        return None


def parse_swap(text: str) -> tuple[int | None, int | None]:
    """(total, used) bytes from `total = 13312.00M  used = 11734.19M  free = ...`."""
    m = _SWAP.search(text)
    if not m:
        return None, None
    try:
        return (int(float(m.group(1)) * _UNITS[m.group(2).upper()]),
                int(float(m.group(3)) * _UNITS[m.group(4).upper()]))
    except (ValueError, OverflowError):
        return None, None


def parse_loadavg(text: str) -> tuple[float, float, float] | None:
    m = _LOAD.match(text.strip())
    if not m:
        return None
    try:
        a, b, c = (float(x) for x in m.groups())
    except ValueError:
        return None
    return a, b, c


def parse_sysctl(text: str) -> dict:
    """The six values of `sysctl -n hw.memsize hw.ncpu vm.loadavg vm.swapusage
    kern.memorystatus_vm_pressure_level vm.compressor_bytes_used`. A field that is not what it
    should be is None. With six lines the position names the field; with fewer (a key this macOS
    does not have: sysctl prints an error and carries on) only what its shape gives away is kept:
    the load average and swap lines, the two numbers in front of them, the two behind."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: dict = dict.fromkeys(("ram_bytes", "ncpu", "load", "swap", "pressure", "compressor_bytes"))
    if len(lines) == len(SYSCTL_KEYS):
        ram, ncpu, load, swap, pressure, comp = lines
    else:
        ram = ncpu = pressure = comp = None
        load = next((ln for ln in lines if ln.startswith("{")), None)
        swap = next((ln for ln in lines if "total" in ln and "used" in ln), None)
        if load in lines and swap in lines:
            i, j = lines.index(load), lines.index(swap)
            if i == 2 and j == 3:
                ram, ncpu = lines[0], lines[1]
            if j == len(lines) - 3:
                pressure, comp = lines[j + 1], lines[j + 2]
    for key, raw in (("ram_bytes", ram), ("ncpu", ncpu), ("pressure", pressure), ("compressor_bytes", comp)):
        v = _int(raw) if raw is not None else None
        out[key] = v if v is not None and v >= 0 else None
    if out["pressure"] not in (None, 1, 2, 4):
        out["pressure"] = None
    if out["ram_bytes"] == 0:
        out["ram_bytes"] = None
    if out["ncpu"] == 0:
        out["ncpu"] = None
    out["load"] = parse_loadavg(load) if load else None
    total, used = parse_swap(swap) if swap else (None, None)
    out["swap"] = (total, used)
    return out


# --- ps and the process classes ------------------------------------------------------------------

_INTERPRETERS = re.compile(r"^(node|nodejs|bun|deno|python[\d.]*|ruby|perl|sh|bash|zsh|dash)$")
_SHELLS = {"sh", "bash", "zsh", "dash"}
_SCRIPT_EXT = (".js", ".mjs", ".cjs", ".py", ".sh", ".rb", ".pl", ".ts")
_UDID = re.compile(r"/Devices/([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})(?:/|$)")
_CLANG = re.compile(r"^clang(\+\+)?(-\d+)?$")
_COMPILERS = {"swift-frontend", "ld", "ld64", "SWBBuildService", "XCBBuildService"}
_FOLD_HELPER = re.compile(r"^(.+?) Helper(?: \(.*\))?$")
_SIMRUNTIME = re.compile(r"/([^/]+)\.simruntime/")      # a process inside a simulator: its path holds spaces


@dataclasses.dataclass
class Row:
    pid: int
    ppid: int
    rss_bytes: int
    etime_s: int | None
    command: str
    exe: str            # basename of the executable (an app's leaf name may hold spaces)
    prog: str           # exe, or the script `node x.js` runs
    args: list          # words after prog
    app: str | None     # the outermost .app bundle the command lives in
    name: str           # what `top` groups by: app, else exe


def _basename(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def parse_row(line: str) -> Row | None:
    """One line of `ps -Ao pid=,ppid=,rss=,pcpu=,etime=,command=`; None for anything else
    (a short line, a zombie shown as `(name)`)."""
    parts = line.split(None, 5)
    if len(parts) < 6:
        return None
    pid, ppid, rss, _cpu, etime, command = parts
    if not (pid.isdigit() and ppid.isdigit() and rss.isdigit()):
        return None
    command = command.strip()
    if not command or command.startswith("("):
        return None
    head = command.split(" -", 1)[0]
    app = None
    sim = _SIMRUNTIME.search(head) if command.startswith("/") else None
    if sim:
        inner = head[sim.end():].split()          # the binary's path below the runtime holds no space
        exe = prog = _basename(inner[0]) if inner else _basename(head)
        args = inner[1:] + command[len(head):].split()
        return Row(int(pid), int(ppid), int(rss) * KIB, parse_etime(etime), command, exe, prog, args, None,
                   f"{sim.group(1)} simulator")
    if command.startswith("/") and ".app/" in head:
        i = head.find(".app/")
        app = _basename(head[:i])
        macos = "/Contents/MacOS/"
        leaf = head.rsplit(macos, 1)[1] if macos in head else _basename(head)
        words = leaf.split() + command[len(head):].split()
        exe = leaf
        prog = words[0] if words else leaf
        args = words[1:]
    else:
        words = command.split()
        exe = prog = _basename(words[0])
        args = words[1:]
        if "/claude/versions/" in words[0]:           # the native installer's versioned binary
            prog = "claude"
        elif _INTERPRETERS.match(exe):
            script = None
            if exe not in _SHELLS or (args and not args[0].startswith("-")):    # `zsh -c "..."` runs no script
                script = next((a for a in args if not a.startswith("-")), None)
            if script:
                prog = _basename(script)
                for ext in _SCRIPT_EXT:
                    if prog.endswith(ext) and len(prog) > len(ext):
                        prog = prog[: -len(ext)]
                        break
                if prog == "cli" and "/claude-code/" in script:
                    prog = "claude"
                args = args[args.index(script) + 1:]
    return Row(int(pid), int(ppid), int(rss) * KIB, parse_etime(etime), command, exe, prog, args, app,
               _FOLD_HELPER.sub(r"\1", app or exe))


def parse_ps(text: str) -> list[Row]:
    rows = []
    for line in text.splitlines():
        r = parse_row(line)
        if r:
            rows.append(r)
    return rows


def _driver_kind(r: Row) -> str | None:
    p = r.prog
    if p == "xcodebuild":
        return "xcodebuild"
    if p in ("swift-build", "swift-test", "swift-package"):
        return "swift"
    if p in ("gradle", "gradlew"):
        return "gradle"
    if r.exe == "java" and ("GradleWrapperMain" in r.command or "org.gradle.launcher.GradleMain" in r.command):
        return "gradle"
    if p == "cargo" and r.args and r.args[0] in ("build", "test"):
        return "cargo"
    return None


def _daemon_kind(r: Row) -> str | None:
    if r.exe != "java":
        return None
    c = r.command
    if "GradleDaemon" in c or "org.gradle.launcher.daemon" in c:
        return "gradle"
    if "KotlinCompileDaemon" in c or "kotlin-daemon" in c or "kotlin-compiler-embeddable" in c:
        return "kotlin"
    return None


# Codex global options that take a value: `codex -m X -c k=v exec ...` still runs `exec`.
_CODEX_VALUE_OPTS = {"-m", "--model", "-c", "--config", "-p", "--profile", "-s", "--sandbox", "-a",
                     "--ask-for-approval", "-C", "--cd", "-i", "--image", "--enable", "--disable"}


def _codex_subcommand(args: list) -> str | None:
    """The first positional argument after Codex's global options. `ps` prints argv unquoted, so a
    prompt that mentions "exec" shows up as a bare word too; only the first positional counts."""
    skip = False
    for a in args:
        if skip:
            skip = False
        elif a.startswith("-"):
            skip = "=" not in a and a in _CODEX_VALUE_OPTS
        else:
            return a
    return None


def _is_lane(harness: str, args: list) -> bool:
    if harness == "codex":
        return _codex_subcommand(args) in ("exec", "e")
    if harness == "grok":
        return any(a in ("-p", "--prompt") or a.startswith("--prompt=") for a in args)
    return any(a in ("-p", "--print") for a in args)


def _roots(rows: list[Row]) -> list[Row]:
    """Rows whose parent is not also in `rows`: a wrapper and the child it starts count once."""
    pids = {r.pid for r in rows}
    return [r for r in rows if r.ppid not in pids or r.ppid == r.pid]


def classify(rows: list[Row]) -> Procs:
    """Pure: parsed `ps` rows -> the process classes."""
    out = Procs()
    sims: list[Row] = []
    drivers: list[tuple[Row, str]] = []
    harness: dict[str, list[Row]] = {"claude": [], "codex": [], "grok": []}
    by_app: dict[str, int] = {}
    for r in rows:
        by_app[r.name] = by_app.get(r.name, 0) + r.rss_bytes
        p = r.prog
        if p == "launchd_sim":
            sims.append(r)
        elif p in harness:
            harness[p].append(r)
        kind = _driver_kind(r)
        if kind:
            drivers.append((r, kind))
        if p in _COMPILERS or _CLANG.match(p):
            out.compilers += 1
            out.compiler_rss_bytes += r.rss_bytes
        dk = _daemon_kind(r)
        if dk:
            out.daemons.append(Daemon(r.pid, dk, r.rss_bytes, r.etime_s))
        if r.name == "Google Chrome":
            out.chrome_rss_bytes += r.rss_bytes
            if r.exe == "Google Chrome Helper (Renderer)":
                out.chrome_renderers += 1
                out.chrome_renderer_rss_bytes += r.rss_bytes
        if r.exe.startswith("com.apple.Virtualization") or p.startswith("qemu-system"):
            out.vms.append(Vm(r.pid, r.exe if r.exe.startswith("com.apple.") else p, r.rss_bytes))
    out.sims = len(sims)
    for r in sims:
        m = _UDID.search(r.command)
        if m and m.group(1).upper() not in out.sim_udids:
            out.sim_udids.append(m.group(1).upper())
    pids = {r.pid for r, _ in drivers}
    out.drivers = [Driver(r.pid, k, r.rss_bytes, r.etime_s) for r, k in drivers if r.ppid not in pids or r.ppid == r.pid]
    for name, rs in harness.items():
        roots = _roots(rs)
        setattr(out, name, len(roots))
        out.lanes += sum(1 for r in roots if _is_lane(name, r.args))
    out.top = [[n, b] for n, b in sorted(by_app.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N] if b > 0]
    return out


# --- the snapshot --------------------------------------------------------------------------------

Runner = Callable[..., "tuple[int, str]"]


def snapshot(run: Runner = run_command, now: dt.datetime | None = None) -> Snapshot | None:
    """One `sysctl` and one `ps`. None when `ps` could not answer (the processes are then
    unknown, not zero); an unreadable sysctl only leaves those fields None."""
    when = now or dt.datetime.now().astimezone()
    rc, out = run(["ps", "-Ao", PS_FORMAT], 15)
    rows = parse_ps(out) if rc == 0 else []
    if not rows:
        return None
    _, sysout = run(["sysctl", "-n", *SYSCTL_KEYS], 5)
    s = parse_sysctl(sysout or "")
    load = s["load"] or (None, None, None)
    total, used = s["swap"]
    return Snapshot(time=when.isoformat(timespec="seconds"), ram_bytes=s["ram_bytes"], ncpu=s["ncpu"],
                    load1=load[0], load5=load[1], load15=load[2], swap_total_bytes=total, swap_used_bytes=used,
                    pressure=s["pressure"], compressor_bytes=s["compressor_bytes"], procs=classify(rows))


def safe_snapshot(run: Runner = run_command) -> Snapshot | None:
    """`snapshot`, with any failure of the guard's own code read as "unknown"."""
    try:
        return snapshot(run)
    except Exception:  # noqa: BLE001 — the guard must never block work because of its own bug
        return None


# --- the verdict -----------------------------------------------------------------------------------

def gb(n: float | None) -> str:
    return "?" if n is None else f"{n / GIB:.1f} GB"


def _pct(part: int | None, whole: int | None) -> float | None:
    return None if part is None or not whole else part * 100.0 / whole


def assess(snap: Snapshot, conf: dict | None = None) -> Verdict:
    """OK, BUSY or CRITICAL, with one short sentence per thing that tripped. Unknown fields
    trip nothing."""
    crit: list[str] = []
    busy: list[str] = []
    ram, p = snap.ram_bytes, snap.procs

    if snap.pressure == 4:
        crit.append("memory pressure is critical (level 4)")
    elif snap.pressure == 2:
        busy.append("memory pressure is warn (level 2)")

    swap = _pct(snap.swap_used_bytes, ram)
    if swap is not None:
        label = f"swap {gb(snap.swap_used_bytes)} = {swap:.0f}% of RAM"
        if swap >= _num(conf, "swap_crit_pct"):
            crit.append(f"{label} (critical ≥ {_num(conf, 'swap_crit_pct'):g}%)")
        elif swap >= _num(conf, "swap_warn_pct"):
            busy.append(f"{label} (warn ≥ {_num(conf, 'swap_warn_pct'):g}%)")

    if snap.load1 is not None and snap.ncpu:
        label = f"load {snap.load1:.0f} on {snap.ncpu} cores"
        crit_at, warn_at = _num(conf, "load_crit_per_core") * snap.ncpu, _num(conf, "load_warn_per_core") * snap.ncpu
        if snap.load1 >= crit_at:
            crit.append(f"{label} (critical ≥ {crit_at:g})")
        elif snap.load1 >= warn_at:
            busy.append(f"{label} (warn ≥ {warn_at:g})")

    comp = _pct(snap.compressor_bytes, ram)
    if comp is not None:
        label = f"compressor {gb(snap.compressor_bytes)} = {comp:.0f}% of RAM"
        if comp >= _num(conf, "compressor_crit_pct"):
            crit.append(f"{label} (critical ≥ {_num(conf, 'compressor_crit_pct'):g}%)")
        elif comp >= _num(conf, "compressor_warn_pct"):
            busy.append(f"{label} (warn ≥ {_num(conf, 'compressor_warn_pct'):g}%)")

    max_sims, max_builds = _num(conf, "max_sims"), _num(conf, "max_builds")
    if max_sims > 0 and p.sims > max_sims:
        busy.append(f"{p.sims} simulators booted (max {max_sims:g})")
    if max_builds > 0 and p.builds > max_builds:
        busy.append(f"{p.builds} builds running (max {max_builds:g})")

    return Verdict(CRITICAL if crit else BUSY if busy else OK, crit + busy, len(crit))


# --- admission --------------------------------------------------------------------------------------

def admit(kind: str, snap: Snapshot, conf: dict | None = None) -> tuple[bool, str]:
    """(allowed, message). The message is empty when allowed; when refused it is for an AI agent:
    why, with the numbers, then what to do instead."""
    verdict = assess(snap, conf)
    p = snap.procs
    why: list[str] = []
    if verdict.level == CRITICAL:
        why.append("the machine is CRITICAL: " + "; ".join(verdict.reasons[:verdict.n_critical]))
    cap = _num(conf, {"build": "max_builds", "sim": "max_sims", "lane": "max_lanes"}.get(kind, ""))
    if kind == "build" and cap > 0 and p.builds >= cap:
        why.append(f"{p.builds} builds already run (max {cap:g})")
    elif kind == "sim" and cap > 0 and p.sims >= cap:
        why.append(f"{p.sims} simulators are already booted (max {cap:g})")
    elif kind == "lane" and cap > 0 and p.lanes >= cap:
        why.append(f"{p.lanes} headless agent lanes already run (max {cap:g})")
    if not why:
        return True, ""
    lines = [f"teyla guard: {kind} refused — " + "; ".join(why)]
    if kind == "sim":
        udids = ", ".join(p.sim_udids)
        lines.append("Reuse an already-booted simulator instead of booting another"
                     + (f" ({udids})." if udids else " (`xcrun simctl list devices booted`)."))
    elif kind == "build":
        lines.append("Let the builds already running finish instead of starting another in parallel.")
    else:
        lines.append("Run the work in a session you already have instead of starting another lane.")
    lines.append(f"Or wait for a slot: `teyla load --wait --kind {kind}` (exit 0 when free, 3 on timeout).")
    lines.append("Or free capacity yourself: shut down the simulators you booted and stop idle Gradle/Kotlin"
                 " daemons you started; leave other agents' processes alone.")
    return False, "\n".join(lines)


def wait(kind: str, conf: dict | None = None, timeout_s: float | None = None, poll_s: float = 15,
         clock: Callable[[], float] | None = None, sleeper: Callable[[float], None] | None = None,
         snap_fn: Callable[[], Snapshot | None] | None = None, out=None, err=None) -> int:
    """Poll `snap_fn` + `admit` until allowed (0) or `timeout_s` (default `guard.wait_timeout_s`) runs
    out (3, the last refusal printed to `out`). One progress line per minute at most, to `err`.
    A snapshot that fails lets the work through (0)."""
    out = out or sys.stdout
    err = err or sys.stderr
    clock = clock or time.monotonic
    sleeper = sleeper or time.sleep
    snap_fn = snap_fn or safe_snapshot
    timeout = _num(conf, "wait_timeout_s") if timeout_s is None else timeout_s
    start = clock()
    last_progress: float | None = None
    while True:
        snap = snap_fn()
        if snap is None:
            return 0
        allowed, msg = admit(kind, snap, conf)
        if allowed:
            return 0
        now = clock()
        elapsed = now - start
        if elapsed >= timeout:
            print(msg, file=out)
            return EXIT_TIMEOUT
        if last_progress is None or now - last_progress >= PROGRESS_EVERY_S:
            last_progress = now
            first = msg.splitlines()[0].removeprefix("teyla guard: ")
            print(f"teyla load: waiting ({int(elapsed)}s of {int(timeout)}s) — {first}", file=err)
        sleeper(max(0.0, min(poll_s, timeout - elapsed)))


# --- the recorder -----------------------------------------------------------------------------------

COLUMNS = ["time", "level", "pressure", "load1", "swap_used_bytes", "ram_bytes", "compressor_bytes", "sims",
           "builds", "compiler_rss_bytes", "daemon_rss_bytes", "claude", "codex", "grok", "lanes",
           "chrome_rss_bytes", "vm_rss_bytes", "top3"]
_INT_COLS = {"pressure", "swap_used_bytes", "ram_bytes", "compressor_bytes", "sims", "builds", "compiler_rss_bytes",
             "daemon_rss_bytes", "claude", "codex", "grok", "lanes", "chrome_rss_bytes", "vm_rss_bytes"}


def record_path() -> pathlib.Path:
    from .corrections import teyla_home
    return teyla_home() / "load.tsv"


_TOP_UNSAFE = re.compile(r"[,:\t\r\n]")


def _top3(snap: Snapshot) -> str:
    return ",".join(f"{_TOP_UNSAFE.sub('_', n)}:{b / GIB:.1f}" for n, b in snap.procs.top[:3])


def record_fields(snap: Snapshot, verdict: Verdict) -> list[str]:
    p = snap.procs
    vals = [snap.time, verdict.level, snap.pressure, None if snap.load1 is None else f"{snap.load1:.2f}",
            snap.swap_used_bytes, snap.ram_bytes, snap.compressor_bytes, p.sims, p.builds, p.compiler_rss_bytes,
            p.daemon_rss_bytes, p.claude, p.codex, p.grok, p.lanes, p.chrome_rss_bytes, p.vm_rss_bytes, _top3(snap)]
    return ["" if v is None else str(v) for v in vals]


def _trim(path: pathlib.Path, max_bytes: int) -> None:
    """Over `max_bytes`: rewrite the file as its header and its newest half of the lines, atomically."""
    try:
        if path.stat().st_size <= max_bytes:
            return
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return
    header = [ln for ln in lines[:1] if ln.startswith("#")]
    data = [ln for ln in lines if not ln.startswith("#")]
    keep = header + data[len(data) // 2:]
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        tmp.write_text("\n".join(keep) + "\n")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def record(snap: Snapshot, verdict: Verdict, path: pathlib.Path | None = None,
           max_bytes: int = RECORD_MAX_BYTES) -> pathlib.Path:
    """Append one TSV line to `~/.teyla/load.tsv` (header first in a new file); keep the file bounded."""
    path = pathlib.Path(path) if path else record_path()
    config.private_dir(path.parent)
    # One lock around trim + append: a trim that read the file before another recorder's append
    # and replaced it after would silently drop that line.
    lock = os.open(path.with_name(path.name + ".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _trim(path, max_bytes)
        new = not path.exists() or path.stat().st_size == 0
        text = ("#" + "\t".join(COLUMNS) + "\n" if new else "") + "\t".join(record_fields(snap, verdict)) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, text.encode())
        finally:
            os.close(fd)
    finally:
        os.close(lock)                       # closing the descriptor releases the lock
    return path


def _when(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.astimezone()).timestamp()
    return float(v)


def parse_record(line: str) -> dict | None:
    cells = line.rstrip("\n").split("\t")
    if len(cells) != len(COLUMNS) or line.startswith("#"):
        return None
    rec: dict = dict(zip(COLUMNS, cells))
    try:
        rec["ts"] = dt.datetime.fromisoformat(rec["time"]).timestamp()
        for k in _INT_COLS:
            rec[k] = int(rec[k]) if rec[k] != "" else None
        rec["load1"] = float(rec["load1"]) if rec["load1"] != "" else None
        top = []
        for item in rec["top3"].split(","):
            if item:
                n, _, g = item.rpartition(":")
                top.append((n, float(g)))
        rec["top3"] = top
    except (ValueError, OverflowError):
        return None
    if rec["level"] not in EXIT:
        return None
    return rec


def read_records(since=None, until=None, path: pathlib.Path | None = None) -> list[dict]:
    """The recorded lines as dicts (`time` as written, `ts` epoch seconds, numbers parsed, empty
    cells None, `top3` as [(name, GB)]), oldest first. `since` and `until` are datetimes or epoch
    seconds. Malformed lines and the header are skipped."""
    path = pathlib.Path(path) if path else record_path()
    lo, hi = _when(since), _when(until)
    out = []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        rec = parse_record(line)
        if rec is None or (lo is not None and rec["ts"] < lo) or (hi is not None and rec["ts"] > hi):
            continue
        out.append(rec)
    return out


# --- the report ----------------------------------------------------------------------------------------

def _mins(s: int | None) -> str:
    return "" if s is None else f" {s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f" {s // 60}m"


def render(snap: Snapshot, verdict: Verdict) -> str:
    p = snap.procs
    lines = [verdict.line()]
    mem = [f"{gb(snap.ram_bytes)} RAM"]
    if snap.swap_used_bytes is not None:
        pct = _pct(snap.swap_used_bytes, snap.ram_bytes)
        mem.append(f"swap {gb(snap.swap_used_bytes)}" + (f" of {gb(snap.swap_total_bytes)}" if snap.swap_total_bytes else "")
                   + (f" ({pct:.0f}% of RAM)" if pct is not None else ""))
    if snap.compressor_bytes is not None:
        mem.append(f"compressor {gb(snap.compressor_bytes)}")
    if snap.pressure is not None:
        mem.append("pressure " + {1: "normal", 2: "warn", 4: "critical"}.get(snap.pressure, str(snap.pressure)))
    lines.append("memory: " + " · ".join(mem))
    if snap.load1 is not None:
        lines.append(f"cpu: load {snap.load1:.1f} / {snap.load5:.1f} / {snap.load15:.1f} on {snap.ncpu or '?'} cores")
    lines.append(f"sims: {p.sims} booted" + (f" ({', '.join(u[:8] for u in p.sim_udids)})" if p.sim_udids else ""))
    drivers = ", ".join(f"{d.kind}{_mins(d.etime_s)}" for d in p.drivers)
    lines.append(f"builds: {p.builds} running" + (f" ({drivers})" if drivers else "")
                 + f"; compilers {p.compilers} ({gb(p.compiler_rss_bytes)})")
    kinds = ", ".join(f"{d.kind} {gb(d.rss_bytes)}{_mins(d.etime_s)}" for d in p.daemons)
    lines.append(f"daemons: {len(p.daemons)} JVM" + (f" ({kinds})" if kinds else ""))
    lines.append(f"agents: claude {p.claude} · codex {p.codex} · grok {p.grok} · headless lanes {p.lanes}")
    lines.append(f"browsers: Chrome {gb(p.chrome_rss_bytes)} ({p.chrome_renderers} renderers, {gb(p.chrome_renderer_rss_bytes)})")
    lines.append(f"vms: {len(p.vms)} ({gb(p.vm_rss_bytes)})")
    if p.top:
        lines.append("top: " + ", ".join(f"{n} {gb(b)}" for n, b in p.top))
    return "\n".join(lines)


# --- the command ----------------------------------------------------------------------------------------

def cmd_load(args, run: Runner = run_command) -> int:
    conf = guard_conf()
    if args.admit:
        if not enabled(conf):
            return 0
        snap = safe_snapshot(run)
        if snap is None:
            return 0
        allowed, msg = admit(args.admit, snap, conf)
        if not allowed:
            print(msg)
            return 2
        return 0
    if args.wait:
        if not enabled(conf):
            return 0
        return wait(args.kind, conf, args.timeout)
    snap = safe_snapshot(run)
    if snap is None:
        print("teyla load: could not read the process table (ps failed); load unknown", file=sys.stderr)
        return 0
    verdict = assess(snap, conf)
    if args.record:
        try:
            record(snap, verdict)
        except OSError as e:
            print(f"teyla load: could not record: {e}", file=sys.stderr)
    if args.json:
        print(json.dumps({"snapshot": snap.to_json(), "verdict": verdict.to_json()}, indent=1))
        return 0
    if args.quiet:
        return 0
    print(render(snap, verdict))
    return verdict.exit_code


def register(sp):
    q = sp.add_parser("load", help="machine load: snapshot, verdict, recorder, admission check and wait-for-a-slot",
                      description=__doc__.split("\n\n")[0] + "\n\nExit codes: 0 OK, 1 BUSY, 2 CRITICAL (--admit: 2 refused; --wait: 3 timeout).")
    q.set_defaults(fn=cmd_load)
    q.add_argument("--json", action="store_true", help="the snapshot and the verdict as JSON (exit 0)")
    q.add_argument("--record", action="store_true", help="append one line to ~/.teyla/load.tsv")
    q.add_argument("--quiet", action="store_true", help="print nothing (with --record: the recorder's mode); exit 0")
    q.add_argument("--admit", choices=KINDS, metavar="KIND", help="build|sim|lane: silent exit 0 when allowed; the refusal and exit 2 when not")
    q.add_argument("--wait", action="store_true", help="poll until --kind is allowed (exit 0) or the timeout (exit 3)")
    q.add_argument("--kind", choices=KINDS, default="build", help="what --wait waits to start (default build)")
    q.add_argument("--timeout", type=float, default=None, metavar="S", help="--wait: give up after S seconds (default guard.wait_timeout_s)")
    return q

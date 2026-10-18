"""`teyla load` — how loaded this machine is right now, a verdict, a recorder and a wait-for-a-slot.

    teyla load [--json] [--record] [--quiet]     snapshot + verdict; exit 0 OK, 1 BUSY, 2 CRITICAL
    teyla load --admit build|sim|lane            silent exit 0 when allowed; the refusal and exit 2 when not
    teyla load --wait --kind build|sim|lane      poll until a slot is free (exit 0) or the timeout (exit 3)
    teyla load --replay [--days N] [--day D]     the verdict and the admissions over the recorded days

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

Verdict (`assess`). CRITICAL when memory pressure is 4, swap used >= `guard.swap_crit_pct` of RAM while pressure is >= 2, the
one-minute load >= `guard.load_crit_per_core` x cores, or the compressor >= `guard.compressor_crit_pct`
of RAM, or free disk under `guard.disk_crit_gb` (APFS swap lives in the same container, so a full disk
leaves the memory compressor nowhere to go). WORSENING (needs the trend, below) when memory is getting worse
right now: the swap-out rate over the last 3 minutes >= `guard.swapout_mb_s`, swap used growing by more than
`guard.swap_grow_gb_30m` per 30 minutes (fitted over `guard.trend_window_min` minutes, and still growing in the last 5),
or free disk on course to fall under `guard.disk_crit_gb` within 30 minutes. BUSY for the warn thresholds of
memory pressure, compressor, load and disk, or more booted simulators than `guard.max_sims`, or more build
drivers than `guard.max_builds`. Swap used alone is information, not a warning: it stayed above 25% of RAM on
70-95% of samples every day and carried no signal.

Trend (`compute_trend`, `current_trend`). Pure over the rows of `load.tsv` from the last
`trend_window_min + hold_min` minutes (read from the end of the file) plus the sample being judged. A slope
needs 4 points and 5 minutes of history, the swap-out rate only 30 seconds. `snapshot()` reads the cumulative
Swapouts and Pageouts counters from `vm_stat`; `record` stores them and the rate against the previous row.

Admission (`decide`, `admit`). Any kind is refused at CRITICAL. A new `sim` or `build` is also refused, whatever
the count, while the machine is WORSENING and for `guard.hold_min` minutes after the last CRITICAL or WORSENING
sample (the hold reads the levels the tick recorded and the verdicts of logged decisions, so a hook that saw the
spike between two ticks counts). Running work is never touched; lanes are refused only at CRITICAL. `build` is
also refused while `guard.max_builds` drivers run, `sim` while `guard.max_sims` simulators are booted, `lane`
while `guard.max_lanes` headless lanes run. A cap of 0 means no cap. The refusal is written for an AI agent:
why, with the numbers, then what to do instead. `--wait` polls until the refusal clears or `guard.wait_timeout_s`.

Recorder (`record`, `read_records`). One TSV line per snapshot in `~/.teyla/load.tsv` (`TEYLA_HOME`
moves it), a `#` header first. Past ~2 MB the file is rewritten with its newest half, atomically.
`--json`, `--quiet` and `--record` never exit non-zero because of the load; the text report does,
so a script can branch on it.

Decision log (`log_decision`). Every `--admit` and every `--wait` appends what it decided to
`~/.teyla/guard-decisions.tsv`: time, kind, verdict, admitted or refused, reason, cwd, harness. A wait
logs once, when it ends (admitted after N s, or refused at the timeout), not once per poll. The file keeps
its newest half past 512 KB. `teyla load` prints the last hour's counts.

Replay (`replay`). `teyla load --replay [--days N]` runs `assess` and `decide` over `load.tsv` with the same
history the live guard has (levels recomputed, not the recorded ones) and prints, per day, how many samples come
out OK, BUSY, WORSENING and CRITICAL, how many of them would let a simulator or a build start, and the refusals the
memory state causes: minutes, episodes (each is one wait an agent would hit) and the longest. `--day YYYY-MM-DD`
lists the changes of state of one day. The recorded rows lack some inputs (cores, swap total), so a replay is an
estimate for tuning thresholds, not a reconstruction.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import fcntl
import json
import math
import os
import pathlib
import re
import shutil
import sys
import time
from typing import Callable

from . import config
from .storage_procs import parse_etime, run_command

GIB = 1024 ** 3
KIB = 1024
OK, BUSY, WORSENING, CRITICAL = "OK", "BUSY", "WORSENING", "CRITICAL"
EXIT = {OK: 0, BUSY: 1, WORSENING: 1, CRITICAL: 2}
BAD = (WORSENING, CRITICAL)                    # the levels that start a hold
EXIT_TIMEOUT = 3
KINDS = ("build", "sim", "lane")

VM_STAT = ["vm_stat"]
SYSCTL_KEYS = ["hw.memsize", "hw.ncpu", "vm.loadavg", "vm.swapusage",
               "kern.memorystatus_vm_pressure_level", "vm.compressor_bytes_used"]
PS_FORMAT = "pid=,ppid=,rss=,pcpu=,etime=,command="
TOP_N = 8
RECORD_MAX_BYTES = 2 * 1024 * 1024
DECISIONS_MAX_BYTES = 512 * 1024
DECISION_WINDOW_S = 3600
RECENT_S = 300              # "still happening": the last five minutes
SWAPOUT_WINDOW_S = 180      # the swap-out rate is measured over the last three minutes
MIN_SPAN_S = 300            # a slope needs this much history ...
MIN_POINTS = 4              # ... and this many points
MAX_RATE_GAP_S = 300        # a rate between two rows further apart than this is not recorded
RECENT_GROWTH_GB = 0.2      # growth in the last five minutes that counts as "still growing"
TAIL_BYTES = 64 * 1024      # how much of the end of load.tsv the trend reads
PROGRESS_EVERY_S = 60


# --- the shapes -------------------------------------------------------------------------------

@dataclasses.dataclass
class Daemon:
    pid: int
    kind: str                  # "gradle" | "kotlin"
    rss_bytes: int
    etime_s: int | None
    cpu: float | None = None   # `ps` %cpu; the idle-daemon reaper treats ~0 as idle


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
    kotlinc: int = 0                                              # running `kotlinc` clients (a Kotlin daemon's users)
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
    disk_free_bytes: int | None = None         # the home volume
    swapout_bytes: int | None = None           # `vm_stat` Swapouts, cumulative since boot
    pageout_bytes: int | None = None           # `vm_stat` Pageouts, cumulative since boot
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
    reasons: list = dataclasses.field(default_factory=list)       # the critical ones first, then the worsening ones
    n_critical: int = 0                                           # how many of `reasons` are critical
    worsening: list = dataclasses.field(default_factory=list)     # the trend reasons (set even when CRITICAL)

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


_VM_PAGE = re.compile(r"page size of (\d+) bytes")
_VM_COUNTER = re.compile(r"^(Swapouts|Pageouts):\s+(\d+)\.?\s*$", re.M)


def parse_vm_stat(text: str) -> tuple[int | None, int | None]:
    """(swapouts, pageouts) in bytes, cumulative since boot, from `vm_stat`. (None, None) when the
    output is not what it should be."""
    m = _VM_PAGE.search(text or "")
    size = int(m.group(1)) if m else 16384
    got = {k: int(v) * size for k, v in _VM_COUNTER.findall(text or "")}
    return got.get("Swapouts"), got.get("Pageouts")


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
    cpu: float = 0.0    # `ps` %cpu


def _basename(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1]


def parse_row(line: str) -> Row | None:
    """One line of `ps -Ao pid=,ppid=,rss=,pcpu=,etime=,command=`; None for anything else
    (a short line, a zombie shown as `(name)`)."""
    parts = line.split(None, 5)
    if len(parts) < 6:
        return None
    pid, ppid, rss, pcpu, etime, command = parts
    if not (pid.isdigit() and ppid.isdigit() and rss.isdigit()):
        return None
    try:
        cpu = float(pcpu)
    except ValueError:
        cpu = 0.0
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
                   f"{sim.group(1)} simulator", cpu)
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
               _FOLD_HELPER.sub(r"\1", app or exe), cpu)


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


_DAEMON_MAIN = {
    "org.gradle.launcher.daemon.bootstrap.GradleDaemon": "gradle",
    "org.jetbrains.kotlin.daemon.KotlinCompileDaemon": "kotlin",
}


def _daemon_kind(r: Row) -> str | None:
    if r.exe != "java":
        return None
    # The main class, as its own argument: a jar name on some other app's classpath
    # (kotlin-compiler-embeddable is a library too) does not make that app a build daemon,
    # and the guard agent stops idle daemons.
    return _DAEMON_MAIN.get(_java_main(r.args))


# java options whose value is the next argument; the main class is the first argument after the options.
_JAVA_VALUE_OPTS = {"-cp", "-classpath", "--class-path", "-p", "--module-path", "--upgrade-module-path",
                    "--add-modules", "--add-opens", "--add-exports", "--add-reads", "--patch-module",
                    "--limit-modules", "--enable-native-access"}


def _java_main(args: list) -> str | None:
    """The main class java was started with: the first argument that is neither an option nor an
    option's value. `-jar` means a jar's manifest decides, `-m` a module: neither is a daemon class.
    Words after the main class are the program's own arguments and never count."""
    skip = False
    for a in args:
        if skip:
            skip = False
        elif a in ("-jar", "-m", "--module"):
            return None
        elif a in _JAVA_VALUE_OPTS:
            skip = True
        elif not a.startswith("-"):
            return a
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
            out.daemons.append(Daemon(r.pid, dk, r.rss_bytes, r.etime_s, r.cpu))
        if (p.startswith("kotlinc") and r.exe != "java") or (r.exe == "java" and "K2JVMCompiler" in r.command):
            out.kotlinc += 1
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


def disk_free() -> int | None:
    """Free bytes on the home volume; None when it cannot be read."""
    try:
        return shutil.disk_usage(str(pathlib.Path.home())).free
    except OSError:
        return None


def snapshot(run: Runner = run_command, now: dt.datetime | None = None, vm: bool = True) -> Snapshot | None:
    """One `sysctl`, one `ps` and (`vm`) one `vm_stat`. None when `ps` could not answer (the processes
    are then unknown, not zero); an unreadable sysctl or vm_stat only leaves those fields None."""
    when = now or dt.datetime.now().astimezone()
    rc, out = run(["ps", "-Ao", PS_FORMAT], 15)
    rows = parse_ps(out) if rc == 0 else []
    if not rows:
        return None
    _, sysout = run(["sysctl", "-n", *SYSCTL_KEYS], 5)
    s = parse_sysctl(sysout or "")
    swapouts = pageouts = None
    if vm:
        vrc, vout = run(VM_STAT, 5)
        if vrc == 0:
            swapouts, pageouts = parse_vm_stat(vout)
    load = s["load"] or (None, None, None)
    total, used = s["swap"]
    return Snapshot(time=when.isoformat(timespec="seconds"), ram_bytes=s["ram_bytes"], ncpu=s["ncpu"],
                    load1=load[0], load5=load[1], load15=load[2], swap_total_bytes=total, swap_used_bytes=used,
                    pressure=s["pressure"], compressor_bytes=s["compressor_bytes"], disk_free_bytes=disk_free(),
                    swapout_bytes=swapouts, pageout_bytes=pageouts, procs=classify(rows))


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


def _worsening(trend: "Trend | None", snap: Snapshot, conf: dict | None) -> list[str]:
    """What the trend says is getting worse, one sentence each. Each rule needs its own history and says nothing without it."""
    if trend is None:
        return []
    out = []
    rate, rate_at = trend.swapout_mb_s, _num(conf, "swapout_mb_s")
    if rate is not None and rate_at > 0 and rate >= rate_at:
        out.append(f"swap-out {rate:.0f} MB/s over the last {SWAPOUT_WINDOW_S // 60} min (worsening ≥ {rate_at:g} MB/s)")
    grow_at = _num(conf, "swap_grow_gb_30m")
    if (trend.swap_gb_30m is not None and grow_at > 0 and trend.swap_gb_30m > grow_at
            and trend.swap_recent_gb is not None and trend.swap_recent_gb > RECENT_GROWTH_GB):
        out.append(f"swap growing {trend.swap_gb_30m:.1f} GB per 30 min (+{trend.swap_recent_gb:.1f} GB in the last 5 min;"
                   f" worsening > {grow_at:g} GB)")
    crit_gb = _num(conf, "disk_crit_gb")
    free = snap.disk_free_bytes
    if (trend.disk_free_30m_gb is not None and free is not None and free >= crit_gb * GIB
            and trend.disk_free_30m_gb < crit_gb and trend.disk_recent_gb is not None and trend.disk_recent_gb > RECENT_GROWTH_GB):
        out.append(f"disk {gb(free)} free and falling: {trend.disk_free_30m_gb:.1f} GB in 30 min, under the"
                   f" {crit_gb:g} GB critical line")
    return out


def assess(snap: Snapshot, conf: dict | None = None, trend: "Trend | None" = None) -> Verdict:
    """OK, BUSY, WORSENING or CRITICAL, with one short sentence per thing that tripped. Unknown fields
    trip nothing. WORSENING needs the `trend` (history of the last minutes); without one the verdict is
    the snapshot's alone."""
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
        # Swapped-out pages stay in swap long after the pressure that pushed them out is gone: swap used
        # is information, not a warning (it kept BUSY on 70-95% of samples every day). It is CRITICAL only
        # while the kernel still reports pressure; whether swap is growing is the trend's job.
        under_pressure = snap.pressure is not None and snap.pressure >= 2
        if swap >= _num(conf, "swap_crit_pct") and under_pressure:
            crit.append(f"{label} (critical ≥ {_num(conf, 'swap_crit_pct'):g}% under memory pressure)")

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

    free = snap.disk_free_bytes
    if free is not None:
        label = f"{gb(free)} free on disk"
        crit_gb, warn_gb = _num(conf, "disk_crit_gb"), _num(conf, "disk_warn_gb")
        if free < crit_gb * GIB:
            crit.append(f"{label} (critical < {crit_gb:g} GB: swap and builds have no room left)")
        elif free < warn_gb * GIB:
            busy.append(f"{label} (warn < {warn_gb:g} GB)")

    max_sims, max_builds = _num(conf, "max_sims"), _num(conf, "max_builds")
    if max_sims > 0 and p.sims > max_sims:
        busy.append(f"{p.sims} simulators booted (max {max_sims:g})")
    if max_builds > 0 and p.builds > max_builds:
        busy.append(f"{p.builds} builds running (max {max_builds:g})")

    worse = _worsening(trend, snap, conf)
    return Verdict(CRITICAL if crit else WORSENING if worse else BUSY if busy else OK, crit + worse + busy, len(crit), worse)


# --- the trend ----------------------------------------------------------------------------------------

@dataclasses.dataclass
class Trend:
    """What the last minutes say. A field is None when its history is too short to say anything."""
    swap_gb_30m: float | None = None          # swap growth projected to 30 min, from the last `trend_window_min`
    swap_recent_gb: float | None = None       # swap growth in the last 5 min
    disk_free_30m_gb: float | None = None     # free disk projected 30 min ahead
    disk_recent_gb: float | None = None       # disk used up in the last 5 min (positive = falling)
    swapout_mb_s: float | None = None         # swap-out rate over the last 3 min
    points: int = 0
    span_s: float = 0
    held_level: str | None = None             # the newest CRITICAL or WORSENING sample inside the hold window
    held_ago_s: float | None = None
    hold_s: float = 0

    def to_json(self) -> dict:
        return dataclasses.asdict(self)

    def hold_left_s(self) -> float | None:
        """Seconds of hold left; None when no hold is running."""
        if self.held_ago_s is None or self.hold_s <= 0:
            return None
        left = self.hold_s - self.held_ago_s
        return left if left > 0 else None


def snap_ts(snap: Snapshot) -> float:
    try:
        return dt.datetime.fromisoformat(snap.time).timestamp()
    except ValueError:
        return time.time()


def point_of(snap: Snapshot, level: str | None = None) -> dict:
    """The few numbers the trend needs, in the shape of a `load.tsv` row."""
    return {"ts": snap_ts(snap), "swap_used_bytes": snap.swap_used_bytes, "disk_free_bytes": snap.disk_free_bytes,
            "swapout_bytes": snap.swapout_bytes, "level": level}


def _slope(pts: list[tuple[float, float]]) -> float | None:
    """Least-squares slope of (seconds, value) per second; None for fewer than two distinct times."""
    n = len(pts)
    if n < 2:
        return None
    mx, my = sum(x for x, _ in pts) / n, sum(y for _, y in pts) / n
    var = sum((x - mx) ** 2 for x, _ in pts)
    return None if var == 0 else sum((x - mx) * (y - my) for x, y in pts) / var


def history_s(conf: dict | None) -> float:
    """How far back the trend and the hold look."""
    return (_num(conf, "trend_window_min") + _num(conf, "hold_min")) * 60


def compute_trend(history: list[dict], snap: Snapshot, conf: dict | None = None, decisions: list[dict] | tuple = ()) -> Trend:
    """Pure. `history` are earlier rows (dicts with ts, swap_used_bytes, disk_free_bytes, swapout_bytes, level),
    `snap` the sample being judged, `decisions` the logged admission decisions (their `verdict` counts for
    the hold like a row's level does: a hook that saw the spike between two ticks leaves a mark too)."""
    cur = point_of(snap)
    now = cur["ts"]
    window = _num(conf, "trend_window_min") * 60
    pts = sorted((h for h in history if now - window <= h["ts"] < now), key=lambda h: h["ts"]) + [cur]
    t = Trend(points=len(pts), span_s=now - pts[0]["ts"])

    def series(key):
        return [(h["ts"] - now, h[key]) for h in pts if h.get(key) is not None]

    def recent_base(key):
        base = [h for h in pts[:-1] if h["ts"] >= now - RECENT_S and h.get(key) is not None]
        return base[0] if base else None

    enough = len(pts) >= MIN_POINTS and t.span_s >= MIN_SPAN_S
    swap, disk = series("swap_used_bytes"), series("disk_free_bytes")
    if enough and len(swap) >= MIN_POINTS and cur["swap_used_bytes"] is not None:
        slope = _slope(swap)
        if slope is not None:
            t.swap_gb_30m = slope * 1800 / GIB
        base = recent_base("swap_used_bytes")
        if base:
            t.swap_recent_gb = (cur["swap_used_bytes"] - base["swap_used_bytes"]) / GIB
    if enough and len(disk) >= MIN_POINTS and cur["disk_free_bytes"] is not None:
        slope = _slope(disk)
        if slope is not None:
            t.disk_free_30m_gb = (cur["disk_free_bytes"] + slope * 1800) / GIB
        base = recent_base("disk_free_bytes")
        if base:
            t.disk_recent_gb = (base["disk_free_bytes"] - cur["disk_free_bytes"]) / GIB
    # The swap-out rate has its own, shorter history: it does not wait for the slopes.
    so = [h for h in pts if h["ts"] >= now - SWAPOUT_WINDOW_S and h.get("swapout_bytes") is not None]
    if len(so) >= 2 and so[-1] is cur and cur["ts"] - so[0]["ts"] >= 30:
        delta = cur["swapout_bytes"] - so[0]["swapout_bytes"]
        if delta >= 0:                               # a smaller counter is a reboot
            t.swapout_mb_s = delta / (cur["ts"] - so[0]["ts"]) / 1024 ** 2
    t.hold_s = _num(conf, "hold_min") * 60
    if t.hold_s > 0:
        bad = [(h["ts"], h["level"]) for h in history if h.get("level") in BAD]
        bad += [(d["ts"], d["verdict"]) for d in decisions if d.get("verdict") in BAD]
        bad = [b for b in bad if now - t.hold_s <= b[0] <= now]
        if bad:
            ts, level = max(bad)
            t.held_level, t.held_ago_s = level, now - ts
    return t


def _tail(path: pathlib.Path, max_bytes: int = TAIL_BYTES) -> list[str]:
    """The last lines of a file (the first of a long file's tail is cut and dropped)."""
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            f.seek(max(0, size - max_bytes))
            data = f.read().decode(errors="replace")
    except OSError:
        return []
    lines = data.splitlines()
    return lines[1:] if size > max_bytes and lines else lines


def read_tail_records(since: float, path: pathlib.Path | None = None) -> list[dict]:
    """The `load.tsv` rows from `since` (epoch seconds) on, read from the end of the file only."""
    path = pathlib.Path(path) if path else record_path()
    return [r for r in (parse_record(ln) for ln in _tail(path)) if r is not None and r["ts"] >= since]


def current_trend(snap: Snapshot, conf: dict | None = None, records: pathlib.Path | None = None,
                  decisions: pathlib.Path | None = None) -> Trend | None:
    """The trend for `snap` from the recorder's file and the decision log. None when anything fails: the
    guard falls back to the snapshot alone."""
    try:
        since = snap_ts(snap) - history_s(conf)
        rows = read_tail_records(since, records)
        decs = [d for d in read_decisions(since=since, path=decisions, tail=True)]
        return compute_trend(rows, snap, conf, decs)
    except Exception:  # noqa: BLE001 — the guard must never block work because of its own bug
        return None


# --- admission --------------------------------------------------------------------------------------

@dataclasses.dataclass
class Decision:
    allowed: bool
    message: str = ""                                             # for an AI agent; empty when allowed
    level: str = OK                                               # the verdict it was made under
    reason: str = ""                                              # one line, for the log


def decide(kind: str, snap: Snapshot, conf: dict | None = None, trend: Trend | None = None) -> Decision:
    """The admission decision for `kind`, with the verdict it was made under and a one-line reason.

    CRITICAL refuses every kind. A new simulator or build is also refused, whatever the count, while the
    machine is WORSENING and for `guard.hold_min` minutes after the last CRITICAL or WORSENING sample (the
    hold: the alert flapped four times in 30 minutes on 2026-10-18 and a simulator and a second build were
    admitted in the gaps). Running work is never touched. Lanes are agent sessions, not memory hogs: only
    CRITICAL stops them."""
    verdict = assess(snap, conf, trend)
    p = snap.procs
    why: list[str] = []
    waiting = False                              # the refusal clears by itself with time
    if verdict.level == CRITICAL:
        why.append("the machine is CRITICAL: " + "; ".join(verdict.reasons[:verdict.n_critical]))
    elif kind in ("sim", "build") and verdict.level == WORSENING:
        why.append("the machine is getting worse: " + "; ".join(verdict.worsening))
        waiting = True
    elif kind in ("sim", "build") and trend is not None and _num(conf, "hold_min") > 0 and trend.hold_left_s() is not None:
        left = trend.hold_left_s()
        why.append(f"held after {trend.held_level} {int(trend.held_ago_s // 60)} min ago: new simulators and builds wait"
                   f" until {_num(conf, 'hold_min'):g} min pass without it ({math.ceil(left / 60)} min left)")
        waiting = True
    cap = _num(conf, {"build": "max_builds", "sim": "max_sims", "lane": "max_lanes"}.get(kind, ""))
    if kind == "build" and cap > 0 and p.builds >= cap:
        why.append(f"{p.builds} builds already run (max {cap:g})")
    elif kind == "sim" and cap > 0 and p.sims >= cap:
        why.append(f"{p.sims} simulators are already booted (max {cap:g})")
    elif kind == "lane" and cap > 0 and p.lanes >= cap:
        why.append(f"{p.lanes} headless agent lanes already run (max {cap:g})")
    if not why:
        return Decision(True, "", verdict.level, "")
    lines = [f"teyla guard: {kind} refused — " + "; ".join(why)]
    if kind == "sim":
        udids = ", ".join(p.sim_udids)
        lines.append("Reuse an already-booted simulator instead of booting another"
                     + (f" ({udids})." if udids else " (`xcrun simctl list devices booted`)."))
    elif kind == "build":
        lines.append("Let the builds already running finish instead of starting another in parallel.")
    else:
        lines.append("Run the work in a session you already have instead of starting another lane.")
    if snap.disk_free_bytes is not None and snap.disk_free_bytes < _num(conf, "disk_crit_gb") * GIB:
        lines.append("Free disk first: `teyla storage sweep --temp` and `teyla storage clean --apply` remove idle"
                     " build output and finished worktrees; `teyla storage` lists what else holds space.")
    if waiting:
        lines.append("Work already running is not affected.")
    lines.append(f"Or wait for a slot: `teyla load --wait --kind {kind}` (exit 0 when free, 3 on timeout).")
    lines.append("Or free capacity yourself: shut down the simulators you booted and stop idle Gradle/Kotlin"
                 " daemons you started; leave other agents' processes alone.")
    return Decision(False, "\n".join(lines), verdict.level, "; ".join(why))


def admit(kind: str, snap: Snapshot, conf: dict | None = None) -> tuple[bool, str]:
    """(allowed, message). The message is empty when allowed; when refused it is for an AI agent:
    why, with the numbers, then what to do instead."""
    d = decide(kind, snap, conf)
    return d.allowed, d.message


def wait(kind: str, conf: dict | None = None, timeout_s: float | None = None, poll_s: float = 15,
         clock: Callable[[], float] | None = None, sleeper: Callable[[float], None] | None = None,
         snap_fn: Callable[[], Snapshot | None] | None = None, out=None, err=None,
         trend_fn: Callable[[Snapshot], Trend | None] | None = None) -> int:
    """Poll `snap_fn` + `admit` until allowed (0) or `timeout_s` (default `guard.wait_timeout_s`) runs
    out (3, the last refusal printed to `out`). One progress line per minute at most, to `err`.
    A snapshot that fails lets the work through (0)."""
    out = out or sys.stdout
    err = err or sys.stderr
    clock = clock or time.monotonic
    sleeper = sleeper or time.sleep
    snap_fn = snap_fn or safe_snapshot
    trend_fn = trend_fn or (lambda s: current_trend(s, conf))
    timeout = _num(conf, "wait_timeout_s") if timeout_s is None else timeout_s
    start = clock()
    last_progress: float | None = None
    last_bad: tuple[str, float] | None = None      # (level, time) of the last bad verdict this wait logged
    while True:
        snap = snap_fn()
        if snap is None:
            log_decision(kind, "unknown", True, "snapshot failed: let through", via="wait")
            return 0
        d = decide(kind, snap, conf, trend_fn(snap))
        now = clock()
        elapsed = now - start
        if d.allowed:
            log_decision(kind, d.level, True, f"after {int(elapsed)}s wait" if elapsed >= 1 else "", via="wait")
            return 0
        if elapsed >= timeout:
            log_decision(kind, d.level, False, f"timeout after {int(elapsed)}s: {d.reason}", via="wait")
            print(d.message, file=out)
            return EXIT_TIMEOUT
        # A WORSENING or CRITICAL poll leaves a mark in the decision log, or a spike that clears between two
        # polls (or two ticks) would let the next poll through with no hold.
        if d.level in BAD and (last_bad is None or last_bad[0] != d.level or now - last_bad[1] >= PROGRESS_EVERY_S):
            last_bad = (d.level, now)
            log_decision(kind, d.level, False, d.reason, via="wait")
        if last_progress is None or now - last_progress >= PROGRESS_EVERY_S:
            last_progress = now
            first = d.message.splitlines()[0].removeprefix("teyla guard: ")
            print(f"teyla load: waiting ({int(elapsed)}s of {int(timeout)}s) — {first}", file=err)
        sleeper(max(0.0, min(poll_s, timeout - elapsed)))


# --- the recorder -----------------------------------------------------------------------------------

COLUMNS = ["time", "level", "pressure", "load1", "swap_used_bytes", "ram_bytes", "compressor_bytes", "sims",
           "builds", "compiler_rss_bytes", "daemon_rss_bytes", "claude", "codex", "grok", "lanes",
           "chrome_rss_bytes", "vm_rss_bytes", "top3", "disk_free_bytes",
           "swapout_bytes", "pageout_bytes", "swapout_mb_s", "pageout_mb_s"]
_INT_COLS = {"pressure", "swap_used_bytes", "ram_bytes", "compressor_bytes", "sims", "builds", "compiler_rss_bytes",
             "daemon_rss_bytes", "claude", "codex", "grok", "lanes", "chrome_rss_bytes", "vm_rss_bytes", "disk_free_bytes",
             "swapout_bytes", "pageout_bytes"}
_FLOAT_COLS = {"load1", "swapout_mb_s", "pageout_mb_s"}
_MIN_COLUMNS = COLUMNS.index("top3") + 1          # the first rows had no disk_free_bytes, and none of what came after


def record_path() -> pathlib.Path:
    from .corrections import teyla_home
    return teyla_home() / "load.tsv"


_TOP_UNSAFE = re.compile(r"[,:\t\r\n]")


def _top3(snap: Snapshot) -> str:
    return ",".join(f"{_TOP_UNSAFE.sub('_', n)}:{b / GIB:.1f}" for n, b in snap.procs.top[:3])


def rates(prev: dict | None, snap: Snapshot) -> tuple[float | None, float | None]:
    """(swap-out, page-out) MB/s since the previous row; None without one close enough, or after a reboot."""
    if not prev:
        return None, None
    dt_s = snap_ts(snap) - prev["ts"]
    if not 5 <= dt_s <= MAX_RATE_GAP_S:
        return None, None
    out = []
    for key in ("swapout_bytes", "pageout_bytes"):
        a, b = prev.get(key), getattr(snap, key)
        out.append(None if a is None or b is None or b < a else (b - a) / dt_s / 1024 ** 2)
    return out[0], out[1]


def record_fields(snap: Snapshot, verdict: Verdict, prev: dict | None = None) -> list[str]:
    p = snap.procs
    so, po = rates(prev, snap)
    vals = [snap.time, verdict.level, snap.pressure, None if snap.load1 is None else f"{snap.load1:.2f}",
            snap.swap_used_bytes, snap.ram_bytes, snap.compressor_bytes, p.sims, p.builds, p.compiler_rss_bytes,
            p.daemon_rss_bytes, p.claude, p.codex, p.grok, p.lanes, p.chrome_rss_bytes, p.vm_rss_bytes, _top3(snap),
            snap.disk_free_bytes, snap.swapout_bytes, snap.pageout_bytes,
            None if so is None else f"{so:.2f}", None if po is None else f"{po:.2f}"]
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


def _append(path: pathlib.Path, columns: list[str], fields: list[str], max_bytes: int) -> None:
    """Append one TSV line (header first in a new file); keep the file bounded."""
    config.private_dir(path.parent)
    # One lock around trim + append: a trim that read the file before another recorder's append
    # and replaced it after would silently drop that line.
    lock = os.open(path.with_name(path.name + ".lock"), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        _trim(path, max_bytes)
        new = not path.exists() or path.stat().st_size == 0
        text = ("#" + "\t".join(columns) + "\n" if new else "") + "\t".join(fields) + "\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, text.encode())
        finally:
            os.close(fd)
    finally:
        os.close(lock)                       # closing the descriptor releases the lock


def record(snap: Snapshot, verdict: Verdict, path: pathlib.Path | None = None,
           max_bytes: int = RECORD_MAX_BYTES) -> pathlib.Path:
    """Append one TSV line to `~/.teyla/load.tsv` (header first in a new file); keep the file bounded."""
    path = pathlib.Path(path) if path else record_path()
    last = read_tail_records(0, path)[-1:]
    _append(path, COLUMNS, record_fields(snap, verdict, last[0] if last else None), max_bytes)
    return path


def _when(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return (v if v.tzinfo else v.astimezone()).timestamp()
    return float(v)


def parse_record(line: str) -> dict | None:
    cells = line.rstrip("\n").split("\t")
    if line.startswith("#") or not _MIN_COLUMNS <= len(cells) <= len(COLUMNS):
        return None
    cells += [""] * (len(COLUMNS) - len(cells))          # a row from before the later columns were recorded
    rec: dict = dict(zip(COLUMNS, cells))
    try:
        rec["ts"] = dt.datetime.fromisoformat(rec["time"]).timestamp()
        for k in _INT_COLS:
            rec[k] = int(rec[k]) if rec[k] != "" else None
        for k in _FLOAT_COLS:
            rec[k] = float(rec[k]) if rec[k] != "" else None
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


# --- the decision log -----------------------------------------------------------------------------------

DECISION_COLUMNS = ["time", "kind", "verdict", "decision", "reason", "cwd", "harness"]
_FIELD_UNSAFE = re.compile(r"[\t\r\n]+")


def decisions_path() -> pathlib.Path:
    from .corrections import teyla_home
    return teyla_home() / "guard-decisions.tsv"


def harness_name(env: dict | None = None) -> str:
    """Which agent harness is asking: `TEYLA_HARNESS` (the Grok hook sets it), else what the environment
    gives away; "" when unknown."""
    env = os.environ if env is None else env
    if env.get("TEYLA_HARNESS"):
        return env["TEYLA_HARNESS"]
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    for prefix, name in (("CODEX_", "codex"), ("GROK_", "grok")):
        if any(k.startswith(prefix) for k in env):
            return name
    return ""


def log_decision(kind: str, level: str, allowed: bool, reason: str, via: str = "admit",
                 path: pathlib.Path | None = None, now: dt.datetime | None = None) -> None:
    """Append one decision to `~/.teyla/guard-decisions.tsv`. Never raises: the log must not block work."""
    try:
        when = now or dt.datetime.now().astimezone()
        reason = f"wait: {reason}" if via == "wait" and reason else "wait" if via == "wait" else reason
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = ""
        fields = [when.isoformat(timespec="seconds"), kind, level, "admitted" if allowed else "refused", reason, cwd,
                  harness_name()]
        _append(pathlib.Path(path) if path else decisions_path(), DECISION_COLUMNS,
                [_FIELD_UNSAFE.sub(" ", f) for f in fields], DECISIONS_MAX_BYTES)
    except Exception:  # noqa: BLE001
        pass


def read_decisions(since=None, path: pathlib.Path | None = None, tail: bool = False) -> list[dict]:
    """The logged decisions as dicts (`ts` epoch seconds added), oldest first. `tail` reads only the end of the file."""
    path = pathlib.Path(path) if path else decisions_path()
    lo = _when(since)
    out = []
    try:
        lines = _tail(path) if tail else path.read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        cells = line.split("\t")
        if line.startswith("#") or len(cells) != len(DECISION_COLUMNS):
            continue
        rec = dict(zip(DECISION_COLUMNS, cells))
        try:
            rec["ts"] = dt.datetime.fromisoformat(rec["time"]).timestamp()
        except ValueError:
            continue
        if lo is None or rec["ts"] >= lo:
            out.append(rec)
    return out


def decision_summary(now: float | None = None, window_s: int = DECISION_WINDOW_S,
                     path: pathlib.Path | None = None) -> str:
    """"guard, last hour: 5 admitted, 2 refused (sim 1, build 1)"; "" when nothing was decided."""
    now = time.time() if now is None else now
    rows = read_decisions(since=now - window_s, path=path)
    if not rows:
        return ""
    refused = [r for r in rows if r["decision"] == "refused"]
    by_kind: dict[str, int] = {}
    for r in refused:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    detail = " (" + ", ".join(f"{k} {n}" for k, n in sorted(by_kind.items())) + ")" if by_kind else ""
    span = "last hour" if window_s == 3600 else f"last {window_s // 60} min"
    return f"guard, {span}: {len(rows) - len(refused)} admitted, {len(refused)} refused{detail}"


# --- replay ------------------------------------------------------------------------------------------------

def snapshot_from_record(rec: dict, ncpu: int | None = None) -> Snapshot:
    """A `load.tsv` row as a snapshot. The row has no core count, swap total or load5/15; `ncpu` stands in
    for the first, and `load1` for the others."""
    procs = Procs(sims=rec["sims"] or 0, drivers=[Driver(0, "xcodebuild", 0, None) for _ in range(rec["builds"] or 0)],
                  compiler_rss_bytes=rec["compiler_rss_bytes"] or 0, claude=rec["claude"] or 0, codex=rec["codex"] or 0,
                  grok=rec["grok"] or 0, lanes=rec["lanes"] or 0, chrome_rss_bytes=rec["chrome_rss_bytes"] or 0)
    return Snapshot(time=rec["time"], ram_bytes=rec["ram_bytes"], ncpu=ncpu or os.cpu_count() or 1, load1=rec["load1"],
                    load5=rec["load1"], load15=rec["load1"], swap_used_bytes=rec["swap_used_bytes"],
                    pressure=rec["pressure"], compressor_bytes=rec["compressor_bytes"],
                    disk_free_bytes=rec["disk_free_bytes"], swapout_bytes=rec.get("swapout_bytes"),
                    pageout_bytes=rec.get("pageout_bytes"), procs=procs)


EPISODE_GAP_S = 300          # rows further apart than this end a refusal episode
ROW_MAX_S = 300              # a row stands for at most this long


def _new_day(day: str) -> dict:
    return {"day": day, "n": 0, "levels": dict.fromkeys(EXIT, 0), "sim": dict.fromkeys(EXIT, 0), "build": dict.fromkeys(EXIT, 0),
            "refused_min": 0.0, "new_min": 0.0, "episodes": 0, "timeouts": 0, "longest_min": 0.0}


def replay(records: list[dict], conf: dict | None = None, ncpu: int | None = None, detail: list | None = None,
           wait_timeout_s: float | None = None) -> list[dict]:
    """Run `assess` and `decide` over the recorded rows, oldest first, carrying the same history the live
    guard has (the levels are recomputed, not the recorded ones). One dict per local day: the OK / BUSY /
    WORSENING / CRITICAL counts, how many samples admit a sim or a build per verdict, and the refusals the
    memory state causes: minutes (of which minutes CRITICAL did not already cause), episodes (each is one
    wait an agent would have hit), the longest one, and how many outlast `wait_timeout_s`. `detail`, a list,
    receives one dict per row."""
    timeout = _num(conf, "wait_timeout_s") if wait_timeout_s is None else wait_timeout_s
    days: dict[str, dict] = {}
    hist: list[dict] = []
    keep = history_s(conf)
    episode: dict | None = None            # {"day", "start", "end"} of the refusal episode in progress

    def close() -> None:
        nonlocal episode
        if episode:
            d = days[episode["day"]]
            length = (episode["end"] - episode["start"]) / 60
            d["episodes"] += 1
            d["longest_min"] = max(d["longest_min"], length)
            d["timeouts"] += length * 60 > timeout
        episode = None

    for i, rec in enumerate(records):
        snap = snapshot_from_record(rec, ncpu)
        day = days.setdefault(rec["time"][:10], _new_day(rec["time"][:10]))
        trend = compute_trend(hist, snap, conf)
        level = assess(snap, conf, trend).level
        hist.append(point_of(snap, level))
        hist = [h for h in hist if rec["ts"] - h["ts"] <= keep]
        day["n"] += 1
        day["levels"][level] += 1
        allowed = {k: decide(k, snap, conf, trend).allowed for k in ("sim", "build")}
        for k, ok in allowed.items():
            if ok:
                day[k][level] += 1
        nxt = records[i + 1]["ts"] if i + 1 < len(records) else rec["ts"] + 60
        dur = max(0.0, min(nxt - rec["ts"], ROW_MAX_S))
        held = trend.hold_left_s() is not None
        refused = level in BAD or held
        if refused:
            day["refused_min"] += dur / 60
            if level != CRITICAL:
                day["new_min"] += dur / 60
            if episode and rec["ts"] - episode["end"] > EPISODE_GAP_S:
                close()
            if episode is None:
                episode = {"day": day["day"], "start": rec["ts"], "end": rec["ts"] + dur}
            else:
                episode["end"] = rec["ts"] + dur
        elif episode:
            close()                    # an admitted row ends the wait: the agent's next poll gets through
        if detail is not None:
            detail.append({"time": rec["time"], "level": level, "held": held, "sim": allowed["sim"], "build": allowed["build"],
                           "why": decide("sim", snap, conf, trend).reason})
    close()
    return list(days.values())


def render_replay(days: list[dict]) -> str:
    """Two tables. Per day: samples, the OK / BUSY / WORSENING / CRITICAL counts, and how many samples
    would let a simulator or a build start, split by the verdict (OK/BUSY/WORSENING/CRITICAL). Then the refusals
    the memory state causes."""
    if not days:
        return "no recorded rows in that window (is `guard.agent` on? `teyla load --record` writes them)"
    levels = (OK, BUSY, WORSENING, CRITICAL)
    total = _new_day("total")
    for d in days:
        total["n"] += d["n"]
        for key in ("levels", "sim", "build"):
            for lv in EXIT:
                total[key][lv] += d[key][lv]
        for key in ("refused_min", "new_min", "episodes", "timeouts"):
            total[key] += d[key]
        total["longest_min"] = max(total["longest_min"], d["longest_min"])
    cell = lambda d, key: "/".join(str(d[key][x]) for x in levels)  # noqa: E731
    lines = [f"{'day':<11}{'rows':>6}{'OK':>6}{'BUSY':>6}{'WORS':>6}{'CRIT':>6}   {'sim allowed OK/BUSY/WORS/CRIT':<32}build allowed OK/BUSY/WORS/CRIT"]
    for d in days + [total]:
        lv = d["levels"]
        lines.append(f"{d['day']:<11}{d['n']:>6}{lv[OK]:>6}{lv[BUSY]:>6}{lv[WORSENING]:>6}{lv[CRITICAL]:>6}   {cell(d, 'sim'):<32}{cell(d, 'build')}")
    lines += ["", "sim and build refused for the memory state (CRITICAL, WORSENING, or the hold after them):",
              f"{'day':<11}{'minutes':>8}{'of them new':>13}{'episodes':>10}{'longest':>9}{'> timeout':>11}"]
    for d in days + [total]:
        lines.append(f"{d['day']:<11}{d['refused_min']:>8.0f}{d['new_min']:>13.0f}{d['episodes']:>10}{d['longest_min']:>8.0f}m{d['timeouts']:>11}")
    lines.append("(an episode is one wait an agent hits if it tries to start a sim or build during it; 'new' = minutes CRITICAL alone would not have refused)")
    return "\n".join(lines)


def render_detail(rows: list[dict], day: str | None = None) -> str:
    """The replayed rows of one day, one line per change of state."""
    out, last = [], None
    for r in rows:
        if day and not r["time"].startswith(day):
            continue
        key = (r["level"], r["held"], r["sim"], r["build"])
        if key != last:
            out.append(f"{r['time'][11:19]}  {r['level']:<9} {'held ' if r['held'] else '     '}sim {'ok     ' if r['sim'] else 'REFUSED'}"
                       f" build {'ok' if r['build'] else 'REFUSED'}" + (f"  {r['why'][:90]}" if r["why"] else ""))
            last = key
    return "\n".join(out) or "no rows"


# --- the report ----------------------------------------------------------------------------------------

def _mins(s: int | None) -> str:
    return "" if s is None else f" {s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f" {s // 60}m"


def trend_lines(trend: Trend | None, conf: dict | None = None) -> list[str]:
    if trend is None:
        return []
    bits = []
    if trend.swap_gb_30m is not None:
        bits.append(f"swap {trend.swap_gb_30m:+.1f} GB per 30 min")
    if trend.disk_free_30m_gb is not None:
        bits.append(f"disk {trend.disk_free_30m_gb:.1f} GB free in 30 min")
    if trend.swapout_mb_s is not None:
        bits.append(f"swap-out {trend.swapout_mb_s:.1f} MB/s")
    out = []
    if bits:
        out.append(f"trend ({_num(conf, 'trend_window_min'):g} min, {trend.points} samples): " + " · ".join(bits))
    elif trend.points:
        out.append(f"trend: too little history yet ({trend.points} samples, {int(trend.span_s)} s)")
    left = trend.hold_left_s()
    if left is not None:
        out.append(f"hold: {trend.held_level} {int(trend.held_ago_s // 60)} min ago; new simulators and builds wait"
                   f" {math.ceil(left / 60)} more min")
    return out


def render(snap: Snapshot, verdict: Verdict, trend: Trend | None = None, conf: dict | None = None) -> str:
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
    if snap.disk_free_bytes is not None:
        lines.append(f"disk: {gb(snap.disk_free_bytes)} free")
    lines += trend_lines(trend, conf)
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
    if args.replay:
        if args.day:
            try:
                start = dt.datetime.fromisoformat(args.day).astimezone()
            except ValueError:
                print(f"teyla load: --day wants YYYY-MM-DD, not {args.day!r}", file=sys.stderr)
                return 1
            rows: list = []
            replay(read_records(since=start - dt.timedelta(seconds=history_s(conf)), until=start + dt.timedelta(days=1)),
                   conf, detail=rows)
            print(render_detail(rows, args.day))
            return 0
        since = time.time() - args.days * 86400
        print(render_replay(replay(read_records(since=since), conf)))
        return 0
    if args.admit:
        if not enabled(conf):
            return 0
        snap = safe_snapshot(run)
        if snap is None:
            log_decision(args.admit, "unknown", True, "snapshot failed: let through")
            return 0
        d = decide(args.admit, snap, conf, current_trend(snap, conf))
        log_decision(args.admit, d.level, d.allowed, d.reason)
        if not d.allowed:
            print(d.message)
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
    trend = current_trend(snap, conf)
    verdict = assess(snap, conf, trend)
    if args.record:
        try:
            record(snap, verdict)
        except OSError as e:
            print(f"teyla load: could not record: {e}", file=sys.stderr)
    if args.json:
        print(json.dumps({"snapshot": snap.to_json(), "verdict": verdict.to_json(),
                          "trend": trend.to_json() if trend else None}, indent=1))
        return 0
    if args.quiet:
        return 0
    print(render(snap, verdict, trend, conf))
    recent = decision_summary()
    if recent:
        print(recent)
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
    q.add_argument("--replay", action="store_true", help="run the verdict and admission over ~/.teyla/load.tsv: per day, the OK/BUSY/CRITICAL counts and how many samples would admit a sim or a build")
    q.add_argument("--days", type=float, default=7, metavar="N", help="--replay: how many days back (default 7)")
    q.add_argument("--day", metavar="YYYY-MM-DD", help="--replay: one line per change of state on that day, instead of the table")
    q.add_argument("--timeout", type=float, default=None, metavar="S", help="--wait: give up after S seconds (default guard.wait_timeout_s)")
    return q

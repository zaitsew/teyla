"""`teyla crash` — after a crash, say what happened and what the machine looked like right before.

    teyla crash [--days N] [--json] [--ack]      kernel panics, watchdog resets and jetsam events, newest first

On 2026-10-09 at 20:25 a 24 GB Mac kernel-panicked while agents overloaded it, and nobody learned why
until someone dug through /Library/Logs/DiagnosticReports by hand. This reads those reports, the load
recorder's rows (`teyla load --record`, `~/.teyla/load.tsv`) from the half hour before, and says what
the panic was, what was running, and what to change. Unacknowledged panics also reach `teyla doctor`
(`machine:crash`, WARN), the session-start banner (through doctor) and the weekly digest.

The report files, as macOS writes them (every parser is tolerant: malformed input is None or partial,
never an exception; an unreadable folder or file is reported as "not readable"):

    panic-*.panic        line 1 a JSON header (`timestamp`, `incident_id`, `os_version`), then one JSON object whose
                         `panicString` holds the reason, the panicked task, the `Epoch Time` block (the real panic
                         time: `Calendar`, hex seconds; the file name and header carry the time it was processed
                         after the reboot), the compressor line and the last started kext
    ResetCounter-*.diag  text; `Boot faults: wdog` is a watchdog reset (the machine reset itself)
    JetsamEvent-*.ips    memory-pressure kills: header `timestamp` is the real event time; `memoryStatus`,
                         `processes` (`rpages` resident pages; `reason` on the killed ones)

An incident can sit in the main folder and in `Retired/` both; the incident id identifies it. A watchdog
reset that follows a panic by less than two hours is that panic's reboot, not a second incident.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import sys
from collections import Counter

GIB = 1024 ** 3
DEFAULT_DAYS = 7
CONTEXT_MINUTES = 30
JETSAM_WINDOW_H = 2
RESET_AFTER_PANIC_H = 2
TOP_N = 8
SWAP_EXHAUSTED_PCT = 40
MANY_AGENTS = 15
KINDS_CRASH = ("panic", "watchdog")

# Resolved at call time through this list so tests (and a moved Library) can redirect it.
DEFAULT_ROOTS: list[pathlib.Path] | None = None


def default_roots() -> list[pathlib.Path]:
    if DEFAULT_ROOTS is not None:
        return list(DEFAULT_ROOTS)
    home = pathlib.Path.home() / "Library" / "Logs" / "DiagnosticReports"
    system = pathlib.Path("/Library/Logs/DiagnosticReports")
    return [system, system / "Retired", home, home / "Retired"]


PATTERNS = {"panic": "panic-*.panic", "reset": "ResetCounter-*.diag", "jetsam": "JetsamEvent-*.ips"}


# --- reading the files -----------------------------------------------------------------------------------

def _parse_ts(s) -> dt.datetime | None:
    """`2026-10-09 21:11:15.00 +0200` (the report header), or the same without an offset (local)."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S.%f %z", "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            t = dt.datetime.strptime(s, fmt)
        except ValueError:
            continue
        return t if t.tzinfo else t.astimezone()
    return None


def _split(text: str) -> tuple[dict, dict]:
    """(header, body): line 1 is a JSON header, the rest is one JSON object. Either may be {}."""
    first, _, rest = text.partition("\n")
    out = []
    for chunk in (first, rest):
        try:
            v = json.loads(chunk)
        except ValueError:
            v = None
        out.append(v if isinstance(v, dict) else {})
    return out[0], out[1]


def _read(path) -> str | None:
    try:
        return pathlib.Path(path).read_text(errors="replace")
    except OSError:
        return None


def _local(t: dt.datetime) -> dt.datetime:
    return t.astimezone()


def _stamp(t: dt.datetime) -> str:
    return _local(t).strftime("%Y-%m-%d %H:%M")


def _gb(n: float | None) -> str:
    return "?" if n is None else f"{n / GIB:.1f} GB"


def _str(v) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


# --- the shapes ---------------------------------------------------------------------------------------------

@dataclasses.dataclass
class Panic:
    time: dt.datetime
    incident: str | None = None
    path: str = ""
    kind: str = "panic"                  # "panic" | "watchdog"
    reason: str | None = None
    task: str | None = None
    pid: int | None = None
    compressor: str | None = None        # the `Compressor Info:` line, verbatim
    compressor_status: str | None = None
    swapfiles: int | None = None
    kext: str | None = None
    os_version: str | None = None

    @property
    def id(self) -> str:
        return self.incident or f"{self.kind}-{int(self.time.timestamp())}"

    def line(self) -> str:
        head = f"{_stamp(self.time)} " + ("watchdog timeout" if self.kind == "watchdog" else "kernel panic")
        parts = [self.reason or "reason unknown"]
        if self.task:
            parts[0] += f"; panicked task {self.task}" + (f" (pid {self.pid})" if self.pid is not None else "")
        if self.compressor_status or self.swapfiles is not None:
            bits = []
            if self.compressor_status:
                bits.append(f"compressor {self.compressor_status}")
            if self.swapfiles is not None:
                bits.append(f"{self.swapfiles} swapfiles")
            parts.append(", ".join(bits))
        if self.kext:
            parts.append(f"last kext {self.kext}")
        return f"{head} — " + "; ".join(parts)

    def short(self) -> str:
        label = "watchdog timeout" if self.kind == "watchdog" else "kernel panic"
        t = _local(self.time).strftime("%m-%d %H:%M")
        return f"{label} {t}: {self.reason or 'reason unknown'}" + (f" ({self.task})" if self.task else "")

    def to_json(self) -> dict:
        return {"kind": self.kind, "time": _local(self.time).isoformat(timespec="seconds"), "incident": self.incident,
                "reason": self.reason, "task": self.task, "pid": self.pid, "compressor": self.compressor,
                "swapfiles": self.swapfiles, "kext": self.kext, "os_version": self.os_version, "path": self.path}


@dataclasses.dataclass
class Reset:
    time: dt.datetime
    incident: str | None = None
    path: str = ""
    faults: list = dataclasses.field(default_factory=list)

    kind = "watchdog"

    @property
    def watchdog(self) -> bool:
        return any(f.lower().startswith("wdog") for f in self.faults)

    @property
    def id(self) -> str:
        return self.incident or f"reset-{int(self.time.timestamp())}"

    def line(self) -> str:
        return (f"{_stamp(self.time)} watchdog reset — boot faults {','.join(self.faults) or 'unknown'}; "
                "the machine reset itself and left no panic log")

    def short(self) -> str:
        return f"watchdog reset {_local(self.time).strftime('%m-%d %H:%M')}: the machine reset itself"

    def to_json(self) -> dict:
        return {"kind": self.kind, "time": _local(self.time).isoformat(timespec="seconds"), "incident": self.incident,
                "faults": self.faults, "path": self.path}


@dataclasses.dataclass
class Jetsam:
    time: dt.datetime
    incident: str | None = None
    path: str = ""
    page_size: int = 16384
    compressor_bytes: int | None = None
    free_bytes: int | None = None
    processes: int = 0
    top: list = dataclasses.field(default_factory=list)        # [(app, resident bytes, process count)]
    killed: list = dataclasses.field(default_factory=list)     # [(process name, reason)]
    largest: str | None = None

    kind = "jetsam"

    @property
    def id(self) -> str:
        return self.incident or f"jetsam-{int(self.time.timestamp())}"

    def top_text(self, n: int = TOP_N) -> str:
        return ", ".join(f"{name} {_gb(b)}" + (f" ×{c}" if c > 1 else "") for name, b, c in self.top[:n])

    def killed_text(self, n: int = 6) -> str:
        groups = Counter(self.killed)
        return ", ".join(f"{name}" + (f" ×{c}" if c > 1 else "") + f" ({reason})"
                         for (name, reason), c in groups.most_common(n))

    def line(self) -> str:
        bits = []
        if self.compressor_bytes is not None:
            bits.append(f"compressor {_gb(self.compressor_bytes)}")
        bits.append(f"{self.processes} processes")
        if self.killed:
            bits.append(f"{len(self.killed)} killed")
        return f"{_stamp(self.time)} jetsam — memory-pressure kills; " + ", ".join(bits)

    def short(self) -> str:
        return f"jetsam {_local(self.time).strftime('%m-%d %H:%M')}"

    def to_json(self) -> dict:
        return {"kind": self.kind, "time": _local(self.time).isoformat(timespec="seconds"), "incident": self.incident,
                "compressor_bytes": self.compressor_bytes, "free_bytes": self.free_bytes, "processes": self.processes,
                "top": [{"app": n, "bytes": b, "count": c} for n, b, c in self.top],
                "killed": [{"name": n, "reason": r} for n, r in self.killed], "largest": self.largest,
                "path": self.path}


# --- the parsers --------------------------------------------------------------------------------------------

_FIRST = re.compile(r"panic\([^)]*\):\s*(.*)")
_TASK = re.compile(r"Panicked task\s+0x[0-9a-fA-F]+:.*?\bpid\s+(\d+):\s*(.+)")
_CAL = re.compile(r"^\s*Calendar:\s*(0x[0-9a-fA-F]+)", re.M)
_COMP = re.compile(r"^(Compressor Info:.*)$", re.M)
_COMP_PARTS = re.compile(r"(\d+)% of compressed pages limit \((\w+)\) and (\d+)% of segments limit \((\w+)\)"
                         r"(?: with (\d+) swapfiles? and (.+?) swap space)?")
_KEXT = re.compile(r"last started kext at \d+:\s*(\S+)")
_WATCHDOG = re.compile(r"watchdog timeout:\s*([^\n(]*)", re.I)
_FOLD_HELPER = re.compile(r"^(.+?) Helper(?: \(.*\))?$")


def _epoch(hexs: str) -> dt.datetime | None:
    try:
        sec = int(hexs, 16)
        t = dt.datetime.fromtimestamp(sec, tz=dt.timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return t if dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc) < t < dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2) else None


def parse_panic(path) -> Panic | None:
    """A `panic-*.panic`. None when not even a time can be found; partial when the body is damaged."""
    text = _read(path)
    if not text:
        return None
    try:
        return _parse_panic(text, str(path))
    except Exception:  # noqa: BLE001 — a damaged report must never stop the others being read
        return None


def _parse_panic(text: str, path: str) -> Panic | None:
    header, body = _split(text)
    ps = body.get("panicString")
    ps = ps if isinstance(ps, str) else ""
    t = None
    m = _CAL.search(ps)
    if m:
        t = _epoch(m.group(1))
    t = t or _parse_ts(body.get("date")) or _parse_ts(header.get("timestamp"))
    if t is None:
        return None
    p = Panic(time=t, incident=_str(header.get("incident_id")) or _str(body.get("incident")), path=path,
              os_version=_str(header.get("os_version")))
    first = ps.split("\n", 1)[0]
    m = _FIRST.match(first)
    reason = (m.group(1) if m else first).strip()
    reason = re.split(r"\s+at pc\b", reason, maxsplit=1)[0].strip().rstrip(",. ")
    if "watchdog" in first.lower():
        p.kind = "watchdog"
        w = _WATCHDOG.search(first)
        reason = ("watchdog timeout: " + w.group(1).strip()) if w and w.group(1).strip() else reason
    p.reason = reason or None
    m = _TASK.search(ps)
    if m:
        p.pid, p.task = int(m.group(1)), m.group(2).strip()
    m = _COMP.search(ps)
    if m:
        p.compressor = m.group(1).strip()
        c = _COMP_PARTS.search(p.compressor)
        if c:
            p_state, s_state = c.group(2), c.group(4)
            p.compressor_status = "OK" if p_state == s_state == "OK" else (
                f"{c.group(1)}% of pages limit ({p_state}), {c.group(3)}% of segments limit ({s_state})")
            p.swapfiles = int(c.group(5)) if c.group(5) else None
            if c.group(6) and c.group(6).strip() != "OK":
                p.compressor_status += f", {c.group(6).strip()} swap space"
    m = _KEXT.search(ps)
    if m:
        p.kext = m.group(1).rsplit(".", 1)[-1]
    return p


def parse_reset(path) -> Reset | None:
    """A `ResetCounter-*.diag`. Its time is when the report was written at the next boot."""
    text = _read(path)
    if not text:
        return None
    try:
        header, _ = _split(text)
        faults = []
        m = re.search(r"^Boot faults:\s*(.*)$", text, re.M)
        if m:
            faults = [f.strip() for f in m.group(1).split(",") if f.strip()]
        d = re.search(r"^Date:\s*(.+)$", text, re.M)
        t = _parse_ts(header.get("timestamp")) or (_parse_ts(d.group(1)) if d else None)
        if t is None:
            return None
        inc = _str(header.get("incident_id"))
        if not inc:
            i = re.search(r"^Incident Identifier:\s*(\S+)", text, re.M)
            inc = i.group(1) if i else None
        return Reset(time=t, incident=inc, path=str(path), faults=faults)
    except Exception:  # noqa: BLE001
        return None


def parse_jetsam(path) -> Jetsam | None:
    """A `JetsamEvent-*.ips`: the real event time, the compressor, the top apps and who was killed."""
    text = _read(path)
    if not text:
        return None
    try:
        header, body = _split(text)
        t = _parse_ts(header.get("timestamp")) or _parse_ts(body.get("date"))
        if t is None:
            return None
        j = Jetsam(time=t, incident=_str(header.get("incident_id")) or _str(body.get("incident")), path=str(path))
        ms = body.get("memoryStatus")
        ms = ms if isinstance(ms, dict) else {}
        ps = ms.get("pageSize")
        j.page_size = ps if isinstance(ps, int) and not isinstance(ps, bool) and ps > 0 else 16384
        comp = ms.get("compressorSize")
        if isinstance(comp, (int, float)) and not isinstance(comp, bool):
            j.compressor_bytes = int(comp * j.page_size)
        pages = ms.get("memoryPages")
        free = pages.get("free") if isinstance(pages, dict) else None
        if isinstance(free, (int, float)) and not isinstance(free, bool):
            j.free_bytes = int(free * j.page_size)
        procs = body.get("processes")
        procs = [p for p in procs if isinstance(p, dict)] if isinstance(procs, list) else []
        j.processes = len(procs)
        size: Counter = Counter()
        count: Counter = Counter()
        for p in procs:
            name = _str(p.get("name")) or "?"
            name = _FOLD_HELPER.sub(r"\1", name)
            rp = p.get("rpages")
            size[name] += int(rp * j.page_size) if isinstance(rp, (int, float)) and not isinstance(rp, bool) else 0
            count[name] += 1
            reason = _str(p.get("reason"))
            if reason:
                j.killed.append((_str(p.get("name")) or "?", reason))
        j.top = [(n, b, count[n]) for n, b in size.most_common(TOP_N) if b > 0]
        lp = body.get("largestProcess")
        j.largest = lp if isinstance(lp, str) else None
        return j
    except Exception:  # noqa: BLE001
        return None


# --- finding the reports ----------------------------------------------------------------------------------

@dataclasses.dataclass
class Found:
    events: list
    unreadable: list


def _mtime_floor(since: dt.datetime | None) -> float | None:
    return None if since is None else since.timestamp()


def find_reports(roots=None, since: dt.datetime | None = None, unreadable: list | None = None) -> list[tuple[str, pathlib.Path]]:
    """[(kind, path)] for every report file under `roots` (default: the system and user DiagnosticReports,
    and their `Retired/`) whose modification time is not before `since` (a report is written after the
    event it describes, so a file older than `since` cannot hold an event newer than it). A folder that
    exists and cannot be read is appended to `unreadable`; one that does not exist is skipped."""
    out = []
    floor = _mtime_floor(since)
    for root in (default_roots() if roots is None else roots):
        root = pathlib.Path(root)
        if not root.is_dir():
            continue
        if not os.access(root, os.R_OK | os.X_OK):
            if unreadable is not None:
                unreadable.append(str(root))
            continue
        for kind, pat in PATTERNS.items():
            try:
                files = sorted(root.glob(pat))
            except OSError:
                if unreadable is not None:
                    unreadable.append(str(root))
                continue
            for f in files:
                try:
                    if floor is not None and f.stat().st_mtime < floor:
                        continue
                except OSError:
                    continue
                out.append((kind, f))
    return out


def collect(since: dt.datetime | None = None, roots=None) -> Found:
    """Every crash-like event since `since`, oldest first, de-duplicated, plus the folders and files
    that could not be read."""
    unreadable: list = []
    parsed = []
    for kind, f in find_reports(roots, since, unreadable):
        if not os.access(f, os.R_OK):
            unreadable.append(str(f))
            continue
        ev = {"panic": parse_panic, "reset": parse_reset, "jetsam": parse_jetsam}[kind](f)
        if ev is not None:
            parsed.append(ev)
    seen: set = set()
    uniq = []
    for ev in parsed:                                  # the main folder is listed before Retired/
        key = ev.incident or (ev.kind, int(ev.time.timestamp() // 60))
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ev)
    crashes = [e for e in uniq if isinstance(e, Panic)]
    out = []
    for ev in uniq:
        if isinstance(ev, Reset):
            if not ev.watchdog:
                continue
            if any(_within_after(c.time, ev.time) for c in crashes):    # a reset that is a panic's reboot
                continue
        if since is not None and ev.time < since:
            continue
        out.append(ev)
    out.sort(key=lambda e: e.time)
    return Found(out, sorted(set(unreadable)))


def _within_after(earlier: dt.datetime, later: dt.datetime) -> bool:
    """True when `later` is 0..RESET_AFTER_PANIC_H hours after `earlier`."""
    return dt.timedelta(0) <= later - earlier <= dt.timedelta(hours=RESET_AFTER_PANIC_H)


def events(since: dt.datetime | None = None, roots=None) -> list:
    """Panics, watchdog resets and jetsam events since `since`, oldest first, one per incident."""
    return collect(since, roots).events


# --- the machine before it ------------------------------------------------------------------------------------

@dataclasses.dataclass
class Context:
    rows: int = 0
    first: str | None = None
    last: str | None = None
    last_gap_s: float | None = None
    peak_swap_bytes: int | None = None
    peak_swap_pct: float | None = None
    peak_load: float | None = None
    peak_compressor_bytes: int | None = None
    max_sims: int | None = None
    max_builds: int | None = None
    max_agents: int | None = None
    max_claude: int | None = None
    max_codex: int | None = None
    max_grok: int | None = None
    max_lanes: int | None = None
    max_daemon_bytes: int | None = None
    max_chrome_bytes: int | None = None
    ram_bytes: int | None = None
    top: list = dataclasses.field(default_factory=list)       # [(app, peak GB)], largest first
    minutes: int = CONTEXT_MINUTES

    def lines(self) -> list[str]:
        if not self.rows:
            return [f"no load records in the {self.minutes} minutes before — the recorder agent was off"]
        hhmm = lambda s: dt.datetime.fromisoformat(s).astimezone().strftime("%H:%M") if s else "?"  # noqa: E731
        gap = f", {int(self.last_gap_s // 60)} min before" if self.last_gap_s is not None else ""
        out = [f"load before it: {self.rows} record(s), {hhmm(self.first)}–{hhmm(self.last)} (last {hhmm(self.last)}{gap})"]
        mem = []
        if self.peak_swap_bytes is not None:
            mem.append(f"swap peak {_gb(self.peak_swap_bytes)}"
                       + (f" ({self.peak_swap_pct:.0f}% of RAM)" if self.peak_swap_pct is not None else ""))
        if self.peak_compressor_bytes is not None:
            mem.append(f"compressor peak {_gb(self.peak_compressor_bytes)}")
        if self.peak_load is not None:
            mem.append(f"load peak {self.peak_load:.0f}")
        if mem:
            out.append("  " + " · ".join(mem))
        work = []
        for label, v in (("simulators", self.max_sims), ("builds", self.max_builds)):
            if v is not None:
                work.append(f"{label} max {v}")
        ag = [f"{n} {v}" for n, v in (("claude", self.max_claude), ("codex", self.max_codex), ("grok", self.max_grok)) if v]
        if ag:
            work.append("agents max " + " / ".join(ag) + (f" (lanes {self.max_lanes})" if self.max_lanes else ""))
        if self.max_daemon_bytes:
            work.append(f"JVM daemons {_gb(self.max_daemon_bytes)}")
        if work:
            out.append("  " + " · ".join(work))
        if self.top:
            out.append("  top apps: " + ", ".join(f"{n} {g:.1f} GB" for n, g in self.top[:5]))
        return out

    def to_json(self) -> dict:
        d = dataclasses.asdict(self)
        d["top"] = [{"app": n, "gb": g} for n, g in self.top]
        return d


def _max(vals):
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def context(event, minutes: int = CONTEXT_MINUTES, path=None) -> Context:
    """The recorder's rows in the `minutes` before `event`, summarised. Rows older than that are not
    "the machine right before it", so an empty window says so."""
    from . import load
    ctx = Context(minutes=minutes)
    try:
        rows = load.read_records(since=event.time - dt.timedelta(minutes=minutes), until=event.time, path=path)
    except Exception:  # noqa: BLE001 — forensics must not fail on a bad recorder file
        rows = []
    if not rows:
        return ctx
    ctx.rows = len(rows)
    ctx.first, ctx.last = rows[0]["time"], rows[-1]["time"]
    ctx.last_gap_s = max(0.0, event.time.timestamp() - rows[-1]["ts"])
    ctx.ram_bytes = _max(r["ram_bytes"] for r in rows)
    ctx.peak_swap_bytes = _max(r["swap_used_bytes"] for r in rows)
    if ctx.peak_swap_bytes is not None and ctx.ram_bytes:
        ctx.peak_swap_pct = ctx.peak_swap_bytes * 100.0 / ctx.ram_bytes
    ctx.peak_load = _max(r["load1"] for r in rows)
    ctx.peak_compressor_bytes = _max(r["compressor_bytes"] for r in rows)
    ctx.max_sims = _max(r["sims"] for r in rows)
    ctx.max_builds = _max(r["builds"] for r in rows)
    ctx.max_claude, ctx.max_codex, ctx.max_grok = (_max(r[k] for r in rows) for k in ("claude", "codex", "grok"))
    ctx.max_lanes = _max(r["lanes"] for r in rows)
    ctx.max_agents = _max((r["claude"] or 0) + (r["codex"] or 0) + (r["grok"] or 0) for r in rows)
    ctx.max_daemon_bytes = _max(r["daemon_rss_bytes"] for r in rows)
    ctx.max_chrome_bytes = _max(r["chrome_rss_bytes"] for r in rows)
    peak: dict[str, float] = {}
    for r in rows:
        for name, g in r["top3"]:
            peak[name] = max(peak.get(name, 0.0), g)
    ctx.top = sorted(peak.items(), key=lambda kv: kv[1], reverse=True)
    return ctx


def nearest_jetsam(event, evs: list, hours: float = JETSAM_WINDOW_H) -> Jetsam | None:
    """The jetsam event closest before `event`, within `hours`."""
    best = None
    for e in evs:
        if isinstance(e, Jetsam) and e is not event and dt.timedelta(0) <= event.time - e.time <= dt.timedelta(hours=hours):
            if best is None or e.time > best.time:
                best = e
    return best


# --- advice, computed from the data ----------------------------------------------------------------------------

def _is_jvm(name: str) -> bool:
    return name.lower() in ("java", "jvm") or "gradle" in name.lower() or "kotlin" in name.lower()


def advice(event, ctx: Context | None, jet: Jetsam | None) -> list[str]:
    """Two to four concrete lines, each from a number in the data. Nothing generic."""
    out: list[str] = []
    ctx = ctx or Context()
    jet = jet or (event if isinstance(event, Jetsam) else None)
    apps: dict[str, float] = {}
    if jet:
        for n, b, _c in jet.top:
            apps[n] = max(apps.get(n, 0.0), b / GIB)
    for n, g in ctx.top:
        apps[n] = max(apps.get(n, 0.0), g)

    task = getattr(event, "task", None)
    if (ctx.max_sims or 0) >= 3 or task == "simctl":
        why = f"{ctx.max_sims} simulators were booted" if (ctx.max_sims or 0) >= 3 else "the panicked task was simctl"
        out.append(f"simulators ({why}): keep `guard.max_sims` at 2, shut down sims your lane booted (`teyla storage sims --reap`)")

    jvm = max([g for n, g in apps.items() if _is_jvm(n)] + [(ctx.max_daemon_bytes or 0) / GIB])
    if jvm >= 1.0:
        out.append(f"Gradle/Kotlin daemons held {jvm:.1f} GB: `./gradlew --stop`, or let the guard agent reap them")

    ranked = sorted(apps.items(), key=lambda kv: kv[1], reverse=True)
    if ranked and not _is_jvm(ranked[0][0]) and ranked[0][1] >= 3.0 and "simulator" not in ranked[0][0].lower():
        name, g = ranked[0]
        out.append(f"{name} was the biggest app at {g:.1f} GB"
                   + (": close its tabs and windows, or quit it before long agent runs" if "chrome" in name.lower()
                      else ": quit or restart it before long agent runs"))

    if ctx.peak_swap_pct is not None and ctx.peak_swap_pct >= SWAP_EXHAUSTED_PCT:
        out.append(f"memory was exhausted: swap reached {_gb(ctx.peak_swap_bytes)} ({ctx.peak_swap_pct:.0f}% of RAM);"
                   " run fewer agents at once (`guard.max_lanes`), start work through `teyla load --wait`")
    elif (ctx.max_agents or 0) >= MANY_AGENTS:
        out.append(f"{ctx.max_agents} agent sessions ran at once: close the idle ones, or cap headless lanes with `guard.max_lanes`")

    cpus = os.cpu_count() or 0
    if ctx.peak_load and cpus and ctx.peak_load >= 3 * cpus:
        out.append(f"CPU starvation: load peaked at {ctx.peak_load:.0f} on {cpus} cores"
                   + (f" with {ctx.max_builds} builds" if ctx.max_builds else "")
                   + ": cap parallel builds (`guard.max_builds`)")
    if not ctx.rows and isinstance(event, (Panic, Reset)):
        out.append("no load records, so nothing above says what was running: record every minute"
                   " (`teyla load --record --quiet` from a launchd agent) so the next crash comes with data")
    return out[:4]


# --- state: acknowledged incidents -------------------------------------------------------------------------------

def seen_path() -> pathlib.Path:
    from .corrections import teyla_home
    return teyla_home() / "state" / "crash.seen"


def seen_ids() -> set:
    try:
        return {ln.strip() for ln in seen_path().read_text().splitlines() if ln.strip()}
    except OSError:
        return set()


def ack(ids) -> int:
    """Mark incidents seen; returns how many were new. Written atomically, 0600."""
    from . import config
    ids = {i for i in ids if i}
    old = seen_ids()
    new = ids - old
    if not new:
        return 0
    p = seen_path()
    config.private_dir(p.parent)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, ("\n".join(sorted(old | ids)) + "\n").encode())
    finally:
        os.close(fd)
    os.replace(tmp, p)
    return len(new)


def unacked(evs: list, seen: set | None = None) -> list:
    """The panics and watchdog resets nobody has acknowledged, newest first."""
    seen = seen_ids() if seen is None else seen
    return sorted((e for e in evs if e.kind in KINDS_CRASH and e.id not in seen), key=lambda e: e.time, reverse=True)


# --- doctor and digest ----------------------------------------------------------------------------------------------

def recent(days: int = DEFAULT_DAYS, roots=None, now: dt.datetime | None = None) -> Found:
    now = now or dt.datetime.now().astimezone()
    return collect(now - dt.timedelta(days=days), roots)


def doctor_row(days: int = DEFAULT_DAYS, roots=None, now: dt.datetime | None = None) -> tuple[str, str, str | None]:
    """(level, detail, fix) for doctor's `machine:crash`: WARN for an unacknowledged panic or watchdog reset
    in the window, INFO otherwise (jetsam alone happens routinely)."""
    found = recent(days, roots, now)
    bad = unacked(found.events)
    if bad:
        extra = f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""
        return "WARN", bad[0].short() + extra, "teyla crash, then teyla crash --ack"
    n_j = sum(1 for e in found.events if isinstance(e, Jetsam))
    n_crash = sum(1 for e in found.events if e.kind in KINDS_CRASH)
    detail = f"no new panic or watchdog reset in {days} days"
    if n_crash:
        detail += f" ({n_crash} acknowledged)"
    if n_j:
        detail += f"; {n_j} jetsam event(s)"
    if found.unreadable:
        detail += "; not readable: " + ", ".join(found.unreadable[:2])
    return "INFO", detail, None


def digest_candidates(days: int = DEFAULT_DAYS, roots=None, now: dt.datetime | None = None) -> list[dict]:
    """One digest line, ranked 1 (as a high-severity finding), for an unacknowledged panic or watchdog
    reset in the window. Reads a handful of file names and the newest few; no process is started."""
    try:
        bad = unacked(recent(days, roots, now).events)
    except Exception:  # noqa: BLE001
        return []
    if not bad:
        return []
    more = f" (+{len(bad) - 1} more)" if len(bad) > 1 else ""
    return [dict(rank=1, id="crash:panic", text=bad[0].short() + more, step="teyla crash", cmd=True)]


# --- the report -----------------------------------------------------------------------------------------------------

def report(days: int = DEFAULT_DAYS, roots=None, records=None, now: dt.datetime | None = None) -> dict:
    """The whole report as data: events newest first, each crash with its context and nearest jetsam,
    the advice, and the folders that could not be read."""
    found = recent(days, roots, now)
    evs = found.events
    seen = seen_ids()
    items = []
    for ev in sorted(evs, key=lambda e: e.time, reverse=True):
        item = {"event": ev, "new": ev.kind in KINDS_CRASH and ev.id not in seen}
        if ev.kind in KINDS_CRASH:
            item["context"] = context(ev, path=records)
            item["jetsam"] = nearest_jetsam(ev, evs)
        items.append(item)
    lead = next((i for i in items if i["event"].kind in KINDS_CRASH), None) or (items[0] if items else None)
    tips: list[str] = []
    if lead:
        ev = lead["event"]
        ctx = lead.get("context") or (context(ev, path=records) if isinstance(ev, Jetsam) else None)
        tips = advice(ev, ctx, lead.get("jetsam"))
    return {"days": days, "items": items, "advice": tips, "unreadable": found.unreadable}


def render(rep: dict) -> str:
    items, out = rep["items"], []
    for it in items:
        ev = it["event"]
        out.append(ev.line() + ("   [new]" if it["new"] else ""))
        if isinstance(ev, Jetsam):
            if ev.top:
                out.append(f"    top apps: {ev.top_text()}")
            if ev.killed:
                out.append(f"    killed: {ev.killed_text()}")
            continue
        if "context" in it:
            out += ["    " + ln.strip() for ln in it["context"].lines()]
        j = it.get("jetsam")
        if j:
            mins = int((ev.time - j.time).total_seconds() // 60)
            out.append(f"    nearest jetsam: {_stamp(j.time)} ({mins} min earlier) — "
                       + (f"compressor {_gb(j.compressor_bytes)}, " if j.compressor_bytes is not None else "")
                       + f"{j.processes} processes")
            if j.top:
                out.append(f"      top apps: {j.top_text()}")
            if j.killed:
                out.append(f"      killed: {j.killed_text()}")
    if not items:
        out.append(f"no panic, watchdog reset or jetsam event in the last {rep['days']} days")
    for p in rep["unreadable"]:
        out.append(f"not readable: {p} (reports there were skipped)")
    if rep["advice"]:
        out.append("")
        out.append("what to change:")
        out += [f"  - {t}" for t in rep["advice"]]
    n_new = sum(1 for it in items if it["new"])
    if n_new:
        out.append("")
        out.append(f"{n_new} unacknowledged: `teyla crash --ack` marks them seen (doctor and the banner stop warning)")
    return "\n".join(out)


def to_json(rep: dict) -> dict:
    items = []
    for it in rep["items"]:
        d = it["event"].to_json()
        d["new"] = it["new"]
        if "context" in it:
            d["context"] = it["context"].to_json()
            d["nearest_jetsam"] = it["jetsam"].to_json() if it.get("jetsam") else None
        items.append(d)
    return {"days": rep["days"], "events": items, "advice": rep["advice"], "unreadable": rep["unreadable"]}


# --- the command ------------------------------------------------------------------------------------------------------

def cmd_crash(args) -> int:
    if args.days < 1:
        print("teyla crash: --days must be 1 or more", file=sys.stderr)
        return 2
    rep = report(args.days)
    if args.json:
        print(json.dumps(to_json(rep), indent=1, ensure_ascii=False))
    else:
        print(render(rep))
    if args.ack:
        try:
            n = ack([it["event"].id for it in rep["items"]])
        except OSError as e:
            print(f"teyla crash: could not record the acknowledgement: {e}", file=sys.stderr)
            return 1
        print(f"acknowledged {n} incident(s)" if n else "nothing new to acknowledge", file=sys.stderr if args.json else sys.stdout)
    return 0


def register(sp):
    q = sp.add_parser("crash", help="after a crash: what the panic was and what the machine looked like right before",
                      description=__doc__.split("\n\n")[0])
    q.set_defaults(fn=cmd_crash)
    q.add_argument("--days", type=int, default=DEFAULT_DAYS, metavar="N", help="how far back to look (default 7)")
    q.add_argument("--json", action="store_true", help="the report as JSON")
    q.add_argument("--ack", action="store_true", help="mark every listed incident seen (doctor and the banner stop warning)")
    return q

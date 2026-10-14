"""`teyla schedules` — every scheduled task on this machine, and whether it ran.

A scheduled task can stop running without anyone noticing: a Claude desktop task whose
definition was written but never registered with the app, a launchd job that exits 1 on every
run, a plist renamed to `.bak`, a cloud routine nobody can see from here. `teyla routines`
covers the tasks a repo declares in its `teyla.toml`; this command covers the rest, from the
records the machine already keeps:

    claude-desktop   ~/.claude/scheduled-tasks/<id>/SKILL.md is the definition; the app's own
                     record is `scheduled-tasks.json` under ~/Library/Application Support/Claude/
                     (`claude-code-sessions/*/*/` and `local-agent-mode-sessions/*/*/`). A
                     definition no record names never fires: UNREGISTERED.
    launchd          ~/Library/LaunchAgents/*.plist with a StartCalendarInterval or StartInterval.
                     `launchctl list` gives the last exit status, not times; run times are the
                     modification times of the plist's StandardOutPath / StandardErrorPath.
    cloud            Claude cloud routines (the RemoteTrigger tool) have no local store. The only
                     trace is the session transcripts that created or updated them, so the entry
                     says "last known as of <date>" and its verdict is UNKNOWN.
    github           `schedule:` crons in <code_root>/*/.github/workflows/*.yml. The last run
                     comes from `gh run list`, only when the network is allowed.
    routines         the `[[routine]]` tables of every repo's teyla.toml, as `teyla routines`
                     judges them (a launchd label seen there is not listed twice).

Session crons (CronCreate) die with the session and are never listed; the output carries one
line with how many the transcripts show created in the last 30 days.

A routine marked `paused = "<date>: <reason>"` in teyla.toml is DISABLED with the note
"paused: <reason>": the owner left it off, so it is not a problem. If it is loaded anyway the verdict
is PAUSED BUT LOADED, which is one.

Verdicts: OK, STALE (last run older than the expected interval x 1.5 + 2h), FAILING (last exit
non-zero), DISABLED, UNREGISTERED, MISSING DEFINITION, NEVER RAN, DONE (a one-shot that ran),
VANISHED, UNKNOWN (nothing on this machine can say). The problems are STALE, FAILING,
UNREGISTERED, MISSING DEFINITION, NEVER RAN and VANISHED; DISABLED, DONE and UNKNOWN are listed
but are not problems, because someone chose them or nothing can say.

The registry, `~/.teyla/schedules.json`, keeps every id ever seen with its first and last day and
its last snapshot. An id seen before and gone now is VANISHED ("last seen <date>") for 30 days:
that is what lets a later session answer "did it disappear?". Cloud routines are the exception,
because their only evidence is transcripts that age out; they stay "last known".

`--quiet` prints nothing, updates the registry and writes the problems to
`~/.teyla/schedules.problems` (`key<TAB>text`, what the session-start banner reads), removing the
file when there are none. Exit 1 when any problem, else 0.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import plistlib
import re
import shutil
import subprocess
import sys

from . import config, net, routines

UTC = dt.timezone.utc
SOURCES = ("claude-desktop", "launchd", "cloud", "github", "routines")
# Worst first: the order problems are listed in.
SEVERITY = ("FAILING", "PAUSED BUT LOADED", "UNREGISTERED", "MISSING DEFINITION", "NEVER RAN", "STALE", "VANISHED",
            "UNKNOWN", "DISABLED", "DONE", "OK")
PROBLEMS = frozenset({"FAILING", "PAUSED BUT LOADED", "UNREGISTERED", "MISSING DEFINITION", "NEVER RAN", "STALE", "VANISHED"})
DEFAULT_IGNORE_PREFIXES = list(config.DEFAULTS["schedules"]["ignore_prefixes"])
VANISHED_KEEP = dt.timedelta(days=30)
CLOUD_LOOKBACK = dt.timedelta(days=90)
SESSION_CRON_WINDOW = dt.timedelta(days=30)
STALE_FACTOR = 1.5
STALE_SLACK = dt.timedelta(hours=2)
DAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
UNREGISTERED_NOTE = ("defined but the app has no schedule for it, so it never fires — recreate it "
                     "from the app or ask Claude to schedule it again")
CRON_KEYS = ("cronExpression", "cron", "schedule")
GH_TIMEOUT_S = 20


# --- small helpers -----------------------------------------------------------------------------

def _now() -> dt.datetime:
    return dt.datetime.now(UTC)


def _home() -> pathlib.Path:
    return pathlib.Path.home()  # at call time: a test's HOME is honoured


def _registry_path() -> pathlib.Path:
    return config.TEYLA_DIR / "schedules.json"


def problems_path() -> pathlib.Path:
    return config.TEYLA_DIR / "schedules.problems"


def _parse_ts(v) -> dt.datetime | None:
    """An ISO timestamp (or epoch milliseconds) as an aware datetime, else None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        t = dt.datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _mtime(p: pathlib.Path) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(p.stat().st_mtime, tz=UTC)
    except OSError:
        return None


# A wrapper that stamps every start (`date ... > "/path/x.last"`, as Teyla's own wrappers do) records
# its runs even when its log stays quiet: a log written only when there is work to do would otherwise
# make a healthy agent look STALE.
_STAMP_RE = re.compile(r'^\s*date\b[^\n>]*>\s*"?([^"\s;&|]+\.last)"?', re.M)


def _wrapper_stamp(plist: dict) -> pathlib.Path | None:
    args = plist.get("ProgramArguments")
    if not isinstance(args, list) or not args or not isinstance(args[-1], str) or not args[-1].endswith(".sh"):
        return None
    try:
        text = pathlib.Path(args[-1]).expanduser().read_text(errors="replace")[:20000]
    except OSError:
        return None
    m = _STAMP_RE.search(text)
    return pathlib.Path(m.group(1)).expanduser() if m else None


def _local(t: dt.datetime) -> dt.datetime:
    return t.astimezone()


def _date(t: dt.datetime | None) -> str:
    return f"{_local(t):%Y-%m-%d}" if t else "?"


def relative(t: dt.datetime | None, now: dt.datetime) -> str:
    if t is None:
        return "never"
    secs = int((now - t).total_seconds())
    if secs < 0:
        return "in the future"
    if secs < 90:
        return "just now"
    if secs < 90 * 60:
        return f"{round(secs / 60)}m ago"
    if secs < 36 * 3600:
        return f"{round(secs / 3600)}h ago"
    return f"{round(secs / 86400)}d ago"


def _short(s: str, n: int = 110) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _every_text(td: dt.timedelta) -> str:
    secs = int(td.total_seconds())
    if secs % 86400 == 0:
        return f"every {secs // 86400}d"
    if secs % 3600 == 0:
        return f"every {secs // 3600}h"
    return f"every {max(secs // 60, 1)}m"


def entry(source: str, key: str, name: str, *, cadence: str = "", expected_every: dt.timedelta | None = None,
          enabled: bool = True, last_run: dt.datetime | None = None, last_exit: int | None = None,
          definition="", note: str = "", verdict: str | None = None, since: dt.datetime | None = None,
          run_known: bool = True, fire_at: dt.datetime | None = None, last_run_text: str | None = None,
          elsewhere: bool = False) -> dict:
    """One scheduled task. `verdict` is preset only by a reader that already knows (UNREGISTERED,
    DISABLED, ...); `verdict_of` decides the rest. `since` is when it was created (how long it has
    had to run), `run_known` whether any record of a run could exist, `elsewhere` that another
    report (`teyla routines`) already puts its problem in the banner."""
    return {"id": f"{source}:{key}", "source": source, "name": name, "cadence": cadence,
            "expected_every": expected_every, "enabled": enabled, "last_run": last_run,
            "last_exit": last_exit, "definition": str(definition), "note": note, "verdict": verdict,
            "since": since, "run_known": run_known, "fire_at": fire_at, "last_run_text": last_run_text,
            "elsewhere": elsewhere}


# --- cadence -----------------------------------------------------------------------------------

def _dow_names(field: str) -> tuple[str, dt.timedelta] | None:
    """(human, longest gap) for a cron day-of-week field of digits, lists and ranges, else None."""
    days: set[int] = set()
    for part in field.split(","):
        m = re.fullmatch(r"(\d)(?:-(\d))?", part)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2) if m.group(2) is not None else m.group(1))
        if a > 7 or b > 7 or b < a:
            return None
        days.update(d % 7 for d in range(a, b + 1))
    return _day_set_text(days)


def _day_set_text(days: set[int]) -> tuple[str, dt.timedelta]:
    ordered = sorted(days)
    gaps = [(ordered[(i + 1) % len(ordered)] - d) % 7 or 7 for i, d in enumerate(ordered)]
    gap = dt.timedelta(days=max(gaps))
    if len(ordered) == 7:
        return "daily", gap
    if ordered == [1, 2, 3, 4, 5]:
        return "weekdays", gap
    if ordered == [0, 6]:
        return "weekends", gap
    if len(ordered) == 1:
        return f"weekly {DAYS[ordered[0]]}", gap
    return "weekly " + ",".join(DAYS[d] for d in ordered), gap


def parse_cron(expr: str) -> tuple[str, dt.timedelta | None]:
    """(human cadence, expected interval) for a five-field cron expression. An expression this does
    not recognise comes back as `cron <expr>` with an interval only when the fields bound it."""
    expr = str(expr).strip()
    parts = expr.split()
    if len(parts) != 5:
        return f"cron {expr}", None
    m, h, dom, mon, dow = parts
    step = lambda x: re.fullmatch(r"\*/(\d+)", x)  # noqa: E731
    is_num = lambda x: x.isdigit()  # noqa: E731
    if dom == "*" and mon == "*" and dow == "*":
        if m == "*" and h == "*":
            return "every minute", dt.timedelta(minutes=1)
        if step(m) and h == "*" and int(step(m).group(1)) > 0:
            return _every_text(dt.timedelta(minutes=int(step(m).group(1)))), dt.timedelta(minutes=int(step(m).group(1)))
        if is_num(m) and h == "*":
            return f"hourly :{int(m):02d}", dt.timedelta(hours=1)
        if is_num(m) and step(h) and int(step(h).group(1)) > 0:
            n = int(step(h).group(1))
            return f"every {n}h", dt.timedelta(hours=n)
    hours = h.split(",")
    if is_num(m) and all(is_num(x) for x in hours) and mon == "*":
        times = ", ".join(f"{int(x):02d}:{int(m):02d}" for x in hours)
        if dom == "*" and dow == "*":
            return f"daily {times}", dt.timedelta(days=1)
        if dom == "*":
            named = _dow_names(dow)
            if named:
                text, gap = named
                return f"{text} {times}", gap
        elif dow == "*" and is_num(dom):
            return f"monthly day {int(dom)} {times}", dt.timedelta(days=31)
    if dom == "*" and dow == "*" and mon == "*":
        return f"cron {expr}", None
    return f"cron {expr}", dt.timedelta(days=7) if dom == "*" and mon == "*" else None


def _calendar_one(d: dict) -> tuple[str, dt.timedelta]:
    def g(k):
        v = d.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    mi, hr, wd, dy, mo = g("Minute"), g("Hour"), g("Weekday"), g("Day"), g("Month")
    t = f"{hr:02d}:{(mi or 0):02d}" if hr is not None else None
    if mo is not None:
        return f"yearly {mo:02d}-{(dy or 1):02d} {t or '00:00'}", dt.timedelta(days=366)
    if dy is not None:
        return f"monthly day {dy} {t or '00:00'}", dt.timedelta(days=31)
    if wd is not None:
        return f"weekly {DAYS[wd % 7]} {t or '00:00'}", dt.timedelta(days=7)
    if hr is not None:
        return f"daily {t}", dt.timedelta(days=1)
    if mi is not None:
        return f"hourly :{mi:02d}", dt.timedelta(hours=1)
    return "every minute", dt.timedelta(minutes=1)


def calendar_cadence(value) -> tuple[str, dt.timedelta | None]:
    """A launchd StartCalendarInterval (one dict or a list of them) as (human, expected interval)."""
    items = [value] if isinstance(value, dict) else [v for v in (value or []) if isinstance(v, dict)]
    if not items:
        return "calendar schedule", None
    if len(items) == 1:
        return _calendar_one(items[0])
    keys = {k for d in items for k in d}
    if "Weekday" in keys and not keys & {"Day", "Month"}:
        times = sorted({(d.get("Hour"), d.get("Minute", 0)) for d in items}, key=lambda x: (x[0] is None, x))
        days = {int(d["Weekday"]) % 7 for d in items if isinstance(d.get("Weekday"), int)}
        if days and all(isinstance(d.get("Weekday"), int) for d in items):
            text, gap = _day_set_text(days)
            hm = ", ".join(f"{int(h):02d}:{int(m):02d}" for h, m in times if isinstance(h, int) and isinstance(m, int))
            return f"{text} {hm}".strip(), gap
    parts = [_calendar_one(d) for d in items]
    gap = min(p[1] for p in parts)  # the shortest: the more frequent entry going quiet is the alarm
    shown = "; ".join(p[0] for p in parts[:3]) + (f"; +{len(parts) - 3} more" if len(parts) > 3 else "")
    return shown, gap


# --- verdicts ----------------------------------------------------------------------------------

def verdict_of(e: dict, now: dt.datetime) -> str:
    """The verdict of one entry: the one its reader preset, else decided from what is recorded."""
    if e.get("verdict"):
        return e["verdict"]
    run, expected, since, fire_at = e.get("last_run"), e.get("expected_every"), e.get("since"), e.get("fire_at")
    if fire_at is not None and run is not None:
        return "DONE"  # a one-shot that ran; the app may have switched it off since
    if not e.get("enabled", True):
        return "DISABLED"
    if e.get("last_exit") not in (None, 0):
        return "FAILING"
    if fire_at is not None:
        if not e.get("run_known", True):
            return "UNKNOWN"
        return "NEVER RAN" if now - fire_at > dt.timedelta(hours=1) else "OK"
    if run is None:
        if not e.get("run_known", True) or expected is None:
            return "UNKNOWN"
        return "NEVER RAN" if since is not None and now - since > expected else "OK"
    if expected is not None and now - run > expected * STALE_FACTOR + STALE_SLACK:
        return "STALE"
    return "OK"


# --- claude desktop ----------------------------------------------------------------------------

def _frontmatter(text: str) -> dict:
    out: dict = {}
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return out
    for line in lines[1:]:
        if line.strip() == "---":
            break
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip("'\"")
    return out


def _cron_of(rec: dict) -> str | None:
    for k in CRON_KEYS:
        v = rec.get(k)
        if isinstance(v, dict):
            v = v.get("cron") or v.get("expression") or v.get("cronExpression")
        if isinstance(v, str) and len(v.split()) in (5, 6):
            return v.strip()
    return None


def _desktop_records(home: pathlib.Path) -> dict[str, dict]:
    base = home / "Library" / "Application Support" / "Claude"
    files: list[pathlib.Path] = []
    for sub in ("claude-code-sessions", "local-agent-mode-sessions"):
        try:
            files += sorted((base / sub).glob("*/*/scheduled-tasks.json"))
        except OSError:
            pass
    out: dict[str, dict] = {}
    for f in files:
        try:
            data = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            data = data.get("scheduledTasks") or data.get("tasks") or []
        for rec in data if isinstance(data, list) else []:
            if not isinstance(rec, dict) or not rec.get("id"):
                continue
            rid = str(rec["id"])
            old = out.get(rid)
            if old is None or (_parse_ts(rec.get("lastRunAt")) or dt.datetime.min.replace(tzinfo=UTC)) >= (
                    _parse_ts(old.get("lastRunAt")) or dt.datetime.min.replace(tzinfo=UTC)):
                out[rid] = rec
    return out


def read_claude_desktop(home: pathlib.Path | None = None, now: dt.datetime | None = None) -> list[dict]:
    home = home or _home()
    records = _desktop_records(home)
    entries: list[dict] = []
    seen_ids: set[str] = set()
    for rid, rec in records.items():
        seen_ids.add(rid)
        fp = rec.get("filePath")
        path = pathlib.Path(str(fp)).expanduser() if fp else home / ".claude" / "scheduled-tasks" / rid / "SKILL.md"
        name = str(rec.get("displayName") or rec.get("name") or rid)
        fire = _parse_ts(rec.get("fireAt"))
        cron = _cron_of(rec)
        if fire is not None:
            cadence, expected = f"once {_local(fire):%Y-%m-%d %H:%M}", None
        elif cron:
            cadence, expected = parse_cron(cron) if len(cron.split()) == 5 else (f"cron {cron}", None)
        else:
            cadence, expected = "schedule not recorded", None
        last = _parse_ts(rec.get("lastRunAt"))
        note = ""
        scheduled_for = _parse_ts(rec.get("lastScheduledFor"))
        if scheduled_for is not None and last is None:
            note = f"last scheduled for {_local(scheduled_for):%Y-%m-%d %H:%M} but no run is recorded"
        verdict = None
        if fp and not path.exists():
            verdict = "MISSING DEFINITION"
            note = f"the app has a schedule for it but {path} is gone, so there is nothing to run"
        enabled = rec.get("enabled", True) is not False
        entries.append(entry("claude-desktop", rid, name, cadence=cadence, expected_every=expected, enabled=enabled,
                             last_run=last, definition=path, note=note, verdict=verdict,
                             since=_parse_ts(rec.get("createdAt")), fire_at=fire))
    registered_paths = set()
    for rec in records.values():
        if rec.get("filePath"):
            try:
                registered_paths.add(str(pathlib.Path(str(rec["filePath"])).expanduser().resolve()))
            except OSError:
                pass
    defs = home / ".claude" / "scheduled-tasks"
    try:
        folders = sorted(p for p in defs.iterdir() if (p / "SKILL.md").is_file())
    except OSError:
        folders = []
    for d in folders:
        skill = d / "SKILL.md"
        try:
            resolved = str(skill.resolve())
        except OSError:
            resolved = str(skill)
        if d.name in seen_ids or resolved in registered_paths:
            continue
        try:
            meta = _frontmatter(skill.read_text())
        except OSError:
            meta = {}
        entries.append(entry("claude-desktop", d.name, meta.get("name") or d.name, cadence="not scheduled",
                             definition=skill, note=UNREGISTERED_NOTE, verdict="UNREGISTERED",
                             since=_mtime(skill), run_known=False))
    return entries


# --- launchd -----------------------------------------------------------------------------------

def _launchctl_disabled() -> set[str]:
    """Labels `launchctl print-disabled gui/<uid>` lists as disabled. Empty when it cannot be read."""
    try:
        r = subprocess.run(["launchctl", "print-disabled", f"gui/{os.getuid()}"], capture_output=True,
                           text=True, timeout=10)
    except (OSError, subprocess.SubprocessError, AttributeError):
        return set()
    return parse_disabled(r.stdout if r.returncode == 0 else "")


def parse_disabled(text: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r'"([^"]+)"\s*=>\s*(?:disabled|true)\b', text or "")}


def parse_listing(text: str) -> dict[str, tuple[str | None, int | None]]:
    """`launchctl list` as {label: (pid or None, last exit status or None)}."""
    out = {}
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or parts[0] == "PID":
            continue
        pid = None if parts[0] == "-" else parts[0]
        try:
            status = int(parts[1])
        except ValueError:
            status = None
        out[parts[2]] = (pid, status)
    return out


_REMOVED_RE = re.compile(r"\.(?:bak|disabled)(?:[-.][\w.-]*)?$")  # .bak, .disabled, .bak-2026-08-26, .disabled-slots


def _ignored(label: str, prefixes) -> bool:
    return label.startswith("com.apple.") or any(label.startswith(p) for p in prefixes if p)


def ignore_prefixes(cfg: dict | None = None) -> list[str]:
    cfg = cfg if cfg is not None else config.load()
    raw = (cfg.get("schedules") or {}).get("ignore_prefixes", DEFAULT_IGNORE_PREFIXES)
    return [str(p) for p in raw] if isinstance(raw, list) else list(DEFAULT_IGNORE_PREFIXES)


def _load_plist(data: bytes) -> dict:
    """The plist as a dict. launchd and plutil accept XML comments with `--` inside, which expat (and
    so plistlib) rejects, so a failed parse is retried with the comments removed."""
    try:
        out = plistlib.loads(data)
    except Exception:  # noqa: BLE001
        out = plistlib.loads(re.sub(rb"<!--.*?-->", b"", data, flags=re.S))
    if not isinstance(out, dict):
        raise ValueError("not a dict")
    return out


def read_launchd(agents_dir: pathlib.Path | None = None, *, listing: str | None = None,
                 disabled: set[str] | None = None, now: dt.datetime | None = None,
                 prefixes: list[str] | None = None) -> list[dict]:
    agents_dir = agents_dir or _home() / "Library" / "LaunchAgents"
    prefixes = DEFAULT_IGNORE_PREFIXES if prefixes is None else prefixes
    loaded = parse_listing(routines._launchctl_list() if listing is None else listing)
    disabled = _launchctl_disabled() if disabled is None else disabled
    try:
        files = sorted(agents_dir.iterdir())
    except OSError:
        return []
    live: dict[str, dict] = {}
    removed: dict[str, dict] = {}
    for f in files:
        n = f.name
        is_live = n.endswith(".plist")
        is_removed = bool(_REMOVED_RE.search(n)) and not is_live
        if not (is_live or is_removed) or not f.is_file():
            continue
        try:
            plist = _load_plist(f.read_bytes())
        except Exception:  # noqa: BLE001 - a plist that does not parse is reported, never fatal
            if is_live:
                label = n[: -len(".plist")]
                if not _ignored(label, prefixes):
                    e = entry("launchd", label, label, definition=f, run_known=False, since=_mtime(f),
                              note="the plist does not parse, so launchd cannot read its schedule")
                    if label in disabled:
                        e.update(enabled=False, verdict="DISABLED",
                                 note=e["note"] + "; it is disabled in launchd")
                    elif label in loaded:
                        e["verdict"] = "UNKNOWN"
                    else:
                        e.update(verdict="UNREGISTERED", note="the plist does not parse and launchd has not "
                                 "loaded it, so it never fires")
                    live[label] = e
            continue
        label = str(plist.get("Label") or re.sub(r"\.plist.*$|" + _REMOVED_RE.pattern, "", n))
        if _ignored(label, prefixes):
            continue
        cal, interval = plist.get("StartCalendarInterval"), plist.get("StartInterval")
        if cal is None and not isinstance(interval, int):
            continue  # a daemon (KeepAlive, RunAtLoad), not a schedule
        if cal is not None:
            cadence, expected = calendar_cadence(cal)
        else:
            expected = dt.timedelta(seconds=max(int(interval), 1))
            cadence = _every_text(expected)
        logs = []
        for key in ("StandardOutPath", "StandardErrorPath"):
            p = plist.get(key)
            if isinstance(p, str) and p:
                t = _mtime(pathlib.Path(p).expanduser())
                if t:
                    logs.append(t)
        stamp = _wrapper_stamp(plist)
        if stamp is not None and (t := _mtime(stamp)):
            logs.append(t)
        has_log_path = stamp is not None or any(
            isinstance(plist.get(k), str) and plist.get(k) for k in ("StandardOutPath", "StandardErrorPath"))
        pid, status = loaded.get(label, (None, None))
        e = entry("launchd", label, label, cadence=cadence, expected_every=expected,
                  last_run=max(logs) if logs else None, last_exit=status, definition=f, since=_mtime(f),
                  run_known=has_log_path)
        if status not in (None, 0):
            e["note"] = f"last exit {status}"
        if not has_log_path:
            e["note"] = (e["note"] + "; " if e["note"] else "") + "no StandardOutPath, so no run time is recorded"
        if is_removed:
            e.update(enabled=False, verdict="DISABLED", last_exit=None,
                     note=f"{n} is a renamed copy: launchd does not load it")
            removed.setdefault(label, e)
            continue
        if plist.get("Disabled") is True or label in disabled:
            e.update(enabled=False, verdict="DISABLED",
                     note=f"disabled in launchd (launchctl enable gui/{os.getuid()}/{label})")
        elif loaded and label not in loaded:
            e.update(verdict="UNREGISTERED",
                     note=f"the plist is in LaunchAgents but launchd has not loaded it, so it never fires "
                          f"(launchctl bootstrap gui/{os.getuid()} {f})")
        live[label] = e
    for label, e in removed.items():
        live.setdefault(label, e)
    return list(live.values())


# --- cloud routines (transcripts) --------------------------------------------------------------

def _blocks(obj: dict):
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict):
                yield b


def _result_text(block: dict) -> str:
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(str(x.get("text", "")) for x in c if isinstance(x, dict))
    return ""


_HTTP_OK_RE = re.compile(r"^\s*HTTP\s+2\d\d\b")


def _delete_succeeded(block: dict) -> bool:
    """A RemoteTrigger delete result that shows success: `HTTP 2xx` first, and not flagged as an error."""
    return not block.get("is_error") and bool(_HTTP_OK_RE.match(_result_text(block)))


def _triggers_in(text: str) -> list[dict]:
    """The routine objects in a RemoteTrigger result. The real result is `HTTP 200` and a line of
    JSON: `{"trigger": {...}}` for create/get/update/run, `{"data": [{...}, ...]}` for list. A routine
    object has an `id` (trig_...), a `name`, a `cron_expression`, `enabled` and `last_fired_at`."""
    i = text.find("{")
    if i < 0:
        return []
    try:
        data = json.loads(text[i:])
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    objs = [data["trigger"]] if isinstance(data.get("trigger"), dict) else (
        [x for x in data["data"] if isinstance(x, dict)] if isinstance(data.get("data"), list) else [])
    return [o for o in objs if isinstance(o.get("id"), str) and ("cron_expression" in o or "name" in o)]


def scan_transcripts(root: str | pathlib.Path | None = None, now: dt.datetime | None = None
                     ) -> tuple[list[dict], int]:
    """(cloud routine entries, how many session crons (CronCreate) the transcripts show created in the
    last 30 days). A routine's state is the newest RemoteTrigger result that shows it (create, get,
    update, run and list all return it); a `delete` call marks it deleted. Only lines that mention
    RemoteTrigger or CronCreate, or answer one of its calls, are parsed; transcripts untouched for 90
    days are skipped (the registry keeps what they once showed)."""
    from .adapters import claude_code
    root = pathlib.Path(claude_code.DEFAULT_ROOT if root is None else root).expanduser()
    now = now or _now()
    state: dict[str, dict] = {}
    cron_count = 0
    try:
        files = sorted(root.glob("*/*.jsonl"))
    except OSError:
        files = []
    for f in files:
        mt = _mtime(f)
        if mt is None or now - mt > CLOUD_LOOKBACK:
            continue
        pending: set[str] = set()  # tool_use ids of RemoteTrigger calls awaiting their result
        deleting: dict[str, str] = {}  # tool_use id -> trigger id, for the delete calls among them
        try:
            fh = f.open("r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if ("RemoteTrigger" not in line and "CronCreate" not in line
                        and not (pending and any(pid in line for pid in pending))):
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                stamp = _parse_ts(obj.get("timestamp")) or mt
                for b in _blocks(obj):
                    kind, name = b.get("type"), str(b.get("name", ""))
                    if kind == "tool_use" and name.endswith("CronCreate"):
                        if now - stamp <= SESSION_CRON_WINDOW:
                            cron_count += 1
                    elif kind == "tool_use" and name.endswith("RemoteTrigger"):
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        if b.get("id"):
                            pending.add(str(b["id"]))
                            if str(inp.get("action", "")).lower() == "delete" and inp.get("trigger_id"):
                                deleting[str(b["id"])] = str(inp["trigger_id"])
                    elif kind == "tool_result" and str(b.get("tool_use_id", "")) in pending:
                        uid = str(b["tool_use_id"])
                        pending.discard(uid)
                        if uid in deleting:
                            # A delete counts only when its result says it worked; a refused or failed
                            # one leaves the routine where it was.
                            tid = deleting.pop(uid)
                            if _delete_succeeded(b):
                                rec = state.setdefault(tid, {"stamp": stamp, "file": str(f)})
                                rec["deleted"] = stamp
                            continue
                        for o in _triggers_in(_result_text(b)):
                            rec = state.setdefault(o["id"], {"stamp": stamp, "file": str(f)})
                            if "name" not in rec or stamp >= rec["stamp"]:
                                rec.update(name=o.get("name"), cron=o.get("cron_expression"),
                                           enabled=o.get("enabled") is not False, stamp=stamp, file=str(f),
                                           fired=_parse_ts(o.get("last_fired_at")))
    out = []
    for key, rec in sorted(state.items()):
        if "name" not in rec:
            continue  # only a delete call was seen: nothing to describe
        cron = rec.get("cron")
        cadence, expected = parse_cron(cron) if cron and len(str(cron).split()) == 5 else (
            (f"cron {cron}" if cron else "schedule not seen"), None)
        note = f"last known as of {_date(rec['stamp'])}"
        if rec.get("fired"):
            note += f"; last fired {_date(rec['fired'])}"
        note += "; cloud runs leave no record on this machine, check its run history in Claude"
        e = entry("cloud", key, rec.get("name") or key, cadence=cadence, expected_every=expected,
                  enabled=rec.get("enabled", True), last_run=rec.get("fired"), definition=rec["file"],
                  run_known=False, since=rec["stamp"], note=note)
        if rec.get("enabled", True):
            e["verdict"] = "UNKNOWN"  # a transcript is old news, not a run record: never STALE from here
        deleted = rec.get("deleted")
        if deleted is not None and deleted >= rec["stamp"]:
            if now - deleted > VANISHED_KEEP:
                continue
            e.update(verdict="VANISHED", note=f"deleted in a session on {_date(deleted)}")
        out.append(e)
    return out, cron_count


def read_cloud(root=None, now: dt.datetime | None = None) -> list[dict]:
    return scan_transcripts(root, now)[0]


# --- github ------------------------------------------------------------------------------------

_CRON_RE = re.compile(r"""\bcron\s*:\s*(['"])(.*?)\1""")


def workflow_crons(text: str) -> list[str]:
    """The cron expressions under `schedule:` in a workflow file, in order."""
    lines = text.splitlines()
    out: list[str] = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)schedule\s*:\s*(.*)$", line)
        if not m:
            continue
        indent = len(m.group(1))
        inline = m.group(2)
        out += [x.group(2) for x in _CRON_RE.finditer(inline)]
        for later in lines[i + 1:]:
            s = later.strip()
            if not s or s.startswith("#"):
                continue
            ind = len(later) - len(later.lstrip())
            if ind < indent or (ind == indent and not s.startswith("-")):
                break
            out += [x.group(2) for x in _CRON_RE.finditer(later.split(" #")[0])]
    return out


def _workflow_name(text: str, fallback: str) -> str:
    m = re.search(r"^name\s*:\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip("'\"") if m else fallback


def _gh_last_run(repo: pathlib.Path, workflow: str) -> dict | None:
    """The newest run of a workflow that the schedule fired, as {conclusion, createdAt}, or None when
    it has none. Pushes and manual runs do not count: they would hide a schedule that stopped firing.
    Raises RuntimeError with a one-line reason when gh cannot answer."""
    try:
        r = subprocess.run(["gh", "run", "list", "--workflow", workflow, "--event", "schedule", "--limit", "1",
                            "--json", "conclusion,createdAt"], capture_output=True, text=True, timeout=GH_TIMEOUT_S,
                           cwd=str(repo))
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh did not answer in time") from None
    except (OSError, subprocess.SubprocessError) as e:
        raise RuntimeError(f"gh could not run ({e})") from None
    if r.returncode != 0:
        tail = ((r.stderr or "").strip().splitlines() or [""])[-1][:120]
        raise RuntimeError(f"gh exited {r.returncode}" + (f": {tail}" if tail else ""))
    try:
        runs = json.loads(r.stdout or "[]")
    except ValueError:
        raise RuntimeError("gh printed something that is not JSON") from None
    return runs[0] if isinstance(runs, list) and runs and isinstance(runs[0], dict) else None


def read_github(code_root: pathlib.Path | None = None, *, check_runs: bool = False,
                now: dt.datetime | None = None) -> list[dict]:
    code_root = code_root or config.code_root()
    try:
        repos = sorted(p for p in code_root.iterdir() if (p / ".github" / "workflows").is_dir())
    except OSError:
        return []
    have_gh = check_runs and shutil.which("gh") is not None
    out = []
    for repo in repos:
        wf_dir = repo / ".github" / "workflows"
        for wf in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
            try:
                text = wf.read_text()
            except OSError:
                continue
            crons = workflow_crons(text)
            if not crons:
                continue
            parsed = [parse_cron(c) for c in crons]
            gaps = [p[1] for p in parsed]
            # The shortest interval: a daily+weekly workflow is overdue when its daily runs stop.
            expected = None if any(g is None for g in gaps) else min(gaps)
            cadence = "; ".join(dict.fromkeys(p[0] for p in parsed))
            e = entry("github", f"{repo.name}/{wf.name}", f"{repo.name}: {_workflow_name(text, wf.stem)}",
                      cadence=cadence, expected_every=expected, definition=wf, since=_mtime(wf), run_known=False)
            if check_runs and not have_gh:
                e.update(last_run_text="not checked", note="gh is not installed, so the last run is not checked")
            elif not check_runs:
                e.update(last_run_text="not checked",
                         note="last run: not checked (safe mode; --allow-network looks it up)")
            else:
                try:
                    run = _gh_last_run(repo, wf.name)
                except RuntimeError as err:
                    e.update(last_run_text="not checked", note=f"last run: not checked ({err})")
                else:
                    e["run_known"] = True
                    if run is not None:
                        e["last_run"] = _parse_ts(run.get("createdAt"))
                        concl = str(run.get("conclusion") or "")
                        if concl in ("failure", "timed_out", "startup_failure", "action_required"):
                            e["last_exit"] = 1
                            e["note"] = f"last run concluded {concl}"
            out.append(e)
    return out


# --- teyla.toml routines -----------------------------------------------------------------------

_ROUTINE_VERDICTS = {"ok": "OK", "STALE": "STALE", "FAILING": "FAILING", "NOT LOADED": "UNREGISTERED",
                     "unknown": "UNKNOWN", routines.PAUSED: "DISABLED", routines.PAUSED_LOADED: "PAUSED BUT LOADED"}


def read_routines(reports: list[dict] | None = None, now: dt.datetime | None = None) -> list[dict]:
    reports = routines.evaluate_all() if reports is None else reports
    out = []
    for rep in reports:
        if rep.get("error"):
            continue
        for row in rep.get("routines") or []:
            raw = row.get("verdict", "unknown")
            verdict = _ROUTINE_VERDICTS.get(raw, "UNKNOWN")
            note = row.get("detail") or ""
            paused = row.get("paused")
            if raw == routines.PAUSED:
                note = "paused: " + str(paused)
            elif raw == routines.PAUSED_LOADED:
                note = f"paused in teyla.toml but {row.get('loaded', 'loaded')}: {paused}"
            elif raw == "NOT LOADED":
                note = "declared in teyla.toml but " + str(row.get("loaded", "not loaded"))
            elif raw in ("unknown", "STALE") and not note:
                note = f"loaded state: {row.get('loaded', '?')}"
            every = str(row.get("every") or "")
            expected = routines.cadence(every) if every else None
            last = _parse_ts(row.get("last_run")) if row.get("last_run") not in (None, "?") else None
            if raw == "ok" and last is None and row.get("loaded") != routines.ON_DEMAND:
                # Loaded, but nothing says it ever ran: "ok" with no run time is a guess.
                if row.get("log"):
                    verdict, note = "NEVER RAN", f"loaded, but its log {row['log']} does not exist"
                else:
                    verdict, note = "UNKNOWN", "loaded, but it declares no log, so there is no run time to judge"
            e = entry("routines", f"{rep['product']}:{row['name']}", f"{rep['product']}: {row['name']}",
                      cadence=("on demand" if row.get("loaded") == routines.ON_DEMAND else every or "unscheduled"),
                      expected_every=expected, last_run=last, definition=pathlib.Path(rep.get("repo", "")) / "teyla.toml",
                      note=note, verdict=verdict, enabled=raw != routines.PAUSED,
                      run_known=raw != routines.PAUSED,
                      # `teyla routines` writes its own banner item only for the verdicts it counts as not
                      # running; the rest (NEVER RAN on an "ok" routine) are this report's alone.
                      elsewhere=raw in routines.NOT_RUNNING_VERDICTS)
            e["label"] = row.get("label", "")
            e["kind"] = row.get("kind", "")
            e["repo"] = rep.get("repo", "")
            out.append(e)
    return out


# --- collection --------------------------------------------------------------------------------

def collect(now: dt.datetime | None = None, *, home: pathlib.Path | None = None,
            code_root: pathlib.Path | None = None, cfg: dict | None = None,
            allow_network: bool | None = None, reports: list[dict] | None = None,
            transcripts_root=None) -> tuple[list[dict], int]:
    """(every current entry with its verdict set, session-cron transcript count)."""
    now = now or _now()
    cfg = cfg if cfg is not None else config.load()
    check_runs = net.gate("`teyla schedules` GitHub run lookups", cfg, quiet=True) if allow_network is None \
        else allow_network
    rout = read_routines(reports, now)
    labels = {e["label"] for e in rout if e.get("kind") in ("launchd", "control") and e.get("label")}
    gh_routines = {(pathlib.Path(e["repo"]).name, e["label"]) for e in rout if e.get("kind") == "github-actions"}
    desktop = read_claude_desktop(home, now)
    launchd = [e for e in read_launchd(None if home is None else home / "Library" / "LaunchAgents", now=now,
                                       prefixes=ignore_prefixes(cfg))
               if e["id"].split(":", 1)[1] not in labels]
    cloud, cron_n = scan_transcripts(transcripts_root, now)
    github = [e for e in read_github(code_root, check_runs=check_runs, now=now)
              if tuple(e["id"].split(":", 1)[1].split("/", 1)) not in gh_routines]
    entries = desktop + launchd + cloud + github + rout
    for e in entries:
        e["verdict"] = verdict_of(e, now)
    return entries, cron_n


# --- registry ----------------------------------------------------------------------------------

def _iso(t: dt.datetime | None) -> str | None:
    return t.isoformat() if t else None


def _snapshot(e: dict) -> dict:
    exp = e.get("expected_every")
    return {"source": e["source"], "name": e["name"], "cadence": e["cadence"], "enabled": e["enabled"],
            "expected_every_s": int(exp.total_seconds()) if exp else None, "last_run": _iso(e.get("last_run")),
            "last_exit": e.get("last_exit"), "definition": e["definition"], "note": e["note"],
            "verdict": e["verdict"], "elsewhere": bool(e.get("elsewhere"))}


def load_registry(path: pathlib.Path | None = None) -> dict:
    p = path or _registry_path()
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError:
        return {"version": 1, "entries": {}}
    except (OSError, ValueError):
        try:  # keep what could not be read: history is the point of this file
            os.replace(p, p.with_name(p.name + ".corrupt"))
        except OSError:
            pass
        return {"version": 1, "entries": {}}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
        return {"version": 1, "entries": {}}
    return data


def save_registry(reg: dict, path: pathlib.Path | None = None) -> bool:
    p = path or _registry_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(reg, indent=1, sort_keys=True) + "\n")
        os.replace(tmp, p)
    except OSError:
        return False
    return True


def forget_ignored(reg: dict, prefixes: list[str]) -> None:
    """Drop launchd ids the ignore list covers now: a vendor agent seen before the list grew is not a
    task that vanished."""
    book = reg.get("entries") or {}
    for eid in [k for k in book if k.startswith("launchd:") and _ignored(k.split(":", 1)[1], prefixes)]:
        del book[eid]


def apply_registry(entries: list[dict], reg: dict, now: dt.datetime) -> list[dict]:
    """Fold the current entries into the registry (mutated) and return the full list: the current
    entries with first_seen/last_seen, plus a VANISHED entry for every id seen before and absent now.
    Entries gone for more than 30 days leave the registry; cloud routines stay as last known."""
    book = reg.setdefault("entries", {})
    current = {e["id"] for e in entries}
    for e in entries:
        rec = book.get(e["id"]) or {"first_seen": _iso(now)}
        rec["last_seen"] = _iso(now)
        rec["snapshot"] = _snapshot(e)
        book[e["id"]] = rec
        e["first_seen"], e["last_seen"] = rec["first_seen"], rec["last_seen"]
    out = list(entries)
    for eid in sorted(set(book) - current):
        rec = book[eid]
        snap = rec.get("snapshot") or {}
        last_seen = _parse_ts(rec.get("last_seen"))
        if snap.get("source") == "cloud" and snap.get("verdict") != "VANISHED":
            # Transcripts age out; the routine was never seen deleted. Keep it as last known.
            kept = _from_snapshot(eid, rec, snap, verdict="UNKNOWN",
                                  note=snap.get("note") or f"last known as of {_date(last_seen)}")
            out.append(kept)
            continue
        if last_seen is None or now - last_seen > VANISHED_KEEP:
            del book[eid]
            continue
        out.append(_from_snapshot(eid, rec, snap, verdict="VANISHED",
                                  note=f"last seen {_date(last_seen)} (first seen {_date(_parse_ts(rec.get('first_seen')))}); "
                                       f"it is no longer on this machine"))
    return out


def _from_snapshot(eid: str, rec: dict, snap: dict, *, verdict: str, note: str) -> dict:
    src, _, key = eid.partition(":")
    exp = snap.get("expected_every_s")
    e = entry(snap.get("source") or src, key, snap.get("name") or key, cadence=snap.get("cadence") or "",
              expected_every=dt.timedelta(seconds=exp) if exp else None, enabled=snap.get("enabled", True),
              last_run=_parse_ts(snap.get("last_run")), last_exit=snap.get("last_exit"),
              definition=snap.get("definition") or "", note=note, verdict=verdict, run_known=False)
    e["id"] = eid
    e["first_seen"], e["last_seen"] = rec.get("first_seen"), rec.get("last_seen")
    return e


# --- output ------------------------------------------------------------------------------------

def is_problem(e: dict) -> bool:
    return e["verdict"] in PROBLEMS


def _sort_key(e: dict):
    return (SEVERITY.index(e["verdict"]) if e["verdict"] in SEVERITY else len(SEVERITY), e["name"].lower())


def line_of(e: dict, now: dt.datetime) -> str:
    if e.get("last_run_text"):
        when = f"last run: {e['last_run_text']}"
    elif e.get("last_run") is not None:
        when = f"last run {relative(e['last_run'], now)} ({_date(e['last_run'])})"
    elif e.get("run_known", True) and e["verdict"] not in ("UNREGISTERED", "VANISHED", "UNKNOWN"):
        when = "never ran"
    else:
        when = "no run record"
    head = f"  {e['verdict']:<18} {e['name']} — " + "; ".join(b for b in (e["cadence"], when) if b)
    return head + (f"\n  {'':<18} {e['note']}" if e.get("note") else "")


def render_text(entries: list[dict], now: dt.datetime, *, show_all: bool = False, cron_n: int = 0) -> str:
    probs = [e for e in entries if is_problem(e)]
    ok = [e for e in entries if e["verdict"] == "OK"]
    others = [e for e in entries if not is_problem(e) and e["verdict"] != "OK"]
    out = [f"scheduled tasks as of {_local(now):%Y-%m-%d %H:%M}: {len(probs)} need attention, "
           f"{len(others)} other, {len(ok)} ok"]
    shown = sorted([e for e in entries if show_all or e["verdict"] != "OK"], key=_sort_key)
    for src in SOURCES:
        group = [e for e in shown if e["source"] == src]
        if not group:
            continue
        out += ["", src]
        out += [line_of(e, now) for e in group]
    if not show_all and ok:
        out += ["", f"{len(ok)} ok (--all lists them)"]
    if not entries:
        out += ["", "no scheduled tasks found"]
    if cron_n:
        out += ["", f"note: {cron_n} session cron{'s were' if cron_n != 1 else ' was'} created in the last 30 "
                    f"days; they die with the session and are not listed"]
    return "\n".join(out) + "\n"


def to_json(e: dict) -> dict:
    exp = e.get("expected_every")
    return {"id": e["id"], "source": e["source"], "name": e["name"], "cadence": e["cadence"],
            "expected_every_s": int(exp.total_seconds()) if exp else None, "enabled": e["enabled"],
            "last_run": _iso(e.get("last_run")), "last_exit": e.get("last_exit"), "definition": e["definition"],
            "note": e["note"], "verdict": e["verdict"], "problem": is_problem(e),
            "first_seen": e.get("first_seen"), "last_seen": e.get("last_seen")}


def problem_lines(entries: list[dict]) -> list[tuple[str, str]]:
    """(key, text) for the banner. The tasks `teyla routines` already reports are left out."""
    out = []
    for e in sorted((x for x in entries if is_problem(x) and not x.get("elsewhere")), key=_sort_key):
        text = f"scheduled task {e['name']} {e['verdict']}" + (f": {_short(e['note'], 70)}" if e.get("note") else "")
        out.append((f"schedule|{e['id']}|{e['verdict']}", text))
    return out


def write_problems(entries: list[dict], path: pathlib.Path | None = None) -> pathlib.Path | None:
    p = path or problems_path()
    items = problem_lines(entries)
    try:
        if items:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text("".join(f"{_clean(k)}\t{_clean(t)}\n" for k, t in items))
            os.replace(tmp, p)
            return p
        p.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def _clean(s: str) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(s))


# --- command -----------------------------------------------------------------------------------

def run(*, allow_network: bool | None = None, now: dt.datetime | None = None, **kw) -> tuple[list[dict], int]:
    """collect() folded into the registry, which is saved. Returns (all entries, session-cron count)."""
    now = now or _now()
    entries, cron_n = collect(now, allow_network=allow_network, **kw)
    reg = load_registry()
    forget_ignored(reg, ignore_prefixes())
    full = apply_registry(entries, reg, now)
    save_registry(reg)
    return full, cron_n


def cmd_schedules(args) -> int:
    now = _now()
    entries, cron_n = run(now=now)
    if args.quiet:
        write_problems(entries)
    elif args.json:
        order = sorted(entries, key=lambda e: (SOURCES.index(e["source"]) if e["source"] in SOURCES else 99,
                                               _sort_key(e)))
        print(json.dumps([to_json(e) for e in order], indent=2))
    else:
        print(render_text(entries, now, show_all=args.all, cron_n=cron_n), end="")
    return 1 if any(is_problem(e) for e in entries) else 0


def register(sp):
    q = sp.add_parser("schedules", help="every scheduled task on this machine (Claude desktop, launchd, cloud "
                                        "routines, GitHub, teyla.toml): did it run, what vanished")
    q.set_defaults(fn=cmd_schedules)
    q.add_argument("--json", action="store_true", help="the full list as JSON")
    q.add_argument("--quiet", action="store_true",
                   help="print nothing; update the registry and ~/.teyla/schedules.problems (the daily routine)")
    q.add_argument("--all", action="store_true", help="also list the tasks that are OK")
    q.add_argument("--allow-network", action="store_true",
                   help="safe mode: let gh look up the last run of each GitHub workflow this once")
    return q

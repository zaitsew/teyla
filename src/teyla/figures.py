"""The numbers behind the first screen: bare `teyla` and `teyla today`.

Computing spend means parsing every session of two weeks, which takes from 5 s to a minute. The
welcome has a budget of 1.5 s, so it never computes: it reads `~/.teyla/first-screen.json` and, when
that file is older than `CACHE_TTL_S`, starts one detached `teyla today --refresh-cache` and shows
what it has. `teyla today` writes the same file whenever it computes.

    {"version": 1, "at": <epoch>, "spend": {"this_week": usd, "last_week": usd, "at": <epoch>} | null,
     "questions": {"waiting": n, "at": <epoch>} | null}

What each figure is, and how stale it can be:

    spend, last 7 days and the 7 before   cache; refreshed in the background when older than 10 minutes;
                                          shown with its age when older than 6 hours; dropped after 7 days
    questions waiting                     cache, same rules (`teyla asks` default list: open, not muted)
    notes in the Inbox                    read live: one small file
    sessions on this machine              read live: is there one session file in any harness's store

`teyla start` (the diagnosis, about 60 s on a big machine) is never run from here. It leaves its
result in `~/.teyla/start-report.json` through `record_start`, and the first screen reads that:

    {"version": 1, "at": <epoch>, "finished": bool, "days": 30, "total_usd": usd, "sessions": n,
     "offers": [{"id": "O1", "title": ..., "applies": bool, "saving_usd_month": {"low": x, "high": y} | null}]}

`finished` is true once the person went through the offers (applied or declined each one). Whether an
offer was applied comes from `~/.teyla/changes.jsonl`, which `teyla apply` writes. This module reads
both files as plain JSON and imports neither `start` nor `diagnose`, so it works before they exist and
after they change.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

CACHE_TTL_S = 10 * 60            # older than this: the welcome starts a background refresh
SHOW_AGE_S = 6 * 3600            # older than this: the figure is shown with "as of 2d ago"
DROP_AGE_S = 7 * 86400           # older than this: the figure is not shown at all
LOCK_STALE_S = 5 * 60            # a refresh that started longer ago than this is presumed dead
WEEK_DAYS = 7


def home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TEYLA_HOME") or (pathlib.Path.home() / ".teyla")).expanduser()


def cache_path() -> pathlib.Path:
    return home() / "first-screen.json"


def start_report_path() -> pathlib.Path:
    return home() / "start-report.json"


def changes_path() -> pathlib.Path:
    return home() / "changes.jsonl"


def now() -> float:
    return time.time()


# --- small files --------------------------------------------------------------------------------

def _read_json(path: pathlib.Path) -> dict | None:
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _write_json(path: pathlib.Path, d: dict) -> None:
    from . import config
    config.private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(d, fh)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- sessions on this machine ------------------------------------------------------------------

def _has_file(root: str, depth: int) -> bool:
    """True when `root` holds a regular file at most `depth` directories down. Stops at the first one."""
    try:
        with os.scandir(root) as it:
            for e in it:
                if e.is_file(follow_symlinks=False):
                    return True
                if depth > 0 and e.is_dir(follow_symlinks=False) and _has_file(e.path, depth - 1):
                    return True
    except OSError:
        pass
    return False


def has_sessions() -> bool:
    """True when any harness's session store holds a session. One directory walk that stops at the
    first hit: it must cost milliseconds, not the minutes a full load takes."""
    from .adapters import claude_code, codex, cursor, grok, hermes
    return (_has_file(claude_code.DEFAULT_ROOT, 1)
            or _has_file(codex.DEFAULT_ROOT, 4) or _has_file(codex.DEFAULT_ARCHIVE_ROOT, 1)
            or _has_file(grok.DEFAULT_ROOT, 2)
            or os.path.isfile(cursor.DEFAULT_ROOT) or os.path.isfile(hermes.DEFAULT_ROOT))


# --- computed figures --------------------------------------------------------------------------

def compute_spend(at: float | None = None, rows=None) -> dict:
    """Spend of the last 7 days and of the 7 before, at API list price, every harness.
    Slow (it parses the sessions): called from `teyla today` and the background refresh only."""
    from . import spend
    at = now() if at is None else at
    rows = spend.session_rows(2 * WEEK_DAYS) if rows is None else rows
    days = spend.by_day(2 * WEEK_DAYS, rows)          # oldest first, 14 local days ending today
    last, this = days[:WEEK_DAYS], days[WEEK_DAYS:]
    return {"this_week": round(sum(d["total_usd"] for d in this), 2),
            "last_week": round(sum(d["total_usd"] for d in last), 2), "at": at}


def waiting_questions(items=None) -> list:
    """The asks `teyla asks` lists by default: open, and not muted in a parked product."""
    from . import asks, registry
    if items is None:
        items = asks.collect(asks.DEFAULT_DAYS, fetch=False)
    reg = registry.load()
    return [a for a in items if a.status == "open" and not asks.is_muted(a, reg)]


def read_cache() -> dict:
    return _read_json(cache_path()) or {}


def write_cache(**parts) -> None:
    """Merge `parts` ({"spend": ..., "questions": ...}) into the cache. Never raises: a cache that
    cannot be written only means the next welcome shows fewer numbers."""
    try:
        d = read_cache()
        d.update(parts)
        d.update(version=1, at=now())
        _write_json(cache_path(), d)
    except (OSError, ValueError):
        pass


def refresh(at: float | None = None) -> None:
    """Compute every cached figure and store it. The body of `teyla today --refresh-cache`. A figure
    that cannot be computed is left as it was; the others are still stored."""
    at = now() if at is None else at
    parts = {}
    try:
        parts["spend"] = compute_spend(at)
    except Exception:  # noqa: BLE001 — an unreadable store leaves the old figure
        pass
    try:
        parts["questions"] = {"waiting": len(waiting_questions()), "at": at}
    except Exception:  # noqa: BLE001
        pass
    if parts:
        write_cache(**parts)


def _lock() -> pathlib.Path:
    return home() / "first-screen.lock"


def spawn_refresh() -> bool:
    """Start one detached refresh unless one started in the last 5 minutes. True when it started."""
    lock = _lock()
    try:
        if lock.exists() and now() - lock.stat().st_mtime < LOCK_STALE_S:
            return False
        from . import config
        config.private_dir(lock.parent)
        lock.touch()
        subprocess.Popen([sys.executable, "-m", "teyla", "today", "--refresh-cache"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def release_lock() -> None:
    try:
        _lock().unlink()
    except OSError:
        pass


def cached(kind: str, at: float | None = None) -> tuple[dict | None, float | None]:
    """(figure, age in seconds) from the cache, or (None, None) when there is none or it is older than
    DROP_AGE_S. The caller decides whether the age asks for a refresh (`stale`)."""
    at = now() if at is None else at
    d = read_cache().get(kind)
    stamp = d.get("at") if isinstance(d, dict) else None
    if not isinstance(stamp, (int, float)):
        return None, None
    age = max(0.0, at - stamp)
    return (None, None) if age > DROP_AGE_S else (d, age)


def stale(age: float | None) -> bool:
    return age is None or age > CACHE_TTL_S


def age_note(age: float | None) -> str:
    """"" for a fresh figure, else "as of 3h ago"."""
    if age is None or age < SHOW_AGE_S:
        return ""
    from .asks import fmt_age
    return f"as of {fmt_age(age)} ago"


def change_pct(this: float, last: float) -> int | None:
    """The change from last week to this one in whole percent; None when last week cost nothing."""
    return round((this - last) / last * 100) if last > 0 else None


# --- the diagnosis, through files --------------------------------------------------------------

def start_available() -> bool:
    """True when this version of Teyla has `teyla start`."""
    return importlib.util.find_spec("teyla.start") is not None


def record_start(payload: dict, finished: bool) -> None:
    """Called by `teyla start` with its payload ({diagnosis, offers, ...}), so the first screen can quote
    it without running it again. Never raises."""
    try:
        diag, offers = payload.get("diagnosis") or {}, payload.get("offers") or []
        prev = _read_json(start_report_path()) or {}
        _write_json(start_report_path(), {
            "version": 1, "at": now(), "finished": bool(finished or prev.get("finished")),
            "days": diag.get("days"), "total_usd": diag.get("total_usd"), "sessions": diag.get("sessions"),
            "offers": [{"id": o.get("id"), "title": o.get("title"), "applies": bool(o.get("applies")),
                        "saving_usd_month": o.get("saving_usd_month")} for o in offers if isinstance(o, dict)]})
    except (OSError, ValueError, TypeError):
        pass


def start_report() -> dict:
    return _read_json(start_report_path()) or {}


def _changes() -> list[dict]:
    try:
        lines = changes_path().read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def applied_offers() -> set[str]:
    """Offer ids with a change that is still in force (made, and not undone since)."""
    log = _changes()
    undone = {o.get("undo_of") for o in log if "undo_of" in o}
    return {str(o["offer"]).upper() for o in log
            if "undo_of" not in o and o.get("offer") and o.get("id") not in undone}


def onboarded() -> bool:
    """True once the person has applied an offer or gone through the offers of a finished `teyla start`."""
    return bool(_changes()) or bool(start_report().get("finished"))


def open_offers() -> list[dict]:
    """The offers `teyla start` found that apply and are not in force now, biggest saving first.
    Each: {id, title, low, high}. An offer without a dollar figure has 0 and comes last, in its own order."""
    rep = start_report()
    done = applied_offers()
    out = []
    for o in rep.get("offers") or []:
        if not isinstance(o, dict) or not o.get("applies") or not o.get("id") or str(o["id"]).upper() in done:
            continue
        s = o.get("saving_usd_month") if isinstance(o.get("saving_usd_month"), dict) else None
        try:
            low, high = (float(s["low"]), float(s["high"])) if s else (0.0, 0.0)
        except (KeyError, TypeError, ValueError):
            low = high = 0.0
        out.append({"id": str(o["id"]), "title": str(o.get("title") or o["id"]), "low": low, "high": high})
    out.sort(key=lambda o: -o["high"])
    return out

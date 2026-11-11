"""GitHub contributions as a second activity graph (`teyla growth activity --github`, the iPhone widget, the Telegram widget).

The numbers are GitHub's own contribution calendar for the signed-in `gh` account: the grid on the profile page, with
commits, pull requests, reviews and issues, and private contributions when the profile counts them. One
`gh api graphql` call (docs/PRIVACY.md row 59) asks for the days from the first Monday of the window to today. The
answer is cached in `~/.teyla/github-activity.json` for CACHE_S seconds, so the relay pass and the Telegram heartbeat
never ask more than once in that time. With no `gh`, a failed call or safe mode on, the last cache serves, however old,
and `at` says when it was taken. With no cache at all the graph is None.

The graph has the shape of `growth.activity` (contract version 1) with `source: "github"`. Levels are GitHub's own
quartiles (`contributionLevel`), not recounted here.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import shutil
import subprocess
import time
from typing import Callable

from . import net
from .control.state import home

CACHE_S = 600
CALL_TIMEOUT_S = 20
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
QUERY = ("query($from:DateTime!,$to:DateTime!){viewer{login contributionsCollection(from:$from,to:$to)"
         "{contributionCalendar{weeks{contributionDays{date contributionCount contributionLevel}}}}}}")

Runner = Callable[[list[str]], tuple[int, str, str]]


def cache_path() -> pathlib.Path:
    return home() / "github-activity.json"


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=CALL_TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return r.returncode, r.stdout, r.stderr


def window_start(today: str, weeks: int) -> str:
    t = _dt.date.fromisoformat(today)
    return (t - _dt.timedelta(days=t.weekday() + 7 * (weeks - 1))).isoformat()


def parse(out: str) -> list[dict] | None:
    """The days of a `gh api graphql` answer, oldest first: {day, count, level}. None when the answer is not one."""
    try:
        cal = json.loads(out)["data"]["viewer"]["contributionsCollection"]["contributionCalendar"]
        raw = [d for w in cal["weeks"] for d in w["contributionDays"]]
    except (ValueError, KeyError, TypeError):
        return None
    days = []
    for d in raw:
        if not isinstance(d, dict) or not isinstance(d.get("date"), str) or type(d.get("contributionCount")) is not int:
            continue
        days.append({"day": d["date"], "count": max(d["contributionCount"], 0),
                     "level": LEVELS.get(d.get("contributionLevel"), 0) if d["contributionCount"] > 0 else 0})
    days.sort(key=lambda d: d["day"])
    return days


def fetch(today: str, weeks: int = 53, runner: Runner | None = None) -> list[dict] | None:
    """One call for the days from the window's first Monday to `today`. None on any failure."""
    start = window_start(today, weeks)
    cmd = ["gh", "api", "graphql", "-f", f"query={QUERY}",
           "-f", f"from={start}T00:00:00Z", "-f", f"to={today}T23:59:59Z"]
    code, out, _err = (runner or _run)(cmd)
    return parse(out) if code == 0 else None


def _load() -> dict:
    try:
        c = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return {}
    return c if isinstance(c, dict) and isinstance(c.get("days"), list) else {}


def _save(c: dict) -> None:
    p = cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(c))
    os.replace(tmp, p)


def days(today: str, weeks: int = 53, now: float | None = None, runner: Runner | None = None,
         max_age: float = CACHE_S) -> tuple[list[dict], float] | None:
    """The cached days and when they were fetched; a fresh fetch first when the cache is older than `max_age`, covers
    less than the window, or is from another day, and the network may be used. None when there is nothing at all."""
    now = time.time() if now is None else now
    c = _load()
    start = window_start(today, weeks)
    stale = (now - float(c.get("at") or 0) > max_age or c.get("today") != today or str(c.get("start") or "9") > start)
    if stale and (runner is not None or shutil.which("gh")) and net.allowed():
        w = max(weeks, int(c.get("weeks") or 0), 17)
        got = fetch(today, w, runner)
        if got:
            c = {"at": now, "today": today, "start": window_start(today, w), "weeks": w, "days": got}
            _save(c)
    if not c.get("days"):
        return None
    return [d for d in c["days"] if start <= d.get("day", "") <= today], float(c.get("at") or 0)


def graph(day_rows: list[dict], today: str, weeks: int, at: float = 0.0) -> dict:
    """The `growth.activity` contract for these days: every day of the window, missing days as 0."""
    t = _dt.date.fromisoformat(today)
    start = _dt.date.fromisoformat(window_start(today, weeks))
    by_day = {d["day"]: d for d in day_rows}
    days_out, d = [], start
    while d <= t:
        x = by_day.get(d.isoformat(), {})
        days_out.append({"day": d.isoformat(), "count": int(x.get("count", 0)), "level": int(x.get("level", 0)), "kinds": {}})
        d += _dt.timedelta(days=1)
    longest = run = 0
    for x in days_out:
        run = run + 1 if x["count"] else 0
        longest = max(longest, run)
    streak, i = 0, len(days_out) - 1
    if i >= 0 and not days_out[i]["count"]:
        i -= 1
    while i >= 0 and days_out[i]["count"]:
        streak += 1
        i -= 1
    monday = (t - _dt.timedelta(days=t.weekday())).isoformat()
    return {"version": 1, "source": "github", "today": today, "weeks": weeks, "start": start.isoformat(),
            "days": days_out, "total": sum(x["count"] for x in days_out), "today_count": by_day.get(today, {}).get("count", 0),
            "week_count": sum(x["count"] for x in days_out if x["day"] >= monday), "streak": streak, "longest": longest,
            "by_kind": {}, "outcomes": {"meetings": 0, "responses": 0}, "claimed": 0, "kinds": [],
            "at": int(at)}


def activity(today: str, weeks: int = 53, now: float | None = None, runner: Runner | None = None,
             max_age: float = CACHE_S) -> dict | None:
    got = days(today, weeks, now, runner, max_age)
    return graph(got[0], today, weeks, got[1]) if got else None

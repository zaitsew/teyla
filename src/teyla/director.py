"""`teyla digest director`: the weekly director brief, one markdown file the director session reads.

    teyla digest director                  write ~/.teyla/director/<ISO week>.md and print its path
    teyla digest director --out FILE       write that file instead
    teyla digest director --stdout         print the brief, write nothing
    teyla digest director --json           print the assembled facts as JSON, write nothing
    teyla digest director --quiet          write the file, print nothing (the Monday routine)

The brief joins three existing views: the hard dates and outcome scoreboard (`teyla today score`), the sprint slots
(`teyla brief slots`) and the questions past 14 days (`teyla asks expire`, dry run). It reuses their `snapshot` and
`candidates` functions and decides nothing. The only file it writes is the brief. It makes no network call.
An input that raises renders as `not_measured: <ExceptionName>`; the other sections still render.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import time

from . import config, expiry, gtm, scoreboard, slots

VERSION = 1
EXPIRY_DAYS = 14
ROWS = 10          # question rows shown
DECISIONS = 5      # oldest open decisions shown (the scoreboard keeps its three oldest)
SLOT_ROWS = 6
BUILD_ROWS = 8
NM = scoreboard.NOT_MEASURED

METRICS = (("posts_published", "Posts published"), ("sale_attempts", "Sale attempts"), ("conversations", "Conversations"),
           ("first_value", "First value"), ("open_decisions", "Open decisions"), ("builds_to_try", "Builds to try"))


def _now() -> float:
    return time.time()


def _iso(now: float) -> str:
    return _dt.datetime.fromtimestamp(now, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_path(week: str) -> pathlib.Path:
    return config.TEYLA_DIR / "director" / f"{week}.md"


def _guard(fn):
    """(value, None) or (None, ExceptionName): one broken input never stops the brief."""
    try:
        return fn(), None
    except Exception as e:  # noqa: BLE001 — each section reports its own failure
        return None, type(e).__name__


def assemble(now: float | None = None) -> dict:
    """The facts, read-only. A failed input is None, and `errors` names the exception."""
    now = _now() if now is None else now
    day = gtm.day_of(now)
    week = gtm.week_of(day)
    mon, sun = gtm.week_range(week)
    parts = {"hard_dates": _guard(lambda: scoreboard.hard_dates(_dt.date.fromisoformat(day))),
             "outcomes": _guard(lambda: scoreboard.snapshot(now)["metrics"]),
             "slots": _guard(lambda: slots.snapshot(now)),
             "expiry": _guard(lambda: expiry.candidates(days=EXPIRY_DAYS, now=now))}   # dry run: never `expiry.apply`
    out = {"version": VERSION, "generated": _iso(now), "week": week, "start": mon, "end": sun}
    errors: dict[str, str] = {}
    for name, (value, err) in parts.items():
        out[name] = value
        if err:
            errors[name] = err
    out["errors"] = errors
    return out


def _cell(text) -> str:
    return " ".join(str(text).split()).replace("|", "/")


def _clip(text, n: int) -> str:
    return scoreboard._clip(text, n)


def _age(days) -> str:
    return "?" if days is None else "today" if days == 0 else f"{days}d"


def _failed(d: dict, name: str) -> str | None:
    return f"{NM}: {d['errors'][name]}" if name in d["errors"] else None


def _detail(m: dict) -> str:
    """The value cell of a measured metric, with the extra counts that carry the point."""
    v = m["value"]
    if isinstance(m.get("breakdown"), dict):
        v = f"{v} ({', '.join(f'{k} {n}' for k, n in m['breakdown'].items())})"
    elif "replies" in m:
        v = f"{v} ({m['replies']} replied)"
    elif isinstance(m.get("by_age"), dict):
        v = f"{v} (over 14 days: {m.get('over_14_days', 0)})"
    return str(v)


def render(d: dict) -> str:
    L = [f"# Director brief — {d['week']} ({d['start']} to {d['end']})", "",
         f"Generated {d['generated']}. Read this, then name the next two sprints. Nothing here was changed.", ""]
    # hard dates
    L += ["## Hard dates", ""]
    if (msg := _failed(d, "hard_dates")):
        L.append(msg)
    elif not d["hard_dates"]:
        L.append("None set. Add `name = \"YYYY-MM-DD\"` under `[dates]` in ~/.teyla/config.toml.")
    else:
        L += [f"- {h['name']}: {h['date']}, {h['days_left']} days left" for h in d["hard_dates"]]
    # outcomes
    L += ["", "## Outcomes this week", ""]
    if (msg := _failed(d, "outcomes")):
        L.append(msg)
    else:
        L += ["| metric | value | source |", "|---|---|---|"]
        for key, label in METRICS:
            m = d["outcomes"][key]
            if m["value"] == NM:
                L.append(f"| {label} | {NM} | {_cell(m.get('reason') or 'no source')} |")
            else:
                L.append(f"| {label} | {_cell(_detail(m))} | {_cell(m.get('source') or '-')} |")
    # slots
    L += ["", "## Sprint slots", ""]
    if (msg := _failed(d, "slots")):
        L.append(msg)
    else:
        s = d["slots"]
        L.append(f"{s['in_flight']} of {s['limit']} in flight")
        if not s["slots"]:
            L.append("No sprint contract is open.")
        for r in s["slots"][:SLOT_ROWS]:
            L.append(f"- {r['product']}: started {_age(r['age_days'])} ago"
                     f"{', overdue' if r['overdue'] else ''}, waits at {_clip(r['waits_at']['text'], 80)}")
        if len(s["slots"]) > SLOT_ROWS:
            L.append(f"- and {len(s['slots']) - SLOT_ROWS} more (`teyla brief slots`)")
        if s["over_limit"]:
            L.append(f"WARN: {s['in_flight']} sprints in flight; the limit is {s['limit']}.")
        if s["no_contract"]:
            L.append("Active without a contract: " + ", ".join(r["product"] for r in s["no_contract"][:SLOT_ROWS]))
    # decisions and builds come from the scoreboard
    L += ["", "## Open decisions", ""]
    if (msg := _failed(d, "outcomes")):
        L.append(msg)
    else:
        od = d["outcomes"]["open_decisions"]
        if od["value"] == NM:
            L.append(f"{NM}: {od.get('reason', 'no source')}")
        else:
            L.append(f"{od['value']} waiting on you, {od.get('over_14_days', 0)} older than 14 days.")
            L += [f"- {r['product']}, {_age(r['age_days'])}: {_clip(r['title'], 80)}" for r in (od.get("oldest") or [])[:DECISIONS]]
        dp = od.get("design_picks") or {}
        if dp.get("value") == NM:
            L.append(f"Design picks waiting: {NM}: {dp.get('reason', 'no source')}")
        else:
            L.append(f"Design picks waiting: {dp.get('value', 0)}")
            L += [f"- {c['product']}, {_age(c.get('age_days'))}: {_clip(c['title'], 80)}" for c in (dp.get("cards") or [])[:DECISIONS]]
    L += ["", "## Builds to try", ""]
    if (msg := _failed(d, "outcomes")):
        L.append(msg)
    else:
        b = d["outcomes"]["builds_to_try"]
        if b["value"] == NM:
            L.append(f"{NM}: {b.get('reason', 'no source')}")
        else:
            L.append(f"{b['value']} build(s) uploaded in the last 7 days and installable.")
            L += [f"- {x['product']} {x['platform']} build {x['build']}, uploaded {x['uploaded']}" for x in b["builds"][:BUILD_ROWS]]
    # questions past 14 days
    L += ["", f"## Questions past {EXPIRY_DAYS} days", ""]
    if (msg := _failed(d, "expiry")):
        L.append(msg)
    else:
        q = d["expiry"]
        n = {o: sum(1 for i in q if i["outcome"] == o) for o in ("default", "drop", "keep")}
        L.append(f"{len(q)} open: " + ", ".join(f"{n[o]} {o}" for o in n))
        for i in q[:ROWS]:
            default = f"{_clip(i['default'], 50)} ({i['default_source']})" if i["default"] else "-"
            L.append(f"- {i['id']}, {i['product']}, {_age(i['age_days'])}, {i['outcome']}, default: {default}")
        if len(q) > ROWS:
            L.append(f"- and {len(q) - ROWS} more (`teyla asks expire`)")
    L.append("Closing them needs an explicit yes; this brief changes nothing.")
    # next two sprints
    L += ["", "## Next two sprints", "", "1. …", "2. …", "",
          "Name each with its gate; open it with `teyla brief <product> --goal \"...\" --gate \"...\" --usd N --hours N`."]
    return "\n".join(L) + "\n"


def cmd_director(args) -> int:
    d = assemble()
    if getattr(args, "json", False):
        print(json.dumps(d, indent=1))
        return 0
    text = render(d)
    if getattr(args, "stdout", False):
        print(text, end="")
        return 0
    path = pathlib.Path(args.out).expanduser() if getattr(args, "out", None) else default_path(d["week"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if not getattr(args, "quiet", False):
        print(f"wrote {path}")
    return 0

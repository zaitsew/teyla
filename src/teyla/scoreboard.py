"""`teyla today score`: the outcome scoreboard. Outcomes are the headline, not agent output.

    teyla today score               one screen of about 20 lines
    teyla today score --json        the same facts as JSON
    teyla today score --refresh     run the live `teyla testflight` check first (network), then show

Six metrics for the ISO week (Monday to Sunday, local date). Each is `{"value": <int or "not_measured">,
"source": ..., "reason": <only when not_measured>, ...extra}`. A number with no source is `not_measured`.

    posts_published   posts the owner recorded this week (growth ledger)
    sale_attempts     posts, marketing and ICP meetings this week (growth ledger, `growth.tally`)
    conversations     calls, meetings and ICP meetings logged this week; `replies` is an extra field
    first_value       installs of a focus product that finished its first-value task (usage capture)
    open_decisions    open questions waiting on the owner, by age; `design_picks` lists open design cards
    builds_to_try     builds uploaded in the last 7 days that the tester can install (testflight cache)

It writes nothing and makes no network call. `--refresh` is the one exception: it runs the testflight check
(`net.gate` applies) and stores its answer in `~/.teyla/testflight.json`, the file `builds_to_try` reads.
`[dates]` in `~/.teyla/config.toml` (`name = "YYYY-MM-DD"`) adds a days-left line per goal.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import time

from . import asks, config, design_cycle, gtm, growth, net, registry, testflight, usage
from .ui import Style

VERSION = 1
NOT_MEASURED = "not_measured"
BUILD_DAYS = 7
CACHE_STALE_S = 48 * 3600
OPEN_SHOWN = 3
CLIP = 56


def _now() -> float:
    return time.time()


def _measured(value, source: str, **extra) -> dict:
    return {"value": value, "source": source, **extra}


def _missing(reason: str, source: str = "", **extra) -> dict:
    return {"value": NOT_MEASURED, "source": source, "reason": reason, **extra}


def _clip(text, n: int = CLIP) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= n else one[:n - 1].rstrip() + "…"


def _iso(now: float) -> str:
    return _dt.datetime.fromtimestamp(now, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the ledger metrics --------------------------------------------------------------------------

def ledger_metrics(now: float) -> dict:
    day = gtm.day_of(now)
    week = gtm.week_of(day)
    mon, sun = gtm.week_range(week)
    store = growth.Store()
    if not store.ledger_path.exists():
        why = "no growth ledger yet: it starts with `teyla growth published ID URL` or `teyla growth log`"
        return {"posts_published": _missing(why, "growth ledger"),
                "sale_attempts": _missing(why, "growth ledger"),
                "conversations": _missing(why, "growth ledger")}
    rows = [r for r in store.ledger() if mon <= str(r.get("day") or "") <= sun]
    doc = gtm.ledger_source(rows, {}, day, week, now)
    counts = doc["counts"]
    t = growth.tally([dict(r, product=r.get("product") or "-") for r in rows],
                     {r.get("product") or "-" for r in rows})
    posts = sum(x["posts"] for x in t.values())
    marketing = sum(x["marketing"] for x in t.values())
    icp = sum(x["icp_meetings"] for x in t.values())
    return {
        "posts_published": _measured(counts.get("posted", 0), "growth ledger"),
        "sale_attempts": _measured(posts + marketing + icp, "growth ledger",
                                   breakdown={"posts": posts, "marketing": marketing, "icp_meetings": icp},
                                   claimed_by_agents=sum(x["claimed"] for x in t.values())),
        "conversations": _measured(counts.get("conversation", 0), "growth ledger",
                                   replies=counts.get("replied", 0),
                                   with_next_step={"value": NOT_MEASURED, "source": "",
                                                   "reason": "the ledger stores no owner or next-step date per conversation"}),
    }


# --- first value ---------------------------------------------------------------------------------

def _first_value_row(pid: str, p: dict) -> dict:
    task = str(p.get("first_value") or "")
    if not task:
        return {"product": pid, **_missing(f"no first-value task set: `teyla product set {pid} first_value=<task>`")}
    batches = usage.load(pid)
    if not batches:
        return {"product": pid, "task": task, **_missing("no usage captured", "usage capture")}
    installs = set()
    for b in batches:
        for e in b.get("events") or []:
            if isinstance(e, dict) and e.get("k") == "task" and e.get("id") == task and e.get("r") == "success":
                installs.add(b["install"])
    return {"product": pid, "task": task, "value": len(installs),
            "source": f"usage capture, task {task}, to date (not this week): installs (a device), not people; "
                      "a batch carries an install id, no tester id"}


def first_value_metric() -> dict:
    reg = registry.load(strict=False)
    focus = [(pid, p) for pid, p in reg["product"].items() if p.get("focus")]
    if not focus:
        return _missing("no focus product: set one with `teyla product core <id>`", "registry")
    rows = [_first_value_row(pid, p) for pid, p in focus]
    done = [r for r in rows if r["value"] != NOT_MEASURED]
    if not done:
        reasons = [f"{r['product']}: {r['reason']}" for r in rows]
        more = f" (+{len(reasons) - 2} more)" if len(reasons) > 2 else ""
        return _missing("; ".join(reasons[:2]) + more, "usage capture", products=rows)
    return _measured(sum(r["value"] for r in done),
                     "usage capture, to date (not this week): installs (a device) that finished the first-value task, not people",
                     measured_products=len(done), focus_products=len(rows), products=rows)


# --- decisions -----------------------------------------------------------------------------------

def _card_age_days(c: dict, now: float):
    try:
        mtime = (design_cycle.folder(c["repo"], c["decision"]) / "options.yaml").stat().st_mtime
    except OSError:
        return NOT_MEASURED
    return max(0, int((now - mtime) // 86400))


def design_picks_metric(now: float) -> dict:
    try:
        cards = design_cycle.open_cards()
    except Exception as e:  # noqa: BLE001 — a broken card store leaves this line unmeasured
        return _missing(f"could not read the design cards ({type(e).__name__})", "design cards")
    rows = [{"product": c["product"], "decision": c["decision"], "title": c["title"],
             "age_days": _card_age_days(c, now)} for c in cards]
    return _measured(len(rows), "design cards", cards=rows)


def open_decisions_metric(now: float) -> dict:
    decision_minutes = _missing("Teyla does not record how long the owner spends deciding")
    try:
        reg = registry.load(strict=False)
        items = asks.collect(now=now, fetch=False, st=asks.load_state())   # `st` given: nothing is saved
    except Exception as e:  # noqa: BLE001
        return _missing(f"could not read the questions ({type(e).__name__})", "asks",
                        design_picks=design_picks_metric(now), decision_minutes=decision_minutes)
    waiting = [a for a in items if a.status == "open" and a.kind not in ("reminder", "report")
               and not asks.is_muted(a, reg)]
    ages = sorted(((a, max(0, int((now - a.when) // 86400))) for a in waiting), key=lambda x: -x[1])
    by_age = {"0-7": 0, "8-14": 0, "15+": 0}
    for _, d in ages:
        by_age["0-7" if d <= 7 else "8-14" if d <= 14 else "15+"] += 1
    return _measured(len(waiting), "asks, open and not muted; reminders and reports left out",
                     oldest_days=ages[0][1] if ages else None, over_14_days=by_age["15+"], by_age=by_age,
                     critical=sum(1 for a in waiting if asks.is_critical(a)),
                     oldest=[{"id": a.id, "product": a.product, "age_days": d, "title": _clip(a.title or a.question, 160)}
                             for a, d in ages[:OPEN_SHOWN]],
                     design_picks=design_picks_metric(now), decision_minutes=decision_minutes)


# --- builds --------------------------------------------------------------------------------------

def builds_metric(now: float) -> dict:
    rows, age = testflight.load_cache(now=now)
    if rows is None:
        return _missing("run `teyla testflight` once (it asks App Store Connect)", "teyla testflight cache")
    cutoff = _dt.datetime.fromtimestamp(now, _dt.timezone.utc) - _dt.timedelta(days=BUILD_DAYS)
    readable = [r for r in rows if isinstance(r, dict) and r.get("verdict") != "error"]
    if not readable:
        # Every product failed (auth, connection): zero would claim a fact nobody read (review P2).
        return _missing("the last `teyla testflight` run read no product (every row was an error)",
                        "teyla testflight cache", cache_age_s=int(age or 0))
    unread = len(rows) - len(readable)
    out = []
    for r in readable:
        plats = (r.get("payload") or {}).get("platforms") or []
        for p in plats:
            if not isinstance(p, dict):
                continue
            up, inst = p.get("newest_uploaded") or {}, p.get("newest_installable") or {}
            when = testflight._upload_time(p)
            if when is None or when < cutoff or not inst or str(inst.get("build")) != str(up.get("build")):
                continue
            out.append({"product": r.get("product"), "platform": testflight._label(str(p.get("platform") or "?")),
                        "build": str(up.get("build")), "uploaded": str(up.get("uploaded") or "")[:10]})
    out.sort(key=lambda b: b["uploaded"], reverse=True)
    stale = age is not None and age > CACHE_STALE_S
    return _measured(len(out), f"teyla testflight cache, {asks.fmt_age(age or 0)} old; build uploaded in the last "
                               f"{BUILD_DAYS} days and installable; Teyla records no verdict",
                     builds=out, cache_age_s=int(age or 0), stale=stale, unread_products=unread)


# --- the dates -----------------------------------------------------------------------------------

def hard_dates(today: _dt.date) -> list[dict]:
    """The `[dates]` table of config.toml as [{name, date, days_left}], soonest first. A bad date is skipped."""
    raw = config.load().get("dates")
    out = []
    for name, value in (raw.items() if isinstance(raw, dict) else []):
        try:
            d = _dt.date.fromisoformat(str(value))
        except ValueError:
            continue
        out.append({"name": str(name), "date": d.isoformat(), "days_left": (d - today).days})
    return sorted(out, key=lambda x: x["date"])


# --- the snapshot and the screen -----------------------------------------------------------------

def snapshot(now: float | None = None) -> dict:
    now = _now() if now is None else now
    day = gtm.day_of(now)
    week = gtm.week_of(day)
    mon, sun = gtm.week_range(week)
    metrics = ledger_metrics(now)
    metrics["first_value"] = first_value_metric()
    metrics["open_decisions"] = open_decisions_metric(now)
    metrics["builds_to_try"] = builds_metric(now)
    order = ("posts_published", "sale_attempts", "conversations", "first_value", "open_decisions", "builds_to_try")
    return {"version": VERSION, "generated": _iso(now), "week": week, "start": mon, "end": sun,
            "metrics": {k: metrics[k] for k in order},
            "hard_dates": hard_dates(_dt.date.fromisoformat(day))}


def _row(st: Style, label: str, m: dict, detail: str) -> str:
    if m["value"] == NOT_MEASURED:
        return f"{label:<16}{NOT_MEASURED}  {st.quiet(m.get('reason', ''))}"
    return f"{label:<16}{st.bold(str(m['value']))}  {st.quiet(detail)}"


def render(snap: dict, st: Style | None = None) -> str:
    st = st or Style()
    m = snap["metrics"]
    p, s, c, fv, od, bt = (m[k] for k in ("posts_published", "sale_attempts", "conversations", "first_value",
                                          "open_decisions", "builds_to_try"))
    mon = _dt.date.fromisoformat(snap["start"]).strftime("%d %b")
    sun = _dt.date.fromisoformat(snap["end"]).strftime("%d %b")
    L = [f"{st.bold('Scoreboard')}  {snap['week']}  {st.quiet(f'{mon} to {sun}')}", ""]
    L.append(_row(st, "Posts", p, "growth ledger"))
    b = s.get("breakdown") or {}
    L.append(_row(st, "Sale attempts", s, f"{b.get('posts', 0)} posts, {b.get('marketing', 0)} marketing, "
                                           f"{b.get('icp_meetings', 0)} ICP meetings"))
    L.append(_row(st, "Conversations", c, f"{c.get('replies', 0)} replies; next step {NOT_MEASURED} (ledger keeps none)"))
    part = f", {fv['measured_products']} of {fv['focus_products']} focus products" if fv.get("measured_products") is not None \
        and fv["measured_products"] < fv["focus_products"] else ""
    L.append(_row(st, "First value", fv, f"installs, not people{part}"))
    if od["value"] == NOT_MEASURED:
        L.append(_row(st, "Open decisions", od, ""))
    else:
        old = f"oldest {od['oldest_days']}d, " if od.get("oldest_days") is not None else ""
        L.append(_row(st, "Open decisions", od, f"{old}{od['over_14_days']} over 14d, {od['critical']} critical"))
    dp = od["design_picks"]
    L.append(_row(st, "Design picks", dp, "open design cards") if dp["value"] != NOT_MEASURED else _row(st, "Design picks", dp, ""))
    if bt["value"] == NOT_MEASURED:
        L.append(_row(st, "Builds to try", bt, ""))
    else:
        age = asks.fmt_age(bt["cache_age_s"])
        L.append(_row(st, "Builds to try", bt, f"testflight cache, {age} old" + ("; STALE, run `teyla today score --refresh`"
                                                                                if bt["stale"] else "")))
    dm = od["decision_minutes"]
    L.append(f"{'Decision time':<16}{NOT_MEASURED}  {st.quiet(dm['reason'])}")
    if snap["hard_dates"]:
        L.append("")
        for d in snap["hard_dates"]:
            when = f"{d['days_left']} days left" if d["days_left"] >= 0 else f"passed {-d['days_left']} days ago"
            L.append(f"{d['name']:<16}{when}  {st.quiet(d['date'])}")
    if od["value"] != NOT_MEASURED and od["oldest"]:
        L += ["", st.bold("Oldest decisions")]
        L += [f"  {x['product'][:18]:<18} {x['age_days']:>3}d  {_clip(x['title'], 48)}" for x in od["oldest"]]
    if bt["value"] != NOT_MEASURED and bt["builds"]:
        L += ["", st.bold("Builds to try")]
        L += [f"  {x['product'][:18]:<18} {x['platform']:<6} build {x['build']}  uploaded {x['uploaded']}" for x in bt["builds"]]
        L.append(st.quiet("  Teyla records no verdict: a build stays here until it is a week old."))
    return "\n".join(L)


# --- the command ---------------------------------------------------------------------------------

def refresh_testflight() -> None:
    """The live check: the same call `teyla testflight` makes. Network, so `net.gate` decides."""
    if not net.gate("`teyla today score --refresh` (your release tool asks App Store Connect)"):
        return
    print("Asking App Store Connect; this takes about a minute.", file=sys.stderr)
    testflight.write_cache(testflight.run(None))


def cmd_score(args) -> int:
    if getattr(args, "refresh", False):
        refresh_testflight()
    snap = snapshot()
    if args.json:
        print(json.dumps(snap, indent=1))
    else:
        print(render(snap))
    return 0

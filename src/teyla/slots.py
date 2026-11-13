"""`teyla brief slots`: the sprint slots. It shows what holds a slot and warns at a third. It refuses nothing.

    teyla brief slots           the open sprint contracts, what each waits at, and the sessions with no contract
    teyla brief slots --json    the same facts as JSON

The operating model allows two product sprints at a time. A sprint holds its slot from its contract
(`teyla brief`) until the owner gives a verdict at its gate; a build waiting for that verdict still holds it.
A contract past its hours still holds its slot and is marked `overdue`. Bug-fix sessions run outside the
limit, so sessions with no contract never trigger the warning.

What a slot waits at, in this order, every match listed: `gate` (the contract's gates), `decision` (open design
cards), `question` (open asks), `build` (builds to try). No match: "agents working".

Everything is local and read-only: no file is written and no network call is made. The exit code is 0.
The limit is `LIMIT`, or `[slots] limit = N` in `~/.teyla/config.toml`.
"""
from __future__ import annotations

import json
import time
import tomllib

from . import asks, brief, config, design_cycle, registry, scoreboard, state
from .ui import Style

VERSION = 1
LIMIT = 2
ACTIVE_WINDOW_S = 24 * 3600
CLIP = 60
_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


def _now() -> float:
    return time.time()


def _iso(now: float) -> str:
    return scoreboard._iso(now)


def limit() -> int:
    try:
        n = int((config.load().get("slots") or {}).get("limit", LIMIT))
    except (TypeError, ValueError, OSError):
        return LIMIT
    return n if n > 0 else LIMIT


def _key(name) -> str:
    return str(name or "").strip().lower()


def _epoch(ts):
    try:
        return brief._parse(str(ts)).timestamp()
    except ValueError:
        return None


# --- the open contracts --------------------------------------------------------------------------

def open_contracts() -> list[dict]:
    """The active contract of each product that has one and has not closed it. Nothing is written."""
    try:
        names = sorted(p.name for p in brief.briefs_dir().iterdir() if p.is_dir())
    except OSError:
        return []
    out = []
    for name in names:
        try:
            found = brief.load_active(name)
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            continue
        if found and not found[1].get("closed") and found[1].get("started"):
            out.append({**found[1], "product": found[1].get("product") or name})
    return out


# --- what a slot waits at ------------------------------------------------------------------------

def _cards(now: float) -> list[dict]:
    try:
        return [{"product": c.get("product"), "title": c.get("title"), "age": scoreboard._card_age_days(c, now)}
                for c in design_cycle.open_cards()]
    except Exception:  # noqa: BLE001 — a broken card store leaves this wait unlisted
        return []


def _asks(now: float) -> list:
    try:
        reg = registry.load(strict=False)
        items = asks.collect(now=now, fetch=False, st=asks.load_state())   # `st` given: nothing is saved
        return [a for a in items if a.status == "open" and a.kind not in ("reminder", "report")
                and not asks.is_muted(a, reg)]
    except Exception:  # noqa: BLE001
        return []


def _builds(now: float) -> list[dict]:
    try:
        m = scoreboard.builds_metric(now)
    except Exception:  # noqa: BLE001
        return []
    return [] if m["value"] == scoreboard.NOT_MEASURED else m.get("builds") or []


def _waiting(product: str, contract: dict, cards, items, builds, now: float) -> list[dict]:
    k = _key(product)
    out = []
    gates = [str(g) for g in contract.get("gates") or []]
    if gates:
        out.append({"kind": "gate", "text": "gates: " + ", ".join(gates)})
    for c in cards:
        if _key(c["product"]) == k:
            row = {"kind": "decision", "text": f"design card: {scoreboard._clip(c['title'], CLIP)}"}
            if isinstance(c["age"], int):
                row["age_days"] = c["age"]
            out.append(row)
    mine = sorted(((a, max(0, int((now - a.when) // 86400))) for a in items if _key(a.product) == k),
                  key=lambda x: -x[1])
    if mine:
        a, age = mine[0]
        n = len(mine)
        out.append({"kind": "question", "age_days": age, "count": n,
                    "text": f"{n} open question{'s' if n != 1 else ''}; oldest {age}d: "
                            f"{scoreboard._clip(a.title or a.question, CLIP)}"})
    for b in builds:
        if _key(b.get("product")) == k:
            out.append({"kind": "build", "text": f"build {b['build']} on {b['platform']} to try, uploaded {b['uploaded']}"})
    return out or [{"kind": "agents", "text": "agents working"}]


def slot_row(c: dict, cards, items, builds, now: float) -> dict:
    started = _epoch(c["started"])
    hours = float(c.get("hours") or 0)
    elapsed = None if started is None else max(0.0, (now - started) / 3600.0)
    waiting = _waiting(c["product"], c, cards, items, builds, now)
    return {"product": c["product"], "started": str(c["started"]),
            "age_days": None if started is None else max(0, int((now - started) // 86400)),
            "goal": str(c.get("goal") or ""), "gates": [str(g) for g in c.get("gates") or []],
            "hours": hours, "hours_elapsed": None if elapsed is None else round(elapsed, 1),
            "overdue": bool(elapsed is not None and hours > 0 and elapsed > hours),
            "waits_at": {"kind": waiting[0]["kind"], "text": waiting[0]["text"]}, "waiting": waiting}


# --- sessions with no contract -------------------------------------------------------------------

def cli_sessions(now: float, root: str | None = None) -> list[tuple[str, str, float]]:
    """(cwd, session id, last write) of Claude Code transcripts written in the window: the sessions the desktop
    and dispatch stores do not list. Reads the first lines of each recent file only."""
    import glob
    import os
    from .adapters import claude_code
    root = claude_code.DEFAULT_ROOT if root is None else root
    out = []
    for f in glob.glob(os.path.join(root, "*", "*.jsonl")):
        try:
            last = os.path.getmtime(f)
            if now - last > ACTIVE_WINDOW_S:
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                for _, line in zip(range(20), fh):
                    try:
                        cwd = json.loads(line).get("cwd")
                    except (ValueError, AttributeError):
                        continue
                    if cwd:
                        out.append((str(cwd), os.path.basename(f)[:-6], last))
                        break
        except OSError:
            continue
    return out


def recent_products(now: float) -> list[dict]:
    """Products with a session active in the last 24 hours: {product, last_active (epoch)}. Local files only.
    `state.running` keeps a 10-minute window, so this reads the same session stores with a 24-hour one."""
    runs = state.dispatched()
    found: dict[str, float] = {}

    def add(product, last):
        if product and product != "unassigned" and last is not None and now - last <= ACTIVE_WINDOW_S:
            found[product] = max(found.get(product, 0.0), last)

    for d in state.desktop_sessions():
        if state._desktop_skipped(d, runs):
            continue
        add(registry.resolve(d.get("cwd") or d.get("originCwd"),
                             session=(str(d.get("cliSessionId") or ""), str(d.get("sessionId") or ""))),
            asks._epoch(d.get("lastActivityAt")))
    for s in state.codex_sessions(now, None, runs):
        add(registry.resolve(s["cwd"], session=s["sid"]), s["_last"])
    for s in state.claude_dispatch_sessions(now, None, runs):
        add(registry.resolve(s["cwd"], session=s["id"]), s["_last"])
    for cwd, sid, last in cli_sessions(now):       # plain `claude` in a terminal (review P2)
        add(registry.resolve(cwd, session=sid), last)
    return [{"product": p, "last_active": t} for p, t in sorted(found.items(), key=lambda x: -x[1])]


def _no_contract(held: set[str], now: float) -> list[dict]:
    try:
        rows = recent_products(now)
    except Exception:  # noqa: BLE001 — the session stores are optional
        return []
    return [{"product": r["product"], "last_active": _iso(r["last_active"])} for r in rows
            if _key(r["product"]) not in held]


# --- snapshot and render -------------------------------------------------------------------------

def snapshot(now: float | None = None) -> dict:
    now = _now() if now is None else now
    cards, items, builds = _cards(now), _asks(now), _builds(now)
    slots = sorted((slot_row(c, cards, items, builds, now) for c in open_contracts()), key=lambda s: s["started"])
    lim = limit()
    return {"version": VERSION, "generated": _iso(now), "limit": lim, "in_flight": len(slots),
            "over_limit": len(slots) > lim, "slots": slots,
            "no_contract": _no_contract({_key(s["product"]) for s in slots}, now)}


def _age(days) -> str:
    return "" if days is None else "today" if days == 0 else f"{days}d ago"


def render(snap: dict, st: Style | None = None) -> str:
    st = st or Style()
    lim = snap["limit"]
    L = [f"{st.bold('Sprint slots')}: {snap['in_flight']} of {lim} in flight", ""]
    if not snap["slots"]:
        L += ["No sprint contract is open.", ""]
    for s in snap["slots"]:
        L.append(f"{st.bold(s['product'])}  started {s['started'][:10]} ({_age(s['age_days'])})")
        if s["overdue"]:
            L.append(f"  overdue: {s['hours_elapsed']:g}h elapsed of {s['hours']:g}h; the slot is still held")
        elif s["hours_elapsed"] is not None:
            L.append(st.quiet(f"  {s['hours_elapsed']:g}h elapsed of {s['hours']:g}h"))
        L.append(f"  goal: {scoreboard._clip(s['goal'], 70) or '-'}")
        L.append(f"  waits at: {s['waits_at']['text']}")
        for w in s["waiting"][1:]:
            L.append(st.quiet(f"    also: {w['text']}"))
        L.append("")
    if snap["over_limit"]:
        word = _WORDS.get(lim, str(lim))
        L += [f"WARN  {snap['in_flight']} sprints in flight; the limit is {word}. "
              "Close one with `teyla brief <product> --close` or finish its gate.", ""]
    if snap["no_contract"]:
        L.append(st.bold("Also active, no contract") + st.quiet("  (last 24 h)"))
        for r in snap["no_contract"]:
            L.append(f"  {r['product']}  last active {r['last_active'][:16].replace('T', ' ')}Z")
        L.append(st.quiet('  Count one in a slot: teyla brief <product> --goal "..." --gate "..." --usd N --hours N'))
        if snap["in_flight"] + len(snap["no_contract"]) > lim:
            L.append(st.quiet(f"  Note: {snap['in_flight']} contracts and {len(snap['no_contract'])} products active without "
                              "one. Bug-fix sessions may run outside the limit."))
    return "\n".join(L).rstrip()


def cmd_slots(args) -> int:
    snap = snapshot()
    print(json.dumps(snap, indent=1) if getattr(args, "json", False) else render(snap))
    return 0

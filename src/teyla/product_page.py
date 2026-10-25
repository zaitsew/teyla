"""`teyla product show <id>`: everything one product page shows, from the figures Teyla already keeps.

    teyla product show <id>              a short text page
    teyla product show <id> --json       the same facts as JSON (the Mac app's product page)
    teyla product show <id> --quick      leave out the sessions and the spend; they need a full read of the
                                         last 30 days of sessions, which can take a minute on a large machine

Nothing here is a new figure. The product is the registry entry (`registry`), the waiting questions are
`asks` attributed to it (muted ones in a parked product left out, as in `teyla asks`), the notes are
`notes.listing`, and the sessions and the spend are `spend.session_rows` and `spend.by_day` over the rows
`registry.attribute` files under the product. JSON, version 1:

    {"version": 1, "generated": "...Z",
     "product": {"id", "name", "stage", "focus", "primary", "repos", "aliases", "registered"},
     "asks":     [{"id", "age_s", "severity": "critical"|"normal", "question", "link"}],
     "notes":    [{"id", "text", "created", "age_s"}],
     "sessions": [{"id", "at", "harness", "model", "cost_usd", "title"}]   (null with --quick)
     "spend":    {"days_7": usd, "days_30": usd}                           (null with --quick)}

The id is a registered product, or `unassigned` (the bucket for sessions nobody filed).
"""
from __future__ import annotations

import datetime as _dt
import json
import sys

from . import asks, figures, notes, registry

VERSION = 1
SESSIONS_SHOWN = 10
WINDOW_DAYS = 30
WEEK_DAYS = 7
QUESTION_CLIP = 400


def known(pid: str, reg: dict) -> bool:
    return pid in reg["product"] or pid == registry.UNASSIGNED


def _iso(at: float) -> str:
    return _dt.datetime.fromtimestamp(at, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(iso: str) -> float:
    try:
        d = _dt.datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)).timestamp()


def header(pid: str, reg: dict) -> dict:
    p = reg["product"].get(pid) or {}
    return {"id": pid, "name": asks.display_name(reg, pid), "stage": p.get("stage") or "",
            "focus": bool(p.get("focus")), "primary": p.get("primary") or "",
            "repos": list(p.get("repos") or []), "aliases": list(p.get("aliases") or []),
            "registered": pid in reg["product"]}


def waiting_asks(pid: str, reg: dict, now: float, items=None) -> list[dict]:
    """The questions `teyla asks` lists for this product: critical ones first, then the oldest (as `teyla today` orders them)."""
    rows = [a for a in figures.waiting_questions(items) if a.product == pid]
    return [{"id": a.id, "age_s": max(0, int(now - a.when)),
             "severity": "critical" if asks.is_critical(a) else "normal",
             "question": asks.clip(a.question or a.title, QUESTION_CLIP), "link": a.link}
            for a in sorted(rows, key=lambda a: (not asks.is_critical(a), a.when))]


def product_notes(pid: str, now: float) -> list[dict]:
    return [{"id": n["id"], "text": n["text"], "created": n["created"],
             "age_s": max(0, int(now - _epoch(n["created"])))} for n in notes.listing(pid)]


def load_rows(days: int = WINDOW_DAYS) -> tuple[list[dict], dict[str, str]]:
    """The session rows of the window (every harness) and each session's title. Slow: it parses the sessions."""
    from . import spend
    from .adapters import load_all, since_epoch
    sessions = load_all(since=since_epoch(days))
    return spend.session_rows(days, sessions=sessions), {s.sid: s.title or "" for s in sessions}


def _top_model(by_model: dict) -> str:
    return max(by_model, key=by_model.get) if by_model else ""


def sessions_and_spend(pid: str, reg: dict, rows: list[dict], titles: dict[str, str]) -> tuple[list[dict], dict]:
    """The product's newest sessions and its spend over 7 and 30 days, from the rows filed under it."""
    from . import spend
    mine = [r for r in rows
            if registry.attribute(r.get("cwd"), session=r["sid"], texts=(titles.get(r["sid"], ""), ""), reg=reg)[0] == pid]
    days = spend.by_day(WINDOW_DAYS, mine)                    # oldest first, 30 local days ending today
    spent = {"days_7": round(sum(d["total_usd"] for d in days[-WEEK_DAYS:]), 2),
             "days_30": round(sum(d["total_usd"] for d in days), 2)}
    newest = sorted(mine, key=lambda r: r.get("last") or r.get("first") or "", reverse=True)[:SESSIONS_SHOWN]
    return ([{"id": r["sid"], "at": r.get("last") or r.get("first") or "", "harness": r["harness"],
              "model": _top_model(r["by_model"]), "cost_usd": round(r["usd"], 2), "title": titles.get(r["sid"], "")}
             for r in newest], spent)


def snapshot(pid: str, now: float | None = None, *, quick: bool = False, reg: dict | None = None, items=None,
             rows: list[dict] | None = None, titles: dict[str, str] | None = None) -> dict:
    """The page's facts. Raises KeyError for an id that is neither registered nor `unassigned`."""
    now = figures.now() if now is None else now
    reg = registry.load() if reg is None else reg
    if not known(pid, reg):
        raise KeyError(pid)
    out = {"version": VERSION, "generated": _iso(now), "product": header(pid, reg),
           "asks": waiting_asks(pid, reg, now, items), "notes": product_notes(pid, now),
           "sessions": None, "spend": None}
    if not quick:
        if rows is None:
            rows, titles = load_rows()
        out["sessions"], out["spend"] = sessions_and_spend(pid, reg, rows, titles or {})
    return out


# --- the text -----------------------------------------------------------------------------------

def _usd(x: float) -> str:
    from .spend import _money
    return _money(x)


def render(snap: dict) -> str:
    p = snap["product"]
    head = f"{p['name']}  ({p['id']})"
    bits = [b for b in (p["stage"], "focus" if p["focus"] else "", f"primary {p['primary']}" if p["primary"] else "") if b]
    L = [head + ("  " + ", ".join(bits) if bits else "")]
    if p["repos"]:
        L.append("  repos:   " + ", ".join(p["repos"]))
    if p["aliases"]:
        L.append("  aliases: " + ", ".join(p["aliases"]))
    if snap["spend"]:
        L.append(f"  spend:   {_usd(snap['spend']['days_7'])} in 7 days, {_usd(snap['spend']['days_30'])} in 30 days (API list price)")
    L += ["", f"Waiting on you ({len(snap['asks'])})"]
    L += [f"  {a['id']}  {asks.fmt_age(a['age_s']):>4}  {a['severity']:<8}  {' '.join(a['question'].split())}" for a in snap["asks"]] \
        or ["  nothing"]
    L += ["", f"Notes ({len(snap['notes'])})"]
    L += [f"  {n['id']}  {asks.fmt_age(n['age_s']):>4}  {notes.clip(n['text'])}" for n in snap["notes"]] or ["  none"]
    if snap["sessions"] is None:
        L += ["", "Sessions and spend left out (--quick)."]
    else:
        L += ["", f"Recent sessions ({len(snap['sessions'])})"]
        L += [f"  {s['at'][:10]}  {s['harness']:<11} {s['model'] or '-':<18} {_usd(s['cost_usd']):>8}  {s['title'] or '(untitled)'}"
              for s in snap["sessions"]] or ["  none in the last 30 days"]
    return "\n".join(L)


def cmd_show(args) -> int:
    try:
        reg = registry.load(strict=True)
    except registry.RegistryError as e:
        print(f"teyla: {e}", file=sys.stderr)
        return 1
    if not known(args.id, reg):
        print(f"teyla: no product {args.id!r}; `teyla product` lists the registered ones.", file=sys.stderr)
        return 2
    snap = snapshot(args.id, quick=args.quick, reg=reg)
    print(json.dumps(snap, indent=1, ensure_ascii=False) if args.json else render(snap))
    return 0

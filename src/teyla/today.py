"""`teyla today`: the daily screen. What waits on you, what the week cost, and the one thing to do next.

    teyla today                 about 25 lines of text
    teyla today --json          the same facts for the Mac app and the web page
    teyla today --fresh         count the spend again now instead of reading the cache

Four blocks, in this order:

    Waiting on you   open questions grouped by product, `focus` products first, at most 3 per product
                     (critical ones first, then oldest first), then "+N more"
    Inbox            the notes with no product yet: the count and the newest 3
    Spend            the last 7 days against the 7 before, at API list price, and the change in percent
    Next             one suggested action

The suggestion is chosen by this rule, first match wins (`suggest`; docs/TODAY.md says the same):

    1. offer     an offer from `teyla start` that is not in force and has a dollar saving: the one with
                 the biggest saving. Command: `teyla apply <id>`.
    2. critical  else the oldest waiting question that is critical (`asks.is_critical`: a blocked
                 session, or a security, money or release-failure matter). Command: `teyla asks --product <id>`.
    3. inbox     else the Inbox, when it holds a note. Command: `teyla notes --inbox`.
    4. question  else the oldest waiting question. Command: `teyla asks --product <id>`.
    5. none      else "Nothing needs you today."

Questions and notes are read live (a fraction of a second). Spend is parsed from every session of two
weeks, which takes 5 s to a minute, so it comes from the cache in `figures` and is counted again in the
background when the cache is older than 10 minutes. With no cache at all the text screen counts it
once, in the foreground, and says so; `--json` never waits and reports `"spend": null` instead.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys

from . import asks, figures, notes, registry
from .spend import _money
from .ui import Style

QUESTIONS_PER_PRODUCT = 3
QUESTION_LINES = 11              # product headers, questions and "+N more" lines together
NOTES_SHOWN = 3
CLIP = 52
VERSION = 1


def clip(text: str, n: int = CLIP) -> str:
    one = " ".join(str(text).split())
    return one if len(one) <= n else one[:n - 1].rstrip() + "…"


def _epoch(iso: str) -> float:
    try:
        return _dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _iso(at: float) -> str:
    return _dt.datetime.fromtimestamp(at, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the facts ----------------------------------------------------------------------------------

def question_groups(items: list, reg: dict, now: float) -> list[dict]:
    """The waiting questions as product groups: `asks.group`'s order, and inside a product the critical
    ones first, then the oldest. Each group lists every question; the screen shows the first three."""
    out = []
    for product, rows in asks.group(items, reg):
        rows = sorted(rows, key=lambda a: (not asks.is_critical(a), a.when))
        out.append({"product": product, "name": asks.display_name(reg, product), "stage": asks.stage_of(reg, product),
                    "focus": bool((reg["product"].get(product) or {}).get("focus")), "count": len(rows),
                    "asks": [{"id": a.id, "age_s": int(now - a.when), "critical": asks.is_critical(a),
                              "question": clip(a.question or a.title, 160), "link": a.link} for a in rows]})
    return out


def inbox_notes(now: float) -> dict:
    rows = notes.listing(notes.INBOX)
    return {"inbox": len(rows),
            "newest": [{"id": n["id"], "text": clip(n["text"], 160), "created": n["created"],
                        "age_s": max(0, int(now - _epoch(n["created"])))} for n in rows[:NOTES_SHOWN]]}


def spend_block(fig: dict | None, age: float | None, source: str) -> dict | None:
    if not fig:
        return None
    this, last = float(fig["this_week"]), float(fig["last_week"])
    return {"this_week": this, "last_week": last, "change_pct": figures.change_pct(this, last),
            "as_of": _iso(float(fig["at"])), "source": source, "note": figures.age_note(age)}


def suggest(groups: list[dict], inbox: int, offers: list[dict]) -> dict:
    """The one suggested action. See the module docstring for the rule."""
    priced = [o for o in offers if o["high"] > 0]
    if priced:
        o = priced[0]
        lo, hi = _money(o["low"]), _money(o["high"])
        saving = hi if lo == hi else f"{lo}-{hi}"
        return {"kind": "offer", "text": f"Apply {o['id']}, {o['title']}: it saves about {saving} a month.",
                "command": f"teyla apply {o['id']}"}
    every = [(g, a) for g in groups for a in g["asks"]]
    critical = sorted((x for x in every if x[1]["critical"]), key=lambda x: -x[1]["age_s"])
    if critical:
        g, a = critical[0]
        return {"kind": "critical", "text": f"Answer the oldest critical question: {g['name']}, {_age(a['age_s'])} old.",
                "command": f"teyla asks --product {g['product']}"}
    if inbox:
        return {"kind": "inbox", "text": f"Put the {inbox} note{'s' if inbox != 1 else ''} in your Inbox under a product.",
                "command": "teyla notes --inbox"}
    if every:
        g, a = max(every, key=lambda x: x[1]["age_s"])
        return {"kind": "question", "text": f"Answer the oldest question: {g['name']}, {_age(a['age_s'])} old.",
                "command": f"teyla asks --product {g['product']}"}
    return {"kind": "none", "text": "Nothing needs you today.", "command": ""}


def _age(age_s: float) -> str:
    return asks.fmt_age(age_s)


def snapshot(now: float | None = None, *, fresh: bool = False, wait: bool = True, items=None) -> dict:
    """Everything the screen shows. `wait`: count the spend in the foreground when there is no cache."""
    now = figures.now() if now is None else now
    reg = registry.load()
    waiting = figures.waiting_questions(items)
    groups = question_groups(waiting, reg, now)
    figures.write_cache(questions={"waiting": len(waiting), "at": now})
    inbox = inbox_notes(now)
    sessions = figures.has_sessions()
    fig, age, source = None, None, "none"
    if sessions:
        fig, age = figures.cached("spend", now)
        source = "cache" if fig else "none"
        if fresh or (fig is None and wait):
            print("Counting two weeks of sessions; the first count can take a minute.", file=sys.stderr)
            try:
                fig = figures.compute_spend(now)
                figures.write_cache(spend=fig)
                age, source = 0.0, "fresh"
            except Exception as e:  # noqa: BLE001 — a session store Teyla cannot read leaves the spend line out
                print(f"teyla: could not count the spend ({type(e).__name__}); the rest of the screen is below.", file=sys.stderr)
        elif figures.stale(age):
            figures.spawn_refresh()
    return {"version": VERSION, "generated": _iso(now),
            "sessions": sessions,
            "questions": {"waiting": len(waiting), "products": groups},
            "notes": inbox,
            "spend": spend_block(fig, age, source),
            "suggestion": suggest(groups, inbox["inbox"], figures.open_offers())}


# --- the text -----------------------------------------------------------------------------------

def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def spend_line(spend: dict | None, sessions: bool, st: Style) -> str:
    if not sessions:
        return "Spend: no agent sessions found yet."
    if not spend:
        return "Spend: not counted yet. It appears in a minute; run `teyla today` again."
    this, last, pct = spend["this_week"], spend["last_week"], spend["change_pct"]
    change = f" ({pct:+d}%)" if pct is not None else ""
    note = f"  {st.quiet(spend['note'])}" if spend.get("note") else ""
    return f"Spend: {_money(this)} in the last 7 days, {_money(last)} in the 7 before{change}. API list price.{note}"


def question_lines(q: dict, st: Style) -> list[str]:
    """The Waiting block: products in order, each with its first three questions. A line budget keeps the
    whole screen near 25 lines; what does not fit is counted on the last line."""
    L = [f"{st.bold('Waiting on you')}: " + st.paint(_plural(q["waiting"], "question"), "needs-you")
         + f" in {_plural(len(q['products']), 'product')}"]
    budget = QUESTION_LINES - 1                     # one line is kept for the closing count
    shown_products = covered = 0
    for g in q["products"]:
        if budget < 2:
            break
        take = min(QUESTIONS_PER_PRODUCT, g["count"], budget - 1)
        head = f"  {g['name']}  {g['count']} waiting" + (f"  [{g['stage']}]" if g["stage"] else "")
        L.append(st.bold(head) if g["focus"] else head)
        for a in g["asks"][:take]:
            tag = st.paint(" critical", "needs-you") if a["critical"] else ""
            L.append(f"    {a['id'][:8]}  {_age(a['age_s']):>3}{tag}  {clip(a['question'])}")
        budget -= 1 + take
        shown_products += 1
        covered += take
        if g["count"] > take and budget >= 1:
            L.append(st.quiet(f"    +{g['count'] - take} more"))
            budget -= 1
            covered += g["count"] - take
    rest_q, rest_p = q["waiting"] - covered, len(q["products"]) - shown_products
    if rest_q > 0:
        where = f" in {_plural(rest_p, 'other product')}" if rest_p else ""
        L.append(st.quiet(f"  +{rest_q} more{where}: ") + st.command("teyla asks"))
    return L


def render(snap: dict, st: Style | None = None) -> str:
    st = st or Style()
    gen = _dt.datetime.fromtimestamp(_epoch(snap["generated"]), _dt.timezone.utc).astimezone()
    L = [f"{st.bold('Today')}  {st.quiet(gen.strftime('%a %d %b'))}", ""]
    q = snap["questions"]
    L += question_lines(q, st) if q["waiting"] else [f"{st.bold('Waiting on you')}: nothing."]
    L.append("")
    inbox = snap["notes"]
    if inbox["inbox"]:
        L.append(f"{st.bold('Inbox')}: " + st.paint(_plural(inbox["inbox"], "note"), "needs-you") + " with no product yet  "
                 + st.command("teyla notes --inbox"))
        L += [f"    {n['id']}  {_age(n['age_s']):>3}  {clip(n['text'])}" for n in inbox["newest"]]
    else:
        L.append(f"{st.bold('Inbox')}: empty.")
    L.append(spend_line(snap["spend"], snap["sessions"], st).replace("Spend:", st.bold("Spend") + ":", 1))
    L.append("")
    s = snap["suggestion"]
    L.append(f"{st.bold('Next')}: {s['text']}")
    if s["command"]:
        L.append("      " + st.command(s["command"]))
    return "\n".join(L)


# --- the command --------------------------------------------------------------------------------

def cmd_today(args) -> int:
    if args.refresh_cache:                      # the background job `figures.spawn_refresh` starts
        try:
            figures.refresh()
        except Exception:  # noqa: BLE001 — nobody reads a background job's error
            return 1
        finally:
            figures.release_lock()
        return 0
    snap = snapshot(fresh=args.fresh, wait=not args.json)
    if args.json:
        print(json.dumps(snap, indent=1))
    else:
        print(render(snap))
    return 0


def register(sp):
    q = sp.add_parser("today", help="the daily screen: what waits on you, the Inbox, the week's spend, one suggested action")
    q.set_defaults(fn=cmd_today)
    q.add_argument("--json", action="store_true", help="the same facts as JSON, for the Mac app and the web page")
    q.add_argument("--fresh", action="store_true", help="count the spend again now instead of reading the cache")
    q.add_argument("--refresh-cache", action="store_true", help=argparse.SUPPRESS)
    return q

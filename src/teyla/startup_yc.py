"""`teyla startup yc` — the YC sheet: 15 boxes the owner can check honestly (docs/STARTUP.md, "The YC sheet").

    teyla startup yc [<id>] [--json]           the sheet; the focus product when no id is given
    teyla startup yc answer <id> <box> <text>  write an answer (from an agent session it stays a draft)
    teyla startup yc confirm <id> <box>        confirm a draft; refused in an agent session
    teyla startup yc export <id>               the answers as Markdown, for pasting

A box means "I can answer this honestly, with evidence", not "this number is good". A true $0 checks "What they pay",
and revenue never blocks an application. All 15 checked says "Apply" with YC's link; otherwise the sheet says "9 of 15"
and names the next box. It is never a percent. Teyla never submits an application: it prepares answers.

Answers live in `~/.teyla/startup/yc/<id>.toml` (mode 0600), the only place customer words are kept. They never enter
`teyla state`, the portfolio or the relay: the `startup` block carries the counts only. An answer written from an agent
session is a draft and checks nothing until the owner confirms it. No network call.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import fcntl
import json
import os
import pathlib
import sys
import time
import tomllib

from . import asks, registry, startup

# Read on ycombinator.com on 2026-11-04. The sheet warns when these are older than 90 days.
FACTS_READ = "2026-11-04"
FACTS_MAX_AGE_DAYS = 90
FACTS = (
    "Winter 2027 runs January to March in San Francisco. The on-time deadline was November 2. Late applications are open.",
    "YC says to apply as soon as you are ready. It says about 40% of the companies it funds in each batch are just an idea, "
    "and most have no revenue.",
    "YC regularly accepts solo founders, and says one-person startups are tough.",
    "The deal is $500,000: $125,000 for 7%, plus $375,000 on an uncapped MFN SAFE.",
)
APPLY_URL = "https://www.ycombinator.com/apply"
MAX_ANSWER = 2000

# (id, question, kind, rung that must be met first, what to write). "auto" boxes come from records, never from an answer.
BOXES = (
    ("building", "What are you building?", "answer", None, "one plain sentence"),
    ("customer", "Pick one customer", "answer", "used", "one real customer, named by role"),
    ("does", "What does it do for them?", "answer", None, "the job it does for that customer"),
    ("using", "Are they using it?", "auto", None, ""),
    ("pay", "What do they pay?", "auto", None, ""),
    ("why_you", "Why you?", "answer", None, "why you are the one to build it"),
    ("custom", "Is it custom software per customer?", "answer", None, "yes or no, and why"),
    ("goal", "What is the Demo Day goal?", "answer", None, "one number or one outcome"),
    ("who", "Who does what?", "answer", None, "include what the agents do"),
    ("talked", "How many customers have you talked to?", "auto", None, ""),
    ("sell", "How do you sell it?", "answer", "tried", "the channel you use, as it is today"),
    ("demo", "Show us the demo", "answer", "built", "a link to the demo (https://...)"),
    ("first_live", "When did the first customer go live?", "answer", "used", "a date and who"),
    ("need", "What do they need most?", "answer", None, "what customers asked for"),
    ("commit", "Can you commit to the batch?", "answer", None, "it is in person in San Francisco"),
)
BOX_IDS = tuple(b[0] for b in BOXES)
ADDED_BY_US = ("commit",)          # not on the founder's list; Teyla added it


# --- facts ----------------------------------------------------------------------------------------------------

def facts_age_days(today: _dt.date | None = None) -> int:
    return ((today or _dt.date.today()) - _dt.date.fromisoformat(FACTS_READ)).days


def facts_stale(today: _dt.date | None = None) -> bool:
    return facts_age_days(today) > FACTS_MAX_AGE_DAYS


# --- the answers store ----------------------------------------------------------------------------------------

def answers_path(pid: str) -> pathlib.Path:
    return startup.home() / "yc" / f"{pid}.toml"


def load_answers(pid: str) -> dict[str, dict]:
    """{box: {text, status, by, at}}; empty when the file is missing or unreadable."""
    try:
        raw = tomllib.loads(answers_path(pid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for box, a in (raw.get("box") or {}).items():
        if box in BOX_IDS and isinstance(a, dict) and isinstance(a.get("text"), str) and a.get("text").strip():
            out[box] = {"text": a["text"], "status": "confirmed" if a.get("status") == "confirmed" else "draft",
                        "by": str(a.get("by") or ""), "at": str(a.get("at") or "")}
    return out


def _dump(answers: dict[str, dict]) -> str:
    L = ["# Teyla YC answers. Private: never in a repo, never in `teyla state`.", ""]
    for box in BOX_IDS:
        a = answers.get(box)
        if a:
            L += [f"[box.{box}]", f"text = {registry._str(a['text'])}", f"status = {registry._str(a['status'])}",
                  f"by = {registry._str(a['by'])}", f"at = {registry._str(a['at'])}", ""]
    return "\n".join(L)


@contextlib.contextmanager
def _locked():
    """One writer at a time, around read-change-write: without it, two answers at once lose one of them."""
    d = startup.home()
    d.mkdir(parents=True, exist_ok=True)
    fd = os.open(d / "yc.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)                              # closing the descriptor drops the lock


def save_answers(pid: str, answers: dict[str, dict]) -> None:
    d = answers_path(pid).parent
    d.mkdir(parents=True, exist_ok=True)
    for x in (startup.home(), d):
        try:
            os.chmod(x, 0o700)
        except OSError:
            pass
    asks._atomic_write(answers_path(pid), _dump(answers))        # mode 0600, atomic


# --- the boxes ------------------------------------------------------------------------------------------------

def _rung(block: dict, rid: str) -> str:
    return next((r["status"] for r in block["rungs"] if r["id"] == rid), "missing")


def auto_text(box: str, block: dict) -> str | None:
    """The answer a record gives for an auto box; None when the records do not support one yet."""
    m = block["metrics"]
    if box == "using":
        u = m["usage"]
        if block["stale"] or not block["as_of"] or u["external"] is None:
            return None
        return (f"{u['external']} outside people{' (assumed: accounts minus the owner)' if u['external_assumed'] else ''}, "
                f"{u['wau'] if u['wau'] is not None else 'unknown'} active this week, "
                f"{u['retained_7d'] if u['retained_7d'] is not None else 'unknown'} returned at day 7. As of {block['as_of'][:10]}.")
    if box == "pay":
        mo = m["money"]
        if not mo["enabled"]:
            return "$0. The product does not charge yet."
        if block["stale"] or (mo["paying"] is None and mo["revenue_30d_usd"] is None):
            return None
        return (f"{mo['paying'] if mo['paying'] is not None else 'unknown'} payers, MRR "
                f"{'$%g' % mo['mrr_usd'] if mo['mrr_usd'] is not None else 'unknown'}, revenue in 30 days "
                f"{'$%g' % mo['revenue_30d_usd'] if mo['revenue_30d_usd'] is not None else 'unknown'}. As of {(block['as_of'] or '')[:10]}.")
    if box == "talked":
        s = m["sales"]
        if s["icp_meetings"] < 1:
            return None
        return f"{s['icp_meetings']} ICP conversations, {s['icp_meetings_30d']} in the last 30 days. Last attempt {s['last']}."
    return None


def rows(pid: str, block: dict, answers: dict[str, dict]) -> list[dict]:
    """One row per box: checked, what is missing, the command, and the answer. Pure: `block` and `answers` are the input."""
    out = []
    for box, question, kind, prereq, hint in BOXES:
        a = answers.get(box)
        need, cmd = [], ""
        if kind == "auto":
            checked = auto_text(box, block) is not None
            if not checked:
                need = {"using": ["A fresh usage probe"], "pay": ["A fresh payer or revenue number"],
                        "talked": ["One ICP conversation you logged yourself"]}[box]
                cmd = {"using": "teyla portfolio --refresh", "pay": "teyla portfolio --refresh",
                       "talked": f"teyla growth log --product {pid} --kind icp-meeting"}[box]
        else:
            ok_prereq = prereq is None or _rung(block, prereq) == "met"
            confirmed = bool(a and a["status"] == "confirmed")
            checked = confirmed and ok_prereq
            if not a:
                need.append("An answer")
                cmd = f'teyla startup yc answer {pid} {box} "<{hint}>"'
            elif not confirmed:
                need.append("Confirm the draft")
                cmd = f"teyla startup yc confirm {pid} {box}"
            if not ok_prereq:
                need.append(f"{startup.TITLES[prereq]} must be met")
                cmd = cmd or {"used": f"teyla startup show {pid}", "tried": "teyla growth",
                              "built": f"teyla portfolio --product {pid}"}[prereq]
        out.append({"id": box, "question": question, "checked": checked, "need": "; ".join(need), "command": cmd,
                    "origin": "teyla" if box in ADDED_BY_US else "founder list", "auto": kind == "auto",
                    "answer": a, "evidence": auto_text(box, block) if kind == "auto" else None})
    return out


def summary(pid: str, block: dict) -> dict:
    """The `yc` object of the startup block: counts only, no answer text. Reads the answers file, never emits it."""
    if block["type"] != "venture":
        return {"eligible": False, "checked": 0, "total": len(BOXES), "next_box": None}
    rs = rows(pid, block, load_answers(pid))
    nxt = next((r["id"] for r in rs if not r["checked"]), None)
    return {"eligible": True, "checked": sum(1 for r in rs if r["checked"]), "total": len(BOXES), "next_box": nxt}


def sheet(pid: str, block: dict, answers: dict[str, dict], today: _dt.date | None = None) -> dict:
    rs = rows(pid, block, answers)
    n = sum(1 for r in rs if r["checked"])
    nxt = next((r for r in rs if not r["checked"]), None)
    age = facts_age_days(today)
    return {"id": pid, "eligible": True, "checked": n, "total": len(rs), "verdict": "apply" if n == len(rs) else "keep going",
            "apply_url": APPLY_URL if n == len(rs) else None, "next_box": nxt["id"] if nxt else None,
            "facts": {"read": FACTS_READ, "age_days": age, "stale": age > FACTS_MAX_AGE_DAYS, "lines": list(FACTS)},
            "boxes": rs}


def render_sheet(sh: dict, title: str) -> str:
    L = [f"YC sheet: {title} ({sh['id']})"]
    if sh["verdict"] == "apply":
        L.append(f"Apply. {sh['checked']} of {sh['total']} checked. {APPLY_URL}")
    else:
        nxt = next(b for b in sh["boxes"] if b["id"] == sh["next_box"])
        L += [f"{sh['checked']} of {sh['total']} checked. Next: {nxt['id']}, \"{nxt['question']}\".", f"  {nxt['command']}"]
    L.append("")
    for b in sh["boxes"]:
        L.append(f"  [{'x' if b['checked'] else ' '}] {b['id']:<11}{b['question']}"
                 + ("" if b["checked"] else f"  needs: {b['need']}")
                 + ("  (added by Teyla)" if b["origin"] == "teyla" else ""))
    L += ["", "An unchecked box does not mean you may not apply. Teyla never submits: you apply yourself.",
          f"YC facts, read on {sh['facts']['read']}:"] + [f"  - {x}" for x in sh["facts"]["lines"]]
    if sh["facts"]["stale"]:
        L.append(f"WARNING: these facts are {sh['facts']['age_days']} days old. Check ycombinator.com before you apply.")
    return "\n".join(L) + "\n"


def export(sh: dict, title: str) -> str:
    L = [f"# {title}: YC interview answers", "",
         f"Prepared with Teyla. Facts read on {sh['facts']['read']}. Teyla does not submit applications.", ""]
    for b in sh["boxes"]:
        L += [f"## {b['question']}", ""]
        a, ev = b["answer"], b["evidence"]
        if b["auto"]:
            L.append(ev or f"_Not ready: {b['need']}._")
        elif a:
            L.append(a["text"] if a["status"] == "confirmed" else f"_Draft, not confirmed:_ {a['text']}")
            if not b["checked"] and a["status"] == "confirmed":
                L += ["", f"_Not ready: {b['need']}._"]
        else:
            L.append(f"_Not ready: {b['need']}._")
        L.append("")
    return "\n".join(L).rstrip("\n") + "\n"


# --- the commands ---------------------------------------------------------------------------------------------

def _fail(msg: str, code: int = 1) -> int:
    print(f"teyla: {msg}", file=sys.stderr)
    return code


def _products(now: float) -> dict[str, dict]:
    return {p["id"]: p for p in startup._view(now)}


def _pick(now: float, pid: str | None):
    """(item, error code, message). No id: the focus product."""
    items = _products(now)
    if not pid:
        pid = startup.focus_of(list(items.values()))
        if not pid:
            return None, 1, "no focus product: every product is parked or personal"
    p = items.get(pid)
    if p is None:
        return None, 2, f"no product '{pid}' in the portfolio"
    if not p.get("startup"):
        return None, 1, f"the startup block of {pid} could not be computed"
    if p["startup"]["type"] != "venture":
        return None, 1, (f"the YC sheet is for venture products; {pid} is {p['startup']['type']}. "
                         f"One application is one company: teyla product set {pid} type=venture")
    return p, 0, ""


def cmd_sheet(pid: str | None, as_json: bool) -> int:
    now = time.time()
    p, rc, msg = _pick(now, pid)
    if p is None:
        return _fail(msg, rc)
    sh = sheet(p["id"], p["startup"], load_answers(p["id"]))
    if as_json:
        print(json.dumps(sh, indent=1))
    else:
        print(render_sheet(sh, p["title"]), end="")
    return 0


def cmd_answer(pid: str, box: str, text: str) -> int:
    if box not in BOX_IDS:
        return _fail(f"unknown box '{box}': {', '.join(BOX_IDS)}", 2)
    kind = next(b[2] for b in BOXES if b[0] == box)
    if kind == "auto":
        return _fail(f"'{box}' is filled from records (usage, money, the growth ledger), not from an answer", 2)
    text = (text or "").strip()
    if not text:
        return _fail("the answer is empty", 2)
    if len(text) > MAX_ANSWER:
        return _fail(f"the answer is {len(text)} characters; the limit is {MAX_ANSWER}", 2)
    if box == "demo" and not text.startswith(("https://", "http://")):
        return _fail("the demo answer is a link: https://...", 2)
    now = time.time()
    p, rc, msg = _pick(now, pid)
    if p is None:
        return _fail(msg, rc)
    agent = startup.in_agent_session()
    with _locked():
        answers = load_answers(pid)
        if agent and answers.get(box, {}).get("status") == "confirmed":
            return _fail(f"you confirmed '{box}' yourself; an agent cannot replace it. Write it from your own shell")
        if answers_path(pid).exists() and not _readable(pid):
            return _fail(f"{answers_path(pid)} does not parse; fix it by hand first")
        answers[box] = {"text": text, "status": "draft" if agent else "confirmed", "by": "agent" if agent else "owner",
                        "at": startup._iso(now)}
        save_answers(pid, answers)
    print(f"{pid} {box}: " + ("draft saved. It checks nothing until you run: " + f"teyla startup yc confirm {pid} {box}"
                              if agent else "answer saved and confirmed"))
    return 0


def _readable(pid: str) -> bool:
    try:
        tomllib.loads(answers_path(pid).read_text(encoding="utf-8"))
        return True
    except (OSError, ValueError):
        return False


def cmd_confirm(pid: str, box: str) -> int:
    if startup.in_agent_session():
        return _fail("only the owner confirms an answer. Run this from your own shell, not from an agent session")
    if box not in BOX_IDS:
        return _fail(f"unknown box '{box}': {', '.join(BOX_IDS)}", 2)
    if pid not in registry.load()["product"]:
        return _fail(f"no product '{pid}' in the registry", 2)
    with _locked():
        answers = load_answers(pid)
        a = answers.get(box)
        if not a:
            return _fail(f"no answer for '{box}' on {pid} to confirm")
        if a["status"] == "confirmed":
            print(f"{pid} {box}: already confirmed")
            return 0
        answers[box] = {**a, "status": "confirmed", "by": "owner", "at": startup._iso(time.time())}
        save_answers(pid, answers)
    print(f"{pid} {box}: confirmed")
    return 0


def cmd_export(pid: str) -> int:
    now = time.time()
    p, rc, msg = _pick(now, pid)
    if p is None:
        return _fail(msg, rc)
    print(export(sheet(p["id"], p["startup"], load_answers(p["id"])), p["title"]), end="")
    return 0


def cmd_yc(args) -> int:
    w = list(args.words or [])
    as_json = bool(getattr(args, "json", False))
    if w and w[0] == "answer":
        if len(w) < 4:
            return _fail("usage: teyla startup yc answer <id> <box> <text>", 2)
        return cmd_answer(w[1], w[2], " ".join(w[3:]))
    if w and w[0] == "confirm":
        if len(w) != 3:
            return _fail("usage: teyla startup yc confirm <id> <box>", 2)
        return cmd_confirm(w[1], w[2])
    if w and w[0] == "export":
        if len(w) != 2:
            return _fail("usage: teyla startup yc export <id>", 2)
        return cmd_export(w[1])
    if len(w) > 1:
        return _fail("usage: teyla startup yc [<id>] | answer <id> <box> <text> | confirm <id> <box> | export <id>", 2)
    return cmd_sheet(w[0] if w else None, as_json)


def register(sub):
    y = sub.add_parser("yc", help="the YC sheet: 15 boxes you can check honestly; answer, confirm, export")
    y.set_defaults(fn=cmd_yc)
    y.add_argument("words", nargs="*", metavar="[ID | answer ID BOX TEXT | confirm ID BOX | export ID]")
    y.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return y

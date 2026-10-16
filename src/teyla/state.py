"""`teyla state` — one snapshot for the Teyla for Mac coordinator window (`docs/APP.md`).

    teyla state [--json]

Open questions ranked by what they unblock, where each product stands, which sessions are running
now, and today's spend. No model call: ranking and the brief line are rules. The snapshot is
private (it holds session text), like `teyla asks`.

Ranking: score = kind weight (blocked or gate 3, question 2, reminder 0) + 3 when the text
mentions a release (App Review, TestFlight, release, store, build, deploy, merge) + 1 when the
item is younger than 24 hours. Ties go to the newer item. Reminders show only once due.

Cost: the desktop app's metadata parse is cached by `asks`; today's spend takes seconds, so it
is read from `~/.teyla/state-spend.json` and refreshed by a detached `teyla state --refresh-spend`
when older than 10 minutes (null until the first refresh lands).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import re
import subprocess
import sys

from . import asks
from .adapters import codex, iter_jsonl
from .control import state as control

VERSION = 1
RUNNING_WINDOW_S = 600
QUIET_DAYS = 3
REPO_RECENT_DAYS = 30            # a repo with no session activity is listed only when it moved this recently
FRESH_S = 24 * 3600
SPEND_FRESH_S = 600
BRIEF_WORDS = 25
KIND_WEIGHT = {"blocked": 3, "gate": 3, "question": 2, "reminder": 0}

_RELEASE_SIGNAL = re.compile(r"\b(app review|testflight|release|store|build|deploy|merge)", re.I)
_RELEASE_PHRASE = re.compile(r"\b(app review|testflight|release|app store|deploy)", re.I)
_SIGN_IN_PHRASE = re.compile(r"\b(sign[ -]?in|log[ -]?in|credential)", re.I)
_MERGE_PHRASE = re.compile(r"\b(merge|pr|pull request)\b", re.I)


# --- ranking ----------------------------------------------------------------------------------

def _text(a: asks.Ask) -> str:
    return f"{a.title}\n{a.question}\n{a.context}"


def unblocks(a: asks.Ask) -> str:
    t = _text(a)
    if _RELEASE_PHRASE.search(t):
        return "a release"
    if _SIGN_IN_PHRASE.search(t):
        return "a sign-in only you can do"
    if _MERGE_PHRASE.search(t):
        return "a merge"
    return ""


def score(a: asks.Ask, now: float) -> int:
    s = KIND_WEIGHT.get(a.kind, 2)
    if _RELEASE_SIGNAL.search(_text(a)):
        s += 3
    if now - a.when < FRESH_S:
        s += 1
    return s


def delivery(a: asks.Ask) -> str:
    """What `teyla answer` tries first for this item."""
    if a.harness == "codex" and a.session:
        return "codex"
    if a.harness in ("claude-desktop", "claude-code") and a.session:
        return "claude"
    return "open"


def _due(a: asks.Ask, today: _dt.date) -> bool:
    from . import remind
    try:
        return remind.days_until(a.due, today) <= 0
    except ValueError:
        return False


def ranked(items: list[asks.Ask], now: float) -> list[dict]:
    today = _dt.datetime.fromtimestamp(now).date()
    open_ = [a for a in items if a.status == "open" and (a.kind != "reminder" or _due(a, today))]
    open_.sort(key=lambda a: (-score(a, now), -a.when))
    out = []
    for i, a in enumerate(open_, 1):
        d = a.to_dict(now)
        d.update(unblocks=unblocks(a), rank=i, delivery=delivery(a))
        out.append(d)
    return out


# --- running sessions -------------------------------------------------------------------------

def _iso(epoch: float) -> str:
    return asks._iso(epoch)


def running_desktop(now: float, root: str | None = None) -> list[dict]:
    root = asks.desktop_root() if root is None else root
    if not os.path.isdir(root):
        return []
    out = []
    for d in asks._desktop_sessions(root):
        if d.get("isArchived"):
            continue
        last = asks._epoch(d.get("lastActivityAt"))
        if last is None or now - last > RUNNING_WINDOW_S:
            continue
        sid = str(d.get("sessionId") or "")
        out.append({"product": asks.product_of(d.get("cwd") or d.get("originCwd")),
                    "title": asks.clip(d.get("title") or "(untitled)", asks.TITLE_MAX),
                    "harness": "claude-desktop", "model": str(d.get("model") or ""),
                    "since": _iso(asks._epoch(d.get("createdAt")) or last),
                    "link": asks.OPEN_LINK + sid if sid.startswith("local_") else "", "_last": last})
    return out


def _codex_head(path: str) -> tuple[dict, str]:
    """session_meta payload and the first model named, from the first few records."""
    meta, model = {}, ""
    for n, o in enumerate(iter_jsonl(path)):
        p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
        if o.get("type") == "session_meta":
            meta = p
        elif o.get("type") == "turn_context" and p.get("model"):
            model = str(p["model"])
        if (meta and model) or n > 30:
            break
    return meta, model


def running_codex(now: float, root: str | None = None) -> list[dict]:
    root = codex.DEFAULT_ROOT if root is None else root
    if not root or not os.path.isdir(root):
        return []
    titles = None
    out = []
    for f in codex._rollouts(root, now - RUNNING_WINDOW_S):
        try:
            last = os.stat(f).st_mtime
        except OSError:
            continue
        if now - last > RUNNING_WINDOW_S:
            continue
        meta, model = _codex_head(f)
        if isinstance(meta.get("source"), dict) and "subagent" in meta["source"]:
            continue
        sid = str(meta.get("session_id") or meta.get("id") or "")
        if not sid:
            continue
        if titles is None:
            titles = codex._load_titles(codex.DEFAULT_INDEX)
        out.append({"product": asks.product_of(meta.get("cwd")),
                    "title": asks.clip(titles.get(sid) or "Codex session", asks.TITLE_MAX),
                    "harness": "codex", "model": model,
                    "since": _iso(asks._epoch(meta.get("timestamp")) or last),
                    "link": f"codex://threads/{sid}", "_last": last})
    return out


def running(now: float, desktop: str | None = None, codex_root: str | None = None) -> list[dict]:
    rows = running_desktop(now, desktop) + running_codex(now, codex_root)
    rows.sort(key=lambda r: -r["_last"])
    return rows


# --- products ---------------------------------------------------------------------------------

def repo_index() -> dict:
    """{name: path} for the repos `teyla products` walks. Cheap: no network, no subprocess."""
    try:
        from . import products
        repos, _ = products.repos_to_probe()
        return {p.name: p for p in repos}
    except Exception:  # noqa: BLE001 — a missing config or code root is "no repos", not a failed snapshot
        return {}


def _repo_signals(path: pathlib.Path, today: _dt.date) -> tuple[float | None, bool]:
    """(time of the last commit or checkout, a release tag written today), from file stamps only."""
    last = None
    for rel in (".git/logs/HEAD", ".git"):
        try:
            last = (path / rel).stat().st_mtime
            break
        except OSError:
            continue
    tagged = False
    try:
        with os.scandir(path / ".git" / "refs" / "tags") as it:
            tagged = any(_dt.datetime.fromtimestamp(e.stat().st_mtime).date() == today for e in it)
    except OSError:
        pass
    return last, tagged


def products_view(items: list[dict], run: list[dict], repos: dict, now: float) -> list[dict]:
    today = _dt.datetime.fromtimestamp(now).date()
    by: dict[str, dict] = {}

    def slot(name):
        return by.setdefault(name, {"waiting": 0, "last": 0.0, "title": "", "title_ts": 0.0, "run": "", "tag": False})
    for a in items:
        s = slot(a["product"])
        s["waiting"] += 1
        ts = asks._epoch(a["ts"]) or 0.0
        s["last"] = max(s["last"], ts)
        if ts >= s["title_ts"]:
            s["title"], s["title_ts"] = a["title"], ts
    for r in run:
        s = slot(r["product"])
        s["last"] = max(s["last"], r["_last"])
        s["run"] = s["run"] or r["title"]
    for name, path in repos.items():
        last, tagged = _repo_signals(path, today)
        if name not in by and (last is None or now - last > REPO_RECENT_DAYS * 86400):
            continue
        s = slot(name)
        s["last"] = max(s["last"], last or 0.0)
        s["tag"] = tagged
    out = []
    for name, s in by.items():
        if not s["waiting"] and (name.startswith("(") or name in ("unknown", "reminders")):
            continue
        idle_days = int((now - s["last"]) // 86400) if s["last"] else None
        if s["waiting"]:
            st = "waiting"
        elif s["run"]:
            st = "active"
        elif s["last"] and idle_days is not None and idle_days >= QUIET_DAYS:
            st = "quiet"
        elif s["tag"]:
            st = "shipped"
        else:
            st = "active"
        if s["title"]:
            line = s["title"]
        elif s["run"]:
            line = s["run"]
        elif st == "shipped":
            line = "release tagged today"
        elif idle_days is None:
            line = "no activity recorded"
        elif idle_days >= 1:
            line = f"no activity for {idle_days} days" if idle_days != 1 else "no activity for 1 day"
        else:
            line = "active today"
        out.append({"name": name, "waiting": s["waiting"], "state": st, "line": line,
                    "last_activity": _iso(s["last"]) if s["last"] else ""})
    out.sort(key=lambda p: (-p["waiting"], p["state"] == "quiet", -(asks._epoch(p["last_activity"]) or 0), p["name"]))
    return out


# --- spend ------------------------------------------------------------------------------------

def _spend_cache() -> pathlib.Path:
    return control.home() / "state-spend.json"


def _local_day(now: float) -> str:
    return _dt.datetime.fromtimestamp(now).date().isoformat()


def compute_spend(now: float) -> float:
    from . import spend
    day = _local_day(now)
    return round(sum((r.get("day_usd") or {}).get(day, 0.0) for r in spend.session_rows(days=1)), 2)


def refresh_spend(now: float | None = None) -> None:
    now = asks._now() if now is None else now
    usd = compute_spend(now)
    asks._atomic_write(_spend_cache(), json.dumps({"day": _local_day(now), "usd": usd, "at": now}))


def _spawn_refresh() -> None:
    lock = control.home() / "state-spend.lock"
    try:
        if lock.exists() and asks._now() - lock.stat().st_mtime < 120:
            return
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.touch()
        subprocess.Popen([sys.executable, "-m", "teyla", "state", "--refresh-spend"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError):
        pass


def spent_today(now: float) -> float | None:
    """Today's spend from the cache; a stale or missing cache starts a background refresh."""
    try:
        c = json.loads(_spend_cache().read_text())
        usd = float(c["usd"]) if c.get("day") == _local_day(now) else None
        fresh = usd is not None and now - float(c.get("at", 0)) < SPEND_FRESH_S
    except (OSError, ValueError, KeyError, TypeError):
        usd, fresh = None, False
    if not fresh:
        _spawn_refresh()
    return usd


# --- the brief --------------------------------------------------------------------------------

def _words(text: str) -> str:
    w = text.split()
    return text if len(w) <= BRIEF_WORDS else " ".join(w[:BRIEF_WORDS - 1]) + "…"


def brief_line(st: dict) -> dict:
    """The one sentence on top. Rules for now; a model-written line plugs in here (source "model")."""
    items = st["asks"]
    if not items:
        return {"line": "Nothing waits on you.", "source": "rules"}
    top = items[:5]
    rel = [a for a in top if a["unblocks"] == "a release"]
    if rel:
        counts: dict[str, int] = {}
        for a in rel:
            counts[a["product"]] = counts.get(a["product"], 0) + 1
        product = max(counts, key=lambda p: (counts[p], -min(a["rank"] for a in rel if a["product"] == p)))
        n = counts[product]
        line = (f"{n} answer{'s' if n != 1 else ''} unblock{'' if n != 1 else 's'} {product}'s release today.")
        rest = [a for a in top if a["product"] != product]
        if rest:
            line += f" {rest[0]['product'].capitalize()} is waiting on you too."
    else:
        n = len(items)
        first = items[0]
        line = (f"{n} question{'s' if n != 1 else ''} wait{'' if n != 1 else 's'} for you, "
                f"the first one in {first['product']}.")
    return {"line": _words(line), "source": "rules"}


# --- the snapshot -----------------------------------------------------------------------------

def build(now: float | None = None, *, days: int = asks.DEFAULT_DAYS, repos: dict | None = None,
          spent="cache", items: list[asks.Ask] | None = None, desktop: str | None = None,
          projects: str | None = None, codex_root: str | None = None, codex_archive: str | None = None,
          reminders: pathlib.Path | None = None) -> dict:
    now = asks._now() if now is None else now
    if items is None:
        items = asks.collect(days, now, desktop=desktop, projects=projects, codex_root=codex_root,
                             codex_archive=codex_archive, reminders=reminders)
    rows = ranked(items, now)
    run = running(now, desktop, codex_root)
    repos = repo_index() if repos is None else repos
    prods = products_view(rows, run, repos, now)
    if spent == "cache":
        try:
            spent = spent_today(now)
        except Exception:  # noqa: BLE001
            spent = None
    st = {"version": VERSION, "generated": _iso(now), "brief": None,
          "totals": {"questions": len(rows), "running": len(run), "spent_today_usd": spent},
          "asks": rows, "products": prods,
          "running": [{k: v for k, v in r.items() if k != "_last"} for r in run]}
    st["brief"] = brief_line(st)
    return st


def render_text(st: dict, now: float) -> str:
    t = st["totals"]
    spent = "n/a" if t["spent_today_usd"] is None else f"${t['spent_today_usd']:.2f}"
    lines = [st["brief"]["line"] if st["brief"] else "",
             f"{t['questions']} waiting, {t['running']} running, {spent} today"]
    for a in st["asks"][:5]:
        why = f"  [{a['unblocks']}]" if a["unblocks"] else ""
        q = a["question"].replace("\n", " ")
        lines.append(f"{a['rank']}. {a['id']} {a['product']}: {q[:70]}{'…' if len(q) > 70 else ''}{why}")
    if len(st["asks"]) > 5:
        lines.append(f"   + {len(st['asks']) - 5} more (teyla asks)")
    for p in st["products"][:4]:
        lines.append(f"{p['name']:14} {p['state']:8} {p['line'][:50]}")
    return "\n".join(lines[:15])


def cmd_state(args) -> int:
    if args.refresh_spend:
        try:
            refresh_spend()
        except Exception:  # noqa: BLE001 — a background job: no spend data is not an error anyone reads
            return 1
        return 0
    now = asks._now()
    st = build(now)
    print(json.dumps(st, indent=1) if args.json else render_text(st, now))
    return 0


def register(sp):
    q = sp.add_parser("state", help="one snapshot for the Teyla for Mac window: ranked questions, products, running sessions")
    q.set_defaults(fn=cmd_state)
    q.add_argument("--json", action="store_true")
    q.add_argument("--refresh-spend", action="store_true", help=argparse.SUPPRESS)
    return q

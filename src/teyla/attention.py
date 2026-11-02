"""`teyla attention` — what is wrong on this Mac's backend now, in one list.

    teyla attention [--json]

The Mac app's Tools page and its command bar read this. It builds the list from what other commands
already know and adds no outbound call of its own: the whole run happens inside `net.offline()`, so a
borrowed reader that would reach GitHub or a store cannot. A source that needs the network is read from
its cache, and the item says how old the cache is.

Items appear only when something is wrong. Healthy things add to the `quiet` counts and nothing else.

    schedule   a scheduled task that is failing, stale, never ran or vanished (`teyla schedules`); the GitHub
               workflows come from the last full run's problems file, with its age
    p1         a PR merged in the last 7 days whose newest review left a P1 open (`teyla portfolio` cache)
    build      a primary platform whose build is behind or blocked (`teyla portfolio` cache)
    disk       free space under the warn line `teyla doctor` uses, with the size a sweep would give back
    offer      a change `teyla start` offers, with its trade-off and its undo, until the owner has answered
    doctor     a FIX or WARN row of the last `teyla doctor` run (its file, with its age)
    guard      the machine guard at CRITICAL
    unknown    a source that failed, timed out, or has a cache too old to trust

A source that cannot be read is a row saying so, never silence: the page says "Nothing needs you here" only
when the list is empty. An action is a command that already exists, with its preview when it has one.
`destructive` is true when the command removes something or cannot be undone. No action charges money, sends a
message, deploys or submits to a store.

JSON: {"generated", "items": [{"id", "kind", "title", "detail", "product", "severity": "act"|"info",
"facts": [{"label", "text"}], "actions": [{"label", "command", "preview", "destructive"}]}], "quiet": {...}}.
`command` and `preview` are arguments of `teyla` (no leading "teyla"). `facts` is optional text the card shows
under the detail (an offer's trade-off and undo, a doctor row's fix).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import shlex
import sys
import threading
import time

from . import config, net

VERSION = 1
KINDS = ("schedule", "p1", "disk", "offer", "doctor", "build", "guard", "unknown")
# Worst first within a severity.
KIND_ORDER = ("guard", "disk", "schedule", "p1", "build", "doctor", "offer", "unknown")
SOURCE_TIMEOUT_S = 40
SWEEP_TIMEOUT_S = 30
TITLE_WORDS = 10
DETAIL_CHARS = 220
SWEEP_WORTH = 256 * 1024 ** 2      # a sweep that gives back less is not offered as the fix
STALE_CACHE_S = 24 * 3600          # a cache older than this no longer says what is true now
DOCTOR_STALE_S = 48 * 3600
HELP = "teyla attention --json"


# --- small helpers -----------------------------------------------------------------------------------------

def _words(text: str, n: int = TITLE_WORDS) -> str:
    w = str(text).split()
    return " ".join(w[:n]) + ("…" if len(w) > n else "")


def _cut(text: str, n: int = DETAIL_CHARS) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _ago(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 3600:
        return f"{max(1, round(s / 60))} min"
    if s < 36 * 3600:
        return f"{round(s / 3600)} h"
    return f"{round(s / 86400)} d"


def _gb(n: float) -> str:
    if n < 1024 ** 3:
        return f"{max(1, round(n / 1024 ** 2))} MB" if n >= 1024 ** 2 else "under 1 MB"
    return f"{n / 1024 ** 3:.1f} GB" if n < 100 * 1024 ** 3 else f"{n / 1024 ** 3:.0f} GB"


def action(label: str, command: list[str], preview: list[str] | None = None, destructive: bool = False) -> dict:
    return {"label": label, "command": list(command), "preview": list(preview) if preview else None,
            "destructive": bool(destructive)}


def item(id_: str, kind: str, title: str, detail: str, *, product: str = "", severity: str = "act",
         facts: list[tuple[str, str]] | None = None, actions: list[dict] | None = None) -> dict:
    assert kind in KINDS and severity in ("act", "info")
    return {"id": id_, "kind": kind, "title": _words(title), "detail": _cut(detail), "product": product,
            "severity": severity, "facts": [{"label": a, "text": _cut(b, 400)} for a, b in facts or []],
            "actions": actions or []}


def unknown_item(source: str, why: str, *, severity: str = "act", actions: list[dict] | None = None) -> dict:
    labels = {"schedules": "Scheduled tasks", "portfolio": "PR and build state", "disk": "Disk", "guard": "Machine load",
              "doctor": "Doctor", "offers": "Offers"}
    return item(f"unknown:{source}", "unknown", f"{labels.get(source, source)} could not be read", why,
                severity=severity, actions=actions)


# --- schedules ----------------------------------------------------------------------------------------------

_PHRASE = {"FAILING": "is failing", "STALE": "has not run on time", "VANISHED": "has vanished",
           "UNREGISTERED": "is not registered", "MISSING DEFINITION": "has no definition", "NEVER RAN": "never ran",
           "PAUSED BUT LOADED": "is paused but still loaded"}


def _schedule_detail(e: dict, now: dt.datetime) -> str:
    from . import schedules
    bits = []
    if e.get("cadence"):
        c = str(e["cadence"])
        bits.append(f"expected every {c}" if re.fullmatch(r"\d+\s?[mhd]", c) else c)
    if e.get("last_run") is not None:
        bits.append(f"last run {schedules.relative(e['last_run'], now)}")
    elif e["verdict"] not in ("VANISHED", "UNREGISTERED", "MISSING DEFINITION"):
        bits.append("no run recorded")
    if e.get("last_exit") not in (None, 0):
        bits.append(f"last exit {e['last_exit']}")
    bits.append(str(e.get("note") or "").split(" — ")[0].strip().rstrip("."))
    return ". ".join(b[:1].upper() + b[1:] for b in bits if b) + "."


def _problems_file_items(now: float) -> list[dict]:
    """The GitHub workflows' problems from the last full `teyla schedules --quiet` run. Reading a workflow's last run
    takes `gh`, so they are the one schedule source read from a file, with the file's age."""
    from . import schedules
    p = schedules.problems_path()
    try:
        lines = p.read_text().splitlines()
        age = max(0.0, now - p.stat().st_mtime)
    except OSError:
        return []
    out = []
    for ln in lines:
        key, _, text = ln.partition("\t")
        parts = key.split("|")
        if len(parts) != 3 or parts[0] != "schedule" or not parts[1].startswith("github:"):
            continue
        eid, verdict = parts[1], parts[2]
        name = eid.split(":", 1)[1]
        out.append(item(f"schedule:{eid}", "schedule", f"{name} {_PHRASE.get(verdict, verdict.lower())}",
                        f"{text.strip()} (last full check {_ago(age)} ago)."))
    return out


def source_schedules(now: float, cfg: dict) -> tuple[list[dict], dict]:
    from . import schedules
    when = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    entries, _cron = schedules.collect(when, allow_network=False, cfg=cfg)
    reg = schedules.load_registry()
    schedules.forget_ignored(reg, schedules.ignore_prefixes(cfg))
    full = schedules.apply_registry(entries, reg, when)          # in memory only: this command saves nothing
    items = []
    for e in sorted((x for x in full if schedules.is_problem(x)), key=schedules._sort_key):
        v = e["verdict"]
        acts = []
        if v == "VANISHED":
            acts.append(action("Forget", ["schedules", "forget", e["id"]], destructive=True))
        product = e["name"].split(":", 1)[0] if e["source"] == "routines" and ":" in e["name"] else ""
        items.append(item(f"schedule:{e['id']}", "schedule", f"{e['name']} {_PHRASE.get(v, v.lower())}",
                          _schedule_detail(e, when), product=product, actions=acts))
    items += _problems_file_items(now)
    ok = sum(1 for e in full if e["verdict"] == "OK")
    unverified = sum(1 for e in full if e["verdict"] == "UNKNOWN")
    quiet = {"schedules": ok}
    if unverified:
        quiet["schedules_unverified"] = unverified
    return items, quiet


# --- portfolio: P1s and builds -----------------------------------------------------------------------------

def source_portfolio(now: float, cfg: dict) -> tuple[list[dict], dict]:
    from . import asks, backlog, portfolio, registry, reviews
    cache = portfolio.load_cache()
    reg = registry.load()
    bl = backlog.view(now, refresh=False)
    ledger = reviews.load_ledger(reviews.ledger_path(cfg)) if cache["github"] else None
    threshold = reviews.min_lines(cfg)
    pf = portfolio.build(now, reg=reg, prods=[], ask_rows=[], tasks=[], bl=bl, ledger=ledger, cache=cache, threshold=threshold)
    items: list[dict] = []
    refresh = [action("Check now", ["portfolio", "--refresh"])]
    checked = cache["checked"]
    for part, what in (("github", "PR reviews"), ("stores", "store builds")):
        stamp = checked.get(part) or ""
        at = asks._epoch(stamp) if stamp else None
        if at is None:
            items.append(item(f"unknown:portfolio-{part}", "unknown", f"{what.capitalize()} were never read",
                              f"No successful read of {what} is cached, so problems there would not show.",
                              severity="info", actions=refresh))
        elif now - at > STALE_CACHE_S:
            items.append(item(f"unknown:portfolio-{part}", "unknown", f"{what.capitalize()} are {_ago(now - at)} old",
                              f"The last successful read of {what} was {_ago(now - at)} ago, so newer problems would not show.",
                              severity="info", actions=refresh))
    github_age = _ago(now - asks._epoch(checked["github"])) if checked.get("github") and asks._epoch(checked["github"]) else ""
    builds_ok = 0
    for p in pf["products"]:
        if p["stage"] == "parked":
            continue
        repos = portfolio.product_repos(reg["product"][p["id"]])
        slugs = portfolio._slugs(repos, bl.get("canonical") or {})
        names = {r.name.lower() for r in repos}
        bad = [pr for pr in portfolio.merged_pr_states(slugs, names, cache, ledger, threshold, now) if pr["state"] == "open_p1"]
        if bad:
            # One row per product: the list stays short and a new P1 changes the number, not the row's id.
            nums = ", ".join(f"#{pr['number']}" for pr in sorted(bad, key=lambda x: x["number"]))
            total = sum(int(pr["p1"] or 0) for pr in bad)
            oldest = max(0, int((now - min(pr["merged_at"] for pr in bad)) // 86400))
            many = len(bad) > 1
            items.append(item(f"p1:{p['id']}", "p1",
                              f"{p['title']}: {len(bad)} merged PR{'s' if many else ''} with an open P1",
                              f"{nums}: {total} open P1 and no later review; the oldest merged {oldest} d ago"
                              + (f" (GitHub read {github_age} ago)." if github_age else "."), product=p["id"]))
        if p["stage"] not in ("building", "beta", "live"):
            continue
        row = next((r for r in p["platforms"] if r["platform"] == p["primary"]), None)
        if row is None:
            continue
        if row["state"] in ("behind", "blocked"):
            items.append(item(f"build:{p['id']}:{row['platform']}", "build",
                              f"{p['title']}: {row['platform']} build is {row['state']}",
                              row["detail"] or f"The newest {row['platform']} build is {row['state']}.", product=p["id"]))
        elif row["state"] in ("current", "live", "in_review"):
            builds_ok += 1
    return items, {"builds": builds_ok}


# --- disk --------------------------------------------------------------------------------------------------

def _sweep_total(cfg: dict) -> int | None:
    """Bytes a full sweep would remove, from its dry run; None when it did not finish in time."""
    from . import storage_sweep
    box: dict = {}

    def work():
        try:
            box["total"] = sum(c["bytes"] for c in storage_sweep.sweepable(cfg))
        except Exception as e:  # noqa: BLE001 — a size is an extra; the disk row stands without it
            box["error"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(SWEEP_TIMEOUT_S)
    return box.get("total")


def source_disk(now: float, cfg: dict) -> tuple[list[dict], dict]:
    from . import storage
    d = storage.disk()
    free = _gb(d["free"]) + " free"
    if d["free_fraction"] >= storage.LOW_FREE_FRACTION and d["free"] >= storage.LOW_FREE_BYTES:
        return [], {"disk": free}
    total = _sweep_total(cfg)
    pct = f"{d['free_fraction']:.0%} of the disk is free"
    acts = []
    if total is None:
        size = "The sweep preview did not finish in time."
        acts.append(action("Free space", ["storage", "sweep"], ["storage", "sweep", "--dry"], destructive=True))
    elif total >= SWEEP_WORTH:
        size = f"A sweep would give back about {_gb(total)}."
        acts.append(action("Free space", ["storage", "sweep"], ["storage", "sweep", "--dry"], destructive=True))
    else:
        size = f"A sweep would give back almost nothing ({_gb(total)}); `teyla storage` lists what else holds space."
    return [item("disk:free", "disk", f"Disk is low: {_gb(d['free'])} free", f"{pct}. {size}", actions=acts)], {"disk": free}


# --- the machine guard ------------------------------------------------------------------------------------

def source_guard(now: float, cfg: dict) -> tuple[list[dict], dict]:
    from . import load
    conf = load.guard_conf(cfg)
    if not load.enabled(conf):
        return [], {"guard": "off"}
    snap = load.safe_snapshot()
    if snap is None:
        return [unknown_item("guard", "The process table could not be read, so the machine load is unknown.", severity="info")], {}
    verdict = load.assess(snap, conf)
    quiet = {"guard": verdict.level.lower()}
    if verdict.level != load.CRITICAL:
        return [], quiet
    reasons = "; ".join(verdict.reasons[:3])
    return [item("guard:critical", "guard", f"Machine is critical: {verdict.reasons[0] if verdict.reasons else 'overloaded'}",
                 f"{reasons}. Start no build or simulator; `teyla load` shows the detail.")], quiet


# --- doctor -----------------------------------------------------------------------------------------------

# Rows another source already covers with live data.
_DOCTOR_SKIP = ("machine:load", "storage:disk")
# A FIX that is not a fault: the owner chooses when to update.
_DOCTOR_INFO = ("version", "update")


def _doctor_label(name: str) -> str:
    group, _, rest = name.partition(":")
    rest = rest.replace("-", " ").replace("_", " ").strip()
    if group == "remind":
        return rest or "Reminder"
    return f"{group.replace('-', ' ').capitalize()}: {rest}" if rest else group.capitalize()


def source_doctor(now: float, cfg: dict) -> tuple[list[dict], dict]:
    from . import doctor
    p = pathlib.Path(doctor.DOCTOR_JSON)
    try:
        rec = json.loads(p.read_text())
        at = dt.datetime.fromisoformat(str(rec["at"])).timestamp()
        rows = [c for c in rec.get("checks") or [] if isinstance(c, dict)]
    except FileNotFoundError:
        return [item("unknown:doctor", "unknown", "Doctor has never run", "No doctor result is stored, so a broken setup would not show.",
                     severity="info")], {"doctor": "never run"}
    except (OSError, ValueError, KeyError, TypeError) as e:
        return [unknown_item("doctor", f"The stored doctor result is unreadable ({type(e).__name__}).", severity="info")], {}
    items = []
    bad = 0
    for c in rows:
        level, name = str(c.get("level")), str(c.get("name"))
        if level not in ("FIX", "WARN") or name in _DOCTOR_SKIP:
            continue
        bad += 1
        act = level == "FIX" and name not in _DOCTOR_INFO
        fix = str(c.get("fix") or "")
        items.append(item(f"doctor:{name}", "doctor", _doctor_label(name), str(c.get("detail", "")),
                          severity="act" if act else "info", facts=[("Fix", fix)] if fix else None))
    age = now - at
    if age > DOCTOR_STALE_S:
        items.append(item("unknown:doctor-age", "unknown", f"Doctor last ran {_ago(age)} ago",
                          f"The stored doctor result is {_ago(age)} old, so a new fault would not show.", severity="info"))
        return items, {"doctor": f"{_ago(age)} old"}
    return items, {"doctor": "ok" if not bad else f"{bad} to look at"}


# --- offers -----------------------------------------------------------------------------------------------

def source_offers(now: float, cfg: dict) -> tuple[list[dict], dict]:
    """The changes `teyla start` offers, until the owner has answered the offers once. Nothing here has a price:
    each is a local change with a backup."""
    from . import figures, offers as offers_mod
    if figures.onboarded():
        return [], {"offers": "answered"}
    live = [o for o in offers_mod.build(with_savings=False) if o.applies]
    items = []
    for o in live:
        irreversible = "teyla undo" not in o.undo           # every offer today has one; a future one without is confirmed
        items.append(item(f"offer:{o.id}", "offer", o.title, o.change.get("summary") or o.short, severity="info",
                          facts=[("Trade-off", o.tradeoff), ("Undo", o.undo)],
                          actions=[action("Apply", ["apply", o.id, "--yes"], ["apply", o.id, "--dry"], destructive=irreversible)]))
    return items, {"offers": len(live) if live else "none"}


SOURCES = {"schedules": source_schedules, "portfolio": source_portfolio, "disk": source_disk, "guard": source_guard,
           "doctor": source_doctor, "offers": source_offers}


# --- the report -------------------------------------------------------------------------------------------

def _run(sources: dict, now: float, cfg: dict, timeout: float) -> dict:
    """Every source on its own thread; whichever has not answered by the deadline is reported as timed out."""
    out: dict = {}

    def work(name, fn):
        try:
            out[name] = ("ok", fn(now, cfg))
        except Exception as e:  # noqa: BLE001 — one failing source must become a row, not a missing report
            out[name] = ("error", f"{type(e).__name__}: {e}")

    threads = {name: threading.Thread(target=work, args=(name, fn), daemon=True) for name, fn in sources.items()}
    for t in threads.values():
        t.start()
    deadline = time.monotonic() + timeout
    for t in threads.values():
        t.join(max(0.0, deadline - time.monotonic()))
    return out


def _sort_key(it: dict):
    return (0 if it["severity"] == "act" else 1, KIND_ORDER.index(it["kind"]) if it["kind"] in KIND_ORDER else 99, it["title"].lower())


def collect(now: float | None = None, *, sources: dict | None = None, cfg: dict | None = None,
            timeout: float = SOURCE_TIMEOUT_S) -> dict:
    now = time.time() if now is None else now
    cfg = config.load() if cfg is None else cfg
    srcs = SOURCES if sources is None else sources
    with net.offline():
        got = _run(srcs, now, cfg, timeout)
    items: list[dict] = []
    quiet: dict = {}
    for name in srcs:
        state = got.get(name)
        if state is None:
            items.append(unknown_item(name, f"It did not answer in {int(timeout)} s, so nothing is known about it."))
        elif state[0] == "error":
            items.append(unknown_item(name, f"It failed: {_cut(state[1], 140)}"))
        else:
            part_items, part_quiet = state[1]
            items += part_items
            quiet.update(part_quiet)
    items.sort(key=_sort_key)
    return {"version": VERSION, "generated": dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(timespec="seconds"),
            "items": items, "quiet": quiet}


# --- output -----------------------------------------------------------------------------------------------

def command_text(argv: list[str]) -> str:
    return "teyla " + " ".join(shlex.quote(a) for a in argv)


def render_text(rep: dict) -> str:
    items = rep["items"]
    act = [i for i in items if i["severity"] == "act"]
    quiet = " · ".join(f"{k} {v}" for k, v in rep["quiet"].items())
    if not items:
        return "Nothing needs you here." + (f" Quiet: {quiet}." if quiet else "") + "\n"
    out = [f"{len(act)} need you, {len(items) - len(act)} to look at" + (f". Quiet: {quiet}." if quiet else ".")]
    for it in items:
        out.append(f"{'ACT ' if it['severity'] == 'act' else 'INFO'} {it['title']}")
        out.append(f"     {it['detail']}")
        for f in it["facts"]:
            out.append(f"     {f['label']}: {f['text']}")
        for a in it["actions"]:
            line = f"     → {a['label']}: {command_text(a['command'])}"
            if a["preview"]:
                line += f"   (preview: {command_text(a['preview'])})"
            out.append(line + ("   [cannot be undone]" if a["destructive"] else ""))
    return "\n".join(out) + "\n"


def cmd_attention(args) -> int:
    rep = collect()
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        sys.stdout.write(render_text(rep))
    return 0


def register(sp):
    q = sp.add_parser("attention", help="what is wrong on this Mac's backend now, in one list (read-only, no network)")
    q.set_defaults(fn=cmd_attention)
    q.add_argument("--json", action="store_true", help="the list as JSON, for the Mac app")
    return q

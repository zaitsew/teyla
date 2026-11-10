"""Usage capture from test builds: the Mac side (packages/review-ios, docs/REVIEW.md "Usage capture").

    teyla usage <product> [--since YYYY-MM-DD] [--before BUILD] [--after BUILD] [--variant ID=NAME] [--json]

A test build records which screens and actions are used, how long a named job takes, dead ends and repeat
taps: ids from a list the app declared, never content. `teyla review pull --channel` copies the batches the
builds sent from the server into `~/.teyla/usage/<product>/<batch id>.json` and deletes the server copy. This
command only reads those files. It makes no network call and prints no install id.

Every batch is checked again here: a wrong shape is refused, and an event whose fields are not in the fixed
vocabulary is dropped, so a hand-made batch cannot put a sentence into the store.

`--before BUILD` keeps builds up to and including BUILD, `--after BUILD` keeps BUILD and later. Given both,
the report is two columns: the builds up to the first, and from the second on, for a decision's before/after.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import statistics
import sys
import time
from collections import Counter, defaultdict

from . import config
from .control import state as control

KINDS = ("session", "screen", "action", "task", "dead_end", "repeat_tap")
RESULTS = {
    "session": {"start", "background", "end"},
    "screen": {None},
    "action": {"done", "cancelled", "error", "undone"},
    "task": {"start", "success", "cancel"},
    "dead_end": {"screen", "sheet"},
    "repeat_tap": {None},
}
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,39}$")
BUILD = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,19}$")
MAX_JSON = 256 * 1024
MAX_MS = 10 * 24 * 3600 * 1000
MAX_DECLARED = 500
RETENTION_DAYS = 180            # what the first-send notice promises a tester
TOP = 10


def usage_home() -> pathlib.Path:
    return control.home() / "usage"


def product_dir(product: str) -> pathlib.Path:
    return usage_home() / product


# --- the import (called by `teyla review pull --channel`) --------------------------------------

def _clean_event(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    t, k, b = raw.get("t"), raw.get("k"), raw.get("b")
    if isinstance(t, bool) or not isinstance(t, int) or not (1_500_000_000 <= t <= 4_000_000_000):
        return None
    if not isinstance(k, str) or k not in KINDS or not isinstance(b, str) or not BUILD.match(b):
        return None
    out: dict = {"t": t, "k": k, "b": b}
    ident = raw.get("id")
    if k == "session":
        if ident is not None:
            return None
    elif not isinstance(ident, str) or not ID.match(ident):
        return None
    else:
        out["id"] = ident
    r = raw.get("r")
    if (r is not None and not isinstance(r, str)) or r not in RESULTS[k]:
        return None
    if r is not None:
        out["r"] = r
    ms = raw.get("ms")
    if ms is not None:
        if isinstance(ms, bool) or not isinstance(ms, int) or not (0 <= ms <= MAX_MS):
            return None
        out["ms"] = ms
    d = raw.get("d")
    if d is not None:
        if not isinstance(d, dict) or len(d) > 20 or not all(isinstance(a, str) and isinstance(v, str)
                                                            and TOKEN.match(a) and TOKEN.match(v) for a, v in d.items()):
            return None
        out["d"] = dict(sorted(d.items()))
    return out


def _safe_event(raw) -> dict | None:
    """One bad event is dropped; it never stops the batch or the pull."""
    try:
        return _clean_event(raw)
    except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
        return None


def _clean_declared(raw) -> dict:
    out = {"screens": [], "actions": [], "tasks": []}
    if not isinstance(raw, dict):
        return out
    for key in out:
        items = raw.get(key)
        if isinstance(items, list):
            out[key] = sorted({i for i in items[:MAX_DECLARED] if isinstance(i, str) and ID.match(i)})
    return out


def import_folder(product: str, folder: pathlib.Path, now: float | None = None) -> dict:
    """Check one `usage.json` batch and store it. {ok, events, dropped, known, why}. `ok` False means the batch
    is not a usage batch this Mac can read; the caller leaves the server copy alone."""
    rep = {"ok": False, "events": 0, "dropped": 0, "known": False, "why": ""}
    if not SLUG.match(product) or not UUID.match(folder.name):
        rep["why"] = "not a usage batch path"
        return rep
    path = folder / "usage.json"
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
            rep["why"] = "usage.json is missing, a link, or over 256 KiB"
            return rep
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rep["why"] = "usage.json cannot be read"
        return rep
    app = obj.get("app") if isinstance(obj, dict) else None
    if (not isinstance(obj, dict) or obj.get("v") != 1 or isinstance(obj.get("v"), bool) or obj.get("kind") != "usage"
            or obj.get("id") != folder.name or not isinstance(app, dict) or app.get("product") != product
            or not isinstance(obj.get("events"), list)):
        rep["why"] = "not a usage batch for this product"
        return rep
    install = obj.get("install")
    if not isinstance(install, str) or not UUID.match(install):
        rep["why"] = "no valid install id"
        return rep
    sent = obj.get("sent")
    if not isinstance(sent, str) or len(sent) > 40:
        sent = ""
    events = [e for e in (_safe_event(x) for x in obj["events"]) if e]
    rep.update(ok=True, events=len(events), dropped=len(obj["events"]) - len(events))
    dest = product_dir(product) / f"{folder.name}.json"
    if dest.exists():
        rep["known"] = True
        return rep
    clean = {"v": 1, "id": folder.name, "install": install, "sent": sent,
             "build": str(app.get("build") or "")[:20] if BUILD.match(str(app.get("build") or "")) else "",
             "declared": _clean_declared(obj.get("declared")), "events": events}
    config.private_dir(dest.parent)
    tmp = dest.with_name(f".{dest.name}.tmp")
    tmp.write_text(json.dumps(clean, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(dest)
    return rep


def prune(now: float | None = None, days: int = RETENTION_DAYS) -> int:
    """Delete batches whose newest event is older than the retention the notice promises. Returns how many."""
    cutoff = (now if now is not None else time.time()) - days * 86400
    gone = 0
    root = usage_home()
    if not root.is_dir():
        return 0
    for pdir in root.iterdir():
        if pdir.is_symlink() or not pdir.is_dir():
            continue
        for f in pdir.glob("*.json"):
            try:
                newest = max((e["t"] for e in json.loads(f.read_text(encoding="utf-8")).get("events", [])), default=0)
                stale = (newest or f.stat().st_mtime) < cutoff
            except (OSError, ValueError, KeyError, TypeError):
                stale = False
            if stale:
                f.unlink(missing_ok=True)
                gone += 1
    return gone


# --- reading and reporting ----------------------------------------------------------------------

def load(product: str) -> list[dict]:
    """Every stored batch of a product, oldest `sent` first."""
    out = []
    for f in sorted(product_dir(product).glob("*.json")) if product_dir(product).is_dir() else []:
        try:
            if f.is_symlink() or f.stat().st_size > 2 * MAX_JSON:
                continue
            obj = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("events"), list) and isinstance(obj.get("install"), str):
            out.append(obj)
    out.sort(key=lambda b: (b.get("sent") or "", b.get("id") or ""))
    return out


def build_key(build: str) -> tuple:
    """Numbers compare as numbers ("9" before "10"); anything else compares as text after them."""
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in re.split(r"[._-]", build) if p)


def parse_since(text: str) -> float:
    return dt.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()


def select(batches: list[dict], *, since: float | None = None, upto: str | None = None, from_build: str | None = None,
           variant: tuple[str, str] | None = None) -> list[tuple[str, dict]]:
    """(install, event) pairs that pass the filters."""
    pairs = []
    for b in batches:
        for e in b["events"]:
            if since is not None and e["t"] < since:
                continue
            if upto is not None and build_key(e["b"]) > build_key(upto):
                continue
            if from_build is not None and build_key(e["b"]) < build_key(from_build):
                continue
            if variant is not None and (e.get("d") or {}).get(variant[0]) != variant[1]:
                continue
            pairs.append((b["install"], e))
    return pairs


def _active_seconds(per_install: dict[str, list[dict]]) -> tuple[int, float]:
    """Visits (a start) and seconds from each start to the next background or end. Time away is not counted."""
    visits, seconds = 0, 0.0
    for events in per_install.values():
        opened = None
        for e in sorted((x for x in events if x["k"] == "session"), key=lambda x: x["t"]):
            if e["r"] == "start":
                visits += 1
                opened = e["t"]
            elif opened is not None:
                seconds += max(0, e["t"] - opened)
                opened = None
    return visits, seconds


def report(batches: list[dict], **filters) -> dict:
    pairs = select(batches, **filters)
    per_install: dict[str, list[dict]] = defaultdict(list)
    for install, e in pairs:
        per_install[install].append(e)
    events = [e for _, e in pairs]
    screens, actions = Counter(), Counter()
    screen_installs: dict[str, set] = defaultdict(set)
    action_results: dict[str, Counter] = defaultdict(Counter)
    task_rows: dict[str, dict] = defaultdict(lambda: {"start": 0, "success": 0, "cancel": 0, "ms": []})
    dead, repeats = Counter(), Counter()
    for install, e in pairs:
        k, i = e["k"], e.get("id")
        if k == "screen":
            screens[i] += 1
            screen_installs[i].add(install)
        elif k == "action":
            actions[i] += 1
            action_results[i][e["r"]] += 1
        elif k == "task":
            row = task_rows[i]
            row[e["r"]] += 1
            if e["r"] == "success" and "ms" in e:
                row["ms"].append(e["ms"])
        elif k == "dead_end":
            dead[(i, e["r"])] += 1
        elif k == "repeat_tap":
            repeats[i] += 1
    declared = None
    for b in reversed(batches):                        # the newest batch with events in the selection
        if b.get("declared") and any(b["declared"].values()) and select([b], **filters):
            declared = b["declared"]
            break
    opened = set(screens)
    visits, seconds = _active_seconds(per_install)
    tasks = {}
    for name, row in sorted(task_rows.items()):
        tasks[name] = {"started": row["start"], "succeeded": row["success"], "cancelled": row["cancel"],
                       "median_seconds": round(statistics.median(row["ms"]) / 1000, 1) if row["ms"] else None,
                       "timed": len(row["ms"])}
    times = [e["t"] for e in events]
    return {
        "events": len(events),
        "installs": len(per_install),
        "builds": sorted({e["b"] for e in events}, key=build_key),
        "from": dt.datetime.fromtimestamp(min(times), dt.timezone.utc).strftime("%Y-%m-%d") if times else None,
        "to": dt.datetime.fromtimestamp(max(times), dt.timezone.utc).strftime("%Y-%m-%d") if times else None,
        "visits": visits,
        "active_minutes": round(seconds / 60, 1),
        "top_screens": [{"id": i, "opens": n, "installs": len(screen_installs[i])} for i, n in screens.most_common(TOP)],
        "top_actions": [{"id": i, "count": n, "results": dict(sorted(action_results[i].items()))}
                        for i, n in actions.most_common(TOP)],
        "tasks": tasks,
        "never_opened": sorted(set(declared["screens"]) - opened) if declared else None,
        "dead_ends": [{"id": i, "reason": r, "count": n} for (i, r), n in dead.most_common(TOP)],
        "dead_end_rate": round(sum(n for (_, r), n in dead.items() if r == "screen") / max(1, sum(screens.values())), 3),
        "repeat_taps": [{"id": i, "count": n} for i, n in repeats.most_common(TOP)],
    }


def _lines(rep: dict, title: str) -> list[str]:
    out = [title]
    if not rep["events"]:
        return out + ["  no events"]
    out.append(f"  {rep['events']} events from {rep['installs']} install(s), {rep['from']} to {rep['to']}; builds {', '.join(rep['builds'])}")
    out.append(f"  {rep['visits']} visits, {rep['active_minutes']} active minutes (time in the background is not counted)")
    if rep["top_screens"]:
        out.append("  top screens:")
        out += [f"    {r['opens']:>5}  {r['id']}  ({r['installs']} install(s))" for r in rep["top_screens"]]
    if rep["top_actions"]:
        out.append("  top actions:")
        out += [f"    {r['count']:>5}  {r['id']}  " + " ".join(f"{k}={v}" for k, v in r["results"].items()) for r in rep["top_actions"]]
    if rep["tasks"]:
        out.append("  tasks (median seconds from start to success):")
        for name, t in rep["tasks"].items():
            med = f"{t['median_seconds']} s over {t['timed']}" if t["median_seconds"] is not None else "no timed success"
            out.append(f"    {name}: {med}; started {t['started']}, succeeded {t['succeeded']}, cancelled {t['cancelled']}")
    if rep["never_opened"] is None:
        out.append("  never opened: the builds sent no declared screen list")
    else:
        out.append("  declared screens never opened: " + (", ".join(rep["never_opened"]) or "none"))
    out.append(f"  dead ends ({rep['dead_end_rate']:.1%} of screen opens):" if rep["dead_ends"] else "  dead ends: none")
    out += [f"    {r['count']:>5}  {r['id']}  ({r['reason']})" for r in rep["dead_ends"]]
    out.append("  repeat taps (3 in a second):" if rep["repeat_taps"] else "  repeat taps: none")
    out += [f"    {r['count']:>5}  {r['id']}" for r in rep["repeat_taps"]]
    return out


def cmd_usage(args) -> int:
    product = args.product
    if not SLUG.match(product or ""):
        print(f"teyla usage: '{product}' is not a product slug (lowercase letters, digits and dashes)", file=sys.stderr)
        return 2
    since = None
    if args.since:
        try:
            since = parse_since(args.since)
        except ValueError:
            print("teyla usage: --since must be a date, YYYY-MM-DD", file=sys.stderr)
            return 2
    variant = None
    if args.variant:
        decision, _, name = args.variant.partition("=")
        if not TOKEN.match(decision) or not TOKEN.match(name):
            print("teyla usage: --variant must look like decision=variant (lowercase letters, digits, dot, dash)", file=sys.stderr)
            return 2
        variant = (decision, name)
    for flag in (args.before, args.after):
        if flag is not None and not BUILD.match(flag):
            print("teyla usage: a build looks like 212 or 1.4.0", file=sys.stderr)
            return 2
    batches = load(product)
    if not batches:
        print(f"teyla usage: no usage events for {product} yet. A test build sends them when the app has a channel and the "
              f"tester allowed it; `teyla review pull --channel` collects them.", file=sys.stderr)
        return 1
    common = {"since": since, "variant": variant}
    if args.before is not None and args.after is not None:
        data = {"before": report(batches, upto=args.before, **common), "after": report(batches, from_build=args.after, **common)}
        lines = _lines(data["before"], f"{product}: builds up to {args.before} (before)") + [""] \
            + _lines(data["after"], f"{product}: builds from {args.after} on (after)")
    else:
        data = report(batches, upto=args.before, from_build=args.after, **common)
        label = f", builds up to {args.before}" if args.before else (f", builds from {args.after} on" if args.after else "")
        lines = _lines(data, f"{product}{label}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print("\n".join(lines))
    return 0


def register(sp):
    q = sp.add_parser("usage", help="usage events from test builds: top screens and actions, time per job, dead ends, repeat taps")
    q.set_defaults(fn=cmd_usage)
    q.add_argument("product", help="the product slug the build's channel key was made for")
    q.add_argument("--since", metavar="DATE", help="only events on or after this day (YYYY-MM-DD, UTC)")
    q.add_argument("--before", metavar="BUILD", help="only builds up to and including BUILD; with --after, the 'before' column")
    q.add_argument("--after", metavar="BUILD", help="only BUILD and later; with --before, the 'after' column")
    q.add_argument("--variant", metavar="DECISION=NAME", help="only events recorded while this design variant was on")
    q.add_argument("--json", action="store_true")
    return q

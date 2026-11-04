"""`teyla subs` — the owner's recurring bills, in one file the console reads.

    teyla subs [list] [--json]
    teyla subs add NAME [--monthly USD] [--category ai|cloud|tool|domain] [--renews YYYY-MM-DD]
                        [--credits USD] [--note TEXT]
    teyla subs set NAME [the same options; `none` clears one]
    teyla subs remove NAME

The file is `~/.teyla/subscriptions.toml` (mode 0600, outside every repo). Teyla cannot read a bill from a
bank, so this list is what the owner states and nothing else: a field left out is `null`, never a guess.

    [[subscription]]
    name = "Claude"            # unique, case-insensitive
    monthly_usd = 200.0        # cash per month; leave it out when unknown
    category = "ai"            # ai | cloud | tool | domain
    renews = "2026-12-01"      # next renewal, an ISO date
    credits_usd = 200.0        # API credits the plan includes per month
    note = "free text"

`teyla console money` sums `monthly_usd` into the forecast and names every row that has none.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import pathlib
import sys
import tomllib

from . import config
from .control import state as control

CATEGORIES = ("ai", "cloud", "tool", "domain")
FIELDS = ("name", "monthly_usd", "category", "renews", "credits_usd", "note")
HEADER = ("# Recurring bills, kept by `teyla subs`. A field left out is unknown, never estimated.\n"
          "# monthly_usd is cash per month; credits_usd is API credit the plan includes.\n\n")


class SubsError(ValueError):
    """A broken file or a bad value, worded for the person who has to fix it."""


def path() -> pathlib.Path:
    return control.home() / "subscriptions.toml"


# --- values ------------------------------------------------------------------------------------------------

def _usd(v, field: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise SubsError(f"{field} must be a number of US dollars, not {v!r}")
    try:
        x = float(v)
    except ValueError:
        raise SubsError(f"{field} must be a number of US dollars, not {v!r}") from None
    if not math.isfinite(x) or x < 0:
        raise SubsError(f"{field} must be zero or more, not {v!r}")
    return round(x, 2)


def _category(v) -> str | None:
    if v is None:
        return None
    c = str(v).strip().lower()
    if c not in CATEGORIES:
        raise SubsError(f"category must be one of {', '.join(CATEGORIES)}, not {v!r}")
    return c


def _renews(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (dt.date, dt.datetime)):
        return (v.date() if isinstance(v, dt.datetime) else v).isoformat()
    try:
        return dt.date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        raise SubsError(f"renews must be a date like 2026-12-01, not {v!r}") from None


def _note(v) -> str | None:
    if v is None:
        return None
    t = " ".join(str(v).split())
    return t[:300] or None


def clean(raw: dict) -> dict:
    """One row with every field present (`None` for unknown) and each value checked."""
    name = " ".join(str(raw.get("name") or "").split())
    if not name:
        raise SubsError("a subscription needs a name")
    return {"name": name, "monthly_usd": _usd(raw.get("monthly_usd"), "monthly_usd"),
            "category": _category(raw.get("category")), "renews": _renews(raw.get("renews")),
            "credits_usd": _usd(raw.get("credits_usd"), "credits_usd"), "note": _note(raw.get("note"))}


# --- the file ----------------------------------------------------------------------------------------------

def load(p: pathlib.Path | None = None) -> list[dict]:
    """The rows, in file order. A missing file is an empty list; a file that does not parse raises
    `SubsError` naming the path, so the console shows why instead of an empty money page."""
    p = p or path()
    try:
        text = p.read_text()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise SubsError(f"{p} cannot be read: {e}") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise SubsError(f"{p} is not valid TOML: {e}") from None
    items = data.get("subscription", [])
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise SubsError(f"{p}: `subscription` must be a list of [[subscription]] tables")
    rows, seen = [], set()
    for i, raw in enumerate(items, 1):
        try:
            row = clean(raw)
        except SubsError as e:
            raise SubsError(f"{p}: subscription #{i}: {e}") from None
        if row["name"].lower() in seen:
            raise SubsError(f"{p}: {row['name']!r} is listed twice")
        seen.add(row["name"].lower())
        rows.append(row)
    return rows


def _toml_value(v) -> str:
    if isinstance(v, float):
        return repr(v)
    return json.dumps(v, ensure_ascii=False)          # a JSON string is a valid TOML basic string


def dumps(rows: list[dict]) -> str:
    out = [HEADER]
    for r in rows:
        out.append("[[subscription]]\n")
        for f in FIELDS:
            if r.get(f) is not None:
                out.append(f"{f} = {_toml_value(r[f])}\n")
        out.append("\n")
    return "".join(out).rstrip("\n") + "\n"


def save(rows: list[dict], p: pathlib.Path | None = None) -> None:
    config.write_private(p or path(), dumps(rows))


def _find(rows: list[dict], name: str) -> int | None:
    key = " ".join(name.split()).lower()
    for i, r in enumerate(rows):
        if r["name"].lower() == key:
            return i
    return None


def add(name: str, **fields) -> dict:
    rows = load()
    if _find(rows, name) is not None:
        raise SubsError(f"{name!r} is already listed; change it with `teyla subs set`")
    row = clean({"name": name, **fields})
    save(rows + [row])
    return row


def update(name: str, **fields) -> dict:
    """Change the given fields; a value of `None` clears that field."""
    rows = load()
    i = _find(rows, name)
    if i is None:
        raise SubsError(f"{name!r} is not listed (`teyla subs` shows the list)")
    rows[i] = clean({**rows[i], **fields})
    save(rows)
    return rows[i]


def remove(name: str) -> dict:
    rows = load()
    i = _find(rows, name)
    if i is None:
        raise SubsError(f"{name!r} is not listed (`teyla subs` shows the list)")
    gone = rows.pop(i)
    save(rows)
    return gone


# --- totals ------------------------------------------------------------------------------------------------

def forecast(rows: list[dict]) -> dict:
    """The monthly cash the rows add up to, and the rows that have no price. A row without `monthly_usd` adds
    nothing and is named: the forecast is a floor, never an estimate."""
    priced = [r for r in rows if r["monthly_usd"] is not None]
    return {"monthly_usd": round(sum(r["monthly_usd"] for r in priced), 2) if priced else None,
            "priced": len(priced), "unpriced": [r["name"] for r in rows if r["monthly_usd"] is None]}


# --- command -----------------------------------------------------------------------------------------------

def _money(x: float | None) -> str:
    return "-" if x is None else f"${x:,.2f}".replace(".00", "")


def render(rows: list[dict]) -> str:
    if not rows:
        return (f"no subscriptions listed ({path()})\n"
                "add one with: teyla subs add NAME --monthly USD --category ai|cloud|tool|domain\n")
    w = max(len(r["name"]) for r in rows)
    lines = [f"{'name':<{w}}  {'monthly':>9}  {'category':<8}  {'renews':<10}  {'credits':>8}  note"]
    for r in rows:
        lines.append(f"{r['name']:<{w}}  {_money(r['monthly_usd']):>9}  {r['category'] or '-':<8}  "
                     f"{r['renews'] or '-':<10}  {_money(r['credits_usd']):>8}  {r['note'] or ''}".rstrip())
    f = forecast(rows)
    lines.append("")
    lines.append(f"cash per month: {_money(f['monthly_usd'])} across {f['priced']} priced subscription(s)"
                 + (f"; no price for: {', '.join(f['unpriced'])}" if f["unpriced"] else ""))
    return "\n".join(lines) + "\n"


def cmd_subs(args) -> int:
    action = args.action or "list"
    fields = {}
    for flag, key in (("monthly", "monthly_usd"), ("category", "category"), ("renews", "renews"),
                      ("credits", "credits_usd"), ("note", "note")):
        v = getattr(args, flag, None)
        if v is not None:
            fields[key] = None if v.strip().lower() == "none" else v
    try:
        if action == "list":
            rows = load()
            if args.json:
                print(json.dumps({"path": str(path()), "subscriptions": rows, "forecast": forecast(rows)}, indent=2))
            else:
                sys.stdout.write(render(rows))
            return 0
        if not args.name:
            print(f"teyla: subs {action} needs a NAME", file=sys.stderr)
            return 2
        if action == "add":
            row = add(args.name, **fields)
            print(f"added {row['name']} ({path()})")
        elif action == "set":
            if not fields:
                print("teyla: subs set needs at least one of --monthly --category --renews --credits --note",
                      file=sys.stderr)
                return 2
            row = update(args.name, **fields)
            print(f"updated {row['name']}")
        else:
            row = remove(args.name)
            print(f"removed {row['name']}")
    except SubsError as e:
        print(f"teyla: {e}", file=sys.stderr)
        return 1
    return 0


def register(sp):
    q = sp.add_parser("subs", help="the recurring bills the console's Money section adds up (list, add, set, remove)")
    q.set_defaults(fn=cmd_subs)
    q.add_argument("action", nargs="?", choices=["list", "add", "set", "remove"], default="list")
    q.add_argument("name", nargs="?", help="the subscription's name")
    q.add_argument("--monthly", metavar="USD", help="cash per month")
    q.add_argument("--category", metavar="CAT", help="ai, cloud, tool or domain")
    q.add_argument("--renews", metavar="DATE", help="next renewal, YYYY-MM-DD")
    q.add_argument("--credits", metavar="USD", help="API credit the plan includes per month")
    q.add_argument("--note", metavar="TEXT")
    q.add_argument("--json", action="store_true", help="list: JSON")
    return q

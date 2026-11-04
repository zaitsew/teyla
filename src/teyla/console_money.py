"""The console's Money section (`docs/CONSOLE.md`): what leaves my accounts.

    teyla console money [--json]

Two kinds of number, kept apart on purpose:

    cash         the owner's own list, `~/.teyla/subscriptions.toml` (`teyla subs`). The headline is the sum of the
                 priced rows; a row with no price adds nothing and is named. Teyla cannot read a bank, so a bill
                 nobody listed is simply absent, never estimated.
    list price   what the local AI sessions would cost at API list prices (`teyla spend`). A subscription bills
                 differently, so these figures are labelled and never added to cash. The providers' own cost APIs,
                 where an admin key exists, give `billed_usd` for the products.

Reading the sessions takes about 25 seconds, so `section()` never does it. `prepare()` does, once in a while, from
`teyla console --refresh` and the detached refresh `teyla state` starts; it writes `~/.teyla/console-money.json`
(mode 0600), and `section()` reads that file and the subscriptions file only. A cache that is missing leaves the
usage fields `null` and says so under `notes`.
"""
from __future__ import annotations

import datetime as dt
import json
import time
from collections import defaultdict

from . import config, subs
from .control import state as control

CACHE_VERSION = 1
USAGE_MAX_AGE_S = 6 * 3600       # `prepare` skips a cache younger than this unless forced
WINDOWS = (7, 30)
TOP_PRODUCTS = 15
TOP_MODELS = 12
RENEWAL_DAYS = 45
LIST_LABEL = "API list price of local AI sessions; a subscription bills differently. Not cash."


def cache_path():
    return control.home() / "console-money.json"


def _round(x, n=2):
    return None if x is None else round(x, n)


def _utc(now: float) -> dt.datetime:
    return dt.datetime.fromtimestamp(now, dt.timezone.utc)


# --- the usage cache (the slow part) -----------------------------------------------------------------------

def _window_rows(rows: list[dict], days: int, now: float) -> list[dict]:
    """The sessions `spend.session_rows(days)` would have kept: active inside the window."""
    cutoff = (_utc(now) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    return [r for r in rows if (r.get("last") or r.get("first") or "")[:19] >= cutoff]


def _provider_total(bills: dict, days: int, today: dt.date) -> float | None:
    """What the providers billed over the window, or None when no provider could be read (a $0 would lie)."""
    from . import providers
    per = providers.totals(bills, days, today)
    if not per:
        return None
    return round(sum(sum(g.values()) for g in per.values()), 2)


def aggregate(rows: list[dict], now: float, bills: dict | None, actions: list[dict] | None,
              today: dt.date | None = None) -> dict:
    """The cached usage: both windows, by product and model, by day, Actions minutes. Pure over its inputs."""
    from . import providers, spend
    today = today or dt.date.fromtimestamp(now)
    utc_today = _utc(now).date()
    windows, products, models = {}, defaultdict(lambda: {7: 0.0, 30: 0.0, "sessions": 0}), \
        defaultdict(lambda: {7: 0.0, 30: 0.0})
    for days in WINDOWS:
        sel = _window_rows(rows, days, now)
        windows[f"days{days}"] = {
            "list_usd": round(sum(r["usd"] for r in sel), 2),
            "sub_usd": round(sum(r["sub_usd"] for r in sel), 2),
            "sessions": len(sel),
            "billed_usd": _provider_total(bills, days, utc_today) if bills is not None else None,
        }
        for r in sel:
            p = products[r["project"]]
            p[days] += r["usd"]
            if days == 30:
                p["sessions"] += 1
            for m, v in (r.get("by_model") or {}).items():
                models[m][days] += v
    by_product = sorted(({"name": k, "days7_usd": round(v[7], 2), "days30_usd": round(v[30], 2),
                          "sessions": v["sessions"]} for k, v in products.items()),
                        key=lambda x: -x["days30_usd"])[:TOP_PRODUCTS]
    by_model = sorted(({"model": k, "days7_usd": round(v[7], 2), "days30_usd": round(v[30], 2)}
                       for k, v in models.items()), key=lambda x: -x["days30_usd"])[:TOP_MODELS]
    by_day = [{"day": d["day"], "list_usd": d["total_usd"], "sub_usd": d["sub_usd"]}
              for d in spend.by_day(30, rows=rows, today=today)]
    acts = None
    if actions is not None:
        included = [a["included"] for a in actions if a.get("included") is not None]
        acts = {"minutes_used": sum(a.get("minutes") or 0 for a in actions),
                "minutes_included": sum(included) if included else None,
                "paid_usd": round(sum(a.get("paid_usd") or 0 for a in actions), 2),
                "accounts": [{"account": a["account"], "plan": a.get("plan"), "minutes": a.get("minutes"),
                              "included": a.get("included"), "share": _round(a.get("share"), 3),
                              "paid_usd": a.get("paid_usd"), "top_repos": a.get("top_repos") or []}
                             for a in actions]}
    provider_rows = None
    if bills is not None:
        per = providers.totals(bills, 30, utc_today)
        provider_rows = {p: ({"billed_usd_30d": round(sum(per[p].values()), 2)} if p in per
                             else {"billed_usd_30d": None, "reason": b.get("skipped") or b.get("error") or "not read"})
                         for p, b in bills.items()}
    return {"version": CACHE_VERSION, "at": now, "windows": windows, "by_product": by_product,
            "by_model": by_model, "by_day": by_day, "actions": acts, "providers": provider_rows}


def compute(now: float, rows=None, bills=None, actions="read") -> tuple[dict, dict]:
    """(usage, notes). Each source on its own: a failing one leaves its part `null` and says why."""
    from . import providers, spend
    notes: dict = {}
    if rows is None:
        try:
            rows = spend.session_rows(max(WINDOWS))
        except Exception as e:  # noqa: BLE001
            notes["spend"] = f"{type(e).__name__}: {e}"[:160]
            rows = []
    if bills is None:
        try:
            bills = providers.read(max(WINDOWS))
        except Exception as e:  # noqa: BLE001
            notes["providers"] = f"{type(e).__name__}: {e}"[:160]
    if actions == "read":
        try:
            actions = spend.actions_usage()
        except Exception as e:  # noqa: BLE001
            notes["actions"] = f"{type(e).__name__}: {e}"[:160]
            actions = None
        if actions == []:             # signed in, but no account's billing could be read: unknown, not zero minutes
            notes["actions"] = "GitHub gave no Actions billing data (the token may lack billing access)"
            actions = None
    usage = aggregate(rows, now, bills, actions)
    if "spend" in notes:
        usage["windows"] = {k: {**v, "list_usd": None, "sub_usd": None, "sessions": None}
                            for k, v in usage["windows"].items()}
        usage["by_product"] = usage["by_model"] = usage["by_day"] = None
    return usage, notes


def read_usage() -> dict | None:
    try:
        data = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == CACHE_VERSION else None


def prepare(now: float | None = None, force: bool = False) -> bool:
    """Refresh the usage cache when it is older than USAGE_MAX_AGE_S (or `force`). True when it was rebuilt.
    This is the slow, networked part (the session scan, the provider cost APIs, the Actions billing read); it
    runs from `teyla console --refresh`, never from `section()`."""
    now = time.time() if now is None else now
    old = read_usage()
    if old and not force and now - float(old.get("at") or 0) < USAGE_MAX_AGE_S:
        return False
    usage, notes = compute(now)
    if notes and old and "spend" in notes:
        return False                  # keep the last good numbers rather than replace them with nulls
    usage["notes"] = notes
    config.write_private(cache_path(), json.dumps(usage))
    return True


# --- the section --------------------------------------------------------------------------------------------

def _renewals(rows: list[dict], now: float) -> list[dict]:
    today = dt.date.fromtimestamp(now)
    out = []
    for r in rows:
        if not r["renews"]:
            continue
        left = (dt.date.fromisoformat(r["renews"]) - today).days
        if 0 <= left <= RENEWAL_DAYS:
            out.append({"name": r["name"], "renews": r["renews"], "days": left, "monthly_usd": r["monthly_usd"]})
    return sorted(out, key=lambda x: x["days"])


def _by_category(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        key = r["category"] or "other"
        out[key] = round(out.get(key, 0.0) + (r["monthly_usd"] or 0.0), 2)
    return out


def _cloud(rows: list[dict], usage: dict | None) -> list[dict]:
    """Cloud lines: the owner's cloud and domain subscriptions, and GitHub Actions use where it was read."""
    out = [{"name": r["name"], "kind": "subscription", "monthly_usd": r["monthly_usd"], "detail": r["note"]}
           for r in rows if r["category"] in ("cloud", "domain")]
    for a in ((usage or {}).get("actions") or {}).get("accounts") or []:
        used, inc = a.get("minutes"), a.get("included")
        out.append({"name": f"GitHub Actions ({a['account']})", "kind": "usage", "monthly_usd": None,
                    "metered_usd": a.get("paid_usd"),
                    "detail": (f"{used} of {inc} minutes used this month" if inc else f"{used} minutes used this month")
                    if used is not None else None})
    return out


def _headline(fc: dict, error: str | None, listed: int) -> dict:
    label = "Cash per month"
    if error:
        return {"label": label, "value": None, "detail": error}
    if not listed:
        return {"label": label, "value": None,
                "detail": "no subscriptions listed; add them with teyla subs add NAME --monthly USD"}
    detail = f"{fc['priced']} of {listed} subscriptions priced"
    if fc["unpriced"]:
        detail += f"; no price for {', '.join(fc['unpriced'])}"
    return {"label": label, "value": fc["monthly_usd"], "detail": detail}


def section(now: float | None = None) -> dict:
    """Reads the subscriptions file and the usage cache; makes no network call and runs no session scan."""
    now = time.time() if now is None else now
    notes: dict = {}
    rows: list[dict] = []
    error = None
    try:
        rows = subs.load()
    except subs.SubsError as e:
        error = str(e)[:200]
        notes["subscriptions"] = error
    fc = subs.forecast(rows)
    usage = read_usage()
    if usage is None:
        notes["usage"] = "no usage cache yet; run `teyla console --refresh` (takes about 30 seconds)"
    elif usage.get("notes"):
        notes.update({f"usage.{k}": v for k, v in usage["notes"].items()})
    windows = (usage or {}).get("windows") or {}
    spend_block = {"label": LIST_LABEL, "as_of": (usage or {}).get("at"),
                   "days7": windows.get("days7") or {"list_usd": None, "billed_usd": None},
                   "days30": windows.get("days30") or {"list_usd": None, "billed_usd": None}}
    credits = [{"name": r["name"], "credits_usd": r["credits_usd"], "monthly_usd": r["monthly_usd"]}
               for r in rows if r["credits_usd"] is not None]
    return {
        "headline": _headline(fc, error, len(rows)),
        "forecast": {**fc, "by_category": _by_category(rows), "renewals": _renewals(rows, now),
                     "label": "Cash per month: the owner's listed subscriptions, no estimates"},
        "subscriptions": rows,
        "spend": spend_block,
        "by_product": (usage or {}).get("by_product"),
        "by_model": (usage or {}).get("by_model"),
        "by_day": (usage or {}).get("by_day"),
        "credits": credits,
        "credits_total_usd": round(sum(c["credits_usd"] for c in credits), 2) if credits else None,
        "providers": (usage or {}).get("providers"),
        "cloud": _cloud(rows, usage),
        "actions": (usage or {}).get("actions"),
        "file": str(subs.path()),
        "notes": notes,
    }


def compact(sec: dict) -> dict:
    if sec.get("error"):
        return {"error": sec["error"]}
    fc = sec.get("forecast") or {}
    nxt = (fc.get("renewals") or [None])[0]
    return {"headline": sec.get("headline"), "monthly_usd": fc.get("monthly_usd"),
            "unpriced": len(fc.get("unpriced") or []),
            "list_usd_7d": ((sec.get("spend") or {}).get("days7") or {}).get("list_usd"),
            "next_renewal": ({k: nxt[k] for k in ("name", "renews", "days")} if nxt else None)}

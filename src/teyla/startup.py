"""`teyla startup` — one page per company: the next fact each product is missing (docs/STARTUP.md).

    teyla startup [--json]                     the focus product, then one line per product
    teyla startup show <id> [--json]           the ladder, the metrics and the next fact
    teyla startup yc [<id>] [--json]           the YC sheet (see startup_yc.py)
    teyla startup yc answer|confirm|export     write, confirm or export the answers

A stage is earned from records a command can read: the portfolio (can someone install it), the growth ledger (did
anyone try to sell it) and the usage probe each repo's `./check.sh usage` prints. Nothing sets a stage by hand, and the
owner chooses a product's type (`teyla product set <id> type=venture|indie|open-source|personal`). Zero, unknown and
stale are three answers: a product with no probe is `unknown`, a probe older than 7 days is `stale`, and a stale rung
earns nothing. An attempt logged from an agent session is `claimed` and counts for nothing until the owner logs it.
There is no percent and no rank of YC fit. This module makes no network call. Exit 0 ok, 1 something needs a fix, 2 usage.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import sys
import time

from . import asks, corrections, growth, portfolio, registry

VERSION = 1
TYPES = registry.TYPES
DEFAULT_TYPE = "venture"                    # an unset type uses the venture ladder and says so
FRESH_DAYS = 7                              # a probe older than this makes its rungs stale
KEEP_DAYS = 400                             # snapshots kept
GROWTH_WEEKS = 4
GROWTH_PCT = 5.0                            # operating default, not a benchmark (docs/STARTUP.md)
RETAINED_MIN = 3
REPEAT_PAYERS = 3
KEPT_DAYS = 30
WINDOW_DAYS = 30                            # two revenue windows must not overlap
STATUSES = ("met", "missing", "unknown", "stale", "not_applicable")
OPEN_STATUSES = ("missing", "unknown", "stale")        # a rung in one of these can be `next`

TITLES = {"built": "Built", "tried": "Tried", "used": "Used", "retained": "Retained", "paid": "Paid",
          "repeating": "Repeating", "growing": "Growing", "sustaining": "Sustaining",
          "used_by_me": "Used by me", "kept": "Kept", "none": "Not built"}
LADDERS = {
    "venture": ("built", "tried", "used", "retained", "paid", "repeating", "growing"),
    "indie": ("built", "tried", "used", "retained", "paid", "repeating", "sustaining"),
    "open-source": ("built", "tried", "used", "retained"),
    "personal": ("built", "used_by_me", "kept"),
}
NORTH_STAR = {
    "venture": "weekly growth of revenue, or of weekly users while it does not charge",
    "indie": "revenue above its AI cost",
    "open-source": "people other than the author using it weekly",
    "personal": "the owner still uses it after 30 days",
}

# Harness environment variables, checked on 2026-11-04 by running each harness: Claude Code sets CLAUDECODE and
# CLAUDE_CODE_SESSION_ID; Codex sets CODEX_THREAD_ID, CODEX_SESSION_ID and CODEX_CI; Grok sets GROK_SESSION_ID and
# GROK_AGENT; AI_AGENT is the shared convention. CODEX_HOME, GROK_HOME and CLAUDE_CODE_ENTRYPOINT are NOT here: a person
# can export them in his own shell. This stops a mistake; an agent on the owner's account can still clear them.
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "CODEX_CI",
             "GROK_SESSION_ID", "GROK_AGENT", "AI_AGENT")


def in_agent_session(env=None) -> bool:
    """True when the harness variables say an AI agent runs this command."""
    env = os.environ if env is None else env
    return any(str(env.get(k) or "").strip().lower() not in ("", "0", "false") for k in AGENT_ENV)


# --- time -----------------------------------------------------------------------------------------------------

def _iso(epoch: float) -> str:
    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _days_between(older: str, newer: str) -> int | None:
    try:
        return (_dt.date.fromisoformat(newer) - _dt.date.fromisoformat(older)).days
    except (TypeError, ValueError):
        return None


# --- snapshots ------------------------------------------------------------------------------------------------

def home() -> pathlib.Path:
    return corrections.teyla_home() / "startup"


def snapshots_path() -> pathlib.Path:
    return home() / "snapshots.jsonl"


def read_snapshots() -> dict[str, list[dict]]:
    """{product id: its snapshot rows, oldest first}. A line that is not a JSON object is skipped."""
    out: dict[str, list[dict]] = {}
    try:
        lines = snapshots_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and isinstance(r.get("id"), str) and isinstance(r.get("day"), str):
            out.setdefault(r["id"], []).append(r)
    for rows in out.values():
        rows.sort(key=lambda r: r["day"])
    return out


def write_snapshots(now: float, rows: list[dict]) -> None:
    """One row per product per day: today's row replaces an earlier one of the same product. Rows older than 400
    days drop out. The file is private (0600) under the Teyla home."""
    if not rows:
        return
    today = growth.day_of(now)
    cutoff = (_dt.date.fromisoformat(today) - _dt.timedelta(days=KEEP_DAYS)).isoformat()
    mine = {r["id"] for r in rows}
    kept = [r for rs in read_snapshots().values() for r in rs
            if r["day"] >= cutoff and not (r["id"] in mine and r["day"] == today)]
    allrows = sorted(kept + rows, key=lambda r: (r["day"], r["id"]))
    home().mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(home(), 0o700)
    except OSError:
        pass
    asks._atomic_write(snapshots_path(), "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in allrows))


# --- facts: the numbers the rungs read ------------------------------------------------------------------------

def _external(explicit, raw):
    """(external people, assumed). `explicit` is what repos printed as `external_*`; `raw` is the raw count of the other
    repos, from which one account for the owner comes off, once per product."""
    if raw is None:
        return explicit, False
    return (explicit or 0) + max(raw - 1, 0), True


def facts(now: float, *, pid: str, rp: dict, repos, usage: dict, ages: dict, money_enabled: bool, can_install: bool,
          ai_cost_30d: float | None, attempts: dict, install_known: bool = True) -> dict:
    """The numbers one product's rungs read, from the caches. None means no source reports it."""
    def get(keys):
        return portfolio._sum_keys(repos, usage, keys, portfolio._count)

    keys = {"total": portfolio._TOTAL_KEYS, "wau": portfolio._WEEKLY_KEYS, "retained": ("retained_7d",),
            "new_7d": portfolio._NEW_KEYS["7d"], "ext_users": ("external_users",), "ext_wau": ("external_wau",),
            "ext_retained": ("external_retained_7d",)}
    u = {k: get(v) for k, v in keys.items()}
    fallback = {"ext_users": "total", "ext_wau": "wau", "ext_retained": "retained"}
    read = [k for ks in (*keys.values(), *portfolio._MONEY_KEYS.values()) for k in ks]       # every counter a rung reads
    contributing = [r.name.lower() for r in repos
                    if any(portfolio._money_number((usage.get(r.name.lower()) or {}).get(k)) is not None for k in read)]
    stamps = [ages.get(n) for n in contributing]
    u["has"] = bool(contributing)
    # Without a time for every probe that contributed, freshness cannot be shown, so it is not claimed.
    u["at"] = min(stamps) if stamps and all(s is not None for s in stamps) else None
    u["fresh"] = u["at"] is not None and now - u["at"] <= FRESH_DAYS * 86400
    def outside(ext_key: str) -> tuple[int | None, bool]:
        """Repo by repo: a repo's own `external_*` counter, and the raw counter of the repos that print none."""
        explicit, raw = None, None
        for r in repos:
            one = {r.name.lower(): usage.get(r.name.lower()) or {}}
            e = portfolio._sum_keys([r], one, keys[ext_key], portfolio._count)
            if e is not None:
                explicit = (explicit or 0) + e
            else:
                n = portfolio._sum_keys([r], one, keys[fallback[ext_key]], portfolio._count)
                raw = raw if n is None else (raw or 0) + n
        return _external(explicit, raw)

    users, a1 = outside("ext_users")
    wau, a2 = outside("ext_wau")
    ret, a3 = outside("ext_retained")
    u.update(external=users, external_wau=wau, external_retained=ret,
             assumed=bool((a1 and users is not None) or (a2 and wau is not None) or (a3 and ret is not None)))
    m = portfolio.money_metrics(money_enabled, repos, usage)
    money = {"enabled": money_enabled, "paying": m["paying"], "mrr_usd": m["mrr_usd"],
             "revenue_30d_usd": m["revenue_usd"]["30d"], "ai_cost_30d_usd": ai_cost_30d}
    return {"id": pid, "registry_stage": rp.get("stage") or "", "can_install": can_install, "install_known": install_known, "usage": u, "money": money,
            "attempts": attempts}


def snapshot_row(now: float, f: dict) -> dict | None:
    """Today's row for the snapshot file; None when there is no fresh probe to record."""
    u = f["usage"]
    if not (u["has"] and u["fresh"]):
        return None
    return {"day": growth.day_of(now), "id": f["id"], "external_users": u["external"], "external_wau": u["external_wau"],
            "wau": u["wau"], "retained_7d": u["external_retained"], "new_7d": u["new_7d"],
            "revenue_30d_usd": f["money"]["revenue_30d_usd"], "paying": f["money"]["paying"],
            "mrr_usd": f["money"]["mrr_usd"]}


# --- the rungs ------------------------------------------------------------------------------------------------

def _gate(known: bool, fresh: bool, ok: bool) -> str:
    """A rung that reads a probe: unknown when nothing reports it, stale when the probe is old, else met or missing."""
    if not known:
        return "unknown"
    if not fresh:
        return "stale"
    return "met" if ok else "missing"


def _n(v, unit: str = "") -> str:
    """A number for a sentence; None is "unknown", never 0. A dollar figure keeps two decimals."""
    if v is None:
        return "unknown"
    return f"${v:,.2f}" if unit == " USD" else f"{v}{unit}"


def _snapshot_at_least(snaps: list[dict], today: str, days: int) -> dict | None:
    """The newest snapshot that is at least `days` old."""
    best = None
    for r in snaps:
        d = _days_between(r["day"], today)
        if d is not None and d >= days:
            best = r
    return best


def _growth(snaps: list[dict], today: str, f: dict) -> dict:
    """Weekly growth (compounded) from the newest snapshot at least 4 weeks old: revenue when the product charges and
    has revenue, else outside weekly users. `weekly_pct` is None until 4 weeks of snapshots exist."""
    u, money = f["usage"], f["money"]
    rev = money["revenue_30d_usd"]
    on = "revenue" if money["enabled"] and rev else "wau"
    span = [d for d in (_days_between(r["day"], today) for r in snaps) if d is not None]
    out = {"weekly_pct": None, "weeks": max(span) // 7 if span else 0, "on": on}
    old = _snapshot_at_least(snaps, today, GROWTH_WEEKS * 7)
    if old is None:
        return out
    now_v, old_v = (rev, old.get("revenue_30d_usd")) if on == "revenue" else (u["external_wau"], old.get("external_wau"))
    days = _days_between(old["day"], today)
    out["weeks"] = days // 7
    if now_v is None or not old_v or old_v <= 0 or not days:
        return out
    out["weekly_pct"] = round(((now_v / old_v) ** (7 / days) - 1) * 100, 1)
    return out


def rungs(now: float, f: dict, ladder: tuple, snaps: list[dict]) -> tuple[list[dict], dict]:
    """(the ladder's rungs in order, the growth block). Each rung is checked on its own."""
    u, money, att = f["usage"], f["money"], f["attempts"]
    today = growth.day_of(now)
    fresh, ext = u["fresh"], u["external"]
    rev, paying = money["revenue_30d_usd"], money["paying"]
    out: dict[str, tuple[str, str]] = {}

    if f["can_install"]:
        out["built"] = ("met", "Installable")
    elif f["registry_stage"] in ("beta", "live"):
        out["built"] = ("met", f"Stage {f['registry_stage']}")
    elif (u["total"] or 0) >= 1:
        out["built"] = ("met", "People have accounts")
    elif f["install_known"]:
        out["built"] = ("missing", "Not installable yet")
    else:
        out["built"] = ("unknown", "Teyla sees no store or site for it")

    n = att["posts"] + att["marketing"] + att["icp_meetings"]
    claimed = att.get("claimed", 0)
    out["tried"] = ("met", f"{n} posts, ads, outreach or ICP meetings") if n else \
        ("missing", "No sale attempt yet" + (f"; {claimed} claimed by an agent" if claimed else ""))

    out["used"] = (_gate(ext is not None, fresh, (ext or 0) >= 1),
                   f"{_n(ext)} outside accounts" + (" (assumed)" if u["assumed"] and u["ext_users"] is None else ""))
    out["retained"] = (_gate(u["external_retained"] is not None, fresh, (u["external_retained"] or 0) >= RETAINED_MIN),
                       f"{_n(u['external_retained'])} outside people returned at day 7, needs {RETAINED_MIN}")

    if not money["enabled"]:
        for rid in ("paid", "repeating", "sustaining"):
            out[rid] = ("not_applicable", "Monetization is off")
    else:
        known = paying is not None or rev is not None
        out["paid"] = (_gate(known, fresh, (paying or 0) >= 1 or (rev or 0) > 0),
                       f"{_n(paying)} payers, revenue in 30 days {_n(rev, ' USD')}")
        prior = _snapshot_at_least([r for r in snaps if (_days_between(r["day"], today) or 0) <= 60], today, WINDOW_DAYS)
        two_windows = bool(rev and rev > 0 and prior and (prior.get("revenue_30d_usd") or 0) > 0)
        out["repeating"] = (_gate(known, fresh, (paying or 0) >= REPEAT_PAYERS or two_windows),
                            f"{_n(paying)} payers, needs {REPEAT_PAYERS}, or revenue in 2 windows of 30 days")
        ai = money["ai_cost_30d_usd"]
        out["sustaining"] = (_gate(rev is not None and ai is not None, fresh, (rev or 0) > (ai or 0)),
                             f"revenue {_n(rev, ' USD')} against AI cost {_n(ai, ' USD')} in 30 days")

    g = _growth(snaps, today, f)
    if g["weekly_pct"] is None:
        out["growing"] = ("stale" if u["has"] and not fresh else "unknown",
                          f"Needs {GROWTH_WEEKS} weeks of snapshots, has {g['weeks']}")
    else:
        out["growing"] = (_gate(True, fresh, g["weekly_pct"] >= GROWTH_PCT),
                          f"{g['weekly_pct']:g}% a week on {'revenue' if g['on'] == 'revenue' else 'weekly users'}, needs {GROWTH_PCT:g}%")

    wau = u["wau"]
    out["used_by_me"] = (_gate(wau is not None, fresh, (wau or 0) >= 1), f"{_n(wau)} weekly users")
    old = _snapshot_at_least(snaps, today, KEPT_DAYS)
    if wau is not None and fresh and old is None:
        out["kept"] = ("unknown", f"Needs {KEPT_DAYS} days of snapshots")
    else:
        out["kept"] = (_gate(wau is not None, fresh, (wau or 0) >= 1 and bool(old and (old.get("wau") or 0) >= 1)),
                       "Weekly users on snapshots 30 days apart")
    rows = [{"id": rid, "title": TITLES[rid], "status": out[rid][0], "detail": out[rid][1]} for rid in ladder]
    return rows, g


def stage_of(rows: list[dict]) -> str:
    """The last met rung of the unbroken run from the start; a rung that does not apply does not break the run."""
    stage = "none"
    for r in rows:
        if r["status"] == "met":
            stage = r["id"]
        elif r["status"] != "not_applicable":
            break
    return stage


def next_of(pid: str, rows: list[dict], f: dict, now: float) -> dict | None:
    """The first rung that is not met, in fixed words (no customer text): {rung, text, command}."""
    r = next((x for x in rows if x["status"] in OPEN_STATUSES), None)
    if r is None:
        return None
    rid, status = r["id"], r["status"]
    u = f["usage"]
    age = int((now - u["at"]) // 86400) if u["at"] else None
    if rid == "built":
        text = "It cannot be installed yet." if status == "missing" else "Teyla cannot tell whether it can be installed."
        cmd = f"teyla portfolio --product {pid}"
    elif rid == "tried":
        claimed = f["attempts"].get("claimed", 0)
        text = (f"{claimed} {'attempt was' if claimed == 1 else 'attempts were'} logged by an agent and do not count. "
                "Log them yourself.") if claimed else "Nobody has tried to sell it yet."
        cmd = "teyla growth"
    elif status == "unknown" and rid in ("growing", "kept"):
        text, cmd = r["detail"] + ".", "teyla portfolio --refresh"
    elif status == "unknown":
        text, cmd = ("No usage probe reports this." if not u["has"] else "The usage probe does not print this number."), "teyla products"
    elif status == "stale":
        text, cmd = (f"The usage probe is {age} days old." if age is not None else "The usage probe has no time on it."), \
            "teyla portfolio --refresh"
    else:
        text = {"used": "No outside person has an account yet.",
                "retained": f"Fewer than {RETAINED_MIN} outside people came back at day 7.",
                "paid": "Nobody pays yet.", "repeating": f"Fewer than {REPEAT_PAYERS} payers, and no revenue in 2 windows.",
                "growing": f"Growth is under {GROWTH_PCT:g}% a week.", "sustaining": "Revenue is not above the AI cost.",
                "used_by_me": "Nobody used it this week.", "kept": "Not used on both snapshots."}[rid]
        cmd = f"teyla startup show {pid}"
    return {"rung": rid, "text": text, "command": cmd}


# --- the block ------------------------------------------------------------------------------------------------

def evaluate(now: float, f: dict, rp: dict, snaps: list[dict], pid: str) -> dict:
    """The `startup` block of one product (docs/STARTUP.md, "JSON"): fixed labels and numbers only."""
    from . import startup_yc
    type_set = rp.get("type") in TYPES
    typ = rp["type"] if type_set else DEFAULT_TYPE
    ladder = LADDERS[typ]
    rs, g = rungs(now, f, ladder, snaps)
    stage = stage_of(rs)
    built_unknown = next(r["status"] for r in rs if r["id"] == "built") == "unknown"
    u, money, att = f["usage"], f["money"], f["attempts"]
    block = {
        "type": typ, "type_set": type_set, "stage": stage, "stage_title": "Not known" if stage == "none" and built_unknown else TITLES[stage],
        "parked": f["registry_stage"] == "parked",
        "as_of": _iso(u["at"]) if u["has"] and u["at"] else None,
        "stale": bool(u["has"] and not u["fresh"]),
        "next": next_of(pid, rs, f, now), "rungs": rs,
        "metrics": {
            "marketing": {"posts": att["posts"], "posts_7d": att.get("posts_7d", 0), "ads_outreach": att["marketing"]},
            "sales": {"icp_meetings": att["icp_meetings"], "icp_meetings_30d": att.get("icp_meetings_30d", 0),
                      "last": att["last"], "claimed": att.get("claimed", 0)},
            "usage": ({"external": None, "external_assumed": False, "wau": u["wau"], "retained_7d": None, "new_7d": u["new_7d"]}
                      if typ == "personal" else
                      {"external": u["external"], "external_assumed": u["assumed"], "wau": u["external_wau"],
                       "retained_7d": u["external_retained"], "new_7d": u["new_7d"]}),
            "money": money,
            "growth": g,
        },
    }
    block["yc"] = startup_yc.summary(pid, block)
    return block


def context(now: float, reg: dict) -> dict:
    """What every product's block shares, read once per build: the growth ledger, the snapshots, the probe times."""
    return {"attempts": growth.tally(growth.Store().ledger(), list(reg["product"]), growth.day_of(now)),
            "snaps": read_snapshots(), "ages": portfolio.load_usage_ages()}


def block_for(ctx: dict, now: float, *, pid: str, rp: dict, repos, usage: dict, can_install: bool, money_enabled: bool,
              ai_cost_30d: float | None, install_known: bool = True) -> dict:
    f = facts(now, pid=pid, rp=rp, repos=repos, usage=usage, ages=ctx["ages"], money_enabled=money_enabled,
              can_install=can_install, ai_cost_30d=ai_cost_30d, attempts=ctx["attempts"][pid], install_known=install_known)
    return evaluate(now, f, rp, ctx["snaps"].get(pid, []), pid)


def record_snapshots(now: float, reg: dict) -> None:
    """Write today's snapshot rows from the usage cache. Called by `teyla portfolio --refresh`; local files only."""
    usage, ages = portfolio.load_usage_cache(), portfolio.load_usage_ages()
    rows = []
    for pid, rp in reg["product"].items():
        repos = portfolio.product_repos(rp)
        manifests = portfolio.parse_manifests(repos)
        f = facts(now, pid=pid, rp=rp, repos=repos, usage=usage, ages=ages,
                  money_enabled=portfolio.monetization_enabled(manifests), can_install=False, ai_cost_30d=None,
                  attempts={"posts": 0, "marketing": 0, "icp_meetings": 0, "last": ""})
        row = snapshot_row(now, f)
        if row:
            rows.append(row)
    write_snapshots(now, rows)


# --- the focus product ----------------------------------------------------------------------------------------

def focus_of(items: list[dict]) -> str | None:
    """The highest outside weekly users among products that are not personal or parked, then the highest retained, then
    the id. `items` are portfolio products. None when no product qualifies."""
    def key(p):
        m = p["startup"]["metrics"]["usage"]
        return (-(m["wau"] if m["wau"] is not None else -1), -(m["retained_7d"] if m["retained_7d"] is not None else -1), p["id"])
    pool = [p for p in items if p.get("startup") and p["startup"]["type"] != "personal" and not p["startup"]["parked"]]
    return min(pool, key=key)["id"] if pool else None


# --- the commands ---------------------------------------------------------------------------------------------

def _view(now: float) -> list[dict]:
    from . import state
    return state.build(now, model_brief=False, refresh=False)["portfolio"]["products"]


def report(now: float, items: list[dict]) -> dict:
    mine = [p for p in items if p.get("startup")]
    counts: dict[str, int] = {}
    for p in mine:
        counts[p["startup"]["stage"]] = counts.get(p["startup"]["stage"], 0) + 1
    return {"version": VERSION, "as_of": _iso(now), "focus": focus_of(mine), "counts": counts,
            "products": [{"id": p["id"], "title": p["title"], **p["startup"]} for p in mine]}


def _line(p: dict) -> str:
    s = p["startup"] if "startup" in p else p
    nxt = "parked" if s["parked"] else (f"next {TITLES[s['next']['rung']]}" if s["next"] else "nothing left on its ladder")
    return f"  {p['id']:<22} {s['type'] + ('' if s['type_set'] else '?'):<12}{s['stage_title']:<11} {nxt}"


def render_focus(p: dict) -> list[str]:
    s = p["startup"] if "startup" in p else p
    head = f"Focus: {p['id']} ({s['type']}{'' if s['type_set'] else ', type not chosen'}). Stage {s['stage_title']}"
    L = [head + (f", next {TITLES[s['next']['rung']]}." if s["next"] else ".")]
    if s["next"]:
        L.append(f"  {s['next']['text']}  {s['next']['command']}")
    L.append("  usage as of " + (f"{s['as_of']}{' (stale)' if s['stale'] else ''}" if s["as_of"] else "unknown: no probe reports it"))
    return L


def render_list(rep: dict) -> str:
    by = {p["id"]: p for p in rep["products"]}
    if not by:
        return "No product is registered (teyla product init --write).\n"
    L = []
    if rep["focus"]:
        L += render_focus(by[rep["focus"]]) + [""]
    else:
        L += ["No focus product: every product is parked or personal.", ""]
    others = [p for p in rep["products"] if p["id"] != rep["focus"]]
    L.append("Other products" if rep["focus"] else "Products")
    L += [_line(p) for p in others] or ["  none"]
    L.append("")
    titles: dict[str, int] = {}
    for p in rep["products"]:
        titles[p["stage_title"]] = titles.get(p["stage_title"], 0) + 1
    L.append("Stages: " + ", ".join(f"{n} {t}" for t, n in sorted(titles.items())))
    unset = sum(1 for p in rep["products"] if not p["type_set"])
    if unset:
        L.append(f"{unset} products have no type (shown with ?). They use the venture ladder. Choose one: teyla product set <id> type=<type>")
    return "\n".join(L) + "\n"


def _metric_lines(s: dict) -> list[str]:
    m = s["metrics"]
    mk, sa, us, mo, gr = m["marketing"], m["sales"], m["usage"], m["money"], m["growth"]
    off = not mo["enabled"]
    last = sa["last"] or "none"
    L = [f"  Marketing  posts {mk['posts']} (7 days {mk['posts_7d']}), ads and outreach {mk['ads_outreach']}",
         f"  Sales      ICP conversations {sa['icp_meetings']} (30 days {sa['icp_meetings_30d']}), last attempt {last}"
         + (f", {sa['claimed']} claimed by an agent, not counted" if sa["claimed"] else "")]
    if s["type"] == "personal":
        L.append(f"  Usage      weekly users {_n(us['wau'])}, new in 7 days {_n(us['new_7d'])}")
    else:
        L.append(f"  Usage      outside people {_n(us['external'])}{' (assumed: accounts minus the owner)' if us['external_assumed'] else ''}, "
                 f"weekly {_n(us['wau'])}, returned at day 7 {_n(us['retained_7d'])}, new in 7 days {_n(us['new_7d'])}")
    L.append("  Money      " + ("monetization is off" if off else
             f"payers {_n(mo['paying'])}, MRR {_n(mo['mrr_usd'], ' USD')}, revenue in 30 days {_n(mo['revenue_30d_usd'], ' USD')}")
             + f", AI cost in 30 days {_n(mo['ai_cost_30d_usd'], ' USD')}")
    L.append("  Growth     " + (f"{gr['weekly_pct']:g}% a week on {'revenue' if gr['on'] == 'revenue' else 'weekly users'} over {gr['weeks']} weeks"
                                if gr["weekly_pct"] is not None else
                                f"unknown: {gr['weeks']} weeks of snapshots, needs {GROWTH_WEEKS}"))
    return L


def render_show(p: dict) -> str:
    s = p["startup"]
    L = [f"{p['id']}: {s['type']}{'' if s['type_set'] else ' (type not chosen; the venture ladder is used)'}, "
         f"stage {s['stage_title']}{', parked' if s['parked'] else ''}",
         f"North star: {NORTH_STAR[s['type']]}.",
         "usage as of " + (f"{s['as_of']}{' (stale, older than 7 days)' if s['stale'] else ''}" if s["as_of"] else "unknown (no probe reports it)"),
         "", "Rungs"]
    L += [f"  {r['status'].replace('_', ' '):<15}{r['title']:<12}{r['detail']}" for r in s["rungs"]]
    L += ["", "Metrics"] + _metric_lines(s) + [""]
    if s["next"]:
        L += [f"Next: {TITLES[s['next']['rung']]}. {s['next']['text']}", f"  {s['next']['command']}"]
    else:
        L.append("Nothing left on this ladder.")
    return "\n".join(L) + "\n"


def cmd_startup(args) -> int:
    now = time.time()
    rep = report(now, _view(now))
    if args.json:
        print(json.dumps(rep, indent=1))
    else:
        print(render_list(rep), end="")
    return 0


def cmd_show(args) -> int:
    now = time.time()
    items = {p["id"]: p for p in _view(now)}
    p = items.get(args.id)
    if p is None:
        print(f"teyla: no product '{args.id}' in the portfolio", file=sys.stderr)
        return 2
    if not p.get("startup"):
        print(f"teyla: the startup block of {args.id} could not be computed", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"id": p["id"], "title": p["title"], **p["startup"]}, indent=1))
    else:
        print(render_show(p), end="")
    return 0


def register(sp):
    from . import startup_yc
    q = sp.add_parser("startup", help="the next fact each product is missing: stage, ladder, metrics, the YC sheet",
                      description=__doc__.split("\n\n")[0])
    q.set_defaults(fn=cmd_startup)
    q.add_argument("--json", action="store_true")
    sub = q.add_subparsers(dest="startup_cmd")
    s = sub.add_parser("show", help="one product's ladder, metrics and next fact")
    s.set_defaults(fn=cmd_show)
    s.add_argument("id")
    s.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    startup_yc.register(sub)
    return q

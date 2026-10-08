"""`teyla spend` — what the last N days of AI work cost, and which part of it bought nothing.

Token spend should be reviewed regularly (daily or weekly) by model, with what was wasted and how
to avoid it next time. The monitor report already prices sessions, but a report in a file tends
not to be read, so this command's output goes into the weekly digest and the daily alert.

Dollars are API list price ("API-equivalent"): a subscription bills differently, but list price
is what makes two sessions, two models and two harnesses comparable. Each waste rule gives a
dollar figure and one fix:

  W1  a session that cost W1_USD or more and left no commit or PR within a day of its end
  W2  re-reading context: messages past 250k tokens of context pay to re-read everything above
      the ~50k a compacted session resumes from (system prompt, tools, the re-injected handoff)
  W3  the top tier in subagents: Fable output in Agent calls, priced as the saving at Sonnet 5.5
  W5  Grok lanes that cost W1_USD or more and left no commit or PR (POLICY §1's Grok rules)
  W6  failed loops: messages sent after three or more failed tool calls in a row
  W8  GitHub Actions minutes this month against the plan's included minutes (POLICY §10)

  W7  product API spend (teyla.providers: the OpenAI and Anthropic cost APIs, admin keys in the
      Keychain): a day past twice the median of the seven before it

Not covered yet, and said so in the output: W4 (the same diff on two branches).

`--alert` is the daily check: it says something only for a session over `spend.alert_session_usd`
in the last day, a project or the day's total over its budget yesterday (`spend.budget.<project>`,
`spend.daily_budget_usd`), Actions past ALERT_ACTIONS_SHARE of the included minutes, or a product
API spike. It posts a notification, writes `~/.teyla/spend.alert` for the session-start banner, and
does not say the same thing again the next day unless the amount grew by a quarter.

`--by-day` is the per-day view: total cost, subagent cost, and the subagents' cost and calls by
model tier.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict

from . import config

# W1/W5: a session under this is not worth a line even when it produced nothing. Spend is heavily
# skewed: a small share of the sessions is most of the money, and below this a line costs more
# attention than money. Defaults live in config.DEFAULTS["spend"]; `[spend]` in config.toml
# overrides them (a machine's spend is not another's).
W1_USD = config.DEFAULTS["spend"]["w1_usd"]
# W1: a commit this long after the session's last message still counts as its outcome.
OUTCOME_GRACE_H = 24
# Findings under this are dropped: a $0.40 loop is not worth a line in a six-line digest.
FINDING_FLOOR_USD = 1.0
# The daily alert. A threshold that fires every morning gets ignored; this one is a handful of
# sessions a week.
ALERT_SESSION_USD = config.DEFAULTS["spend"]["alert_session_usd"]
# An alert already given yesterday is repeated only when its amount grew by this much.
ALERT_REGROWTH = 0.25
ALERT_ACTIONS_SHARE = 0.8
# W3: the model the policy says volume work runs on.
VOLUME_MODEL = "claude-sonnet-5-5"
# W8: GitHub bills Linux at this per minute and counts included minutes in Linux minutes;
# a plan's included minutes by plan name (GitHub's plans page, 2026-09).
LINUX_USD_PER_MIN = 0.006
PLAN_MINUTES = {"free": 2000, "pro": 3000, "team": 3000, "enterprise": 50000}

NOT_COVERED = "not covered yet: W4 duplicated work"


# --- config ----------------------------------------------------------------------------------

def _number(v, default: float) -> float:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return default
    return n if n == n and n >= 0 else default


def setting(name: str, cfg: dict | None = None) -> float:
    """A `[spend]` number from config.toml, else its default; a value that is not a number or is
    negative reads as the default rather than switching a check off by accident."""
    default = config.DEFAULTS["spend"][name]
    return _number(((cfg or config.load()).get("spend") or {}).get(name, default), default)


def budgets(cfg: dict | None = None) -> tuple[float, dict[str, float]]:
    """(the day's total budget, {project: budget}); 0 and absent mean no budget. A project's budget is
    `spend.budget.<project>` (what `teyla config set` writes: a key literally named `budget.<project>`)
    or an entry of a `[spend.budget]` table."""
    sp = (cfg or config.load()).get("spend") or {}
    per = {}
    nested = sp.get("budget")
    for k, v in (nested.items() if isinstance(nested, dict) else []):
        per[str(k)] = _number(v, 0.0)
    for k, v in sp.items():
        if isinstance(k, str) and k.startswith("budget."):
            per[k[len("budget."):]] = _number(v, 0.0)
    return setting("daily_budget_usd", cfg), {k: v for k, v in per.items() if v > 0}


# --- rows ------------------------------------------------------------------------------------

def _usd(model: str, usage: dict) -> float:
    from .pricing import cost_usd
    return cost_usd(model, usage) or 0.0


def _project(cwd: str | None) -> str:
    if not cwd:
        return "unknown"
    parts = pathlib.Path(cwd).parts
    if ".worktrees" in parts:  # ~/.worktrees/<repo>/<branch>
        i = parts.index(".worktrees")
        if len(parts) > i + 1:
            return parts[i + 1]
    return os.path.basename(cwd.rstrip("/")) or "unknown"


# Per-day keys of a row: the input of --by-day and the budget alerts, left out of printed rows.
DAY_KEYS = ("day_usd", "day_model_usd", "sub_day_model_usd", "sub_calls")


def _day_fields(s) -> dict:
    """Per local day: what the session cost, by model, and what its subagents cost, by model, plus
    one (day, model) per subagent call. A harness whose transcript carries no per-message time
    (everything but Claude Code) books the whole session on the day it was last active."""
    split = s.day_usage or {}
    sub = s.sub_day_usage or {}
    if not split:
        from .adapters import local_day
        split = {local_day(s.last or s.first): s.usage}
    day_model = {d: {m: _usd(m, u) for m, u in mm.items()} for d, mm in split.items()}
    return dict(day_usd={d: sum(mm.values()) for d, mm in day_model.items()},
                day_model_usd=day_model,
                sub_day_model_usd={d: {m: _usd(m, u) for m, u in mm.items()} for d, mm in sub.items()},
                sub_calls=list(s.sub_calls or []))


def session_rows(days: int = 7, sessions=None, grok_rows=None) -> list[dict]:
    """One row per session in the window, every harness: what it cost and the inputs of the rules."""
    from .adapters import since_epoch
    from .pricing import tier
    if sessions is None:
        from .adapters import load_all
        sessions = load_all(since=since_epoch(days))
    cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = []
    for s in sessions:
        # In the window when it was active in it: a session resumed today counts today (its whole
        # cost; a transcript does not split by day). Grok is priced from its own costUsdTicks below.
        if s.sidechain or s.harness == "grok" or (s.last or s.first or "")[:19] < cutoff:
            continue
        by_model = {m: _usd(m, u) for m, u in s.usage.items()}
        sub = {m: _usd(m, u) for m, u in s.sub_usage.items()}
        saving = sum(max(0.0, _usd(m, u) - _usd(VOLUME_MODEL, u))
                     for m, u in s.sub_usage.items() if tier(m) == "orchestrate")
        from .pricing import lookup
        reread = sum(n * (lookup(m) or (0, 0, 0))[2] / 1e6 for m, n in s.reread_excess.items())
        rows.append(dict(
            harness=s.harness, sid=s.sid, project=_project(s.cwd), cwd=s.cwd, first=s.first, last=s.last,
            usd=sum(by_model.values()), by_model=by_model, sub_usd=sum(sub.values()), top_tier_sub_saving=saving,
            reread_usd=reread, loop_usd=sum(_usd(m, u) for m, u in s.loop_usage.items()),
            inherited_agents=sum(1 for a in s.agents if not a.model), agents=len(s.agents),
            prs=s.pr_links, batch=s.batch, repos=sorted(s.touched_repos, key=lambda r: -s.touched_repos[r])[:5],
            **_day_fields(s),
        ))
    if grok_rows is None:
        try:
            from .adapters import grok
            grok_rows = grok.session_costs(since=since_epoch(days))
        except Exception:  # noqa: BLE001 — Grok not on this machine, or its store unreadable
            grok_rows = []
    for c in grok_rows:
        if (c.created or "")[:19] < cutoff:
            continue
        from .adapters import local_day
        model = c.model or "grok"
        rows.append(dict(harness="grok", sid=c.sid, project=_project(c.cwd), cwd=c.cwd, first=c.created,
                         last=c.created, usd=c.usd, by_model={model: c.usd}, sub_usd=0.0,
                         top_tier_sub_saving=0.0, reread_usd=0.0, loop_usd=0.0, inherited_agents=0, agents=0,
                         prs=c.prs, batch=False, repos=[], day_usd={local_day(c.created): c.usd},
                         day_model_usd={local_day(c.created): {model: c.usd}}, sub_day_model_usd={}, sub_calls=[]))
    return sorted(rows, key=lambda r: -r["usd"])


# --- outcome (W1, W5) ------------------------------------------------------------------------

def _git(args: list[str], cwd: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _repo_dirs(row: dict) -> list[str]:
    """Where the session's commits would be: its cwd's repo, else the repos its tool calls touched.
    A removed worktree (~/.worktrees/<repo>/<branch>) falls back to <code root>/<repo>."""
    root = str(config.code_root())
    out = []
    cwd = row.get("cwd")
    if cwd and os.path.isdir(cwd) and _git(["rev-parse", "--show-toplevel"], cwd):
        out.append(cwd)  # and the repos it touched: work started in A is often committed in B
    elif cwd and ".worktrees" in pathlib.Path(cwd).parts:
        out.append(os.path.join(root, row["project"]))
    out += [os.path.join(root, r) for r in row.get("repos") or []]
    return [d for d in dict.fromkeys(out) if os.path.isdir(os.path.join(d, ".git")) or _git(["rev-parse", "--git-dir"], d)]


def _ts(s: str | None) -> _dt.datetime | None:
    try:
        return _dt.datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def outcome(row: dict) -> bool | None:
    """True when a PR was opened in the session or a commit landed in its repo (any branch) between
    its first message and a day after its last; False when neither; None when there is no repo to
    look in (the finding needs a place to point at)."""
    if row.get("prs"):
        return True
    start, end = _ts(row.get("first")), _ts(row.get("last"))
    if not start or not end:
        return None
    dirs = _repo_dirs(row)
    if not dirs:
        return None
    until = end + _dt.timedelta(hours=OUTCOME_GRACE_H)
    failed = False
    for d in dirs:
        out = _git(["log", "--all", "-n1", "--format=%H", f"--since={start.isoformat()}", f"--until={until.isoformat()}"], d)
        if out:
            return True
        failed = failed or out is None  # git failed: an empty answer we cannot trust
    return None if failed else False


# --- GitHub Actions (W8) ---------------------------------------------------------------------

def _gh_json(path: str):
    if not shutil.which("gh"):
        return None
    try:
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def actions_usage(today: _dt.date | None = None, gh=_gh_json) -> list[dict] | None:
    """This month's Actions use for the gh user and each org it belongs to, or None when gh or the
    network is not available. Minutes are the included minutes used, Linux-equivalent (discounted
    dollars / Linux price), which is how GitHub counts them: a standard macOS minute is ten."""
    from . import net
    if not net.gate("gh api (Actions billing)", quiet=True):
        return None
    today = today or _dt.date.today()
    me = gh("/user")
    if not isinstance(me, dict) or not me.get("login"):
        return None
    accounts = [("users", me["login"], (me.get("plan") or {}).get("name"))]
    for o in gh("/user/orgs") or []:
        plan = (gh(f"/orgs/{o['login']}") or {}).get("plan") or {}
        accounts.append(("organizations", o["login"], plan.get("name")))
    out = []
    for kind, login, plan in accounts:
        data = gh(f"/{kind}/{login}/settings/billing/usage?year={today.year}&month={today.month}")
        if not isinstance(data, dict):
            continue
        items = [i for i in data.get("usageItems") or []
                 if str(i.get("product")).lower() == "actions" and str(i.get("unitType")).lower() == "minutes"]
        # The included minutes are what GitHub discounted: larger runners never draw on them, so
        # gross dollars would over-count; the discount is exactly the quota used.
        used = sum((i.get("discountAmount") if i.get("discountAmount") is not None
                    else (i.get("grossAmount") or 0) - (i.get("netAmount") or 0)) or 0 for i in items)
        net_usd = sum(i.get("netAmount") or 0 for i in items)
        by_repo, macos = Counter(), Counter()
        for i in items:
            by_repo[i.get("repositoryName") or "?"] += i.get("grossAmount") or 0
            if "macos" in str(i.get("sku") or "").lower():
                macos[i.get("repositoryName") or "?"] += i.get("quantity") or 0
        included = PLAN_MINUTES.get(str(plan or "").lower())
        minutes = used / LINUX_USD_PER_MIN
        out.append(dict(account=login, plan=plan, minutes=round(minutes), included=included,
                        share=(minutes / included) if included else None, paid_usd=round(net_usd, 2),
                        top_repos=[r for r, _ in by_repo.most_common(3)],
                        macos_minutes={r: round(q) for r, q in macos.most_common()}))
    return out


# --- rules -----------------------------------------------------------------------------------

def _who(r: dict) -> str:
    return f"{r['project']} {r['sid'][:8]} {(r.get('first') or '')[:10]}"


def _money(x: float) -> str:
    return f"${x:,.0f}" if x >= 10 else f"${x:,.2f}"


def _w2_fix() -> str:
    """W2's fix names this machine's autoCompactWindow (compaction ≈ window − 35k), or the
    recommended 335000 when ~/.claude/settings.json has none."""
    window, at, is_set = config.compaction()
    hook = ("context-budget-hook re-injects the handoff; if W2 stays high, check the session had the "
            "setting and the hook fired (~/.teyla/handoff/), and that the orchestrator "
            "delegates reading to subagents")
    if is_set:
        return f"compaction is set (autoCompactWindow {window}, ~{at // 1000}k); {hook}"
    return (f"compaction is not set: add \"autoCompactWindow\": {window} to ~/.claude/settings.json "
            f"(~{at // 1000}k); {hook}")


def findings(rows: list[dict], actions: list[dict] | None = None, outcome_of=outcome,
             coverage: list[str] | None = None, spikes: list[dict] | None = None) -> list[dict]:
    """The waste findings, largest first: {id, usd, title, evidence, fix, cmd}. `usd` is None for
    W8, whose cost is minutes, not tokens. What a rule could not check is appended to `coverage`."""
    F = []
    coverage = [] if coverage is None else coverage
    w1 = setting("w1_usd")
    for rid, harness_ok, fix in (
        ("W1", lambda h: h != "grok",
         "a session that stops without a commit should push a draft PR first (the compaction handoff keeps "
         "a session going, it does not ship anything); resume the top one and ship or drop the work"),
        ("W5", lambda h: h == "grok",
         "POLICY §1 for Grok lanes: a file manifest, --max-turns, and paste-only fixes applied by hand; "
         "`teyla grok-cost --by session`"),
    ):
        idle, unknown = [], []
        for r in rows:
            if not harness_ok(r["harness"]) or r["batch"] or r["usd"] < w1:
                continue
            verdict = outcome_of(r)
            if verdict is False:
                idle.append(r)
            elif verdict is None:
                unknown.append(r)
        if unknown:
            coverage.append(f"{rid}: {len(unknown)} session(s) over {_money(w1)} had no repo to check "
                            f"({_money(sum(r['usd'] for r in unknown))})")
        if idle:
            total = sum(r["usd"] for r in idle)
            F.append(dict(id=rid, usd=total, cmd=False, fix=fix, sids=[r["sid"] for r in idle],
                          title=f"{len(idle)} session(s) over {_money(w1)} left no commit or PR",
                          evidence="; ".join(f"{_who(r)} {_money(r['usd'])}" for r in idle[:3])))
    reread = [r for r in rows if r["reread_usd"] > 0]
    if reread:
        reread.sort(key=lambda r: -r["reread_usd"])
        F.append(dict(id="W2", usd=sum(r["reread_usd"] for r in reread), cmd=False,
                      title=f"re-reading context past 250k tokens in {len(reread)} session(s)",
                      evidence="; ".join(f"{_who(r)} {_money(r['reread_usd'])}" for r in reread[:3]),
                      fix=_w2_fix()))
    top = [r for r in rows if r["top_tier_sub_saving"] > 0]
    if top:
        top.sort(key=lambda r: -r["top_tier_sub_saving"])
        inherited = sum(r["inherited_agents"] for r in top); calls = sum(r["agents"] for r in top)
        F.append(dict(id="W3", usd=sum(r["top_tier_sub_saving"] for r in top), cmd=False,
                      title="Fable ran in subagents: the saving at Sonnet 5.5",
                      evidence=f"{inherited} of {calls} Agent calls in those sessions inherited the model; "
                               + "; ".join(f"{_who(r)} {_money(r['top_tier_sub_saving'])}" for r in top[:2]),
                      fix='pass model: "sonnet" (or "haiku") on every Agent call that reads, summarises or drafts'))
    loops = [r for r in rows if r["loop_usd"] > 0]
    if loops:
        loops.sort(key=lambda r: -r["loop_usd"])
        F.append(dict(id="W6", usd=sum(r["loop_usd"] for r in loops), cmd=False,
                      title=f"failed loops (3+ failed tool calls in a row) in {len(loops)} session(s)",
                      evidence="; ".join(f"{_who(r)} {_money(r['loop_usd'])}" for r in loops[:3]),
                      fix="after three failures in a row stop, read the error, and change the approach (or ask)"))
    if spikes:
        F.append(dict(id="W7", usd=sum(s["excess"] for s in spikes), cmd=False,
                      title=f"{len(spikes)} day(s) of product API spend past 2x the week's median",
                      evidence="; ".join(f"{s['provider']} {s['group']} {s['day']} {_money(s['usd'])} (median {_money(s['median'])})"
                                         for s in spikes[:3]),
                      fix="open that product's logs for the day: a deploy, a retry loop or a model switch; "
                          "cap it (max_tokens, retries, a cheaper model on the path) before it repeats"))
    F = [f for f in F if f["usd"] >= FINDING_FLOOR_USD]
    for a in actions or []:
        if a["share"] is not None and a["share"] >= ALERT_ACTIONS_SHARE or a["paid_usd"] > 0:
            mac = ", ".join(f"{r} {m} min" for r, m in a["macos_minutes"].items())
            F.append(dict(id="W8", usd=None, cmd=False,
                          title=f"GitHub Actions {a['account']}: {a['minutes']} of {a['included'] or '?'} included minutes"
                                + (f", {_money(a['paid_usd'])} paid" if a["paid_usd"] > 0 else ""),
                          evidence=f"top repos {', '.join(a['top_repos'])}" + (f"; macOS: {mac}" if mac else ""),
                          fix="turn the remaining automatic triggers into workflow_dispatch (POLICY §10); never macOS on a trigger"))
    return sorted(F, key=lambda f: -(f["usd"] if f["usd"] is not None else 1e9))


# --- report ----------------------------------------------------------------------------------

def report(days: int = 7, rows=None, actions=None, with_actions: bool = True, bills=None) -> dict:
    from . import providers
    rows = session_rows(days) if rows is None else rows
    if actions is None and with_actions:
        actions = actions_usage()
    bills = providers.read(days) if bills is None else bills
    coverage: list[str] = [f"W7: {p} not read ({b.get('skipped') or b.get('error')})"
                           for p, b in bills.items() if "daily" not in b]
    F = findings(rows, actions, coverage=coverage, spikes=providers.spikes(bills, days))
    by_harness, by_model = Counter(), Counter()
    for r in rows:
        by_harness[r["harness"]] += r["usd"]
        for m, v in r["by_model"].items():
            by_model[m] += v
    total = sum(by_harness.values())
    waste = waste_usd(rows, F)
    return dict(days=days, total_usd=total, sub_usd=sum(r["sub_usd"] for r in rows), waste_usd=waste,
                product_waste_usd=sum(f["usd"] for f in F if f["id"] == "W7"),
                by_harness=dict(by_harness.most_common()), by_model=dict(by_model.most_common()),
                findings=F, actions=actions,
                top_sessions=[{k: v for k, v in r.items() if k not in DAY_KEYS} for r in rows[:5]], sessions=len(rows), coverage=coverage,
                providers=providers.totals(bills, days))


def waste_usd(rows: list[dict], F: list[dict]) -> float:
    """The waste total without counting a dollar twice: a session with no outcome is waste whole
    (its re-reads and loops are inside that); any other session's W2/W3/W6 dollars are capped at
    what it cost. W7 is product API spend, not part of the sessions' total, so it is reported on its
    own (product_waste_usd) and never inflates the share; W8 is minutes, not dollars."""
    idle = {sid for f in F if f["id"] in ("W1", "W5") for sid in f.get("sids") or []}
    shown = {f["id"] for f in F}  # a rule under the floor is not reported, so its dollars do not count

    def partial(r):
        return ((r["reread_usd"] if "W2" in shown else 0) + (r["loop_usd"] if "W6" in shown else 0)
                + (r["top_tier_sub_saving"] if "W3" in shown else 0))
    per_session = sum(r["usd"] if r["sid"] in idle else min(r["usd"], partial(r)) for r in rows)
    return per_session


def summary_line(rep: dict) -> str:
    total = rep["total_usd"]
    share = f" ({rep['waste_usd'] / total * 100:.0f}%)" if total else ""
    product = rep.get("product_waste_usd") or 0
    return (f"spend {rep['days']}d: {_money(total)} API-equivalent, {_money(rep['waste_usd'])} of it waste{share}"
            + (f", plus {_money(product)} of product API spikes" if product else "")
            + (f"; top: {rep['findings'][0]['id']} {rep['findings'][0]['title']}" if rep["findings"] else ""))


def render(rep: dict) -> str:
    L = [f"teyla spend — last {rep['days']} days, API list price (a subscription bills differently)", "",
         f"total {_money(rep['total_usd'])} over {rep['sessions']} sessions  ·  "
         + "  ·  ".join(f"{h} {_money(v)}" for h, v in rep["by_harness"].items() if v >= 0.01)
         + (f"  ·  of which subagents {_money(rep['sub_usd'])}" if rep["sub_usd"] else ""),
         "by model: " + ", ".join(f"{m} {_money(v)}" for m, v in list(rep["by_model"].items())[:6])]
    for prov, groups in (rep.get("providers") or {}).items():
        L.append(f"{prov} billed (products, all keys): {_money(sum(groups.values()))}"
                 + (" — " + ", ".join(f"{g} {_money(v)}" for g, v in list(groups.items())[:5]) if groups else ""))
    L.append("")
    if rep["findings"]:
        L.append(f"waste {_money(rep['waste_usd'])}"
                 + (f" + product spikes {_money(rep['product_waste_usd'])}" if rep.get("product_waste_usd") else "")
                 + ":")
        for f in rep["findings"]:
            money = _money(f["usd"]) if f["usd"] is not None else "—"
            L += [f"  {f['id']} {money:>7}  {f['title']}", f"              {f['evidence']}", f"              fix: {f['fix']}"]
    else:
        L.append("waste: nothing over the thresholds")
    if rep.get("actions") is None:
        L.append("  W8 GitHub Actions: not checked (no gh, no network, or safe mode)")
    L += [f"  {c}" for c in rep.get("coverage") or []]
    L += ["", NOT_COVERED, "", "top sessions:"]
    L += [f"  {_money(r['usd']):>7}  {r['harness']:<11} {_who(r)}" for r in rep["top_sessions"]]
    return "\n".join(L)


# --- digest and daily alert ------------------------------------------------------------------

def digest_candidates(rep: dict) -> list[dict]:
    """Waste findings as digest candidates (teyla.digest.candidates' shape). A finding worth $25 or
    more ranks with high advice; the rest with medium."""
    out = []
    for f in rep["findings"]:
        money = _money(f["usd"]) if f["usd"] is not None else ""
        out.append(dict(rank=1 if (f["usd"] or 0) >= 25 or f["id"] == "W8" else 4, id=f"spend:{f['id']}",
                        text=f"{f['id']} {money} {f['title']}".replace("  ", " "), step=f["fix"], cmd=False))
    return out


def _top(d: dict, n: int = 3) -> list[tuple[str, float]]:
    return sorted(((k, v) for k, v in d.items() if v > 0), key=lambda kv: -kv[1])[:n]


def _budget_alert(rows: list[dict], day: str, project: str | None, budget: float) -> dict | None:
    """One budget alert for `day`: a project's cost that day (`project`), or the day's total (None),
    against `budget`. Names the amount, the budget, the top three sessions and the top model by cost."""
    sessions, models, projects = {}, {}, {}
    for r in rows:
        if project is not None and r["project"] != project:
            continue
        usd = (r.get("day_usd") or {}).get(day, 0.0)
        if usd <= 0:
            continue
        sessions[f"{r['sid'][:8]}"] = sessions.get(f"{r['sid'][:8]}", 0.0) + usd
        projects[r["project"]] = projects.get(r["project"], 0.0) + usd
        for m, v in ((r.get("day_model_usd") or {}).get(day) or {}).items():
            models[m] = models.get(m, 0.0) + v
    total = sum(projects.values())
    if total <= budget:
        return None
    top_sessions = ", ".join(f"{s} {_money(v)}" for s, v in _top(sessions))
    top_model = _top(models, 1)
    who = f"project {project}" if project is not None else "all projects"
    text = (f"budget: {who} cost {_money(total)} on {day}, over its {_money(budget)} a day"
            + (f" (largest: {', '.join(f'{p} {_money(v)}' for p, v in _top(projects))})" if project is None else "")
            + f"; top sessions {top_sessions}"
            + (f"; top model {top_model[0][0]} {_money(top_model[0][1])}" if top_model else ""))
    # The key names the budget, not the day: the same overspend every day is one alert until it
    # grows by the dedupe margin.
    return dict(key=f"budget:{project or '*'}", usd=total, text=text)


def alert_items(rows: list[dict], actions: list[dict] | None, now: _dt.datetime | None = None,
                spikes: list[dict] | None = None, cfg: dict | None = None) -> list[dict]:
    """Everything `--alert` would say before the dedupe: {key, usd, text}. `usd` is the amount the
    dedupe compares (Actions: the percent of included minutes); `key` names the thing, so yesterday's
    alert and today's can be recognised as the same one."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    cfg = cfg or config.load()
    since = (now - _dt.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
    limit = setting("alert_session_usd", cfg)
    out = [dict(key=f"session:{r['harness']}:{r['sid']}", usd=r["usd"],
                text=f"session {_who(r)} cost {_money(r['usd'])} ({r['harness']})")
           for r in rows if r["usd"] >= limit and (r.get("last") or "")[:19] >= since]
    # Yesterday, by the local calendar: the day is over, so its total is final.
    yesterday = (now.astimezone().date() - _dt.timedelta(days=1)).isoformat()
    total_budget, per_project = budgets(cfg)
    for project, budget in sorted(per_project.items()):
        a = _budget_alert(rows, yesterday, project, budget)
        if a:
            out.append(a)
    if total_budget > 0:
        a = _budget_alert(rows, yesterday, None, total_budget)
        if a:
            out.append(a)
    for a in actions or []:
        if a["share"] is not None and a["share"] >= ALERT_ACTIONS_SHARE:
            out.append(dict(key=f"actions:{a['account']}", usd=a["share"] * 100,
                            text=f"GitHub Actions {a['account']} at {a['share'] * 100:.0f}% of included minutes"))
    for s in spikes or []:
        out.append(dict(key=f"spike:{s['provider']}:{s['group']}:{s['day']}", usd=s["usd"],
                        text=f"{s['provider']} {s['group']} spent {_money(s['usd'])} on {s['day']} (median {_money(s['median'])})"))
    return out


def alerts(rows: list[dict], actions: list[dict] | None, now: _dt.datetime | None = None,
           spikes: list[dict] | None = None, cfg: dict | None = None) -> list[str]:
    return [a["text"] for a in alert_items(rows, actions, now, spikes, cfg)]


def state_path() -> pathlib.Path:
    return config.TEYLA_DIR / "state" / "spend-alerts.json"


def dedupe(items: list[dict], today: _dt.date, state: dict | None = None) -> tuple[list[dict], list[dict], dict]:
    """(new, shown, state'). An alert given yesterday (or kept quiet yesterday for being the same) is
    not given again today unless its amount grew by ALERT_REGROWTH over the amount last given; one
    already given today stays shown. `new` are the ones to notify about, `shown` all that go in the
    banner file. State: key -> {alerted: day, usd: the amount given, seen: last day it was true}."""
    state = {k: dict(v) for k, v in (state or {}).items() if isinstance(v, dict)}
    yesterday = (today - _dt.timedelta(days=1)).isoformat()
    day = today.isoformat()
    new, shown = [], []
    for a in items:
        st = state.get(a["key"])
        grew = not st or a["usd"] >= _number(st.get("usd"), 0.0) * (1 + ALERT_REGROWTH)
        if st and not grew and st.get("alerted") == day:
            shown.append(a)
        elif st and not grew and str(st.get("seen") or "") >= yesterday:
            st["seen"] = day  # same thing, still true: quiet, and the streak goes on
        else:
            state[a["key"]] = dict(alerted=day, usd=a["usd"], seen=day)
            new.append(a); shown.append(a)
    # Forget what has not been true for two weeks.
    keep = (today - _dt.timedelta(days=14)).isoformat()
    return new, shown, {k: v for k, v in state.items() if str(v.get("seen") or "") >= keep}


def _read_state() -> dict:
    try:
        raw = json.loads(state_path().read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def notify(lines: list[str]) -> bool:
    from .storage import _truthy
    if not lines or sys.platform != "darwin" or not shutil.which("osascript"):
        return False
    if not _truthy((config.load().get("digest") or {}).get("notify", True)):
        return False
    text = "; ".join(lines)[:200].replace("\\", "\\\\").replace('"', '\\"')
    try:
        r = subprocess.run(["osascript", "-e", f'display notification "{text}" with title "Teyla spend"'],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def alerts_path() -> pathlib.Path:
    """What the session-start banner shows: the current alerts, one per line, no date. Written by
    every `--alert` run and removed when there is nothing to say."""
    return config.TEYLA_DIR / "spend.alert"


def run_alert(items: list[dict], today: _dt.date, write: bool = True) -> list[dict]:
    """Dedupe against yesterday's state, print what is shown, and (unless `write` is off) leave the
    banner file and the state behind. Returns the alerts that are new today, for the notification."""
    new, shown, state = dedupe(items, today, _read_state())
    if write:
        # The banner reads this file (plugin/hooks/session-start.sh): the current alerts, or no file.
        write_alert_file([a["text"] for a in shown])
        config.write_private(state_path(), json.dumps(state, indent=1) + "\n")
    for a in shown:
        print(f"teyla spend alert: {a['text']}")
    return new


def write_alert_file(lines: list[str]) -> None:
    p = alerts_path()
    # The file this one replaced carried a date per line and went through banner.items.
    (config.TEYLA_DIR / "spend.alerts").unlink(missing_ok=True)
    if lines:
        config.write_private(p, "".join(l.replace("\n", " ") + "\n" for l in lines))
    else:
        p.unlink(missing_ok=True)


# --- per day ---------------------------------------------------------------------------------

TIERS = ("orchestrate", "volume", "triage", "unknown")


def by_day(days: int = 7, rows: list[dict] | None = None, today: _dt.date | None = None) -> list[dict]:
    """One row per local day, oldest first, for the last `days` days including today: total cost, the
    subagents' cost, and the subagents' cost and calls by model tier (a model with no price is
    "unknown"), with the top tier's share of the subagent cost. Cost is split by the day each message
    was sent, not by the session's start; harnesses without per-message times book a session on its
    last day (see _day_fields)."""
    from .pricing import tier
    today = today or _dt.date.today()
    window = [(today - _dt.timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    rows = session_rows(days + 1) if rows is None else rows
    out = {d: dict(day=d, total_usd=0.0, sub_usd=0.0, sessions=0,
                   tiers={t: dict(usd=0.0, calls=0) for t in TIERS}) for d in window}
    for r in rows:
        touched = set()
        for d, usd in (r.get("day_usd") or {}).items():
            if d in out:
                out[d]["total_usd"] += usd
                touched.add(d)
        for d, mm in (r.get("sub_day_model_usd") or {}).items():
            if d in out:
                for m, usd in mm.items():
                    out[d]["sub_usd"] += usd
                    out[d]["tiers"][tier(m)]["usd"] += usd
        for d, m in r.get("sub_calls") or []:
            if d in out:
                out[d]["tiers"][tier(m)]["calls"] += 1
        for d in touched:
            out[d]["sessions"] += 1
    for row in out.values():
        top = row["tiers"]["orchestrate"]["usd"]
        row["top_share"] = round(top / row["sub_usd"], 3) if row["sub_usd"] else None
        row["total_usd"] = round(row["total_usd"], 2)
        row["sub_usd"] = round(row["sub_usd"], 2)
        for v in row["tiers"].values():
            v["usd"] = round(v["usd"], 2)
    return list(out.values())


def render_by_day(rows: list[dict]) -> str:
    cell = lambda v: f"{_money(v['usd'])}/{v['calls']}" if v["usd"] or v["calls"] else "-"
    L = [f"teyla spend --by-day — API list price; subagent columns are cost/calls by the tier the subagent ran on", "",
         f"{'day':<10}  {'total':>8}  {'subagents':>9}  " + "  ".join(f"{t:>14}" for t in TIERS) + "  top-tier share"]
    for r in rows:
        share = f"{r['top_share'] * 100:.0f}%" if r["top_share"] is not None else "-"
        L.append(f"{r['day']:<10}  {_money(r['total_usd']):>8}  {_money(r['sub_usd']):>9}  "
                 + "  ".join(f"{cell(r['tiers'][t]):>14}" for t in TIERS) + f"  {share:>14}")
    return "\n".join(L)


# --- command ---------------------------------------------------------------------------------

def cmd_spend(args) -> int:
    if args.by_day:
        rows = by_day(max(1, args.days))
        print(json.dumps(dict(days=args.days, rows=rows), indent=1) if args.json else render_by_day(rows))
        return 0
    if args.alert:
        from . import providers
        # Three days of sessions: the budget check looks at yesterday, the session check at the last 24 h.
        rows = session_rows(3)
        # Yesterday and today (UTC): the providers' day is UTC and today's bucket is still filling.
        items = alert_items(rows, actions_usage(), spikes=providers.spikes(providers.read(2), 2))
        new = run_alert(items, _dt.date.today(), write=not args.no_write)
        if new and not args.no_notify and not args.no_write:
            notify([a["text"] for a in new])
        return 0
    rep = report(args.days, with_actions=not args.no_actions)
    if args.json:
        print(json.dumps(rep, indent=1, default=str))
    else:
        print(render(rep))
    return 0


def register(sp):
    q = sp.add_parser("spend", help="what the AI work cost and which part of it bought nothing (W1–W8), each with a fix")
    q.set_defaults(fn=cmd_spend)
    q.add_argument("--days", type=int, default=7)
    q.add_argument("--json", action="store_true")
    q.add_argument("--by-day", action="store_true", help="one row per day: total, subagent cost, and subagent cost/calls by model tier")
    q.add_argument("--alert", action="store_true",
                   help="the daily check: a session over spend.alert_session_usd in the last day, a project or the day over its budget yesterday, Actions past 80%%")
    q.add_argument("--no-write", action="store_true", help="--alert: print only; leave ~/.teyla/spend.alert and the dedupe state alone")
    q.add_argument("--no-actions", action="store_true", help="skip the GitHub Actions billing call")
    q.add_argument("--no-notify", action="store_true", help="--alert: no macOS notification")
    q.add_argument("--allow-network", action="store_true", help="safe mode: allow gh for this one run")
    return q

"""Aggregate Sessions into the adoption metrics the report and the advice rules read."""
from __future__ import annotations

import datetime as _dt
from collections import Counter, defaultdict

from .adapters import Session
from .pricing import cost_usd, tier

GIANT_BYTES = 8_000_000
LONG_ACTIVE_HOURS = 12  # active_hours, not wall span — a session resumed after days is not giant


def metrics(sessions: list[Session], days: int | None = None) -> dict:
    if days:
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
        sessions = [s for s in sessions if (s.first or "")[:19] >= cutoff]
    m: dict = {"n_sessions": len(sessions), "days": days}
    tok = Counter(); by_model = defaultdict(Counter); by_project = defaultdict(lambda: defaultdict(Counter))
    by_harness = Counter(); by_day = defaultdict(Counter); cost = 0.0; cost_known = 0; cost_unknown = set()
    user_turns = corr = 0; agents = Counter(); giant = []; skills = Counter(); tools = Counter()
    corr_texts = []; gov = []
    batch_by_harness = Counter()
    for s in sessions:
        by_harness[s.harness] += 1
        if s.batch:
            batch_by_harness[s.harness] += 1
        for model, u in s.usage.items():
            by_model[model].update(u); tok.update(u)
            c = cost_usd(model, u)
            if c is None:
                cost_unknown.add(model)
            else:
                cost += c; cost_known += 1
            by_project[s.project][model].update(u)
        by_day[s.day]["sessions"] += 1; by_day[s.day]["output_tokens"] += s.tokens["output_tokens"]
        if not s.batch:
            user_turns += s.n_user; corr += s.n_corr
            corr_texts += [t.text[:200] for t in s.user_turns if t.corr]
        for a in s.agents:
            agents[a.model or "inherit"] += 1
        skills.update(s.skills); tools.update(s.tools)
        if s.gov_edits:
            gov.append(dict(project=s.project, sid=s.sid[:8], day=s.day, edits=s.gov_edits,
                            days=sorted(s.gov_days) or [s.day]))
        # One human turn is already one logical unit: a big autonomous run cannot be "split into
        # one session per unit", so size alone never makes it giant. It still counts when it ran
        # for more active hours than a unit should, or compacted repeatedly — those are the
        # shapes A3's advice actually addresses.
        oversized = s.size > GIANT_BYTES and s.n_user > 1
        if oversized or (s.active_hours or 0) > LONG_ACTIVE_HOURS or s.compactions >= 3:
            giant.append(dict(project=s.project, sid=s.sid[:8], day=s.day, mb=round(s.size / 1e6, 1), hours=s.hours,
                              active_hours=round(s.active_hours or 0, 2),
                              compactions=s.compactions, turns=s.n_user, out=s.tokens["output_tokens"]))
    out_by_tier = Counter()
    for model, u in by_model.items():
        out_by_tier[tier(model)] += u["output_tokens"]
    total_tool_calls = sum(tools.values())
    connector_calls = sum(v for k, v in tools.items() if (k or "").startswith("mcp__"))
    connector_share = round(connector_calls / total_tool_calls, 3) if total_tool_calls else None
    m.update(dict(
        tokens=dict(tok), by_model={k: dict(v) for k, v in by_model.items()},
        by_project={p: {k: dict(v) for k, v in mm.items()} for p, mm in by_project.items()},
        by_harness=dict(by_harness), batch_by_harness=dict(batch_by_harness), by_day={d: dict(v) for d, v in sorted(by_day.items())},
        cost_estimate_usd=round(cost, 2), cost_models_unknown=sorted(cost_unknown),
        user_turns=user_turns, corrections=corr,
        correction_rate=round(corr / user_turns, 3) if user_turns else None,
        subagents=dict(agents), subagent_inherit_rate=round(agents["inherit"] / sum(agents.values()), 2) if agents else None,
        output_by_tier=dict(out_by_tier),
        orchestrator_share=round(out_by_tier["orchestrate"] / max(1, sum(out_by_tier.values())), 2),
        cache_read_ratio=round(tok["cache_read_input_tokens"] / max(1, tok["output_tokens"]), 1),
        giant_sessions=sorted(giant, key=lambda g: -g["mb"]), skills=dict(skills), tools=dict(tools.most_common(30)),
        total_tool_calls=total_tool_calls, connector_calls=connector_calls, connector_share=connector_share,
        correction_samples=corr_texts[:50], governance_edits=gov,
        wrong_root=[dict(project=s.project, sid=s.sid[:8], cwd=s.cwd) for s in sessions
                    if s.cwd and s.cwd.rstrip("/").endswith("/repos")],
    ))
    m["models_drift"] = _models_drift(sessions, days)
    m["headless"] = headless(sessions, days)  # cli.py adds Grok's list-price cost (grok_rows)
    from .detect import permission_ask_metrics
    m["permission_asks"] = permission_ask_metrics(sessions)
    try:
        from . import connectors as _c
        m["connectors"] = _c.metrics(sessions)
    except Exception:  # noqa: BLE001
        m["connectors"] = None
    return m


# --- headless volume -----------------------------------------------------------------------------
#
# A batch session is one headless call: `claude -p`, `codex exec`, `grok -p` from a script or
# another agent (adapters set `batch`). In September 2026 they were 15,236 of Grok's 15,240 and
# 534 of Codex's 545 sessions here, and the Grok ones were invisible: Grok stores no per-message
# token counts, so the By-model table had no Grok row, until the balance ran out (HTTP 402).
# Grok's list-price cost comes from `teyla grok-cost` (adapters.grok.session_costs,
# costUsdTicks), passed in as `grok_rows`; other harnesses are priced from their tokens with
# pricing.cost_usd. Where neither exists the row says "calls, tokens unknown", never $0.

HEADLESS_PER_DAY = 200       # A17: one project driving more headless calls a day than this
HEADLESS_DOUBLING_FLOOR = 100  # A17: "doubled week over week" only counts from this many calls in the previous week


def headless(sessions: list[Session], days: int | None, grok_rows: list | None = None,
             now: _dt.datetime | None = None) -> list[dict]:
    """Per harness and project: headless calls in the last 7 days, the 7 before, and the window
    (up to 29 days), per day, with an API-equivalent cost where one is known."""
    from .grokcost import project_of
    now = now or _dt.datetime.now(_dt.timezone.utc)
    span = min(days or 29, 29)
    edge = {k: (now - _dt.timedelta(days=k)).strftime("%Y-%m-%dT%H:%M:%S") for k in (7, 14, span)}
    grok_usd = {c.sid: c.usd for c in (grok_rows or []) if getattr(c, "turns", 0)}
    rows: dict = {}
    for s in sessions:
        if not s.batch:
            continue
        ts = (s.first or s.last or "")[:19]
        if ts < edge[span]:
            continue
        key = (s.harness, project_of(s.cwd or s.project))
        r = rows.setdefault(key, dict(harness=key[0], project=key[1], calls=0, calls_7d=0, calls_prev_7d=0,
                                      usd=0.0, priced=0, tokens_known=0, unpriced_models=set()))
        r["calls"] += 1
        if ts >= edge[7]:
            r["calls_7d"] += 1
        elif ts >= edge[14]:
            r["calls_prev_7d"] += 1
        if s.harness == "grok":
            if s.sid in grok_usd:
                r["usd"] += grok_usd[s.sid]; r["priced"] += 1; r["tokens_known"] += 1
            continue
        if s.usage:
            r["tokens_known"] += 1
            unpriced = False
            for model, u in s.usage.items():
                c = cost_usd(model, u)
                if c is None:
                    r["unpriced_models"].add(model); unpriced = True
                else:
                    r["usd"] += c
            if not unpriced:  # per session: one unpriced call must not un-price the ones before it
                r["priced"] += 1
    out = []
    for r in rows.values():
        r["per_day_7d"] = round(r["calls_7d"] / 7, 1)
        r["per_day_window"] = round(r["calls"] / span, 1)
        r["window_days"] = span
        if not r["tokens_known"]:
            r["cost_note"] = "calls, tokens unknown"
        elif r["unpriced_models"]:
            r["cost_note"] = "no list price for " + ", ".join(sorted(r["unpriced_models"]))
        else:
            r["cost_note"] = "list price" if r["harness"] == "grok" else "API-equivalent"
        # A cost known for only some of the calls is a floor, not the total (review of #69, P2).
        r["cost_partial"] = bool(r["tokens_known"]) and r["priced"] < r["calls"]
        if r["cost_partial"]:
            r["cost_note"] += f", partial: {r['priced']} of {r['calls']} calls costed"
        r["unpriced_models"] = sorted(r["unpriced_models"])
        r["usd"] = round(r["usd"], 2)
        # The floor is the baseline: 100 calls this week after none last week is a start, not a doubling
        # (review of #69, P2).
        r["doubled"] = r["calls_prev_7d"] >= HEADLESS_DOUBLING_FLOOR and span >= 14 and r["calls_7d"] >= 2 * r["calls_prev_7d"]
        out.append(r)
    return sorted(out, key=lambda r: (-r["calls"], r["harness"], r["project"]))


def _models_drift(sessions: list[Session], days: int | None) -> list[dict]:
    """Model ladder + price drift, folded into the report. Reuses the Sessions already loaded
    here for the 'used in Claude Code' list instead of a second disk scan, and never hits the
    network (models.snapshot's refresh defaults to False) — cheap enough for every monitor run.
    Any failure (no ~/.agents/POLICY.md yet, no models.dev cache, non-macOS, ...) degrades to no
    flags rather than breaking the report."""
    try:
        from . import models as _models
        claude_used = sorted({model for s in sessions if s.harness == "claude-code" for model in s.usage.keys()})
        snap = _models.snapshot(days=days or 30, claude_used_models=claude_used)
        return _models.drift(snap)
    except Exception:  # noqa: BLE001 — advisory only, must never take the report down with it
        return []


def fingerprint(text: str) -> str:
    """Stable, irreversible id for a correction shape: sha1 of the normalised text, 10 hex chars."""
    import hashlib, re as _re
    return hashlib.sha1(_re.sub(r"\W+", " ", text.lower()).strip().encode()).hexdigest()[:10]


# Skill names that may stay readable in a shared report: Teyla's own public skills and the
# public built-ins every Claude Code install ships or Teyla's POLICY template names (§2, §3).
# Anything else is a name somebody chose — an internal plugin's skill names say what the team
# works on — so it becomes s01..sNN.
PUBLIC_SKILLS = frozenset({
    # Teyla's plugin and CLI skills, bare and namespaced
    "adoption-review", "harvest", "wiki-pass", "correct", "rule",
    "teyla:adoption-review", "teyla:harvest", "teyla:wiki-pass", "teyla:correct", "teyla:rule",
    # Claude Code built-ins
    "review", "security-review", "code-review", "init", "simplify", "loop", "schedule", "run",
    "update-config", "keybindings-help", "claude-api", "fewer-permission-prompts", "compact",
    # Anthropic's public document skills
    "pdf", "docx", "xlsx", "pptx", "skill-creator",
    # named by Teyla's POLICY template (§2 cross-provider review, §3 tool ladder)
    "codex", "grok", "autoplan", "qa", "spec",
})

# A6 asks "was any review skill used?" — answered on the real names, before they are hidden.
REVIEW_SKILL_WORDS = ("review", "codex", "grok")


def scrub_home(text: str) -> str:
    """Replace every occurrence of the home directory with `~`. The last line of defence for a
    shareable text: the structural redaction below should already have removed every path."""
    import pathlib
    home = str(pathlib.Path.home())
    if not home or home == "/":
        return text
    return text.replace(home, "~")


def _ranked_alias(counts: dict, prefix: str, keep=frozenset()) -> dict:
    """{name: pseudonym}, busiest first (ties by name, so a re-run gives the same aliases);
    names in `keep` map to themselves."""
    alias, i = {}, 0
    for name in sorted(counts, key=lambda k: (-counts[k], str(k))):
        if name in keep:
            alias[name] = name
        else:
            i += 1
            alias[name] = f"{prefix}{i:02d}"
    return alias


def redact(m: dict) -> dict:
    """A copy of the metrics safe to share. Compute findings from THIS, never from the raw
    metrics: advice evidence quotes projects, sessions and connectors, and whatever advise()
    reads is what the report prints.

    - projects become p01..pNN (ordered by output tokens); session ids and cwd paths are dropped
    - MCP connectors (server ids and display names) become c01..cNN and their tool verbs
      t01..tNN (per connector), in the connector table and in `mcp__<server>__<tool>` names
    - skills become s01..sNN, except PUBLIC_SKILLS
    - correction text is dropped; only its irreversible fingerprints stay
    Model names and built-in tool names stay: they are the vocabulary the advice is written in."""
    import copy
    from . import connectors as _c
    r = copy.deepcopy(m)
    order = sorted(r["by_project"], key=lambda p: -sum(u.get("output_tokens", 0) for u in r["by_project"][p].values()))
    alias = {p: f"p{i+1:02d}" for i, p in enumerate(order)}
    r["by_project"] = {alias[p]: v for p, v in r["by_project"].items()}
    for g in r.get("giant_sessions", []):
        g["project"] = alias.get(g["project"], "p??"); g["sid"] = "—"
    for g in r.get("governance_edits", []):
        g["project"] = alias.get(g["project"], "p??"); g["sid"] = "—"
    r["wrong_root"] = [dict(project=alias.get(w["project"], "p??"), sid="—", cwd="—") for w in r.get("wrong_root", [])]
    # Headless rows are keyed by grok-cost's project name, not by_project's key: their own pseudonyms.
    hp = {h["project"] for h in r.get("headless") or []}
    halias = {n: f"h{i+1:02d}" for i, n in enumerate(sorted(hp))}
    for h in r.get("headless") or []:
        h["project"] = halias[h["project"]]
    gw = r.get("grok_week")
    if gw:
        # Grok cost groups by grokcost.project_of(cwd), a repo name, while by_project is keyed by
        # the cwd itself: join through project_of so the same project keeps the same pseudonym.
        try:
            from .grokcost import project_of
            galias = {project_of(p): a for p, a in alias.items() if p.startswith("/")}
        except Exception:  # noqa: BLE001 — a join is a nicety, the redaction is not
            galias = {}
        extra = {}

        def _g(name):
            # a Grok project with no token usage in this window is not in by_project: next alias
            if name in galias:
                return galias[name]
            return extra.setdefault(name, f"p{len(alias) + len(extra) + 1:02d}")
        top = gw.get("top_project")
        gw["top_project"] = _g(top)
        if isinstance(gw.get("top_session"), dict):
            gw["top_session"] = dict(gw["top_session"], sid="—", project=_g(gw["top_session"].get("project")))

    # connectors: one alias per MCP server, whether it shows up in the connector table, the tool
    # counts, or both — the same server must not be c01 in one table and c03 in the next.
    cm = r.get("connectors") or {}
    calls = Counter({s: c.get("calls", 0) for s, c in (cm.get("connectors") or {}).items()})
    for name, n in (m.get("tools") or {}).items():
        parsed = _c.parse_mcp_tool(name or "")
        if parsed and parsed[0] not in calls:
            calls[parsed[0]] = 0
    calias = _ranked_alias(calls, "c")
    # Tool verbs too, per connector: an MCP server's verbs often carry its own name
    # (`acme_get_trip`, `acme_whoami`), so a kept verb names the connector its alias hides.
    # The advice needs none of them — C1–C4 read counts and shares computed before this point.
    verbs = defaultdict(Counter)
    for name, n in (m.get("tools") or {}).items():
        parsed = _c.parse_mcp_tool(name or "")
        if parsed:
            verbs[parsed[0]][parsed[1]] += n
    for s, c in (cm.get("connectors") or {}).items():
        for t, n in list(c.get("top_tools") or []) + list(c.get("rediscovery_top") or []):
            verbs[s][t] = max(verbs[s][t], n)
    valias = {s: _ranked_alias(v, "t") for s, v in verbs.items()}
    if cm:
        cm["connectors"] = {calias[s]: dict(c, display=calias[s],
                                            top_tools=[(valias[s][t], n) for t, n in c.get("top_tools") or []],
                                            rediscovery_top=[(valias[s][t], n) for t, n in c.get("rediscovery_top") or []])
                            for s, c in (cm.get("connectors") or {}).items()}
        cm["names"] = {}
    tools = Counter()
    for name, n in (r.get("tools") or {}).items():
        parsed = _c.parse_mcp_tool(name or "")
        tools[f"mcp__{calias[parsed[0]]}__{valias[parsed[0]][parsed[1]]}" if parsed else name] += n
    r["tools"] = dict(tools)

    skills = {str(k): v for k, v in (m.get("skills") or {}).items()}
    salias = _ranked_alias(skills, "s", keep=PUBLIC_SKILLS)
    r["skills"] = {salias[k]: v for k, v in skills.items()}
    r["review_skill_used"] = any(w in k for k in skills for w in REVIEW_SKILL_WORDS)

    r["correction_samples"] = []
    # A15's example quotes the agent's own words and A16's names a repo and a workflow file:
    # the words go, the project keeps its pseudonym, repos become r01..rNN, files and paths go.
    for e in (r.get("permission_asks") or {}).get("examples", []):
        e["project"] = alias.get(e["project"], "p??"); e["sid"] = "—"; e.pop("ask", None)
    if r.get("workflow_triggers"):
        ralias = {}
        for w in r["workflow_triggers"]:
            ralias.setdefault(w["repo"], f"r{len(ralias) + 1:02d}")
        r["workflow_triggers"] = [dict(repo=ralias[w["repo"]], path=None, file=None, triggers=w["triggers"], where=w["where"])
                                  for w in r["workflow_triggers"]]
    from .adapters import is_retry
    r["correction_fingerprints"] = dict(Counter(fingerprint(t) for t in m.get("correction_samples", [])
                                                if not is_retry(t)))
    r["redacted"] = True
    return r

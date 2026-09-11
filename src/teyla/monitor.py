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
    for s in sessions:
        by_harness[s.harness] += 1
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
            gov.append(dict(project=s.project, sid=s.sid[:8], day=s.day, edits=s.gov_edits))
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
        by_harness=dict(by_harness), by_day={d: dict(v) for d, v in sorted(by_day.items())},
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
    try:
        from . import connectors as _c
        m["connectors"] = _c.metrics(sessions)
    except Exception:  # noqa: BLE001
        m["connectors"] = None
    return m


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


def redact(m: dict) -> dict:
    """A copy of the metrics safe to share: projects become p01..pNN (ordered by output tokens),
    correction text is dropped, cwd paths are dropped. Tool, skill and model names stay."""
    import copy
    r = copy.deepcopy(m)
    order = sorted(r["by_project"], key=lambda p: -sum(u.get("output_tokens", 0) for u in r["by_project"][p].values()))
    alias = {p: f"p{i+1:02d}" for i, p in enumerate(order)}
    r["by_project"] = {alias[p]: v for p, v in r["by_project"].items()}
    for g in r.get("giant_sessions", []):
        g["project"] = alias.get(g["project"], "p??"); g["sid"] = "—"
    for g in r.get("governance_edits", []):
        g["project"] = alias.get(g["project"], "p??"); g["sid"] = "—"
    r["wrong_root"] = [dict(project=alias.get(w["project"], "p??"), sid="—", cwd="—") for w in r.get("wrong_root", [])]
    r["correction_samples"] = []
    r["correction_fingerprints"] = dict(Counter(fingerprint(t) for t in m.get("correction_samples", [])))
    r["redacted"] = True
    return r

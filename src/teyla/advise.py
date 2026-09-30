"""Advice rules. Each rule reads the metrics dict and returns zero or more findings.

A finding: id, severity (high/medium/low), title, evidence (numbers), action (one imperative sentence).
Rules are deliberately simple and explainable — a finding you cannot trace to a number is noise.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter


def _fmt(n):
    return f"{n/1e6:.1f}M" if n >= 1e6 else f"{n/1e3:.0f}k"


def _ack_info() -> tuple[str | None, str | None]:
    """(acked sha256, acked date) from ~/.teyla/ack.json, or (None, None) if absent/unreadable.
    Read-only: `teyla policy ack` owns writing this file, advise() only consults it."""
    path = pathlib.Path.home() / ".teyla" / "ack.json"
    try:
        entry = json.loads(path.read_text()).get("claude_md") or {}
        return entry.get("sha256"), entry.get("date")
    except Exception:
        return None, None


def _current_claude_md_sha() -> str | None:
    path = pathlib.Path.home() / ".claude" / "CLAUDE.md"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


A10_SEEN = "a10-seen.json"
A10_UNACKED = "The global instructions file was edited and never acknowledged"


def _a10_seen_sha() -> str | None:
    try:
        return json.loads((pathlib.Path.home() / ".teyla" / A10_SEEN).read_text()).get("sha256")
    except Exception:
        return None


def mark_seen(findings: list[dict]) -> None:
    """After a report showed the never-acknowledged A10, remember the file's hash so the next
    report does not repeat it while ~/.claude/CLAUDE.md stays the same. The CLI calls this;
    advise() itself stays read-only."""
    if not any(f["id"] == "A10" and f["title"] == A10_UNACKED for f in findings):
        return
    sha = _current_claude_md_sha()
    if not sha:
        return
    from . import config
    try:
        config.write_private(pathlib.Path.home() / ".teyla" / A10_SEEN, json.dumps({"sha256": sha}) + "\n")
    except OSError:
        pass


def _a10(gov: list[dict]) -> list[dict]:
    """Sessions that wrote ~/.claude/CLAUDE.md, judged against `teyla policy ack`.

    Weeks 2026-09-15, 09-21 and 09-28 each opened with an A10 [high] for edits the owner had
    asked for — ack had never been run, so every edit in the window counted, every week, and
    the finding stopped being read. Now:
      - acknowledged, file unchanged since: only edits after the ack day count;
      - file changed since the ack: [high] for the edits after the ack day — those are the
        unacknowledged ones — and the evidence says how many of the window's edits they are
        (same-day edits are named, not counted as after: the ack has no time of day);
      - never acknowledged: one [medium] asking for a review and an ack, shown once per
        version of the file (`mark_seen`), not a [high] every week.
    """
    acked_sha, acked_date = _ack_info()
    current_sha = _current_claude_md_sha()
    last = lambda g: f"{g[-1]['project']} {g[-1]['sid']} {g[-1]['day']}"
    if not acked_sha:
        if current_sha and current_sha == _a10_seen_sha():
            return []
        return [dict(id="A10", severity="medium", title=A10_UNACKED,
                     evidence=f"{len(gov)} session(s) wrote to ~/.claude/CLAUDE.md, e.g. {last(gov)}; "
                              f"`teyla policy ack` has never been run, so none of them can be told apart from an edit you asked for",
                     action="Run `teyla policy ack` after reviewing ~/.claude/CLAUDE.md; from then on only "
                            "edits after the ack are flagged. Shown once until the file changes.")]
    # Compare the days the writes happened on, not the day the session started: a session begun
    # before the ack and resumed after it wrote after it (review of #68, P2). Metrics written
    # before `days` existed fall back to the start day.
    days = lambda g: g.get("days") or [g["day"]]
    is_after = lambda g: bool(acked_date) and any(d > acked_date for d in days(g))
    is_same_day = lambda g: bool(acked_date) and any(d == acked_date for d in days(g))
    if current_sha and current_sha == acked_sha:
        after = [g for g in gov if is_after(g)]
        if not after:
            return []
        suffix = ""
    else:
        # The ack records a day, not a time: an edit on that day may be before or after it,
        # so it is counted apart and never alone makes the finding [high].
        after = [g for g in gov if is_after(g)]
        same_day = [g for g in gov if is_same_day(g) and not is_after(g)]
        suffix = f" — file changed since your ack on {acked_date}"
        if same_day:
            suffix += f"; {len(same_day)} more on the ack day itself"
        if not after:
            return [dict(id="A10", severity="medium", title="The global instructions file changed since your ack",
                         evidence=f"no session in this window wrote it after the day of the ack "
                                  f"({len(gov)} edit(s) in the window){suffix}",
                         action="Diff ~/.claude/CLAUDE.md; if the change is yours, run `teyla policy ack`.")]
    return [dict(id="A10", severity="high", title="A session edited the global instructions file",
                 evidence=f"{len(after)} of {len(gov)} session edit(s) to ~/.claude/CLAUDE.md came after your last "
                          f"`teyla policy ack` ({acked_date}), e.g. {last(after)}{suffix}",
                 action="Diff that file now. The merge-approved list and standing rules are edited by you, "
                        "never by an agent; if the edit is not yours, revert it — if the edit is yours, "
                        "run `teyla policy ack`.")]


def advise(m: dict, policy_status: dict | None = None) -> list[dict]:
    F = []
    sub = m.get("subagents") or {}
    total_sub = sum(sub.values())
    if total_sub >= 10 and (m.get("subagent_inherit_rate") or 0) > 0.5:
        F.append(dict(id="A1", severity="high", title="Subagents inherit the parent model",
                      evidence=f"{sub.get('inherit',0)} of {total_sub} subagent calls had no model set ({int(m['subagent_inherit_rate']*100)}%)",
                      action="Pass model: sonnet (or haiku) on every Agent call that reads, summarises or drafts; keep the top model for review and synthesis."))
    connector_share = m.get("connector_share")
    connector_heavy = connector_share is not None and connector_share > 0.5
    if not connector_heavy and m.get("orchestrator_share", 0) > 0.6 and m["tokens"].get("output_tokens", 0) > 1e6:
        F.append(dict(id="A2", severity="high", title="Most output tokens come from the top-tier model",
                      evidence=f"{int(m['orchestrator_share']*100)}% of {_fmt(m['tokens']['output_tokens'])} output tokens on orchestrate-tier models",
                      action="Route volume work (boilerplate, tests, docs, bulk edits) to the volume tier; see POLICY.md §1."))
    g = m.get("giant_sessions") or []
    if g:
        worst = g[0]
        F.append(dict(id="A3", severity="medium", title=f"{len(g)} giant sessions",
                      evidence=f"largest: {worst['project']} {worst['sid']} {worst['day']} — {worst['mb']} MB, "
                               f"{worst['hours']} span h, {worst.get('active_hours', worst['hours'])} active h, "
                               f"{worst['compactions']} compactions, {worst['turns']} human turns",
                      action="Split work into one session per logical unit; start a fresh session after each merged PR instead of continuing for hours."))
    if not connector_heavy and m.get("cache_read_ratio", 0) > 150:
        F.append(dict(id="A4", severity="medium", title="Very high cache-read to output ratio",
                      evidence=f"{m['cache_read_ratio']}x cache-read tokens per output token ({_fmt(m['tokens'].get('cache_read_input_tokens',0))} read)",
                      action="Long contexts are re-read on every turn. Shorter sessions, subagents for reading, and summaries instead of whole-file reads bring this down."))
    if connector_heavy:
        F.append(dict(id="A12", severity="medium", title="Connector-heavy work: tokens are not the lever",
                      evidence=f"{int(connector_share*100)}% of tool calls are connector calls (mcp__*) — "
                               f"{m.get('connector_calls',0)} of {m.get('total_tool_calls',0)}",
                      action="run `teyla connectors` — round-trips per outcome and empty-result rate are the waste here"))
    cr = m.get("correction_rate")
    if cr is not None and m.get("user_turns", 0) >= 50 and cr > 0.08:
        sev = "high" if cr > 0.15 else "medium"
        F.append(dict(id="A5", severity=sev, title="Correction rate",
                      evidence=f"{m['corrections']} of {m['user_turns']} human turns look like corrections ({cr*100:.1f}%)",
                      action="Run `teyla corrections` to cluster them; every correction that appears twice becomes a rule in .claude/rules/ or AGENTS.md."))
    sk = m.get("skills") or {}
    if total_sub > 50 and not any(any(w in (k or "") for w in ("review", "codex", "grok")) for k in sk):
        F.append(dict(id="A6", severity="medium", title="No cross-provider or pre-merge review skill used",
                      evidence=f"skills invoked: {', '.join(list(sk)[:8]) or 'none'}",
                      action="Run /review before each PR and /codex or /grok review before anything touching money, credentials or other people's data (POLICY.md §2)."))
    wr = m.get("wrong_root") or []
    if wr:
        F.append(dict(id="A7", severity="low", title="Sessions launched from a parent directory",
                      evidence=f"{len(wr)} sessions with cwd ending in /repos, e.g. {wr[0]['sid']} — transcripts and memory land under the wrong project",
                      action="Launch from the repo root (~/repos/<repo>), never from ~/repos."))
    if policy_status:
        # None means "harness not installed" (see policy.status()) — that is not a finding,
        # only an explicit False (installed but not wired to POLICY.md) counts as missing.
        missing = [h for h, ok in policy_status.items() if ok is False]
        if missing:
            F.append(dict(id="A8", severity="medium", title="Policy not wired into every harness",
                          evidence="missing: " + ", ".join(missing),
                          action="Run `teyla policy sync` so Codex, Hermes, Grok and project AGENTS.md read the same POLICY.md."))
    # repeated corrections → rule candidates. A retry is never one: the "repeats 13×" that
    # topped A9 on 2026-09-21 was "Try again" after an API outage. The adapters no longer
    # count retries; the filter here also covers a metrics JSON written before they did.
    from .adapters import is_retry
    from .monitor import fingerprint
    norm = Counter(fingerprint(t) for t in m.get("correction_samples") or [] if not is_retry(t))
    rep = sorted(((n, fp) for fp, n in norm.items() if n >= 2), reverse=True)
    if rep:
        F.append(dict(id="A9", severity="medium", title="Corrections that repeat verbatim",
                      evidence=f"{len(rep)} shapes repeat; the most frequent {rep[0][0]} times (fingerprint {rep[0][1]}) — `teyla corrections --cluster` shows the text locally",
                      action="Each of these is a rule nobody wrote down. Add it with /teyla:rule (or a line in .claude/rules/) and it stops recurring."))
    gov = m.get("governance_edits") or []
    if gov:
        F += _a10(gov)
    drift = m.get("models_drift") or []
    if drift:
        kinds = Counter(f["flag"] for f in drift)
        F.append(dict(id="A11", severity="medium", title="Model ladder drift",
                      evidence=", ".join(f"{k}×{n}" for k, n in kinds.most_common()),
                      action="Run `teyla models --write-policy` to refresh the ladder in ~/.agents/POLICY.md from the current catalogues and credentials."))
    try:
        from . import connectors as _c
        cm = m.get("connectors")
        if cm:
            F += _c.advise(cm)
    except Exception:  # noqa: BLE001 — connector advice is optional
        pass
    try:
        from . import grokcost as _g
        F += _g.advise(m.get("grok_week"))
    except Exception:  # noqa: BLE001 — Grok cost advice is optional
        pass
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(F, key=lambda f: order[f["severity"]])

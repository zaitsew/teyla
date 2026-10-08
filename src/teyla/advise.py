"""Advice rules. Each rule reads the metrics dict and returns zero or more findings.

A finding: id, severity (high/medium/low), title, evidence (numbers), action (one imperative sentence).
Rules are deliberately simple and explainable — a finding you cannot trace to a number is noise.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter

from . import config


def _fmt(n):
    return f"{n/1e6:.1f}M" if n >= 1e6 else f"{n/1e3:.0f}k"


def _compaction() -> str:
    """Where this machine compacts, from its own ~/.claude/settings.json; the recommended
    window when it sets none (then compaction happens only near the model's full window)."""
    window, at, is_set = config.compaction()
    if is_set:
        return f"autoCompactWindow {window}: compaction at ~{at // 1000}k"
    return f"set autoCompactWindow {window} in ~/.claude/settings.json: compaction at ~{at // 1000}k"


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

    Before the ack was taken into account, every week opened with an A10 [high] for edits the
    owner had asked for: ack had never been run, so every edit in the window counted, and the
    finding stopped being read. Now:
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
    # before the ack and resumed after it wrote after it (caught in review, P2). Metrics written
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


def _a20(projects: dict) -> list[dict]:
    """A20: a project whose Agent calls name a top-tier model explicitly. A1 only sees calls that
    inherit; after the policy moves volume work down the ladder, the habit that stays is
    `model: "<top tier>"` typed on every call. Per project: more than `spend.a20_share` of its
    subagent calls (at least `spend.a20_min_calls`), with the top tier's share of its subagent cost."""
    cfg = config.load().get("spend") or {}
    try:
        share = float(cfg.get("a20_share", 0.3))
        min_calls = int(cfg.get("a20_min_calls", 10))
    except (TypeError, ValueError):
        share, min_calls = 0.3, 10
    hot = []
    for name, d in projects.items():
        calls, top = d.get("calls", 0), d.get("explicit_top", 0)
        if calls >= min_calls and calls and top / calls > share:
            hot.append((top / calls, top, name, d))
    out = []
    for frac, top, name, d in sorted(hot, key=lambda h: (-h[0], str(h[2])))[:3]:
        cost = (f"; the top tier ran {d['top_sub_usd'] / d['sub_usd'] * 100:.0f}% of its subagent cost "
                f"(${d['top_sub_usd']:,.0f} of ${d['sub_usd']:,.0f})") if d.get("sub_usd") else ""
        models = ", ".join(f"{m}×{n}" for m, n in sorted((d.get("top_models") or {}).items(), key=lambda x: -x[1])[:3])
        out.append(dict(id="A20", severity="high" if frac > 0.6 else "medium",
                        title=f"{name} names a top-tier model on its subagent calls",
                        evidence=f"{top} of {d['calls']} subagent calls in {name} set a top-tier model explicitly "
                                 f"({frac * 100:.0f}%, threshold {share * 100:.0f}% from {min_calls} calls){cost}"
                                 + (f"; {models}" if models else ""),
                        action="Route volume lanes (reading, boilerplate, tests, docs, bulk edits) to the volume tier with "
                               "model: sonnet; keep the top tier for review and design, passed on that call only."))
    return out


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
                      action=f"One session per project, compacted in place ({_compaction()}, handoff re-injected by "
                             "the context-budget hook); one PR per logical unit inside it, and reading delegated to subagents."))
    if not connector_heavy and m.get("cache_read_ratio", 0) > 150:
        F.append(dict(id="A4", severity="medium", title="Very high cache-read to output ratio",
                      evidence=f"{m['cache_read_ratio']}x cache-read tokens per output token ({_fmt(m['tokens'].get('cache_read_input_tokens',0))} read)",
                      action=f"Long contexts are re-read on every turn. Compaction ({_compaction()}), subagents for reading, and summaries instead of whole-file reads bring this down."))
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
    # Redacted metrics carry the answer precomputed: their skill names are pseudonyms.
    reviewed = m["review_skill_used"] if "review_skill_used" in m else \
        any(any(w in (k or "") for w in ("review", "codex", "grok")) for k in sk)
    if total_sub > 50 and not reviewed:
        F.append(dict(id="A6", severity="medium", title="No cross-provider or pre-merge review skill used",
                      evidence=f"skills invoked: {', '.join(list(sk)[:8]) or 'none'}",
                      action="Run /review before each PR and /codex or /grok review before anything touching money, credentials or other people's data (POLICY.md §2)."))
    wr = m.get("wrong_root") or []
    if wr:
        F.append(dict(id="A7", severity="low", title="Sessions launched from a parent directory",
                      evidence=f"{len(wr)} sessions with cwd ending in /repos, e.g. {wr[0]['project']} {wr[0]['sid']} — transcripts and memory land under the wrong project",
                      action="Launch from the repo root (~/repos/<repo>), never from ~/repos."))
    if policy_status:
        # None means "harness not installed" (see policy.status()) — that is not a finding,
        # only an explicit False (installed but not wired to POLICY.md) counts as missing.
        missing = [h for h, ok in policy_status.items() if ok is False]
        if missing:
            F.append(dict(id="A8", severity="medium", title="Policy not wired into every harness",
                          evidence="missing: " + ", ".join(missing),
                          action="Run `teyla policy sync` so Codex, Hermes, Grok and project AGENTS.md read the same POLICY.md."))
    # repeated corrections → rule candidates. A retry is never one: a "repeats 13×" that
    # topped A9 once was "Try again" after an API outage. The adapters no longer
    # count retries; the filter here also covers a metrics JSON written before they did.
    from .adapters import is_retry
    from .monitor import fingerprint
    # Redacted metrics have no samples, only their fingerprints: count those instead
    # (redact() drops retries from them too).
    norm = Counter(m["correction_fingerprints"]) if "correction_fingerprints" in m else \
        Counter(fingerprint(t) for t in m.get("correction_samples") or [] if not is_retry(t))
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
    # Policy detectors (teyla.detect): each fires only when ~/.agents/POLICY.md declares its
    # rule — `teyla.detect.enrich` puts the declared ids in m["policy_detectors"].
    declared = set(m.get("policy_detectors") or ())
    pa = m.get("permission_asks") or {}
    weeks = pa.get("by_week") or {}
    from .detect import ASK_THRESHOLD_PER_WEEK
    if "ask-permission" in declared and weeks and max(weeks.values()) >= ASK_THRESHOLD_PER_WEEK:
        ex = (pa.get("examples") or [{}])[-1]
        # Redacted metrics have no `ask` (the agent's words) and no session id: say where, not what.
        eg = ""
        if ex.get("project"):
            eg = f"; e.g. {ex['project']}" + (f" {ex['sid']}" if ex.get("sid") not in (None, "—") else "") + f" {ex.get('day', '')}"
            if ex.get("ask"):
                eg += f": \"{ex['ask']}\""
        F.append(dict(id="A15", severity="medium", title="Turns end by asking permission for the next step",
                      evidence=f"{pa.get('total', 0)} turn(s) ended with a permission question the human answered with a bare yes "
                               f"(per week: {', '.join(f'{w} {n}' for w, n in weeks.items())}; threshold {ASK_THRESHOLD_PER_WEEK}/week){eg}",
                      action="POLICY §4: do the step and report it; ask only about a product decision (with a proposed default) "
                             "or a real blocker. Say it once in the repo's rules if one repo keeps doing it."))
    wt = m.get("workflow_triggers") or []
    if "no-actions" in declared and wt:
        repos = sorted({w["repo"] for w in wt})
        w0 = wt[0]
        F.append(dict(id="A16", severity="high", title="Workflows run on push, pull_request or schedule",
                      evidence=f"{len(wt)} workflow file(s) in {len(repos)} repo(s) ({', '.join(repos[:6])}); e.g. "
                               f"{w0['repo']}{' ' + w0['file'] if w0.get('file') else ''} on: {', '.join(w0['triggers'])} ({w0['where']})",
                      action="Set `on:` to `workflow_dispatch:` only (or delete the workflow), commit and push; "
                             "`teyla doctor` lists every file. The laptop's ./check.sh is the gate."))
    # A17: headless volume one project drives through one harness (monitor.headless). Named, so
    # the loop that burnt a balance is found before the balance is gone, not after.
    from .monitor import HEADLESS_PER_DAY
    hot = [r for r in m.get("headless") or [] if r["per_day_7d"] > HEADLESS_PER_DAY or r.get("doubled")]
    for r in hot[:3]:
        cost = f", ${r['usd']:,.0f} {r['cost_note']}" if r["usd"] else f" ({r['cost_note']})"
        why = (f"{r['per_day_7d']:g} headless calls/day over the last 7 days" if r["per_day_7d"] > HEADLESS_PER_DAY
               else f"{r['calls_7d']} headless calls this week, {r['calls_prev_7d']} the week before")
        F.append(dict(id="A17", severity="high" if r["per_day_7d"] > HEADLESS_PER_DAY and r.get("doubled") else "medium",
                      title=f"{r['project']} drives {r['harness']} headless volume",
                      evidence=f"{r['project']} → {r['harness']}: {why}; {r['calls']} in {r['window_days']} days{cost}",
                      action=f"Check that {r['project']}'s routine means to call {r['harness']} this often: cap it, "
                             "batch several items per call, or move it to a cheaper provider "
                             f"({'`teyla grok-cost --by session --cwd <path>`' if r['harness'] == 'grok' else '`teyla sessions --project ' + r['project'] + '`'})."))
    # A18: a harness answered quota/balance or auth errors (health.window_errors). Still failing
    # is [high]: every routine on that harness is producing nothing.
    for e in m.get("harness_errors") or []:
        F.append(dict(id="A18", severity="high" if e["still_failing"] else "medium",
                      title=f"{e['harness']} returned {'quota/balance' if e['kind'] == 'quota' else 'auth'} errors"
                            + ("" if e["still_failing"] else " (recovered)"),
                      evidence=f"last {e['day']}" + (f", ×{e['count']}" if e.get("count", 1) > 1 else "")
                               + f": {e['message'][:140]}" + ("" if e["still_failing"] else " — later calls succeeded"),
                      action=f"{e['fix']}; `teyla harness verify` shows every harness's state."))
    F += _a20(m.get("subagent_projects") or {})
    try:
        from . import cloud as _cloud
        stuck = _cloud.stuck(m.get("cloud_sessions") or [])
    except Exception:  # noqa: BLE001 — cloud advice is optional
        stuck = []
    if stuck:
        # The failure seen in practice: cloud sessions end on a pushed branch with no
        # PR, and days later still have none. The work exists; nobody sees it.
        s0 = max(stuck, key=lambda s: s["age_hours"])
        F.append(dict(id="A19", severity="high", title="Cloud work with no PR",
                      evidence=f"{len(stuck)} cloud branch(es) with commits and no PR after 24 h; oldest shown: "
                               f"{s0['repo']} {s0['branch']} — {s0['commits']} commit(s), last {s0['age_hours']:.0f} h ago",
                      action=("Run `teyla cloud inbox` for each branch and its `gh pr create` line"
                              if m.get("redacted") else
                              f"Open it: `{_cloud.open_pr_command(s0)}`, then build and review it in a local session; "
                              "`teyla cloud inbox` lists the rest.")))
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

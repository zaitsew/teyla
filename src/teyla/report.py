"""Render metrics + findings as markdown (and JSON). Aggregates only — no transcript content leaves the machine
unless you choose to share the correction samples section."""
from __future__ import annotations

import datetime as _dt
import json


def _short(project: str) -> str:
    """Last path segment for cwd-style keys; the tail after the user prefix for Claude slugs."""
    import os, re
    if project.startswith("/"):
        return os.path.basename(project.rstrip("/")) or project
    return re.sub(r"^-Users-[^-]+-", "", project)


def _fmt(n):
    return f"{n/1e6:.1f}M" if n >= 1e6 else f"{n/1e3:.0f}k"


def markdown(m: dict, findings: list[dict], *, title="Teyla adoption report", include_samples=False, top_projects=15) -> str:
    L = [f"# {title}", "", f"Generated {_dt.date.today().isoformat()} · window: {m['days'] or 'all'} days · "
         f"{m['n_sessions']} sessions · harnesses: {', '.join(f'{k} ({v})' for k, v in m['by_harness'].items()) or 'none found'}", ""]
    t = m["tokens"]
    L += ["## Headline", "", "| metric | value |", "|---|---|",
          f"| output tokens | {_fmt(t.get('output_tokens',0))} |",
          f"| cache read / cache write / fresh input | {_fmt(t.get('cache_read_input_tokens',0))} / {_fmt(t.get('cache_creation_input_tokens',0))} / {_fmt(t.get('input_tokens',0))} |",
          f"| API-equivalent cost (list prices; on a subscription this is what you would have paid) | ${m['cost_estimate_usd']:,.0f}{' · unknown: ' + ', '.join(m['cost_models_unknown']) if m['cost_models_unknown'] else ''} |",
          f"| output on orchestrate-tier models | {int(m['orchestrator_share']*100)}% |",
          f"| subagent calls / inherited top model | {sum(m['subagents'].values())} / {int((m['subagent_inherit_rate'] or 0)*100)}% |",
          f"| human turns / correction-shaped | {m['user_turns']} / {m['corrections']} ({(m['correction_rate'] or 0)*100:.1f}%) |",
          f"| cache-read tokens per output token | {m['cache_read_ratio']}x |",
          f"| giant sessions (>8 MB, >12 active h, or ≥3 compactions) | {len(m['giant_sessions'])} |", ""]
    L += ["## Advice", ""]
    if not findings:
        L.append("Nothing to flag in this window.")
    for f in findings:
        L += [f"- **[{f['severity']}] {f['id']} {f['title']}** — {f['evidence']}", f"  → {f['action']}"]
    L += ["", "## By model", "", "| model | output | cache read | cache write | input |", "|---|---|---|---|---|"]
    for model, u in sorted(m["by_model"].items(), key=lambda kv: -kv[1].get("output_tokens", 0)):
        L.append(f"| {model} | {_fmt(u.get('output_tokens',0))} | {_fmt(u.get('cache_read_input_tokens',0))} | {_fmt(u.get('cache_creation_input_tokens',0))} | {_fmt(u.get('input_tokens',0))} |")
    L += ["", "## By project", "", "| project | output | cache read | models |", "|---|---|---|---|"]
    rows = []
    for p, mm in m["by_project"].items():
        o = sum(u.get("output_tokens", 0) for u in mm.values()); c = sum(u.get("cache_read_input_tokens", 0) for u in mm.values())
        rows.append((o, c, p, ", ".join(sorted(mm))))
    for o, c, p, models in sorted(rows, reverse=True)[:top_projects]:
        L.append(f"| {_short(p)} | {_fmt(o)} | {_fmt(c)} | {models} |")
    if m["giant_sessions"]:
        L += ["", "## Giant sessions", "",
              "| project | session | day | MB | span h | active h | compactions | human turns |",
              "|---|---|---|---|---|---|---|---|"]
        for g in m["giant_sessions"][:15]:
            L.append(f"| {_short(g['project'])} | {g['sid']} | {g['day']} | {g['mb']} | {g['hours']} | "
                      f"{g.get('active_hours', g['hours'])} | {g['compactions']} | {g['turns']} |")
    if m.get("skills"):
        L += ["", "## Skills invoked", "", ", ".join(f"{k} ({v})" for k, v in sorted(m["skills"].items(), key=lambda kv: -kv[1]))]
    if include_samples and m.get("correction_samples"):
        L += ["", "## Correction-shaped turns (samples)", ""] + [f"- {s.replace(chr(10),' ')[:160]}" for s in m["correction_samples"][:30]]
    L += ["", "---", "_Teyla · aggregates computed locally from harness session logs; nothing was sent anywhere._"
          + (" _Redacted: projects are pseudonyms, no session ids, no correction text._" if m.get("redacted") else
             " _Not redacted: project names and session ids are shown; use --share for a shareable version._")]
    return "\n".join(L) + "\n"


def to_json(m: dict, findings: list[dict]) -> str:
    slim = {k: v for k, v in m.items() if k not in ("correction_samples",)}
    return json.dumps(dict(metrics=slim, findings=findings, schema="teyla.report.v1"), indent=1, ensure_ascii=False)

"""Harvest: the machine half of turning repeated manual work into a routine.

Given a path, find the sessions that touched it, print each session's tool spine (the ordered tool calls)
and every correction-shaped human turn. A model (the harvest skill in plugin/skills/harvest) then does the
judgement half: what was done the same way every time → skill; what varied or was corrected → candidate rules.
Refuses below two sessions: with one run you cannot tell a procedure from an accident.
"""
from __future__ import annotations

import json
import os

from .adapters import claude_code


def harvest(path: str, project: str | None = None, min_sessions: int = 2) -> str:
    root = claude_code.DEFAULT_ROOT
    dirs = [os.path.join(root, project)] if project else [os.path.join(root, d) for d in os.listdir(root)]
    hits = []
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if not f.endswith(".jsonl"):
                continue
            fp = os.path.join(d, f)
            with open(fp, errors="replace") as fh:
                if any(path in line for line in fh):
                    hits.append(fp)
    if len(hits) < min_sessions:
        return f"{len(hits)} session(s) touched {path!r}; harvest needs at least {min_sessions}. Do the job by hand once more, then harvest."
    out = [f"# Harvest input for {path}", f"{len(hits)} sessions", ""]
    for fp in sorted(hits):
        s = claude_code.parse(fp)
        if not s:
            continue
        out += [f"## {s.day} {s.sid[:8]} ({s.project}) — {s.n_user} human turns, {sum(s.tools.values())} tool calls", "",
                "tool spine: " + " → ".join(_spine(fp)), ""]
        corr = [t.text[:300].replace("\n", " ") for t in s.user_turns if t.corr]
        if corr:
            out += ["corrections:"] + [f"- {c}" for c in corr] + [""]
    out += ["", "Next: the skill goes only what every session did the same way; everything that varied or was corrected goes to candidate-rules.md."]
    return "\n".join(out)


def _spine(fp: str, limit: int = 60) -> list[str]:
    seq = []
    with open(fp, errors="replace") as fh:
        for line in fh:
            if '"tool_use"' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") != "assistant":
                continue
            for b in o.get("message", {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = b.get("input", {}) or {}
                    detail = inp.get("command") or inp.get("file_path") or inp.get("skill") or inp.get("description") or ""
                    seq.append(f"{b['name']}({str(detail)[:40]})" if detail else b["name"])
    if len(seq) > limit:
        seq = seq[:limit // 2] + ["…"] + seq[-limit // 2:]
    return seq

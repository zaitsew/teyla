"""`teyla products` — the "built, not used" detector.

Every repo that follows the scaffold exposes `./check.sh usage`, printing `key=value` lines with the
product's own real-usage counters (rows logged, messages sent, reviews done, active users…). This command
runs it in every repo under ~/repos (or the paths given) and prints one table, so a sprint kickoff starts
from what is actually used instead of what is built. A repo without a usage probe is listed as "no probe" —
which is itself the first finding.
"""
from __future__ import annotations

import os
import pathlib
import subprocess


def probe(repo: pathlib.Path, timeout: int = 60) -> dict:
    sh = repo / "check.sh"
    if not sh.exists():
        return {"_status": "no check.sh"}
    if "usage)" not in sh.read_text(errors="replace"):
        return {"_status": "no probe"}
    try:
        r = subprocess.run(["bash", str(sh), "usage"], cwd=repo, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"_status": "timeout"}
    if r.returncode == 64:  # convention: 64 = "usage" mode not implemented
        return {"_status": "no probe"}
    if r.returncode != 0:
        return {"_status": f"exit {r.returncode}"}
    out = {"_status": "ok"}
    for line in r.stdout.splitlines():
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def table(paths: list[str] | None = None) -> str:
    root = pathlib.Path.home() / "repos"
    repos = [pathlib.Path(p).expanduser() for p in paths] if paths else sorted(p for p in root.iterdir() if (p / ".git").exists())
    lines = [f"{'repo':18} {'status':10} counters", "-" * 70]
    for r in repos:
        d = probe(r)
        st = d.pop("_status")
        counters = ", ".join(f"{k}={v}" for k, v in d.items()) or "-"
        lines.append(f"{r.name:18} {st:10} {counters}")
    lines.append("")
    lines.append("Zero everywhere means the next sprint is 'make one input free', not a feature.")
    return "\n".join(lines)

"""`teyla products` — the "built, not used" detector.

Every repo that follows the scaffold exposes `./check.sh usage`, printing `key=value` lines with the
product's own real-usage counters (rows logged, messages sent, reviews done, active users…). This command
runs it in every repo under config code_root (or the paths given) and prints one table, so a sprint kickoff starts
from what is actually used instead of what is built. A repo without a usage probe is listed as "no probe" —
which is itself the first finding.

`./check.sh usage` is the repo's own code, so running it everywhere is running every repo's
code. `[products] repos = [...]` in ~/.teyla/config.toml narrows the default walk to those
repos (the weekly routine calls this with no paths). In safe mode it is also the only place
anything runs: a repo not on the list — even one named on the command line — is listed as
"not allowed" and its check.sh is never started.
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


def repos_to_probe(paths: list[str] | None = None, cfg: dict | None = None) -> tuple[list[pathlib.Path], set[pathlib.Path]]:
    """(repos to list, the subset whose check.sh may run)."""
    from . import config
    cfg = cfg or config.load()
    allow = config.products_allowlist(cfg)
    safe = config.safe_mode(cfg)
    if paths:
        repos = [pathlib.Path(p).expanduser() for p in paths]
    elif allow:
        repos = [p for p in allow if p.is_dir()]
    else:
        root = config.code_root(cfg)
        repos = sorted(p for p in root.iterdir() if (p / ".git").exists()) if root.is_dir() else []
    if safe or (allow and not paths):
        runnable = {r for r in repos if r.resolve() in allow}
    else:
        runnable = set(repos)
    return repos, runnable


def table(paths: list[str] | None = None, cfg: dict | None = None) -> str:
    repos, runnable = repos_to_probe(paths, cfg)
    lines = [f"{'repo':18} {'status':10} counters", "-" * 70]
    for r in repos:
        d = probe(r) if r in runnable else {"_status": "not allowed"}
        st = d.pop("_status")
        counters = ", ".join(f"{k}={v}" for k, v in d.items()) or "-"
        lines.append(f"{r.name:18} {st:10} {counters}")
    lines.append("")
    if any(r not in runnable for r in repos):
        lines.append("not allowed: safe mode runs ./check.sh usage only in [products] repos — "
                     "teyla config set products.repos=<name>,<name>")
    lines.append("Zero everywhere means the next sprint is 'make one input free', not a feature.")
    return "\n".join(lines)

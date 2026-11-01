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

import json
import os
import pathlib
import re
import subprocess
import time


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


def cache_path() -> pathlib.Path:
    from .control import state as control
    return control.home() / "products-cache.json"


def write_cache(results: dict[str, tuple[str, dict]]) -> None:
    """~/.teyla/products-cache.json (0600): {repo folder: {status, counters}} from the table just printed, for
    the portfolio's `progress.users` (docs/APP.md). A repo whose probe worked replaces its row; one that did not
    (timeout, not allowed) keeps the last good row, so a failed probe never blanks good data. The file never
    leaves the machine."""
    from . import asks
    try:
        old = json.loads(cache_path().read_text())
        repos = dict(old["repos"]) if isinstance(old, dict) and old.get("version") == 1 else {}
    except (OSError, ValueError, KeyError, TypeError):
        repos = {}
    for name, (st, d) in results.items():
        key = name.lower()
        if st == "ok" or not (isinstance(repos.get(key), dict) and repos[key].get("status") == "ok"):
            repos[key] = {"status": st, "counters": d}
    try:
        asks._atomic_write(cache_path(), json.dumps({"version": 1, "at": time.time(), "repos": repos}, indent=1))
    except OSError:
        pass                                  # the table is the product; the cache is an extra


def table(paths: list[str] | None = None, cfg: dict | None = None, *, cache: bool = False) -> str:
    repos, runnable = repos_to_probe(paths, cfg)
    lines = [f"{'repo':18} {'status':10} counters", "-" * 70]
    results: dict[str, dict] = {}
    for r in repos:
        d = probe(r) if r in runnable else {"_status": "not allowed"}
        st = d.pop("_status")
        results[r.name] = (st, dict(d))
        counters = ", ".join(f"{k}={v}" for k, v in d.items()) or "-"
        lines.append(f"{r.name:18} {st:10} {counters}")
    lines.append("")
    if any(r not in runnable for r in repos):
        lines.append("not allowed: safe mode runs ./check.sh usage only in [products] repos — "
                     "teyla config set products.repos=<name>,<name>")
    lines.append("Zero everywhere means the next sprint is 'make one input free', not a feature.")
    if cache:
        write_cache(results)
    return "\n".join(lines)


# --- `teyla probe-sql`: one read-only query for a usage probe -------------------------------
# A probe for a product on Supabase needs its counters from the project's database. Every repo
# writing its own curl + Keychain snippet is six copies of the same token handling, so the probe
# calls this instead:  teyla probe-sql <project-ref> "select count(*) as trips_7d from trips …"
# It uses the Management API's read-only endpoint (the query runs in a read-only transaction),
# with the token `supabase login` already stored, and prints the first row as key=value lines.

SUPABASE_API = "https://api.supabase.com/v1/projects/{ref}/database/query/read-only"
# A project ref is 20 lowercase letters. Anything else could rewrite the path (`<ref>/database/query?`
# would reach the writable endpoint), so it is refused before a request is built.
REF_RE = re.compile(r"[a-z]{20}")


def supabase_token() -> str | None:
    """SUPABASE_ACCESS_TOKEN, else the token the Supabase CLI keeps in the Keychain."""
    tok = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if tok:
        return tok.strip()
    from .providers import keychain
    tok = keychain("Supabase CLI")
    if tok and tok.startswith("go-keyring-base64:"):
        import base64
        try:
            tok = base64.b64decode(tok.split(":", 1)[1]).decode()
        except ValueError:
            return None
    return tok or None


def query_lines(rows: list, prefix: str = "") -> list[str]:
    """The first row as `key=value` lines; no row means zero, which is a finding."""
    if not rows:
        return [f"{prefix}rows=0"]
    out = []
    for k, v in rows[0].items():
        v = "" if v is None else v
        if isinstance(v, float):
            v = f"{v:g}"
        out.append(f"{prefix}{k}={v}")
    return out


def probe_sql(ref: str, sql: str, prefix: str = "", timeout: int = 30) -> tuple[int, list[str]]:
    """(exit code, lines). Never raises: a probe prints what went wrong and `teyla products`
    shows it in the table instead of a stack trace."""
    import json
    import urllib.error
    import urllib.request
    from . import config
    if config.safe_mode():
        return 0, [f"{prefix}probe=safe_mode"]
    if not REF_RE.fullmatch(ref or ""):
        return 2, [f"{prefix}probe=bad_ref"]
    tok = supabase_token()
    if not tok:
        return 0, [f"{prefix}probe=needs_key"]  # supabase login, or SUPABASE_ACCESS_TOKEN
    from .update import ssl_context
    req = urllib.request.Request(SUPABASE_API.format(ref=ref), method="POST",
                                 data=json.dumps({"query": sql}).encode(),
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                          "User-Agent": "teyla-probe"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as r:  # noqa: S310 — fixed host
            rows = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        msg = e.read().decode(errors="replace")[:200].replace("\n", " ")
        return 1, [f"{prefix}probe=http_{e.code}", f"# {msg}"]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        return 1, [f"{prefix}probe=unreachable", f"# {e}"]
    if not isinstance(rows, list):
        return 1, [f"{prefix}probe=bad_answer"]
    return 0, query_lines(rows, prefix)

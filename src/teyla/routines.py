"""`teyla routines` — routines and manual checks.

Some work must run without a human: launchd jobs, cron lines, pg_cron
schedules, GitHub Actions workflows, one-off scripts. Some work only a human
can confirm: does the thing actually behave the way it is supposed to, from
the outside, today? Both halves rot silently — a launchd job can be unloaded
for months before anyone notices, and "I checked that once in July" is not a
check.

A repo declares both in one `teyla.toml` at its root:

    [product]
    name = "my-app"
    usage = "./check.sh usage"

    [[routine]]
    name = "nightly-sync"
    kind = "launchd"
    label = "com.example.sync"
    every = "1d"
    log = "~/Library/Logs/app-sync.log"

    [[check]]
    name = "log an entry from a photo"
    how = "app → New → photo → caption"
    status = "broken"
    confirmed = 2026-09-09

`teyla routines [path...]` walks every git repo under ~/repos by default (or
the paths given), reads each `teyla.toml`, and reports whether the automated
half is actually loaded and running on schedule, and whether the manual half
is confirmed working and recent.

A routine's verdict is `unknown` when nothing on the machine can say whether it
runs at all — a `pg_cron`/`script` routine (no local API to inspect), or a
`github-actions` routine with no `gh` and no log, with no log evidence either.
`unknown` is not a pass: it counts as NOT RUNNING everywhere `NOT LOADED`/`STALE`
do, in the summary line and in the exit code below, because "nothing can tell
you if this runs" is exactly the built-but-unused case this file exists to catch.

Exit codes: `0` clean; `1` if any routine is not running (`NOT LOADED`, `STALE`,
`unknown`) or any check is `BROKEN`; `2` if the only problems are `UNTESTED`/
`RE-TEST` checks — unverified is not the same as broken, and this split lets a CI
gate tell "nobody has tried this" apart from "this is provably failing".
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import shutil
import subprocess
import tomllib

CADENCE = {
    "15m": dt.timedelta(minutes=15),
    "1h": dt.timedelta(hours=1),
    "1d": dt.timedelta(days=1),
    "7d": dt.timedelta(days=7),
}

RECHECK_DAYS = 30


class ManifestError(ValueError):
    pass


def find_manifests(paths: list[str] | None = None) -> list[pathlib.Path]:
    """teyla.toml files: at the given paths, or one level under every git repo in ~/repos."""
    if paths:
        out = []
        for p in paths:
            p = pathlib.Path(p).expanduser()
            if p.is_dir():
                m = p / "teyla.toml"
                if m.exists():
                    out.append(m)
            elif p.name == "teyla.toml" and p.exists():
                out.append(p)
        return out
    root = pathlib.Path.home() / "repos"
    if not root.is_dir():
        return []
    out = []
    for p in sorted(root.iterdir()):
        if (p / ".git").exists() and (p / "teyla.toml").exists():
            out.append(p / "teyla.toml")
    return out


def parse_manifest(path: pathlib.Path) -> dict:
    """Parse a teyla.toml with tomllib. Raises ManifestError on missing required fields."""
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{path}: invalid TOML: {e}") from e

    product = data.get("product") or {}
    if "name" not in product:
        raise ManifestError(f"{path}: [product] is missing required key 'name'")

    routines = data.get("routine") or []
    for r in routines:
        if _is_control_routine(r):
            # A control-plane routine — Teyla runs this one itself rather than reporting
            # on something scheduled elsewhere. Its real validation lives in
            # teyla.control.manifest; here it only needs enough shape to appear as a row,
            # so the two kinds of routine can sit in one file without either being
            # rewritten. See docs/CONTROL-PLANE.md.
            if "name" not in r:
                raise ManifestError(f"{path}: [[routine]] with a `step` is missing required key 'name'")
            r.setdefault("kind", "control")
            r.setdefault("label", f"com.teyla.{product['name']}.{r['name']}")
            r.setdefault("every", "1d")
            continue
        for key in ("name", "kind", "label", "every"):
            if key not in r:
                raise ManifestError(f"{path}: [[routine]] {r.get('name', '?')!r} missing required key {key!r}")
        if r["kind"] not in ("launchd", "cron", "pg_cron", "github-actions", "script", "control"):
            raise ManifestError(f"{path}: routine {r['name']!r} has unknown kind {r['kind']!r}")
        if r["every"] not in CADENCE:
            raise ManifestError(f"{path}: routine {r['name']!r} has unknown cadence {r['every']!r}")

    checks = data.get("check") or []
    for c in checks:
        for key in ("name", "how", "status"):
            if key not in c:
                raise ManifestError(f"{path}: [[check]] {c.get('name', '?')!r} missing required key {key!r}")
        if c["status"] not in ("ok", "broken", "untested"):
            raise ManifestError(f"{path}: check {c['name']!r} has unknown status {c['status']!r}")

    return {"path": path, "repo": path.parent, "product": product, "routines": routines, "checks": checks}


# --- control-plane routines ----------------------------------------------------
#
# `teyla.control` is the half that *runs* a routine. This file only needs two things
# from it: to not choke on its manifest shape, and to show the last receipt outcome
# next to the row. Both are done through narrow, failure-tolerant helpers rather than
# a hard import, so `teyla routines` keeps working if the control plane is absent.

def _is_control_routine(r: dict) -> bool:
    return isinstance(r, dict) and isinstance(r.get("step"), dict)


ON_DEMAND = "on demand"


def last_receipt_outcomes() -> dict:
    """`{"<product>:<routine>": "<outcome of its most recent receipt>"}`, or `{}`.

    Never raises: a report that dies because a receipt log is malformed is worse than
    a report with one column missing."""
    try:
        from .control.state import read_jsonl, receipts_path
        rows = read_jsonl(receipts_path())
    except Exception:  # noqa: BLE001 - a reporting nicety must never be fatal
        return {}
    out = {}
    for r in rows:
        ref = r.get("routine")
        if ref:
            out[ref] = r.get("outcome") or "?"
    return out


# --- routine loading detection ------------------------------------------------

def _launchctl_list() -> str:
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _crontab_l() -> str:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def loaded_state(routine: dict, *, launchctl_output: str | None = None, crontab_output: str | None = None) -> str:
    """'loaded' status string for a routine row: pid/exit summary, 'not loaded', 'unknown'."""
    kind = routine["kind"]
    label = routine.get("label", "")

    if kind == "control":
        # A control-plane routine is "loaded" only if it has a clock trigger installed as
        # a launchd agent. Anything else runs when something asks it to, which is not a
        # state that can rot, so it reports `on demand` rather than a false `unknown`.
        if (routine.get("trigger") or {}).get("type") != "clock":
            return ON_DEMAND
        kind = "launchd"

    if kind == "launchd":
        text = _launchctl_list() if launchctl_output is None else launchctl_output
        for line in text.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2] == label:
                pid, status = parts[0], parts[1]
                if pid != "-":
                    return f"loaded (pid {pid})"
                return f"loaded (last exit {status})"
        return "not loaded"

    if kind == "cron":
        text = _crontab_l() if crontab_output is None else crontab_output
        for line in text.splitlines():
            if label in line:
                return "in crontab"
        return "not in crontab"

    if kind == "github-actions":
        if shutil.which("gh") is None:
            return "unknown"
        try:
            r = subprocess.run(
                ["gh", "run", "list", "-w", label, "-L", "1", "--json", "status,conclusion,createdAt"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return "unknown"
        if r.returncode != 0 or not r.stdout.strip():
            return "unknown"
        import json as _json
        try:
            runs = _json.loads(r.stdout)
        except ValueError:
            return "unknown"
        if not runs:
            return "no runs yet"
        return f"last run {runs[0].get('conclusion') or runs[0].get('status', '?')}"

    # pg_cron, script: no local API to inspect membership; rely on log mtime alone.
    return "unknown"


def last_run(routine: dict) -> dt.datetime | None:
    """mtime of the routine's log file, if given and present."""
    log = routine.get("log")
    if not log:
        return None
    p = pathlib.Path(log).expanduser()
    if not p.exists():
        return None
    return dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)


def routine_verdict(routine: dict, loaded: str, run_at: dt.datetime | None, *, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    if loaded == ON_DEMAND:
        return "ok"
    if loaded in ("not loaded", "not in crontab"):
        return "NOT LOADED"
    if run_at is not None:
        cadence = CADENCE[routine["every"]]
        if now - run_at > cadence * 2:
            return "STALE"
        return "ok"
    if loaded == "unknown":
        return "unknown"
    return "ok"


# --- check verdicts ------------------------------------------------------------

def check_age_days(check: dict, *, today: dt.date | None = None) -> int | None:
    confirmed = check.get("confirmed")
    if confirmed is None:
        return None
    today = today or dt.datetime.now(dt.timezone.utc).date()
    if isinstance(confirmed, dt.datetime):
        confirmed = confirmed.date()
    return (today - confirmed).days


def check_verdict(check: dict, age_days: int | None) -> str:
    status = check["status"]
    if status == "broken":
        return "BROKEN"
    if status == "untested":
        return "UNTESTED"
    # status == "ok"
    if age_days is not None and age_days > RECHECK_DAYS:
        return "RE-TEST"
    return "ok"


# --- report assembly ------------------------------------------------------------

def evaluate(manifest: dict, *, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    lc = _launchctl_list()
    ct = _crontab_l()
    outcomes = last_receipt_outcomes()
    product_name = manifest["product"].get("name", manifest["repo"].name)

    routine_rows = []
    for r in manifest["routines"]:
        loaded = loaded_state(r, launchctl_output=lc, crontab_output=ct)
        run_at = last_run(r)
        verdict = routine_verdict(r, loaded, run_at, now=now)
        routine_rows.append({
            "name": r["name"], "kind": r["kind"], "loaded": loaded,
            "last_run": run_at.isoformat() if run_at else "?", "verdict": verdict,
            "last_receipt": outcomes.get(f"{product_name}:{r['name']}", "-"),
        })

    check_rows = []
    for c in manifest["checks"]:
        age = check_age_days(c, today=now.date())
        verdict = check_verdict(c, age)
        check_rows.append({
            "name": c["name"], "status": c["status"],
            "confirmed": str(c.get("confirmed") or "-"),
            "age_days": age if age is not None else "-",
            "verdict": verdict,
        })

    return {"product": manifest["product"].get("name", manifest["repo"].name),
            "repo": str(manifest["repo"]), "routines": routine_rows, "checks": check_rows}


def evaluate_all(paths: list[str] | None = None) -> list[dict]:
    out = []
    for m in find_manifests(paths):
        try:
            manifest = parse_manifest(m)
        except ManifestError as e:
            out.append({"product": m.parent.name, "repo": str(m.parent), "error": str(e), "routines": [], "checks": []})
            continue
        out.append(evaluate(manifest))
    return out


NOT_RUNNING_VERDICTS = {"NOT LOADED", "STALE", "unknown"}
BROKEN_CHECK_VERDICTS = {"BROKEN"}
NEEDS_ATTENTION_CHECK_VERDICTS = {"UNTESTED", "RE-TEST"}


def summarize(reports: list[dict]) -> tuple[int, int, int]:
    """(routines not running, checks broken, checks untested/re-test). A routine verdict of
    `unknown` counts as not running, same as `NOT LOADED`/`STALE` — see NOT_RUNNING_VERDICTS."""
    n = sum(1 for r in reports for row in r["routines"] if row["verdict"] in NOT_RUNNING_VERDICTS)
    m = sum(1 for r in reports for row in r["checks"] if row["verdict"] in BROKEN_CHECK_VERDICTS)
    k = sum(1 for r in reports for row in r["checks"] if row["verdict"] in NEEDS_ATTENTION_CHECK_VERDICTS)
    return n, m, k


def exit_code(n: int, m: int, k: int) -> int:
    """`summarize()`'s (routines not running, checks broken, checks needing attention) -> the
    process exit code documented in the module docstring: 1 if anything is actually not running
    or broken, 2 if the only problems are untested/re-test checks, 0 if everything is clean."""
    if n or m:
        return 1
    if k:
        return 2
    return 0


NAME_TRUNC = 40


def _trunc(s: str, n: int = NAME_TRUNC) -> str:
    """Truncate at `n` chars with an ellipsis — the one column (name) with no fixed upper bound
    in practice, so it is the one that can blow up alignment for every column after it."""
    s = str(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Render a left-aligned table whose column widths come from the actual content (header
    included), not a fixed guess — so a value longer than a hardcoded width can never misalign
    the columns that follow it."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    def _line(cells):
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells)).rstrip()
    return [_line(headers)] + [_line(row) for row in rows]


def render_text(reports: list[dict]) -> str:
    lines = []
    for r in reports:
        lines.append(f"## {r['product']}  ({r['repo']})")
        if r.get("error"):
            lines.append(f"  ERROR: {r['error']}")
            lines.append("")
            continue
        if r["routines"]:
            # The receipt column only appears when some routine here has one. A column of
            # dashes on a repo with no control-plane routines is noise in every report.
            show_receipt = any(row.get("last_receipt", "-") != "-" for row in r["routines"])
            headers = ["name", "kind", "loaded", "last run", "verdict"]
            rows = [[_trunc(row["name"]), row["kind"], row["loaded"], row["last_run"], row["verdict"]]
                    for row in r["routines"]]
            if show_receipt:
                headers.append("last receipt")
                for row, src in zip(rows, r["routines"]):
                    row.append(str(src.get("last_receipt", "-")))
            lines.extend(_table(headers, rows))
        else:
            lines.append("  (no routines declared)")
        if r["checks"]:
            lines.append("")
            rows = [[_trunc(row["name"]), row["status"], row["confirmed"], str(row["age_days"]), row["verdict"]]
                    for row in r["checks"]]
            lines.extend(_table(["name", "status", "confirmed", "age(d)", "verdict"], rows))
        else:
            lines.append("  (no checks declared)")
        lines.append("")
    n, m, k = summarize(reports)
    lines.append(f"{n} routines not running, {m} checks broken, {k} untested/re-test")
    return "\n".join(lines)


def render_json(reports: list[dict]) -> dict:
    n, m, k = summarize(reports)
    return {"products": reports, "summary": {"routines_not_running": n, "checks_broken": m, "checks_needs_attention": k}}


# --- `teyla routines --issues` --------------------------------------------------
#
# Dry by default: `evaluate_all` + `render_text`/`render_json` above only ever read. This
# section is the write path, run only when `--issues` is passed: for every BROKEN check in
# a repo that GitHub recognises, make sure exactly one open-or-closed issue with a fixed
# title exists, so re-running never duplicates it.

def _is_github_repo(repo_path) -> bool:
    if shutil.which("gh") is None:
        return False
    try:
        r = subprocess.run(["gh", "repo", "view"], cwd=str(repo_path), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def _check_detail_by_name(repo_path) -> dict:
    """name -> {'how', 'note'} straight from this repo's teyla.toml. evaluate()'s check rows
    carry only name/status/confirmed/age_days/verdict, so the issue body is built from a
    fresh (best-effort) re-parse rather than by widening that shape."""
    p = pathlib.Path(repo_path) / "teyla.toml"
    if not p.exists():
        return {}
    try:
        manifest = parse_manifest(p)
    except ManifestError:
        return {}
    return {c["name"]: {"how": c.get("how", ""), "note": c.get("note", "")} for c in manifest["checks"]}


def _issue_exists(repo_path, title: str) -> bool:
    try:
        r = subprocess.run(
            ["gh", "issue", "list", "--search", f'"{title}" in:title', "--state", "all", "--json", "title"],
            cwd=str(repo_path), capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0 or not r.stdout.strip():
        return False
    import json as _json
    try:
        issues = _json.loads(r.stdout)
    except ValueError:
        return False
    return any(i.get("title") == title for i in issues)


def _create_issue(repo_path, title: str, body: str) -> bool:
    try:
        r = subprocess.run(
            ["gh", "issue", "create", "--title", title, "--body", body],
            cwd=str(repo_path), capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def issue_title(check_name: str) -> str:
    return f"[teyla] broken check: {check_name}"


def open_issues(results: list[dict]) -> list[str]:
    """The `--issues` handler: `results` is `evaluate_all()`'s output. For every check whose
    verdict is BROKEN in a repo `gh repo view` recognises, ensure one issue titled
    `[teyla] broken check: <name>` exists — search first, create only if missing, never
    duplicate. Repos that are not GitHub repos, and checks that are not BROKEN, are skipped
    without calling `gh`. Returns one line per action taken, for the caller to print."""
    lines = []
    for r in results:
        if r.get("error"):
            continue
        broken = [c for c in r.get("checks", []) if c.get("verdict") == "BROKEN"]
        if not broken:
            continue
        repo_path = r["repo"]
        if not _is_github_repo(repo_path):
            lines.append(f"{r['product']}: not a GitHub repo (or `gh` unavailable) — skipping {len(broken)} broken check(s)")
            continue
        detail = _check_detail_by_name(repo_path)
        for c in broken:
            title = issue_title(c["name"])
            if _issue_exists(repo_path, title):
                lines.append(f"{r['product']}: issue already exists for {c['name']!r} — skipped")
                continue
            d = detail.get(c["name"], {})
            body_lines = []
            if d.get("how"):
                body_lines.append(f"how: {d['how']}")
            if d.get("note"):
                body_lines.append(f"note: {d['note']}")
            body = "\n".join(body_lines) or "(no `how`/`note` in teyla.toml)"
            if _create_issue(repo_path, title, body):
                lines.append(f"{r['product']}: created issue for {c['name']!r}")
            else:
                lines.append(f"{r['product']}: FAILED to create issue for {c['name']!r}")
    return lines

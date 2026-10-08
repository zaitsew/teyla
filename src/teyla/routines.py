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

`teyla routines [path...]` walks every git repo under code_root by default (or
the paths given), reads each `teyla.toml`, and reports whether the automated
half is actually loaded and running on schedule, and whether the manual half
is confirmed working and recent.

A routine's verdict is `unknown` when nothing on the machine can say whether it
runs at all — a `pg_cron`/`script` routine (no local API to inspect), or a
`github-actions` routine with no `gh` and no log, with no log evidence either.
`unknown` is not a pass: it counts as NOT RUNNING everywhere `NOT LOADED`/`STALE`
do, in the summary line and in the exit code below, because "nothing can tell
you if this runs" is exactly the built-but-unused case this file exists to catch.

A routine whose `log` is JSONL (a `.jsonl` file, or a last line that is a JSON object
with a boolean `ok`) is judged by what its last real run did, not just by when the log was
touched: a routine that runs and fails touches its log every time, so mtime alone calls it
healthy. When the last non-`dry_run` row has `ok: false` the verdict is `FAILING`, with the
streak's start, its length and the first line of `error` in the row's detail. Any other log
keeps the mtime behaviour, and a malformed log never raises.

Exit codes: `0` clean; `1` if any routine is not running (`NOT LOADED`, `STALE`,
`unknown`, `FAILING`) or any check is `BROKEN`; `2` if the only problems are `UNTESTED`/
`RE-TEST` checks — unverified is not the same as broken, and this split lets a CI
gate tell "nobody has tried this" apart from "this is provably failing".
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
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
_CADENCE_RE = re.compile(r"^(\d+)([mhd])$")


def cadence(every: str) -> dt.timedelta | None:
    """`every` as a timedelta: the four named buckets or any `<n>m|h|d` (a StartInterval of
    300 s is `5m`, not "the nearest bucket"). None for `unscheduled` or anything else."""
    if every in CADENCE:
        return CADENCE[every]
    m = _CADENCE_RE.match(str(every))
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return dt.timedelta(**{{"m": "minutes", "h": "hours", "d": "days"}[unit]: n})

RECHECK_DAYS = 30


class ManifestError(ValueError):
    pass


def find_manifests(paths: list[str] | None = None) -> list[pathlib.Path]:
    """teyla.toml files: at the given paths, or one level under every git repo in config code_root."""
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
    from . import config
    root = config.code_root()  # ~/repos by default; a work laptop keeps code elsewhere
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
        if r.get("kind") == "script":
            # A script routine is often "a container with restart: unless-stopped" or "a health
            # URL" — it has a `how`, no scheduler label and no cadence. Teyla still shows the row
            # (verdict `unknown` unless a `log` is given) instead of refusing the whole product.
            r.setdefault("label", r.get("name", "?"))
            r.setdefault("every", "unscheduled")
        for key in ("name", "kind", "label", "every"):
            if key not in r:
                raise ManifestError(f"{path}: [[routine]] {r.get('name', '?')!r} missing required key {key!r}")
        if r["kind"] not in ("launchd", "cron", "pg_cron", "github-actions", "script", "control"):
            raise ManifestError(f"{path}: routine {r['name']!r} has unknown kind {r['kind']!r}")
        if cadence(r["every"]) is None and r["every"] != "unscheduled":
            raise ManifestError(f"{path}: routine {r['name']!r} has unknown cadence {r['every']!r} — 15m, 1h, 1d, 7d, or any <n>m|h|d")

    checks = data.get("check") or []
    for c in checks:
        for key in ("name", "how", "status"):
            if key not in c:
                raise ManifestError(f"{path}: [[check]] {c.get('name', '?')!r} missing required key {key!r}")
        if c["status"] not in ("ok", "broken", "untested"):
            shown = str(c["status"])
            shown = shown[:40] + "…" if len(shown) > 40 else shown
            raise ManifestError(f"{path}: check {c['name']!r} has unknown status {shown!r} — status is exactly one of "
                                f"ok, broken, untested; put what was seen in `note = \"...\"` and the date in `confirmed`")

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
        from . import net
        if shutil.which("gh") is None or not net.allowed():
            # Safe mode: `gh run list` is a call to GitHub, and this runs unattended weekly.
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


LOG_TAIL_BYTES = 256 * 1024
ERROR_TRUNC = 120


def _parse_ts(v) -> dt.datetime | None:
    if not isinstance(v, str):
        return None
    try:
        t = dt.datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def _log_tail_rows(p: pathlib.Path) -> tuple[list[dict], bool]:
    """(JSON-object rows from the last LOG_TAIL_BYTES of p, whether the window starts mid-file).
    Lines that do not parse are skipped. Reads only the tail, never the whole file."""
    size = p.stat().st_size
    with p.open("rb") as f:
        truncated = size > LOG_TAIL_BYTES
        if truncated:
            f.seek(size - LOG_TAIL_BYTES)
        data = f.read()
    lines = data.decode("utf-8", errors="replace").splitlines()
    if truncated and lines:
        lines = lines[1:]  # the first line of a mid-file window is cut
    rows = []
    for line in lines:
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows, truncated


def log_outcome(routine: dict) -> dict | None:
    """What the routine's last real run did, read from its JSONL log, or None when the log is
    not that kind of log (missing, plain text, no usable rows) — callers then use the mtime.

    `{"ok": bool, "finished_at": datetime | None, "streak": int, "since": datetime | None,
    "streak_open": bool, "error": str}`. Rows with `dry_run` true are ignored; a row counts only
    if its `ok` is a boolean. `streak` is the number of consecutive failures ending at the last
    row, `streak_open` that the tail window ended before the streak did. Never raises."""
    try:
        log = routine.get("log")
        if not log:
            return None
        p = pathlib.Path(log).expanduser()
        if not p.is_file():
            return None
        rows, truncated = _log_tail_rows(p)
        if not p.name.endswith(".jsonl"):
            # A plain-text log keeps the mtime behaviour unless its last non-empty line is a result row.
            last = ""
            with p.open("rb") as f:
                f.seek(max(0, p.stat().st_size - 65536))
                for ln in f.read().decode("utf-8", errors="replace").splitlines():
                    if ln.strip():
                        last = ln.strip()
            try:
                obj = json.loads(last)
            except ValueError:
                return None
            if not isinstance(obj, dict) or not isinstance(obj.get("ok"), bool):
                return None
        runs = [r for r in rows if isinstance(r.get("ok"), bool) and not r.get("dry_run")]
        if not runs:
            return None
        last_row = runs[-1]
        out = {"ok": last_row["ok"], "finished_at": _parse_ts(last_row.get("finished_at")),
               "streak": 0, "since": None, "streak_open": False, "error": ""}
        if not last_row["ok"]:
            i = len(runs)
            while i > 0 and not runs[i - 1]["ok"]:
                i -= 1
            streak = runs[i:]
            out["streak"] = len(streak)
            out["since"] = _parse_ts(streak[0].get("finished_at")) or _parse_ts(streak[0].get("started_at"))
            out["streak_open"] = i == 0 and truncated
            err = last_row.get("error")
            first = str(err).strip().splitlines()[0] if err is not None and str(err).strip() else "no error recorded"
            out["error"] = first if len(first) <= ERROR_TRUNC else first[:ERROR_TRUNC - 1] + "…"
        return out
    except Exception:  # noqa: BLE001 - a reporting nicety must never be fatal
        return None


def failing_detail(outcome: dict) -> str:
    since = outcome.get("since")
    n = outcome["streak"]
    when = f" since {since:%Y-%m-%d %H:%M}Z" if since else ""
    count = f"{n}{'+' if outcome.get('streak_open') else ''} consecutive failure{'s' if n != 1 else ''}"
    return f"{count}{when}: {outcome['error']}"


def routine_verdict(routine: dict, loaded: str, run_at: dt.datetime | None, *, now: dt.datetime | None = None,
                    outcome: dict | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    if loaded == ON_DEMAND:
        return "ok"
    if loaded in ("not loaded", "not in crontab"):
        return "NOT LOADED"
    if run_at is not None:
        period = cadence(routine["every"])
        if period is not None and now - run_at > period * 2:
            return "STALE"
        if outcome is not None and not outcome["ok"]:
            return "FAILING"
        return "ok"
    if outcome is not None and not outcome["ok"]:
        return "FAILING"
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
        outcome = log_outcome(r)
        run_at = (outcome or {}).get("finished_at") or last_run(r)
        verdict = routine_verdict(r, loaded, run_at, now=now, outcome=outcome)
        row = {
            "name": r["name"], "kind": r["kind"], "loaded": loaded,
            "last_run": run_at.isoformat() if run_at else "?", "verdict": verdict,
            "last_receipt": outcomes.get(f"{product_name}:{r['name']}", "-"),
        }
        if verdict == "FAILING":
            row["detail"] = failing_detail(outcome)
        routine_rows.append(row)

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


# One line per product, kept where the plugin's session-start hook can read it without
# running anything: ~/.teyla/routines/<product>.line. "Did it run?" then arrives in the
# model's context before the human asks — the measured alternative was four sessions in
# one repo that answered that question by reading code and git log.
LINES_DIR = pathlib.Path(os.path.expanduser("~/.teyla/routines"))


# A BROKEN or UNTESTED check left alone this long gets its one-command confirmation named in
# the product line. Measured 2026-09-29: 26 of 30 checks untested, 2 broken for 19 days, while
# the line said "N untested" every session — a count names no next step.
STALE_CHECK_DAYS = 14


def stale_checks(report: dict) -> list[dict]:
    """BROKEN, then UNTESTED, check rows confirmed more than STALE_CHECK_DAYS ago — or never
    (no `confirmed` date: nobody can say it was ever looked at)."""
    def old(c):
        age = c.get("age_days")
        return not isinstance(age, int) or age > STALE_CHECK_DAYS
    rows = report.get("checks") or []
    return ([c for c in rows if c.get("verdict") == "BROKEN" and old(c)]
            + [c for c in rows if c.get("verdict") == "UNTESTED" and old(c)])


def _sh(s: str) -> str:
    """Shell-quote for a line a human copies: double quotes read better than shlex's
    'today'"'"'s' and are exact whenever the text holds none of " $ ` \\ !."""
    import shlex
    s = str(s)
    if re.fullmatch(r"[A-Za-z0-9._/:@+-]+", s):
        return s
    return f'"{s}"' if not re.search(r'["$`\\!]', s) else shlex.quote(s)


def confirm_command(product: str, check_name: str, status: str = "ok") -> str:
    """One pasteable command. Never `ok|broken` in one line: pasted, that is a pipeline — Teyla
    records ok and the shell then tries to run `broken` (caught in review, P2)."""
    return f"teyla check {_sh(product)} {_sh(check_name)} {status}"


def confirm_step(product: str, check_name: str) -> str:
    """The digest step for a check: two separate commands, one per outcome."""
    return (f"try it, then `{confirm_command(product, check_name, 'ok')}` or, if it failed, "
            f"`{confirm_command(product, check_name, 'broken')}`")


def summary_line(report: dict, *, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now().astimezone()
    stamp = f"as of {now:%Y-%m-%d %H:%M}"
    if report.get("error"):
        return f"{report['product']}: teyla.toml has an error ({stamp}) — `teyla routines .` shows it"
    rs = report["routines"]; cs = report["checks"]
    parts = []
    if rs:
        bad = [r["name"] for r in rs if r["verdict"] in NOT_RUNNING_VERDICTS]
        parts.append(f"{len(rs) - len(bad)}/{len(rs)} routines running" + (f" (not: {', '.join(bad)})" if bad else ""))
    else:
        parts.append("no routines declared")
    if cs:
        broken = [c["name"] for c in cs if c["verdict"] in BROKEN_CHECK_VERDICTS]
        pending = sum(1 for c in cs if c["verdict"] in NEEDS_ATTENTION_CHECK_VERDICTS)
        parts.append(f"{len(cs)} checks" + (f", broken: {', '.join(broken)}" if broken else "") + (f", {pending} untested/re-test" if pending else ""))
    confirm = ""
    stale = stale_checks(report)
    if stale:
        c = stale[0]
        more = f" (+{len(stale) - 1} more)" if len(stale) > 1 else ""
        confirm = (f" — {c['verdict'].lower()} >{STALE_CHECK_DAYS}d: {_trunc(c['name'])}{more}; after trying it: "
                   f"`{confirm_command(report['product'], c['name'], 'ok')}` or, if it failed, "
                   f"`{confirm_command(report['product'], c['name'], 'broken')}`")
    return f"{report['product']}: {' · '.join(parts)} ({stamp}){confirm} — `teyla routines .` for the table"


def problem_items(report: dict) -> list[tuple[str, str]]:
    """(key, text) for the session-start banner: routines not running (NOT_RUNNING_VERDICTS) and broken checks. The key
    is what "seen" is tracked by, so a routine that goes from STALE to NOT LOADED is news again."""
    if report.get("error"):
        return [(f"toml|{report['product']}", f"{report['product']} teyla.toml has an error")]
    out = []
    for r in report.get("routines") or []:
        if r.get("verdict") in NOT_RUNNING_VERDICTS:  # `unknown` included: nothing can say it runs
            out.append((f"routine|{report['product']}|{r['name']}|{r['verdict']}",
                        f"{report['product']} routine {r['name']} {r['verdict']}"
                        + (f" ({r['detail']})" if r.get("detail") else "")))
    for c in report.get("checks") or []:
        if c.get("verdict") == "BROKEN":
            out.append((f"check|{report['product']}|{c['name']}|BROKEN", f"{report['product']} check {_trunc(c['name'])} BROKEN"))
    return out


def write_lines(reports: list[dict], lines_dir: pathlib.Path | None = None) -> list[pathlib.Path]:
    """<product>.line (the product line) and <product>.problems (banner items, key<TAB>text) per report."""
    lines_dir = lines_dir or LINES_DIR
    written = []
    try:
        lines_dir.mkdir(parents=True, exist_ok=True)
        for r in reports:
            name = re.sub(r"[^A-Za-z0-9._-]", "_", str(r["product"]))
            f = lines_dir / f"{name}.line"
            f.write_text(summary_line(r) + "\n")
            written.append(f)
            items = problem_items(r)
            prob = lines_dir / f"{name}.problems"
            if items:
                prob.write_text("".join(f"{_clean(k)}\t{_clean(t)}\n" for k, t in items))
            elif prob.exists():
                prob.unlink()
    except OSError:
        pass  # a read-only home must not break the report
    return written


def _clean(s: str) -> str:
    return re.sub(r"[\t\r\n]+", " ", str(s))


NOT_RUNNING_VERDICTS = {"NOT LOADED", "STALE", "unknown", "FAILING"}
BROKEN_CHECK_VERDICTS = {"BROKEN"}
NEEDS_ATTENTION_CHECK_VERDICTS = {"UNTESTED", "RE-TEST"}


def summarize(reports: list[dict]) -> tuple[int, int, int]:
    """(routines not running, checks broken, checks untested/re-test). A routine verdict of
    `unknown` and `FAILING` count as not running, same as `NOT LOADED`/`STALE` — see NOT_RUNNING_VERDICTS."""
    n = sum(1 for r in reports for row in r["routines"] if row["verdict"] in NOT_RUNNING_VERDICTS)
    m = sum(1 for r in reports for row in r["checks"] if row["verdict"] in BROKEN_CHECK_VERDICTS)
    k = sum(1 for r in reports for row in r["checks"] if row["verdict"] in NEEDS_ATTENTION_CHECK_VERDICTS)
    return n, m, k


def count_failing(reports: list[dict]) -> int:
    return sum(1 for r in reports for row in r.get("routines") or [] if row.get("verdict") == "FAILING")


def counts_line(reports: list[dict]) -> str:
    """"N routines not running, M checks broken, K untested/re-test"; a FAILING routine is counted
    on its own ("1 routine failing"), not under "not running"."""
    n, m, k = summarize(reports)
    f = count_failing(reports)
    failing = f", {f} routine{'s' if f != 1 else ''} failing" if f else ""
    return f"{n - f} routines not running{failing}, {m} checks broken, {k} untested/re-test"


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
            for row in r["routines"]:
                if row.get("detail"):
                    lines.append(f"  {_trunc(row['name'])}: {row['detail']}")
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
    lines.append(counts_line(reports))
    return "\n".join(lines)


def render_json(reports: list[dict]) -> dict:
    n, m, k = summarize(reports)
    return {"products": reports, "summary": {"routines_not_running": n, "routines_failing": count_failing(reports),
                                             "checks_broken": m, "checks_needs_attention": k}}


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


# --- `teyla check <product> <check> ok|broken` --------------------------------------------
#
# Confirming a check used to mean opening teyla.toml, finding the block, editing two lines by
# hand. 26 of 30 checks were never confirmed. This is the one command: it rewrites only the
# `status`, `confirmed` (and, with --note, `note`) lines of that one [[check]] block — every
# other byte of the file, comments included, stays as it was.

_TABLE_RE = re.compile(r"^\s*\[\[?\s*([A-Za-z0-9_.-]+)\s*\]\]?\s*(?:#.*)?$")
_KV_RE = re.compile(r"""^(\s*)([A-Za-z0-9_-]+)(\s*=\s*)("(?:[^"\\]|\\.)*"|'[^']*'|[^\s#]+)(.*)$""")


def find_product(product: str, *, cwd: pathlib.Path | None = None) -> pathlib.Path | None:
    """The teyla.toml of a product: a path to a repo or a teyla.toml, else the manifest whose
    [product] name (or repo directory name) is `product` — the current directory first, then
    every repo under code_root."""
    p = pathlib.Path(product).expanduser()
    if p.name == "teyla.toml" and p.is_file():
        return p
    if p.is_dir() and (p / "teyla.toml").is_file():
        return p / "teyla.toml"
    from . import config
    cands = [(cwd or pathlib.Path.cwd()) / "teyla.toml"]
    root = config.code_root()
    if root.is_dir():
        cands += [d / "teyla.toml" for d in sorted(root.iterdir()) if (d / "teyla.toml").is_file()]
    for m in cands:
        if not m.is_file():
            continue
        try:
            name = (tomllib.loads(m.read_text()).get("product") or {}).get("name")
        except (tomllib.TOMLDecodeError, OSError):
            name = None
        if product in (name, m.parent.name):
            return m
    return None


def _toml_str(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _inside_value(lines: list[str]) -> list[bool]:
    """inside[i]: does line i begin in the middle of a TOML value — a multiline string or a
    multiline array? Such a line is text, never a table header or a `key = value` field (caught in
    review, P1: a `how` that quoted `status = "..."` on its own line was eaten as the field).
    One extra entry at the end: whether the file stops inside a value."""
    inside, st, depth = [], None, 0
    for line in lines:
        inside.append(st is not None or depth > 0)
        i, n = 0, len(line)
        while i < n:
            c = line[i]
            if st is not None:
                q = st[0]
                if q == '"' and c == "\\":
                    i += 2
                elif line.startswith(st, i):
                    while i < n and line[i] == q:  # a run of quotes: the last three close
                        i += 1
                    st = None
                else:
                    i += 1
            elif c == "#":
                break
            elif line.startswith('"""', i) or line.startswith("'''", i):
                st = line[i:i + 3]
                i += 3
            elif c == '"':
                i += 1
                while i < n and line[i] != '"':
                    i += 2 if line[i] == "\\" else 1
                i += 1
            elif c == "'":
                j = line.find("'", i + 1)
                i = n if j < 0 else j + 1
            else:
                depth += (c == "[") - (c == "]")
                i += 1
    inside.append(st is not None or depth > 0)
    return inside


def set_check(path: pathlib.Path, check_name: str, status: str, *, note: str | None = None,
              today: dt.date | None = None) -> str:
    """Set one [[check]]'s status and confirmed date (and note) in place. Returns a one-line
    result; raises ManifestError when the check is not there, when the edit cannot be made
    safely, or when the result is not exactly the original plus the intended fields — and then
    the file is left as it was."""
    if status not in ("ok", "broken", "untested"):
        raise ManifestError(f"status is ok, broken or untested — not {status!r}")
    today = today or dt.date.today()
    text = path.read_text()
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{path}: does not parse ({e}); file left unchanged") from e
    lines = text.splitlines(keepends=True)
    inside = _inside_value(lines)

    def header(k):
        return not inside[k] and _TABLE_RE.match(lines[k].rstrip("\n"))

    def field(k):
        return None if inside[k] else _KV_RE.match(lines[k].rstrip("\n"))

    # Find the block: a [[check]] header, then the lines up to the next table header.
    start = end = None
    i = 0
    while i < len(lines):
        m = header(i)
        if m and lines[i].lstrip().startswith("[[") and m.group(1) == "check":
            j = i + 1
            while j < len(lines) and not header(j):
                j += 1
            for k in range(i + 1, j):
                kv = field(k)
                if kv and kv.group(2) == "name":
                    try:
                        val = tomllib.loads(f"v = {kv.group(4)}")["v"]
                    except tomllib.TOMLDecodeError:
                        val = None
                    if val == check_name:
                        start, end = i, j
            if start is not None:
                break
            i = j
            continue
        i += 1
    if start is None:
        names = [c.get("name") for c in (before.get("check") or [])]
        raise ManifestError(f"{path}: no [[check]] named {check_name!r}; there are: {', '.join(map(repr, names)) or 'none'}")
    want = {"status": _toml_str(status), "confirmed": today.isoformat()}
    if note is not None:
        want["note"] = _toml_str(note)
    seen_keys, last_kv = set(), start
    for k in range(start + 1, end):
        raw = lines[k]
        nl = "\n" if raw.endswith("\n") else ""
        kv = field(k)
        if not kv:
            continue
        last_kv = k
        key = kv.group(2)
        if key in want:
            if inside[k + 1]:  # the old value runs on over later lines: replacing line k would leave them behind
                raise ManifestError(f"{path}: `{key}` in that [[check]] is a multiline value; edit it by hand. File left unchanged")
            lines[k] = f"{kv.group(1)}{key}{kv.group(3)}{want[key]}{kv.group(5)}{nl}"
            seen_keys.add(key)
    missing = [k for k in ("status", "confirmed", "note") if k in want and k not in seen_keys]
    if missing:
        # After the block's last line of content — which may end a multiline `how`, not start one.
        tail = max((k for k in range(start, end)
                    if inside[k] or (lines[k].strip() and not lines[k].lstrip().startswith("#"))), default=start)
        if inside[tail + 1]:
            raise ManifestError(f"{path}: cannot find where that [[check]] ends; edit it by hand. File left unchanged")
        kv = field(last_kv) if last_kv > start else None
        indent = kv.group(1) if kv else ""
        if not lines[tail].endswith("\n"):
            lines[tail] += "\n"
        lines[tail + 1:tail + 1] = [f"{indent}{k} = {want[k]}\n" for k in missing]
    new = "".join(lines)
    try:
        parsed = tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:
        raise ManifestError(f"{path}: the edit would not parse ({e}); file left unchanged") from e
    # The edit is right only if the file now says exactly what it said, plus these fields on this
    # one check — nothing lost from a `how`, nothing landing inside a string.
    expect = copy.deepcopy(before)
    row = next(c for c in expect["check"] if c.get("name") == check_name)
    row["status"], row["confirmed"] = status, today
    if note is not None:
        row["note"] = note
    if parsed != expect:
        raise ManifestError(f"{path}: the edit did not come out as intended (the file has multiline text or an "
                            f"unusual layout there); file left unchanged — edit it by hand")
    path.write_text(new)
    was = next((c.get("status") for c in before.get("check") or [] if c.get("name") == check_name), "?")
    return f"{check_name}: {was} -> {status}, confirmed {today.isoformat()} ({path})"


def cmd_check(args) -> int:
    path = find_product(args.product)
    if path is None:
        print(f"no teyla.toml for product {args.product!r} (here or under code_root); pass the repo path instead")
        return 1
    try:
        print(set_check(path, args.check, args.status, note=args.note))
    except ManifestError as e:
        print(str(e))
        return 1
    # Refresh this product's session-start line and banner items now, not at tomorrow's daily.
    try:
        report = evaluate(parse_manifest(path))
        write_lines([report])
        from . import digest
        digest.write_banner_items()
    except Exception:  # noqa: BLE001 — the edit is done; a stale one-liner is not a failure
        pass
    return 0


def register_check(sp):
    q = sp.add_parser("check", help="confirm a manual check: set its status and today's date in the product's teyla.toml")
    q.set_defaults(fn=cmd_check)
    q.add_argument("product", help="the [product] name, the repo directory name, or a path to the repo / teyla.toml")
    q.add_argument("check", help="the [[check]] name, exactly as in teyla.toml")
    q.add_argument("status", choices=["ok", "broken", "untested"])
    q.add_argument("--note", help='what was seen, e.g. --note "photo upload times out on 5G"')
    return q

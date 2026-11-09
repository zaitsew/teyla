"""`teyla platform check` — POLICY §14 as a gate: a second platform needs a written, dated trigger.

The rule "one primary platform per product" used to be a sentence, and a sprint built iPad layouts
nobody asked for. This module turns it into a check that the pre-push hook runs. The repo's
`teyla.toml` says which paths belong to which platform and which platform is primary:

    [productize]
    primary = "ios"
    platforms = ["ios", "macos", "android"]

    [productize.triggers]
    macos = "2026-10-06: the owner asked for a Mac app"

    [productize.paths]                    # platform -> glob patterns (`**`, `*`, `?`)
    ios = ["apps/ios/**"]
    macos = ["apps/macos/**", "App/Mac/**"]
    android = ["android/**"]

    teyla platform check [--repo PATH] [--range A..B | --pre-push [--remote NAME]]
                         [--label security|data-loss|backend-break] [--json]

A changed file maps to every platform whose pattern matches it. A file that matches no pattern is
shared code and never fails the gate. A touched platform other than `primary` passes only with a
trigger `"YYYY-MM-DD: <reason>"` (the validity rules of productize R10). Exit 1 lists, per platform,
the files, what is wrong with the trigger, and the line to add.

§14 allows three same-day exceptions: a security fix, a data-loss fix and a backend change that would
break a shipped client. `--label` (or `TEYLA_PLATFORM_LABEL`) lets a failing push pass. The use is
a row in `~/.teyla/platform-gate.tsv` (`TEYLA_HOME` moves it); when the row cannot be written, the
push is refused, because an exception must be on record.

Files come from `--range A..B` (git diff), `--pre-push` (git's ref lines on stdin: a new branch is the
commits no remote-tracking ref has; deletions are skipped), or, by default, the merge-base of
`origin/main` and HEAD to HEAD. No `teyla.toml`, no `[productize]` or no `[productize.paths]` is a pass
with one line saying nothing was checked.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import tomllib

from . import config
from .productize import TRIGGER_RE, _real_date

LABELS = ("security", "data-loss", "backend-break")
LOG_NAME = "platform-gate.tsv"
MAX_FILES = 10
NO_MAP = "platform gate: no path map in teyla.toml, nothing checked"
ZEROS = set("0")


class GateError(Exception):
    """A refusal that is not a finding: bad label, unreadable log, unusable git state."""


# --- globs -----------------------------------------------------------------------------------

def glob_re(pattern: str) -> re.Pattern:
    """`**/` is zero or more directories, `**` anything, `*` anything but `/`, `?` one char but `/`."""
    out, i, n = [], 0, len(pattern)
    while i < n:
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def platforms_of(path: str, paths: dict) -> list[str]:
    if path.startswith("./"):
        path = path[2:]
    hit = []
    for plat, pats in paths.items():
        for pat in ([pats] if isinstance(pats, str) else pats or []):
            if glob_re(str(pat)).match(path):
                hit.append(plat)
                break
    return hit


# --- triggers --------------------------------------------------------------------------------

def trigger_problem(triggers: dict, plat: str) -> str | None:
    """None when the trigger is present and dated with a reason; else what is wrong (R10's rules)."""
    value = triggers.get(plat)
    if value is None or not str(value).strip():
        return "no trigger"
    m = TRIGGER_RE.match(str(value).strip())
    if not m or not _real_date(m.group(1)):
        return "trigger has no date"
    if not m.group(2).strip():
        return "trigger has no reason"
    return None


# --- git -------------------------------------------------------------------------------------

def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def _lines(p: subprocess.CompletedProcess) -> list[str]:
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def files_in_range(repo: pathlib.Path, rng: str) -> list[str]:
    p = _git(repo, "diff", "--name-only", rng)
    if p.returncode:
        raise GateError(f"git diff {rng} failed: {p.stderr.strip()}")
    return _lines(p)


def files_default(repo: pathlib.Path) -> tuple[list[str], str]:
    for base in ("origin/main", "main"):
        if _git(repo, "rev-parse", "--verify", "-q", base + "^{commit}").returncode:
            continue
        mb = _git(repo, "merge-base", base, "HEAD")
        if mb.returncode == 0 and mb.stdout.strip():
            rng = f"{mb.stdout.strip()}..HEAD"
            return files_in_range(repo, rng), rng
    return [], ""


def files_pre_push(repo: pathlib.Path, text: str, remote: str | None) -> tuple[list[str], str]:
    """Files touched by the commits a push adds, from git's `<lref> <lsha> <rref> <rsha>` lines."""
    files: list[str] = []
    ranges: list[str] = []
    seen = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        lsha, rsha = parts[1], parts[3]
        if not set(lsha) - ZEROS:          # a deletion pushes no commits
            continue
        if set(rsha) - ZEROS and _git(repo, "cat-file", "-e", rsha + "^{commit}").returncode == 0:
            excl, label = [rsha], f"{rsha[:12]}..{lsha[:12]}"
        else:                               # new branch: what no remote-tracking ref has
            excl = ["--remotes=" + remote] if remote else ["--remotes"]
            label = f"new:{lsha[:12]}"
        p = _git(repo, "log", "--name-only", "--format=", "-m", lsha, "--not", *excl)
        if p.returncode:
            raise GateError(f"git log for {label} failed: {p.stderr.strip()}")
        ranges.append(label)
        for f in _lines(p):
            if f not in seen:
                seen.add(f)
                files.append(f)
    return files, ",".join(ranges)


# --- the check -------------------------------------------------------------------------------

def load_manifest(repo: pathlib.Path) -> dict | None:
    f = repo / "teyla.toml"
    if not f.is_file():
        return None
    try:
        return tomllib.loads(f.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return None


def evaluate(manifest: dict | None, files: list[str]) -> dict:
    """Pure: the manifest and the changed files in, the verdict out. No git, no I/O."""
    pz = (manifest or {}).get("productize")
    paths = pz.get("paths") if isinstance(pz, dict) else None
    if not isinstance(paths, dict) or not paths:
        return {"ok": True, "checked": False, "note": NO_MAP, "violations": []}
    declared = [str(p) for p in (pz.get("platforms") or [])] or list(paths)
    primary = str(pz.get("primary") or "").strip()
    if len(declared) <= 1:
        return {"ok": True, "checked": False, "note": "platform gate: one platform, nothing to check",
                "violations": []}
    if not primary:
        return {"ok": True, "checked": False, "note": "platform gate: no primary in [productize], nothing checked",
                "violations": []}
    triggers = pz.get("triggers") if isinstance(pz.get("triggers"), dict) else {}
    touched: dict[str, list[str]] = {}
    for f in files:
        for plat in platforms_of(f, paths):
            touched.setdefault(plat, []).append(f)
    violations = []
    for plat, fs in touched.items():
        if plat == primary:
            continue
        problem = trigger_problem(triggers, plat)
        if problem:
            violations.append({"platform": plat, "files": fs, "problem": problem,
                               "add": f'{plat} = "YYYY-MM-DD: <who asked, why>"'})
    return {"ok": not violations, "checked": True, "primary": primary, "touched": sorted(touched),
            "violations": violations}


def render(result: dict) -> str:
    if not result["checked"]:
        return result["note"] + "\n"
    if result["ok"]:
        return f"platform gate: ok (primary {result['primary']}; touched: {', '.join(result['touched']) or 'none'})\n"
    out = [f"platform gate: refused. Primary is {result['primary']}; a second platform needs a dated trigger "
           f"(POLICY §14)."]
    for v in result["violations"]:
        out.append(f"\n  {v['platform']}: {v['problem']}")
        out.append("    files:")
        out += [f"      {f}" for f in v["files"][:MAX_FILES]]
        if len(v["files"]) > MAX_FILES:
            out.append(f"      +{len(v['files']) - MAX_FILES} more")
        out.append("    add to teyla.toml:")
        out.append("      [productize.triggers]")
        out.append(f"      {v['add']}")
    out.append(f"\n  Exception (security, data loss, a backend change that breaks a shipped client): "
               f"rerun with --label {'|'.join(LABELS)} or TEYLA_PLATFORM_LABEL=<label>; the use is logged.")
    return "\n".join(out) + "\n"


# --- the exception log -----------------------------------------------------------------------

def log_path() -> pathlib.Path:
    home = os.environ.get("TEYLA_HOME")
    return (pathlib.Path(home).expanduser() if home else config.TEYLA_DIR) / LOG_NAME


def log_exception(repo: pathlib.Path, label: str, platforms: list[str], rng: str) -> None:
    top = _git(repo, "rev-parse", "--show-toplevel")
    name = pathlib.Path(top.stdout.strip() or str(repo)).name
    row = "\t".join([datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), name, label,
                     ",".join(platforms), rng or "-"]) + "\n"
    p = log_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as fh:
            fh.write(row)
    except OSError as e:
        raise GateError(f"cannot record the exception in {p} ({e.strerror or e}); an exception that is not on "
                        f"record is not an exception") from e


def run(repo: pathlib.Path, *, rng: str | None = None, pre_push: bool = False, remote: str | None = None,
        label: str | None = None, stdin_text: str = "") -> tuple[int, dict]:
    label = (label or os.environ.get("TEYLA_PLATFORM_LABEL") or "").strip() or None
    if label and label not in LABELS:
        raise GateError(f"unknown label '{label}'; valid labels: {', '.join(LABELS)}")
    manifest = load_manifest(repo)
    if manifest is None or not isinstance(manifest.get("productize"), dict):
        return 0, evaluate(None, [])
    if pre_push:
        files, used = files_pre_push(repo, stdin_text, remote)
    elif rng:
        files, used = files_in_range(repo, rng), rng
    else:
        files, used = files_default(repo)
    result = evaluate(manifest, files)
    result["range"] = used
    if result["ok"]:
        return 0, result
    if label:
        log_exception(repo, label, [v["platform"] for v in result["violations"]], used)
        result["ok"], result["label"] = True, label
        return 0, result
    return 1, result


def cmd_check(args) -> int:
    repo = pathlib.Path(getattr(args, "repo", None) or ".").expanduser().resolve()
    pre_push = bool(getattr(args, "pre_push", False))
    stdin_text = sys.stdin.read() if pre_push else ""
    try:
        code, result = run(repo, rng=getattr(args, "range", None), pre_push=pre_push,
                           remote=getattr(args, "remote", None), label=getattr(args, "label", None),
                           stdin_text=stdin_text)
    except GateError as e:
        print(f"platform gate: refused: {e}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
    elif result.get("label"):
        print(f"platform gate: passed on label '{result['label']}' (logged to {log_path()})")
    elif code:
        sys.stderr.write(render(result))
    else:
        sys.stdout.write(render(result))
    return code

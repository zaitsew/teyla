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


def _git_z(repo: pathlib.Path, *args: str) -> tuple[int, list[str], str]:
    """Run git with `-z` output: NUL-separated, never quoted (core.quotePath cannot hide a path);
    decoded as UTF-8 with surrogateescape so any byte sequence survives."""
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    names = [n for n in p.stdout.decode("utf-8", "surrogateescape").split("\0") if n]
    return p.returncode, names, p.stderr.decode("utf-8", "replace").strip()


def _rev_of(rng: str | None) -> str:
    """The revision whose teyla.toml counts for `A..B` or `A...B`: B (HEAD when empty); else HEAD."""
    if rng and ".." in rng:
        return rng.split("..")[-1].lstrip(".") or "HEAD"
    return "HEAD"


def files_in_range(repo: pathlib.Path, rng: str) -> list[str]:
    # --no-renames: a move reports both the source and the destination path
    rc, names, err = _git_z(repo, "diff", "--name-only", "-z", "--no-renames", rng)
    if rc:
        raise GateError(f"git diff {rng} failed: {err}")
    return names


def files_default(repo: pathlib.Path) -> tuple[list[str], str]:  # the range is merge-base..HEAD
    for base in ("origin/main", "main"):
        if _git(repo, "rev-parse", "--verify", "-q", base + "^{commit}").returncode:
            continue
        mb = _git(repo, "merge-base", base, "HEAD")
        if mb.returncode == 0 and mb.stdout.strip():
            rng = f"{mb.stdout.strip()}..HEAD"
            return files_in_range(repo, rng), rng
    return [], ""


def files_pre_push(repo: pathlib.Path, text: str, remote: str | None) -> list[tuple[list[str], str, str]]:
    """Per pushed ref `(files, label, local sha)`: the files touched by the commits the push adds, from git's
    `<lref> <lsha> <rref> <rsha>` lines. The sha names the revision whose teyla.toml applies."""
    groups: list[tuple[list[str], str, str]] = []
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
        rc, names, err = _git_z(repo, "log", "--name-only", "-z", "--no-renames", "--format=", "-m", lsha,
                                "--not", *excl)
        if rc:
            raise GateError(f"git log for {label} failed: {err}")
        groups.append((list(dict.fromkeys(names)), label, lsha))
    return groups


# --- the check -------------------------------------------------------------------------------

def load_manifest(repo: pathlib.Path, rev: str) -> dict | None:
    """teyla.toml as committed at `rev`, never the working tree: an uncommitted trigger is not pushed."""
    p = subprocess.run(["git", "-C", str(repo), "show", f"{rev}:teyla.toml"], capture_output=True)
    if p.returncode:
        return None
    try:
        return tomllib.loads(p.stdout.decode("utf-8", "replace"))
    except tomllib.TOMLDecodeError:
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
    if pre_push:
        groups = files_pre_push(repo, stdin_text, remote)
    elif rng:
        groups = [(files_in_range(repo, rng), rng, _rev_of(rng))]
    else:
        files, used = files_default(repo)
        groups = [(files, used, "HEAD")]
    result = {"ok": True, "checked": False, "note": NO_MAP, "violations": []}
    merged: dict[str, dict] = {}
    for files, used, rev in groups:
        manifest = load_manifest(repo, rev)
        if manifest is None or not isinstance(manifest.get("productize"), dict):
            continue
        r = evaluate(manifest, files)
        if not r["checked"]:
            result["note"] = r["note"]
            continue
        result.update(checked=True, primary=r["primary"])
        result["touched"] = sorted(set(result.get("touched", [])) | set(r["touched"]))
        for v in r["violations"]:
            m = merged.setdefault(v["platform"], dict(v, files=[]))
            m["files"] += [f for f in v["files"] if f not in m["files"]]
    result["violations"] = list(merged.values())
    result["ok"] = not merged
    result["range"] = ",".join(g[1] for g in groups)
    used = result["range"]
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

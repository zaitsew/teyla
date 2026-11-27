"""`teyla ux check --diff [BASE]` — only what this change adds.

A repo-wide count is debt: it is the same number before and after a PR, so it cannot say whether
the PR is fine. Diff mode reads `git diff -U0` against BASE (default: the merge-base of HEAD with
origin/HEAD, else origin/main, origin/master, main, master), plus untracked files, and reports a
finding for each ADDED line that breaks a rule, with file:line and the rule. Local git only.

    blocking (exit 1)   font     a font size typed into a view
                        colour   a colour typed into a view
                        spacing  a padding number typed into a view
    warning (exit 0)    motion   a hand-written animation curve (SwiftUI)

The same file filters as the repo-wide check apply: token files, tests, previews, generated files
and comments are never flagged. Copy rules and the crowded-screen count stay repo-wide: they need
the whole screen to judge. Repo debt is one context line: the repo's literal count now and what
this diff changed (added minus removed, per changed file).
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess

from . import ux_check as u

BLOCKING = {"font", "colour", "spacing"}
RULES = {
    "font": ("font size typed into a view", "take the size from the product's type tokens"),
    "colour": ("colour typed into a view", "take the colour from the product's palette tokens"),
    "spacing": ("padding number typed into a view", "take the value from the product's spacing tokens"),
    "motion": ("hand-written animation curve", "take the curve from the product's motion tokens (R24)"),
}
BASE_CANDIDATES = ("origin/HEAD", "origin/main", "origin/master", "main", "master")


def _git(root: pathlib.Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def default_base(root: pathlib.Path) -> str | None:
    """The merge-base commit of HEAD with the first upstream ref that exists."""
    for ref in BASE_CANDIDATES:
        out = _git(root, "merge-base", "HEAD", ref)
        if out and out.strip():
            return out.strip()
    return None


def differs_from_base(root: pathlib.Path) -> bool:
    base = default_base(root)
    if not base:
        return False
    head = (_git(root, "rev-parse", "HEAD") or "").strip()
    if head and head != base:
        return True
    return bool((_git(root, "status", "--porcelain") or "").strip())


# --- line-level hits ----------------------------------------------------------------------------

def _kind(path: pathlib.Path, rel_parts: tuple[str, ...]) -> str | None:
    """swift, kotlin, web, or None when the file is not scanned for literals."""
    suffix = path.suffix.lower()
    if suffix not in (".swift", ".kt") and suffix not in u.WEB_SUFFIX:
        return None
    if u._skip_file(path) or u._is_token_file(path, rel_parts):
        return None
    if any(u._skip_dir(p) for p in rel_parts[:-1]):
        return None
    return "swift" if suffix == ".swift" else "kotlin" if suffix == ".kt" else "web"


def hits(text: str, kind: str, suffix: str) -> list[tuple[int, str]]:
    """(line, rule) for every literal in the text, one entry per literal."""
    if u._generated(text):
        return []
    out: list[tuple[int, str]] = []
    if kind == "swift":
        if not re.search(r"^\s*import\s+(SwiftUI|UIKit)\b", text, re.M):
            return []
        code = u.blank_blocks(u.strip_comments(text), u.SWIFT_PREVIEW)
        for i, ln in enumerate(code.splitlines(), 1):
            out += [(i, "font")] * len(u.SW_FONT.findall(ln))
            out += [(i, "colour")] * len(u.SW_COLOR.findall(ln))
            out += [(i, "spacing")] * u._padding_literals(ln, kotlin=False)
        for m in u.SW_MOTION.finditer(code):
            out.append((code.count("\n", 0, m.start()) + 1, "motion"))
    elif kind == "kotlin":
        if "@Composable" not in text:
            return []
        code = u.blank_blocks(u.strip_comments(text, quotes='"\''), u.KOTLIN_PREVIEW)
        for i, ln in enumerate(code.splitlines(), 1):
            out += [(i, "font")] * len(u.KT_FONT.findall(ln))
            out += [(i, "colour")] * len(u.KT_COLOR.findall(ln))
            out += [(i, "spacing")] * u._padding_literals(ln, kotlin=True)
    else:
        if suffix in u.HTMLISH:
            text = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
        code = u.strip_comments(text, quotes="" if suffix == ".css" else "'\"`", line_comments=suffix != ".css")
        for i, ln in enumerate(code.splitlines(), 1):
            out += [(i, "font")] * len(u.WEB_FONT.findall(ln))
            out += [(i, "colour")] * u._web_colors(ln)
    return out


# --- the diff -----------------------------------------------------------------------------------

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed(root: pathlib.Path, base: str) -> dict[str, dict] | None:
    """{path: {"old": path before or None, "added": set of line numbers or None for a new file}}"""
    diff = _git(root, "diff", "-U0", "--no-color", "--no-ext-diff", "-M", base, "--")
    if diff is None:
        return None
    files: dict[str, dict] = {}
    old: str | None = None
    cur: dict | None = None
    for ln in diff.splitlines():
        if ln.startswith("diff --git "):
            old, cur = None, None
        elif ln.startswith("--- "):
            old = None if ln == "--- /dev/null" else ln[6:] if ln.startswith("--- a/") else None
        elif ln.startswith("+++ "):
            if ln == "+++ /dev/null":
                cur = None
                continue
            path = ln[6:] if ln.startswith("+++ b/") else ln[4:]
            cur = files.setdefault(path, {"old": old, "added": set()})
        elif cur is not None and (m := HUNK.match(ln)):
            start, n = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            cur["added"].update(range(start, start + n))
    untracked = _git(root, "ls-files", "--others", "--exclude-standard") or ""
    for p in untracked.splitlines():
        files.setdefault(p, {"old": None, "added": set()})["new"] = True
    return files


def _read_head(root: pathlib.Path, rel: str) -> str | None:
    return u._read(root / rel)


def check_diff(root: pathlib.Path, base: str | None = None) -> dict:
    root = pathlib.Path(root)
    resolved = base or default_base(root)
    report = {"repo": root.name, "path": str(root), "base": resolved, "findings": [], "blocking": 0,
              "warnings": 0, "debt": None, "debt_delta": 0, "error": None}
    if not resolved:
        report["error"] = "no base: pass one, e.g. `--diff origin/main`"
        return report
    base_sha = (_git(root, "rev-parse", "--verify", f"{resolved}^{{commit}}") or "").strip()
    if not base_sha:
        report["error"] = f"base {resolved!r} is not a commit in this repo"
        return report
    if base:  # an explicit base may be a branch: compare from the point the branch forked
        mb = (_git(root, "merge-base", "HEAD", base_sha) or "").strip()
        base_sha = mb or base_sha
    report["base"] = base_sha[:10]
    files = changed(root, base_sha)
    if files is None:
        report["error"] = "git diff failed"
        return report
    delta = 0
    for rel, info in sorted(files.items()):
        path = root / rel
        kind = _kind(path, pathlib.PurePosixPath(rel).parts)
        if kind is None:
            continue
        text = _read_head(root, rel)
        if text is None:
            continue
        suffix = path.suffix.lower()
        now = hits(text, kind, suffix)
        added = info["added"]
        new_file = info.get("new") or info["old"] is None
        for line, rule in now:
            if new_file or line in added:
                what, fix = RULES[rule]
                sev = "FIX" if rule in BLOCKING else "WARN"
                report["findings"].append({"check": rule, "severity": sev, "file": rel, "line": line,
                                           "message": what, "fix": fix})
        before = []
        if info["old"]:
            old_text = _git(root, "show", f"{base_sha}:{info['old']}")
            before = hits(old_text, kind, suffix) if old_text else []
        delta += sum(1 for _, r in now if r in BLOCKING) - sum(1 for _, r in before if r in BLOCKING)
    report["findings"].sort(key=lambda f: (f["file"], f["line"], f["check"]))
    report["blocking"] = sum(1 for f in report["findings"] if f["severity"] == "FIX")
    report["warnings"] = len(report["findings"]) - report["blocking"]
    a = u.audit(root)
    c = a["counts"]
    report["debt"] = {"font": c["font"], "colour": c["colour"], "spacing": c["spacing"], "total": a["literals"]}
    report["debt_delta"] = delta
    return report


def debt_line(r: dict) -> str:
    d = r["debt"]
    parts = [f"{d[k]} {k} literals" for k in ("font", "colour", "spacing") if d[k]] or ["0 literals"]
    delta = r["debt_delta"]
    change = "unchanged" if delta == 0 else f"+{delta}" if delta > 0 else f"−{-delta}"
    return f"repo debt: {', '.join(parts)}, {change} by this diff"


def render(reports: list[dict]) -> str:
    L: list[str] = []
    for r in reports:
        if len(reports) > 1:
            L.append(f"{r['repo']}:")
        if r["error"]:
            L.append(f"  ERROR {r['error']}")
            continue
        for f in r["findings"]:
            L.append(f"{f['severity']:<4} {f['check']:<8} {f['file']}:{f['line']}  {f['message']}; fix: {f['fix']}")
        verdict = "FAIL" if r["blocking"] else "PASS"
        L.append(f"{verdict}: {r['blocking']} blocking, {r['warnings']} warning(s) added since {r['base']}")
        L.append(debt_line(r))
    return "\n".join(L)


def run(repos: list[pathlib.Path], base: str | None, as_json: bool) -> int:
    reports = [check_diff(r, base) for r in repos]
    if as_json:
        print(json.dumps({"repos": reports, "blocking": sum(r["blocking"] for r in reports)}, indent=1))
    else:
        print(render(reports))
    if any(r["error"] for r in reports):
        return 2
    return 1 if any(r["blocking"] for r in reports) else 0


def hint(root: pathlib.Path) -> str | None:
    if differs_from_base(root):
        return "hint: this branch differs from its base; `teyla ux check --diff` reports only what it adds (exit 1 on a violation)"
    return None

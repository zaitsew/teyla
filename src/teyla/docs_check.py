"""`teyla docs check` — does a repo's documentation describe the product as it is now?

    teyla docs check [repo...] [--all] [--json] [--strict]

READMEs get written once and drift while the product changes; internal docs collect the story of
how a decision was reached instead of the state that resulted. This reads a repo's README.md and
docs/ and says what to fix. It reads files only: no network, no writes, no git history.

Repos: none given means the git root of the current directory. A name is looked up under
`code_root`, a path is used as it is, `--all` is every git repo under `code_root`.

Each finding has a severity and the fix:

    FIX   the README has no opening, or its opening is the scaffold's placeholder; a README is missing
    WARN  everything else below

Checks:

    opening       The first prose paragraph after the H1 (badges, images, HTML and comments skipped)
                  says what the product is, in 60 words or fewer. Missing or a template placeholder
                  is FIX; longer than 60 words is WARN.
    quick-start   A fenced shell block within the first 80 lines of the README. WARN if absent.
    length        README over 2,500 words (whitespace-separated, as `wc -w`). WARN, naming the
                  largest `##` section and its words: "move to docs/".
    placeholder   `(fill in` or similar template text left anywhere in the README. WARN.
    dead-command  Only for a Python CLI whose `[project.scripts]` has `teyla` (Teyla itself): every
                  `teyla <sub>` in a code span or fenced block of README.md and docs/ must be a
                  subcommand of the parser (and a second word, where the parser nests). The parser
                  is built in-process from `teyla.cli.build_parser`. Other repos: skipped.
                  docs/ROADMAP.md is not read, nor a doc whose `Status:` line (within its first
                  five lines) says roadmap: a roadmap names commands that do not exist yet.
    history       A docs/*.md file whose lines read as decision history: dated phrases ("on
                  2026-", "(2026-09-30)", "as of", "rev. 2"), "used to", "we decided", "was
                  changed", "previously". 4 or more such lines AND 5% or more of its prose lines is
                  WARN: keep the current state, move the story to the PR or docs/decisions/.
                  Not read: docs/decisions/, docs/reviews/, docs/case-studies/, CHANGELOG, ROADMAP.
    status-drift  A doc whose first lines say "Status: spec", "draft" or "v0" while the README links
                  it without such a label on that line. WARN.

Exit status is 0, unless `--strict` is given and a FIX exists (then 1). `--json` prints
{"repos": [{"repo", "path", "findings": [{"check", "severity", "file", "line", "message", "fix"}]}],
"totals": {"FIX", "WARN"}}.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

from . import config

FIX, WARN = "FIX", "WARN"

OPENING_MAX_WORDS = 60
QUICK_START_LINES = 80
README_MAX_WORDS = 2500
HISTORY_MIN_LINES = 4
HISTORY_MIN_SHARE = 0.05

# docs/ subtrees and files that are history, plans or generated on purpose.
HISTORY_DIRS = {"decisions", "reviews", "case-studies"}
SKIP_NAMES = {"changelog.md", "roadmap.md"}
SHELL_LANGS = {"", "sh", "bash", "shell", "zsh", "console", "terminal", "shell-session", "fish"}

PLACEHOLDERS = [
    re.compile(r"^one line: what .+ does, for the person opening this repo cold", re.I),
    re.compile(r"\(fill in", re.I),
    re.compile(r"\{\{\s*\w+\s*\}\}"),
    re.compile(r"\blorem ipsum\b", re.I),
    re.compile(r"\bTODO\b"),
    re.compile(r"^(a )?short description\b", re.I),
    re.compile(r"\b(describe|add) (your|the|a) (project|app|product)\b", re.I),
    re.compile(r"^this (project|repo|repository) was bootstrapped with\b", re.I),
]

NARRATIVE = [
    re.compile(r"\b(on|as of|since|from|until|by|in) 20\d\d-\d\d", re.I),
    re.compile(r"\(\s*20\d\d-\d\d(-\d\d)?\b"),
    re.compile(r"\bas of\b", re.I),
    re.compile(r"\brev(ision|\.)?\s*\d+\b", re.I),
    re.compile(r"\bused to\b", re.I),
    re.compile(r"\bwe (decided|chose|agreed)\b", re.I),
    re.compile(r"\bwas (changed|renamed|replaced|dropped|reverted)\b", re.I),
    re.compile(r"\bpreviously\b", re.I),
]

FENCE = re.compile(r"^\s*(```+|~~~+)\s*([\w+-]*)")
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
BADGE_LINE = re.compile(r"^(\[?!\[[^\]]*\]\([^)]*\)\]?(\([^)]*\))?\s*)+$")
HTML_LINE = re.compile(r"^</?[a-zA-Z][^>]*>")
STATUS_LINE = re.compile(r"^\W*status\W*:?\s*(.*)$", re.I)
STATUS_WORDS = re.compile(r"\b(spec|draft|v0|proposal|proposed|rfc|wip)\b", re.I)
LABEL_WORDS = re.compile(r"\b(spec|draft|v0|proposal|proposed|rfc|wip|planned|experimental|preview|alpha|beta)\b", re.I)
TEYLA_CMD = re.compile(r"(?:^|[\s;&|(\"'])teyla\s+([a-z][\w-]*)(?:\s+([a-z][\w-]*))?")


def _finding(check, severity, file, line, message, fix):
    return {"check": check, "severity": severity, "file": file, "line": line, "message": message, "fix": fix}


def words(text: str) -> int:
    return len(text.split())


# --- markdown reading ------------------------------------------------------------------------

def fence_state(lines: list[str]) -> list[str | None]:
    """Per line: None outside a fenced block, else the block's language ('' when unlabelled).
    The fence marker lines themselves are marked as '<marker>'."""
    out: list[str | None] = []
    marker = None
    lang = ""
    for ln in lines:
        m = FENCE.match(ln)
        if marker is None:
            if m:
                marker, lang = m.group(1), m.group(2).lower()
                out.append("<marker>")
            else:
                out.append(None)
        else:
            if m and m.group(1).startswith(marker) and not m.group(2):
                marker = None
                out.append("<marker>")
            else:
                out.append(lang)
    return out


def _plain(s: str) -> str:
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    return re.sub(r"[*_`]", "", s).strip()


def opening_paragraph(lines: list[str], state: list[str | None]) -> tuple[str, int] | None:
    """The first prose paragraph after the first H1, and its 1-based line. None when a heading,
    a fenced block, a list or a table comes first."""
    start = 0
    for i, ln in enumerate(lines):
        if state[i] is None and re.match(r"^#\s+\S", ln):
            start = i + 1
            break
    para: list[str] = []
    first = 0
    in_comment = False
    for i in range(start, len(lines)):
        raw = lines[i]
        s = raw.strip()
        if state[i] is not None:
            return (" ".join(para), first) if para else None
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith("<!--"):
            if "-->" not in s:
                in_comment = True
            continue
        if not s:
            if para:
                break
            continue
        if HEADING.match(s):
            if para:
                break
            return None
        if not para:
            if BADGE_LINE.match(s) or HTML_LINE.match(s):
                continue
            if re.match(r"^([-*+]\s|\d+[.)]\s|\|)", s):
                return None
            if s.startswith(">"):
                s = s.lstrip("> ").strip()
                if not s:
                    continue
        elif re.match(r"^([-*+]\s|\d+[.)]\s|\|)", s):
            break
        if not para:
            first = i + 1
        para.append(s)
    return (" ".join(para), first) if para else None


def sections(lines: list[str], state: list[str | None]) -> list[tuple[str, int]]:
    """(`##` heading, words under it incl. subsections), in order. Text before the first `##` is not a section."""
    out: list[list] = []
    for i, ln in enumerate(lines):
        if state[i] is None:
            m = HEADING.match(ln)
            if m and len(m.group(1)) == 2:
                out.append([m.group(2), 0])
                continue
        if out:
            out[-1][1] += words(ln)
    return [(h, n) for h, n in out]


# --- the checks ------------------------------------------------------------------------------

def check_readme(root: pathlib.Path, readme: pathlib.Path) -> list[dict]:
    rel = readme.name
    text = readme.read_text(errors="replace")
    lines = text.splitlines()
    state = fence_state(lines)
    out: list[dict] = []

    op = opening_paragraph(lines, state)
    if op is None:
        out.append(_finding("opening", FIX, rel, 1,
                            "no opening paragraph: a heading, list or code block comes before any prose",
                            "put one paragraph under the title saying what the product is and who it is for, in 60 words or fewer"))
    else:
        para, ln = op
        plain = _plain(para)
        if any(p.search(plain) for p in PLACEHOLDERS):
            out.append(_finding("opening", FIX, rel, ln, "the opening is the template placeholder",
                                "replace it with what the product does, in 60 words or fewer"))
        elif words(plain) > OPENING_MAX_WORDS:
            out.append(_finding("opening", WARN, rel, ln, f"the opening is {words(plain)} words (limit {OPENING_MAX_WORDS})",
                                "cut it to what the product is, who it is for and why it helps; move the rest below"))

    for i, ln in enumerate(lines[:QUICK_START_LINES]):
        if state[i] == "<marker>" and (i == 0 or state[i - 1] is None):
            m = FENCE.match(ln)
            if m and m.group(2).lower() in SHELL_LANGS:
                break
    else:
        out.append(_finding("quick-start", WARN, rel, 1,
                            f"no fenced shell block in the first {QUICK_START_LINES} lines",
                            "add a quick start: the three to five commands that take a new reader from clone to first result"))

    total = words(text)
    if total > README_MAX_WORDS:
        secs = sections(lines, state)
        if secs:
            name, n = max(secs, key=lambda s: s[1])
            big = f"; largest section: \"{name}\" ({n:,} words)"
        else:
            big = ""
        out.append(_finding("length", WARN, rel, 1, f"{total:,} words (limit {README_MAX_WORDS:,}){big}",
                            f"move that section to docs/ and leave a link" if big else "move reference material to docs/ and leave links"))

    for i, ln in enumerate(lines):
        if state[i] is None and re.search(r"\(fill in|\{\{\s*\w+\s*\}\}", ln, re.I):
            out.append(_finding("placeholder", WARN, rel, i + 1, "template placeholder text left in the README",
                                "write the real content or delete the line"))
            break
    return out


def _doc_files(root: pathlib.Path) -> list[pathlib.Path]:
    d = root / "docs"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.rglob("*.md")):
        parts = p.relative_to(d).parts
        if HISTORY_DIRS & set(parts[:-1]) or p.name.lower() in SKIP_NAMES:
            continue
        out.append(p)
    return out


def check_history(root: pathlib.Path, doc: pathlib.Path) -> dict | None:
    lines = doc.read_text(errors="replace").splitlines()
    state = fence_state(lines)
    prose = [ln for i, ln in enumerate(lines) if state[i] is None and ln.strip() and not HEADING.match(ln)]
    hits = [ln for ln in prose if any(p.search(ln) for p in NARRATIVE)]
    if len(hits) >= HISTORY_MIN_LINES and prose and len(hits) / len(prose) >= HISTORY_MIN_SHARE:
        rel = str(doc.relative_to(root))
        return _finding("history", WARN, rel, 1,
                        f"reads as decision history: {len(hits)} of {len(prose)} prose lines are dated or narrative",
                        "keep the current state here; move the story to the PR or docs/decisions/")
    return None


def check_status_drift(root: pathlib.Path, readme: pathlib.Path | None, docs: list[pathlib.Path]) -> list[dict]:
    """A doc that calls itself a spec or draft while the README (or docs/COMMANDS.md, where the command
    table lives) links it without any such label on the linking line."""
    presenters = [(readme, "")] if readme else []
    cmds = root / "docs" / "COMMANDS.md"
    if cmds.is_file():
        presenters.append((cmds, "docs/"))
    if not presenters:
        return []
    out = []
    for doc in docs:
        head = doc.read_text(errors="replace").splitlines()[:12]
        status = None
        for ln in head[1:]:
            m = STATUS_LINE.match(ln.strip())
            if m and STATUS_WORDS.search(m.group(1)):
                status = ln.strip()
                break
        if not status:
            continue
        rel = str(doc.relative_to(root))
        linking = []
        for pres, prefix in presenters:
            target = rel[len(prefix):] if prefix and rel.startswith(prefix) else rel
            linking += [ln for ln in pres.read_text(errors="replace").splitlines() if f"({target})" in ln or f"({target}#" in ln or f"`{target}`" in ln]
        if linking and not any(LABEL_WORDS.search(ln) for ln in linking):
            out.append(_finding("status-drift", WARN, rel, 1,
                                f"says \"{status[:60]}\" but the README presents it without that label",
                                "update the status line to what shipped, or label it in the README"))
    return out


# --- dead commands (Teyla itself) --------------------------------------------------------------

def is_teyla_repo(root: pathlib.Path) -> bool:
    py = root / "pyproject.toml"
    if not py.is_file():
        return False
    try:
        import tomllib
        data = tomllib.loads(py.read_text())
    except (OSError, ValueError):
        return False
    return "teyla" in ((data.get("project") or {}).get("scripts") or {})


def parser_commands() -> dict[str, set[str] | None]:
    """Top-level subcommands of the real parser -> its nested subcommand names, or None when the
    command takes positional words rather than argparse sub-subcommands."""
    import argparse
    from . import cli
    p = cli.build_parser()

    def subs(parser):
        for a in parser._actions:
            if isinstance(a, argparse._SubParsersAction):
                return a.choices
        return None
    top = subs(p) or {}
    out: dict[str, set[str] | None] = {}
    for name, sub in top.items():
        nested = subs(sub)
        out[name] = set(nested) if nested else None
    return out


def code_mentions(lines: list[str], state: list[str | None]):
    """(line number, text) for every code span and fenced-block line."""
    for i, ln in enumerate(lines):
        st = state[i]
        if st is None:
            for m in re.finditer(r"`([^`\n]+)`", ln):
                yield i + 1, m.group(1)
        elif st != "<marker>":
            yield i + 1, ln


def is_roadmap(doc: pathlib.Path) -> bool:
    """docs/ROADMAP.md, or a doc whose `Status:` line in its first five lines says roadmap."""
    if doc.name.lower() == "roadmap.md":
        return True
    try:
        head = doc.read_text(encoding="utf-8", errors="replace").splitlines()[:5]
    except OSError:
        return False
    return any(line.startswith("Status:") and "roadmap" in line.lower() for line in head)


def check_dead_commands(root: pathlib.Path, files: list[pathlib.Path], commands: dict[str, set[str] | None] | None = None) -> list[dict]:
    cmds = commands if commands is not None else parser_commands()
    out, seen = [], set()
    for f in files:
        lines = f.read_text(errors="replace").splitlines()
        state = fence_state(lines)
        rel = str(f.relative_to(root))
        for no, text in code_mentions(lines, state):
            for m in TEYLA_CMD.finditer(text):
                sub, nxt = m.group(1), m.group(2)
                if sub not in cmds:
                    key = (rel, sub)
                    if key not in seen:
                        seen.add(key)
                        out.append(_finding("dead-command", WARN, rel, no, f"`teyla {sub}` is not a command",
                                            "rename it to the current command or remove the line"))
                elif cmds[sub] is not None and nxt and nxt not in cmds[sub]:
                    key = (rel, f"{sub} {nxt}")
                    if key not in seen:
                        seen.add(key)
                        out.append(_finding("dead-command", WARN, rel, no, f"`teyla {sub} {nxt}` is not a command",
                                            "rename it to the current command or remove the line"))
    return out


# --- a repo ------------------------------------------------------------------------------------

def check_repo(root: pathlib.Path, commands: dict | None = None) -> dict:
    root = pathlib.Path(root)
    findings: list[dict] = []
    readme = next((root / n for n in ("README.md", "Readme.md", "readme.md") if (root / n).is_file()), None)
    docs = _doc_files(root)
    if readme is None:
        findings.append(_finding("opening", FIX, "README.md", 0, "no README.md", "write one: what the product is, then a quick start"))
    else:
        findings += check_readme(root, readme)
    for d in docs:
        f = check_history(root, d)
        if f:
            findings.append(f)
    findings += check_status_drift(root, readme, docs)
    if is_teyla_repo(root):
        scan = ([readme] if readme else []) + [d for d in docs if not is_roadmap(d)]
        findings += check_dead_commands(root, scan, commands)
    return {"repo": root.name, "path": str(root), "findings": findings}


def totals(reports: list[dict]) -> dict:
    return {s: sum(1 for r in reports for f in r["findings"] if f["severity"] == s) for s in (FIX, WARN)}


# --- CLI ---------------------------------------------------------------------------------------

def _git_root(cwd: pathlib.Path) -> pathlib.Path:
    try:
        r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return pathlib.Path(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return cwd


def resolve(args_repos: list[str], all_repos: bool, cfg: dict | None = None) -> list[pathlib.Path]:
    cfg = cfg or config.load()
    if all_repos:
        from . import cloud
        return cloud.discover_repos(cfg)
    if not args_repos:
        return [_git_root(pathlib.Path.cwd())]
    root = config.code_root(cfg)
    out = []
    for a in args_repos:
        p = pathlib.Path(a).expanduser()
        if not (p.is_absolute() or "/" in a or a.startswith("~") or a in (".", "..")) and (root / a).is_dir():
            p = root / a
        if not p.is_dir():
            raise FileNotFoundError(f"{a}: not a directory ({p})")
        out.append(p)
    return out


def render(reports: list[dict]) -> str:
    L: list[str] = []
    for r in reports:
        if not r["findings"]:
            L.append(f"{r['repo']}: ok")
            continue
        L.append(f"{r['repo']}:")
        for f in r["findings"]:
            where = f["file"] + (f":{f['line']}" if f["line"] else "")
            L.append(f"  {f['severity']:<4} {f['check']:<13} {where}  {f['message']}")
            L.append(f"       fix: {f['fix']}")
    t = totals(reports)
    L.append("")
    L.append(f"{len(reports)} repo(s): {t[FIX]} FIX, {t[WARN]} WARN")
    return "\n".join(L)


def cmd_docs(args) -> int:
    if args.action != "check":
        print(f"teyla docs: unknown action {args.action!r}", file=sys.stderr)
        return 2
    try:
        repos = resolve(args.repos, args.all)
    except FileNotFoundError as e:
        print(f"teyla docs check: {e}", file=sys.stderr)
        return 2
    cmds = None
    reports = []
    for r in repos:
        if cmds is None and is_teyla_repo(r):
            cmds = parser_commands()
        reports.append(check_repo(r, cmds))
    if args.json:
        print(json.dumps({"repos": reports, "totals": totals(reports)}, indent=1))
    else:
        print(render(reports))
    return 1 if args.strict and totals(reports)[FIX] else 0


def register(sp):
    q = sp.add_parser("docs", help="does a repo's README and docs describe the product as it is now: opening, quick start, length, dead commands, decision history")
    q.set_defaults(fn=cmd_docs)
    q.add_argument("action", choices=["check"])
    q.add_argument("repos", nargs="*", help="repo names under code_root or paths (default: the git root of the current directory)")
    q.add_argument("--all", action="store_true", help="every git repo under code_root")
    q.add_argument("--json", action="store_true")
    q.add_argument("--strict", action="store_true", help="exit 1 when any FIX exists")
    return q

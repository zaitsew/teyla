"""`teyla cloud` — what a cloud session (Claude Code on the web, `claude --cloud`) will lack in
a repo, and what the cloud sessions that already ran left behind.

    teyla cloud check [<repo>...] [--json]     readiness per repo; exit 1 on any BLOCK
    teyla cloud inbox [--days N] [--json]      cloud branches with no PR + open PRs labelled needs-mac
    teyla cloud prep <repo> [--dry] [--allow-public] [--fix-gitignore]   write what is missing (cloud_prep.py)

Why this exists (measured 2026-09-29): all three cloud sessions in September left their work
on a `claude/*` branch — unbuilt, no PR, unmerged — and a local session had to find, build,
review and merge it the next morning. A cloud VM clones the repo and nothing else: no user
CLAUDE.md, no POLICY.md, no user skills, plugins, hooks or memory, no codex/grok/Xcode. It
does honour the repo's own CLAUDE.md, `.claude/rules/`, `.claude/skills/` and (single-repo
sessions) `.claude/settings.json` hooks, and it sets CLAUDE_CODE_REMOTE=true. So a repo is
cloud-ready when everything a session needs to *finish* is in the clone.

Cloud sessions are found in git, not in transcripts: the desktop app lists only local
sessions, but every cloud commit carries a `Claude-Session: https://claude.ai/code/session_…`
trailer. Local refs can be stale; `git fetch` in a repo refreshes what this sees.
"""
from __future__ import annotations

import concurrent.futures as _cf
import datetime as _dt
import errno
import json
import os
import pathlib
import re
import shutil
import subprocess

from . import config

# --- levels -----------------------------------------------------------------------
# BLOCK: a cloud session in this repo will not finish (the observed failure). WARN: it will
# finish worse than a local one. INFO: a fact, not scored.
BLOCK, WARN, OK, INFO = "BLOCK", "WARN", "OK", "INFO"

DONE_STATE_LABEL = "needs-mac"
CLOUD_MARK = "teyla:cloud:start"
# The file `teyla cloud prep` writes the environment script and secret names into; a repo
# that lists its secret names there has a manifest.
SECRETS_MANIFEST = "docs/cloud-setup.md"

# Home-directory files that carry instructions. A pointer to one of them ("Merge-approved per
# the user CLAUDE.md") is an instruction the cloud session cannot follow: the file is not there.
_POLICY_POINTER = re.compile(r"~/\.(?:claude|agents|codex|grok|hermes)/")
_HOME_PATH = re.compile(r"(?<![\w.])~/")
_MERGE_LINE = re.compile(r"^[\s>*-]*`?merge-approved:\s*`?\s*(yes|no)\b", re.I | re.M)

# Shipping rules a repo must carry itself, each as (name, pattern over the instruction text).
SHIPPING_RULES = (
    ("one PR per logical unit", re.compile(r"one (?:PR|pull request) per|PR per (?:logical )?unit", re.I)),
    ("merge, don't squash", re.compile(r"squash", re.I)),
    ("never force-push", re.compile(r"force[- ]?push", re.I)),
)
DONE_STATE = re.compile(r"needs-mac|definition of done|done state|done-state|open the PR before|" + CLOUD_MARK, re.I)

# check.sh steps that need a Mac. The Linux cloud image has none of these (Ubuntu 24.04 with
# gh, git, Node, Python, uv, Docker, Postgres — cloud-environments docs).
MAC_STEPS = (
    ("xcodebuild", re.compile(r"\bxcodebuild\b")),
    ("xcrun", re.compile(r"\bxcrun\b")),
    ("xcodegen", re.compile(r"\bxcodegen\b")),
    ("swift", re.compile(r"\bswift\s+(?:build|test|run|package)\b")),
    ("simctl", re.compile(r"\bsimctl\b")),
    ("launchctl", re.compile(r"\blaunchctl\b")),
    ("security", re.compile(r"\bsecurity\s+(?:find|add|unlock|import|delete|default|list)-")),
    ("codesign", re.compile(r"\bcodesign\b")),
    ("osascript", re.compile(r"\bosascript\b")),
    ("testflight", re.compile(r"\btestflight\b")),
    ("notarytool", re.compile(r"\bnotarytool\b")),
)
_GENERIC_GUARD = re.compile(r"\buname\b|Darwin|OSTYPE|CLAUDE_CODE_REMOTE|\[\s+-[dxef]\s+[^]]*(?:Xcode|DEVELOPER_DIR|XCODE)")
_SKIP_PRINT = re.compile(r"(?:echo|printf|say|skip)\b[^\n]*skip|^\s*skip\s", re.I | re.M)

_SLUG = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")


def _safe_mode() -> bool:
    """Work mode, when this build has it (config.safe_mode); else TEYLA_SAFE=1. In safe mode
    nothing here calls `gh` — that is the network."""
    fn = getattr(config, "safe_mode", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:  # noqa: BLE001 — unreadable config must fail closed
            return True
    return os.environ.get("TEYLA_SAFE", "").strip().lower() in ("1", "true", "yes", "on")


def gh_usable() -> bool:
    return bool(shutil.which("gh")) and not _safe_mode()


def _git(repo: pathlib.Path, *args, timeout=20) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=timeout)


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


# --- the owner's list --------------------------------------------------------------

def owner_claude_md() -> pathlib.Path:
    return pathlib.Path.home() / ".claude" / "CLAUDE.md"


def parse_owner_list(text: str) -> set[str] | None:
    """owner/name entries of the MERGE-APPROVED REPOS block in the owner's CLAUDE.md, lowercased.
    The block is the lines after the `MERGE-APPROVED REPOS` header up to the closing fence; an
    entry is the first token of a line, before any `#` comment (comments name other repos —
    "added as <old name>" — and must not count). None when the file has no such block."""
    lines = text.splitlines()
    start = next((i + 1 for i, l in enumerate(lines) if "MERGE-APPROVED REPOS" in l), None)
    if start is None:
        return None
    out = set()
    for line in lines[start:]:
        s = line.strip()
        if s.startswith("```"):
            break
        s = s.split("#", 1)[0].strip()
        if not s:
            continue
        tok = s.split()[0]
        if re.fullmatch(r"[\w.-]+/[\w.-]+", tok):
            out.add(tok.lower())
    return out


def owner_list(path: pathlib.Path | None = None) -> set[str] | None:
    p = path or owner_claude_md()
    return parse_owner_list(_read(p)) if p.exists() else None


def origin_slug(repo: pathlib.Path) -> str | None:
    """owner/name of `origin` on GitHub. Read from .git/config directly — doctor runs this for
    every repo under code_root and a `git remote get-url` per repo is most of its budget."""
    url = None
    cfgf = repo / ".git" / "config"
    if cfgf.is_file():
        m = re.search(r'\[remote "origin"\][^\[]*?^\s*url\s*=\s*(\S+)', _read(cfgf), re.M | re.S)
        url = m.group(1) if m else None
    else:
        try:
            r = _git(repo, "remote", "get-url", "origin", timeout=5)
            url = r.stdout.strip() if r.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            url = None
    if not url:
        return None
    m = _SLUG.search(url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def expected_merge_approved(slug: str | None, owners: set[str] | None) -> str | None:
    if slug is None or owners is None:
        return None
    return "yes" if slug.lower() in owners else "no"


# --- what the clone carries ---------------------------------------------------------

def _instruction_candidates(repo: pathlib.Path) -> list[pathlib.Path]:
    cands = [repo / "CLAUDE.md", repo / "AGENTS.md", repo / ".claude" / "CLAUDE.md"]
    rules = repo / ".claude" / "rules"
    if rules.is_dir():
        cands += sorted(rules.rglob("*.md"))
    # is_symlink() too: a dangling link (CLAUDE.md → a policy file only this Mac has) is not
    # is_file(), and dropping it here hid it from external_instruction_links (review, P1).
    return [p for p in cands if p.is_file() or p.is_symlink()]


def symlink_loop(p: pathlib.Path) -> bool:
    """A symlink that never reaches a file (CLAUDE.md → AGENTS.md → CLAUDE.md). Asked with
    os.stat, the same on every Python: resolve() raises RuntimeError on 3.11/3.12 and returns
    the path on 3.13, and the RuntimeError crashed `cloud check` (review of #70, P2)."""
    try:
        if not p.is_symlink():
            return False
        os.stat(p)
        return False
    except OSError as e:
        return e.errno == errno.ELOOP


def _inside(repo: pathlib.Path, p: pathlib.Path) -> bool:
    try:
        p.resolve().relative_to(repo.resolve())
        return True
    except (ValueError, RuntimeError, OSError):  # RuntimeError: a symlink loop on Python < 3.13
        return False


def external_instruction_links(repo: pathlib.Path) -> list[str]:
    """Instruction files that are symlinks resolving outside the repo (e.g. CLAUDE.md →
    ~/.claude/CLAUDE.md). A cloud clone gets a dangling link, so they carry nothing there
    (review of #70, P1)."""
    return [f"{p.relative_to(repo)} → {os.readlink(p)}" for p in _instruction_candidates(repo)
            if p.is_symlink() and not symlink_loop(p) and not _inside(repo, p)]


def looped_instruction_links(repo: pathlib.Path) -> list[str]:
    """Instruction files that are symlinks in a loop: no session, local or cloud, can read them."""
    return [f"{p.relative_to(repo)} → {os.readlink(p)}" for p in _instruction_candidates(repo) if symlink_loop(p)]


def instruction_files(repo: pathlib.Path) -> list[tuple[str, str]]:
    """(repo-relative name, text) for every instruction file a cloud session reads, each real
    file once (AGENTS.md → CLAUDE.md symlinks are common and would double every finding).
    A symlink that resolves outside the repo is not read: readiness is judged on what the
    committed tree carries, and the clone does not carry its target (review of #70, P1)."""
    repo = repo.resolve()
    seen, out = set(), []
    for p in _instruction_candidates(repo):
        if symlink_loop(p) or not p.is_file() or not _inside(repo, p):
            continue
        real = p.resolve()
        if real in seen:
            continue
        seen.add(real)
        # Name the real file: in a CLAUDE.md → AGENTS.md repo the line numbers are AGENTS.md's.
        out.append((str(real.relative_to(repo)), _read(p)))
    return out


def declared_merge_approved(files: list[tuple[str, str]]) -> set[str]:
    return {m.group(1).lower() for _, t in files for m in _MERGE_LINE.finditer(t)}


def _line_numbers(text: str, rx: re.Pattern) -> list[int]:
    return [i for i, l in enumerate(text.splitlines(), 1) if rx.search(l)]


def claude_ignored(repo: pathlib.Path) -> list[str]:
    """The repo-scoped Claude Code files git would refuse to add. `--no-index` so a tracked file
    does not hide an ignore rule that blocks the next new one."""
    paths = (".claude/settings.json", ".claude/rules/cloud.md", ".claude/hooks/teyla-cloud-stop.sh")
    try:
        r = _git(repo, "check-ignore", "--no-index", "--", *paths, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return []
    hit = set(r.stdout.split())
    return [p for p in paths if p in hit]


def settings_hooks(repo: pathlib.Path) -> tuple[set[str], str | None]:
    """Hook event names declared in .claude/settings.json, and an error if it is not JSON."""
    p = repo / ".claude" / "settings.json"
    if not p.is_file():
        return set(), None
    try:
        data = json.loads(_read(p) or "{}")
    except ValueError as e:
        return set(), f".claude/settings.json is not valid JSON: {e}"
    hooks = data.get("hooks") if isinstance(data, dict) else None
    return (set(hooks) if isinstance(hooks, dict) else set()), None


def gate_script(repo: pathlib.Path) -> pathlib.Path | None:
    for rel in ("check.sh", "scripts/check.sh"):
        if (repo / rel).is_file():
            return repo / rel
    return None


_NEGATED = re.compile(r"^\s*!|\[\[?\s+!\s|!=|\s-ne\s")  # per clause, `if`/`elif` stripped
_CHAIN = re.compile(r"(&&|\|\||;)")
_QUOTED = re.compile(r'"(?:[^"\\]|\\.)*"|\'[^\']*\'')


def _clauses(text: str) -> tuple[list[str], list[str]]:
    """`a && b || c` → (["a", "b", "c"], ["&&", "||"])."""
    parts = _CHAIN.split(text)
    return [c.strip() for c in parts[0::2]], parts[1::2]


def _is_guard(clause: str, tool_guard: re.Pattern) -> bool:
    return bool(tool_guard.search(clause) or _GENERIC_GUARD.search(clause))


def _enclosing_guard(lines: list[str], i: int, tool_guard: re.Pattern) -> bool:
    """Is line i inside a branch that a guard test makes safe? Walks up from the line, skipping
    blocks that closed before it (`fi` ... `if`), and reads the branch it is in: the `then`
    branch of a positive test is guarded, so is the `else` (or a later `elif`) of a negated one
    (`if ! command -v x; then skip; else x ...`). A step after a completed guarded block is not
    (review of #70, P2)."""
    depth = 0
    holds = True  # does the next condition header up the chain hold on the way to line i?
    for j in range(i - 1, max(-1, i - 16), -1):
        prev = lines[j].strip()
        if re.match(r"if\b.*;\s*fi\b", prev):
            continue  # a whole block on one line: says nothing about line i
        if re.match(r"fi\b", prev):
            depth += 1
        elif re.match(r"if\b", prev):
            if depth:
                depth -= 1
                continue
            if _cond_guards(prev, holds, tool_guard):
                return True
            holds = True  # an outer chain starts fresh
        elif depth == 0 and re.match(r"elif\b", prev):
            if _cond_guards(prev, holds, tool_guard):
                return True
            holds = False  # the earlier tests in this chain failed to get here
        elif depth == 0 and re.match(r"else\b", prev):
            holds = False
    return False


def _cond_guards(cond: str, holds: bool, tool_guard: re.Pattern) -> bool:
    """Does the branch of `if <cond>` — its `then` when `holds`, else its `else` — run only where
    the tool (or the platform) is there? A plain test: the then of a positive one, the else of a
    negated one. A compound test only where the logic forces it: `guard && …` in the then, and
    `! guard || …` in the else (`if ! command -v x || …; then skip; else x`). `if ! command -v x
    && …; then skip; else x` is NOT guarded: the else also runs when the other test fails, x or
    no x (review of #70, P2). Any other mix of &&, || and ; is not guarded."""
    body = re.split(r";\s*then\b", re.sub(r"^\s*(?:el)?if\s+", "", cond), maxsplit=1)[0]
    clauses, ops = _clauses(body)
    guards = [c for c in clauses if _is_guard(c, tool_guard)]
    if not guards:
        return False
    if len(clauses) == 1:
        return holds != bool(_NEGATED.search(clauses[0]))
    if holds and set(ops) == {"&&"}:
        return any(not _NEGATED.search(c) for c in guards)
    if not holds and set(ops) == {"||"}:
        return any(_NEGATED.search(c) for c in guards)
    return False


def _line_guards(line: str, rx: re.Pattern, tool_guard: re.Pattern) -> bool:
    """Is the step on this line guarded by the line itself? A one-line `if …; then …; else …`
    is read like a block; otherwise the step's clause must follow a positive guard through `&&`
    only (`command -v x && x test`), or come straight after `! guard ||`. A line that names the
    tool only in its probe (`if command -v x; then`) is the guard, not a step."""
    step = lambda c: bool(rx.search(_QUOTED.sub('""', c)))  # noqa: E731
    m = re.match(r"\s*(?:el)?if\s+(.*?);\s*then\b(.*)", line)
    if m:
        cond, body = m.group(1), m.group(2)
        then_part, else_part = (re.split(r";\s*else\b", body, maxsplit=1) + [""])[:2]
        if step(then_part):
            return _cond_guards(cond, True, tool_guard)
        if step(else_part):
            return _cond_guards(cond, False, tool_guard)
        return bool(tool_guard.search(cond))
    clauses, ops = _clauses(line)
    k = next((n for n, c in enumerate(clauses) if step(c) and not tool_guard.search(c)), None)
    if k is None:
        return any(tool_guard.search(c) for c in clauses)
    for j in range(k - 1, -1, -1):
        if not _is_guard(clauses[j], tool_guard):
            continue
        between = ops[j:k]
        if not _NEGATED.search(clauses[j]) and all(o == "&&" for o in between):
            return True
        if _NEGATED.search(clauses[j]) and between == ["||"]:
            return True
    return False


def mac_steps(text: str) -> list[dict]:
    """Every non-comment line of a gate script that runs a Mac-only tool, and whether it is
    guarded: the line itself tests for the tool (`command -v swift && swift test`), or an
    `if`/`elif` whose branch it sits in (within 15 lines) tests for the tool, the platform or an
    Xcode directory (see _enclosing_guard, _cond_guards). A heuristic: it reads the shape a skip
    usually has, it does not run the script."""
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        # A tool named inside a quoted string is a message ("no xcodegen here — skipped"), not a
        # step; the guard is still looked for in the whole line.
        bare = _QUOTED.sub('""', line)
        for tool, rx in MAC_STEPS:
            if not rx.search(bare):
                continue
            tool_guard = re.compile(r"(?:command\s+-v|which|type|hash)\s+" + re.escape(tool.split()[0]) + r"\b")
            guarded = _line_guards(line, rx, tool_guard) or _enclosing_guard(lines, i, tool_guard)
            out.append({"tool": tool, "line": i + 1, "guarded": guarded})
    return out


def env_example_names(repo: pathlib.Path) -> list[str]:
    """Variable NAMES in .env.example — values are never read past the `=`."""
    p = repo / ".env.example"
    if not p.is_file():
        return []
    names = []
    for line in _read(p).splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    return names


def visibility(slug: str | None, net: bool = True) -> str | None:
    """"public" | "private" | "internal" from `gh repo view`, or None when it cannot be asked
    (no gh, safe mode, no GitHub origin, or gh failed). None must be read as public."""
    if not (net and slug and gh_usable()):
        return None
    try:
        r = subprocess.run(["gh", "repo", "view", slug, "--json", "visibility", "-q", ".visibility"],
                           capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    v = r.stdout.strip().lower()
    return v if r.returncode == 0 and v in ("public", "private", "internal") else None


# --- the check ------------------------------------------------------------------------

def _item(level, name, detail, fix=None):
    return {"level": level, "name": name, "detail": detail, "fix": fix}


def check_repo(repo, owners: set[str] | None = ..., net: bool = True) -> dict:
    """Readiness of one repo for a cloud session. Every detail is repo-relative: the text is
    meant to be pasteable into a PR."""
    repo = pathlib.Path(repo).expanduser().resolve()
    if owners is ...:
        owners = owner_list()
    slug = origin_slug(repo)
    files = instruction_files(repo)
    text = "\n".join(t for _, t in files)
    has_cloud_section = CLOUD_MARK in text
    items = []

    # 1. instructions at all
    top = [n for n in ("CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md") if (repo / n).is_file() and _inside(repo, repo / n)]
    external = external_instruction_links(repo)
    looped = looped_instruction_links(repo)
    if looped or external:
        why = []
        if looped:
            why.append(f"{', '.join(looped)}: symlink loop; no session can read {'it' if len(looped) == 1 else 'them'}, here or in the cloud")
        if external:
            why.append(f"{', '.join(external)}: symlink(s) out of the repo; the cloud clone has a dangling link, so those rules do not exist there")
        items.append(_item(BLOCK, "instructions", "; ".join(why),
                           "commit the text into the repo (a real AGENTS.md), and keep the link for local sessions only if at all"
                           if not looped else "make AGENTS.md a real file and point CLAUDE.md at it (or import it with @AGENTS.md)"))
    elif not top:
        items.append(_item(BLOCK, "instructions", "no CLAUDE.md or AGENTS.md: a cloud session starts with no instructions",
                           f"teyla cloud prep {repo.name}  (AGENTS.md with the shipping section, CLAUDE.md importing it)"))
    else:
        links = [f"{n} → {os.readlink(repo / n)}" for n in ("CLAUDE.md", "AGENTS.md") if (repo / n).is_symlink()]
        detail = ", ".join(top) + (f" ({', '.join(links)})" if links else "")
        if "CLAUDE.md" not in top and ".claude/CLAUDE.md" not in top:
            items.append(_item(WARN, "instructions", f"{detail}: no CLAUDE.md; Claude Code reads AGENTS.md itself only "
                               "from 2.1.277 and the cloud VM's version is unverified", f"teyla cloud prep {repo.name}  (adds a CLAUDE.md containing @AGENTS.md)"))
        else:
            items.append(_item(OK, "instructions", detail))

    # 2. pointers into the home directory
    pointers, other = [], 0
    for n, t in files:
        ln = _line_numbers(t, _POLICY_POINTER)
        if ln:
            pointers.append(f"{n}:{','.join(map(str, ln[:6]))}")
        other += sum(1 for l in t.splitlines() if _HOME_PATH.search(l) and not _POLICY_POINTER.search(l))
    tail = f"; {other} other line(s) name home-directory paths (local-only tools, logs)" if other else ""
    if pointers:
        lvl = WARN if has_cloud_section else BLOCK
        why = ("the repo carries its own cloud section, but the pointer still dangles there"
               if has_cloud_section else "those rules do not exist in a cloud VM")
        items.append(_item(lvl, "home-refs", f"{'; '.join(pointers)} defer to a home-directory policy file: {why}{tail}",
                           f"teyla cloud prep {repo.name}  (states the rules in the repo; the pointer can stay for local sessions)"))
    else:
        items.append(_item(OK, "home-refs", f"no instruction defers to a home-directory policy file{tail}"))

    # 3. can .claude/ be committed at all
    ignored = claude_ignored(repo)
    if ignored:
        items.append(_item(BLOCK, "gitignore", f"{', '.join(ignored)} git-ignored: repo settings, hooks and rules cannot be committed",
                           f"teyla cloud prep {repo.name} --fix-gitignore  (ignores only .claude/settings.local.json, launch.json, worktrees/)"))
    else:
        items.append(_item(OK, "gitignore", ".claude/settings.json, rules and hooks can be committed"))

    # 4. shipping rules and the cloud definition of done
    missing = [name for name, rx in SHIPPING_RULES if not rx.search(text)]
    if not DONE_STATE.search(text):
        items.append(_item(BLOCK, "shipping", "no cloud definition of done (branch pushed, PR open with the gate's output, "
                           f"`{DONE_STATE_LABEL}` label when a Mac step was skipped)"
                           + (f"; also missing: {', '.join(missing)}" if missing else ""),
                           f"teyla cloud prep {repo.name}  (the Shipping section in AGENTS.md)"))
    elif missing:
        items.append(_item(WARN, "shipping", f"missing in the repo: {', '.join(missing)}", f"teyla cloud prep {repo.name}"))
    else:
        items.append(_item(OK, "shipping", "PR per unit, merge-not-squash, no force-push and a done state are in the repo"))

    # 5. hooks: orientation at start, landing check at stop
    events, err = settings_hooks(repo)
    if err:
        items.append(_item(WARN, "hooks", err, "fix the JSON; a cloud session ignores the whole file"))
    else:
        lack = [(e, w) for e, w in (("SessionStart", "orientation"), ("Stop", "landing check")) if e not in events]
        if lack:
            items.append(_item(WARN, "hooks", "no " + " and no ".join(f"{e} hook ({w})" for e, w in lack) + " in .claude/settings.json",
                               f"teyla cloud prep {repo.name}  (orientation at start, a Stop hook that blocks until the PR is open)"))
        else:
            items.append(_item(OK, "hooks", "SessionStart and Stop hooks in .claude/settings.json"))

    # 6. merge-approved, derived from the owner's list
    want = expected_merge_approved(slug, owners)
    have = declared_merge_approved(files)
    if want is None:
        why = "no GitHub origin" if slug is None else "the owner's list was not found"
        items.append(_item(INFO, "merge-approved", f"not checked: {why}" + (f" (repo says {'/'.join(sorted(have))})" if have else "")))
    elif not have:
        items.append(_item(WARN, "merge-approved", f"no `merge-approved:` line; the owner's list says {want}",
                           f"teyla cloud prep {repo.name}  (writes `merge-approved: {want}`)"))
    elif have != {want}:
        items.append(_item(BLOCK, "merge-approved", f"drift: the repo says {'/'.join(sorted(have))}, the owner's list says {want}",
                           f"teyla cloud prep {repo.name}  (rewrites it to `merge-approved: {want}`; the owner's list is the source)"))
    else:
        items.append(_item(OK, "merge-approved", f"`merge-approved: {want}` matches the owner's list"))

    # 7. the gate, and what of it needs a Mac
    gate = gate_script(repo)
    if gate is None:
        items.append(_item(WARN, "gate", "no check.sh: a cloud session has no command that proves its work",
                           "a ./check.sh that runs what Linux can run and prints a skip for the rest"))
    else:
        gtext = _read(gate)
        rel = str(gate.relative_to(repo))
        steps = mac_steps(gtext)
        bare = [s for s in steps if not s["guarded"]]
        tools = sorted({s["tool"] for s in steps})
        if bare:
            items.append(_item(WARN, "gate", f"{rel}: Mac-only step(s) with no guard, which fail on Linux: "
                               + ", ".join(f"{s['tool']} (line {s['line']})" for s in bare[:6]),
                               "guard each with `command -v <tool>` and print a skip naming it"))
        elif steps and not _SKIP_PRINT.search(gtext):
            items.append(_item(WARN, "gate", f"{rel}: Mac-only steps ({', '.join(tools)}) are guarded but no skip is printed",
                               "print `skipped here: <step> (no Mac)` so the PR says what did not run"))
        else:
            items.append(_item(OK, "gate", f"{rel}" + (f"; Mac-only steps guarded with a printed skip: {', '.join(tools)}" if tools else "; nothing Mac-only")))

    # 8. secrets a session would need, by name
    names = env_example_names(repo)
    if names:
        manifest = _read(repo / SECRETS_MANIFEST)
        unlisted = [n for n in names if n not in manifest]
        if unlisted:
            items.append(_item(WARN, "secrets", f".env.example names {len(names)} variable(s); {len(unlisted)} not in {SECRETS_MANIFEST}: "
                               + ", ".join(unlisted[:8]) + ("…" if len(unlisted) > 8 else ""),
                               f"teyla cloud prep {repo.name}  (lists each name in {SECRETS_MANIFEST} with where it goes)"))
        else:
            items.append(_item(OK, "secrets", f"all {len(names)} .env.example name(s) are in {SECRETS_MANIFEST}"))

    # 9. visibility (network; doctor skips it)
    if net:
        vis = visibility(slug, net=net)
        if vis == "public":
            items.append(_item(WARN, "visibility", "public: everything a cloud setup writes into this repo is world-readable",
                               "keep personal paths, lists and metrics out of generated files"))
        elif vis is None:
            items.append(_item(INFO, "visibility", "unknown (no gh, safe mode, or no GitHub origin): treated as public"))
        else:
            items.append(_item(OK, "visibility", vis))

    # 10. the pre-push gate is local config
    if (repo / ".githooks").is_dir():
        items.append(_item(INFO, "githooks", ".githooks/ is wired by core.hooksPath, which is local config: in the cloud the gate runs only when the session runs it"))

    scored = [i for i in items if i["level"] != INFO]
    n_ok = sum(1 for i in scored if i["level"] == OK)
    return {"repo": repo.name, "slug": slug, "ready": not any(i["level"] == BLOCK for i in items),
            "score": f"{n_ok}/{len(scored)}", "items": items}


def discover_repos(cfg: dict | None = None) -> list[pathlib.Path]:
    root = config.code_root(cfg)
    if not root.is_dir():
        return []
    return [d for d in sorted(root.iterdir()) if d.is_dir() and (d / ".git").exists()]


def check_all(paths: list[str] | None = None, net: bool = True) -> list[dict]:
    repos = [pathlib.Path(p).expanduser() for p in paths] if paths else discover_repos()
    owners = owner_list()
    return [check_repo(r, owners=owners, net=net) for r in repos]


def render_check(reports: list[dict]) -> str:
    L = []
    for r in reports:
        L.append(f"{r['repo']}  {'ready' if r['ready'] else 'NOT READY'}  score {r['score']}")
        for i in r["items"]:
            L.append(f"  {i['level']:5} {i['name']:15} {i['detail']}")
            if i["fix"] and i["level"] in (BLOCK, WARN):
                L.append(f"  {'':5} {'':15} → {i['fix']}")
        L.append("")
    n = sum(1 for r in reports if r["ready"])
    L.append(f"cloud-ready {n}/{len(reports)} repos")
    return "\n".join(L)


def doctor_check(cfg: dict | None = None) -> dict:
    """One doctor line. No network (visibility is skipped) and no subprocess beyond one
    `git check-ignore` per path: doctor runs at every session start."""
    repos = discover_repos(cfg)
    if not repos:
        return {"level": INFO, "name": "cloud", "detail": "no git repos under code_root", "fix": None}
    owners = owner_list()
    reports = [check_repo(r, owners=owners, net=False) for r in repos]
    not_ready = [r["repo"] for r in reports if not r["ready"]]
    n = len(reports) - len(not_ready)
    detail = f"cloud-ready {n}/{len(reports)} repos" + (f"; not ready: {', '.join(not_ready[:6])}{'…' if len(not_ready) > 6 else ''}" if not_ready else "")
    return {"level": INFO, "name": "cloud", "detail": detail, "fix": "teyla cloud check" if not_ready else None}


# --- cloud sessions, from git --------------------------------------------------------

_SESSION = re.compile(r"https://claude\.ai/code/(session_[A-Za-z0-9]+)")


def default_ref(repo: pathlib.Path) -> str:
    try:
        r = _git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD", timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    for cand in ("origin/main", "origin/master", "main", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", cand, timeout=5).returncode == 0:
            return cand
    return "origin/main"


def _short_ref(ref: str) -> str:
    for pre in ("refs/remotes/origin/", "refs/heads/", "refs/remotes/", "origin/"):
        if ref.startswith(pre):
            return ref[len(pre):]
    return ref


def _pick_branch(repo: pathlib.Path, tip: str, refs: list[str], default: str) -> str | None:
    """The branch a cloud session's newest commit belongs to, among the refs that contain it. A
    later branch cut from the session's branch contains it too, and the alphabetical first used
    to win (review of #70, P2). Now: a `claude/*` branch first, then the one whose tip is fewest
    commits past the commit (its own branch is 0), then the name — deterministic. Local and
    remote-tracking refs of one name count once, at the nearer tip. The `Claude-Session:`
    trailer carries no branch name, so it cannot break the tie."""
    dist: dict[str, int] = {}
    for ref in refs:
        s = _short_ref(ref)
        if s in ("HEAD", _short_ref(default)) or s.endswith("/HEAD"):
            continue
        try:
            r = _git(repo, "rev-list", "--count", f"{tip}..{ref}", timeout=10)
            d = int(r.stdout.strip()) if r.returncode == 0 else 1 << 30
        except (OSError, subprocess.SubprocessError, ValueError):
            d = 1 << 30
        dist[s] = min(dist.get(s, d), d)
    if not dist:
        return None
    return min(dist, key=lambda n: (not n.startswith("claude/"), dist[n], n))


def repo_sessions(repo: pathlib.Path, days: int | None = None) -> list[dict]:
    """Cloud sessions whose commits are reachable from any ref (local or remote-tracking)."""
    fmt = "%x1e%H%x1f%cI%x1f%(trailers:key=Claude-Session,valueonly,separator=%x2c)"
    args = ["log", "--all", "--grep=Claude-Session: https://claude.ai/code/session_", f"--format={fmt}"]
    if days:
        args.append(f"--since={int(days)}.days")
    try:
        r = _git(repo, *args, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    by: dict[str, dict] = {}
    for rec in r.stdout.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 3:
            continue
        sha, when, trailer = parts[0], parts[1], parts[2]
        m = _SESSION.search(trailer)
        if not m:
            continue
        s = by.setdefault(m.group(1), {"session": m.group(1), "shas": [], "first": when, "last": when})
        s["shas"].append(sha)
        s["first"] = min(s["first"], when)
        s["last"] = max(s["last"], when)
    if not by:
        return []
    default = default_ref(repo)
    # Landed means contained in exactly the default ref (origin/main), never a local `main` of
    # the same short name that was merged and not pushed (review of #70, P2).
    full = _git(repo, "rev-parse", "--symbolic-full-name", default, timeout=5)
    default_full = full.stdout.strip() if full.returncode == 0 else ""
    # default_ref() falls back to a local main when no remote default resolves; that is no
    # evidence of landing, so only a remote-tracking ref counts (review, P2).
    if not default_full.startswith("refs/remotes/"):
        default_full = ""
    slug = origin_slug(repo)
    out = []
    for s in by.values():
        tip = s["shas"][0]  # git log is newest first
        refs = _git(repo, "for-each-ref", "--contains", tip, "--format=%(refname)", "refs/heads", "refs/remotes", timeout=10).stdout.split()
        landed = bool(default_full) and default_full in refs
        branch = _pick_branch(repo, tip, refs, default)
        out.append({"repo": repo.name, "path": str(repo), "slug": slug, "session": s["session"],
                    "branch": branch or (_short_ref(default) if landed else None), "commits": len(s["shas"]),
                    "first": s["first"], "last": s["last"], "landed": landed,
                    "pr": "landed" if landed else "unknown", "pr_url": None, "labels": []})
    return out


def pr_for_branch(slug: str, branch: str) -> dict:
    """{"pr": open|merged|closed|none|unknown, "pr_url", "labels"} for the newest PR whose head is
    `branch`. Only called when gh is usable; any failure is "unknown", never "none"."""
    try:
        r = subprocess.run(["gh", "pr", "list", "--repo", slug, "--head", branch, "--state", "all",
                            "--json", "number,state,url,labels", "--limit", "5"], capture_output=True, text=True, timeout=30)
        rows = json.loads(r.stdout or "null") if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        rows = None
    if rows is None:
        return {"pr": "unknown", "pr_url": None, "labels": []}
    if not rows:
        return {"pr": "none", "pr_url": None, "labels": []}
    row = max(rows, key=lambda x: x.get("number", 0))
    return {"pr": (row.get("state") or "unknown").lower(), "pr_url": row.get("url"),
            "labels": [l.get("name") for l in row.get("labels") or [] if l.get("name")]}


def scan_sessions(repos: list[pathlib.Path] | None = None, days: int | None = None, gh: bool | None = None,
                  now: _dt.datetime | None = None) -> list[dict]:
    """Every cloud session in the repos (default: every git repo under code_root), newest first,
    with the PR state of its branch when gh may be asked (not in safe mode, gh on PATH)."""
    repos = repos if repos is not None else discover_repos()
    gh = gh_usable() if gh is None else gh
    now = now or _dt.datetime.now(_dt.timezone.utc)
    out = []
    for repo in repos:
        out += repo_sessions(pathlib.Path(repo), days)
    for s in out:
        last = _dt.datetime.fromisoformat(s["last"].replace("Z", "+00:00"))
        s["age_hours"] = round((now - last).total_seconds() / 3600, 1)
    ask = [s for s in out if not s["landed"] and s["branch"] and s["slug"]] if gh else []
    if ask:
        with _cf.ThreadPoolExecutor(max_workers=8) as ex:
            for s, res in zip(ask, ex.map(lambda s: pr_for_branch(s["slug"], s["branch"]), ask)):
                s.update(res)
    return sorted(out, key=lambda s: s["last"], reverse=True)


def stuck(sessions: list[dict], hours: float = 24) -> list[dict]:
    """Cloud branches with commits, not on the default branch, known to have no PR, older than
    `hours`. "unknown" does not count: a finding must trace to a fact."""
    return [s for s in sessions if not s["landed"] and s["pr"] == "none" and s["branch"] and s["age_hours"] >= hours]


def open_pr_command(s: dict) -> str:
    return f"gh pr create --repo {s['slug']} --head {s['branch']} --fill" if s.get("slug") else f"cd {s['repo']} && gh pr create --head {s['branch']} --fill"


def _age(h: float) -> str:
    return f"{h:.0f}h ago" if h < 48 else f"{h / 24:.0f}d ago"


def render_sessions_md(sessions: list[dict]) -> list[str]:
    """The monitor's "Cloud sessions" section."""
    if not sessions:
        return []
    L = ["", "## Cloud sessions", "",
         "From `Claude-Session:` commit trailers in every repo (local and remote-tracking refs).", "",
         "| repo | branch | session | commits | last commit | PR |", "|---|---|---|---|---|---|"]
    for s in sessions:
        L.append(f"| {s['repo']} | {s['branch'] or '?'} | {s['session'][:16]} | {s['commits']} | {s['last'][:10]} ({_age(s['age_hours'])}) | {s['pr']} |")
    return L


def needs_mac_prs(slugs: list[str]) -> tuple[list[dict], list[str]]:
    """Open PRs labelled needs-mac, per repo, in parallel. Returns (rows, repos gh failed for)."""
    def one(slug):
        try:
            r = subprocess.run(["gh", "pr", "list", "--repo", slug, "--label", DONE_STATE_LABEL, "--state", "open",
                                "--json", "number,title,url,headRefName"], capture_output=True, text=True, timeout=30)
            return slug, (json.loads(r.stdout or "[]") if r.returncode == 0 else None)
        except (OSError, subprocess.SubprocessError, ValueError):
            return slug, None
    rows, failed = [], []
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        for slug, res in ex.map(one, slugs):
            if res is None:
                failed.append(slug)
            else:
                rows += [dict(x, slug=slug) for x in res]
    return rows, failed


def inbox(days: int = 14, repos: list[pathlib.Path] | None = None, gh: bool | None = None) -> dict:
    repos = repos if repos is not None else discover_repos()
    gh = gh_usable() if gh is None else gh
    sessions = scan_sessions(repos, days=days, gh=gh)
    unlanded = [s for s in sessions if not s["landed"] and s["pr"] in ("none", "unknown")]
    slugs = sorted({origin_slug(pathlib.Path(r)) for r in repos} - {None})
    prs, failed = needs_mac_prs(slugs) if gh else ([], [])
    return {"days": days, "gh": gh, "no_pr": unlanded, "needs_mac": prs, "gh_failed": failed}


def render_inbox(box: dict) -> str:
    L = [f"Cloud branches without a PR ({'last ' + str(box['days']) + ' days' if box['days'] else 'all history'}, local refs — `git fetch` refreshes them):"]
    if not box["no_pr"]:
        L.append("  none")
    for s in box["no_pr"]:
        state = "no PR" if s["pr"] == "none" else "PR unknown"
        L.append(f"  {s['repo']:14} {s['branch'] or '?'}  {s['commits']} commit(s), {_age(s['age_hours'])}, {state}")
        L.append(f"  {'':14} → {open_pr_command(s)}")
    L += ["", f"Open PRs labelled {DONE_STATE_LABEL} (the Mac half a local session finishes):"]
    if not box["gh"]:
        L.append("  not asked: gh is absent or safe mode is on")
    elif not box["needs_mac"]:
        L.append("  none")
    for p in box["needs_mac"]:
        L.append(f"  {p['slug']}#{p['number']}  {p['title'][:70]}  ({p['headRefName']})")
        L.append(f"  {'':14} → {p['url']}")
    if box["gh_failed"]:
        L.append(f"  gh failed for: {', '.join(box['gh_failed'])}")
    return "\n".join(L)


# --- CLI -----------------------------------------------------------------------------

def cmd_cloud(args):
    if args.action == "check":
        reports = check_all(args.paths or None, net=not args.no_net)
        print(json.dumps(reports, indent=2) if args.json else render_check(reports))
        return 1 if any(not r["ready"] for r in reports) else 0
    if args.action == "prep":
        from . import cloud_prep
        return cloud_prep.cmd_prep(args)
    if args.action == "inbox":
        box = inbox(days=args.days or 14, repos=[pathlib.Path(p).expanduser() for p in args.paths] if args.paths else None)
        print(json.dumps(box, indent=2) if args.json else render_inbox(box))
        return 0
    return 2


def register(sp):
    q = sp.add_parser("cloud", help="cloud sessions: readiness per repo (check), what they left behind (inbox), the files a repo needs (prep)")
    q.set_defaults(fn=cmd_cloud)
    q.add_argument("action", choices=["check", "inbox", "prep"])
    q.add_argument("paths", nargs="*", help="repos (default: every git repo under code_root)")
    q.add_argument("--json", action="store_true")
    q.add_argument("--days", type=int, help="inbox: how far back to look for cloud commits (default 14)")
    q.add_argument("--no-net", action="store_true", help="check: do not ask gh for the repo's visibility")
    q.add_argument("--dry", action="store_true", help="prep: print a unified diff of every file, write nothing")
    q.add_argument("--allow-public", action="store_true", help="prep: write into a public repo (or one whose visibility gh cannot tell)")
    q.add_argument("--fix-gitignore", action="store_true", help="prep: replace a wholesale `.claude/` ignore with the three narrow lines")

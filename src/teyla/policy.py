"""The shared operating policy: one file, wired into every harness.

    ~/.agents/POLICY.md                 the source of truth (template in templates/POLICY.md)
    ~/.claude/CLAUDE.md                 gets an `@~/.agents/POLICY.md` import line
    ~/.codex/AGENTS.md                  symlink → POLICY.md        (Codex global instructions)
    ~/.grok/AGENTS.md                   symlink → POLICY.md        (Grok CLI global rules)
    ~/.hermes/SOUL.md                   gets a short "Operating policy" section (Hermes injects SOUL.md)
    <repo>/AGENTS.md                    symlink → CLAUDE.md when only CLAUDE.md exists (Cursor, Zed, Hermes, Grok, Codex read AGENTS.md)
"""
from __future__ import annotations

import os
import pathlib

HOME = pathlib.Path.home()
POLICY = HOME / ".agents" / "POLICY.md"
TEMPLATE = __import__("teyla").templates_dir() / "POLICY.md"
IMPORT_LINE = "@~/.agents/POLICY.md"
HERMES_MARK = "## Operating policy"
HERMES_BLOCK = f"""

{HERMES_MARK}
Follow ~/.agents/POLICY.md — read it at session start. Short form: the most capable model orchestrates and cheaper models do volume work; get a cross-provider second opinion before non-trivial designs; use connectors before CLIs before browser before computer use; ask about product decisions with a proposed default, never ask for permission to proceed; stop only at a real blocker (a key, a payment, a sign-in) and then open the exact page and name the exact file; deliver plug-and-play (README, setup, .env.example, first-run check); say when something is unverified.
"""

TARGETS = {
    "claude-code": HOME / ".claude" / "CLAUDE.md",
    "codex": HOME / ".codex" / "AGENTS.md",
    "grok": HOME / ".grok" / "AGENTS.md",
    "hermes": HOME / ".hermes" / "SOUL.md",
}


def init(force=False, owner: str | None = None, dry: bool = False) -> str:
    """Write ~/.agents/POLICY.md from the template, with {{owner}} filled in (defaults to the
    login name). `dry` reports what would happen and touches nothing on disk — not even
    ~/.agents/ itself."""
    import getpass
    if POLICY.exists() and not force:
        return f"exists: {POLICY}"
    if dry:
        return f"would write {POLICY}"
    POLICY.parent.mkdir(parents=True, exist_ok=True)
    text = TEMPLATE.read_text().replace("{{owner}}", owner or getpass.getuser())
    POLICY.write_text(text)
    return f"wrote {POLICY}"


def status() -> dict:
    """harness -> True/False/None (None = harness not installed)."""
    st = {}
    st["policy-file"] = POLICY.exists()
    p = TARGETS["claude-code"]
    st["claude-code"] = (IMPORT_LINE in p.read_text()) if p.exists() else None
    for h in ("codex", "grok"):
        p = TARGETS[h]
        st[h] = (p.resolve() == POLICY.resolve()) if p.exists() else (None if not p.parent.exists() else False)
    p = TARGETS["hermes"]
    st["hermes"] = (HERMES_MARK in p.read_text()) if p.exists() else None
    return st


def sync(dry=False, owner: str | None = None) -> list[str]:
    done = []
    if not POLICY.exists():
        done.append(init(owner=owner, dry=dry))
    p = TARGETS["claude-code"]
    if p.exists() and IMPORT_LINE not in p.read_text():
        if not dry:
            p.write_text(p.read_text().rstrip() + f"\n\n## How to run a session\n\n{IMPORT_LINE}\n")
        done.append(f"added import to {p}")
    for h in ("codex", "grok"):
        p = TARGETS[h]
        if p.parent.exists() and not (p.exists() and p.resolve() == POLICY.resolve()):
            if p.exists() and not p.is_symlink():
                done.append(f"SKIP {p}: a real file exists; merge by hand or delete it")
                continue
            if not dry:
                if p.is_symlink():
                    p.unlink()
                p.symlink_to(POLICY)
            done.append(f"symlinked {p} → {POLICY}")
    p = TARGETS["hermes"]
    if p.exists() and HERMES_MARK not in p.read_text():
        if not dry:
            p.write_text(p.read_text().rstrip() + HERMES_BLOCK)
        done.append(f"appended policy section to {p}")
    return done or ["already in sync"]


def sync_repo(repo: str, dry=False, prefer: str | None = None) -> str:
    """Give a repo an AGENTS.md if it only has CLAUDE.md (or vice versa).

    If both exist as real (non-symlink) files, this refuses by default — they may be
    deliberately different documents — and prints a one-line summary of how much they differ.
    Only `prefer` ("agents" or "claude") authorizes collapsing them: the losing file is copied
    to `<name>.md.bak` first, then replaced with a symlink to the winner."""
    r = pathlib.Path(repo).expanduser()
    a, c = r / "AGENTS.md", r / "CLAUDE.md"

    if a.exists() and c.exists():
        if a.is_symlink() or c.is_symlink():
            return f"{r.name}: already linked"
        a_lines, c_lines = a.read_text().splitlines(), c.read_text().splitlines()
        if a_lines == c_lines:
            if not dry:
                c.unlink()
                c.symlink_to("AGENTS.md")
            return f"{r.name}: both exist and are identical — {'would link' if dry else 'linked'} CLAUDE.md → AGENTS.md"
        only_a = len(set(a_lines) - set(c_lines))
        only_c = len(set(c_lines) - set(a_lines))
        if prefer not in ("agents", "claude"):
            return (f"{r.name}: both exist and differ: {only_a} lines only in AGENTS.md, {only_c} only in "
                     f"CLAUDE.md — merge by hand, or `--prefer agents|claude` to keep one and link the other")
        keep, lose = (a, c) if prefer == "agents" else (c, a)
        bak = lose.with_name(lose.name + ".bak")
        if dry:
            return f"{r.name}: would keep {keep.name}; would back up {lose.name} → {bak.name}; would link {lose.name} → {keep.name}"
        bak.write_text(lose.read_text())
        lose.unlink()
        lose.symlink_to(keep.name)
        return f"{r.name}: kept {keep.name}; backed up {lose.name} → {bak.name}; linked {lose.name} → {keep.name}"
    if c.exists():
        if not dry:
            os.symlink("CLAUDE.md", a)
        return f"{r.name}: AGENTS.md → CLAUDE.md"
    if a.exists():
        if not dry:
            os.symlink("AGENTS.md", c)
        return f"{r.name}: CLAUDE.md → AGENTS.md"
    return f"{r.name}: neither exists — run `teyla scaffold` first"


CLAUDE_GLOBAL = HOME / ".claude" / "CLAUDE.md"


def init_claude_md(owner: str | None = None, merge_rule: str | None = None, code_root: str = "~/repos",
                   ops_root: str = "~/ops", force: bool = False, dry: bool = False) -> str:
    """Write ~/.claude/CLAUDE.md from templates/CLAUDE.global.md if it does not exist (or --force).
    `dry` reports what would happen and writes nothing."""
    import getpass
    if CLAUDE_GLOBAL.exists() and not force:
        return f"exists: {CLAUDE_GLOBAL} (use --force to overwrite; the @POLICY import is added by sync)"
    if dry:
        return f"would write {CLAUDE_GLOBAL}"
    tpl = (__import__("teyla").templates_dir() / "CLAUDE.global.md").read_text()
    text = (tpl.replace("{{owner}}", owner or getpass.getuser())
               .replace("{{merge_rule}}", merge_rule or "Open the PR/MR, then stop and tell me. I merge it, or I tell you to. No exceptions.")
               .replace("{{code_root}}", code_root).replace("{{ops_root}}", ops_root))
    CLAUDE_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_GLOBAL.write_text(text)
    return f"wrote {CLAUDE_GLOBAL}"


def init_ops_root(path: str, owner: str | None = None, code_root: str = "~/repos", dry: bool = False) -> list[str]:
    """Create an ops root: CLAUDE.md (+AGENTS.md link), .claude/{skills,rules}, wiki/, runs gitignore.
    `dry` reports what would be created/written and touches nothing on disk."""
    import getpass, os
    root = pathlib.Path(path).expanduser()
    done = []
    if not root.exists():
        if dry:
            done.append(f"would create {root}")
        else:
            root.mkdir(parents=True, exist_ok=True)
    c = root / "CLAUDE.md"
    if not c.exists():
        if dry:
            done.append(f"would write {c}")
        else:
            tpl = (__import__("teyla").templates_dir() / "ops" / "CLAUDE.md").read_text()
            c.write_text(tpl.replace("{{owner}}", owner or getpass.getuser()).replace("{{code_root}}", code_root))
            done.append(f"wrote {c}")
    a = root / "AGENTS.md"
    if not a.exists():
        if dry:
            done.append(f"would link {a} -> CLAUDE.md")
        else:
            os.symlink("CLAUDE.md", a); done.append(f"linked {a}")
    for d in (".claude/skills", ".claude/rules", "runs"):
        dp = root / d
        if not dp.exists():
            if dry:
                done.append(f"would create {dp}")
            else:
                dp.mkdir(parents=True, exist_ok=True)
    gi = root / ".gitignore"
    if not gi.exists() or "runs/" not in gi.read_text():
        if dry:
            done.append(f"would update {gi}")
        else:
            gi.write_text((gi.read_text() if gi.exists() else "") + "runs/\n.env\n.teyla/corrections.jsonl\n"); done.append(f"gitignore: runs/ in {gi}")
    rr = root / ".claude" / "rules" / "README.md"
    if not rr.exists():
        if dry:
            done.append(f"would write {rr}")
        else:
            rr.write_text("# Rules\n\nOne file per rule cluster, frontmatter `globs:` scopes it. A rule is one or two sentences born from a correction; `/teyla:rule` writes one here.\n"); done.append(f"wrote {rr}")
    return done or ["already initialised"]


ACK_PATH = HOME / ".teyla" / "ack.json"


def ack(note: str | None = None) -> str:
    """Record sha256 of ~/.claude/CLAUDE.md and today's date into ~/.teyla/ack.json — the human's
    acknowledgement that they accepted whatever that file currently says. This is how an
    intentional edit (e.g. `teyla policy init --claude-md`, run because a kickoff asked for it)
    stops looking like an unauthorized one: advise.py's A10 can compare the file's current hash
    against this record instead of firing on every edit forever."""
    import datetime as _dt
    import hashlib
    import json
    digest = hashlib.sha256(CLAUDE_GLOBAL.read_bytes()).hexdigest() if CLAUDE_GLOBAL.exists() else None
    today = _dt.date.today().isoformat()
    record = {"claude_md": {"sha256": digest, "date": today}}
    if note:
        record["claude_md"]["note"] = note
    ACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACK_PATH.write_text(json.dumps(record, indent=2) + "\n")
    detail = f"sha256={digest} date={today}" + (f" note={note!r}" if note else "")
    return f"recorded {CLAUDE_GLOBAL} -> {ACK_PATH}: {detail}"

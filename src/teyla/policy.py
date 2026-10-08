"""The shared operating policy: one file, wired into every harness.

    ~/.agents/POLICY.md                 the source of truth (template in templates/POLICY.md, or
                                        templates/POLICY.work.md with `teyla policy init --work`)
    ~/.claude/CLAUDE.md                 gets an `@~/.agents/POLICY.md` import line
    ~/.codex/AGENTS.md                  generated: POLICY.md + the owner's rules (Codex global instructions)
    ~/.grok/AGENTS.md                   generated: POLICY.md + the owner's rules (Grok CLI global rules)
                                        — or a symlink → POLICY.md while ~/.claude/CLAUDE.md holds
                                        nothing but the import line
    ~/.hermes/SOUL.md                   gets a short "Operating policy" section (Hermes injects SOUL.md)
    ~/.cursor/skills/teyla-policy/SKILL.md   a user-level skill carrying the same text as AGENTS.md
                                        (Cursor has no global rules file; skills under ~/.cursor/skills
                                        load in every project — Cursor 3.19.7 create-skill/SKILL.md)
    <repo>/AGENTS.md                    symlink → CLAUDE.md when only CLAUDE.md exists (Cursor, Zed, Hermes, Grok, Codex read AGENTS.md)

Why AGENTS.md is generated rather than a symlink: the owner's own rules — which repos may be
merged into without asking, how releases are cut, the layout, git safety — live in
~/.claude/CLAUDE.md, and Claude Code is the only harness that reads it. Codex has no `@path`
imports (codex-cli 0.159.2: an `@extra.md` line in $CODEX_HOME/AGENTS.md reaches the model as
the literal line), so a symlink to POLICY.md left every Codex session without the merge list.
The generated file is POLICY.md, then CLAUDE.md with the policy import dropped and any other
`@~/...` import inlined one level, then where the shared project memory lives. Its first line is
a generated-by marker: sync replaces a file carrying it, and never one without it.

Edits made inside a generated copy are kept, not lost. Every time sync writes a copy (or the
Hermes section) it records the sha256 of exactly what it wrote in ~/.teyla/state/policy-written.json,
with a copy of the text. The next sync that is about to overwrite a copy whose hash no longer
matches first files the difference (lines added and removed since the last write) in
~/.teyla/policy-inbox/<harness>-<date-time>.md, then overwrites as before. `teyla policy inbox`
lists those files; the person moves what should stay into ~/.agents/POLICY.md or
~/.claude/CLAUDE.md (the sources) and marks the file done. Without a record (the first sync after
an upgrade) the copy is compared with what sync would write now.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import json
import os
import pathlib
import re

HOME = pathlib.Path.home()
POLICY = HOME / ".agents" / "POLICY.md"
TEMPLATE = __import__("teyla").templates_dir() / "POLICY.md"
# The work variant: no cross-provider review and no `grok -p` volume worker, because on a work
# laptop both send the employer's code to a vendor IT never approved. A POLICY.md says which
# variant it is by the marker line, so `refresh` keeps merging from the template it came from.
TEMPLATE_WORK = __import__("teyla").templates_dir() / "POLICY.work.md"
WORK_MARKER = "<!-- teyla-template: work"
IMPORT_LINE = "@~/.agents/POLICY.md"
HERMES_MARK = "## Operating policy"
HERMES_BLOCK = f"""

{HERMES_MARK}
Follow ~/.agents/POLICY.md — read it at session start. Short form: the most capable model orchestrates and cheaper models do volume work; get a cross-provider second opinion before non-trivial designs; use connectors before CLIs before browser before computer use; ask about product decisions with a proposed default, never ask for permission to proceed; stop only at a real blocker (a key, a payment, a sign-in) and then open the exact page and name the exact file; deliver plug-and-play (README, setup, .env.example, first-run check); say when something is unverified.
"""
HERMES_BLOCK_WORK = HERMES_BLOCK.replace(
    "get a cross-provider second opinion before non-trivial designs",
    "get a second opinion from a fresh same-provider session before non-trivial designs; send code only to providers IT approved")


def hermes_block() -> str:
    """The section SOUL.md should carry for the installed policy's variant."""
    return HERMES_BLOCK_WORK if is_work() else HERMES_BLOCK


def _hermes_section(text: str) -> tuple[int, int] | None:
    """(start, end) of Teyla's managed section in SOUL.md: from the HERMES_MARK heading to the
    next `## ` heading or the end of the file, blank lines before it included."""
    at = text.find(HERMES_MARK)
    if at < 0:
        return None
    start = len(text[:at].rstrip("\n"))
    nxt = text.find("\n## ", at + len(HERMES_MARK))
    return start, (nxt + 1 if nxt >= 0 else len(text))


def _hermes_current(text: str) -> bool:
    span = _hermes_section(text)
    return span is not None and text[span[0]:span[1]].strip() == hermes_block().strip()


def is_work(text: str | None = None) -> bool:
    """Whether this POLICY.md text (default: the installed file) came from the work template."""
    if text is None:
        text = POLICY.read_text() if POLICY.exists() else ""
    return WORK_MARKER in text


def template_path(work: bool = False) -> pathlib.Path:
    return TEMPLATE_WORK if work else TEMPLATE


def _guard(text: str, path) -> str:
    """`text`, unless it holds an invisible or bidi character — then InvisibleText, before the
    write (invisible.py: every harness obeys these files and a person reviews them rendered)."""
    from . import invisible
    invisible.check(text, str(path))
    return text

TARGETS = {
    "claude-code": HOME / ".claude" / "CLAUDE.md",
    "codex": HOME / ".codex" / "AGENTS.md",
    "grok": HOME / ".grok" / "AGENTS.md",
    "hermes": HOME / ".hermes" / "SOUL.md",
    "cursor": HOME / ".cursor" / "skills" / "teyla-policy" / "SKILL.md",
}
CURSOR_HEAD = """---
name: teyla-policy
description: The operating policy for every session — model ladder, second opinions, tool ladder, when to ask, when to stop, plug-and-play, merging, honest reporting, "did it run?". Read it before starting any task; it is what AGENTS.md means by "the policy".
disable-model-invocation: false
---

<!-- generated by `teyla policy sync` from ~/.agents/POLICY.md — edit the source, not this copy -->

"""


def cursor_skill_text() -> str:
    return CURSOR_HEAD + combined_text()


def init(force=False, owner: str | None = None, dry: bool = False, work: bool = False) -> str:
    """Write ~/.agents/POLICY.md from the template (`work`: the work variant), with {{owner}}
    filled in (defaults to the login name). `dry` reports what would happen and touches nothing
    on disk — not even ~/.agents/ itself. --force over an existing file keeps a dated backup."""
    if POLICY.exists() and not force:
        if work and not is_work():
            return (f"exists: {POLICY} (from the home template: it sends diffs to other providers) — "
                    f"`teyla policy init --work --force` replaces it with the work template, keeping a dated backup")
        return f"exists: {POLICY}"
    if dry:
        return f"would write {POLICY}" + (" from the work template" if work else "")
    if POLICY.exists():
        _backup_policy()
    POLICY.parent.mkdir(parents=True, exist_ok=True)
    POLICY.write_text(_guard(render_template(owner, work=work), POLICY))
    return f"wrote {POLICY}" + (" from the work template" if work else "")


def _disabled() -> list[str]:
    """Harnesses `[harness] disabled` in config.toml leaves alone (status, sync and drift skip them)."""
    from . import config
    return config.disabled_harnesses()[0]


def status() -> dict:
    """harness -> True/False/None (None = harness not installed). A harness listed in
    `[harness] disabled` is left out altogether."""
    st = {}
    off = _disabled()
    st["policy-file"] = POLICY.exists()
    p = TARGETS["claude-code"]
    if "claude-code" not in off:
        st["claude-code"] = (IMPORT_LINE in p.read_text()) if p.exists() else None
    want = agents_text() if POLICY.exists() else None
    for h in ("codex", "grok"):
        if h in off:
            continue
        p = TARGETS[h]
        if not p.exists():
            st[h] = None if not p.parent.exists() else False
        elif want is None:
            st[h] = p.resolve() == POLICY.resolve()
        else:
            st[h] = not p.is_symlink() and p.read_text() == want
    p = TARGETS["hermes"]
    # Current, not merely present: after `policy init --work --force` a home-variant section
    # still tells Hermes to send diffs to another provider (Codex review, P1).
    if "hermes" not in off:
        st["hermes"] = _hermes_current(p.read_text()) if p.exists() else None
    p = TARGETS.get("cursor")
    if p is not None and "cursor" not in off:  # tests patch TARGETS without it
        if not p.parents[2].is_dir():
            st["cursor"] = None
        else:
            st["cursor"] = bool(POLICY.exists() and p.exists() and p.read_text() == cursor_skill_text())
    return {k: v for k, v in st.items() if k not in off}


# ---------------------------------------------------------------------------
# Fingerprints and hand edits. What sync writes is hashed (and its text kept beside the hash);
# a copy that no longer matches its hash was edited by hand, and the edit is filed in the policy
# inbox before the next sync overwrites it. Nothing here is read by a harness.

def _teyla_dir() -> pathlib.Path:
    return HOME / ".teyla"


def written_path() -> pathlib.Path:
    return _teyla_dir() / "state" / "policy-written.json"


def _written_copy(harness: str) -> pathlib.Path:
    return _teyla_dir() / "state" / "policy-written" / f"{harness}.txt"


def inbox_dir() -> pathlib.Path:
    return _teyla_dir() / "policy-inbox"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _now() -> _dt.datetime:
    return _dt.datetime.now()


def load_written() -> dict:
    """{key: {"harness", "sha256", "date"}}: what the last sync wrote. {} when absent or unreadable."""
    try:
        data = json.loads(written_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _record(harness: str, key: str, text: str) -> None:
    """Remember that sync wrote `text` at `key` (hash, date and a copy of the text for the diff).
    Best effort: a full disk must not stop a sync, it only means the next edit is compared with
    what sync would write then."""
    from . import config
    try:
        state = load_written()
        entry = {"harness": harness, "sha256": _sha(text), "date": _now().date().isoformat()}
        if (state.get(key) or {}).get("sha256") != entry["sha256"]:
            state[key] = entry
            config.write_private(written_path(), json.dumps(state, indent=2, sort_keys=True) + "\n")
        copy = _written_copy(harness)
        if not copy.exists() or _sha(copy.read_text()) != entry["sha256"]:
            config.write_private(copy, text)
    except OSError:
        pass


def _baseline(harness: str, key: str) -> tuple[str | None, str | None]:
    """(hash, text) of what sync last wrote at `key`: (None, None) with no record; (hash, None)
    when the record has no usable copy of the text."""
    rec = load_written().get(key)
    if not isinstance(rec, dict) or not isinstance(rec.get("sha256"), str):
        return None, None
    try:
        text = _written_copy(harness).read_text()
    except OSError:
        return rec["sha256"], None
    return rec["sha256"], (text if _sha(text) == rec["sha256"] else None)


def _is_marker_line(line: str) -> bool:
    return line.startswith(("<!-- generated by `teyla policy sync`", AGENTS_MARKER))


def _changes(before: str, after: str, context: int = 0) -> tuple[list[str], list[str], list[str]]:
    """(added lines, removed lines, unified diff lines) turning `before` into `after`; the
    generated-by marker line is not an edit."""
    diff = list(difflib.unified_diff(before.splitlines(), after.splitlines(), "last written", "current",
                                     lineterm="", n=context))
    added = [l[1:] for l in diff[2:] if l.startswith("+") and not _is_marker_line(l[1:])]
    removed = [l[1:] for l in diff[2:] if l.startswith("-") and not _is_marker_line(l[1:])]
    return added, removed, diff


def _visible(text: str) -> str:
    """`text` with every invisible or bidi character spelled out as <U+XXXX>: an inbox file is
    read by a person, and the edit that carried such a character is exactly what they must see."""
    from . import invisible
    return "".join(f"<U+{ord(ch):04X}>" if invisible._kind(ord(ch)) else ch for ch in text)


def _fence(text: str) -> str:
    runs = [len(m) for m in re.findall(r"`+", text)]
    return "`" * max(3, max(runs, default=0) + 1)


def _inbox_text(harness: str, label: str, name: str, basis: str, added: list[str], removed: list[str],
                diff: list[str], when: _dt.datetime) -> str:
    def block(lines: list[str]) -> str:
        body = "\n".join(lines)
        f = _fence(body)
        return f"{f}text\n{body}\n{f}\n"
    n_add = sum(1 for l in added if l.strip())
    n_rem = sum(1 for l in removed if l.strip())
    out = [f"<!-- teyla-policy-inbox harness={harness} added={n_add} removed={n_rem} file={label} -->",
           f"# Hand edit to {label} ({harness})", "",
           f"`teyla policy sync` found this file changed since it last wrote it, on {when:%Y-%m-%d %H:%M}. "
           "The edit is kept here; the file has been overwritten with the generated text, so the edit "
           "is not in effect any more.", "",
           f"Compared with: {basis}.", "",
           f"**Move what should stay into ~/.agents/POLICY.md or ~/.claude/CLAUDE.md, then "
           f"`teyla policy inbox --done {name}`.**", ""]
    if added:
        out += [f"## Added ({n_add} line(s))", "", block(added)]
    if removed:
        out += [f"## Removed ({n_rem} line(s))", "", block(removed)]
    out += ["## Diff", "", block(diff)]
    return "\n".join(out)


def _copy_text() -> str | None:
    """What a generated copy holds when sync symlinks instead: the marker line and the policy. The
    basis for spotting a hand edit in a copy about to become a symlink, with no record of it."""
    try:
        return AGENTS_HEAD + combined_text()
    except (OSError, ValueError):
        return None


def _keep_edit(harness: str, key: str, label: str, current: str | None, want: str | None, dry: bool,
               known_alt: tuple[str, ...] = ()) -> tuple[bool, str | None]:
    """Before a generated copy at `key` is overwritten: file any hand edit it holds. `current` is the
    text now on disk (None: nothing to lose), `want` what sync is about to write (None: a symlink).
    Returns (go ahead and overwrite, a line for sync's report)."""
    if current is None:
        return True, None
    rec_hash, rec_text = _baseline(harness, key)
    if rec_hash is not None:
        if _sha(current) == rec_hash:
            return True, None  # exactly what sync wrote: stale, not edited
        basis = "the text `teyla policy sync` last wrote there" if rec_text is not None else None
        before = rec_text if rec_text is not None else want
        if before is None:
            return True, None
        basis = basis or "the text sync would write now (the copy of the last write is gone)"
        added, removed, diff = _changes(before, current, context=2)
        changed = any(l.strip() for l in added + removed)
    else:
        # No record (the first sync after an upgrade): what sync would write now is all there is
        # to compare with, and only added lines count — a copy that is merely behind its sources
        # has lines the sources no longer have, which says nothing about an edit.
        ref = want if want is not None else _copy_text()
        if ref is None or current == ref or current.strip() in known_alt:
            return True, None
        basis = "the text sync would write now (no record of the last write yet)"
        added, removed, diff = _changes(ref, current, context=2)
        changed = any(l.strip() for l in added)
    if not changed:
        return True, None
    n_add = sum(1 for l in added if l.strip())
    n_rem = sum(1 for l in removed if l.strip())
    what = f"{n_add} added and {n_rem} removed line(s)" if rec_hash is not None else f"{n_add} added line(s)"
    when = _now()
    d = inbox_dir()

    def named(k: int) -> str:
        return f"{harness}-{when:%Y-%m-%d-%H%M}" + (f"-{k}" if k > 1 else "") + ".md"

    k = 1
    while (d / named(k)).exists():
        k += 1
    name = named(k)
    if dry:
        return True, f"would keep the hand edit of {label} ({what}) in {_tilde(d / name)}, then overwrite it"
    try:
        from . import config
        config.private_dir(d)
        # O_EXCL: a second sync picking the same name moves on to the next one instead of
        # overwriting the first one's edit.
        while True:
            name = named(k)
            try:
                fd = os.open(d / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
                break
            except FileExistsError:
                k += 1
        try:
            config.write_all(fd, _visible(_inbox_text(harness, label, name, basis, added, removed, diff, when)).encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        return False, (f"SKIP {label}: it holds a hand edit ({what}) and the policy inbox {d} could not be "
                       f"written ({e}); nothing overwritten")
    return True, f"kept the hand edit of {label} ({what}) in {_tilde(d / name)} (teyla policy inbox), then overwrote it"


def pending_edits() -> list[dict]:
    """The hand edits waiting in the policy inbox, newest first: name, path, harness, file, added, removed."""
    d = inbox_dir()
    rows = []
    try:
        files = [p for p in d.iterdir() if p.suffix == ".md" and p.is_file()]
    except OSError:
        return []
    for p in files:
        try:
            head = p.read_text().splitlines()[0]
            mt = p.stat().st_mtime
        except (OSError, IndexError):
            head, mt = "", 0.0
        m = re.match(r"<!-- teyla-policy-inbox harness=(\S+) added=(\d+) removed=(\d+) file=(.*) -->$", head)
        rows.append(dict(name=p.name, path=p, mtime=mt,
                         harness=m.group(1) if m else p.name.split("-", 1)[0],
                         added=int(m.group(2)) if m else 0, removed=int(m.group(3)) if m else 0,
                         file=m.group(4) if m else "?"))
    return sorted(rows, key=lambda r: (r["mtime"], r["name"]), reverse=True)


def inbox_summary(rows: list[dict] | None = None) -> str:
    rows = pending_edits() if rows is None else rows
    if not rows:
        return "policy inbox: empty"
    lines = [f"{len(rows)} hand edit(s) to generated policy files wait for review in {_tilde(inbox_dir())}:"]
    for r in rows:
        lines.append(f"  {r['name']}  +{r['added']} -{r['removed']} line(s)  {r['file']}")
    lines.append("move what should stay into ~/.agents/POLICY.md or ~/.claude/CLAUDE.md, "
                 "then `teyla policy inbox --done <file>` (or --all)")
    return "\n".join(lines)


def inbox_done(name: str | None = None, everything: bool = False) -> list[str]:
    """Mark one inbox file (by file name) done, or every pending one: the file is deleted."""
    rows = pending_edits()
    if everything:
        picked = rows
    else:
        want = pathlib.Path(name or "").name  # a name only: never a path outside the inbox
        picked = [r for r in rows if r["name"] == want]
        if not picked:
            return [f"no pending edit named {name!r}" + (": " + ", ".join(r["name"] for r in rows) if rows else "")]
    out = []
    for r in picked:
        try:
            r["path"].unlink()
            out.append(f"done: {r['name']}")
        except OSError as e:
            out.append(f"could not remove {r['name']}: {e}")
    return out or ["policy inbox: nothing pending"]


def sync(dry=False, owner: str | None = None, unattended: bool = False) -> list[str]:
    """Wire the policy into every harness that is installed and not disabled. `unattended` (the
    daily routine, --quiet): never create POLICY.md and never edit ~/.claude/CLAUDE.md — those two
    are for a person to start. Everything else is the same, and nothing here touches the network."""
    done = []
    off = _disabled()
    if not POLICY.exists():
        if unattended:
            return [f"SKIP no {POLICY}: run `teyla policy init` first"]
        done.append(init(owner=owner, dry=dry))
    # The source first, once: the imports and symlinks below expose POLICY.md to every harness,
    # and a refusal half-way would leave some wired and some not (caught in review, P2).
    if POLICY.exists():
        _guard(POLICY.read_text(), POLICY)
    # ... and so is everything AGENTS.md and the Cursor skill are made of: CLAUDE.md under its own
    # name (the refusal should point at the file to fix), then the whole text with the inlined
    # imports, before the first write below.
    want = None
    if POLICY.exists():
        cm = TARGETS["claude-code"]
        if cm.exists():
            _guard(cm.read_text(), cm)
        want = agents_text()
        if want is not None:
            _guard(want, TARGETS["codex"])
    p = TARGETS["claude-code"]
    if "claude-code" not in off and not unattended and p.exists() and IMPORT_LINE not in p.read_text():
        if not dry:
            p.write_text(_guard(p.read_text().rstrip() + f"\n\n## How to run a session\n\n{IMPORT_LINE}\n", p))
        done.append(f"added import to {p}")
    warned = False
    for h in ("codex", "grok"):
        if h in off:
            continue
        p = TARGETS[h]
        if not p.parent.exists():
            continue
        real = p.exists() and not p.is_symlink()
        if real and not is_generated_agents(p.read_text()):
            done.append(f"SKIP {p}: a real file exists; merge by hand or delete it")
            continue
        current = p.read_text() if real else None
        if want is None:
            if p.exists() and p.resolve() == POLICY.resolve() and p.is_symlink():
                continue
            ok, line = _keep_edit(h, str(p), _tilde(p), current, None, dry)
            if line:
                done.append(line)
            if not ok:
                continue
            if not dry:
                if p.is_symlink() or real:
                    p.unlink()
                p.symlink_to(POLICY)
            done.append(f"symlinked {p} → {POLICY}")
            continue
        if len(want.encode()) > AGENTS_SIZE_WARN and not warned:
            warned = True
            done.append(f"WARN the generated AGENTS.md is {len(want.encode()) // 1024} KiB, over the 32 KiB Codex "
                        "allows a project doc (the global file is read whole); prune ~/.claude/CLAUDE.md or POLICY.md")
        if real and current == want:
            # Same text, older file: touch it, or session-start.sh's -nt test would start a sync
            # at every session for an edit that changed nothing here.
            if not dry and _older_than_sources(p):
                os.utime(p)
            if not dry:
                _record(h, str(p), want)
            continue
        ok, line = _keep_edit(h, str(p), _tilde(p), current, want, dry)
        if line:
            done.append(line)
        if not ok:
            continue
        if not dry:
            if p.is_symlink():
                p.unlink()  # never write through it: it points at POLICY.md
            p.write_text(_guard(want, p))
            _record(h, str(p), want)
        done.append(f"wrote {p}: POLICY.md + the owner's rules from {TARGETS['claude-code']}")
    p = TARGETS["hermes"]
    if "hermes" not in off and p.exists():
        text = p.read_text()
        key = f"{p}#operating-policy"
        block = hermes_block().strip()
        if _hermes_current(text):
            if not dry:
                _record("hermes", key, block)
        else:
            span = _hermes_section(text)
            if span is None:
                new_text, what = text.rstrip() + hermes_block(), "appended policy section to"
            else:
                ok, line = _keep_edit("hermes", key, f"{_tilde(p)} (the Operating policy section)",
                                      text[span[0]:span[1]].strip(), block, dry,
                                      known_alt=(HERMES_BLOCK.strip(), HERMES_BLOCK_WORK.strip()))
                if line:
                    done.append(line)
                if not ok:
                    new_text = None
                else:
                    # The section under HERMES_MARK is Teyla's: replaced whole, whatever variant it was.
                    rest = text[span[1]:]
                    new_text = text[:span[0]] + hermes_block().rstrip("\n") + "\n" + ("\n" + rest if rest else "")
                    what = "replaced the policy section in"
            if new_text is not None:
                if not dry:
                    p.write_text(_guard(new_text, p))
                    _record("hermes", key, block)
                done.append(f"{what} {p}")
    p = TARGETS.get("cursor")
    if p is not None and "cursor" not in off and p.parents[2].is_dir() and POLICY.exists():
        skill = cursor_skill_text()
        current = p.read_text() if p.exists() else None
        if current == skill:
            if not dry:
                _record("cursor", str(p), skill)
        else:
            ok, line = _keep_edit("cursor", str(p), _tilde(p), current, skill, dry)
            if line:
                done.append(line)
            if ok:
                if not dry:
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(_guard(skill, p))
                    _record("cursor", str(p), skill)
                done.append(f"wrote the policy as a Cursor user skill: {p}")
    return done or ["already in sync"]


# CLAUDE.md that pulls AGENTS.md in: `@AGENTS.md` on a line of its own.
IMPORT_RE = re.compile(r"^@AGENTS\.md\s*$", re.M)
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _live_lines(text: str):
    """(line, live) for every line of `text`; `live` is False for the lines of a ``` or ~~~ fenced
    code block, fences included. Claude Code does not expand an import shown in code."""
    fence = None  # (char, length) of the open fence
    for line in text.splitlines():
        m = _FENCE_RE.match(line)
        if fence is None:
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
                yield line, False
            else:
                yield line, True
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not m.group(2).strip():
                fence = None
            yield line, False


def imports_agents(text: str) -> bool:
    """True when `text` has a live `@AGENTS.md` import: a line of its own that is not inside a
    ``` or ~~~ fenced code block. Claude Code does not expand imports in code, so a CLAUDE.md that
    only shows the line as an example is not linked to AGENTS.md (caught in review, P2)."""
    return any(live and IMPORT_RE.match(line) for line, live in _live_lines(text))


# ---------------------------------------------------------------------------
# The owner's rules for harnesses that cannot import: ~/.codex/AGENTS.md, ~/.grok/AGENTS.md and
# the Cursor skill get POLICY.md + ~/.claude/CLAUDE.md as one generated text.

AGENTS_MARKER = "<!-- generated by teyla policy sync"
AGENTS_HEAD = (f"{AGENTS_MARKER} from ~/.agents/POLICY.md + ~/.claude/CLAUDE.md — "
               "edit those, not this file -->\n\n")
OWNER_HEAD = "# The owner's rules (from ~/.claude/CLAUDE.md)"
OWNER_PREAMBLE = (
    "Everything below is the owner's own global instructions, copied here by `teyla policy sync` "
    "because this harness cannot import ~/.claude/CLAUDE.md the way Claude Code does. Edit "
    "~/.agents/POLICY.md or ~/.claude/CLAUDE.md, not this file: the next sync overwrites it. They "
    "bind you exactly as the policy above does. Where a line says it is Claude-specific or names "
    "Claude Code tools (`Agent`, `model: sonnet`, skills, slash commands), apply the equivalent "
    "of your own harness.")
MEMORY_SECTION = """## Project memory (shared with Claude Code)

Per-project memory lives in `~/.claude/projects/<key>/memory/`, and Claude Code reads and writes
the same directory. `<key>` is the repo's absolute path with every `/` and `.` replaced by `-`
(`/Users/me/repos/app` → `-Users-me-repos-app`); in a git worktree, use the main checkout's path,
the parent of `git rev-parse --path-format=absolute --git-common-dir`. When you start work in a
repo, read `MEMORY.md` there: an index, one line per memory file. To keep a new durable fact (a
decision, a gotcha, how this owner wants something done), write it as one small `.md` file in
that directory — frontmatter with `name` and a one-line `description`, then the fact and why —
and add one line to `MEMORY.md`: `- [Title](file.md) — one-line hook`, the format Claude Code uses.
"""
# Codex caps a project doc at 32 KiB (project_doc_max_bytes); the global file is read whole
# (verified on 0.159.2), but a file that size is mostly not being read either.
AGENTS_SIZE_WARN = 32 * 1024
# An import line Claude Code expands: `@~/...` or `@/abs/...`, alone on its line.
_PATH_IMPORT_RE = re.compile(r"^\s*@((?:~/|/)\S+)\s*$")
_RUN_HEADING = "## How to run a session"


def is_generated_agents(text: str) -> bool:
    """Whether an AGENTS.md is the one sync writes: its first line is the generated-by marker."""
    return text.startswith(AGENTS_MARKER)


def _import_path(spec: str) -> pathlib.Path:
    return HOME / spec[2:] if spec.startswith("~/") else pathlib.Path(spec)


def _same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def owner_rules(text: str) -> str | None:
    """CLAUDE.md's text as the other harnesses should get it, or None when it holds nothing but
    the policy import (and headings, blank lines) — then AGENTS.md stays a plain symlink.

    The `@~/.agents/POLICY.md` import is dropped (the policy is already above it), with the
    `## How to run a session` heading sync puts over it when that heading is left empty. Any
    other live `@~/...` or `@/abs/...` import line is replaced by that file's text, one level
    deep — a missing file leaves the line as it was. An import inside a code fence is an example,
    not an import, and stays as written."""
    out: list[str] = []
    dropped = False
    targets = [TARGETS[h] for h in ("codex", "grok") if h in TARGETS]
    for line, live in _live_lines(text):
        m = _PATH_IMPORT_RE.match(line) if live else None
        if m:
            path = _import_path(m.group(1))
            if line.strip() == IMPORT_LINE or _same_file(path, POLICY):
                dropped = bool(out) and not out[-1].strip()
                continue
            if path.is_file() and not any(_same_file(path, t) for t in targets):
                out.extend(path.read_text().rstrip("\n").splitlines())
                continue
        if dropped and not line.strip():
            dropped = False
            continue  # the blank line after a dropped import: one gap, not two
        dropped = False
        out.append(line)
    # The heading sync wrote over the import, now with nothing under it.
    i = 0
    while i < len(out):
        if out[i].strip() == _RUN_HEADING:
            j = i + 1
            while j < len(out) and not out[j].strip():
                j += 1
            if j == len(out) or out[j].startswith("#"):
                del out[i:j]
                continue
        i += 1
    body = "\n".join(out).strip()
    if all(not l.strip() or l.lstrip().startswith("#") for l in body.splitlines()):
        return None
    return body + "\n"


def _claude_md_rules() -> str | None:
    p = TARGETS["claude-code"]
    return owner_rules(p.read_text()) if p.exists() else None


def combined_text() -> str:
    """POLICY.md, then — when ~/.claude/CLAUDE.md has rules of its own — those rules under
    OWNER_HEAD and the shared-memory section. With no owner rules: POLICY.md as it is."""
    text = POLICY.read_text()
    rules = _claude_md_rules()
    if rules is None:
        return text
    return (text.rstrip("\n") + "\n\n---\n\n" + OWNER_HEAD + "\n\n" + OWNER_PREAMBLE + "\n\n"
            + rules + "\n" + MEMORY_SECTION)


def agents_text() -> str | None:
    """What ~/.codex/AGENTS.md and ~/.grok/AGENTS.md should hold, or None for "a symlink to
    POLICY.md" (CLAUDE.md missing, or nothing in it but the import)."""
    if _claude_md_rules() is None:
        return None
    return AGENTS_HEAD + combined_text()


def _sources() -> list[pathlib.Path]:
    return [p for p in (TARGETS["claude-code"], POLICY) if p.exists()]


def _older_than_sources(p: pathlib.Path) -> pathlib.Path | None:
    """The first source (CLAUDE.md, POLICY.md) modified after `p`, or None."""
    mt = p.stat().st_mtime
    return next((s for s in _sources() if s.stat().st_mtime > mt), None)


def _tilde(p: pathlib.Path) -> str:
    try:
        return "~/" + str(p.relative_to(HOME))
    except ValueError:
        return str(p)


def drift(h: str) -> tuple[str, str] | None:
    """(why, fix) when ~/.<h>/AGENTS.md is not what sync would write — for `teyla doctor`, which
    otherwise could only say "not wired" about a file that is merely a day behind CLAUDE.md."""
    p = TARGETS[h]
    if not POLICY.exists() or not p.parent.exists():
        return None
    sync_fix = "teyla policy sync"
    if not p.exists():
        return f"{_tilde(p)} is missing", sync_fix
    want = agents_text()
    real = not p.is_symlink()
    if real and not is_generated_agents(p.read_text()):
        return (f"{_tilde(p)} is a hand-written file (no generated-by marker), so sync leaves it alone",
                f"merge it into ~/.agents/POLICY.md or ~/.claude/CLAUDE.md, delete it, then: {sync_fix}")
    if want is None:
        if real:
            return f"{_tilde(p)} still carries owner rules that {_tilde(TARGETS['claude-code'])} no longer has", sync_fix
        if _same_file(p, POLICY):
            return None
        return f"{_tilde(p)} is a symlink, but not to {_tilde(POLICY)}", sync_fix
    if not real:
        return (f"{_tilde(p)} is a symlink to the policy alone: this harness cannot import "
                f"{_tilde(TARGETS['claude-code'])}, so it misses the owner's rules"), sync_fix
    cur = p.read_text()
    if cur == want:
        return None
    rec_hash, _ = _baseline(h, str(p))
    if rec_hash is not None and _sha(cur) != rec_hash:
        return (f"{_tilde(p)} was edited after sync wrote it", sync_fix + "   (files the edit in "
                f"{_tilde(inbox_dir())} first; move what should stay into ~/.agents/POLICY.md or ~/.claude/CLAUDE.md)")
    newer = _older_than_sources(p)
    if newer is not None:
        return f"{_tilde(p)} is older than {_tilde(newer)}", sync_fix
    return f"{_tilde(p)} differs from what sync would write (an imported file changed?)", sync_fix


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
        if imports_agents(c.read_text()):
            return f"{r.name}: already linked (CLAUDE.md imports @AGENTS.md)"
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


def layout_roots(texts: "list[str] | None" = None) -> dict:
    """{code_root, ops_root} as the Layout section of an existing policy file declares them —
    `~/.agents/POLICY.md` first, then `~/.claude/CLAUDE.md` — or {} for whatever is not stated.
    The shape is the template's own: a line with `<root>/<repo>` names code_root; a line whose
    root is followed by "everything that is not a code repo" names ops_root. `policy init`
    seeds config.toml from this instead of a constant, so a laptop whose policy says code lives
    in ~/work is not told "no git repos under ~/repos"."""
    import re
    if texts is None:
        texts = []
        for p in (POLICY, CLAUDE_GLOBAL):
            try:
                texts.append(p.read_text())
            except OSError:
                pass
    out = {}
    for text in texts:
        if "code_root" not in out:
            m = re.search(r"`(~/[^`\s]+)/<repo>`", text)
            if m:
                out["code_root"] = m.group(1)
        if "ops_root" not in out:
            m = re.search(r"`(~/[^`\s]+)`\s*[—-]+\s*everything that is not a code repo", text)
            if m:
                out["ops_root"] = m.group(1)
    return out


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
    CLAUDE_GLOBAL.write_text(_guard(text, CLAUDE_GLOBAL))
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
            c.write_text(_guard(tpl.replace("{{owner}}", owner or getpass.getuser()).replace("{{code_root}}", code_root), c))
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
            gi.write_text((gi.read_text() if gi.exists() else "") + "runs/\n.env\n.teyla/\n"); done.append(f"gitignore: runs/ in {gi}")
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
    from . import config
    config.write_private(ACK_PATH, json.dumps(record, indent=2) + "\n")
    detail = f"sha256={digest} date={today}" + (f" note={note!r}" if note else "")
    return f"recorded {CLAUDE_GLOBAL} -> {ACK_PATH}: {detail}"


# ---------------------------------------------------------------------------
# Template drift: keep ~/.agents/POLICY.md current across Teyla releases without
# losing the owner's edits. Three-way merge: base (the template as last applied),
# new (the template shipped with this version), local (the owner's file).

BASE_PATH = HOME / ".teyla" / "policy-base.md"
CONFLICT_PATH = HOME / ".teyla" / "policy-merge-conflict.md"
# Safe mode: a template change arrives with an update the owner did not start, and POLICY.md is
# what every harness obeys. So the merge is only proposed here; the owner diffs and applies it.
PROPOSED_PATH = HOME / ".teyla" / "policy-proposed.md"


def proposal_commands() -> str:
    return (f"diff -u {POLICY} {PROPOSED_PATH}   then, to take it: "
            f"cp {PROPOSED_PATH} {POLICY} && teyla policy refresh --resolved")


def _owner_from(text: str) -> str | None:
    import re
    m = re.search(r"^Owner:\s*(.+?)\.\s*(?:Edit here.*)?$", text, re.M)
    return m.group(1).strip() if m else None


def render_template(owner: str | None = None, work: bool | None = None) -> str:
    """The shipped template with the owner filled in. `work` None: the variant the installed
    POLICY.md came from, so a work policy is never merged against the home template."""
    import getpass
    if work is None:
        work = is_work()
    return template_path(work).read_text().replace("{{owner}}", owner or getpass.getuser())


def refresh(dry: bool = False) -> list[str]:
    """Merge template changes into ~/.agents/POLICY.md.

    - no POLICY.md: nothing (sync creates it)
    - no base recorded: record the current template as base, keep the owner's file as is,
      report how far it differs
    - base == new template: nothing changed upstream
    - otherwise `git merge-file` local/base/new; clean → write, back up the old file, move
      base forward; conflicts → write the marked-up merge to CONFLICT_PATH, leave POLICY.md
      untouched, and let doctor nag until it is resolved (`teyla policy refresh --resolved`)
    """
    import datetime as _dt
    import difflib
    import shutil
    import subprocess
    import tempfile
    if not POLICY.exists():
        return ["no POLICY.md yet — run `teyla policy sync`"]
    local = POLICY.read_text()
    new = render_template(_owner_from(local))
    if not BASE_PATH.exists():
        n = sum(1 for l in difflib.unified_diff(new.splitlines(), local.splitlines(), lineterm="", n=0)
                if l.startswith(("+", "-")) and not l.startswith(("+++", "---")))
        if dry:
            return [f"would record the current template as base ({n} line(s) differ locally; kept)"]
        BASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASE_PATH.write_text(new)
        return [f"recorded template base at {BASE_PATH}; your file differs from it in {n} line(s), kept as is"]
    base = BASE_PATH.read_text()
    if base == new:
        if CONFLICT_PATH.exists():
            return [f"template unchanged; a merge conflict is still waiting in {CONFLICT_PATH}"]
        return ["template unchanged since last refresh"]
    # Every write below (POLICY.md, the proposal, the conflict file) is made of these two.
    _guard(local, POLICY); _guard(new, POLICY)
    from . import config
    if config.safe_mode():
        return _propose(local, base, new, dry)
    if local == base:
        if not dry:
            _backup_policy()
            POLICY.write_text(new); BASE_PATH.write_text(new)
        return [f"{'would apply' if dry else 'applied'} template changes to {POLICY} (no local edits to keep)"]
    git = shutil.which("git")
    if not git:
        return ["template changed but `git` is not available for a three-way merge — merge by hand"]
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td)
        (p / "local").write_text(local); (p / "base").write_text(base); (p / "new").write_text(new)
        r = subprocess.run([git, "merge-file", "-p", "-L", "yours", "-L", "base", "-L", "teyla-template",
                            str(p / "local"), str(p / "base"), str(p / "new")], capture_output=True, text=True)
    # The exit code is the conflict count, capped at 127; a negative one (a signal) or anything
    # above 127 (255 and the like) is an error, not "N conflicts": there is no merge to write
    # (caught in review, P2).
    if r.returncode < 0 or r.returncode > 127:
        return [f"git merge-file failed: {r.stderr.strip() or f'exit {r.returncode}'}; "
                f"nothing written, {POLICY} untouched"]
    if r.returncode == 0:
        if not dry:
            _backup_policy()
            POLICY.write_text(r.stdout); BASE_PATH.write_text(new)
            if CONFLICT_PATH.exists():
                CONFLICT_PATH.unlink()
        return [f"{'would merge' if dry else 'merged'} template changes into {POLICY} (your edits kept)"]
    if not dry:
        CONFLICT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFLICT_PATH.write_text(r.stdout)
    return [f"{r.returncode} conflict(s): template and your edits touch the same lines. "
            f"{'Would write' if dry else 'Wrote'} the marked-up merge to {CONFLICT_PATH}; {POLICY} untouched. "
            f"Resolve there, copy into {POLICY}, then `teyla policy refresh --resolved`"]


def _merge(local: str, base: str, new: str) -> tuple[str | None, int, str]:
    """(merged text, conflict count, error) from `git merge-file`; (None, -1, "") without git,
    (None, -1, stderr) when git failed."""
    import shutil
    import subprocess
    import tempfile
    if local == base:
        return new, 0, ""
    git = shutil.which("git")
    if not git:
        return None, -1, ""
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td)
        (p / "local").write_text(local); (p / "base").write_text(base); (p / "new").write_text(new)
        r = subprocess.run([git, "merge-file", "-p", "-L", "yours", "-L", "base", "-L", "teyla-template",
                            str(p / "local"), str(p / "base"), str(p / "new")], capture_output=True, text=True)
    # git merge-file exits with the conflict count, capped at 127; above that (255 and the like,
    # with empty stdout) is an error, not a merge — proposing its stdout would offer an empty
    # POLICY.md to copy over the real one (caught in review, P2).
    if 0 <= r.returncode <= 127:
        return r.stdout, r.returncode, ""
    return None, -1, (r.stderr.strip() or f"exit {r.returncode}")


def _propose(local: str, base: str, new: str, dry: bool) -> list[str]:
    merged, conflicts, err = _merge(local, base, new)
    if err:
        return [f"safe mode: the policy template changed but `git merge-file` failed: {err}; "
                f"nothing proposed, {POLICY} and any earlier {PROPOSED_PATH.name} untouched"]
    if merged is None:
        merged, conflicts = new, 0  # no git: propose the template itself; the diff shows what it drops
    if not dry:
        PROPOSED_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROPOSED_PATH.write_text(merged)
    what = f"with {conflicts} conflict(s) marked" if conflicts else "merged cleanly with your edits"
    return [f"safe mode: the policy template changed; {'would propose' if dry else 'proposed'} the new {POLICY.name} "
            f"({what}) in {PROPOSED_PATH} — {POLICY} untouched. Review: {proposal_commands()}"]


def resolved() -> str:
    """The owner says the conflict is resolved in POLICY.md (or took the safe-mode proposal):
    move base forward, drop the conflict and proposal files."""
    if not POLICY.exists():
        return "no POLICY.md"
    BASE_PATH.write_text(render_template(_owner_from(POLICY.read_text())))
    removed = []
    for p in (CONFLICT_PATH, PROPOSED_PATH):
        if p.exists():
            p.unlink()
            removed.append(p.name)
    return "base moved to the current template" + (f"; {', '.join(removed)} removed" if removed else "")


def _backup_policy() -> pathlib.Path:
    import datetime as _dt
    bak = POLICY.with_name(POLICY.name + ".bak-" + _dt.date.today().isoformat())
    if not bak.exists():
        bak.write_text(POLICY.read_text())
    return bak


def repos_status(root: pathlib.Path) -> list[tuple[str, str]]:
    """For each git repo directly under root: ('ok'|'missing'|'differ'|'none', name)."""
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if not (d / ".git").exists():
            continue
        a, c = d / "AGENTS.md", d / "CLAUDE.md"
        if a.exists() and c.exists():
            # ok = one source of truth: a symlink, identical text, or CLAUDE.md that imports
            # AGENTS.md (`@AGENTS.md` on a line of its own — what `teyla cloud prep` writes, and
            # what a repo with Claude-only lines needs). Claude Code expands the import, so the two
            # files cannot drift; comparing their text would flag exactly the layout we recommend.
            if a.is_symlink() or c.is_symlink() or a.read_text() == c.read_text() or imports_agents(c.read_text()):
                out.append(("ok", d.name))
            else:
                out.append(("differ", d.name))
        elif a.exists() or c.exists():
            out.append(("missing", d.name))
        else:
            out.append(("none", d.name))
    return out

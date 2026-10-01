"""`teyla rule` and `teyla correct` — the two file writes behind the Claude Code plugin's
`/teyla:rule` and `/teyla:correct`, as a CLI.

The slash commands are prompts: Claude reads them and does the writing. Codex, Cursor, Grok
and Hermes each run skills, not Claude Code commands, so the same two writes have to exist
as something every harness can call the same way — a command. The plugin commands keep
working as they are (they need no CLI); the skills `teyla harness sync` installs into the
other harnesses call these.

    teyla rule "<one sentence>" [--scope <glob>] [--repo <path>] [--dry]
    teyla correct "<what was wrong>" [--repo <path>]

A rule lands in `.claude/rules/<slug>.md` (frontmatter `globs:`), is mirrored into a
`## Rules` section of `AGENTS.md` when that is a real file (Codex, Hermes, Grok and Cursor
read AGENTS.md; a symlink onto CLAUDE.md would write through and double the rule), and —
only when the repo already has `.cursor/rules/` — into `.cursor/rules/<slug>.mdc`, Cursor's
own scoped-rule shape. A correction is one JSON line in the repo's file under
`~/.teyla/corrections/` (see corrections.py: outside the repo, secrets scrubbed), the same
record the capture hook writes but with `source: "correct"` — a person ran this, so
`teyla rules propose` counts it as human (rules_lifecycle.py) — plus a proposed rule sentence
to promote or not.

A new rule file starts with lifecycle fields (`created`, `hits`, `last_hit`, `expires`; see
rules_lifecycle.py). Both commands refuse text with invisible or bidi characters (invisible.py)
before writing anything, and `teyla rule` warns when a file it wrote is past ~200 lines.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re

RULES_DIR = ".claude/rules"
CURSOR_RULES_DIR = ".cursor/rules"
STOP = {"a", "an", "the", "in", "on", "at", "to", "of", "for", "and", "or", "not", "never", "always", "is", "are",
        "be", "with", "this", "that", "it", "use", "do", "don't", "dont", "no", "we", "you", "i", "here", "by"}


def slug_of(text: str) -> str:
    """A few significant words of the rule, kebab-cased: 'Outbound drafts open with a claim, not a
    question.' -> outbound-drafts-open-claim."""
    words = [w for w in re.findall(r"[a-zA-Zа-яА-Я0-9]+", text.lower()) if w not in STOP]
    slug = "-".join(words[:4]) or "rule"
    return slug[:48].strip("-")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().rstrip(".")).lower()


def find_duplicate(repo: pathlib.Path, text: str) -> pathlib.Path | None:
    rules = repo / RULES_DIR
    if not rules.is_dir():
        return None
    want = _norm(text)
    for f in sorted(rules.glob("*.md")):
        for line in f.read_text(errors="replace").splitlines():
            if _norm(line.lstrip("- ")) == want:
                return f
    return None


def _mirror_agents_md(repo: pathlib.Path, bullet: str, dry: bool) -> str:
    a = repo / "AGENTS.md"
    if not a.exists():
        return "AGENTS.md: none, not mirrored"
    if a.is_symlink():
        return "AGENTS.md: a symlink, not mirrored (it would write through)"
    text = a.read_text()
    if bullet in text:
        return "AGENTS.md: already has it"
    if "\n## Rules" in text or text.startswith("## Rules"):
        new = text.rstrip("\n") + "\n" + bullet + "\n"
    else:
        new = text.rstrip("\n") + "\n\n## Rules\n\n" + bullet + "\n"
    if not dry:
        a.write_text(new)
    return f"AGENTS.md: {'would mirror' if dry else 'mirrored'} into ## Rules"


def _mirror_cursor(repo: pathlib.Path, slug: str, text: str, scope: str, dry: bool) -> str | None:
    d = repo / CURSOR_RULES_DIR
    if not d.is_dir():
        return None
    f = d / f"{slug}.mdc"
    if f.exists():
        body = f.read_text()
        if _norm(text) in (_norm(l.lstrip("- ")) for l in body.splitlines()):
            return f"{CURSOR_RULES_DIR}/{slug}.mdc: already has it"
        new = body.rstrip("\n") + f"\n- {text}\n"
    else:
        always = "true" if scope in ("**", "*") else "false"
        new = f"---\ndescription: {text[:120]}\nglobs: {scope}\nalwaysApply: {always}\n---\n\n- {text}\n"
    if not dry:
        f.write_text(new)
    return f"{CURSOR_RULES_DIR}/{slug}.mdc: {'would write' if dry else 'written'}"


def add_rule(repo: str | pathlib.Path, text: str, scope: str = "**", dry: bool = False,
             today: _dt.date | None = None) -> list[str]:
    from . import invisible, rules_lifecycle
    repo = pathlib.Path(repo).expanduser().resolve()
    text = " ".join(text.split()).strip()
    if not text:
        return ["nothing to add: empty rule"]
    # Before anything is written: the rule, its scope and every mirror get the same bytes.
    invisible.check(text, "the rule"); invisible.check(scope, "the rule's scope")
    if not text.endswith((".", "!", "?")):
        text += "."
    dup = find_duplicate(repo, text)
    if dup:
        return [f"already there: {dup.relative_to(repo)} — nothing written"]
    slug = slug_of(text)
    f = repo / RULES_DIR / f"{slug}.md"
    bullet = f"- {text}"
    out = []
    if f.exists():
        new = f.read_text().rstrip("\n") + "\n" + bullet + "\n"
        out.append(f"{'would append' if dry else 'appended'} to {f.relative_to(repo)} (scope kept as is)")
    else:
        fields = rules_lifecycle.lifecycle_fields(today or _dt.date.today())
        new = f"---\nglobs: {scope}\n{fields}---\n\n{bullet}\n"
        out.append(f"{'would write' if dry else 'wrote'} {f.relative_to(repo)} (globs: {scope})")
    if not dry:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(new)
    out.append(_mirror_agents_md(repo, bullet, dry))
    c = _mirror_cursor(repo, slug, text, scope, dry)
    if c:
        out.append(c)
    if not dry:
        out += rules_lifecycle.budget_lines(rules_lifecycle.budget(repo, [f, repo / "AGENTS.md"]))
    return out


def record_correction(repo: str | pathlib.Path, text: str) -> list[str]:
    from . import corrections, invisible, rules_lifecycle
    repo = pathlib.Path(repo).expanduser().resolve()
    text = text.strip()
    if not text:
        return ["nothing to record: empty correction"]
    # A rule is drafted from these words; hidden characters in them would ride into it.
    invisible.check(text, "the correction")
    rec = {"ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), "text": text, "cwd": str(repo),
           "source": "correct"}
    f = corrections.append(repo, rec)
    n = len(corrections.records(repo))
    shown = str(f).replace(str(pathlib.Path.home()), "~", 1)
    out = [f"recorded in {shown} ({n} so far)"]
    if corrections.scrub(text) != text:
        out.append("something secret-shaped was replaced by [redacted] before writing")
    hit = rules_lifecycle.best_rule(rules_lifecycle.load_rules(repo), text)
    if hit:
        out.append(f"it matches {hit.rel}: that rule exists and was not followed — sharpen it or narrow its scope "
                   f"(`teyla rules propose --write` counts the hit)")
        return out
    out += ["a correction is a data point, not yet a rule; if it has now happened twice, promote it:",
            f'  teyla rule "<the constraint, one sentence>" --scope "<glob>"   (in {repo})']
    return out


def cmd_rule(args):
    for line in add_rule(args.repo or ".", args.text, scope=args.scope, dry=args.dry):
        print(line)
    return 0  # an InvisibleText refusal is printed and turned into exit 2 by cli.main


def cmd_correct(args):
    for line in record_correction(args.repo or ".", args.text):
        print(line)
    return 0


def register(sp):
    q = sp.add_parser("rule", help="append a one-sentence rule to .claude/rules/<slug>.md; mirror into AGENTS.md (and .cursor/rules/ if present)")
    q.set_defaults(fn=cmd_rule)
    q.add_argument("text", help="the rule, one or two sentences: the constraint, not the reasoning")
    q.add_argument("--scope", default="**", help="path glob the rule loads for (default **)")
    q.add_argument("--repo", help="repo root (default: current directory)")
    q.add_argument("--dry", action="store_true")
    q = sp.add_parser("correct", help="record a correction in ~/.teyla/corrections/<repo>.jsonl (scrubbed) and say how to promote it")
    q.set_defaults(fn=cmd_correct)
    q.add_argument("text", help="what was wrong, in the words it was said")
    q.add_argument("--repo", help="repo root (default: current directory)")
    from . import rules_lifecycle
    rules_lifecycle.register(sp)

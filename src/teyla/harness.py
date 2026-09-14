"""`teyla harness status|sync` — the same skills, hooks and policy in Cursor, Codex, Grok and
Hermes that the Claude Code plugin gives Claude.

What each harness reads, verified on this machine on 2026-09-14 against the harness's own
on-disk docs (Cursor 3.19.7 `~/.cursor/skills-cursor/*/SKILL.md`; Grok CLI 1.0.0
`~/.grok/docs/user-guide/`; Hermes 0.20.4 `~/.hermes/hermes-agent/website/docs`; Codex 0.153.4
`codex --help` and `~/.codex/skills`):

  harness  policy                               skills                         hooks
  cursor   no global rules file; per-repo       ~/.cursor/skills/<name>/       ~/.cursor/hooks.json
           AGENTS.md; a user skill carries        SKILL.md (name, description,   {version:1, hooks:{sessionStart,
           ~/.agents/POLICY.md                    disable-model-invocation)      beforeSubmitPrompt: [{command}]}}
  codex    ~/.codex/AGENTS.md → POLICY.md       ~/.codex/skills/<name>/        none (only `notify`)
           (policy.py)                            SKILL.md
  grok     ~/.grok/AGENTS.md → POLICY.md        ~/.grok/skills/<name>/         ~/.grok/hooks/*.json
           (policy.py); also reads               SKILL.md (also scans           {hooks:{SessionStart,
           AGENTS.md/CLAUDE.md per directory      ~/.claude and ~/.cursor)       UserPromptSubmit:[{hooks:[…]}]}}
  hermes   ~/.hermes/SOUL.md section            ~/.hermes/skills/<category>/   `hooks:` block in ~/.hermes/config.yaml
           (policy.py); AGENTS.md per repo        <name>/SKILL.md                (on_session_start, pre_llm_call)

Hook scripts are one copy each in ~/.teyla/hooks/ — the plugin's own session-start.sh and
capture-correction.sh, which already read every harness's stdin shape (`prompt`, `text`,
`user_message`, Hermes's `extra.user_message`) and de-duplicate, since Grok also loads
~/.cursor/hooks.json. Skills are rendered from the plugin's SKILL.md files with `/teyla:rule`
and `/teyla:correct` replaced by the CLI (`teyla rule`, `teyla correct`), and carry a
"generated from" line; edits go in the plugin source, and the next sync overwrites the copy.

Nothing here touches a harness that is not installed, and every write is idempotent: a second
sync with nothing changed prints "in sync".
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat

from . import __version__, plugin_dir

HOME = pathlib.Path.home()
HOOKS_DIR = HOME / ".teyla" / "hooks"
HOOK_SCRIPTS = ("session-start.sh", "capture-correction.sh")
PLUGIN_SKILLS = ("harvest", "adoption-review", "wiki-pass")
CLI_SKILLS = {
    "teyla-rule": (
        "Write a one-sentence rule into this repo so a correction is never said twice: `.claude/rules/<slug>.md`, "
        "mirrored into AGENTS.md (and .cursor/rules/ if present). Trigger phrases: \"add a rule\", \"make that a rule\", "
        "\"never do X here\", \"always do Y in this repo\".",
        """# Rule

A rule is a constraint — what must always or never be true here. One or two sentences,
the constraint and not the reasoning, in language close to what was actually said, scoped
with the narrowest path glob that covers it.

1. Turn what was said into one sentence. "Don't be salesy" is unactionable; "open with a
   claim, not a question" is checkable.
2. Run:

   ```sh
   teyla rule "<the sentence>" --scope "<glob, default **>"
   ```

   It refuses a duplicate, writes `.claude/rules/<slug>.md` with a `globs:` frontmatter,
   mirrors the bullet into a `## Rules` section of `AGENTS.md` when that is a real file
   (every harness reads AGENTS.md; a symlink would write through), and into
   `.cursor/rules/<slug>.mdc` when the repo already has that directory.
3. Report the file written, the scope, and whether AGENTS.md was updated or why not.

Never write a rule nobody asked for. A rule comes from a correction that happened.
""",
    ),
    "teyla-correct": (
        "Record a correction the human just made (\"no, not like that\") so it can become a rule the second time. "
        "Trigger phrases: \"note that correction\", \"remember I said\", \"log this correction\".",
        """# Correct

A correction is the human rejecting or changing work already produced. It is a data point,
not yet a rule.

1. Run, with the correction in the words it was said:

   ```sh
   teyla correct "<what was wrong>"
   ```

   It appends `{ts, text, cwd}` to `.teyla/corrections.jsonl` in this repo — the same file
   the capture hook writes — and prints how many are there.
2. Draft one candidate rule sentence and a scope glob from it, show both, and ask whether to
   promote it now with `teyla rule "<sentence>" --scope "<glob>"`. Do not promote on your
   own: two occurrences make a rule, one makes a note.
""",
    ),
}


class Harness:
    def __init__(self, name, home, skills_dir, hooks_path=None, hooks_kind=None, app=None):
        self.name, self.home, self.skills_dir, self.hooks_path, self.hooks_kind, self.app = name, home, skills_dir, hooks_path, hooks_kind, app

    def present(self) -> bool:
        return self.home.is_dir() or (self.app is not None and pathlib.Path(self.app).exists())


def harnesses(home: pathlib.Path | None = None) -> dict[str, Harness]:
    h = home or HOME
    return {
        "cursor": Harness("cursor", h / ".cursor", h / ".cursor" / "skills", h / ".cursor" / "hooks.json", "cursor",
                          app="/Applications/Cursor.app"),
        "codex": Harness("codex", h / ".codex", h / ".codex" / "skills"),
        "grok": Harness("grok", h / ".grok", h / ".grok" / "skills", h / ".grok" / "hooks" / "teyla.json", "grok"),
        "hermes": Harness("hermes", h / ".hermes", h / ".hermes" / "skills" / "teyla", h / ".hermes" / "config.yaml", "hermes"),
    }


# --- skills ---------------------------------------------------------------------------------

def _split_frontmatter(text: str) -> tuple[dict, str]:
    from .plugins import _frontmatter
    fm = _frontmatter(text)
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                return fm, "\n".join(lines[i + 1:]).lstrip("\n")
    return fm, text


def _neutral(body: str) -> str:
    return (body.replace("`/teyla:rule`", "`teyla rule`").replace("/teyla:rule", "`teyla rule`")
                .replace("`/teyla:correct`", "`teyla correct`").replace("/teyla:correct", "`teyla correct`"))


def render_skill(name: str, harness: str, plugin: pathlib.Path | None = None) -> str:
    """The SKILL.md text for one skill in one harness."""
    plugin = plugin or plugin_dir()
    if name in CLI_SKILLS:
        description, body = CLI_SKILLS[name]
        source = "plugin/commands/" + name.split("-", 1)[1] + ".md"
        fm = {"name": name, "description": description}
    else:
        src = plugin / "skills" / name / "SKILL.md"
        fm, body = _split_frontmatter(src.read_text())
        fm = {"name": f"teyla-{fm.get('name', name)}", "description": fm.get("description", "")}
        body = _neutral(body)
        source = f"plugin/skills/{name}/SKILL.md"
    head = ["---", f"name: {fm['name']}", f"description: {fm['description']}"]
    if harness == "cursor":
        head.append("disable-model-invocation: false")
    head.append("---")
    note = f"<!-- generated by `teyla harness sync` (teyla {__version__}) from {source} — edit the source, not this copy -->"
    return "\n".join(head) + "\n\n" + note + "\n\n" + body.rstrip("\n") + "\n"


def skill_names() -> list[str]:
    return [f"teyla-{n}" for n in PLUGIN_SKILLS] + list(CLI_SKILLS)


def _skill_path(h: Harness, skill: str) -> pathlib.Path:
    return h.skills_dir / skill / "SKILL.md"


def _sync_skills(h: Harness, dry: bool) -> list[str]:
    out = []
    for src_name, skill in zip(list(PLUGIN_SKILLS) + list(CLI_SKILLS), skill_names()):
        want = render_skill(src_name, h.name)
        p = _skill_path(h, skill)
        if p.exists() and p.read_text() == want:
            continue
        if not dry:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(want)
        out.append(f"{h.name}: {'would write' if dry else 'wrote'} {p}")
    return out


# --- hooks ----------------------------------------------------------------------------------

def _sync_scripts(dry: bool, plugin: pathlib.Path | None = None) -> list[str]:
    plugin = plugin or plugin_dir()
    out = []
    for name in HOOK_SCRIPTS:
        src, dst = plugin / "hooks" / name, HOOKS_DIR / name
        if dst.exists() and dst.read_text() == src.read_text():
            continue
        if not dry:
            HOOKS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        out.append(f"{'would copy' if dry else 'copied'} {name} → {dst}")
    return out


def _cursor_hooks(existing: dict | None) -> dict:
    """Cursor's ~/.cursor/hooks.json with Teyla's two entries present, everything else kept."""
    d = dict(existing or {})
    d.setdefault("version", 1)
    hooks = dict(d.get("hooks") or {})
    for event, script in (("sessionStart", "session-start.sh"), ("beforeSubmitPrompt", "capture-correction.sh")):
        entries = [e for e in (hooks.get(event) or []) if not str(e.get("command", "")).startswith(str(HOOKS_DIR))]
        entries.append({"command": str(HOOKS_DIR / script), "type": "command", "timeout": 5})
        hooks[event] = entries
    d["hooks"] = hooks
    return d


def _grok_hooks() -> dict:
    return {"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": str(HOOKS_DIR / "session-start.sh"), "timeout": 5}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": str(HOOKS_DIR / "capture-correction.sh"), "timeout": 5}]}],
    }}


HERMES_BEGIN = "# teyla-hooks begin (written by `teyla harness sync`; delete the block to undo)"
HERMES_END = "# teyla-hooks end"


def hermes_block() -> str:
    return "\n".join([
        HERMES_BEGIN,
        "hooks:",
        "  on_session_start:",
        f'    - command: "{HOOKS_DIR / "session-start.sh"}"',
        "      timeout: 5",
        "  pre_llm_call:",
        f'    - command: "{HOOKS_DIR / "capture-correction.sh"}"',
        "      timeout: 5",
        HERMES_END,
    ]) + "\n"


def _sync_hooks(h: Harness, dry: bool) -> list[str]:
    if not h.hooks_kind:
        return []
    p = h.hooks_path
    if h.hooks_kind == "cursor":
        existing = None
        if p.exists():
            try:
                existing = json.loads(p.read_text())
            except ValueError:
                return [f"cursor: {p} is not valid JSON — not touched; add the two entries by hand (teyla harness status shows them)"]
        want = _cursor_hooks(existing)
        if existing == want:
            return []
        if not dry:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(want, indent=2) + "\n")
        return [f"cursor: {'would write' if dry else 'wrote'} sessionStart + beforeSubmitPrompt into {p}"]
    if h.hooks_kind == "grok":
        want = json.dumps(_grok_hooks(), indent=2) + "\n"
        if p.exists() and p.read_text() == want:
            return []
        if not dry:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(want)
        return [f"grok: {'would write' if dry else 'wrote'} SessionStart + UserPromptSubmit into {p}"]
    if h.hooks_kind == "hermes":
        if not p.exists():
            return [f"hermes: no {p}; hooks not written (Hermes writes it on first run — sync again after)"]
        text = p.read_text()
        if HERMES_BEGIN in text:
            start, end = text.index(HERMES_BEGIN), text.index(HERMES_END) + len(HERMES_END) + 1
            if text[start:end] == hermes_block():
                return []
            new = text[:start] + hermes_block() + text[end:]
        elif any(line.startswith("hooks:") for line in text.splitlines()):
            return [f"hermes: {p} already has a top-level `hooks:` block — add these entries to it by hand:\n"
                    + "\n".join("    " + l for l in hermes_block().splitlines()[1:-1])]
        else:
            new = text.rstrip("\n") + "\n\n" + hermes_block()
        if not dry:
            p.write_text(new)
        return [f"hermes: {'would append' if dry else 'appended'} on_session_start + pre_llm_call shell hooks to {p} "
                "(Hermes asks once per hook before running it)"]
    return []


def hooks_wired(h: Harness) -> bool | None:
    """True/False, or None when the harness has no hook mechanism Teyla uses."""
    if not h.hooks_kind:
        return None
    p = h.hooks_path
    if not p.exists():
        return False
    if h.hooks_kind == "cursor":
        try:
            return json.loads(p.read_text()) == _cursor_hooks(json.loads(p.read_text()))
        except ValueError:
            return False
    if h.hooks_kind == "grok":
        return p.read_text() == json.dumps(_grok_hooks(), indent=2) + "\n"
    if h.hooks_kind == "hermes":
        return hermes_block() in p.read_text()
    return None


# --- status / sync ---------------------------------------------------------------------------

def status(home: pathlib.Path | None = None) -> list[dict]:
    from . import policy
    pol = policy.status()
    out = []
    for name, h in harnesses(home).items():
        if not h.present():
            out.append(dict(harness=name, present=False))
            continue
        skills = sum(1 for src, s in zip(list(PLUGIN_SKILLS) + list(CLI_SKILLS), skill_names())
                     if _skill_path(h, s).exists() and _skill_path(h, s).read_text() == render_skill(src, name))
        scripts = all((HOOKS_DIR / s).exists() for s in HOOK_SCRIPTS)
        wired = hooks_wired(h)
        out.append(dict(harness=name, present=True, policy=pol.get(name), skills=skills, skills_total=len(skill_names()),
                        hooks=(wired and scripts) if wired is not None else None, hooks_path=str(h.hooks_path) if h.hooks_path else None))
    return out


def render_status(rows: list[dict]) -> str:
    lines = [f"{'harness':8} {'present':8} {'policy':8} {'skills':8} hooks"]
    for r in rows:
        if not r["present"]:
            lines.append(f"{r['harness']:8} {'absent':8}")
            continue
        pol = {True: "wired", False: "NOT WIRED", None: "-"}[r.get("policy")]
        hooks = {True: "wired", False: "NOT WIRED", None: "n/a"}[r.get("hooks")]
        lines.append(f"{r['harness']:8} {'yes':8} {pol:8} {r['skills']}/{r['skills_total']:<6} {hooks}" + (f"  ({r['hooks_path']})" if r.get("hooks_path") else ""))
    return "\n".join(lines)


def sync(dry: bool = False, home: pathlib.Path | None = None) -> list[str]:
    out = []
    hs = {n: h for n, h in harnesses(home).items() if h.present()}
    if not hs:
        return ["no other harness on this machine (no ~/.cursor, ~/.codex, ~/.grok, ~/.hermes)"]
    if any(h.hooks_kind for h in hs.values()):
        out += _sync_scripts(dry)
    for h in hs.values():
        out += _sync_skills(h, dry)
        out += _sync_hooks(h, dry)
    return out or [f"in sync: {', '.join(hs)}"]


def cmd_harness(args):
    if args.action == "status":
        print(render_status(status()))
        return 0
    for line in sync(dry=args.dry):
        print(line)
    return 0


def register(sp):
    q = sp.add_parser("harness", help="the plugin's skills, hooks and policy in Cursor, Codex, Grok and Hermes")
    q.set_defaults(fn=cmd_harness)
    q.add_argument("action", choices=["status", "sync"])
    q.add_argument("--dry", action="store_true")
    return q

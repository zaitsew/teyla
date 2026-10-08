"""`teyla harness status|sync` — the same skills, hooks and policy in Cursor, Codex, Grok and
Hermes that the Claude Code plugin gives Claude.

What each harness reads, verified against the harness's own
on-disk docs (Cursor 3.19.7 `~/.cursor/skills-cursor/*/SKILL.md`; Grok CLI 1.0.0
`~/.grok/docs/user-guide/`; Hermes 0.20.4 `~/.hermes/hermes-agent/website/docs`; Codex 0.153.4
`codex --help` and `~/.codex/skills`). Codex hooks were re-checked by running
`codex exec` (0.153.4 from npm, 0.158.0-alpha.2.1 inside the ChatGPT app) against a scratch
CODEX_HOME holding a hooks.json:

  harness  policy                               skills                         hooks
  cursor   no global rules file; per-repo       ~/.cursor/skills/<name>/       ~/.cursor/hooks.json
           AGENTS.md; a user skill carries        SKILL.md (name, description,   {version:1, hooks:{sessionStart,
           ~/.agents/POLICY.md                    disable-model-invocation)      beforeSubmitPrompt: [{command}]}}
  codex    ~/.codex/AGENTS.md → POLICY.md       ~/.codex/skills/<name>/        ~/.codex/hooks.json
           (policy.py)                            SKILL.md                       {description?, hooks:{SessionStart,
                                                                                 UserPromptSubmit:[{hooks:[…]}]}}
  grok     ~/.grok/AGENTS.md → POLICY.md        ~/.grok/skills/<name>/         ~/.grok/hooks/*.json
           (policy.py); also reads               SKILL.md (also scans           {hooks:{SessionStart,
           AGENTS.md/CLAUDE.md per directory      ~/.claude and ~/.cursor)       UserPromptSubmit:[{hooks:[…]}]}}
  hermes   ~/.hermes/SOUL.md section            ~/.hermes/skills/<category>/   `hooks:` block in ~/.hermes/config.yaml
           (policy.py); AGENTS.md per repo        <name>/SKILL.md                (on_session_start, pre_llm_call ×2)

Hook scripts are one copy each in ~/.teyla/hooks/ — the plugin's own session-start.sh and
capture-correction.sh, which already read every harness's stdin shape (`prompt`, `text`,
`user_message`, Hermes's `extra.user_message`) and de-duplicate, since Grok also loads
~/.cursor/hooks.json. session-start.sh takes `--codex` (skip `codex exec` batch runs) and
`--context-json` (Hermes: the orientation as `{"context": …}` on the first turn only).

The opt-in land check (`[hooks] land_check = true`) is wired into Codex as a Stop hook running
`land-check.sh --codex` (`{"systemMessage": …}`, the field Codex documents for Stop output) —
only while the key is on: a sync with it off removes Teyla's Stop handler and keeps any other.
The context-budget hook is not: it reads Claude Code's transcript usage records and relies on
its autoCompactWindow, neither of which Codex has.

Codex parses hooks.json strictly — an unknown top-level key (anything but `description` and
`hooks`) makes it skip the whole file with "failed to parse hooks config" — so Teyla's marker
there is the command path under ~/.teyla/hooks/ plus the file's `description`, not a comment.
Codex runs a new or changed hook only after the user trusts it once ("Hooks need review" at
startup, or `/hooks`); until then it is skipped silently, `codex exec` included. Skills are rendered from the plugin's SKILL.md files with `/teyla:rule`
and `/teyla:correct` replaced by the CLI (`teyla rule`, `teyla correct`), and carry a
"generated from" line; edits go in the plugin source, and the next sync overwrites the copy.

Nothing here touches a harness that is not installed, and every write is idempotent: a second
sync with nothing changed prints "in sync".
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import stat

from . import __version__, plugin_dir

HOME = pathlib.Path.home()
HOOKS_DIR = HOME / ".teyla" / "hooks"
HOOK_SCRIPTS = ("session-start.sh", "capture-correction.sh", "land-check.sh")
PLUGIN_SKILLS = ("harvest", "adoption-review", "wiki-pass", "review")
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

   It appends `{ts, text, cwd, source: "correct"}` to this repo's file under `~/.teyla/corrections/` — the same
   file the capture hook writes, outside the repo, secrets replaced by `[redacted]` — and
   prints how many are there.
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
        "codex": Harness("codex", h / ".codex", h / ".codex" / "skills", h / ".codex" / "hooks.json", "codex"),
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
        entries = [e for e in (hooks.get(event) or []) if not str(e.get("command", "")).startswith(str(HOOKS_DIR) + "/")]
        entries.append({"command": str(HOOKS_DIR / script), "type": "command", "timeout": 5})
        hooks[event] = entries
    d["hooks"] = hooks
    return d


CODEX_DESCRIPTION = ("Entries whose command is under ~/.teyla/hooks/ are written by `teyla harness sync`; "
                     "delete those entries (or this file, if nothing else is in it) to undo.")


def _is_teyla_handler(handler) -> bool:
    return isinstance(handler, dict) and str(handler.get("command", "")).startswith(str(HOOKS_DIR) + "/")


def _is_teyla_group(group) -> bool:
    return isinstance(group, dict) and any(_is_teyla_handler(h) for h in (group.get("hooks") or []))


def _without_teyla(groups) -> list:
    """`groups` minus Teyla's handlers. A user's handler that shares a group with ours stays in
    that group (matcher and other keys kept); a group is dropped only once it is left empty
    (caught in review, P1)."""
    out = []
    for g in groups or []:
        if not _is_teyla_group(g):
            out.append(g)
            continue
        rest = [h for h in g["hooks"] if not _is_teyla_handler(h)]
        if rest:
            out.append({**g, "hooks": rest})
    return out


def _land_check_on() -> bool:
    from . import config
    try:
        return config.hook_on("land_check")
    except Exception:  # noqa: BLE001 — an unreadable config wires nothing optional
        return False


def _codex_hooks(existing: dict | None, land_check: bool | None = None) -> dict:
    """~/.codex/hooks.json with Teyla's SessionStart and UserPromptSubmit groups present, every other
    group kept. Codex's shape is Claude Code's (`{hooks: {Event: [{matcher?, hooks: [{type, command,
    timeout}]}]}}`); plain SessionStart stdout reaches the model as `hooks.additional_context`.
    A Stop group running `land-check.sh --codex` is present exactly while `[hooks] land_check` is
    on (`land_check` None reads the config); turned off, Teyla's Stop handler goes and the user's
    Stop groups stay."""
    d = dict(existing or {})
    d.setdefault("description", CODEX_DESCRIPTION)
    hooks = dict(d.get("hooks") or {})
    for event, command in (("SessionStart", f"{HOOKS_DIR / 'session-start.sh'} --codex"),
                           ("UserPromptSubmit", str(HOOKS_DIR / "capture-correction.sh"))):
        groups = _without_teyla(hooks.get(event))
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 5}]})
        hooks[event] = groups
    land = _land_check_on() if land_check is None else land_check
    before = hooks.get("Stop")
    stop = _without_teyla(before)
    if land:
        stop.append({"hooks": [{"type": "command", "command": f"{HOOKS_DIR / 'land-check.sh'} --codex", "timeout": 10}]})
    if stop:
        hooks["Stop"] = stop
    elif before:  # only Teyla's handler was there: drop the event, not a user's empty list
        del hooks["Stop"]
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
        # on_session_start's output is ignored; a pre_llm_call hook's `{"context": …}` is added
        # to the user message (hermes-agent 0.20.4 agent/shell_hooks.py). --context-json prints
        # the orientation on the first turn only.
        f'    - command: "{HOOKS_DIR / "session-start.sh"} --context-json"',
        "      timeout: 5",
        HERMES_END,
    ]) + "\n"


def _hermes_present_pairs(text: str) -> set[tuple[str, str]]:
    """(event, command) of every hook under the top-level `hooks:` block, whatever the quoting.
    Hermes 0.21.5 rewrites config.yaml on update: comments (Teyla's markers) and quotes go, the
    entries stay — so Teyla recognises its hooks by what they run, as it does for Codex. An
    event's entries are the list items at the indent of its first item (indented or YAML's
    indentless style); a `- command:` nested deeper is inside an entry, not a hook."""
    pairs, event, item_indent, inside = set(), None, None, False
    bare_entry, entry_indent = False, None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            inside = line.split("#", 1)[0].rstrip() == "hooks:"
            event, bare_entry = None, False
            continue
        if not inside:
            continue
        s, indent = line.split(" #", 1)[0].strip(), len(line) - len(line.lstrip())
        if indent == 2 and not s.startswith("-"):
            event, item_indent, bare_entry = (s[:-1] if s.endswith(":") else None), None, False
            continue
        bare = s == "-"  # a list item whose mapping starts on the next line
        if not event or not (bare or s.startswith("- ")):
            if bare_entry and indent > item_indent:
                entry_indent = indent if entry_indent is None else entry_indent
                if indent == entry_indent and s.startswith("command:"):
                    pairs.add((event, s.split(":", 1)[1].strip().strip("\"'")))
            continue
        if item_indent is None:
            item_indent = indent
        if indent == item_indent:
            bare_entry, entry_indent = bare, None  # a new entry of the event
        if indent == item_indent and s.startswith("- command:"):
            pairs.add((event, s.split(":", 1)[1].strip().strip("\"'")))
    return pairs


def _hermes_missing(text: str) -> list[tuple[str, str]]:
    have = _hermes_present_pairs(text)
    return [pair for pair in _hermes_pairs() if pair not in have]


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
    if h.hooks_kind == "codex":
        existing = None
        if p.exists():
            try:
                existing = json.loads(p.read_text())
            except ValueError:
                return [f"codex: {p} is not valid JSON — not touched; add the two entries by hand (teyla harness status shows them)"]
        want = _codex_hooks(existing)
        if existing == want:
            return []
        if not dry:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(want, indent=2) + "\n")
        events = "SessionStart + UserPromptSubmit" + (" + Stop (land check)" if "Stop" in (want.get("hooks") or {})
                                                         and any(_is_teyla_group(g) for g in want["hooks"]["Stop"]) else "")
        return [f"codex: {'would write' if dry else 'wrote'} {events} into {p} — "
                "open Codex once and trust them (\"Hooks need review\" → Trust, or /hooks); until then Codex skips them"]
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
            missing = _hermes_missing(text)
            if not missing:
                return []  # Teyla's entries are there without their markers (Hermes rewrote the file)
            lines, last = [], None
            for event, cmd in missing:
                if event != last:
                    lines.append(f"  {event}:")
                    last = event
                lines += [f'    - command: "{cmd}"', "      timeout: 5"]
            return [f"hermes: {p} already has a top-level `hooks:` block — add these entries under it by hand:\n"
                    + "\n".join("    " + l for l in lines)]
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
    if h.hooks_kind in ("cursor", "codex"):
        merge = _cursor_hooks if h.hooks_kind == "cursor" else _codex_hooks
        try:
            d = json.loads(p.read_text())
            return d == merge(d)
        except (ValueError, AttributeError, TypeError):
            return False
    if h.hooks_kind == "grok":
        return p.read_text() == json.dumps(_grok_hooks(), indent=2) + "\n"
    if h.hooks_kind == "hermes":
        text = p.read_text()
        return hermes_block() in text or not _hermes_missing(text)
    return None


# --- trust: has the person approved the hooks in the harness itself? -------------------------
#
# Codex and Hermes both refuse to run a hook nobody approved, and neither says so in a batch
# run. "wired" without "approved" is a hook that never fires, so status reports both.

# Codex's trust-event label for each hook event (the `hook_event_key_label` in
# codex-rs/hooks/src/engine/discovery.rs, visible in `hooks/list` keys).
# "stop" follows the same snake_case rule; it was not re-read from discovery.rs when the land
# check was added, so a Stop handler reported untrusted after trusting it is the
# first thing to check there.
_CODEX_EVENT_LABELS = {"SessionStart": "session_start", "UserPromptSubmit": "user_prompt_submit", "Stop": "stop"}


def codex_hook_hash(event: str, handler: dict, matcher: str | None = None) -> str:
    """The `currentHash` Codex compares with `[hooks.state."<key>"].trusted_hash` in config.toml:
    sha256 of the compact, key-sorted JSON of {event_name, matcher?, hooks: [normalized handler]}
    (codex-rs/hooks/src/engine/discovery.rs `hook_hash` → codex-rs/config/src/fingerprint.rs
    `version_for_toml`). Reproduced against `codex app-server` `hooks/list` 0.153.4,
    and a config.toml carrying it made `codex exec` run the hook without
    --dangerously-bypass-hook-trust."""
    import hashlib
    h = {"type": handler.get("type", "command"), "command": handler["command"],
         "timeout": handler.get("timeout", 600), "async": bool(handler.get("async", False))}
    if handler.get("statusMessage"):
        h["statusMessage"] = handler["statusMessage"]
    ident = {"event_name": _CODEX_EVENT_LABELS.get(event, event), "hooks": [h]}
    if matcher is not None:
        ident["matcher"] = matcher
    blob = json.dumps(ident, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode()).hexdigest()


def _codex_trust(h: Harness) -> tuple[int, int, list[str]]:
    """(approved, total, states) for Teyla's own entries in ~/.codex/hooks.json."""
    import tomllib
    try:
        d = json.loads(h.hooks_path.read_text())
    except (OSError, ValueError):
        return 0, 0, []
    try:
        state = (tomllib.loads((h.home / "config.toml").read_text()).get("hooks") or {}).get("state") or {}
    except (OSError, ValueError):
        state = {}
    approved, total, states = 0, 0, []
    for event in _CODEX_EVENT_LABELS:
        for gi, group in enumerate((d.get("hooks") or {}).get(event) or []):
            if not _is_teyla_group(group):
                continue
            for hi, handler in enumerate(group.get("hooks") or []):
                if not _is_teyla_handler(handler):
                    continue  # a user's handler in a shared group is not ours to count (caught in review)
                total += 1
                rec = state.get(f"{h.hooks_path}:{_CODEX_EVENT_LABELS[event]}:{gi}:{hi}") or {}
                want = codex_hook_hash(event, handler, group.get("matcher"))
                if rec.get("enabled") is False:
                    states.append(f"{event} disabled")
                elif rec.get("trusted_hash") == want:
                    approved += 1
                elif rec.get("trusted_hash"):
                    states.append(f"{event} modified since trusted")
                else:
                    states.append(f"{event} untrusted")
    return approved, total, states


def _hermes_pairs() -> list[tuple[str, str]]:
    """(event, command) for every hook in hermes_block(), as Hermes's allowlist records them."""
    pairs, event = [], None
    for line in hermes_block().splitlines():
        s = line.strip()
        if s.endswith(":") and not s.startswith(("-", "#")) and s != "hooks:":
            event = s[:-1]
        elif s.startswith("- command:"):
            pairs.append((event, s.split(":", 1)[1].strip().strip('"')))
    return pairs


_BLOCK_SCALAR = re.compile(r"^(\s*)((?:-\s+)*)(?P<key>[^\s#][^#]*?:\s+)?[|>][+-]?\d?[+-]?\s*(?:#.*)?$")


def _block_scalar_parent(line: str) -> int | None:
    """If `line` opens a block scalar (`key: |`, `key: >-`, `- |`), the indent the scalar's lines must
    exceed: the key's column, or the dash's for a bare `- |`; else None."""
    m = _BLOCK_SCALAR.match(line)
    if not m:
        return None
    lead = len(m.group(1))
    return lead + len(m.group(2)) if m.group("key") else lead


def _flow_delta(line: str) -> int:
    """Net `{`/`[` opened by one config line, ignoring quoted text and a trailing comment."""
    d, quote, prev = 0, None, " "
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'" and prev in " \t{[,:-":
            quote = ch
        elif ch == "#" and prev in " \t":
            break
        elif ch in "{[":
            d += 1
        elif ch in "}]":
            d -= 1
        prev = ch
    return d


_HERMES_TRUTHY = {"1", "true", "yes", "on"}  # agent/shell_hooks.py `_TRUTHY`


def _hermes_auto_accept(text: str) -> bool:
    """Is `hooks_auto_accept` set, as a top-level key, to what Hermes reads as true? A commented
    line or a nested key of the same name does not count (caught in review, P2). No YAML dependency:
    only an unindented `key: value` line is looked at, and the last one wins, as in YAML loaders."""
    val, depth, block_parent = None, 0, None
    for line in text.splitlines():
        # The indented lines of a block scalar (`key: |`, `- >-`) are text, not YAML: a `}` in one
        # must not close a mapping (Codex P2).
        if block_parent is not None:
            if not line.strip() or len(line) - len(line.lstrip()) > block_parent:
                continue
            block_parent = None
        # A `{…}` / `[…]` that spans lines keeps its members out of the top level, whatever column
        # they start in: count the brackets of every line, outside quotes and comments.
        at_top = depth <= 0
        if depth <= 0:
            block_parent = _block_scalar_parent(line)
        depth += _flow_delta(line)
        m = re.match(r"hooks_auto_accept\s*:\s*(.*)$", line)
        if not m or not at_top:
            continue
        v = re.sub(r"\s+#.*$", "", m.group(1)).strip()  # trailing comment
        quoted = len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'"
        if quoted:
            v = v[1:-1]
        v = v.strip().lower()
        # Hermes: a YAML bool as is, a string if it is truthy; a bare 1 is an int, so not.
        val = v in _HERMES_TRUTHY - {"1"} or (quoted and v == "1")
    return bool(val)


def _hermes_trust(h: Harness) -> tuple[int, int, list[str]]:
    """Hermes asks once per (event, command) on a TTY and records the answer in
    ~/.hermes/shell-hooks-allowlist.json (`{"approvals": [{event, command, …}]}`); a non-TTY
    run (the desktop app, `hermes -z`) skips an unapproved hook (hermes-agent 0.20.4
    agent/shell_hooks.py `_is_allowlisted`, `_prompt_and_record`)."""
    try:
        if _hermes_auto_accept((h.home / "config.yaml").read_text()):
            n = len(_hermes_pairs())
            return n, n, []
    except OSError:
        pass
    try:
        approvals = json.loads((h.home / "shell-hooks-allowlist.json").read_text()).get("approvals") or []
    except (OSError, ValueError, AttributeError):
        approvals = []
    seen = {(a.get("event"), a.get("command")) for a in approvals if isinstance(a, dict)}
    pairs = _hermes_pairs()
    missing = [f"{e} not approved" for e, c in pairs if (e, c) not in seen]
    return len(pairs) - len(missing), len(pairs), missing


def hooks_trust(h: Harness) -> tuple[int, int, list[str]] | None:
    """(approved, total, what is not) for harnesses that gate hooks on consent; None otherwise
    (Cursor and Grok run a configured hook without asking)."""
    if h.hooks_kind == "codex":
        return _codex_trust(h)
    if h.hooks_kind == "hermes":
        return _hermes_trust(h)
    return None


TRUST_HOWTO = {
    "codex": "open Codex (`codex` in a terminal) → \"Hooks need review\" → Trust all, or /hooks",
    "hermes": "run `hermes` in a terminal once and approve each hook (`hermes hooks list` shows which)",
}


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
        trust = hooks_trust(h) if wired else None
        out.append(dict(harness=name, present=True, policy=pol.get(name), skills=skills, skills_total=len(skill_names()),
                        hooks=(wired and scripts) if wired is not None else None, hooks_path=str(h.hooks_path) if h.hooks_path else None,
                        trust=None if trust is None else {"approved": trust[0], "total": trust[1], "missing": trust[2]}))
    return out


def render_status(rows: list[dict]) -> str:
    lines = [f"{'harness':8} {'present':8} {'policy':8} {'skills':8} hooks"]
    for r in rows:
        if not r["present"]:
            lines.append(f"{r['harness']:8} {'absent':8}")
            continue
        pol = {True: "wired", False: "NOT WIRED", None: "-"}[r.get("policy")]
        hooks = {True: "wired", False: "NOT WIRED", None: "n/a"}[r.get("hooks")]
        tr = r.get("trust")
        if tr and tr["total"]:
            hooks += f", approved {tr['approved']}/{tr['total']}" if tr["approved"] == tr["total"] else f", NOT APPROVED {tr['approved']}/{tr['total']}"
        lines.append(f"{r['harness']:8} {'yes':8} {pol:8} {r['skills']}/{r['skills_total']:<6} {hooks}" + (f"  ({r['hooks_path']})" if r.get("hooks_path") else ""))
        if tr and tr["approved"] < tr["total"]:
            lines.append(f"{'':8} {'':8} {'':8} {'':8} → {TRUST_HOWTO.get(r['harness'], 'approve them in the harness')}")
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
    if args.action == "verify":
        from . import health
        return health.cmd_verify(args)
    if args.action == "status":
        print(render_status(status()))
        return 0
    for line in sync(dry=args.dry):
        print(line)
    return 0


def register(sp):
    q = sp.add_parser("harness", help="the plugin's skills, hooks and policy in Cursor, Codex, Grok and Hermes; "
                                      "`verify` checks each can do work now")
    q.set_defaults(fn=cmd_harness)
    q.add_argument("action", choices=["status", "sync", "verify"])
    q.add_argument("--dry", action="store_true")
    q.add_argument("--live", action="store_true",
                   help="verify: also send one line through each harness headless (spends a few tokens; never run by routines)")
    q.add_argument("--timeout", type=int, default=120, help="verify --live: seconds per harness")
    q.add_argument("--json", action="store_true")
    return q

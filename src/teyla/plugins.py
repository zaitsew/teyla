"""`teyla plugins` — inventory and quality pass over installed Claude Code plugins.

Born from doing this by hand: docs/case-studies/2026-09-09-corporate-pm-work-report.md
§A is a human running the skill / rule / fact test (docs/WIKI.md's "three-objects rule",
docs/MANUAL.md §1) over someone else's plugin, one skill at a time, with a script written
for the occasion. This module is that script, kept.

Reads the Claude Code plugin registry — `~/.claude/plugins/known_marketplaces.json` (what
marketplace a plugin came from, and whether its source is a local directory) and
`~/.claude/plugins/installed_plugins.json` (which version is actually loaded, and from
where) — to find plugins, then inspects each one on disk:

  - **version installed vs. working copy** — when a marketplace's source is a local
    directory, its `.claude-plugin/marketplace.json` names each plugin's subpath, and that
    subpath's own `.claude-plugin/plugin.json` carries the version actually on disk today.
    The two can differ: that is exactly how the case study's plugin showed newest-two-skills
    invocation counts of zero — the installed copy was older than the working copy.
  - **per skill**: words, lines, "over one screen" (> 60 lines), whether the description
    carries a trigger phrase a router can match (a quoted phrase, or the words "when asked
    to"), constraint-sentence count (never / always / must not / do not / don't), fact-literal
    count (long numeric ids, ticket-key patterns, URLs), and whether it mentions a second
    artifact type (a ticket *and* a workbook, say — keyword-based, so treat a hit as "worth a
    human read", not proof).
  - **pairwise description overlap** (Jaccard on word sets) across a plugin's own skills.
  - **commands, hooks, MCP servers** — counted, not read for content.
  - **rules files**, with size, flagged over 20 KB.

Verdict per skill is one of `ok`, `trim`, `split`, `move facts`, `add triggers` — see
`skill_verdict()` for the exact thresholds. It is a heuristic, tuned to match the shape of
the case study's findings, not a re-implementation of a human's judgement calls (two skills
in that report get the same verdict for different reasons a script cannot see — "already
disambiguated in-text" is not a countable fact).

Never prints a skill's, rule's, or command's own file content — only computed counts,
paths and verdicts.

    teyla plugins                 every plugin in the registry
    teyla plugins <name>          one installed plugin — "name" or "name@marketplace"
    teyla plugins <path>          a plugin directory, installed or not
    teyla plugins ... --json
"""
from __future__ import annotations

import json
import pathlib
import re

HOME = pathlib.Path.home()
PLUGINS_DIR = HOME / ".claude" / "plugins"
KNOWN_MARKETPLACES = PLUGINS_DIR / "known_marketplaces.json"
INSTALLED_PLUGINS = PLUGINS_DIR / "installed_plugins.json"

ONE_SCREEN_LINES = 60          # docs/MANUAL.md's convention; the work report's "over one screen"
SPLIT_CONSTRAINT_THRESHOLD = 8  # over-screen + this many constraint sentences: it's a ruleset too
MOVE_FACTS_THRESHOLD = 20       # this many fact literals: lift them into a reference file
OVERLAP_FLAG = 0.5              # pairwise description Jaccard at/over this is worth a look
RULES_FILE_FLAG_BYTES = 20 * 1024

CONSTRAINT_RE = re.compile(r"\b(never|always|must not|do not|don't)\b", re.I)
FACT_ID_RE = re.compile(r"(?<!\w)\d{6,}(?!\w)")
TICKET_RE = re.compile(r"\b[A-Z]{2,}-\d+\b")
URL_RE = re.compile(r"https?://\S+")
TRIGGER_RE = re.compile(r'"[^"]{2,}"|\bwhen asked to\b', re.I)

# Keyword-based, deliberately loose — a hit means "look at this by hand", not "confirmed".
ARTIFACT_PATTERNS = {
    "ticket": re.compile(r"\b(ticket|jira|issue)\b", re.I),
    "workbook": re.compile(r"\b(workbook|spreadsheet|xlsx|excel)\b", re.I),
    "wiki page": re.compile(r"\b(wiki page|confluence)\b", re.I),
    "document": re.compile(r"\bdocument\b", re.I),
    "email": re.compile(r"\be-?mail\b", re.I),
    "pull request": re.compile(r"\b(pull request|merge request)\b", re.I),
}


class PluginError(ValueError):
    pass


# --- small stdlib readers ----------------------------------------------------

def _load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _frontmatter(text: str) -> dict:
    """`key: value` lines between the first two `---` lines. Good enough for SKILL.md's
    name/description/argument-hint, which are single-line scalars in every skill this reads;
    not a general YAML parser (see teyla.wiki.parse_frontmatter for one that also does lists)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data: dict = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        data[k.strip()] = v.strip()
    return data


def _plugin_json_version(plugin_dir: pathlib.Path) -> str | None:
    return _load_json(plugin_dir / ".claude-plugin" / "plugin.json").get("version")


# --- per-skill quality pass ---------------------------------------------------

def skill_verdict(has_triggers: bool, over_one_screen: bool, constraint_sentences: int, fact_literals: int) -> str:
    """ok / trim / split / move facts / add triggers — see module docstring for the thresholds
    and why this will not reproduce every call a human report made by hand."""
    if not has_triggers:
        return "add triggers"
    if over_one_screen and constraint_sentences >= SPLIT_CONSTRAINT_THRESHOLD:
        return "split"
    if fact_literals >= MOVE_FACTS_THRESHOLD:
        return "move facts"
    if over_one_screen:
        return "trim"
    return "ok"


def analyze_skill(path: pathlib.Path) -> dict:
    text = path.read_text(errors="replace")
    fm = _frontmatter(text)
    description = fm.get("description", "")
    n_lines = len(text.splitlines())
    n_words = len(text.split())
    constraints = len(CONSTRAINT_RE.findall(text))
    facts = len(FACT_ID_RE.findall(text)) + len(TICKET_RE.findall(text)) + len(URL_RE.findall(text))
    has_triggers = bool(TRIGGER_RE.search(description))
    over_one_screen = n_lines > ONE_SCREEN_LINES
    artifacts = sorted(name for name, pat in ARTIFACT_PATTERNS.items() if pat.search(text))
    return {
        "name": fm.get("name") or path.parent.name,
        "path": str(path),
        "description": description,
        "words": n_words,
        "lines": n_lines,
        "over_one_screen": over_one_screen,
        "constraint_sentences": constraints,
        "fact_literals": facts,
        "has_triggers": has_triggers,
        "second_artifact_types": artifacts,
        "second_artifact_flag": len(artifacts) >= 2,
        "verdict": skill_verdict(has_triggers, over_one_screen, constraints, facts),
    }


def _word_set(text: str) -> set:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def jaccard(a: str, b: str) -> float:
    sa, sb = _word_set(a), _word_set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def pairwise_overlaps(skills: list[dict], flag: float = OVERLAP_FLAG) -> list[dict]:
    out = []
    for i in range(len(skills)):
        for j in range(i + 1, len(skills)):
            a, b = skills[i], skills[j]
            score = jaccard(a["description"], b["description"])
            if score >= flag:
                out.append({"a": a["name"], "b": b["name"], "jaccard": round(score, 3)})
    return out


# --- non-skill plugin assets --------------------------------------------------

def find_skills(plugin_dir: pathlib.Path) -> list[pathlib.Path]:
    d = plugin_dir / "skills"
    return sorted(d.glob("*/SKILL.md")) if d.is_dir() else []


def count_commands(plugin_dir: pathlib.Path) -> int:
    d = plugin_dir / "commands"
    return len(list(d.glob("*.md"))) if d.is_dir() else 0


def count_hooks(plugin_dir: pathlib.Path) -> int:
    """Individual hook commands declared in hooks/hooks.json — the real shape is
    `{"hooks": {"<Event>": [{"hooks": [{"type": "command", ...}, ...]}, ...]}}`, an event
    keyed at the top of a top-level "hooks" wrapper; unwrap it if present, else assume the
    file is already the events dict (a plugin that skips the wrapper still counts right)."""
    data = _load_json(plugin_dir / "hooks" / "hooks.json")
    events = data.get("hooks", data) if isinstance(data.get("hooks"), dict) else data
    n = 0
    for entries in events.values():
        if not isinstance(entries, list):
            continue
        for e in entries:
            inner = e.get("hooks") if isinstance(e, dict) else None
            n += len(inner) if isinstance(inner, list) else 1
    return n


def count_mcp_servers(plugin_dir: pathlib.Path) -> int:
    data = _load_json(plugin_dir / ".mcp.json")
    servers = data.get("mcpServers", {})
    return len(servers) if isinstance(servers, dict) else 0


def find_rules_files(plugin_dir: pathlib.Path, flag_bytes: int = RULES_FILE_FLAG_BYTES) -> list[dict]:
    out = []
    if not plugin_dir.is_dir():
        return out
    for d in sorted(plugin_dir.rglob("rules")):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            size = f.stat().st_size
            out.append({"path": str(f), "size_bytes": size, "over_20kb": size > flag_bytes})
    return out


def has_templates_dir(plugin_dir: pathlib.Path) -> bool:
    return (plugin_dir / "templates").is_dir()


# --- registry lookup: installed vs. working copy ------------------------------

def working_copy(marketplace_key: str, plugin_name: str, known_marketplaces: dict) -> tuple[pathlib.Path | None, str | None]:
    """(plugin dir, version) resolved from the marketplace's own directory source, if it has
    one. A `directory` marketplace source is used in place (no cache copy of the marketplace
    itself) — see known_marketplaces.json's shape — so this is the actual working tree the
    plugin's author edits."""
    mp = known_marketplaces.get(marketplace_key)
    if not mp:
        return None, None
    src = mp.get("source", {})
    if src.get("source") != "directory":
        return None, None
    root = pathlib.Path(mp.get("installLocation") or src.get("path", "")).expanduser()
    manifest = _load_json(root / ".claude-plugin" / "marketplace.json")
    for entry in manifest.get("plugins", []):
        if entry.get("name") == plugin_name:
            plugin_dir = (root / entry.get("source", "./")).resolve()
            return plugin_dir, _plugin_json_version(plugin_dir)
    return None, None


def resolve_targets(arg: str | None) -> list[dict]:
    """[{name, marketplace, version_installed, install_path, working_path, working_version}]
    for every plugin `arg` could mean: a directory (used directly, no registry lookup), a
    bare/`name@marketplace` key into installed_plugins.json, or (no arg) everything in it."""
    if arg:
        p = pathlib.Path(arg).expanduser()
        if p.is_dir():
            return [{"name": p.name, "marketplace": None, "version_installed": None,
                      "install_path": None, "working_path": str(p.resolve()),
                      "working_version": _plugin_json_version(p)}]

    installed = _load_json(INSTALLED_PLUGINS).get("plugins", {})
    known = _load_json(KNOWN_MARKETPLACES)
    out = []
    for key, entries in installed.items():
        plugin_name, _, marketplace = key.partition("@")
        if arg and arg not in (key, plugin_name):
            continue
        entry = (entries or [{}])[0]
        wpath, wversion = working_copy(marketplace, plugin_name, known)
        out.append({
            "name": plugin_name, "marketplace": marketplace or None,
            "version_installed": entry.get("version"),
            "install_path": entry.get("installPath"),
            "working_path": str(wpath) if wpath else None,
            "working_version": wversion,
        })
    if arg and not out:
        raise PluginError(f"{arg!r} is not an installed plugin (name or name@marketplace) and not a directory")
    return out


# --- assembling a report -------------------------------------------------------

def analyze_plugin_dir(plugin_dir: pathlib.Path, *, name: str | None = None) -> dict:
    skills = [analyze_skill(p) for p in find_skills(plugin_dir)]
    return {
        "name": name or plugin_dir.name,
        "path": str(plugin_dir),
        "skills": skills,
        "skills_over_one_screen": sum(1 for s in skills if s["over_one_screen"]),
        "pairwise_overlaps": pairwise_overlaps(skills),
        "commands": count_commands(plugin_dir),
        "hooks": count_hooks(plugin_dir),
        "mcp_servers": count_mcp_servers(plugin_dir),
        "rules_files": find_rules_files(plugin_dir),
        "has_templates_dir": has_templates_dir(plugin_dir),
    }


def _empty_report(name: str) -> dict:
    return {"name": name, "path": None, "skills": [], "skills_over_one_screen": 0,
             "pairwise_overlaps": [], "commands": 0, "hooks": 0, "mcp_servers": 0,
             "rules_files": [], "has_templates_dir": False}


def build_report(arg: str | None = None) -> list[dict]:
    reports = []
    for target in resolve_targets(arg):
        scan_dir = target["working_path"] or target["install_path"]
        report = analyze_plugin_dir(pathlib.Path(scan_dir), name=target["name"]) if scan_dir else _empty_report(target["name"])
        installed_v, working_v = target["version_installed"], target["working_version"]
        report.update({
            "marketplace": target["marketplace"],
            "version_installed": installed_v,
            "working_version": working_v,
            "version_mismatch": bool(installed_v and working_v and installed_v != working_v),
            "scanned": "working copy" if target["working_path"] else ("installed copy" if target["install_path"] else "-"),
        })
        reports.append(report)
    return reports


# --- rendering -----------------------------------------------------------------

def render_table(reports: list[dict]) -> str:
    if not reports:
        return "(no plugins found)\n"
    lines = []
    for r in reports:
        title = r["name"] + (f"@{r['marketplace']}" if r.get("marketplace") else "")
        vers = []
        if r.get("version_installed"):
            vers.append(f"installed {r['version_installed']}")
        if r.get("working_version"):
            vers.append(f"working {r['working_version']}")
        if r.get("version_mismatch"):
            vers.append("MISMATCH")
        lines.append(f"## {title}  ({', '.join(vers) or '-'})  scanned: {r.get('scanned', '-')}")
        lines.append(f"  commands: {r['commands']}  hooks: {r['hooks']}  mcp servers: {r['mcp_servers']}"
                      f"  templates dir: {'yes' if r['has_templates_dir'] else 'no'}")
        if r["skills"]:
            lines.append(f"  {'skill':28} {'words':>6} {'lines':>6} {'screen':>7} {'constr':>6} {'facts':>6} {'trig':>4}  verdict")
            for s in r["skills"]:
                lines.append(f"  {s['name'][:28]:28} {s['words']:6} {s['lines']:6} "
                              f"{('over' if s['over_one_screen'] else 'ok'):>7} {s['constraint_sentences']:6} "
                              f"{s['fact_literals']:6} {('y' if s['has_triggers'] else 'n'):>4}  {s['verdict']}"
                              + ("  (2nd artifact)" if s["second_artifact_flag"] else ""))
        else:
            lines.append("  (no skills found)")
        if r["pairwise_overlaps"]:
            lines.append("  description overlap:")
            for o in r["pairwise_overlaps"]:
                lines.append(f"    {o['a']} <-> {o['b']}: {o['jaccard']}")
        if r["rules_files"]:
            lines.append("  rules files:")
            for rf in r["rules_files"]:
                lines.append(f"    {rf['path']}  {rf['size_bytes']}B" + (" OVER 20KB" if rf["over_20kb"] else ""))
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_json(reports: list[dict]) -> dict:
    return {"plugins": reports}


# --- CLI -------------------------------------------------------------------------

def cmd_plugins(args):
    try:
        reports = build_report(args.target)
    except PluginError as e:
        print(f"error: {e}")
        return 1
    if args.json:
        print(json.dumps(render_json(reports), indent=2))
    else:
        print(render_table(reports), end="")
    return 0


def register(sp):
    """Add `teyla plugins` to an argparse subparsers object."""
    q = sp.add_parser("plugins", help="inventory + skill/rule/fact quality pass over installed Claude Code plugins")
    q.set_defaults(fn=cmd_plugins)
    q.add_argument("target", nargs="?",
                    help="a plugin name, name@marketplace, or a path to a plugin directory (default: every installed plugin)")
    q.add_argument("--json", action="store_true")
    return q

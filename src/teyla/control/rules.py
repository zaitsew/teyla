"""The rules that govern one run, loaded from the product repo.

Two sources, because two harnesses read two files:

    <repo>/.claude/rules/*.md    frontmatter `globs:` scopes each rule to paths
    <repo>/AGENTS.md             the `## Rules` section, unscoped

Rules are matched by **exact scope**, never by similarity. The manual is blunt
about why: missing a fact costs a worse draft, missing a rule costs a repeated
mistake, and the rule you most need is precisely the one the draft does not
resemble — "never mention pricing in a first message" ranks last in a similarity
search exactly when it is doing its job. So a rule applies to a run when its
glob matches one of the routine's declared context paths, or when it declares no
globs at all, and never because it read as relevant.

The ids returned here (the filenames, and `AGENTS.md#rules`) are what the
receipt records under "rule ids". A receipt naming the rules that governed the
run is the difference between an audit trail and a log line.
"""
from __future__ import annotations

import fnmatch
import pathlib
import re

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.S)
AGENTS_RULES_RE = re.compile(r"^##\s+Rules\s*$(.*?)(?=^##\s|\Z)", re.M | re.S)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """A minimal YAML-ish frontmatter reader: `key: value` and `- item` lists only.

    Teyla is stdlib-only, so there is no YAML parser to reach for. Rule files are
    written by `/teyla:rule` and are one or two keys deep, so this covers them; a
    rule file with structure this cannot read still loads, it just loads unscoped —
    which errs toward applying the rule rather than silently dropping it."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    key = None
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(line.lstrip()[2:].strip().strip("\"'"))
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            key = k.strip()
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                meta[key] = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()]
            elif v:
                meta[key] = v.strip("\"'")
            else:
                meta[key] = []
    return meta, text[m.end():]


def _globs_of(meta: dict) -> list[str]:
    raw = meta.get("globs") or meta.get("glob") or meta.get("scope") or []
    if isinstance(raw, str):
        return [g.strip() for g in raw.split(",") if g.strip()]
    return [str(g).strip() for g in raw if str(g).strip()]


def glob_matches(pattern: str, path: str) -> bool:
    """`startup/combra/gtm/**` matches `startup/combra/gtm/x-outbound/NOTES.md`, and also
    the directory `startup/combra/gtm` itself — a routine whose context is the folder
    must pick up the rules scoped to the folder."""
    pattern, path = pattern.strip().rstrip("/"), str(path).strip().rstrip("/")
    if not pattern:
        return False
    if fnmatch.fnmatch(path, pattern):
        return True
    if pattern.endswith("/**"):
        base = pattern[:-3]
        if path == base or path.startswith(base + "/") or fnmatch.fnmatch(path, base):
            return True
    # A rule scoped to a file inside a directory the routine names as context.
    if fnmatch.fnmatch(pattern, path + "/*") or pattern.startswith(path + "/"):
        return True
    return False


def load(repo, context_paths=()) -> list[dict]:
    """Every rule governing a run over `context_paths`, as
    `[{"id", "globs", "text", "source"}]`, rule files first then AGENTS.md."""
    repo = pathlib.Path(repo).expanduser()
    context_paths = [str(c).strip() for c in (context_paths or []) if str(c).strip()]
    out: list[dict] = []

    rules_dir = repo / ".claude" / "rules"
    if rules_dir.is_dir():
        for f in sorted(rules_dir.glob("*.md")):
            if f.name.upper() == "README.MD":
                continue
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            globs = _globs_of(meta)
            if globs and context_paths:
                if not any(glob_matches(g, c) for g in globs for c in context_paths):
                    continue
            elif globs and not context_paths:
                # The routine declares no context, so nothing can be matched against.
                # A scoped rule is skipped rather than assumed to apply everywhere.
                continue
            body = body.strip()
            if body:
                out.append({"id": f.name, "globs": globs, "text": body, "source": str(f)})

    agents = repo / "AGENTS.md"
    if agents.exists():
        try:
            m = AGENTS_RULES_RE.search(agents.read_text(errors="replace"))
        except OSError:
            m = None
        if m and m.group(1).strip():
            out.append({"id": "AGENTS.md#rules", "globs": [], "text": m.group(1).strip(), "source": str(agents)})

    return out


def render(rules) -> str:
    """The rules block injected into an agent prompt. Ids are included so the model can
    name the rule it is following and the receipt and the transcript agree."""
    if not rules:
        return "(no rules are on file for this scope)"
    parts = []
    for r in rules:
        scope = f" (scope: {', '.join(r['globs'])})" if r.get("globs") else ""
        parts.append(f"### {r['id']}{scope}\n{r['text']}")
    return "\n\n".join(parts)


def ids(rules) -> list[str]:
    return [r["id"] for r in rules]

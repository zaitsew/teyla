"""`teyla wiki` — the facts store as an LLM-maintained wiki.

A wiki is a directory of plain markdown pages: `index.md`, `pages/<slug>.md`,
`inbox.md`, `log.md`. Plain enough to live in a GitHub repo, a GitLab Wiki (a
git repo of `.md` files — this layout works there unchanged), or `~/ops`.

The `wiki-pass` skill (plugin/skills/wiki-pass/SKILL.md) is where an agent
actually writes and updates pages from a session's sources. This module is
the mechanical half: scaffold the layout, report its health, check its
internal consistency, and flip a page from agent-drafted to human-confirmed.
See docs/WIKI.md for the full conventions (frontmatter fields, the human
loop, the three-objects rule).

    teyla wiki init <path>            create the layout (idempotent)
    teyla wiki status <path> [--json] pages / drafts / confirmed / stale / inbox
    teyla wiki lint <path>            frontmatter + index consistency, exit 1 on failure
    teyla wiki confirm <path> <slug>  mark a page confirmed_by: human

Frontmatter is parsed with a tiny stdlib parser — `key: value` lines, and a
list under a key whose value is empty, as `- item` lines. No PyYAML: the
shape of a wiki page's frontmatter is small and fixed enough not to need it.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

STALE_DAYS = 90
REQUIRED_FIELDS = ("title", "summary", "sources", "last_verified", "confirmed_by", "status")
CONFIRMED_BY_VALUES = ("human", "agent")
STATUS_VALUES = ("draft", "confirmed", "stale")

INDEX = "index.md"
INBOX = "inbox.md"
LOG = "log.md"
PAGES_DIR = "pages"


class WikiError(ValueError):
    pass


# --- frontmatter: a tiny stdlib parser ---------------------------------------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """(frontmatter dict, body). No frontmatter (no leading '---' line) → ({}, text)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    data: dict = {}
    key = None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("- ") and isinstance(data.get(key), list):
            data[key].append(stripped[2:].strip())
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            data[key] = [] if value == "" else value

    if end is None:
        raise WikiError("frontmatter opened with '---' but never closed")

    body = "\n".join(lines[end + 1:])
    return data, body.lstrip("\n")


def render_frontmatter(data: dict) -> str:
    """Inverse of parse_frontmatter, with the known fields first in a fixed order."""
    ordered_keys = [k for k in REQUIRED_FIELDS if k in data]
    ordered_keys += [k for k in data if k not in REQUIRED_FIELDS]
    lines = ["---"]
    for key in ordered_keys:
        value = data[key]
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {item}" for item in value)
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines)


def render_page(data: dict, body: str) -> str:
    body = body.strip("\n")
    return render_frontmatter(data) + "\n\n" + body + "\n" if body else render_frontmatter(data) + "\n"


def read_page(path: pathlib.Path) -> tuple[dict, str]:
    return parse_frontmatter(path.read_text())


def write_page(path: pathlib.Path, data: dict, body: str) -> None:
    path.write_text(render_page(data, body))


def _parse_date(value) -> dt.date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


# --- layout -------------------------------------------------------------------

def pages_dir(path: pathlib.Path) -> pathlib.Path:
    return path / PAGES_DIR


def list_pages(path: pathlib.Path) -> list[pathlib.Path]:
    d = pages_dir(path)
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.md") if p.name != ".gitkeep")


def slug_for(page_path: pathlib.Path) -> str:
    return page_path.stem


def _page_path(path: pathlib.Path, slug: str) -> pathlib.Path:
    slug = slug[:-3] if slug.endswith(".md") else slug
    return pages_dir(path) / f"{slug}.md"


# --- init -----------------------------------------------------------------------

def init(path: str) -> list[str]:
    """Create the wiki layout at `path` from templates/wiki/. Idempotent: an
    existing file is left alone and reported as SKIP."""
    from . import templates_dir

    dest = pathlib.Path(path).expanduser()
    src_root = templates_dir() / "wiki"
    if not src_root.is_dir():
        raise WikiError(f"template root missing: {src_root}")

    report = []
    for src in sorted(src_root.rglob("*")):
        if src.is_dir():
            continue
        rel = src.relative_to(src_root)
        out = dest / rel
        if out.exists():
            report.append(f"SKIP {out} (already exists)")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(src.read_text())
        report.append(f"wrote {out}")
    return report


# --- status -----------------------------------------------------------------------

def _bucket(fm: dict, today: dt.date) -> str:
    """One of 'draft' / 'confirmed' / 'stale' — stale wins even over a page
    that declares itself confirmed, because last_verified is the fact that
    actually decays."""
    verified = _parse_date(fm.get("last_verified"))
    if verified is not None and (today - verified).days > STALE_DAYS:
        return "stale"
    if fm.get("status") == "confirmed" and fm.get("confirmed_by") == "human":
        return "confirmed"
    return "draft"


_ENTRIES_MARKER = "<!-- entries below this line -->"


def _inbox_count(path: pathlib.Path) -> int:
    p = path / INBOX
    if not p.exists():
        return 0
    lines = p.read_text().splitlines()
    if _ENTRIES_MARKER in lines:
        lines = lines[lines.index(_ENTRIES_MARKER) + 1:]
    return sum(1 for line in lines if line.strip().startswith("- "))


def status(path: str, *, today: dt.date | None = None) -> dict:
    dest = pathlib.Path(path).expanduser()
    today = today or dt.datetime.now(dt.timezone.utc).date()

    pages = []
    for p in list_pages(dest):
        fm, _ = read_page(p)
        pages.append({"slug": slug_for(p), "title": fm.get("title", ""), "bucket": _bucket(fm, today)})

    return {
        "path": str(dest),
        "pages": len(pages),
        "drafts": sum(1 for pg in pages if pg["bucket"] == "draft"),
        "confirmed": sum(1 for pg in pages if pg["bucket"] == "confirmed"),
        "stale": sum(1 for pg in pages if pg["bucket"] == "stale"),
        "inbox": _inbox_count(dest),
        "page_rows": pages,
    }


def render_status_text(report: dict) -> str:
    lines = [f"wiki: {report['path']}", ""]
    lines.append(f"{'pages':10} {'drafts':10} {'confirmed':10} {'stale':10} inbox")
    lines.append(f"{report['pages']:<10} {report['drafts']:<10} {report['confirmed']:<10} {report['stale']:<10} {report['inbox']}")
    if report["page_rows"]:
        lines.append("")
        lines.append(f"{'slug':30} {'title':40} bucket")
        for pg in report["page_rows"]:
            lines.append(f"{pg['slug']:30} {pg['title'][:40]:40} {pg['bucket']}")
    return "\n".join(lines)


def render_status_json(report: dict) -> dict:
    return {k: v for k, v in report.items() if k != "page_rows"} | {"pages_detail": report["page_rows"]}


# --- lint -----------------------------------------------------------------------

def _index_slugs(path: pathlib.Path) -> set[str]:
    p = path / INDEX
    if not p.exists():
        return set()
    import re
    return set(re.findall(r"\(pages/([a-zA-Z0-9_-]+)\.md\)", p.read_text()))


def lint(path: str) -> list[str]:
    """Every page has required frontmatter, non-empty sources, and an index
    entry; every index entry points at a page that exists. Returns a list of
    error strings — empty means the wiki is consistent."""
    dest = pathlib.Path(path).expanduser()
    errors = []

    if not dest.is_dir():
        return [f"{dest}: not a directory — run `teyla wiki init {path}` first"]

    page_paths = list_pages(dest)
    page_slugs = {slug_for(p) for p in page_paths}

    for p in page_paths:
        slug = slug_for(p)
        try:
            fm, _ = read_page(p)
        except WikiError as e:
            errors.append(f"{p}: {e}")
            continue
        for field in REQUIRED_FIELDS:
            if not fm.get(field):
                errors.append(f"{p}: missing required frontmatter field '{field}'")
        if fm.get("confirmed_by") and fm["confirmed_by"] not in CONFIRMED_BY_VALUES:
            errors.append(f"{p}: confirmed_by must be one of {CONFIRMED_BY_VALUES}, got {fm['confirmed_by']!r}")
        if fm.get("status") and fm["status"] not in STATUS_VALUES:
            errors.append(f"{p}: status must be one of {STATUS_VALUES}, got {fm['status']!r}")
        sources = fm.get("sources")
        if fm.get("sources") is not None and not isinstance(sources, list):
            errors.append(f"{p}: sources must be a list")
        elif isinstance(sources, list) and not sources:
            errors.append(f"{p}: sources is empty")

    index_slugs = _index_slugs(dest)
    for slug in sorted(page_slugs - index_slugs):
        errors.append(f"pages/{slug}.md: not referenced from {INDEX}")
    for slug in sorted(index_slugs - page_slugs):
        errors.append(f"{INDEX}: entry for pages/{slug}.md but that page does not exist")

    return errors


# --- confirm -----------------------------------------------------------------------

def confirm(path: str, slug: str, *, today: dt.date | None = None) -> list[str]:
    """Flip a page to confirmed_by: human, status: confirmed, last_verified:
    today, and append that to log.md."""
    dest = pathlib.Path(path).expanduser()
    today = today or dt.datetime.now(dt.timezone.utc).date()
    page_path = _page_path(dest, slug)
    if not page_path.exists():
        raise WikiError(f"no such page: {page_path}")

    fm, body = read_page(page_path)
    fm["confirmed_by"] = "human"
    fm["status"] = "confirmed"
    fm["last_verified"] = today.isoformat()
    write_page(page_path, fm, body)

    log_path = dest / LOG
    title = fm.get("title", slug)
    entry = f"- {today.isoformat()} — confirmed '{title}' (source: teyla wiki confirm, confirmed by: human)\n"
    if log_path.exists():
        with log_path.open("a") as fh:
            fh.write(entry)
    else:
        log_path.write_text("# Log\n\n" + entry)

    return [f"confirmed {page_path}", f"logged to {log_path}"]


# --- CLI wiring -----------------------------------------------------------------

def cmd_init(args):
    for line in init(args.path):
        print(line)
    return 0


def cmd_status(args):
    report = status(args.path)
    if args.json:
        print(json.dumps(render_status_json(report), indent=2))
    else:
        print(render_status_text(report))
    return 1 if (report["drafts"] or report["stale"]) else 0


def cmd_lint(args):
    errors = lint(args.path)
    for e in errors:
        print(e)
    if not errors:
        print(f"ok: {args.path}")
    return 1 if errors else 0


def cmd_confirm(args):
    for line in confirm(args.path, args.slug):
        print(line)
    return 0


def register(sp):
    """Add the `wiki` subcommand to the top-level argparse subparsers object
    (the `sp` created in cli.py's main() via `p.add_subparsers(...)`)."""
    q = sp.add_parser("wiki", help="LLM-maintained facts wiki: init, status, lint, confirm")
    wsp = q.add_subparsers(dest="wiki_action", required=True)

    i = wsp.add_parser("init"); i.set_defaults(fn=cmd_init)
    i.add_argument("path")

    s = wsp.add_parser("status"); s.set_defaults(fn=cmd_status)
    s.add_argument("path")
    s.add_argument("--json", action="store_true")

    l = wsp.add_parser("lint"); l.set_defaults(fn=cmd_lint)
    l.add_argument("path")

    c = wsp.add_parser("confirm"); c.set_defaults(fn=cmd_confirm)
    c.add_argument("path")
    c.add_argument("slug")

    return q

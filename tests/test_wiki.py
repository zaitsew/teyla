"""teyla wiki: init idempotency, status counts, lint failures, confirm."""
from __future__ import annotations

import datetime as dt
import pathlib

import pytest

from teyla.wiki import (
    WikiError,
    confirm,
    init,
    lint,
    list_pages,
    parse_frontmatter,
    render_frontmatter,
    status,
)

PAGE = """---
title: {title}
summary: {summary}
sources:
  - conversation with the founder
last_verified: {last_verified}
confirmed_by: {confirmed_by}
status: {status}
---

{body}
"""


def write_page(wiki: pathlib.Path, slug: str, *, title="A page", summary="A summary.",
                last_verified="2026-09-09", confirmed_by="agent", status_="draft", body="Some facts."):
    (wiki / "pages").mkdir(parents=True, exist_ok=True)
    text = PAGE.format(title=title, summary=summary, last_verified=last_verified,
                        confirmed_by=confirmed_by, status=status_, body=body)
    (wiki / "pages" / f"{slug}.md").write_text(text)


def index_line(slug: str, title="A page", verified="2026-09-09") -> str:
    return f"- [{title}](pages/{slug}.md) — a summary (last verified: {verified})\n"


# --- frontmatter parser ---------------------------------------------------------

def test_parse_frontmatter_scalars_and_list():
    fm, body = parse_frontmatter(PAGE.format(
        title="X", summary="Y", last_verified="2026-09-09",
        confirmed_by="agent", status="draft", body="Body text.",
    ))
    assert fm["title"] == "X"
    assert fm["summary"] == "Y"
    assert fm["sources"] == ["conversation with the founder"]
    assert fm["confirmed_by"] == "agent"
    assert body.strip() == "Body text."


def test_parse_frontmatter_no_frontmatter_returns_empty_dict():
    fm, body = parse_frontmatter("just a plain markdown file\n")
    assert fm == {}
    assert body == "just a plain markdown file\n"


def test_parse_frontmatter_unclosed_raises():
    with pytest.raises(WikiError):
        parse_frontmatter("---\ntitle: X\n")


def test_render_frontmatter_roundtrip():
    data = {"title": "X", "summary": "Y", "sources": ["a", "b"],
            "last_verified": "2026-09-09", "confirmed_by": "human", "status": "confirmed"}
    rendered = render_frontmatter(data)
    fm, _ = parse_frontmatter(rendered + "\n\nbody\n")
    assert fm == data


# --- init -------------------------------------------------------------------------

def test_init_creates_layout(tmp_path):
    dest = tmp_path / "wiki"
    report = init(str(dest))
    assert any("wrote" in line for line in report)
    assert (dest / "index.md").exists()
    assert (dest / "inbox.md").exists()
    assert (dest / "log.md").exists()
    assert (dest / "README.md").exists()
    assert (dest / "pages").is_dir()


def test_init_is_idempotent(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    (dest / "index.md").write_text("hand-edited\n")
    report = init(str(dest))
    assert any("SKIP" in line and "index.md" in line for line in report)
    assert (dest / "index.md").read_text() == "hand-edited\n"


# --- status -----------------------------------------------------------------------

def test_status_counts_drafts_confirmed_stale(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    today = dt.date(2026, 9, 9)

    write_page(dest, "draft-page", confirmed_by="agent", status_="draft", last_verified="2026-09-01")
    write_page(dest, "confirmed-page", confirmed_by="human", status_="confirmed", last_verified="2026-09-05")
    old = (today - dt.timedelta(days=100)).isoformat()
    write_page(dest, "stale-page", confirmed_by="human", status_="confirmed", last_verified=old)

    (dest / "inbox.md").write_text("# Inbox\n\n- an unfiled fact\n- another one\n")

    report = status(str(dest), today=today)
    assert report["pages"] == 3
    assert report["drafts"] == 1
    assert report["confirmed"] == 1
    assert report["stale"] == 1
    assert report["inbox"] == 2


def test_status_empty_wiki(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    report = status(str(dest))
    assert report["pages"] == 0
    assert report["drafts"] == 0
    assert report["confirmed"] == 0
    assert report["stale"] == 0
    assert report["inbox"] == 0


# --- lint -------------------------------------------------------------------------

def test_lint_passes_on_consistent_wiki(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    write_page(dest, "ok-page")
    (dest / "index.md").write_text((dest / "index.md").read_text() + index_line("ok-page"))
    assert lint(str(dest)) == []


def test_lint_fails_on_page_missing_from_index(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    write_page(dest, "orphan-page")
    errors = lint(str(dest))
    assert any("orphan-page" in e and "not referenced" in e for e in errors)


def test_lint_fails_on_index_entry_without_page(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    (dest / "index.md").write_text((dest / "index.md").read_text() + index_line("ghost-page"))
    errors = lint(str(dest))
    assert any("ghost-page" in e and "does not exist" in e for e in errors)


def test_lint_fails_on_missing_required_field(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    (dest / "pages").mkdir(exist_ok=True)
    (dest / "pages" / "bad.md").write_text("---\ntitle: X\n---\n\nbody\n")
    (dest / "index.md").write_text((dest / "index.md").read_text() + index_line("bad"))
    errors = lint(str(dest))
    assert any("missing required frontmatter field 'summary'" in e for e in errors)
    assert any("missing required frontmatter field 'sources'" in e for e in errors)


def test_lint_fails_on_empty_sources(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    (dest / "pages").mkdir(exist_ok=True)
    (dest / "pages" / "no-sources.md").write_text(
        "---\ntitle: X\nsummary: Y\nsources:\nlast_verified: 2026-09-09\nconfirmed_by: agent\nstatus: draft\n---\n\nbody\n"
    )
    (dest / "index.md").write_text((dest / "index.md").read_text() + index_line("no-sources"))
    errors = lint(str(dest))
    assert any("sources is empty" in e for e in errors)


def test_lint_on_missing_directory():
    errors = lint("/no/such/wiki/dir")
    assert errors and "run `teyla wiki init" in errors[0]


# --- confirm ------------------------------------------------------------------------

def test_confirm_flips_fields_and_logs(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    write_page(dest, "draft-page", title="Draft Page", confirmed_by="agent", status_="draft", last_verified="2026-09-01")

    confirm(str(dest), "draft-page", today=dt.date(2026, 9, 9))

    fm, _ = parse_frontmatter((dest / "pages" / "draft-page.md").read_text())
    assert fm["confirmed_by"] == "human"
    assert fm["status"] == "confirmed"
    assert fm["last_verified"] == "2026-09-09"

    log_text = (dest / "log.md").read_text()
    assert "Draft Page" in log_text
    assert "confirmed by: human" in log_text


def test_confirm_accepts_slug_with_md_suffix(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    write_page(dest, "draft-page")
    confirm(str(dest), "draft-page.md", today=dt.date(2026, 9, 9))
    fm, _ = parse_frontmatter((dest / "pages" / "draft-page.md").read_text())
    assert fm["status"] == "confirmed"


def test_confirm_missing_page_raises(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    with pytest.raises(WikiError):
        confirm(str(dest), "no-such-page")


def test_list_pages_ignores_gitkeep(tmp_path):
    dest = tmp_path / "wiki"
    init(str(dest))
    write_page(dest, "real-page")
    slugs = {p.stem for p in list_pages(dest)}
    assert slugs == {"real-page"}

"""Read the parts of a product's `DESIGN.md` and `brand/kit.toml` that `teyla copy` and `teyla voice chart` use.

`DESIGN.md` is at the repo root or in `docs/` (the template is `templates/design/DESIGN.md`). Its `## Glossary`
section is a Markdown table, `| Concept | en | es | ru |`; its `## Voice` section is prose. A row or a line that
still holds a `{{placeholder}}` is skipped: the template is not content.

`brand/kit.toml` is lane F's file and its schema is not fixed yet. This module reads only what it needs and
ignores the rest: `product` or `name`, and a `[voice]` table with `traits`, `banned`, `preferred` (lists of
text) and `chart` (a directory of `en.md`, `es.md`, `ru.md`, relative to the repo). A missing or unreadable
file is not an error: the callers fall back to `DESIGN.md` alone.
"""
from __future__ import annotations

import pathlib
import re
import tomllib

LANGS = ("en", "es", "ru")


def find(repo: pathlib.Path) -> pathlib.Path | None:
    for rel in ("DESIGN.md", "docs/DESIGN.md"):
        if (repo / rel).is_file():
            return repo / rel
    return None


def read(repo: pathlib.Path) -> str:
    p = find(repo)
    try:
        return p.read_text(encoding="utf-8") if p else ""
    except (OSError, UnicodeDecodeError):
        return ""


def section(text: str, heading: str) -> str:
    """The body of the `## <heading>` section, up to the next `## ` heading, without comment lines."""
    out, on = [], False
    for line in text.splitlines():
        m = re.match(r"^##\s+(.*?)\s*$", line)
        if m:
            if on:
                break
            on = m.group(1).lower() == heading.lower()
            continue
        if on:
            out.append(line)
    body = "\n".join(l for l in out if not l.lstrip().startswith("<!--")).strip()
    return body


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def glossary(text: str) -> list[dict]:
    """[{concept, en, es, ru}] from the first table of the Glossary section. Placeholder rows are skipped."""
    rows: list[dict] = []
    head: list[str] | None = None
    for line in section(text, "Glossary").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if head is None:
            head = [c.lower() for c in cells]
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        row = dict(zip(head, cells))
        if any("{{" in c for c in cells):
            continue
        concept = row.get("concept") or (cells[0] if cells else "")
        if concept:
            rows.append(dict(concept=concept, **{l: row.get(l, "") for l in LANGS}))
    return rows


def voice_text(text: str) -> str:
    body = section(text, "Voice")
    return "" if "{{" in body else body


def load_kit(repo: pathlib.Path) -> dict:
    """The kit values this module uses, or {}."""
    p = repo / "brand" / "kit.toml"
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    voice = data.get("voice") if isinstance(data.get("voice"), dict) else {}

    def texts(v) -> list[str]:
        return [str(x) for x in v if isinstance(x, (str, int))] if isinstance(v, list) else []

    return dict(product=str(data.get("product") or data.get("name") or ""), traits=texts(voice.get("traits")),
                banned=texts(voice.get("banned")), preferred=texts(voice.get("preferred")),
                chart=str(voice.get("chart") or ""))


def chart_dir(repo: pathlib.Path, explicit: str | None = None) -> pathlib.Path | None:
    """Where the product's voice charts are: --chart, the kit's `[voice] chart`, then `brand/voice`,
    `docs/voice`, `voice`. The first that holds an `en.md`, `es.md` or `ru.md`."""
    cands = []
    if explicit:
        cands.append(pathlib.Path(explicit).expanduser())
    kit = load_kit(repo).get("chart")
    if kit:
        cands.append(repo / kit)
    cands += [repo / "brand" / "voice", repo / "docs" / "voice", repo / "voice"]
    for c in cands:
        if c.is_dir() and any((c / f"{l}.md").is_file() for l in LANGS):
            return c
    return None


def default_chart_dir(repo: pathlib.Path) -> pathlib.Path:
    """Where `teyla voice chart` writes: the kit's directory, else `brand/voice`."""
    kit = load_kit(repo).get("chart")
    return repo / kit if kit else repo / "brand" / "voice"

"""templates/design/REFERENCE.md and the example design/references/*.yaml: seeded, parseable by the taste ledger, in step."""
from __future__ import annotations

import pathlib
import re

from teyla import taste

ROOT = pathlib.Path(__file__).resolve().parents[1]
DESIGN = ROOT / "templates" / "design"
TYPES = ("onboarding", "list", "detail", "settings", "chat", "voice", "timeline")


def test_reference_md_has_every_screen_type_with_at_most_three_references():
    text = (DESIGN / "REFERENCE.md").read_text()
    heads = re.findall(r"(?m)^## (\w+)$", text)
    assert heads == list(TYPES)
    for t in TYPES:
        body = text.split(f"## {t}\n", 1)[1].split("\n## ", 1)[0]
        rows = [r for r in body.splitlines() if r.startswith("| ") and not r.startswith("| Reference") and not r.startswith("|---")]
        assert 1 <= len(rows) <= 3, t
        for r in rows:
            assert re.search(r"\| https://\S+ \|$", r), r


def test_the_seed_set_is_there():
    text = (DESIGN / "REFERENCE.md").read_text()
    for name in ("Things", "Flighty", "Structured", "Tiimo", "Sunsama", "ChatGPT voice", "Finch", "Moonlitt", "grug"):
        assert name in text, name


def test_each_example_yaml_loads_through_the_taste_ledger_and_matches_the_markdown():
    md = (DESIGN / "REFERENCE.md").read_text()
    files = sorted((DESIGN / "references").glob("*.yaml"))
    assert [f.stem for f in files] == sorted(TYPES)
    for f in files:
        data = taste.load_file(f)
        assert data["screen_type"] == f.stem
        refs = data["references"]
        assert 1 <= len(refs) <= 3
        for r in refs:
            assert r["name"] and r["what_to_copy"] and r["link"].startswith("https://")
            assert r["link"] in md, (f.name, r["link"])


def test_a_product_that_copies_the_examples_gets_them_back_from_load_references(tmp_path):
    dest = tmp_path / "design" / "references"
    dest.mkdir(parents=True)
    for f in (DESIGN / "references").glob("*.yaml"):
        (dest / f.name).write_text(f.read_text())
    got = taste.load_references(tmp_path)
    assert {g["screen_type"] for g in got} == set(TYPES)
    assert len(taste.load_references(tmp_path, "list")) == 1

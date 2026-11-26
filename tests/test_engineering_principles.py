"""The engineering principles template stays short, dated and countable."""
from __future__ import annotations

import pathlib
import re

from teyla import ux_check

ROOT = pathlib.Path(__file__).resolve().parents[1] / "templates"
META = re.compile(r"Since \d{4}-\d{2}-\d{2} · Scope: .+ · Check: .+")


def _active(text: str) -> list[tuple[str, str]]:
    """(id, the line after the heading) for each `### E<n>.` above `## Retired or advisory`."""
    lines = text.splitlines()
    out = []
    for i, ln in enumerate(lines):
        if re.match(r"##\s+Retired or advisory", ln):
            break
        m = re.match(r"###\s+(E\d+)\.", ln)
        if m:
            out.append((m.group(1), lines[i + 1] if i + 1 < len(lines) else ""))
    return out


def test_principles_are_few_unique_and_dated():
    text = (ROOT / "engineering" / "PRINCIPLES.md").read_text()
    active = _active(text)
    ids = [a for a, _ in active]
    assert active and len(active) <= 15
    assert len(set(ids)) == len(ids)
    for pid, nxt in active:
        assert META.fullmatch(nxt.strip()), pid
    assert len(text.splitlines()) < 200


def test_design_standard_has_at_most_twenty_rules():
    rules = ux_check.standard_rules((ROOT / "design" / "STANDARD.md").read_text())
    assert 0 < len(rules) <= 20

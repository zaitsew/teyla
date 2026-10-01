"""Refuse to write instruction text that holds characters a reviewer cannot see.

Every harness obeys POLICY.md, CLAUDE.md, AGENTS.md and `.claude/rules/*.md` verbatim, and a
person reviews them as rendered text. Three classes of code point make the two differ:

    bidi controls     U+202A–U+202E, U+2066–U+2069, U+200E/U+200F — reorder what is shown, so a
                      line can read as one instruction and tokenize as another ("Trojan Source")
    zero-width        U+200B–U+200D, U+2060, U+FEFF — split or join words invisibly, defeating
                      a grep for the rule a reviewer is looking for
    tag characters    U+E0000–U+E007F — an invisible copy of ASCII: a whole sentence can ride
                      along that no editor shows and every model reads

A rule comes from a correction, and a correction can be pasted from anywhere — a web page, an
issue, another agent's output. So the check sits at the write, not at the source: `teyla rule`,
`teyla correct`, `teyla rules propose --write` and every write in policy.py call `check()`, and
the CLI turns its exception into a non-zero exit with the positions. Nothing is stripped
silently: a stripped character still changed what someone meant, and the person who pasted it
should see where.

The cost is a false refusal on an emoji sequence (a family emoji is joined by U+200D) or a file
saved with a BOM. Both are rare in instruction files, and the message names the line and column.
"""
from __future__ import annotations

import unicodedata

_RANGES = (
    (0x200B, 0x200F, "zero-width/bidi mark"),   # ZWSP, ZWNJ, ZWJ, LRM, RLM
    (0x202A, 0x202E, "bidi control"),
    (0x2060, 0x2060, "zero-width"),             # WORD JOINER
    (0x2066, 0x2069, "bidi isolate"),
    (0xFEFF, 0xFEFF, "zero-width"),             # BOM / ZWNBSP
    (0xE0000, 0xE007F, "tag character"),
)
MAX_LISTED = 5


class InvisibleText(ValueError):
    """Raised instead of writing. `str()` is the message the CLI prints."""


def _kind(cp: int) -> str | None:
    for lo, hi, kind in _RANGES:
        if lo <= cp <= hi:
            return kind
    return None


def find(text: str) -> list[tuple[int, int, str]]:
    """(line, column, description) of every hidden character in `text`, 1-based."""
    out = []
    line, col = 1, 0
    for ch in text or "":
        if ch == "\n":
            line, col = line + 1, 0
            continue
        col += 1
        kind = _kind(ord(ch))
        if kind:
            name = unicodedata.name(ch, "") or kind
            out.append((line, col, f"U+{ord(ch):04X} {name}"))
    return out


def check(text: str, where: str) -> None:
    """Raise InvisibleText when `text`, about to be written to `where`, holds a hidden character."""
    hits = find(text)
    if not hits:
        return
    listed = "; ".join(f"{d} at line {l}, col {c}" for l, c, d in hits[:MAX_LISTED])
    more = f" (+{len(hits) - MAX_LISTED} more)" if len(hits) > MAX_LISTED else ""
    raise InvisibleText(
        f"refused: {where} would get {len(hits)} invisible or bidi character(s) — {listed}{more}. "
        "They can make the text an agent obeys differ from the text a reviewer reads; "
        "remove them and run the command again. Nothing was written.")

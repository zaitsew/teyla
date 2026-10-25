"""Terminal styling for the first screen: bare `teyla`, `teyla today`, `teyla help`.

One `Style` per output stream. Every method returns the text unchanged when colour is off
(NO_COLOR, TERM=dumb, or a stream that is not a terminal), so a screen is written once and is
plain text when piped. Roles and colours are brand.py's.
"""
from __future__ import annotations

import shutil
import sys
from typing import Mapping, TextIO

from . import brand


class Style:
    def __init__(self, stream: TextIO | None = None, env: Mapping[str, str] | None = None):
        self.stream = sys.stdout if stream is None else stream
        self.env = env

    def paint(self, text: str, role: str) -> str:
        return brand.paint(text, role, self.stream, self.env)

    def bold(self, text: str) -> str:
        return brand.bold(text, self.stream, self.env)

    def command(self, text: str) -> str:
        """A command the person can type: the primary colour."""
        return self.paint(text, "primary")

    def quiet(self, text: str) -> str:
        return self.paint(text, "text-secondary")

    def mark(self) -> str:
        """The two-character mark: a bold T in primary, then the amber block that waits for you."""
        block = "█" if _utf8(self.stream) else "#"
        return self.bold(self.paint("T", "primary")) + self.paint(block, "needs-you")

    def width(self, low: int = 60, high: int = 100) -> int:
        try:
            cols = shutil.get_terminal_size((80, 24)).columns
        except (OSError, ValueError):
            cols = 80
        return max(low, min(high, cols))


def _utf8(stream: TextIO) -> bool:
    enc = (getattr(stream, "encoding", None) or "utf-8").lower().replace("_", "-")
    return enc in ("utf-8", "utf8")


def pad(text: str, width: int) -> str:
    """`text` padded to `width` columns by its visible length (escape codes do not count)."""
    import re
    visible = len(re.sub(r"\033\[[0-9;]*m", "", text))
    return text + " " * max(0, width - visible)

"""Teyla's colours for the terminal.

The values mirror brand/tokens.json, the single source; tests/test_brand.py fails when they
differ. Roles, not colours: `primary` (indigo), `needs-you` (amber: something waits on the
person), `saving` (green: money saved), `danger`, `text-secondary`.

    from teyla import brand
    print(brand.paint("2 waiting on you", "needs-you"))

Colour is off, and `paint` returns the text unchanged, when NO_COLOR is set to anything
non-empty (no-color.org), when TERM is "dumb", or when the stream is not a terminal.
Otherwise the palette follows the terminal background: TEYLA_THEME=light|dark wins, then
COLORFGBG. A 256-colour terminal with a known background gets the ANSI 256 set for it; any
other gets the 16-colour fallback, which reads on light and dark alike.
"""
from __future__ import annotations

import os
import sys
from typing import Mapping, TextIO

ROLES = ("primary", "needs-you", "saving", "danger", "text-secondary")

# xterm-256 indices. Contrast is at least 4.5:1 against #FFFFFF (light) and #1E1E1E (dark).
ANSI256 = {
    "light": {"primary": 61, "needs-you": 130, "saving": 28, "danger": 124, "text-secondary": 59},
    "dark": {"primary": 147, "needs-you": 215, "saving": 78, "danger": 203, "text-secondary": 248},
}

# SGR parameters for terminals with 16 colours or an unknown background.
ANSI16 = {"primary": "1;34", "needs-you": "33", "saving": "32", "danger": "31", "text-secondary": "2"}

RESET = "\033[0m"


def enabled(stream: TextIO | None = None, env: Mapping[str, str] | None = None) -> bool:
    """True when colour may be written to `stream` (default: stdout)."""
    env = os.environ if env is None else env
    if env.get("NO_COLOR") or env.get("TERM") == "dumb":
        return False
    stream = sys.stdout if stream is None else stream
    try:
        return stream.isatty()
    except (AttributeError, ValueError):  # no isatty, or a closed stream
        return False


def background(env: Mapping[str, str] | None = None) -> str | None:
    """"light", "dark" or None when the terminal does not say."""
    env = os.environ if env is None else env
    theme = env.get("TEYLA_THEME", "").strip().lower()
    if theme in ("light", "dark"):
        return theme
    # COLORFGBG is "fg;bg" or "fg;default;bg"; the last field is the background's colour number.
    last = env.get("COLORFGBG", "").split(";")[-1].strip()
    if last.isdigit():
        return "light" if int(last) in (7, 9, 10, 11, 12, 13, 14, 15) else "dark"
    return None


def depth(env: Mapping[str, str] | None = None) -> int:
    """256 when the terminal says it has 256 colours or more, else 16."""
    env = os.environ if env is None else env
    if "256color" in env.get("TERM", "") or env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return 256
    return 16


def code(role: str, env: Mapping[str, str] | None = None) -> str:
    """The SGR escape that starts `role`, for this terminal."""
    if role not in ROLES:
        raise ValueError(f"unknown colour role {role!r}; one of {', '.join(ROLES)}")
    bg = background(env)
    if bg and depth(env) == 256:
        return f"\033[38;5;{ANSI256[bg][role]}m"
    return f"\033[{ANSI16[role]}m"


def paint(text: str, role: str, stream: TextIO | None = None, env: Mapping[str, str] | None = None) -> str:
    """`text` in the colour of `role`, or `text` unchanged when colour is off."""
    if role not in ROLES:
        raise ValueError(f"unknown colour role {role!r}; one of {', '.join(ROLES)}")
    if not enabled(stream, env):
        return text
    return f"{code(role, env)}{text}{RESET}"

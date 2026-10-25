"""brand/tokens.json is the single source: the CLI palette and the Mac app's colours must match it."""
import io
import json
import pathlib
import re

import pytest

from teyla import brand

ROOT = pathlib.Path(__file__).resolve().parents[1]
TOKENS = json.loads((ROOT / "brand" / "tokens.json").read_text())
SWIFT = (ROOT / "apps" / "mac" / "Teyla" / "UI" / "Tokens.swift").read_text()


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_cli_ansi256_matches_tokens():
    for bg in ("light", "dark"):
        want = {role: v["index"] for role, v in TOKENS["ansi256"][f"{bg}-terminal"].items()}
        assert brand.ANSI256[bg] == want
    assert set(brand.ROLES) == set(TOKENS["ansi256"]["ansi16-fallback"])


def test_mac_palette_matches_tokens():
    light, dark = TOKENS["color"]["light"], TOKENS["color"]["dark"]
    found = {name: (l, d) for name, l, d in
             re.findall(r"static let (\w+) = Color\(light: 0x([0-9A-F]{6}), dark: 0x([0-9A-F]{6})\)", SWIFT)}
    for role in light:
        name = re.sub(r"-(\w)", lambda m: m.group(1).upper(), role)
        assert found.get(name) == (light[role].lstrip("#"), dark[role].lstrip("#")), role
    assert len(found) == len(light)


def test_no_color_and_pipes_get_plain_text():
    tty = {"TERM": "xterm-256color", "COLORFGBG": "15;0"}
    assert brand.paint("x", "saving", TTY(), {**tty, "NO_COLOR": "1"}) == "x"
    assert brand.paint("x", "saving", io.StringIO(), tty) == "x"
    assert brand.paint("x", "saving", TTY(), {"TERM": "dumb"}) == "x"
    # An empty NO_COLOR does not turn colour off (no-color.org).
    assert brand.paint("x", "saving", TTY(), {**tty, "NO_COLOR": ""}) != "x"


def test_palette_follows_background_and_depth():
    assert brand.paint("x", "needs-you", TTY(), {"TERM": "xterm-256color", "COLORFGBG": "15;0"}) == "\033[38;5;215mx\033[0m"
    assert brand.paint("x", "needs-you", TTY(), {"TERM": "xterm-256color", "COLORFGBG": "0;default;15"}) == "\033[38;5;130mx\033[0m"
    assert brand.code("primary", {"TERM": "xterm-256color", "TEYLA_THEME": "light", "COLORFGBG": "15;0"}) == "\033[38;5;61m"
    # Unknown background, or 16 colours only: the fallback.
    assert brand.code("needs-you", {"TERM": "xterm-256color"}) == "\033[33m"
    assert brand.code("saving", {"TERM": "xterm", "COLORFGBG": "15;0"}) == "\033[32m"


def test_unknown_role_is_an_error():
    with pytest.raises(ValueError):
        brand.paint("x", "accent", TTY(), {})

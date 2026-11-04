"""The apps' design system stays small: five type levels, one number style, tokens for everything else.

A view picks a level from `Typo`, a gap from `Space`, a radius from `Radius` and a colour from `Palette`.
A literal in a view is how "sometimes tiny, sometimes huge" comes back, so it fails here.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
APPS = {"mac": ROOT / "apps" / "mac" / "Teyla", "ios": ROOT / "apps" / "ios" / "Teyla"}
VIEW_DIRS = ("UI", "App", "Store")
# Tokens define the values. BrandMark draws the logo in its own grid. Preview.swift is the PNG hook, never shown to a person.
EXEMPT = {"Tokens.swift", "BrandMark.swift", "Preview.swift"}
LEVELS = {"pageTitle", "section", "cardTitle", "body", "caption", "number"}
VARIANTS = {"code"}  # a level's size in another face, not a level

RULES = {
    "literal font": re.compile(
        r"\.font\(\.|\bFont\.(system|custom|body|title\d?|largeTitle|headline|subheadline|callout|footnote|caption2?)\b"
        r"|\.system\(\s*(size:|\.)|\b(NSFont|UIFont)\."
    ),
    "literal colour": re.compile(
        r"\bColor\.(red|green|blue|orange|yellow|pink|purple|gray|primary|secondary|accentColor|white|black|brand\w*)\b"
        r"|\bColor\(\s*(\.|red:|white:|hue:|light:|uiColor:|nsColor:)"
        r"|\.(foregroundStyle|tint|background|foregroundColor)\(\s*\.(red|green|blue|orange|yellow|gray|primary|secondary|tertiary|white|black)\b"
    ),
    "literal gap": re.compile(
        r"\bspacing:\s*[1-9]|\bvar spacing: CGFloat = \d|\bpadding\(\s*(\.\w+,\s*)?-?[1-9]|\bSpacer\(minLength:\s*[1-9]"
    ),
    "literal radius": re.compile(r"\bcornerRadius:\s*\d"),
    "literal size": re.compile(r"\.frame\([^)]*\b(width|height|minWidth|maxWidth|minHeight|maxHeight):\s*[1-9]"),
    "token arithmetic": re.compile(r"\bSpace\.\w+\s*[-+*]\s*(\d|Space\.)|\b\d+\s*\*\s*Space\."),
}


def bypasses(text: str) -> list[str]:
    """The lines of a view's source that set a value a token should set, comments aside."""
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        code = line.split("//", 1)[0]
        for rule, pattern in RULES.items():
            if pattern.search(code):
                found.append(f"{number}: {rule}: {line.strip()}")
    return found


def view_files():
    return [
        pytest.param(path, id=f"{app}/{path.relative_to(root)}")
        for app, root in APPS.items()
        for folder in VIEW_DIRS
        for path in sorted((root / folder).rglob("*.swift"))
        if path.name not in EXEMPT
    ]


@pytest.mark.parametrize("path", view_files())
def test_views_use_tokens_only(path):
    assert bypasses(path.read_text()) == []


@pytest.mark.parametrize("line", [
    ".font(.system(size: 13))",
    ".font(.caption)",
    "Text(a).font(Font.system(size: 9))",
    "view.font = NSFont.systemFont(ofSize: 15)",
    ".foregroundStyle(.secondary)",
    "Circle().fill(Color.green)",
    "VStack(spacing: 10) {",
    ".padding(.top, 6)",
    ".padding(9)",
    "padding(16)",
    "Spacer(minLength: 8)",
    "RoundedRectangle(cornerRadius: 12)",
    ".frame(width: 26)",
    ".padding(Space.xs + Space.xxs)",
])
def test_the_rule_catches_a_bypass(line):
    assert bypasses(line)


@pytest.mark.parametrize("line", [
    ".font(Typo.caption.weight(.medium))",
    ".foregroundStyle(Palette.textSecondary)",
    "VStack(spacing: 0) {",
    ".padding(.top, Space.xl)",
    ".frame(width: Space.glyph)",
    "// .font(.system(size: 13)) is what this replaced",
])
def test_the_rule_passes_a_token(line):
    assert not bypasses(line)


def typo_block(app: str) -> str:
    text = (APPS[app] / "UI" / "Tokens.swift").read_text()
    return re.search(r"enum Typo \{(.*?)\n\}", text, re.S).group(1)


@pytest.mark.parametrize("app", APPS)
def test_exactly_five_levels_and_one_number(app):
    names = set(re.findall(r"static let (\w+)\s*=\s*Font", typo_block(app)))
    assert names == LEVELS | VARIANTS


def test_mac_levels_have_five_sizes_in_order():
    sizes = dict(re.findall(r"static let (\w+) = Font\.system\(size: (\d+)", typo_block("mac")))
    ladder = [int(sizes[name]) for name in ("pageTitle", "section", "cardTitle", "body", "caption")]
    assert ladder == sorted(ladder, reverse=True) and len(set(ladder)) == 5
    assert sizes["number"] == sizes["pageTitle"]
    assert sizes["code"] == sizes["caption"]


@pytest.mark.parametrize("app", APPS)
def test_views_name_only_real_levels(app):
    allowed = LEVELS | VARIANTS | {"monogram", "noteField"}
    for path in APPS[app].rglob("*.swift"):
        for name in re.findall(r"\bTypo\.(\w+)", path.read_text()):
            assert name in allowed, f"{path.name}: Typo.{name}"

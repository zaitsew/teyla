"""The README is the first thing a stranger reads, and docs/GUIDE.md is the depth behind it. Both name commands,
files and anchors that must exist. Parsing runs the argparse parser only: nothing is executed."""
from __future__ import annotations

import pathlib
import re

import pytest

import teyla
from teyla import cli
from test_agents_md import _commands, _parses as _strict

ROOT = pathlib.Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
GUIDE = (ROOT / "docs" / "GUIDE.md").read_text()
INSTALL = "uv tool install --python 3.12 git+https://github.com/zaitsew/teyla"


def _without_comments(text: str) -> str:
    """Drop the trailing `# comment` of each line inside a fence, so a fence line parses like a typed command."""
    def fence(m):
        return m.group(1) + "\n".join(re.sub(r"[ \t]+#.*$", "", l) for l in m.group(2).splitlines()) + "\n```"
    return re.sub(r"(```[^\n]*\n)(.*?)\n?```", fence, text, flags=re.S)


def _parses(argv: list[str]) -> bool:
    """A command is real when the parser knows it. Prose names a command without its arguments (`teyla undo`,
    `teyla wiki`), so a parse that stops only on a missing argument counts; an unknown command or flag does not.
    A word like `check|prep|inbox` lists alternatives: each one must parse."""
    for i, word in enumerate(argv):
        if "|" in word and not word.startswith("-"):
            return all(_parses(argv[:i] + [alt] + argv[i + 1:]) for alt in word.split("|"))
    if _strict(argv):
        return True
    import contextlib
    import io
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            cli.build_parser().parse_known_args(argv)
    except SystemExit:
        msg = err.getvalue()
        return "required" in msg or "expected" in msg and "argument" in msg
    return False


def _argvs(text: str) -> list[list[str]]:
    seen, out = set(), []
    for argv in _commands(_without_comments(text)):
        if tuple(argv) not in seen:
            seen.add(tuple(argv))
            out.append(argv)
    return out


def _slug(heading: str) -> str:
    s = re.sub(r"[`*]", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", s).replace(" ", "-")


def _anchors(text: str) -> set[str]:
    return {_slug(m.group(1)) for m in re.finditer(r"(?m)^#{1,6} (.+)$", re.sub(r"```.*?```", "", text, flags=re.S))}


def _links(text: str) -> list[str]:
    return [m.group(1) for m in re.finditer(r"!?\[[^\]]*\]\(([^)\s]+)\)", text)] + re.findall(r'(?:src|srcset)="([^"]+)"', text)


# --- the README ------------------------------------------------------------------------

def test_the_readme_fits_two_screens_and_opens_with_the_promise():
    lines = README.splitlines()
    assert len(lines) <= 120
    assert "brand/lockup.svg" in README and "brand/lockup-dark.svg" in README and "prefers-color-scheme: dark" in README
    assert "docs/img/web-start.png" in "\n".join(lines[:14])
    assert teyla.PROMISE in " ".join(README.split())


def test_the_readme_has_its_parts_in_order():
    heads = re.findall(r"(?m)^## (.+)$", README)
    assert heads == ["Set it up with your agent", "Or by hand", "Cost and waste", "What's waiting on you",
                     "Where every product stands", "Your products and notes", "One policy for every agent", "The Mac app", "Privacy",
                     "Undo and uninstall", "Links"]


def test_the_readme_gives_a_stranger_one_line_to_paste_and_one_install_command():
    assert "```\nSet up https://github.com/zaitsew/teyla\n```" in README
    assert "AGENTS.md" in README
    assert INSTALL in README
    for line in README.splitlines():
        if "uv tool install" in line:
            assert "--python 3.12" in line, line
    assert "uvx --python 3.12 --from git+https://github.com/zaitsew/teyla teyla start" in README


def test_the_readme_defines_the_words_a_stranger_would_not_know():
    for term in ("List price", "Context", "subagent", "hooks", "product"):
        assert re.search(rf"\*{term}\*|\*{term.lower()}\*", README, re.I), term


def test_the_readme_names_every_part_of_the_first_run_and_the_undo():
    cmds = _argvs(README)
    for need in (("start",), ("today",), ("asks",), ("product", "init"), ("note",), ("policy", "sync"),
                 ("harness", "sync"), ("routine", "install"), ("changes",), ("undo", "O1"), ("uninstall", "--dry"),
                 ("uninstall",), ("web",)):
        assert any(c[:len(need)] == list(need) for c in cmds), need


def test_the_readme_and_guide_are_english_and_name_no_person():
    for text in (README, GUIDE):
        assert not re.search("[\\u0400-\\u04ff]", text)
        assert "/Users/" not in text and ("Iv" + "an") not in text


def test_the_readme_privacy_block_points_at_the_table_it_summarises():
    block = README.split("## Privacy", 1)[1].split("\n## ", 1)[0]
    assert "docs/PRIVACY.md" in block and "safe.enabled=true" in block
    privacy = (ROOT / "docs" / "PRIVACY.md").read_text()
    assert "teyla relay on" in privacy and "teyla relay on" in block
    assert "| 1 | The update check" in privacy


# --- every command parses --------------------------------------------------------------

@pytest.mark.parametrize("argv", _argvs(README), ids=lambda a: "README: teyla " + " ".join(a))
def test_every_teyla_command_in_the_readme_parses(argv):
    assert _parses(argv), f"README.md names `teyla {' '.join(argv)}` and the parser rejects it"


@pytest.mark.parametrize("argv", _argvs(GUIDE), ids=lambda a: "GUIDE: teyla " + " ".join(a))
def test_every_teyla_command_in_the_guide_parses(argv):
    assert _parses(argv), f"docs/GUIDE.md names `teyla {' '.join(argv)}` and the parser rejects it"


# --- links, images, anchors ------------------------------------------------------------

@pytest.mark.parametrize("name,text,base", [("README.md", README, ROOT), ("docs/GUIDE.md", GUIDE, ROOT / "docs")])
def test_every_relative_link_resolves(name, text, base):
    bad = []
    for link in _links(text):
        if re.match(r"[a-z]+:", link):
            continue
        path, _, frag = link.partition("#")
        target = (base / path).resolve() if path else (base / pathlib.Path(name).name).resolve()
        if not target.exists():
            bad.append(link)
        elif frag and target.suffix == ".md" and frag not in _anchors(target.read_text()):
            bad.append(link)
    assert not bad, f"{name}: {bad}"


def test_other_docs_still_find_the_guide_sections_they_link_to():
    anchors = _anchors(GUIDE)
    for doc in (ROOT / "docs").glob("*.md"):
        for m in re.finditer(r"GUIDE\.md#([\w-]+)", doc.read_text()):
            assert m.group(1) in anchors, f"{doc.name} links GUIDE.md#{m.group(1)}"


# --- the guide keeps what the old README carried ----------------------------------------

def test_the_guide_follows_the_readme_order_and_keeps_every_old_section():
    heads = re.findall(r"(?m)^## (.+)$", GUIDE)
    order = ["Install and update", "Cost and waste", "What's waiting on you", "Your products and notes",
             "One policy for every agent", "Privacy and safe mode", "Undo and uninstall"]
    assert [h for h in heads if h in order] == order
    for old in ("Find the waste: `teyla start`", "Spend fewer tokens", "Keep the machine alive",
                "Questions an agent left open: `teyla asks`", "The Mac app", "Your own words",
                "Whether a build reached a person", "Whether the automated half ran", "How agents write",
                "The policy", "The plugin", "Cloud sessions", "Routines and checks", "What gets read"):
        assert f"### {old}" in GUIDE, old


def test_the_guide_pins_the_install_line_and_lists_the_documents():
    assert INSTALL in GUIDE
    for line in GUIDE.splitlines():
        if "uv tool install" in line and "zaitsew/teyla" in line:
            assert "--python 3.12" in line, line
    for doc in sorted((ROOT / "docs").glob("*.md")):
        if doc.name in {"GUIDE.md", "DIRECTORY.md", "DISPATCH.md", "HANDOVER.md", "reel.md"}:
            continue          # linked from the install section or from a command row, not from the list
        assert doc.name in GUIDE, f"docs/{doc.name} is not linked from the guide"

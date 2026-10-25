"""AGENTS.md is read by an AI agent that was asked to set Teyla up. It must name only commands the parser has,
carry no placeholder name, and stay short. Parsing runs the argparse parser only: nothing is executed."""
from __future__ import annotations

import pathlib
import re
import shlex

import pytest

from teyla import cli

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEXT = (ROOT / "AGENTS.md").read_text()


def _commands(text: str) -> list[list[str]]:
    """Every `teyla ...` command in a code span or fence, as argv without the leading `teyla`. A `uvx ... teyla X`
    line counts; `<id>` style placeholders become O1; a trailing `...` is dropped."""
    spans = re.findall(r"`([^`\n]+)`", text) + [l for f in re.findall(r"```.*?\n(.*?)```", text, re.S) for l in f.splitlines()]
    out = []
    for span in spans:
        for part in re.split(r"\s*(?:&&|;|\|\|)\s*", span):
            m = re.search(r"(?:^|\s)teyla\s+([a-z][\w-]*.*)$", part)
            if not m or part.lstrip().startswith(("uv ", "pipx ")):
                continue
            words = re.sub(r"<[^>]+>", "O1", m.group(1).replace("$(git config user.name)", "Ada")).replace("...", "")
            words = words.split(" (")[0]
            try:
                argv = shlex.split(words)
            except ValueError:
                continue
            out.append(argv)
    return out


def _parses(argv: list[str]) -> bool:
    parser = cli.build_parser()
    try:
        args, extra = parser.parse_known_args(argv)
    except SystemExit:
        return False
    return not extra or isinstance(getattr(args, "words", None), list)


def test_agents_md_names_the_commands_an_agent_needs():
    cmds = _commands(TEXT)
    for need in (("start", "--agent"), ("changes",), ("doctor",), ("uninstall", "--dry"), ("routine", "install"),
                 ("policy", "init"), ("policy", "sync")):
        assert any(c[:len(need)] == list(need) for c in cmds), need
    assert any(c[:2] == ["apply", "O1"] for c in _commands(TEXT))
    assert any(c[:2] == ["undo", "O1"] for c in _commands(TEXT))


@pytest.mark.parametrize("argv", _commands(TEXT), ids=lambda a: "teyla " + " ".join(a))
def test_every_teyla_command_in_agents_md_parses(argv):
    assert _parses(argv), f"AGENTS.md names `teyla {' '.join(argv)}` and the parser rejects it"


def test_agents_md_is_short_and_has_no_placeholder_name():
    assert len(TEXT.splitlines()) <= 100
    assert "Your Name" not in TEXT and "Your name" not in TEXT
    assert not re.search(r"[\u0400-\u04ff]", TEXT)


def test_agents_md_asks_per_offer_and_ends_with_the_closing_line():
    assert "one question about that one offer" in TEXT or "one question" in TEXT
    assert "Never put two offers in one question" in TEXT
    assert "Run `teyla` any time. `teyla today` is the daily screen." in TEXT


def test_claude_md_points_installers_to_agents_md_and_contributors_to_contributing():
    claude = (ROOT / "CLAUDE.md").read_text()
    assert claude.splitlines()[0].find("AGENTS.md") != -1
    assert "CONTRIBUTING.md" in claude
    assert (ROOT / "CONTRIBUTING.md").is_file()


def test_the_promise_is_one_sentence_used_everywhere():
    import tomllib
    from teyla import PROMISE, welcome
    assert welcome.PROMISE is PROMISE
    assert PROMISE in " ".join(TEXT.split())
    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["description"] == PROMISE
    assert PROMISE.endswith("Nothing about your sessions leaves your Mac unless you turn it on.")
    assert "Teyla reads files on your Mac. It sends nothing about your sessions anywhere unless you turn on a feature" in " ".join(TEXT.split())

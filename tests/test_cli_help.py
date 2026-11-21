"""Every command and subcommand the parser knows answers `--help` with exit 0 and some text.

In-process, through `teyla.cli.main`: a command whose parser raises while it is built, or whose help string has a
stray `%`, fails here and not on a person's first `teyla <command> --help`."""
from __future__ import annotations

import argparse

import pytest

from teyla import cli


def _paths(parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()):
    """Every command path the parser knows, subcommands included: ("doctor",), ("storage", "offload"), ..."""
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            for name, sub in act.choices.items():
                yield prefix + (name,)
                yield from _paths(sub, prefix + (name,))


PATHS = sorted(set(_paths(cli.build_parser())))


def test_the_parser_knows_the_commands_the_sprint_named():
    for name in ("doctor", "monitor", "products"):
        assert (name,) in PATHS
    assert len(PATHS) > 30


@pytest.mark.parametrize("path", PATHS, ids=lambda p: " ".join(p))
def test_help_exits_zero_with_text(path, capsys):
    try:
        code = cli.main([*path, "--help"])      # `help` renders its own text and returns; argparse exits
    except SystemExit as e:
        code = e.code
    assert code in (0, None)
    out = capsys.readouterr().out
    assert out.strip(), f"`teyla {' '.join(path)} --help` printed nothing"
    assert "usage:" in out.lower() or "teyla" in out

"""docs/COMMANDS.md names every command and every subcommand the parser has. A command added to
the CLI without a row in the doc fails here, with the missing names listed."""
from __future__ import annotations

import argparse
import pathlib
import re

from teyla import cli

DOC = pathlib.Path(__file__).resolve().parent.parent / "docs" / "COMMANDS.md"


def _subparsers(parser):
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            return a.choices
    return None


def parser_tree() -> dict[str, set[str]]:
    """Command -> its subcommand names: argparse sub-parsers plus the choices of an `action` positional."""
    out: dict[str, set[str]] = {}
    for name, sp in (_subparsers(cli.build_parser()) or {}).items():
        names = set(_subparsers(sp) or {})
        for a in sp._actions:
            if a.dest in ("action", "sub", "verb") and a.choices:
                names |= set(a.choices)
        out[name] = names
    return out


def missing_from(doc: str, tree: dict[str, set[str]]) -> list[str]:
    """`teyla <cmd>` when no line names the command, `teyla <cmd> <sub>` when no line naming the command names the sub."""
    lines = doc.splitlines()
    gaps = []
    for cmd, subs in sorted(tree.items()):
        mine = [ln for ln in lines if re.search(r"teyla " + re.escape(cmd) + r"(?![\w-])", ln)]
        if not mine:
            gaps.append(f"teyla {cmd}")
            continue
        for sub in sorted(subs):
            if not any(re.search(r"(?<![\w-])" + re.escape(sub) + r"(?![\w-])", ln) for ln in mine):
                gaps.append(f"teyla {cmd} {sub}")
    return gaps


def test_every_command_and_subcommand_is_in_commands_md():
    gaps = missing_from(DOC.read_text(encoding="utf-8"), parser_tree())
    assert not gaps, f"add a row to docs/COMMANDS.md for: {gaps}"


def test_the_check_fails_when_a_command_or_subcommand_is_missing():
    tree = {"alpha": {"run", "stop"}, "beta": set()}
    assert missing_from("| `teyla alpha run` | x |", tree) == ["teyla alpha stop", "teyla beta"]
    assert missing_from("`teyla alpha run|stop` `teyla beta`", tree) == []


def test_the_tree_sees_prose_and_tg():
    tree = parser_tree()
    assert "prose" in tree and {"activity", "serve"} <= tree["tg"]

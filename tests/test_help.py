"""`teyla help`: six groups under 40 lines, every command in exactly one group, an unknown command that
suggests the nearest one, and no traceback for what a new user types."""
from __future__ import annotations

import io
import re

import pytest

from teyla import cli, helpgroups
from teyla.ui import Style

ESC = re.compile(r"\033\[")
GROUP_NAMES = ["Start", "Daily", "Products", "Spend", "Setup", "Advanced"]


class TTY(io.StringIO):
    def isatty(self):
        return True


def run(capsys, *argv):
    try:
        rc = cli.main(list(argv))
    except SystemExit as e:               # argparse's own --help and errors exit this way
        rc = e.code
    out = capsys.readouterr()
    return rc, out.out, out.err


def registered() -> list[str]:
    return cli._commands(cli.build_parser())


# --- every command is in one group ----------------------------------------------------------------

def test_every_registered_command_is_in_a_group():
    """A command added to cli.py without a line in helpgroups.GROUPS fails here."""
    missing = [c for c in registered() if c != "help" and helpgroups.group_of(c) is None]
    assert not missing, f"add {missing} to helpgroups.GROUPS (one group each, with a one-line description)"


def test_no_command_is_in_two_groups_or_listed_twice():
    names = [c for rows in helpgroups.GROUPS.values() for c, _ in rows]
    assert len(names) == len(set(names)), sorted(n for n in names if names.count(n) > 1)


def test_group_names_and_featured_commands_are_known():
    assert list(helpgroups.GROUPS) == GROUP_NAMES
    assert set(helpgroups.FEATURED) == set(GROUP_NAMES)
    for g, picked in helpgroups.FEATURED.items():
        assert all(c in dict(helpgroups.GROUPS[g]) for c in picked), g


def test_every_listed_command_exists_except_those_a_pending_change_adds():
    cmds = set(registered())
    stray = [c for rows in helpgroups.GROUPS.values() for c, _ in rows if c not in cmds and c not in helpgroups.NEEDS]
    assert not stray


def test_every_description_is_one_short_line():
    for rows in helpgroups.GROUPS.values():
        for c, d in rows:
            assert d and "\n" not in d and len(d) <= 70, (c, d)


# --- the grouped help -----------------------------------------------------------------------------

@pytest.mark.parametrize("argv", [["help"], ["--help"], ["-h"]])
def test_help_is_grouped_and_under_40_lines(capsys, argv):
    rc, out, err = run(capsys, *argv)
    lines = out.splitlines()
    assert rc == 0 and err == ""
    assert len(lines) < 40, len(lines)
    heads = [ln for ln in lines if ln in GROUP_NAMES]
    assert heads == GROUP_NAMES
    assert "teyla help --all" in out
    assert not ESC.search(out)                   # piped: no colour


def test_help_names_a_few_commands_per_group_and_counts_the_rest(capsys):
    _, out, _ = run(capsys, "help")
    for c in ("today", "asks", "spend", "doctor", "update"):
        assert re.search(rf"^  {c}\s", out, re.M), c
    assert re.search(r"^  \d+ more: teyla help --all", out, re.M)
    assert not re.search(r"^  tidy\s", out, re.M)            # a rarely used command waits for --all


def test_help_all_lists_every_registered_command_once(capsys):
    _, out, _ = run(capsys, "help", "--all")
    for c in registered():
        if c != "help":
            assert len(re.findall(rf"^  {re.escape(c)}\s", out, re.M)) == 1, c


def test_help_names_a_command_only_when_this_version_has_it(capsys, monkeypatch):
    monkeypatch.setattr(helpgroups, "present", lambda c: c != "start")
    _, out, _ = run(capsys, "help")
    assert not re.search(r"^  start\s", out, re.M) and "teyla start" not in out
    monkeypatch.setattr(helpgroups, "present", lambda c: True)
    _, out, _ = run(capsys, "help")
    assert re.search(r"^  start\s", out, re.M) and "teyla start" in out


def test_help_for_one_command_shows_its_own_options(capsys):
    rc, out, _ = run(capsys, "help", "asks")
    assert rc == 0 and "--product" in out and "--json" in out


def test_every_command_keeps_its_own_help(capsys):
    for c in registered():
        rc, out, _ = run(capsys, c, "--help")
        assert rc == 0 and f"teyla {c}" in out, c


def test_help_colours_a_terminal_and_not_no_color_or_dumb():
    tty = {"TERM": "xterm-256color", "COLORFGBG": "15;0"}
    assert ESC.search(helpgroups.render(False, Style(TTY(), tty)))
    assert not ESC.search(helpgroups.render(False, Style(TTY(), {**tty, "NO_COLOR": "1"})))
    assert not ESC.search(helpgroups.render(False, Style(TTY(), {"TERM": "dumb"})))
    assert not ESC.search(helpgroups.render(True, Style(io.StringIO(), tty)))


# --- unknown commands and failures ------------------------------------------------------------------

def test_unknown_command_suggests_the_nearest_and_shows_the_help(capsys):
    rc, out, err = run(capsys, "spnd")
    assert rc == 2
    assert err.splitlines()[0] == "Unknown command 'spnd'. Did you mean 'spend'?"
    assert all(g in err.splitlines() for g in GROUP_NAMES)
    assert "Traceback" not in err and out == ""


def test_unknown_command_with_no_near_match_still_shows_the_help(capsys):
    rc, _, err = run(capsys, "qqqqzz")
    assert rc == 2
    assert err.splitlines()[0] == "Unknown command 'qqqqzz'."
    assert "Start" in err


def test_unknown_command_never_suggests_one_this_version_lacks(capsys, monkeypatch):
    monkeypatch.setattr(helpgroups, "present", lambda c: c not in ("start", "apply", "undo", "changes"))
    _, _, err = run(capsys, "strt")
    assert "Did you mean 'start'" not in err


def test_an_option_in_place_of_a_command_is_one_line(capsys):
    rc, _, err = run(capsys, "--frobnicate")
    assert rc == 2 and err.startswith("teyla: ") and "teyla help" in err and "Traceback" not in err


def test_a_missing_optional_package_is_one_line_with_the_fix(capsys, monkeypatch):
    def boom(args):
        raise ModuleNotFoundError("No module named 'PIL'", name="PIL")
    monkeypatch.setattr(cli, "cmd_prompt", boom)
    rc, out, err = run(capsys, "prompt")
    assert rc == 1 and out == ""
    assert err.count("\n") == 1 and "pillow" in err and "uv tool install" in err


def test_an_unreadable_teyla_file_is_one_line_naming_it(capsys, monkeypatch, tmp_path):
    from teyla.control import state as control
    target = control.home() / "state.json"

    def boom(args):
        raise PermissionError(13, "Permission denied", str(target))
    monkeypatch.setattr(cli, "cmd_prompt", boom)
    rc, _, err = run(capsys, "prompt")
    assert rc == 1 and err.count("\n") == 1 and str(target) in err and "teyla doctor" in err


def test_any_other_failure_is_one_line_and_debug_brings_the_traceback_back(capsys, monkeypatch):
    def boom(args):
        raise RuntimeError("the store is odd")
    monkeypatch.setattr(cli, "cmd_prompt", boom)
    rc, _, err = run(capsys, "prompt")
    assert rc == 1 and err.count("\n") == 1 and "RuntimeError: the store is odd" in err and "TEYLA_DEBUG=1" in err
    monkeypatch.setenv("TEYLA_DEBUG", "1")
    with pytest.raises(RuntimeError):
        cli.main(["prompt"])


@pytest.mark.parametrize("argv", [["asks"], ["notes"], ["state"], ["today"], ["product"], ["intent"], ["sessions"]])
def test_commands_a_new_user_types_work_on_an_empty_teyla_home(capsys, argv):
    rc, out, err = run(capsys, *argv)
    assert rc in (0, None) and "Traceback" not in out + err

"""Bare `teyla`: a welcome of at most 15 lines, with and without sessions, before and after `teyla start`.
Nothing here computes spend or reads a real session store: the cache is written by hand and the
background refresh is replaced by a recorder."""
from __future__ import annotations

import io
import json
import re

import pytest

from teyla import __version__, cli, figures, notes, welcome
from teyla import changes as changes_mod
from teyla.adapters import claude_code
from teyla.ui import Style

REAL_SPAWN_REFRESH = figures.spawn_refresh              # the autouse fixture replaces the module attribute
ESC = re.compile(r"\033\[")
NOW = 1_790_000_000.0
TTY_ENV = {"TERM": "xterm-256color", "COLORFGBG": "15;0"}


class TTY(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def _no_computing(monkeypatch):
    """The welcome must not compute spend and must not start a real process."""
    spawned = []
    monkeypatch.setattr(figures, "spawn_refresh", lambda: spawned.append(1) or True)
    monkeypatch.setattr(figures, "now", lambda: NOW)

    def refuse(*a, **k):
        raise AssertionError("the welcome computed something slow")
    monkeypatch.setattr(figures, "compute_spend", refuse)
    from teyla import spend
    monkeypatch.setattr(spend, "session_rows", refuse)
    return spawned


@pytest.fixture
def spawned(_no_computing):
    return _no_computing


@pytest.fixture
def sessions():
    """One Claude Code session file where the adapter looks: enough for `has_sessions`."""
    d = claude_code.DEFAULT_ROOT
    import os
    os.makedirs(os.path.join(d, "proj-a"))
    with open(os.path.join(d, "proj-a", "s1.jsonl"), "w") as fh:
        fh.write("{}\n")


def cache(spend=(412.0, 380.0), questions=3, age=60.0):
    figures.write_cache(spend={"this_week": spend[0], "last_week": spend[1], "at": NOW - age},
                        questions={"waiting": questions, "at": NOW - age})


def welcome_text(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    return out.out


def record_start(finished: bool, offers=None):
    figures.record_start({"diagnosis": {"days": 30, "total_usd": 1840.0, "sessions": 212},
                          "offers": offers if offers is not None else [
                              {"id": "O1", "title": "Compact long sessions earlier", "applies": True,
                               "saving_usd_month": {"low": 120.0, "high": 240.0}},
                              {"id": "O5", "title": "One rules file", "applies": True, "saving_usd_month": None}]},
                         finished)


# --- with sessions --------------------------------------------------------------------------------

def test_with_sessions_it_shows_three_numbers_each_with_its_command(sessions, capsys):
    cache()
    notes.add("Try a dark icon")
    out = welcome_text(capsys)
    lines = out.splitlines()
    assert lines[0] == f"T█ Teyla {__version__}"
    assert "Nothing about your sessions leaves your Mac unless you turn it on." in " ".join(out.split())
    assert any(re.match(r"  \$412\s+spent in the last 7 days\s+teyla spend$", ln) for ln in lines)
    assert any(re.match(r"  3\s+questions waiting on you\s+teyla asks$", ln) for ln in lines)
    assert any(re.match(r"  1\s+note in your Inbox\s+teyla notes --inbox$", ln) for ln in lines)


def test_the_inbox_count_is_read_now_and_the_other_two_come_from_the_cache(sessions, capsys):
    cache(questions=0)
    assert re.search(r"^  0\s+questions waiting", welcome_text(capsys), re.M)
    notes.add("one")
    notes.add("two")
    assert re.search(r"^  2\s+notes in your Inbox", welcome_text(capsys), re.M)


def test_the_welcome_is_at_most_15_lines_even_with_everything_to_say(sessions, capsys):
    cache()
    for i in range(5):
        notes.add(f"note {i}")
    record_start(False)
    out = welcome_text(capsys)
    assert 8 <= len(out.splitlines()) <= welcome.MAX_LINES == 15


def test_a_fresh_cache_starts_nothing_and_a_stale_one_starts_one_refresh(sessions, capsys, spawned):
    cache(age=60)
    welcome_text(capsys)
    assert spawned == []
    cache(age=3 * 3600)
    out = welcome_text(capsys)
    assert len(spawned) == 1
    assert "$412" in out                                  # the stale figure is still shown


def test_an_old_figure_carries_its_age_and_a_very_old_one_is_dropped(sessions, capsys):
    cache(age=2 * 86400)
    out = welcome_text(capsys)
    assert re.search(r"spent in the last 7 days\s+teyla spend\s+as of 2d ago", out)
    cache(age=9 * 86400)
    out = welcome_text(capsys)
    assert "$412" not in out and "counting now" in out


def test_without_a_cache_it_says_it_is_counting_and_starts_the_count(sessions, capsys, spawned):
    out = welcome_text(capsys)
    assert len(spawned) == 1
    assert "counting now" in out and "$" not in out
    assert re.search(r"^  0\s+notes in your Inbox", out, re.M)       # the Inbox needs no count
    assert len(out.splitlines()) <= 15


# --- without sessions -----------------------------------------------------------------------------

def test_without_sessions_it_says_so_in_one_line_and_starts_with_teyla_start(capsys, spawned):
    out = welcome_text(capsys)
    lines = out.splitlines()
    assert sum("No agent sessions found yet" in ln for ln in lines) == 1
    assert "`teyla start`" in out
    nxt = lines[lines.index("Next") + 1:]
    assert nxt[0].split()[:2] == ["teyla", "start"]
    assert "questions waiting" not in out and spawned == []


# --- the next commands ----------------------------------------------------------------------------

def next_commands(out: str) -> list[str]:
    lines = out.splitlines()
    return [" ".join(ln.split()[:2]) for ln in lines[lines.index("Next") + 1:]]


def test_the_first_next_command_is_teyla_start_until_an_offer_was_applied_or_declined(sessions, capsys):
    cache()
    assert next_commands(welcome_text(capsys)) == ["teyla start", "teyla today", "teyla help"]
    record_start(False)                                    # a diagnosis nobody went through
    assert next_commands(welcome_text(capsys))[0] == "teyla start"


def test_after_a_finished_start_the_first_next_command_is_teyla_today(sessions, capsys):
    cache()
    record_start(True)
    assert next_commands(welcome_text(capsys)) == ["teyla today", "teyla spend", "teyla help"]


def test_after_an_applied_change_the_first_next_command_is_teyla_today(sessions, capsys):
    cache()
    changes_mod.log_path().write_text(json.dumps({"id": "c1", "offer": "O1", "kind": "json", "file": "x", "key_path": ["k"]}) + "\n")
    assert next_commands(welcome_text(capsys))[0] == "teyla today"


def test_a_command_change_that_undo_refuses_counts_as_applied(sessions, capsys):
    cache()
    changes_mod.log_path().write_text(json.dumps({"id": "c1", "offer": "O5", "kind": "command", "command": "teyla policy sync"}) + "\n")
    assert next_commands(welcome_text(capsys))[0] == "teyla today"
    assert figures.applied_offers() == {"O5"}              # no undo row can ever follow: it stays in force


def test_an_undone_change_still_means_the_person_has_been_through_start(sessions, capsys):
    cache()
    changes_mod.log_path().write_text(json.dumps({"id": "c1", "offer": "O1", "kind": "json"}) + "\n"
                                      + json.dumps({"undo_of": "c1", "offer": "O1"}) + "\n")
    assert figures.onboarded() and figures.applied_offers() == set()
    assert next_commands(welcome_text(capsys))[0] == "teyla today"


def test_a_machine_with_no_changes_log_gets_teyla_start_first(sessions, capsys):
    cache()
    assert not changes_mod.log_path().exists()
    assert next_commands(welcome_text(capsys))[0] == "teyla start"


def test_unapplied_offers_with_a_saving_get_one_line_quoting_the_last_diagnosis(sessions, capsys):
    cache()
    record_start(False)
    out = welcome_text(capsys)
    (line,) = [ln for ln in out.splitlines() if "could save" in ln]
    assert "1 change could save about $120-$240 a month" in line and line.endswith("teyla start")
    changes_mod.log_path().write_text(json.dumps({"id": "c1", "offer": "O1", "kind": "json"}) + "\n")      # applied: nothing left to quote
    assert "could save" not in welcome_text(capsys)
    changes_mod.log_path().write_text(json.dumps({"id": "c1", "offer": "O1", "kind": "json"}) + "\n" + json.dumps({"undo_of": "c1", "offer": "O1"}) + "\n")
    assert "could save" in welcome_text(capsys)            # undone: it is open again


def test_a_broken_start_report_is_ignored(sessions, capsys):
    cache()
    figures.start_report_path().write_text("{nope")
    out = welcome_text(capsys)
    assert "could save" not in out and "Traceback" not in out


# --- colour ---------------------------------------------------------------------------------------

def test_a_terminal_gets_the_brand_colours_and_the_mark_is_bold_t_then_amber_block(sessions):
    cache()
    out = welcome.render(Style(TTY(), TTY_ENV), NOW)
    first = out.splitlines()[0]
    assert first.startswith("\033[1m\033[38;5;147mT\033[0m\033[0m\033[38;5;215m█\033[0m")
    assert ESC.search(out)


@pytest.mark.parametrize("env", [{**TTY_ENV, "NO_COLOR": "1"}, {"TERM": "dumb"}])
def test_no_color_and_dumb_terminals_get_plain_text(sessions, env):
    cache()
    out = welcome.render(Style(TTY(), env), NOW)
    assert not ESC.search(out) and out.startswith("T█ Teyla")


def test_piped_output_is_plain_text(sessions, capsys):
    cache()
    assert not ESC.search(welcome_text(capsys))


def test_a_terminal_that_is_not_utf8_gets_an_ascii_block(sessions):
    class Ascii(TTY):
        encoding = "ascii"
    stream = Ascii()
    assert "T#" in welcome.render(Style(stream, {"NO_COLOR": "1"}), NOW).splitlines()[0]


# --- it never fails -------------------------------------------------------------------------------

def test_bare_teyla_is_never_an_argparse_error(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr()
    assert "usage:" not in out.out + out.err and "required" not in out.err


def test_a_failure_inside_the_welcome_still_prints_the_header_and_the_way_on(capsys, monkeypatch):
    monkeypatch.setattr(welcome, "render", lambda *a, **k: 1 / 0)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"Teyla {__version__}") and "teyla help" in out and "Traceback" not in out


def test_a_corrupt_cache_is_ignored(sessions, capsys):
    figures.cache_path().write_text("not json")
    out = welcome_text(capsys)
    assert "counting now" in out


def test_the_welcome_writes_nothing_but_the_refresh_lock(sessions, capsys):
    cache()
    before = sorted(p.name for p in figures.home().iterdir())
    welcome_text(capsys)
    assert sorted(p.name for p in figures.home().iterdir()) == before


# --- the pieces under it --------------------------------------------------------------------------

def test_has_sessions_looks_in_every_store_and_stops_at_the_first_file(tmp_path, monkeypatch):
    from teyla.adapters import codex
    assert figures.has_sessions() is False
    nested = tmp_path / "codex" / "2026" / "10" / "25"
    nested.mkdir(parents=True)
    monkeypatch.setattr(codex, "DEFAULT_ROOT", str(tmp_path / "codex"))
    assert figures.has_sessions() is False                  # directories alone are not sessions
    (nested / "rollout-1.jsonl").write_text("{}\n")
    assert figures.has_sessions() is True


def test_the_refresh_starts_once_per_five_minutes(monkeypatch):
    started = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    assert REAL_SPAWN_REFRESH() is True and REAL_SPAWN_REFRESH() is False
    assert len(started) == 1 and started[0][-3:] == ["teyla", "today", "--refresh-cache"]


def _race(n: int = 16) -> list[bool]:
    import threading
    barrier, got = threading.Barrier(n), []

    def go():
        barrier.wait()
        got.append(figures.acquire_lock())
    threads = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    return got


def test_two_acquirers_get_one_lock():
    assert figures.acquire_lock() is True
    assert figures.acquire_lock() is False
    assert oct(figures._lock().stat().st_mode & 0o777) == "0o600"
    figures.release_lock()
    assert figures.acquire_lock() is True


def test_sixteen_callers_at_once_get_exactly_one_lock():
    for _ in range(5):
        figures.release_lock()
        got = _race()
        assert got.count(True) == 1 and len(got) == 16


def test_a_lock_older_than_five_minutes_is_taken_over_by_exactly_one_caller():
    import os
    figures.release_lock()
    assert figures.acquire_lock()
    old = figures.now() - figures.LOCK_STALE_S - 60
    os.utime(figures._lock(), (old, old))
    assert _race().count(True) == 1
    assert figures.now() - figures._lock().stat().st_mtime < figures.LOCK_STALE_S    # the new holder's lock is fresh
    assert [p.name for p in figures.home().iterdir() if p.name.startswith("first-screen.lock.")] == []


def test_a_lock_younger_than_five_minutes_is_respected():
    import os
    assert figures.acquire_lock()
    young = figures.now() - figures.LOCK_STALE_S + 60
    os.utime(figures._lock(), (young, young))
    assert figures.acquire_lock() is False


def test_two_refreshes_never_start_together(monkeypatch):
    import subprocess
    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **k: started.append(cmd))
    import threading
    out, barrier = [], threading.Barrier(8)

    def go():
        barrier.wait()
        out.append(REAL_SPAWN_REFRESH())
    ts = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out.count(True) == 1 and len(started) == 1


def test_the_cache_is_private_and_a_broken_one_is_replaced(sessions):
    cache()
    assert oct(figures.cache_path().stat().st_mode & 0o777) == "0o600"
    figures.cache_path().write_text("[1, 2]")
    assert figures.read_cache() == {}
    cache()
    assert figures.read_cache()["questions"]["waiting"] == 3


def test_the_ansi_helper_bolds_only_where_colour_is_on():
    from teyla import brand
    assert brand.bold("x", TTY(), TTY_ENV) == "\033[1mx\033[0m"
    assert brand.bold("x", TTY(), {"NO_COLOR": "1"}) == "x" and brand.bold("x", io.StringIO(), TTY_ENV) == "x"

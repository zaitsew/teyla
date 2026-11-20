"""`teyla corrections`: --days cuts each turn by its own time, and --recorded lists what `teyla rules
propose` counts as human, never a prompt a harness wrote."""
from __future__ import annotations

import datetime as _dt

from teyla.adapters import Session, Turn
from teyla.cli import correction_rows, recorded_rows

NOW = _dt.datetime(2026, 11, 20, 12, 0, tzinfo=_dt.timezone.utc)


def _session(sid, first, turns):
    s = Session(harness="claude-code", project="demo", sid=sid, path=f"/tmp/{sid}.jsonl", size=1)
    s.first = first
    s.last = turns[-1][0]
    s.user_turns = [Turn(ts, text, True) for ts, text in turns]
    return s


def test_days_filters_each_turn_not_the_session(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    # Started in August, resumed in November: with --days 7 only the November turn is listed, dated by itself.
    old = _session("aaaaaaaa11", "2026-08-18T09:00:00Z", [("2026-08-18T09:00:00Z", "no, wrong file"),
                                                          ("2026-11-19T09:00:00Z", "no, use the other one")])
    ancient = _session("bbbbbbbb22", "2026-08-20T09:00:00Z", [("2026-08-20T09:00:00Z", "that is wrong")])
    rows = correction_rows([old, ancient], 7, now=NOW)
    assert rows == [("2026-11-19", "demo", "aaaaaaaa", "no, use the other one")]
    assert len(correction_rows([old, ancient])) == 3                       # no window: every turn
    assert [r[0] for r in correction_rows([old], 30, now=NOW)] == ["2026-11-19"]
    assert [r[0] for r in correction_rows([old], 120, now=NOW)] == ["2026-08-18", "2026-11-19"]


def test_recorded_hides_harness_messages_and_hook_guesses():
    task = "<task-notification><task-id>b1</task-id><status>completed</status></task-notification>"
    recs = [("repo", {"ts": "2026-11-19T09:00:00+00:00", "text": "no, use the other one", "source": "correct"}),
            ("repo", {"ts": "2026-11-19T09:01:00+00:00", "text": task, "source": "correct"}),             # automated whatever the source
            ("repo", {"ts": "2026-11-19T09:02:00+00:00", "text": "that is wrong again", "source": "hook"}),   # a regex guess
            ("repo", {"ts": "2026-11-19T09:03:00+00:00", "text": task, "source": "hook"})]
    shown = recorded_rows(recs)
    assert [r["text"] for _, r in shown] == ["no, use the other one"]
    assert len(recorded_rows(recs, show_all=True)) == 4
    assert recorded_rows(recs, cutoff="2026-11-20") == []

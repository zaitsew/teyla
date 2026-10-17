"""`teyla answer` marks an item done only when the session's transcript shows the text.
A started process is not a delivery. Transcripts are tmp files; the fake `run` plays the session by
appending to them (or not). No real `claude` or `codex` starts."""
from __future__ import annotations

import datetime as dt
import json

import pytest

from teyla import answer, asks
from teyla.adapters import claude_code, codex

NOW = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.timezone.utc).timestamp()
CODEX_SID = "01a14630-4c3f-7921-91ca-b89037bced86"
CLAUDE_SID = "0bbe62f8-fca8-4e9b-b708-8362976fb8ac"


def ask(id="aaaa0001", harness="claude-desktop", session=CLAUDE_SID, link="claude://claude.ai/epitaxy/local_x"):
    return asks.Ask(id=id, kind="question", product="atlas", title="t", question="q", context="", options=[],
                    when=NOW - 3600, archived=False, link=link, pr="", harness=harness, session=session)


def claude_line(text, kind="user"):
    if kind == "assistant":
        return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    if kind == "tool_result":
        return {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t", "content": text}]}}
    return {"type": "user", "message": {"role": "user", "content": text}}


def codex_line(text):
    return {"type": "response_item", "payload": {"type": "message", "role": "user",
                                                 "content": [{"type": "input_text", "text": text}]}}


def append(path, *objs):
    with open(path, "a") as f:
        for o in objs:
            f.write(json.dumps(o) + "\n")


@pytest.fixture
def world(tmp_path, monkeypatch):
    class W:
        pass
    w = W()
    w.work = tmp_path / "work"
    w.work.mkdir()
    w.projects = tmp_path / "projects"
    w.proj = w.projects / "-work"
    w.proj.mkdir(parents=True)
    w.transcript = w.proj / f"{CLAUDE_SID}.jsonl"
    append(w.transcript, claude_line("an earlier message: Keep 1.0"))          # same text, before the start
    w.codex = tmp_path / "codex"
    w.rollout = w.codex / "2026" / "10" / "16" / f"rollout-2026-10-16T10-00-00-{CODEX_SID}.jsonl"
    w.rollout.parent.mkdir(parents=True)
    append(w.rollout, {"type": "session_meta", "payload": {"id": CODEX_SID, "cwd": str(w.work)}})
    sessions = tmp_path / "sessions" / "acct" / "work"
    sessions.mkdir(parents=True)
    (sessions / "local_x.json").write_text(json.dumps({
        "sessionId": "local_x", "cliSessionId": CLAUDE_SID, "cwd": str(w.work), "originCwd": str(w.work),
        "permissionMode": "acceptEdits", "lastActivityAt": 1, "createdAt": 1}))
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(w.projects))
    monkeypatch.setattr(codex, "DEFAULT_ROOT", str(w.codex))
    monkeypatch.setattr(codex, "DEFAULT_ARCHIVE_ROOT", "")
    monkeypatch.setattr(answer, "CONFIRM_POLL_S", 0.01)
    w.items = []
    monkeypatch.setattr(asks, "collect", lambda *a, **k: w.items)
    w.session = lambda cmd, cwd=None, input_text=None, timeout=30, detach=None: (0, "out")     # a session that ignores it
    monkeypatch.setattr(answer, "run", lambda *a, **k: w.session(*a, **k))
    return w


def done():
    return asks.load_state()["done"]


# --- claude ------------------------------------------------------------------------------------

def test_claude_is_done_only_when_the_transcript_gains_the_text(world):
    def session(cmd, **kw):
        append(world.transcript, claude_line("Keep 1.0"))
        return 0, "out"
    world.session = session
    r = answer.answer(ask(), "Keep 1.0", now=NOW, wait_s=0)
    assert r == {"ok": True, "via": "claude-bg", "detail": "out", "id": "aaaa0001"}
    assert done()["aaaa0001"]["note"] == "answered in Teyla via claude-bg"


def test_a_started_process_with_no_entry_is_not_confirmed_and_leaves_the_ask_open(world):
    r = answer.answer(ask(), "Keep 1.0", now=NOW, wait_s=0)
    assert r == {"ok": True, "via": "claude-bg", "detail": "started, not confirmed yet", "id": "aaaa0001"}
    assert "aaaa0001" not in done()


def test_only_a_user_entry_after_the_start_counts(world):
    def session(cmd, **kw):
        append(world.transcript, claude_line("I will Keep 1.0 then", "assistant"), claude_line("Keep 1.0", "tool_result"))
        return 0, "out"
    world.session = session
    r = answer.answer(ask(), "Keep 1.0", now=NOW, wait_s=0)
    assert r["detail"] == answer.NOT_CONFIRMED and "aaaa0001" not in done()


def test_a_copy_started_for_a_running_session_counts(world):
    def session(cmd, **kw):
        append(world.proj / "11111111-2222-3333-4444-555555555555.jsonl", claude_line("Keep 1.0"))
        return 0, "out"
    world.session = session
    r = answer.answer(ask(), "Keep 1.0", now=NOW, wait_s=0)
    assert r["detail"] == "out" and "aaaa0001" in done()


def test_a_multi_line_answer_matches_despite_whitespace(world):
    def session(cmd, **kw):
        append(world.transcript, claude_line("Keep   1.0\n\nship it"))
        return 0, "out"
    world.session = session
    r = answer.answer(ask(), "Keep 1.0\nship it", now=NOW, wait_s=0)
    assert r["detail"] == "out" and "aaaa0001" in done()


def test_the_wait_polls_until_the_entry_appears_and_is_bounded(world, monkeypatch):
    sleeps = []

    def late_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 3:
            append(world.transcript, claude_line("Keep 1.0"))
    monkeypatch.setattr(answer.time, "sleep", late_sleep)
    r = answer.answer(ask(), "Keep 1.0", now=NOW, wait_s=5)
    assert r["detail"] == "out" and len(sleeps) == 3
    sleeps.clear()
    monkeypatch.setattr(answer.time, "sleep", lambda s: sleeps.append(s))
    world.transcript.write_text("")
    r = answer.answer(ask("aaaa0002"), "never arrives", now=NOW, wait_s=0.05)
    assert r["detail"] == answer.NOT_CONFIRMED and "aaaa0002" not in done()


def test_the_default_waits_stay_inside_fifteen_seconds():
    assert answer.DETACH_WAIT_S + answer.CONFIRM_WAIT_S <= 15


def test_a_session_with_no_transcript_cannot_be_confirmed(world):
    world.transcript.unlink()
    r = answer.answer(ask(), "Keep 1.0", now=NOW, wait_s=0)
    assert r["detail"] == answer.NOT_CONFIRMED and "aaaa0001" not in done()


# --- codex -------------------------------------------------------------------------------------

def codex_ask():
    return ask("aaaa0002", harness="codex", session=CODEX_SID, link=f"codex resume {CODEX_SID}")


def test_codex_resume_is_done_when_the_rollout_gains_the_text(world):
    def session(cmd, **kw):
        assert cmd[:4] == ["codex", "exec", "resume", CODEX_SID]
        append(world.rollout, codex_line("yes do it"))
        return 0, "out"
    world.session = session
    r = answer.answer(codex_ask(), "yes do it", now=NOW, wait_s=0)
    assert (r["ok"], r["via"], r["detail"]) == (True, "codex-resume", "out")
    assert done()["aaaa0002"]["note"] == "answered in Teyla via codex-resume"


def test_codex_event_user_message_counts_and_assistant_output_does_not(world):
    def session(cmd, **kw):
        append(world.rollout, {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "yes do it"}]}})
        return 0, "out"
    world.session = session
    r = answer.answer(codex_ask(), "yes do it", now=NOW, wait_s=0)
    assert r["detail"] == answer.NOT_CONFIRMED and "aaaa0002" not in done()
    append(world.rollout, {"type": "event_msg", "payload": {"type": "user_message", "message": "yes do it"}})
    before = {}
    assert answer.arrived({"kind": "codex", "session": CODEX_SID}, before, "yes do it")


def test_codex_not_confirmed_does_not_fall_through_to_the_queue(world):
    calls = []
    world.session = lambda cmd, **kw: (calls.append(cmd) or (0, "out"))
    r = answer.answer(codex_ask(), "yes", now=NOW, wait_s=0)
    assert r["detail"] == answer.NOT_CONFIRMED and [c[1] for c in calls] == ["exec"]


def test_a_start_that_fails_still_falls_through_to_the_next_step(world):
    codes = [1, 0]
    world.session = lambda cmd, **kw: (codes.pop(0), "out")
    r = answer.answer(codex_ask(), "yes", now=NOW, wait_s=0)
    assert r["via"] == "codex-queue" and "aaaa0002" in done()

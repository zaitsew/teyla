"""Trustworthy numbers: one noise classification, one correction matcher, and batch sessions
that are never human turns — built from the shapes 2026-09's transcripts actually had
(anonymised: paths, ids and prompt text are made up, the record structure is real)."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from collections import Counter

import pytest

from teyla.adapters import Session, Turn, claude_code, codex, hermes, human_text, is_correction, is_noise_turn, is_retry
from teyla.advise import advise, mark_seen
from teyla.monitor import metrics


def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


# --- the matcher ------------------------------------------------------------------------------

# Shapes of real 2026-09 corrections, reworded.
CORRECTIONS = [
    "You use too much GitHub actions",                                          # missed by 0.11: no keyword
    "Can you make changes and don’t use GitHub actions at all, or only when necessary?",  # missed: curly ’
    "No, I mean the folder you created yesterday",
    "You are wrong - I sent 3 comments, not 2",
    "Something wrong with the formatting",
    "Why did you push one commit when you said there were 14?",
    "Where is the video? I haven't asked you to change it",
    "I don't like the title, too long",
    "never use npm in this project, always pnpm",
    "Pages /today and /learned do not work for me",
    "For the app, I again got a link, not a code",
    "You still didn't understand me. Go 2 steps back",
    "revert that last change",
    "не так, я же говорил — через конфиг",
    "Опять ничего не понял",
    "Я думаю ты неправильно уловил суть",
    "Зачем ты это удалил?",
    "Сделай сам или доведи до шага, где нужно моё действие",
    "Это не то, что мне нужно",
    "Ты зря остановил discovery",
]

# Instructions, questions and reports that 0.11 counted and a person would not call a correction.
NOT_CORRECTIONS = [
    "Don't forget to deploy everything to github",      # an instruction, not pushback (precision over recall)
    "I don't mind agencies as additional hypotheses",
    "I set a hard spend limit, don't worry",
    "I don't understand what 'preference Elo' means",
    "Any tools I can use instead of building my own?",
    "Do we actually need to store rules in one file?",
    "So run again with OpenAI and propose the final structure",
    "Keep going non-stop for the next 3 hours",
    "Do you still have p2/p3 tasks unresolved?",
    "Зачем мне нужен gbrain?",
    "Снова скорее всего поменялся IP из-за отключения электричества",
    "Потраченные токены и время не зря?",
    "Ты не мог бы проверить логи?",
    "Try again",
    "add a --json flag to the sessions command",
]


@pytest.mark.parametrize("text", CORRECTIONS)
def test_real_correction_shapes_are_matched(text):
    assert is_correction(text)


@pytest.mark.parametrize("text", NOT_CORRECTIONS)
def test_instructions_questions_and_retries_are_not(text):
    assert not is_correction(text)


def test_a_brief_is_never_a_correction():
    assert not is_correction("Review this diff. Do not run anything; it is wrong to guess. " + "x" * 800)


# --- noise ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "[Artifact comment sent to Claude] on the pricing section: wrong number",
    '<artifact-view-context artifact="00000000-0000-0000-0000-000000000000">\n{"context":{"mode":"canvas"}}',
    "<system-reminder>\nYou are operating in a git worktree. Don't commit to main again.\n</system-reminder>",
    "  <system-reminder>a</system-reminder>\n<system-reminder>b</system-reminder>  ",
    "[SYSTEM NOTIFICATION - NOT USER INPUT] background task finished",
    "Try again", "try again.", "Continue", "ещё раз", "Retry please",
])
def test_harness_turns_and_retries_are_not_human_text(text):
    assert human_text(text) is None


def test_a_reminder_appended_to_a_real_prompt_is_cut_off_not_decisive():
    assert human_text("add the flag\n<system-reminder>don't do that again</system-reminder>") == "add the flag"


def test_a_retry_with_content_is_a_retry_only_right_after_an_api_error():
    assert is_retry("Try again - the connector is available now", after_error=True)
    assert not is_retry("Try again - the connector is available now")
    assert not is_retry("try again with pnpm, not npm", after_error=False)
    assert not is_noise_turn("Try again")  # a retry is dropped by human_text, not mistaken for a harness turn


# --- batch sessions, per harness --------------------------------------------------------------

def test_claude_try_again_after_an_api_error_is_not_a_turn_and_never_reaches_a9(tmp_path):
    """The real shape: a synthetic assistant record with isApiErrorMessage, two
    queue-operation records, then the human's "Try again". 13 of these made A9's top shape."""
    root = tmp_path / "projects"
    for n in range(13):
        _write(str(root / "-Users-me-repos-app" / f"s{n}.jsonl"), [
            {"type": "user", "timestamp": "2026-09-20T10:00:00Z", "entrypoint": "claude-desktop",
             "message": {"role": "user", "content": "ship the fix"}},
            {"type": "assistant", "timestamp": "2026-09-20T10:00:05Z", "isApiErrorMessage": True, "error": "server_error",
             "message": {"model": "<synthetic>", "role": "assistant",
                         "content": [{"type": "text", "text": "API Error: Can't reach the API server (ENOTFOUND)"}]}},
            {"type": "queue-operation", "timestamp": "2026-09-20T10:01:00Z"},
            {"type": "queue-operation", "timestamp": "2026-09-20T10:01:01Z"},
            {"type": "user", "timestamp": "2026-09-20T10:01:02Z", "entrypoint": "claude-desktop",
             "message": {"role": "user", "content": "Try again - the connector is back"}},
        ])
    ss = claude_code.load(root=str(root))
    assert all(s.n_user == 1 and s.n_corr == 0 for s in ss)
    m = metrics(ss)
    assert m["user_turns"] == 13 and m["corrections"] == 0
    assert not [f for f in advise(m) if f["id"] == "A9"]


def test_a9_ignores_retries_in_an_old_metrics_file():
    m = metrics([])
    m["correction_samples"] = ["Try again"] * 13 + ["no, use pnpm"] * 2
    a9 = [f for f in advise(m) if f["id"] == "A9"]
    assert len(a9) == 1 and "most frequent 2 times" in a9[0]["evidence"]


@pytest.mark.parametrize("entrypoint,batch", [("sdk-cli", True), ("sdk-py", True), ("sdk-ts", True),
                                               ("claude-desktop", False), ("cli", False)])
def test_claude_sdk_entrypoints_are_batch(tmp_path, entrypoint, batch):
    root = tmp_path / "projects"
    _write(str(root / "-Users-me-ops" / "s.jsonl"), [
        {"type": "user", "timestamp": "2026-09-24T00:00:00Z", "entrypoint": entrypoint,
         "message": {"role": "user", "content": "Review PR #1. Do not run any command; that approach is wrong."}}])
    [s] = claude_code.load(root=str(root))
    assert s.batch is batch and s.n_user == (0 if batch else 1)


def test_codex_desktop_injected_two_part_message_is_not_a_human_turn(tmp_path):
    """Codex's desktop app opens a thread with one user message in two parts —
    <recommended_plugins> and <environment_context>. 0.11 wanted a single block, so all 11
    such threads of 2026-09 counted their plugin list as the human's first turn."""
    day = tmp_path / "sessions" / "2026" / "09" / "05"
    _write(str(day / "rollout-2026-09-05T00-00-00-d1.jsonl"), [
        {"timestamp": "2026-09-05T00:00:00.000Z", "type": "session_meta",
         "payload": {"session_id": "d1", "id": "d1", "cwd": "/Users/me/repos/app", "source": "vscode",
                     "originator": "codex-chrome-extension-sidepanel", "thread_source": "user"}},
        {"timestamp": "2026-09-05T00:00:01.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [
             {"type": "input_text", "text": "<recommended_plugins>\nHere is a list of plugins that are available but not "
                                            "installed.\n\n- Example (app-000@openai-curated-remote)\n</recommended_plugins>"},
             {"type": "input_text", "text": "<environment_context>\n  <cwd>/Users/me/repos/app</cwd>\n</environment_context>"}]}},
        {"timestamp": "2026-09-05T00:00:02.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [
             {"type": "input_text", "text": "<in-app-browser-context>\nurl: https://example.com\n</in-app-browser-context>\n"
                                            "why did you change the header?"}]}},
    ])
    [s] = codex.load(root=str(tmp_path / "sessions"), archive_root=str(tmp_path / "x"), index_path=str(tmp_path / "x.jsonl"))
    assert s.batch is False
    assert [t.text for t in s.user_turns] == ["why did you change the header?"] and s.n_corr == 1


@pytest.mark.parametrize("source,originator", [
    ("exec", "codex_exec"),
    ({"subagent": "review"}, "codex_exec"),
    ({"subagent": {"thread_spawn": {"parent_thread_id": "p", "depth": 1}}}, "Codex Desktop"),
])
def test_codex_exec_review_and_spawned_agents_are_batch(tmp_path, source, originator):
    day = tmp_path / "sessions" / "2026" / "09" / "21"
    _write(str(day / "rollout-2026-09-21T00-00-00-x.jsonl"), [
        {"timestamp": "2026-09-21T00:00:00.000Z", "type": "session_meta",
         "payload": {"session_id": "x", "cwd": "/r", "source": source, "originator": originator}},
        {"timestamp": "2026-09-21T00:00:01.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [
             {"type": "input_text", "text": "You are a security reviewer. Do not edit; say what is wrong."}]}}])
    [s] = codex.load(root=str(tmp_path / "sessions"), archive_root=str(tmp_path / "x"), index_path=str(tmp_path / "x.jsonl"))
    assert s.batch is True and s.n_user == 0 and s.n_corr == 0


def test_hermes_one_shot_is_batch_desktop_is_not(tmp_path):
    db = tmp_path / "state.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sessions (id TEXT, source TEXT, model TEXT, cwd TEXT, git_repo_root TEXT, session_key TEXT,"
                " title TEXT, started_at REAL, ended_at REAL, last_activity_at REAL, input_tokens INTEGER,"
                " output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER)")
    con.execute("CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, tool_name TEXT, timestamp REAL)")
    for sid, src in (("z", "cli"), ("d", "desktop")):
        con.execute("INSERT INTO sessions VALUES (?,?,'m','/r',NULL,NULL,NULL,1790000000,1790000100,NULL,0,0,0,0)", (sid, src))
        con.execute("INSERT INTO messages VALUES (?, 'user', 'that is wrong, redo it', NULL, 1790000001)", (sid,))
    con.commit(); con.close()
    ss = {s.sid: s for s in hermes.load(root=str(db))}
    assert ss["z"].batch is True and ss["z"].n_user == 0
    assert ss["d"].batch is False and ss["d"].n_corr == 1


def test_no_metric_counts_a_batch_turn(tmp_path):
    """Human turns, correction rate, A5 and A9 over a week shaped like 2026-09-21: 188 codex
    exec reviews whose briefs are correction-shaped, next to 60 human turns."""
    batch = []
    for i in range(188):
        s = Session(harness="codex", project="/r", sid=f"b{i}", path="/x", size=1, batch=True)
        s.first = "2026-09-21T00:00:00Z"
        s.user_turns = [Turn(s.first, "Do not run anything. What is wrong here? Revert nothing.", True)]
        batch.append(s)
    human = Session(harness="claude-code", project="p", sid="h", path="/y", size=1)
    human.first = "2026-09-21T00:00:00Z"
    human.user_turns = [Turn(human.first, f"step {i}", False) for i in range(60)]
    m = metrics(batch + [human])
    assert m["user_turns"] == 60 and m["corrections"] == 0 and m["correction_samples"] == []
    assert not [f for f in advise(m) if f["id"] in ("A5", "A9")]


# --- the capture hook skips headless runs -----------------------------------------------------

HOOK = os.path.join(os.path.dirname(__file__), "..", "plugin", "hooks", "capture-correction.sh")


def _hook(tmp_path, payload, **env):
    e = {**os.environ, "TEYLA_HOME": str(tmp_path / "th"), "TEYLA_PYTHON": sys.executable, **env}
    subprocess.run(["sh", HOOK], input=json.dumps(payload), text=True, check=True, env=e, capture_output=True)
    f = tmp_path / "th" / "corrections" / "misc.jsonl"
    return [json.loads(l)["text"] for l in f.read_text().splitlines()] if f.exists() else []


def test_hook_skips_claude_print_mode(tmp_path):
    assert _hook(tmp_path, {"prompt": "that is wrong", "cwd": str(tmp_path)}, CLAUDE_CODE_ENTRYPOINT="sdk-cli") == []
    assert _hook(tmp_path, {"prompt": "that is wrong", "cwd": str(tmp_path)}, CLAUDE_CODE_ENTRYPOINT="claude-desktop") == ["that is wrong"]


def test_hook_skips_the_user_query_envelope(tmp_path):
    """41 of 2026-09's 107 records: `grok -p` review briefs, delivered through the Cursor hook
    wrapped in <user_query>."""
    brief = "<user_query>\nReview the follow-up commit below. Do not read files; say what is wrong.\n</user_query>"
    assert _hook(tmp_path, {"hookEventName": "user_prompt_submit", "prompt": brief, "workspaceRoot": str(tmp_path)}) == []


def test_hook_skips_hermes_one_shot(tmp_path):
    payload = {"hook_event_name": "pre_llm_call", "cwd": str(tmp_path), "extra": {"user_message": "that is wrong"}}
    assert _hook(tmp_path, payload, HERMES_YOLO_MODE="1", HERMES_ACCEPT_HOOKS="1") == []


def test_hook_skips_retries_and_artifact_relays(tmp_path):
    for p in ("Try again", "[Artifact comment sent to Claude] wrong number on slide 3",
              "<system-reminder>\nwrong again\n</system-reminder>"):
        assert _hook(tmp_path, {"prompt": p, "cwd": str(tmp_path)}) == []


# --- A10 --------------------------------------------------------------------------------------

def _gov_session(day):
    s = Session(harness="claude-code", project="demo", sid=f"s{day}", path="/x", size=1)
    s.first = f"{day}T00:00:00Z"
    s.gov_edits = 1
    return s


def _home(tmp_path, monkeypatch, text, ack=None):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / "CLAUDE.md").write_text(text)
    if ack:
        (tmp_path / ".teyla").mkdir(exist_ok=True)
        (tmp_path / ".teyla" / "ack.json").write_text(json.dumps({"claude_md": ack}))


def _a10(m):
    return [f for f in advise(m) if f["id"] == "A10"]


def test_a10_never_acked_is_one_medium_shown_once_per_version(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, "v1")
    m = metrics([_gov_session("2026-09-14"), _gov_session("2026-09-15")])
    [f] = _a10(m)
    assert f["severity"] == "medium" and "`teyla policy ack` after reviewing" in f["action"]
    mark_seen([f])
    assert _a10(m) == [], "shown once: the same file does not raise it again next week"
    (tmp_path / ".claude" / "CLAUDE.md").write_text("v2")
    assert [x["severity"] for x in _a10(m)] == ["medium"], "a new version of the file is shown again"


def test_a10_high_only_for_edits_after_the_ack_and_says_how_many(tmp_path, monkeypatch):
    old = hashlib.sha256(b"v1").hexdigest()
    _home(tmp_path, monkeypatch, "v2", ack={"sha256": old, "date": "2026-09-20"})
    m = metrics([_gov_session("2026-09-14"), _gov_session("2026-09-18"), _gov_session("2026-09-23")])
    [f] = _a10(m)
    assert f["severity"] == "high"
    assert f["evidence"].startswith("1 of 3 session edit(s)") and "(2026-09-20)" in f["evidence"]


def test_a10_changed_file_but_no_session_edit_after_the_ack_is_medium(tmp_path, monkeypatch):
    old = hashlib.sha256(b"v1").hexdigest()
    _home(tmp_path, monkeypatch, "v2", ack={"sha256": old, "date": "2026-09-25"})
    [f] = _a10(metrics([_gov_session("2026-09-14")]))
    assert f["severity"] == "medium" and "changed since your ack" in f["title"]


def test_a10_same_day_edits_are_named_not_counted_as_after_the_ack(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, "v2", ack={"sha256": hashlib.sha256(b"v1").hexdigest(), "date": "2026-09-20"})
    [f] = _a10(metrics([_gov_session("2026-09-20")]))
    assert f["severity"] == "medium" and "1 more on the ack day itself" in f["evidence"]


def test_codex_keeps_a_pasted_block_in_front_of_a_real_question():
    assert codex.strip_injected("<config>\na=1\n</config>\nwhy is this wrong?") == "<config>\na=1\n</config>\nwhy is this wrong?"
    assert codex.strip_injected("<environment_context>x</environment_context>\n<config>a</config>\nq") == "<config>a</config>\nq"
    assert codex.strip_injected("<anything>x</anything>") == ""


def test_proceed_is_a_decision_not_a_retry():
    assert human_text("proceed") == "proceed" and human_text("continue") is None


def test_a10_acked_and_unchanged_is_silent(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch, "v1", ack={"sha256": hashlib.sha256(b"v1").hexdigest(), "date": "2026-09-25"})
    assert _a10(metrics([_gov_session("2026-09-14"), _gov_session("2026-09-25")])) == []

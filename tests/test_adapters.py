"""Adapter tests against tiny synthetic fixtures written inline to tmp_path.

Each fixture is deliberately small (a handful of lines) and mirrors the real record shapes
found on-disk for that harness, not an idealized schema.
"""
from __future__ import annotations

import json
import os
import sqlite3

from teyla.adapters import claude_code, codex, grok, hermes


def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


# ---------------------------------------------------------------------------
# claude_code
# ---------------------------------------------------------------------------

def test_claude_code_basic(tmp_path):
    root = tmp_path / "projects"
    f = root / "-Users-me-repos-demo" / "sess1.jsonl"
    _write(str(f), [
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Users/me/repos/demo",
         "message": {"role": "user", "content": "please add a login button"}},
        {"type": "assistant", "timestamp": "2026-01-01T00:00:05Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5",
                     "usage": {"input_tokens": 100, "output_tokens": 50,
                               "cache_read_input_tokens": 10, "cache_creation_input_tokens": 0},
                     "content": [{"type": "text", "text": "done"}]}},
        {"type": "user", "timestamp": "2026-01-01T00:01:00Z",
         "message": {"role": "user", "content": "no, that's wrong, do it again"}},
        {"type": "assistant", "timestamp": "2026-01-01T00:01:05Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5",
                     "usage": {"input_tokens": 20, "output_tokens": 10,
                               "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                     "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
    ])
    sessions = claude_code.load(root=str(root))
    assert len(sessions) == 1
    s = sessions[0]
    assert s.harness == "claude-code"
    assert s.models["claude-sonnet-5"] == 2
    assert s.tokens["input_tokens"] == 120
    assert s.tokens["output_tokens"] == 60
    assert s.n_user == 2
    assert s.n_corr == 1
    assert s.tools["Bash"] == 1


def test_claude_code_filters_noise_turns(tmp_path):
    root = tmp_path / "projects"
    f = root / "slug" / "sess2.jsonl"
    _write(str(f), [
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z",
         "message": {"role": "user", "content": "<system-reminder>ignore me</system-reminder>"}},
        {"type": "user", "timestamp": "2026-01-01T00:00:01Z",
         "message": {"role": "user", "content": "real prompt here"}},
    ])
    sessions = claude_code.load(root=str(root))
    assert len(sessions) == 1
    assert sessions[0].n_user == 1
    assert sessions[0].user_turns[0].text == "real prompt here"


def test_claude_code_active_hours_sums_small_gaps(tmp_path):
    root = tmp_path / "projects"
    f = root / "slug" / "sess3.jsonl"
    _write(str(f), [
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "start"}},
        {"type": "assistant", "timestamp": "2026-01-01T00:05:00Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5", "usage": {},
                     "content": [{"type": "text", "text": "ok"}]}},
        {"type": "user", "timestamp": "2026-01-01T00:10:00Z", "message": {"role": "user", "content": "continue"}},
    ])
    sessions = claude_code.load(root=str(root))
    s = sessions[0]
    # Two 5-minute gaps, both under the 30-minute ceiling: 600s -> 0.17h.
    assert abs(s.active_hours - 0.17) < 0.01


def test_claude_code_active_hours_excludes_gap_from_session_resumed_after_days(tmp_path):
    root = tmp_path / "projects"
    f = root / "slug" / "sess4.jsonl"
    _write(str(f), [
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "start"}},
        {"type": "assistant", "timestamp": "2026-01-01T00:02:00Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5", "usage": {},
                     "content": [{"type": "text", "text": "ok"}]}},
        # resumed three days later
        {"type": "user", "timestamp": "2026-01-04T00:02:30Z", "message": {"role": "user", "content": "continue"}},
        {"type": "assistant", "timestamp": "2026-01-04T00:04:30Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5", "usage": {},
                     "content": [{"type": "text", "text": "done"}]}},
    ])
    sessions = claude_code.load(root=str(root))
    s = sessions[0]
    # Wall span is ~3 days; active time is only the two small in-session gaps (120s + 120s).
    assert s.hours > 70
    assert s.active_hours < 0.2


def test_claude_code_missing_root_raises(tmp_path):
    try:
        claude_code.load(root=str(tmp_path / "nope"))
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# codex
# ---------------------------------------------------------------------------

def test_codex_basic(tmp_path):
    root = tmp_path / "sessions" / "2026" / "01" / "01"
    f = root / "rollout-2026-01-01T00-00-00-abc123.jsonl"
    lines = [
        {"timestamp": "2026-01-01T00:00:00.000Z", "type": "session_meta",
         "payload": {"session_id": "abc123", "cwd": "/Users/me/repos/demo"}},
        {"timestamp": "2026-01-01T00:00:01.000Z", "type": "turn_context",
         "payload": {"turn_id": "t1", "model": "gpt-5.5"}},
        {"timestamp": "2026-01-01T00:00:02.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "<environment_context>noise</environment_context>"}]}},
        {"timestamp": "2026-01-01T00:00:03.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "fix the failing test"}]}},
        {"timestamp": "2026-01-01T00:00:04.000Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "exec_command", "arguments": "{}"}},
        {"timestamp": "2026-01-01T00:00:05.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "fixed"}]}},
        {"timestamp": "2026-01-01T00:00:06.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "no, that's not it, try again"}]}},
        {"timestamp": "2026-01-01T00:00:07.000Z", "type": "event_msg",
         "payload": {"type": "token_count",
                     "info": {"total_token_usage": {"input_tokens": 500, "cached_input_tokens": 50,
                                                     "cache_write_input_tokens": 0, "output_tokens": 80,
                                                     "reasoning_output_tokens": 20}}}},
    ]
    _write(str(f), lines)
    sessions = codex.load(root=str(tmp_path / "sessions"), archive_root=str(tmp_path / "no-archive"),
                           index_path=str(tmp_path / "no-index.jsonl"))
    assert len(sessions) == 1
    s = sessions[0]
    assert s.harness == "codex"
    assert s.sid == "abc123"
    assert s.cwd == "/Users/me/repos/demo"
    assert s.models["gpt-5.5"] == 1
    assert s.n_user == 2  # the <environment_context> turn is excluded
    assert s.n_corr == 1
    assert s.tools["exec_command"] == 1
    assert s.tokens["input_tokens"] == 500
    assert s.tokens["cache_read_input_tokens"] == 50
    assert s.tokens["output_tokens"] == 80  # reasoning_output_tokens is a detail of output_tokens, not added


def test_codex_spawn_agent(tmp_path):
    root = tmp_path / "sessions" / "2026" / "01" / "01"
    f = root / "rollout-2026-01-01T00-00-00-def456.jsonl"
    lines = [
        {"timestamp": "2026-01-01T00:00:00.000Z", "type": "session_meta",
         "payload": {"session_id": "def456", "cwd": "/Users/me/repos/demo"}},
        {"timestamp": "2026-01-01T00:00:01.000Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "collaboration.spawn_agent",
                     "arguments": json.dumps({"task_name": "reviewer", "model": "gpt-5-mini"})}},
    ]
    _write(str(f), lines)
    sessions = codex.load(root=str(tmp_path / "sessions"), archive_root=str(tmp_path / "no-archive"),
                           index_path=str(tmp_path / "no-index.jsonl"))
    s = sessions[0]
    assert len(s.agents) == 1
    assert s.agents[0].model == "gpt-5-mini"
    assert s.agents[0].desc == "reviewer"


def test_codex_missing_root_raises(tmp_path):
    try:
        codex.load(root=str(tmp_path / "nope"))
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_codex_reasoning_tokens_not_double_counted(tmp_path):
    # reasoning_output_tokens is OpenAI's breakdown detail of output_tokens, not an addition to
    # it -- summing them would double-count the reasoning spend.
    root = tmp_path / "sessions" / "2026" / "01" / "01"
    f = root / "rollout-2026-01-01T00-00-00-ghi789.jsonl"
    lines = [
        {"timestamp": "2026-01-01T00:00:00.000Z", "type": "session_meta",
         "payload": {"session_id": "ghi789", "cwd": "/Users/me/repos/demo"}},
        {"timestamp": "2026-01-01T00:00:01.000Z", "type": "turn_context",
         "payload": {"turn_id": "t1", "model": "gpt-5.5"}},
        {"timestamp": "2026-01-01T00:00:02.000Z", "type": "event_msg",
         "payload": {"type": "token_count",
                     "info": {"total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 0,
                                                     "cache_write_input_tokens": 0, "output_tokens": 200,
                                                     "reasoning_output_tokens": 150}}}},
    ]
    _write(str(f), lines)
    sessions = codex.load(root=str(tmp_path / "sessions"), archive_root=str(tmp_path / "no-archive"),
                           index_path=str(tmp_path / "no-index.jsonl"))
    s = sessions[0]
    assert s.tokens["output_tokens"] == 200


# ---------------------------------------------------------------------------
# grok
# ---------------------------------------------------------------------------

def test_grok_basic(tmp_path):
    root = tmp_path / "sessions"
    cwd_dir = root / "%2FUsers%2Fme%2Frepos%2Fdemo"
    sess_dir = cwd_dir / "sess-1"
    os.makedirs(sess_dir, exist_ok=True)
    with open(cwd_dir / "prompt_history.jsonl", "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "session_id": "sess-1",
                              "prompt": "add a health check endpoint", "is_bash": False}) + "\n")
        fh.write(json.dumps({"timestamp": "2026-01-01T00:01:00Z", "session_id": "sess-1",
                              "prompt": "no, don't do it that way", "is_bash": False}) + "\n")
    with open(sess_dir / "summary.json", "w") as fh:
        json.dump({"info": {"id": "sess-1", "cwd": "/Users/me/repos/demo"},
                    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:01:00Z",
                    "current_model_id": "grok-4.6"}, fh)
    with open(sess_dir / "signals.json", "w") as fh:
        json.dump({"modelsUsed": ["grok-4.6"], "primaryModelId": "grok-4.6"}, fh)
    with open(sess_dir / "chat_history.jsonl", "w") as fh:
        fh.write(json.dumps({"type": "assistant", "content": "ok",
                              "tool_calls": [{"name": "run_terminal_command"}]}) + "\n")

    sessions = grok.load(root=str(root))
    assert len(sessions) == 1
    s = sessions[0]
    assert s.harness == "grok"
    assert s.cwd == "/Users/me/repos/demo"
    assert s.models["grok-4.6"] == 1
    assert s.n_user == 2
    assert s.n_corr == 1
    assert s.tools["run_terminal_command"] == 1


def test_grok_batch_flag_on_single_prompt_session(tmp_path):
    # A session with <=1 prompt is a programmatic one-shot call (`grok -p` from a pipeline),
    # not a human at the keyboard: it should be flagged batch, not the old sidechain.
    root = tmp_path / "sessions"
    cwd_dir = root / "%2FUsers%2Fme%2Frepos%2Fdemo"
    sess_dir = cwd_dir / "sess-batch"
    os.makedirs(sess_dir, exist_ok=True)
    with open(cwd_dir / "prompt_history.jsonl", "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "session_id": "sess-batch",
                              "prompt": "summarize this diff", "is_bash": False}) + "\n")
    with open(sess_dir / "summary.json", "w") as fh:
        json.dump({"info": {"id": "sess-batch", "cwd": "/Users/me/repos/demo"},
                    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:05Z"}, fh)
    with open(sess_dir / "signals.json", "w") as fh:
        json.dump({"modelsUsed": ["grok-4.6"]}, fh)

    sessions = grok.load(root=str(root))
    s = sessions[0]
    assert s.batch is True
    assert s.sidechain is False


def test_grok_last_timestamp_not_clobbered_by_last_prompt(tmp_path):
    # The human's last prompt can land well before the assistant's final activity; s.last must
    # reflect the max across summary/signals/prompt timestamps, not just the last prompt seen
    # (which used to produce a bogus zero-ish duration).
    root = tmp_path / "sessions"
    cwd_dir = root / "%2FUsers%2Fme%2Frepos%2Fdemo"
    sess_dir = cwd_dir / "sess-late"
    os.makedirs(sess_dir, exist_ok=True)
    with open(cwd_dir / "prompt_history.jsonl", "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "session_id": "sess-late",
                              "prompt": "kick off the refactor", "is_bash": False}) + "\n")
        fh.write(json.dumps({"timestamp": "2026-01-01T00:00:10Z", "session_id": "sess-late",
                              "prompt": "go ahead", "is_bash": False}) + "\n")
    with open(sess_dir / "summary.json", "w") as fh:
        json.dump({"info": {"id": "sess-late", "cwd": "/Users/me/repos/demo"},
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T01:30:00Z"}, fh)
    with open(sess_dir / "signals.json", "w") as fh:
        json.dump({"modelsUsed": ["grok-4.6"]}, fh)

    sessions = grok.load(root=str(root))
    s = sessions[0]
    assert s.first == "2026-01-01T00:00:00Z"
    assert s.last == "2026-01-01T01:30:00Z"
    assert s.hours == 1.5


def test_grok_compaction_count(tmp_path):
    root = tmp_path / "sessions"
    cwd_dir = root / "%2FUsers%2Fme%2Frepos%2Fdemo"
    sess_dir = cwd_dir / "sess-compact"
    os.makedirs(sess_dir, exist_ok=True)
    with open(cwd_dir / "prompt_history.jsonl", "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "session_id": "sess-compact",
                              "prompt": "keep going", "is_bash": False}) + "\n")
        fh.write(json.dumps({"timestamp": "2026-01-01T00:05:00Z", "session_id": "sess-compact",
                              "prompt": "and again", "is_bash": False}) + "\n")
    with open(sess_dir / "summary.json", "w") as fh:
        json.dump({"info": {"id": "sess-compact", "cwd": "/Users/me/repos/demo"},
                    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:05:00Z"}, fh)
    with open(sess_dir / "signals.json", "w") as fh:
        json.dump({"modelsUsed": ["grok-4.6"], "compactionCount": 3}, fh)

    sessions = grok.load(root=str(root))
    assert sessions[0].compactions == 3


def test_grok_dir_size_is_recursive(tmp_path):
    root = tmp_path / "sessions"
    cwd_dir = root / "%2FUsers%2Fme%2Frepos%2Fdemo"
    sess_dir = cwd_dir / "sess-nested"
    nested = sess_dir / "attachments"
    os.makedirs(nested, exist_ok=True)
    with open(cwd_dir / "prompt_history.jsonl", "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "session_id": "sess-nested",
                              "prompt": "attach this file", "is_bash": False}) + "\n")
    with open(sess_dir / "summary.json", "w") as fh:
        json.dump({"info": {"id": "sess-nested", "cwd": "/Users/me/repos/demo"},
                    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:01Z"}, fh)
    with open(sess_dir / "signals.json", "w") as fh:
        json.dump({"modelsUsed": ["grok-4.6"]}, fh)
    top_level_size = len(b"top-level")
    (sess_dir / "note.txt").write_bytes(b"top-level")
    nested_size = len(b"nested-file-contents")
    (nested / "extra.bin").write_bytes(b"nested-file-contents")

    sessions = grok.load(root=str(root))
    assert sessions[0].size >= top_level_size + nested_size


def test_grok_spawn_subagent(tmp_path):
    root = tmp_path / "sessions"
    cwd_dir = root / "%2FUsers%2Fme%2Frepos%2Fdemo"
    sess_dir = cwd_dir / "sess-sub"
    os.makedirs(sess_dir, exist_ok=True)
    with open(cwd_dir / "prompt_history.jsonl", "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "session_id": "sess-sub",
                              "prompt": "land this PR", "is_bash": False}) + "\n")
        fh.write(json.dumps({"timestamp": "2026-01-01T00:01:00Z", "session_id": "sess-sub",
                              "prompt": "go", "is_bash": False}) + "\n")
    with open(sess_dir / "summary.json", "w") as fh:
        json.dump({"info": {"id": "sess-sub", "cwd": "/Users/me/repos/demo"},
                    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:01:00Z"}, fh)
    with open(sess_dir / "signals.json", "w") as fh:
        json.dump({"modelsUsed": ["grok-4.6"]}, fh)
    with open(sess_dir / "chat_history.jsonl", "w") as fh:
        fh.write(json.dumps({
            "type": "assistant", "content": "spawning a subagent",
            "tool_calls": [{"name": "spawn_subagent",
                             "arguments": json.dumps({"description": "Land the roadmap PR",
                                                       "subagent_type": "general-purpose"})}],
        }) + "\n")

    sessions = grok.load(root=str(root))
    s = sessions[0]
    assert s.tools["spawn_subagent"] == 1
    assert len(s.agents) == 1
    assert s.agents[0].model is None
    assert s.agents[0].kind == "grok-subagent"
    assert s.agents[0].desc == "Land the roadmap PR"


def test_grok_hash_session_dir_reads_cwd_from_dotfile(tmp_path):
    # Newer layout: a hash-named session dir sits directly under root (no urlencoded-cwd
    # container), with a .cwd file naming the real working directory.
    root = tmp_path / "sessions"
    sess_dir = root / "a1b2c3d4e5f6"
    os.makedirs(sess_dir, exist_ok=True)
    with open(sess_dir / ".cwd", "w") as fh:
        fh.write("/Users/me/repos/hashed\n")
    with open(sess_dir / "summary.json", "w") as fh:
        json.dump({"info": {"id": "a1b2c3d4e5f6"},
                    "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:05Z"}, fh)
    with open(sess_dir / "signals.json", "w") as fh:
        json.dump({"modelsUsed": ["grok-4.6"]}, fh)

    sessions = grok.load(root=str(root))
    assert len(sessions) == 1
    assert sessions[0].cwd == "/Users/me/repos/hashed"


def test_grok_missing_root_raises(tmp_path):
    try:
        grok.load(root=str(tmp_path / "nope"))
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# hermes
# ---------------------------------------------------------------------------

def _make_hermes_db(path):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE sessions (
        id TEXT, source TEXT, model TEXT, cwd TEXT, git_repo_root TEXT, session_key TEXT,
        title TEXT, started_at REAL, ended_at REAL, last_activity_at REAL,
        input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER
    )""")
    con.execute("""CREATE TABLE session_model_usage (
        session_id TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER,
        cache_read_tokens INTEGER, cache_write_tokens INTEGER
    )""")
    con.execute("""CREATE TABLE messages (
        session_id TEXT, role TEXT, content TEXT, tool_name TEXT, timestamp REAL
    )""")
    con.execute("""CREATE TABLE async_delegations (
        origin_session TEXT, parent_session_id TEXT, task_json TEXT
    )""")
    con.execute("INSERT INTO sessions VALUES ('s1','cli','grok-4.6','/Users/me/repos/demo',NULL,NULL,"
                "'a title',1700000000,1700000100,1700000100,0,0,0,0)")
    con.execute("INSERT INTO session_model_usage VALUES ('s1','grok-4.6',100,50,10,0)")
    con.execute("INSERT INTO messages VALUES ('s1','user','write a haiku about tests',NULL,1700000001)")
    con.execute("INSERT INTO messages VALUES ('s1','user',\"no, don't do that\",NULL,1700000050)")
    con.execute("INSERT INTO messages VALUES ('s1','assistant','ok','write_file',1700000060)")
    con.commit()
    con.close()


def test_hermes_basic(tmp_path):
    db = tmp_path / "state.db"
    _make_hermes_db(str(db))
    sessions = hermes.load(root=str(db))
    assert len(sessions) == 1
    s = sessions[0]
    assert s.harness == "hermes"
    assert s.cwd == "/Users/me/repos/demo"
    assert s.models["grok-4.6"] == 1
    assert s.tokens["input_tokens"] == 100
    assert s.tokens["output_tokens"] == 50
    assert s.n_user == 2
    assert s.n_corr == 1
    assert s.tools["write_file"] == 1


def test_hermes_missing_root_raises(tmp_path):
    try:
        hermes.load(root=str(tmp_path / "nope.db"))
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass


def test_noise_turns_include_notifications_interrupts_and_continuations():
    from teyla.adapters import is_noise_turn
    assert is_noise_turn("<task-notification>\n<task-id>a1</task-id>\n<output>done, but don't…</output>")
    assert is_noise_turn("<command-message>_gstack-command</command-message>\n<command-name>/ship</command-name>")
    assert is_noise_turn("[Request interrupted by user for tool use]")
    assert is_noise_turn("This session is being continued from a previous conversation that ran out of context. The summary…")
    assert not is_noise_turn("don't do that again")
    assert not is_noise_turn("<p>an html snippet the human pasted</p>")


def test_capture_correction_hook_skips_harness_injected_prompts(tmp_path):
    """The plugin hook applies the same noise list as is_noise_turn; the measured failure was
    35 subagent notifications filed as corrections in one repo."""
    import json, subprocess, pathlib
    hook = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "capture-correction.sh"
    out = tmp_path / ".teyla" / "corrections.jsonl"

    def run(prompt):
        subprocess.run(["sh", str(hook)], input=json.dumps({"prompt": prompt, "cwd": str(tmp_path)}), text=True, check=True)

    run("<task-notification>\n<task-id>x</task-id>\n<output>I could not do it again</output>\n</task-notification>")
    run("[Request interrupted by user]")
    run("This session is being continued from a previous conversation that ran out of context. Don't repeat.")
    run("<command-message>_gstack-command</command-message>\n<command-name>/ship</command-name> revert")
    assert not out.exists()
    run("no, don't use npm here, again: pnpm")
    assert out.exists() and json.loads(out.read_text().splitlines()[0])["text"].startswith("no, don't use npm")


# --- cursor: one sqlite store, composers + bubbles ---------------------------------------------

def _cursor_db(path, composers):
    import sqlite3
    con = sqlite3.connect(str(path))
    con.execute("create table cursorDiskKV (key text primary key, value text)")
    con.execute("create table ItemTable (key text primary key, value text)")
    for cid, comp, bubbles in composers:
        con.execute("insert into cursorDiskKV values (?, ?)", (f"composerData:{cid}", json.dumps(comp)))
        for i, b in enumerate(bubbles):
            con.execute("insert into cursorDiskKV values (?, ?)", (f"bubbleId:{cid}:b{i}", json.dumps(b)))
    con.commit(); con.close()


def test_cursor_sessions_from_state_vscdb(tmp_path):
    from teyla.adapters import cursor
    db = tmp_path / "state.vscdb"
    comp = {"composerId": "c1", "name": "X outbound plan", "createdAt": 1787077425163, "lastUpdatedAt": 1787087300084,
            "unifiedMode": "agent", "modelConfig": {"modelName": "grok-4.6"},
            "workspaceIdentifier": {"id": "w", "uri": {"fsPath": "/Users/me/ops"}}, "contextTokensUsed": 141808}
    bubbles = [
        {"type": 1, "createdAt": "2026-08-18T18:23:45.247Z", "text": "I'm building routine X", "modelInfo": {"modelName": "grok-4.6"}},
        {"type": 2, "createdAt": "2026-08-18T18:23:50.000Z", "text": "", "toolFormerData": {"name": "glob_file_search", "status": "completed"}},
        {"type": 2, "createdAt": "2026-08-18T18:24:00.000Z", "text": "done"},
        {"type": 1, "createdAt": "2026-08-18T18:30:00.000Z", "text": "no, not like that — again"},
    ]
    empty = {"composerId": "c2", "createdAt": 1787077425163, "lastUpdatedAt": 1787077425163, "modelConfig": {"modelName": "grok-4.6"}}
    _cursor_db(db, [("c1", comp, bubbles), ("c2", empty, [])])
    ss = {s.sid: s for s in cursor.load(root=str(db))}
    s = ss["c1"]
    assert s.harness == "cursor" and s.project == "/Users/me/ops" and s.cwd == "/Users/me/ops" and s.title == "X outbound plan"
    assert s.first == "2026-08-18T18:23:45.163000+00:00" and s.last.startswith("2026-08-18T21:08:20")
    assert dict(s.models) == {"grok-4.6": 1} and not s.usage
    assert s.n_user == 2 and s.n_corr == 1 and s.assistant_turns == 2 and dict(s.tools) == {"glob_file_search": 1}
    assert ss["c2"].n_user == 0 and ss["c2"].project == "?"


def test_cursor_missing_or_foreign_store(tmp_path):
    import pytest, sqlite3
    from teyla.adapters import cursor
    with pytest.raises(FileNotFoundError):
        cursor.load(root=str(tmp_path / "nope.vscdb"))
    other = tmp_path / "other.vscdb"
    con = sqlite3.connect(str(other)); con.execute("create table ItemTable (key text, value text)"); con.commit(); con.close()
    assert cursor.load(root=str(other)) == []


def test_capture_correction_hook_reads_every_harness_shape_and_deduplicates(tmp_path):
    import json, subprocess, pathlib
    hook = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "capture-correction.sh"
    out = tmp_path / ".teyla" / "corrections.jsonl"

    def run(payload):
        subprocess.run(["sh", str(hook)], input=json.dumps(payload), text=True, check=True, cwd=tmp_path)

    run({"hookEventName": "user_prompt_submit", "prompt": "don't do that", "workspaceRoot": str(tmp_path)})          # grok
    run({"hook_event_name": "pre_llm_call", "tool_name": None, "cwd": str(tmp_path),
         "extra": {"user_message": "wrong file, revert it", "is_first_turn": False}})                              # hermes
    run({"prompt": "again: use pnpm", "cwd": str(tmp_path)})                                                       # claude / cursor
    run({"prompt": "again: use pnpm", "cwd": str(tmp_path)})                                                       # grok re-delivering cursor's hook
    run({"hook_event_name": "pre_llm_call", "extra": {"user_message": "fine, carry on"}, "cwd": str(tmp_path)})   # not a correction
    recs = [json.loads(l) for l in out.read_text().splitlines()]
    assert [r["text"] for r in recs] == ["don't do that", "wrong file, revert it", "again: use pnpm"]
    assert all(r["cwd"] == str(tmp_path) for r in recs)

"""connectors.py tests: adapter-level jsonl fixtures for connector_calls/skills_read collection,
plus metrics()/advise() against hand-rolled Sessions for the two shapes that matter most —
a person-lookup-heavy connector (C2) and a round-trip tail (C1)."""
from __future__ import annotations

import argparse
import json
import os

from teyla.adapters import Session
from teyla.adapters import claude_code, codex
from teyla.connectors import advise, classify_result, metrics, parse_mcp_tool, register, render_table


def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


# ---------------------------------------------------------------------------
# parse_mcp_tool / classify_result — small pure-function units
# ---------------------------------------------------------------------------

def test_parse_mcp_tool_splits_on_first_double_underscore():
    assert parse_mcp_tool("mcp__myserver__create_item") == ("myserver", "create_item")
    assert parse_mcp_tool("mcp__otherserver__dismiss_task") == ("otherserver", "dismiss_task")
    assert parse_mcp_tool("mcp__calendar__create_event") == ("calendar", "create_event")


def test_parse_mcp_tool_rejects_non_mcp_names():
    assert parse_mcp_tool("Bash") is None
    assert parse_mcp_tool("mcp__onlyserver") is None
    assert parse_mcp_tool("") is None
    assert parse_mcp_tool(None) is None


def test_classify_result_error_wins():
    assert classify_result(True, "anything at all") == "error"


def test_classify_result_empty_content():
    assert classify_result(False, "") == "empty"
    assert classify_result(False, None) == "empty"
    assert classify_result(False, []) == "empty"


def test_classify_result_short_no_results_string_is_empty():
    assert classify_result(False, "no results") == "empty"
    assert classify_result(False, "[]") == "empty"
    assert classify_result(False, "Not found") == "empty"


def test_classify_result_long_or_substantive_content_is_ok():
    assert classify_result(False, "here are the 12 issues you asked for: ...") == "ok"
    assert classify_result(False, [{"type": "text", "text": "sent"}]) == "ok"


# ---------------------------------------------------------------------------
# claude_code adapter: tool_use / tool_result jsonl fixtures
# ---------------------------------------------------------------------------

def test_claude_code_collects_connector_calls_and_skill_reads(tmp_path):
    root = tmp_path / "projects"
    f = root / "-Users-me-repos-demo" / "sess1.jsonl"
    _write(str(f), [
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "cwd": "/Users/me/repos/demo",
         "message": {"role": "user", "content": "find alice's slack id and message her"}},
        {"type": "assistant", "timestamp": "2026-01-01T00:00:01Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5", "usage": {},
                     "content": [{"type": "tool_use", "id": "tu1", "name": "mcp__messaging__find_user",
                                  "input": {"query": "alice"}}]}},
        {"type": "user", "timestamp": "2026-01-01T00:00:02Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "tu1", "is_error": False, "content": "no results"}]}},
        {"type": "assistant", "timestamp": "2026-01-01T00:00:03Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5", "usage": {},
                     "content": [{"type": "tool_use", "id": "tu2", "name": "mcp__messaging__resolve",
                                  "input": {"query": "alice"}}]}},
        {"type": "user", "timestamp": "2026-01-01T00:00:04Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "tu2", "is_error": True, "content": "permission denied"}]}},
        {"type": "assistant", "timestamp": "2026-01-01T00:00:05Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5", "usage": {},
                     "content": [{"type": "tool_use", "id": "tu3", "name": "Read",
                                  "input": {"file_path": "/Users/me/.claude/skills/outbound/SKILL.md"}}]}},
        {"type": "user", "timestamp": "2026-01-01T00:00:06Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "tu3", "content": [{"type": "text", "text": "# Outbound\n..."}]}]}},
        # a second human turn -- calls after this point should carry turn_index 1
        {"type": "user", "timestamp": "2026-01-01T00:01:00Z",
         "message": {"role": "user", "content": "ok now actually send it"}},
        {"type": "assistant", "timestamp": "2026-01-01T00:01:01Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5", "usage": {},
                     "content": [{"type": "tool_use", "id": "tu4", "name": "mcp__messaging__send_message",
                                  "input": {"to": "alice", "text": "hi"}}]}},
        {"type": "user", "timestamp": "2026-01-01T00:01:02Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "tu4", "content": [{"type": "text", "text": "message sent, id=42"}]}]}},
    ])
    sessions = claude_code.load(root=str(root))
    assert len(sessions) == 1
    s = sessions[0]

    assert len(s.connector_calls) == 3  # the Read tool_use is not an mcp__ call
    by_tool = {c["tool"]: c for c in s.connector_calls}
    assert by_tool["find_user"] == dict(server="messaging", tool="find_user", turn_index=1, result="empty")
    assert by_tool["resolve"] == dict(server="messaging", tool="resolve", turn_index=1, result="error")
    assert by_tool["send_message"] == dict(server="messaging", tool="send_message", turn_index=2, result="ok")

    assert s.skills_read["outbound"] == 1


def test_claude_code_ignores_non_mcp_tool_use(tmp_path):
    root = tmp_path / "projects"
    f = root / "slug" / "sess2.jsonl"
    _write(str(f), [
        {"type": "user", "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "run the tests"}},
        {"type": "assistant", "timestamp": "2026-01-01T00:00:01Z",
         "message": {"role": "assistant", "model": "claude-sonnet-5", "usage": {},
                     "content": [{"type": "tool_use", "id": "tu1", "name": "Bash", "input": {"command": "pytest"}}]}},
        {"type": "user", "timestamp": "2026-01-01T00:00:02Z",
         "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu1", "content": "5 passed"}]}},
    ])
    sessions = claude_code.load(root=str(root))
    assert sessions[0].connector_calls == []


# ---------------------------------------------------------------------------
# codex adapter: function_call / function_call_output jsonl fixtures
# ---------------------------------------------------------------------------

def test_codex_collects_connector_calls(tmp_path):
    root = tmp_path / "sessions" / "2026" / "01" / "01"
    f = root / "rollout-2026-01-01T00-00-00-conn001.jsonl"
    lines = [
        {"timestamp": "2026-01-01T00:00:00.000Z", "type": "session_meta",
         "payload": {"session_id": "conn001", "cwd": "/Users/me/repos/demo"}},
        {"timestamp": "2026-01-01T00:00:01.000Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "list open tickets"}]}},
        {"timestamp": "2026-01-01T00:00:02.000Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "mcp__atlassian__issue_search",
                     "arguments": "{}", "call_id": "call_1"}},
        {"timestamp": "2026-01-01T00:00:03.000Z", "type": "response_item",
         "payload": {"type": "function_call_output", "call_id": "call_1", "output": "[]"}},
        {"timestamp": "2026-01-01T00:00:04.000Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "mcp__atlassian__issue_create",
                     "arguments": "{}", "call_id": "call_2"}},
        {"timestamp": "2026-01-01T00:00:05.000Z", "type": "response_item",
         "payload": {"type": "function_call_output", "call_id": "call_2", "output": "created TICK-42"}},
    ]
    _write(str(f), lines)
    sessions = codex.load(root=str(tmp_path / "sessions"), archive_root=str(tmp_path / "no-archive"),
                           index_path=str(tmp_path / "no-index.jsonl"))
    s = sessions[0]
    assert len(s.connector_calls) == 2
    by_tool = {c["tool"]: c for c in s.connector_calls}
    assert by_tool["issue_search"] == dict(server="atlassian", tool="issue_search", turn_index=1, result="empty")
    assert by_tool["issue_create"] == dict(server="atlassian", tool="issue_create", turn_index=1, result="ok")


# ---------------------------------------------------------------------------
# metrics() / advise() — hand-rolled Sessions
# ---------------------------------------------------------------------------

def _session(sid, calls):
    s = Session(harness="claude-code", project="demo", sid=sid, path=f"/tmp/{sid}.jsonl", size=1000)
    s.first = s.last = "2026-01-01T00:00:00Z"
    s.connector_calls = calls
    return s


def test_metrics_basic_shape_and_read_write_split():
    calls = [
        dict(server="atlassian", tool="issue-search", turn_index=0, result="ok"),
        dict(server="atlassian", tool="issue-search", turn_index=0, result="ok"),
        dict(server="atlassian", tool="issue-create", turn_index=1, result="ok"),
        dict(server="atlassian", tool="issue-update", turn_index=1, result="error"),
    ]
    m = metrics([_session("s1", calls)])
    c = m["connectors"]["atlassian"]
    assert c["sessions"] == 1
    assert c["calls"] == 4
    assert c["read"] == 2 and c["write"] == 2  # create/update count as writes
    assert c["error"] == 1 and c["error_rate"] == 0.25
    assert c["empty"] == 0
    assert ("issue-search", 2) in c["top_tools"]


def test_metrics_person_lookup_heavy_connector_triggers_c2():
    # Mirrors the case study: a messaging connector where identity-resolution tools are most
    # of the traffic. 10 calls, 6 are find_user/resolve (60% > the 40% C2 threshold).
    calls = []
    for i in range(6):
        calls.append(dict(server="messaging", tool="find_user" if i % 2 == 0 else "resolve",
                           turn_index=i, result="ok"))
    for i in range(4):
        calls.append(dict(server="messaging", tool="send_message", turn_index=i, result="ok"))
    m = metrics([_session("s1", calls)])
    c = m["connectors"]["messaging"]
    assert c["calls"] == 10
    assert c["rediscovery_share"] > 0.4
    ids = {f["id"] for f in advise(m)}
    assert "C2" in ids


def test_metrics_p95_tail_triggers_c1():
    # Four ordinary human turns (2 calls each) and one where the agent goes searching blind
    # (90 calls in a single turn) -- the case study's "median is fine, the max is the problem".
    calls = []
    for turn in range(4):
        for _ in range(2):
            calls.append(dict(server="atlassian", tool="issue-search", turn_index=turn, result="ok"))
    for _ in range(90):
        calls.append(dict(server="atlassian", tool="issue-search", turn_index=4, result="ok"))
    m = metrics([_session("s1", calls)])
    c = m["connectors"]["atlassian"]
    assert c["segment_max"] == 90
    assert c["segment_p95"] > 25
    ids = {f["id"] for f in advise(m)}
    assert "C1" in ids


def test_metrics_empty_or_error_triggers_c3():
    calls = [dict(server="drive", tool="get_file", turn_index=i, result="ok") for i in range(14)]
    calls += [dict(server="drive", tool="search_files", turn_index=i, result="empty") for i in range(3)]
    calls += [dict(server="drive", tool="get_file", turn_index=i, result="error") for i in range(3)]
    m = metrics([_session("s1", calls)])
    c = m["connectors"]["drive"]
    assert c["calls"] == 20
    assert round(c["empty_rate"] + c["error_rate"], 2) == 0.3
    ids = {f["id"] for f in advise(m)}
    assert "C3" in ids


def test_metrics_low_volume_high_error_triggers_c4_not_c1():
    calls = [dict(server="m365", tool="get_event", turn_index=0, result="ok") for _ in range(4)]
    calls += [dict(server="m365", tool="get_event", turn_index=0, result="error") for _ in range(5)]
    m = metrics([_session("s1", calls)])
    c = m["connectors"]["m365"]
    assert c["calls"] == 9
    assert c["error_rate"] > 0.4
    ids = {f["id"] for f in advise(m)}
    assert "C4" in ids
    assert "C1" not in ids  # far too few calls/segments for a round-trip tail


def test_metrics_days_filter():
    import datetime as dt
    old = _session("old", [dict(server="atlassian", tool="issue-search", turn_index=0, result="ok")])
    old.first = old.last = "2020-01-01T00:00:00+00:00"
    recent = _session("recent", [dict(server="atlassian", tool="issue-search", turn_index=0, result="ok")])
    now = dt.datetime.now(dt.timezone.utc)
    recent.first = recent.last = now.isoformat()
    m = metrics([old, recent], days=7)
    assert m["n_sessions"] == 1
    assert m["connectors"]["atlassian"]["calls"] == 1


def test_metrics_no_connector_calls_is_empty_not_an_error():
    m = metrics([_session("s1", [])])
    assert m["connectors"] == {}


def test_advise_never_includes_arguments_or_results():
    # advise() text should only ever reference names/numbers, never the raw content that
    # classify_result saw -- spot-check by making sure the raw "content" strings never leak in.
    calls = [dict(server="messaging", tool="find_user", turn_index=i, result="empty") for i in range(10)]
    m = metrics([_session("s1", calls)])
    findings = advise(m)
    blob = json.dumps(findings)
    assert "no results" not in blob and "not found" not in blob


def test_render_table_handles_empty_and_populated_metrics():
    assert "No connector" in render_table(metrics([]))
    calls = [dict(server="atlassian", tool="issue-search", turn_index=0, result="ok")]
    out = render_table(metrics([_session("s1", calls)]))
    assert "atlassian" in out
    assert "issue-search" in out


def test_register_wires_a_connectors_subcommand():
    parser = argparse.ArgumentParser()
    sp = parser.add_subparsers(dest="cmd", required=True)
    register(sp)
    args = parser.parse_args(["connectors", "--json", "--days", "14", "--project", "demo"])
    assert args.cmd == "connectors"
    assert args.json is True
    assert args.days == 14
    assert args.project == "demo"
    assert callable(args.fn)

"""teyla mcp: the JSON-RPC loop driven with in-memory streams. The child process that runs Teyla is replaced
everywhere except one end-to-end test that talks to a real `python -m teyla mcp`; nothing reads ~/.teyla."""
from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

from teyla import __version__, cli, helpgroups, mcp

ROOT = pathlib.Path(__file__).resolve().parents[1]


class Runner:
    """Stands in for mcp.run_teyla: records every call and returns a canned answer."""

    def __init__(self, rc=0, out="ok\n", err="", boom=None):
        self.rc, self.out, self.err, self.boom, self.calls = rc, out, err, boom, []

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        if self.boom:
            raise self.boom
        return self.rc, self.out, self.err


@pytest.fixture
def runner(monkeypatch):
    r = Runner()
    monkeypatch.setattr(mcp, "run_teyla", r)
    return r


def talk(*messages) -> list[dict]:
    """Send messages (dicts, or raw strings) through the loop; return the replies."""
    lines = [m if isinstance(m, str) else json.dumps(m) for m in messages]
    out = io.StringIO()
    assert mcp.serve(io.StringIO("\n".join(lines) + "\n"), out) == 0
    return [json.loads(x) for x in out.getvalue().splitlines()]


def req(id_, method, params=None):
    m = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        m["params"] = params
    return m


def call(name, arguments=None, id_=1):
    return talk(req(id_, "tools/call", {"name": name, "arguments": arguments or {}}))[0]


# --- handshake --------------------------------------------------------------------------------

@pytest.mark.parametrize("asked", ["2025-06-18", "2025-03-26", "2024-11-05"])
def test_initialize_echoes_a_supported_version(asked):
    (r,) = talk(req(1, "initialize", {"protocolVersion": asked, "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}))
    assert r["id"] == 1 and r["result"]["protocolVersion"] == asked
    assert r["result"]["capabilities"] == {"tools": {}}
    assert r["result"]["serverInfo"] == {"name": "teyla", "version": __version__}


@pytest.mark.parametrize("params", [{"protocolVersion": "2030-01-01"}, {}, None])
def test_initialize_falls_back_to_the_newest_version(params):
    (r,) = talk(req(1, "initialize", params))
    assert r["result"]["protocolVersion"] == "2025-06-18"


def test_initialized_notification_gets_no_reply_and_ping_works():
    replies = talk({"jsonrpc": "2.0", "method": "notifications/initialized"}, req(7, "ping"))
    assert replies == [{"jsonrpc": "2.0", "id": 7, "result": {}}]


def test_any_notification_gets_no_reply_even_an_unknown_one():
    assert talk({"jsonrpc": "2.0", "method": "no/such"}, {"jsonrpc": "2.0", "method": "tools/list"}) == []


# --- tools/list -------------------------------------------------------------------------------

NAMES = ["teyla_asks", "teyla_answer", "teyla_intent", "teyla_load", "teyla_routines", "teyla_monitor"]


def test_tools_list_shape():
    (r,) = talk(req(1, "tools/list"))
    tools = r["result"]["tools"]
    assert [t["name"] for t in tools] == NAMES
    for t in tools:
        assert t["description"].strip()
        assert t["inputSchema"]["type"] == "object" and t["inputSchema"]["additionalProperties"] is False
        assert set(t["annotations"]) >= {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
        assert "argv" not in t and "timeout" not in t
        for p in t["inputSchema"]["required"]:
            assert p in t["inputSchema"]["properties"]
        for spec in t["inputSchema"]["properties"].values():
            assert spec["description"]
    assert {t["name"] for t in tools if t["annotations"]["readOnlyHint"]} == set(NAMES) - {"teyla_answer"}
    assert not any(t["annotations"]["destructiveHint"] for t in tools)
    answer = next(t for t in tools if t["name"] == "teyla_answer")
    assert answer["inputSchema"]["required"] == ["id", "text"]
    assert "user wrote or explicitly approved" in answer["description"] and "made up" in answer["description"]
    assert answer["annotations"]["openWorldHint"] is False
    assert next(t for t in tools if t["name"] == "teyla_routines")["annotations"]["openWorldHint"] is True


def test_no_state_changing_word_is_reachable():
    text = json.dumps(mcp.list_tools())
    for word in ("--record", "--wait", "--admit", "--issues", "--allow-network", "--share", "--samples", "backfill", "snooze",
                 "--model"):
        assert word not in text


# --- argv -------------------------------------------------------------------------------------

CASES = [
    ("teyla_asks", {}, ["asks", "--json"]),
    ("teyla_asks", {"days": 3, "product": "alpha", "all": True}, ["asks", "--json", "--days", "3", "--product=alpha", "--all"]),
    ("teyla_asks", {"all": False}, ["asks", "--json"]),
    ("teyla_answer", {"id": "ab12", "text": "yes, ship it"}, ["answer", "--json", "--", "ab12", "yes, ship it"]),
    ("teyla_answer", {"id": "ab12", "text": "-n no", "dry": True}, ["answer", "--json", "--dry", "--", "ab12", "-n no"]),
    ("teyla_intent", {}, ["intent", "--json"]),
    ("teyla_intent", {"product": "alpha", "days": 7, "grep": "-x"}, ["intent", "--json", "--days", "7", "--grep=-x", "alpha"]),
    ("teyla_load", {}, ["load", "--json"]),
    ("teyla_routines", {}, ["routines", "--json"]),
    ("teyla_routines", {"paths": ["a", "b c"]}, ["routines", "--json", "a", "b c"]),
    ("teyla_monitor", {}, ["monitor", "--json", "--no-mark-seen"]),
    ("teyla_monitor", {"days": 30, "project": "alpha"}, ["monitor", "--json", "--no-mark-seen", "--days", "30", "--project=alpha"]),
]


@pytest.mark.parametrize("name,args,argv", CASES)
def test_each_tool_builds_the_right_argv(runner, name, args, argv):
    r = call(name, args)
    assert runner.calls[0][0] == argv
    assert r["result"] == {"content": [{"type": "text", "text": "ok\n"}], "isError": False}


def test_a_shell_metacharacter_stays_one_argv_item(runner):
    call("teyla_answer", {"id": "ab", "text": "$(rm -rf ~); echo `x` | cat"})
    assert runner.calls[0][0][-1] == "$(rm -rf ~); echo `x` | cat"


def test_every_tool_has_a_timeout(runner):
    for n in NAMES:
        call(n, {"id": "a", "text": "b"} if n == "teyla_answer" else {})
    assert len(runner.calls) == len(NAMES) and all(0 < t <= 600 for _, t in runner.calls)


# --- errors from the command ------------------------------------------------------------------

def test_nonzero_exit_is_a_tool_error_not_a_protocol_error(monkeypatch):
    monkeypatch.setattr(mcp, "run_teyla", Runner(rc=1, out='{"ok": false}\n', err="teyla: boom\n"))
    r = call("teyla_load")
    assert "error" not in r and r["result"]["isError"] is True
    text = r["result"]["content"][0]["text"]
    assert "status 1" in text and "teyla: boom" in text and '{"ok": false}' in text


def test_timeout_is_a_tool_error(monkeypatch):
    monkeypatch.setattr(mcp, "run_teyla", Runner(boom=subprocess.TimeoutExpired(["x"], 1)))
    r = call("teyla_monitor")
    assert r["result"]["isError"] is True and "timed out" in r["result"]["content"][0]["text"]


def test_a_missing_interpreter_is_a_tool_error(monkeypatch):
    monkeypatch.setattr(mcp, "run_teyla", Runner(boom=FileNotFoundError("nope")))
    assert call("teyla_load")["result"]["isError"] is True


def test_an_unexpected_exception_does_not_end_the_loop(monkeypatch):
    monkeypatch.setattr(mcp, "run_teyla", Runner(boom=RuntimeError("bug")))
    replies = talk(req(1, "tools/call", {"name": "teyla_load", "arguments": {}}), req(2, "ping"))
    assert replies[0]["result"]["isError"] is True and replies[1]["result"] == {}


def test_empty_output_still_returns_a_text_item(monkeypatch):
    monkeypatch.setattr(mcp, "run_teyla", Runner(out=""))
    assert call("teyla_load")["result"]["content"][0]["text"] == "(no output)"


def test_output_is_capped_with_a_note(monkeypatch):
    monkeypatch.setattr(mcp, "run_teyla", Runner(out="x" * (mcp.MAX_TEXT + 500)))
    text = call("teyla_asks")["result"]["content"][0]["text"]
    assert text.startswith("x" * mcp.MAX_TEXT) and "500 more characters" in text
    assert len(text) < mcp.MAX_TEXT + 300


def test_output_at_the_cap_is_not_cut(monkeypatch):
    monkeypatch.setattr(mcp, "run_teyla", Runner(out="y" * mcp.MAX_TEXT))
    assert call("teyla_asks")["result"]["content"][0]["text"] == "y" * mcp.MAX_TEXT


# --- bad requests -----------------------------------------------------------------------------

def test_unknown_method_is_32601():
    (r,) = talk(req(5, "resources/list"))
    assert r["error"]["code"] == -32601 and r["id"] == 5


def test_parse_error_is_32700_with_null_id_and_the_loop_survives():
    replies = talk("{not json", req(2, "ping"))
    assert replies[0] == {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
    assert replies[1]["result"] == {}


@pytest.mark.parametrize("bad", ['"a string"', "42", "null", '{"id": 3}', '{"jsonrpc": "2.0", "id": 3, "method": 5}',
                                 '{"jsonrpc": "2.0", "id": [1], "method": "ping"}', "[]"])
def test_a_non_request_is_an_invalid_request_not_a_crash(bad):
    (r,) = talk(bad)
    assert r["error"]["code"] == -32600


def test_a_batch_gets_a_batch_of_replies_without_the_notifications():
    (r,) = talk([req(1, "ping"), {"jsonrpc": "2.0", "method": "notifications/initialized"}, req(2, "bogus")])
    assert [x["id"] for x in r] == [1, 2] and r[1]["error"]["code"] == -32601


def test_a_client_response_is_ignored():
    assert talk({"jsonrpc": "2.0", "id": 9, "result": {}}) == []


def test_blank_lines_are_skipped_and_eof_ends_cleanly():
    out = io.StringIO()
    assert mcp.serve(io.StringIO("\n\n"), out) == 0 and out.getvalue() == ""


@pytest.mark.parametrize("params", [[], "x", 3])
def test_params_must_be_an_object(params):
    (r,) = talk({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": params})
    assert r["error"]["code"] == -32602


@pytest.mark.parametrize("name,args", [
    ("no_such_tool", {}),
    ("teyla_asks", {"days": "7"}),
    ("teyla_asks", {"days": True}),
    ("teyla_asks", {"days": 1.5}),
    ("teyla_asks", {"days": 0}),
    ("teyla_asks", {"days": 99999}),
    ("teyla_asks", {"product": 3}),
    ("teyla_asks", {"all": "yes"}),
    ("teyla_asks", {"nope": 1}),
    ("teyla_asks", {"product": "a\0b"}),
    ("teyla_answer", {"id": "ab"}),
    ("teyla_answer", {"text": "x"}),
    ("teyla_answer", {"id": "ab", "text": "  "}),
    ("teyla_answer", {"id": "--json", "text": "x"}),
    ("teyla_answer", {"id": "ab", "text": "x", "dry": 1}),
    ("teyla_answer", {"id": "ab", "text": "x" * (mcp.MAX_ARG + 1)}),
    ("teyla_intent", {"product": "-x"}),
    ("teyla_intent", {"product": "backfill"}),
    ("teyla_intent", {"grep": ["a"]}),
    ("teyla_load", {"record": True}),
    ("teyla_routines", {"paths": "a"}),
    ("teyla_routines", {"paths": [1]}),
    ("teyla_routines", {"paths": ["--issues"]}),
    ("teyla_monitor", {"days": None}),
])
def test_bad_arguments_are_32602_and_nothing_runs(runner, name, args):
    r = call(name, args)
    assert r["error"]["code"] == -32602
    assert runner.calls == []


def test_arguments_must_be_an_object(runner):
    (r,) = talk(req(1, "tools/call", {"name": "teyla_load", "arguments": [1]}))
    assert r["error"]["code"] == -32602
    (r,) = talk(req(1, "tools/call", {"name": 5}))
    assert r["error"]["code"] == -32602
    (r,) = talk(req(1, "tools/call", {"name": "teyla_load"}))      # arguments may be left out
    assert r["result"]["isError"] is False


# --- the command ------------------------------------------------------------------------------

def test_list_tools_flag(capsys):
    assert cli.main(["mcp", "--list-tools"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert [ln.split()[0] for ln in out] == NAMES and all(len(ln) < 100 for ln in out)


def test_the_command_is_in_a_help_group():
    assert helpgroups.group_of("mcp") == "Setup"


def test_real_run_teyla_runs_the_cli_with_stdin_closed():
    rc, out, err = mcp.run_teyla(["--version"], 60)
    assert rc == 0 and __version__ in out


def test_real_run_teyla_kills_the_child_group_on_timeout(tmp_path, monkeypatch):
    marker = tmp_path / "grandchild-survived"
    fake = tmp_path / "fake-python"
    fake.write_text(f"#!/bin/sh\n(sleep 3; touch {marker}) &\nsleep 30\n")
    fake.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(fake))
    with pytest.raises(subprocess.TimeoutExpired):
        mcp.run_teyla(["x"], 0.5)
    import time
    time.sleep(3.5)
    assert not marker.exists()


# --- end to end -------------------------------------------------------------------------------

def test_end_to_end_over_a_real_process(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), HOME=str(tmp_path), TEYLA_HOME=str(tmp_path / ".teyla"))
    msgs = [req(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}),
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            req(2, "tools/list")]
    p = subprocess.run([sys.executable, "-m", "teyla", "mcp"], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                       capture_output=True, text=True, env=env, timeout=60, cwd=tmp_path)
    assert p.returncode == 0
    replies = [json.loads(x) for x in p.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    assert replies[0]["result"]["serverInfo"]["name"] == "teyla"
    assert [t["name"] for t in replies[1]["result"]["tools"]] == NAMES
    assert "ready on stdio" in p.stderr


def test_monitor_no_mark_seen_keeps_a10(monkeypatch):
    """An agent's monitor call through MCP must not mark A10 seen: the owner has not read it."""
    from teyla import cli
    calls = []
    monkeypatch.setattr("teyla.advise.mark_seen", lambda F: calls.append(F))
    monkeypatch.setattr(cli, "_sessions", lambda args: [])
    monkeypatch.setattr(cli, "_extras", lambda m, ss, days: None)
    monkeypatch.setattr(cli, "_cloud_sessions", lambda days: 0)
    monkeypatch.setattr(cli, "_deliver", lambda out: True)
    base = ["monitor", "--json"]
    for argv, want in ((base + ["--no-mark-seen"], 0), (base, 1)):
        calls.clear()
        args = cli.build_parser().parse_args(argv)
        args.fn(args)
        assert len(calls) == want, argv

"""The orchestrator gate (`teyla.orchestrator_gate`, `plugin/hooks/orchestrator-gate.sh`): a top-tier main
session is refused builds, commits and merges; a worker, a sub-agent and read-only commands pass."""
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

from teyla import orchestrator_gate as og

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "orchestrator-gate.sh"
FABLE, ASTRA = "claude-fable-5-2", "gpt-6.2-astra"
SONNET, SOL = "claude-sonnet-5-5", "gpt-6.1-sol"


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "teyla"
    home.mkdir()
    return {"TEYLA_HOME": str(home), "HOME": str(tmp_path), "CODEX_HOME": str(tmp_path / "codex")}


def rows(env):
    p = pathlib.Path(env["TEYLA_HOME"]) / og.LOG_NAME
    return [r.split("\t") for r in p.read_text().splitlines()] if p.exists() else []


def claude_transcript(tmp_path, model, sidechain=False, name="t.jsonl"):
    p = tmp_path / name
    recs = [{"type": "user", "message": {"role": "user", "content": "hi"}},
            {"type": "assistant", "isSidechain": sidechain, "message": {"model": "claude-old-1", "content": []}},
            {"type": "assistant", "isSidechain": sidechain, "message": {"model": model, "content": []}},
            {"type": "system", "subtype": "x"}]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return str(p)


def rollout(tmp_path, model, subagent=False, name="rollout-2026-11-27T10-00-00-abc12345-0000.jsonl"):
    p = tmp_path / name
    meta = {"type": "session_meta", "payload": {"id": "abc12345-0000", "cwd": "/w",
                                                "thread_source": "subagent" if subagent else "user"}}
    recs = [meta, {"type": "turn_context", "payload": {"model": "gpt-old"}},
            {"type": "turn_context", "payload": {"model": model}}, {"type": "event_msg", "payload": {}}]
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return str(p)


def claude(tmp_path, model, command, **kw):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "s1", "cwd": "/w",
            "transcript_path": claude_transcript(tmp_path, model, **kw), "tool_input": {"command": command}}


def codex(model, command, **extra):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash", "session_id": "abc12345-0000", "cwd": "/w",
            "turn_id": "t1", "model": model, "transcript_path": None, "permission_mode": "default",
            "tool_use_id": "u1", "tool_input": {"command": command}, **extra}


WORKER = ["xcodebuild -scheme App test", "cd app && swift build", "xcrun simctl boot ABC", "xcrun simctl launch booted x",
          "./gradlew assembleDebug", "npm run build", "pnpm test", "yarn build", "pytest -q", "uv run pytest tests",
          "./check.sh", "git commit -m x", "git -C /w push origin b", "git merge main", "git rebase main",
          "git cherry-pick abc", "gh pr create --title t", "gh pr merge 5 --merge", "~/ops/bin/testflight release x",
          "~/ops/bin/codex-review --context x", "claude-review", "bash -lc 'git push'", "FOO=1 git commit -m x",
          "echo hi && git commit -m x"]
READONLY = ["git status", "git log --oneline", "git diff", "git show HEAD", "gh pr view 5", "gh pr list", "cat a.txt",
            "rg foo", "ls -la", "teyla load", "xcodebuild -list", "xcrun simctl list", "git commit-graph x".replace("x", ""),
            "echo git commit", "git log --grep=commit", "npm install", "./gradlew --stop", "gh issue list"]


@pytest.mark.parametrize("command", WORKER)
@pytest.mark.parametrize("who", ["claude", "codex"])
def test_top_tier_main_is_refused_worker_commands(command, who, tmp_path, env):
    payload = claude(tmp_path, FABLE, command) if who == "claude" else codex(ASTRA, command)
    text = og.decide(payload, env)
    assert text and "Agent(subagent_type: builder, model: sonnet)" in text and "spawn_agent(agent_type: volume)" in text
    assert rows(env)[-1][1:3] == ["refuse", who]


@pytest.mark.parametrize("command", READONLY)
def test_read_only_commands_pass(command, tmp_path, env):
    assert og.decide(claude(tmp_path, FABLE, command), env) is None
    assert og.decide(codex(ASTRA, command), env) is None
    assert rows(env) == []


def test_worker_models_pass(tmp_path, env):
    assert og.decide(claude(tmp_path, SONNET, "git commit -m x"), env) is None
    assert og.decide(codex(SOL, "git commit -m x"), env) is None
    assert og.decide(codex("gpt-6-luna", "xcodebuild test"), env) is None


def test_the_claude_model_is_the_last_assistant_record(tmp_path, env):
    assert og.session_model({"transcript_path": claude_transcript(tmp_path, FABLE)}, "claude") == (FABLE, False)
    big = tmp_path / "big.jsonl"
    big.write_text(json.dumps({"type": "assistant", "message": {"model": FABLE}}) + "\n" + "x" * 400000 + "\n")
    assert og.session_model({"transcript_path": str(big)}, "claude")[0] == ""  # tail has no record: unknown, allowed


def test_claude_subagents_are_never_gated(tmp_path, env):
    side = claude(tmp_path, FABLE, "git commit -m x", sidechain=True)
    assert og.decide(side, env) is None
    with_id = claude(tmp_path, FABLE, "git commit -m x")
    with_id["agent_id"] = "a1"
    assert og.decide(with_id, env) is None
    sub_dir = tmp_path / "s" / "subagents"
    sub_dir.mkdir(parents=True)
    in_dir = claude(sub_dir, FABLE, "git commit -m x")
    assert og.decide(in_dir, env) is None


def test_codex_subagent_rollout_is_never_gated(tmp_path, env):
    payload = codex(ASTRA, "git commit -m x")
    payload["transcript_path"] = rollout(tmp_path, ASTRA, subagent=True)
    assert og.decide(payload, env) is None
    payload["transcript_path"] = rollout(tmp_path, ASTRA, subagent=False)
    assert og.decide(payload, env)


def test_codex_model_falls_back_to_the_rollout_found_by_session_id(tmp_path, env):
    day = pathlib.Path(env["CODEX_HOME"]) / "sessions" / "2026" / "11" / "27"
    day.mkdir(parents=True)
    rollout(day, ASTRA)
    payload = codex(ASTRA, "git push")
    del payload["model"]
    assert og.session_model(payload, "codex", env) == (ASTRA, False)
    assert og.decide(payload, env)
    payload["session_id"] = "../../etc/passwd"
    assert og.session_model(payload, "codex", env) == ("", False)


def test_codex_array_command_is_understood(tmp_path, env):
    assert og.decide(codex(ASTRA, ["bash", "-lc", "git commit -m x"]), env)


def test_modes(tmp_path, env, capsys):
    cfg = pathlib.Path(env["TEYLA_HOME"]) / "config.toml"
    cfg.write_text('[orchestrator]\ngate = "warn"\n')
    assert og.decide(codex(ASTRA, "git commit -m x"), env) is None
    assert "(warn)" in capsys.readouterr().err and rows(env)[-1][1] == "warn"
    cfg.write_text('[orchestrator]\ngate = "off"\n')
    n = len(rows(env))
    assert og.decide(codex(ASTRA, "git commit -m x"), env) is None and len(rows(env)) == n
    cfg.write_text('[orchestrator]\ngate = "nonsense"\n')
    assert og.decide(codex(ASTRA, "git commit -m x"), env)  # unknown mode is the default, refuse
    cfg.write_text("[orchestrator\n")
    assert og.decide(codex(ASTRA, "git commit -m x"), env)  # a broken file gives the defaults


def test_top_models_come_from_config(tmp_path, env):
    cfg = pathlib.Path(env["TEYLA_HOME"]) / "config.toml"
    cfg.write_text('[orchestrator]\ntop_models = ["^acme-big"]\n')
    assert og.decide(codex(FABLE, "git commit -m x"), env) is None
    assert og.decide(codex("acme-big-2", "git commit -m x"), env)


def test_the_override_is_logged_and_allows(tmp_path, env):
    e = dict(env, TEYLA_ORCH_OK="release hotfix")
    assert og.decide(codex(ASTRA, "git push"), e) is None
    assert rows(env)[-1][1:] == ["override", "codex", ASTRA, "git push", "release hotfix"]
    assert og.decide(codex(ASTRA, 'TEYLA_ORCH_OK="one-off" git commit -m x'), env) is None
    assert rows(env)[-1][1] == "override" and rows(env)[-1][5] == "one-off"
    assert all("-m" not in r[4] for r in rows(env))  # the head holds no arguments


def test_garbage_input_fails_open(env, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(b"{not json")})())
    monkeypatch.setenv("TEYLA_HOME", env["TEYLA_HOME"])
    assert og.main([]) == 0
    for payload in ({}, {"tool_input": "x"}, {"tool_input": {"command": 5}}, {"tool_input": {"command": "git commit"}}):
        assert og.decide(payload, env) is None
    lost = dict(codex(ASTRA, "git commit"), transcript_path=str(tmp_path / "missing"))  # sub-agent status unknowable
    with pytest.raises(OSError):
        og.decide(lost, env)
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(json.dumps(lost).encode())})())
    assert og.main([]) == 0 and rows(env)[-1][1] == "error"  # main() fails open and logs
    broken = claude(tmp_path, FABLE, "git commit -m x")
    broken["transcript_path"] = str(tmp_path / "missing.jsonl")
    with pytest.raises(OSError):
        og.session_model(broken, "claude")
    monkeypatch.setattr(og, "decide", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(sys, "stdin", type("S", (), {"buffer": io.BytesIO(b"{}")})())
    assert og.main([]) == 0 and rows(env)[-1][1] == "error"


def test_monitor_line(env):
    assert og.monitor_line(7, env) == ""
    og.log_row("refuse", "codex", ASTRA, "git commit", environ=env)
    og.log_row("refuse", "claude", FABLE, "gh pr merge", environ=env)
    og.log_row("override", "claude", FABLE, "git push", "why", environ=env)
    assert og.monitor_line(7, env) == "Orchestrator gate, last 7 days: 2 refuse, 1 override.\n"


# --- the shell hook, run for real ---------------------------------------------------------------------------

def run_hook(payload, env, tmp_path, python=True):
    wrap = tmp_path / "py"
    wrap.write_text(f'#!/bin/sh\nPYTHONPATH="{ROOT / "src"}" exec "{sys.executable}" "$@"\n')
    wrap.chmod(0o755)
    e = {"PATH": "/usr/bin:/bin", "HOME": env["HOME"], "TEYLA_HOME": env["TEYLA_HOME"]}
    if python:
        e["TEYLA_PYTHON"] = str(wrap)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(["sh", str(HOOK)], input=raw, capture_output=True, text=True, env=e, timeout=30)


def test_hook_refuses_for_both_harnesses(tmp_path, env):
    for payload in (claude(tmp_path, FABLE, "git commit -m x"), codex(ASTRA, "xcodebuild test")):
        r = run_hook(payload, env, tmp_path)
        assert r.returncode == 2 and "only orchestrates" in r.stderr


def test_hook_allows_workers_read_only_and_garbage(tmp_path, env):
    for payload in (claude(tmp_path, SONNET, "git commit -m x"), codex(SOL, "git push"), codex(ASTRA, "git status"),
                    codex(ASTRA, "ls"), "{not json", "", '{"tool_input": {"command": "git commit"'):
        r = run_hook(payload, env, tmp_path)
        assert r.returncode == 0 and r.stdout == "", (payload, r.stderr)


def test_hook_without_python_or_teyla_allows(tmp_path, env):
    r = run_hook(codex(ASTRA, "git commit -m x"), env, tmp_path, python=False)
    assert r.returncode in (0, 2)  # the sandbox python may carry teyla; the point is that it never crashes
    e = {"PATH": str(tmp_path / "empty"), "HOME": env["HOME"], "TEYLA_HOME": env["TEYLA_HOME"]}
    (tmp_path / "empty").mkdir()
    r = subprocess.run(["/bin/sh", str(HOOK)], input=json.dumps(codex(ASTRA, "git commit -m x")),
                       capture_output=True, text=True, env=e)
    assert r.returncode == 0


def test_hook_kill_switch_and_override_env(tmp_path, env):
    wrap_env = dict(env)
    r = run_hook(codex(ASTRA, "git commit -m x"), wrap_env, tmp_path)
    assert r.returncode == 2
    r = subprocess.run(["sh", str(HOOK)], input=json.dumps(codex(ASTRA, "git commit")), capture_output=True,
                       text=True, env={"PATH": "/usr/bin:/bin", "TEYLA_ORCH_GATE": "0"})
    assert r.returncode == 0


def test_hook_is_wired_in_both_harnesses():
    hooks = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
    cmds = [(g.get("matcher"), h["command"], h["timeout"]) for g in hooks for h in g["hooks"]]
    assert ("Bash", 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/orchestrator-gate.sh"', 10) in cmds
    assert HOOK.stat().st_mode & 0o111
    from teyla import harness
    codex_groups = harness._codex_hooks({})["hooks"]["PreToolUse"]
    assert any(g["matcher"] == "Bash" and g["hooks"][0]["command"].endswith("/.teyla/hooks/orchestrator-gate.sh")
               for g in codex_groups)
    assert "orchestrator-gate.sh" in harness.HOOK_SCRIPTS

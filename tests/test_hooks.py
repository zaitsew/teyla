"""The plugin's `UserPromptSubmit` hook (`plugin/hooks/capture-correction.sh`), run for real
through `sh` with a JSON payload on stdin and `cwd` pointed at `tmp_path`, so nothing here
writes into a real repo's `.teyla/`."""
from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "capture-correction.sh"

# The exact shape the Claude Code harness injects as a user turn when a background subagent
# finishes. On 2026-09-11 one of these was recorded as a correction in another repo: the
# `<note>` carries "again", which the heuristic matches.
TASK_NOTIFICATION = (
    "<task-notification>\n"
    "<task-id>a257944d6c38e1807</task-id>\n"
    "<tool-use-id>toolu_01Y1utWdg4jFo6Nis5gVbp9g</tool-use-id>\n"
    "<output-file>/private/tmp/claude-501/-Users-ceozaitsev-repos-njord/"
    "def1dd1e-d751-4770-aeb7-77a3f1e9b6df/tasks/a257944d6c38e1807.output</output-file>\n"
    "<status>completed</status>\n"
    '<summary>Agent "SwiftUI macOS Njord console" finished</summary>\n'
    "<note>A task-notification fires each time this agent stops with no live background "
    "children of its own. The user can send it another message and it will run again; "
    "don't wait on it.</note>\n"
    "</task-notification>"
)


def run_hook(tmp_path: pathlib.Path, prompt: str) -> subprocess.CompletedProcess:
    payload = json.dumps({"prompt": prompt, "cwd": str(tmp_path), "hook_event_name": "UserPromptSubmit"})
    return subprocess.run(["sh", str(HOOK)], input=payload, capture_output=True, text=True, timeout=10)


def records(tmp_path: pathlib.Path) -> list[dict]:
    p = tmp_path / ".teyla" / "corrections.jsonl"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def test_human_correction_is_recorded_silently(tmp_path):
    proc = run_hook(tmp_path, "no, don't rewrite the whole file, just fix the one line")
    assert proc.returncode == 0
    assert proc.stdout == ""  # UserPromptSubmit stdout lands in the model's context
    rows = records(tmp_path)
    assert len(rows) == 1
    assert rows[0]["cwd"] == str(tmp_path)
    assert rows[0]["text"].startswith("no, don't")
    assert set(rows[0]) == {"ts", "cwd", "text"}


def test_plain_prompt_without_correction_words_is_not_recorded(tmp_path):
    proc = run_hook(tmp_path, "add a --json flag to the sessions command")
    assert proc.returncode == 0
    assert records(tmp_path) == []
    assert not (tmp_path / ".teyla").exists()


def test_task_notification_is_ignored(tmp_path):
    proc = run_hook(tmp_path, TASK_NOTIFICATION)
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert records(tmp_path) == []


@pytest.mark.parametrize("prompt", [
    "<system-reminder>\nDon't do that again, the user said.\n</system-reminder>",
    "[SYSTEM NOTIFICATION: background task finished — don't wait on it again]",
    "<command-name>/teyla:correct</command-name>\n<command-message>wrong again</command-message>",
    "  \n<task-notification>\n<note>run again</note>\n</task-notification>",  # leading whitespace
])
def test_other_harness_turns_are_ignored(tmp_path, prompt):
    assert run_hook(tmp_path, prompt).returncode == 0
    assert records(tmp_path) == []


def test_human_prompt_that_merely_mentions_a_tag_is_still_recorded(tmp_path):
    run_hook(tmp_path, "the hook recorded a <task-notification> as a correction again, that's wrong")
    assert len(records(tmp_path)) == 1


def test_bad_json_exits_zero_and_writes_nothing(tmp_path):
    proc = subprocess.run(["sh", str(HOOK)], input="not json", capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert records(tmp_path) == []


# --- Codex: the UserPromptSubmit/SessionStart payloads Codex sends ------------------------------
#
# Captured from `codex exec` 0.158.0-alpha.2.1 (the ChatGPT app's bundled CLI) on 2026-09-29 with
# a scratch CODEX_HOME whose hooks.json pointed at a script that saved its stdin. Paths shortened.

def _codex_payload(tmp_path, event, **extra):
    d = {"session_id": "01a0ee07-c654-7d51-a3f5-836ddf44ac5a",
         "transcript_path": str(tmp_path / "rollout.jsonl"),
         "cwd": str(tmp_path), "hook_event_name": event, "model": "gpt-6-astra", "permission_mode": "default"}
    if event == "UserPromptSubmit":
        d["turn_id"] = "01a0ee07-c68e-72c0-8e1a-8bcb44c5a9db"
    d.update(extra)
    return d


def _rollout(tmp_path, originator):
    # The rollout's first record, as Codex writes it before any hook fires.
    source = "exec" if originator == "codex_exec" else "vscode"
    (tmp_path / "rollout.jsonl").write_text(json.dumps({
        "timestamp": "2026-09-29T16:39:39.795Z", "ordinal": 0, "type": "session_meta",
        "payload": {"session_id": "01a0ee09", "cwd": str(tmp_path), "originator": originator,
                    "cli_version": "0.158.0-alpha.2.1", "source": source,
                    "base_instructions": {"text": "You are Codex, " + "x" * 3000}}},
        separators=(",", ":")) + "\n")


def test_codex_prompt_is_recorded_from_an_interactive_session(tmp_path):
    _rollout(tmp_path, "Codex Desktop")
    payload = _codex_payload(tmp_path, "UserPromptSubmit", prompt="no, that's wrong — use pnpm")
    proc = subprocess.run(["sh", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0 and proc.stdout == ""
    assert [r["text"] for r in records(tmp_path)] == ["no, that's wrong — use pnpm"]


def test_codex_exec_prompt_is_a_batch_brief_not_a_correction(tmp_path):
    _rollout(tmp_path, "codex_exec")
    payload = _codex_payload(tmp_path, "UserPromptSubmit", permission_mode="bypassPermissions",
                             prompt="Review this diff. Don't run any command; flag anything wrong.")
    assert subprocess.run(["sh", str(HOOK)], input=json.dumps(payload), text=True, timeout=10).returncode == 0
    assert records(tmp_path) == []


START = ROOT / "plugin" / "hooks" / "session-start.sh"


def run_start(tmp_path, *args, payload=None):
    """session-start.sh in tmp_path with HOME pointed at it and no `teyla` on PATH, so the
    background update never starts."""
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True, exist_ok=True)
    (home / ".teyla" / "doctor.summary").write_text("teyla: 1 warning(s) — run `teyla doctor`\n")
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["sh", str(START), *args], input=json.dumps(payload) if payload is not None else "",
                          capture_output=True, text=True, timeout=10, cwd=tmp_path, env=env)


def test_session_start_plain_mode_prints_the_orientation(tmp_path):
    proc = run_start(tmp_path)
    assert proc.returncode == 0 and proc.stdout == "teyla: 1 warning(s) — run `teyla doctor`\n"


def test_session_start_codex_prints_for_a_person_and_nothing_for_codex_exec(tmp_path):
    _rollout(tmp_path, "Codex Desktop")
    ss = _codex_payload(tmp_path, "SessionStart", source="startup")
    assert run_start(tmp_path, "--codex", payload=ss).stdout == "teyla: 1 warning(s) — run `teyla doctor`\n"
    _rollout(tmp_path, "codex_exec")
    proc = run_start(tmp_path, "--codex", payload=ss)
    assert proc.returncode == 0 and proc.stdout == ""


def test_session_start_context_json_is_hermes_first_turn_only(tmp_path):
    # Hermes pre_llm_call shell-hook stdin (hermes-agent 0.20.4 agent/shell_hooks.py
    # `_serialize_payload`: json.dumps with default separators).
    first = {"hook_event_name": "pre_llm_call", "tool_name": None, "tool_input": None, "session_id": "s1",
             "cwd": str(tmp_path), "extra": {"user_message": "hi", "is_first_turn": True, "platform": "cli"}}
    proc = run_start(tmp_path, "--context-json", payload=first)
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"context": "teyla: 1 warning(s) — run `teyla doctor`"}
    later = dict(first, extra={"user_message": "and now?", "is_first_turn": False})
    assert run_start(tmp_path, "--context-json", payload=later).stdout == ""

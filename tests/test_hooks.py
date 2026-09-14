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

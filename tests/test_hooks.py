"""The plugin's `UserPromptSubmit` hook (`plugin/hooks/capture-correction.sh`), run for real
through `sh` with a JSON payload on stdin, `cwd` pointed at `tmp_path` and HOME at a tmp dir,
so nothing here writes into a real repo's `.teyla/` or the real ~/.teyla."""
from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import sys

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


def hook_env(home: pathlib.Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "TEYLA_HOME"}
    env.update(HOME=str(home), TEYLA_PYTHON=sys.executable, **extra)
    return env


def run_hook(tmp_path: pathlib.Path, prompt: str, cwd: pathlib.Path | None = None, **env) -> subprocess.CompletedProcess:
    payload = json.dumps({"prompt": prompt, "cwd": str(cwd or tmp_path), "hook_event_name": "UserPromptSubmit"})
    return subprocess.run(["sh", str(HOOK)], input=payload, capture_output=True, text=True, timeout=10,
                          env=hook_env(tmp_path / "home", **env))


def store(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "home" / ".teyla" / "corrections"


def records(tmp_path: pathlib.Path, name: str = "misc.jsonl") -> list[dict]:
    p = store(tmp_path) / name
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
    # cwd_key: a misc record is looked up by a hash of its unscrubbed cwd (review of #63, P2).
    assert set(rows[0]) == {"ts", "cwd", "text", "cwd_key"}


def test_plain_prompt_without_correction_words_is_not_recorded(tmp_path):
    proc = run_hook(tmp_path, "add a --json flag to the sessions command")
    assert proc.returncode == 0
    assert records(tmp_path) == []
    assert not (tmp_path / ".teyla").exists()
    assert not store(tmp_path).exists()


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
    proc = subprocess.run(["sh", str(HOOK)], input="not json", capture_output=True, text=True, timeout=10,
                          env=hook_env(tmp_path / "home"))
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert records(tmp_path) == []


# --- 0.12: the store is outside the repo, private, and scrubbed ---------------------------

def _git_repo(path: pathlib.Path) -> pathlib.Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    return path


def test_a_correction_in_a_repo_lands_outside_it_private_and_scrubbed(tmp_path):
    """The security review's P0: 500 raw chars of a prompt went into <repo>/.teyla/ with 0644,
    and work repos do not ignore `.teyla/`."""
    repo = _git_repo(tmp_path / "work-repo")
    key = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    proc = run_hook(tmp_path, f"no, wrong token, use {key} instead", cwd=repo)
    assert proc.returncode == 0 and proc.stdout == ""
    assert not (repo / ".teyla").exists()
    [f] = list(store(tmp_path).glob("work-repo-*.jsonl"))
    text = f.read_text()
    assert key not in text and "[redacted]" in text
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert stat.S_IMODE(store(tmp_path).stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "home" / ".teyla").stat().st_mode) == 0o700


def test_a_legacy_in_repo_file_gets_the_repo_excluded_on_first_touch(tmp_path):
    repo = _git_repo(tmp_path / "old-repo")
    (repo / ".teyla").mkdir()
    legacy = repo / ".teyla" / "corrections.jsonl"
    legacy.write_text('{"ts": "2026-09-01T00:00:00+00:00", "cwd": "x", "text": "old one"}\n')
    run_hook(tmp_path, "don't do that again", cwd=repo)
    assert legacy.read_text().count("\n") == 1, "the legacy file is never written to, never deleted"
    assert ".teyla/" in (repo / ".git" / "info" / "exclude").read_text().splitlines()
    status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
                            capture_output=True, text=True).stdout
    assert ".teyla" not in status


def test_without_a_usable_python_the_hook_does_nothing(tmp_path):
    """No teyla, no python3 on PATH: exit 0, silently, nothing written."""
    empty = tmp_path / "bin"; empty.mkdir()
    env = hook_env(tmp_path / "home", PATH=str(empty))
    env.pop("TEYLA_PYTHON")
    payload = json.dumps({"prompt": "that's wrong", "cwd": str(tmp_path)})
    proc = subprocess.run(["/bin/sh", str(HOOK)], input=payload, capture_output=True, text=True, timeout=10, env=env)
    assert proc.returncode == 0 and proc.stdout == ""
    assert records(tmp_path) == []


def test_the_installed_teyla_interpreter_is_preferred(tmp_path):
    """A `teyla` entry script on PATH: its shebang interpreter runs the hook, python3 is never asked."""
    bin_ = tmp_path / "bin"; bin_.mkdir()
    (bin_ / "teyla").write_text(f"#!{sys.executable}\nimport sys\n")
    (bin_ / "teyla").chmod(0o755)
    for tool in ("dirname", "head", "sed", "uname"):
        src = next(pathlib.Path(d, tool) for d in ("/usr/bin", "/bin") if pathlib.Path(d, tool).exists())
        (bin_ / tool).symlink_to(src)
    env = hook_env(tmp_path / "home", PATH=str(bin_))
    env.pop("TEYLA_PYTHON")
    payload = json.dumps({"prompt": "that's wrong", "cwd": str(tmp_path)})
    proc = subprocess.run(["/bin/sh", str(HOOK)], input=payload, capture_output=True, text=True, timeout=10, env=env)
    assert proc.returncode == 0
    assert [r["text"] for r in records(tmp_path)] == ["that's wrong"]


@pytest.mark.skipif(sys.platform != "darwin" or not pathlib.Path("/usr/bin/python3").exists(), reason="macOS stub python")
def test_the_macos_python_stub_is_not_run_without_the_developer_tools(tmp_path):
    """/usr/bin/python3 without the Command Line Tools pops an install dialog; the hook runs on
    every prompt, so it asks `xcode-select -p` first and gives up when that fails."""
    bin_ = tmp_path / "bin"; bin_.mkdir()
    asked = tmp_path / "asked"
    (bin_ / "xcode-select").write_text(f"#!/bin/sh\ntouch {asked}\nexit 2\n")
    (bin_ / "xcode-select").chmod(0o755)
    env = hook_env(tmp_path / "home", PATH=f"{bin_}:/usr/bin:/bin")
    env.pop("TEYLA_PYTHON")
    payload = json.dumps({"prompt": "that's wrong", "cwd": str(tmp_path)})
    proc = subprocess.run(["/bin/sh", str(HOOK)], input=payload, capture_output=True, text=True, timeout=10, env=env)
    assert proc.returncode == 0 and proc.stdout == ""
    assert asked.exists(), "xcode-select -p is consulted before /usr/bin/python3"
    assert records(tmp_path) == []

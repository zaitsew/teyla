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
    assert set(rows[0]) == {"ts", "cwd", "text", "source", "cwd_key"} and rows[0]["source"] == "hook"


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
    proc = subprocess.run(["sh", str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, timeout=10,
                          env=hook_env(tmp_path / "home"))
    assert proc.returncode == 0 and proc.stdout == ""
    assert [r["text"] for r in records(tmp_path)] == ["no, that's wrong — use pnpm"]


def test_codex_exec_prompt_is_a_batch_brief_not_a_correction(tmp_path):
    _rollout(tmp_path, "codex_exec")
    payload = _codex_payload(tmp_path, "UserPromptSubmit", permission_mode="bypassPermissions",
                             prompt="Review this diff. Don't run any command; flag anything wrong.")
    assert subprocess.run(["sh", str(HOOK)], input=json.dumps(payload), text=True, timeout=10,
                          env=hook_env(tmp_path / "home")).returncode == 0
    assert records(tmp_path) == []
    assert not store(tmp_path).exists() or not any(store(tmp_path).iterdir())


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


# --- Codex: the project memory index, shared with Claude Code ------------------------------------

def _memory(home: pathlib.Path, root: pathlib.Path, text: str) -> pathlib.Path:
    """MEMORY.md where Claude Code keeps it for `root`: every / and . of the path made -."""
    key = str(root.resolve()).replace("/", "-").replace(".", "-")
    d = home / ".claude" / "projects" / key / "memory"
    d.mkdir(parents=True)
    (d / "MEMORY.md").write_text(text)
    return d


def _git(*args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], check=True, capture_output=True)


def test_session_start_codex_prints_the_project_memory_index(tmp_path):
    repo = _git_repo(tmp_path / "my.app")
    (repo / "src").mkdir()
    index = "".join(f"- [Fact {i}](fact-{i}.md) — hook {i}\n" for i in range(60))
    d = _memory(tmp_path / "home", repo, index)
    _rollout(tmp_path, "Codex Desktop")
    ss = _codex_payload(tmp_path, "SessionStart", source="startup", cwd=str(repo / "src"))
    out = run_start(tmp_path, "--codex", payload=ss).stdout.splitlines()
    assert out[0] == "teyla: 1 warning(s) — run `teyla doctor`"
    assert out[1] == f"teyla: project memory (shared with Claude Code): {d}"
    assert "-my-app" in out[1], "the . in the path is a - in the key, as Claude Code writes it"
    assert out[2:] == index.splitlines()[:40]
    # plain mode (Claude Code reads its own memory) prints no index
    assert "project memory" not in run_start(tmp_path).stdout


def test_session_start_codex_prints_no_index_without_memory(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    _rollout(tmp_path, "Codex Desktop")
    ss = _codex_payload(tmp_path, "SessionStart", source="startup", cwd=str(repo))
    assert run_start(tmp_path, "--codex", payload=ss).stdout == "teyla: 1 warning(s) — run `teyla doctor`\n"


def test_session_start_codex_index_is_capped(tmp_path):
    repo = _git_repo(tmp_path / "repo")
    _memory(tmp_path / "home", repo, ("- " + "x" * 400 + "\n") * 30)
    _rollout(tmp_path, "Codex Desktop")
    ss = _codex_payload(tmp_path, "SessionStart", source="startup", cwd=str(repo))
    out = run_start(tmp_path, "--codex", payload=ss).stdout
    index = out.split("teyla: project memory (shared with Claude Code): ", 1)[1].split("\n", 1)[1]
    assert 3900 < len(index.encode()) <= 4001, "about 4 KB of the index, cut, then one newline"


def test_session_start_codex_worktree_uses_the_main_checkout_key(tmp_path):
    main = _git_repo(tmp_path / "repos" / "app")
    (main / "f").write_text("x\n")
    _git("-C", str(main), "add", "f")
    _git("-C", str(main), "commit", "-qm", "init")
    wt = tmp_path / ".worktrees" / "app" / "feature"
    _git("-C", str(main), "worktree", "add", "-q", "-b", "feature", str(wt))
    _memory(tmp_path / "home", main, "- [Main fact](main.md) — from the main checkout\n")
    _rollout(tmp_path, "Codex Desktop")
    ss = _codex_payload(tmp_path, "SessionStart", source="startup", cwd=str(wt))
    out = run_start(tmp_path, "--codex", payload=ss).stdout
    assert "- [Main fact](main.md) — from the main checkout" in out
    assert "-worktrees-" not in out


# --- the generated AGENTS.md is refreshed when its sources are newer --------------------------

def _start_with_fake_teyla(tmp_path):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True, exist_ok=True)
    (home / ".teyla" / "update-check.json").write_text("{}")  # fresh: no daily update chain
    bin_ = tmp_path / "bin"
    bin_.mkdir(exist_ok=True)
    log = tmp_path / "teyla-calls"
    (bin_ / "teyla").write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    (bin_ / "teyla").chmod(0o755)
    env = {"HOME": str(home), "PATH": f"{bin_}:/usr/bin:/bin"}
    proc = subprocess.run(["sh", str(START)], input="", capture_output=True, text=True, timeout=10, cwd=tmp_path, env=env)
    assert proc.returncode == 0
    return log


def _wait_for(path: pathlib.Path, seconds: float = 5.0) -> str:
    import time
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(0.05)
    return path.read_text() if path.exists() else ""


def _generated_agents(home: pathlib.Path, claude_newer: bool):
    import time
    for d in (".claude", ".agents", ".codex"):
        (home / d).mkdir(parents=True, exist_ok=True)
    (home / ".agents" / "POLICY.md").write_text("# P\n")
    agents = home / ".codex" / "AGENTS.md"
    agents.write_text("<!-- generated by teyla policy sync from ~/.agents/POLICY.md + ~/.claude/CLAUDE.md -->\n\n# P\n")
    (home / ".claude" / "CLAUDE.md").write_text("# Mine\n")
    old, new = time.time() - 3600, time.time()
    os.utime(home / ".agents" / "POLICY.md", (old, old))
    os.utime(home / ".claude" / "CLAUDE.md", (new, new) if claude_newer else (old, old))
    os.utime(agents, (old + 60, old + 60) if claude_newer else (new, new))


def test_session_start_syncs_a_generated_agents_md_older_than_claude_md(tmp_path):
    _generated_agents(tmp_path / "home", claude_newer=True)
    log = _start_with_fake_teyla(tmp_path)
    assert "policy sync --quiet" in _wait_for(log)


def test_session_start_leaves_a_current_or_hand_written_agents_md_alone(tmp_path):
    import time
    home = tmp_path / "home"
    _generated_agents(home, claude_newer=False)
    log = _start_with_fake_teyla(tmp_path)
    # a hand-written AGENTS.md older than CLAUDE.md is not Teyla's to refresh either
    (home / ".codex" / "AGENTS.md").write_text("my own codex rules\n")
    os.utime(home / ".codex" / "AGENTS.md", (time.time() - 7200,) * 2)
    _start_with_fake_teyla(tmp_path)
    time.sleep(0.5)
    assert "policy sync" not in (log.read_text() if log.exists() else "")


def test_session_start_syncs_when_an_imported_file_is_newer(tmp_path):
    # a file CLAUDE.md pulls in with @~/... is a source too (Codex review of #96, P2)
    import time
    home = tmp_path / "home"
    _generated_agents(home, claude_newer=False)
    (home / ".claude" / "CLAUDE.md").write_text("# Mine\n@~/ops/releases.md\n")
    old = time.time() - 3600
    os.utime(home / ".claude" / "CLAUDE.md", (old, old))
    (home / "ops").mkdir()
    (home / "ops" / "releases.md").write_text("ship it\n")
    os.utime(home / "ops" / "releases.md", (time.time() + 60,) * 2)
    log = _start_with_fake_teyla(tmp_path)
    assert "policy sync --quiet" in _wait_for(log)


def test_session_start_syncs_a_symlink_once_claude_md_changes(tmp_path):
    # a symlink to POLICY.md is stale once CLAUDE.md changes after the last sync: it may have gained rules
    import time
    home = tmp_path / "home"
    for d in (".claude", ".agents", ".codex", ".teyla"):
        (home / d).mkdir(parents=True, exist_ok=True)
    (home / ".agents" / "POLICY.md").write_text("# P\n")
    (home / ".codex" / "AGENTS.md").symlink_to(home / ".agents" / "POLICY.md")
    (home / ".claude" / "CLAUDE.md").write_text("# Mine\n")
    stamp = home / ".teyla" / "policy-sync.stamp"
    stamp.write_text("")
    os.utime(stamp, (time.time() - 3600,) * 2)
    log = _start_with_fake_teyla(tmp_path)
    assert "policy sync --quiet" in _wait_for(log)
    log.unlink()
    _start_with_fake_teyla(tmp_path)  # the stamp is fresh now: no second sync
    time.sleep(0.5)
    assert "policy sync" not in (log.read_text() if log.exists() else "")

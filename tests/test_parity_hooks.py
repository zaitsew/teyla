"""The three practices ported from the personal Mac's ~/ops/bin into the plugin, for the work
MacBook: the context budget (plugin/hooks/context-budget.sh + .py), the land check
(plugin/hooks/land-check.sh) and the `/teyla:review` skill. Both hooks are opt-in under
`[hooks]` in ~/.teyla/config.toml; every hook here runs for real through `sh` with HOME, TMPDIR
and the config in tmp_path, so nothing touches the real ~/.teyla, ~/.claude or ~/.codex."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from teyla import config, doctor, harness, policy

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOKS = ROOT / "plugin" / "hooks"
BUDGET = HOOKS / "context-budget.sh"
LAND = HOOKS / "land-check.sh"
GIT_ID = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}


def _env(tmp_path: pathlib.Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("TEYLA_HOME", "TEYLA_SAFE")}
    env.update(HOME=str(tmp_path / "home"), TMPDIR=str(tmp_path / "tmp"), TEYLA_PYTHON=sys.executable, **GIT_ID)
    env.update(extra)
    (tmp_path / "home" / ".teyla").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tmp").mkdir(exist_ok=True)
    return env


def _config(tmp_path: pathlib.Path, text: str) -> None:
    (tmp_path / "home" / ".teyla").mkdir(parents=True, exist_ok=True)
    (tmp_path / "home" / ".teyla" / "config.toml").write_text(text)


def _run(script, tmp_path, payload, *args, cwd=None, **env):
    return subprocess.run(["sh", str(script), *args], input=json.dumps(payload), capture_output=True, text=True,
                          timeout=20, cwd=cwd or tmp_path, env=_env(tmp_path, **env))


def _spies(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """A bin dir whose python3, teyla and git only leave a mark, and that mark's directory."""
    bin_, marks = tmp_path / "spy-bin", tmp_path / "marks"
    bin_.mkdir(); marks.mkdir()
    for tool in ("python3", "teyla", "git"):
        (bin_ / tool).write_text(f"#!/bin/sh\ntouch {marks / tool}\n")
        (bin_ / tool).chmod(0o755)
    return bin_, marks


# --- off is free ------------------------------------------------------------------------------

@pytest.mark.parametrize("cfg", [None, "[hooks]\ncontext_budget = false\nland_check = false\n",
                                 "[safe]\nenabled = true\ncontext_budget = true\nland_check = true\n",
                                 "[hooks]\ncontext_budget_first = 1\n"])
def test_disabled_hooks_start_no_python_no_git_and_print_nothing(tmp_path, cfg):
    if cfg is not None:
        _config(tmp_path, cfg)
    bin_, marks = _spies(tmp_path)
    spy_py = str(bin_ / "python3")
    for script, event in ((BUDGET, "PostToolUse"), (BUDGET, "UserPromptSubmit"), (LAND, "Stop")):
        proc = _run(script, tmp_path, {"hook_event_name": event, "session_id": "s", "cwd": str(tmp_path)},
                    PATH=f"{bin_}:/usr/bin:/bin", TEYLA_PYTHON=spy_py)
        assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == "", (script.name, proc)
    assert list(marks.iterdir()) == [], "a disabled hook started an interpreter or git"


def test_the_plugin_wires_both_hooks_on_the_right_events():
    hooks = json.loads((HOOKS / "hooks.json").read_text())["hooks"]
    cmds = {ev: [h["command"] for g in groups for h in g["hooks"]] for ev, groups in hooks.items()}
    for ev in ("UserPromptSubmit", "PostToolUse"):
        assert any("context-budget.sh" in c for c in cmds[ev]), ev
    compact = [g for g in hooks["SessionStart"] if any("context-budget.sh" in h["command"] for h in g["hooks"])]
    assert compact and compact[0]["matcher"] == "compact"
    assert any("land-check.sh" in c for c in cmds["Stop"])
    # the always-on hooks are untouched
    assert any("session-start.sh" in c for c in cmds["SessionStart"])
    assert any("capture-correction.sh" in c for c in cmds["UserPromptSubmit"])


# --- context budget ---------------------------------------------------------------------------

def _transcript(tmp_path: pathlib.Path, tokens: int, sidechain_tokens: int | None = None) -> pathlib.Path:
    t = tmp_path / "session.jsonl"
    usage = {"input_tokens": 10, "cache_read_input_tokens": tokens - 2010, "cache_creation_input_tokens": 2000}
    lines = [json.dumps({"type": "user", "message": {"content": "hi"}}),
             json.dumps({"type": "assistant", "message": {"usage": usage}})]
    if sidechain_tokens is not None:
        lines.append(json.dumps({"type": "assistant", "isSidechain": True,
                                 "message": {"usage": {"input_tokens": sidechain_tokens}}}))
    t.write_text("\n".join(lines) + "\n")
    return t


def _turn(tmp_path, event="PostToolUse", sid="sess-1", **env):
    return _run(BUDGET, tmp_path, {"hook_event_name": event, "session_id": sid,
                                   "transcript_path": str(tmp_path / "session.jsonl"), "cwd": str(tmp_path)}, **env)


def test_context_budget_asks_for_a_handoff_at_the_threshold_once_per_step(tmp_path):
    _config(tmp_path, "[hooks]\ncontext_budget = true\n")
    handoff = tmp_path / "home" / ".teyla" / "handoff"
    _transcript(tmp_path, 239_000)
    assert _turn(tmp_path).stdout == ""
    _transcript(tmp_path, 250_000, sidechain_tokens=5)  # a subagent's record is not the session's context
    out = json.loads(_turn(tmp_path).stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    note = out["additionalContext"]
    assert "~250k tokens" in note and str(handoff / "sess-1.md") in note
    # no ~/.claude/settings.json in this HOME: the note says so and names 335000 (~300k)
    assert "near the model's full window" in note and '335000 would compact at about 300k' in note
    assert "Write the handoff" in note and "Do not stop" in note
    assert oct(handoff.stat().st_mode & 0o777) == "0o700"
    assert _turn(tmp_path).stdout == "", "the same level is asked for once"
    (handoff / "sess-1.md").write_text("state\n")
    _transcript(tmp_path, 275_000)
    note = json.loads(_turn(tmp_path, event="UserPromptSubmit").stdout)["hookSpecificOutput"]
    assert note["hookEventName"] == "UserPromptSubmit" and "Rewrite the handoff" in note["additionalContext"]


@pytest.mark.parametrize("settings,expect", [
    ({"autoCompactWindow": 335000}, 'at about 300k with "autoCompactWindow": 335000'),
    ({"model": "opus", "autoCompactWindow": 400000}, 'at about 365k with "autoCompactWindow": 400000'),
    ({"autoCompactWindow": "400000"}, "near the model's full window"),
    (["not", "an", "object"], "near the model's full window"),
])
def test_context_budget_names_where_this_machine_compacts(tmp_path, settings, expect):
    _config(tmp_path, "[hooks]\ncontext_budget = true\n")
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    (tmp_path / "home" / ".claude" / "settings.json").write_text(json.dumps(settings))
    _transcript(tmp_path, 241_000)
    assert expect in json.loads(_turn(tmp_path).stdout)["hookSpecificOutput"]["additionalContext"]


def test_context_budget_thresholds_come_from_config_and_safe_mode_does_not_stop_it(tmp_path):
    _config(tmp_path, '[safe]\nenabled = true\n\n[hooks]\ncontext_budget = "on"  # opt in\n'
                      "context_budget_first = 50000\ncontext_budget_step = 10000\n")
    _transcript(tmp_path, 49_000)
    assert _turn(tmp_path, TEYLA_SAFE="1").stdout == ""
    _transcript(tmp_path, 51_000)
    assert "~51k" in _turn(tmp_path, TEYLA_SAFE="1").stdout
    _transcript(tmp_path, 60_500)
    assert "~60k" in _turn(tmp_path).stdout


def test_context_budget_puts_the_handoff_back_after_compaction_once(tmp_path):
    _config(tmp_path, "[hooks]\ncontext_budget = true\n")
    _transcript(tmp_path, 330_000)
    assert _turn(tmp_path).stdout  # level 0 asked for
    handoff = tmp_path / "home" / ".teyla" / "handoff"
    (handoff / "sess-1.md").write_text("## state\nPR !12 open, lane B running\n")
    compact = {"hook_event_name": "SessionStart", "source": "compact", "session_id": "sess-1"}
    note = json.loads(_run(BUDGET, tmp_path, compact).stdout)["hookSpecificOutput"]
    assert note["hookEventName"] == "SessionStart" and "PR !12 open, lane B running" in note["additionalContext"]
    assert not (handoff / "sess-1.md").exists() and (handoff / "sess-1.prev.md").exists()
    again = json.loads(_run(BUDGET, tmp_path, compact).stdout)["hookSpecificOutput"]["additionalContext"]
    assert "PR !12" not in again and "no handoff was written" in again and "sess-1.prev.md" in again
    # the level was reset: the next climb asks again
    assert _turn(tmp_path).stdout
    # another session's handoff is never used; a startup SessionStart prints nothing
    other = {"hook_event_name": "SessionStart", "source": "compact", "session_id": "sess-2"}
    assert "PR !12" not in _run(BUDGET, tmp_path, other).stdout
    assert _run(BUDGET, tmp_path, dict(compact, source="startup")).stdout == ""


def test_context_budget_keeps_the_session_id_out_of_the_path(tmp_path):
    _config(tmp_path, "[hooks]\ncontext_budget = true\n")
    _transcript(tmp_path, 400_000)
    out = _turn(tmp_path, sid="../../escape").stdout
    assert "/handoff/escape.md" in out
    assert not (tmp_path / "home" / "escape.level").exists()


def test_context_budget_never_fails_on_bad_input(tmp_path):
    _config(tmp_path, "[hooks]\ncontext_budget = true\n")
    proc = subprocess.run(["sh", str(BUDGET)], input="not json", capture_output=True, text=True, timeout=10,
                          env=_env(tmp_path))
    assert proc.returncode == 0 and proc.stdout == ""


# --- land check -------------------------------------------------------------------------------

def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, **GIT_ID}).stdout


def _repo(tmp_path, origin: str | None = None) -> pathlib.Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "a")
    if origin:
        _git(repo, "remote", "add", "origin", origin)
    return repo


def _claude_md(tmp_path, *slugs):
    p = tmp_path / "home" / ".claude" / "CLAUDE.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    entries = "\n".join(f"    {s:28} # added on the owner's instruction" for s in slugs)
    p.write_text("# Shipping\n\nThe MERGE-APPROVED REPOS list below is the whole permission.\n"
                 "approved/in-prose\n\n```\nMERGE-APPROVED REPOS\n" + entries + "\n```\n\nacme/app\n")


def _stop(tmp_path, repo, *args, sid="s1", **payload):
    p = {"hook_event_name": "Stop", "session_id": sid, "cwd": str(repo), "stop_hook_active": False, **payload}
    return _run(LAND, tmp_path, p, *args)


def _note(proc) -> str:
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


def test_land_check_names_commits_on_no_remote_even_with_no_remote_at_all(tmp_path):
    _config(tmp_path, "[hooks]\nland_check = true\n")
    repo = _repo(tmp_path)  # never pushed anywhere: `log --not --remotes` without HEAD says 0
    out = json.loads(_stop(tmp_path, repo).stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "Stop"
    assert "1 commit on no remote" in out["additionalContext"] and '"main"' in out["additionalContext"]
    assert "STOP" in out["additionalContext"] and "merge it" not in out["additionalContext"]


def test_land_check_is_once_per_session_and_silent_when_everything_is_landed(tmp_path):
    _config(tmp_path, "[hooks]\nland_check = true\n")
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(bare))
    repo = _repo(tmp_path, origin=str(bare))
    _git(repo, "push", "-q", "origin", "main")
    assert _stop(tmp_path, repo).stdout == "", "clean and pushed: nothing to say"
    (repo / "b.txt").write_text("b\n")
    (repo / "c.txt").write_text("c\n")
    note = _note(_stop(tmp_path, repo))
    assert "2 uncommitted files" in note and "on no remote" not in note
    assert _stop(tmp_path, repo).stdout == "", "said once per session"
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "bc")
    assert "1 commit on no remote" in _note(_stop(tmp_path, repo, sid="s2"))


@pytest.mark.parametrize("origin,slug", [
    ("git@github.com:Zaitsew/Teyla.git", "zaitsew/teyla"),
    ("https://github.com/zaitsew/teyla", "zaitsew/teyla"),
    ("ssh://git@gitlab.corp.example:2222/platform/tools/svc-api.git", "gitlab.corp.example/platform/tools/svc-api"),
    ("https://GitLab.corp.example/platform/tools/svc-api.git", "gitlab.corp.example/platform/tools/svc-api"),
    ("git@gitlab.corp.example:platform/tools/svc-api.git", "gitlab.corp.example/platform/tools/svc-api"),
    ("https://github.com/zaitsew/teyla", "github.com/zaitsew/teyla"),
])
def test_land_check_merges_only_in_a_merge_approved_repo(tmp_path, origin, slug):
    _config(tmp_path, "[hooks]\nland_check = true\n")
    repo = _repo(tmp_path, origin=origin)
    _claude_md(tmp_path, "someone/else", slug)
    note = _note(_stop(tmp_path, repo))
    assert "merge it — merge, not squash, never force-push" in note and "STOP" not in note


def test_land_check_stops_at_the_pr_off_the_list(tmp_path):
    _config(tmp_path, "[hooks]\nland_check = true\n")
    # on the page but not in the fenced list, a prefix of a listed repo, or a parent group
    _claude_md(tmp_path, "platform/tools/svc-api-v2", "platform/tools", "zaitsew/teyla", "other.host/platform/x")
    for i, origin in enumerate(("git@github.com:approved/in-prose.git", "git@github.com:acme/app.git",
                                "https://gitlab.corp.example/platform/tools/svc-api.git",
                                # a bare owner/repo approves GitHub only, not the same path on
                                # another host (caught in review, P1); a host entry approves only
                                # that host
                                "git@gitlab.corp.example:zaitsew/teyla.git",
                                "https://gitlab.corp.example/platform/x.git")):
        shutil.rmtree(tmp_path / "repo", ignore_errors=True)
        repo = _repo(tmp_path, origin=origin)
        note = _note(_stop(tmp_path, repo, sid=f"x{i}"))
        assert "Open the PR/MR and STOP" in note and "not on the MERGE-APPROVED list" in note, origin
        assert "Write access is not permission" in note


def test_land_check_codex_mode_prints_a_system_message_and_skips_codex_exec(tmp_path):
    _config(tmp_path, "[hooks]\nland_check = true\n")
    repo = _repo(tmp_path)
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(json.dumps({"type": "session_meta", "payload": {"originator": "codex_exec"}}) + "\n")
    assert _stop(tmp_path, repo, "--codex", transcript_path=str(rollout)).stdout == ""
    rollout.write_text(json.dumps({"type": "session_meta", "payload": {"originator": "Codex Desktop"}}) + "\n")
    out = json.loads(_stop(tmp_path, repo, "--codex", sid="c2", transcript_path=str(rollout)).stdout)
    assert set(out) == {"systemMessage"} and "1 commit on no remote" in out["systemMessage"]


def test_land_check_outside_a_repo_says_nothing(tmp_path):
    _config(tmp_path, "[hooks]\nland_check = true\n")
    (tmp_path / "plain").mkdir()
    proc = _stop(tmp_path, tmp_path / "plain")
    assert proc.returncode == 0 and proc.stdout == ""


# --- config, doctor, harness, skill -----------------------------------------------------------

def test_config_keys_are_typed_and_default_off(tmp_path):
    p = tmp_path / "c.toml"
    assert config.hook_on("context_budget", config.load(p)) is False and config.hook_on("land_check", config.load(p)) is False
    assert config.set_value("hooks.context_budget", "true", path=p).startswith("set")
    assert config.set_value("hooks.context_budget_first", "250000", path=p).startswith("set")
    assert config.set_value("hooks.land_check", "maybe", path=p).startswith("invalid")
    assert config.set_value("hooks.context_budget_step", "lots", path=p).startswith("invalid")
    cfg = config.load(p)
    assert cfg["hooks"]["context_budget"] is True and cfg["hooks"]["context_budget_first"] == 250000
    assert cfg["hooks"]["context_budget_step"] == 30000 and config.hook_on("context_budget", cfg)
    assert "[hooks]\ncontext_budget = true\ncontext_budget_first = 250000\n" in p.read_text()


def test_doctor_names_each_enabled_hook_and_the_missing_autocompact_window(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(config, "HOME", home)
    assert doctor.hook_checks(config.load(tmp_path / "none.toml")) == []
    cfg = {"hooks": {"context_budget": True, "land_check": True, "context_budget_first": 300000,
                     "context_budget_step": 40000}}
    by = {c["name"]: c for c in doctor.hook_checks(cfg)}
    assert by["hooks:context-budget"]["level"] == "INFO" and "300k" in by["hooks:context-budget"]["detail"]
    assert by["hooks:land-check"]["level"] == "INFO"
    warn = by["hooks:autocompact"]
    assert warn["level"] == "WARN" and '"autoCompactWindow": 335000' in warn["fix"] and "/config" in warn["fix"]
    settings = home / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "opus", "autoCompactWindow": 400000}))
    before = settings.read_text()
    assert "hooks:autocompact" not in {c["name"] for c in doctor.hook_checks(cfg)}
    assert settings.read_text() == before, "doctor never writes settings.json"
    only_land = {"hooks": {"land_check": True}}
    assert [c["name"] for c in doctor.hook_checks(only_land)] == ["hooks:land-check"]
    assert "hooks:context-budget-late" not in {c["name"] for c in doctor.hook_checks(cfg)}, "300k < ~365k"


def test_doctor_warns_when_the_handoff_comes_after_the_compaction(tmp_path, monkeypatch):
    """A config.toml still at 300k with a 335000 window (~300k): the compaction comes first."""
    monkeypatch.setattr(config, "HOME", tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"autoCompactWindow": 335000}))
    late = {c["name"]: c for c in doctor.hook_checks({"hooks": {"context_budget": True, "context_budget_first": 300000}})}
    late = late["hooks:context-budget-late"]
    assert late["level"] == "WARN" and "about 300k" in late["detail"]
    assert late["fix"] == "teyla config set hooks.context_budget_first=240000 hooks.context_budget_step=30000"
    by = {c["name"] for c in doctor.hook_checks({"hooks": {"context_budget": True}})}
    assert "hooks:context-budget-late" not in by and "hooks:autocompact" not in by, "the defaults fit 335000"


@pytest.mark.parametrize("settings,window,at,is_set", [
    (None, 335000, 300000, False),
    ({"autoCompactWindow": 400000}, 400000, 365000, True),
    ({"autoCompactWindow": 335000}, 335000, 300000, True),
    ({"autoCompactWindow": True}, 335000, 300000, False),
    ({"autoCompactWindow": 20000}, 335000, 300000, False),
    ("not json", 335000, 300000, False),
])
def test_compaction_reads_this_machines_window_or_recommends_335000(tmp_path, monkeypatch, settings, window, at, is_set):
    monkeypatch.setattr(config, "HOME", tmp_path)
    if settings is not None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(settings if isinstance(settings, str) else json.dumps(settings))
    assert config.compaction() == (window, at, is_set)


def test_advise_and_spend_name_the_machines_compaction(tmp_path, monkeypatch):
    from teyla import advise, spend
    monkeypatch.setattr(config, "HOME", tmp_path)
    assert advise._compaction() == "set autoCompactWindow 335000 in ~/.claude/settings.json: compaction at ~300k"
    assert spend._w2_fix().startswith('compaction is not set: add "autoCompactWindow": 335000 to ~/.claude/settings.json (~300k)')
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"autoCompactWindow": 400000}))
    assert advise._compaction() == "autoCompactWindow 400000: compaction at ~365k"
    assert spend._w2_fix().startswith("compaction is set (autoCompactWindow 400000, ~365k)")


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    for d in (".codex",):
        (h / d).mkdir(parents=True)
    monkeypatch.setattr(harness, "HOME", h)
    monkeypatch.setattr(harness, "HOOKS_DIR", h / ".teyla" / "hooks")
    monkeypatch.setattr(policy, "HOME", h)
    monkeypatch.setattr(policy, "POLICY", h / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "TARGETS", {"claude-code": h / ".claude" / "CLAUDE.md", "codex": h / ".codex" / "AGENTS.md",
                                            "grok": h / ".grok" / "AGENTS.md", "hermes": h / ".hermes" / "SOUL.md",
                                            "cursor": h / ".cursor" / "skills" / "teyla-policy" / "SKILL.md"})
    return h


def test_harness_sync_wires_the_codex_stop_hook_only_while_the_key_is_on(fake_home):
    hooks_json = fake_home / ".codex" / "hooks.json"
    harness.sync(home=fake_home)
    assert "Stop" not in json.loads(hooks_json.read_text())["hooks"]
    assert (fake_home / ".teyla" / "hooks" / "land-check.sh").stat().st_mode & 0o111
    # a user's own Stop hook, then the key on
    d = json.loads(hooks_json.read_text())
    d["hooks"]["Stop"] = [{"hooks": [{"type": "command", "command": "/x/mine.sh"}]}]
    hooks_json.write_text(json.dumps(d))
    assert config.set_value("hooks.land_check", "true").startswith("set")
    lines = harness.sync(home=fake_home)
    assert any("Stop (land check)" in l for l in lines)
    stop = json.loads(hooks_json.read_text())["hooks"]["Stop"]
    assert stop[0] == {"hooks": [{"type": "command", "command": "/x/mine.sh"}]}
    assert stop[1]["hooks"][0]["command"] == f"{fake_home / '.teyla' / 'hooks' / 'land-check.sh'} --codex"
    row = next(r for r in harness.status(home=fake_home) if r["harness"] == "codex")
    assert row["hooks"] is True and row["trust"]["total"] == 3 and "Stop untrusted" in row["trust"]["missing"]
    # off again: Teyla's handler goes, the user's stays, and status agrees
    assert config.set_value("hooks.land_check", "false").startswith("set")
    assert next(r for r in harness.status(home=fake_home) if r["harness"] == "codex")["hooks"] is False
    harness.sync(home=fake_home)
    assert json.loads(hooks_json.read_text())["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "/x/mine.sh"}]}]
    assert harness.sync(home=fake_home)[0].startswith("in sync:")  # (Cursor counts when its app is installed)


def test_codex_stop_group_alone_is_dropped_when_the_key_goes_off():
    on = harness._codex_hooks({}, land_check=True)
    assert len(on["hooks"]["Stop"]) == 1
    off = harness._codex_hooks(on, land_check=False)
    assert "Stop" not in off["hooks"]
    assert harness._codex_hooks({"hooks": {"Stop": []}}, land_check=False)["hooks"]["Stop"] == []


def test_review_skill_is_lean_and_synced_to_the_other_harnesses(fake_home):
    text = (ROOT / "plugin" / "skills" / "review" / "SKILL.md").read_text()
    assert text.startswith("---\nname: review\n")
    for must in ("No P1/P2", "same-provider review", "cross-provider", "~/ops/bin/codex-review", "--commit <sha>",
                 "git merge-base", "P1 path:line — defect — scenario", "No round three", 'model: "opus"'):
        assert must in text, must
    assert len(text.splitlines()) < 80, "under one screen"
    assert "teyla-review" in harness.skill_names()
    harness.sync(home=fake_home)
    synced = (fake_home / ".codex" / "skills" / "teyla-review" / "SKILL.md").read_text()
    assert "name: teyla-review" in synced and "No P1/P2" in synced and "plugin/skills/review/SKILL.md" in synced

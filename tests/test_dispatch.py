"""`teyla dispatch` and `teyla say`. No test starts a real `codex` or `claude`: `dispatch.spawn` and
`answer.run` are replaced. The worktree test uses a real `git` in tmp dirs, with a local origin."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import stat
import subprocess

import pytest

from teyla import answer, cli, config, dispatch

NOW = dt.datetime(2026, 10, 17, 1, 30)
CODEX_SID = "01a14630-4c3f-7921-91ca-b89037bced86"


def sh(*cmd, cwd=None):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A repo `atlas` cloned from a local origin, a worktree root, and a recording spawn."""
    class W:
        pass
    w = W()
    origin = tmp_path / "origin.git"
    sh("git", "init", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    sh("git", "clone", str(origin), str(seed))
    (seed / "a.txt").write_text("a")
    sh("git", "add", "a.txt", cwd=seed)
    sh("git", "commit", "-m", "init", cwd=seed)
    sh("git", "push", "origin", "HEAD:main", cwd=seed)
    w.repo = tmp_path / "atlas"
    sh("git", "clone", str(origin), str(w.repo))
    w.root = tmp_path / "worktrees"
    w.index = {"atlas": w.repo}
    w.spawned = []

    def fake_spawn(cmd, cwd, log, settle_s=0):
        w.spawned.append({"cmd": cmd, "cwd": cwd, "log": log})
        return 4242, w.code, w.out
    w.code, w.out = 0, "started"
    monkeypatch.setattr(dispatch, "spawn", fake_spawn)
    monkeypatch.setattr(dispatch, "codex_lane", lambda: "/ops/bin/codex-lane")
    w.go = lambda text="Fix the sync bug", **kw: dispatch.dispatch(
        "atlas", text, now=NOW, index=w.index, wt_root=w.root, **kw)
    return w


# --- dispatch ----------------------------------------------------------------------------------

def test_slug_and_branch_name():
    assert dispatch.slug("Fix the Sync bug, now!!") == "fix-the-sync-bug-now"
    assert dispatch.slug("   ") == "task"
    assert dispatch.slug("\u0436") == "task"
    assert len(dispatch.slug("word " * 40)) <= dispatch.SLUG_MAX
    assert not dispatch.slug("word " * 40).endswith("-")
    assert dispatch.branch_name("Fix it", NOW) == "task/20261017-0130-fix-it"


def test_codex_dispatch_cuts_a_worktree_from_origin_and_starts_a_lane(world):
    r = world.go("Fix the sync bug")
    wt = world.root / "atlas" / "task" / "20261017-0130-fix-the-sync-bug"
    assert r["ok"] and r["via"] == "codex-exec" and r["worktree"] == str(wt) and r["link"] == f"file://{wt}"
    assert (wt / "a.txt").exists()
    branch = subprocess.run(["git", "-C", str(wt), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    assert branch == "task/20261017-0130-fix-the-sync-bug"
    # no upstream: a stray `git push` cannot target the default branch
    assert subprocess.run(["git", "-C", str(wt), "config", f"branch.{branch}.merge"], capture_output=True).returncode != 0
    c = world.spawned[0]
    assert c["cwd"] == str(wt)
    assert c["cmd"][:6] == ["/ops/bin/codex-lane", "-m", "gpt-6.1-sol", "-C", str(wt), "-s"]
    assert c["cmd"][6] == "workspace-write"
    assert c["cmd"][-2] == "--" and c["cmd"][-1] == dispatch.HEADER + "\n\nFix the sync bug"
    assert c["cmd"][c["cmd"].index("--add-dir") + 1].endswith("atlas/.git")


def test_the_main_checkout_is_untouched(world):
    head = subprocess.run(["git", "-C", str(world.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    world.go()
    assert subprocess.run(["git", "-C", str(world.repo), "status", "--porcelain"], capture_output=True, text=True).stdout == ""
    assert subprocess.run(["git", "-C", str(world.repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout == head
    assert subprocess.run(["git", "-C", str(world.repo), "branch", "--show-current"], capture_output=True, text=True).stdout.strip() == "main"


def test_the_text_is_one_argv_entry_and_never_reaches_a_shell(world):
    nasty = "-x; rm -rf ~ $(whoami) `id` 'quote' \"dq\"\nsecond line"
    r = world.go(nasty)
    assert r["ok"]
    cmd = world.spawned[0]["cmd"]
    assert cmd[-1] == dispatch.HEADER + "\n\n" + nasty and cmd[-2] == "--"
    assert cmd.count("--") == 1 and "sh" not in cmd[:1]


def test_claude_dispatch_waits_for_the_guard_then_runs_claude_with_the_prompt_as_an_argument(world):
    r = world.go("Add a settings screen", harness="claude")
    assert r["ok"] and r["via"] == "claude-bg"
    cmd = world.spawned[0]["cmd"]
    assert cmd[:3] == ["sh", "-c", 'teyla load --wait --kind lane && exec "$@"']
    inner = cmd[4:]                                    # [0] is $0 of the script, the rest is "$@"
    assert inner[:5] == ["claude", "--bg", "--model", "claude-sonnet-5-5", "--permission-mode"]
    assert inner[5] == "acceptEdits"
    assert inner[-1] == dispatch.HEADER + "\n\nAdd a settings screen"
    assert "Add a settings screen" not in cmd[2]       # the script text holds no part of the task


def test_claude_permission_mode_comes_from_config_and_falls_back(world, monkeypatch):
    monkeypatch.setattr(config, "load", lambda *a, **k: {"dispatch": {"claude_permission_mode": "plan"}})
    world.go(harness="claude")
    assert world.spawned[0]["cmd"][world.spawned[0]["cmd"].index("--permission-mode") + 1] == "plan"
    monkeypatch.setattr(config, "load", lambda *a, **k: {"dispatch": {"claude_permission_mode": "yolo"}})
    assert dispatch.permission_mode() == "acceptEdits"


def test_model_override_and_flag_shaped_models_are_refused(world):
    world.go(model="gpt-6-astra")
    assert world.spawned[0]["cmd"][2] == "gpt-6-astra"
    r = world.go(model="--dangerously-bypass-approvals-and-sandbox")
    assert not r["ok"] and "not a model name" in r["detail"] and len(world.spawned) == 1


def test_the_journal_and_the_log_are_owner_only(world, tmp_path):
    r = world.go("Fix the sync bug")
    j = dispatch.journal_path()
    rows = [json.loads(l) for l in j.read_text().splitlines()]
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"id", "product", "harness", "worktree", "branch", "started", "pid", "log"}
    assert row["id"] == r["id"] and row["product"] == "atlas" and row["harness"] == "codex" and row["pid"] == 4242
    assert row["worktree"] == r["worktree"] and row["log"].endswith(f"dispatch/{r['id']}.log")
    assert stat.S_IMODE(j.stat().st_mode) == 0o600
    world.go("Another task")
    assert len(j.read_text().splitlines()) == 2 and stat.S_IMODE(j.stat().st_mode) == 0o600


def test_spawn_writes_an_owner_only_log_even_over_an_open_one(tmp_path):
    log = tmp_path / "d" / "x.log"
    log.parent.mkdir()
    log.write_text("old\n")
    log.chmod(0o644)
    pid, code, out = dispatch.spawn(["sh", "-c", "echo hello"], str(tmp_path), str(log), settle_s=3)
    assert code == 0 and out == "hello" and pid
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    assert dispatch.spawn(["teyla-no-such-program-xyz"], str(tmp_path), str(log))[1] == 127


def test_spawn_reports_a_command_that_dies_at_once(tmp_path):
    pid, code, out = dispatch.spawn(["sh", "-c", "echo boom; exit 3"], str(tmp_path), str(tmp_path / "l.log"), settle_s=3)
    assert code == 3 and out == "boom"


def test_a_failed_start_keeps_the_worktree_and_writes_no_journal_row(world):
    world.code, world.out = 75, "the machine is still overloaded"
    r = world.go()
    assert not r["ok"] and "did not start" in r["detail"] and "overloaded" in r["detail"]
    assert pathlib.Path(r["worktree"]).is_dir() and not dispatch.journal_path().exists()


def test_it_refuses_when_the_worktree_path_exists(world):
    assert world.go()["ok"]
    r = world.go()
    assert not r["ok"] and "already exists" in r["detail"] and len(world.spawned) == 1


def test_dry_prints_the_plan_and_changes_nothing(world):
    r = world.go("Fix the sync bug", dry=True)
    assert r["ok"] and r["dry"] and r["detail"].startswith("would run: ")
    assert "worktree add --no-track -b task/20261017-0130-fix-the-sync-bug" in r["detail"]
    assert "codex-lane" in r["detail"] and "origin/main" in r["detail"]
    assert not world.root.exists() and world.spawned == [] and not dispatch.journal_path().exists()
    assert not (dispatch.dispatch_dir()).exists()


def test_safe_mode_refuses_dispatch(world, monkeypatch):
    monkeypatch.setenv("TEYLA_SAFE", "1")
    r = world.go()
    assert not r["ok"] and "safe mode" in r["detail"]
    assert not world.root.exists() and world.spawned == []


def test_unknown_product_unknown_harness_and_empty_text(world):
    assert "unknown product" in dispatch.dispatch("nope", "x", now=NOW, index=world.index, wt_root=world.root)["detail"]
    assert "not a git checkout" in dispatch.dispatch("/no/such/dir", "x", now=NOW, wt_root=world.root)["detail"]
    assert "unknown harness" in world.go(harness="grok")["detail"]
    assert "empty" in world.go("   ")["detail"]
    assert world.spawned == [] and not world.root.exists()


def test_a_product_can_be_a_path_or_a_differently_cased_name(world):
    assert dispatch.resolve_repo(str(world.repo), {})[0] == world.repo.resolve()
    assert dispatch.resolve_repo("ATLAS", world.index)[0] == world.repo


def test_default_branch_follows_origin_head_and_falls_back_to_master(monkeypatch, tmp_path):
    seen = []

    def fake(repo, *args, timeout=0):
        seen.append(args)
        if args[0] == "symbolic-ref":
            return 128, "fatal: not a symbolic ref"
        return (0, "") if args[-1] == "refs/remotes/origin/master" else (1, "")
    monkeypatch.setattr(dispatch, "git", fake)
    assert dispatch.default_branch(tmp_path) == "master"
    monkeypatch.setattr(dispatch, "git", lambda repo, *a, timeout=0: (0, "origin/trunk") if a[0] == "symbolic-ref" else (1, ""))
    assert dispatch.default_branch(tmp_path) == "trunk"
    monkeypatch.setattr(dispatch, "git", lambda *a, **k: (1, ""))
    assert dispatch.default_branch(tmp_path) is None


def test_a_failed_fetch_is_reported_but_does_not_stop_the_task(world, monkeypatch):
    real = dispatch.git

    def flaky(repo, *args, timeout=0):
        return (1, "could not resolve host") if args[0] == "fetch" else real(repo, *args)
    monkeypatch.setattr(dispatch, "git", flaky)
    r = world.go()
    assert r["ok"] and "fetch failed: could not resolve host" in r["detail"]


# --- the commands ------------------------------------------------------------------------------

def test_dispatch_command_takes_the_text_after_double_dash_and_prints_json(world, monkeypatch, capsys):
    monkeypatch.setattr(dispatch, "dispatch", lambda product, text, **kw: {"ok": True, "via": "codex-exec", "detail": "d",
                                                                         "id": "i", "worktree": "w", "link": "l",
                                                                         "args": [product, text, kw["harness"], kw["model"]]})
    assert cli.main(["dispatch", "atlas", "--harness", "claude", "--json", "--", "-1 for that", "and more"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["args"] == ["atlas", "-1 for that and more", "claude", None]


def test_dispatch_command_usage_errors(capsys):
    assert cli.main(["dispatch", "atlas"]) == 64
    assert cli.main(["say", "abcdef"]) == 64


# --- say ---------------------------------------------------------------------------------------

def rows():
    return [{"id": "run-codex-1", "product": "atlas", "title": "t", "harness": "codex", "model": "m", "since": "s",
             "link": f"codex://threads/{CODEX_SID}"},
            {"id": "run-desk-1", "product": "cellar", "title": "u", "harness": "claude-desktop", "model": "m",
             "since": "s", "link": "claude://claude.ai/epitaxy/local_abc123"},
            {"id": "run-bare-1", "product": "lens", "title": "v", "harness": "claude-desktop", "model": "m",
             "since": "s", "link": ""}]


@pytest.fixture
def calls(monkeypatch):
    class Calls:
        def __init__(self):
            self.calls, self.codes = [], []

        def __call__(self, cmd, cwd=None, input_text=None, timeout=30, detach=None):
            self.calls.append({"cmd": cmd, "cwd": cwd, "input": input_text, "detach": detach})
            return (self.codes.pop(0) if self.codes else 0), "out"
    c = Calls()
    monkeypatch.setattr(answer, "run", c)
    return c


def test_a_live_codex_session_gets_a_queued_message(calls):
    r = dispatch.say("run-codex-1", "use the cache", rows=rows())
    assert r == {"ok": True, "via": "codex-queue", "detail": "queued; delivered after the current turn", "id": "run-codex-1"}
    assert calls.calls[0]["cmd"] == ["codex", "queue", "--thread", CODEX_SID, "--message=use the cache"]


def test_say_never_resumes_a_live_session(calls):
    for ref in ("run-codex-1", "run-desk-1"):
        dispatch.say(ref, "x", rows=rows())
    flat = [" ".join(c["cmd"]) for c in calls.calls]
    assert not any("resume" in f or "--bg" in f or " exec " in f for f in flat)
    # even when queueing fails, there is no fallback to a second writer
    calls.codes = [1]
    r = dispatch.say("run-codex-1", "x", rows=rows())
    assert not r["ok"] and len(calls.calls) == 4 and calls.calls[-1]["cmd"][:2] == ["codex", "queue"]


def test_text_that_starts_with_a_dash_is_safe_for_the_queue(calls):
    dispatch.say("run-codex-1", "--thread other", rows=rows())
    assert calls.calls[0]["cmd"][-1] == "--message=--thread other"


def test_a_claude_session_gets_the_text_copied_and_its_window_opened(calls):
    r = dispatch.say("run-desk-1", "stop and rethink", rows=rows())
    assert (r["ok"], r["via"], r["id"]) == (True, "opened", "run-desk-1")
    assert calls.calls[0]["cmd"] == ["pbcopy"] and calls.calls[0]["input"] == "stop and rethink"
    assert calls.calls[1]["cmd"] == ["open", "claude://claude.ai/epitaxy/local_abc123"]


def test_refs_match_by_id_session_id_or_prefix(calls):
    assert dispatch.say(CODEX_SID, "x", rows=rows())["id"] == "run-codex-1"
    assert dispatch.say("local_abc123", "x", rows=rows())["id"] == "run-desk-1"
    assert dispatch.say("run-cod", "x", rows=rows())["id"] == "run-codex-1"
    r = dispatch.say("run-", "x", rows=rows())
    assert not r["ok"] and "no running session" in r["detail"]       # too short to be a prefix
    r = dispatch.say("run-desk", "x", rows=rows() + [{**rows()[1], "id": "run-desk-2"}])
    assert not r["ok"] and "matches 2" in r["detail"]


def test_unknown_ref_and_a_session_with_no_way_in_return_ok_false(calls):
    r = dispatch.say("nothing-here", "x", rows=rows())
    assert r["ok"] is False and r["id"] == "" and "no running session" in r["detail"]
    r = dispatch.say("run-bare-1", "x", rows=rows())
    assert not r["ok"] and r["id"] == "run-bare-1"
    assert calls.calls == []


def test_say_dry_runs_nothing(calls):
    r = dispatch.say("run-codex-1", "use the cache", dry=True, rows=rows())
    assert r["ok"] and r["dry"] and r["detail"].startswith("would run: ") and "codex queue" in r["detail"]
    assert calls.calls == []


def test_say_command_prints_json(calls, monkeypatch, capsys):
    monkeypatch.setattr(dispatch.state, "running", lambda now, **kw: rows())
    assert cli.main(["say", "run-codex-1", "--json", "--", "use the cache"]) == 0
    assert json.loads(capsys.readouterr().out)["via"] == "codex-queue"
    assert cli.main(["say", "zzzzzzzz", "--json", "--", "x"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False

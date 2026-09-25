"""`teyla storage` — the report of what agent-driven development is holding on disk (linked
worktrees, git-ignored build output) and the `clean` command that gives the SAFE part back.

These tests build real git repos with `subprocess` (a bare "remote" and a clone as the main
checkout) and drive `scan()`/`worktrees()`/`artifacts()`/`clean()` against them, mechanically
checking the SAFE/KEEP/REVIEW rule described in storage.py's module docstring: clean, pushed,
idle, unlocked, unused worktrees go; git-ignored build output of an idle repo goes; anything
else is left with a reason. They also cover `settings()`'s tolerant config parsing, the
`clean --auto` gate in `cmd_storage`, and the daily routine wrapper's "does it clean storage"
staleness check in `routine_install`.

Every test runs with HOME pointed at tmp_path and `storage.LOG_PATH` repointed into it, so
nothing here ever touches the real ~/.teyla, ~/repos or ~/.worktrees. Every git repo a test
creates lives under tmp_path.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import time

import pytest

from teyla import routine_install, storage


# --- fixtures & small helpers -----------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # storage.LOG_PATH is bound from config.TEYLA_DIR at import time, before HOME is patched —
    # repoint it explicitly so a successful `clean(apply=True)` never writes to the real machine.
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / ".teyla" / "storage.log")


def _git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"git {args} in {cwd} failed: {r.stderr}"
    return r.stdout


def _cfg(tmp_path, **storage_overrides):
    return {"code_root": str(tmp_path / "code"), "ops_root": str(tmp_path / "noops"),
            "storage": storage_overrides}


def _make_repo(tmp_path, name="demo"):
    """A bare "remote" repo and a clone of it as the main checkout under tmp_path/code/<name>,
    with one commit on main already pushed — the shape `storage.repos()` expects."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "-c", "init.defaultBranch=main", "init", "--bare", str(remote))
    code_root = tmp_path / "code"
    code_root.mkdir(exist_ok=True)
    main = code_root / name
    _git(tmp_path, "clone", str(remote), str(main))
    _git(main, "config", "user.email", "test@example.com")
    _git(main, "config", "user.name", "Test")
    (main / "README.md").write_text("hi\n")
    _git(main, "add", "README.md")
    _git(main, "commit", "-m", "init")
    _git(main, "push", "-u", "origin", "HEAD:main")
    return code_root, main, remote


def _add_worktree(main, path, branch, push=True):
    """A linked worktree with one commit, optionally pushed to its own remote branch. The file
    name/content is keyed on the branch so two worktrees never produce byte-identical commits
    (same tree + message + author would hash the same and make an unpushed branch look pushed,
    since it would be reachable from whatever remote branch holds the identical commit)."""
    _git(main, "worktree", "add", "-b", branch, str(path))
    (path / f"{branch}.txt").write_text(f"{branch}\n")
    _git(path, "add", f"{branch}.txt")
    _git(path, "commit", "-m", f"worktree commit ({branch})")
    if push:
        _git(path, "push", "-u", "origin", branch)


def _gitdir(path):
    """The linked worktree's private gitdir, read the same way storage.py reads it."""
    text = (pathlib.Path(path) / ".git").read_text()
    return pathlib.Path(text.split("gitdir:", 1)[1].strip())


def _age_worktree(path, gitdir, days, now):
    """os.utime on the worktree dir and the gitdir files idleness is measured from."""
    t = now - days * 86400
    for p in (pathlib.Path(path), gitdir / "index", gitdir / "HEAD", gitdir / "logs" / "HEAD"):
        if p.exists():
            os.utime(p, (t, t))


# --- worktree verdicts --------------------------------------------------------------------

def test_clean_pushed_idle_worktree_is_safe(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)

    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], now=now, sizes=False)
    row = next(r for r in rep["worktrees"] if r["path"] == str(wt))
    assert row["verdict"] == "SAFE"


def test_uncommitted_change_keeps_worktree(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    (wt / "dirty.txt").write_text("uncommitted\n")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)

    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], now=now, sizes=False)
    row = next(r for r in rep["worktrees"] if r["path"] == str(wt))
    assert row["verdict"] == "KEEP"
    assert "uncommitted" in row["reason"]


def test_unpushed_branch_keeps_worktree(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat", push=False)
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)

    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], now=now, sizes=False)
    row = next(r for r in rep["worktrees"] if r["path"] == str(wt))
    assert row["verdict"] == "KEEP"
    assert "no remote branch" in row["reason"]


def test_worktree_in_use_by_a_process_is_kept(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    busy = os.path.realpath(str(wt)) + os.sep + "sub" + os.sep + "deep"

    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[busy], now=now, sizes=False)
    row = next(r for r in rep["worktrees"] if r["path"] == str(wt))
    assert row["verdict"] == "KEEP"
    assert "a process is working in it" in row["reason"]


def test_recently_touched_worktree_is_kept_as_only_recent(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    # not aged: mtimes are ~now, well inside the default 3-day idle_days window

    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], sizes=False)
    row = next(r for r in rep["worktrees"] if r["path"] == str(wt))
    assert row["verdict"] == "KEEP"
    assert row["only_recent"] is True


def test_agent_worktree_default_idle_vs_named_worktree(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    agent_wt = main / ".claude" / "worktrees" / "agent-abc123"
    named_wt = main / ".claude" / "worktrees" / "nice-name"
    _add_worktree(main, agent_wt, "agent-feat")
    _add_worktree(main, named_wt, "named-feat")
    now = time.time()
    _age_worktree(agent_wt, _gitdir(agent_wt), 1.5, now)
    _age_worktree(named_wt, _gitdir(named_wt), 1.5, now)

    # default settings: agent_idle_days=1, idle_days=3
    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], now=now, sizes=False)
    rows = {r["path"]: r for r in rep["worktrees"]}
    assert rows[str(agent_wt)]["verdict"] == "SAFE"
    assert rows[str(named_wt)]["verdict"] == "KEEP"
    assert rows[str(named_wt)]["only_recent"] is True


def test_is_agent_worktree():
    assert storage.is_agent_worktree("/repos/demo/.claude/worktrees/agent-abc123") is True
    assert storage.is_agent_worktree("/repos/demo/.claude/worktrees/nice-name") is False
    assert storage.is_agent_worktree("/repos/demo/.worktrees/agent-abc123") is False
    assert storage.is_agent_worktree("/repos/demo/.claude/worktrees/agent-abc123/nested") is False


def test_locked_worktree_is_kept(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-lock"
    _add_worktree(main, wt, "lockbranch")
    _git(main, "worktree", "lock", str(wt))
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)

    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], now=now, sizes=False)
    row = next(r for r in rep["worktrees"] if r["path"] == str(wt))
    assert row["verdict"] == "KEEP"
    assert "locked" in row["reason"]


def test_scan_never_refreshes_the_index_no_optional_locks(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    idx = _gitdir(wt) / "index"
    # bump the tracked file's mtime so a plain `git status` (without --no-optional-locks)
    # would re-stat it and rewrite the index
    os.utime(wt / "feat.txt", None)
    before = idx.stat().st_mtime_ns

    storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], sizes=False)

    after = idx.stat().st_mtime_ns
    assert after == before


# --- build/dependency artifacts -----------------------------------------------------------

def test_artifacts_build_deps_and_tracked_dir(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / ".gitignore").write_text("build/\nnode_modules/\n")
    (main / "build").mkdir()
    (main / "build" / "out.txt").write_text("x\n")
    (main / "node_modules").mkdir()
    (main / "node_modules" / "pkg.js").write_text("x\n")
    (main / "dist").mkdir()
    (main / "dist" / "index.js").write_text("x\n")
    _git(main, "add", ".gitignore", "dist")
    _git(main, "commit", "-m", "gitignore + tracked dist")
    _git(main, "push")

    # repo_idle_days uses the last commit time: push `now` 20 days into the future so the
    # just-made commit reads as idle, without touching any mtimes.
    future = time.time() + 20 * 86400
    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path, build_idle_days=14), cwds=[], now=future, sizes=False)
    by_path = {r["path"]: r for r in rep["artifacts"]}
    assert by_path[str(main / "build")]["verdict"] == "SAFE"
    assert by_path[str(main / "node_modules")]["verdict"] == "REVIEW"
    assert str(main / "dist") not in by_path

    # real "now": the repo just committed, so it reads as active — build output is kept
    rep_now = storage.scan(root=code_root, cfg=_cfg(tmp_path, build_idle_days=14), cwds=[], sizes=False)
    build_row = next(r for r in rep_now["artifacts"] if r["path"] == str(main / "build"))
    assert build_row["verdict"] == "KEEP"


# --- clean ----------------------------------------------------------------------------

def test_clean_dry_run_reports_and_removes_nothing(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], now=now, sizes=True)

    lines = storage.clean(rep, apply=False)

    assert any(l.startswith("would remove") and str(wt) in l for l in lines)
    assert wt.exists()


def test_clean_apply_removes_safe_worktree_and_build_keeps_others_and_logs(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    safe_wt = tmp_path / "wt-feat"
    _add_worktree(main, safe_wt, "feat")
    keep_wt = tmp_path / "wt-keep"
    _add_worktree(main, keep_wt, "keepbranch", push=False)

    (main / ".gitignore").write_text("build/\n")
    (main / "build").mkdir()
    (main / "build" / "o.txt").write_text("z\n")
    _git(main, "add", ".gitignore")
    _git(main, "commit", "-m", "gitignore")
    _git(main, "push")

    now = time.time()
    _age_worktree(safe_wt, _gitdir(safe_wt), 5, now)
    _age_worktree(keep_wt, _gitdir(keep_wt), 5, now)
    future = now + 20 * 86400

    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path, build_idle_days=14), cwds=[], now=future, sizes=True)
    safe_rows = {r["path"]: r for r in rep["worktrees"] + rep["artifacts"] if r["verdict"] == "SAFE"}
    assert str(safe_wt) in safe_rows and str(main / "build") in safe_rows

    lines = storage.clean(rep, apply=True)

    assert not safe_wt.exists()
    assert not (main / "build").exists()
    assert keep_wt.exists()
    worktree_list = _git(main, "worktree", "list")
    assert str(safe_wt) not in worktree_list
    assert str(keep_wt) in worktree_list
    branches = _git(main, "branch", "--list", "feat")
    assert "feat" in branches  # `git worktree remove` never deletes the branch

    log_text = storage.LOG_PATH.read_text()
    assert str(safe_wt) in log_text
    assert str(main / "build") in log_text
    assert any(l.startswith("removed") for l in lines)


def test_clean_apply_refuses_worktree_that_became_dirty_since_scan(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], now=now, sizes=False)
    row = next(r for r in rep["worktrees"] if r["path"] == str(wt))
    assert row["verdict"] == "SAFE"

    (wt / "new_untracked.txt").write_text("surprise\n")

    lines = storage.clean(rep, apply=True)

    line = next(l for l in lines if str(wt) in l)
    assert line.startswith("kept")
    assert wt.exists()


# --- settings ---------------------------------------------------------------------------

def test_settings_parses_config_set_strings_and_falls_back_on_garbage():
    cfg = {"storage": {"auto_clean": "true", "idle_days": "5", "agent_idle_days": "bogus",
                        "build_idle_days": "20"}}
    s = storage.settings(cfg)
    assert s["auto_clean"] is True
    assert s["idle_days"] == 5
    assert s["agent_idle_days"] == 1  # default: "bogus" is not an int
    assert s["build_idle_days"] == 20


# --- CLI ----------------------------------------------------------------------------------

def test_cmd_storage_clean_auto_is_silent_noop_when_auto_clean_is_off(monkeypatch, capsys):
    monkeypatch.setattr(storage.config, "load", lambda: {"storage": {"auto_clean": False}})
    args = argparse.Namespace(action="clean", auto=True, apply=False, quiet=False, json=False, no_sizes=False)

    rc = storage.cmd_storage(args)

    assert rc == 0
    assert capsys.readouterr().out == ""


# --- routine_install: daily wrapper staleness ----------------------------------------------

def test_wrapper_stale_flags_wrapper_missing_storage_clean(tmp_path, monkeypatch):
    wrapper_path = tmp_path / "daily.sh"
    monkeypatch.setattr(routine_install, "DAILY_WRAPPER_PATH", wrapper_path)
    teyla_bin = "/usr/local/bin/teyla"
    stamp = tmp_path / "daily.last"

    old_text = (
        "#!/usr/bin/env bash\n"
        f'date -u +%FT%TZ > "{stamp}"\n'
        f'TEYLA="{teyla_bin}"\n'
        '"$TEYLA" update --quiet\n'
        "teyla doctor --quiet\n"
    )
    wrapper_path.write_text(old_text)
    assert routine_install._wrapper_stale(wrapper_path, teyla_bin) is True

    fresh_text = old_text + '"$TEYLA" storage clean --auto --quiet\n'
    wrapper_path.write_text(fresh_text)
    assert routine_install._wrapper_stale(wrapper_path, teyla_bin) is False


def test_daily_wrapper_template_runs_storage_clean_auto_quiet():
    assert "teyla storage clean --auto --quiet" in routine_install.DAILY_WRAPPER_TEMPLATE


# --- what `git worktree remove` would destroy without complaint (review findings) ----------

def _safe_row(tmp_path, code_root, wt, now):
    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), cwds=[], now=now, sizes=False)
    return rep, next(r for r in rep["worktrees"] if r["path"] == str(wt))


def test_ignored_file_that_is_work_keeps_worktree(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / ".gitignore").write_text(".env\nbuild/\n")
    _git(main, "add", ".gitignore"); _git(main, "commit", "-m", "ignore"); _git(main, "push")
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    (wt / ".env").write_text("KEY=only-here\n")
    (wt / "build").mkdir(); (wt / "build" / "out.o").write_text("x")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    _, row = _safe_row(tmp_path, code_root, wt, now)
    assert row["verdict"] == "KEEP"
    assert row["reason"].endswith("not build output: .env")


def test_corrections_are_rescued_into_the_main_checkout(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / ".gitignore").write_text(".teyla/\n")
    _git(main, "add", ".gitignore"); _git(main, "commit", "-m", "ignore"); _git(main, "push")
    (main / ".teyla").mkdir(); (main / ".teyla" / "corrections.jsonl").write_text('{"a": 1}\n')
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    (wt / ".teyla").mkdir(); (wt / ".teyla" / "corrections.jsonl").write_text('{"a": 1}\n{"b": 2}\n')
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    rep, row = _safe_row(tmp_path, code_root, wt, now)
    assert row["verdict"] == "SAFE", row["reason"]
    lines = storage.clean(rep, apply=True)
    assert any(l.startswith("removed") and str(wt) in l for l in lines), lines
    assert not wt.exists()
    assert (main / ".teyla" / "corrections.jsonl").read_text() == '{"a": 1}\n{"b": 2}\n'


def test_dirty_worktree_nested_inside_keeps_the_outer_one(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / ".git" / "info" / "exclude").write_text(".claude/worktrees/\n")
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    inner = wt / ".claude" / "worktrees" / "agent-abc"
    inner.parent.mkdir(parents=True)
    _git(main, "worktree", "add", "-b", "inner", str(inner))
    (inner / "work.txt").write_text("unsaved\n")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    _, row = _safe_row(tmp_path, code_root, wt, now)
    assert row["verdict"] == "KEEP"
    assert "inside it" in row["reason"]


def test_detached_commit_only_in_reflog_keeps_worktree(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-det"
    _git(main, "worktree", "add", "--detach", str(wt), "origin/main")
    (wt / "lost.txt").write_text("only here\n")
    _git(wt, "add", "lost.txt"); _git(wt, "commit", "-m", "unpushed")
    _git(wt, "checkout", "--detach", "origin/main")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    _, row = _safe_row(tmp_path, code_root, wt, now)
    assert row["verdict"] == "KEEP"
    assert "reflog" in row["reason"]


def test_build_dirs_inside_a_nested_clone_are_not_listed(tmp_path):
    code_root, main, remote = _make_repo(tmp_path)
    (main / ".gitignore").write_text("vendor/\ndist/\n")
    _git(main, "add", ".gitignore"); _git(main, "commit", "-m", "ignore"); _git(main, "push")
    _git(main, "clone", str(remote), "vendor/lib")
    (main / "vendor" / "lib" / "dist").mkdir()
    (main / "vendor" / "lib" / "dist" / "x.js").write_text("tracked elsewhere\n")
    rows = storage.artifacts(main, [], 14, sizes=False, now=time.time() + 30 * 86400)
    assert not any("vendor" in r["path"] for r in rows), rows


def test_build_dir_a_launch_agent_runs_from_is_kept(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / ".gitignore").write_text("build/\n")
    _git(main, "add", ".gitignore"); _git(main, "commit", "-m", "ignore"); _git(main, "push")
    (main / "build").mkdir()
    rows = storage.artifacts(main, [], 14, sizes=False, now=time.time() + 30 * 86400,
                             launched=f"<string>{main}/build/tool</string>")
    assert rows[0]["verdict"] == "KEEP" and "LaunchAgent" in rows[0]["reason"]


def test_lsof_failure_means_nothing_is_safe(tmp_path, monkeypatch):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    monkeypatch.setattr(storage.subprocess, "run", _lsof_fails(storage.subprocess.run))
    assert storage.process_cwds() is None
    rep = storage.scan(root=code_root, cfg=_cfg(tmp_path), now=now, sizes=False)
    row = next(r for r in rep["worktrees"] if r["path"] == str(wt))
    assert row["verdict"] == "KEEP" and "lsof" in row["reason"]


def _lsof_fails(real_run):
    def run(cmd, *a, **kw):
        if cmd and cmd[0] == "lsof":
            raise subprocess.TimeoutExpired(cmd, 60)
        return real_run(cmd, *a, **kw)
    return run


# --- second review: what still passed as "already on the remote" or "build output" ---------

def _detached(tmp_path, main, name="wt-det"):
    wt = tmp_path / name
    _git(main, "worktree", "add", "--detach", str(wt), "origin/main")
    return wt


def test_whitespace_only_amend_is_work(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / "f.py").write_text("if x:\n    a()\n    b()\n")
    _git(main, "add", "f.py"); _git(main, "commit", "-m", "f"); _git(main, "push")
    wt = _detached(tmp_path, main)
    (wt / "f.py").write_text("if x:\n    a()\nb()\n")
    _git(wt, "commit", "-am", "f"); _git(wt, "checkout", "--detach", "origin/main")
    assert storage.reflog_only_commits(str(wt))


def test_merge_with_a_hand_resolution_is_work(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    for b, text in (("b1", "one\n"), ("b2", "two\n")):
        _git(main, "checkout", "-q", "-b", b, "main")
        (main / "c.txt").write_text(text)
        _git(main, "add", "c.txt"); _git(main, "commit", "-m", b); _git(main, "push", "-u", "origin", b)
    _git(main, "checkout", "-q", "main")
    wt = tmp_path / "wt-merge"
    _git(main, "worktree", "add", "--detach", str(wt), "origin/b1")
    subprocess.run(["git", "merge", "origin/b2"], cwd=wt, capture_output=True)
    (wt / "c.txt").write_text("one and two\n")
    _git(wt, "commit", "-am", "resolved")
    _git(wt, "checkout", "--detach", "origin/main")
    assert storage.reflog_only_commits(str(wt))


def test_a_copy_of_a_pushed_commit_is_not_work(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = _detached(tmp_path, main)
    (wt / "g.txt").write_text("g\n")
    _git(wt, "add", "g.txt"); _git(wt, "commit", "-m", "g")
    _git(wt, "push", "origin", "HEAD:refs/heads/g")
    _git(wt, "commit", "--amend", "-m", "g, reworded")  # same change, different commit
    _git(wt, "push", "-f", "origin", "HEAD:refs/heads/g2")
    _git(wt, "checkout", "--detach", "origin/main")
    _git(main, "fetch", "-q", "--prune")
    _git(main, "push", "-q", "origin", ":refs/heads/g")  # the original is gone from the remote
    _git(main, "fetch", "-q", "--prune")
    assert not storage.reflog_only_commits(str(wt))


def test_ignored_file_inside_a_tracked_build_dir_is_work(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / ".gitignore").write_text("*.p12\n")
    (main / "build").mkdir(); (main / "build" / "entitlements.plist").write_text("<plist/>\n")
    _git(main, "add", "-A"); _git(main, "commit", "-m", "b"); _git(main, "push")
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    (wt / "build" / "signing.p12").write_text("secret")
    work, _ = storage.ignored_work(str(wt))
    assert work == ["build/signing.p12"]


def test_rescue_keeps_records_apart(tmp_path):
    wt, main = tmp_path / "wt", tmp_path / "main"
    for p, text in ((wt, '{"b": 2}\n'), (main, '{"a": 1}')):
        (p / ".teyla").mkdir(parents=True); (p / ".teyla" / "corrections.jsonl").write_text(text)
    storage.rescue(str(wt), str(main))
    assert (main / ".teyla" / "corrections.jsonl").read_text() == '{"a": 1}\n{"b": 2}\n'


def test_worktree_mid_rebase_is_kept(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    wt = tmp_path / "wt-feat"
    _add_worktree(main, wt, "feat")
    (_gitdir(wt) / "rebase-merge").mkdir()
    now = time.time()
    _age_worktree(wt, _gitdir(wt), 5, now)
    _, row = _safe_row(tmp_path, code_root, wt, now)
    assert row["verdict"] == "KEEP" and "in progress" in row["reason"]


def test_build_dir_holding_an_archive_is_review(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / ".gitignore").write_text("build/\n")
    _git(main, "add", ".gitignore"); _git(main, "commit", "-m", "ignore"); _git(main, "push")
    (main / "build" / "App.xcarchive").mkdir(parents=True)
    rows = storage.artifacts(main, [], 14, sizes=False, now=time.time() + 30 * 86400)
    assert rows[0]["verdict"] == "REVIEW" and "xcarchive" in rows[0]["reason"]


def test_rescue_does_not_split_a_record_on_u2028(tmp_path):
    wt, main = tmp_path / "wt", tmp_path / "main"
    rec = '{"a": "x y"}\n'
    (wt / ".teyla").mkdir(parents=True); (wt / ".teyla" / "corrections.jsonl").write_text(rec, encoding="utf-8")
    storage.rescue(str(wt), str(main))
    assert (main / ".teyla" / "corrections.jsonl").read_text(encoding="utf-8") == rec


def test_launch_agent_working_directory_without_slash_keeps_build(tmp_path):
    code_root, main, _ = _make_repo(tmp_path)
    (main / ".gitignore").write_text("dist/\n")
    _git(main, "add", ".gitignore"); _git(main, "commit", "-m", "ignore"); _git(main, "push")
    (main / "dist").mkdir()
    plist = f"<key>WorkingDirectory</key><string>{main}</string><string>dist/a</string>"
    rows = storage.artifacts(main, [], 14, sizes=False, now=time.time() + 30 * 86400, launched=plist)
    assert rows[0]["verdict"] == "KEEP"


def test_xcuserdata_is_not_work():
    assert storage._harmless("App.xcodeproj/xcuserdata/")

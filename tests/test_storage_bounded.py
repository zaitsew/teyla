"""`teyla storage` and `teyla doctor` finish in bounded time: probes run side by side, a stuck one is
reported as "<check> did not answer in N s", `--no-sizes` never measures anything, and a worktree that is
kept for another reason is not put through the slow reflog comparison.

HOME is tmp_path; the only git repos are ones created under it."""
from __future__ import annotations

import argparse
import json
import subprocess
import threading

import pytest

from teyla import doctor, storage, storage_procs, storage_sweep


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / ".teyla" / "storage.log")
    monkeypatch.setattr(storage, "xcode_writing", lambda: False)
    monkeypatch.setattr(storage, "process_cwds", lambda: [])
    monkeypatch.setattr(storage, "booted_simulators", lambda: [])
    monkeypatch.setattr(storage, "memory_by_app", lambda top=8: [("app", 1024, 1)])
    monkeypatch.setattr(storage_procs, "find", lambda cfg=None, ctx=None: {"orphans": []})
    real_load = storage.config.load
    monkeypatch.setattr(storage.config, "load",
                        lambda: {**real_load(), "code_root": str(tmp_path / "code"), "ops_root": str(tmp_path / "noops")})
    (tmp_path / "code").mkdir()


def _args(**kw):
    base = dict(action=None, auto=False, apply=False, quiet=False, json=False, no_sizes=False)
    return argparse.Namespace(**{**base, **kw})


def _git_repo(path):
    path.mkdir(parents=True)
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", "-C", str(path), *cmd], check=True, capture_output=True)
    (path / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(path), "add", "a.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "init"], check=True, capture_output=True)


def _hang(stop):
    return lambda *a, **k: stop.wait(30) or []


def test_no_sizes_never_calls_the_size_walker(tmp_path, monkeypatch, capsys):
    def walker(path):
        raise AssertionError(f"du walked {path}")

    def sweepable(cfg):
        raise AssertionError("sweepable measures sizes")
    monkeypatch.setattr(storage, "du", walker)
    monkeypatch.setattr(storage_sweep, "sweepable", sweepable)
    (tmp_path / ".npm").mkdir()
    _git_repo(tmp_path / "code" / "demo")
    assert storage.cmd_storage(_args(no_sizes=True)) == 0
    out = capsys.readouterr().out
    assert "npm cache" in out and "did not answer" not in out


def test_a_slow_probe_is_named_and_the_rest_of_the_report_prints(monkeypatch, capsys):
    stop = threading.Event()
    monkeypatch.setattr(storage, "REPORT_TIMEOUT", 0.2)
    monkeypatch.setattr(storage, "memory_by_app", _hang(stop))
    assert storage.cmd_storage(_args(no_sizes=True)) == 0
    stop.set()
    out = capsys.readouterr().out
    assert "memory did not answer in 0.2 s" in out
    assert out.startswith("disk ")   # the sections before it are intact


def test_json_keeps_its_shape_and_lists_what_did_not_answer(monkeypatch, capsys):
    stop = threading.Event()
    monkeypatch.setattr(storage, "REPORT_TIMEOUT", 0.2)
    monkeypatch.setattr(storage, "memory_by_app", _hang(stop))
    storage.cmd_storage(_args(no_sizes=True, json=True))
    stop.set()
    rep = json.loads(capsys.readouterr().out)
    assert rep["unanswered"] == ["memory did not answer in 0.2 s"]
    assert rep["memory"] == [] and "worktrees" in rep and "caches" in rep and "reclaimable" in rep


def test_json_has_no_unanswered_key_when_everything_answered(capsys):
    storage.cmd_storage(_args(no_sizes=True, json=True))
    rep = json.loads(capsys.readouterr().out)
    assert "unanswered" not in rep and rep["memory"][0]["name"] == "app"


def test_a_repo_that_does_not_answer_adds_no_rows_and_is_named(tmp_path, monkeypatch):
    for name in ("fast", "stuck"):
        _git_repo(tmp_path / "code" / name)
    stop = threading.Event()
    real = storage.worktrees

    def worktrees(repo, *a, **k):
        if repo.name == "stuck":
            stop.wait(30)
        return real(repo, *a, **k)
    monkeypatch.setattr(storage, "worktrees", worktrees)
    rep = storage.scan(root=tmp_path / "code", sizes=False, cfg={}, cwds=[], repo_timeout=0.3)
    stop.set()
    assert rep["unanswered"] == ["repo stuck did not answer in 0.3 s"]


def test_scan_without_a_timeout_has_no_unanswered_key(tmp_path):
    _git_repo(tmp_path / "code" / "demo")
    assert "unanswered" not in storage.scan(root=tmp_path / "code", sizes=False, cfg={}, cwds=[])


def test_a_worktree_kept_for_another_reason_skips_the_reflog_comparison(tmp_path, monkeypatch):
    repo = tmp_path / "code" / "demo"
    _git_repo(repo)
    (repo / "dirty.txt").write_text("x\n")
    calls = []
    monkeypatch.setattr(storage, "reflog_only_commits", lambda path: calls.append(path) or True)
    a = storage.assess(str(repo), [], limit=0, deep=True)
    assert a["dirty"] == 1 and calls == []
    assert "its reflog holds commits nothing else contains" not in a["why"]


def test_a_tree_with_no_other_reason_is_still_compared_against_its_reflog(tmp_path, monkeypatch):
    repo = tmp_path / "code" / "demo"
    _git_repo(repo)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "fetch", "-q", "origin"], check=True, capture_output=True)
    calls = []
    monkeypatch.setattr(storage, "reflog_only_commits", lambda path: calls.append(path) or True)
    a = storage.assess(str(repo), [], limit=0, deep=True)
    assert calls == [str(repo)]
    assert a["why"] == ["its reflog holds commits nothing else contains"]


def test_doctor_names_a_probe_that_does_not_answer_and_prints_the_rest(monkeypatch):
    stop = threading.Event()
    monkeypatch.setattr(doctor, "DOCTOR_PROBE_TIMEOUT", 0.2)
    monkeypatch.setattr(storage, "doctor_checks", _hang(stop))
    monkeypatch.setattr(doctor, "_repo_checks", lambda cfg: [doctor._check("OK", "repos:agents-md", "fine")])
    cs = {c["name"]: c for c in doctor.checks(scan_repos=True)}
    stop.set()
    assert cs["storage"]["level"] == "WARN"
    assert cs["storage"]["detail"] == "storage did not answer in 0.2 s"
    assert cs["repos:agents-md"]["level"] == "OK"
    assert "safe" in cs and "machine:load" in cs


def test_doctor_names_a_harness_whose_transcripts_do_not_parse_in_time(tmp_path, monkeypatch):
    from teyla.adapters import claude_code
    stop = threading.Event()
    store = tmp_path / "claude-projects"
    store.mkdir()
    monkeypatch.setattr(doctor, "DOCTOR_PROBE_TIMEOUT", 0.2)
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(store))
    monkeypatch.setattr(claude_code, "load", _hang(stop))
    cs = {c["name"]: c for c in doctor.checks(scan_repos=False)}
    stop.set()
    assert cs["harness:claude-code"]["level"] == "WARN"
    assert cs["harness:claude-code"]["detail"] == "harness:claude-code did not answer in 0.2 s"

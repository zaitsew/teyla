""".githooks/pre-push runs ./check.sh (POLICY section 10) when the pushed range touches code.

Each test builds a throwaway repository with a stub check.sh and a stub `teyla` on PATH, so the
real suite never runs from here."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".githooks" / "pre-push"
LEAK = ROOT / "scripts" / "leak_check.py"
ZERO = "0" * 40
CYR = "".join(chr(c) for c in (0x41F, 0x440, 0x438, 0x432, 0x435, 0x442))   # a Russian greeting, built at run time


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "Test Author", "GIT_AUTHOR_EMAIL": "author@example.com",
           "GIT_COMMITTER_NAME": "Test Author", "GIT_COMMITTER_EMAIL": "author@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True,
                          check=True).stdout.strip()


def commit(repo: Path, files: dict[str, str], msg: str) -> str:
    for name, text in files.items():
        f = repo / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


class Box:
    def __init__(self, tmp: Path, check_exit: int = 0):
        self.tmp = tmp
        self.repo = tmp / "repo"
        self.repo.mkdir()
        self.home = tmp / "home"
        self.bin = tmp / "bin"
        self.bin.mkdir()
        self.marks = tmp / "marks"
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "scripts").mkdir()
        (self.repo / "scripts" / "leak_check.py").write_text(LEAK.read_text())
        check = self.repo / "check.sh"
        check.write_text(f"#!/usr/bin/env bash\necho check >> '{self.marks}'\nexit {check_exit}\n")
        check.chmod(0o755)
        stub = self.bin / "teyla"
        stub.write_text(f"#!/usr/bin/env bash\necho \"teyla $*\" >> '{self.marks}'\n")
        stub.chmod(0o755)
        self.base = commit(self.repo, {"README.md": "hello\n"}, "base")
        self.dest = tmp / "dest.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.dest)], check=True)
        git(self.repo, "push", "-q", "--no-verify", str(self.dest), f"{self.base}:refs/heads/main")

    def push(self, sha: str, **env: str) -> subprocess.CompletedProcess:
        e = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "TEYLA_HOME": str(self.home), **env}
        return subprocess.run(["bash", str(HOOK), "dest", str(self.dest)], cwd=self.repo, env=e,
                              capture_output=True, text=True,
                              input=f"refs/heads/main {sha} refs/heads/main {self.base}\n")

    def marked(self) -> list[str]:
        return self.marks.read_text().splitlines() if self.marks.exists() else []


@pytest.fixture(autouse=True)
def fake_terms(tmp_path, monkeypatch):
    """The leak check must not read the owner's real private-terms file."""
    f = tmp_path / "terms.txt"
    f.write_text("# fake terms\nzebracorn\n")
    monkeypatch.setenv("TEYLA_PRIVATE_TERMS", str(f))


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


def test_code_push_queues_then_runs_check_sh(box):
    sha = commit(box.repo, {"src/mod.py": "x = 1\n"}, "code")
    p = box.push(sha)
    assert p.returncode == 0, p.stderr
    assert box.marked() == ["teyla load --wait --kind build", "check"]


@pytest.mark.parametrize("path", ["tests/test_x.py", "apps/ios/App.swift", "scripts/tool.sh", "check.sh"])
def test_every_code_directory_triggers_the_gate(box, path):
    body = (box.repo / path).read_text() + "# touched\n" if path == "check.sh" else "x = 1\n"
    sha = commit(box.repo, {path: body}, "code")
    assert box.push(sha).returncode == 0
    assert "check" in box.marked()


def test_docs_only_push_skips_the_tests(box):
    sha = commit(box.repo, {"docs/NOTE.md": "a note\n"}, "docs")
    assert box.push(sha).returncode == 0
    assert box.marked() == []


def test_failing_check_sh_refuses_the_push(tmp_path):
    box = Box(tmp_path, check_exit=1)
    sha = commit(box.repo, {"src/mod.py": "x = 1\n"}, "code")
    p = box.push(sha)
    assert p.returncode == 1 and "check.sh failed" in p.stderr


def test_escape_hatch_skips_and_logs(box):
    sha = commit(box.repo, {"src/mod.py": "x = 1\n"}, "code")
    p = box.push(sha, TEYLA_PREPUSH_TESTS="0")
    assert p.returncode == 0 and box.marked() == []
    rows = (box.home / "prepush-skips.log").read_text().splitlines()
    assert len(rows) == 1 and rows[0].split("\t")[1] == "repo"


def test_escape_hatch_refuses_when_the_log_cannot_be_written(box):
    box.home.write_text("a file, not a directory\n")
    sha = commit(box.repo, {"src/mod.py": "x = 1\n"}, "code")
    p = box.push(sha, TEYLA_PREPUSH_TESTS="0")
    assert p.returncode == 1 and "not on record" in p.stderr


def test_leak_failure_stops_before_the_tests(box):
    sha = commit(box.repo, {"src/mod.py": "# " + CYR + "\n"}, "code")
    p = box.push(sha)
    assert p.returncode == 1 and box.marked() == []


def test_ref_deletion_runs_nothing(box):
    p = subprocess.run(["bash", str(HOOK), "dest", str(box.dest)], cwd=box.repo, capture_output=True,
                       text=True, input=f"(delete) {ZERO} refs/heads/main {box.base}\n",
                       env={**os.environ, "PATH": f"{box.bin}:{os.environ['PATH']}"})
    assert p.returncode == 0 and box.marked() == []


def test_this_repos_hook_names_check_sh():
    text = HOOK.read_text()
    assert "./check.sh" in text and "teyla load --wait --kind build" in text
    assert "TEYLA_PREPUSH_TESTS" in text

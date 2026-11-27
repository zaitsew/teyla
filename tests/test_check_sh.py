"""check.sh keeps the full pytest output in a log and ends with the failing test ids and the log path."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent

FAKE_PYTEST = """#!/bin/sh
# stands in for .venv/bin/python: `-m pytest ...` prints a long run that fails two tests
case "$*" in *"-m pytest"*) ;; *) exit 0;; esac
case "$*" in *"-rf"*) ;; *) echo "pytest was started without -rf" >&2; exit 9;; esac
i=0; while [ $i -lt 300 ]; do echo "noise line $i"; i=$((i+1)); done
echo "FAILED tests/test_a.py::test_one - assert 1 == 2"
echo "FAILED tests/test_b.py::test_two - boom"
echo "2 failed, 8 passed"
exit ${FAKE_RC:-1}
"""


def _sandbox(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "check.sh", repo / "check.sh")
    (repo / "scripts" / "leak_check.py").write_text("")
    (repo / ".venv" / "bin").mkdir(parents=True)
    py = repo / ".venv" / "bin" / "python"
    py.write_text(FAKE_PYTEST)
    py.chmod(0o755)
    (repo / ".venv" / ".teyla-install-stamp").write_text("")
    return repo


def _run(repo: pathlib.Path, tmp_path: pathlib.Path, rc: int) -> subprocess.CompletedProcess:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TEYLA_HOME": str(home / ".teyla"), "FAKE_RC": str(rc)}
    return subprocess.run(["bash", str(repo / "check.sh")], cwd=repo, env=env, capture_output=True, text=True, timeout=60)


def test_a_failing_run_ends_with_the_failed_ids_and_the_log_path(tmp_path):
    repo = _sandbox(tmp_path)
    r = _run(repo, tmp_path, 1)
    log = tmp_path / "home" / ".teyla" / "check-last.log"
    assert r.returncode == 1
    tail = (r.stdout + r.stderr).splitlines()[-4:]
    assert any(l.startswith("FAILED tests/test_a.py::test_one") for l in tail)
    assert any(l.startswith("FAILED tests/test_b.py::test_two") for l in tail)
    assert tail[-1].endswith(str(log))
    assert "noise line 299" in log.read_text()


def test_a_passing_run_keeps_its_exit_code_and_prints_no_failure_footer(tmp_path):
    repo = _sandbox(tmp_path)
    r = _run(repo, tmp_path, 0)
    assert r.returncode == 0 and "pytest failed" not in r.stdout + r.stderr
    assert os.path.exists(tmp_path / "home" / ".teyla" / "check-last.log")

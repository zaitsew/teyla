"""scripts/release.sh and scripts/changelog_release.py: release hygiene.

Nothing here reaches the network or the real repo: the script runs against a throwaway clone whose
"origin" is a local bare repository, and it stops at a fake gate before any push.
"""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

_spec = importlib.util.spec_from_file_location("changelog_release", SCRIPTS / "changelog_release.py")
cr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cr)

SAMPLE = """# Changelog

## Unreleased

- **First.** One line.

- **Second.** Another line.

## 0.2.0 — 2026-01-02 — A title

- **Old.** Already shipped.
"""


def test_moves_unreleased_under_a_dated_heading():
    out = cr.release(SAMPLE, "0.3.0", "2026-02-03")
    assert out.startswith("# Changelog\n\n## Unreleased\n\n## 0.3.0 — 2026-02-03\n\n- **First.**")
    assert "- **Second.** Another line.\n\n## 0.2.0 — 2026-01-02 — A title" in out
    # bullet text is untouched, and the old release stays where it was
    assert "- **First.** One line.\n\n- **Second.** Another line." in out
    assert out.count("## Unreleased") == 1


def test_heading_style_is_the_files_own():
    out = cr.release(SAMPLE, "0.3.0", "2026-02-03")
    headings = [line for line in out.splitlines() if line.startswith("## ")]
    assert headings == ["## Unreleased", "## 0.3.0 — 2026-02-03", "## 0.2.0 — 2026-01-02 — A title"]


def test_empty_unreleased_is_refused():
    empty = SAMPLE.replace("- **First.** One line.\n\n- **Second.** Another line.\n", "")
    with pytest.raises(cr.ChangelogError, match="empty"):
        cr.release(empty, "0.3.0", "2026-02-03")


def test_missing_unreleased_and_duplicate_version_are_refused():
    with pytest.raises(cr.ChangelogError, match="no"):
        cr.release("# Changelog\n\n## 0.2.0 — 2026-01-02\n", "0.3.0", "2026-02-03")
    with pytest.raises(cr.ChangelogError, match="already"):
        cr.release(SAMPLE, "0.2.0", "2026-02-03")


def test_cli_rewrites_the_file_and_exits_1_when_empty(tmp_path):
    f = tmp_path / "CHANGELOG.md"
    f.write_text(SAMPLE)
    script = str(SCRIPTS / "changelog_release.py")
    ok = subprocess.run(["python3", script, str(f), "0.3.0", "2026-02-03"], capture_output=True, text=True)
    assert ok.returncode == 0 and "## 0.3.0 — 2026-02-03" in f.read_text()
    again = subprocess.run(["python3", script, str(f), "0.4.0", "2026-02-04"], capture_output=True, text=True)
    assert again.returncode == 1 and "empty" in again.stderr


def test_the_repo_changelog_has_a_heading_per_release_and_a_dated_style():
    text = (ROOT / "CHANGELOG.md").read_text()
    for v in ("0.55.0", "0.55.1", "0.56.0", "0.56.1", "0.57.0", "0.58.0", "0.58.1"):
        assert f"\n## {v} — 20" in text, v


# --- release.sh -------------------------------------------------------------------------------

def _git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=True)


def _checkout(tmp_path, with_origin):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPTS / "release.sh", repo / "scripts" / "release.sh")
    (repo / "check.sh").write_text("#!/bin/sh\necho fake gate\nexit 7\n")
    (repo / "check.sh").chmod(0o755)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    if with_origin:
        bare = tmp_path / "origin.git"
        _git(tmp_path, "init", "-q", "--bare", str(bare))
        _git(repo, "remote", "add", "origin", str(bare))
        _git(repo, "push", "-q", "origin", "main")
    return repo


def _run_release(repo, tmp_path):
    env = {**os.environ, "TMPDIR": str(tmp_path), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    return subprocess.run(["bash", str(repo / "scripts" / "release.sh"), "9.9.9"],
                          cwd=repo, capture_output=True, text=True, env=env)


def test_release_refuses_when_origin_main_cannot_be_resolved(tmp_path):
    repo = _checkout(tmp_path, with_origin=False)
    r = _run_release(repo, tmp_path)
    assert r.returncode != 0
    assert "origin/main" in r.stdout
    assert "fake gate" not in r.stdout


def test_release_runs_in_a_temporary_worktree_and_removes_it_on_failure(tmp_path):
    repo = _checkout(tmp_path, with_origin=True)
    # a dirty checkout on another branch: the old script refused this, the new one does not care
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "foreign.txt").write_text("another tool's file\n")
    r = _run_release(repo, tmp_path)
    assert r.returncode == 7, r.stdout + r.stderr  # reached the gate, in the worktree
    assert "fake gate" in r.stdout
    assert "not clean" not in r.stdout and "release from main" not in r.stdout
    assert _git(repo, "worktree", "list").stdout.strip().count("\n") == 0  # the temporary worktree is gone
    assert not list(tmp_path.glob("teyla-release.*"))
    assert (repo / "foreign.txt").exists()
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "feature"


def test_release_script_text_keeps_its_steps_and_drops_the_clean_main_checks():
    script = (SCRIPTS / "release.sh").read_text()
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "working tree not clean" not in code and "release from main" not in code
    assert "worktree add -q --detach" in code and "worktree remove" in code and "trap cleanup EXIT" in code
    assert code.index("changelog_release.py") < code.index("sed -i '' \"s/^version")
    assert "git add CHANGELOG.md" in code
    for step in ("./check.sh", "gh pr create", "gh pr merge --merge", 'git tag -a "v$v"', "gh release create", "teyla update"):
        assert step in code, step

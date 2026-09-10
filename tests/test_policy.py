"""teyla.policy — POLICY.md/CLAUDE.md/ops-root init (dry must genuinely write nothing),
sync-repo's AGENTS.md/CLAUDE.md merge guard, and the ack record. Every path this module reads
or writes is monkeypatched into tmp_path so these tests never touch the real home directory."""
from __future__ import annotations

import json

import pytest

from teyla import policy


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(policy, "HOME", home)
    monkeypatch.setattr(policy, "POLICY", home / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "CLAUDE_GLOBAL", home / ".claude" / "CLAUDE.md")
    monkeypatch.setattr(policy, "ACK_PATH", home / ".teyla" / "ack.json")
    monkeypatch.setattr(policy, "TARGETS", {
        "claude-code": home / ".claude" / "CLAUDE.md",
        "codex": home / ".codex" / "AGENTS.md",
        "grok": home / ".grok" / "AGENTS.md",
        "hermes": home / ".hermes" / "SOUL.md",
    })
    return home


def _tree(path) -> set[str]:
    """Every path under `path` that exists, relative to it — used to assert a dry run touched
    nothing at all, not even by creating an empty parent directory."""
    if not path.exists():
        return set()
    return {str(p.relative_to(path)) for p in path.rglob("*")}


# --- policy init --dry ---------------------------------------------------------

def test_init_dry_does_not_write(tmp_path):
    before = _tree(tmp_path)
    msg = policy.init(dry=True)
    assert _tree(tmp_path) == before
    assert not policy.POLICY.exists()
    assert "would write" in msg


def test_init_dry_true_run_reports_already_initialised(tmp_path):
    policy.init()
    assert policy.POLICY.exists()
    msg = policy.init(dry=True)
    assert "exists" in msg


def test_init_not_dry_writes():
    msg = policy.init()
    assert policy.POLICY.exists()
    assert "wrote" in msg


def test_init_dry_with_force_does_not_overwrite_existing():
    policy.init()
    before = policy.POLICY.read_text()
    msg = policy.init(dry=True, force=True)
    assert policy.POLICY.read_text() == before
    assert "would write" in msg


# --- init_claude_md --dry -------------------------------------------------------

def test_init_claude_md_dry_does_not_write(tmp_path):
    before = _tree(tmp_path)
    msg = policy.init_claude_md(dry=True)
    assert _tree(tmp_path) == before
    assert not policy.CLAUDE_GLOBAL.exists()
    assert "would write" in msg


def test_init_claude_md_dry_with_force_does_not_overwrite_existing():
    policy.init_claude_md()
    before = policy.CLAUDE_GLOBAL.read_text()
    msg = policy.init_claude_md(dry=True, force=True)
    assert policy.CLAUDE_GLOBAL.read_text() == before
    assert "would write" in msg


def test_init_claude_md_not_dry_writes():
    msg = policy.init_claude_md(owner="alice")
    assert policy.CLAUDE_GLOBAL.exists()
    assert "wrote" in msg
    assert "alice" in policy.CLAUDE_GLOBAL.read_text()


# --- init_ops_root --dry ---------------------------------------------------------

def test_init_ops_root_dry_does_not_write(tmp_path):
    before = _tree(tmp_path)
    root = tmp_path / "ops"
    lines = policy.init_ops_root(str(root), dry=True)
    assert _tree(tmp_path) == before
    assert not root.exists()
    assert any("would" in line for line in lines)


def test_init_ops_root_not_dry_creates_everything(tmp_path):
    root = tmp_path / "ops"
    lines = policy.init_ops_root(str(root))
    assert (root / "CLAUDE.md").exists()
    assert (root / "AGENTS.md").is_symlink()
    assert (root / ".claude" / "skills").is_dir()
    assert (root / ".claude" / "rules").is_dir()
    assert (root / "runs").is_dir()
    assert "runs/" in (root / ".gitignore").read_text()
    assert (root / ".claude" / "rules" / "README.md").exists()
    assert lines and all("would" not in line for line in lines)


def test_init_ops_root_dry_on_already_initialised_reports_already(tmp_path):
    root = tmp_path / "ops"
    policy.init_ops_root(str(root))
    lines = policy.init_ops_root(str(root), dry=True)
    assert lines == ["already initialised"]


# --- policy sync respects dry too ------------------------------------------------

def test_sync_dry_does_not_write_policy(tmp_path):
    before = _tree(tmp_path)
    lines = policy.sync(dry=True)
    assert _tree(tmp_path) == before
    assert any("would write" in line for line in lines)


# --- sync_repo: refuse when both AGENTS.md and CLAUDE.md exist and differ ------

def test_sync_repo_creates_missing_agents_md(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("hello\n")
    msg = policy.sync_repo(str(repo))
    assert (repo / "AGENTS.md").is_symlink()
    assert "AGENTS.md" in msg


def test_sync_repo_both_missing():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        msg = policy.sync_repo(d)
    assert "neither exists" in msg


def test_sync_repo_refuses_when_both_exist_and_differ(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("line one\nline two\nline three\n")
    (repo / "CLAUDE.md").write_text("line one\nline four\n")
    msg = policy.sync_repo(str(repo))
    assert "both exist and differ" in msg
    assert "--prefer" in msg
    # nothing was touched
    assert not (repo / "AGENTS.md").is_symlink()
    assert not (repo / "CLAUDE.md").is_symlink()
    assert not (repo / "AGENTS.md.bak").exists()
    assert not (repo / "CLAUDE.md.bak").exists()
    # one-line summary counts lines unique to each side
    assert "2 lines only in AGENTS.md" in msg
    assert "1 only in CLAUDE.md" in msg


def test_sync_repo_identical_content_links_without_prefer(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("same\n")
    (repo / "CLAUDE.md").write_text("same\n")
    msg = policy.sync_repo(str(repo))
    assert (repo / "CLAUDE.md").is_symlink()
    assert "identical" in msg


def test_sync_repo_prefer_agents_backs_up_and_links_claude(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("agents version\n")
    (repo / "CLAUDE.md").write_text("claude version\n")
    msg = policy.sync_repo(str(repo), prefer="agents")
    assert (repo / "AGENTS.md").read_text() == "agents version\n"
    assert not (repo / "AGENTS.md").is_symlink()
    assert (repo / "CLAUDE.md").is_symlink()
    assert (repo / "CLAUDE.md.bak").read_text() == "claude version\n"
    assert "kept AGENTS.md" in msg


def test_sync_repo_prefer_claude_backs_up_and_links_agents(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("agents version\n")
    (repo / "CLAUDE.md").write_text("claude version\n")
    msg = policy.sync_repo(str(repo), prefer="claude")
    assert (repo / "CLAUDE.md").read_text() == "claude version\n"
    assert not (repo / "CLAUDE.md").is_symlink()
    assert (repo / "AGENTS.md").is_symlink()
    assert (repo / "AGENTS.md.bak").read_text() == "agents version\n"
    assert "kept CLAUDE.md" in msg


def test_sync_repo_prefer_dry_does_not_touch_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text("agents version\n")
    (repo / "CLAUDE.md").write_text("claude version\n")
    msg = policy.sync_repo(str(repo), dry=True, prefer="agents")
    assert not (repo / "CLAUDE.md").is_symlink()
    assert not (repo / "CLAUDE.md.bak").exists()
    assert "would" in msg


def test_sync_repo_already_linked_is_a_noop(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("hello\n")
    import os
    os.symlink("CLAUDE.md", repo / "AGENTS.md")
    msg = policy.sync_repo(str(repo))
    assert "already linked" in msg


# --- policy ack -------------------------------------------------------------------

def test_ack_records_sha256_and_date(tmp_path):
    policy.CLAUDE_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    policy.CLAUDE_GLOBAL.write_text("my global claude.md\n")
    import hashlib
    expected = hashlib.sha256(b"my global claude.md\n").hexdigest()

    msg = policy.ack(note="kickoff told me to")
    assert policy.ACK_PATH.exists()
    record = json.loads(policy.ACK_PATH.read_text())
    assert record["claude_md"]["sha256"] == expected
    assert record["claude_md"]["note"] == "kickoff told me to"
    import datetime as dt
    assert record["claude_md"]["date"] == dt.date.today().isoformat()
    assert expected in msg


def test_ack_without_claude_md_records_none_hash():
    msg = policy.ack()
    record = json.loads(policy.ACK_PATH.read_text())
    assert record["claude_md"]["sha256"] is None
    assert "note" not in record["claude_md"]

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


# --- policy init: roots from the Layout section, and Teyla acks the CLAUDE.md it writes --------

def test_layout_roots_reads_the_template_shape():
    text = ("## Layout\n\n- `~/work/<repo>` — flat, one level, one directory per git repo\n"
            "- `~/ops-here` — everything that is not a code repo: notes, plans, runs, the wiki\n")
    assert policy.layout_roots([text]) == {"code_root": "~/work", "ops_root": "~/ops-here"}
    assert policy.layout_roots(["no layout here"]) == {}
    # POLICY.md wins over CLAUDE.md for a key both state; each file can fill in the other's gap
    assert policy.layout_roots(["- `~/a/<repo>` x", "- `~/b/<repo>` y\n- `~/o` — everything that is not a code repo"]) == \
        {"code_root": "~/a", "ops_root": "~/o"}


def test_layout_roots_reads_the_files_on_disk(_isolated_paths):
    assert policy.layout_roots() == {}
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("# P\n\n## Layout\n\n- `~/work/<repo>` — flat\n")
    assert policy.layout_roots() == {"code_root": "~/work"}


def test_policy_init_seeds_config_from_layout_and_acks_its_own_claude_md(_isolated_paths, monkeypatch, tmp_path, capsys):
    from teyla import config
    from teyla.cli import main
    monkeypatch.setattr(config, "CONFIG_PATH", _isolated_paths / ".teyla" / "config.toml")
    monkeypatch.setattr(config, "TEYLA_DIR", _isolated_paths / ".teyla")
    monkeypatch.setattr(policy, "BASE_PATH", _isolated_paths / ".teyla" / "policy-base.md")
    policy.POLICY.parent.mkdir(parents=True)
    policy.POLICY.write_text("# P\nOwner: Ada.\n\n## Layout\n\n- `~/work/<repo>` — flat, one level\n")
    rc = main(["policy", "init", "--owner", "Ada", "--claude-md"])
    out = capsys.readouterr().out
    assert "layout from policy: code_root=~/work" in out
    assert config.load()["code_root"] == "~/work", "seeded from the policy's Layout, not the ~/repos constant"
    assert "`~/work/<repo>`" in policy.CLAUDE_GLOBAL.read_text()
    assert "recorded" in out and policy.ACK_PATH.exists()
    rec = json.loads(policy.ACK_PATH.read_text())["claude_md"]
    import hashlib
    assert rec["sha256"] == hashlib.sha256(policy.CLAUDE_GLOBAL.read_bytes()).hexdigest()
    assert "policy init --claude-md" in rec["note"]
    # an explicit flag still wins over the layout
    main(["policy", "init", "--owner", "Ada", "--code-root", "~/src", "--force"])
    assert config.load()["code_root"] == "~/src"


# --- the owner's rules reach the harnesses that cannot import (Codex, Grok, Cursor) ------------

POLICY_TEXT = "# Policy\n\n## 7. Merging\n\nOpen the PR, then stop.\n"
OWNER_MD = ("# How I want work shipped\n\nApplies in every repo.\n\n@~/.agents/POLICY.md\n\n"
            "## Shipping\n\n- MERGE-APPROVED REPOS: me/app\n\n@~/ops/releases.md\n\n"
            "Shown, not imported:\n\n```\n@~/ops/releases.md\n```\n\n@~/ops/missing.md\n")


def _wire(home, claude_md=None, harnesses=("codex", "grok")):
    for h in harnesses:
        (home / f".{h}").mkdir(exist_ok=True)
    policy.POLICY.parent.mkdir(parents=True, exist_ok=True)
    policy.POLICY.write_text(POLICY_TEXT)
    (home / "ops").mkdir(exist_ok=True)
    (home / "ops" / "releases.md").write_text("## Releases\n\nTestFlight through the API key only.\n")
    if claude_md is not None:
        policy.CLAUDE_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
        policy.CLAUDE_GLOBAL.write_text(claude_md)
    return home / ".codex" / "AGENTS.md", home / ".grok" / "AGENTS.md"


@pytest.mark.parametrize("claude_md", [None, "@~/.agents/POLICY.md\n",
                                       "# Global\n\n## How to run a session\n\n@~/.agents/POLICY.md\n"])
def test_nothing_but_the_import_keeps_the_symlink(_isolated_paths, claude_md):
    codex, grok = _wire(_isolated_paths, claude_md)
    policy.sync()
    for p in (codex, grok):
        assert p.is_symlink() and p.resolve() == policy.POLICY.resolve()
    st = policy.status()
    assert st["codex"] is True and st["grok"] is True
    assert policy.agents_text() is None and policy.drift("codex") is None


def test_owner_rules_are_generated_into_agents_md(_isolated_paths):
    codex, grok = _wire(_isolated_paths, OWNER_MD)
    lines = policy.sync()
    assert any(l.startswith(f"wrote {codex}") for l in lines)
    text = codex.read_text()
    assert not codex.is_symlink() and grok.read_text() == text
    assert text.splitlines()[0].startswith("<!-- generated by teyla policy sync")
    assert text.index("Open the PR, then stop.") < text.index(policy.OWNER_HEAD) < text.index("MERGE-APPROVED REPOS: me/app")
    assert "Edit ~/.agents/POLICY.md or ~/.claude/CLAUDE.md, not this file" in text
    assert "@~/.agents/POLICY.md" not in text, "the import line is dropped: the policy is above it"
    assert "TestFlight through the API key only." in text, "a live @~/ import is inlined"
    assert "```\n@~/ops/releases.md\n```" in text, "a fenced import is an example and stays as written"
    assert "@~/ops/missing.md" in text, "a missing file leaves the line as it was"
    assert "## Project memory (shared with Claude Code)" in text and "~/.claude/projects/<key>/memory/" in text
    assert "\n\n\n" not in text.split("## Project memory")[0]
    assert policy.POLICY.read_text() == POLICY_TEXT
    st = policy.status()
    assert st["codex"] is True and st["grok"] is True
    assert policy.sync() == ["already in sync"]


def test_the_empty_run_heading_sync_added_is_dropped(_isolated_paths):
    codex, _ = _wire(_isolated_paths, "# Mine\n\n- one rule\n")
    policy.sync()  # adds "## How to run a session" + the import to CLAUDE.md, then generates
    assert "## How to run a session" in policy.CLAUDE_GLOBAL.read_text()
    text = codex.read_text()
    assert "- one rule" in text and "How to run a session" not in text
    assert policy.status()["codex"] is True


def test_a_symlink_is_replaced_without_writing_through_it(_isolated_paths):
    codex, grok = _wire(_isolated_paths)
    policy.sync()
    assert codex.is_symlink()
    policy.CLAUDE_GLOBAL.parent.mkdir(parents=True, exist_ok=True)
    policy.CLAUDE_GLOBAL.write_text(OWNER_MD)
    assert policy.status()["codex"] is False
    assert "symlink to the policy alone" in policy.drift("codex")[0]
    policy.sync()
    assert not codex.is_symlink() and "me/app" in codex.read_text()
    assert policy.POLICY.read_text() == POLICY_TEXT, "POLICY.md itself was overwritten through the symlink"
    # and back: CLAUDE.md down to the import → a generated file (ours) becomes the symlink again
    policy.CLAUDE_GLOBAL.write_text("@~/.agents/POLICY.md\n")
    assert policy.status()["codex"] is False
    policy.sync()
    assert codex.is_symlink() and grok.is_symlink()


def test_a_marked_file_is_replaced_and_a_hand_written_one_skipped(_isolated_paths):
    codex, grok = _wire(_isolated_paths, OWNER_MD)
    codex.write_text(policy.AGENTS_MARKER + " an older version -->\n\nold text\n")
    grok.write_text("my own grok rules\n")
    lines = policy.sync()
    assert "me/app" in codex.read_text()
    assert grok.read_text() == "my own grok rules\n"
    assert f"SKIP {grok}: a real file exists; merge by hand or delete it" in lines
    assert policy.status()["grok"] is False
    why, fix = policy.drift("grok")
    assert "hand-written" in why and "delete it" in fix


def test_stale_generated_file_is_not_wired_and_says_why(_isolated_paths):
    import os
    codex, _ = _wire(_isolated_paths, OWNER_MD)
    policy.sync()
    policy.CLAUDE_GLOBAL.write_text(policy.CLAUDE_GLOBAL.read_text() + "\n- a new rule\n")
    os.utime(codex, (1, 1))
    assert policy.status()["codex"] is False
    assert policy.drift("codex") == ("~/.codex/AGENTS.md is older than ~/.claude/CLAUDE.md", "teyla policy sync")
    policy.sync()
    assert "- a new rule" in codex.read_text() and policy.status()["codex"] is True


def test_same_text_but_older_is_touched_not_rewritten(_isolated_paths):
    import os
    codex, _ = _wire(_isolated_paths, OWNER_MD)
    policy.sync()
    os.utime(codex, (1, 1))
    assert policy.sync() == ["already in sync"]
    assert codex.stat().st_mtime >= policy.CLAUDE_GLOBAL.stat().st_mtime, \
        "left older, session-start.sh would start a sync at every session"


def test_an_invisible_character_in_claude_md_writes_nothing(_isolated_paths):
    from teyla import invisible
    codex, grok = _wire(_isolated_paths, OWNER_MD.replace("me/app", "me/a​pp"))
    before = _tree(_isolated_paths)
    with pytest.raises(invisible.InvisibleText) as e:
        policy.sync()
    assert str(policy.CLAUDE_GLOBAL) in str(e.value)
    assert _tree(_isolated_paths) == before and not codex.exists() and not grok.exists()


def test_an_invisible_character_in_an_imported_file_writes_nothing(_isolated_paths):
    from teyla import invisible
    codex, _ = _wire(_isolated_paths, "# Mine\n\n- one rule\n")
    (_isolated_paths / "ops" / "releases.md").write_text("Release ‮on Fridays\n")
    policy.CLAUDE_GLOBAL.write_text("# Mine\n\n@~/ops/releases.md\n")
    with pytest.raises(invisible.InvisibleText):
        policy.sync()
    assert not codex.exists()
    assert "@~/.agents/POLICY.md" not in policy.CLAUDE_GLOBAL.read_text(), "nothing half-wired"


def test_the_work_policy_gets_the_owner_rules_too(_isolated_paths):
    codex, _ = _wire(_isolated_paths, OWNER_MD)
    policy.POLICY.write_text(policy.WORK_MARKER + " -->\n" + POLICY_TEXT)
    assert policy.is_work()
    policy.sync()
    text = codex.read_text()
    assert policy.WORK_MARKER in text and "me/app" in text and "## Project memory" in text


def test_the_cursor_skill_carries_the_same_text(_isolated_paths, monkeypatch):
    skill = _isolated_paths / ".cursor" / "skills" / "teyla-policy" / "SKILL.md"
    (_isolated_paths / ".cursor").mkdir()
    monkeypatch.setitem(policy.TARGETS, "cursor", skill)
    _wire(_isolated_paths, OWNER_MD)
    policy.sync()
    text = skill.read_text()
    assert text.startswith(policy.CURSOR_HEAD)
    assert text[len(policy.CURSOR_HEAD):] == policy.combined_text()
    assert "me/app" in text and "TestFlight through the API key only." in text
    assert policy.status()["cursor"] is True


def test_a_large_generated_file_is_warned_about(_isolated_paths):
    codex, _ = _wire(_isolated_paths, "# Mine\n\n" + "- a rule that goes on and on\n" * 1300)
    lines = policy.sync()
    assert any(l.startswith("WARN the generated AGENTS.md is") for l in lines)
    assert codex.exists()


def test_policy_sync_quiet_prints_only_what_needs_a_human(_isolated_paths, capsys):
    from teyla.cli import main
    codex, grok = _wire(_isolated_paths, OWNER_MD)
    grok.write_text("mine\n")
    assert main(["policy", "sync", "--quiet"]) in (0, None)
    out = capsys.readouterr().out
    assert out.strip() == f"SKIP {grok}: a real file exists; merge by hand or delete it"
    assert "me/app" in codex.read_text()

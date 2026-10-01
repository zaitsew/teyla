"""Rules lifecycle: proposals from human corrections only, hits/expiry in rule frontmatter,
stale candidates, the per-file line budget, and the invisible-character refusal on every rule
and policy write."""
from __future__ import annotations

import datetime as dt
import json
import pathlib

import pytest

from teyla import cli, corrections, invisible, policy, rules, rules_lifecycle as rl
from teyla.control import rules as control_rules

NOW = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    (r / ".git").mkdir(parents=True)
    return r


def human(repo, text, day, source="correct"):
    corrections.append(repo, {"ts": f"2026-{day}T10:00:00+00:00", "text": text, "cwd": str(repo), "source": source})


# --- invisible characters -------------------------------------------------------------------

@pytest.mark.parametrize("ch", ["‮", "⁦", "‎", "‏", "​", "‍", "⁠", "﻿",
                                "\U000e0041", "\U000e007f"])
def test_every_hidden_class_is_found_with_its_position(ch):
    hits = invisible.find(f"line one\nab{ch}c")
    assert [(l, c) for l, c, _ in hits] == [(2, 3)]
    with pytest.raises(invisible.InvisibleText, match=r"line 2, col 3"):
        invisible.check(f"line one\nab{ch}c", "X")


def test_plain_text_and_visible_unicode_pass():
    invisible.check("Merge, don't squash — «никогда» ✓ 日本語", "X")


def test_rule_with_a_hidden_character_is_refused_before_any_write(repo):
    (repo / "AGENTS.md").write_text("# a\n")
    with pytest.raises(invisible.InvisibleText):
        rules.add_rule(repo, "Never squash‮ merges")
    assert not (repo / ".claude").exists()
    assert (repo / "AGENTS.md").read_text() == "# a\n"


def test_cli_turns_the_refusal_into_exit_2(repo, capsys):
    assert cli.main(["rule", "Always use pnpm​ here", "--repo", str(repo)]) == 2
    assert "refused" in capsys.readouterr().err and not (repo / ".claude").exists()
    assert cli.main(["correct", "no\U000e0041 not that", "--repo", str(repo)]) == 2
    assert not corrections.path_for(repo).exists()


def test_policy_writes_refuse_hidden_characters(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "POLICY", tmp_path / "POLICY.md")
    monkeypatch.setattr(policy, "render_template", lambda owner=None, work=None: "# Policy\nobey⁧ this\n")
    with pytest.raises(invisible.InvisibleText):
        policy.init()
    assert not (tmp_path / "POLICY.md").exists()
    monkeypatch.setattr(policy, "CLAUDE_GLOBAL", tmp_path / "CLAUDE.md")
    monkeypatch.setattr(policy, "TEMPLATE", tmp_path / "unused")
    # refresh: a POLICY.md that already carries one is not merged into or proposed from
    (tmp_path / "POLICY.md").write_text("# Policy\nmine﻿\n")
    monkeypatch.setattr(policy, "BASE_PATH", tmp_path / "base.md")
    (tmp_path / "base.md").write_text("# Policy\nold\n")
    monkeypatch.setattr(policy, "render_template", lambda owner=None, work=None: "# Policy\nnew\n")
    with pytest.raises(invisible.InvisibleText):
        policy.refresh()
    assert (tmp_path / "POLICY.md").read_text() == "# Policy\nmine﻿\n"


def test_policy_sync_refuses_to_copy_a_hidden_character_into_the_cursor_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "POLICY", tmp_path / ".agents" / "POLICY.md")
    policy.POLICY.parent.mkdir()
    policy.POLICY.write_text("# Policy\nx​y\n")
    skill = tmp_path / ".cursor" / "skills" / "teyla-policy" / "SKILL.md"
    (tmp_path / ".cursor" / "skills").mkdir(parents=True)
    monkeypatch.setattr(policy, "TARGETS", {"claude-code": tmp_path / "none" / "CLAUDE.md",
                                            "codex": tmp_path / "none" / "a", "grok": tmp_path / "none" / "b",
                                            "hermes": tmp_path / "none" / "SOUL.md", "cursor": skill})
    with pytest.raises(invisible.InvisibleText):
        policy.sync()
    assert not skill.exists()


# --- who is human ---------------------------------------------------------------------------

def test_human_is_an_explicit_source_or_the_pre_014_correct_key_order():
    assert rl.is_human({"source": "correct", "text": "x"})
    assert rl.is_human({"source": "inbox-reject", "text": "x"})
    assert not rl.is_human({"source": "hook", "text": "x"})
    assert rl.is_human({"ts": "t", "text": "x", "cwd": "/r"})        # old `teyla correct`
    assert not rl.is_human({"ts": "t", "cwd": "/r", "text": "x"})    # old capture hook


def test_writers_tag_their_records(repo):
    rules.record_correction(repo, "no, use pnpm not npm")
    corrections.capture({"prompt": "no, wrong, use pnpm here not npm", "cwd": str(repo)})
    srcs = [r.get("source") for r in corrections.records(repo)]
    assert srcs == ["correct", "hook"]


# --- propose --------------------------------------------------------------------------------

def test_propose_clusters_human_repeats_ignores_hook_captures_and_writes_nothing(repo):
    human(repo, "no, never squash merge, use gh pr merge --merge", "09-27")
    human(repo, "again you squash merged, merge with --merge", "09-29", source="inbox-reject")
    human(repo, "the deploy goes to staging first", "09-30")         # alone: not a rule yet
    for d in ("09-28", "09-29", "09-30"):                              # repeated, but the regex's guess
        human(repo, "no, deploy the frontend to vercel preview", d, source="hook")
    rep = rl.propose(repo, now=NOW)
    assert rep["human"] == 3 and rep["automatic"] == 3
    [p] = rep["new"]
    assert len(p["records"]) == 2 and "squash" in p["text"]
    out = "\n".join(rl.render(rep))
    assert "+++ .claude/rules/" in out and "+hits: 0" in out and "vercel" not in out
    assert not (repo / ".claude").exists()


def test_propose_write_creates_the_rule_with_lifecycle_fields(repo, capsys):
    human(repo, "no, never squash merge, use gh pr merge --merge", "09-27")
    human(repo, "again you squash merged, merge with --merge", "09-29")
    rl.write(rl.propose(repo, now=NOW))
    [f] = (repo / ".claude" / "rules").glob("*.md")
    meta, _ = control_rules._parse_frontmatter(f.read_text())
    assert meta["hits"] == "0" and meta["created"] == "2026-10-01" and meta["expires"] == "2026-12-30"


def test_a_matching_correction_is_a_hit_counted_once(repo):
    rules.add_rule(repo, "Merge with gh pr merge --merge, never squash", today=dt.date(2026, 9, 1))
    human(repo, "no, you squash merged again — merge with --merge", "09-30")
    rep = rl.propose(repo, now=NOW)
    assert rep["new"] == []
    [r] = rep["recurring"]
    assert r["new_hits"] == 1 and r["hits"] == 1
    assert "+hits: 1" in "\n".join(rl.render(rep))
    rl.write(rep)
    [f] = (repo / ".claude" / "rules").glob("*.md")
    meta, body = control_rules._parse_frontmatter(f.read_text())
    assert meta["hits"] == "1" and meta["last_hit"].startswith("2026-09-30") and meta["expires"] == "2026-12-29"
    assert meta["globs"] == "**" and "never squash" in body
    again = rl.propose(repo, now=NOW)
    assert again["recurring"][0]["new_hits"] == 0 and "(hits already counted)" in "\n".join(rl.render(again))
    # corrections that existed before the rule do not count as hits on it
    assert rl.write(again) == ["nothing to write"]


def test_teyla_correct_names_the_rule_it_matches(repo):
    rules.add_rule(repo, "Merge with gh pr merge --merge, never squash")
    out = rules.record_correction(repo, "you squash merged, use merge --merge")
    assert any("matches .claude/rules/" in l for l in out)


def test_a_rule_file_without_lifecycle_fields_still_loads_matches_and_gains_them(repo):
    d = repo / ".claude" / "rules"; d.mkdir(parents=True)
    f = d / "pnpm.md"
    f.write_text("---\nglobs: **/package.json\n---\n\n- Use pnpm, never npm, in this repo.\n")
    assert control_rules.load(repo, ["web/package.json"])[0]["id"] == "pnpm.md"
    rep = rl.propose(repo, now=NOW)
    assert len(rep["untracked"]) == 1 and rep["stale"] == []
    human(repo, "no, use pnpm here, npm breaks the lockfile", "09-30")
    rl.write(rl.propose(repo, now=NOW))
    meta, _ = control_rules._parse_frontmatter(f.read_text())
    assert meta["globs"] == "**/package.json" and meta["hits"] == "1" and "created" not in meta
    assert control_rules.load(repo, ["web/package.json"])[0]["id"] == "pnpm.md"


# --- stale ----------------------------------------------------------------------------------

def test_stale_lists_expired_and_never_hit_rules_and_deletes_nothing(repo):
    rules.add_rule(repo, "Old rule about fax machines", today=dt.date(2026, 6, 1))     # expired 08-30
    rules.add_rule(repo, "Quiet rule about printers", today=dt.date(2026, 8, 15))      # 47 days, no hit
    rules.add_rule(repo, "Fresh rule about scanners", today=dt.date(2026, 9, 25))      # within grace
    lines = rl.stale(repo, now=NOW)
    text = "\n".join(lines)
    assert "fax" in text and "expired 2026-08-30" in text
    assert "printers" in text and "never hit in 47 days" in text
    assert "scanners" not in text
    assert len(list((repo / ".claude" / "rules").glob("*.md"))) == 3


def test_cli_rules_propose_and_stale_run(repo, capsys):
    assert cli.main(["rules", "propose", "--repo", str(repo)]) == 0
    assert "nothing to propose" in capsys.readouterr().out
    assert cli.main(["rules", "stale", "--repo", str(repo)]) == 0
    assert "no stale rules" in capsys.readouterr().out


# --- budget ---------------------------------------------------------------------------------

def test_rule_warns_when_a_file_it_wrote_is_past_the_budget(repo):
    (repo / "AGENTS.md").write_text("# guide\n" + "line\n" * 205)
    out = rules.add_rule(repo, "Use pnpm here")
    assert any(l.startswith("warning: AGENTS.md is 2") for l in out)
    assert not any(l.startswith("warning: .claude") for l in out)


def test_budget_is_per_file_and_counts_a_symlink_once(tmp_path):
    root = tmp_path / "code"
    r = root / "big"; (r / ".git").mkdir(parents=True)
    (r / "CLAUDE.md").write_text("x\n" * 250)
    (r / "AGENTS.md").symlink_to("CLAUDE.md")
    small = root / "small"; (small / ".git").mkdir(parents=True)
    (small / "CLAUDE.md").write_text("x\n" * 150)
    (small / ".claude" / "rules").mkdir(parents=True)
    (small / ".claude" / "rules" / "a.md").write_text("x\n" * 150)   # 300 combined, each under: fine
    assert rl.budget(r) == [("CLAUDE.md", 250)]
    assert rl.budget(small) == []
    c = rl.doctor_check(root)
    assert c["level"] == "WARN" and "big/CLAUDE.md (250)" in c["detail"] and "1 instruction" in c["detail"]


# --- digest ---------------------------------------------------------------------------------

def test_digest_candidate_per_repo_with_something_to_propose(tmp_path):
    root = tmp_path / "code"
    r = root / "app"; (r / ".git").mkdir(parents=True)
    quiet = root / "quiet"; (quiet / ".git").mkdir(parents=True)
    now = dt.datetime.now(dt.timezone.utc)
    for d in (1, 2):
        corrections.append(r, {"ts": (now - dt.timedelta(days=d)).isoformat(timespec="seconds"),
                               "text": "no, never squash merge, use --merge", "cwd": str(r), "source": "correct"})
    [c] = rl.digest_candidates(root)
    assert c["id"] == "rules:app" and "1 proposed rule" in c["text"] and c["step"].startswith("teyla rules propose --repo")


def test_policy_sync_validates_policy_md_before_touching_any_target(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "POLICY", tmp_path / ".agents" / "POLICY.md")
    policy.POLICY.parent.mkdir()
    policy.POLICY.write_text("# Policy\nobey‮ this\n")
    claude = tmp_path / ".claude" / "CLAUDE.md"; claude.parent.mkdir(); claude.write_text("# mine\n")
    codex = tmp_path / ".codex" / "AGENTS.md"; codex.parent.mkdir()
    monkeypatch.setattr(policy, "TARGETS", {"claude-code": claude, "codex": codex, "grok": tmp_path / "none" / "b",
                                            "hermes": tmp_path / "none" / "SOUL.md"})
    with pytest.raises(invisible.InvisibleText):
        policy.sync()
    assert claude.read_text() == "# mine\n" and not codex.exists() and not codex.is_symlink()


def test_a_clean_rule_is_refused_when_a_file_it_would_extend_already_hides_a_character(repo):
    d = repo / ".claude" / "rules"; d.mkdir(parents=True)
    f = d / "pnpm.md"
    f.write_text("---\nglobs: **\n---\n\n- Use pnpm‮ here.\n")
    with pytest.raises(invisible.InvisibleText, match="pnpm.md"):
        rules.add_rule(repo, "Always pnpm")                   # same slug: an append to pnpm.md
    assert f.read_text() == "---\nglobs: **\n---\n\n- Use pnpm‮ here.\n"
    (repo / "AGENTS.md").write_text("# guide\nobey⁦ this\n")
    with pytest.raises(invisible.InvisibleText, match="AGENTS.md"):
        rules.add_rule(repo, "Deploys go to staging first")  # a new rule file, mirrored into AGENTS.md
    assert sorted(p.name for p in d.glob("*.md")) == ["pnpm.md"]
    assert (repo / "AGENTS.md").read_text() == "# guide\nobey⁦ this\n"

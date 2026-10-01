"""`teyla harness status|sync` and `teyla rule|correct`: the plugin's skills, hooks and policy
in Cursor, Codex, Grok and Hermes, written into a fake HOME."""
from __future__ import annotations

import json
import pathlib

import pytest

from teyla import harness, policy, rules


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    for d in (".cursor", ".codex", ".grok", ".hermes"):
        (h / d).mkdir(parents=True)
    (h / ".hermes" / "config.yaml").write_text("model:\n  default: grok-4.6\n")
    (h / ".agents").mkdir()
    (h / ".agents" / "POLICY.md").write_text("# policy\n\n## 1. ladder\n\ntext\n")
    monkeypatch.setattr(harness, "HOME", h)
    monkeypatch.setattr(harness, "HOOKS_DIR", h / ".teyla" / "hooks")
    monkeypatch.setattr(policy, "HOME", h)
    monkeypatch.setattr(policy, "POLICY", h / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "TARGETS", {
        "claude-code": h / ".claude" / "CLAUDE.md", "codex": h / ".codex" / "AGENTS.md",
        "grok": h / ".grok" / "AGENTS.md", "hermes": h / ".hermes" / "SOUL.md",
        "cursor": h / ".cursor" / "skills" / "teyla-policy" / "SKILL.md"})
    return h


def test_sync_writes_skills_hooks_and_is_idempotent(home):
    lines = harness.sync(home=home)
    assert any("copied session-start.sh" in l for l in lines)
    # five skills per harness, hooks for the three that have a mechanism
    for h in ("cursor", "codex", "grok"):
        for s in harness.skill_names():
            assert (home / f".{h}" / "skills" / s / "SKILL.md").exists(), (h, s)
    for s in harness.skill_names():
        assert (home / ".hermes" / "skills" / "teyla" / s / "SKILL.md").exists()
    codex = json.loads((home / ".codex" / "hooks.json").read_text())
    assert set(codex) == {"description", "hooks"}  # Codex rejects any other top-level key
    assert set(codex["hooks"]) == {"SessionStart", "UserPromptSubmit"}
    assert codex["hooks"]["SessionStart"][0]["hooks"][0]["command"].endswith("/.teyla/hooks/session-start.sh --codex")
    assert codex["hooks"]["UserPromptSubmit"][0]["hooks"][0] == {
        "type": "command", "command": str(home / ".teyla" / "hooks" / "capture-correction.sh"), "timeout": 5}
    cur = json.loads((home / ".cursor" / "hooks.json").read_text())
    assert cur["version"] == 1 and set(cur["hooks"]) == {"sessionStart", "beforeSubmitPrompt"}
    assert cur["hooks"]["beforeSubmitPrompt"][0]["command"].endswith("/.teyla/hooks/capture-correction.sh")
    grok = json.loads((home / ".grok" / "hooks" / "teyla.json").read_text())
    assert set(grok["hooks"]) == {"SessionStart", "UserPromptSubmit"}
    yaml = (home / ".hermes" / "config.yaml").read_text()
    assert yaml.startswith("model:") and "hooks:\n  on_session_start:" in yaml and "pre_llm_call:" in yaml
    assert "session-start.sh --context-json" in yaml
    assert harness.HERMES_BEGIN in yaml and harness.HERMES_END in yaml
    scripts = home / ".teyla" / "hooks"
    assert (scripts / "capture-correction.sh").stat().st_mode & 0o111
    # second run: nothing to do
    assert harness.sync(home=home) == ["in sync: cursor, codex, grok, hermes"]
    rows = {r["harness"]: r for r in harness.status(home=home)}
    assert rows["cursor"]["skills"] == 5 and rows["cursor"]["hooks"] is True
    assert rows["codex"]["hooks"] is True and rows["grok"]["hooks"] is True and rows["hermes"]["hooks"] is True
    # wired is not approved: Codex and Hermes skip a hook nobody trusted
    assert rows["codex"]["trust"] == {"approved": 0, "total": 2,
                                      "missing": ["SessionStart untrusted", "UserPromptSubmit untrusted"]}
    assert rows["hermes"]["trust"]["approved"] == 0 and rows["hermes"]["trust"]["total"] == 3
    assert rows["grok"]["trust"] is None and rows["cursor"]["trust"] is None
    text = harness.render_status(harness.status(home=home))
    assert "wired, NOT APPROVED 0/2" in text and "/hooks" in text


def test_sync_keeps_a_users_cursor_hooks_and_refuses_a_foreign_hermes_block(home):
    cur = home / ".cursor" / "hooks.json"
    cur.write_text(json.dumps({"version": 1, "hooks": {"beforeShellExecution": [{"command": ".cursor/hooks/mine.sh"}],
                                                      "sessionStart": [{"command": "/x/other.sh"}]}}))
    (home / ".hermes" / "config.yaml").write_text("hooks:\n  pre_tool_call:\n    - command: /x/guard.sh\n")
    lines = harness.sync(home=home)
    d = json.loads(cur.read_text())
    assert d["hooks"]["beforeShellExecution"] == [{"command": ".cursor/hooks/mine.sh"}]
    assert [e["command"] for e in d["hooks"]["sessionStart"]][0] == "/x/other.sh"
    assert len(d["hooks"]["sessionStart"]) == 2
    assert any("hermes" in l and "by hand" in l for l in lines)
    assert (home / ".hermes" / "config.yaml").read_text().startswith("hooks:\n  pre_tool_call:")
    rows = {r["harness"]: r for r in harness.status(home=home)}
    assert rows["hermes"]["hooks"] is False


def test_absent_harness_is_left_alone(home, tmp_path):
    import shutil
    shutil.rmtree(home / ".codex"); shutil.rmtree(home / ".hermes")
    lines = harness.sync(home=home)
    assert not (home / ".codex").exists() and not (home / ".hermes").exists()
    assert not any("codex" in l or "hermes" in l for l in lines)
    rows = {r["harness"]: r for r in harness.status(home=home)}
    assert rows["codex"]["present"] is False


def test_rendered_skill_is_harness_neutral_and_says_where_it_came_from():
    text = harness.render_skill("harvest", "codex")
    assert text.startswith("---\nname: teyla-harvest\ndescription: ")
    assert "/teyla:rule" not in text and "`teyla rule`" in text
    assert "generated by `teyla harness sync`" in text and "plugin/skills/harvest/SKILL.md" in text
    assert "disable-model-invocation" not in text
    assert "disable-model-invocation: false" in harness.render_skill("harvest", "cursor")
    rule = harness.render_skill("teyla-rule", "grok")
    assert 'teyla rule "<the sentence>"' in rule and "plugin/commands/rule.md" in rule


def test_policy_sync_writes_the_cursor_policy_skill(home):
    st = policy.status()
    assert st["cursor"] is False
    done = policy.sync()
    assert any("Cursor user skill" in d for d in done)
    p = home / ".cursor" / "skills" / "teyla-policy" / "SKILL.md"
    assert p.read_text().startswith("---\nname: teyla-policy\n") and p.read_text().endswith("text\n")
    assert policy.status()["cursor"] is True
    (home / ".agents" / "POLICY.md").write_text("# policy v2\n")
    assert policy.status()["cursor"] is False
    policy.sync()
    assert policy.status()["cursor"] is True


# --- teyla rule / teyla correct ----------------------------------------------------------------

def test_rule_writes_scoped_file_mirrors_into_real_agents_md_and_refuses_duplicates(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "AGENTS.md").write_text("# guide\n\nsome text\n")
    out = rules.add_rule(repo, "Outbound drafts open with a claim, not a question", scope="gtm/**")
    f = repo / ".claude" / "rules" / "outbound-drafts-open-claim.md"
    assert f.read_text() == "---\nglobs: gtm/**\n---\n\n- Outbound drafts open with a claim, not a question.\n"
    assert (repo / "AGENTS.md").read_text().endswith("## Rules\n\n- Outbound drafts open with a claim, not a question.\n")
    assert out[0].startswith("wrote .claude/rules/outbound-drafts-open-claim.md")
    # exact and near-exact duplicates are refused
    again = rules.add_rule(repo, "outbound drafts open with a claim, not a question.")
    assert again == ["already there: .claude/rules/outbound-drafts-open-claim.md — nothing written"]
    # a second rule in the same cluster appends a bullet, scope kept
    rules.add_rule(repo, "Outbound drafts never name a prospect outside runs/", scope="**")
    assert (repo / "AGENTS.md").read_text().count("- Outbound") == 2
    assert len(list((repo / ".claude" / "rules").glob("*.md"))) == 2
    # dry run writes nothing
    before = sorted(p.name for p in (repo / ".claude" / "rules").glob("*.md"))
    rules.add_rule(repo, "Never use npm here, always pnpm", dry=True)
    assert sorted(p.name for p in (repo / ".claude" / "rules").glob("*.md")) == before


def test_rule_skips_a_symlinked_agents_md_and_fills_cursor_rules_when_present(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    (repo / "CLAUDE.md").write_text("# claude\n")
    (repo / "AGENTS.md").symlink_to("CLAUDE.md")
    (repo / ".cursor" / "rules").mkdir(parents=True)
    out = rules.add_rule(repo, "Never use npm here, always pnpm", scope="**/package.json")
    assert any("symlink" in l for l in out)
    assert (repo / "CLAUDE.md").read_text() == "# claude\n"
    [mdc] = list((repo / ".cursor" / "rules").glob("*.mdc"))
    assert mdc.name == "npm-pnpm.mdc"
    assert "globs: **/package.json" in mdc.read_text() and "alwaysApply: false" in mdc.read_text()
    assert mdc.read_text().endswith("- Never use npm here, always pnpm.\n")


def test_correct_records_a_line_and_says_how_to_promote(tmp_path, monkeypatch):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "th"))
    repo = tmp_path / "repo"; repo.mkdir()
    out = rules.record_correction(repo, "no, the gate opens at 14:30 not 14:00")
    assert not (repo / ".teyla").exists()
    rec = json.loads((tmp_path / "th" / "corrections" / "misc.jsonl").read_text())
    assert rec["text"].startswith("no, the gate") and rec["cwd"] == str(repo.resolve()) and rec["ts"].endswith("+00:00")
    assert out[0].endswith("(1 so far)") and any("teyla rule" in l for l in out)


# --- Codex: hooks.json, and the trust Codex asks for before it runs one -------------------------

def test_codex_hooks_keep_a_users_groups_and_leave_invalid_json_alone(home):
    p = home / ".codex" / "hooks.json"
    mine = {"matcher": "startup", "hooks": [{"type": "command", "command": "/x/mine.sh"}]}
    p.write_text(json.dumps({"description": "my hooks", "hooks": {"SessionStart": [mine],
                                                                 "Stop": [{"hooks": [{"type": "command", "command": "/x/stop.sh"}]}]}}))
    harness.sync(home=home)
    d = json.loads(p.read_text())
    assert d["description"] == "my hooks"  # not ours to replace
    assert d["hooks"]["SessionStart"][0] == mine and len(d["hooks"]["SessionStart"]) == 2
    assert d["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "/x/stop.sh"}]}]
    # a second sync does not duplicate Teyla's group
    harness.sync(home=home)
    assert len(json.loads(p.read_text())["hooks"]["SessionStart"]) == 2
    p.write_text("{not json")
    lines = harness.sync(home=home)
    assert any(l.startswith("codex:") and "not valid JSON" in l for l in lines)
    assert p.read_text() == "{not json"
    assert {r["harness"]: r for r in harness.status(home=home)}["codex"]["hooks"] is False


def test_codex_sync_keeps_a_users_handler_that_shares_a_group_with_ours(home):
    # (review of #61, P1) a user's handler grouped next to Teyla's must survive sync, and a
    # group left empty by removing ours is dropped
    p = home / ".codex" / "hooks.json"
    theirs = {"type": "command", "command": "/x/mine.sh"}
    old = str(harness.HOOKS_DIR / "session-start.sh") + " --codex"
    p.write_text(json.dumps({"hooks": {
        "SessionStart": [{"matcher": "startup", "hooks": [theirs, {"type": "command", "command": old}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": str(harness.HOOKS_DIR / "capture-correction.sh")}]}]}}))
    harness.sync(home=home)
    d = json.loads(p.read_text())["hooks"]
    assert d["SessionStart"][0] == {"matcher": "startup", "hooks": [theirs]}
    assert len(d["SessionStart"]) == 2 and d["SessionStart"][1]["hooks"][0]["command"] == old
    assert len(d["UserPromptSubmit"]) == 1
    assert harness.sync(home=home) == ["in sync: cursor, codex, grok, hermes"]
    tr = {r["harness"]: r for r in harness.status(home=home)}["codex"]["trust"]
    assert tr["total"] == 2  # the user's handler is not counted as Teyla's


def test_hermes_auto_accept_is_a_top_level_true_key_not_a_substring(home):
    # (review of #61, P2)
    harness.sync(home=home)
    cfg = home / ".hermes" / "config.yaml"
    base = cfg.read_text()

    def approved(extra):
        cfg.write_text(base + extra)
        return {r["harness"]: r for r in harness.status(home=home)}["hermes"]["trust"]["approved"]

    assert approved("# hooks_auto_accept: true\n") == 0
    assert approved("agent:\n  hooks_auto_accept: true\n") == 0
    assert approved("hooks_auto_accept: false\n") == 0
    assert approved("hooks_auto_accept: true\n") == 3
    assert approved("hooks_auto_accept: yes  # on\n") == 3
    assert approved("hooks_auto_accept: 'on'\n") == 3


def test_codex_hook_hash_matches_what_codex_computed():
    # `codex app-server` hooks/list, Codex 0.153.4, 2026-09-29: this handler in a scratch
    # CODEX_HOME/hooks.json reported currentHash sha256:e21d99f3…cf00.
    handler = {"type": "command", "timeout": 5, "statusMessage": "teyla: orientation",
               "command": "/private/tmp/claude-501/-Users-ceozaitsev-repos-teyla/"
                          "46bca301-b4cf-4e94-8a5f-57b6f50b09ab/scratchpad/hook.sh start"}
    assert harness.codex_hook_hash("SessionStart", handler) == \
        "sha256:e21d99f3378164b3cef97119afeaeb6876436c8fa4dbfc08d175a5dbedcbcf00"


def test_codex_trust_is_read_from_config_toml(home):
    harness.sync(home=home)
    hooks_json = home / ".codex" / "hooks.json"
    d = json.loads(hooks_json.read_text())
    ss, ups = d["hooks"]["SessionStart"][0]["hooks"][0], d["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    cfg = home / ".codex" / "config.toml"
    cfg.write_text('model = "gpt-6"\n\n'
                   f'[hooks.state."{hooks_json}:session_start:0:0"]\ntrusted_hash = "{harness.codex_hook_hash("SessionStart", ss)}"\n\n'
                   f'[hooks.state."{hooks_json}:user_prompt_submit:0:0"]\ntrusted_hash = "sha256:stale"\n')
    tr = {r["harness"]: r for r in harness.status(home=home)}["codex"]["trust"]
    assert tr == {"approved": 1, "total": 2, "missing": ["UserPromptSubmit modified since trusted"]}
    cfg.write_text(cfg.read_text().replace("sha256:stale", harness.codex_hook_hash("UserPromptSubmit", ups)))
    tr = {r["harness"]: r for r in harness.status(home=home)}["codex"]["trust"]
    assert tr == {"approved": 2, "total": 2, "missing": []}
    assert "approved 2/2" in harness.render_status(harness.status(home=home))


def test_hermes_trust_is_read_from_its_allowlist(home):
    harness.sync(home=home)
    pairs = harness._hermes_pairs()
    assert [e for e, _ in pairs] == ["on_session_start", "pre_llm_call", "pre_llm_call"]
    allow = home / ".hermes" / "shell-hooks-allowlist.json"
    allow.write_text(json.dumps({"approvals": [{"event": e, "command": c, "approved_at": "2026-09-29T10:00:00Z"}
                                               for e, c in pairs[:2]]}))
    tr = {r["harness"]: r for r in harness.status(home=home)}["hermes"]["trust"]
    assert tr["approved"] == 2 and tr["missing"] == ["pre_llm_call not approved"]
    cfg = home / ".hermes" / "config.yaml"
    cfg.write_text(cfg.read_text() + "hooks_auto_accept: true\n")
    assert {r["harness"]: r for r in harness.status(home=home)}["hermes"]["trust"]["approved"] == 3


def test_hermes_hooks_are_recognised_after_hermes_strips_the_markers(home):
    # Hermes 0.21.5 rewrote config.yaml on update: Teyla's marker comments and the quotes went,
    # the entries stayed. sync said "add these entries by hand" and doctor "hooks not wired".
    harness.sync(home=home)
    cfg = home / ".hermes" / "config.yaml"
    rewritten = "\n".join(l.replace('"', "") for l in cfg.read_text().splitlines() if not l.lstrip().startswith("#")) + "\n"
    cfg.write_text(rewritten)
    assert harness.sync(home=home) == ["in sync: cursor, codex, grok, hermes"]
    assert {r["harness"]: r for r in harness.status(home=home)}["hermes"]["hooks"] is True
    assert cfg.read_text() == rewritten


def test_hermes_unmarked_block_missing_one_entry_names_only_that_entry(home):
    harness.sync(home=home)
    cfg = home / ".hermes" / "config.yaml"
    text = "\n".join(l.replace('"', "") for l in cfg.read_text().splitlines()
                     if not l.lstrip().startswith("#") and "--context-json" not in l) + "\n"
    text = text.replace("      timeout: 5\n      timeout: 5\n", "      timeout: 5\n")
    cfg.write_text(text)
    lines = harness.sync(home=home)
    hermes = [l for l in lines if l.startswith("hermes:")]
    assert len(hermes) == 1 and "--context-json" in hermes[0] and "capture-correction" not in hermes[0]
    assert {r["harness"]: r for r in harness.status(home=home)}["hermes"]["hooks"] is False


def test_hermes_parser_ignores_nested_commands_and_reads_a_commented_header():
    # Codex review: an `examples:` list inside a foreign entry is not a hook; `hooks: # x` is.
    cmds = harness._hermes_pairs()
    nested = "hooks:\n  on_session_start:\n    - command: /x/guard.sh\n      examples:\n" + "".join(
        f"        - command: {c}\n" for _, c in cmds)
    assert set(harness._hermes_missing(nested)) == set(cmds)
    header = "hooks: # mine\n" + "".join(f"  {e}:\n    - command: {c}\n      timeout: 5\n" for e, c in cmds)
    assert harness._hermes_missing(header) == []


def test_hermes_parser_reads_indentless_sequences():
    # Codex review: yaml.safe_dump writes `  event:` then `  - command:` at the same indent.
    cmds = harness._hermes_pairs()
    text = "hooks:\n" + "".join(f"  {e}:\n  - command: {c}\n    timeout: 5\n" for e, c in cmds)
    assert harness._hermes_missing(text) == []


def test_hermes_parser_a_bare_dash_item_sets_the_entry_indent(tmp_path):
    # (#75) A foreign entry written as a bare `-` whose mapping follows on the next lines, with
    # nested `examples:` commands: the first `- ` the parser saw was the nested one, so it took
    # that deeper indent as the event's entry indent, counted the nested command as a hook, and
    # missed the real entries at the shallower indent.
    cmds = harness._hermes_pairs()
    (ev0, c0), rest = cmds[0], cmds[1:]
    text = (f"hooks:\n  {ev0}:\n    -\n      timeout: 9\n      examples:\n" +
            "".join(f"        - command: {c}\n" for _, c in cmds) +
            f"    - command: {c0}\n      timeout: 5\n" +
            "".join(f"  {e}:\n    - command: {c}\n      timeout: 5\n" for e, c in rest if e != ev0))
    have = harness._hermes_present_pairs(text)
    assert (ev0, c0) in have
    assert harness._hermes_missing(text) == [p for p in rest if p[0] == ev0]  # only what is truly absent
    # the nested commands alone are not hooks
    nested_only = f"hooks:\n  {ev0}:\n    -\n      examples:\n" + "".join(f"        - command: {c}\n" for _, c in cmds)
    assert harness._hermes_present_pairs(nested_only) == set()
    # a bare dash entry whose own `command:` key is on the next line is that entry's command
    keyed = f"hooks:\n  {ev0}:\n    -\n      command: {c0}\n      timeout: 5\n"
    assert harness._hermes_present_pairs(keyed) == {(ev0, c0)}


def test_hermes_auto_accept_ignores_a_column_zero_key_inside_a_multiline_flow_mapping(home):
    # (#61) `hooks_auto_accept: true` at column 0 inside `{ … }` spanning lines belongs to that
    # mapping, not to the top level.
    harness.sync(home=home)
    cfg = home / ".hermes" / "config.yaml"
    base = cfg.read_text()

    def approved(extra):
        cfg.write_text(base + extra)
        return {r["harness"]: r for r in harness.status(home=home)}["hermes"]["trust"]["approved"]

    assert approved("agent: {\nhooks_auto_accept: true\n}\n") == 0
    assert approved("agent: {\n  a: 1,\nhooks_auto_accept: true,\n  b: [1,\n2]\n}\n") == 0
    assert approved("agent:\n  tags: [x,\nhooks_auto_accept: true]\n") == 0
    # braces in quotes or comments do not open a mapping; the top-level key after one still counts
    assert approved("name: \"{not a mapping\"  # { nor this\nhooks_auto_accept: true\n") == 3
    assert approved("agent: {a: 1}\nhooks_auto_accept: true\n") == 3
    assert approved("agent: {\n  a: 1\n}\nhooks_auto_accept: true\n") == 3

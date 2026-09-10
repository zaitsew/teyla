"""`teyla plugins` (inventory + quality pass) and `teyla plugin install|uninstall`
(the no-CLI registry editor). Every test builds its own fixture plugin under `tmp_path` and
points the module's path constants there with `monkeypatch` — nothing here touches this
machine's real `~/.claude/plugins`."""
from __future__ import annotations

import json
import pathlib

import pytest

from teyla import plugin_install as pi
from teyla import plugins as pl


# --- fixtures -----------------------------------------------------------------

SKILL_SHORT_WITH_TRIGGERS = """---
name: demo
description: A demo skill. Use when asked to "do the demo thing".
---

Body.
"""

SKILL_NO_TRIGGERS = """---
name: no-triggers
description: Handles the full flow end to end, creating the artifact with the right fields.
---

Body.
"""

SKILL_LONG_MANY_CONSTRAINTS = "\n".join([
    "---",
    "name: long-and-strict",
    'description: Use when asked to "run the long thing".',
    "---",
    "",
] + [f"Line {i}: never skip this, always do that, must not forget, do not rush." for i in range(70)])

SKILL_MANY_FACTS = "\n".join([
    "---",
    "name: fact-heavy",
    'description: Use when asked to "look up the fact-heavy thing".',
    "---",
    "",
] + [f"See ticket ABC-{i}, id {100000 + i}, https://example.com/{i}" for i in range(10)])


def make_plugin(root: pathlib.Path, *, skills: dict[str, str], version: str = "1.0.0",
                 name: str = "fixture") -> pathlib.Path:
    """A plugin directory with .claude-plugin/plugin.json and one SKILL.md per (slug, text)
    in `skills`. Returns the plugin dir."""
    plugin_dir = root / "plugin"
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    (plugin_dir / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name, "version": version}))
    for slug, text in skills.items():
        d = plugin_dir / "skills" / slug
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(text)
    return plugin_dir


def make_marketplace(root: pathlib.Path, *, plugin_name: str = "fixture") -> pathlib.Path:
    """A marketplace root (root/.claude-plugin/marketplace.json -> ./plugin). Returns `root`."""
    (root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": "fixture-mp", "plugins": [{"name": plugin_name, "source": "./plugin", "description": "test"}]}))
    return root


# =============================== teyla plugins =================================

# --- frontmatter -----------------------------------------------------------------

def test_frontmatter_parses_scalars():
    fm = pl._frontmatter("---\nname: x\ndescription: has: a colon\n---\nbody")
    assert fm == {"name": "x", "description": "has: a colon"}


def test_frontmatter_no_leading_marker_is_empty():
    assert pl._frontmatter("# Just a heading\n") == {}


# --- skill_verdict, isolated from file I/O ---------------------------------------

def test_verdict_no_triggers_wins_over_everything_else():
    assert pl.skill_verdict(False, True, 99, 99) == "add triggers"


def test_verdict_split_needs_over_screen_and_many_constraints():
    assert pl.skill_verdict(True, True, pl.SPLIT_CONSTRAINT_THRESHOLD, 0) == "split"
    assert pl.skill_verdict(True, False, pl.SPLIT_CONSTRAINT_THRESHOLD, 0) != "split"


def test_verdict_move_facts_below_split_threshold():
    assert pl.skill_verdict(True, False, 0, pl.MOVE_FACTS_THRESHOLD) == "move facts"


def test_verdict_trim_when_only_over_screen():
    assert pl.skill_verdict(True, True, 0, 0) == "trim"


def test_verdict_ok_when_short_and_clean():
    assert pl.skill_verdict(True, False, 0, 0) == "ok"


# --- analyze_skill end to end on real files --------------------------------------

def test_analyze_skill_short_with_triggers(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text(SKILL_SHORT_WITH_TRIGGERS)
    s = pl.analyze_skill(p)
    assert s["name"] == "demo"
    assert s["has_triggers"] is True
    assert s["over_one_screen"] is False
    assert s["verdict"] == "ok"


def test_analyze_skill_no_triggers_flagged(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text(SKILL_NO_TRIGGERS)
    s = pl.analyze_skill(p)
    assert s["has_triggers"] is False
    assert s["verdict"] == "add triggers"


def test_analyze_skill_long_with_constraints_splits(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text(SKILL_LONG_MANY_CONSTRAINTS)
    s = pl.analyze_skill(p)
    assert s["over_one_screen"] is True
    assert s["constraint_sentences"] >= pl.SPLIT_CONSTRAINT_THRESHOLD
    assert s["verdict"] == "split"


def test_analyze_skill_many_facts_moves_facts(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text(SKILL_MANY_FACTS)
    s = pl.analyze_skill(p)
    assert s["fact_literals"] >= pl.MOVE_FACTS_THRESHOLD
    assert s["verdict"] == "move facts"


def test_analyze_skill_never_prints_body(tmp_path, capsys):
    p = tmp_path / "SKILL.md"
    p.write_text(SKILL_MANY_FACTS)
    pl.analyze_skill(p)
    assert capsys.readouterr().out == ""


# --- second-artifact and overlap ---------------------------------------------------

def test_second_artifact_flag_needs_two_distinct_types(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text('---\nname: dual\ndescription: Use when asked to "file it".\n---\n\n'
                 "Attach the workbook to the ticket before closing it.\n")
    s = pl.analyze_skill(p)
    assert set(s["second_artifact_types"]) >= {"ticket", "workbook"}
    assert s["second_artifact_flag"] is True


def test_jaccard_identical_text_is_one():
    assert pl.jaccard("same words here", "same words here") == 1.0


def test_jaccard_disjoint_text_is_zero():
    assert pl.jaccard("alpha beta", "gamma delta") == 0.0


def test_pairwise_overlaps_flags_high_similarity_only():
    skills = [
        {"name": "a", "description": "handles the full flow end to end with the right fields"},
        {"name": "b", "description": "handles the full flow end to end with the right fields"},
        {"name": "c", "description": "something entirely unrelated about wine cellars"},
    ]
    overlaps = pl.pairwise_overlaps(skills)
    pairs = {(o["a"], o["b"]) for o in overlaps}
    assert ("a", "b") in pairs
    assert not any("c" in p for p in pairs)


# --- non-skill assets -------------------------------------------------------------

def test_count_commands(tmp_path):
    d = tmp_path / "commands"
    d.mkdir()
    (d / "one.md").write_text("x")
    (d / "two.md").write_text("x")
    assert pl.count_commands(tmp_path) == 2
    assert pl.count_commands(tmp_path / "nope") == 0


def test_count_hooks_unwraps_top_level_hooks_key(tmp_path):
    d = tmp_path / "hooks"
    d.mkdir()
    (d / "hooks.json").write_text(json.dumps({
        "hooks": {
            "SessionStart": [{"hooks": [{"type": "command", "command": "a"}]}],
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "b"}]}],
        }
    }))
    assert pl.count_hooks(tmp_path) == 2


def test_count_hooks_missing_file_is_zero(tmp_path):
    assert pl.count_hooks(tmp_path) == 0


def test_count_mcp_servers(tmp_path):
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"a": {}, "b": {}}}))
    assert pl.count_mcp_servers(tmp_path) == 2
    assert pl.count_mcp_servers(tmp_path.parent) == 0


def test_find_rules_files_flags_over_20kb(tmp_path):
    d = tmp_path / "rules"
    d.mkdir()
    (d / "small.md").write_text("x" * 10)
    (d / "big.md").write_text("x" * (pl.RULES_FILE_FLAG_BYTES + 1))
    rows = {r["path"]: r for r in pl.find_rules_files(tmp_path)}
    assert rows[str(d / "small.md")]["over_20kb"] is False
    assert rows[str(d / "big.md")]["over_20kb"] is True


def test_has_templates_dir(tmp_path):
    assert pl.has_templates_dir(tmp_path) is False
    (tmp_path / "templates").mkdir()
    assert pl.has_templates_dir(tmp_path) is True


# --- registry resolution: installed vs. working copy -------------------------------

@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    known = tmp_path / "known_marketplaces.json"
    installed = tmp_path / "installed_plugins.json"
    monkeypatch.setattr(pl, "KNOWN_MARKETPLACES", known)
    monkeypatch.setattr(pl, "INSTALLED_PLUGINS", installed)
    return known, installed


def test_resolve_targets_path_mode_skips_registry(tmp_path, isolated_registry):
    plugin_dir = make_plugin(tmp_path, skills={"demo": SKILL_SHORT_WITH_TRIGGERS})
    targets = pl.resolve_targets(str(plugin_dir))
    assert len(targets) == 1
    assert targets[0]["working_path"] == str(plugin_dir.resolve())
    assert targets[0]["working_version"] == "1.0.0"


def test_resolve_targets_unknown_name_raises(isolated_registry):
    known, installed = isolated_registry
    installed.write_text(json.dumps({"version": 2, "plugins": {}}))
    with pytest.raises(pl.PluginError):
        pl.resolve_targets("nope")


def test_resolve_targets_finds_working_copy_and_flags_mismatch(tmp_path, isolated_registry):
    known, installed = isolated_registry
    mp_root = make_marketplace(tmp_path / "mp")
    make_plugin(mp_root, skills={"demo": SKILL_SHORT_WITH_TRIGGERS}, version="2.0.0")

    known.write_text(json.dumps({
        "fixture-mp": {"source": {"source": "directory", "path": str(mp_root)},
                        "installLocation": str(mp_root), "lastUpdated": "2026-09-09T00:00:00Z"},
    }))
    installed.write_text(json.dumps({"version": 2, "plugins": {
        "fixture@fixture-mp": [{"scope": "user", "installPath": str(tmp_path / "cache"),
                                  "version": "1.0.0", "installedAt": "x", "lastUpdated": "x"}],
    }}))

    targets = pl.resolve_targets(None)
    assert len(targets) == 1
    t = targets[0]
    assert t["name"] == "fixture"
    assert t["version_installed"] == "1.0.0"
    assert t["working_version"] == "2.0.0"

    reports = pl.build_report(None)
    assert reports[0]["version_mismatch"] is True
    assert reports[0]["scanned"] == "working copy"
    assert [s["name"] for s in reports[0]["skills"]] == ["demo"]


def test_build_report_with_no_scan_dir_is_empty_but_present(isolated_registry):
    known, installed = isolated_registry
    installed.write_text(json.dumps({"version": 2, "plugins": {
        "ghost@nowhere": [{"scope": "user", "installPath": "", "version": "0.0.1"}],
    }}))
    known.write_text(json.dumps({}))
    reports = pl.build_report(None)
    assert reports[0]["name"] == "ghost"
    assert reports[0]["skills"] == []


# --- CLI surface: render + error path -----------------------------------------------

def test_render_table_and_json_smoke(tmp_path, isolated_registry):
    plugin_dir = make_plugin(tmp_path, skills={"demo": SKILL_SHORT_WITH_TRIGGERS})
    reports = pl.build_report(str(plugin_dir))
    text = pl.render_table(reports)
    assert "demo" in text
    assert "ok" in text
    data = pl.render_json(reports)
    assert data["plugins"][0]["skills"][0]["name"] == "demo"


def test_render_table_no_plugins():
    assert pl.render_table([]) == "(no plugins found)\n"


def test_cmd_plugins_reports_error_for_unknown_target(isolated_registry, capsys):
    class Args:
        target = "nope"
        json = False
    rc = pl.cmd_plugins(Args())
    assert rc == 1
    assert "error" in capsys.readouterr().out


# ============================ teyla plugin install/uninstall ========================

def test_resolve_source_local_dir(tmp_path):
    root, source_dict = pi.resolve_source(str(tmp_path), marketplaces_dir=tmp_path / "marketplaces")
    assert root == tmp_path.resolve()
    assert source_dict == {"source": "directory", "path": str(tmp_path.resolve())}


def test_resolve_source_rejects_garbage(tmp_path):
    with pytest.raises(pi.InstallError):
        pi.resolve_source("not a path and not owner/repo!!", marketplaces_dir=tmp_path)


def test_resolve_source_github_shorthand_without_git(tmp_path, monkeypatch):
    monkeypatch.setattr(pi.shutil, "which", lambda name: None)
    with pytest.raises(pi.InstallError, match="git"):
        pi.resolve_source("someowner/somerepo", marketplaces_dir=tmp_path)


def test_find_hash_manifest_skips_known_registry_shapes(tmp_path):
    (tmp_path / "known_marketplaces.json").write_text(json.dumps({"a": {"x": 1}}))
    (tmp_path / "installed_plugins.json").write_text(json.dumps({"plugins": {}}))
    assert pi._find_hash_manifest(tmp_path) is None


def test_find_hash_manifest_finds_a_real_one(tmp_path):
    (tmp_path / "known_marketplaces.json").write_text(json.dumps({"a": {"x": 1}}))
    manifest = tmp_path / "some-manifest.json"
    manifest.write_text(json.dumps({"skills/demo/SKILL.md": "a" * 64}))
    assert pi._find_hash_manifest(tmp_path) == manifest


def test_hash_tree_matches_sha256(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    tree = pi._hash_tree(tmp_path)
    import hashlib
    assert tree["a.txt"] == hashlib.sha256(b"hello").hexdigest()


def test_backup_only_writes_once_per_day(tmp_path):
    target = tmp_path / "registry.json"
    target.write_text("v1")
    bak1 = pi._backup(target, today="2026-09-09")
    target.write_text("v2")
    bak2 = pi._backup(target, today="2026-09-09")
    assert bak1 == bak2
    assert pathlib.Path(bak1).read_text() == "v1"  # not clobbered by the second call


def test_backup_missing_file_is_noop(tmp_path):
    assert pi._backup(tmp_path / "nope.json") is None


@pytest.fixture
def fixture_marketplace(tmp_path):
    root = make_marketplace(tmp_path / "source")
    make_plugin(root, skills={"demo": SKILL_SHORT_WITH_TRIGGERS}, version="1.0.0")
    return root


def test_install_writes_registry_and_cache(tmp_path, fixture_marketplace):
    # a local-path install never clones (no network); the only subprocess it may run is a
    # `git -C <dir> rev-parse HEAD` sha lookup, which is fine to let run for real here since
    # `fixture_marketplace` isn't a git repo and that call just fails cleanly.
    plugins_dir = tmp_path / "plugins"
    lines = pi.install(str(fixture_marketplace), plugins_dir=plugins_dir)
    assert any("wrote known_marketplaces.json" in line for line in lines)
    assert any("wrote installed_plugins.json" in line for line in lines)
    assert any("no file-hash manifest" in line for line in lines)

    known = json.loads((plugins_dir / "known_marketplaces.json").read_text())
    assert known["fixture-mp"]["source"] == {"source": "directory", "path": str(fixture_marketplace.resolve())}

    installed = json.loads((plugins_dir / "installed_plugins.json").read_text())
    row = installed["plugins"]["fixture@fixture-mp"][0]
    cache_path = pathlib.Path(row["installPath"])
    assert row["version"] == "1.0.0"
    assert cache_path.is_dir()
    assert (cache_path / "skills" / "demo" / "SKILL.md").exists()


def test_install_is_idempotent_and_preserves_installed_at(tmp_path, fixture_marketplace):
    plugins_dir = tmp_path / "plugins"
    pi.install(str(fixture_marketplace), plugins_dir=plugins_dir)
    first = json.loads((plugins_dir / "installed_plugins.json").read_text())
    first_installed_at = first["plugins"]["fixture@fixture-mp"][0]["installedAt"]

    pi.install(str(fixture_marketplace), plugins_dir=plugins_dir)
    second = json.loads((plugins_dir / "installed_plugins.json").read_text())
    row = second["plugins"]["fixture@fixture-mp"][0]
    assert row["installedAt"] == first_installed_at
    # exactly one backup per registry file for the (single) day this test runs on
    backups = list(plugins_dir.glob("known_marketplaces.json.bak-*"))
    assert len(backups) == 1


def test_install_mirrors_an_existing_hash_manifest_format(tmp_path, fixture_marketplace):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    (plugins_dir / "some-hash-manifest.json").write_text(json.dumps({"whatever/path": "b" * 64}))
    lines = pi.install(str(fixture_marketplace), plugins_dir=plugins_dir)
    assert any("wrote hash manifest" in line for line in lines)
    cache_path = pathlib.Path(json.loads((plugins_dir / "installed_plugins.json").read_text())
                               ["plugins"]["fixture@fixture-mp"][0]["installPath"])
    manifest = json.loads((cache_path / "some-hash-manifest.json").read_text())
    assert manifest["skills/demo/SKILL.md"]


def test_install_rejects_a_directory_with_no_marketplace_manifest(tmp_path):
    with pytest.raises(pi.InstallError):
        pi.install(str(tmp_path), plugins_dir=tmp_path / "plugins")


def test_uninstall_reverses_install(tmp_path, fixture_marketplace):
    plugins_dir = tmp_path / "plugins"
    pi.install(str(fixture_marketplace), plugins_dir=plugins_dir)
    cache_path = pathlib.Path(json.loads((plugins_dir / "installed_plugins.json").read_text())
                               ["plugins"]["fixture@fixture-mp"][0]["installPath"])
    assert cache_path.is_dir()

    lines = pi.uninstall("fixture", plugins_dir=plugins_dir)
    assert any("removed installed_plugins.json" in line for line in lines)
    assert not cache_path.exists()
    installed = json.loads((plugins_dir / "installed_plugins.json").read_text())
    assert "fixture@fixture-mp" not in installed["plugins"]
    # the marketplace registration itself is left alone
    known = json.loads((plugins_dir / "known_marketplaces.json").read_text())
    assert "fixture-mp" in known


def test_uninstall_by_name_at_marketplace(tmp_path, fixture_marketplace):
    plugins_dir = tmp_path / "plugins"
    pi.install(str(fixture_marketplace), plugins_dir=plugins_dir)
    lines = pi.uninstall("fixture@fixture-mp", plugins_dir=plugins_dir)
    assert any("removed" in line for line in lines)


def test_uninstall_unknown_plugin_is_a_clean_noop(tmp_path):
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    lines = pi.uninstall("nope", plugins_dir=plugins_dir)
    assert lines == ["nope: not installed — nothing to do"]


# --- full loop: install with a tmp HOME, then `teyla plugins` sees it ----------------

def test_teyla_plugins_reads_back_what_plugin_install_wrote(tmp_path, fixture_marketplace, monkeypatch):
    home = tmp_path / "home"
    plugins_dir = home / ".claude" / "plugins"
    pi.install(str(fixture_marketplace), plugins_dir=plugins_dir)

    monkeypatch.setattr(pl, "KNOWN_MARKETPLACES", plugins_dir / "known_marketplaces.json")
    monkeypatch.setattr(pl, "INSTALLED_PLUGINS", plugins_dir / "installed_plugins.json")

    reports = pl.build_report("fixture")
    assert reports[0]["version_installed"] == "1.0.0"
    assert reports[0]["scanned"] == "working copy"
    assert [s["name"] for s in reports[0]["skills"]] == ["demo"]

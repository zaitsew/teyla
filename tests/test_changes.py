"""`teyla.changes`: the safe writes behind `teyla start`, and the undo that goes with them.
Every file here lives in a temporary directory; the real ~/.claude and ~/.codex are never touched."""
from __future__ import annotations

import json
import os
import pathlib
import stat

import pytest

from teyla import changes


@pytest.fixture
def settings(tmp_path):
    return tmp_path / "claude" / "settings.json"


def _write(p: pathlib.Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


ORIGINAL = """{
  "zeta": 1,
  "model": "opus",
  "permissions": {
    "allow": ["Bash(ls:*)"]
  },
  "alpha": [1, 2]
}
"""


def test_json_write_keeps_key_order_and_indent(settings):
    _write(settings, ORIGINAL)
    changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    text = settings.read_text()
    assert list(json.loads(text)) == ["zeta", "model", "permissions", "alpha", "autoCompactWindow"]
    assert text == json.dumps(json.loads(ORIGINAL) | {"autoCompactWindow": 335000}, indent=2) + "\n"


@pytest.mark.parametrize("indent,sample", [(4, "{\n    \"a\": 1\n}\n"), ("\t", "{\n\t\"a\": 1\n}\n")])
def test_json_write_keeps_the_files_own_indent(settings, indent, sample):
    _write(settings, sample)
    changes.apply_json("O1", settings, ["b"], 2)
    assert settings.read_text() == json.dumps({"a": 1, "b": 2}, indent=indent) + "\n"


def test_a_file_without_a_final_newline_stays_without_one(settings):
    _write(settings, '{\n  "a": 1\n}')
    changes.apply_json("O1", settings, ["b"], 2)
    assert not settings.read_text().endswith("\n")


def test_bad_json_is_refused_and_nothing_is_written(settings, tmp_path):
    _write(settings, '{"a": 1,, }')
    with pytest.raises(changes.ChangeError, match="not valid JSON"):
        changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    assert settings.read_text() == '{"a": 1,, }'
    assert [p.name for p in settings.parent.iterdir()] == ["settings.json"]   # no backup, no temp file
    assert changes.load_log() == []


def test_a_json_array_at_the_top_is_refused(settings):
    _write(settings, "[1, 2]")
    with pytest.raises(changes.ChangeError, match="not an object"):
        changes.apply_json("O1", settings, ["x"], 1)


def test_backup_and_log_are_private_and_complete(settings):
    _write(settings, ORIGINAL)
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    bak = pathlib.Path(rec["backup"])
    assert bak.name.startswith("settings.json.teyla-bak-") and bak.read_text() == ORIGINAL
    assert stat.S_IMODE(bak.stat().st_mode) == 0o600
    log = changes.log_path()
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    row = json.loads(log.read_text().splitlines()[0])
    assert {"id", "offer", "file", "key_path", "old", "new", "at", "sha256_after"} <= set(row)
    assert row["offer"] == "O1" and row["key_path"] == ["autoCompactWindow"]
    assert row["old"] == "<absent>" and row["new"] == 335000
    assert row["sha256_after"] == changes._sha(settings.read_bytes())


def test_the_old_value_is_recorded(settings):
    _write(settings, '{\n  "autoCompactWindow": 900000\n}\n')
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    assert rec["old"] == 900000 and rec["old_present"] is True


def test_applying_the_value_that_is_there_changes_nothing(settings):
    _write(settings, '{\n  "autoCompactWindow": 335000\n}\n')
    with pytest.raises(changes.ChangeError, match="already"):
        changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)


def test_undo_of_an_untouched_file_is_byte_identical_even_for_odd_formatting(settings):
    original = '{"zeta":1,   "model" : "opus",\n\t"nested":{"a":[1,2]}}'      # nothing like json.dumps output
    _write(settings, original)
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    assert settings.read_text() != original
    changes.revert(rec)
    assert settings.read_bytes() == original.encode()


def test_undo_of_a_file_teyla_created_removes_it(settings):
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    assert json.loads(settings.read_text()) == {"autoCompactWindow": 335000}
    changes.revert(rec)
    assert not settings.exists()


def test_undo_after_an_unrelated_later_edit_keeps_that_edit(settings):
    _write(settings, ORIGINAL)
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    data = json.loads(settings.read_text())
    data["theme"] = "dark"                                  # the user edits something else afterwards
    data["model"] = "sonnet"
    settings.write_text(json.dumps(data, indent=2) + "\n")
    changes.revert(rec)
    after = json.loads(settings.read_text())
    assert "autoCompactWindow" not in after
    assert after["theme"] == "dark" and after["model"] == "sonnet"
    assert list(after) == ["zeta", "model", "permissions", "alpha", "theme"]


def test_undo_puts_back_a_previous_value_in_place(settings):
    _write(settings, '{\n  "a": 1,\n  "autoCompactWindow": 900000,\n  "z": 2\n}\n')
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    data = json.loads(settings.read_text())
    data["z"] = 3
    settings.write_text(json.dumps(data, indent=2) + "\n")
    changes.revert(rec)
    after = json.loads(settings.read_text())
    assert after == {"a": 1, "autoCompactWindow": 900000, "z": 3} and list(after) == ["a", "autoCompactWindow", "z"]


def test_undo_is_refused_when_the_key_changed_and_shows_both_values(settings):
    _write(settings, ORIGINAL)
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    data = json.loads(settings.read_text())
    data["autoCompactWindow"] = 500000
    settings.write_text(json.dumps(data, indent=2) + "\n")
    with pytest.raises(changes.ChangeError) as e:
        changes.revert(rec)
    assert "500000" in str(e.value) and "335000" in str(e.value) and "--force" in str(e.value)
    assert json.loads(settings.read_text())["autoCompactWindow"] == 500000       # untouched
    changes.revert(rec, force=True)
    assert "autoCompactWindow" not in json.loads(settings.read_text())
    assert changes.load_log()[-1]["forced"] is True


def test_undo_of_a_removed_key_is_refused_without_force_and_a_no_op_with_it(settings):
    _write(settings, ORIGINAL)
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    settings.write_text(ORIGINAL)                                                # the user dropped the key
    with pytest.raises(changes.ChangeError):
        changes.revert(rec)
    assert changes.revert(rec, force=True) == [f"autoCompactWindow is already absent in {settings}; nothing to revert."]


def test_a_nested_key_creates_and_prunes_only_what_teyla_made(settings):
    _write(settings, '{\n  "a": 1\n}\n')
    rec = changes.apply_json("O2", settings, ["env", "CLAUDE_CODE_SUBAGENT_MODEL"], "sonnet")
    assert json.loads(settings.read_text())["env"] == {"CLAUDE_CODE_SUBAGENT_MODEL": "sonnet"}
    data = json.loads(settings.read_text())
    data["a"] = 2
    settings.write_text(json.dumps(data, indent=2) + "\n")
    changes.revert(rec)
    assert json.loads(settings.read_text()) == {"a": 2}                          # the env object Teyla made is gone

    _write(settings, '{\n  "env": {\n    "FOO": "1"\n  }\n}\n')
    rec = changes.apply_json("O2", settings, ["env", "CLAUDE_CODE_SUBAGENT_MODEL"], "sonnet")
    data = json.loads(settings.read_text())
    data["x"] = 1
    settings.write_text(json.dumps(data, indent=2) + "\n")
    changes.revert(rec)
    assert json.loads(settings.read_text()) == {"env": {"FOO": "1"}, "x": 1}     # the user's env stays


def test_a_symlinked_settings_file_is_edited_at_its_target(tmp_path, settings):
    target = tmp_path / "dotfiles" / "settings.json"
    _write(target, ORIGINAL)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.symlink_to(target)
    changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    assert settings.is_symlink() and "autoCompactWindow" in target.read_text()


def test_the_file_mode_survives_the_atomic_write(settings):
    _write(settings, ORIGINAL)
    settings.chmod(0o640)
    changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    assert stat.S_IMODE(settings.stat().st_mode) == 0o640
    assert [p.name for p in settings.parent.iterdir() if "tmp" in p.name] == []


def test_resolve_by_change_id_and_by_offer_id_and_double_undo(settings):
    _write(settings, ORIGINAL)
    rec = changes.apply_json("O1", settings, ["autoCompactWindow"], 335000)
    assert [c["id"] for c in changes.resolve(rec["id"])] == [rec["id"]]
    assert [c["id"] for c in changes.resolve("o1")] == [rec["id"]]
    changes.revert(changes.resolve("O1")[0])
    assert changes.resolve("O1") == []                        # undone changes are not active
    assert changes.changes()[0]["undone"]
    with pytest.raises(changes.ChangeError, match="already undone"):
        changes.revert(rec)


# --- TOML ---------------------------------------------------------------------------------------

CODEX = """# my codex
model = "gpt-6.1-sol"
model_reasoning_effort = "high"   # thinking time

[profiles.fast]
model_reasoning_effort = "low"
"""


def test_toml_edit_changes_one_line_and_keeps_everything_else(tmp_path):
    p = tmp_path / "config.toml"
    _write(p, CODEX)
    rec = changes.apply_toml("O4", p, "model_reasoning_effort", "medium")
    assert p.read_text() == CODEX.replace('"high"   # thinking', '"medium"   # thinking')
    assert rec["old"] == "high"


def test_toml_undo_untouched_is_byte_identical_and_after_an_edit_keeps_the_edit(tmp_path):
    p = tmp_path / "config.toml"
    _write(p, CODEX)
    rec = changes.apply_toml("O4", p, "model_reasoning_effort", "medium")
    changes.revert(rec)
    assert p.read_text() == CODEX

    rec = changes.apply_toml("O4", p, "model_reasoning_effort", "medium")
    p.write_text(p.read_text().replace('model = "gpt-6.1-sol"', 'model = "gpt-6.1-sol"\napproval = "never"'))
    changes.revert(rec)
    text = p.read_text()
    assert 'model_reasoning_effort = "high"   # thinking time' in text and 'approval = "never"' in text
    assert '[profiles.fast]\nmodel_reasoning_effort = "low"' in text


def test_toml_refuses_a_file_that_does_not_parse(tmp_path):
    p = tmp_path / "config.toml"
    _write(p, "model = \n")
    with pytest.raises(changes.ChangeError, match="not valid TOML"):
        changes.apply_toml("O4", p, "model_reasoning_effort", "medium")


def test_toml_adds_a_missing_key_above_the_first_table_and_undo_removes_it(tmp_path):
    p = tmp_path / "config.toml"
    src = 'model = "x"\n\n[profiles.a]\nk = 1\n'
    _write(p, src)
    rec = changes.apply_toml("O4", p, "model_reasoning_effort", "medium")
    import tomllib
    d = tomllib.loads(p.read_text())
    assert d["model_reasoning_effort"] == "medium" and d["profiles"]["a"]["k"] == 1
    p.write_text(p.read_text() + "tail = 1\n")
    changes.revert(rec)
    assert tomllib.loads(p.read_text()) == {"model": "x", "profiles": {"a": {"k": 1, "tail": 1}}}


# --- a file Teyla creates -------------------------------------------------------------------------

def test_apply_file_never_overwrites_and_undo_asks_before_deleting_an_edited_file(tmp_path):
    p = tmp_path / "agents" / "scout.md"
    rec = changes.apply_file("O3", p, "scout\n")
    assert p.read_text() == "scout\n"
    with pytest.raises(changes.ChangeError, match="already exists"):
        changes.apply_file("O3", p, "other\n")
    p.write_text("edited\n")
    with pytest.raises(changes.ChangeError, match="--force"):
        changes.revert(rec)
    changes.revert(rec, force=True)
    assert not p.exists()


# --- a piece (an existing sync) ---------------------------------------------------------------------

def test_apply_piece_logs_what_it_created_and_undo_removes_only_that(fake_home, monkeypatch):
    from teyla import policy
    (fake_home.home / ".codex").mkdir()
    (fake_home.home / ".agents").mkdir()
    (fake_home.home / ".agents" / "POLICY.md").write_text("# policy\n\n## 1. rules\n\ntext\n")
    rec, lines = changes.apply_piece("O5", "policy", lambda: policy.sync(), fake_home.home)
    agents = fake_home.home / ".codex" / "AGENTS.md"
    assert agents.exists() or agents.is_symlink()
    assert rec["created"] and all(t.startswith(str(fake_home.home)) for _v, t in rec["created"])
    out = changes.revert(rec)
    assert not agents.exists() and not agents.is_symlink() and out
    assert (fake_home.home / ".agents" / "POLICY.md").exists()          # the policy file is the user's


def test_a_piece_that_was_already_in_place_undoes_to_nothing(fake_home):
    rec, _ = changes.apply_piece("O6", "hooks", lambda: ["in sync"], fake_home.home)
    assert rec["created"] == []
    assert "nothing to remove" in changes.revert(rec)[0]


# --- a piece: what it overwrites is backed up, and undo takes back only what it wrote -----------------

def _hooks_sync(home):
    from teyla import harness
    return lambda: harness.sync(home=home)


def test_a_piece_backs_up_a_file_it_overwrites_and_undo_restores_it_byte_for_byte(fake_home):
    grok = fake_home.home / ".grok" / "hooks"
    grok.mkdir(parents=True)
    mine = b'{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "/my/own/handler.sh"}]}]}}\n'
    (grok / "teyla.json").write_bytes(mine)
    rec, _ = changes.apply_piece("O6", "hooks", _hooks_sync(fake_home.home), fake_home.home)
    row = next(f for f in rec["files"] if f["path"].endswith(".grok/hooks/teyla.json"))
    assert row["op"] == "modified"
    assert row["sha_before"] == changes._sha(mine) and row["sha_after"] != row["sha_before"]
    bak = pathlib.Path(row["backup"])
    assert bak.read_bytes() == mine and ".teyla-bak-" in bak.name
    assert stat.S_IMODE(bak.stat().st_mode) == 0o600
    assert b"/my/own/handler.sh" not in (grok / "teyla.json").read_bytes()      # the sync did overwrite it
    changes.revert(rec)
    assert (grok / "teyla.json").read_bytes() == mine


def test_undo_keeps_a_file_edited_after_the_apply_and_a_file_the_user_added(fake_home):
    home = fake_home.home
    (home / ".cursor").mkdir()
    rec, _ = changes.apply_piece("O6", "hooks", _hooks_sync(home), home)
    made = [f for f in rec["files"] if f["op"] == "created" and f["path"].startswith(str(home / ".cursor" / "skills"))]
    assert made, "the sync should have created Cursor skills"
    edited = pathlib.Path(made[0]["path"])
    edited.write_text(edited.read_text() + "\nmy own note\n")
    mine = edited.parent / "personal.md"
    mine.write_text("keep me\n")
    out = "\n".join(changes.revert(rec))
    assert edited.exists() and "my own note" in edited.read_text()
    assert mine.read_text() == "keep me\n"
    assert edited.parent.is_dir()                                       # not empty, so not removed
    assert "Left in place" in out and str(edited) in out
    others = [pathlib.Path(f["path"]) for f in made[1:]]
    assert all(not p.exists() for p in others if p.parent != edited.parent)   # untouched files did go


def test_undo_removes_a_directory_only_when_it_is_empty(fake_home):
    home = fake_home.home
    (home / ".cursor").mkdir()
    rec, _ = changes.apply_piece("O6", "hooks", _hooks_sync(home), home)
    assert rec["dirs"]
    stray = pathlib.Path(rec["dirs"][0]) / "notes.txt"                 # the deepest directory it made
    stray.write_text("mine\n")
    changes.revert(rec)
    assert stray.read_text() == "mine\n"


def test_a_hook_added_next_to_an_existing_teyla_hook_is_recorded_and_undone(fake_home):
    from teyla import harness
    home = fake_home.home
    codex = home / ".codex"
    codex.mkdir()
    old = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command":
           f"{harness.HOOKS_DIR / 'session-start.sh'} --codex", "timeout": 5}]}]}}
    mine = {"type": "command", "command": "/my/own/handler.sh"}
    old["hooks"]["Stop"] = [{"hooks": [mine]}]
    (codex / "hooks.json").write_text(json.dumps(old, indent=2) + "\n")
    rec, _ = changes.apply_piece("O6", "hooks", _hooks_sync(home), home)
    added = [h for h in rec["hook_entries"] if h["file"].endswith(".codex/hooks.json")]
    assert added and {h["event"] for h in added} >= {"UserPromptSubmit"}
    # The user edits the file after the apply, so an exact restore is no longer possible.
    d = json.loads((codex / "hooks.json").read_text())
    d["hooks"]["PostToolUse"] = [{"hooks": [{"type": "command", "command": "/another.sh"}]}]
    (codex / "hooks.json").write_text(json.dumps(d, indent=2) + "\n")
    changes.revert(rec)
    left = json.loads((codex / "hooks.json").read_text())
    cmds = [h["command"] for g in sum(left["hooks"].values(), []) for h in g.get("hooks", [])]
    assert f"{harness.HOOKS_DIR / 'session-start.sh'} --codex" in cmds         # it was there before the apply
    assert "/my/own/handler.sh" in cmds and "/another.sh" in cmds
    assert not any("capture-correction.sh" in c or "machine-guard.sh" in c for c in cmds)


def test_force_restores_the_old_value_of_a_key_the_user_removed(settings):
    _write(settings, '{"model": "opus", "effort": "high"}\n')
    rec = changes.apply_json("O4", settings, ["effort"], "medium")
    _write(settings, '{"model": "opus"}\n')                               # the user deleted the key
    with pytest.raises(changes.ChangeError):
        changes.revert(rec)
    changes.revert(rec, force=True)
    assert json.loads(settings.read_text()) == {"model": "opus", "effort": "high"}
    assert changes.load_log()[-1].get("undo_of") == rec["id"]


def test_force_restores_the_old_value_of_a_toml_key_the_user_removed(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('model = "x"\nmodel_reasoning_effort = "high"\n')
    rec = changes.apply_toml("O4", p, "model_reasoning_effort", "medium")
    p.write_text('model = "x"\n')
    changes.revert(rec, force=True)
    assert 'model_reasoning_effort = "high"' in p.read_text()

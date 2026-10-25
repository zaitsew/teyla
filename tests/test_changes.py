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


# --- a command (an existing sync, run as it is) ---------------------------------------------------

def test_apply_command_logs_the_command_and_undo_refuses_with_the_reason(fake_home):
    ran = []
    rec, lines = changes.apply_command("O6", "teyla harness sync", lambda: ran.append(1) or ["synced"],
                                       "Run `teyla uninstall`.")
    assert ran == [1] and lines == ["synced"]
    assert rec["kind"] == "command" and rec["command"] == "teyla harness sync" and rec["offer"] == "O6" and rec["at"]
    assert "files" not in rec
    with pytest.raises(changes.ChangeError, match="Teyla's sync owns these files; its uninstall removes them") as e:
        changes.revert(rec)
    assert "teyla uninstall" in str(e.value)
    assert changes.changes()[0]["undone"] is None                  # nothing was undone, nothing was logged as undone


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

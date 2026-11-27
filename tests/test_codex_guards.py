"""Codex runs the same credential and parity guards as Claude Code. Its one edit tool is `apply_patch`: the
hook payload has `tool_name: "apply_patch"` and the whole patch in `tool_input.command`. These tests feed that
shape (generic paths only) to `teyla.hook_paths`, `teyla.leak_guard`, `teyla.platform_hook` and the two shell
wrappers, and pin the PreToolUse wiring of `teyla harness sync` for Codex and Grok."""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from teyla import harness, hook_paths, leak_guard, parity, platform_hook

ROOT = pathlib.Path(__file__).resolve().parent.parent
LEAK_HOOK = ROOT / "plugin" / "hooks" / "leak-guard.sh"
PLATFORM_HOOK = ROOT / "plugin" / "hooks" / "platform-gate.sh"
SRC = ROOT / "src"

TOML = """[product]
name = "widget"

[productize]
primary = "macos"
platforms = ["macos", "ios"]

[productize.triggers]
ios = "2026-10-26: the owner asked for an iOS version"

[productize.paths]
macos = ["apps/mac/**"]
ios = ["apps/ios/**"]
"""


def patch(*sections: str) -> str:
    return "*** Begin Patch\n" + "".join(sections) + "*** End Patch\n"


def update(path: str, new: str = "x") -> str:
    return f"*** Update File: {path}\n@@\n-old\n+{new}\n"


def codex_payload(text: str, cwd: pathlib.Path, tool: str = "apply_patch") -> dict:
    return {"session_id": "s", "turn_id": "t", "cwd": str(cwd), "hook_event_name": "PreToolUse", "model": "m",
            "permission_mode": "default", "tool_name": tool, "tool_use_id": "u", "transcript_path": None,
            "tool_input": {"command": text}}


# --- the patch adapter --------------------------------------------------------------------------

def test_patch_paths_reads_add_update_delete_and_move():
    text = patch("*** Add File: new/a.txt\n+hi\n", update("src/b.py"), "*** Delete File: old/c.txt\n",
                 "*** Update File: d.txt\n*** Move to: moved/e.txt\n@@\n-a\n+b\n")
    assert hook_paths.patch_paths(text) == ["new/a.txt", "src/b.py", "old/c.txt", "d.txt", "moved/e.txt"]


def test_patch_paths_keeps_spaces_drops_repeats_and_ignores_body_lines():
    text = patch(update("dir/with space.txt"), update("dir/with space.txt"),
                 "*** Add File: z.txt\n+*** Update File: not/a/header\n")
    assert hook_paths.patch_paths(text) == ["dir/with space.txt", "z.txt"]


@pytest.mark.parametrize("bad", ["", None, "no headers here\n", 7])
def test_patch_paths_of_nothing_is_empty(bad):
    assert hook_paths.patch_paths(bad) == []


def test_edit_paths_reads_both_payload_shapes():
    assert hook_paths.edit_paths({"tool_name": "apply_patch", "tool_input": {"command": patch(update("a.txt"))}}) == ["a.txt"]
    assert hook_paths.edit_paths({"tool_name": "Edit", "tool_input": {"file_path": "/r/b.txt"}}) == ["/r/b.txt"]
    assert hook_paths.edit_paths({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "n.ipynb"}}) == ["n.ipynb"]
    assert hook_paths.edit_paths({"tool_name": "search_replace", "tool_input": {"path": "g.txt"}}) == ["g.txt"]
    assert hook_paths.edit_paths({"tool_name": "Bash", "tool_input": {"command": "ls"}}) == []
    assert hook_paths.edit_paths({"tool_name": "apply_patch", "tool_input": None}) == []


# --- the credential guard on Codex input --------------------------------------------------------

@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    (home / ".aws").mkdir(parents=True)
    work = tmp_path / "work"
    (work / ".git").mkdir(parents=True)
    return {"HOME": str(home), "TEYLA_HOME": str(home / ".teyla")}, home, work


def test_leak_guard_refuses_a_patch_that_touches_a_credential(env):
    e, home, work = env
    for section in (update(f"{home}/.aws/credentials"), f"*** Add File: {home}/.ssh/id_ed25519\n+k\n",
                    "*** Delete File: ../home/.aws/credentials\n"):
        lines = leak_guard.decide(codex_payload(patch(update("ok.txt"), section), work), e)
        assert lines and "credential" in lines[0], section


def test_leak_guard_passes_an_ordinary_patch_and_does_not_read_it_as_a_shell_command(env):
    e, _, work = env
    # the patch body holds words a shell scan would call a publication; it is file text, not a command
    text = patch(update("notes.md", "gh pr create --body 'x' && git push --no-verify"))
    assert leak_guard.decide(codex_payload(text, work), e) is None


def test_leak_guard_still_sends_codex_shell_calls_down_the_bash_path(env):
    e, home, work = env
    p = codex_payload(f"cat {home}/.aws/credentials", work, tool="Bash")
    assert leak_guard.decide(p, e)


def test_leak_guard_reads_a_groks_path_key(env):
    e, home, work = env
    p = {"cwd": str(work), "tool_name": "read_file", "tool_input": {"path": f"{home}/.aws/credentials"}}
    assert leak_guard.decide(p, e)


def run_script(script, payload: dict, tmp_path, home, extra=None, args=()):
    wrapper = tmp_path / "py"
    wrapper.write_text(f'#!/bin/sh\n[ "$1" = -I ] || exit 3\nshift\nPYTHONPATH="{SRC}" exec "{sys.executable}" "$@"\n')
    wrapper.chmod(0o755)
    e = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TEYLA_HOME": str(home / ".teyla"), "TEYLA_PYTHON": str(wrapper),
         **(extra or {})}
    return subprocess.run(["/bin/sh", str(script), *args], input=json.dumps(payload), capture_output=True, text=True,
                          env=e, timeout=60)


def test_the_leak_guard_script_refuses_a_codex_patch_on_a_credential(env, tmp_path):
    _, home, work = env
    r = run_script(LEAK_HOOK, codex_payload(patch(update(f"{home}/.aws/credentials")), work), tmp_path, home)
    assert r.returncode == 2 and "credential" in r.stderr, r
    ok = run_script(LEAK_HOOK, codex_payload(patch(update("README.md")), work), tmp_path, home)
    assert ok.returncode == 0, ok


# --- the parity gate on Codex input -------------------------------------------------------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("TEYLA_PLATFORM_LABEL", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "teyla.toml").write_text(TOML)
    parity.save(root, {"train": {"ios": {"state": "closed", "base": "abc"}}})
    return root


def test_platform_gate_refuses_a_patch_that_edits_a_closed_secondary(repo):
    text = patch(update("apps/mac/A.swift"), update("apps/ios/App.swift"))
    code, msg = platform_hook.decide(codex_payload(text, repo))
    assert code == 2 and msg.startswith("platform gate: ios is closed in widget")


def test_platform_gate_checks_every_file_of_a_move_and_resolves_relative_paths(repo):
    text = patch("*** Update File: apps/mac/A.swift\n*** Move to: apps/ios/A.swift\n@@\n-a\n+b\n")
    assert platform_hook.decide(codex_payload(text, repo))[0] == 2
    assert platform_hook.decide(codex_payload(patch(update("apps/mac/A.swift"), update("docs/x.md")), repo)) == (0, "")
    assert platform_hook.decide(codex_payload(patch(update(str(repo / "apps/ios/App.swift"))), pathlib.Path("/")))[0] == 2


def test_the_platform_gate_script_refuses_a_codex_patch_and_passes_the_primary(repo, tmp_path):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    bad = run_script(PLATFORM_HOOK, codex_payload(patch(update("apps/ios/App.swift")), repo), tmp_path, home)
    assert bad.returncode == 2 and "ios is closed in widget" in bad.stderr, bad
    good = run_script(PLATFORM_HOOK, codex_payload(patch(update("apps/mac/A.swift")), repo), tmp_path, home)
    assert good.returncode == 0 and good.stderr == ""


def test_the_platform_gate_script_reads_a_groks_path_key(repo, tmp_path):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    payload = {"cwd": str(repo), "tool_name": "search_replace", "tool_input": {"path": "apps/ios/App.swift"}}
    assert run_script(PLATFORM_HOOK, payload, tmp_path, home).returncode == 2


# --- the wiring ---------------------------------------------------------------------------------

def _pre_tool_use_matchers(groups) -> dict[str, str | None]:
    return {harness._script_of(h["command"]): g.get("matcher") for g in groups for h in g["hooks"]}


def test_codex_pre_tool_use_wires_the_guards_with_codex_tool_names():
    m = _pre_tool_use_matchers(harness._codex_hooks(None)["hooks"]["PreToolUse"])
    assert m["leak-guard.sh"] == "Bash|apply_patch"
    assert m["platform-gate.sh"] == "apply_patch"
    assert m["pre-tool-use.sh"] is None
    assert m["machine-guard.sh"] == m["orchestrator-gate.sh"] == "Bash"


def test_grok_pre_tool_use_wires_the_guards_with_claude_aliases():
    groups = harness._grok_hooks()["hooks"]["PreToolUse"]
    m = _pre_tool_use_matchers(groups)
    assert m["leak-guard.sh"] == "Bash|Read|Edit|Write|MultiEdit"
    assert m["platform-gate.sh"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert any(h["command"].endswith("leak-guard.sh --grok") for g in groups for h in g["hooks"])

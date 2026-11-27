"""`teyla.design_hint`: the prompt hook that points the model at drawings first (POLICY 16, 2026-11-27)."""
import io
import json
import pathlib
import subprocess
import sys

import pytest

from teyla import design_hint, harness

ROOT = pathlib.Path(__file__).resolve().parent.parent

DESIGN = [
    "Draw a full iOS version of the home screen with bottom navigation",
    "Make a mockup of the settings page",
    "I need a redesign of onboarding",
    "Give me two concepts for the app screen",
    "wireframes for the checkout flow please",
    "Sketch the new profile screen",
    "нарисуй экран настроек",
    "Сделай макет главной и редизайн онбординга",
    "dibuja la pantalla de inicio",
    "Necesito un boceto del flujo",
    "Draw a mockup of the SwiftUI screen for review",
    "draw a full iOS version with bottom nav",
]
IMPLEMENT = [
    "Redesign the home screen and implement it, then ship to TestFlight",
    "Mock up the settings page and build it in SwiftUI",
    "Сделай редизайн и запусти в разработку",
    "Haz un rediseño y implementa la pantalla",
]
NOT_DESIGN = [
    "Fix the crash in the login view model",
    "This is only a proof of concept for the parser",
    "Draw the chart with Canvas in the existing code",
    "Run the tests and push the branch",
    "Add a button to the Mac app",
    "исправь падение при запуске",
    "arregla el error de la sincronización",
    "What is the design token for spacing?",
    "",
]


@pytest.mark.parametrize("prompt", DESIGN)
def test_design_request_gets_the_drawings_first_hint(prompt):
    assert design_hint.hint(prompt) == design_hint.DESIGN_ONLY


@pytest.mark.parametrize("prompt", IMPLEMENT)
def test_a_design_request_that_asks_to_implement_authorizes_it(prompt):
    assert design_hint.hint(prompt) == design_hint.IMPLEMENT_OK


@pytest.mark.parametrize("prompt", NOT_DESIGN)
def test_other_prompts_get_nothing(prompt):
    assert design_hint.hint(prompt) == ""


@pytest.mark.parametrize("prompt", ["Redesign the screen, don't build anything", "Mockup of home, no code yet",
                                    "Сделай макет, не реализуй пока"])
def test_a_negated_implement_word_stays_design_only(prompt):
    assert design_hint.hint(prompt) == design_hint.DESIGN_ONLY


def test_hints_are_at_most_three_lines():
    for text in (design_hint.DESIGN_ONLY, design_hint.IMPLEMENT_OK):
        assert len(text.splitlines()) <= 3


def test_hook_main_prints_for_a_design_prompt_and_is_silent_otherwise(capsys, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    design_hint.hook_main(io.StringIO(json.dumps({"prompt": "Draw the home screen mockup"})))
    assert capsys.readouterr().out == design_hint.DESIGN_ONLY + "\n"
    design_hint.hook_main(io.StringIO(json.dumps({"prompt": "fix the bug"})))
    design_hint.hook_main(io.StringIO("not json"))
    assert capsys.readouterr().out == ""


def test_hook_main_skips_headless_runs(capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-cli")
    design_hint.hook_main(io.StringIO(json.dumps({"prompt": "Draw the home screen mockup"})))
    assert capsys.readouterr().out == ""


def test_the_script_prints_the_hint_through_the_installed_python(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TEYLA_PYTHON": sys.executable,
           "PYTHONPATH": str(ROOT / "src")}
    run = lambda prompt: subprocess.run(["sh", str(ROOT / "plugin" / "hooks" / "design-hint.sh")],
                                        input=json.dumps({"prompt": prompt}), capture_output=True, text=True, env=env, timeout=30)
    r = run("нарисуй экран профиля")
    assert r.returncode == 0 and r.stdout == design_hint.DESIGN_ONLY + "\n" and r.stderr == ""
    r = run("fix the bug")
    assert (r.returncode, r.stdout) == (0, "")


def test_the_hook_is_wired_for_claude_codex_and_grok_and_synced():
    assert "design-hint.sh" in harness.HOOK_SCRIPTS
    cfg = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())
    assert any("design-hint.sh" in h["command"] for g in cfg["hooks"]["UserPromptSubmit"] for h in g["hooks"])
    assert any("design-hint.sh" in h["command"] for g in harness._codex_hooks(None)["hooks"]["UserPromptSubmit"] for h in g["hooks"])
    assert any("design-hint.sh" in h["command"] for g in harness._grok_hooks()["hooks"]["UserPromptSubmit"] for h in g["hooks"])


def test_the_taste_skill_is_synced_to_codex_without_claude_only_fields():
    assert "teyla-taste" in harness.skill_names()
    text = harness.render_skill("taste", "codex")
    assert text.startswith("---\nname: teyla-taste\n") and "argument-hint" not in text.split("---")[1]
    assert not any("gstack" in n for n in harness.skill_names())


def test_standard_states_the_rule():
    text = (ROOT / "templates" / "design" / "STANDARD.md").read_text()
    assert "Drawings first" in text and "2026-11-27" in text

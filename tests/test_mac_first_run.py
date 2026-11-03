"""The Mac app hardcodes one sentence and one command; these tests fail when they drift from the CLI."""
import json
import pathlib
import re

import teyla

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAC = ROOT / "apps" / "mac"


def swift_string(source: str, name: str) -> str:
    m = re.search(rf'static let {name} = "((?:[^"\\]|\\.)*)"', source)
    assert m, f"{name} not found"
    return json.loads(f'"{m.group(1)}"')


def test_the_welcome_promise_is_the_cli_promise():
    first_run = (MAC / "Teyla" / "Core" / "FirstRun.swift").read_text()
    assert swift_string(first_run, "promise") == teyla.PROMISE


def test_the_install_command_is_the_readme_command():
    binary = (MAC / "Teyla" / "Core" / "TeylaBinary.swift").read_text()
    command = swift_string(binary, "installCommand")
    assert command == "uv tool install --python 3.12 git+https://github.com/zaitsew/teyla"
    assert command in (ROOT / "README.md").read_text()


def test_the_mac_fixtures_are_valid_json_of_the_shapes_the_app_decodes():
    fixtures = MAC / "TeylaTests" / "Fixtures"
    start = json.loads((fixtures / "start.v1.json").read_text())
    assert set(start) >= {"summary_text", "diagnosis", "offers"}
    assert {o["id"] for o in start["offers"]} == {f"O{i}" for i in range(1, 8)}
    product = json.loads((fixtures / "product.v1.json").read_text())
    assert product["version"] == 1 and product["product"]["id"] == "sample-app"
    state = json.loads((fixtures / "state.sample.v2.json").read_text())
    assert state["version"] == 2 and any(p["registered"] for p in state["products"])


def _target_block(project: str, name: str) -> str:
    """The text of one target in apps/mac/project.yml (two-space keys under `targets:`)."""
    m = re.search(rf"^  {name}:\n(.*?)(?=^  \w[\w-]*:\n|^schemes:)", project, re.S | re.M)
    assert m, f"target {name} not found"
    return m.group(1)


def test_only_the_store_build_registers_the_pairing_link():
    project = (MAC / "project.yml").read_text()
    assert "CFBundleURLSchemes" in _target_block(project, "TeylaStore")
    assert "teyla-pair" in _target_block(project, "TeylaStore")
    for other in ("Teyla", "TeylaTests"):
        assert "teyla-pair" not in _target_block(project, other), f"{other} must not register teyla-pair"
        assert "CFBundleURLTypes" not in _target_block(project, other)


def test_the_store_build_number_moved_past_the_testflight_build():
    project = (MAC / "project.yml").read_text()
    m = re.search(r"CURRENT_PROJECT_VERSION: (\d+)", _target_block(project, "TeylaStore"))
    assert m and int(m.group(1)) >= 2


def test_the_store_setup_commands_are_the_install_command_and_the_connect_command():
    views = (MAC / "Teyla" / "Store" / "StoreViews.swift").read_text()
    binary = (MAC / "Teyla" / "Core" / "TeylaBinary.swift").read_text()
    assert swift_string(views, "install") == swift_string(binary, "installCommand")
    assert swift_string(views, "connect") == "teyla relay connect"
    assert 'static let oneCommand = "\\(install) && \\(connect)"' in views


def test_the_agent_prompt_and_the_review_notes_name_no_model_provider():
    views = (MAC / "Teyla" / "Store" / "StoreViews.swift").read_text()
    prompt = views[views.index("static let agentPrompt"):views.index("static let terminalBundleID")]
    notes = (ROOT / "apps" / "store" / "listing" / "macos" / "en-US" / "review_notes.txt").read_text()
    for text in (prompt, notes):
        for name in ("openai", "chatgpt", "claude", "anthropic", "gemini", "grok", "codex"):
            assert name not in text.lower(), name

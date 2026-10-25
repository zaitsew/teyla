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

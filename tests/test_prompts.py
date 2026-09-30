"""The paste-able prompts ship inside the package, and the kickoff follows the shipped copy —
never an unpinned `main` on GitHub, whose instructions can run ahead of the installed code."""
from __future__ import annotations

import pathlib
import re

from teyla import prompts_dir
from teyla.cli import main

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_prompt_lists_and_prints_the_shipped_prompts(capsys):
    assert main(["prompt"]) == 0
    assert "onboard" in capsys.readouterr().out.split()
    assert main(["prompt", "onboard"]) == 0
    assert capsys.readouterr().out == (prompts_dir() / "onboard.md").read_text()
    assert main(["prompt", "no-such-prompt"]) == 1


def test_prompts_are_packaged_in_the_wheel():
    assert '"prompts" = "teyla/prompts"' in (ROOT / "pyproject.toml").read_text()


def test_no_prompt_tells_an_agent_to_follow_instructions_from_main():
    for p in (ROOT / "prompts").glob("*.md"):
        text = p.read_text()
        assert not re.search(r"raw\.githubusercontent\.com/zaitsew/teyla/main/prompts", text), p.name
        assert not re.search(r"(?i)follow https://[^\s]*/main/prompts", text), p.name


def test_onboard_points_at_uninstall_and_lists_the_network_calls():
    text = (ROOT / "prompts" / "onboard.md").read_text()
    assert "teyla uninstall --dry" in text
    assert "nothing leaves this machine" not in text.lower()
    for call in ("api.github.com", "teyla update", "models.dev", "LaunchAgent"):
        assert call in text

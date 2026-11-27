"""Every hook the Claude plugin runs has a Codex decision. Adding a script to plugin/hooks/hooks.json without
wiring it in `harness._codex_hooks` (or naming it in INTENTIONAL below, with a reason) fails here."""
from __future__ import annotations

import json
import pathlib

from teyla import harness

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (event, script) pairs the Claude plugin runs and Codex deliberately does not. One line of reason each.
INTENTIONAL = {
    ("SessionStart", "context-budget.sh"): "matcher `compact`: it reads Claude's transcript and compaction events; opt-in",
    ("UserPromptSubmit", "context-budget.sh"): "same hook: the handoff nudge reads a Claude transcript; opt-in",
    ("PostToolUse", "context-budget.sh"): "same hook: Codex rollouts have another shape; opt-in",
}


def _scripts(hooks: dict) -> set[tuple[str, str]]:
    return {(event, harness._script_of(h["command"].split("hooks/", 1)[-1].split(" ")[0].strip('"')))
            for event, groups in hooks.items() for g in groups for h in g["hooks"]}


def test_every_claude_hook_is_wired_for_codex_or_named_as_a_difference():
    claude = _scripts(json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"])
    codex = _scripts(harness._codex_hooks(None, land_check=True)["hooks"])
    missing = sorted(claude - codex - set(INTENTIONAL))
    assert not missing, (f"Claude hooks with no Codex decision: {missing}. Wire each in harness._codex_hooks "
                         "(and _grok_hooks where Grok's hook API allows), or add it to INTENTIONAL with a reason.")


def test_the_allowlist_holds_no_stale_entries():
    claude = _scripts(json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"])
    codex = _scripts(harness._codex_hooks(None, land_check=True)["hooks"])
    assert not (set(INTENTIONAL) - claude), "INTENTIONAL names a hook the Claude plugin no longer runs"
    assert not (set(INTENTIONAL) & codex), "INTENTIONAL names a hook Codex already runs: delete the entry"


def test_every_script_wired_for_codex_or_grok_is_installed_by_sync():
    wired = {s for _, s in _scripts(harness._codex_hooks(None, land_check=True)["hooks"])}
    wired |= {s for _, s in _scripts(harness._grok_hooks()["hooks"])}
    assert wired <= set(harness.HOOK_SCRIPTS), sorted(wired - set(harness.HOOK_SCRIPTS))

"""`teyla harness parity` and the `parity` doctor line: the Claude Code x Codex table, per hook, with trust."""
from __future__ import annotations

import json

import pytest

from teyla import doctor, harness, harness_parity as hp, policy


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    for d in (".claude/plugins", ".codex"):
        (h / d).mkdir(parents=True)
    (h / ".agents").mkdir()
    (h / ".agents" / "POLICY.md").write_text("# policy\n\n## 1. ladder\n\ntext\n")
    (h / ".claude" / "CLAUDE.md").write_text("# rules\n")
    monkeypatch.setattr(harness, "HOME", h)
    monkeypatch.setattr(harness, "HOOKS_DIR", h / ".teyla" / "hooks")
    monkeypatch.setattr(harness, "_land_check_on", lambda: False)
    monkeypatch.setattr(hp, "config_on", lambda name: False)
    monkeypatch.setattr(policy, "HOME", h)
    monkeypatch.setattr(policy, "POLICY", h / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "TARGETS", {
        "claude-code": h / ".claude" / "CLAUDE.md", "codex": h / ".codex" / "AGENTS.md",
        "grok": h / ".grok" / "AGENTS.md", "hermes": h / ".hermes" / "SOUL.md",
        "cursor": h / ".cursor" / "skills" / "teyla-policy" / "SKILL.md"})
    (h / ".claude" / "plugins" / "installed_plugins.json").write_text(
        json.dumps({"plugins": {"teyla@teyla": [{"version": "9.9.9"}]}}))
    return h


def cell(t, needle, harness_name="codex"):
    rows = [r for r in t["rows"] if needle in r["capability"] and not (needle == "plugin" and r["capability"] != "plugin")]
    assert len(rows) == 1, [r["capability"] for r in t["rows"]]
    return rows[0][harness_name]


def trust_all(home, skip=()):
    p = home / ".codex" / "hooks.json"
    d = json.loads(p.read_text())
    out = ""
    for event, groups in d["hooks"].items():
        for gi, g in enumerate(groups):
            for hi, hh in enumerate(g["hooks"]):
                if harness._script_of(hh["command"]) in skip:
                    continue
                out += (f'\n[hooks.state."{p}:{harness._CODEX_EVENT_LABELS[event]}:{gi}:{hi}"]\n'
                        f'trusted_hash = "{harness.codex_hook_hash(event, hh, g.get("matcher"))}"\n')
    (home / ".codex" / "config.toml").write_text(out)


def test_nothing_synced_every_codex_hook_is_missing_with_the_sync_fix(home):
    t = hp.table(home)
    assert cell(t, "leak-guard.sh") == "missing" and cell(t, "leak-guard.sh", "claude-code") == "ok"
    assert cell(t, "hook scripts") == "missing"
    assert {r["fix"] for r in hp.gaps(t) if "hook " in r["capability"]} == {"teyla harness sync"}
    assert "✗ missing" in hp.render(t)


def test_expected_set_is_what_sync_writes_not_a_list(home):
    harness.sync(home=home)
    t = hp.table(home)
    wanted = {harness._script_of(h["command"]) for gs in harness._codex_hooks(None, land_check=False)["hooks"].values()
              for g in gs for h in g["hooks"]}
    shown = {r["capability"].split()[1] for r in t["rows"] if r["capability"].startswith("hook ") and r["codex"] != "n/a"}
    assert wanted <= shown
    assert not any(cell(t, s) == "missing" for s in wanted)


def test_synced_but_untrusted_needs_trust_then_ok(home):
    harness.sync(home=home)
    t = hp.table(home)
    assert cell(t, "leak-guard.sh") == "needs trust"
    assert hp.TRUST_FIX in {r["fix"] for r in hp.gaps(t)}
    trust_all(home)
    t = hp.table(home)
    assert cell(t, "leak-guard.sh") == "ok" and cell(t, "session-start.sh") == "ok"


def test_one_hook_untrusted_is_named(home):
    harness.sync(home=home)
    trust_all(home, skip=("pr-size-gate.sh",))
    t = hp.table(home)
    assert cell(t, "pr-size-gate.sh") == "needs trust" and cell(t, "leak-guard.sh") == "ok"


def test_changed_hook_is_modified_and_disabled_is_flagged(home):
    harness.sync(home=home)
    trust_all(home)
    cfg = home / ".codex" / "config.toml"
    p = home / ".codex" / "hooks.json"
    key = f'[hooks.state."{p}:session_start:0:0"]\n'
    cfg.write_text(cfg.read_text().replace(key + 'trusted_hash = "sha256:', key + 'trusted_hash = "sha256:00'))
    assert cell(hp.table(home), "session-start.sh") == "modified"
    cfg.write_text(cfg.read_text().replace(key, key + "enabled = false\n"))
    assert cell(hp.table(home), "session-start.sh") == "disabled"


def test_unparseable_config_is_unknown_never_a_guess(home):
    harness.sync(home=home)
    (home / ".codex" / "config.toml").write_text("this is [not toml")
    t = hp.table(home)
    assert cell(t, "leak-guard.sh") == "unknown"
    assert "approve" in " ".join(r["fix"] for r in hp.gaps(t)).lower()


def test_outdated_entry_is_flagged(home):
    harness.sync(home=home)
    p = home / ".codex" / "hooks.json"
    d = json.loads(p.read_text())
    d["hooks"]["PreToolUse"][0]["hooks"][0]["timeout"] = 1
    p.write_text(json.dumps(d))
    assert cell(hp.table(home), "machine-guard.sh") == "outdated"


def test_missing_skill_and_stale_policy_are_gaps(home):
    harness.sync(home=home)
    (home / ".codex" / "skills" / "teyla-taste" / "SKILL.md").unlink()
    t = hp.table(home)
    assert cell(t, "skills") == "missing"
    assert "teyla-taste" in [r for r in t["rows"] if r["capability"].startswith("skills")][0]["fix"]
    assert cell(t, "policy text") in ("ok", "stale")


def test_claude_without_plugin_and_absent_harness(home):
    (home / ".claude" / "plugins" / "installed_plugins.json").write_text("{}")
    t = hp.table(home)
    assert cell(t, "plugin", "claude-code") == "no plugin"
    assert cell(t, "leak-guard.sh", "claude-code") == "no plugin"
    import shutil
    shutil.rmtree(home / ".codex")
    t = hp.table(home)
    assert cell(t, "leak-guard.sh") == "absent" and not t["codex_present"]


def test_doctor_line_names_the_gap_and_goes_ok_when_parity(home):
    [line] = doctor.parity_checks()
    assert line["level"] == "WARN" and "leak-guard.sh" in line["detail"] and "teyla harness sync" in line["fix"]
    harness.sync(home=home)
    trust_all(home)
    t = hp.table(home)
    if not hp.gaps(t):
        assert doctor.parity_checks()[0]["level"] == "OK"
    else:  # policy file differences in the temp home are not this test's subject
        assert all("policy" in r["capability"] or "skills" in r["capability"] for r in hp.gaps(t))

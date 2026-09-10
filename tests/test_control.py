"""The control plane: manifest, run loop, gates, idempotency, kill switch, hook, promote.

Everything here runs against a throwaway product repo in tmp_path, with `TEYLA_HOME`
and `TEYLA_REPO_ROOTS` pointed away from the real machine — no launchctl, no `claude`,
no network. Routines use `command` steps precisely so the loop can be exercised end to
end without a model in it: the loop is the thing under test, and the loop is code.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess

import pytest

from teyla import control
from teyla.control import engine, grants as G, promote, rules as R, state as S, triggers
from teyla.control.manifest import ManifestError, load as load_manifest, parse_days, parse_capability

HOOK = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "hooks" / "pre-tool-use.sh"
SRC = pathlib.Path(__file__).resolve().parents[1] / "src"


# --- fixtures --------------------------------------------------------------------------

MANIFEST = """
[product]
name = "demo"

[[routine]]
name = "digest"
gate = "A"
idempotency = "date"
trigger = { type = "clock", at = "07:00", tz = "Europe/Madrid", days = "mon-fri" }
step = { kind = "command", run = "echo DRAFT-LINE-ONE; echo more" }
act  = { kind = "command", run = "echo ACTED > acted.txt; echo 'rm acted.txt' > \\"$TEYLA_UNDO\\"; echo done" }
capabilities = ["fs.write:runs/**", "shell:git push"]
caps = { max_minutes = 1, max_writes = 5, max_sends = 0 }

[[routine]]
name = "nightly"
kind = "launchd"
label = "com.demo.nightly"
every = "1d"
"""


@pytest.fixture()
def product(tmp_path, monkeypatch):
    """A product repo with a control-plane routine and a legacy one, plus an isolated
    ~/.teyla. Returns the repo path."""
    repos = tmp_path / "repos"
    repo = repos / "demo"
    repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(MANIFEST)
    (repo / ".claude" / "rules").mkdir(parents=True)
    (repo / ".claude" / "rules" / "tone.md").write_text(
        "---\nglobs: notes/**\n---\n\n- Open with a claim, not a question.\n"
    )
    (repo / ".claude" / "rules" / "always.md").write_text("- Never invent a number.\n")
    (repo / "AGENTS.md").write_text("# demo\n\n## Rules\n\n- Say what is unverified.\n\n## Other\n\nnope\n")
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "teyla-home"))
    monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    return repo


def cli(*argv) -> int:
    """Drive the commands through `register(sp)` exactly as cli.py will."""
    p = argparse.ArgumentParser(prog="teyla")
    sp = p.add_subparsers(dest="cmd", required=True)
    control.register(sp)
    args = p.parse_args(list(argv))
    return args.fn(args)


# --- 1. manifest parsing -----------------------------------------------------------------


def test_parses_control_and_leaves_legacy_alone(product):
    rs = load_manifest(product / "teyla.toml")
    assert [r.name for r in rs] == ["digest"], "a legacy routine must not appear as control-plane"
    r = rs[0]
    assert r.ref == "demo:digest"
    assert r.gate == "A"
    assert r.trigger.type == "clock" and r.trigger.at == "07:00"
    assert r.trigger.days == ("mon", "tue", "wed", "thu", "fri")
    assert r.step.kind == "command"
    assert r.act is not None
    assert r.caps["max_writes"] == 5
    assert r.caps["max_output_tokens"] == 200_000, "unset caps fall back to the defaults"
    assert r.launchd_label == "com.teyla.demo.digest"


def test_legacy_manifest_still_parses_unchanged(product):
    from teyla.routines import parse_manifest
    m = parse_manifest(product / "teyla.toml")
    assert {r["name"] for r in m["routines"]} == {"digest", "nightly"}
    control_row = next(r for r in m["routines"] if r["name"] == "digest")
    assert control_row["kind"] == "control"
    assert control_row["label"] == "com.teyla.demo.digest"


def test_manifest_rejects_gate_b_without_act(tmp_path):
    p = tmp_path / "teyla.toml"
    p.write_text('[product]\nname="x"\n[[routine]]\nname="a"\ngate="B"\nstep={kind="command",run="true"}\n')
    with pytest.raises(ManifestError, match="needs an `act` step"):
        load_manifest(p)


def test_manifest_rejects_gate_c_without_critic(tmp_path):
    p = tmp_path / "teyla.toml"
    p.write_text('[product]\nname="x"\n[[routine]]\nname="a"\ngate="C"\n'
                 'step={kind="command",run="true"}\nact={kind="command",run="true"}\n')
    with pytest.raises(ManifestError, match="needs a `critic`"):
        load_manifest(p)


def test_manifest_rejects_clock_trigger_without_tz(tmp_path):
    p = tmp_path / "teyla.toml"
    p.write_text('[product]\nname="x"\n[[routine]]\nname="a"\n'
                 'trigger={type="clock",at="07:00"}\nstep={kind="command",run="true"}\n')
    with pytest.raises(ManifestError, match="explicit `tz`"):
        load_manifest(p)


def test_manifest_rejects_unknown_capability_scheme(tmp_path):
    p = tmp_path / "teyla.toml"
    p.write_text('[product]\nname="x"\n[[routine]]\nname="a"\n'
                 'step={kind="command",run="true"}\ncapabilities=["db:drop"]\n')
    with pytest.raises(ManifestError, match="unknown scheme"):
        load_manifest(p)


def test_agent_step_requires_a_known_harness(tmp_path):
    p = tmp_path / "teyla.toml"
    p.write_text('[product]\nname="x"\n[[routine]]\nname="a"\n'
                 'step={kind="agent",harness="gemini",prompt="hi"}\n')
    with pytest.raises(ManifestError, match="harness"):
        load_manifest(p)


@pytest.mark.parametrize("spec,expected", [
    ("mon-fri", ("mon", "tue", "wed", "thu", "fri")),
    ("daily", ("mon", "tue", "wed", "thu", "fri", "sat", "sun")),
    ("sat,sun", ("sat", "sun")),
    (None, ("mon", "tue", "wed", "thu", "fri", "sat", "sun")),
])
def test_parse_days(spec, expected):
    assert parse_days(spec) == expected


def test_parse_days_refuses_a_backwards_range():
    with pytest.raises(ManifestError):
        parse_days("fri-mon")


def test_parse_capability_splits_on_the_first_colon_only():
    assert parse_capability("tool:mcp__loco__*") == ("tool", "mcp__loco__*")
    assert parse_capability("shell:git push") == ("shell", "git push")


# --- 2. a command routine, end to end ------------------------------------------------------


def test_gate_a_end_to_end_then_approve(product, capsys):
    assert cli("run", "demo:digest") == 0
    out = capsys.readouterr().out
    assert "NEEDS-YOU" in out and "gate A" in out

    run_dir = next((product / "runs").rglob("receipt.json")).parent
    assert (run_dir / "draft.md").read_text().startswith("DRAFT-LINE-ONE")

    receipt = json.loads((run_dir / "receipt.json").read_text())
    assert receipt["outcome"] == "needs-you"
    assert receipt["gate"] == "A"
    assert receipt["routine"] == "demo:digest"
    assert receipt["key"].startswith("date:demo:digest:")
    assert receipt["capabilities"] == ["fs.write:runs/**", "shell:git push"]
    assert "always.md" in receipt["rule_ids"] and "AGENTS.md#rules" in receipt["rule_ids"]
    assert "tone.md" not in receipt["rule_ids"], "a rule scoped to notes/** must not govern this run"
    assert receipt["summary"] and receipt["duration_s"] >= 0

    items = S.fold_inbox()
    (run_id, item), = items.items()
    assert run_id == receipt["run_id"] and item["state"] == "needs-you"

    assert cli("inbox", "list") == 0
    assert run_id in capsys.readouterr().out

    assert cli("inbox", "show", run_id) == 0
    assert "DRAFT-LINE-ONE" in capsys.readouterr().out

    assert cli("inbox", "approve", run_id) == 0
    approved = capsys.readouterr().out
    assert "OK: approved" in approved

    assert (product / "acted.txt").read_text().strip() == "ACTED", "the act step really ran"
    act_receipt = [r for r in S.receipts_for("demo:digest") if r.get("approved_from") == run_id]
    assert len(act_receipt) == 1
    assert act_receipt[0]["outcome"] == "ok"
    assert act_receipt[0]["undo_available"] is True
    assert "rm acted.txt" in (pathlib.Path(act_receipt[0]["run_dir"]) / "undo.md").read_text()

    assert S.fold_inbox()[run_id]["decision"] == "approved"


def test_approving_twice_is_refused(product, capsys):
    cli("run", "demo:digest")
    run_id = next(iter(S.fold_inbox()))
    capsys.readouterr()
    assert cli("inbox", "approve", run_id) == 0
    capsys.readouterr()
    assert cli("inbox", "approve", run_id) == 1
    assert "already approved" in capsys.readouterr().out


def test_reject_with_a_note_becomes_a_correction_candidate(product, capsys):
    cli("run", "demo:digest")
    run_id = next(iter(S.fold_inbox()))
    capsys.readouterr()
    assert cli("inbox", "reject", run_id, "--note", "opened with a question again") == 0
    assert "correction candidate" in capsys.readouterr().out
    rows = S.read_jsonl(product / ".teyla" / "corrections.jsonl")
    assert len(rows) == 1
    assert rows[0]["text"] == "opened with a question again"
    assert rows[0]["routine"] == "demo:digest"
    assert not (product / "acted.txt").exists(), "a rejected item must not act"


def test_reject_without_a_note_records_nothing_to_learn_from(product, capsys):
    cli("run", "demo:digest")
    run_id = next(iter(S.fold_inbox()))
    capsys.readouterr()
    assert cli("inbox", "reject", run_id) == 0
    assert "No --note given" in capsys.readouterr().out
    assert not (product / ".teyla" / "corrections.jsonl").exists()


def test_gate_b_acts_and_writes_an_undo(tmp_path, monkeypatch, capsys):
    repos = tmp_path / "repos"; repo = repos / "b"; repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(
        '[product]\nname="b"\n[[routine]]\nname="r"\ngate="B"\n'
        'step={kind="command",run="echo draft"}\n'
        'act={kind="command",run="echo ACTED > out.txt; echo \'rm out.txt\' > \\"$TEYLA_UNDO\\""}\n'
    )
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "h")); monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    assert cli("run", "b:r") == 0
    assert "OK:" in capsys.readouterr().out
    assert (repo / "out.txt").exists()
    receipt = S.receipts_for("b:r")[-1]
    assert receipt["outcome"] == "ok" and receipt["undo_available"] is True
    assert S.fold_inbox()[receipt["run_id"]]["state"] == "acted"


def test_gate_b_flags_a_missing_undo(tmp_path, monkeypatch, capsys):
    repos = tmp_path / "repos"; repo = repos / "b"; repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(
        '[product]\nname="b"\n[[routine]]\nname="r"\ngate="B"\n'
        'step={kind="command",run="echo draft"}\nact={kind="command",run="echo acted"}\n'
    )
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "h")); monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    assert cli("run", "b:r") == 0
    assert "NO UNDO AVAILABLE" in capsys.readouterr().out
    receipt = S.receipts_for("b:r")[-1]
    assert receipt["undo_available"] is False
    assert "no undo available" in (pathlib.Path(receipt["run_dir"]) / "undo.md").read_text()


def test_a_failing_draft_step_still_writes_a_receipt(tmp_path, monkeypatch, capsys):
    repos = tmp_path / "repos"; repo = repos / "f"; repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(
        '[product]\nname="f"\n[[routine]]\nname="r"\nstep={kind="command",run="exit 3"}\n'
    )
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "h")); monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    assert cli("run", "f:r") == 1
    assert "FAILED:" in capsys.readouterr().out
    receipt = S.receipts_for("f:r")[-1]
    assert receipt["outcome"] == "failed" and "exited 3" in receipt["summary"]


def test_agent_step_fails_clearly_when_the_harness_is_absent(tmp_path, monkeypatch, capsys):
    repos = tmp_path / "repos"; repo = repos / "a"; repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(
        '[product]\nname="a"\n[[routine]]\nname="r"\n'
        'step={kind="agent",harness="grok",prompt="draft it"}\n'
    )
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "h")); monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert cli("run", "a:r") == 1
    assert "no `grok` binary is on PATH" in capsys.readouterr().out


# --- 3. idempotency ------------------------------------------------------------------------


def test_second_run_the_same_day_is_skipped_and_force_overrides(product, capsys):
    assert cli("run", "demo:digest") == 0
    capsys.readouterr()

    assert cli("run", "demo:digest") == 0
    out = capsys.readouterr().out
    assert "SKIPPED" in out and "--force" in out
    assert len(S.receipts_for("demo:digest")) == 1, "a skip must not write a second receipt"

    assert cli("run", "demo:digest", "--force") == 0
    assert "NEEDS-YOU" in capsys.readouterr().out
    assert len(S.receipts_for("demo:digest")) == 2


def test_idempotency_none_never_collides(product):
    r = load_manifest(product / "teyla.toml")[0]
    r = type(r)(**{**r.__dict__, "idempotency": "none"})
    assert engine.idempotency_key(r, run_id="a") != engine.idempotency_key(r, run_id="b")


def test_input_hash_key_changes_with_the_input(tmp_path, monkeypatch):
    repos = tmp_path / "repos"; repo = repos / "h"; repo.mkdir(parents=True)
    (repo / "notes.md").write_text("one")
    (repo / "teyla.toml").write_text(
        '[product]\nname="h"\n[[routine]]\nname="r"\nidempotency="input-hash"\n'
        'step={kind="agent",harness="claude",prompt="p",context=["notes.md"]}\n'
    )
    monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    r = load_manifest(repo / "teyla.toml")[0]
    before = engine.idempotency_key(r, run_id="x")
    assert engine.idempotency_key(r, run_id="y") == before, "same input, same key"
    (repo / "notes.md").write_text("two")
    assert engine.idempotency_key(r, run_id="x") != before


def test_dry_run_creates_nothing(product, capsys):
    assert cli("run", "demo:digest", "--dry") == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "gate A" in out and "date:demo:digest:" in out
    assert "fs.write:runs/**" in out and "always.md" in out
    assert not (product / "runs").exists()
    assert S.receipts_for("demo:digest") == []


# --- 4. the kill switch ---------------------------------------------------------------------


def test_kill_switch_refuses_a_run(product, capsys):
    assert cli("kill", "on", "--reason", "spending too much") == 0
    capsys.readouterr()
    assert cli("run", "demo:digest") == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out and "spending too much" in out
    assert not (product / "runs").exists(), "a refused run must not create its directory"
    assert S.receipts_for("demo:digest") == []

    assert cli("kill", "status") == 0
    assert "ON" in capsys.readouterr().out

    assert cli("kill", "off") == 0
    capsys.readouterr()
    assert cli("run", "demo:digest") == 0
    assert "NEEDS-YOU" in capsys.readouterr().out


def test_kill_switch_refuses_an_approval(product, capsys):
    cli("run", "demo:digest")
    run_id = next(iter(S.fold_inbox()))
    cli("kill", "on", "--reason", "stop")
    capsys.readouterr()
    assert cli("inbox", "approve", run_id) == 1
    assert "kill switch is on" in capsys.readouterr().out
    assert not (product / "acted.txt").exists()


# --- 5. the hook -----------------------------------------------------------------------------


def hook(payload: dict, *, home: pathlib.Path, grants_path=None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["TEYLA_HOME"] = str(home)
    env["PYTHONPATH"] = str(SRC) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env.pop("TEYLA_GRANTS", None)
    if grants_path is not None:
        env["TEYLA_GRANTS"] = str(grants_path)
    return subprocess.run(["/bin/sh", str(HOOK)], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, timeout=30)


@pytest.fixture()
def fixture_grants(tmp_path):
    """A grants.json on disk, as `teyla run` writes it, plus its counter file."""
    home = tmp_path / "home"; home.mkdir()
    run_dir = tmp_path / "run"; run_dir.mkdir()
    doc = {
        "version": 1, "run_id": "R1", "routine": "demo:digest", "repo": str(tmp_path / "repo"),
        "gate": "A",
        "capabilities": ["fs.write:runs/**", "shell:git push", "tool:mcp__loco__*"],
        "grants": {"fs.write": ["runs/**"], "shell": ["git push"], "net": [],
                   "send": [], "tool": ["mcp__loco__*"]},
        "caps": {"max_writes": 2, "max_sends": 0},
        "run_dir": str(run_dir), "state": str(run_dir / "grants-state.json"),
        "actions": str(run_dir / "actions.jsonl"),
    }
    p = run_dir / "grants.json"
    p.write_text(json.dumps(doc))
    G.write_state(run_dir / "grants-state.json", {"writes": 0, "sends": 0, "calls": 0, "denied": 0})
    return {"home": home, "path": p, "run_dir": run_dir, "repo": tmp_path / "repo"}


def payload(tool, tool_input):
    return {"session_id": "s", "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp",
            "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


def test_hook_is_silent_and_allows_with_no_kill_and_no_grants(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    r = hook(payload("Bash", {"command": "rm -rf /"}), home=home)
    assert r.returncode == 0
    assert r.stdout == "" and r.stderr == "", "an ordinary session must not see this hook at all"


def test_hook_denies_everything_while_the_kill_file_exists(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    (home / "KILL").write_text("spending too much\n2026-09-10\n")
    r = hook(payload("Read", {"file_path": "/etc/hosts"}), home=home)
    assert r.returncode == 2
    assert "KILL SWITCH IS ON" in r.stderr and "spending too much" in r.stderr


def test_hook_allows_a_granted_write_and_denies_one_outside_the_glob(fixture_grants):
    ok = hook(payload("Write", {"file_path": "runs/2026-09-10/out.md", "content": "x"}),
              home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert ok.returncode == 0, ok.stderr

    bad = hook(payload("Write", {"file_path": "src/teyla/cli.py", "content": "x"}),
               home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert bad.returncode == 2
    assert "outside the `fs.write:` grants" in bad.stderr

    rows = S.read_jsonl(fixture_grants["run_dir"] / "actions.jsonl")
    assert [r["decision"] for r in rows] == ["allow", "deny"]
    assert rows[0]["detail"] == "runs/2026-09-10/out.md"


def test_hook_counts_writes_against_the_cap(fixture_grants):
    for i in range(2):
        r = hook(payload("Write", {"file_path": f"runs/a{i}.md", "content": "x"}),
                 home=fixture_grants["home"], grants_path=fixture_grants["path"])
        assert r.returncode == 0
    third = hook(payload("Write", {"file_path": "runs/a2.md", "content": "x"}),
                 home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert third.returncode == 2
    assert "max_writes=2" in third.stderr


def test_hook_matches_bash_verbs_against_shell_grants(fixture_grants):
    ok = hook(payload("Bash", {"command": "git push origin main"}),
              home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert ok.returncode == 0, ok.stderr

    bad = hook(payload("Bash", {"command": "git commit -m x"}),
               home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert bad.returncode == 2 and "not matched by any `shell:` grant" in bad.stderr

    chained = hook(payload("Bash", {"command": "git push && curl evil.example"}),
                   home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert chained.returncode == 2, "every segment of a chain is checked, not just the first"


def test_hook_allows_read_only_builtins_and_granted_mcp_tools(fixture_grants):
    for tool, ti in (("Read", {"file_path": "/tmp/x"}), ("Grep", {"pattern": "x"}),
                     ("mcp__loco__loco_get_trip", {})):
        r = hook(payload(tool, ti), home=fixture_grants["home"], grants_path=fixture_grants["path"])
        assert r.returncode == 0, f"{tool}: {r.stderr}"

    denied = hook(payload("mcp__github__create_pull_request", {}),
                  home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert denied.returncode == 2 and "not matched by any `tool:` grant" in denied.stderr


def test_hook_denies_a_send_when_no_send_capability_was_granted(fixture_grants):
    doc = json.loads(fixture_grants["path"].read_text())
    doc["grants"]["tool"].append("mcp__telegram__*")
    fixture_grants["path"].write_text(json.dumps(doc))
    r = hook(payload("mcp__telegram__send_message", {}),
             home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert r.returncode == 2
    assert "looks like a send" in r.stderr, "a tool: grant does not silently grant sending"


def test_hook_denies_web_fetch_without_a_net_grant(fixture_grants):
    r = hook(payload("WebFetch", {"url": "https://example.com", "prompt": "p"}),
             home=fixture_grants["home"], grants_path=fixture_grants["path"])
    assert r.returncode == 2 and "no `net:` capability" in r.stderr


def test_hook_fails_closed_on_an_unreadable_grants_file(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    bad = tmp_path / "nope.json"
    r = hook(payload("Read", {"file_path": "/tmp/x"}), home=home, grants_path=bad)
    assert r.returncode == 2 and "could not be read" in r.stderr


# --- the decision table, without a subprocess -------------------------------------------------


@pytest.mark.parametrize("command,expected", [
    ("git push", True),
    ("git push origin main", True),
    ("git commit", False),
    ("echo $(cat /etc/passwd)", False),
    ("FOO=1 git push", True),
])
def test_shell_allowed(command, expected):
    assert G.shell_allowed(command, ["git push"])[0] is expected


def test_shell_star_grants_everything_including_substitution():
    assert G.shell_allowed("echo $(whoami) | tee /tmp/x", ["*"])[0] is True


@pytest.mark.parametrize("target,ok", [
    ("runs/a.md", True), ("runs/2026/09/a.md", True), ("src/x.py", False), ("/etc/hosts", False),
])
def test_path_matches(tmp_path, target, ok):
    assert G.path_matches(target, ["runs/**"], tmp_path) is ok


def test_net_grant_matches_hosts_not_substrings():
    assert G.net_allowed("https://api.example.com/x", ["example.com"])[0] is True
    assert G.net_allowed("https://example.com.evil.net/x", ["example.com"])[0] is False


# --- 6. rules -----------------------------------------------------------------------------------


def test_rules_are_matched_by_scope_not_by_similarity(product):
    scoped = R.load(product, ["notes/plan.md"])
    assert {r["id"] for r in scoped} == {"tone.md", "always.md", "AGENTS.md#rules"}
    unscoped = R.load(product, ["runs/**"])
    assert {r["id"] for r in unscoped} == {"always.md", "AGENTS.md#rules"}
    assert "Say what is unverified" in next(r for r in unscoped if r["id"] == "AGENTS.md#rules")["text"]
    assert "## Other" not in next(r for r in unscoped if r["id"] == "AGENTS.md#rules")["text"]


# --- 7. triggers --------------------------------------------------------------------------------


def test_plist_generation_for_a_weekday_clock_trigger(product):
    r = load_manifest(product / "teyla.toml")[0]
    xml = triggers.plist_for(r, binary="/usr/local/bin/teyla")
    assert "<string>com.teyla.demo.digest</string>" in xml
    assert "<string>/usr/local/bin/teyla</string>" in xml
    assert "<string>run</string>" in xml and "<string>demo:digest</string>" in xml
    assert xml.count("<key>Weekday</key>") == 5, "mon-fri is five StartCalendarInterval entries"
    assert "<integer>7</integer>" in xml and "<integer>0</integer>" in xml  # hour 7, minute 0
    assert triggers.plist_path(r).name == "com.teyla.demo.digest.plist"


def test_daily_clock_trigger_omits_weekday(tmp_path, monkeypatch):
    repos = tmp_path / "repos"; repo = repos / "d"; repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(
        '[product]\nname="d"\n[[routine]]\nname="r"\n'
        'trigger={type="clock",at="23:15",tz="UTC",days="daily"}\nstep={kind="command",run="true"}\n'
    )
    monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    xml = triggers.plist_for(load_manifest(repo / "teyla.toml")[0], binary="teyla")
    assert "<key>Weekday</key>" not in xml
    assert "<integer>23</integer>" in xml and "<integer>15</integer>" in xml


def test_non_clock_triggers_do_not_install(tmp_path, monkeypatch):
    repos = tmp_path / "repos"; repo = repos / "w"; repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(
        '[product]\nname="w"\n[[routine]]\nname="r"\n'
        'trigger={type="webhook"}\nstep={kind="command",run="true"}\n'
    )
    monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    r = load_manifest(repo / "teyla.toml")[0]
    assert r.trigger.implemented is False
    with pytest.raises(ManifestError, match="not built"):
        triggers.plist_for(r, binary="teyla")


# --- 8. promote ------------------------------------------------------------------------------------


def test_promote_refuses_without_evidence_and_prints_it(product, capsys):
    cli("run", "demo:digest")
    capsys.readouterr()
    assert cli("promote", "demo:digest", "--gate", "B") == 1
    out = capsys.readouterr().out
    assert "REFUSED" in out
    assert "only 1 receipt(s) at gate A; 10 are required" in out
    assert 'gate = "A"' in (product / "teyla.toml").read_text(), "a refusal must not edit the manifest"


def test_promote_refuses_when_an_approval_carried_a_note(product):
    for _ in range(10):
        cli("run", "demo:digest", "--force")
    ids = list(S.fold_inbox())
    for i, rid in enumerate(ids):
        S.add_inbox_decision(run_id=rid, decision="approve", note=("wrong tone" if i == 3 else None))
    ev = promote.evidence("demo:digest", "A")
    ok, problems = promote.verdict(ev)
    assert ok is False
    assert any("approved with a note" in p for p in problems)


def test_promote_succeeds_on_ten_clean_approvals(product, capsys):
    for _ in range(10):
        cli("run", "demo:digest", "--force")
    for rid in S.fold_inbox():
        S.add_inbox_decision(run_id=rid, decision="approve", note=None)
    capsys.readouterr()
    assert cli("promote", "demo:digest", "--gate", "B") == 0
    assert 'gate = "B"' in (product / "teyla.toml").read_text()
    assert load_manifest(product / "teyla.toml")[0].gate == "B"
    assert S.read_jsonl(S.promotions_path())[-1]["to"] == "B"


def test_promote_force_records_the_override(product, capsys):
    cli("run", "demo:digest")
    capsys.readouterr()
    assert cli("promote", "demo:digest", "--gate", "B", "--force", "--note", "I know") == 0
    assert "FORCED" in capsys.readouterr().out
    rec = S.read_jsonl(S.promotions_path())[-1]
    assert rec["forced"] is True and rec["note"] == "I know" and rec["problems"]


def test_set_gate_only_touches_the_named_routine():
    text = ('[product]\nname="x"\n\n'
            '[[routine]]\nname="a"\ngate = "A"\nstep={kind="command",run="true"}\n\n'
            '[[routine]]\nname="b"\ngate = "A"\nstep={kind="command",run="true"}\n')
    out = promote.set_gate(text, "b", "C")
    blocks = out.split("[[routine]]")
    assert 'gate = "A"' in blocks[1] and 'name="a"' in blocks[1]
    assert 'gate = "C"' in blocks[2] and 'name="b"' in blocks[2]


def test_set_gate_inserts_a_missing_gate_line():
    text = '[product]\nname="x"\n[[routine]]\nname = "a"\nstep={kind="command",run="true"}\n'
    assert 'gate = "B"' in promote.set_gate(text, "a", "B")


# --- 9. receipts and the routines table ------------------------------------------------------------


def test_receipts_command_lists_runs(product, capsys):
    cli("run", "demo:digest")
    cli("run", "demo:digest", "--force")
    capsys.readouterr()
    assert cli("receipts", "demo:digest", "-n", "5") == 0
    out = capsys.readouterr().out
    assert out.count("needs-you") == 2


def test_routines_table_shows_the_last_receipt_outcome(product, capsys):
    cli("run", "demo:digest")
    capsys.readouterr()
    from teyla.routines import evaluate_all, render_text
    reports = evaluate_all([str(product)])
    rows = {r["name"]: r for r in reports[0]["routines"]}
    assert rows["digest"]["last_receipt"] == "needs-you"
    assert rows["nightly"]["last_receipt"] == "-"
    text = render_text(reports)
    assert "last receipt" in text and "needs-you" in text


def test_control_routine_with_a_clock_trigger_reports_not_loaded(product):
    from teyla.routines import evaluate_all
    row = next(r for r in evaluate_all([str(product)])[0]["routines"] if r["name"] == "digest")
    assert row["verdict"] == "NOT LOADED", "a clock routine with no plist is not running"


def test_control_routine_without_a_clock_trigger_is_on_demand(tmp_path, monkeypatch):
    repos = tmp_path / "repos"; repo = repos / "m"; repo.mkdir(parents=True)
    (repo / "teyla.toml").write_text(
        '[product]\nname="m"\n[[routine]]\nname="r"\nstep={kind="command",run="true"}\n'
    )
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "h")); monkeypatch.setenv("TEYLA_REPO_ROOTS", str(repos))
    from teyla.routines import evaluate_all
    row = evaluate_all([str(repo)])[0]["routines"][0]
    assert row["loaded"] == "on demand" and row["verdict"] == "ok"


# --- 10. the scaffold template --------------------------------------------------------------------


def test_scaffolded_repo_has_a_runnable_example_routine(tmp_path, monkeypatch):
    from teyla.scaffold import scaffold
    dest = tmp_path / "repos" / "newthing"
    scaffold(str(dest), name="newthing", kind="cli", license="none")
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "h"))
    monkeypatch.setenv("TEYLA_REPO_ROOTS", str(tmp_path / "repos"))
    rs = load_manifest(dest / "teyla.toml")
    assert [r.name for r in rs] == ["example"]
    assert rs[0].gate == "A" and rs[0].step.kind == "command"
    assert cli("run", "newthing:example") == 0
    assert S.receipts_for("newthing:example")[-1]["outcome"] == "needs-you"

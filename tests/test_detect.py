"""teyla.detect: POLICY.md markers, the no-Actions workflow scan, and the ask-permission turn detector."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
from collections import Counter

import pytest

from teyla import detect
from teyla.adapters import Session, claude_code, codex
from teyla.advise import advise
from teyla.monitor import metrics, redact

ROOT = pathlib.Path(__file__).resolve().parents[1]


# --- which detectors the policy declares ----------------------------------------------------

def test_markers_and_wording_declare_detectors():
    text = "# P\n<!-- teyla:detect no-actions -->\n<!-- teyla:detect nonsense-id -->\n"
    assert detect.declared(text) == (["no-actions"], ["nonsense-id"])
    # Ivan's §10 heading and the template's §4 wording switch detectors on without a marker.
    ivan = "## 10. GitHub Actions are off — the laptop is the gate\n\n## 4. Ask about product decisions, not about permission\n"
    assert detect.declared(ivan) == (["ask-permission", "no-actions"], [])
    assert detect.declared("# A policy without either rule\n## 3. Use the tool ladder\n") == ([], [])


def test_the_template_declares_ask_permission_but_not_no_actions():
    active, unknown = detect.declared((ROOT / "templates" / "POLICY.md").read_text())
    assert active == ["ask-permission"] and unknown == []


def test_doctor_rows_for_unknown_marker_and_no_policy(tmp_path):
    assert detect.doctor_checks({}, scan_repos=False, text="") == []
    rows = detect.doctor_checks({}, scan_repos=False, text="<!-- teyla:detect typo-id -->")
    assert rows[0]["level"] == "WARN" and "typo-id" in rows[0]["detail"]


# --- no-actions: the `on:` parser ---------------------------------------------------------------

@pytest.mark.parametrize("yml,want", [
    ("on: push\njobs: {}\n", ["push"]),
    ("name: x\non: [push, pull_request]\n", ["push", "pull_request"]),
    ("on: [\n  push,\n  workflow_dispatch\n]\njobs:\n", ["push", "workflow_dispatch"]),
    ("on:\n  push:\n    branches: [main]\n  workflow_dispatch:\n\njobs:\n  a: {}\n", ["push", "workflow_dispatch"]),
    ('"on":\n  schedule:\n    - cron: "0 6 * * 1"   # Mondays\n  workflow_dispatch:\n', ["schedule", "workflow_dispatch"]),
    ("on:\n  - pull_request_target\n  - issues\n", ["pull_request_target", "issues"]),
    ("on: {push: {branches: [main]}, workflow_dispatch: {}}\n", ["push", "workflow_dispatch"]),
    ("on:\n  # push: disabled per POLICY §10\n  workflow_dispatch:\n", ["workflow_dispatch"]),
    ("on: workflow_dispatch # manual only\n", ["workflow_dispatch"]),
    ("jobs:\n  build:\n    on: push\n", []),  # not top level
])
def test_workflow_triggers_shapes(yml, want):
    assert detect.workflow_triggers(yml) == want


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": "/dev/null"})


def _repo_with_origin(tmp_path, name, committed: dict, local: dict):
    """A clone under tmp/code/<name> whose origin/HEAD has `committed` and whose working tree has
    `local` on top ({relpath: text}; text None deletes)."""
    seed = tmp_path / "seed" / name
    seed.mkdir(parents=True)
    _git(seed, "init", "-q", "-b", "main")
    for rel, text in committed.items():
        (seed / rel).parent.mkdir(parents=True, exist_ok=True)
        (seed / rel).write_text(text)
    (seed / "README").write_text("x")
    _git(seed, "add", "-A"); _git(seed, "commit", "-qm", "seed")
    bare = tmp_path / "bare" / f"{name}.git"
    _git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    clone = tmp_path / "code" / name
    _git(tmp_path, "clone", "-q", str(bare), str(clone))
    for rel, text in local.items():
        p = clone / rel
        if text is None:
            p.unlink()
        else:
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
    return clone


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_scan_says_which_copy_declares_the_trigger(tmp_path):
    wf = ".github/workflows/"
    _repo_with_origin(tmp_path, "both", {wf + "ci.yml": "on: [push, pull_request]\n"}, {})
    _repo_with_origin(tmp_path, "localonly", {wf + "ci.yml": "on: workflow_dispatch\n"},
                      {wf + "ci.yml": "on:\n  push:\n  workflow_dispatch:\n"})
    _repo_with_origin(tmp_path, "remoteonly", {wf + "nightly.yaml": "on:\n  schedule:\n    - cron: '0 1 * * *'\n"},
                      {wf + "nightly.yaml": None})
    _repo_with_origin(tmp_path, "clean", {wf + "ci.yml": "on:\n  workflow_dispatch:\n"}, {})
    (tmp_path / "code" / "not-a-repo" / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "code" / "not-a-repo" / ".github" / "workflows" / "x.yml").write_text("on: push\n")
    cfg = {"code_root": str(tmp_path / "code"), "ops_root": str(tmp_path / "no-ops")}
    scan = detect.scan_workflows(cfg)
    assert scan["repos"] == 4
    got = {f["repo"]: (f["file"], f["triggers"], f["where"]) for f in scan["findings"]}
    assert got == {
        "both": (wf + "ci.yml", ["push", "pull_request"], "default branch + working tree"),
        "localonly": (wf + "ci.yml", ["push"], "working tree only"),
        "remoteonly": (wf + "nightly.yaml", ["schedule"], "default branch only"),
    }
    rows = detect.doctor_checks(cfg, text="## 10. GitHub Actions are off — the laptop is the gate\n")
    by = {r["name"]: r for r in rows}
    assert by["policy:detect"]["level"] == "OK"
    assert by["actions:both"]["level"] == "WARN" and "ci.yml on: push, pull_request" in by["actions:both"]["detail"]
    assert "workflow_dispatch" in by["actions:both"]["fix"] and str(tmp_path / "code" / "both") in by["actions:both"]["fix"]
    assert "actions:clean" not in by
    # Without the rule in the policy nothing is scanned and nothing is said.
    assert detect.doctor_checks(cfg, text="# no such rule\n") == []


def test_scan_without_origin_and_clean_ok_row(tmp_path):
    repo = tmp_path / "code" / "solo"
    (repo / ".git").mkdir(parents=True)  # a git dir with no origin/HEAD
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "a.yml").write_text("on: pull_request\n")
    cfg = {"code_root": str(tmp_path / "code"), "ops_root": str(tmp_path / "code" / "solo")}
    scan = detect.scan_workflows(cfg)
    assert scan["repos"] == 1  # ops_root == a repo already listed: counted once
    assert scan["findings"][0]["where"] == "working tree only, no origin/HEAD to compare"
    assert detect.no_actions_checks({"repos": 3, "findings": []})[0]["level"] == "OK"


def test_enrich_scans_only_when_declared(tmp_path, monkeypatch):
    monkeypatch.setattr(detect, "scan_workflows", lambda cfg=None: {"repos": 1, "findings": [
        dict(repo="loco", path="/r/loco", file=".github/workflows/ci.yml", triggers=["push"], where="default branch + working tree")]})
    m = detect.enrich({}, text="<!-- teyla:detect no-actions -->")
    assert m["policy_detectors"] == ["no-actions"] and m["workflow_triggers"][0]["repo"] == "loco"
    m2 = detect.enrich({}, text="")
    assert m2["policy_detectors"] == [] and "workflow_triggers" not in m2


# --- ask-permission -------------------------------------------------------------------------

@pytest.mark.parametrize("ending,reply", [
    ("All four PRs are green and pushed.\n\nWant me to push them?", "yes, push them"),
    ("Первое вернёт половину прогона, второе снимет четверть отказов. Делать?", "да, делай"),
    ("The plan is in PLAN.md.\n\nProceed?", "go"),
    ("Tests pass locally.\n\nShould I open the PR now?", "Yes"),
    ("I found the leak in the cache layer. Let me know if you want me to fix it.", "yes please"),
    ("Хочешь — соберу такой прогон?", "Да"),
])
def test_permission_asks_answered_with_a_bare_yes_count(ending, reply):
    assert detect.is_permission_ask(ending, reply)


@pytest.mark.parametrize("ending,reply", [
    # a real decision: alternatives, a choice, a menu
    ("Want me to run that, or build a /grok skill mirroring the /codex one?", "yes"),
    ("Which do you want? If A, I'll regenerate all 8.", "yes"),
    ("Делать её сейчас или сначала закончить снос gbrain?", "да"),
    # something the policy reserves for the human
    ("Want me to merge it?", "yes"),
    ("Should I deploy to production?", "yes"),
    ("Paste the API key here, want me to wait?", "yes"),
    ("Should I add them to ~/.agents/POLICY.md?", "yes"),
    # the human did not just say yes
    ("Want me to push them?", "Why did you change the lockfile?"),
    ("Want me to run Grok on the same prompt now as the third vote?", "Okay, skip grok. So what is your top title"),
    ("Хотите, поправлю конфиг сам?", "Давай переавторизуемся с Grok"),
    ("Want me to push them?", None),
    # no question at the end of the turn
    ("Want me to push them?\n\nPushed anyway; PR #12 is open.", "yes"),
    ("Done. All tests pass.", "yes"),
])
def test_decisions_blockers_and_real_answers_do_not_count(ending, reply):
    assert detect.is_permission_ask(ending, reply) is None


def _s(sid, ends, batch=False):
    s = Session(harness="claude-code", project="demo", sid=sid, path=f"/tmp/{sid}", size=1)
    s.first = s.last = ends[0][0] if ends else "2026-09-21T10:00:00Z"
    s.turn_ends = ends
    s.batch = batch
    return s


def test_permission_ask_metrics_by_week_and_batch_excluded():
    ask = ("Want me to push them?", "yes")
    s1 = _s("a1", [("2026-09-21T10:00:00Z", *ask), ("2026-09-22T10:00:00Z", *ask), ("2026-09-29T10:00:00Z", *ask),
                   ("2026-09-29T11:00:00Z", "Which one, A or B?", "yes")])
    s2 = _s("b1", [("2026-09-23T10:00:00Z", *ask)], batch=True)
    pm = detect.permission_ask_metrics([s1, s2])
    assert pm["by_week"] == {"2026-W39": 2, "2026-W40": 1}
    assert pm["total"] == 3 and pm["examined"] == 4
    assert pm["examples"][0] == dict(project="demo", sid="a1", day="2026-09-21", ask="Want me to push them?")


def test_a15_fires_above_threshold_only_when_policy_declares_it():
    ask = ("Want me to push them?", "yes")
    s = _s("a1", [(f"2026-09-2{i}T10:00:00Z", *ask) for i in range(1, 5)])
    m = metrics([s])
    assert m["permission_asks"]["by_week"] == {"2026-W39": 4}
    m["policy_detectors"] = ["ask-permission"]
    a15 = [f for f in advise(m) if f["id"] == "A15"]
    assert a15 and a15[0]["severity"] == "medium" and "2026-W39 4" in a15[0]["evidence"]
    m["policy_detectors"] = []
    assert not [f for f in advise(m) if f["id"] == "A15"]
    m["policy_detectors"] = ["ask-permission"]
    m["permission_asks"]["by_week"] = {"2026-W39": 2}
    assert not [f for f in advise(m) if f["id"] == "A15"]


def test_a16_fires_on_workflow_triggers_when_declared():
    m = metrics([_s("a1", [])])
    m["workflow_triggers"] = [dict(repo="loco", path="/r/loco", file=".github/workflows/ci.yml", triggers=["push", "pull_request"],
                                   where="default branch + working tree")]
    m["policy_detectors"] = ["no-actions"]
    a16 = [f for f in advise(m) if f["id"] == "A16"]
    assert a16 and a16[0]["severity"] == "high" and "loco .github/workflows/ci.yml on: push, pull_request" in a16[0]["evidence"]
    m["policy_detectors"] = []
    assert not [f for f in advise(m) if f["id"] == "A16"]


def test_redact_drops_ask_text_and_repo_names():
    s = _s("a1", [("2026-09-21T10:00:00Z", "Want me to push the acme-project branch?", "yes")])
    m = metrics([s])
    m["workflow_triggers"] = [dict(repo="acme", path="/r/acme", file=".github/workflows/ci.yml", triggers=["push"], where="x")]
    r = redact(m)
    blob = json.dumps(r)
    assert "acme" not in blob
    assert r["permission_asks"]["examples"][0]["ask"] == "—" and r["workflow_triggers"][0]["triggers"] == ["push"]


# --- adapters record turn endings --------------------------------------------------------------

def _write(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _cc(ts, kind, content):
    if kind == "user":
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": content}}
    return {"type": "assistant", "timestamp": ts, "message": {"role": "assistant", "model": "claude-sonnet-5",
                                                              "usage": {}, "content": content}}


def test_claude_code_records_the_text_a_turn_ended_on(tmp_path):
    f = tmp_path / "projects" / "slug" / "s.jsonl"
    _write(str(f), [
        _cc("2026-09-21T10:00:00Z", "user", "fix the build"),
        _cc("2026-09-21T10:00:05Z", "assistant", [{"type": "text", "text": "Should I start?"}]),
        _cc("2026-09-21T10:00:06Z", "assistant", [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]),
        _cc("2026-09-21T10:00:07Z", "user", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]),
        _cc("2026-09-21T10:00:08Z", "assistant", [{"type": "text", "text": "Fixed.\n\nWant me to push it?"}]),
        _cc("2026-09-21T10:01:00Z", "user", "<system-reminder>noise</system-reminder>"),
        _cc("2026-09-21T10:02:00Z", "user", "yes"),
        _cc("2026-09-21T10:02:05Z", "assistant", [{"type": "text", "text": "Pushed."}]),
        _cc("2026-09-21T10:03:00Z", "user", "thanks"),
    ])
    s = claude_code.load(root=str(tmp_path / "projects"))[0]
    # "Should I start?" was followed by a tool call (not an ending); "Pushed." asks nothing.
    assert s.turn_ends == [("2026-09-21T10:00:08Z", "Fixed.\n\nWant me to push it?", "yes")]


def test_codex_records_the_text_a_turn_ended_on(tmp_path):
    root = tmp_path / "sessions" / "2026" / "09" / "21"
    f = root / "rollout-2026-09-21T10-00-00-x.jsonl"

    def msg(ts, role, text):
        kind = "input_text" if role == "user" else "output_text"
        return {"timestamp": ts, "type": "response_item",
                "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}}
    _write(str(f), [
        {"timestamp": "2026-09-21T10:00:00Z", "type": "session_meta", "payload": {"id": "x", "cwd": "/r/demo"}},
        msg("2026-09-21T10:00:01Z", "user", "fix it"),
        msg("2026-09-21T10:00:02Z", "assistant", "Shall I run the tests first?"),
        {"timestamp": "2026-09-21T10:00:03Z", "type": "response_item", "payload": {"type": "function_call", "name": "exec_command"}},
        msg("2026-09-21T10:00:04Z", "assistant", "Fixed. Shall I open the PR?"),
        msg("2026-09-21T10:00:05Z", "user", "yes"),
    ])
    s = codex.load(root=str(tmp_path / "sessions"), archive_root=str(tmp_path / "x"), index_path=str(tmp_path / "i"))[0]
    assert s.turn_ends == [("2026-09-21T10:00:04Z", "Fixed. Shall I open the PR?", "yes")]
    assert detect.is_permission_ask(*s.turn_ends[0][1:])

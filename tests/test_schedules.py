"""teyla.schedules — every scheduled task, and whether it ran.

Everything lives under tmp_path: fake plists, fake SKILL.md folders, a fake scheduled-tasks.json,
fake transcript lines and fake workflow files. launchctl and gh are monkeypatched; nothing here
reads the real ~/Library, ~/.claude or ~/.teyla, or reaches the network."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import plistlib
import subprocess

import pytest

from teyla import cli, config, digest, net, routines, schedules
from teyla.adapters import claude_code

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
H = dt.timedelta(hours=1)
D = dt.timedelta(days=1)

LISTING_HEAD = "PID\tStatus\tLabel\n"


def listing(*rows):
    """`launchctl list` text: rows are (pid or '-', status, label)."""
    return LISTING_HEAD + "".join(f"{p}\t{s}\t{lab}\n" for p, s, lab in rows)


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    (home / "Library" / "LaunchAgents").mkdir(parents=True)
    repos = tmp_path / "repos"
    repos.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.setattr(config, "code_root", lambda cfg=None: repos)
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: False)
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(home / ".claude" / "projects"))
    monkeypatch.setattr(routines, "LINES_DIR", home / ".teyla" / "routines")
    monkeypatch.setattr(routines, "_launchctl_list", lambda: "")
    monkeypatch.setattr(routines, "_crontab_l", lambda: "")
    monkeypatch.setattr(schedules, "_launchctl_disabled", lambda: set())
    monkeypatch.setattr(schedules.shutil, "which", lambda name: None)
    monkeypatch.setattr(schedules, "_now", lambda: NOW)
    from teyla import plugin_install, remind
    monkeypatch.setattr(remind, "REMINDERS_PATH", home / ".teyla" / "reminders.toml")
    monkeypatch.setattr(plugin_install, "lag_banner_item", lambda *a, **k: None)
    monkeypatch.setattr(schedules, "_gh_last_run",
                        lambda repo, wf: (_ for _ in ()).throw(AssertionError("gh ran")))
    return pathlib.Path(home)


def set_mtime(path: pathlib.Path, when: dt.datetime) -> None:
    ts = when.timestamp()
    os.utime(path, (ts, ts))


def plist(env, label, *, calendar=None, interval=None, log=None, mtime=NOW - 30 * D, name=None, extra=None):
    body = {"Label": label}
    if calendar is not None:
        body["StartCalendarInterval"] = calendar
    if interval is not None:
        body["StartInterval"] = interval
    if log is not None:
        body["StandardOutPath"] = str(log)
        body["StandardErrorPath"] = str(log)
    body.update(extra or {})
    p = env / "Library" / "LaunchAgents" / (name or f"{label}.plist")
    p.write_bytes(plistlib.dumps(body))
    set_mtime(p, mtime)
    return p


def log_file(env, name, when):
    p = env / "Library" / "Logs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("ran\n")
    set_mtime(p, when)
    return p


def by_id(entries):
    return {e["id"]: e for e in entries}


def verdicts(entries):
    return {e["id"]: e["verdict"] for e in entries}


def collect(env, **kw):
    entries, n = schedules.collect(NOW, allow_network=kw.pop("allow_network", False), **kw)
    return by_id(entries), n


# --- cadence -----------------------------------------------------------------------------------

@pytest.mark.parametrize("expr,human,every", [
    ("15 6 * * *", "daily 06:15", D),
    ("0 9,17 * * *", "daily 09:00, 17:00", D),
    ("*/30 * * * *", "every 30m", dt.timedelta(minutes=30)),
    ("5 * * * *", "hourly :05", H),
    ("0 */6 * * *", "every 6h", 6 * H),
    ("0 9 * * 1", "weekly Mon 09:00", 7 * D),
    ("0 9 * * 1-5", "weekdays 09:00", 3 * D),
    ("30 8 1 * *", "monthly day 1 08:30", 31 * D),
    ("*/5 9-17 * * *", "cron */5 9-17 * * *", None),
    ("not a cron", "cron not a cron", None),
])
def test_parse_cron(expr, human, every):
    assert schedules.parse_cron(expr) == (human, every)


def test_calendar_cadence():
    assert schedules.calendar_cadence({"Hour": 6, "Minute": 15}) == ("daily 06:15", D)
    assert schedules.calendar_cadence({"Weekday": 5, "Hour": 20, "Minute": 45}) == ("weekly Fri 20:45", 7 * D)
    assert schedules.calendar_cadence({"Minute": 10}) == ("hourly :10", H)
    assert schedules.calendar_cadence({"Day": 3, "Hour": 7}) == ("monthly day 3 07:00", 31 * D)
    days = [{"Weekday": w, "Hour": 9, "Minute": 0} for w in range(1, 6)]
    assert schedules.calendar_cadence(days) == ("weekdays 09:00", 3 * D)
    two = [{"Hour": 8}, {"Hour": 20}]
    text, every = schedules.calendar_cadence(two)
    assert text == "daily 08:00; daily 20:00" and every == D
    assert schedules.calendar_cadence([]) == ("calendar schedule", None)


# --- verdicts ----------------------------------------------------------------------------------

def e_(**kw):
    base = dict(cadence="daily 06:15", expected_every=D, last_run=NOW - 2 * H, since=NOW - 30 * D)
    base.update(kw)
    return schedules.entry("launchd", "x", "x", **base)


@pytest.mark.parametrize("kw,want", [
    ({}, "OK"),
    (dict(last_run=NOW - (D * 1.5 + 2 * H) - dt.timedelta(minutes=1)), "STALE"),
    (dict(last_run=NOW - (D * 1.5 + 2 * H) + dt.timedelta(minutes=1)), "OK"),
    (dict(last_exit=1), "FAILING"),
    (dict(last_exit=0), "OK"),
    (dict(enabled=False, last_exit=1), "DISABLED"),
    (dict(last_run=None), "NEVER RAN"),
    (dict(last_run=None, since=NOW - 3 * H), "OK"),                 # not yet a full cadence old
    (dict(last_run=None, run_known=False), "UNKNOWN"),
    (dict(last_run=None, expected_every=None), "UNKNOWN"),
    (dict(verdict="UNREGISTERED"), "UNREGISTERED"),
    (dict(fire_at=NOW - D, last_run=NOW - D, expected_every=None, enabled=False), "DONE"),
    (dict(fire_at=NOW - D, last_run=None, expected_every=None), "NEVER RAN"),
    (dict(fire_at=NOW + D, last_run=None, expected_every=None), "OK"),
])
def test_verdict_of(kw, want):
    assert schedules.verdict_of(e_(**kw), NOW) == want


# --- claude desktop ----------------------------------------------------------------------------

def desktop_store(env, records, *, sub="claude-code-sessions", wrap=False, name="a"):
    d = env / "Library" / "Application Support" / "Claude" / sub / name / "b"
    d.mkdir(parents=True, exist_ok=True)
    (d / "scheduled-tasks.json").write_text(json.dumps({"scheduledTasks": records} if wrap else records))


def skill(env, task_id, name=None):
    d = env / ".claude" / "scheduled-tasks" / task_id
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name or task_id}\ndescription: does {task_id}\n---\nbody\n")
    return d / "SKILL.md"


def ms(t: dt.datetime) -> int:
    return int(t.timestamp() * 1000)


def test_desktop_every_verdict(env):
    fresh = skill(env, "morning-brief", "Morning brief")
    old = skill(env, "weekly-review")
    skill(env, "never-registered", "Orphan task")
    once_done = skill(env, "remind-once")
    once_future = skill(env, "remind-later")
    off = skill(env, "paused-task")
    desktop_store(env, [
        {"id": "morning-brief", "displayName": "Morning brief", "enabled": True, "filePath": str(fresh),
         "createdAt": ms(NOW - 20 * D), "lastRunAt": (NOW - 3 * H).isoformat(),
         "lastScheduledFor": (NOW - 3 * H).isoformat(), "cronExpression": "0 6 * * *"},
        {"id": "weekly-review", "displayName": "Weekly review", "enabled": True, "filePath": str(old),
         "createdAt": ms(NOW - 60 * D), "lastRunAt": (NOW - 20 * D).isoformat(), "cron": "0 17 * * 5"},
        {"id": "remind-once", "displayName": "Remind once", "enabled": False, "filePath": str(once_done),
         "createdAt": ms(NOW - 9 * D), "fireAt": ms(NOW - 8 * D), "lastRunAt": (NOW - 8 * D).isoformat()},
        {"id": "ghost-task", "displayName": "Ghost", "enabled": True,
         "filePath": str(env / ".claude" / "scheduled-tasks" / "ghost-task" / "SKILL.md"),
         "createdAt": ms(NOW - 9 * D), "schedule": "0 7 * * *"},
    ], wrap=False)
    desktop_store(env, [
        {"id": "remind-later", "displayName": "Remind later", "enabled": True, "filePath": str(once_future),
         "createdAt": ms(NOW - D), "fireAt": ms(NOW + 2 * D)},
        {"id": "paused-task", "displayName": "Paused", "enabled": False, "filePath": str(off),
         "createdAt": ms(NOW - 5 * D), "cronExpression": "0 8 * * *"},
    ], sub="local-agent-mode-sessions", wrap=True)

    got, _ = collect(env)
    v = verdicts(got.values())
    assert v == {
        "claude-desktop:morning-brief": "OK",
        "claude-desktop:weekly-review": "STALE",
        "claude-desktop:remind-once": "DONE",
        "claude-desktop:remind-later": "OK",
        "claude-desktop:paused-task": "DISABLED",
        "claude-desktop:ghost-task": "MISSING DEFINITION",
        "claude-desktop:never-registered": "UNREGISTERED",
    }
    orphan = got["claude-desktop:never-registered"]
    assert orphan["name"] == "Orphan task"
    assert orphan["note"] == schedules.UNREGISTERED_NOTE
    assert got["claude-desktop:morning-brief"]["cadence"] == "daily 06:00"
    assert got["claude-desktop:weekly-review"]["cadence"] == "weekly Fri 17:00"
    once = got["claude-desktop:remind-once"]["cadence"]
    assert once == f"once {(NOW - 8 * D).astimezone():%Y-%m-%d %H:%M}"
    assert "is gone" in got["claude-desktop:ghost-task"]["note"]


def test_desktop_never_ran_and_matching_by_path(env):
    p = skill(env, "folder-name")
    desktop_store(env, [{"id": "app-id-123", "displayName": "Other id", "enabled": True, "filePath": str(p),
                         "createdAt": ms(NOW - 10 * D), "cronExpression": "0 6 * * *"}])
    got, _ = collect(env)
    # the definition is registered under another id, matched by its file path: not UNREGISTERED
    assert verdicts(got.values()) == {"claude-desktop:app-id-123": "NEVER RAN"}


def test_desktop_no_files_at_all(env):
    got, _ = collect(env)
    assert [k for k in got if k.startswith("claude-desktop")] == []


def test_desktop_garbage_store_is_skipped(env):
    d = env / "Library" / "Application Support" / "Claude" / "claude-code-sessions" / "a" / "b"
    d.mkdir(parents=True)
    (d / "scheduled-tasks.json").write_text("{not json")
    skill(env, "lonely")
    got, _ = collect(env)
    assert verdicts(got.values()) == {"claude-desktop:lonely": "UNREGISTERED"}


# --- launchd -----------------------------------------------------------------------------------

def test_launchd_every_verdict(env, monkeypatch):
    plist(env, "com.example.ok", calendar={"Hour": 6, "Minute": 15}, log=log_file(env, "ok.log", NOW - 2 * H))
    plist(env, "com.example.failing", calendar={"Hour": 6}, log=log_file(env, "failing.log", NOW - 3 * H))
    plist(env, "com.example.stale", interval=3600, log=log_file(env, "stale.log", NOW - 2 * D))
    plist(env, "com.example.neverran", calendar={"Hour": 6}, log=env / "Library" / "Logs" / "absent.log")
    plist(env, "com.example.nolog", calendar={"Hour": 6})
    plist(env, "com.example.disabled", calendar={"Hour": 6}, log=log_file(env, "d.log", NOW - H))
    plist(env, "com.example.plistoff", calendar={"Hour": 6}, extra={"Disabled": True})
    plist(env, "com.example.notloaded", calendar={"Hour": 6}, log=log_file(env, "n.log", NOW - H))
    plist(env, "com.example.removed", calendar={"Hour": 6}, name="com.example.removed.plist.bak")
    plist(env, "com.example.removed2", calendar={"Hour": 6}, name="com.example.removed2.plist.disabled")
    plist(env, "com.apple.something", calendar={"Hour": 6})
    plist(env, "com.google.keystone.agent", interval=3600)
    plist(env, "com.example.daemon", extra={"KeepAlive": True, "RunAtLoad": True})
    (env / "Library" / "LaunchAgents" / "broken.plist").write_text("<<< not a plist")
    monkeypatch.setattr(routines, "_launchctl_list", lambda: listing(
        ("-", 0, "com.example.ok"), ("-", 1, "com.example.failing"), ("-", 0, "com.example.stale"),
        ("-", 0, "com.example.neverran"), ("-", 0, "com.example.nolog"), ("-", 0, "com.example.disabled"),
        ("-", 0, "com.example.daemon"), ("123", 0, "com.google.keystone.agent")))
    monkeypatch.setattr(schedules, "_launchctl_disabled", lambda: {"com.example.disabled"})

    got, _ = collect(env)
    assert verdicts(v for k, v in got.items() if k.startswith("launchd")) == {
        "launchd:com.example.ok": "OK",
        "launchd:com.example.failing": "FAILING",
        "launchd:com.example.stale": "STALE",
        "launchd:com.example.neverran": "NEVER RAN",
        "launchd:com.example.nolog": "UNKNOWN",
        "launchd:com.example.disabled": "DISABLED",
        "launchd:com.example.plistoff": "DISABLED",
        "launchd:com.example.notloaded": "UNREGISTERED",
        "launchd:com.example.removed": "DISABLED",
        "launchd:com.example.removed2": "DISABLED",
        "launchd:broken": "UNKNOWN",
    }
    ok = got["launchd:com.example.ok"]
    assert ok["cadence"] == "daily 06:15" and ok["expected_every"] == D
    assert ok["last_run"] == NOW - 2 * H and ok["last_exit"] == 0
    assert got["launchd:com.example.failing"]["last_exit"] == 1
    assert "last exit 1" in got["launchd:com.example.failing"]["note"]
    assert got["launchd:com.example.stale"]["cadence"] == "every 1h"
    assert "StandardOutPath" in got["launchd:com.example.nolog"]["note"]
    assert "renamed copy" in got["launchd:com.example.removed"]["note"]
    assert "launchctl bootstrap" in got["launchd:com.example.notloaded"]["note"]


def test_launchd_ignore_prefixes_are_config(env, monkeypatch):
    plist(env, "com.google.keystone.agent", interval=3600)
    plist(env, "com.vendor.helper", interval=3600)
    monkeypatch.setattr(routines, "_launchctl_list", lambda: listing(("-", 0, "com.vendor.helper")))
    got, _ = collect(env)
    assert "launchd:com.google.keystone.agent" not in got and "launchd:com.vendor.helper" in got
    (env / ".teyla" / "config.toml").write_text('[schedules]\nignore_prefixes = ["com.vendor."]\n')
    got, _ = collect(env)
    assert "launchd:com.vendor.helper" not in got and "launchd:com.google.keystone.agent" in got


def test_launchd_empty_listing_does_not_call_everything_unregistered(env, monkeypatch):
    plist(env, "com.example.a", interval=3600, log=log_file(env, "a.log", NOW - H))
    got, _ = collect(env)  # launchctl printed nothing: loaded-ness is unknown, not "no"
    assert got["launchd:com.example.a"]["verdict"] == "OK"


def test_parse_disabled_and_listing():
    text = '{\n\t"com.example.a" => disabled\n\t"com.example.b" => enabled\n\t"com.example.c" => true\n}'
    assert schedules.parse_disabled(text) == {"com.example.a", "com.example.c"}
    assert schedules.parse_listing(listing(("42", 0, "x"), ("-", -15, "y"))) == {"x": ("42", 0), "y": (None, -15)}


# --- cloud routines (transcripts) --------------------------------------------------------------

def transcript(env, name, rows, *, mtime=NOW - H, project="proj-a"):
    d = env / ".claude" / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text("".join(json.dumps(r) + "\n" for r in rows))
    set_mtime(f, mtime)
    return f


def tool_use(when, name, inp, use_id="toolu_1"):
    return {"timestamp": when.isoformat().replace("+00:00", "Z"), "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": use_id, "name": name, "input": inp}]}}


def tool_result(when, use_id, text):
    return {"timestamp": when.isoformat(), "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": use_id, "content": text}]}}


def test_cloud_routines_from_transcripts(env):
    t0 = NOW - 10 * D
    transcript(env, "s1.jsonl", [
        {"type": "summary", "summary": "unrelated line"},
        tool_use(t0, "RemoteTrigger", {"action": "create", "name": "Nightly digest",
                                       "cron_expression": "0 5 * * *", "enabled": True}, "toolu_a"),
        tool_result(t0, "toolu_a", '{"id": "trig_abc123", "name": "Nightly digest"}'),
        tool_use(NOW - 3 * D, "RemoteTrigger", {"action": "update", "trigger_id": "trig_abc123",
                                                "cron_expression": "30 5 * * *"}, "toolu_b"),
        tool_use(NOW - 2 * D, "RemoteTrigger", {"action": "list"}, "toolu_c"),
        tool_use(NOW - 2 * D, "CronCreate", {"cron": "*/5 * * * *"}, "toolu_d"),
        tool_use(NOW - 40 * D, "CronCreate", {"cron": "*/5 * * * *"}, "toolu_e"),
    ])
    transcript(env, "s2.jsonl", [
        tool_use(NOW - 5 * D, "RemoteTrigger", {"action": "create", "name": "Paused one",
                                                "cron_expression": "0 8 * * 1", "enabled": False}),
        tool_use(NOW - 4 * D, "CronCreate", {"cron": "0 * * * *"}, "toolu_f"),
    ], project="proj-b")
    transcript(env, "ancient.jsonl", [
        tool_use(NOW - 200 * D, "RemoteTrigger", {"action": "create", "name": "Ancient",
                                                  "cron_expression": "0 1 * * *"}),
    ], mtime=NOW - 200 * D)

    got, crons = collect(env)
    cloud = {k: v for k, v in got.items() if k.startswith("cloud")}
    assert set(cloud) == {"cloud:trig_abc123", "cloud:Paused one"}
    nightly = cloud["cloud:trig_abc123"]
    assert nightly["name"] == "Nightly digest" and nightly["cadence"] == "daily 05:30"
    assert nightly["verdict"] == "UNKNOWN"
    assert f"last known as of {(NOW - 3 * D).astimezone():%Y-%m-%d}" in nightly["note"]
    assert cloud["cloud:Paused one"]["verdict"] == "DISABLED"
    assert crons == 2  # the 40-day-old CronCreate is outside the 30-day window


def test_cloud_deleted_routine_is_vanished_then_forgotten(env):
    transcript(env, "s.jsonl", [
        tool_use(NOW - 9 * D, "RemoteTrigger", {"action": "create", "name": "Doomed", "cron_expression": "0 1 * * *"}),
        tool_use(NOW - 8 * D, "RemoteTrigger", {"action": "delete", "name": "Doomed"}),
    ])
    got, _ = collect(env)
    assert got["cloud:Doomed"]["verdict"] == "VANISHED"
    assert "deleted in a session on" in got["cloud:Doomed"]["note"]
    transcript(env, "s.jsonl", [
        tool_use(NOW - 49 * D, "RemoteTrigger", {"action": "create", "name": "Doomed", "cron_expression": "0 1 * * *"}),
        tool_use(NOW - 48 * D, "RemoteTrigger", {"action": "delete", "name": "Doomed"}),
    ])
    got, _ = collect(env)
    assert "cloud:Doomed" not in got


# --- github ------------------------------------------------------------------------------------

WORKFLOW = """name: Nightly build
on:
  push:
    branches: [main]
  schedule:
    - cron: '15 3 * * *'   # every night
    - cron: "0 12 * * 1"
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
"""


def workflow(env, repo, fname, text=WORKFLOW):
    d = env.parent / "repos" / repo / ".github" / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(text)
    set_mtime(d / fname, NOW - 40 * D)
    return d / fname


def test_workflow_crons_parser():
    assert schedules.workflow_crons(WORKFLOW) == ["15 3 * * *", "0 12 * * 1"]
    assert schedules.workflow_crons("on:\n  push:\n    branches: [main]\n") == []
    assert schedules.workflow_crons("on:\n  schedule:\n  - cron: '1 2 * * *'\njobs:\n  x:\n    run: cron: '9 9 * * *'\n") == ["1 2 * * *"]
    assert schedules.workflow_crons("on: {schedule: [{cron: '5 4 * * *'}]}\n") == []  # flow style is not scanned


def test_github_without_network_says_not_checked(env):
    workflow(env, "app-a", "nightly.yml")
    workflow(env, "app-a", "ci.yml", "name: ci\non: [push]\n")
    got, _ = collect(env, allow_network=False)
    gh = {k: v for k, v in got.items() if k.startswith("github")}
    assert list(gh) == ["github:app-a/nightly.yml"]
    e = gh["github:app-a/nightly.yml"]
    assert e["name"] == "app-a: Nightly build"
    assert e["cadence"] == "daily 03:15; weekly Mon 12:00" and e["expected_every"] == 7 * D
    assert e["verdict"] == "UNKNOWN" and e["last_run_text"] == "not checked"
    assert "not checked" in e["note"]


def test_github_with_network_uses_gh(env, monkeypatch):
    workflow(env, "app-a", "nightly.yml")
    workflow(env, "app-b", "weekly.yml", "name: Weekly\non:\n  schedule:\n    - cron: '0 6 * * 0'\n")
    workflow(env, "app-c", "broken.yml", "name: Broken\non:\n  schedule:\n    - cron: '0 6 * * *'\n")
    workflow(env, "app-d", "silent.yml", "name: Silent\non:\n  schedule:\n    - cron: '0 6 * * *'\n")
    monkeypatch.setattr(schedules.shutil, "which", lambda name: "/usr/bin/gh")
    runs = {"nightly.yml": {"conclusion": "success", "createdAt": (NOW - 5 * H).isoformat().replace("+00:00", "Z")},
            "weekly.yml": {"conclusion": "success", "createdAt": (NOW - 30 * D).isoformat()},
            "broken.yml": {"conclusion": "failure", "createdAt": (NOW - H).isoformat()},
            "silent.yml": None}
    calls = []

    def fake(repo, wf):
        calls.append((repo.name, wf))
        return runs[wf]
    monkeypatch.setattr(schedules, "_gh_last_run", fake)
    got, _ = collect(env, allow_network=True)
    assert verdicts(v for k, v in got.items() if k.startswith("github")) == {
        "github:app-a/nightly.yml": "OK", "github:app-b/weekly.yml": "STALE",
        "github:app-c/broken.yml": "FAILING", "github:app-d/silent.yml": "NEVER RAN"}
    assert ("app-a", "nightly.yml") in calls
    assert "concluded failure" in got["github:app-c/broken.yml"]["note"]


def test_github_gh_failure_is_a_note_not_a_crash(env, monkeypatch):
    workflow(env, "app-a", "nightly.yml")
    monkeypatch.setattr(schedules.shutil, "which", lambda name: "/usr/bin/gh")

    def boom(repo, wf):
        raise RuntimeError("gh exited 4: not logged in")
    monkeypatch.setattr(schedules, "_gh_last_run", boom)
    got, _ = collect(env, allow_network=True)
    e = got["github:app-a/nightly.yml"]
    assert e["verdict"] == "UNKNOWN" and "not logged in" in e["note"]


def test_gh_last_run_command(tmp_path, monkeypatch):
    seen = {}

    def run(cmd, **kw):
        seen["cmd"], seen["cwd"] = cmd, kw.get("cwd")
        return subprocess.CompletedProcess(cmd, 0, stdout='[{"conclusion": "success", "createdAt": "2026-10-13T03:15:00Z"}]',
                                           stderr="")
    monkeypatch.setattr(schedules.subprocess, "run", run)
    out = schedules._gh_last_run(tmp_path, "nightly.yml")
    assert out["conclusion"] == "success"
    assert seen["cmd"] == ["gh", "run", "list", "--workflow", "nightly.yml", "--limit", "1", "--json",
                           "conclusion,createdAt"] and seen["cwd"] == str(tmp_path)
    monkeypatch.setattr(schedules.subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no auth\n"))
    with pytest.raises(RuntimeError, match="exited 1: no auth"):
        schedules._gh_last_run(tmp_path, "nightly.yml")


def test_safe_mode_gate_decides_network(env, monkeypatch):
    workflow(env, "app-a", "nightly.yml")
    monkeypatch.setattr(schedules.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(config, "safe_mode", lambda cfg=None: True)
    monkeypatch.setattr(net, "_allow_once", False)
    got, _ = schedules.collect(NOW)  # allow_network unset: the gate answers (and the stub would raise if gh ran)
    assert by_id(got)["github:app-a/nightly.yml"]["last_run_text"] == "not checked"
    net.allow_for_this_command(True)
    monkeypatch.setattr(schedules, "_gh_last_run", lambda repo, wf: None)
    got, _ = schedules.collect(NOW)
    assert by_id(got)["github:app-a/nightly.yml"]["verdict"] == "NEVER RAN"


# --- teyla.toml routines -----------------------------------------------------------------------

def test_routines_are_reused_and_not_listed_twice(env, monkeypatch):
    repo = env.parent / "repos" / "app-a"
    (repo / ".git").mkdir(parents=True)
    log = log_file(env, "sync.log", dt.datetime.now(UTC) - 2 * H)  # routines.evaluate reads the real clock
    (repo / "teyla.toml").write_text(
        '[product]\nname = "app-a"\n'
        f'[[routine]]\nname = "sync"\nkind = "launchd"\nlabel = "com.example.sync"\nevery = "1d"\nlog = "{log}"\n'
        '[[routine]]\nname = "gone"\nkind = "launchd"\nlabel = "com.example.gone"\nevery = "1d"\n'
        '[[routine]]\nname = "web"\nkind = "script"\nhow = "container restarts"\n')
    plist(env, "com.example.sync", calendar={"Hour": 6}, log=log)
    plist(env, "com.example.other", calendar={"Hour": 6}, log=log)
    monkeypatch.setattr(routines, "_launchctl_list", lambda: listing(("-", 0, "com.example.sync"),
                                                                    ("-", 0, "com.example.other")))
    got, _ = collect(env)
    assert "launchd:com.example.sync" not in got      # the teyla.toml row carries it
    assert "launchd:com.example.other" in got
    assert verdicts(v for k, v in got.items() if k.startswith("routines")) == {
        "routines:app-a:sync": "OK", "routines:app-a:gone": "UNREGISTERED", "routines:app-a:web": "UNKNOWN"}
    assert got["routines:app-a:sync"]["cadence"] == "1d"
    assert all(e["elsewhere"] for k, e in got.items() if k.startswith("routines"))


# --- registry ----------------------------------------------------------------------------------

def test_vanished_across_two_runs_and_dropped_after_30_days(env, monkeypatch):
    p = plist(env, "com.example.job", calendar={"Hour": 6}, log=log_file(env, "j.log", NOW - H))
    monkeypatch.setattr(routines, "_launchctl_list", lambda: listing(("-", 0, "com.example.job")))
    full, _ = schedules.run(now=NOW, allow_network=False)
    assert verdicts(full) == {"launchd:com.example.job": "OK"}
    reg = json.loads((env / ".teyla" / "schedules.json").read_text())
    rec = reg["entries"]["launchd:com.example.job"]
    assert rec["first_seen"] == rec["last_seen"] == NOW.isoformat()
    assert rec["snapshot"]["cadence"] == "daily 06:00" and rec["snapshot"]["source"] == "launchd"

    p.unlink()                                           # the task disappears
    later = NOW + 2 * D
    full, _ = schedules.run(now=later, allow_network=False)
    gone = by_id(full)["launchd:com.example.job"]
    assert gone["verdict"] == "VANISHED" and schedules.is_problem(gone)
    assert gone["note"].startswith(f"last seen {NOW.astimezone():%Y-%m-%d}")
    assert gone["name"] == "com.example.job" and gone["cadence"] == "daily 06:00"

    full, _ = schedules.run(now=NOW + 29 * D, allow_network=False)
    assert verdicts(full) == {"launchd:com.example.job": "VANISHED"}
    full, _ = schedules.run(now=NOW + 31 * D, allow_network=False)
    assert full == []
    assert json.loads((env / ".teyla" / "schedules.json").read_text())["entries"] == {}


def test_back_again_clears_vanished_and_keeps_first_seen(env, monkeypatch):
    p = plist(env, "com.example.job", calendar={"Hour": 6}, log=log_file(env, "j.log", NOW - H))
    monkeypatch.setattr(routines, "_launchctl_list", lambda: listing(("-", 0, "com.example.job")))
    schedules.run(now=NOW, allow_network=False)
    saved = p.read_bytes()
    p.unlink()
    schedules.run(now=NOW + D, allow_network=False)
    p.write_bytes(saved)
    set_mtime(p, NOW)
    full, _ = schedules.run(now=NOW + 2 * D, allow_network=False)
    e = by_id(full)["launchd:com.example.job"]
    assert e["verdict"] != "VANISHED" and e["first_seen"] == NOW.isoformat()


def test_cloud_routine_stays_last_known_when_transcripts_age_out(env):
    f = transcript(env, "s.jsonl", [tool_use(NOW - 5 * D, "RemoteTrigger", {
        "action": "create", "name": "Keeper", "cron_expression": "0 5 * * *"})])
    schedules.run(now=NOW, allow_network=False)
    f.unlink()
    full, _ = schedules.run(now=NOW + 60 * D, allow_network=False)
    e = by_id(full)["cloud:Keeper"]
    assert e["verdict"] == "UNKNOWN" and "last known as of" in e["note"]


def test_corrupt_registry_is_set_aside_not_lost(env):
    reg = env / ".teyla" / "schedules.json"
    reg.write_text("{broken")
    schedules.run(now=NOW, allow_network=False)
    assert (env / ".teyla" / "schedules.json.corrupt").read_text() == "{broken"
    assert json.loads(reg.read_text())["entries"] == {}
    assert not list((env / ".teyla").glob("*.tmp"))


# --- output, exit codes, --quiet ---------------------------------------------------------------

def scenario(env, monkeypatch):
    """One failing launchd job, one unregistered desktop task, one OK job."""
    plist(env, "com.example.sync", calendar={"Hour": 6, "Minute": 15}, log=log_file(env, "sync.log", NOW - 2 * H))
    plist(env, "com.example.fine", calendar={"Hour": 7}, log=log_file(env, "fine.log", NOW - H))
    skill(env, "orphan-task", "Orphan task")
    monkeypatch.setattr(routines, "_launchctl_list",
                        lambda: listing(("-", 1, "com.example.sync"), ("-", 0, "com.example.fine")))


def test_text_output_groups_problems_and_counts_ok(env, monkeypatch, capsys):
    scenario(env, monkeypatch)
    rc = cli.main(["schedules"])
    out = capsys.readouterr().out
    assert rc == 1
    lines = out.splitlines()
    assert lines[0].endswith("2 need attention, 0 other, 1 ok")
    assert "claude-desktop" in lines and "launchd" in lines
    assert lines.index("claude-desktop") < lines.index("launchd")
    desk = next(ln for ln in lines if ln.lstrip().startswith("UNREGISTERED"))
    assert "Orphan task" in desk and "not scheduled" in desk
    assert "never fires" in lines[lines.index(desk) + 1]
    fail = next(ln for ln in lines if ln.lstrip().startswith("FAILING"))
    assert fail.split()[1] == "com.example.sync"
    assert "daily 06:15; last run 2h ago" in fail
    assert lines[lines.index(fail) + 1].strip() == "last exit 1"
    assert "com.example.fine" not in out and "1 ok (--all lists them)" in out


def test_all_lists_ok_too(env, monkeypatch, capsys):
    scenario(env, monkeypatch)
    cli.main(["schedules", "--all"])
    out = capsys.readouterr().out
    assert "com.example.fine" in out and "lists them" not in out


def test_json_is_the_full_list(env, monkeypatch, capsys):
    scenario(env, monkeypatch)
    rc = cli.main(["schedules", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 1 and isinstance(data, list)
    got = {d["id"]: d for d in data}
    assert set(got) == {"claude-desktop:orphan-task", "launchd:com.example.sync", "launchd:com.example.fine"}
    row = got["launchd:com.example.sync"]
    assert set(row) == {"id", "source", "name", "cadence", "expected_every_s", "enabled", "last_run", "last_exit",
                        "definition", "note", "verdict", "problem", "first_seen", "last_seen"}
    assert row["verdict"] == "FAILING" and row["problem"] is True and row["expected_every_s"] == 86400
    assert got["launchd:com.example.fine"]["problem"] is False


def test_exit_zero_when_nothing_is_wrong(env, monkeypatch, capsys):
    plist(env, "com.example.fine", calendar={"Hour": 7}, log=log_file(env, "fine.log", NOW - H))
    plist(env, "com.example.off", calendar={"Hour": 7}, extra={"Disabled": True})
    monkeypatch.setattr(routines, "_launchctl_list", lambda: listing(("-", 0, "com.example.fine")))
    rc = cli.main(["schedules"])
    out = capsys.readouterr().out
    assert rc == 0 and "0 need attention" in out and "DISABLED" in out   # listed, but not a problem


def test_empty_machine(env, capsys):
    rc = cli.main(["schedules"])
    assert rc == 0 and "no scheduled tasks found" in capsys.readouterr().out


def test_quiet_prints_nothing_and_writes_then_removes_problems(env, monkeypatch, capsys):
    scenario(env, monkeypatch)
    rc = cli.main(["schedules", "--quiet"])
    cap = capsys.readouterr()
    assert rc == 1 and cap.out == "" and cap.err == ""
    prob = env / ".teyla" / "schedules.problems"
    rows = [ln.split("\t") for ln in prob.read_text().splitlines()]
    assert len(rows) == 2 and all(len(r) == 2 for r in rows)
    assert {r[0] for r in rows} == {"schedule|launchd:com.example.sync|FAILING",
                                    "schedule|claude-desktop:orphan-task|UNREGISTERED"}
    assert any(r[1].startswith("scheduled task com.example.sync FAILING") for r in rows)
    assert (env / ".teyla" / "schedules.json").exists()

    monkeypatch.setattr(routines, "_launchctl_list",
                        lambda: listing(("-", 0, "com.example.sync"), ("-", 0, "com.example.fine")))
    (env / ".claude" / "scheduled-tasks" / "orphan-task" / "SKILL.md").unlink()
    # the orphan definition is gone too: it is VANISHED now, which is still a problem
    assert cli.main(["schedules", "--quiet"]) == 1
    assert [ln.split("\t")[0] for ln in prob.read_text().splitlines()] == ["schedule|claude-desktop:orphan-task|VANISHED"]

    # once the registry forgets it (31 days on) nothing is left: the file is removed
    monkeypatch.setattr(schedules, "run", lambda **kw: ([], 0))
    assert cli.main(["schedules", "--quiet"]) == 0
    assert not prob.exists()


def test_routines_problems_are_not_repeated_in_schedules_problems(env, monkeypatch):
    repo = env.parent / "repos" / "app-a"
    (repo / ".git").mkdir(parents=True)
    (repo / "teyla.toml").write_text('[product]\nname = "app-a"\n[[routine]]\nname = "gone"\nkind = "launchd"\n'
                                     'label = "com.example.gone"\nevery = "1d"\n')
    full, _ = schedules.run(now=NOW, allow_network=False)
    assert verdicts(full) == {"routines:app-a:gone": "UNREGISTERED"}
    assert schedules.problem_lines(full) == []           # `teyla routines` writes that one already
    assert schedules.is_problem(full[0])


def test_session_crons_are_counted_never_listed(env):
    transcript(env, "s.jsonl", [tool_use(NOW - D, "CronCreate", {"cron": "* * * * *"}),
                                tool_use(NOW - D, "CronCreate", {"cron": "*/2 * * * *"}, "toolu_2")])
    entries, n = schedules.collect(NOW, allow_network=False)
    assert n == 2 and entries == []
    text = schedules.render_text(entries, NOW, cron_n=n)
    notes = [ln for ln in text.splitlines() if ln.startswith("note:")]
    assert notes == ["note: 2 session crons were created in the last 30 days; they die with the session and "
                     "are not listed"]
    assert not any(ln.startswith("note:") for ln in schedules.render_text(entries, NOW).splitlines())


# --- the digest and the banner -----------------------------------------------------------------

def test_digest_reads_both_problem_files(env, monkeypatch):
    scenario(env, monkeypatch)
    cli.main(["schedules", "--quiet"])
    (env / ".teyla" / "testflight.problems").write_text(
        "testflight|app-a|IOS|behind\tapp-a iOS: 2 behind — 120: processing\n")
    assert [k for k, _ in digest.schedule_items()][0].startswith("schedule|")
    assert digest.testflight_items() == [("testflight|app-a|IOS|behind", "app-a iOS: 2 behind — 120: processing")]

    path = digest.write_banner_items(checks=[], today=dt.date(2026, 10, 14))
    keys = [ln.split("\t")[0] for ln in path.read_text().splitlines()]
    assert "schedule|launchd:com.example.sync|FAILING" in keys
    assert "schedule|claude-desktop:orphan-task|UNREGISTERED" in keys
    assert "testflight|app-a|IOS|behind" in keys

    cands = {c["id"]: c for c in digest.problem_file_candidates()}
    assert set(cands) == {"schedules", "testflight"}
    assert cands["schedules"]["step"] == "teyla schedules" and cands["schedules"]["cmd"] is True
    assert cands["schedules"]["text"].startswith("2 scheduled tasks not running: ")
    assert cands["testflight"]["text"].startswith("1 TestFlight platform not current: app-a iOS")
    assert cands["testflight"]["step"] == "teyla testflight"
    assert cands["schedules"]["rank"] < cands["testflight"]["rank"]


def test_digest_without_problem_files(env):
    assert digest.schedule_items() == [] and digest.testflight_items() == []
    assert digest.problem_file_candidates() == []
    keys = [ln for ln in digest.write_banner_items(checks=[], today=dt.date(2026, 10, 14)).read_text().splitlines()]
    assert keys == []


# --- the daily routine -------------------------------------------------------------------------

def test_daily_wrapper_runs_both_quiet_steps_and_never_fails_on_them():
    from teyla import routine_install
    t = routine_install.DAILY_WRAPPER_TEMPLATE
    assert "teyla schedules --quiet || true" in t and "teyla testflight --quiet || true" in t

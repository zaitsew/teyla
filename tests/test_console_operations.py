"""The console's Operations section (docs/CONSOLE.md): fakes for every source, no real machine, no network."""
from __future__ import annotations

import json
import os
import time

import pytest

from teyla import console, console_operations as ops, load

GIB = 1024 ** 3
REAL_SPAWN = console.spawn_refresh              # captured before conftest's autouse stub replaces it


def snap(**kw):
    procs = load.Procs(sims=1, claude=4, codex=2, grok=0, lanes=kw.pop("lanes", 0),
                       top=[["App", 2 * GIB], ["Other", GIB // 2]])
    if kw.pop("build", False):
        procs.drivers = [load.Driver(pid=1, kind="xcodebuild", rss_bytes=GIB, etime_s=5)]
    base = dict(time="2026-11-04T01:00:00+01:00", ram_bytes=24 * GIB, ncpu=10, load1=3.5, load5=3.0, load15=2.5,
                swap_total_bytes=5 * GIB, swap_used_bytes=2 * GIB, pressure=1, compressor_bytes=GIB,
                disk_free_bytes=90 * GIB, procs=procs)
    base.update(kw)
    return load.Snapshot(**base)


@pytest.fixture
def fake_machine(monkeypatch):
    from teyla import storage

    def install(s):
        monkeypatch.setattr(load, "safe_snapshot", lambda *a, **k: s)
        monkeypatch.setattr(load, "current_trend", lambda *a, **k: None)
        monkeypatch.setattr(load, "read_records", lambda *a, **k: [])
        monkeypatch.setattr(storage, "disk", lambda path=None: {"total": 460 * GIB, "used": 370 * GIB,
                                                                "free": 90 * GIB, "free_fraction": 0.2})
    return install


# --- machine and leave ------------------------------------------------------------------------------------

def test_machine_reports_the_snapshot_in_gigabytes(fake_machine):
    fake_machine(snap())
    m = ops.machine(time.time())
    assert (m["verdict"], m["ram_gb"], m["swap_used_gb"], m["swap_total_gb"]) == ("OK", 24.0, 2.0, 5.0)
    assert (m["disk_free_gb"], m["disk_total_gb"], m["cores"], m["cpu_load"]) == (90.0, 460.0, 10, 3.5)
    assert m["agents"] == {"claude": 4, "codex": 2, "grok": 0} and m["sims"] == 1 and m["builds"] == 0
    assert m["top"][0] == {"name": "App", "gb": 2.0}


def test_machine_that_cannot_be_read_is_null_not_zero(fake_machine):
    fake_machine(None)
    m = ops.machine(time.time())
    assert m["verdict"] is None and m["ram_gb"] is None and m["agents"]["claude"] is None
    assert m["disk_free_gb"] == 90.0            # the disk is read on its own
    assert ops.leave(m)["ok"] is None


def test_series_are_last_day_pairs_and_capped(monkeypatch):
    recs = [{"ts": 1000 + i, "disk_free_bytes": (50 + i % 3) * GIB, "swap_used_bytes": GIB} for i in range(500)]
    recs.append({"ts": 5000, "disk_free_bytes": None, "swap_used_bytes": None})
    out = ops.series(9999, records=recs)
    assert len(out["disk"]) == ops.SERIES_POINTS and out["disk"][0] == [1000, 50.0]
    assert out["disk"][-1][0] == 1499 and out["swap"][0][1] == 1.0


def test_leave_is_ok_only_when_nothing_blocks(fake_machine):
    fake_machine(snap())
    assert ops.leave(ops.machine(1.0)) == {"ok": True, "blockers": []}


def test_leave_names_each_blocker(fake_machine):
    fake_machine(snap(lanes=2, build=True, disk_free_bytes=3 * GIB, pressure=4))
    # the disk fake still says 90 GB; the snapshot-level verdict is CRITICAL through pressure 4
    out = ops.leave(ops.machine(1.0))
    assert out["ok"] is False
    assert any("CRITICAL" in b for b in out["blockers"])
    assert any("2 headless agent lane" in b for b in out["blockers"])
    assert any("1 build" in b for b in out["blockers"])


def test_leave_blocks_on_a_full_disk(fake_machine, monkeypatch):
    from teyla import storage
    fake_machine(snap())
    monkeypatch.setattr(storage, "disk", lambda path=None: {"total": 460 * GIB, "used": 459 * GIB,
                                                            "free": 1 * GIB, "free_fraction": 0.002})
    out = ops.leave(ops.machine(1.0))
    assert out["ok"] is False and any("1.0 GB free" in b for b in out["blockers"])


# --- failures and the headline ----------------------------------------------------------------------------

def item(title, severity="act", kind="schedule", actions=None):
    return {"id": title, "kind": kind, "title": title, "detail": "d", "product": "app", "severity": severity,
            "facts": [], "actions": actions or []}


def test_failures_map_attention_items_and_keep_the_action_command(monkeypatch):
    from teyla import attention
    seen = {}

    def collect(now, sources=None, timeout=None, **kw):
        seen.update(sources=sources, timeout=timeout)
        return {"items": [item("a", actions=[attention.action("Fix", ["storage", "sweep"])]), item("b", "info", "unknown")]}
    monkeypatch.setattr(attention, "collect", collect)
    out = ops.failures(1.0)
    assert out[0] == {"title": "a", "detail": "d", "severity": "act", "product": "app", "kind": "schedule",
                      "action": "teyla storage sweep"}
    assert out[1]["action"] is None
    assert set(seen["sources"]) == set(attention.SOURCES) and seen["timeout"] == ops.ATTENTION_TIMEOUT_S


def test_failures_reuse_the_schedule_entries_and_skip_the_sweep_preview(monkeypatch):
    from teyla import attention, storage
    calls = []
    monkeypatch.setattr(attention, "_sweep_total", lambda cfg: calls.append("sweep") or 5)
    monkeypatch.setattr(storage, "disk", lambda path=None: {"total": 100 * GIB, "used": 99 * GIB, "free": GIB,
                                                            "free_fraction": 0.01})
    once = ops.Once(lambda: calls.append("scan") or [])
    rep = ops.failures(1.0, once, timeout=5)
    ops.Once.get(once)
    assert calls == ["scan"]                                   # scanned once, no sweep
    assert any(f["kind"] == "disk" and "sweep --dry" in f["detail"] for f in rep)


def test_headline_counts_only_acting_failures():
    fails = [{"severity": "act", "title": "Disk is low"}, {"severity": "act", "title": "x"},
             {"severity": "info", "title": "y"}]
    assert ops.headline(fails) == {"label": "Unresolved failures", "value": 2, "detail": "Disk is low (+1 more)"}
    assert ops.headline([{"severity": "info", "title": "y"}])["detail"].startswith("Nothing needs you here; 1 source")
    h = ops.headline(None, "TimeoutError: slow")
    assert h["value"] is None and "slow" in h["detail"]


def test_once_computes_once_and_repeats_its_error():
    n = []
    once = ops.Once(lambda: n.append(1) or "v")
    assert once.get() == once.get() == "v" and n == [1]
    bad = ops.Once(lambda: 1 / 0)
    for _ in range(2):
        with pytest.raises(ZeroDivisionError):
            bad.get()


# --- schedules --------------------------------------------------------------------------------------------

def entry(name, verdict, source="launchd", last=None):
    return {"id": f"{source}:{name}", "source": source, "name": name, "verdict": verdict, "cadence": "daily 07:00",
            "last_run": last, "note": "n" if verdict != "OK" else ""}


def test_schedule_rows_are_sorted_worst_first_and_counted():
    rows = ops.schedule_rows([entry("a", "OK"), entry("b", "STALE"), entry("c", "DISABLED"), entry("d", "FAILING")])
    assert [r["name"] for r in rows["rows"]] == ["d", "b", "c", "a"]
    assert rows["counts"] == {"attention": 2, "ok": 1, "other": 1}
    assert rows["rows"][3]["note"] is None and rows["rows"][0]["last_run"] is None


# --- harnesses and the policy copies ----------------------------------------------------------------------

def test_harness_rows_carry_version_policy_and_hook_trust(monkeypatch):
    from teyla import harness, policy
    monkeypatch.setattr(policy, "status", lambda: {"claude-code": True, "codex": True, "grok": False})
    monkeypatch.setattr(harness, "installed", lambda name, home=None: True)
    monkeypatch.setattr(harness, "status", lambda: [
        {"harness": "codex", "present": True, "policy": True, "skills": 7, "skills_total": 7, "hooks": True,
         "trust": {"approved": 3, "total": 4, "missing": ["x"]}},
        {"harness": "grok", "present": True, "policy": False, "skills": 6, "skills_total": 7, "hooks": False, "trust": None},
        {"harness": "hermes", "present": False}])
    rows = {r["name"]: r for r in ops.harness_rows(ver=lambda names: {"claude-code": "2.0.1", "codex": "0.1.0"})}
    assert rows["claude-code"]["version"] == "2.0.1" and rows["claude-code"]["policy"] == "synced"
    assert rows["codex"]["note"] == "skills 7/7, hooks wired, hooks not approved (3/4)"
    assert rows["grok"]["policy"] == "not wired" and rows["grok"]["version"] is None
    assert rows["hermes"]["installed"] is False and rows["hermes"]["policy"] is None
    assert "cursor" not in rows                      # not in harness.status: switched off


def test_policy_sync_reports_drift_inbox_and_repos(monkeypatch, tmp_path):
    from teyla import config, policy
    monkeypatch.setattr(policy, "POLICY", tmp_path / "POLICY.md")
    (tmp_path / "POLICY.md").write_text("x")
    monkeypatch.setattr(policy, "HOME", tmp_path)
    monkeypatch.setattr(config, "code_root", lambda cfg=None: tmp_path)
    monkeypatch.setattr(policy, "drift", lambda h: ("a copy is stale", "teyla policy sync") if h == "grok" else None)
    monkeypatch.setattr(policy, "pending_edits", lambda: [])
    monkeypatch.setattr(policy, "repos_status", lambda root: [("ok", "a"), ("missing", "b"), ("none", "c")])
    out = ops.policy_sync(1.0)
    assert out["status"] == "drift" and out["drift"] == [{"harness": "grok", "why": "a copy is stale",
                                                          "fix": "teyla policy sync"}]
    assert out["repos"] == {"ok": 1, "differ": 0, "missing": 1, "none": 1, "to_fix": ["b"]}
    assert out["last_sync"] is None
    monkeypatch.setattr(policy, "drift", lambda h: None)
    assert ops.policy_sync(1.0)["status"] == "ok"             # a repo with one file is listed, not drift
    monkeypatch.setattr(policy, "pending_edits", lambda: [{"name": "x"}])
    assert ops.policy_sync(1.0)["status"] == "drift"


# --- security: caches only --------------------------------------------------------------------------------

def test_security_reads_the_three_caches_and_leaves_shield_null(monkeypatch, tmp_path):
    from teyla import deps, leak_published, reviews
    (tmp_path / "d.json").write_text(json.dumps({"at": "2026-11-01T00:00:00+00:00", "fix": 5}))
    (tmp_path / "l.json").write_text(json.dumps({"at": "2026-11-02T00:00:00+00:00", "blockers": 2}))
    monkeypatch.setattr(deps, "summary_path", lambda: tmp_path / "d.json")
    monkeypatch.setattr(leak_published, "summary_path", lambda: tmp_path / "l.json")
    monkeypatch.setattr(reviews, "summary_path", lambda: tmp_path / "missing.json")
    out = ops.security()
    assert (out["shield_issues"], out["leak_findings"], out["deps_vulns"], out["unreviewed_prs"]) == (None, 2, 5, None)
    assert out["as_of"]["deps"].startswith("2026-11-01") and out["as_of"]["reviews"] is None
    assert any("reviews" in n for n in out["notes"]) and any("shield" in n for n in out["notes"])


# --- the section ------------------------------------------------------------------------------------------

def test_run_parts_survives_a_raising_and_a_late_part():
    out, notes = ops.run_parts({"ok": lambda: 1, "bad": lambda: 1 / 0, "slow": lambda: time.sleep(2)}, budget_s=0.3)
    assert out == {"ok": 1} and "ZeroDivisionError" in notes["bad"] and "no answer" in notes["slow"]


def test_section_has_the_contract_keys_and_one_broken_part_does_not_hide_the_rest(monkeypatch, fake_machine):
    fake_machine(snap())
    monkeypatch.setattr(ops, "failures", lambda now, entries=None, **kw: [item("Disk is low")])
    monkeypatch.setattr(ops, "schedule_entries", lambda now: [entry("a", "OK")])
    monkeypatch.setattr(ops, "harness_rows", lambda: 1 / 0)
    monkeypatch.setattr(ops, "policy_sync", lambda now: {"status": "ok", "drift": []})
    monkeypatch.setattr(ops, "security", lambda: {"shield_issues": None})
    sec = ops.section(time.time())
    assert set(sec) >= {"headline", "machine", "leave", "failures", "schedules", "harnesses", "policy_sync",
                        "security", "notes"}
    assert sec["headline"]["value"] == 1 and sec["machine"]["verdict"] == "OK" and sec["leave"]["ok"] is True
    assert sec["harnesses"] is None and "ZeroDivisionError" in sec["notes"]["harnesses"]
    assert sec["schedules"]["counts"]["ok"] == 1
    json.dumps(sec)                                           # serialisable


def test_section_makes_no_network_call(monkeypatch, fake_machine):
    import socket
    fake_machine(snap())
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr(ops, "failures", lambda now, entries=None, **kw: [])
    monkeypatch.setattr(ops, "schedule_entries", lambda now: [])
    monkeypatch.setattr(ops, "harness_rows", lambda: [])
    monkeypatch.setattr(ops, "policy_sync", lambda now: {})
    ops.section(time.time())


def test_compact_is_small_and_has_the_top_three_failures():
    sec = {"headline": {"label": "Unresolved failures", "value": 4, "detail": "x"},
           "machine": {"verdict": "BUSY", "disk_free_gb": 40.0, "series": {"disk": [[1, 2]] * 90}},
           "leave": {"ok": False, "blockers": ["b"]},
           "failures": [item(f"f{i}") for i in range(5)], "schedules": {"rows": [1] * 50}}
    c = ops.compact(sec)
    assert c["machine"] == {"verdict": "BUSY", "disk_free_gb": 40.0} and c["leave_ok"] is False
    assert [f["title"] for f in c["failures"]] == ["f0", "f1", "f2"]
    assert "schedules" not in c and len(json.dumps(c)) < 600
    assert ops.compact({"error": "boom"}) == {"error": "boom"}
    assert ops.compact({"headline": {"value": None}})["machine"] == {"verdict": None, "disk_free_gb": None}


def test_console_picks_up_this_module():
    assert console.SECTIONS["operations"] == "console_operations"


# --- the detached refresh from `teyla state` --------------------------------------------------------------

def test_spawn_refresh_takes_a_lock_and_runs_detached(monkeypatch, tmp_path):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path))
    monkeypatch.setattr(console, "spawn_refresh", REAL_SPAWN)       # conftest stubs it for every test
    mod = console
    started = []
    monkeypatch.setattr(mod.subprocess, "Popen", lambda argv, **kw: started.append((argv, kw)))
    assert mod.maybe_refresh({"generated": 1000.0}, now=1000.0 + 60) is False          # fresh
    assert mod.maybe_refresh({"generated": 1000.0}, now=1000.0 + 31 * 60) is True      # old
    assert mod.maybe_refresh(None, now=5000.0) is False                                 # lock held: one at a time
    assert len(started) == 1
    argv, kw = started[0]
    assert argv[-3:] == ["console", "--refresh", "--background"] and kw["start_new_session"] is True
    os.utime(mod.lock_path(), (100, 100))
    assert mod.maybe_refresh(None, now=100 + mod.LOCK_STALE_S + 1) is True              # stale lock is taken over
    assert len(started) == 2


def test_background_run_writes_the_cache_and_removes_the_lock(monkeypatch, tmp_path):
    from teyla import cli
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path))
    monkeypatch.setattr(console, "build_section", lambda name, now: {"headline": {"label": name, "value": 1}})
    console.lock_path().parent.mkdir(parents=True, exist_ok=True)
    console.lock_path().write_text("")
    assert cli.main(["console", "--refresh", "--background"]) == 0
    assert not console.lock_path().exists()
    assert console.read_cache()["operations"]["headline"]["value"] == 1


def test_state_carries_the_compact_console_and_asks_for_a_refresh(monkeypatch):
    from teyla import state
    asked = []
    monkeypatch.setattr(console, "read_cache", lambda: {"version": 1, "generated": 5.0,
                                                          "operations": {"headline": {"value": 2}}})
    monkeypatch.setattr(console, "maybe_refresh", lambda rep, now: asked.append(now) or False)
    got = state.console_view(77.0)
    assert asked == [77.0] and got["operations"]["headline"] == {"value": 2}
    monkeypatch.setattr(console, "read_cache", lambda: 1 / 0)
    assert state.console_view(1.0) is None

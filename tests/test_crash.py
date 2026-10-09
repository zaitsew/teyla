"""`teyla crash` — the report parsers, de-duplication, the load context, the advice, the acknowledgement,
doctor's `machine:crash` row on its way to the session-start banner, and the digest line.

Every report is written to tmp_path with anonymised values; nothing here reads the real
/Library/Logs/DiagnosticReports (conftest points `crash.DEFAULT_ROOTS` at nothing) or the real ~/.teyla.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os

import pytest

from teyla import cli, config, crash, digest, doctor, load

GIB = 1024 ** 3
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 9, 22, 0, tzinfo=UTC)
PANIC_AT = dt.datetime(2026, 10, 9, 18, 25, 24, tzinfo=UTC)       # the real panic time
INCIDENT = "AAAAAAAA-0000-4000-8000-000000000001"
RESET_INCIDENT = "AAAAAAAA-0000-4000-8000-000000000002"
JETSAM_INCIDENT = "AAAAAAAA-0000-4000-8000-000000000003"

COMPRESSOR = "Compressor Info: 13% of compressed pages limit (OK) and 27% of segments limit (OK) with 21 swapfiles and OK swap space"


def hdr(when: dt.datetime, incident: str, bug_type: str = "210") -> str:
    return json.dumps({"bug_type": bug_type, "timestamp": when.strftime("%Y-%m-%d %H:%M:%S.00 +0000"),
                       "os_version": "macOS 27.0 (00A0000a)", "roots_installed": 0, "incident_id": incident})


def panic_string(first: str, task: str | None = "pid 27899: simctl", when: dt.datetime | None = PANIC_AT,
                 compressor: str | None = COMPRESSOR, kext: str | None = "com.example.filesystems.autofs") -> str:
    lines = [first, "\t  x0:  0xf9fffe29f0ffc200 x1:  0xf5fffe29f386c200"]
    if task:
        lines.append(f"Panicked task 0xf3fffe1d17fd5bb0: 0 pages, 1 threads: {task}")
    if when is not None:
        lines += ["Epoch Time:        sec       usec", f"  Calendar: 0x{int(when.timestamp()):x} 0x0007c36d",
                  "  Boot    : 0x6ac4d9a6 0x000b9e82", "  Sleep   : 0x6ac926b4 0x000bc31e", "  Wake    : 0x6ac92887 0x000162b4"]
    if compressor:
        lines.append(compressor)
    if kext:
        lines.append(f"last started kext at 1624147826: {kext}\t3.0 (addr 0xfffffe003fedea60, size 5927)")
    return "\n".join(lines) + "\n"


def write_panic(d, processed_at=None, incident=INCIDENT, ps=None, name="panic-base+socd-2026-10-09-201115.000.panic",
                body_extra=None):
    d.mkdir(parents=True, exist_ok=True)
    ps = ps if ps is not None else panic_string("panic(cpu 9 caller 0xfffffe004479ec08): Kernel data abort. at pc 0xfffffe0044475030, lr 0x01c4")
    body = {"product": "Mac00,0", "kernel": "Darwin Kernel Version 27.0.0", "panicString": ps, "date": "2026-10-09 20:25:24.12 +0200",
            "incident": incident, **(body_extra or {})}
    p = d / name
    p.write_text(hdr(processed_at or PANIC_AT + dt.timedelta(minutes=46), incident) + "\n" + json.dumps(body, indent=2))
    return p


def write_reset(d, when=None, faults="wdog,reset_in_1", incident=RESET_INCIDENT, name="ResetCounter-2026-10-09-201116.diag"):
    d.mkdir(parents=True, exist_ok=True)
    when = when or PANIC_AT + dt.timedelta(minutes=46)
    p = d / name
    p.write_text(hdr(when, incident, "115") + f"\nIncident Identifier: {incident}\nDate: {when:%Y-%m-%d %H:%M:%S}.00 +0000\n"
                 f"Reset count: 1\nBoot failure count: 0\nBoot faults: {faults}\nBoot stage: 0x0\n")
    return p


def proc(name, rpages, reason=None):
    d = {"name": name, "pid": abs(hash(name)) % 90000, "rpages": rpages, "states": []}
    if reason:
        d["reason"] = reason
    return d


def write_jetsam(d, when, incident=JETSAM_INCIDENT, processes=None, name=None, compressor_pages=700_000, page_size=16384):
    d.mkdir(parents=True, exist_ok=True)
    gb_pages = lambda g: int(g * GIB / page_size)  # noqa: E731
    processes = processes if processes is not None else [
        proc("Google Chrome", gb_pages(2.0)), proc("Google Chrome Helper (Renderer)", gb_pages(1.5)),
        proc("Google Chrome Helper (Renderer)", gb_pages(1.5)), proc("Google Chrome Helper", gb_pages(0.5)),
        proc("java", gb_pages(2.5)), proc("java", gb_pages(2.0)), proc("claude", gb_pages(0.6)), proc("claude", gb_pages(0.6)),
        proc("tiny", 10), proc("ReportCrashService", 4182, "per-process-limit"), proc("mdworker", 100, "vm-pageshortage"),
    ]
    body = {"product": "Mac00,0", "incident": incident, "largestProcess": "java",
            "memoryStatus": {"compressorSize": compressor_pages, "pageSize": page_size, "memoryPages": {"free": 1000, "active": 5}},
            "processes": processes}
    p = d / (name or f"JetsamEvent-{when:%Y-%m-%d-%H%M%S}.ips")
    p.write_text(hdr(when, incident, "298") + "\n" + json.dumps(body))
    return p


def record_row(path, when: dt.datetime, swap_gb=0.0, load1=1.0, sims=0, builds=0, claude=0, codex=0, lanes=0,
               top=(), daemon_gb=0.0, ram_gb=24):
    procs = load.Procs(sims=sims, drivers=[load.Driver(i, "xcodebuild", 0, 60) for i in range(builds)], claude=claude,
                       codex=codex, lanes=lanes, top=[[n, int(g * GIB)] for n, g in top],
                       daemons=[load.Daemon(1, "gradle", int(daemon_gb * GIB), 60)] if daemon_gb else [])
    s = load.Snapshot(time=when.isoformat(timespec="seconds"), ram_bytes=ram_gb * GIB, ncpu=10, load1=load1, load5=load1,
                      load15=load1, swap_total_bytes=13 * GIB, swap_used_bytes=int(swap_gb * GIB), pressure=1,
                      compressor_bytes=int(swap_gb * GIB / 2), procs=procs)
    load.record(s, load.assess(s, {}), path=path)


@pytest.fixture
def reports(tmp_path, monkeypatch):
    """A fake DiagnosticReports with a `Retired/` beside it, wired in as the default roots."""
    main, retired = tmp_path / "Reports", tmp_path / "Reports" / "Retired"
    retired.mkdir(parents=True)
    monkeypatch.setattr(crash, "DEFAULT_ROOTS", [main, retired])
    return main, retired


# --- parse_panic ------------------------------------------------------------------------------------

def test_panic_takes_the_real_time_from_the_epoch_block_not_from_the_processing_time(tmp_path):
    p = crash.parse_panic(write_panic(tmp_path))
    assert p.kind == "panic" and p.time == PANIC_AT and p.incident == INCIDENT
    assert p.reason == "Kernel data abort"
    assert (p.task, p.pid) == ("simctl", 27899)
    assert p.compressor == COMPRESSOR and p.compressor_status == "OK" and p.swapfiles == 21
    assert p.kext == "autofs" and p.os_version == "macOS 27.0 (00A0000a)"
    stamp = PANIC_AT.astimezone().strftime("%Y-%m-%d %H:%M")
    assert p.line() == (f"{stamp} kernel panic — Kernel data abort; panicked task simctl (pid 27899); "
                        "compressor OK, 21 swapfiles; last kext autofs")


def test_panic_falls_back_to_the_body_date_then_the_header_when_there_is_no_epoch_block(tmp_path):
    ps = panic_string("panic(cpu 1 caller 0x1): Kernel data abort. at pc 0x2", when=None)
    p = crash.parse_panic(write_panic(tmp_path, ps=ps))
    assert p.time == dt.datetime(2026, 10, 9, 20, 25, 24, 120000, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    path = write_panic(tmp_path, ps=ps, name="panic-b.panic", body_extra={"date": "not a date"})
    assert crash.parse_panic(path).time == PANIC_AT + dt.timedelta(minutes=46)
    insane = panic_string("panic(cpu 1 caller 0x1): x", when=dt.datetime(1971, 1, 1, tzinfo=UTC))   # a garbled Calendar
    assert crash.parse_panic(write_panic(tmp_path, ps=insane, name="panic-c.panic")).time != dt.datetime(1971, 1, 1, tzinfo=UTC)


def test_watchdog_panic_is_classified_and_names_the_stall(tmp_path):
    ps = panic_string("panic(cpu 4 caller 0xfffffe0012345678): watchdog timeout: no checkins from watchdogd in 94 seconds "
                      "(4 total checkins since monitoring last enabled)", task=None)
    p = crash.parse_panic(write_panic(tmp_path, ps=ps))
    assert p.kind == "watchdog" and p.reason == "watchdog timeout: no checkins from watchdogd in 94 seconds"
    assert p.task is None and " watchdog timeout — " in p.line()


def test_panic_without_the_optional_lines_still_reads(tmp_path):
    ps = panic_string("panic(cpu 0 caller 0x1): Kernel trap at 0x2", task=None, compressor=None, kext=None)
    p = crash.parse_panic(write_panic(tmp_path, ps=ps))
    assert p.reason == "Kernel trap at 0x2" and p.task is None and p.compressor is None and p.kext is None
    assert p.line().endswith("— Kernel trap at 0x2")
    bad = panic_string("panic(cpu 0 caller 0x1): x", compressor="Compressor Info: 91% of compressed pages limit (BAD) and 27% of segments limit (OK) with 40 swapfiles and LOW swap space")
    q = crash.parse_panic(write_panic(tmp_path, ps=bad, name="panic-d.panic"))
    assert "BAD" in q.compressor_status and "LOW swap space" in q.compressor_status and q.swapfiles == 40


def test_malformed_panics_are_none_or_partial_and_never_raise(tmp_path):
    assert crash.parse_panic(tmp_path / "missing.panic") is None
    for name, text in {"empty": "", "garbage": "\x00\x01 not json at all", "list": "[1, 2]\n[3]", "header-only-no-time": '{"a": 1}\n'}.items():
        f = tmp_path / f"{name}.panic"
        f.write_text(text)
        assert crash.parse_panic(f) is None, name
    header_only = tmp_path / "h.panic"
    header_only.write_text(hdr(PANIC_AT, INCIDENT) + "\n{ truncated")           # the body was cut off
    p = crash.parse_panic(header_only)
    assert p.time == PANIC_AT and p.reason is None and p.line().endswith("reason unknown")
    wrong = tmp_path / "w.panic"
    wrong.write_text(hdr(PANIC_AT, INCIDENT) + "\n" + json.dumps({"panicString": 12345}))
    assert crash.parse_panic(wrong).reason is None


# --- parse_reset / parse_jetsam --------------------------------------------------------------------------

def test_reset_counter_classifies_wdog_as_a_watchdog_reset(tmp_path):
    r = crash.parse_reset(write_reset(tmp_path))
    assert r.watchdog and r.kind == "watchdog" and r.faults == ["wdog", "reset_in_1"] and r.incident == RESET_INCIDENT
    assert "watchdog reset" in r.line()
    assert not crash.parse_reset(write_reset(tmp_path, faults="none", name="ResetCounter-b.diag")).watchdog


def test_malformed_reset_counters(tmp_path):
    assert crash.parse_reset(tmp_path / "nope.diag") is None
    f = tmp_path / "x.diag"
    f.write_text("Boot faults: wdog\n")                       # no time anywhere
    assert crash.parse_reset(f) is None
    f.write_text("Incident Identifier: ID1\nDate: 2026-10-09 20:25:24.00 +0000\nBoot faults: wdog\n")   # no JSON header
    r = crash.parse_reset(f)
    assert r.watchdog and r.incident == "ID1" and r.time == dt.datetime(2026, 10, 9, 20, 25, 24, tzinfo=UTC)


def test_jetsam_summary_folds_helpers_and_names_the_killed(tmp_path):
    when = dt.datetime(2026, 10, 9, 17, 4, 21, tzinfo=UTC)
    j = crash.parse_jetsam(write_jetsam(tmp_path, when))
    assert j.time == when and j.incident == JETSAM_INCIDENT and j.processes == 11
    assert j.compressor_bytes == 700_000 * 16384 and j.free_bytes == 1000 * 16384 and j.largest == "java"
    top = {n: (round(b / GIB, 1), c) for n, b, c in j.top}
    assert top["Google Chrome"] == (5.5, 4) and top["java"] == (4.5, 2) and top["claude"] == (1.2, 2)
    assert [n for n, _, _ in j.top][:2] == ["Google Chrome", "java"] and len(j.top) <= 8
    assert sorted(j.killed) == [("ReportCrashService", "per-process-limit"), ("mdworker", "vm-pageshortage")]
    assert "Google Chrome 5.5 GB ×4" in j.top_text() and "ReportCrashService (per-process-limit)" in j.killed_text()
    assert "compressor 10.7 GB, 11 processes, 2 killed" in j.line()


def test_malformed_jetsam_is_partial_or_none(tmp_path):
    assert crash.parse_jetsam(tmp_path / "x.ips") is None
    f = tmp_path / "bad.ips"
    f.write_text("nonsense")
    assert crash.parse_jetsam(f) is None
    f.write_text(hdr(PANIC_AT, "I1", "298") + "\n{ cut off")
    j = crash.parse_jetsam(f)
    assert j.time == PANIC_AT and j.processes == 0 and j.top == [] and j.compressor_bytes is None
    f.write_text(hdr(PANIC_AT, "I1", "298") + "\n" + json.dumps({"memoryStatus": {"pageSize": "big", "compressorSize": True},
                                                              "processes": [1, None, {"name": 7, "rpages": "x"}, {"rpages": 5}]}))
    j = crash.parse_jetsam(f)
    assert j.page_size == 16384 and j.compressor_bytes is None and j.processes == 2


# --- finding and de-duplicating -------------------------------------------------------------------------------

def test_the_same_incident_in_the_folder_and_in_retired_counts_once(reports):
    main, retired = reports
    write_panic(retired)
    write_panic(main, name="panic-copy.panic")
    write_jetsam(main, PANIC_AT - dt.timedelta(minutes=21))
    write_jetsam(retired, PANIC_AT - dt.timedelta(minutes=21))
    evs = crash.events()
    assert [e.kind for e in evs] == ["jetsam", "panic"]
    assert evs[1].path.endswith("panic-copy.panic")                  # the main folder is read first


def test_events_are_sorted_oldest_first_and_cut_at_since(reports):
    main, _ = reports
    old = PANIC_AT - dt.timedelta(days=5)
    write_jetsam(main, old, incident="J-OLD")
    write_jetsam(main, PANIC_AT - dt.timedelta(minutes=21), incident="J-NEW")
    write_panic(main)
    assert [e.incident for e in crash.events()] == ["J-OLD", "J-NEW", INCIDENT]
    assert [e.incident for e in crash.events(since=PANIC_AT - dt.timedelta(days=1))] == ["J-NEW", INCIDENT]


def test_a_watchdog_reset_after_a_panic_is_its_reboot_not_a_second_incident(reports):
    main, _ = reports
    write_panic(main)
    write_reset(main)                                                # 46 minutes later
    assert [e.kind for e in crash.events()] == ["panic"]
    write_reset(main, when=PANIC_AT + dt.timedelta(hours=9), incident="R-LATE", name="ResetCounter-late.diag")
    assert [(e.kind, e.incident) for e in crash.events()] == [("panic", INCIDENT), ("watchdog", "R-LATE")]


def test_a_reset_with_no_panic_is_an_event_and_a_non_watchdog_reset_is_not(reports):
    main, _ = reports
    write_reset(main)
    write_reset(main, faults="reset_in_1", incident="R2", name="ResetCounter-2.diag")
    evs = crash.events()
    assert [(e.kind, e.incident) for e in evs] == [("watchdog", RESET_INCIDENT)]


def test_an_unreadable_folder_is_reported_not_raised(reports, tmp_path, monkeypatch):
    main, retired = reports
    write_panic(retired)
    missing = tmp_path / "does-not-exist"
    found = crash.collect(roots=[missing, main, retired])
    assert [e.kind for e in found.events] == ["panic"] and found.unreadable == []     # absent is not "not readable"
    real = os.access
    monkeypatch.setattr(os, "access", lambda p, mode, **kw: False if str(p) == str(main) else real(p, mode, **kw))
    found = crash.collect(roots=[main, retired])
    assert found.unreadable == [str(main)] and [e.kind for e in found.events] == ["panic"]


def test_glob_failing_with_permission_error_is_reported(reports, monkeypatch):
    main, _ = reports

    def boom(self, pattern):
        raise PermissionError("denied")
    monkeypatch.setattr(type(main), "glob", boom)
    found = crash.collect(roots=[main])
    assert found.events == [] and found.unreadable == [str(main)]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads everything")
def test_an_unreadable_file_is_reported_and_skipped(reports):
    main, retired = reports
    p = write_panic(main)
    write_jetsam(main, PANIC_AT - dt.timedelta(minutes=21))
    p.chmod(0)
    try:
        found = crash.collect()
        assert found.unreadable == [str(p)] and [e.kind for e in found.events] == ["jetsam"]
    finally:
        p.chmod(0o600)


# --- the machine before it ----------------------------------------------------------------------------------

def test_context_summarises_the_half_hour_before_the_event(tmp_path):
    rec = tmp_path / "load.tsv"
    ev = crash.Panic(time=PANIC_AT)
    record_row(rec, PANIC_AT - dt.timedelta(minutes=45), swap_gb=20, sims=9)            # before the window: ignored
    record_row(rec, PANIC_AT - dt.timedelta(minutes=20), swap_gb=6, load1=40, sims=1, builds=1, claude=10, codex=3,
               top=[("Google Chrome", 5.0), ("java", 3.0)])
    record_row(rec, PANIC_AT - dt.timedelta(minutes=5), swap_gb=11.2, load1=512, sims=3, builds=4, claude=36, codex=17,
               lanes=5, top=[("Google Chrome", 6.1), ("java", 4.3), ("Claude", 2.0)], daemon_gb=4.3)
    record_row(rec, PANIC_AT + dt.timedelta(minutes=1), swap_gb=12, sims=9)             # after the event: ignored
    c = crash.context(ev, path=rec)
    assert c.rows == 2 and c.peak_swap_bytes == int(11.2 * GIB) and round(c.peak_swap_pct) == 47
    assert c.peak_load == 512 and c.max_sims == 3 and c.max_builds == 4 and c.max_agents == 53 and c.max_lanes == 5
    assert c.top[:2] == [("Google Chrome", 6.1), ("java", 4.3)] and c.last_gap_s == 300
    text = "\n".join(c.lines())
    assert "swap peak 11.2 GB (47% of RAM)" in text and "load peak 512" in text and "simulators max 3" in text
    assert "claude 36 / codex 17" in text and "JVM daemons 4.3 GB" in text and "top apps: Google Chrome 6.1 GB" in text
    assert c.to_json()["top"][0] == {"app": "Google Chrome", "gb": 6.1}


def test_context_says_so_plainly_when_the_recorder_was_off(tmp_path):
    ev = crash.Panic(time=PANIC_AT)
    for path in (tmp_path / "absent.tsv",):
        assert crash.context(ev, path=path).lines() == ["no load records in the 30 minutes before — the recorder agent was off"]
    rec = tmp_path / "load.tsv"
    record_row(rec, PANIC_AT - dt.timedelta(hours=3))                                   # only an old row
    assert crash.context(ev, path=rec).rows == 0
    rec.write_text("#header\nnot\ta\trow\n")
    assert crash.context(ev, path=rec).rows == 0


def test_context_reads_the_real_recorder_file_by_default(tmp_path):
    record_row(load.record_path(), PANIC_AT - dt.timedelta(minutes=2), swap_gb=3)
    assert crash.context(crash.Panic(time=PANIC_AT)).rows == 1


def test_nearest_jetsam_is_the_closest_before_within_two_hours(tmp_path):
    ev = crash.Panic(time=PANIC_AT)
    mk = lambda mins, i: crash.Jetsam(time=PANIC_AT - dt.timedelta(minutes=mins), incident=i)  # noqa: E731
    evs = [mk(200, "far"), mk(60, "mid"), mk(21, "near"), mk(-5, "after"), ev]
    assert crash.nearest_jetsam(ev, evs).incident == "near"
    assert crash.nearest_jetsam(ev, [mk(200, "far"), mk(-5, "after")]) is None


# --- advice -------------------------------------------------------------------------------------------------------

def adv(event=None, **ctx):
    jet = ctx.pop("jet", None)
    return crash.advice(event or crash.Panic(time=PANIC_AT), crash.Context(rows=3, **ctx), jet)


def test_advice_for_simulators_by_count_and_by_the_panicked_task():
    assert any("keep `guard.max_sims` at 2" in a and "3 simulators" in a for a in adv(max_sims=3))
    assert any("panicked task was simctl" in a for a in adv(crash.Panic(time=PANIC_AT, task="simctl"), max_sims=1))
    assert not any("simulators" in a for a in adv(max_sims=2))


def test_advice_for_jvm_daemons_names_the_gigabytes():
    a = adv(top=[("java", 4.5)])
    assert any("Gradle/Kotlin daemons held 4.5 GB: `./gradlew --stop`" in x for x in a)
    a = adv(max_daemon_bytes=int(2.5 * GIB))
    assert any("held 2.5 GB" in x for x in a)
    assert not any("Gradle" in x for x in adv(top=[("java", 0.4)]))
    jet = crash.Jetsam(time=PANIC_AT, top=[("java", int(3.2 * GIB), 2)])
    assert any("held 3.2 GB" in x for x in adv(jet=jet))


def test_advice_names_the_app_that_tops_the_list():
    a = adv(top=[("Google Chrome", 6.1), ("java", 0.5)])
    assert any("Google Chrome was the biggest app at 6.1 GB: close its tabs" in x for x in a)
    a = adv(top=[("Xcode", 5.0)])
    assert any("Xcode was the biggest app at 5.0 GB: quit or restart it" in x for x in a)
    assert not any("biggest app" in x for x in adv(top=[("Xcode", 1.0)]))
    assert not any("biggest app" in x for x in adv(top=[("java", 6.0)]))                # the JVM line covers it


def test_advice_for_memory_exhaustion_and_too_many_agents():
    a = adv(peak_swap_bytes=int(11.2 * GIB), peak_swap_pct=47.0)
    assert any(x.startswith("memory was exhausted: swap reached 11.2 GB (47% of RAM)") for x in a)
    assert not any("exhausted" in x for x in adv(peak_swap_bytes=int(8 * GIB), peak_swap_pct=39.9))
    assert any("53 agent sessions ran at once" in x for x in adv(max_agents=53, peak_swap_pct=10.0))
    assert not any("agent sessions" in x for x in adv(max_agents=53, peak_swap_pct=47.0, peak_swap_bytes=GIB))   # exhaustion says it


def test_advice_for_cpu_starvation_uses_the_core_count(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 10)
    assert any("load peaked at 512 on 10 cores with 4 builds" in x for x in adv(peak_load=512, max_builds=4))
    assert not any("starvation" in x for x in adv(peak_load=29))


def test_advice_with_no_load_records_says_how_to_get_them_and_nothing_is_filler():
    a = crash.advice(crash.Panic(time=PANIC_AT), crash.Context(), None)
    assert len(a) == 1 and "no load records" in a[0] and "teyla load --record" in a[0]
    assert crash.advice(crash.Panic(time=PANIC_AT), crash.Context(rows=3, max_sims=1), None) == []
    assert crash.advice(crash.Jetsam(time=PANIC_AT), crash.Context(), None) == []     # a jetsam alone: no recorder nag


def test_advice_is_at_most_four_lines():
    a = adv(crash.Panic(time=PANIC_AT, task="simctl"), max_sims=4, top=[("java", 5.0), ("Google Chrome", 9.0)], peak_swap_pct=60.0,
            peak_swap_bytes=14 * GIB, peak_load=900, max_builds=5, max_agents=60)
    assert len(a) == 4


# --- the report and the command ----------------------------------------------------------------------------------

def build_scene(reports, tmp_path, with_records=True):
    main, retired = reports
    write_panic(retired)
    write_reset(main)                                                       # absorbed by the panic
    write_jetsam(main, PANIC_AT - dt.timedelta(minutes=21), incident="J-NEAR")
    write_jetsam(main, PANIC_AT - dt.timedelta(minutes=200), incident="J-FAR")
    write_jetsam(main, PANIC_AT + dt.timedelta(minutes=70), incident="J-LATER")
    if with_records:
        rec = load.record_path()
        record_row(rec, PANIC_AT - dt.timedelta(minutes=3), swap_gb=11.2, load1=300, sims=3, builds=2, claude=30, codex=10,
                   top=[("Google Chrome", 6.1), ("java", 4.3), ("Claude", 2.0)])


def run_report(days=7):
    return crash.report(days, now=NOW)


def test_report_text_lists_newest_first_with_context_nearest_jetsam_and_advice(reports, tmp_path):
    build_scene(reports, tmp_path)
    text = crash.render(run_report())
    lines = text.splitlines()
    stamp = PANIC_AT.astimezone().strftime("%Y-%m-%d %H:%M")
    panic_line = (f"{stamp} kernel panic — Kernel data abort; panicked task simctl (pid 27899); "
                  "compressor OK, 21 swapfiles; last kext autofs   [new]")
    kinds = [ln.split(" ", 2)[2].split(" ")[0] for ln in lines if ln[:2] == "20"]
    assert kinds == ["jetsam", "kernel", "jetsam", "jetsam"]                          # newest first
    assert panic_line in lines
    i = lines.index(panic_line)
    assert lines[i + 1].startswith("    load before it: 1 record(s)")
    assert any("swap peak 11.2 GB (47% of RAM)" in ln for ln in lines[i:])
    near = next(ln for ln in lines[i:] if "nearest jetsam:" in ln)
    assert "(21 min earlier)" in near and "J-FAR" not in text
    assert any(ln.strip().startswith("top apps: Google Chrome 5.5 GB ×4, java 4.5 GB ×2") for ln in lines[i:])
    assert any(ln.strip().startswith("killed: ReportCrashService (per-process-limit)") for ln in lines[i:])
    assert "what to change:" in text and "  - simulators (3 simulators were booted)" in text
    assert text.rstrip().endswith("`teyla crash --ack` marks them seen (doctor and the banner stop warning)")


def test_report_with_no_events_and_with_unreadable_roots(reports, monkeypatch):
    assert crash.render(run_report(3)) == "no panic, watchdog reset or jetsam event in the last 3 days"
    main, _ = reports
    real = os.access
    monkeypatch.setattr(os, "access", lambda p, mode, **kw: False if str(p) == str(main) else real(p, mode, **kw))
    assert f"not readable: {main}" in crash.render(run_report())


def test_report_without_records_says_the_recorder_was_off(reports, tmp_path):
    build_scene(reports, tmp_path, with_records=False)
    text = crash.render(run_report())
    assert "no load records in the 30 minutes before — the recorder agent was off" in text


def test_a_jetsam_alone_gets_advice_from_its_own_numbers(reports):
    main, _ = reports
    write_jetsam(main, NOW - dt.timedelta(hours=1))
    text = crash.render(run_report())
    assert "Gradle/Kotlin daemons held 4.5 GB" in text and "Google Chrome was the biggest app at 5.5 GB" in text


def test_json_output_has_events_context_and_advice(reports, tmp_path, capsys):
    build_scene(reports, tmp_path)
    assert cli.main(["crash", "--days", "30", "--json"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["days"] == 30 and [e["kind"] for e in d["events"]] == ["jetsam", "panic", "jetsam", "jetsam"]
    panic = d["events"][1]
    assert panic["task"] == "simctl" and panic["new"] is True and panic["context"]["rows"] == 1
    assert panic["nearest_jetsam"]["incident"] == "J-NEAR" and d["advice"] and d["unreadable"] == []


def test_days_must_be_positive(capsys):
    assert cli.main(["crash", "--days", "0"]) == 2
    assert "--days must be 1 or more" in capsys.readouterr().err


# --- acknowledgement ---------------------------------------------------------------------------------------------

def args(**kw):
    return argparse.Namespace(**{"days": 7, "json": False, "ack": False, **kw})


def test_ack_round_trip(reports, tmp_path, capsys, monkeypatch):
    main, _ = reports
    write_panic(main, name="panic-x.panic")
    write_jetsam(main, NOW - dt.timedelta(hours=1), incident="J1")
    monkeypatch.setattr(crash, "recent", lambda days=7, roots=None, now=None: crash.collect(NOW - dt.timedelta(days=days)))
    assert crash.unacked(crash.events())[0].id == INCIDENT
    assert crash.cmd_crash(args(ack=True)) == 0
    out = capsys.readouterr().out
    assert "[new]" in out and "acknowledged 2 incident(s)" in out                    # the report as it was, then the ack
    assert crash.seen_path().read_text().split() == sorted([INCIDENT, "J1"])
    assert crash.seen_path().parent.name == "state" and (crash.seen_path().stat().st_mode & 0o077) == 0
    assert crash.unacked(crash.events()) == []
    assert crash.cmd_crash(args()) == 0
    again = capsys.readouterr().out
    assert "[new]" not in again and "unacknowledged" not in again
    assert crash.cmd_crash(args(ack=True)) == 0
    assert "nothing new to acknowledge" in capsys.readouterr().out


def test_ack_with_json_keeps_stdout_pure(reports, capsys):
    main, _ = reports
    write_panic(main)
    assert crash.cmd_crash(args(ack=True, json=True, days=30)) == 0
    cap = capsys.readouterr()
    json.loads(cap.out)
    assert "acknowledged 1 incident(s)" in cap.err


def test_ack_failure_is_reported(reports, capsys, monkeypatch):
    main, _ = reports
    write_panic(main)

    def boom(ids):
        raise OSError("read-only")
    monkeypatch.setattr(crash, "ack", boom)
    assert crash.cmd_crash(args(days=30)) == 0
    assert crash.cmd_crash(args(days=30, ack=True)) == 1
    assert "could not record the acknowledgement" in capsys.readouterr().err


def test_seen_file_with_blank_lines_and_a_missing_file(tmp_path):
    assert crash.seen_ids() == set()
    crash.seen_path().parent.mkdir(parents=True)
    crash.seen_path().write_text("A\n\n  B  \n")
    assert crash.seen_ids() == {"A", "B"}
    assert crash.ack(["B", "C", None]) == 1 and crash.seen_ids() == {"A", "B", "C"}


# --- doctor: machine:crash -> banner.items --------------------------------------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "HOME", h)
    monkeypatch.setattr(config, "TEYLA_DIR", h / ".teyla")
    from teyla import remind, routines
    monkeypatch.setattr(routines, "LINES_DIR", h / ".teyla" / "routines")          # the banner reads these too
    monkeypatch.setattr(remind, "REMINDERS_PATH", h / ".teyla" / "reminders.toml")
    return h


def fresh_panic(main):
    """A panic one hour ago, in terms of the real clock (doctor reads it)."""
    at = dt.datetime.now(UTC) - dt.timedelta(hours=1)
    write_panic(main, ps=panic_string("panic(cpu 9 caller 0x1): Kernel data abort. at pc 0x2", when=at), incident="FRESH-1")
    return at


def test_machine_crash_warns_on_an_unacknowledged_panic_and_the_warning_reaches_the_banner(reports, home):
    main, _ = reports
    fresh_panic(main)
    row = doctor._crash_check()
    assert row["level"] == "WARN" and row["name"] == "machine:crash"
    assert row["detail"].startswith("kernel panic ") and "Kernel data abort (simctl)" in row["detail"]
    assert row["fix"] == "teyla crash, then teyla crash --ack"
    p = digest.write_banner_items([row])
    items = p.read_text().splitlines()
    assert len(items) == 1 and items[0].startswith("WARN|machine:crash\tmachine:crash WARN: kernel panic ")
    assert digest.banner(p.read_text(), None).startswith("teyla: new — machine:crash WARN: kernel panic ")


def test_machine_crash_goes_quiet_once_acknowledged_and_for_jetsam_alone(reports, home):
    main, _ = reports
    write_jetsam(main, dt.datetime.now(UTC) - dt.timedelta(hours=2), incident="J-ONLY")
    row = doctor._crash_check()
    assert row["level"] == "INFO" and row["detail"] == "no new panic or watchdog reset in 7 days; 1 jetsam event(s)"
    assert digest.doctor_items([row]) == []
    fresh_panic(main)
    assert doctor._crash_check()["level"] == "WARN"
    crash.ack(["FRESH-1"])
    row = doctor._crash_check()
    assert row["level"] == "INFO" and "(1 acknowledged)" in row["detail"]


def test_machine_crash_counts_extra_incidents_and_ignores_old_ones(reports, home):
    main, _ = reports
    now = dt.datetime.now(UTC)
    for i, hours in enumerate((1, 5)):
        write_panic(main, ps=panic_string("panic(cpu 1 caller 0x1): x", when=now - dt.timedelta(hours=hours)), incident=f"P{i}",
                    name=f"panic-{i}.panic")
    assert doctor._crash_check()["detail"].endswith("(+1 more)")
    write_panic(main, ps=panic_string("panic(cpu 1 caller 0x1): x", when=now - dt.timedelta(days=9)), incident="OLD", name="panic-old.panic")
    crash.ack(["P0", "P1"])
    assert doctor._crash_check()["level"] == "INFO"                                  # the 9-day-old one is outside the window


def test_machine_crash_never_breaks_doctor(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(crash, "doctor_row", boom)
    row = doctor._crash_check()
    assert row["level"] == "INFO" and "disk on fire" in row["detail"]


def test_doctor_only_scans_the_reports_with_the_repo_scan(monkeypatch):
    calls = []
    monkeypatch.setattr(crash, "doctor_row", lambda *a, **k: (calls.append(1), ("INFO", "x", None))[1])
    monkeypatch.setattr(doctor, "_load_check", lambda cfg: doctor._check("INFO", "machine:load", "OK"))
    assert "machine:crash" not in {c["name"] for c in doctor.checks(scan_repos=False)} and calls == []


# --- digest ----------------------------------------------------------------------------------------------------------

def test_digest_candidate_ranks_an_unacknowledged_panic_first_and_only_then(reports):
    main, _ = reports
    assert crash.digest_candidates() == []
    fresh_panic(main)
    (c,) = crash.digest_candidates()
    assert c["rank"] == 1 and c["id"] == "crash:panic" and c["step"] == "teyla crash" and c["cmd"] is True
    assert c["text"].startswith("kernel panic ")
    crash.ack(["FRESH-1"])
    assert crash.digest_candidates() == []


def test_digest_write_puts_the_panic_at_the_top(reports, home, monkeypatch):
    main, _ = reports
    fresh_panic(main)
    from teyla import models_watch, rules_lifecycle, tidy
    for mod in (rules_lifecycle, models_watch, tidy):
        monkeypatch.setattr(mod, "digest_candidates", lambda *a, **k: [])
    lines = digest.write([], [], [], today=dt.date(2026, 10, 9), notify_now=False)
    assert any("kernel panic" in ln and "teyla crash" in ln for ln in lines), lines
    first_item = next(ln for ln in lines if ln.lstrip().startswith("1"))
    assert "kernel panic" in first_item


def test_digest_write_survives_a_failing_crash_scan(reports, home, monkeypatch):
    from teyla import models_watch, rules_lifecycle, tidy
    for mod in (rules_lifecycle, models_watch, tidy):
        monkeypatch.setattr(mod, "digest_candidates", lambda *a, **k: [])
    monkeypatch.setattr(crash, "recent", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert crash.digest_candidates() == []
    assert digest.write([], [], [], today=dt.date(2026, 10, 9), notify_now=False)

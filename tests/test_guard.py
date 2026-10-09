"""`teyla guard tick|status` — record, alert file, notification, idle JVM daemon reaper.

Hermetic: `ps`, `sysctl` and `osascript` are faked, the clock is a number the test moves, signals go to a
recorder, and every file lands under the suite's tmp TEYLA_HOME (conftest) — nothing reads the real
process table, sends a signal or notifies.
"""
from __future__ import annotations

import argparse
import os
import time

import pytest

from teyla import cli, config, guard, load, storage, storage_procs

GIB = 1024 ** 3
RAM = 24 * GIB
OK_SYSCTL = "25769803776\n10\n{ 1.50 2.00 3.00 }\ntotal = 1024.00M  used = 512.00M  free = 512.00M  (encrypted)\n1\n1073741824\n"
CRIT_SYSCTL = ("25769803776\n10\n{ 579.67 508.27 442.81 }\n"
               "total = 13312.00M  used = 11734.19M  free = 1577.81M  (encrypted)\n4\n12884901888\n")
GRADLE_DAEMON = ("/jdk/bin/java -Xmx2g -cp /g/lib/gradle-launcher.jar "
                 "org.gradle.launcher.daemon.bootstrap.GradleDaemon 8.10")
KOTLIN_DAEMON = ("/jdk/bin/java -cp /k/kotlin-compiler-embeddable-2.0.jar "
                 "org.jetbrains.kotlin.daemon.KotlinCompileDaemon --daemon-runFilesPath=/tmp")
UID = 501


def etime(seconds: int) -> str:
    d, rest = divmod(int(seconds), 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    return (f"{d}-" if d else "") + f"{h:02d}:{m:02d}:{s:02d}"


class Clock:
    def __init__(self, hh=20, mm=21):
        self.t = time.mktime((2026, 10, 9, hh, mm, 0, 0, 0, -1))

    def __call__(self):
        return self.t

    def advance(self, minutes=1.0):
        self.t += minutes * 60


class Machine:
    """A fake `ps`, `sysctl` and the signalling side of the machine."""

    def __init__(self, clock: Clock, sysctl=OK_SYSCTL):
        self.clock = clock
        self.sysctl = sysctl
        self.ps_fails = False
        self.procs: dict[int, dict] = {}
        self.signals: list[tuple[int, int]] = []
        self.notes: list[list] = []
        self.lookup_patch: dict[int, dict] = {}     # what `ps -p` shows for a pid after the snapshot was taken
        self.add(1, "/sbin/launchd", ppid=0, uid=0, started_s_ago=86400)    # an empty process table reads as "ps failed"

    def add(self, pid, command, started_s_ago=3600, rss_kb=1000, cpu="0.0", ppid=1, uid=UID):
        self.procs[pid] = dict(command=command, start=self.clock.t - started_s_ago, rss_kb=rss_kb, cpu=cpu, ppid=ppid, uid=uid)
        return pid

    def lstart(self, pid):
        return time.strftime("%a %b %e %H:%M:%S %Y", time.localtime(self.procs[pid]["start"]))

    def run(self, cmd, timeout=60):
        if cmd[0] == "sysctl":
            return 0, self.sysctl
        if cmd[0] == "ps" and cmd[1] == "-Ao":
            if self.ps_fails:
                return 1, ""
            return 0, "\n".join(f"{pid:>6} {p['ppid']:>6} {p['rss_kb']:>8} {p['cpu']:>5} {etime(self.clock.t - p['start']):>11} {p['command']}"
                                for pid, p in self.procs.items())
        if cmd[0] == "ps" and cmd[1] == "-o":                        # storage_procs.lookup
            pid = int(cmd[-1])
            p = self.procs.get(pid)
            if p is None:
                return 1, ""
            p = {**p, **self.lookup_patch.get(pid, {})}
            lstart = time.strftime("%a %b %e %H:%M:%S %Y", time.localtime(p["start"]))
            return 0, f"{pid} {p['ppid']} {p['uid']} ?? {p['rss_kb']} {etime(self.clock.t - p['start'])} {lstart} {p['command']}"
        return 127, ""

    def kill(self, pid, sig):
        self.signals.append((pid, sig))
        self.procs.pop(pid, None)                                      # the process obeys

    def notify_run(self, cmd, timeout=60):
        self.notes.append([cmd, timeout])
        return 0, ""

    def env(self, platform="darwin"):
        ctx = storage_procs.Ctx(run=self.run, kill=self.kill, sleep=lambda s: self.clock.advance(s / 60), watch=lambda pid: None,
                                uid=UID, self_pid=os.getpid())
        return guard.Env(run=self.run, notify_run=self.notify_run, ctx=ctx, now=self.clock, platform=platform)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def m(clock, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "LOG_PATH", tmp_path / "storage.log")
    return Machine(clock)


def conf(**kw):
    return load.guard_conf({"guard": kw})


def tick(m, dry=False, platform="darwin", **kw):
    return guard.tick(conf(**kw), m.env(platform), dry=dry)


def alert_lines():
    p = guard.alert_path()
    return p.read_text().splitlines() if p.exists() else None


def storage_log(tmp_path):
    p = tmp_path / "storage.log"
    return p.read_text() if p.exists() else ""


# --- record -------------------------------------------------------------------------------------------

def test_tick_records_a_row_and_writes_no_alert_when_ok(m):
    res = tick(m)
    assert res["verdict"].level == load.OK
    rows = load.read_records()
    assert len(rows) == 1 and rows[0]["level"] == "OK"
    assert alert_lines() is None and m.notes == []
    tick(m)
    assert len(load.read_records()) == 2


def test_tick_does_nothing_when_the_guard_is_off_or_ps_fails(m):
    assert tick(m, enabled=False)["verdict"] is None and load.read_records() == []
    m.ps_fails = True
    res = tick(m)
    assert res["verdict"] is None and "could not read the process table" in res["lines"][0]
    assert load.read_records() == [] and alert_lines() is None


def test_tick_makes_no_simctl_or_lsof_call(m):
    seen = []
    base = m.run
    m.run = lambda cmd, timeout=60: seen.append(cmd[0]) or base(cmd, timeout)
    tick(m)
    assert set(seen) == {"ps", "sysctl"}


# --- the alert file -----------------------------------------------------------------------------------------

def test_critical_writes_the_alert_with_a_since_that_survives_consecutive_ticks(m, clock):
    m.sysctl = CRIT_SYSCTL
    m.add(10, "/Applications/Foo.app/Contents/MacOS/Foo", rss_kb=3_000_000)
    m.add(11, "/Applications/Bar.app/Contents/MacOS/Bar", rss_kb=2_000_000)
    m.add(12, "/Applications/Baz.app/Contents/MacOS/Baz", rss_kb=1_000_000)
    m.add(13, "/Applications/Qux.app/Contents/MacOS/Qux", rss_kb=500_000)
    tick(m)
    lines = alert_lines()
    assert lines[0].startswith("machine CRITICAL since 20:21 — ")
    assert "swap 11.5 GB = 48% of RAM" in lines[0] and "load 580 on 10 cores" in lines[0]
    assert "(critical" not in lines[0] and lines[0].endswith("Do not start builds or boot simulators; run teyla load.")
    assert [ln.strip() for ln in lines[1:]] == ["Foo 2.9 GB", "Bar 1.9 GB", "Baz 1.0 GB"]
    clock.advance(7)
    m.procs[13]["rss_kb"] = 9_000_000
    tick(m)
    lines = alert_lines()
    assert lines[0].startswith("machine CRITICAL since 20:21 — "), "the start of the incident is kept"
    assert lines[1].strip() == "Qux 8.6 GB", "the apps are fresh every tick"
    assert not list(guard.alert_path().parent.glob("load.alert.*.tmp")), "written atomically, no tmp left"


def test_the_alert_goes_after_three_ticks_below_critical_and_flapping_does_not_clear_it(m, clock):
    m.sysctl = CRIT_SYSCTL
    tick(m)
    m.sysctl = OK_SYSCTL
    for _ in range(2):
        clock.advance()
        tick(m)
    assert alert_lines() is not None
    m.sysctl = CRIT_SYSCTL                 # flaps back: the counter starts over, the incident is the same
    clock.advance()
    tick(m)
    assert alert_lines()[0].startswith("machine CRITICAL since 20:21")
    m.sysctl = OK_SYSCTL
    for i in range(3):
        assert alert_lines() is not None
        clock.advance()
        res = tick(m)
    assert alert_lines() is None and any("alert removed" in ln for ln in res["lines"])
    m.sysctl = CRIT_SYSCTL                 # a new incident has a new start
    clock.advance(5)
    tick(m)
    assert alert_lines()[0].startswith(f"machine CRITICAL since {time.strftime('%H:%M', time.localtime(clock.t))}")


def test_busy_alone_writes_no_alert(m):
    m.sysctl = "25769803776\n10\n{ 45.00 20.00 10.00 }\ntotal = 1024.00M  used = 512.00M  free = 512.00M  (encrypted)\n1\n0\n"
    assert tick(m)["verdict"].level == load.BUSY
    assert alert_lines() is None


def test_alert_false_writes_nothing_and_removes_a_leftover(m):
    m.sysctl = CRIT_SYSCTL
    tick(m, alert=False)
    assert alert_lines() is None and m.notes == []
    guard.alert_path().write_text("machine CRITICAL since 01:00 — old\n")
    tick(m, alert=False)
    assert alert_lines() is None
    assert load.read_records()[-1]["level"] == "CRITICAL", "recording does not depend on the alert"


def test_dry_run_records_writes_and_notifies_nothing(m):
    m.sysctl = CRIT_SYSCTL
    res = tick(m, dry=True)
    assert res["verdict"].level == load.CRITICAL
    assert load.read_records() == [] and alert_lines() is None and m.notes == []
    assert not (storage.state_dir() / guard.ALERT_STATE).exists()


# --- the notification ---------------------------------------------------------------------------------------

def test_notification_only_on_entering_critical_and_at_most_every_30_minutes(m, clock):
    m.sysctl = CRIT_SYSCTL
    tick(m)
    assert len(m.notes) == 1
    cmd, timeout = m.notes[0]
    assert cmd[:2] == ["osascript", "-e"] and timeout == 5
    assert cmd[2].startswith('display notification "CRITICAL since 20:21: ') and cmd[2].endswith('with title "Teyla: machine overloaded"')
    for _ in range(5):                                  # still critical: no new notification
        clock.advance()
        tick(m)
    assert len(m.notes) == 1
    m.sysctl = OK_SYSCTL
    for _ in range(3):
        clock.advance()
        tick(m)
    assert alert_lines() is None
    m.sysctl = CRIT_SYSCTL                              # a new incident 10 minutes after the first: rate-limited
    clock.advance(1)
    tick(m)
    assert len(m.notes) == 1 and alert_lines() is not None, "the alert is still written"
    m.sysctl = OK_SYSCTL
    for _ in range(3):
        clock.advance()
        tick(m)
    clock.advance(31)
    m.sysctl = CRIT_SYSCTL
    tick(m)
    assert len(m.notes) == 2


def test_no_notification_in_safe_mode_or_off_macos(m, monkeypatch):
    m.sysctl = CRIT_SYSCTL
    monkeypatch.setenv("TEYLA_SAFE", "1")
    tick(m)
    assert m.notes == [] and alert_lines() is not None, "safe mode still writes the alert file"
    monkeypatch.delenv("TEYLA_SAFE")
    guard.alert_path().unlink()
    (storage.state_dir() / guard.ALERT_STATE).unlink()
    tick(m, platform="linux")
    assert m.notes == [] and alert_lines() is not None
    guard.alert_path().unlink()
    (storage.state_dir() / guard.ALERT_STATE).unlink()
    tick(m)
    assert len(m.notes) == 1


def test_the_notification_text_is_escaped_for_applescript():
    assert guard._applescript('a "b" \\c') == 'a \\"b\\" \\\\c'


# --- reaping idle daemons -----------------------------------------------------------------------------------

def state_files():
    d = storage.state_dir(guard.GUARD_STATE)
    return sorted(f.name for f in d.iterdir()) if d.is_dir() else []


def test_an_idle_gradle_daemon_is_stopped_after_the_limit(m, clock, tmp_path):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200, rss_kb=1_048_576)
    tick(m)
    assert state_files() == ["100"] and m.signals == []
    clock.advance(29)
    tick(m)
    assert m.signals == []
    clock.advance(2)
    res = tick(m)
    assert m.signals == [(100, 15)] and 100 not in m.procs
    assert any(ln.startswith("stopped gradle daemon pid 100 (1.0 GB), idle 31m") for ln in res["lines"])
    assert "guard stopped gradle daemon pid 100 1.0GB idle 31m" in storage_log(tmp_path)
    assert state_files() == []


def test_a_gradle_client_or_cpu_makes_a_daemon_not_idle(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m)
    assert state_files() == ["100"]
    client = m.add(101, "/bin/sh ./gradlew assembleDebug")
    clock.advance(40)
    tick(m)
    assert m.signals == [] and state_files() == [], "a client runs: the idle clock is forgotten"
    del m.procs[client]
    tick(m)
    assert state_files() == ["100"], "idle again: the clock starts over"
    clock.advance(40)
    m.procs[100]["cpu"] = "35.0"
    tick(m)
    assert m.signals == [] and state_files() == []
    m.procs[100]["cpu"] = "0.4"
    tick(m)
    clock.advance(31)
    tick(m)
    assert m.signals == [(100, 15)], "under 1% CPU counts as idle"


def test_a_kotlin_daemon_waits_for_kotlinc_as_well(m, clock):
    m.add(200, KOTLIN_DAEMON, started_s_ago=7200)
    tick(m)
    kc = m.add(201, "/opt/kotlinc/bin/kotlinc Main.kt")
    clock.advance(40)
    tick(m)
    assert m.signals == [] and state_files() == []
    del m.procs[kc]
    tick(m)
    clock.advance(31)
    tick(m)
    assert m.signals == [(200, 15)]


def test_a_gradle_daemon_is_not_held_by_kotlinc(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    m.add(201, "/opt/kotlinc/bin/kotlinc Main.kt")
    tick(m)
    clock.advance(31)
    tick(m)
    assert (100, 15) in m.signals


def test_gradle_idle_min_zero_turns_the_reaper_off(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m, gradle_idle_min=0)
    clock.advance(600)
    tick(m, gradle_idle_min=0)
    assert m.signals == [] and state_files() == []


def test_dry_run_reports_what_it_would_stop_and_changes_nothing(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m)
    clock.advance(45)
    before = state_files()
    res = tick(m, dry=True)
    assert any(ln.startswith("would stop gradle daemon pid 100") and "idle 45m" in ln for ln in res["lines"])
    assert m.signals == [] and 100 in m.procs and state_files() == before


def test_dry_run_does_not_start_an_idle_clock(m):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m, dry=True)
    assert state_files() == []


@pytest.mark.parametrize("patch", [{"start": -3 * 3600}, {"command": "/usr/bin/python3 server.py"}, {"uid": 0}],
                         ids=["start-time", "command", "uid"])
def test_the_pid_is_rechecked_before_the_signal(m, clock, patch):
    """The snapshot said "idle gradle daemon"; by the time of the signal the pid is someone else's."""
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m)
    clock.advance(40)
    start = m.procs[100]["start"]
    m.lookup_patch[100] = {k: start + v if k == "start" else v for k, v in patch.items()}
    res = tick(m)
    assert m.signals == [] and 100 in m.procs
    assert any(ln.startswith("skipped gradle daemon pid 100") for ln in res["lines"])
    assert state_files() == []


def test_a_recycled_pid_does_not_inherit_the_idle_time(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m)
    clock.advance(40)
    m.procs[100]["start"] = clock.t - 60                    # the old daemon died; a new one got the pid
    tick(m)
    assert m.signals == [], "the new daemon has been idle for no time at all"


def test_other_users_daemons_and_other_java_are_never_touched(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200, uid=0)             # root's daemon, idle for hours
    m.add(101, "/jdk/bin/java -jar /apps/server.jar", started_s_ago=7200)
    d = storage.state_dir(guard.GUARD_STATE)
    d.mkdir(parents=True)
    for pid in (100, 101):                                          # both have an old idle clock on file
        start = int(m.procs[pid]["start"])
        (d / str(pid)).write_text(f"{start} {start}\n")
    clock.advance(60)
    res = tick(m)
    assert m.signals == [] and 100 in m.procs and 101 in m.procs
    assert any(ln.startswith("skipped gradle daemon pid 100") for ln in res["lines"]), "root's daemon was a candidate and was refused"
    assert state_files() == [], "pid 101 is not a daemon: its clock is dropped"


def test_state_of_vanished_daemons_is_cleaned_up(m):
    d = storage.state_dir(guard.GUARD_STATE)
    d.mkdir(parents=True)
    (d / "999").write_text("1 1\n")
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m)
    assert state_files() == ["100"]


def test_a_daemon_that_ignores_sigterm_gets_sigkill_once(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m)
    clock.advance(40)

    env = m.env()

    def stubborn(pid, sig):
        m.signals.append((pid, sig))
        if sig == 9:
            m.procs.pop(pid, None)
    env.ctx.kill = stubborn
    res = guard.tick(conf(), env)
    assert m.signals == [(100, 15), (100, 9)]
    assert any("killed with SIGKILL" in ln for ln in res["lines"])


# --- the command never raises ---------------------------------------------------------------------------

def args(**kw):
    return argparse.Namespace(**{"quiet": False, "dry": False, "action": "tick", **kw})


def test_cmd_tick_swallows_errors_and_exits_zero(m, capsys):
    def boom(cmd, timeout=60):
        raise RuntimeError("ps exploded")
    env = m.env()
    env.run = boom
    assert guard.cmd_tick(args(), env) == 0
    err = capsys.readouterr().err
    assert "RuntimeError: ps exploded" in err


def test_cmd_tick_quiet_prints_only_what_was_done(m, clock, capsys):
    assert guard.cmd_tick(args(quiet=True), m.env()) == 0
    assert capsys.readouterr().out == ""
    m.sysctl = CRIT_SYSCTL
    guard.cmd_tick(args(quiet=True), m.env())
    out = capsys.readouterr().out
    assert "alert written" in out and "load: CRITICAL" not in out
    guard.cmd_tick(args(), m.env())
    assert capsys.readouterr().out.startswith("load: CRITICAL")


def test_status_shows_rows_alert_and_state(m, clock, capsys):
    assert "no rows yet" in guard.status_lines()[0]
    m.sysctl = CRIT_SYSCTL
    tick(m)
    text = "\n".join(guard.status_lines(now=clock.t + 30))
    assert "CRITICAL" in text and "alert: " in text and "machine CRITICAL since 20:21" in text
    assert "state: CRITICAL since 20:21, 0/3 ticks below CRITICAL" in text and "agent=False" in text
    assert cli.main(["guard", "status"]) in (0, None)
    assert "config: enabled=True" in capsys.readouterr().out


def test_the_command_is_registered(capsys):
    with pytest.raises(SystemExit):
        cli.main(["guard", "nonsense"])
    assert "tick" in capsys.readouterr().err


def test_a_daemon_that_got_busy_again_before_the_signal_is_spared(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m)
    clock.advance(31)
    full_ps = m.run
    calls = {"n": 0}

    def busy_on_second_look(cmd, timeout=60):
        if cmd[0] == "ps" and cmd[1] == "-Ao":
            calls["n"] += 1
            if calls["n"] == 2:                           # the re-check right before the signal
                m.procs[100]["cpu"] = "55.0"
        return full_ps(cmd, timeout)

    m.run = busy_on_second_look
    res = tick(m)
    assert m.signals == [] and 100 in m.procs
    assert any("pid 100: busy again" in ln for ln in res["lines"])


def test_a_gradle_build_started_since_the_snapshot_spares_every_daemon(m, clock):
    m.add(100, GRADLE_DAEMON, started_s_ago=7200)
    tick(m)
    clock.advance(31)
    full_ps = m.run
    calls = {"n": 0}

    def client_on_second_look(cmd, timeout=60):
        if cmd[0] == "ps" and cmd[1] == "-Ao":
            calls["n"] += 1
            if calls["n"] == 2:
                m.add(300, "/jdk/bin/java -cp /w/gradle-wrapper.jar org.gradle.wrapper.GradleWrapperMain assembleDebug")
        return full_ps(cmd, timeout)

    m.run = client_on_second_look
    res = tick(m)
    assert m.signals == []
    assert any("a Gradle build started" in ln for ln in res["lines"])


def test_switching_alerts_off_forgets_the_incident(m, clock):
    m.sysctl = CRIT_SYSCTL
    tick(m)
    first = alert_lines()[0]
    tick(m, alert=False)                                  # off during the incident; it ends while off
    clock.advance(120)
    tick(m)                                               # back on, a later CRITICAL: a new incident
    assert alert_lines()[0] != first and "since 22:2" in alert_lines()[0]
    assert len(m.notes) == 2


def test_a_jar_on_some_apps_classpath_is_not_a_build_daemon(m, clock):
    m.add(100, "/jdk/bin/java -cp /k/kotlin-compiler-embeddable-2.0.jar:/app.jar com.example.Server", started_s_ago=7200)
    m.add(101, "/jdk/bin/java -cp /g/gradle-launcher.jar com.example.UsesGradleTooling", started_s_ago=7200)
    tick(m)
    clock.advance(60)
    tick(m)
    assert m.signals == [] and state_files() == []


def test_a_build_seen_on_the_second_look_restarts_the_idle_clock(m, clock):
    test_a_gradle_build_started_since_the_snapshot_spares_every_daemon(m, clock)
    m.procs.pop(300)                                      # the build ends before the next tick
    tick(m)
    assert m.signals == [] and 100 in m.procs             # idle again from now, not from before the build

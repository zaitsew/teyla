"""`teyla storage apps` and step 7 of `guard tick` — quit listed apps that nobody used for hours.

Hermetic: `lsappinfo`, `ps` and `docker` are a fake `Mac`, the quit request goes to a recorder, the clock is a number
the test moves, and every file lands under the suite's tmp TEYLA_HOME (conftest). Nothing quits a real app,
reads the real process table or touches the real ~/.teyla.
"""
from __future__ import annotations

import argparse
import json

import pytest

from teyla import config, features, guard, load, storage_apps as sa

GIB = 1024 ** 3
RAM = 24 * GIB
T0 = 1_800_000_000.0
HOUR = 3600.0
OK_SYSCTL = "25769803776\n10\n{ 1.50 2.00 3.00 }\ntotal = 1024.00M  used = 512.00M  free = 512.00M  (encrypted)\n4\n1073741824\n"

LSAPPINFO = ''' 1) "loginwindow" ASN:0x0-0x2002:
    bundleID="com.apple.loginwindow"
    bundle path="/System/Library/CoreServices/loginwindow.app"
    pid = 419 token=[sess=1 pid=419 uid:0,0,4294967295 g:0,0 pV:950] type="UIElement" flavor=3 Version="1" fileType="APPL"
 2) "Finder" ASN:0x0-0x9009:
    bundleID="com.apple.finder"
    bundle path="/System/Library/CoreServices/Finder.app"
    pid = 651 token=[sess=1 pid=651 uid:501,501,501 g:20,20 pV:1591] type="Foreground" flavor=3 Version="1" fileType="FNDR"
 3) "Docker" ASN:0x0-0x1e90e8f:
    bundleID="com.docker.docker"
    bundle path="/Applications/Docker.app"
    pid = 700 token=[sess=1 pid=700 uid:501,501,501 g:20,20 pV:2310] type="Foreground" flavor=3 Version="1" fileType="APPL"
 4) "Docker Desktop" ASN:0x0-0x1e91e90:
    bundleID="com.electron.dockerdesktop"
    bundle path="/Applications/Docker.app/Contents/MacOS/Docker Desktop.app"
    pid = 701 token=[sess=1 pid=701 uid:501,501,501 g:20,20 pV:2310] type="Foreground" flavor=3 Version="1" fileType="APPL"
 5) "Helper" ASN:0x0-0x3:
    bundleID=[ NULL ]
    bundle path="/usr/sbin/helperd"
    pid = 702 token=[sess=1 pid=702 uid:501,501,501 g:20,20 pV:2310] !signalled type="BackgroundOnly" flavor=3 Version=[ NULL ]
 6) "Notes" ASN:0x0-0x3e1ae17: (in front)
    bundleID="com.example.notes"
    bundle path="/Applications/Notes.app"
    pid = 800 token=[sess=1 pid=800 uid:501,501,501 g:20,20 pV:2310] type="Foreground" flavor=3 Version="1" fileType="APPL"
'''


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds

    def minutes(self, n):
        self.t += n * 60

    def hours(self, n):
        self.t += n * HOUR


class Mac:
    """A fake `lsappinfo`, `ps` and `docker`, and the quit request."""

    def __init__(self):
        self.apps: dict[str, dict] = {}          # bundle id -> app
        self.front: str | None = None
        self.next_pid = 1000
        self.calls: list[list[str]] = []
        self.quit_calls: list[str] = []
        self.stubborn: set[str] = set()          # an unsaved-changes dialog: terminate is accepted, the app stays
        self.docker = (0, "")
        self.lsappinfo_fails = False
        self.add("Finder", "com.apple.finder", mb=1)                 # an empty `lsappinfo` reads as a failed one

    def add(self, name, bundle, mb=500, folder=None, kind="Foreground", front=False):
        folder = folder or name
        self.apps[bundle] = dict(name=name, bundle=bundle, folder=folder, pid=self.next_pid, mb=mb, kind=kind)
        self.next_pid += 1
        if front:
            self.front = bundle
        return bundle

    def remove(self, bundle):
        self.apps.pop(bundle, None)
        if self.front == bundle:
            self.front = None

    def run(self, cmd, timeout=60):
        self.calls.append(list(cmd))
        if cmd[0] == "lsappinfo":
            if self.lsappinfo_fails:
                return 1, ""
            out = []
            for i, a in enumerate(self.apps.values(), 1):
                mark = "(in front) " if a["bundle"] == self.front else ""
                out.append(f' {i}) "{a["name"]}" ASN:0x0-0x{i:x}: {mark}\n    bundleID="{a["bundle"]}"\n'
                           f'    bundle path="/Applications/{a["folder"]}.app"\n'
                           f'    pid = {a["pid"]} token=[sess=1] type="{a["kind"]}" flavor=3 Version="1"\n')
            return 0, "".join(out)
        if cmd[0] == "ps":
            rows = [f"{a['pid']:>6} 1 {a['mb'] * 1024:>8} 0.0 01:00:00 /Applications/{a['folder']}.app/Contents/MacOS/{a['folder']}"
                    for a in self.apps.values()]
            return 0, "\n".join(rows + ["     1     0     1000 0.0 05-00:00:00 /sbin/launchd"])
        if cmd[0] == "docker":
            return self.docker
        if cmd[0] == "sysctl":
            return 0, OK_SYSCTL
        return 127, ""

    def quit_app(self, bundle):
        self.quit_calls.append(bundle)
        if bundle not in self.apps:
            return "not-running"
        if bundle not in self.stubborn:
            self.remove(bundle)
        return "requested"

    def subprocess_calls(self):
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    monkeypatch.setattr(config, "HOME", tmp_path / "home")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def mac():
    return Mac()


def ctx_of(mac, clock, platform="darwin"):
    return sa.Ctx(run=mac.run, quit_app=mac.quit_app, now=clock, sleep=lambda s: clock.advance(s), platform=platform)


def conf(**kw):
    kw.setdefault("apps_quit", "on")
    kw.setdefault("apps_quit_list", ["Slack", "Big", "Small", "Docker"])
    return load.guard_conf({"guard": kw})


def snapshot(pressure=1, compressor=0, disk_free=500 * GIB, load1=1.0):
    return load.Snapshot(time="2026-11-05T10:00:00+00:00", ram_bytes=RAM, ncpu=10, load1=load1, pressure=pressure,
                         compressor_bytes=compressor, disk_free_bytes=disk_free)


TIGHT = snapshot(pressure=2)
CALM = snapshot()


def tick(mac, clock, c=None, snap=TIGHT, trend=None, notify=None, dry=False, platform="darwin"):
    return sa.tick(c or conf(), snap, trend, ctx_of(mac, clock, platform), notify, dry=dry)


def journal_rows():
    return sa.read_journal(0)


def actions():
    return [(r["action"], r["app"]) for r in journal_rows()]


def settle(mac, clock, c=None, hours=5):
    """Let the tick see the apps, then let them go idle."""
    tick(mac, clock, {**(c or conf()), "apps_quit": "on"}, snap=CALM)
    clock.hours(hours)


# --- reading lsappinfo -----------------------------------------------------------------------------

def test_lsappinfo_parse_reads_foreground_apps_front_marker_and_the_outer_app_folder():
    apps = {a.name: a for a in sa.parse_lsappinfo(LSAPPINFO)}
    assert set(apps) == {"Finder", "Docker", "Docker Desktop", "Notes"}          # UIElement and BackgroundOnly are left out
    assert [a.name for a in apps.values() if a.front] == ["Notes"]
    assert apps["Docker"].bundle_id == "com.docker.docker" and apps["Docker"].pid == 700
    # "Docker Desktop" lives inside Docker.app: its memory is the `ps` rows folded under "Docker"
    assert apps["Docker Desktop"].folder == "Docker" and apps["Docker"].folder == "Docker"


def test_memory_folds_helpers_and_maps_docker_desktop_to_the_docker_folder(mac, clock):
    ps = ("  900 1 102400 0.0 01:00 /Applications/Docker.app/Contents/MacOS/com.docker.backend run\n"
          "  901 1 204800 0.0 01:00 /Applications/Docker.app/Contents/MacOS/Docker Desktop.app/Contents/MacOS/Docker Desktop --x\n"
          "  902 1  51200 0.0 01:00 /Applications/Slack.app/Contents/Frameworks/Slack Helper (Renderer).app/Contents/MacOS/Slack Helper (Renderer) --type=renderer\n"
          "  903 1  51200 0.0 01:00 /Applications/Slack.app/Contents/MacOS/Slack\n")
    ctx = sa.Ctx(run=lambda cmd, timeout=60: (0, ps), now=clock, platform="darwin")
    mem = sa.memory_by_folder(ctx)
    assert mem["docker"] == 300 * 1024 ** 2 and mem["slack"] == 100 * 1024 ** 2


def test_a_failing_lsappinfo_changes_nothing(mac, clock):
    mac.lsappinfo_fails = True
    assert tick(mac, clock) == ["apps: `lsappinfo list` failed; nothing changed"]
    assert not sa.state_path().exists() and not sa.journal_path().exists()


# --- who is protected, who is listed -----------------------------------------------------------------

@pytest.mark.parametrize("name,bundle", [("Safari", "com.apple.Safari"), ("Finder", "com.apple.finder"),
                                         ("iTerm2", "com.googlecode.iterm2"), ("Google Chrome", "com.google.Chrome"),
                                         ("Teyla Console", "com.example.teylaconsole"), ("Claude", "com.anthropic.claudefordesktop")])
def test_protected_beats_the_list(mac, clock, name, bundle):
    mac.add(name, bundle)
    mac.add("Slack", "com.example.slack", mb=100)
    c = conf(apps_quit_list=[name, bundle, "Slack"])
    settle(mac, clock, c)
    tick(mac, clock, c)
    assert mac.quit_calls == ["com.example.slack"]
    rows = {r.app.name: r.status for r in sa.classify(sa.running_apps(ctx_of(mac, clock)), sa.load_state(), sa.settings(c), {}, clock())}
    assert rows[name] == sa.PROTECTED


def test_a_list_entry_matches_name_folder_or_bundle_id_in_any_case(mac, clock):
    mac.add("Docker Desktop", "com.example.dd", folder="DD App")
    app = sa.parse_lsappinfo(mac.run(["lsappinfo", "list"])[1])[-1]
    for entry in ("docker desktop", "DD APP", "dd app.app", "COM.EXAMPLE.DD"):
        assert sa.is_listed(app, [entry])
    assert not sa.is_listed(app, ["docker", "com.example"]) and not sa.is_listed(app, [])


def test_an_app_without_a_bundle_id_is_never_quit(mac, clock):
    apps = sa.parse_lsappinfo(' 1) "Odd" ASN:0x0-0x1: \n    bundleID=[ NULL ] \n    bundle path="/Applications/Odd.app"\n'
                              '    pid = 5 token=[x] type="Foreground" flavor=3\n')
    rows = sa.classify(apps, {"apps": {"Odd": {"first_seen": 0, "last_front": None}}}, sa.settings(conf(apps_quit_list=["Odd"])), {}, T0)
    assert rows[0].status == sa.LISTED and not rows[0].eligible


# --- idle ----------------------------------------------------------------------------------------------

def test_idle_is_the_time_since_first_seen_or_last_front_whichever_is_later(mac, clock):
    mac.add("Slack", "com.example.slack")
    mac.add("Notes", "com.example.notes", front=True)
    tick(mac, clock, snap=CALM)                                  # first sight: not idle
    clock.hours(3.9)
    tick(mac, clock)
    assert mac.quit_calls == []
    clock.minutes(7)                                             # 4 h 1 min after first sight
    tick(mac, clock)
    assert mac.quit_calls == ["com.example.slack"]               # Notes was in front and is not listed anyway


def test_coming_to_the_front_restarts_the_idle_clock(mac, clock):
    mac.add("Slack", "com.example.slack")
    tick(mac, clock, snap=CALM)
    clock.hours(3.5)
    mac.front = "com.example.slack"
    tick(mac, clock, snap=CALM)
    mac.front = None
    clock.hours(3.5)                                             # 7 h since first sight, 3.5 h since in front
    tick(mac, clock)
    assert mac.quit_calls == []
    clock.hours(0.6)
    tick(mac, clock)
    assert mac.quit_calls == ["com.example.slack"]


def test_a_relaunched_app_starts_over(mac, clock):
    mac.add("Slack", "com.example.slack")
    settle(mac, clock)                                           # idle for 5 h
    mac.remove("com.example.slack")
    tick(mac, clock, snap=CALM)
    assert "com.example.slack" not in sa.load_state()["apps"]    # dropped when it stopped running
    mac.add("Slack", "com.example.slack")
    tick(mac, clock)
    assert mac.quit_calls == []                                  # a new process, first seen just now


def test_a_new_pid_between_ticks_is_a_relaunch_too(mac, clock):
    mac.add("Slack", "com.example.slack")
    settle(mac, clock)
    mac.apps["com.example.slack"]["pid"] = 4242
    tick(mac, clock)
    assert mac.quit_calls == []


# --- when memory is tight -------------------------------------------------------------------------------

def test_disk_and_cpu_load_alone_never_start_a_quit_even_when_the_verdict_is_critical(mac, clock):
    mac.add("Slack", "com.example.slack")
    settle(mac, clock)
    bad = snapshot(pressure=1, disk_free=1 * GIB, load1=500.0)
    assert load.assess(bad, load.guard_conf({})).level == load.CRITICAL
    assert tick(mac, clock, snap=bad) == [] and mac.quit_calls == []


def test_tight_reason_counts_pressure_compressor_and_swapout_only():
    c = load.guard_conf({})
    assert sa.tight_reason(snapshot(pressure=1), None, c) is None
    assert "warn" in sa.tight_reason(snapshot(pressure=2), None, c)
    assert "critical" in sa.tight_reason(snapshot(pressure=4), None, c)
    assert "compressor" in sa.tight_reason(snapshot(compressor=int(0.46 * RAM)), None, c)
    assert sa.tight_reason(snapshot(compressor=int(0.44 * RAM)), None, c) is None
    assert "swap-out" in sa.tight_reason(snapshot(), load.Trend(swapout_mb_s=25.0), c)
    assert sa.tight_reason(snapshot(), load.Trend(swapout_mb_s=5.0), c) is None
    assert sa.tight_reason(snapshot(), load.Trend(), c) is None and sa.tight_reason(None, None, c) is None


@pytest.mark.parametrize("snap,trend", [(snapshot(pressure=2), None), (snapshot(compressor=int(0.5 * RAM)), None),
                                        (snapshot(), load.Trend(swapout_mb_s=30.0))])
def test_each_memory_signal_triggers_a_quit(mac, clock, snap, trend):
    mac.add("Slack", "com.example.slack")
    settle(mac, clock)
    tick(mac, clock, snap=snap, trend=trend)
    assert mac.quit_calls == ["com.example.slack"]


def test_an_empty_list_quits_nothing_and_does_not_read_the_process_table(mac, clock):
    mac.add("Slack", "com.example.slack")
    c = conf(apps_quit_list=[])
    settle(mac, clock, c)
    tick(mac, clock, c)
    assert mac.quit_calls == [] and "ps" not in mac.subprocess_calls()


# --- which one, how often ---------------------------------------------------------------------------------

def test_the_largest_eligible_app_goes_first_and_one_per_pause(mac, clock):
    mac.add("Small", "com.example.small", mb=100)
    mac.add("Big", "com.example.big", mb=900)
    mac.add("Slack", "com.example.slack", mb=400)
    settle(mac, clock)
    tick(mac, clock)
    assert mac.quit_calls == ["com.example.big"]
    clock.minutes(1)
    tick(mac, clock)
    clock.minutes(2.5)
    tick(mac, clock)
    assert mac.quit_calls == ["com.example.big"]                 # still inside the 5 minutes
    clock.minutes(2)
    tick(mac, clock)
    assert mac.quit_calls == ["com.example.big", "com.example.slack"]
    clock.minutes(5)
    tick(mac, clock)
    assert mac.quit_calls[-1] == "com.example.small"


def test_the_tick_does_not_wait_and_the_next_one_journals_the_quit(mac, clock):
    mac.add("Slack", "com.example.slack", mb=400)
    settle(mac, clock)
    lines = tick(mac, clock)
    assert lines == [] and actions() == []                       # requested, not yet known
    assert "com.example.slack" not in mac.apps
    clock.minutes(1)
    lines = tick(mac, clock, snap=CALM)
    assert actions() == [("quit", "Slack")] and lines[0].startswith("apps: quit Slack")
    row = journal_rows()[0]
    assert row["mode"] == "on" and row["memory_bytes"] == 400 * 1024 ** 2 and row["idle_min"] >= 300 and "pressure" in row["reason"]
    clock.minutes(1)
    assert tick(mac, clock, snap=CALM) == [] and len(journal_rows()) == 1          # nothing happened: no new row


def test_an_app_that_stays_is_journaled_still_running_and_not_asked_again_until_it_was_in_front(mac, clock):
    mac.add("Slack", "com.example.slack")
    mac.stubborn.add("com.example.slack")
    settle(mac, clock)
    tick(mac, clock)
    clock.minutes(1)
    tick(mac, clock)
    assert actions() == [("still-running", "Slack")]
    for _ in range(4):                                           # the pause is over, memory is still tight
        clock.minutes(6)
        tick(mac, clock)
    assert mac.quit_calls == ["com.example.slack"] and len(journal_rows()) == 1
    mac.front = "com.example.slack"
    tick(mac, clock, snap=CALM)
    mac.front = None
    clock.hours(5)
    tick(mac, clock, snap=CALM)
    tick(mac, clock)
    assert mac.quit_calls == ["com.example.slack"] * 2           # in front once: eligible again after another idle spell


def test_a_refused_request_is_journaled_at_once_and_not_retried(mac, clock):
    mac.add("Slack", "com.example.slack")
    settle(mac, clock)
    mac.quit_app = lambda b: "failed"
    tick(mac, clock)
    assert actions() == [("still-running", "Slack")] and "not accepted" in journal_rows()[0]["reason"]


# --- dry mode ----------------------------------------------------------------------------------------------

def test_dry_mode_quits_nothing_and_does_not_count_an_app_twice(mac, clock):
    c = conf(apps_quit="dry")
    mac.add("Slack", "com.example.slack", mb=400)
    settle(mac, clock, c)
    lines = tick(mac, clock, c)
    assert mac.quit_calls == [] and actions() == [("would-quit", "Slack")] and lines[0].startswith("apps: would quit Slack")
    for _ in range(5):
        clock.minutes(6)
        tick(mac, clock, c)
    assert len(journal_rows()) == 1                              # treated as gone until it is in front
    mac.front = "com.example.slack"
    tick(mac, clock, c, snap=CALM)
    mac.front = None
    clock.hours(5)
    tick(mac, clock, c, snap=CALM)
    tick(mac, clock, c)
    assert len(journal_rows()) == 2
    rep = sa.report(7, now=clock())
    assert rep["total"] == {"quits": 0, "freed": 0, "would_quits": 2, "would_free": 800 * 1024 ** 2}


def test_a_dry_run_mark_does_not_shield_an_app_once_quits_are_real(mac, clock):
    dry = conf(apps_quit="dry")
    mac.add("Slack", "com.example.slack")
    settle(mac, clock, dry)
    tick(mac, clock, dry)
    assert actions() == [("would-quit", "Slack")] and mac.quit_calls == []
    clock.minutes(6)
    tick(mac, clock, conf(apps_quit="on"))
    assert mac.quit_calls == ["com.example.slack"]


def test_a_manual_quit_in_dry_mode_ignores_the_dry_run_mark(mac, clock):
    dry = conf(apps_quit="dry")
    mac.add("Slack", "com.example.slack")
    settle(mac, clock, dry)
    tick(mac, clock, dry)
    sa.manual_pass(dry, ctx_of(mac, clock), dry=False)
    assert mac.quit_calls == ["com.example.slack"]


@pytest.mark.parametrize("listed", ["Docker", "Docker Desktop"])
def test_an_app_inside_another_quits_through_the_outer_one_and_counts_once(mac, clock, listed):
    c = conf(apps_quit="dry", apps_quit_list=[listed])
    mac.add("Docker", "com.docker.docker", folder="Docker", mb=500)
    mac.add("Docker Desktop", "com.electron.dockerdesktop", folder="Docker.app/Contents/MacOS/Docker Desktop", mb=100)
    settle(mac, clock, c)
    tick(mac, clock, c)
    for _ in range(3):
        clock.minutes(6)
        tick(mac, clock, c)
    assert actions() == [("would-quit", "Docker")]
    on = conf(apps_quit="on", apps_quit_list=[listed])
    clock.minutes(6)
    tick(mac, clock, on)
    assert mac.quit_calls == ["com.docker.docker"]


def test_dry_mode_posts_one_notification_after_a_week(mac, clock):
    c = conf(apps_quit="dry")
    notes = []
    mac.add("Slack", "com.example.slack", mb=2048)
    settle(mac, clock, c)
    tick(mac, clock, c, notify=notes.append)
    assert sa.load_state()["dry_since"] == T0 + 5 * HOUR
    clock.hours(24 * 6)
    tick(mac, clock, c, snap=CALM, notify=notes.append)
    assert notes == []
    clock.hours(25)
    tick(mac, clock, c, snap=CALM, notify=notes.append)
    assert notes == ["Teyla: in a week it would have quit 1 apps, 2.0 GB. See: teyla storage apps --report"]
    for _ in range(3):
        clock.hours(25)
        tick(mac, clock, c, snap=CALM, notify=notes.append)
    assert len(notes) == 1 and sa.load_state()["dry_notified"] is True


def test_no_notification_in_on_mode(mac, clock):
    notes = []
    mac.add("Slack", "com.example.slack")
    settle(mac, clock)
    clock.hours(24 * 8)
    tick(mac, clock, snap=CALM, notify=notes.append)
    assert notes == []


# --- Docker ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("answer,quits", [((0, ""), True), ((0, "abc123\n"), False), ((1, ""), False), ((124, ""), False), ((127, ""), False)])
def test_docker_is_quit_only_when_docker_ps_answers_with_no_containers(mac, clock, answer, quits):
    mac.add("Docker", "com.docker.docker", mb=900)
    mac.docker = answer
    settle(mac, clock)
    tick(mac, clock)
    assert (mac.quit_calls == ["com.docker.docker"]) is quits
    assert ["docker", "ps", "-q"] in mac.calls
    if not quits:
        assert actions() == [("skipped-docker", "Docker")]


def test_a_busy_docker_does_not_block_the_next_app_and_is_not_asked_every_minute(mac, clock):
    mac.add("Docker", "com.docker.docker", mb=900)
    mac.add("Slack", "com.example.slack", mb=100)
    mac.docker = (0, "abc\n")
    settle(mac, clock)
    tick(mac, clock)
    assert mac.quit_calls == ["com.example.slack"] and actions() == [("skipped-docker", "Docker")]
    mac.calls.clear()
    clock.minutes(1)
    tick(mac, clock)
    assert ["docker", "ps", "-q"] not in mac.calls and len(journal_rows()) == 2          # + the Slack quit, no second skip row


def test_docker_desktop_is_gated_like_docker(mac, clock):
    mac.add("Docker Desktop", "com.electron.dockerdesktop", folder="Docker Desktop", mb=900)
    c = conf(apps_quit_list=["Docker Desktop"])
    mac.docker = (1, "")
    settle(mac, clock, c)
    tick(mac, clock, c)
    assert mac.quit_calls == []


# --- off ------------------------------------------------------------------------------------------------------

def test_off_makes_no_subprocess_call_and_writes_nothing(mac, clock):
    mac.add("Slack", "com.example.slack")
    c = conf(apps_quit="off")
    assert tick(mac, clock, c) == [] and mac.calls == [] and mac.quit_calls == []
    assert not sa.state_path().exists() and not sa.journal_path().exists()


def test_a_bad_mode_reads_as_off_and_not_macos_does_nothing(mac, clock):
    mac.add("Slack", "com.example.slack")
    assert sa.mode(conf(apps_quit="maybe")) == "off" and sa.mode(conf(apps_quit="ON")) == "on"
    assert tick(mac, clock, platform="linux") == [] and mac.calls == []
    assert sa.quit_bundle("") == "failed"


def test_quit_bundle_off_macos_does_nothing(monkeypatch):
    monkeypatch.setattr(sa.sys, "platform", "linux")
    assert sa.quit_bundle("com.example.slack") == "failed"


# --- guard.tick ------------------------------------------------------------------------------------------------

def guard_env(mac, clock, notes=None):
    return guard.Env(run=mac.run, notify_run=lambda cmd, timeout=60: (notes.append(cmd) if notes is not None else None) or (0, ""),
                     quit_app=mac.quit_app, now=clock, platform="darwin")


def test_guard_tick_quits_through_its_env_and_a_dry_tick_changes_nothing(mac, clock):
    mac.add("Slack", "com.example.slack")
    mac.add("launchd-fixture", "com.example.x", mb=1)
    g = conf()
    settle(mac, clock, g)
    dry = guard.tick(g, guard_env(mac, clock), dry=True)
    assert any(line.startswith("apps: would quit Slack") for line in dry["lines"])
    assert mac.quit_calls == [] and not sa.journal_path().exists()
    assert "dry_since" not in sa.load_state() and sa.load_state()["apps"]["com.example.slack"].get("pending") is None
    res = guard.tick(g, guard_env(mac, clock))
    assert mac.quit_calls == ["com.example.slack"]
    assert res["verdict"] is not None


def test_guard_tick_with_the_feature_off_runs_no_lsappinfo(mac, clock):
    mac.add("Slack", "com.example.slack")
    guard.tick(load.guard_conf({}), guard_env(mac, clock))
    assert "lsappinfo" not in mac.subprocess_calls()


def test_a_failure_in_the_apps_pass_is_one_line_and_the_tick_goes_on(mac, clock, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("broken")
    monkeypatch.setattr(sa, "tick", boom)
    res = guard.tick(conf(), guard_env(mac, clock))
    assert "apps: RuntimeError: broken" in res["lines"] and res["verdict"] is not None
    assert load.read_records()                                   # the record step ran before it


def test_the_dry_week_notice_goes_through_the_guards_notifier(mac, clock):
    notes = []
    mac.add("Slack", "com.example.slack", mb=1024)
    g = conf(apps_quit="dry")
    settle(mac, clock, g)
    env = guard_env(mac, clock, notes)
    guard.tick(g, env)
    clock.hours(24 * 7 + 1)
    guard.tick(g, env)
    guard.tick(g, env)
    week = [n for n in notes if "in a week" in n[2]]
    assert len(week) == 1 and "in a week it would have quit 1 apps, 1.0 GB" in week[0][2] and 'with title "Teyla"' in week[0][2]


# --- the commands -------------------------------------------------------------------------------------------------

def args(**kw):
    base = dict(quit=False, dry=False, report=False, days=7, json=False, quiet=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_the_table_lists_status_memory_and_hours_and_writes_nothing(mac, clock, capsys, monkeypatch):
    mac.add("Slack", "com.example.slack", mb=400)
    mac.add("Safari", "com.apple.Safari", mb=700)
    mac.add("Plain", "com.example.plain", mb=50)
    mac.add("Notes", "com.example.notes", mb=60, front=True)
    c = conf(apps_quit_list=["Slack", "Safari", "Notes"])
    settle(mac, clock, c)
    before = sa.state_path().read_text()
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None, footprints=None: TIGHT)
    cfg = {"guard": {"apps_quit": "dry", "apps_quit_list": ["Slack", "Safari", "Notes"]}}
    assert sa.cmd_apps(args(), cfg, ctx_of(mac, clock)) == 0
    out = capsys.readouterr().out
    assert "mode: dry" in out and "memory: tight (memory pressure is warn" in out
    row = {line.split()[0]: line for line in out.splitlines()[2:]}
    assert "listed" in row["Slack"] and "5.0" in row["Slack"]
    assert "protected" in row["Safari"] and "not listed" in row["Plain"] and "in front" in row["Notes"]
    assert sa.state_path().read_text() == before and mac.quit_calls == []


def test_the_table_as_json(mac, clock, capsys, monkeypatch):
    mac.add("Slack", "com.example.slack")
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None, footprints=None: CALM)
    sa.cmd_apps(args(json=True), {"guard": {"apps_quit_list": ["Slack"]}}, ctx_of(mac, clock))
    d = json.loads(capsys.readouterr().out)
    assert d["mode"] == "off" and d["tight"] is None and {a["name"]: a["status"] for a in d["apps"]}["Slack"] == "not idle yet"


def test_quit_now_ignores_memory_and_the_pause_and_journals_what_went(mac, clock, capsys):
    mac.add("Big", "com.example.big", mb=900)
    mac.add("Slack", "com.example.slack", mb=400)
    mac.add("Stuck", "com.example.stuck", mb=200)
    mac.stubborn.add("com.example.stuck")
    cfg = {"guard": {"apps_quit": "off", "apps_quit_list": ["Big", "Slack", "Stuck"]}}
    c = load.guard_conf(cfg)
    settle(mac, clock, c)
    assert sa.cmd_apps(args(quit=True), cfg, ctx_of(mac, clock)) == 0
    assert sorted(mac.quit_calls) == ["com.example.big", "com.example.slack", "com.example.stuck"]
    assert sorted(actions()) == [("quit", "Big"), ("quit", "Slack"), ("still-running", "Stuck")]
    assert {r["mode"] for r in journal_rows()} == {"manual"}
    assert capsys.readouterr().out.count("apps: ") == 3
    sa.cmd_apps(args(quit=True), cfg, ctx_of(mac, clock))        # Stuck is not asked again
    assert mac.quit_calls.count("com.example.stuck") == 1


def test_quit_now_with_dry_reports_and_changes_nothing(mac, clock, capsys):
    mac.add("Slack", "com.example.slack")
    cfg = {"guard": {"apps_quit_list": ["Slack"]}}
    settle(mac, clock, load.guard_conf(cfg))
    before = sa.state_path().read_text()
    sa.cmd_apps(args(quit=True, dry=True), cfg, ctx_of(mac, clock))
    assert "would quit Slack" in capsys.readouterr().out
    assert mac.quit_calls == [] and not sa.journal_path().exists() and sa.state_path().read_text() == before


def test_quit_now_says_so_when_nothing_is_eligible(mac, clock, capsys):
    mac.add("Slack", "com.example.slack")
    sa.cmd_apps(args(quit=True), {"guard": {"apps_quit_list": ["Slack"]}}, ctx_of(mac, clock))
    assert "nothing is eligible" in capsys.readouterr().out and mac.quit_calls == []


def test_report_sums_quits_and_would_quits_per_app_over_the_days(clock, capsys):
    rows = [dict(mode="on", action="quit", app="Slack", memory=GIB, idle_min=300, reason="r"),
            dict(mode="on", action="quit", app="Slack", memory=GIB, idle_min=300, reason="r"),
            dict(mode="dry", action="would-quit", app="Big", memory=3 * GIB, idle_min=300, reason="r"),
            dict(mode="on", action="still-running", app="Big", memory=3 * GIB, idle_min=300, reason="r"),
            dict(mode="on", action="skipped-docker", app="Docker", memory=GIB, idle_min=300, reason="r")]
    sa.journal(rows[:2], clock())
    sa.journal(rows[2:], clock() - 3 * 86400)
    sa.journal([dict(mode="on", action="quit", app="Old", memory=GIB, idle_min=1, reason="r")], clock() - 20 * 86400)
    rep = sa.report(7, now=clock())
    assert {a["app"]: a for a in rep["apps"]}["Slack"] == {"app": "Slack", "quits": 2, "freed": 2 * GIB, "would_quits": 0, "would_free": 0}
    assert {a["app"] for a in rep["apps"]} == {"Slack", "Big"}                     # still-running, skipped-docker and old rows are not counted
    assert rep["total"] == {"quits": 2, "freed": 2 * GIB, "would_quits": 1, "would_free": 3 * GIB}
    assert sa.report(30, now=clock())["total"]["quits"] == 3
    assert sa.cmd_apps(args(report=True, days=7), {}, sa.Ctx(now=clock)) == 0
    out = capsys.readouterr().out
    assert "Slack" in out and out.splitlines()[-1].startswith("total")
    assert "no quits" in "\n".join(sa.render_report(sa.report(7, now=clock() + 30 * 86400)))


def test_the_journal_sanitises_fields_and_keeps_one_header(clock):
    sa.journal([dict(mode="on", action="quit", app="A\tB\nC", memory=1, idle_min=2, reason="x\ty")] * 2, clock())
    lines = sa.journal_path().read_text().splitlines()
    assert lines[0] == "#" + "\t".join(sa.JOURNAL_COLUMNS) and len(lines) == 3
    assert all(len(line.split("\t")) == 7 for line in lines[1:])


# --- config ------------------------------------------------------------------------------------------------------

def test_defaults_are_off_and_empty():
    g = config.DEFAULTS["guard"]
    assert (g["apps_quit"], g["apps_quit_list"], g["apps_quit_idle_h"], g["apps_quit_every_min"]) == ("off", [], 4, 5)
    assert sa.settings(load.guard_conf({}))["mode"] == "off"


def test_config_set_can_set_the_list_and_the_mode(tmp_path):
    p = tmp_path / "config.toml"
    assert "guard.apps_quit_list" in config.set_value("guard.apps_quit_list", "Slack, Docker Desktop,com.example.x", path=p)
    config.set_value("guard.apps_quit", "dry", path=p)
    config.set_value("guard.apps_quit_idle_h", "6", path=p)
    cfg = config._read(p)
    s = sa.settings(load.guard_conf(cfg))
    assert s["list"] == ["Slack", "Docker Desktop", "com.example.x"] and s["mode"] == "dry" and s["idle_h"] == 6


def test_a_list_written_as_one_string_still_works():
    assert sa.settings(load.guard_conf({"guard": {"apps_quit_list": "Slack, Zoom"}}))["list"] == ["Slack", "Zoom"]


def test_no_feature_pack_switches_the_feature_on():
    for pack in features.PACKS:
        assert not any(k.startswith("guard.apps_quit") for k in pack.switches)

"""`teyla load` — snapshot, verdict, admission, recorder, wait.

`ps` and `sysctl` are faked (`fake_run`); nothing here reads the real process table, sleeps or
touches the real ~/.teyla (TEYLA_HOME points into a tmp dir for every test, see conftest).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import time

import pytest

from teyla import config, doctor, load

GIB = 1024 ** 3
UDID_A = "739ACE86-D869-4278-A1BA-612044100EBA"
UDID_B = "B3C0CC25-8299-478F-84E6-1CA573D22842"
CLAUDE_APP = "/Users/me/Library/Application Support/Claude/claude-code/2.1.293/8433d0d9cd0d/claude.app/Contents/MacOS/claude"
CHROME = "/Applications/Google Chrome.app/Contents"
RENDERER = (f"{CHROME}/Frameworks/Google Chrome Framework.framework/Versions/155.0.8059.40/Helpers/"
            "Google Chrome Helper (Renderer).app/Contents/MacOS/Google Chrome Helper (Renderer) --type=renderer --lang=en-US")
XCODE_BIN = "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin"
SIM_RT = "/Library/Developer/CoreSimulator/Volumes/iOS_24A5423a/Library/Developer/CoreSimulator/Profiles/Runtimes/iOS 27.0.simruntime/Contents/Resources/RuntimeRoot"
def ram_pct(p: float) -> int:
    return math.ceil(24 * GIB * p / 100)


GOOD_SYSCTL = "25769803776\n10\n{ 1.50 2.00 3.00 }\ntotal = 1024.00M  used = 512.00M  free = 512.00M  (encrypted)\n1\n1073741824\n"


def ps_line(pid, command, ppid=0, rss_kb=1000, cpu="0.0", etime="05:00"):
    return f"{pid:>6} {ppid:>6} {rss_kb:>8} {cpu:>5} {etime:>11} {command}"


class Machine:
    """A fake `ps` + `sysctl`."""

    def __init__(self, sysctl=GOOD_SYSCTL):
        self.lines: list[str] = []
        self.sysctl = sysctl
        self.ps_fails = False
        self.calls: list[list[str]] = []

    def add(self, pid, command, **kw):
        self.lines.append(ps_line(pid, command, **kw))
        return pid

    def run(self, cmd, timeout=60):
        self.calls.append(cmd)
        if cmd[0] == "ps":
            return (1, "") if self.ps_fails else (0, "\n".join(self.lines))
        if cmd[0] == "sysctl":
            return 0, self.sysctl
        return 127, ""


def sysctl_text(ram=24 * GIB, ncpu=10, load=(1.0, 1.0, 1.0), swap_used_mb=0, pressure=1, comp=0):
    l1, l5, l15 = load
    return (f"{ram}\n{ncpu}\n{{ {l1} {l5} {l15} }}\ntotal = 8192.00M  used = {swap_used_mb:.2f}M  free = 1.00M  (encrypted)\n"
            f"{pressure}\n{comp}\n")


def snap_of(machine: Machine) -> load.Snapshot:
    s = load.snapshot(machine.run, now=dt.datetime(2026, 10, 9, 20, 25, tzinfo=dt.timezone(dt.timedelta(hours=2))))
    assert s is not None
    return s


def classify(*lines) -> load.Procs:
    return load.classify(load.parse_ps("\n".join(lines)))


# --- sysctl -----------------------------------------------------------------------------------

def test_sysctl_parses_the_six_values_in_order():
    s = load.parse_sysctl("25769803776\n10\n{ 579.67 508.27 442.81 }\n"
                          "total = 13312.00M  used = 11734.19M  free = 1577.81M  (encrypted)\n4\n12884901888\n")
    assert s["ram_bytes"] == 24 * GIB and s["ncpu"] == 10
    assert s["load"] == (579.67, 508.27, 442.81)
    assert s["swap"] == (13312 * 1024 ** 2, int(11734.19 * 1024 ** 2))
    assert s["pressure"] == 4 and s["compressor_bytes"] == 12 * GIB


@pytest.mark.parametrize("text", ["", "garbage", "\n\n", "a\nb\nc\nd\ne\nf\n", "{ x y z }\ntotal = ?\nq\nr\ns\nt\n", "-5\n0\n{}\nused\n-1\nx\n"])
def test_sysctl_garbage_gives_none_and_never_raises(text):
    s = load.parse_sysctl(text)
    assert s["ram_bytes"] is None and s["ncpu"] is None and s["load"] is None
    assert s["swap"] == (None, None) and s["pressure"] is None and s["compressor_bytes"] is None


def test_sysctl_one_bad_field_does_not_spoil_the_others():
    s = load.parse_sysctl("25769803776\nten\n{ 1 2 3 }\nnonsense\n2\n100\n")
    assert s["ram_bytes"] == 24 * GIB and s["ncpu"] is None
    assert s["load"] == (1.0, 2.0, 3.0) and s["swap"] == (None, None) and s["pressure"] == 2 and s["compressor_bytes"] == 100


def test_sysctl_with_a_missing_key_keeps_what_its_shape_gives_away():
    # a macOS without the compressor key prints five lines (the error goes to stderr)
    s = load.parse_sysctl("25769803776\n10\n{ 1 2 3 }\ntotal = 1.00G  used = 0.50G  free = 0.50G\n1\n")
    assert s["ram_bytes"] == 24 * GIB and s["ncpu"] == 10 and s["load"] == (1.0, 2.0, 3.0)
    assert s["swap"] == (GIB, GIB // 2)
    assert s["pressure"] is None and s["compressor_bytes"] is None


# --- ps classification ------------------------------------------------------------------------

def test_booted_simulators_are_counted_with_their_udids():
    p = classify(
        ps_line(10, f"launchd_sim /Users/me/Library/Developer/CoreSimulator/Devices/{UDID_A}/data/var/run/launchd_bootstrap.plist"),
        ps_line(11, f"{SIM_RT}/sbin/launchd_sim /Users/me/Library/Developer/CoreSimulator/Devices/{UDID_B}/data/var/run/launchd_bootstrap.plist"),
        ps_line(12, "launchd_sim /somewhere/else"),
        ps_line(13, f"{SIM_RT}/usr/libexec/backboardd", ppid=10),   # inside a simulator: not a simulator
    )
    assert p.sims == 3
    assert p.sim_udids == [UDID_A, UDID_B]


def test_simulator_guest_processes_group_under_their_runtime_in_top():
    p = classify(ps_line(1, f"{SIM_RT}/usr/libexec/backboardd", rss_kb=2000),
                 ps_line(2, f"{SIM_RT}/System/Library/PrivateFrameworks/AssistantServices.framework/assistantd", rss_kb=3000))
    assert p.top == [["iOS 27.0 simulator", 5000 * 1024]]


def test_build_drivers_are_counted_and_compilers_kept_apart():
    p = classify(
        ps_line(1, f"/usr/bin/xcodebuild -scheme App build", rss_kb=100, etime="02:00"),
        ps_line(2, f"{XCODE_BIN}/swift-build --scratch-path .build", rss_kb=100),
        ps_line(3, f"{XCODE_BIN}/swift-frontend -frontend -c a.swift", ppid=2, rss_kb=500),
        ps_line(4, f"{XCODE_BIN}/swift-frontend -frontend -c b.swift", ppid=2, rss_kb=500),
        ps_line(5, "/usr/bin/clang -c x.c", rss_kb=50),
        ps_line(6, "/usr/bin/ld -o out", rss_kb=50),
        ps_line(7, "/Applications/Xcode.app/Contents/SharedFrameworks/SwiftBuild.framework/Versions/A/PlugIns/SWBBuildService.bundle/Contents/MacOS/SWBBuildService", rss_kb=200),
        ps_line(8, "/System/Library/PrivateFrameworks/XCBuild.framework/XCBBuildService", rss_kb=200),
        ps_line(9, "(swift-frontend)"),                     # a zombie
        ps_line(10, "/bin/zsh -c xcodebuild test"),         # a shell that merely mentions it
        ps_line(11, "/Users/me/.cargo/bin/cargo build --release"),
        ps_line(12, "/Users/me/.cargo/bin/cargo fmt"),
        ps_line(13, "/usr/bin/swift-test"),
    )
    assert sorted(d.kind for d in p.drivers) == ["cargo", "swift", "swift", "xcodebuild"]
    assert p.builds == 4
    assert p.compilers == 6 and p.compiler_rss_bytes == (500 + 500 + 50 + 50 + 200 + 200) * 1024
    xb = next(d for d in p.drivers if d.kind == "xcodebuild")
    assert xb.etime_s == 120


def test_gradle_wrapper_and_the_jvm_it_starts_are_one_build_and_the_daemon_is_not_a_build():
    p = classify(
        ps_line(1, "/bin/sh ./gradlew assembleDebug"),
        ps_line(2, "/Users/me/.local/jdk/bin/java -classpath /p/gradle/wrapper/gradle-wrapper.jar org.gradle.wrapper.GradleWrapperMain assembleDebug", ppid=1),
        ps_line(3, "/Users/me/.local/jdk/bin/java --add-opens=java.base/java.lang=ALL-UNNAMED -Xmx2g -cp /g/lib/gradle-launcher.jar "
                   "-Dfile.encoding=UTF-8 org.gradle.launcher.daemon.bootstrap.GradleDaemon 8.10", rss_kb=1_000_000, etime="1-02:00:00"),
    )
    assert p.builds == 1 and p.drivers[0].kind == "gradle"
    assert [(d.kind, d.rss_bytes, d.etime_s) for d in p.daemons] == [("gradle", 1_000_000 * 1024, 93600)]


def test_kotlin_daemon_is_a_daemon_not_a_build():
    p = classify(ps_line(1, "/jdk/bin/java -cp /Users/me/.gradle/caches/modules-2/files-2.1/org.jetbrains.kotlin/"
                            "kotlin-compiler-embeddable/2.0.21/abc/kotlin-compiler-embeddable-2.0.21.jar:/x.jar "
                            "org.jetbrains.kotlin.daemon.KotlinCompileDaemon --daemon-runFilesPath=/tmp", rss_kb=800))
    assert [d.kind for d in p.daemons] == ["kotlin"] and p.builds == 0
    q = classify(ps_line(2, "/jdk/bin/java -jar app.jar"))
    assert q.daemons == []


def test_daemons_carry_their_cpu_and_kotlinc_clients_are_counted():
    p = classify(
        ps_line(3, "/jdk/bin/java -cp /g/lib/gradle-launcher.jar org.gradle.launcher.daemon.bootstrap.GradleDaemon 8.10", cpu="37.5"),
        ps_line(4, "/jdk/bin/java -cp /k/kotlin-compiler-embeddable.jar org.jetbrains.kotlin.daemon.KotlinCompileDaemon", cpu="0.0"),
        ps_line(5, "/opt/kotlinc/bin/kotlinc Main.kt"),
        ps_line(6, "/jdk/bin/java -cp /k/kotlin-compiler.jar org.jetbrains.kotlin.cli.jvm.K2JVMCompiler Main.kt"),
    )
    assert [(d.kind, d.cpu) for d in p.daemons] == [("gradle", 37.5), ("kotlin", 0.0)]
    assert p.kotlinc == 2
    assert classify(ps_line(1, "/bin/sh -c ls")).kotlinc == 0


def test_claude_sessions_count_once_and_the_apps_own_processes_not_at_all():
    p = classify(
        ps_line(1, "/Applications/Claude.app/Contents/MacOS/Claude"),
        ps_line(2, "/Applications/Claude.app/Contents/Frameworks/Claude Helper (Renderer).app/Contents/MacOS/Claude Helper (Renderer) --type=renderer"),
        ps_line(3, "/Applications/Claude.app/Contents/Frameworks/Claude Helper.app/Contents/MacOS/Claude Helper --type=gpu-process"),
        ps_line(4, f"/Applications/Claude.app/Contents/Helpers/disclaimer --pgroup -- {CLAUDE_APP} --output-format stream-json --verbose"),
        ps_line(5, f"{CLAUDE_APP} --output-format stream-json --verbose --input-format stream-json --effort high", ppid=4),
        ps_line(6, f"{CLAUDE_APP} --output-format stream-json --verbose --input-format stream-json", ppid=1),
        ps_line(7, "claude --dangerously-skip-permissions"),                       # a terminal session
        ps_line(8, "claude -p summarise the repo"),                              # a headless lane
        ps_line(9, "/Users/me/.local/bin/claude --print --model sonnet"),         # another one
        ps_line(10, "/Users/me/.local/share/claude/versions/2.1.100 --verbose"),   # the native installer's binary
    )
    assert p.claude == 6 and p.lanes == 2


def test_codex_lanes_are_codex_exec_and_the_node_wrapper_is_counted_with_its_child():
    p = classify(
        ps_line(1, "node /Users/me/.local/bin/codex exec -m gpt-6.1-sol --sandbox workspace-write do the thing"),
        ps_line(2, "/Users/me/.local/lib/vendor/codex/codex exec -m gpt-6.1-sol do the thing", ppid=1),
        ps_line(3, "node /Users/me/.local/bin/codex -m gpt-6.1-sol"),               # an interactive session
        ps_line(4, "/Users/me/.local/lib/vendor/codex/codex", ppid=3),
        ps_line(5, "/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex exec-server --remote https://x"),
        ps_line(6, "/Applications/ChatGPT.app/Contents/Frameworks/Codex Framework.framework/Versions/1/Helpers/Codex (Service).app/Contents/MacOS/Codex (Service) --type=gpu-process"),
        ps_line(7, "/Applications/Codex.app/Contents/Frameworks/Codex Helper (Renderer).app/Contents/MacOS/Codex Helper (Renderer) --type=renderer"),
    )
    assert p.codex == 3        # exec lane, interactive session, exec-server
    assert p.lanes == 1        # only the `codex exec`


def test_grok_prompt_runs_are_lanes_and_the_grok_bot_app_is_not_grok():
    p = classify(
        ps_line(1, "/Users/me/.grok/bin/grok"),
        ps_line(2, "/Users/me/.grok/bin/grok -p review this --max-turns 60"),
        ps_line(3, "grok --prompt hello"),
        ps_line(4, "/Applications/Grok Bot.app/Contents/MacOS/Grok Bot"),
        ps_line(5, "/Applications/Grok Bot.app/Contents/Frameworks/Grok Bot Helper.app/Contents/MacOS/Grok Bot Helper --type=gpu-process"),
    )
    assert p.grok == 3 and p.lanes == 2


def test_chrome_renderers_and_all_of_chrome():
    p = classify(
        ps_line(1, f"{CHROME}/MacOS/Google Chrome", rss_kb=300),
        ps_line(2, RENDERER, rss_kb=400),
        ps_line(3, RENDERER, rss_kb=500),
        ps_line(4, f"{CHROME}/Frameworks/Google Chrome Framework.framework/Versions/1/Helpers/Google Chrome Helper.app/Contents/MacOS/Google Chrome Helper --type=utility", rss_kb=100),
        ps_line(5, "/Applications/Safari.app/Contents/MacOS/Safari", rss_kb=900),
    )
    assert p.chrome_renderers == 2 and p.chrome_renderer_rss_bytes == 900 * 1024
    assert p.chrome_rss_bytes == 1300 * 1024


def test_vms_and_top_apps_fold_helpers_into_the_app():
    p = classify(
        ps_line(1, "/System/Library/Frameworks/Virtualization.framework/Versions/A/XPCServices/com.apple.Virtualization.VirtualMachine.xpc/Contents/MacOS/com.apple.Virtualization.VirtualMachine", rss_kb=3000),
        ps_line(2, "/opt/homebrew/bin/qemu-system-aarch64 -machine virt -m 4096", rss_kb=2000),
        ps_line(3, f"{CHROME}/MacOS/Google Chrome", rss_kb=300),
        ps_line(4, RENDERER, rss_kb=400),
        *[ps_line(10 + i, f"/usr/bin/tool{i} --x", rss_kb=10 + i) for i in range(12)],
    )
    assert [(v.name, v.rss_bytes) for v in p.vms] == [("com.apple.Virtualization.VirtualMachine", 3000 * 1024), ("qemu-system-aarch64", 2000 * 1024)]
    assert p.vm_rss_bytes == 5000 * 1024
    assert p.top[0] == ["com.apple.Virtualization.VirtualMachine", 3000 * 1024]
    assert ["Google Chrome", 700 * 1024] in p.top
    assert len(p.top) == load.TOP_N


def test_malformed_ps_lines_are_dropped():
    rows = load.parse_ps("garbage\n\n  1 2 x 0.0 01:00 cmd\n" + ps_line(5, "/bin/ls") + "\n  7 1 100\n")
    assert [r.pid for r in rows] == [5]


# --- snapshot ----------------------------------------------------------------------------------

def test_snapshot_makes_one_sysctl_and_one_ps_call():
    m = Machine()
    m.add(1, f"launchd_sim /x/Devices/{UDID_A}/data")
    s = snap_of(m)
    assert [c[0] for c in m.calls].count("ps") == 1 and [c[0] for c in m.calls].count("sysctl") == 1
    assert len(m.calls) == 2
    assert s.time == "2026-10-09T20:25:00+02:00"
    assert s.ram_bytes == 24 * GIB and s.ncpu == 10 and s.load1 == 1.5 and s.procs.sims == 1
    assert s.swap_total_bytes == 1024 * 1024 ** 2 and s.swap_used_bytes == 512 * 1024 ** 2
    assert s.pressure == 1 and s.compressor_bytes == GIB


def test_snapshot_is_none_when_ps_fails_and_survives_a_dead_sysctl():
    m = Machine()
    m.ps_fails = True
    assert load.snapshot(m.run) is None
    m2 = Machine(sysctl="")
    m2.add(1, "/bin/ls")
    s = load.snapshot(m2.run)
    assert s is not None and s.ram_bytes is None and s.load1 is None and s.procs.builds == 0


def test_snapshot_json_is_serialisable_with_the_derived_counts():
    m = Machine()
    m.add(1, "/usr/bin/xcodebuild build")
    d = snap_of(m).to_json()
    json.dumps(d)
    assert d["procs"]["builds"] == 1 and d["procs"]["daemon_rss_bytes"] == 0 and d["ram_bytes"] == 24 * GIB


# --- verdict -----------------------------------------------------------------------------------

def snap(**kw) -> load.Snapshot:
    base = dict(time="2026-10-09T20:25:00+02:00", ram_bytes=24 * GIB, ncpu=10, load1=1.0, load5=1.0, load15=1.0,
                swap_total_bytes=8 * GIB, swap_used_bytes=0, pressure=1, compressor_bytes=0)
    procs = kw.pop("procs", load.Procs())
    return load.Snapshot(**{**base, **kw}, procs=procs)


def procs(sims=0, builds=0, lanes=0, udids=()):
    return load.Procs(sims=sims, sim_udids=list(udids), drivers=[load.Driver(i, "xcodebuild", 0, 60) for i in range(builds)], lanes=lanes)


def test_quiet_machine_is_ok():
    v = load.assess(snap(), {})
    assert v.level == "OK" and v.reasons == [] and v.exit_code == 0


@pytest.mark.parametrize("kw,level", [
    (dict(pressure=4), "CRITICAL"), (dict(pressure=2), "BUSY"), (dict(pressure=1), "OK"),
    (dict(swap_used_bytes=ram_pct(40), pressure=2), "CRITICAL"), (dict(swap_used_bytes=ram_pct(39.9), pressure=2), "BUSY"),
    (dict(swap_used_bytes=ram_pct(40)), "BUSY"),       # swap with no pressure left: the machine has recovered
    (dict(swap_used_bytes=ram_pct(25)), "BUSY"), (dict(swap_used_bytes=ram_pct(24.9)), "OK"),
    (dict(load1=100.0), "CRITICAL"), (dict(load1=99.9), "BUSY"), (dict(load1=40.0), "BUSY"), (dict(load1=39.9), "OK"),
    (dict(compressor_bytes=ram_pct(45)), "CRITICAL"), (dict(compressor_bytes=ram_pct(44.9)), "BUSY"),
    (dict(compressor_bytes=ram_pct(30)), "BUSY"), (dict(compressor_bytes=ram_pct(29.9)), "OK"),
])
def test_thresholds_trip_on_both_sides(kw, level):
    assert load.assess(snap(**kw), {}).level == level


def test_sims_and_builds_make_the_machine_busy_above_the_cap_not_at_it():
    assert load.assess(snap(procs=procs(sims=2, builds=2)), {}).level == "OK"
    assert load.assess(snap(procs=procs(sims=3)), {}).level == "BUSY"
    assert load.assess(snap(procs=procs(builds=3)), {}).level == "BUSY"
    assert load.assess(snap(procs=procs(sims=3)), {"max_sims": 3}).level == "OK"
    assert load.assess(snap(procs=procs(sims=30, builds=30)), {"max_sims": 0, "max_builds": 0}).level == "OK"


def test_unknown_fields_trip_nothing():
    blank = load.Snapshot(time="t")
    assert load.assess(blank, {}).level == "OK"


def test_reasons_carry_the_number_and_the_threshold_critical_first():
    v = load.assess(snap(swap_used_bytes=int(11.7 * GIB), load1=579.67, pressure=2, procs=procs(sims=4)), {})
    assert v.level == "CRITICAL"
    assert v.reasons[0] == "swap 11.7 GB = 49% of RAM (critical ≥ 40% under memory pressure)"
    assert v.reasons[1] == "load 580 on 10 cores (critical ≥ 100)"
    assert any("pressure is warn" in r for r in v.reasons) and any("4 simulators booted (max 2)" in r for r in v.reasons)
    assert v.n_critical == 2
    assert v.line().startswith("load: CRITICAL — swap 11.7 GB")


def test_thresholds_follow_the_config():
    s = snap(swap_used_bytes=int(3.0 * GIB), pressure=2)          # 12.5%
    assert load.assess(s, {}).level == "BUSY"                          # the pressure alone
    assert load.assess(s, {"swap_warn_pct": 10}).level == "BUSY"
    assert load.assess(s, {"swap_warn_pct": 5, "swap_crit_pct": 12}).level == "CRITICAL"
    assert load.assess(s, {"swap_warn_pct": "banana"}).level == "BUSY"      # a mistyped value falls back


# --- admission ---------------------------------------------------------------------------------

def test_a_quiet_machine_admits_everything():
    for kind in load.KINDS:
        assert load.admit(kind, snap(), {}) == (True, "")


def test_critical_refuses_every_kind_with_the_numbers():
    s = snap(swap_used_bytes=int(11.7 * GIB), pressure=2)
    for kind in load.KINDS:
        ok, msg = load.admit(kind, s, {})
        assert not ok and "CRITICAL" in msg and "swap 11.7 GB" in msg
        assert f"teyla load --wait --kind {kind}" in msg
        assert len(msg.splitlines()) <= 6


def test_build_is_refused_at_the_cap():
    assert load.admit("build", snap(procs=procs(builds=1)), {})[0]
    ok, msg = load.admit("build", snap(procs=procs(builds=2)), {})
    assert not ok and "2 builds already run (max 2)" in msg
    assert load.admit("build", snap(procs=procs(builds=2)), {"max_builds": 3})[0]
    assert load.admit("build", snap(procs=procs(builds=9)), {"max_builds": 0})[0]


def test_sim_is_refused_at_the_cap_and_the_message_names_the_booted_ones():
    assert load.admit("sim", snap(procs=procs(sims=1)), {})[0]
    ok, msg = load.admit("sim", snap(procs=procs(sims=2, udids=[UDID_A, UDID_B])), {})
    assert not ok and "2 simulators are already booted (max 2)" in msg
    assert UDID_A in msg and UDID_B in msg and "Reuse an already-booted simulator" in msg
    ok, msg = load.admit("sim", snap(procs=procs(sims=2)), {})
    assert not ok and "xcrun simctl list devices booted" in msg
    assert load.admit("build", snap(procs=procs(sims=5)), {})[0]      # sims do not block builds


def test_lane_cap_is_off_by_default_and_counts_headless_lanes():
    assert load.admit("lane", snap(procs=procs(lanes=50)), {})[0]
    ok, msg = load.admit("lane", snap(procs=procs(lanes=3)), {"max_lanes": 3})
    assert not ok and "3 headless agent lanes already run (max 3)" in msg
    assert load.admit("lane", snap(procs=procs(lanes=2)), {"max_lanes": 3})[0]


# --- config ------------------------------------------------------------------------------------

def test_guard_defaults():
    g = config.DEFAULTS["guard"]
    assert g == {"enabled": True, "max_sims": 2, "max_builds": 2, "max_lanes": 0, "swap_warn_pct": 25, "swap_crit_pct": 40,
                 "compressor_warn_pct": 30, "compressor_crit_pct": 45, "load_warn_per_core": 4.0, "load_crit_per_core": 10.0,
                 "wait_timeout_s": 900, "agent": False, "gradle_idle_min": 30, "alert": True,
                 "disk_warn_gb": 25, "disk_crit_gb": 10, "disk_sweep": True}
    assert load.guard_conf({"guard": {"max_sims": 5}})["max_sims"] == 5
    assert load.guard_conf({})["max_sims"] == 2


def test_config_set_coerces_guard_keys(tmp_path):
    p = tmp_path / "config.toml"
    assert config.set_value("guard.max_sims", "3", p).startswith("set")
    assert config.set_value("guard.load_warn_per_core", "5", p).startswith("set")
    assert config.set_value("guard.enabled", "false", p).startswith("set")
    cfg = config.load(p)["guard"]
    assert cfg["max_sims"] == 3 and type(cfg["max_sims"]) is int
    assert cfg["load_warn_per_core"] == 5.0 and type(cfg["load_warn_per_core"]) is float
    assert cfg["enabled"] is False
    assert config.set_value("guard.max_sims", "many", p).startswith("invalid")
    assert load.guard_conf(config.load(p))["max_sims"] == 3


# --- recorder ----------------------------------------------------------------------------------

def loaded_snap(sec=0, **kw) -> load.Snapshot:
    when = dt.datetime(2026, 10, 9, 20, 0, sec, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    p = load.Procs(sims=2, drivers=[load.Driver(1, "gradle", 0, 5)], compilers=3, compiler_rss_bytes=GIB,
                   daemons=[load.Daemon(2, "gradle", 2 * GIB, 60)], claude=36, codex=17, grok=1, lanes=2,
                   chrome_renderers=9, chrome_renderer_rss_bytes=GIB, chrome_rss_bytes=11 * GIB,
                   vms=[load.Vm(3, "qemu-system-aarch64", 3 * GIB)],
                   top=[["Google Chrome", 11 * GIB], ["a:b,c", 4 * GIB], ["java", 2 * GIB], ["node", GIB]])
    return load.Snapshot(time=when.replace(second=sec).isoformat(timespec="seconds"), ram_bytes=24 * GIB, ncpu=10,
                         load1=579.67, load5=1, load15=1, swap_total_bytes=13 * GIB, swap_used_bytes=int(11.7 * GIB),
                         pressure=4, compressor_bytes=12 * GIB, procs=p, **kw)


def test_record_writes_a_header_then_one_line_and_reads_back(tmp_path):
    path = tmp_path / "sub" / "load.tsv"
    s = loaded_snap()
    v = load.assess(s, {})
    assert load.record(s, v, path) == path
    load.record(s, v, path)
    lines = path.read_text().splitlines()
    assert lines[0] == "#" + "\t".join(load.COLUMNS) and len(lines) == 3
    assert len(lines[1].split("\t")) == len(load.COLUMNS)
    assert lines[1].split("\t")[load.COLUMNS.index("top3")] == "Google Chrome:11.0,a_b_c:4.0,java:2.0"
    recs = load.read_records(path=path)
    assert len(recs) == 2
    r = recs[0]
    assert r["level"] == "CRITICAL" and r["pressure"] == 4 and r["load1"] == 579.67
    assert r["swap_used_bytes"] == int(11.7 * GIB) and r["ram_bytes"] == 24 * GIB and r["compressor_bytes"] == 12 * GIB
    assert (r["sims"], r["builds"], r["claude"], r["codex"], r["grok"], r["lanes"]) == (2, 1, 36, 17, 1, 2)
    assert r["compiler_rss_bytes"] == GIB and r["daemon_rss_bytes"] == 2 * GIB
    assert r["chrome_rss_bytes"] == 11 * GIB and r["vm_rss_bytes"] == 3 * GIB
    assert r["top3"] == [("Google Chrome", 11.0), ("a_b_c", 4.0), ("java", 2.0)]
    assert r["time"] == "2026-10-09T20:00:00+02:00"


def test_record_defaults_to_the_teyla_home(tmp_path, monkeypatch):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path / "th"))
    s = loaded_snap()
    load.record(s, load.assess(s, {}))
    assert (tmp_path / "th" / "load.tsv").exists()
    assert len(load.read_records()) == 1


def test_unknown_fields_are_empty_cells_and_read_back_as_none(tmp_path):
    path = tmp_path / "load.tsv"
    s = load.Snapshot(time="2026-10-09T20:00:00+02:00")
    load.record(s, load.assess(s, {}), path)
    r = load.read_records(path=path)[0]
    assert r["pressure"] is None and r["load1"] is None and r["ram_bytes"] is None and r["top3"] == [] and r["level"] == "OK"


def test_the_file_is_trimmed_to_its_newest_half_with_the_header_kept(tmp_path):
    path = tmp_path / "load.tsv"
    for i in range(40):
        s = loaded_snap(sec=i)
        load.record(s, load.assess(s, {}), path, max_bytes=2000)
    lines = path.read_text().splitlines()
    assert lines[0].startswith("#")
    assert path.stat().st_size < 2000 + 400
    recs = load.read_records(path=path)
    assert recs and recs[-1]["time"].endswith("20:00:39+02:00")        # newest kept
    assert recs[0]["time"] != "2026-10-09T20:00:00+02:00"              # oldest gone
    secs = [int(r["time"][17:19]) for r in recs]
    assert secs == sorted(secs) and secs == list(range(secs[0], 40))   # contiguous tail
    assert not list(tmp_path.glob("*.tmp"))


def test_read_records_tolerates_junk_and_filters_by_time(tmp_path):
    path = tmp_path / "load.tsv"
    for sec in (0, 10, 20):
        s = loaded_snap(sec=sec)
        load.record(s, load.assess(s, {}), path)
    with open(path, "a") as f:
        f.write("not a record\n\x00\x01\ttoo\tfew\n" + "\t".join(["bad-time"] + ["x"] * (len(load.COLUMNS) - 1)) + "\n")
    assert len(load.read_records(path=path)) == 3
    t = lambda sec: dt.datetime(2026, 10, 9, 20, 0, sec, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    assert [r["time"][17:19] for r in load.read_records(since=t(5), until=t(15), path=path)] == ["10"]
    assert len(load.read_records(since=t(10).timestamp(), path=path)) == 2
    assert load.read_records(path=tmp_path / "missing.tsv") == []


# --- wait --------------------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


class Sink:
    def __init__(self):
        self.text = ""

    def write(self, s):
        self.text += s

    def flush(self):
        pass


def test_wait_times_out_with_the_last_refusal_and_one_progress_line_a_minute():
    clock, out, err = Clock(), Sink(), Sink()
    busy = snap(procs=procs(builds=2))
    code = load.wait("build", {}, 300, poll_s=15, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: busy, out=out, err=err)
    assert code == 3
    assert "2 builds already run (max 2)" in out.text
    assert 4 <= len(err.text.splitlines()) <= 6                  # ~one a minute over 300 s
    assert clock.t == 300


def test_wait_returns_zero_as_soon_as_the_slot_opens():
    clock, out, err = Clock(), Sink(), Sink()
    states = [snap(procs=procs(builds=3))] * 3 + [snap(procs=procs(builds=1))]
    it = iter(states)
    assert load.wait("build", {}, 900, poll_s=15, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: next(it), out=out, err=err) == 0
    assert clock.slept == [15, 15, 15] and out.text == ""
    assert len(err.text.splitlines()) == 1


def test_wait_fails_open_when_the_snapshot_fails_and_uses_the_config_timeout():
    clock, out, err = Clock(), Sink(), Sink()
    assert load.wait("sim", {}, 10, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: None, out=out, err=err) == 0
    busy = snap(procs=procs(sims=2))
    code = load.wait("sim", {"wait_timeout_s": 40}, None, poll_s=15, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: busy, out=out, err=err)
    assert code == 3 and sum(clock.slept) == 40


def test_wait_with_a_zero_timeout_checks_once():
    clock, out, err = Clock(), Sink(), Sink()
    busy = snap(procs=procs(sims=2))
    assert load.wait("sim", {}, 0, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: busy, out=out, err=err) == 3
    assert clock.slept == []


# --- the command -------------------------------------------------------------------------------

def args(**kw):
    base = dict(json=False, record=False, quiet=False, admit=None, wait=False, kind="build", timeout=None,
                replay=False, days=7)
    return argparse.Namespace(**{**base, **kw})


def crowded() -> Machine:
    m = Machine(sysctl_text(swap_used_mb=12000, pressure=2))          # 11.7 GB of 24 GB: 49%
    for i in range(3):
        m.add(100 + i, f"launchd_sim /x/Devices/{UDID_A}/data")
    return m


def test_text_report_leads_with_the_verdict_and_exits_by_level(capsys):
    m = crowded()
    assert load.cmd_load(args(), run=m.run) == 2
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("load: CRITICAL — swap 11.7 GB = 49% of RAM")
    assert any(ln.startswith("sims: 3 booted") for ln in lines) and any(ln.startswith("agents:") for ln in lines)
    calm = Machine(sysctl_text())
    calm.add(1, "/bin/ls")
    assert load.cmd_load(args(), run=calm.run) == 0
    busy = Machine(sysctl_text(pressure=2))
    busy.add(1, "/bin/ls")
    assert load.cmd_load(args(), run=busy.run) == 1


def test_json_and_quiet_never_exit_nonzero_for_the_load(capsys, tmp_path):
    m = crowded()
    assert load.cmd_load(args(json=True), run=m.run) == 0
    d = json.loads(capsys.readouterr().out)
    assert d["verdict"]["level"] == "CRITICAL" and d["snapshot"]["procs"]["sims"] == 3
    assert load.cmd_load(args(quiet=True, record=True), run=m.run) == 0
    assert capsys.readouterr().out == ""
    from teyla.corrections import teyla_home
    assert len(load.read_records(path=teyla_home() / "load.tsv")) == 1


def test_admit_prints_nothing_when_allowed_and_refuses_with_exit_2(capsys):
    quiet = Machine(sysctl_text())
    quiet.add(1, "/bin/ls")
    assert load.cmd_load(args(admit="build"), run=quiet.run) == 0
    assert capsys.readouterr().out == ""
    assert load.cmd_load(args(admit="sim"), run=crowded().run) == 2
    out = capsys.readouterr().out
    assert "sim refused" in out and UDID_A in out


def test_admit_fails_open_when_ps_fails_or_the_guard_is_off(capsys, tmp_path, monkeypatch):
    m = crowded()
    m.ps_fails = True
    assert load.cmd_load(args(admit="build"), run=m.run) == 0
    assert capsys.readouterr().out == ""

    def boom(cmd, timeout=60):
        raise RuntimeError("bug in the runner")
    assert load.cmd_load(args(admit="build"), run=boom) == 0

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "off.toml")
    assert config.set_value("guard.enabled", "false", tmp_path / "off.toml").startswith("set")
    assert load.cmd_load(args(admit="sim"), run=crowded().run) == 0
    assert load.cmd_load(args(wait=True, kind="sim", timeout=0), run=crowded().run) == 0
    assert capsys.readouterr().out == ""


def test_the_report_with_a_dead_ps_says_so_and_exits_zero(capsys):
    m = Machine()
    m.ps_fails = True
    assert load.cmd_load(args(), run=m.run) == 0
    assert "could not read the process table" in capsys.readouterr().err


def test_wait_through_the_command_times_out_with_exit_3(capsys, monkeypatch):
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None: snap(procs=procs(builds=5)))
    monkeypatch.setattr(load.time, "sleep", lambda s: None)
    t = iter(range(0, 10_000, 100))
    monkeypatch.setattr(load.time, "monotonic", lambda: next(t))
    assert load.cmd_load(args(wait=True, kind="build", timeout=250)) == 3
    assert "5 builds already run" in capsys.readouterr().out


def test_register_wires_the_flags():
    import teyla.cli as cli
    p = argparse.ArgumentParser()
    sp = p.add_subparsers()
    load.register(sp)
    a = p.parse_args(["load", "--admit", "sim"])
    assert a.fn is load.cmd_load and a.admit == "sim"
    a = p.parse_args(["load", "--wait", "--kind", "lane", "--timeout", "5"])
    assert a.wait and a.kind == "lane" and a.timeout == 5.0
    with pytest.raises(SystemExit):
        p.parse_args(["load", "--admit", "nope"])
    assert "teyla load" in cli.__doc__


# --- doctor ------------------------------------------------------------------------------------

def test_doctor_row_warns_at_critical_and_is_info_otherwise(monkeypatch):
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None: snap(swap_used_bytes=int(11.7 * GIB), pressure=2))
    row = doctor._load_check(config.load())
    assert row["level"] == "WARN" and row["name"] == "machine:load" and row["fix"] == "teyla load"
    assert "swap 11.7 GB" in row["detail"]
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None: snap(procs=procs(builds=3)))
    row = doctor._load_check(config.load())
    assert row["level"] == "INFO" and row["detail"].startswith("BUSY — 3 builds running")
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None: snap())
    assert doctor._load_check(config.load())["detail"] == "OK"
    monkeypatch.setattr(load, "safe_snapshot", lambda run=None: None)
    assert doctor._load_check(config.load())["level"] == "INFO"



def test_codex_lane_with_global_options_before_exec():
    p = classify(
        ps_line(1, "/opt/vendor/codex/codex -m gpt-6.1-sol -c model_reasoning_effort=medium exec task"),
        ps_line(2, "/opt/vendor/codex/codex fix the exec path in the build"),
    )
    assert p.codex == 2
    assert p.lanes == 1        # only the first positional argument names the subcommand


def test_record_takes_a_lock_beside_the_file(tmp_path):
    snap = load.Snapshot(time="2026-10-09T20:00:00+02:00")
    path = load.record(snap, load.assess(snap, load.guard_conf({})), path=tmp_path / "load.tsv")
    assert (tmp_path / "load.tsv.lock").exists()
    assert len(load.read_records(path=path)) == 1


def test_only_the_daemon_main_class_makes_a_build_daemon():
    p = classify(ps_line(1, "/jdk/bin/java -cp /k/kotlin-compiler-embeddable-2.0.jar com.example.Server"),
                 ps_line(2, "/jdk/bin/java -cp /k/kotlin-daemon-client.jar:/g/GradleDaemonTools.jar com.example.Tool"))
    assert p.daemons == []


def test_the_daemon_class_must_be_javas_main_class_not_a_program_argument():
    p = classify(ps_line(1, "/jdk/bin/java -cp app.jar com.example.Server org.jetbrains.kotlin.daemon.KotlinCompileDaemon"),
                 ps_line(2, "/jdk/bin/java -jar tool.jar org.gradle.launcher.daemon.bootstrap.GradleDaemon"),
                 ps_line(3, "/jdk/bin/java --add-opens java.base/java.lang=ALL-UNNAMED -Xmx2g -cp /g/a.jar "
                            "org.gradle.launcher.daemon.bootstrap.GradleDaemon 8.10"))
    assert [(d.pid, d.kind) for d in p.daemons] == [(3, "gradle")]


# --- the decision log --------------------------------------------------------------------------

def decisions():
    return load.read_decisions()


def test_decide_carries_the_verdict_and_a_one_line_reason():
    d = load.decide("build", snap(procs=procs(builds=2)), {})
    assert not d.allowed and d.level == "OK"          # at the cap is not above it
    assert d.reason == "2 builds already run (max 2)" and d.message.startswith("teyla guard: build refused")
    d = load.decide("sim", snap(swap_used_bytes=12 * GIB, pressure=4), {})
    assert not d.allowed and d.level == "CRITICAL" and d.reason.startswith("the machine is CRITICAL: ")
    ok = load.decide("lane", snap(), {})
    assert ok.allowed and ok.message == "" and ok.reason == "" and ok.level == "OK"
    assert load.admit("build", snap(procs=procs(builds=2)), {}) == (False, load.decide("build", snap(procs=procs(builds=2)), {}).message)


def test_admit_logs_each_decision_with_cwd_and_harness(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("TEYLA_HARNESS", "codex")
    monkeypatch.chdir(tmp_path)
    quiet = Machine(sysctl_text())
    quiet.add(1, "/bin/ls")
    assert load.cmd_load(args(admit="build"), run=quiet.run) == 0
    assert load.cmd_load(args(admit="sim"), run=crowded().run) == 2
    capsys.readouterr()
    ok, refused = decisions()
    assert (ok["kind"], ok["verdict"], ok["decision"], ok["reason"]) == ("build", "OK", "admitted", "")
    assert (refused["kind"], refused["verdict"], refused["decision"]) == ("sim", "CRITICAL", "refused")
    assert "swap" in refused["reason"] and refused["cwd"] == os.getcwd() and refused["harness"] == "codex"
    header = load.decisions_path().read_text().splitlines()[0]
    assert header == "#" + "\t".join(["time", "kind", "verdict", "decision", "reason", "cwd", "harness"])


def test_a_dead_ps_is_logged_as_unknown_and_a_disabled_guard_logs_nothing(tmp_path):
    m = crowded()
    m.ps_fails = True
    assert load.cmd_load(args(admit="build"), run=m.run) == 0
    (row,) = decisions()
    assert (row["verdict"], row["decision"]) == ("unknown", "admitted") and "snapshot failed" in row["reason"]
    off = tmp_path / "off.toml"
    config.CONFIG_PATH = off
    assert config.set_value("guard.enabled", "false", off).startswith("set")
    assert load.cmd_load(args(admit="sim"), run=crowded().run) == 0
    assert len(decisions()) == 1


def test_wait_logs_once_when_it_ends_not_once_per_poll():
    clock, out, err = Clock(), Sink(), Sink()
    states = [snap(procs=procs(builds=3))] * 3 + [snap(procs=procs(builds=1))]
    it = iter(states)
    assert load.wait("build", {}, 900, poll_s=15, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: next(it), out=out, err=err) == 0
    (row,) = decisions()
    assert (row["kind"], row["decision"], row["reason"]) == ("build", "admitted", "wait: after 45s wait")
    clock2 = Clock()
    busy = snap(procs=procs(sims=2))
    assert load.wait("sim", {}, 60, poll_s=15, clock=clock2.now, sleeper=clock2.sleep, snap_fn=lambda: busy, out=out, err=err) == 3
    last = decisions()[-1]
    assert (last["kind"], last["decision"]) == ("sim", "refused")
    assert last["reason"] == "wait: timeout after 60s: 2 simulators are already booted (max 2)"
    assert len(decisions()) == 2


def test_an_immediate_wait_logs_an_empty_reason_and_a_failed_snapshot_is_let_through():
    clock, out, err = Clock(), Sink(), Sink()
    assert load.wait("build", {}, 10, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: snap(), out=out, err=err) == 0
    assert load.wait("build", {}, 10, clock=clock.now, sleeper=clock.sleep, snap_fn=lambda: None, out=out, err=err) == 0
    first, second = decisions()
    assert first["reason"] == "wait" and second["verdict"] == "unknown"


def test_the_log_keeps_one_line_per_decision_and_its_newest_half(tmp_path, monkeypatch):
    path = tmp_path / "d.tsv"
    load.log_decision("build", "BUSY", False, "a\tb\nc", path=path)
    (row,) = load.read_decisions(path=path)
    assert row["reason"] == "a b c"
    monkeypatch.setattr(load, "DECISIONS_MAX_BYTES", 600)
    for i in range(30):
        load.log_decision("sim", "OK", True, f"n{i}", path=path)
    rows = load.read_decisions(path=path)
    assert rows[-1]["reason"] == "n29" and len(rows) < 30
    assert path.read_text().startswith("#time")


def test_logging_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    load.log_decision("build", "OK", True, "", path=blocker / "sub" / "d.tsv")      # the parent is a file


def test_harness_name_reads_the_environment():
    assert load.harness_name({"TEYLA_HARNESS": "grok", "CLAUDECODE": "1"}) == "grok"
    assert load.harness_name({"CLAUDECODE": "1"}) == "claude"
    assert load.harness_name({"CODEX_THREAD_ID": "x"}) == "codex"
    assert load.harness_name({"GROK_SESSION": "x"}) == "grok"
    assert load.harness_name({"PATH": "/bin"}) == ""


def test_decision_summary_counts_the_last_hour(tmp_path):
    path = tmp_path / "d.tsv"
    now = dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc)
    old = now - dt.timedelta(hours=2)
    for t, kind, ok in ((old, "sim", False), (now - dt.timedelta(minutes=50), "build", True),
                        (now - dt.timedelta(minutes=10), "sim", False), (now - dt.timedelta(minutes=5), "sim", False),
                        (now - dt.timedelta(minutes=1), "build", False)):
        load.log_decision(kind, "BUSY", ok, "r", path=path, now=t)
    assert load.decision_summary(now.timestamp(), path=path) == "guard, last hour: 1 admitted, 3 refused (build 1, sim 2)"
    assert load.decision_summary(now.timestamp() + 7200, path=path) == ""


def test_the_text_report_ends_with_the_last_hours_decisions(capsys):
    quiet = Machine(sysctl_text())
    quiet.add(1, "/bin/ls")
    load.log_decision("sim", "BUSY", False, "x")
    load.cmd_load(args(), run=quiet.run)
    assert capsys.readouterr().out.splitlines()[-1] == "guard, last hour: 0 admitted, 1 refused (sim 1)"


# --- replay ------------------------------------------------------------------------------------

def rec_row(tsv_time, **kw):
    base = dict(time=tsv_time, ts=0, level="OK", pressure=1, load1=1.0, swap_used_bytes=0, ram_bytes=24 * GIB,
                compressor_bytes=0, sims=0, builds=0, compiler_rss_bytes=0, daemon_rss_bytes=0, claude=1, codex=0,
                grok=0, lanes=0, chrome_rss_bytes=0, vm_rss_bytes=0, top3=[], disk_free_bytes=50 * GIB)
    return {**base, **kw}


def test_replay_counts_levels_and_admissions_per_day():
    rows = [rec_row("2026-10-17T10:00:00+02:00"),
            rec_row("2026-10-17T10:01:00+02:00", sims=2),                       # BUSY? no: at the cap, not above it
            rec_row("2026-10-18T10:00:00+02:00", pressure=2),                   # BUSY
            rec_row("2026-10-18T10:01:00+02:00", pressure=4, builds=1)]         # CRITICAL
    days = load.replay(rows, {}, ncpu=10)
    assert [d["day"] for d in days] == ["2026-10-17", "2026-10-18"]
    d17, d18 = days
    assert d17["levels"] == {"OK": 2, "BUSY": 0, "CRITICAL": 0} and d17["sim"] == {"OK": 1, "BUSY": 0, "CRITICAL": 0}
    assert d17["build"]["OK"] == 2
    assert d18["levels"] == {"OK": 0, "BUSY": 1, "CRITICAL": 1}
    assert d18["sim"] == {"OK": 0, "BUSY": 1, "CRITICAL": 0} and d18["build"] == {"OK": 0, "BUSY": 1, "CRITICAL": 0}


def test_replay_reads_the_thresholds_from_the_config():
    rows = [rec_row("2026-10-18T10:00:00+02:00", swap_used_bytes=7 * GIB)]       # 29% of RAM
    assert load.replay(rows, {}, ncpu=10)[0]["levels"]["BUSY"] == 1
    assert load.replay(rows, {"swap_warn_pct": 40}, ncpu=10)[0]["levels"]["OK"] == 1


def test_replay_turns_a_record_back_into_a_snapshot():
    s = load.snapshot_from_record(rec_row("2026-10-18T10:00:00+02:00", builds=2, sims=1, lanes=3, pressure=2), ncpu=8)
    assert (s.procs.builds, s.procs.sims, s.procs.lanes, s.pressure, s.ncpu) == (2, 1, 3, 2, 8)


def test_render_replay_has_a_row_per_day_and_a_total():
    days = load.replay([rec_row("2026-10-17T10:00:00+02:00"), rec_row("2026-10-18T10:00:00+02:00", pressure=2)], {}, ncpu=10)
    lines = load.render_replay(days).splitlines()
    assert lines[0].split()[:5] == ["day", "rows", "OK", "BUSY", "CRIT"]
    assert lines[1].startswith("2026-10-17") and lines[3].startswith("total")
    assert lines[3].split()[1:5] == ["2", "1", "1", "0"]
    assert "no recorded rows" in load.render_replay([])


def test_replay_command_reads_load_tsv_for_the_last_n_days(capsys):
    now = dt.datetime.now().astimezone()
    for days_ago, pressure in ((10, 4), (1, 2)):
        when = now - dt.timedelta(days=days_ago)
        snap_ = load.Snapshot(time=when.isoformat(timespec="seconds"), ram_bytes=24 * GIB, ncpu=10, load1=1.0, pressure=pressure,
                              swap_used_bytes=0, compressor_bytes=0, disk_free_bytes=50 * GIB)
        load.record(snap_, load.assess(snap_, {}))
    assert load.cmd_load(args(replay=True, days=3)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3 and lines[-1].split()[:5] == ["total", "1", "0", "1", "0"]


def test_register_wires_replay():
    p = argparse.ArgumentParser()
    load.register(p.add_subparsers())
    a = p.parse_args(["load", "--replay", "--days", "3"])
    assert a.replay and a.days == 3.0 and p.parse_args(["load", "--replay"]).days == 7

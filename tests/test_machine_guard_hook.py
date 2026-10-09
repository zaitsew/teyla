"""The machine guard's PreToolUse hook (`plugin/hooks/machine-guard.sh`), run for real through `sh`
with the hook JSON on stdin and a fake `teyla` first on PATH (it records its arguments and exits
with a chosen code). HOME and TEYLA_HOME point into tmp_path, so nothing reads the real ~/.teyla.

Heavy work is a build, a simulator boot or a headless agent lane; everything else must cost the
machine nothing: no `teyla`, and not even an `awk`."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOOK = ROOT / "plugin" / "hooks" / "machine-guard.sh"
REFUSAL = "teyla guard: build refused — swap is 91% of RAM (threshold 75%)\nWait for a slot: teyla load --wait --kind build"

FAKE_TEYLA = """#!/bin/sh
echo "$@" >> "$FAKE_CALLS"
case "$FAKE_MODE" in
  refuse) echo "teyla guard: $3 refused — swap is 91% of RAM (threshold 75%)"; echo "Wait for a slot: teyla load --wait --kind $3"; exit 2 ;;
  refuse-sim) if [ "$3" = sim ]; then echo "teyla guard: sim refused — two simulators are booted"; exit 2; fi; exit 0 ;;
  argparse) echo "usage: teyla load [-h]" >&2; exit 2 ;;
  crash) echo "Traceback (most recent call last):" >&2; exit 1 ;;
  segv) kill -SEGV $$ ;;
  *) exit 0 ;;
esac
"""


class Box:
    """A tmp HOME, a fake-bin directory with a recording `teyla`, and the plugin script's real path."""

    def __init__(self, tmp_path: pathlib.Path):
        self.home = tmp_path / "home"
        (self.home / ".teyla").mkdir(parents=True)
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.calls = tmp_path / "calls"
        self.calls.write_text("")
        self.tmp = tmp_path
        self.install_teyla()

    def install_teyla(self) -> None:
        t = self.bin / "teyla"
        t.write_text(FAKE_TEYLA)
        t.chmod(0o755)

    def config(self, text: str) -> None:
        (self.home / ".teyla" / "config.toml").write_text(text)

    def spy(self, tool: str) -> pathlib.Path:
        """A `tool` on PATH that only leaves a mark (and prints nothing)."""
        mark = self.tmp / f"{tool}.mark"
        p = self.bin / tool
        p.write_text(f'#!/bin/sh\ntouch "{mark}"\n')
        p.chmod(0o755)
        return mark

    def run(self, command, mode: str = "refuse", args=(), script: pathlib.Path = HOOK, payload=None, **env):
        if payload is None:
            payload = json.dumps({"session_id": "s", "transcript_path": "/srv/app/.claude/projects/-srv-app-repos-app/s.jsonl",
                                  "cwd": str(self.tmp), "hook_event_name": "PreToolUse",
                                  "tool_name": "Bash", "tool_input": {"command": command, "description": "d"}})
        e = {k: v for k, v in os.environ.items() if k not in ("TEYLA_HOME", "TEYLA_GUARD", "CLAUDE_PLUGIN_ROOT", "PYTHONPATH")}
        e.update(HOME=str(self.home), TEYLA_HOME=str(self.home / ".teyla"), FAKE_CALLS=str(self.calls),
                 FAKE_MODE=mode, PATH=f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin", **env)
        return subprocess.run(["sh", str(script), *args], input=payload, capture_output=True, text=True, timeout=20, env=e)

    def called(self) -> list[str]:
        return [l for l in self.calls.read_text().splitlines() if l]


@pytest.fixture
def box(tmp_path):
    return Box(tmp_path)


# --- the ordinary path costs nothing ------------------------------------------------------------

ORDINARY = [
    "ls -la", "git status", "git commit -m 'fix the xcodebuild flag'", 'git commit -m "bump gradle"',
    "grep -rn xcodebuild docs/", "cat gradle.properties", "echo swift build", "cargo --version", "cargo fmt",
    "cargo clippy", "swift package resolve", "swift --version", "python3 -m pytest -q", "npm test",
    "xcrun simctl list devices", "xcrun --sdk iphoneos --show-sdk-path", "claude --version", "claude plugin list",
    "codex --version", "codex login status", "grok --help", "teyla load --json", "teyla load --admit build",
    "rm -rf build/", "open -a Simulator", "sed -n 1,5p Package.swift", "ls ~/.codex/sessions",
]


@pytest.mark.parametrize("command", ORDINARY)
def test_an_ordinary_command_never_reaches_teyla(box, command):
    r = box.run(command)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), command
    assert box.called() == [], command


def test_an_ordinary_command_starts_no_awk_and_no_teyla(box):
    awk, py = box.spy("awk"), box.spy("python3")
    for command in ("ls", "git log --oneline", "cat Package.resolved"):
        assert box.run(command).returncode == 0
    assert not awk.exists() and not py.exists() and box.called() == []


def test_a_payload_that_never_mentions_a_command_is_allowed(box):
    for payload in ("", "{}", "not json", '{"tool_name": "Bash", "tool_input": {}}',
                    '{"tool_name": "Bash", "tool_input": {"command": 7}} xcodebuild'):
        r = box.run("", payload=payload)
        assert r.returncode == 0, payload
    assert box.called() == []


# --- what is heavy ------------------------------------------------------------------------------

HEAVY = [
    ("xcodebuild -scheme A test", "build"),
    ("cd /x && xcodebuild -scheme A test", "build"),
    ("cd /x; xcodebuild build | xcbeautify", "build"),
    ("(cd app && xcodebuild test)", "build"),
    ("FOO=1 BAR=2 xcodebuild test", "build"),
    ("env FOO=1 xcodebuild test", "build"),
    ("time xcodebuild test", "build"),
    ("xcrun xcodebuild test", "build"),
    ("/Applications/Xcode.app/Contents/Developer/usr/bin/xcodebuild test", "build"),
    ("sudo -u nobody xcodebuild test", "build"),
    ("nohup xcodebuild test > log 2>&1 &", "build"),
    ("if true; then xcodebuild test; fi", "build"),
    ("echo x\nxcodebuild test", "build"),
    ("swift build", "build"),
    ("swift test --parallel", "build"),
    ("xcrun swift build -c release", "build"),
    ("./gradlew assembleDebug", "build"),
    ("gradlew :app:test", "build"),
    ("gradle build", "build"),
    ("cd android && ./gradlew --no-daemon -q testDebugUnitTest", "build"),
    ("cargo build --release", "build"),
    ("cargo test", "build"),
    ("cargo +nightly build", "build"),
    ("bazel build //app:all", "build"),
    ("bazel test //...", "build"),
    ("xcrun simctl boot ABC", "sim"),
    ("xcrun simctl create Test com.apple.CoreSimulator.SimDeviceType.iPhone-17", "sim"),
    ("xcrun simctl clone ABC Copy", "sim"),
    ("simctl boot ABC", "sim"),
    ("xcrun simctl --set /tmp/devs boot ABC", "sim"),
    ("xcrun simctl bootstatus ABC -b", "sim"),
    ("xcrun simctl boot ABC && xcrun simctl launch ABC com.example.App", "sim"),
    ("codex exec 'review this diff'", "lane"),
    ("codex -m gpt-6.1-sol exec -", "lane"),
    ("~/ops/bin/codex-review --commit abc123", "lane"),
    ("codex-lane -m gpt-6-luna", "lane"),
    ("claude-review", "lane"),
    ("sh ~/ops/bin/codex-review", "lane"),
    ("claude -p 'summarise'", "lane"),
    ("claude --print --model sonnet hi", "lane"),
    ("cat prompt.md | claude -p", "lane"),
    ("grok -p 'research x'", "lane"),
    ("grok --prompt 'research x'", "lane"),
]


@pytest.mark.parametrize("command,kind", HEAVY)
def test_a_heavy_command_is_put_to_teyla_with_its_kind(box, command, kind):
    r = box.run(command, mode="allow")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), command
    assert box.called() == [f"load --admit {kind}"], command


READ_ONLY = [
    "xcodebuild -list", "xcodebuild -list -project A.xcodeproj", "xcodebuild -showsdks", "xcodebuild -version",
    "xcodebuild -showBuildSettings -scheme A", "xcodebuild -showdestinations -scheme A", "xcodebuild -help",
    "xcodebuild -scheme A -showBuildSettings | grep SDKROOT",
    "xcrun simctl list", "xcrun simctl list devices booted", "xcrun simctl io booted screenshot a.png",
    "xcrun simctl launch booted com.example.App", "xcrun simctl install booted A.app",
    "xcrun simctl spawn booted log stream", "xcrun simctl shutdown all", "xcrun simctl terminate booted com.example.App",
    "xcrun simctl erase ABC", "xcrun simctl delete ABC", "xcrun simctl bootstatus ABC",
    "./gradlew --stop", "./gradlew --version", "gradle -v", "./gradlew --status", "./gradlew",
    "cargo check", "cargo run", "bazel version", "bazel info",
]


@pytest.mark.parametrize("command", READ_ONLY)
def test_read_only_and_resource_freeing_commands_are_not_gated(box, command):
    r = box.run(command)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), command
    assert box.called() == [], command


def test_a_heavy_word_inside_a_quoted_string_or_an_argument_is_not_a_command(box):
    for command in ('echo "xcodebuild test"', "echo xcodebuild", 'git commit -m "xcodebuild test"', "man xcodebuild",
                    "grep 'simctl boot' notes.md", "which xcodebuild", "ls build/xcodebuild", "cat ./gradlew",
                    "git log --grep='cargo build'", "tail -f xcodebuild.log", "open codex-review.md"):
        r = box.run(command)
        assert (r.returncode, r.stderr) == (0, ""), command
    assert box.called() == []


def test_every_kind_in_a_compound_command_is_checked(box):
    r = box.run("xcodebuild test && xcrun simctl boot ABC", mode="refuse-sim")
    assert r.returncode == 2 and "teyla guard: sim refused" in r.stderr
    assert box.called() == ["load --admit build", "load --admit sim"]


def test_a_repeated_kind_is_asked_once(box):
    box.run("xcodebuild test; cargo build; swift build", mode="allow")
    assert box.called() == ["load --admit build"]


# --- the refusal --------------------------------------------------------------------------------

def test_a_refusal_is_exit_2_with_the_whole_text_on_stderr_and_nothing_on_stdout(box):
    r = box.run("cd /x && xcodebuild -scheme A test")
    assert r.returncode == 2 and r.stdout == ""
    assert r.stderr == REFUSAL + "\n"


def test_grok_mode_also_prints_the_full_reason_as_a_deny_decision(box):
    r = box.run("xcodebuild test", args=("--grok",))
    assert r.returncode == 2 and r.stderr == REFUSAL + "\n"
    d = json.loads(r.stdout)
    assert d["decision"] == "deny" and d["reason"] == REFUSAL + "\n"


def test_grok_mode_allowing_prints_nothing(box):
    r = box.run("xcodebuild test", mode="allow", args=("--grok",))
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


# --- it fails open ------------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["crash", "segv", "argparse"])
def test_a_broken_teyla_never_blocks(box, mode):
    # `argparse`: an older teyla without --admit exits 2 too, with a usage line and no refusal
    r = box.run("xcodebuild test", mode=mode)
    assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), mode
    assert box.called() == ["load --admit build"]


def test_a_missing_teyla_never_blocks(box, tmp_path):
    (box.bin / "teyla").unlink()
    # a copy of the script away from the repo, so there is no ../../src to fall back on
    lone = tmp_path / "plugin" / "hooks"
    lone.mkdir(parents=True)
    shutil.copy(HOOK, lone / "machine-guard.sh")
    r = box.run("xcodebuild test", script=lone / "machine-guard.sh")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")


def test_teyla_in_dot_local_bin_is_found_when_it_is_not_on_path(box):
    (box.home / ".local" / "bin").mkdir(parents=True)
    shutil.move(box.bin / "teyla", box.home / ".local" / "bin" / "teyla")
    r = box.run("xcodebuild test")
    assert r.returncode == 2 and r.stderr == REFUSAL + "\n"


@pytest.mark.skipif(sys.platform != "darwin", reason="`teyla load` reads macOS sysctl keys")
def test_without_teyla_on_path_the_plugins_own_sources_answer(box, tmp_path):
    # The repo's src is the fallback (pre-tool-use.sh does the same). Thresholds this low make any
    # machine CRITICAL, so the real `teyla load --admit` refuses without the fake.
    (box.bin / "teyla").unlink()
    py = box.bin / "python3"
    py.symlink_to(sys.executable)
    box.config("[guard]\nload_crit_per_core = 0.0001\nload_warn_per_core = 0.00001\n")
    r = box.run("xcodebuild test", CLAUDE_PLUGIN_ROOT=str(ROOT / "plugin"))
    assert r.returncode == 2, r.stderr
    assert r.stderr.startswith("teyla guard: build refused")


# --- the ways out -------------------------------------------------------------------------------

def test_a_command_that_already_waits_for_a_slot_is_allowed(box):
    for command in ("teyla load --wait --kind build && xcodebuild -scheme A test",
                    "teyla load --wait --kind sim --timeout 600 && xcrun simctl boot ABC",
                    "cd /x && teyla load --wait --kind build; ./gradlew assembleDebug"):
        r = box.run(command)
        assert (r.returncode, r.stderr) == (0, ""), command
    assert box.called() == []


def test_teyla_load_without_wait_does_not_excuse_a_build(box):
    assert box.run("teyla load --json && xcodebuild test").returncode == 2


def test_teyla_guard_zero_switches_it_off(box):
    r = box.run("xcodebuild test", TEYLA_GUARD="0")
    assert (r.returncode, r.stderr) == (0, "") and box.called() == []
    assert box.run("xcodebuild test", TEYLA_GUARD="1").returncode == 2


@pytest.mark.parametrize("text", ["[guard]\nenabled = false\n", "[guard]\nenabled=false # off\n", '[guard]\nenabled = "false"\n',
                                  "[guard]\nenabled = 0\n", "[other]\nx = 1\n\n[guard]\nmax_sims = 2\nenabled = false\n",
                                  "[guard]\nenabled = true\nenabled = false\n", "[guard]\r\nenabled = false\r\n"])
def test_config_enabled_false_switches_it_off(box, text):
    box.config(text)
    r = box.run("xcodebuild test")
    assert (r.returncode, r.stderr) == (0, ""), text
    assert box.called() == []


@pytest.mark.parametrize("text", ["[guard]\nenabled = true\n", "[guard]\nmax_sims = 3\n", "[other]\nenabled = false\n",
                                  "# [guard]\n# enabled = false\n", "[hooks]\nenabled = false\n[guard]\nenabled = true\n",
                                  "[guard]\nenabled = false\nenabled = true\n"])
def test_config_that_does_not_say_off_leaves_the_guard_on(box, text):
    box.config(text)
    assert box.run("xcodebuild test").returncode == 2, text


# --- the shape of the JSON ----------------------------------------------------------------------

def test_escaped_quotes_newlines_and_unicode_in_the_command_are_read(box):
    raw = '{"tool_name":"Bash","tool_input":{"command":"bash -c \\"cd \\\\\\"/x y\\\\\\" && xcodebuild -scheme A test\\"","description":"d"}}'
    assert box.run("", payload=raw).returncode == 2
    raw = '{"tool_input":{"command":"echo done\\n\\txcrun simctl boot ABC\\n","description":"x"}}'
    assert box.run("", payload=raw).returncode == 2 and box.called()[-1] == "load --admit sim"
    raw = '{"tool_input":{"command":"echo caf\\u00e9 \\u0026\\u0026 cargo build"}}'
    assert box.run("", payload=raw).returncode == 2


def test_bash_c_with_either_kind_of_quote_is_a_heavy_command(box):
    for command in ("bash -c 'xcodebuild test'", 'sh -c "cargo build"', "zsh -lc 'cd x && swift test'", "bash -ec \"./gradlew build\""):
        assert box.run(command).returncode == 2, command


def test_a_description_that_mentions_a_tool_does_not_make_a_command_heavy(box):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls", "description": "Check that xcodebuild and cargo build work"}})
    r = box.run("", payload=payload)
    assert (r.returncode, r.stderr) == (0, "") and box.called() == []


def test_a_pretty_printed_payload_and_codex_and_grok_field_names_work(box):
    pretty = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "t",
                         "tool_input": {"command": "xcodebuild test"}}, indent=2)
    assert box.run("", payload=pretty).returncode == 2
    grok = json.dumps({"hookEventName": "pre_tool_use", "toolName": "run_terminal_command",
                       "toolInput": {"command": "xcrun simctl boot ABC"}})
    assert box.run("", payload=grok, args=("--grok",)).returncode == 2
    assert box.called()[-1] == "load --admit sim"


def test_a_very_long_command_is_still_read(box):
    command = "echo " + "x" * 12000 + " && xcodebuild test"
    assert box.run(command).returncode == 2


# --- it is wired --------------------------------------------------------------------------------

def test_the_plugin_registers_it_on_bash_next_to_the_kill_switch_hook():
    hooks = json.loads((ROOT / "plugin" / "hooks" / "hooks.json").read_text())["hooks"]["PreToolUse"]
    commands = [(g.get("matcher"), h["command"], h["timeout"]) for g in hooks for h in g["hooks"]]
    assert (None, 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/pre-tool-use.sh"', 10) in commands  # unchanged
    assert ("Bash", 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/machine-guard.sh"', 15) in commands
    assert (ROOT / "plugin" / "hooks" / "machine-guard.sh").stat().st_mode & 0o111


# --- review round 1 (Codex, PR #147): quotes, per-kind waits, option values, tabs ---------------------

def test_separators_inside_quotes_do_not_split_a_command(box):
    for command in ("git commit -m 'fix parser; xcodebuild test'", 'git commit -m "fix: a && xcodebuild test"',
                    "echo 'a | cargo build'", "grep 'simctl boot' notes.md", 'echo "xcodebuild"',
                    'git commit -m "wire xcodebuild; then swift build | tee"', "echo \"it's; xcodebuild test\"",
                    "git commit -m 'x\ny; ./gradlew build'", "echo 'a' \"b;c\" && ls"):
        r = box.run(command)
        assert (r.returncode, r.stderr) == (0, ""), command
    assert box.called() == []


def test_a_separator_after_a_closed_quote_still_splits(box):
    for command in ("echo 'a' && xcodebuild test", 'echo "a;b" && xcodebuild test', "echo 'x'; cargo build",
                    "echo \"a\\\" b\" | swift build", "git commit -m 'm' && ./gradlew assembleDebug"):
        assert box.run(command).returncode == 2, command


def test_the_script_of_a_shell_dash_c_is_classified_by_the_same_rules(box):
    heavy = ['bash -c "cd x && xcodebuild test"', "sh -c 'a; cargo build'", "bash -lc 'cd x && swift test'",
             "bash -c \"bash -c 'xcodebuild test'\"", 'sh -c "echo hi; xcrun simctl boot ABC"',
             "env FOO=1 bash -c 'xcodebuild test'", "bash -c xcodebuild test", "zsh -c \"cd \\\"/x y\\\" && xcodebuild test\""]
    for command in heavy:
        assert box.run(command).returncode == 2, command
    for command in ("bash -c \"echo 'xcodebuild'\"", "sh -c 'echo xcodebuild; ls'", "bash -c 'git commit -m \"xcodebuild\"'",
                    "bash -c \"grep 'simctl boot' f\"", "bash script.sh", "sh -c 'ls'"):
        r = box.run(command)
        assert (r.returncode, r.stderr) == (0, ""), command


def test_a_wait_covers_only_the_kind_it_names(box):
    cases = [
        ("teyla load --wait --kind build && xcrun simctl boot ABC", ["sim"]),
        ("teyla load --wait --kind sim && xcodebuild test", ["build"]),
        ("teyla load --wait --kind=sim && xcrun simctl boot ABC && cargo build", ["build"]),
        ("teyla load --wait && xcrun simctl boot ABC", ["sim"]),  # --kind defaults to build in the CLI
        ("teyla load --wait --kind lane && claude -p hi && xcodebuild test", ["build"]),
        ("xcodebuild test && teyla load --wait --kind build", ["build"]),  # a wait after the work covers nothing
        ("teyla load --wait --kind build && xcrun simctl boot ABC && codex exec x", ["sim", "lane"]),
    ]
    for command, kinds in cases:
        box.calls.write_text("")
        box.run(command, mode="allow")
        assert box.called() == [f"load --admit {k}" for k in kinds], command


def test_a_wait_for_the_default_kind_covers_a_build(box):
    for command in ("teyla load --wait && xcodebuild test", "teyla load --wait --kind build --timeout 60 && cargo test",
                    "bash -c 'teyla load --wait --kind sim && xcrun simctl boot ABC'"):
        r = box.run(command)
        assert (r.returncode, r.stderr) == (0, ""), command
    assert box.called() == []


def test_option_values_are_not_mistaken_for_the_subcommand(box):
    heavy = ["bazel --output_base /tmp/bazel build //app:all", "bazel --output_base=/x test //...", "bazelisk --host_jvm_args=-Xmx2g build //x",
             "cargo --config build.jobs=2 test", "cargo +nightly -Z unstable-options test", "cargo test -- --nocapture",
             "swift -Xswiftc -v build", "swift --package-path /tmp/p test", "cargo -q build --release"]
    for command in heavy:
        assert box.run(command).returncode == 2, command
    for command in ["bazel run //x -- build", "cargo run -- test", "bazel --output_base /tmp/build info", "cargo fmt -- --check",
                    "swift package --package-path /tmp/test resolve", "bazel query //x", "swift --version"]:
        r = box.run(command)
        assert (r.returncode, r.stderr) == (0, ""), command


def test_a_tab_between_words_does_not_get_past_the_screen(box):
    for command in ("cargo\tbuild", "swift\ttest", "xcodebuild\t-scheme\tA\ttest", "claude\t-p\thi", "grok\t-p x",
                    "codex\texec x", "xcrun\tsimctl\tboot\tABC", "./gradlew\tassembleDebug", "bazel\tbuild //x"):
        raw = json.dumps({"tool_input": {"command": command}})
        assert "\\t" in raw  # a JSON \t escape, not a space
        assert box.run("", payload=raw).returncode == 2, command


def test_the_screen_ignores_the_transcript_path_and_cwd_that_precede_the_command(box):
    awk = box.spy("awk")
    payload = json.dumps({"session_id": "s", "transcript_path": "/srv/app/.claude/projects/-srv-app-repos-swift-gradle-cargo/s.jsonl",
                          "cwd": "/srv/app/repos/codex-grok-bazel", "tool_name": "Bash", "tool_input": {"command": "ls -la"}})
    assert box.run("", payload=payload).returncode == 0
    assert not awk.exists()
    # ... while a command that names a tool (a .swift file counts) goes on to the exact classifier
    assert box.run("cat Sources/App.swift").returncode == 0 and awk.exists()

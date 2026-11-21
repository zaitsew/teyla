"""The autouse guard in tests/conftest.py: a test cannot signal a process, quit an app or run osascript,
killall, pkill or a launchctl write by accident. `@pytest.mark.real_process_calls` opts a test out."""
from __future__ import annotations

import os
import subprocess

import pytest

from teyla import guard, storage_apps, storage_procs


def test_the_real_kill_is_refused():
    with pytest.raises(AssertionError, match="real os.kill"):
        os.kill(os.getpid(), 15)


def test_a_liveness_probe_is_allowed():
    os.kill(os.getpid(), 0)


def test_a_default_ctx_cannot_kill():
    with pytest.raises(AssertionError, match="os.kill"):
        storage_procs.Ctx().kill(os.getpid(), 15)


def test_a_default_env_cannot_quit_an_app():
    with pytest.raises(AssertionError, match="app quit"):
        guard.Env().quit_app("com.example.app", 1)
    with pytest.raises(AssertionError, match="app quit"):
        storage_apps.quit_bundle("com.example.app", 1)


@pytest.mark.parametrize("argv", [["osascript", "-e", "1"], ["killall", "x"], ["/usr/bin/pkill", "x"],
                                  ["launchctl", "bootout", "gui/1/x"]])
def test_a_real_tool_spawn_is_refused(argv):
    with pytest.raises(AssertionError, match="real"):
        subprocess.run(argv, capture_output=True)


def test_a_harmless_command_still_runs():
    assert subprocess.run(["echo", "ok"], capture_output=True, text=True).stdout.strip() == "ok"


@pytest.mark.real_process_calls
def test_the_marker_opts_out():
    assert "_real_kill_guard" not in os.kill.__qualname__
    os.kill(os.getpid(), 0)


def test_a_test_may_signal_its_own_child_and_a_timeout_cleans_up():
    # subprocess.run kills the child on timeout and then waits for it; the guard used to raise in
    # Popen.kill and the cleanup then hung.
    import sys
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    child.kill()
    assert child.wait(timeout=10) != 0


def test_a_pid_the_test_did_not_start_is_still_refused():
    with pytest.raises(AssertionError, match="real os.kill"):
        os.kill(os.getppid(), 15)           # the parent of the test run is foreign

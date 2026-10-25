"""Suite-wide safety net. Every test starts outside safe mode and away from the real
~/.teyla/config.toml (and the update records beside it): config.load() is called from deep
inside products, routines, models and doctor, and a work laptop with `[safe] enabled = true`
(or TEYLA_SAFE=1 in the shell) would otherwise change what they do.

TEYLA_HOME points into a tmp dir for every test, so code that resolves ~/.teyla at call time
(the correction store, the control plane) cannot write to the real one even when a test
forgets to isolate HOME. On 2026-09-29 two hook tests that predate the store wrote five
records into the real ~/.teyla/corrections/ before this existed. Tests that exercise
HOME-based resolution unset it themselves."""
from __future__ import annotations

import os
import pathlib
import subprocess

import pytest

from teyla import config, net, providers, routine_install, update
from teyla.control import triggers
from teyla.adapters import claude_code, codex, cursor, grok, hermes


@pytest.fixture(autouse=True)
def _teyla_home_in_tmp(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path_factory.mktemp("teyla-home")))
    # corrections.grok_headless reads Grok's session store; never this Mac's ~/.grok.
    monkeypatch.setenv("GROK_HOME", str(tmp_path_factory.mktemp("grok-home")))
    monkeypatch.delenv("GROK_SESSION_ID", raising=False)
    # The capture hook skips headless runs by these (corrections.headless); a suite started
    # from `claude -p` or `hermes -z` would otherwise see every hook test record nothing.
    for var in ("CLAUDE_CODE_ENTRYPOINT", "HERMES_YOLO_MODE", "HERMES_ACCEPT_HOOKS", "HERMES_INTERACTIVE",
                "HERMES_SINGLE_QUERY_SESSION"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_real_config(tmp_path, monkeypatch):
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "conftest-config.toml")
    # update.py records what `teyla update` installed; a test must never write the real one.
    monkeypatch.setattr(update, "CHECK_PATH", tmp_path / "conftest-update-check.json")
    monkeypatch.setattr(update, "INSTALLED_PATH", tmp_path / "conftest-installed.json")
    # ...nor read the provenance of whatever `teyla` this interpreter has installed.
    monkeypatch.setattr(update, "_dist_commit", lambda: None)
    # ...nor read the owner's admin keys and call the providers' cost APIs (`teyla spend`).
    monkeypatch.setattr(providers, "keychain", lambda service: None)
    net.allow_for_this_command(False)
    yield
    net.allow_for_this_command(False)


@pytest.fixture(autouse=True)
def _no_real_transcripts(tmp_path_factory, monkeypatch):
    """Every adapter reads an empty, missing root unless the test hands it one. `doctor.checks()`
    loads the last week's sessions of every harness; before this it parsed this Mac's real
    ~/.claude/projects, ~/.codex and ~/.grok — the doctor tests took 184 s under load and
    depended on whatever transcripts the machine happened to hold."""
    none = tmp_path_factory.mktemp("no-transcripts")
    for mod in (claude_code, codex, cursor, grok, hermes):
        monkeypatch.setattr(mod, "DEFAULT_ROOT", str(none / mod.__name__.rsplit(".", 1)[-1]))
    monkeypatch.setattr(codex, "DEFAULT_ARCHIVE_ROOT", str(none / "codex-archive"))


@pytest.fixture(autouse=True)
def _no_real_crash_reports(monkeypatch):
    """`teyla crash`, doctor's `machine:crash` and the digest read /Library/Logs/DiagnosticReports; a test
    must not depend on whether this Mac has panicked this week. Tests that want reports pass roots."""
    from teyla import crash
    monkeypatch.setattr(crash, "DEFAULT_ROOTS", [])


_LAUNCHCTL_WRITES = {"bootstrap", "bootout", "load", "unload", "enable", "disable", "kickstart", "kill", "remove", "submit"}


@pytest.fixture(autouse=True)
def _no_real_launchd(tmp_path_factory, monkeypatch):
    """No test reaches this Mac's launchd or ~/Library/LaunchAgents, whatever its own fixture forgets.

    On 2026-10-10 a runs_root test isolated only routine_install.WRAPPER_PATH. Its install() wrote the
    real daily.sh (naming the fake /opt/tools/bin/teyla) and the real daily and weekly plists, and,
    since its config had the optional agents off, booted out and deleted the real sims, sweep and
    load agents. The machine ran a day without its guard and sweep, filled its disk and hung.

    Every Path constant of routine_install and control.triggers under the real home is moved into
    a tmp home; `_real_launch_agents` names a directory nothing is written to, so `_load` and
    `_unload` refuse any plist a test did not stub them for; and a launchctl verb that changes
    launchd fails the test. A test that runs a fake launchctl first on PATH sets
    TEYLA_LAUNCHD_ANY_HOME=1, as before."""
    home = tmp_path_factory.mktemp("launchd-home")
    real = pathlib.Path.home()
    for mod in (routine_install, triggers):
        for name, value in list(vars(mod).items()):
            if isinstance(value, pathlib.Path) and value.is_relative_to(real):
                monkeypatch.setattr(mod, name, home / value.relative_to(real))
    monkeypatch.setattr(routine_install, "_real_launch_agents", lambda: home / "no-real-launchd")
    real_run = subprocess.run

    def run(cmd, *a, **k):
        argv = cmd if isinstance(cmd, (list, tuple)) else str(cmd).split()
        if (argv and os.path.basename(str(argv[0])) == "launchctl" and len(argv) > 1
                and str(argv[1]) in _LAUNCHCTL_WRITES and os.environ.get("TEYLA_LAUNCHD_ANY_HOME") != "1"):
            raise AssertionError(f"a test reached the real launchctl: {' '.join(map(str, argv))}")
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(subprocess, "run", run)


@pytest.fixture(autouse=True)
def _no_real_disk(monkeypatch):
    """`load.snapshot` reads the free space of the real home volume. A verdict in a test must not
    depend on how full this Mac is, and `guard tick` must never sweep it. Tests pass disk_free_bytes."""
    from teyla import load
    monkeypatch.setattr(load, "disk_free", lambda: None)


@pytest.fixture(autouse=True)
def _no_real_asks_sources(tmp_path_factory, monkeypatch):
    """`teyla asks` reads the Claude desktop app's session metadata and the reminders file. A test
    that forgets to hand it a root must see an empty machine, not this Mac's open questions."""
    from teyla import remind
    none = tmp_path_factory.mktemp("no-asks")
    monkeypatch.setenv("TEYLA_CLAUDE_SESSIONS", str(none / "claude-code-sessions"))
    monkeypatch.setattr(remind, "REMINDERS_PATH", none / "reminders.toml")


@pytest.fixture(autouse=True)
def _no_real_claude_for_state_brief(monkeypatch):
    """`teyla state` starts a detached refresh that runs `claude -p` and another that runs `gh`; no test may
    start either."""
    from teyla import backlog, state
    monkeypatch.setattr(backlog, "spawn_refresh", lambda *a, **k: None)
    monkeypatch.setattr(backlog, "default_runner", lambda argv: (127, "", "a test reached the real gh"))

    def _refuse(*a, **k):
        raise AssertionError("a test reached the real claude; monkeypatch state._run_claude")
    monkeypatch.setattr(state, "_spawn_brief_refresh", lambda *a, **k: None)
    monkeypatch.setattr(state, "_run_claude", _refuse)


@pytest.fixture
def fake_code_root(monkeypatch):
    """Every directory directly under /Users/someone/repos is an unregistered git checkout under
    code_root, so the placeholder paths the asks and state tests use keep their repo name as the
    product without a real tree on disk."""
    from teyla import registry
    root = pathlib.Path("/Users/someone/repos")
    monkeypatch.setattr(config, "code_root", lambda cfg=None: root)
    monkeypatch.setattr(registry, "_is_checkout", lambda d: d.parent == root)
    return root


# --- `teyla start`: a whole fake machine ------------------------------------------------------

class FakeHome:
    """A temporary HOME with generic Claude Code / Codex session stores and builders for synthetic
    transcripts. Nothing here names a real product, person or path."""

    def __init__(self, home: pathlib.Path):
        self.home = home
        self.projects = home / ".claude" / "projects"

    @property
    def settings(self) -> pathlib.Path:
        return self.home / ".claude" / "settings.json"

    @staticmethod
    def ts(age_days: float, step: int = 0) -> str:
        import datetime as dt
        t = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age_days) + dt.timedelta(seconds=step)
        return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    @staticmethod
    def usage(cread=0, out=0, inp=0, cwrite=0) -> dict:
        return {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cread,
                "cache_creation_input_tokens": cwrite}

    def _write(self, path: pathlib.Path, records: list[dict]) -> None:
        import json
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in records))

    def _assistant(self, ts: str, mid: str, model: str, usage: dict, tools=()) -> dict:
        content = [{"type": "text", "text": "ok"}]
        content += [{"type": "tool_use", "id": f"toolu_{mid}_{n}", "name": t, "input": {}} for n, t in enumerate(tools)]
        return {"type": "assistant", "timestamp": ts, "cwd": "/work/demo", "message": {
            "id": mid, "role": "assistant", "model": model, "usage": usage, "content": content}}

    def session(self, sid: str, messages: list[tuple[str, dict]], project: str = "-work-demo", age_days: float = 2.0) -> pathlib.Path:
        """A Claude Code transcript: one assistant message per (model, usage) pair."""
        recs = [self._assistant(self.ts(age_days, i), f"{sid}-m{i}", model, usage)
                for i, (model, usage) in enumerate(messages)]
        p = self.projects / project / f"{sid}.jsonl"
        self._write(p, recs)
        return p

    def subagent(self, sid: str, agent: str, model: str, usage: dict, explicit: str | None = None,
                 kind: str = "general-purpose", tools=(), project: str = "-work-demo", age_days: float = 2.0) -> None:
        """One subagent call of session `sid`. `explicit`: the model the Agent call named (None: it named none)."""
        import json
        d = self.projects / project / sid / "subagents"
        self._write(d / f"agent-{agent}.jsonl", [self._assistant(self.ts(age_days, 1), f"{agent}-m0", model, usage, tools)])
        meta = {"agentType": kind, "description": "d", "toolUseId": f"toolu_{agent}"}
        if explicit:
            meta["model"] = explicit
        (d / f"agent-{agent}.meta.json").write_text(json.dumps(meta))

    def codex_session(self, sid: str, model: str, input_tokens: int, output_tokens: int, age_days: float = 2.0) -> None:
        import json
        import datetime as dt
        day = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=age_days))
        p = self.home / ".codex" / "sessions" / day.strftime("%Y/%m/%d") / f"rollout-{day.strftime('%Y-%m-%dT%H-%M-%S')}-{sid}.jsonl"
        self._write(p, [
            {"type": "session_meta", "timestamp": self.ts(age_days), "payload": {"id": sid, "cwd": "/work/demo"}},
            {"type": "turn_context", "timestamp": self.ts(age_days, 1), "payload": {"model": model}},
            {"type": "event_msg", "timestamp": self.ts(age_days, 2), "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": input_tokens, "output_tokens": output_tokens}}}}])

    def tree(self) -> dict:
        """Every file under HOME and TEYLA_HOME with its bytes: what a read-only command must leave alone."""
        import os
        out = {}
        for root in (self.home, pathlib.Path(os.environ["TEYLA_HOME"])):
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if name == "start-report.json":     # what `teyla start` leaves for the first screen: not a change to a tool
                        continue
                    p = pathlib.Path(dirpath, name)
                    out[str(p)] = p.read_bytes()
        return out


@pytest.fixture
def fake_home(tmp_path_factory, monkeypatch):
    """A fake HOME for `teyla start` tests: session stores, harness and policy paths all moved into it, and
    the launchd listing emptied. The real ~/.claude, ~/.codex and ~/Library are never read or written."""
    from teyla import harness, policy, uninstall
    home = tmp_path_factory.mktemp("start-home")
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(claude_code, "DEFAULT_ROOT", str(home / ".claude" / "projects"))
    monkeypatch.setattr(codex, "DEFAULT_ROOT", str(home / ".codex" / "sessions"))
    monkeypatch.setattr(codex, "DEFAULT_ARCHIVE_ROOT", str(home / ".codex" / "archived_sessions"))
    monkeypatch.setattr(harness, "HOME", home)
    monkeypatch.setattr(harness, "HOOKS_DIR", home / ".teyla" / "hooks")
    monkeypatch.setattr(policy, "HOME", home)
    monkeypatch.setattr(policy, "POLICY", home / ".agents" / "POLICY.md")
    monkeypatch.setattr(policy, "TARGETS", {
        "claude-code": home / ".claude" / "CLAUDE.md", "codex": home / ".codex" / "AGENTS.md",
        "grok": home / ".grok" / "AGENTS.md", "hermes": home / ".hermes" / "SOUL.md",
        "cursor": home / ".cursor" / "skills" / "teyla-policy" / "SKILL.md"})
    monkeypatch.setattr(policy, "CLAUDE_GLOBAL", home / ".claude" / "CLAUDE.md")
    monkeypatch.setattr(policy, "ACK_PATH", home / ".teyla" / "ack.json")
    monkeypatch.setattr(uninstall, "_launchctl_list", lambda: "")
    return FakeHome(home)

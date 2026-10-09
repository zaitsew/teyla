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

import pytest

from teyla import config, net, providers, update
from teyla.adapters import claude_code, codex, cursor, grok, hermes


@pytest.fixture(autouse=True)
def _teyla_home_in_tmp(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path_factory.mktemp("teyla-home")))
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

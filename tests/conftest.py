"""Every test starts outside safe mode and away from the real ~/.teyla/config.toml (and the
update records beside it): config.load()
is called from deep inside products, routines, models and doctor, and a work laptop with
`[safe] enabled = true` (or TEYLA_SAFE=1 in the shell) would otherwise change what they do."""
from __future__ import annotations

import pytest

from teyla import config, net, update


@pytest.fixture(autouse=True)
def _no_real_config(tmp_path, monkeypatch):
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "conftest-config.toml")
    # update.py records what `teyla update` installed; a test must never write the real one.
    monkeypatch.setattr(update, "CHECK_PATH", tmp_path / "conftest-update-check.json")
    monkeypatch.setattr(update, "INSTALLED_PATH", tmp_path / "conftest-installed.json")
    # ...nor read the provenance of whatever `teyla` this interpreter has installed.
    monkeypatch.setattr(update, "_dist_commit", lambda: None)
    net.allow_for_this_command(False)
    yield
    net.allow_for_this_command(False)

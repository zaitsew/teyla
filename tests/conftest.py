"""Every test starts outside safe mode and away from the real ~/.teyla/config.toml: config.load()
is called from deep inside products, routines, models and doctor, and a work laptop with
`[safe] enabled = true` (or TEYLA_SAFE=1 in the shell) would otherwise change what they do."""
from __future__ import annotations

import pytest

from teyla import config, net


@pytest.fixture(autouse=True)
def _no_real_config(tmp_path, monkeypatch):
    monkeypatch.delenv("TEYLA_SAFE", raising=False)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "conftest-config.toml")
    net.allow_for_this_command(False)
    yield
    net.allow_for_this_command(False)

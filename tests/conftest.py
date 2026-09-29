"""Suite-wide safety net: TEYLA_HOME points into a tmp dir for every test, so code that
resolves ~/.teyla at call time (the correction store, the control plane) cannot write to
the real one even when a test forgets to isolate HOME. On 2026-09-29 two hook tests that
predate the store wrote five records into the real ~/.teyla/corrections/ before this
existed. Tests that exercise HOME-based resolution unset it themselves."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _teyla_home_in_tmp(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path_factory.mktemp("teyla-home")))

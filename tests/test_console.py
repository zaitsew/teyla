"""`teyla console` (docs/CONSOLE.md): one section failing never takes the others down."""
from __future__ import annotations

import json
import stat
import types

from teyla import cli, console


def fake(monkeypatch, **mods):
    def load(name):
        if name in mods:
            return mods[name]
        raise ImportError(name)
    monkeypatch.setattr(console, "_module", load)


def good(value=1):
    return types.SimpleNamespace(section=lambda now: {"headline": {"label": "x", "value": value}, "rows": [1, 2]})


def test_a_failing_section_shows_its_error_and_the_rest_load(monkeypatch):
    fake(monkeypatch, operations=good())
    rep = console.build(now=5.0)
    assert rep["operations"]["headline"]["value"] == 1
    assert "ImportError" in rep["money"]["error"]


def test_cache_is_private(monkeypatch, tmp_path):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path))
    console.write_cache({"version": 1, "generated": 1.0})
    assert stat.S_IMODE(console.cache_path().stat().st_mode) == 0o600
    assert console.read_cache()["generated"] == 1.0


def test_compact_keeps_the_headline_only_by_default(monkeypatch):
    fake(monkeypatch, operations=good())
    rep = {"version": 1, "generated": 1.0, "operations": {"headline": {"value": 3}, "rows": [1]}}
    assert console.compact(rep)["operations"] == {"headline": {"value": 3}}
    assert console.compact(None) is None


def test_cli_prints_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TEYLA_HOME", str(tmp_path))
    fake(monkeypatch, operations=good(7))
    assert cli.main(["console", "--json", "--refresh"]) == 0
    assert json.loads(capsys.readouterr().out)["operations"]["headline"]["value"] == 7

"""runs_root: where the weekly routine files its reports. A config key, default <ops_root>/runs;
an install that predates the key and already has its reports in the older place keeps them."""
import pathlib

import pytest

from teyla import config, routine_install, uninstall


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".teyla").mkdir(parents=True)
    monkeypatch.setattr(config, "HOME", home)
    monkeypatch.setattr(config, "TEYLA_DIR", home / ".teyla")
    monkeypatch.setattr(config, "CONFIG_PATH", home / ".teyla" / "config.toml")
    monkeypatch.setattr(routine_install, "WRAPPER_PATH", home / ".teyla" / "weekly.sh")
    return home


def _legacy(ops: pathlib.Path) -> pathlib.Path:
    return ops.joinpath(*config._LEGACY_RUNS)


def test_default_is_runs_under_ops_root(tmp_path):
    config.set_value("ops_root", str(tmp_path / "ops"))
    assert config.runs_root() == tmp_path / "ops" / "runs"


def test_explicit_runs_root_wins_and_expands_tilde(tmp_path):
    config.set_value("ops_root", str(tmp_path / "ops"))
    assert config.set_value("runs_root", "~/reports").startswith("set runs_root")
    assert config.runs_root() == pathlib.Path("~/reports").expanduser()
    config.set_value("runs_root", str(tmp_path / "elsewhere"))
    _legacy(tmp_path / "ops").mkdir(parents=True)  # even with an old tree present
    assert config.runs_root() == tmp_path / "elsewhere"


def test_legacy_tree_is_kept_when_the_key_is_unset(tmp_path):
    config.set_value("ops_root", str(tmp_path / "ops"))
    assert config.runs_root() == tmp_path / "ops" / "runs"
    _legacy(tmp_path / "ops").mkdir(parents=True)
    assert config.runs_root() == _legacy(tmp_path / "ops")
    config.set_value("runs_root", str(tmp_path / "new"))
    assert config.runs_root() == tmp_path / "new"
    config.set_value("runs_root", None)  # unset: back to the fallback chain
    assert config.runs_root() == _legacy(tmp_path / "ops")


def test_config_show_names_the_effective_root(tmp_path):
    config.set_value("ops_root", str(tmp_path / "ops"))
    assert f"reports go to {tmp_path / 'ops' / 'runs'}" in config.show()
    config.set_value("runs_root", str(tmp_path / "r"))
    assert str(tmp_path / "r") in config.show() and "reports go to" not in config.show()


def test_changing_runs_root_makes_the_wrapper_stale_and_rewritten(tmp_path, monkeypatch):
    monkeypatch.setattr(routine_install, "_load", lambda plist, label: f"loaded {label}")
    monkeypatch.setattr(routine_install, "_teyla_bin", lambda: "/opt/tools/bin/teyla")
    config.set_value("ops_root", str(tmp_path / "ops"))
    routine_install.install()
    assert f'OUT_DIR="{tmp_path / "ops" / "runs"}/' in routine_install.WRAPPER_PATH.read_text()
    assert not routine_install.is_stale()
    config.set_value("runs_root", str(tmp_path / "reports"))
    assert routine_install.is_stale()
    routine_install.install()
    assert f'OUT_DIR="{tmp_path / "reports"}/' in routine_install.WRAPPER_PATH.read_text()
    assert not routine_install.is_stale()


def test_uninstall_lists_the_configured_runs_dir(tmp_path):
    home = tmp_path / "uhome"
    (home / "reports").mkdir(parents=True)
    steps = uninstall._reports(home, {"ops_root": "~/ops", "runs_root": "~/reports"})
    assert any(s.target == str(home / "reports") for s in steps)
    (home / "ops" / "runs").mkdir(parents=True)
    steps = uninstall._reports(home, {"ops_root": "~/ops"})
    assert any(s.target == str(home / "ops" / "runs") for s in steps)


def test_a_forced_config_rewrite_keeps_runs_root(tmp_path):
    config.set_value("runs_root", str(tmp_path / "reports"))
    config.write(ops_root=str(tmp_path / "ops"), force=True)
    assert config.runs_root() == tmp_path / "reports"

"""The apps show the release version, so TestFlight and the Mac never look older than the CLI."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _package_version():
    return re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)


def test_every_app_target_carries_the_package_version():
    want = _package_version()
    for name in ("apps/ios/project.yml", "apps/mac/project.yml"):
        found = re.findall(r'^ +CFBundleShortVersionString: "([^"]+)"', (ROOT / name).read_text(), re.M)
        assert found, name
        assert set(found) == {want}, f"{name}: {found}, package is {want}; scripts/release.sh sets both"


def test_release_script_bumps_the_apps():
    script = (ROOT / "scripts/release.sh").read_text()
    assert "CFBundleShortVersionString" in script
    assert "apps/ios/project.yml apps/mac/project.yml" in script

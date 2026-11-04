"""The Swift marker (packages/review-ios/Sources/TeylaReview/Core/ReviewMarker.swift) is in a release binary
that calls the package's entry point when the overlay is compiled in, and absent when it is not.
`teyla review store-check` relies on both directions. Real `swift build -c release`, so it skips without swift
and off the Mac. The build folder lives in the repo's `build/` (gitignored) and is deleted afterwards."""
from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from teyla import review_gate

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "packages" / "review-ios"
BUILD = ROOT / "build" / "review-marker"

MANIFEST = """// swift-tools-version:5.9
import PackageDescription
let package = Package(
    name: "MarkerProbe",
    platforms: [.macOS(.v14)],
    dependencies: [.package(path: "%s")],
    targets: [.executableTarget(name: "probe", dependencies: [.product(name: "TeylaReview", package: "review-ios")])]
)
"""
# What a product does: call the entry point. Dead stripping keeps the marker only because this call reaches it.
MAIN = """import TeylaReview
MainActor.assumeIsolated { TeylaReview.present() }
"""


def _swift_works() -> bool:
    if sys.platform != "darwin" or not shutil.which("swift"):
        return False
    try:
        return subprocess.run(["swift", "--version"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


pytestmark = pytest.mark.skipif(not _swift_works(), reason="swift is not available on this machine")


def build_probe(tmp_path: pathlib.Path, name: str, review: bool) -> pathlib.Path:
    """Build the probe executable in release mode and return its path."""
    pkg = tmp_path / name
    (pkg / "Sources" / "probe").mkdir(parents=True)
    (pkg / "Package.swift").write_text(MANIFEST % PACKAGE)
    (pkg / "Sources" / "probe" / "main.swift").write_text(MAIN)
    scratch = BUILD / name
    env = {**os.environ, "TEYLA_REVIEW": "1" if review else "0"}
    # Machine rule (POLICY section 13): wait for a build slot before any build.
    wait = subprocess.run([sys.executable, "-m", "teyla", "load", "--wait", "--kind", "build"],
                          env={**env, "PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True)
    if wait.returncode != 0:
        pytest.skip("the machine guard did not admit a build: " + wait.stderr.strip()[-200:])
    done = subprocess.run(["swift", "build", "-c", "release", "--package-path", str(pkg), "--scratch-path", str(scratch)],
                          env=env, capture_output=True, text=True)
    assert done.returncode == 0, "\n".join(done.stdout.splitlines()[-15:] + done.stderr.splitlines()[-15:])
    exe = scratch / "release" / "probe"
    assert exe.is_file()
    return exe


@pytest.fixture(scope="module", autouse=True)
def _clean_build_dir():
    yield
    shutil.rmtree(BUILD, ignore_errors=True)


def test_the_marker_survives_a_release_build_when_the_overlay_is_compiled_in(tmp_path):
    exe = build_probe(tmp_path, "with-review", review=True)
    assert review_gate.file_contains(exe, review_gate.MARKER_SWIFT)


def test_the_marker_is_absent_when_the_package_is_built_without_the_overlay(tmp_path):
    exe = build_probe(tmp_path, "without-review", review=False)
    assert not review_gate.file_contains(exe, review_gate.MARKER_SWIFT)

"""packages/review-android: the fixture app built in its three variants, and `teyla review store-check` on each.

`debug` and `internal` link the real module, `release` the no-op; all three have one application id. The build
is heavy (it needs a JDK, the Android SDK, the Gradle cache and about 2 GB of disk), so it runs only when
TEYLA_REVIEW_ANDROID_BUILD=1 and skips otherwise. `teyla load --wait --kind build` goes first, as everywhere."""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest

from teyla import review_gate as gate

PKG = pathlib.Path(__file__).resolve().parents[1] / "packages" / "review-android"
HOME = pathlib.Path.home()


def _jdk() -> str | None:
    for c in (os.environ.get("JAVA_HOME"), *sorted(str(p) for p in (HOME / ".local").glob("jdk-*/Contents/Home"))):
        if c and (pathlib.Path(c) / "bin" / "javac").exists():
            return c
    return None


def _sdk() -> str | None:
    for c in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"), str(HOME / "Library/Android/sdk"), str(HOME / "Android/Sdk")):
        if c and (pathlib.Path(c) / "platforms").is_dir():
            return c
    return None


pytestmark = pytest.mark.skipif(
    os.environ.get("TEYLA_REVIEW_ANDROID_BUILD") != "1" or not _jdk() or not _sdk(),
    reason="set TEYLA_REVIEW_ANDROID_BUILD=1 with a JDK and the Android SDK to build the fixture app",
)


@pytest.fixture(scope="module")
def apks():
    env = {**os.environ, "JAVA_HOME": _jdk() or "", "ANDROID_HOME": _sdk() or ""}
    if shutil.which("teyla"):
        subprocess.run(["teyla", "load", "--wait", "--kind", "build"], check=True, timeout=1800)
    done = subprocess.run(
        ["./gradlew", "--console=plain", ":fixture:assembleInternal", ":fixture:assembleRelease"],
        cwd=PKG, env=env, capture_output=True, text=True, timeout=1800,
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    subprocess.run(["./gradlew", "--stop"], cwd=PKG, env=env, capture_output=True)
    out = PKG / "fixture" / "build" / "outputs" / "apk"
    return {"internal": out / "internal" / "fixture-internal.apk", "release": out / "release" / "fixture-release.apk", "meta": out}


def test_the_release_build_passes_the_store_check(apks):
    kind, checks = gate.run(apks["release"])
    assert checks and all(c.ok for c in checks), [c for c in checks if not c.ok]


def test_the_internal_build_holds_the_marker_even_after_r8(apks):
    kind, checks = gate.run(apks["internal"])
    assert checks and not all(c.ok for c in checks)
    assert any("overlay class found" in c.detail for c in checks)


def test_all_variants_share_one_application_id(apks):
    ids = set()
    for variant in ("internal", "release"):
        meta = json.loads((apks["meta"] / variant / "output-metadata.json").read_text())
        ids.add(meta["applicationId"])
    assert ids == {"teyla.review.fixture"}


def test_the_release_apk_holds_no_review_activity_and_no_key():
    release = PKG / "fixture" / "build" / "outputs" / "apk" / "release" / "fixture-release.apk"
    import zipfile

    with zipfile.ZipFile(release) as z:
        blob = b"".join(z.read(n) for n in z.namelist() if n.endswith(".dex"))
        manifest = z.read("AndroidManifest.xml")
    assert b"ReviewActivity" not in blob and b"ReviewActivity" not in manifest
    assert b"fixture-write-only-key" not in blob, "the key is in the fixture's Application class only in a variant that links the real module"

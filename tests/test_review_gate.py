"""`teyla review store-check` (docs/REVIEW.md, "The switch"): a production artifact must hold no review entry point.
The fixtures are small hand-made bundles; the real Swift build that proves the marker is in
test_review_marker.py."""
from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
import sys
import zipfile

import pytest

from teyla import cli, review_gate as gate

SWIFT = gate.MARKER_SWIFT
SECRET = "pairing-secret-value-123"


def info(**extra) -> bytes:
    return plistlib.dumps({"CFBundleExecutable": "App", "CFBundleIdentifier": "com.example.app", **extra})


def make_app(root, name="App.app", plist=None, exe=b"\x00plain binary\x00", framework=None, mac=False):
    app = root / name
    base = app / "Contents" if mac else app
    (base / ("MacOS" if mac else ".")).mkdir(parents=True, exist_ok=True)
    (base / "Info.plist").write_bytes(plist if plist is not None else info())
    (base / ("MacOS/App" if mac else "App")).write_bytes(exe)
    if framework is not None:
        fw = base / "Frameworks" / "Pkg.framework"
        fw.mkdir(parents=True)
        (fw / "Pkg").write_bytes(framework)
    return app


def make_archive(root, **kw):
    arch = root / "Thing.xcarchive"
    (arch / "Products" / "Applications").mkdir(parents=True)
    make_app(arch / "Products" / "Applications", **kw)
    return arch


def make_ipa(path, plist=None, exe=b"plain", framework=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Payload/App.app/Info.plist", plist if plist is not None else info())
        z.writestr("Payload/App.app/App", exe)
        if framework is not None:
            z.writestr("Payload/App.app/Frameworks/Pkg.framework/Pkg", framework)
    return path


def make_android(path, dex=b"dex\n035 Lcom/example/Main;", member="classes.dex"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(member, dex)
        z.writestr("res/raw/notes.txt", gate.MARKER_ANDROID)     # outside dex: not a finding
    return path


def run(path, *flags, capsys):
    code = cli.main(["review", "store-check", str(path), *flags])
    out = capsys.readouterr()
    return code, out.out, out.err


# ---- parse_enabled is the package's rule ------------------------------------------------------------

@pytest.mark.parametrize("value, on", [
    ("YES", True), (" true ", True), ("1", True), (True, True), (1, True), (1.0, True),
    (None, False), ("", False), ("$(TEYLA_REVIEW_ENABLED)", False), ("NO", False), (False, False),
    (0, False), (2, False), ("2", False), ([], False),
])
def test_parse_enabled_follows_the_swift_rule(value, on):
    assert gate.parse_enabled(value) is on


# ---- .app, .xcarchive, .ipa -------------------------------------------------------------------------

def test_a_clean_app_passes(tmp_path, capsys):
    code, out, _ = run(make_app(tmp_path), capsys=capsys)
    assert code == 0 and "FAIL" not in out and "clean" in out


def test_a_clean_mac_app_passes(tmp_path, capsys):
    code, _, _ = run(make_app(tmp_path, mac=True), capsys=capsys)
    assert code == 0


@pytest.mark.parametrize("on", ["YES", "true", "1", True])
def test_an_enabled_key_fails(tmp_path, capsys, on):
    code, out, _ = run(make_app(tmp_path, plist=info(TeylaReviewEnabled=on)), capsys=capsys)
    assert code == 1 and "FAIL TeylaReviewEnabled" in out


def test_an_off_key_and_an_unexpanded_placeholder_pass(tmp_path, capsys):
    for value in ("NO", "", "$(TEYLA_REVIEW_ENABLED)"):
        sub = tmp_path / (value or "empty").replace("$", "").replace("(", "").replace(")", "")
        sub.mkdir()
        code, _, _ = run(make_app(sub, plist=info(TeylaReviewEnabled=value)), capsys=capsys)
        assert code == 0, value


def test_a_channel_key_fails_and_its_value_is_never_printed(tmp_path, capsys):
    code, out, err = run(make_app(tmp_path, plist=info(TeylaReviewChannelKey=SECRET)), "--json", capsys=capsys)
    assert code == 1 and SECRET not in out + err
    assert any(not c["ok"] and "TeylaReviewChannelKey" in c["name"] for c in json.loads(out)["checks"])


def test_a_channel_url_fails_and_its_value_is_never_printed(tmp_path, capsys):
    url = "https://channel.example.test/secret-path"
    code, out, err = run(make_app(tmp_path, plist=info(TeylaReviewChannelURL=url)), "--json", capsys=capsys)
    assert code == 1 and url not in out + err and "secret-path" not in out + err
    assert any(not c["ok"] and "TeylaReviewChannelURL" in c["name"] for c in json.loads(out)["checks"])


def test_a_channel_url_fails_in_an_ipa_and_a_nested_bundle(tmp_path, capsys):
    assert run(make_ipa(tmp_path / "u.ipa", plist=info(TeylaReviewChannelURL="https://channel.example.test")), capsys=capsys)[0] == 1
    app = make_app(tmp_path)
    ext = app / "PlugIns" / "Widget.appex"
    ext.mkdir(parents=True)
    (ext / "Info.plist").write_bytes(info(TeylaReviewChannelKey=SECRET, TeylaReviewChannelURL="https://channel.example.test"))
    code, out, err = run(app, "--json", capsys=capsys)
    assert code == 1 and SECRET not in out + err
    assert sum(1 for c in json.loads(out)["checks"] if not c["ok"] and "Widget.appex" in c["name"]) == 2


def test_an_empty_channel_url_passes(tmp_path, capsys):
    code, _, _ = run(make_app(tmp_path, plist=info(TeylaReviewChannelURL="")), capsys=capsys)
    assert code == 0


def test_an_empty_channel_key_passes(tmp_path, capsys):
    code, _, _ = run(make_app(tmp_path, plist=info(TeylaReviewChannelKey="  ")), capsys=capsys)
    assert code == 0


def test_the_marker_in_the_executable_fails(tmp_path, capsys):
    code, out, _ = run(make_app(tmp_path, exe=b"\x00\x01" + SWIFT + b"\x00"), capsys=capsys)
    assert code == 1 and "marker found in App" in out


def test_the_marker_in_an_embedded_framework_fails(tmp_path, capsys):
    code, out, _ = run(make_app(tmp_path, framework=b"x" * 5000 + SWIFT), capsys=capsys)
    assert code == 1 and "Frameworks/Pkg.framework/Pkg" in out


def test_a_marker_split_across_a_read_block_is_found(tmp_path):
    blob = b"\x00" * (gate._CHUNK - 5) + SWIFT + b"\x00" * 10
    import io
    assert gate._stream_contains(io.BytesIO(blob), SWIFT)
    assert not gate._stream_contains(io.BytesIO(b"\x00" * (gate._CHUNK + 9)), SWIFT)


def test_an_archive_checks_every_app_in_it(tmp_path, capsys):
    arch = make_archive(tmp_path)
    make_app(arch / "Products" / "Applications", name="Other.app", exe=SWIFT)
    # the second bundle's executable is named App too; the marker is in it
    code, out, _ = run(arch, capsys=capsys)
    assert code == 1 and "Other.app: no review marker" in out


def test_a_clean_archive_passes(tmp_path, capsys):
    code, out, _ = run(make_archive(tmp_path), capsys=capsys)
    assert code == 0 and out.count("ok  ") == 4


def test_an_archive_without_an_app_cannot_be_read(tmp_path, capsys):
    arch = tmp_path / "Empty.xcarchive"
    arch.mkdir()
    code, _, err = run(arch, capsys=capsys)
    assert code == 2 and "Products/Applications" in err


def test_ipa_clean_and_each_failure(tmp_path, capsys):
    assert run(make_ipa(tmp_path / "a.ipa"), capsys=capsys)[0] == 0
    assert run(make_ipa(tmp_path / "b.ipa", plist=info(TeylaReviewEnabled="YES")), capsys=capsys)[0] == 1
    assert run(make_ipa(tmp_path / "c.ipa", plist=info(TeylaReviewChannelKey=SECRET)), capsys=capsys)[0] == 1
    assert run(make_ipa(tmp_path / "d.ipa", exe=SWIFT), capsys=capsys)[0] == 1
    code, out, _ = run(make_ipa(tmp_path / "e.ipa", framework=SWIFT), capsys=capsys)
    assert code == 1 and "Frameworks/Pkg.framework/Pkg" in out


def test_a_broken_ipa_cannot_be_read(tmp_path, capsys):
    bad = tmp_path / "bad.ipa"
    bad.write_bytes(b"not a zip")
    assert run(bad, capsys=capsys)[0] == 2


# ---- Android ----------------------------------------------------------------------------------------

def test_android_clean_apk_and_aab_pass(tmp_path, capsys):
    assert run(make_android(tmp_path / "a.apk"), capsys=capsys)[0] == 0
    assert run(make_android(tmp_path / "a.aab", member="base/dex/classes.dex"), capsys=capsys)[0] == 0


def test_android_overlay_class_in_a_dex_fails(tmp_path, capsys):
    dex = b"dex\n035 L" + gate.MARKER_ANDROID + b";"
    for name, member in (("a.apk", "classes2.dex"), ("a.aab", "base/dex/classes.dex")):
        code, out, _ = run(make_android(tmp_path / name, dex=dex, member=member), capsys=capsys)
        assert code == 1 and member in out


def test_an_apk_without_dex_cannot_be_read(tmp_path, capsys):
    p = tmp_path / "x.apk"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("AndroidManifest.xml", "x")
    assert run(p, capsys=capsys)[0] == 2


# ---- a web dist -------------------------------------------------------------------------------------

def test_web_dist(tmp_path, capsys):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    assert run(dist, capsys=capsys)[0] == 0
    (dist / "assets" / "app.js").write_bytes(b"x=1;" + gate.MARKER_WEB)
    code, out, _ = run(dist, capsys=capsys)
    assert code == 1 and "assets/app.js" in out


def test_an_empty_folder_cannot_be_read(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert run(tmp_path / "empty", capsys=capsys)[0] == 2


# ---- exit 2 and output ------------------------------------------------------------------------------

def test_missing_path_and_unknown_type_exit_2(tmp_path, capsys):
    assert run(tmp_path / "nope.ipa", capsys=capsys)[0] == 2
    other = tmp_path / "thing.zip"
    other.write_bytes(b"x")
    code, _, err = run(other, capsys=capsys)
    assert code == 2 and "unknown artifact type" in err


def test_store_check_wants_exactly_one_path(capsys):
    assert cli.main(["review", "store-check"]) == 2
    assert cli.main(["review", "store-check", "a", "b"]) == 2


def test_json_output_has_the_shape(tmp_path, capsys):
    code, out, _ = run(make_ipa(tmp_path / "a.ipa"), "--json", capsys=capsys)
    doc = json.loads(out)
    assert code == 0 and doc["ok"] is True and doc["type"] == "ipa" and len(doc["checks"]) == 4


def test_a_nested_bundle_with_review_on_fails(tmp_path, capsys):
    app = make_app(tmp_path)
    clip = app / "AppClips" / "Clip.app"
    clip.mkdir(parents=True)
    (clip / "Info.plist").write_bytes(info(TeylaReviewEnabled="YES"))
    assert run(app, capsys=capsys)[0] == 1


def test_the_marker_in_an_extension_fails(tmp_path, capsys):
    app = make_app(tmp_path)
    ext = app / "PlugIns" / "Share.appex"
    ext.mkdir(parents=True)
    (ext / "Share").write_bytes(b"x" + SWIFT + b"x")
    assert run(app, capsys=capsys)[0] == 1


def test_a_nested_bundle_in_an_ipa_fails(tmp_path, capsys):
    path = make_ipa(tmp_path / "App.ipa")
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("Payload/App.app/PlugIns/Share.appex/Info.plist", info(TeylaReviewEnabled="YES"))
    assert run(path, capsys=capsys)[0] == 1


def test_the_marker_in_an_ipa_extension_fails(tmp_path, capsys):
    path = make_ipa(tmp_path / "App.ipa")
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("Payload/App.app/PlugIns/Share.appex/Share", b"x" + SWIFT + b"x")
    assert run(path, capsys=capsys)[0] == 1


def test_an_unreadable_folder_in_a_dist_cannot_pass(tmp_path, capsys):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>")
    (dist / "assets").chmod(0)
    try:
        assert run(dist, capsys=capsys)[0] == 2
    finally:
        (dist / "assets").chmod(0o755)


# ---- Mac bundles: Contents/Info.plist, Contents/MacOS, and a .pkg export ----------------------------------

def test_a_mac_app_is_read_through_contents(tmp_path, capsys):
    app = make_app(tmp_path, mac=True, plist=info(TeylaReviewEnabled="NO"))
    assert (app / "Contents" / "Info.plist").is_file() and not (app / "Info.plist").exists()
    code, out, _ = run(app, capsys=capsys)
    assert code == 0 and "FAIL" not in out and "TeylaReviewEnabled is off" in out


def test_the_plist_of_a_mac_app_is_the_one_in_contents(tmp_path, capsys):
    code, out, _ = run(make_app(tmp_path, mac=True, plist=info(TeylaReviewEnabled="YES")), capsys=capsys)
    assert code == 1 and "FAIL TeylaReviewEnabled" in out


def test_the_marker_in_a_mac_executable_fails(tmp_path, capsys):
    code, out, _ = run(make_app(tmp_path, mac=True, exe=b"\x00" + gate.MARKER_SWIFT + b"\x00"), capsys=capsys)
    assert code == 1 and "Contents/MacOS/App" in out


def test_the_marker_in_a_mac_framework_fails(tmp_path, capsys):
    code, out, _ = run(make_app(tmp_path, mac=True, framework=b"x" + gate.MARKER_SWIFT), capsys=capsys)
    assert code == 1 and "Contents/Frameworks/Pkg.framework/Pkg" in out


def test_a_channel_key_in_a_mac_plist_fails_and_is_not_printed(tmp_path, capsys):
    code, out, err = run(make_app(tmp_path, mac=True, plist=info(TeylaReviewChannelKey=SECRET)), capsys=capsys)
    assert code == 1 and "FAIL TeylaReviewChannelKey" in out and SECRET not in out + err


def test_a_nested_mac_helper_with_review_on_fails(tmp_path, capsys):
    app = make_app(tmp_path, mac=True)
    helper = app / "Contents" / "Library" / "LoginItems" / "Helper.app" / "Contents"
    helper.mkdir(parents=True)
    (helper / "Info.plist").write_bytes(info(TeylaReviewEnabled="1"))
    code, out, _ = run(app, capsys=capsys)
    assert code == 1 and "Helper.app/Contents/Info.plist" in out


def test_a_clean_mac_archive_passes_and_a_marked_one_fails(tmp_path, capsys):
    clean = tmp_path / "clean"
    clean.mkdir()
    code, out, _ = run(make_archive(clean, mac=True), capsys=capsys)
    assert code == 0 and "FAIL" not in out
    marked = tmp_path / "marked"
    marked.mkdir()
    code, out, _ = run(make_archive(marked, mac=True, exe=gate.MARKER_SWIFT), capsys=capsys)
    assert code == 1 and "Contents/MacOS/App" in out


def test_a_mac_app_without_a_readable_plist_cannot_be_read(tmp_path, capsys):
    app = tmp_path / "Broken.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    code, _, err = run(app, capsys=capsys)
    assert code == 2 and "cannot read" in err


needs_pkgbuild = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("pkgbuild") or not shutil.which("pkgutil"),
                                    reason="pkgbuild and pkgutil exist only on macOS")


def make_pkg(root, name="App.app", **kw):
    """A real flat installer of one Mac app, the way an App Store export holds it."""
    payload = root / "payload"
    payload.mkdir()
    make_app(payload, name=name, mac=True, **kw)
    pkg = root / "App.pkg"
    subprocess.run(["pkgbuild", "--root", str(payload), "--install-location", "/Applications", "--identifier", "com.example.app", str(pkg)],
                   check=True, capture_output=True)
    return pkg


@needs_pkgbuild
def test_a_clean_pkg_passes(tmp_path, capsys):
    code, out, _ = run(make_pkg(tmp_path), capsys=capsys)
    assert code == 0 and "FAIL" not in out and out.startswith("ok") and "pkg App.pkg" in out


@needs_pkgbuild
def test_a_pkg_whose_app_holds_the_marker_fails(tmp_path, capsys):
    code, out, _ = run(make_pkg(tmp_path, exe=gate.MARKER_SWIFT), capsys=capsys)
    assert code == 1 and "Contents/MacOS/App" in out


@needs_pkgbuild
def test_a_pkg_whose_app_has_review_on_fails(tmp_path, capsys):
    code, out, _ = run(make_pkg(tmp_path, plist=info(TeylaReviewEnabled="YES")), capsys=capsys)
    assert code == 1 and "FAIL" in out and "TeylaReviewEnabled" in out


@needs_pkgbuild
def test_a_pkg_without_an_app_cannot_be_read(tmp_path, capsys):
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "readme.txt").write_text("no app here")
    pkg = tmp_path / "Empty.pkg"
    subprocess.run(["pkgbuild", "--root", str(payload), "--identifier", "com.example.empty", str(pkg)], check=True, capture_output=True)
    code, _, err = run(pkg, capsys=capsys)
    assert code == 2 and "holds no .app" in err


def test_a_file_that_is_not_a_pkg_cannot_be_read(tmp_path, capsys):
    bad = tmp_path / "Fake.pkg"
    bad.write_bytes(b"not an installer")
    code, _, err = run(bad, capsys=capsys)
    assert code == 2 and "cannot read" in err


def test_a_pkg_without_pkgutil_cannot_pass(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _name: None)
    bad = tmp_path / "App.pkg"
    bad.write_bytes(b"x")
    code, _, err = run(bad, capsys=capsys)
    assert code == 2 and "pkgutil" in err

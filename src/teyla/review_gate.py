"""`teyla review store-check PATH`: prove that a production artifact holds no review entry point.

A store build is a separate archive of the same commit, built with the review switches off (docs/REVIEW.md,
"The switch"). This module reads the finished artifact and says whether anything of the review overlay is in it.
It reads files and prints one line per check. It never prints a key's value and makes no network call.

    .xcarchive, .app, .ipa   Info.plist: TeylaReviewEnabled absent or falsy (the package's own `parseEnabled`),
                             TeylaReviewChannelKey and TeylaReviewChannelURL absent or empty; the main executable and the embedded
                             frameworks do not contain the Swift marker
    .aab, .apk               no dex file contains the bytes of the overlay class name
    a directory              no file contains the web marker

Exit 0: clean. Exit 1: something found. Exit 2: the path cannot be read, or its type is unknown.
"""
from __future__ import annotations

import json
import mmap
import os
import pathlib
import plistlib
import sys
import zipfile
from dataclasses import dataclass

# Present in the binary only when the Swift package was compiled with TEYLA_REVIEW (ReviewMarker.swift).
MARKER_SWIFT = b"TEYLA_REVIEW_IOS_ACTIVE"
# Written into a web bundle by the web overlay build, and only by it.
MARKER_WEB = b"TEYLA_REVIEW_WEB_ACTIVE"
# Android: the internal name of the overlay class, as a dex string table holds it.
MARKER_ANDROID = b"teyla/review/ReviewOverlay"

KEY_ENABLED = "TeylaReviewEnabled"
KEY_CHANNEL = "TeylaReviewChannelKey"
KEY_CHANNEL_URL = "TeylaReviewChannelURL"

_CHUNK = 1 << 20


class GateError(Exception):
    """The path cannot be read, or its type is unknown: exit 2."""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def parse_enabled(value) -> bool:
    """The Swift package's `TeylaReview.parseEnabled`: a bool, "yes" / "true" / "1" in any case with
    surrounding blanks trimmed, or the number 1. Everything else, including an unexpanded
    `$(TEYLA_REVIEW_ENABLED)`, is off."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("yes", "true", "1")
    if isinstance(value, (int, float)):
        return int(value) == 1
    return False


def _stream_contains(stream, marker: bytes) -> bool:
    keep = len(marker) - 1
    tail = b""
    while True:
        block = stream.read(_CHUNK)
        if not block:
            return False
        window = tail + block
        if marker in window:
            return True
        tail = window[-keep:] if keep else b""


def file_contains(path: pathlib.Path, marker: bytes) -> bool:
    try:
        if path.stat().st_size == 0:
            return False
        with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            return mm.find(marker) != -1
    except (OSError, ValueError) as e:
        raise GateError(f"cannot read {path}: {e}") from e


def _has_value(value) -> bool:
    return value is not None and not (isinstance(value, (str, bytes)) and not value.strip())


def _plist_checks(info: dict) -> list[Check]:
    enabled = info.get(KEY_ENABLED)
    # Names only: the value of a key is never printed.
    out = [Check(f"{KEY_ENABLED} is off", not parse_enabled(enabled),
                 "" if not parse_enabled(enabled) else f"{KEY_ENABLED} turns review mode on")]
    for name in (KEY_CHANNEL, KEY_CHANNEL_URL):
        held = _has_value(info.get(name))
        out.append(Check(f"{name} is absent or empty", not held,
                         "" if not held else f"{name} holds a value (not shown)"))
    return out


def _read_plist(data: bytes, where: str) -> dict:
    try:
        info = plistlib.loads(data)
    except Exception as e:  # plistlib raises several types for a bad file
        raise GateError(f"cannot read {where}: {e}") from e
    if not isinstance(info, dict):
        raise GateError(f"{where} is not a dictionary")
    return info


# ---- .app, .xcarchive -------------------------------------------------------------------------------

def _app_layout(app: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """(Info.plist, the folder of the executable, the frameworks folder): iOS bundles are flat, Mac bundles
    keep everything under Contents."""
    if (app / "Contents" / "Info.plist").is_file():
        c = app / "Contents"
        return c / "Info.plist", c / "MacOS", c / "Frameworks"
    return app / "Info.plist", app, app / "Frameworks"


def _files(top: pathlib.Path):
    """Every regular file under `top`. A folder it cannot read stops the check: it must not pass unread."""
    def stop(e: OSError):
        raise GateError(f"cannot read {e.filename}: {e.strerror}") from e
    for root, _dirs, files in os.walk(top, onerror=stop):      # os.walk does not follow symlinked folders
        for f in sorted(files):
            p = pathlib.Path(root) / f
            if not p.is_symlink() and p.is_file():
                yield p


def check_app(app: pathlib.Path) -> list[Check]:
    """The whole bundle, not only its main executable: an App Clip, an extension or a helper is a way in too."""
    plist, exec_dir, _frameworks = _app_layout(app)
    try:
        info = _read_plist(plist.read_bytes(), f"{app.name}/Info.plist")
    except OSError as e:
        raise GateError(f"cannot read {plist}: {e}") from e
    checks = _plist_checks(info)
    name = info.get("CFBundleExecutable")
    if not isinstance(name, str) or not name:
        raise GateError(f"{app.name}/Info.plist has no CFBundleExecutable")
    exe = exec_dir / name
    if not exe.is_file():
        raise GateError(f"cannot read {exe}: not a file")
    hits: list[str] = []
    for p in _files(app):
        where = str(p.relative_to(app))
        if p.name == "Info.plist" and p != plist:
            try:
                nested = _read_plist(p.read_bytes(), f"{app.name}/{where}")
            except OSError as e:
                raise GateError(f"cannot read {p}: {e}") from e
            checks += [Check(f"{where}: {c.name}", c.ok, c.detail) for c in _plist_checks(nested)]
        if file_contains(p, MARKER_SWIFT):
            hits.append(where)
    checks.append(Check("no review marker anywhere in the bundle", not hits,
                        "" if not hits else "marker found in " + ", ".join(hits)))
    return checks


def check_xcarchive(path: pathlib.Path) -> list[Check]:
    apps = sorted((path / "Products" / "Applications").glob("*.app")) if (path / "Products").is_dir() else []
    if not apps:
        raise GateError(f"{path.name} holds no Products/Applications/*.app")
    return _per_app(apps, lambda a: a.name, check_app)


def _per_app(apps, label, check) -> list[Check]:
    out: list[Check] = []
    for a in apps:
        for c in check(a):
            out.append(Check(f"{label(a)}: {c.name}", c.ok, c.detail))
    return out


# ---- zip files: .ipa, .aab, .apk --------------------------------------------------------------------

def _open_zip(path: pathlib.Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as e:
        raise GateError(f"cannot read {path}: {e}") from e


def _zip_member_contains(z: zipfile.ZipFile, name: str, marker: bytes) -> bool:
    try:
        with z.open(name) as f:
            return _stream_contains(f, marker)
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError) as e:
        raise GateError(f"cannot read {name} in {z.filename}: {e}") from e


def check_ipa(path: pathlib.Path) -> list[Check]:
    with _open_zip(path) as z:
        names = z.namelist()
        apps = sorted({n.split("/")[1] for n in names if n.startswith("Payload/") and n.split("/")[1].endswith(".app")
                       and len(n.split("/")) > 2})
        if not apps:
            raise GateError(f"{path.name} holds no Payload/*.app")
        out: list[Check] = []
        for app in apps:
            prefix = f"Payload/{app}/"
            if prefix + "Info.plist" not in names:
                raise GateError(f"{path.name} has no {prefix}Info.plist")
            try:
                info = _read_plist(z.read(prefix + "Info.plist"), f"{app}/Info.plist")
            except (OSError, zipfile.BadZipFile, RuntimeError) as e:
                raise GateError(f"cannot read {prefix}Info.plist: {e}") from e
            checks = _plist_checks(info)
            exe = info.get("CFBundleExecutable")
            if not isinstance(exe, str) or not exe or prefix + exe not in names:
                raise GateError(f"{app} has no readable main executable")
            # The whole bundle, as in check_app.
            scan = [n for n in names if n.startswith(prefix) and not n.endswith("/")]
            for n in scan:
                if n.endswith("/Info.plist") and n != prefix + "Info.plist":
                    try:
                        nested = _read_plist(z.read(n), n)
                    except (OSError, zipfile.BadZipFile, RuntimeError) as e:
                        raise GateError(f"cannot read {n}: {e}") from e
                    checks += [Check(f"{n[len(prefix):]}: {c.name}", c.ok, c.detail) for c in _plist_checks(nested)]
            hits = [n[len(prefix):] for n in scan if _zip_member_contains(z, n, MARKER_SWIFT)]
            checks.append(Check("no review marker anywhere in the bundle", not hits,
                                "" if not hits else "marker found in " + ", ".join(hits)))
            out += [Check(f"{app}: {c.name}", c.ok, c.detail) for c in checks]
        return out


def check_android(path: pathlib.Path) -> list[Check]:
    with _open_zip(path) as z:
        dex = [n for n in z.namelist() if n.endswith(".dex")]
        if not dex:
            raise GateError(f"{path.name} holds no dex file")
        hits = [n for n in dex if _zip_member_contains(z, n, MARKER_ANDROID)]
    return [Check("no review overlay class in any dex file", not hits,
                  "" if not hits else "overlay class found in " + ", ".join(hits))]


# ---- a directory (web dist) -------------------------------------------------------------------------

def check_dir(path: pathlib.Path) -> list[Check]:
    hits: list[str] = []
    count = 0
    for p in _files(path):
        count += 1
        if file_contains(p, MARKER_WEB):
            hits.append(str(p.relative_to(path)))
    if count == 0:
        raise GateError(f"{path} holds no files")
    return [Check("no web review marker in any file", not hits,
                  "" if not hits else "marker found in " + ", ".join(hits))]


# ---- entry points -----------------------------------------------------------------------------------

def run(path: pathlib.Path) -> tuple[str, list[Check]]:
    """(the artifact type, its checks). Raises GateError."""
    if not path.exists():
        raise GateError(f"cannot read {path}: no such file or folder")
    suffix = path.suffix.lower()
    if suffix == ".xcarchive" and path.is_dir():
        return "xcarchive", check_xcarchive(path)
    if suffix == ".app" and path.is_dir():
        return "app", check_app(path)
    if suffix == ".ipa" and path.is_file():
        return "ipa", check_ipa(path)
    if suffix in (".aab", ".apk") and path.is_file():
        return suffix[1:], check_android(path)
    if path.is_dir() and suffix not in (".xcarchive", ".app"):
        return "directory", check_dir(path)
    raise GateError(f"unknown artifact type: {path.name} (expected .xcarchive, .app, .ipa, .aab, .apk or a folder)")


def cmd_store_check(words: list[str], as_json: bool = False) -> int:
    if len(words) != 1:
        print("teyla review store-check: give one path (.xcarchive, .app, .ipa, .aab, .apk or a folder)", file=sys.stderr)
        return 2
    path = pathlib.Path(words[0]).expanduser()
    try:
        kind, checks = run(path)
    except GateError as e:
        print(f"teyla review store-check: {e}", file=sys.stderr)
        return 2
    ok = all(c.ok for c in checks)
    if as_json:
        print(json.dumps({"path": str(path), "type": kind, "ok": ok,
                          "checks": [{"name": c.name, "ok": c.ok, **({"detail": c.detail} if c.detail else {})}
                                     for c in checks]}, indent=1, ensure_ascii=False))
    else:
        for c in checks:
            print(f"{'ok  ' if c.ok else 'FAIL'} {c.name}" + (f": {c.detail}" if c.detail else ""))
        print(f"{kind} {path.name}: " + ("clean, no review entry point" if ok else "NOT CLEAN, do not upload"))
    return 0 if ok else 1

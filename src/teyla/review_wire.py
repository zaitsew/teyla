"""The phone's capture format and the Mac's answers, as docs/REVIEW.md in the capture lane defines them.

    capture.json   version 1, snake_case; `normalize()` reduces it to the flat shape the queue stores
    capture.sig    lowercase hex HMAC-SHA256 of `capture_message()`, key = the relay key (relay.read_key)
    review-status/<id>.json   written here: `write_status()` for "received", later "pr_ready", "verified_on_device"

The signature covers the SHA-256 of the bytes of `capture.json` and of the picture, so the JSON form does not
matter: the bytes that arrived are hashed. The same key and the same HMAC-SHA256 sign the relay's outbox actions
(`relay.sign`). Pure functions and one file write; no network.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import json
import os
import pathlib
import re
import stat

from . import relay

CAPTURE_TAG = "teyla-review-v1"
STATUS_TAG = "teyla-review-status-v1"
CHAIN = ("saved_on_phone", "received", "pr_ready", "verified_on_device")
WRITTEN_BY_MAC = CHAIN[1:]
FUTURE_SLACK_S = 10 * 60
PICTURE = "capture.png"
STATUS_DIR = "review-status"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_contract(obj) -> bool:
    """A capture in the phone's format carries `v`. The older flat shape does not."""
    return isinstance(obj, dict) and "v" in obj


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize(obj: dict) -> tuple[dict | None, str]:
    """(the flat capture `review.validate` reads, "") or (None, why not). Refuses a `v` other than 1."""
    if obj.get("v") != 1 or isinstance(obj.get("v"), bool):
        return None, "capture.json has a version this tool does not read (v must be 1)"
    app = obj.get("app") if isinstance(obj.get("app"), dict) else {}
    env = obj.get("environment") if isinstance(obj.get("environment"), dict) else {}
    bundle = app.get("bundle_id")
    if not isinstance(bundle, str) or not bundle:
        return None, "app.bundle_id is missing"
    comment = obj.get("comment")
    if not isinstance(comment, dict) or not isinstance(comment.get("text"), str):
        return None, "comment.text is missing"
    el = obj.get("element") if isinstance(obj.get("element"), dict) else None
    flat_el = None
    if el:
        b = el.get("bounds") if isinstance(el.get("bounds"), dict) else {}
        src = el.get("source") if isinstance(el.get("source"), dict) else {}
        flat_el = {"id": el.get("id"), "parent": el.get("parent"), "role": el.get("role"),
                   "bounds": {k: b[k] for k in ("x", "y", "width", "height") if _num(b.get(k)) is not None},
                   "string_keys": el.get("strings") if isinstance(el.get("strings"), list) else [],
                   "source_file": src.get("file"), "source_line": src.get("line")}
    tap = obj.get("tap") if isinstance(obj.get("tap"), dict) else None
    screen = obj.get("screen")
    if not screen and el:
        screen = el.get("screen")
    flat = {"id": obj.get("id"), "product": bundle.rsplit(".", 1)[-1], "screen": screen or "",
            "element": flat_el, "tap": {"x": tap.get("x"), "y": tap.get("y")} if tap else None,
            "comment": comment["text"], "created_at": obj.get("created"), "build": app.get("build", ""),
            "commit": app.get("commit", ""), "locale": env.get("locale", ""),
            "dynamic_type": env.get("dynamic_type", ""), "appearance": env.get("appearance", ""),
            "device": obj.get("device", "")}
    return flat, ""


def capture_message(cid: str, created: str, json_sha: str, png_sha: str) -> bytes:
    return "\n".join((CAPTURE_TAG, cid, created, json_sha, png_sha)).encode("utf-8")


def status_message(cid: str, status: str, updated: str, pr: str = "") -> bytes:
    return "\n".join((STATUS_TAG, cid, status, updated, pr or "")).encode("utf-8")


def capture_sig(key: bytes, cid: str, created: str, json_bytes: bytes, png_bytes: bytes) -> str:
    return relay.sign(key, capture_message(cid, created, sha256_hex(json_bytes), sha256_hex(png_bytes)))


def status_sig(key: bytes, cid: str, status: str, updated: str, pr: str = "") -> str:
    return relay.sign(key, status_message(cid, status, updated, pr))


def _iso(epoch: float) -> str:
    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(stamp) -> float | None:
    try:
        return _dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def verify_capture(key: bytes, raw: dict, json_bytes: bytes, png_bytes: bytes, sig_text: str, now: float) -> str:
    """"" when the capture is the one the phone signed, else the reason."""
    cid, created = raw.get("id"), raw.get("created")
    if not isinstance(cid, str) or not isinstance(created, str):
        return "id or created is missing"
    sig = sig_text.strip()
    if not _HEX64.match(sig):
        return "capture.sig is not 64 hex characters"
    if not hmac.compare_digest(capture_sig(key, cid, created, json_bytes, png_bytes).encode("ascii"), sig.encode("ascii")):
        return "the signature does not match (wrong key, or the files changed)"
    when = _epoch(created)
    if when is None:
        return "created is not YYYY-MM-DDTHH:MM:SSZ"
    if when > now + FUTURE_SLACK_S:
        return "created is more than 10 minutes in the future"
    return ""


def status_path(root: pathlib.Path, cid: str) -> pathlib.Path:
    return root / STATUS_DIR / f"{cid}.json"


def current_status(root: pathlib.Path, cid: str) -> str | None:
    """The status in `review-status/<id>.json`, or None when there is no readable file."""
    try:
        data = json.loads(status_path(root, cid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    s = data.get("status") if isinstance(data, dict) else None
    return s if s in CHAIN else None


def _status_dir(root: pathlib.Path) -> pathlib.Path:
    d = root / STATUS_DIR
    try:
        os.mkdir(d, 0o700)
    except FileExistsError:
        pass
    st = os.lstat(d)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise OSError(f"{d} is not a plain directory of this user")
    return d


def write_status(root: pathlib.Path, key: bytes, cid: str, status: str, now: float, pr: str = "") -> bool:
    """Write `review-status/<id>.json`, signed. The chain only moves forward: a file already at this state or
    beyond is left alone (False). Raises OSError when the folder cannot be written."""
    if status not in WRITTEN_BY_MAC:
        raise ValueError(f"status must be one of {', '.join(WRITTEN_BY_MAC)}")
    have = current_status(root, cid)
    if have is not None and CHAIN.index(have) >= CHAIN.index(status):
        return False
    updated = _iso(now)
    body = {"v": 1, "id": cid, "status": status, "updated": updated, "sig": status_sig(key, cid, status, updated, pr)}
    if pr:
        body["pr"] = pr
    _status_dir(root)
    relay._write_json(status_path(root, cid), body)
    return True

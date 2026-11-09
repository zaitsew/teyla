"""Taste drops from the iPhone's Share extension: the phone's folder format and the Mac's import (docs/TASTE.md, "From the phone").

The extension saves a like or a dislike, a link or a picture, and an optional dictated sentence. The Teyla app
signs it and writes one folder into the relay's outbox, the same iCloud folder and the same key as every other
phone-to-Mac entry (`relay.py`):

    <relay folder>/outbox/taste/<uuid>/
        taste.json   {"v":1,"id","created","device","verdict","url","image","sentence"}
        taste.sig    lowercase hex HMAC-SHA256 of `drop_message()`, key = the relay key
        image.jpg    optional, at most 5 MB; `url` and `image` are never both set, and one of them always is

`relay.sync` calls `pull()` once per pass. A drop that checks out becomes a corpus entry exactly as `teyla taste add`
would make it, minus the capture: a pass never opens a page. The sentence is stored as written; with a sentence the
entry is `proposed` (ready for `teyla taste accept`), without one it is `raw`. The folder is anyone-can-write iCloud,
so everything in it is data until the signature holds: sizes are capped before reading, names are fixed, nothing is
followed through a link, and an id is imported at most once (the relay journal, as for entries).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
import pathlib

from . import relay, taste_corpus

TAG = "teyla-taste-v1"
DIR = "taste"
MAX_JSON = 64 * 1024
MAX_IMAGE = 5 * 1024 * 1024
MAX_SENTENCE = relay.MAX_TEXT
MAX_URL = 2000
YOUNG_S = 600                    # a drop first seen on this Mac less than this long ago may still be arriving from iCloud
MAX_TRIES = 3                    # an import that fails (a corpus that cannot be written) is tried this often, then given up
FIELDS = frozenset({"v", "id", "created", "device", "verdict", "url", "image", "sentence"})
IMAGES = {"image.jpg": ".jpg", "image.png": ".png"}
VERDICTS = ("like", "dislike")
MAX_PER_PASS = 20

_HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def drop_message(did: str, created: str, json_bytes: bytes, image_bytes: bytes) -> bytes:
    return "\n".join((TAG, did, created, sha256_bytes(json_bytes), sha256_bytes(image_bytes))).encode("utf-8")


def drop_sig(key: bytes, did: str, created: str, json_bytes: bytes, image_bytes: bytes = b"") -> str:
    return relay.sign(key, drop_message(did, created, json_bytes, image_bytes))


def shape(obj) -> str:
    """"" when `obj` is a well-formed drop, else the reason. Nothing here depends on the key."""
    if not isinstance(obj, dict) or set(obj) != FIELDS:
        return "malformed drop"
    if type(obj["v"]) is not int or obj["v"] != 1:
        return "malformed drop: unknown version"
    for k in ("id", "created", "device", "verdict", "sentence"):
        if not isinstance(obj[k], str):
            return f"malformed drop: {k}"
    if not relay._UUID_RE.fullmatch(obj["id"]):
        return "malformed drop: id"
    if not relay._PATTERNS["created"].fullmatch(obj["created"]) or relay._created_epoch(obj["created"]) is None:
        return "malformed drop: created"
    if not relay._PATTERNS["device"].fullmatch(obj["device"]):
        return "malformed drop: device"
    if obj["verdict"] not in VERDICTS:
        return "malformed drop: verdict"
    s = obj["sentence"]
    if len(s) > MAX_SENTENCE or "\x00" in s:
        return "malformed drop: sentence"
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return "malformed drop: sentence"
    url, image = obj["url"], obj["image"]
    if (url is None) == (image is None):
        return "malformed drop: give a link or a picture, not both or neither"
    if url is not None and (not isinstance(url, str) or len(url) > MAX_URL or not taste_corpus.is_url(url)):
        return "malformed drop: url"
    if image is not None and (not isinstance(image, str) or image not in IMAGES):
        return "malformed drop: image"
    return ""


# --- reading the folder, never through a link ----------------------------------------------------

def _open_dir(name: str, dir_fd: int) -> int | None:
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError:
        return None


def _read_file(dfd: int, name: str, cap: int) -> tuple[bytes | None, str]:
    """(bytes, "") or (None, why). Missing is "missing"; a link, a directory or a file over `cap` is a refusal."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dfd)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "not a readable file"
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            return None, "not a regular file"
        if st.st_size > cap:
            return None, "too large"
        return f.read(cap + 1), ""


def seen_path() -> pathlib.Path:
    return relay.ctl.home() / "taste-seen.json"


def _load_seen() -> dict[str, float]:
    """When this Mac first saw each drop that is still waiting. The grace for files still arriving counts from
    here: a synced modification time says when the phone wrote a file, not when iCloud delivered it."""
    try:
        got = json.loads(seen_path().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(got, dict):
        return {}
    return {k: float(v) for k, v in got.items() if isinstance(k, str) and isinstance(v, (int, float))}


def _remove(parent_fd: int, name: str) -> None:
    """Delete a drop folder: its plain files, then the folder. Anything else in it leaves it in place."""
    dfd = _open_dir(name, parent_fd)
    if dfd is None:
        return
    try:
        for n in os.listdir(dfd):
            try:
                os.unlink(n, dir_fd=dfd)
            except OSError:
                pass
    finally:
        os.close(dfd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError:
        pass


def import_drop(obj: dict, image: bytes | None, add_fn=None) -> str:
    """Create the corpus entry for a drop that has been verified. Returns the entry id."""
    add_fn = add_fn or taste_corpus.add
    sentence = obj["sentence"].strip()
    words: list[str]
    tmp: tempfile.TemporaryDirectory | None = None
    try:
        if obj["url"] is not None:
            words = [obj["url"], sentence] if sentence else [obj["url"]]
        else:
            tmp = tempfile.TemporaryDirectory(prefix="teyla-taste-")
            path = pathlib.Path(tmp.name) / ("image" + IMAGES[obj["image"]])
            path.write_bytes(image or b"")
            words = [str(path), sentence] if sentence else [str(path)]
        d, e = add_fn(words, verdict=obj["verdict"])
    finally:
        if tmp is not None:
            tmp.cleanup()
    if obj["url"] is None:                        # the temporary path is gone; name the source for what it is
        try:
            e["source"] = f"iphone-share-{obj['id'][:8]}{IMAGES[obj['image']]}"
            taste_corpus.write_entry(d, e)
        except OSError:
            pass                                      # the entry exists; a retry would add it twice
    return e["id"]


def pull(dirs: "relay.Dirs", key: bytes, now: float, add_fn=None) -> list[dict]:
    """Import every verified drop in `outbox/taste/`. One result per drop that was decided this pass:
    {"id", "kind": "taste", "ok", "detail"}. A drop still arriving is left alone."""
    box = _open_dir(DIR, dirs.outbox)
    if box is None:
        return []
    out: list[dict] = []
    seen = _load_seen()
    before = dict(seen)
    try:
        names = sorted(n for n in os.listdir(box) if relay._UUID_RE.fullmatch(n))[:MAX_PER_PASS]
        for name in names:
            try:
                res = _one(box, name, key, now, add_fn, seen)
            except Exception as exc:  # noqa: BLE001 - one odd folder must never stop the drops after it
                res = {"id": name.lower(), "kind": "taste", "ok": False,
                       "detail": f"skipped: {type(exc).__name__}: {relay._clip(str(exc), 120)}"}
            if res is not None:
                out.append(res)
        waiting = {n.lower() for n in os.listdir(box)}
        seen = {k: v for k, v in seen.items() if k in waiting and now - v < relay.JOURNAL_KEEP_S}
        if seen != before:
            try:
                relay._write_json(seen_path(), seen)
            except OSError:
                pass
    finally:
        os.close(box)
    return out


def _one(box: int, name: str, key: bytes, now: float, add_fn, seen: dict[str, float]) -> dict | None:
    did = name.lower()

    def refuse(why: str) -> dict:
        _remove(box, name)
        return {"id": did, "kind": "taste", "ok": False, "detail": why}

    dfd = _open_dir(name, box)
    if dfd is None:
        return refuse("not a plain folder")
    try:
        young = now - seen.setdefault(did, now) < YOUNG_S
        raw, why = _read_file(dfd, "taste.json", MAX_JSON)
        sig, why_s = _read_file(dfd, "taste.sig", 1024)
        if raw is None or sig is None:
            if "missing" in (why, why_s) and young:
                return None
            return refuse(f"taste.json or taste.sig: {why if raw is None else why_s}")
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            return None if young else refuse("taste.json is not JSON")
        bad = shape(obj)
        if not bad and obj["id"].lower() != did:
            bad = "malformed drop: id does not match the folder name"
        if bad:
            return refuse(bad)
        image = b""
        if obj["image"] is not None:
            img, why_i = _read_file(dfd, obj["image"], MAX_IMAGE)
            if img is None:
                if why_i == "missing" and young:
                    return None
                return refuse(f"{obj['image']}: {why_i}")
            if taste_corpus_media(img) is None:
                return refuse("the picture is not a PNG or JPEG")
            image = img
        sig_text = sig.decode("ascii", "replace").strip()
        good = _HEX64.fullmatch(sig_text) and hmac.compare_digest(
            drop_sig(key, obj["id"], obj["created"], raw, image).encode("ascii"), sig_text.encode("ascii"))
        if not good:
            return None if young else refuse("bad signature")
        age = now - (relay._created_epoch(obj["created"]) or 0.0)
        if age > relay.MAX_AGE_S:
            return refuse("too old (more than 7 days); share it again")
        if age < -relay.MAX_AHEAD_S:
            return refuse("dated in the future; check the phone's clock")
        tries = 0
        if not relay._claim({"id": did, "kind": "taste", "target": "taste"}, now):
            rec = relay._journal_read(did) or {}
            res = rec.get("result") if isinstance(rec.get("result"), dict) else {}
            if rec.get("state") != "retry":           # imported, or a pass was cut off: never imported twice
                _remove(box, name)
                return {"id": did, "kind": "taste", "ok": False, "detail": "replay: already handled"}
            tries = res.get("tries") if type(res.get("tries")) is int else MAX_TRIES
            relay._journal_set(did, "claimed", now, {"tries": tries})
        try:
            eid = import_drop(obj, image or None, add_fn)
        except Exception as exc:                        # noqa: BLE001
            tries += 1
            why = f"{type(exc).__name__}: {relay._clip(str(exc), 120)}"
            if tries < MAX_TRIES:                       # the drop stays in the outbox; the next pass tries again
                relay._journal_set(did, "retry", now, {"tries": tries, "ok": False, "detail": why})
                return {"id": did, "kind": "taste", "ok": False,
                        "detail": f"could not add it, will retry ({tries}/{MAX_TRIES}): {why}"}
            detail = f"could not add it after {MAX_TRIES} tries: {why}"
            relay._journal_set(did, "done", now, {"ok": False, "via": "taste", "detail": relay._clip(detail)})
            _remove(box, name)
            return {"id": did, "kind": "taste", "ok": False, "detail": detail}
        detail = f"added {eid} ({obj['verdict']}, {'proposed' if obj['sentence'].strip() else 'raw'})"
        relay._journal_set(did, "done", now, {"ok": True, "via": "taste", "detail": relay._clip(detail)})
        _remove(box, name)                              # only now, after the corpus entry is on disk
        return {"id": did, "kind": "taste", "ok": True, "detail": detail}
    finally:
        os.close(dfd)


def taste_corpus_media(head: bytes):
    from . import ux_judge
    t = ux_judge._media_type(head[:16])
    return t if t in ("image/png", "image/jpeg") else None

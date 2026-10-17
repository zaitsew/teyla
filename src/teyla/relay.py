"""`teyla relay` — the Mac side of the iPhone relay (`docs/APP.md`, "The relay (Mac ↔ iPhone)").

    teyla relay on | off | status [--json]       switch the relay on or off, say where it stands
    teyla relay pair [--json] [--rotate]         create the shared key, print the pairing string
    teyla relay sync [--quiet]                   one pass: write the snapshot, deliver the signed outbox

The relay folder is in iCloud Drive, so anyone who can write to it is untrusted: the outbox can make
Teyla send text into coding sessions that run with bypassed permissions. Everything in it is data
until its signature checks out, and an entry is delivered at most once.

An entry is checked in this order, and the first failure ends it:

1. Shape, before any cryptography: the file is a regular file under 64 KB (opened without following
   a link), the JSON has exactly the nine fields, and every field but `text` matches its strict
   pattern, so no line break can move text into another signed field.
2. The HMAC-SHA256 over the signed lines, compared in constant time. A bad signature is answered
   with the reason alone, never with the text.
3. The journal: `~/.teyla/relay-journal/<id>.json` is created with O_EXCL (state `claimed`). An id
   that is already there is a replay and is never delivered again.
4. The window (`created` not older than 7 days, not more than 10 minutes ahead), `text` length, the
   target (an open question, a running session, a product) and `about`, the SHA-256 of the text the
   owner saw. Then delivery, then the journal entry becomes `done` and `sent/<id>.json` is written.

A `claimed` entry found at the start of a pass was cut off between claim and result: it gets
`ok: false, "interrupted; check the session, then send again"` and is never retried. The journal
holds no text. Entries older than 8 days are dropped: the 7-day window makes a replay impossible.

An answer never falls back to the clipboard (`answer.answer(clipboard=False)`): a question that only
`copy and open` could deliver stays open and `sent/` says "needs the Mac". Safe mode makes `sync`
a no-op. The launchd agent `com.zaitsew.teyla.relay` runs `sync` when the outbox changes and every
60 seconds. The key is read from `~/.teyla/relay.key` and written nowhere else, and never printed
except by `pair`.
"""
from __future__ import annotations

import base64
import datetime as _dt
import fcntl
import hashlib
import hmac
import json
import os
import pathlib
import re
import secrets
import stat
import subprocess
import sys
import time

from . import answer as answer_mod
from . import asks, config
from . import routine_install as ri
from . import state as snapshot
from .control import state as ctl

LABEL = "com.zaitsew.teyla.relay"
DEFAULT_FOLDER = "~/Library/Mobile Documents/com~apple~CloudDocs/Teyla"
PAIR_PREFIX = "teyla-pair:v1:"
STATE_PREFIX = b"teyla-state-v1\n"
OUTBOX_TAG = "teyla-outbox-v1"
KEY_BYTES = 32
MAX_FILE = 64 * 1024
MAX_TEXT = 8000
MAX_AGE_S = 7 * 86400
MAX_AHEAD_S = 600
JOURNAL_KEEP_S = 8 * 86400
YOUNG_FILE_S = 120               # a file this fresh that does not parse may still be arriving
KINDS = ("answer", "say", "dispatch")
FIELDS = frozenset({"v", "id", "kind", "target", "about", "text", "created", "device", "sig"})
DETAIL_MAX = 300
RUN_TIMEOUT_S = {"say": 60, "dispatch": 180}

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_UUID_RE = re.compile(_UUID, re.ASCII | re.IGNORECASE)
_FILE_RE = re.compile(_UUID + r"\.json", re.ASCII | re.IGNORECASE)
_PATTERNS = {
    "kind": re.compile(r"answer|say|dispatch", re.ASCII),
    "target": re.compile(r"[A-Za-z0-9_.:#/-]{1,200}", re.ASCII),
    "about": re.compile(r"[0-9a-f]{64}", re.ASCII),
    "created": re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})", re.ASCII),
    "device": re.compile(r"[A-Za-z0-9 ._-]{1,64}", re.ASCII),
    "sig": re.compile(r"[0-9a-f]{64}", re.ASCII),
}


class RelayError(Exception):
    """A problem the owner can fix; the message says how."""


# --- paths and settings -----------------------------------------------------------------------

def key_path() -> pathlib.Path:
    return ctl.home() / "relay.key"


def cfg_path() -> pathlib.Path:
    return ctl.home() / "relay.json"


def lock_path() -> pathlib.Path:
    return ctl.home() / "relay.lock"


def journal_dir() -> pathlib.Path:
    return ctl.home() / "relay-journal"


def configured_folder() -> pathlib.Path:
    raw = str(((config.load().get("relay") or {}).get("folder")) or DEFAULT_FOLDER)
    return pathlib.Path(raw).expanduser()


def plist_path() -> pathlib.Path:
    return ri.PLIST_PATH.parent / f"{LABEL}.plist"


def wrapper_path() -> pathlib.Path:
    return ri.WRAPPER_PATH.parent / "relay.sh"


def log_path() -> pathlib.Path:
    return ri.LOG_PATH.parent / "teyla-relay.log"


def _iso(epoch: float) -> str:
    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> float:
    return time.time()


def _clip(text: str, n: int = DETAIL_MAX) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _write_atomic(path: pathlib.Path, data: bytes, mode: int = 0o600) -> None:
    """Write beside the target and rename over it: a reader sees the old file or the new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_json(path: pathlib.Path, obj: dict, mode: int = 0o600) -> None:
    _write_atomic(path, (json.dumps(obj, indent=1, ensure_ascii=False) + "\n").encode("utf-8"), mode)


def read_cfg() -> dict:
    d = {"on": False, "folder": "", "synced": ""}
    try:
        got = json.loads(cfg_path().read_text())
    except (OSError, ValueError):
        return d
    if isinstance(got, dict):
        d["on"] = got.get("on") is True
        d["folder"] = got["folder"] if isinstance(got.get("folder"), str) else ""
        d["synced"] = got["synced"] if isinstance(got.get("synced"), str) else ""
    return d


def write_cfg(cfg: dict) -> None:
    _write_json(cfg_path(), {"on": bool(cfg["on"]), "folder": str(cfg["folder"]), "synced": str(cfg["synced"])})


# --- the key and the signatures ---------------------------------------------------------------

def read_key() -> bytes | None:
    """The shared key, or None when there is no usable one. A key file others can read, a link, or the wrong size
    is not used: signing with a key that may have leaked would be worse than not syncing."""
    try:
        fd = os.open(key_path(), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
            return None
        key = f.read(KEY_BYTES + 1)
    return key if len(key) == KEY_BYTES else None


def create_key(rotate: bool = False) -> bytes:
    """32 random bytes into ~/.teyla/relay.key, mode 0600, created exclusively. An existing key is kept
    unless `rotate`, which replaces it by renaming a fresh exclusive file over it."""
    p = key_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_bytes(KEY_BYTES)
    target = p.with_name(p.name + ".new") if rotate and os.path.lexists(p) else p
    if target != p:
        try:
            os.unlink(target)               # left by a rotation that died; O_EXCL below still guards the new one
        except FileNotFoundError:
            pass
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        raise RelayError(f"{p} exists: the relay is already paired. `teyla relay pair --rotate` replaces the key "
                         "and the phone must pair again") from None
    with os.fdopen(fd, "wb") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(key)
        f.flush()
        os.fsync(f.fileno())
    if target != p:
        os.replace(target, p)
    return key


def pairing_string(key: bytes) -> str:
    return PAIR_PREFIX + base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii")


def sign(key: bytes, message: bytes) -> str:
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def state_bytes(snap: dict) -> bytes:
    # a lone surrogate in session text becomes "?", not an exception that stops the pass
    return json.dumps(snap, separators=(",", ":"), ensure_ascii=False).encode("utf-8", "replace")


def state_file(key: bytes, body: bytes) -> bytes:
    """Line 1 the signature, then the bytes it covers."""
    return sign(key, STATE_PREFIX + body).encode("ascii") + b"\n" + body


def entry_message(e: dict) -> bytes:
    return "\n".join([OUTBOX_TAG, str(e["v"]), e["id"], e["kind"], e["target"], e["about"],
                      e["created"], e["device"], e["text"]]).encode("utf-8")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _created_epoch(created: str) -> float | None:
    try:
        d = _dt.datetime.fromisoformat(created)
    except ValueError:
        return None
    return d.timestamp() if d.tzinfo else None


def entry_shape(obj) -> str:
    """"" when `obj` is a well-formed entry, else the reason. Nothing here depends on the key."""
    if not isinstance(obj, dict) or set(obj) != FIELDS:
        return "malformed entry"
    if type(obj["v"]) is not int or obj["v"] != 1:
        return "malformed entry: unknown version"
    for k in ("id", "text", *_PATTERNS):
        if not isinstance(obj[k], str):
            return f"malformed entry: {k}"
    if not _UUID_RE.fullmatch(obj["id"]):
        return "malformed entry: id"
    for k, rx in _PATTERNS.items():
        if not rx.fullmatch(obj[k]):
            return f"malformed entry: {k}"
    if _created_epoch(obj["created"]) is None:
        return "malformed entry: created"
    try:
        obj["text"].encode("utf-8")
    except UnicodeEncodeError:
        return "malformed entry: text"
    if len(obj["text"]) > MAX_TEXT:
        return "text is longer than 8,000 characters"
    if not obj["text"].strip() or "\x00" in obj["text"]:
        return "malformed entry: text"
    return ""


def signature_ok(key: bytes, e: dict) -> bool:
    return hmac.compare_digest(sign(key, entry_message(e)).encode("ascii"), e["sig"].encode("ascii"))


# --- status -----------------------------------------------------------------------------------

def status() -> dict:
    """{on, paired, folder, synced, agent}: the snapshot's `relay` object (`agent`: the launchd plist exists)."""
    c = read_cfg()
    return {"on": c["on"], "paired": read_key() is not None, "folder": c["folder"], "synced": c["synced"],
            "agent": plist_path().exists()}


# --- on / off ---------------------------------------------------------------------------------

PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>{wrapper}</string>
    </array>
    <key>WatchPaths</key>
    <array>
        <string>{outbox}</string>
    </array>
    <key>StartInterval</key>
    <integer>60</integer>
    <key>EnvironmentVariables</key>
    <dict>
{env_plist}    </dict>
    <key>StandardOutPath</key>
    <string>{log}</string>
    <key>StandardErrorPath</key>
    <string>{log}</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""

WRAPPER = """#!/usr/bin/env bash
# Written by `teyla relay on`; `teyla relay off` removes it. One relay pass: snapshot out, signed outbox in.
set -uo pipefail
{env_sh}
export TEYLA_IN_ROUTINE="{label}"
"{teyla_bin}" relay sync --quiet
"""


def _folder_for_on() -> pathlib.Path:
    folder = configured_folder()
    icloud = pathlib.Path(DEFAULT_FOLDER).expanduser().parent
    if folder.parent == icloud and not icloud.is_dir():
        raise RelayError(f"iCloud Drive is not set up here ({icloud} is missing). Turn on iCloud Drive in System "
                         "Settings, or point `teyla config set relay.folder=<path>` at another folder")
    return folder


def relay_on(*, load=None) -> list[str]:
    load = ri._load if load is None else load
    folder = _folder_for_on()
    for sub in ("", "outbox", "sent"):
        (folder / sub).mkdir(parents=True, exist_ok=True)
    cfg = read_cfg()
    cfg.update(on=True, folder=str(folder))
    write_cfg(cfg)
    lines = [f"relay folder: {folder}"]
    teyla_bin = ri._teyla_bin()
    env = ri.launchd_env(teyla_bin)
    wrapper, plist, log = wrapper_path(), plist_path(), log_path()
    for d in (wrapper.parent, plist.parent, log.parent):
        d.mkdir(parents=True, exist_ok=True)
    ri._write(wrapper, WRAPPER.format(env_sh=ri._env_sh(env), label=LABEL, teyla_bin=teyla_bin), 0o755)
    ri._write(plist, PLIST.format(label=LABEL, wrapper=wrapper, outbox=folder / "outbox", log=log,
                                  env_plist=ri._env_plist(env)))
    lines += [f"wrote {wrapper}", f"wrote {plist}"]
    if sys.platform == "darwin":
        lines.append(load(plist, LABEL))
    else:
        lines.append(f"not macOS: run `teyla relay sync` every minute yourself ({wrapper})")
    if read_key() is None:
        lines.append("not paired yet: run `teyla relay pair`")
    if config.safe_mode():
        lines.append("safe mode is on: `sync` does nothing until it is off")
    return lines


def relay_off(*, unload=None) -> list[str]:
    unload = ri._unload if unload is None else unload
    lines = []
    plist, wrapper = plist_path(), wrapper_path()
    if plist.exists() and sys.platform == "darwin":
        lines.append(unload(plist, LABEL))
    for f in (plist, wrapper):
        if f.exists():
            f.unlink()
            lines.append(f"removed {f}")
    cfg = read_cfg()
    cfg["on"] = False
    write_cfg(cfg)
    lines.append(f"relay off; the folder {cfg['folder'] or '(none)'} and the key are left as they are")
    return lines


# --- the journal ------------------------------------------------------------------------------

def _journal_file(jid: str) -> pathlib.Path:
    return journal_dir() / f"{jid.lower()}.json"


def _claim(e: dict, now: float) -> bool:
    """Create the journal entry exclusively. False: it exists, so this id was handled or is being handled."""
    jd = journal_dir()
    jd.mkdir(parents=True, exist_ok=True)
    os.chmod(jd, 0o700)
    try:
        fd = os.open(_journal_file(e["id"]), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    rec = {"id": e["id"], "state": "claimed", "kind": e["kind"], "target": e["target"], "ts": _iso(now)}
    with os.fdopen(fd, "wb") as f:
        f.write(json.dumps(rec).encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    return True


def _journal_read(jid: str) -> dict | None:
    try:
        got = json.loads(_journal_file(jid).read_text())
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def _journal_set(jid: str, state: str, now: float, result: dict | None = None) -> None:
    rec = _journal_read(jid) or {"id": jid, "ts": _iso(now)}
    rec["state"] = state
    if result is not None:
        rec["result"] = result
    _write_json(_journal_file(jid), rec)


def prune_journal(now: float) -> int:
    n = 0
    for f in journal_dir().glob("*.json"):
        try:
            rec = json.loads(f.read_text())
            ts = _created_epoch(str(rec.get("ts", "")))
            if ts is None:
                ts = f.stat().st_mtime
            if now - ts > JOURNAL_KEEP_S:
                f.unlink()
                n += 1
        except (OSError, ValueError, AttributeError):
            continue
    return n


# --- sent/ ------------------------------------------------------------------------------------

def _sent_file(folder: pathlib.Path, eid: str) -> pathlib.Path:
    return folder / "sent" / f"{eid}.json"


def write_sent(folder: pathlib.Path, eid: str, ok: bool, via: str, detail: str, now: float) -> None:
    _write_json(_sent_file(folder, eid), {"id": eid, "ok": ok, "via": via, "detail": _clip(detail),
                                          "done_at": _iso(now)})


def _unlink(path: pathlib.Path) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


# --- delivery ---------------------------------------------------------------------------------

def run_command(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    """(exit code, stdout, stderr). 127 no such program, 124 timed out."""
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except FileNotFoundError:
        return 127, "", f"{cmd[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{cmd[0]}: timed out after {timeout}s"
    except (OSError, ValueError) as e:
        return 126, "", str(e)


def teyla_command() -> list[str]:
    return [sys.executable, "-m", "teyla"]


def _last_line(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return lines[-1] if lines else ""


def deliver_subcommand(kind: str, target: str, text: str, runner, base: list[str]) -> tuple[bool, str, str]:
    """`teyla say <running-id> --json -- <text>` or `teyla dispatch <product> --json -- <text>`."""
    code, out, err = runner([*base, kind, target, "--json", "--", text], RUN_TIMEOUT_S[kind])
    if code == 2 and ("invalid choice" in err or "unrecognized" in err):
        return False, "", f"this Teyla cannot do {kind} yet"
    if code == 124:
        return False, "", "timed out; check the session, then send again"
    try:
        res = json.loads(_last_line(out))
    except ValueError:
        res = None
    if isinstance(res, dict):
        ok = res.get("ok") is True and code == 0
        return ok, str(res.get("via") or ""), str(res.get("detail") or "")
    return False, "", _last_line(err) or _last_line(out) or f"exit {code}"


def deliver_answer(item: asks.Ask, text: str, answer_fn) -> tuple[bool, str, str]:
    res = answer_fn(item, text, clipboard=False)
    return bool(res.get("ok")), str(res.get("via") or ""), str(res.get("detail") or "")


# --- one sync pass ----------------------------------------------------------------------------

class Pass:
    """What one pass works from: the folder, the key, the facts the phone's `about` is checked against."""

    def __init__(self, folder, key, now, snap, items, answer_fn, runner, base):
        self.folder, self.key, self.now = folder, key, now
        self.answers = {r["id"]: r["question"] for r in snap.get("asks", []) if isinstance(r, dict) and "id" in r}
        self.running = {r["id"]: r.get("title", "") for r in snap.get("running", []) if isinstance(r, dict) and r.get("id")}
        self.products = {r["name"] for r in snap.get("products", []) if isinstance(r, dict) and "name" in r}
        self.items = {a.id: a for a in items}
        self.answer_fn, self.runner, self.base = answer_fn, runner, base


def recover(folder: pathlib.Path, now: float) -> list[dict]:
    """A journal entry still `claimed` was cut off before it had a result. Report it; never retry it."""
    out = []
    for f in sorted(journal_dir().glob("*.json")):
        rec = _journal_read(f.stem)
        if not rec or rec.get("state") != "claimed":
            continue
        eid = str(rec.get("id") or f.stem)
        if not _UUID_RE.fullmatch(eid):
            continue
        detail = "interrupted; check the session, then send again"
        _journal_set(eid, "interrupted", now, {"ok": False, "via": "", "detail": detail})
        write_sent(folder, eid, False, "", detail, now)
        _unlink(folder / "outbox" / f"{eid}.json")
        out.append({"id": eid, "ok": False, "detail": detail})
    return out


def _reject_unsigned(p: Pass, path: pathlib.Path, stem: str, reason: str) -> dict:
    """An entry that did not prove it came from the phone. The reason goes to sent/, unless that id has an
    outcome already: a forged copy of a real id must not overwrite the real result."""
    if _journal_read(stem) is None and not _sent_file(p.folder, stem).exists():
        write_sent(p.folder, stem, False, "", reason, p.now)
    _unlink(path)
    return {"id": stem, "ok": False, "detail": reason}


def _replay(p: Pass, e: dict, path: pathlib.Path) -> dict:
    """A signed entry whose id the journal knows: never delivered again. The real result is put back in
    sent/ if the phone has already cleared it; nothing existing is overwritten."""
    rec = _journal_read(e["id"]) or {}
    res = rec.get("result") if isinstance(rec.get("result"), dict) else None
    if not _sent_file(p.folder, e["id"]).exists():
        if res and rec.get("state") in ("done", "rejected", "interrupted"):
            write_sent(p.folder, e["id"], bool(res.get("ok")), str(res.get("via") or ""), str(res.get("detail") or ""), p.now)
        else:
            write_sent(p.folder, e["id"], False, "", "already handled", p.now)
    _unlink(path)
    return {"id": e["id"], "ok": False, "detail": "replay: already handled"}


def _decide(p: Pass, e: dict) -> tuple[bool, str, str, str]:
    """(ok, via, detail, state). Checks, then delivery. state is `done` or `rejected`."""
    def no(why: str):
        return False, "", why, "rejected"
    age = p.now - (_created_epoch(e["created"]) or 0.0)
    if age > MAX_AGE_S:
        return no("too old (more than 7 days); send it again")
    if age < -MAX_AHEAD_S:
        return no("dated in the future; check the phone's clock")
    kind, target = e["kind"], e["target"]
    if kind == "answer":
        seen = p.answers.get(target)
        if seen is None or target not in p.items:
            return no("that question is no longer open")
    elif kind == "say":
        seen = p.running.get(target)
        if seen is None:
            return no("that session is not running")
    else:
        seen = target if target in p.products else None
        if seen is None:
            return no("unknown product")
    if not hmac.compare_digest(sha256_hex(str(seen)).encode("ascii"), e["about"].encode("ascii")):
        return no("it changed since you read it; look again")
    try:
        if kind == "answer":
            ok, via, detail = deliver_answer(p.items[target], e["text"], p.answer_fn)
        else:
            ok, via, detail = deliver_subcommand(kind, target, e["text"], p.runner, p.base)
    except Exception as exc:  # noqa: BLE001 — whatever went wrong, the entry has been claimed: report, never retry
        return False, "", f"delivery failed ({type(exc).__name__}); check the session, then send again", "done"
    return ok, via, detail, "done"


def process_one(p: Pass, path: pathlib.Path, stem: str) -> dict | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return _reject_unsigned(p, path, stem, "malformed entry: not a readable file")
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            return _reject_unsigned(p, path, stem, "malformed entry: not a regular file")
        if st.st_size > MAX_FILE:
            return _reject_unsigned(p, path, stem, "file is larger than 64 KB")
        raw = f.read(MAX_FILE + 1)
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        if p.now - st.st_mtime < YOUNG_FILE_S:
            return None                         # may still be arriving from iCloud: look again next pass
        return _reject_unsigned(p, path, stem, "malformed entry: not JSON")
    why = entry_shape(obj)
    if not why and obj["id"] != stem:
        why = "malformed entry: id does not match the file name"
    if why:
        return _reject_unsigned(p, path, stem, why)
    if not signature_ok(p.key, obj):
        return _reject_unsigned(p, path, stem, "bad signature")
    if not _claim(obj, p.now):
        return _replay(p, obj, path)
    ok, via, detail, state = _decide(p, obj)
    result = {"ok": ok, "via": via, "detail": _clip(detail)}
    _journal_set(obj["id"].lower(), state, p.now, result)
    write_sent(p.folder, obj["id"], ok, via, detail, p.now)
    _unlink(path)
    return {"id": obj["id"], "kind": obj["kind"], **result}


def process_outbox(p: Pass) -> list[dict]:
    box = p.folder / "outbox"
    try:
        names = sorted(os.listdir(box))
    except OSError:
        return []
    out = []
    for name in names:
        if not _FILE_RE.fullmatch(name):        # iCloud placeholders (.name.json.icloud), temp files, strays
            continue
        res = process_one(p, box / name, name[:-len(".json")])
        if res is not None:
            out.append(res)
    return out


def default_source(now: float):
    items = asks.collect(asks.DEFAULT_DAYS, now)
    return snapshot.build(now, items=items), items


def write_snapshot(folder: pathlib.Path, key: bytes, snap: dict) -> None:
    _write_atomic(folder / "state.teyla", state_file(key, state_bytes(snap)))


def sync(*, now: float | None = None, source=None, answer_fn=None, runner=None, base: list[str] | None = None,
         folder: pathlib.Path | None = None) -> dict:
    """One pass. Returns {"skipped": reason} or {"processed": [...], "recovered": [...]}."""
    if config.safe_mode():
        return {"skipped": "safe mode"}
    cfg = read_cfg()
    if not cfg["on"]:
        return {"skipped": "relay is off"}
    key = read_key()
    if key is None:
        return {"skipped": "not paired (no usable key)"}
    folder = folder or pathlib.Path(cfg["folder"] or configured_folder())
    ctl.home().mkdir(parents=True, exist_ok=True)
    lock = os.open(lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"skipped": "another pass is running"}
        now = _now() if now is None else now
        source = source or default_source
        recovered = recover(folder, now)
        snap, items = source(now)
        write_snapshot(folder, key, snap)
        p = Pass(folder, key, now, snap, items, answer_fn or answer_mod.answer, runner or run_command,
                 base or teyla_command())
        processed = process_outbox(p)
        if processed or recovered:
            snap, _ = source(now)              # what was just answered is no longer waiting
            write_snapshot(folder, key, snap)
        cfg["synced"] = snap.get("generated") if isinstance(snap.get("generated"), str) else _iso(now)
        write_cfg(cfg)
        prune_journal(now)
        return {"processed": processed, "recovered": recovered}
    finally:
        os.close(lock)                          # closing releases the flock


# --- CLI --------------------------------------------------------------------------------------

def cmd_relay(args) -> int:
    act = args.action
    try:
        if act == "pair":
            existing = None if args.rotate else read_key()
            # Pairing a second phone, or showing the QR again, reuses the key; --rotate replaces it.
            key = existing or create_key(rotate=args.rotate)
            s = pairing_string(key)
            if args.json:
                print(json.dumps({"pairing": s, "rotated": bool(args.rotate), "new": existing is None}))
            else:
                print(s)
                print("Scan or paste this on the iPhone. It is the key: do not share it.", file=sys.stderr)
            return 0
        if act == "on":
            print("\n".join(relay_on()))
            return 0
        if act == "off":
            print("\n".join(relay_off()))
            return 0
        if act == "status":
            st = status()
            if args.json:
                print(json.dumps(st))
            else:
                print(f"relay {'on' if st['on'] else 'off'}, {'paired' if st['paired'] else 'not paired'}, "
                      f"agent {'installed' if st['agent'] else 'not installed'}; folder {st['folder'] or '(none)'}; "
                      f"last snapshot {st['synced'] or 'never'}")
            return 0
        res = sync()
    except RelayError as e:
        print(f"teyla relay: {e}", file=sys.stderr)
        return 1
    if "skipped" in res:
        if not args.quiet:
            print(f"relay sync skipped: {res['skipped']}")
        return 0
    for r in res["recovered"] + res["processed"]:
        print(f"{r['id']}: {'ok' if r['ok'] else 'refused'}: {r['detail']}")
    if not args.quiet and not (res["recovered"] or res["processed"]):
        print("relay synced; the outbox is empty")
    return 0


def register(sp):
    q = sp.add_parser("relay", help="the iPhone relay: on, off, status, pair, sync")
    q.set_defaults(fn=cmd_relay)
    q.add_argument("action", choices=["on", "off", "status", "pair", "sync"])
    q.add_argument("--json", action="store_true", help="status, pair: print JSON")
    q.add_argument("--rotate", action="store_true", help="pair: replace the key (the phone must pair again)")
    q.add_argument("--quiet", action="store_true", help="sync: print only what was delivered or refused")
    return q

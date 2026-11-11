"""`teyla relay` — the Mac side of the iPhone relay (`docs/APP.md`, "The relay (Mac ↔ iPhone)").

    teyla relay on | off | status [--json]       switch the relay on or off, say where it stands
    teyla relay connect [--json]                 on + key + one sync, then hand the key to Teyla for Mac
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

One more kind, `activity`, is the phone's "+1" on the Growth tab: `target` is one of `ACTIVITY_KINDS`, `text` is
the fixed string `+1`, `about` is the SHA-256 of the kind, and it runs exactly `teyla growth log --kind <target>`.
The kind is checked against the fixed list, so free text never reaches a command line.

Two more kinds exist for the Decisions screen, and they run exactly one command each: `close` runs
`teyla asks accept-close <id> --json` for a question in triage bucket `close`, and `reopen` runs
`teyla asks undo <id>`. Neither sends text anywhere. `close` is checked against the question the owner
saw (`about` is the SHA-256 of its text, as for an answer); `reopen` has no open question to show, so
its `about` is the SHA-256 of the id, and `asks undo` itself refuses a question that is not closed.

One more thing travels the same way, in its own folder: `outbox/taste/<uuid>/` holds a signed like or dislike from the
iPhone's Share extension (a link or a picture, and an optional sentence). `taste_wire.py` checks and imports it as a
corpus entry; it is never run as a command.

An answer never falls back to the clipboard (`answer.answer(clipboard=False)`): a question that only
`copy and open` could deliver stays open and `sent/` says "needs the Mac". Safe mode makes `sync`
a no-op. The launchd agent `com.zaitsew.teyla.relay` runs `sync` when the outbox changes and every
60 seconds. The key is read from `~/.teyla/relay.key` and written nowhere else, and never printed
except by `pair`, and by `connect` when it cannot hand the key to Teyla for Mac.
"""
from __future__ import annotations

import base64
import ctypes
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
from xml.sax.saxutils import escape as _xml

from . import answer as answer_mod
from . import asks, config, github_activity
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
KINDS = ("answer", "say", "dispatch", "close", "reopen", "activity")
# The kinds of `teyla growth log --kind`: the phone's `activity` entry may name only these. Fixed here, never read from an entry.
ACTIVITY_KINDS = ("post", "comment", "reply", "email", "dm", "call", "meeting", "icp-meeting", "ad", "outreach", "response")
ACTIVITY_WEEKS = 17
FIELDS = frozenset({"v", "id", "kind", "target", "about", "text", "created", "device", "sig"})
DETAIL_MAX = 300
RUN_TIMEOUT_S = {"say": 60, "dispatch": 180, "close": 60, "reopen": 60, "activity": 60}

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_UUID_RE = re.compile(_UUID, re.ASCII | re.IGNORECASE)
_FILE_RE = re.compile(_UUID + r"\.json", re.ASCII | re.IGNORECASE)
_PATTERNS = {
    "kind": re.compile(r"answer|say|dispatch|close|reopen|activity", re.ASCII),
    "target": re.compile(r"[A-Za-z0-9_.:#/-]{1,200}", re.ASCII),
    "about": re.compile(r"[0-9a-f]{64}", re.ASCII),
    "created": re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-][0-9]{2}:[0-9]{2})", re.ASCII),
    "device": re.compile(r"[A-Za-z0-9 ._-]{1,64}", re.ASCII),
    "sig": re.compile(r"[0-9a-f]{64}", re.ASCII),
}
# `close` and `reopen` put the target on a command line, so it must not start like an option.
_ASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:#/-]{0,199}", re.ASCII)


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


def _rename_at(dfd: int, src: str, dst: str) -> None:
    """rename(2) inside one directory descriptor. Python on macOS has no dir_fd for os.replace, so renameat
    from libc is called directly there."""
    if os.replace in os.supports_dir_fd:
        os.replace(src, dst, src_dir_fd=dfd, dst_dir_fd=dfd)
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat(dfd, os.fsencode(src), dfd, os.fsencode(dst)) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), dst)


def _write_atomic_at(dfd: int, name: str, data: bytes, mode: int = 0o600) -> None:
    """_write_atomic for a directory held open: no path is looked up again, so a link swapped in after the
    folder was checked cannot redirect the write."""
    tmp = f".{name}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode, dir_fd=dfd)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fchmod(f.fileno(), mode)
            os.fsync(f.fileno())
        _rename_at(dfd, tmp, name)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dfd)
        except OSError:
            pass
        raise


def _fsync_dir(path: pathlib.Path) -> None:
    dfd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


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


def relay_on(*, load=None, paired_hint: bool = True) -> list[str]:
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
    ri._write(plist, PLIST.format(label=LABEL, wrapper=_xml(str(wrapper)), outbox=_xml(str(folder / "outbox")), log=_xml(str(log)),
                                  env_plist=ri._env_plist(env)))
    lines += [f"wrote {wrapper}", f"wrote {plist}"]
    if sys.platform == "darwin":
        lines.append(load(plist, LABEL))
    else:
        lines.append(f"not macOS: run `teyla relay sync` every minute yourself ({wrapper})")
    if paired_hint and read_key() is None:
        lines.append("not paired yet: run `teyla relay connect`")
    if config.safe_mode():
        lines.append("safe mode is on: `sync` does nothing until it is off")
    return lines

MAC_APP_BUNDLE_ID = "com.zaitsew.teyla"          # Teyla for Mac (store build); it registers the `teyla-pair:` URL scheme
PAIR_TEXT = ("Paste this into Teyla on your Mac or iPhone, or scan its QR code in Teyla on the Mac (Connect iPhone). "
             "It is the key: do not share it.")


def open_pairing(url: str) -> bool:
    """Hand the pairing URL to Teyla for Mac. An argv list, never a shell; macOS only. False when it did not open."""
    if sys.platform != "darwin":
        return False
    try:
        return subprocess.run(["open", "-b", MAC_APP_BUNDLE_ID, url], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def relay_connect(*, load=None, opener=None, sync_fn=None) -> dict:
    """The whole setup in one call: relay on, a key (an existing one is reused, never rotated), one sync so
    `state.teyla` exists at once, then the pairing URL to the Mac store build. A sync that fails or is skipped is
    a warning. Returns {"lines", "warnings", "folder", "new", "handed_over", "synced", "pairing"}."""
    opener = open_pairing if opener is None else opener
    sync_fn = sync if sync_fn is None else sync_fn
    lines = relay_on(load=load, paired_hint=False)
    existing = read_key()
    key = existing or create_key()
    warnings: list[str] = []
    synced = False
    try:
        res = sync_fn()
        if "skipped" in res:
            warnings.append(f"first sync skipped: {res['skipped']}")
        else:
            synced = True
    except Exception as exc:                    # a failed first pass must not undo the setup; the agent retries in 60 s
        warnings.append(f"first sync failed: {_clip(str(exc), 200)}")
    pairing = pairing_string(key)
    handed_over = bool(opener(pairing))
    return {"lines": lines, "warnings": warnings, "folder": read_cfg()["folder"], "new": existing is None,
            "handed_over": handed_over, "synced": synced, "pairing": pairing}


def _print_connect(res: dict, as_json: bool) -> None:
    if as_json:
        out = {"on": True, "folder": res["folder"], "new": res["new"], "handed_over": res["handed_over"],
               "synced": res["synced"]}
        if not res["handed_over"]:
            out["pairing"] = res["pairing"]
        print(json.dumps(out))
        for w in res["warnings"]:
            print(f"warning: {w}", file=sys.stderr)
        return
    progress = res["lines"] + [f"warning: {w}" for w in res["warnings"]]
    if res["handed_over"]:
        print("\n".join(progress))
        print('The Teyla window opens on your Mac: click "Use this folder" there.')
        # `open -b` also succeeds with a build older than the URL scheme: that build opens and ignores the key.
        print("If Teyla does not connect, update it, or run `teyla relay pair` and paste the string into it.")
        print("On your iPhone: in Teyla on the Mac, choose Connect iPhone and scan the QR code.")
        return
    print("\n".join(progress), file=sys.stderr)
    print(res["pairing"])
    print(PAIR_TEXT, file=sys.stderr)
    # The full build is "Teyla Admin.app"; builds before 0.41 were installed as Teyla.app.
    if any(pathlib.Path(f"~/Applications/{n}.app").expanduser().exists() for n in ("Teyla Admin", "Teyla")):
        print("The full Teyla app on this Mac needs no pairing: it shows the iPhone QR code under Connect iPhone.",
              file=sys.stderr)


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
    new = not jd.is_dir()
    jd.mkdir(parents=True, exist_ok=True)
    os.chmod(jd, 0o700)
    if new:
        _fsync_dir(jd.parent)                   # the journal directory's own entry must survive a power cut
    try:
        fd = os.open(_journal_file(e["id"]), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    rec = {"id": e["id"], "state": "claimed", "kind": e["kind"], "target": e["target"], "ts": _iso(now)}
    with os.fdopen(fd, "wb") as f:
        f.write(json.dumps(rec).encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())
    # The claim must survive a power cut before anything is delivered: fsync the directory entry too.
    _fsync_dir(jd)
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

def _sent_exists(dirs: "Dirs", eid: str) -> bool:
    try:
        os.stat(f"{eid}.json", dir_fd=dirs.sent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def write_sent(dirs: "Dirs", eid: str, ok: bool, via: str, detail: str, now: float) -> None:
    body = {"id": eid, "ok": ok, "via": via, "detail": _clip(detail), "done_at": _iso(now)}
    _write_atomic_at(dirs.sent, f"{eid}.json", (json.dumps(body, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


def _unlink(dirs: "Dirs", name: str) -> None:
    try:
        os.unlink(name, dir_fd=dirs.outbox)
    except OSError:
        pass                                    # gone, a directory, or not ours to remove: refused each pass


def folder_problem(folder: pathlib.Path) -> str:
    """Why the relay folder is unsafe to read from or write to, or "". Anyone with iCloud access may plant
    a link: `outbox` linked to the journal would let the cleanup of refused entries delete claims and
    reopen replays. So the folder, `outbox` and `sent` must be real directories (no link anywhere on the
    way from the folder down), owned by this user, and nowhere inside Teyla's own home."""
    try:
        real = pathlib.Path(os.path.realpath(folder))
        home = pathlib.Path(os.path.realpath(ctl.home()))
        if real == home or home in real.parents or real in home.parents:
            return f"{folder} overlaps Teyla's home {home}"
        for d in (folder, folder / "outbox", folder / "sent"):
            st = os.lstat(d)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
                return f"{d} is not a plain directory"
            if st.st_uid != os.getuid():
                return f"{d} is not owned by this user"
        for sub in ("outbox", "sent"):
            if pathlib.Path(os.path.realpath(folder / sub)) != real / sub:
                return f"{folder / sub} resolves somewhere else"
    except OSError as exc:
        return f"{folder}: {exc.strerror or exc}"
    return ""


class Dirs:
    """The relay folder, its outbox and sent/, each opened once without following a link and used only
    through these descriptors for the whole pass. folder_problem() checks paths; a link swapped in after
    that check (outbox -> the journal, say) changes nothing here, because no path is looked up again."""

    _FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def __init__(self, folder: pathlib.Path):
        self.folder = folder
        self.root = self.outbox = self.sent = -1

    def open(self) -> "Dirs":
        """Open and check all three; RelayError says why the folder is refused."""
        try:
            self.root = os.open(self.folder, self._FLAGS)
            self.outbox = os.open("outbox", self._FLAGS, dir_fd=self.root)
            self.sent = os.open("sent", self._FLAGS, dir_fd=self.root)
            ours = set()
            for d in (ctl.home(), journal_dir()):
                try:
                    st = os.stat(d)
                    ours.add((st.st_dev, st.st_ino))
                except OSError:
                    pass
            for name, fd in (("folder", self.root), ("outbox", self.outbox), ("sent", self.sent)):
                st = os.fstat(fd)
                if st.st_uid != os.getuid():
                    raise RelayError(f"{name} is not owned by this user")
                if (st.st_dev, st.st_ino) in ours:
                    raise RelayError(f"{name} is Teyla's own directory")
        except OSError as exc:
            self.close()
            raise RelayError(f"{self.folder}: {exc.strerror or exc}") from exc
        except RelayError:
            self.close()
            raise
        return self

    def __enter__(self) -> "Dirs":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for attr in ("sent", "outbox", "root"):
            fd = getattr(self, attr)
            if fd >= 0:
                os.close(fd)
                setattr(self, attr, -1)


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


def deliver_ask_action(kind: str, target: str, runner, base: list[str]) -> tuple[bool, str, str]:
    """The two commands the phone may run besides `say` and `dispatch`: `teyla asks accept-close <id> --json`
    and `teyla asks undo <id>`. Nothing else is built from an outbox entry's fields."""
    if not _ASK_ID.fullmatch(target):
        return False, "", "that id cannot be used"
    if kind == "close":
        code, out, err = runner([*base, "asks", "accept-close", target, "--json"], RUN_TIMEOUT_S[kind])
    else:
        code, out, err = runner([*base, "asks", "undo", target], RUN_TIMEOUT_S[kind])
    if code == 124:
        return False, "", "timed out; check the question on the Mac"
    if kind == "close":
        try:
            res = json.loads(out)
        except ValueError:
            res = None
        if isinstance(res, dict):
            closed = [c.get("id") for c in res.get("closed", []) if isinstance(c, dict)]
            if code == 0 and target in closed:
                return True, "asks", "closed"
            errors = [str(e) for e in res.get("errors", [])]
            return False, "", _clip(errors[0]) if errors else "it is not in the list Teyla suggests closing"
    elif code == 0:
        return True, "asks", "reopened"
    return False, "", _last_line(err) or _last_line(out) or f"exit {code}"


def deliver_activity(target: str, runner, base: list[str]) -> tuple[bool, str, str]:
    """`teyla growth log --kind <kind>`: one +1 from the phone. The kind comes from `ACTIVITY_KINDS`, never from free text."""
    if target not in ACTIVITY_KINDS:
        return False, "", "unknown activity kind"
    code, out, err = runner([*base, "growth", "log", "--kind", target], RUN_TIMEOUT_S["activity"])
    if code == 2 and ("invalid choice" in err or "unrecognized" in err):
        return False, "", "this Teyla cannot log activity yet"
    if code == 124:
        return False, "", "timed out; check the log on the Mac"
    if code == 0:
        return True, "growth", "logged"
    return False, "", _clip(_last_line(err) or _last_line(out) or f"exit {code}")


def activity_view(runner=None, base: list[str] | None = None) -> dict | None:
    """The activity graph for the phone, counts only: no notes, no products, no kinds per day. `total` is the year's. None when this Teyla
    has no `growth activity` or it fails, so the snapshot simply has no card."""
    runner = runner or run_command
    code, out, _err = runner([*(base or teyla_command()), "growth", "activity", "--json", "--weeks", str(ACTIVITY_WEEKS)], 30)
    if code != 0:
        return None
    try:
        raw = json.loads(out)
    except ValueError:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("days"), list):
        return None
    days = []
    for d in raw["days"]:
        if isinstance(d, dict) and isinstance(d.get("day"), str) and type(d.get("count")) is int:
            lvl = d.get("level")
            days.append({"day": d["day"], "count": d["count"], "level": lvl if type(lvl) is int else 0})
    if not days:
        return None
    try:
        last = _dt.date.fromisoformat(days[-1]["day"])
    except ValueError:
        return None
    # Whole ISO weeks: the Monday of the last day's week, minus 16 weeks. The grid then starts on a Monday.
    first = (last - _dt.timedelta(days=last.weekday(), weeks=ACTIVITY_WEEKS - 1)).isoformat()
    days = [d for d in days if d["day"] >= first]
    if not days:
        return None
    def num(k):
        v = raw.get(k)
        return v if type(v) is int else 0
    kinds = [k for k in raw.get("kinds", []) if k in ACTIVITY_KINDS] or list(ACTIVITY_KINDS)
    return {"today": raw.get("today") if isinstance(raw.get("today"), str) else days[-1]["day"],
            "start": days[0]["day"], "days": days, "today_count": num("today_count"), "week_count": num("week_count"),
            "total": raw["total"] if type(raw.get("total")) is int else sum(d["count"] for d in days), "streak": num("streak"), "longest": num("longest"), "kinds": kinds}


GTM_KINDS = ("approve", "send", "reply", "follow_up")
GTM_GOALS = 4
GTM_TARGETS = 6
GTM_COUNTERS = ("outcomes", "distribution", "preparation")


def gtm_view(runner=None, base: list[str] | None = None) -> dict | None:
    """The GTM Today card for the phone (docs/GTM.md): counts, the owner's own goal titles and targets, the ordered next
    actions as kinds and counts. Each goal also carries `done_when`, `weeks_left`, `short` and each target its `counter`, so the
    phone can draw the goal first. No source names, no links, no doctor lines. None when this Teyla has no `gtm` or it fails."""
    runner = runner or run_command
    code, out, _err = runner([*(base or teyla_command()), "gtm", "today", "--json"], 30)
    if code != 0:
        return None
    try:
        raw = json.loads(out)
    except ValueError:
        return None
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("day"), str):
        return None

    def n(v):
        return v if type(v) is int and v >= 0 else 0

    def total(k):
        v = raw.get(k)
        return n(v.get("total")) if isinstance(v, dict) else 0

    dist = raw.get("distribution") if isinstance(raw.get("distribution"), dict) else {}
    target = dist.get("target")
    goals = []
    for g in raw.get("goals") or []:
        if not isinstance(g, dict) or not isinstance(g.get("id"), str):
            continue
        rows = [{"stage": str(t["stage"])[:40], "count": n(t.get("count")), "target": n(t.get("target")),
                 "counter": t["counter"] if t.get("counter") in GTM_COUNTERS else "outcomes"}
                for t in g.get("targets") or [] if isinstance(t, dict) and isinstance(t.get("stage"), str)][:GTM_TARGETS]
        dl, wl, deadline = g.get("days_left"), g.get("weeks_left"), g.get("deadline")
        done_when = g.get("done_when")
        goals.append({"id": g["id"][:40], "title": str(g.get("title") or g["id"])[:80],
                      "done_when": done_when[:120] if isinstance(done_when, str) and done_when.strip() else None,
                      "deadline": deadline if isinstance(deadline, str) and len(deadline) == 10 else None,
                      "days_left": dl if type(dl) is int else None, "weeks_left": wl if type(wl) is int else None,
                      "short": n(g.get("short")), "targets": rows,
                      "drafts": n(g["drafts"].get("total")) if isinstance(g.get("drafts"), dict) else 0})
    nxt = [{"kind": a["kind"], "count": n(a.get("count"))} for a in raw.get("next") or []
           if isinstance(a, dict) and a.get("kind") in (*GTM_KINDS, "distribute")]
    return {"day": raw["day"], **{k: total(k) for k in GTM_KINDS},
            "distribution": {"today": n(dist.get("today")), "target": target if type(target) is int and target > 0 else None,
                             "week": n(dist.get("week"))},
            "outcomes_week": n((raw.get("outcomes") or {}).get("week")) if isinstance(raw.get("outcomes"), dict) else 0,
            "has_goals": raw.get("has_goals") is True, "goals": goals[:GTM_GOALS], "next": nxt,
            "untagged_drafts": n(raw.get("untagged_drafts"))}


def deliver_answer(item: asks.Ask, text: str, answer_fn) -> tuple[bool, str, str]:
    res = answer_fn(item, text, clipboard=False)
    return bool(res.get("ok")), str(res.get("via") or ""), str(res.get("detail") or "")


# --- one sync pass ----------------------------------------------------------------------------

class Pass:
    """What one pass works from: the folder, the key, the facts the phone's `about` is checked against."""

    def __init__(self, dirs, key, now, snap, items, answer_fn, runner, base):
        self.dirs, self.key, self.now = dirs, key, now
        self.answers = {r["id"]: r["question"] for r in snap.get("asks", []) if isinstance(r, dict) and "id" in r}
        self.running = {r["id"]: r.get("title", "") for r in snap.get("running", []) if isinstance(r, dict) and r.get("id")}
        self.products = {r["name"] for r in snap.get("products", []) if isinstance(r, dict) and "name" in r}
        self.rows = {r["id"]: r for r in snap.get("asks", []) if isinstance(r, dict) and "id" in r}
        self.items = {a.id: a for a in items}
        self.answer_fn, self.runner, self.base = answer_fn, runner, base


def recover(dirs: Dirs, now: float) -> list[dict]:
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
        write_sent(dirs, eid, False, "", detail, now)
        _unlink(dirs, f"{eid}.json")
        out.append({"id": eid, "ok": False, "detail": detail})
    return out


def _reject_unsigned(p: Pass, name: str, stem: str, reason: str) -> dict:
    """An entry that did not prove it came from the phone. The reason goes to sent/, unless that id has an
    outcome already: a forged copy of a real id must not overwrite the real result."""
    if _journal_read(stem) is None and not _sent_exists(p.dirs, stem):
        write_sent(p.dirs, stem, False, "", reason, p.now)
    _unlink(p.dirs, name)
    return {"id": stem, "ok": False, "detail": reason}


def _replay(p: Pass, e: dict, name: str) -> dict:
    """A signed entry whose id the journal knows: never delivered again. The real result is put back in
    sent/ if the phone has already cleared it; nothing existing is overwritten."""
    rec = _journal_read(e["id"]) or {}
    res = rec.get("result") if isinstance(rec.get("result"), dict) else None
    if not _sent_exists(p.dirs, e["id"]):
        if res and rec.get("state") in ("done", "rejected", "interrupted"):
            write_sent(p.dirs, e["id"], bool(res.get("ok")), str(res.get("via") or ""), str(res.get("detail") or ""), p.now)
        else:
            write_sent(p.dirs, e["id"], False, "", "already handled", p.now)
    _unlink(p.dirs, name)
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
    elif kind == "close":
        seen = p.answers.get(target)
        if seen is None or target not in p.items:
            return no("that question is no longer open")
        if ((p.rows.get(target) or {}).get("triage") or {}).get("bucket") != "close":
            return no("Teyla no longer suggests closing that question")
    elif kind == "reopen":
        seen = target
    elif kind == "activity":
        if target not in ACTIVITY_KINDS:
            return no("unknown activity kind")
        if e["text"] != "+1":
            return no("malformed entry: text")
        seen = target
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
        elif kind in ("close", "reopen"):
            ok, via, detail = deliver_ask_action(kind, target, p.runner, p.base)
        elif kind == "activity":
            ok, via, detail = deliver_activity(target, p.runner, p.base)
        else:
            ok, via, detail = deliver_subcommand(kind, target, e["text"], p.runner, p.base)
    except Exception as exc:  # noqa: BLE001 — whatever went wrong, the entry has been claimed: report, never retry
        return False, "", f"delivery failed ({type(exc).__name__}); check the session, then send again", "done"
    return ok, via, detail, "done"


def process_one(p: Pass, name: str, stem: str) -> dict | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=p.dirs.outbox)
    except OSError:
        return _reject_unsigned(p, name, stem, "malformed entry: not a readable file")
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):            # checked before fdopen, which refuses a directory
        os.close(fd)
        return _reject_unsigned(p, name, stem, "malformed entry: not a regular file")
    with os.fdopen(fd, "rb") as f:
        if st.st_size > MAX_FILE:
            return _reject_unsigned(p, name, stem, "file is larger than 64 KB")
        raw = f.read(MAX_FILE + 1)
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        if p.now - st.st_mtime < YOUNG_FILE_S:
            return None                         # may still be arriving from iCloud: look again next pass
        return _reject_unsigned(p, name, stem, "malformed entry: not JSON")
    why = entry_shape(obj)
    if not why and obj["id"] != stem:
        why = "malformed entry: id does not match the file name"
    if why:
        return _reject_unsigned(p, name, stem, why)
    if not signature_ok(p.key, obj):
        return _reject_unsigned(p, name, stem, "bad signature")
    if not _claim(obj, p.now):
        return _replay(p, obj, name)
    ok, via, detail, state = _decide(p, obj)
    result = {"ok": ok, "via": via, "detail": _clip(detail)}
    _journal_set(obj["id"].lower(), state, p.now, result)
    write_sent(p.dirs, obj["id"], ok, via, detail, p.now)
    _unlink(p.dirs, name)
    return {"id": obj["id"], "kind": obj["kind"], **result}


def process_outbox(p: Pass) -> list[dict]:
    try:
        names = sorted(os.listdir(p.dirs.outbox))
    except OSError:
        return []
    out = []
    for name in names:
        if not _FILE_RE.fullmatch(name):        # iCloud placeholders (.name.json.icloud), temp files, strays
            continue
        res = process_one(p, name, name[:-len(".json")])
        if res is not None:
            out.append(res)
    return out


def _pull_taste(dirs: Dirs, key: bytes, now: float) -> list[dict]:
    """The Share extension's taste drops (`taste_wire.py`). One bad drop never stops the pass."""
    from . import taste_wire
    try:
        return taste_wire.pull(dirs, key, now)
    except Exception as exc:  # noqa: BLE001
        return [{"id": "taste", "kind": "taste", "ok": False, "detail": f"taste drops: {_clip(str(exc), 120)}"}]


def github_view(today: str, now: float, source=None) -> dict | None:
    """GitHub's contribution calendar for the phone's widget (docs/PRIVACY.md row 59), the last ACTIVITY_WEEKS weeks: counts and
    levels per day, nothing else. Served from the 10-minute cache in `~/.teyla/github-activity.json`; None when there is none."""
    try:
        g = (source or github_activity.activity)(today, ACTIVITY_WEEKS, now)
    except Exception:  # noqa: BLE001
        return None
    if not g or not g.get("days"):
        return None
    return {"start": g["start"], "days": [{"day": d["day"], "count": d["count"], "level": d["level"]} for d in g["days"]],
            "today_count": g["today_count"], "week_count": g["week_count"], "total": g["total"],
            "streak": g["streak"], "longest": g["longest"], "at": g.get("at", 0)}


def default_source(now: float):
    items = asks.collect(asks.DEFAULT_DAYS, now)
    snap = snapshot.build(now, items=items)
    act = activity_view()                       # additive: an older `teyla` has no `growth activity`, and the card is hidden
    if act is not None:
        gh = github_view(act["today"], now)     # additive: the widget's second grid; absent without `gh` or a cache
        if gh is not None:
            act["github"] = gh
        snap["activity"] = act
    gtm = gtm_view()                            # additive: an older `teyla` has no `gtm`, and the Today card is hidden
    if gtm is not None:
        snap["gtm"] = gtm
    return snap, items


def write_snapshot(dirs: Dirs, key: bytes, snap: dict) -> None:
    _write_atomic_at(dirs.root, "state.teyla", state_file(key, state_bytes(snap)))


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
        why = folder_problem(folder)
        if why:
            return {"skipped": f"unsafe relay folder: {why}"}
        source = source or default_source
        try:
            dirs = Dirs(folder).open()
        except RelayError as exc:
            return {"skipped": f"unsafe relay folder: {exc}"}
        with dirs:
            recovered = recover(dirs, now)
            snap, items = source(now)
            write_snapshot(dirs, key, snap)
            p = Pass(dirs, key, now, snap, items, answer_fn or answer_mod.answer, runner or run_command,
                     base or teyla_command())
            processed = process_outbox(p)
            processed += _pull_taste(dirs, key, now)
            if processed or recovered:
                snap, _ = source(now)          # what was just answered is no longer waiting
                write_snapshot(dirs, key, snap)
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
                print(PAIR_TEXT, file=sys.stderr)
            return 0
        if act == "connect":
            _print_connect(relay_connect(), args.json)
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
    q = sp.add_parser("relay", help="the iPhone relay: connect, on, off, status, pair, sync")
    q.set_defaults(fn=cmd_relay)
    q.add_argument("action", choices=["connect", "on", "off", "status", "pair", "sync"])
    q.add_argument("--json", action="store_true", help="connect, status, pair: print JSON")
    q.add_argument("--rotate", action="store_true", help="pair: replace the key (the phone must pair again)")
    q.add_argument("--quiet", action="store_true", help="sync: print only what was delivered or refused")
    return q

"""Safe writes for `teyla start`: every change Teyla makes to another tool's settings, with a way back.

Teyla never edited `~/.claude/settings.json` before `teyla start`. So each write here follows the same
rules, and `teyla undo` depends on all of them:

  - A JSON file is edited as data: key order and the file's own indent survive. A file that does not
    parse is refused, never overwritten.
  - Before the first byte is written the file is copied to `<file>.teyla-bak-<UTC>` (mode 0600).
  - The write is atomic (a temp file in the same directory, then a rename) and runs under a lock.
  - The change is appended to `~/.teyla/changes.jsonl` (mode 0600):
        {id, offer, file, key_path, old, new, at, sha256_after}
    `old` is the value that was there, or the string "<absent>" (`old_present` tells a key holding that
    string from a missing key). `sha256_before` and `backup` let an untouched file go back byte for byte.
  - `revert` changes only the key Teyla wrote. If the key no longer holds Teyla's value it stops and shows
    both values; `force` reverts anyway. It never restores the whole file over later edits. The one
    exception is a file whose hash still equals `sha256_after`: nothing else changed, so the pre-apply bytes
    come back exactly (the backup, or no file at all when there was none).

Four kinds of change share the log: `json` (a key path in a JSON file), `toml` (one top-level key in a
TOML file, edited as text so comments and other keys stay), `file` (a new file Teyla creates only when
absent), and `command` (an existing sync such as `teyla harness sync`, run as it is and logged with the
command and the time). A command is not wrapped, snapshotted or undone here; its own uninstall reverses it.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import tempfile
import time

ABSENT = "<absent>"
FILE_NEW = "<new file>"


class ChangeError(Exception):
    """A refusal: the message says what stopped it and what to do."""


# --- the log ---------------------------------------------------------------------------------

def teyla_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TEYLA_HOME") or (pathlib.Path.home() / ".teyla")).expanduser()


def log_path() -> pathlib.Path:
    return teyla_home() / "changes.jsonl"


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _stamp(now: _dt.datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@contextlib.contextmanager
def _locked(timeout_s: float = 10.0):
    """One writer at a time: an exclusive flock on ~/.teyla/changes.lock."""
    from . import config
    d = teyla_home()
    config.private_dir(d)
    fd = os.open(d / "changes.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise ChangeError("another `teyla` is writing changes right now; try again in a moment")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)  # closing the descriptor drops the lock


def _append(rec: dict) -> None:
    p = log_path()
    new = not p.exists()
    with open(p, "a") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if new:
        os.chmod(p, 0o600)


def load_log() -> list[dict]:
    try:
        lines = log_path().read_text().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if isinstance(o, dict):
            out.append(o)
    return out


def changes() -> list[dict]:
    """Every change in the order made, each with `undone` (the time it was undone, or None)."""
    log = load_log()
    undone = {o["undo_of"]: o.get("at") for o in log if "undo_of" in o}
    return [dict(o, undone=undone.get(o.get("id"))) for o in log if "undo_of" not in o]


def resolve(ref: str) -> list[dict]:
    """The active changes a change id or an offer id names, newest first. A change id is exact;
    an offer id ("O1", any case) names every change of that offer not yet undone."""
    rows = changes()
    exact = [c for c in rows if c["id"] == ref]
    if exact:
        return exact
    return [c for c in reversed(rows) if str(c.get("offer", "")).lower() == ref.lower() and not c["undone"]]


# --- writing a file safely -------------------------------------------------------------------

def _real(path: pathlib.Path) -> pathlib.Path:
    """Where a write goes: a symlinked settings file (dotfiles) is edited at its target, not replaced."""
    return pathlib.Path(os.path.realpath(path))


def _atomic_write(path: pathlib.Path, data: bytes, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o777
        except OSError:
            mode = 0o600
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".teyla-tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _backup(path: pathlib.Path, data: bytes, now: _dt.datetime) -> pathlib.Path:
    bak, n = path.with_name(f"{path.name}.teyla-bak-{_stamp(now)}"), 1
    while bak.exists():                      # never overwrite an earlier backup
        n += 1
        bak = path.with_name(f"{path.name}.teyla-bak-{_stamp(now)}-{n}")
    fd = os.open(bak, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(bak, 0o600)
    return bak


# --- JSON ------------------------------------------------------------------------------------

def _indent_of(text: str):
    """The indent a JSON file already uses: a tab, else the width of its first indented line, else 2."""
    m = re.search(r"\n([ \t]+)\S", text)
    if not m:
        return 2
    lead = m.group(1)
    return "\t" if lead.startswith("\t") else len(lead)


def _parse_json(path: pathlib.Path, raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise ChangeError(f"{path} is not valid JSON ({e}); Teyla will not edit it. Fix the file, then run this again.")
    if not isinstance(data, dict):
        raise ChangeError(f"{path} holds JSON, but not an object; Teyla will not edit it.")
    return data


def _dump_json(data: dict, like: str) -> bytes:
    text = json.dumps(data, indent=_indent_of(like), ensure_ascii=False)
    return (text + ("\n" if (like.endswith("\n") or not like) else "")).encode("utf-8")


def get_path(data, key_path):
    """(present, value) at key_path inside nested dicts."""
    cur = data
    for k in key_path:
        if not isinstance(cur, dict) or k not in cur:
            return False, None
        cur = cur[k]
    return True, cur


def _set_path(data: dict, key_path, value) -> int:
    """Set the value; returns how many levels of dicts it had to create."""
    cur, created = data, 0
    for k in key_path[:-1]:
        if k not in cur:
            cur[k] = {}
            created += 1
        elif not isinstance(cur[k], dict):
            raise ChangeError(f"{'.'.join(key_path[:-1])} is not an object in this file; Teyla will not replace it.")
        cur = cur[k]
    cur[key_path[-1]] = value
    return created


def _del_path(data: dict, key_path, prune: int) -> None:
    parents = [data]
    for k in key_path[:-1]:
        parents.append(parents[-1][k])
    parents[-1].pop(key_path[-1], None)
    for depth in range(len(key_path) - 1, len(key_path) - 1 - prune, -1):  # empty parents Teyla made
        if depth >= 1 and not parents[depth]:
            parents[depth - 1].pop(key_path[depth - 1], None)


# --- TOML (one top-level scalar, edited as text) ---------------------------------------------

def _toml_key_re(key: str) -> "re.Pattern":
    return re.compile(rf'^(?P<lead>[ \t]*){re.escape(key)}(?P<eq>[ \t]*=[ \t]*)(?P<val>"[^"\n]*"|\'[^\'\n]*\'|[^#\n]*?)(?P<tail>[ \t]*(?:#[^\n]*)?)$', re.M)


def _toml_top_end(text: str) -> int:
    """Offset of the first [table] header: top-level keys live before it."""
    m = re.search(r"^[ \t]*\[", text, re.M)
    return m.start() if m else len(text)


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return json.dumps(str(v), ensure_ascii=False)


def toml_get(text: str, key: str):
    """(present, value) of a top-level key."""
    import tomllib
    try:
        d = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return False, None
    return (key in d), d.get(key)


def toml_set(text: str, key: str, value) -> str:
    top = _toml_top_end(text)
    head, rest = text[:top], text[top:]
    rx = _toml_key_re(key)
    if rx.search(head):
        head = rx.sub(lambda m: f"{m['lead']}{key}{m['eq']}{_toml_value(value)}{m['tail']}", head, count=1)
    else:
        sep = "" if (not head or head.endswith("\n")) else "\n"
        head = f"{head}{sep}{key} = {_toml_value(value)}\n" + ("\n" if rest and not head.endswith("\n\n") else "")
    return head + rest


def toml_del(text: str, key: str) -> str:
    top = _toml_top_end(text)
    head, rest = text[:top], text[top:]
    head = re.sub(rf"^[ \t]*{re.escape(key)}[ \t]*=[^\n]*\n?", "", head, count=1, flags=re.M)
    return head + rest


def _parse_toml(path: pathlib.Path, raw: bytes) -> str:
    import tomllib
    try:
        text = raw.decode("utf-8")
        tomllib.loads(text)
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ChangeError(f"{path} is not valid TOML ({e}); Teyla will not edit it. Fix the file, then run this again.")
    return text


# --- apply -----------------------------------------------------------------------------------

def _record(offer: str, kind: str, path: pathlib.Path, key_path, old, old_present: bool, new, now, *,
            sha_before, sha_after, backup, existed, levels=0, **extra) -> dict:
    taken = {o.get("id") for o in load_log()}
    cid, n = f"{offer}-{_stamp(now)}", 1
    while cid in taken:                      # two changes of one offer within a second
        n += 1
        cid = f"{offer}-{_stamp(now)}-{n}"
    rec = dict(id=cid, offer=offer, kind=kind, file=str(path), key_path=list(key_path),
               old=old if old_present else ABSENT, old_present=old_present, new=new, at=now.isoformat(timespec="seconds"),
               sha256_after=sha_after, sha256_before=sha_before, backup=str(backup) if backup else None,
               file_existed=existed, created_levels=levels)
    rec.update(extra)
    return rec


def apply_json(offer: str, path: pathlib.Path, key_path: list[str], new, now: _dt.datetime | None = None) -> dict:
    """Set `key_path` to `new` in a JSON file. Returns the change record (also appended to the log)."""
    now = now or _now()
    real = _real(path)
    with _locked():
        existed = real.exists()
        raw = real.read_bytes() if existed else b""
        data = _parse_json(path, raw) if existed and raw.strip() else {}
        had, old = get_path(data, key_path)
        if had and old == new:
            raise ChangeError(f"{'.'.join(key_path)} is already {json.dumps(new)} in {path}; nothing to change.")
        like = raw.decode("utf-8") if existed else ""
        created = _set_path(data, key_path, new)
        out = _dump_json(data, like)
        backup = _backup(real, raw, now) if existed else None
        _atomic_write(real, out)
        rec = _record(offer, "json", path, key_path, old, had, new, now, sha_before=_sha(raw) if existed else None,
                      sha_after=_sha(out), backup=backup, existed=existed, levels=created)
        _append(rec)
    return rec


def apply_toml(offer: str, path: pathlib.Path, key: str, new, now: _dt.datetime | None = None) -> dict:
    """Set one top-level key of a TOML file by editing its text in place (other keys, comments and
    tables stay byte for byte)."""
    now = now or _now()
    real = _real(path)
    with _locked():
        existed = real.exists()
        raw = real.read_bytes() if existed else b""
        text = _parse_toml(path, raw) if existed else ""
        had, old = toml_get(text, key)
        if had and old == new:
            raise ChangeError(f"{key} is already {_toml_value(new)} in {path}; nothing to change.")
        out_text = toml_set(text, key, new)
        _parse_toml(path, out_text.encode("utf-8"))  # never write a file that stops parsing
        out = out_text.encode("utf-8")
        backup = _backup(real, raw, now) if existed else None
        _atomic_write(real, out)
        rec = _record(offer, "toml", path, [key], old, had, new, now, sha_before=_sha(raw) if existed else None,
                      sha_after=_sha(out), backup=backup, existed=existed)
        _append(rec)
    return rec


def apply_file(offer: str, path: pathlib.Path, content: str, now: _dt.datetime | None = None) -> dict:
    """Create a file Teyla owns. Refuses when something is already there."""
    now = now or _now()
    with _locked():
        if path.exists() or path.is_symlink():
            raise ChangeError(f"{path} already exists; Teyla does not overwrite it.")
        out = content.encode("utf-8")
        _atomic_write(path, out, 0o644)
        rec = _record(offer, "file", path, [], None, False, FILE_NEW, now, sha_before=None, sha_after=_sha(out),
                      backup=None, existed=False)
        _append(rec)
    return rec


# --- a command: an existing sync the offer runs as it is ---------------------------------------

def apply_command(offer: str, command: str, run, undo: str = "", now: _dt.datetime | None = None) -> tuple[dict, list[str]]:
    """Run `run()` (an existing command such as `teyla harness sync`, which returns its output lines) exactly
    as the command does today and log that it ran: the offer, the command and the time. Nothing is
    snapshotted or hashed, and `revert` does not undo it: the command's own uninstall does."""
    now = now or _now()
    lines = run()
    with _locked():
        rec = _record(offer, "command", pathlib.Path("(command)"), [], None, False, command, now,
                      sha_before=None, sha_after=None, backup=None, existed=True, command=command, undo=undo)
        _append(rec)
    return rec, list(lines or [])


# --- undo ------------------------------------------------------------------------------------

def _current_json(rec: dict):
    path = pathlib.Path(rec["file"])
    real = _real(path)
    if not real.exists():
        return None, None, b"", False
    raw = real.read_bytes()
    data = _parse_json(path, raw)
    return data, real, raw, True


def _mismatch(rec: dict, have, cur) -> str:
    where = ".".join(rec["key_path"]) or rec["file"]
    return (f"not reverting {where} in {rec['file']}: it is {json.dumps(cur) if have else ABSENT} now, "
            f"but Teyla wrote {json.dumps(rec['new'])}. Someone changed it after Teyla did. "
            f"`teyla undo {rec['id']} --force` reverts it anyway.")


def _restore_exact(rec: dict, real: pathlib.Path) -> bool:
    """The file is still exactly what Teyla wrote: put the pre-apply bytes back. False if it cannot be
    proven they are the right bytes (the key-level revert then runs)."""
    if not rec.get("file_existed"):
        real.unlink()
        return True
    bak = pathlib.Path(rec.get("backup") or "")
    try:
        raw = bak.read_bytes()
    except OSError:
        return False
    if _sha(raw) != rec.get("sha256_before"):
        return False
    _atomic_write(real, raw)
    return True


def revert(rec: dict, force: bool = False, now: _dt.datetime | None = None) -> list[str]:
    """Undo one change. Returns the lines to show. Raises ChangeError when it refuses."""
    now = now or _now()
    kind = rec.get("kind", "json")
    with _locked():
        if rec["id"] in {o.get("undo_of") for o in load_log()}:
            raise ChangeError(f"{rec['id']} was already undone.")
        if kind == "command":
            raise ChangeError(f"{rec['offer']}: Teyla's sync owns these files; its uninstall removes them. "
                              f"{rec.get('undo') or 'Run `teyla uninstall --dry` to see what it removes.'}")
        if kind == "file":
            lines = _revert_file(rec, force)
        elif kind == "toml":
            lines = _revert_toml(rec, force)
        else:
            lines = _revert_json(rec, force)
        _append(dict(undo_of=rec["id"], offer=rec.get("offer"), at=now.isoformat(timespec="seconds"), forced=bool(force)))
    return lines


def _revert_json(rec: dict, force: bool) -> list[str]:
    path = pathlib.Path(rec["file"])
    data, real, raw, exists = _current_json(rec)
    if not exists:
        return [f"{path} is gone; nothing to revert."]
    have, cur = get_path(data, rec["key_path"])
    where = ".".join(rec["key_path"])
    if not have or cur != rec["new"]:
        if not force:
            raise ChangeError(_mismatch(rec, have, cur))
        if not have and not rec.get("old_present"):
            return [f"{where} is already absent in {path}; nothing to revert."]
    if have and cur == rec["new"] and _sha(raw) == rec.get("sha256_after") and _restore_exact(rec, real):
        return [f"restored {path} exactly as it was before {rec['offer']}" if rec.get("file_existed")
                else f"removed {path} (Teyla created it)"]
    if rec.get("old_present"):
        _set_path(data, rec["key_path"], rec["old"])
    else:
        _del_path(data, rec["key_path"], rec.get("created_levels", 0))
    _atomic_write(real, _dump_json(data, raw.decode("utf-8")))
    return [f"{where} in {path}: back to {json.dumps(rec['old']) if rec.get('old_present') else 'absent'}; "
            f"everything else in the file is as it is now"]


def _revert_toml(rec: dict, force: bool) -> list[str]:
    path = pathlib.Path(rec["file"])
    real = _real(path)
    key = rec["key_path"][0]
    if not real.exists():
        return [f"{path} is gone; nothing to revert."]
    raw = real.read_bytes()
    text = _parse_toml(path, raw)
    have, cur = toml_get(text, key)
    if not have or cur != rec["new"]:
        if not force:
            raise ChangeError(_mismatch(rec, have, cur))
        if not have and not rec.get("old_present"):
            return [f"{key} is already absent in {path}; nothing to revert."]
    if have and cur == rec["new"] and _sha(raw) == rec.get("sha256_after") and _restore_exact(rec, real):
        return [f"restored {path} exactly as it was before {rec['offer']}" if rec.get("file_existed")
                else f"removed {path} (Teyla created it)"]
    out = toml_set(text, key, rec["old"]) if rec.get("old_present") else toml_del(text, key)
    _parse_toml(path, out.encode("utf-8"))
    _atomic_write(real, out.encode("utf-8"))
    return [f"{key} in {path}: back to {_toml_value(rec['old']) if rec.get('old_present') else 'absent'}; "
            f"the rest of the file is as it is now"]


def _revert_file(rec: dict, force: bool) -> list[str]:
    path = pathlib.Path(rec["file"])
    if not path.exists():
        return [f"{path} is gone; nothing to revert."]
    if _sha(path.read_bytes()) != rec.get("sha256_after") and not force:
        raise ChangeError(f"not removing {path}: it was edited after Teyla created it. "
                          f"`teyla undo {rec['id']} --force` removes it anyway.")
    path.unlink()
    return [f"removed {path} (Teyla created it)"]

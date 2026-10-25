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

Three kinds of change share the log: `json` (a key path in a JSON file), `toml` (one top-level key in a
TOML file, edited as text so comments and other keys stay), `file` (a new file Teyla creates only when
absent), and `piece` (the files an existing sync wrote). A piece is logged file by file: each file it created
or changed with its hashes before and after, a copy of every file it overwrote, the directories it created and
each hook handler it added. Its undo removes or restores a file only while the file still has the hash the apply
left, takes back only the recorded hook handlers from a file edited since, removes a directory only when it is
empty, and names everything it leaves in place.
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


# --- a piece: files written by an existing sync ----------------------------------------------------

SNAP_MAX = 2_000_000          # a file larger than this is compared by size and mtime, not read
# What each sync may write, relative to HOME. `files` are exact paths (plus their `<name>.*` siblings,
# where a sync leaves a copy); `trees` are directories walked to a depth (None: all the way down, 1: the
# files directly inside). A piece's undo can only touch what this lists, so it names every path.
_WATCH = {
    "policy": dict(files=[".agents/POLICY.md", ".claude/CLAUDE.md", ".codex/AGENTS.md", ".grok/AGENTS.md",
                          ".hermes/SOUL.md", ".cursor/skills/teyla-policy/SKILL.md"],
                   trees=[(".agents", 1)]),
    "hooks": dict(files=[".cursor/hooks.json", ".codex/hooks.json", ".grok/hooks/teyla.json", ".hermes/config.yaml"],
                  trees=[(".cursor/skills", None), (".codex/skills", None), (".grok/skills", None),
                         (".hermes/skills/teyla", None), (".teyla/hooks", None)]),
    "routine": dict(files=[], trees=[(".teyla", 1), ("Library/LaunchAgents", 1)]),
}


def _snap_one(p: pathlib.Path):
    """('link', target) | ('file', sha, bytes or None) | None for a path that is absent or not a file."""
    import stat as _stat
    try:
        st = os.lstat(p)
    except OSError:
        return None
    if _stat.S_ISLNK(st.st_mode):
        return ("link", os.readlink(p))
    if not _stat.S_ISREG(st.st_mode):
        return None
    if st.st_size > SNAP_MAX:
        return ("file", f"big:{st.st_size}:{st.st_mtime_ns}", None)
    try:
        data = p.read_bytes()
    except OSError:
        return None
    return ("file", _sha(data), data)


def _snapshot(piece: str, home: pathlib.Path) -> tuple[dict, set]:
    """(path -> snapshot of every file the piece's sync may write, the set of directories that exist
    on the way to them)."""
    spec = _WATCH[piece]
    paths: set = set()
    dirs: set = set()
    roots: list = []
    for rel in spec["files"]:
        f = home / rel
        paths.add(f)
        roots.append(f.parent)
        if f.parent.is_dir():
            paths.update(x for x in f.parent.glob(f.name + ".*"))
    for rel, depth in spec["trees"]:
        root = home / rel
        roots.append(root)
        if not root.is_dir() or root.is_symlink():
            continue
        for dp, dn, fn in os.walk(root, followlinks=False):
            dpp = pathlib.Path(dp)
            level = len(dpp.relative_to(root).parts)
            dirs.add(str(dpp))
            for name in fn:
                paths.add(dpp / name)
            for name in list(dn):
                if (dpp / name).is_symlink():
                    paths.add(dpp / name)
                    dn.remove(name)
            if depth is not None and level + 1 >= depth:
                dn[:] = []
    for r in roots:
        for anc in [r, *r.parents]:
            if anc == home or home not in anc.parents:
                break
            if anc.is_dir() and not anc.is_symlink():
                dirs.add(str(anc))
    snap = {}
    for f in paths:
        e = _snap_one(f)
        if e is not None:
            snap[str(f)] = e
    return snap, dirs


def _hook_handlers(raw: bytes | None) -> list:
    """[(event, handler dict)] of a hooks.json in either shape: Cursor's entries are the handlers,
    Codex's and Grok's hold them in a group's `hooks` list."""
    if not raw:
        return []
    try:
        d = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return []
    out = []
    hooks = d.get("hooks") if isinstance(d, dict) else None
    for event, items in (hooks.items() if isinstance(hooks, dict) else []):
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and isinstance(it.get("hooks"), list):
                out += [(event, h) for h in it["hooks"] if isinstance(h, dict)]
            elif isinstance(it, dict):
                out.append((event, it))
    return out


def _added_handlers(before: bytes | None, after: bytes | None) -> list:
    """The hook handlers present after a sync that were not there before, one row per addition."""
    from collections import Counter
    key = lambda eh: (eh[0], json.dumps(eh[1], sort_keys=True))
    have = Counter(key(x) for x in _hook_handlers(before))
    out = []
    for x in _hook_handlers(after):
        k = key(x)
        if have[k] > 0:
            have[k] -= 1
        else:
            out.append(x)
    return out


def apply_piece(offer: str, piece: str, run, home: pathlib.Path | None = None,
                now: _dt.datetime | None = None) -> tuple[dict, list[str]]:
    """Run `run()` (an existing sync that returns its output lines) and log what it did to the files
    in `_WATCH[piece]`: each file it created or changed, with its hashes before and after, and a copy
    of every file it overwrote (`<file>.teyla-bak-<UTC>`, mode 0600). Also logged: the directories it
    created and each hook handler it added. `undo` works from that list and nothing else.
    Returns (record, the sync's lines)."""
    from . import uninstall
    now = now or _now()
    home = home or pathlib.Path.home()
    with _locked():
        steps_before = {(s.verb, s.target) for s in uninstall.piece_steps(piece, home) if s.fn}
        snap_before, dirs_before = _snapshot(piece, home)
        lines = run()
        snap_after, dirs_after = _snapshot(piece, home)
        created = [[v, t] for v, t in ((s.verb, s.target) for s in uninstall.piece_steps(piece, home) if s.fn)
                   if (v, t) not in steps_before]
        files, hooks = [], []
        for path in sorted(snap_after):
            a, b = snap_after[path], snap_before.get(path)
            if b is not None and b[:2] == a[:2]:
                continue
            f = dict(path=path, op="modified" if b is not None else "created", kind=a[0],
                     sha_after=a[1] if a[0] == "file" else None, link_after=a[1] if a[0] == "link" else None,
                     before_kind=b[0] if b else None, sha_before=b[1] if b and b[0] == "file" else None,
                     link_before=b[1] if b and b[0] == "link" else None, backup=None)
            if b is not None and b[0] == "file" and b[2] is not None:
                f["backup"] = str(_backup(pathlib.Path(path), b[2], now))
            files.append(f)
            if path.endswith("hooks.json") or path.endswith("hooks/teyla.json"):
                for event, h in _added_handlers(b[2] if b and b[0] == "file" else None,
                                                a[2] if a[0] == "file" else None):
                    hooks.append(dict(file=path, event=event, handler=h))
        new_dirs = sorted(dirs_after - dirs_before, key=len, reverse=True)
        rec = _record(offer, "piece", pathlib.Path(f"({piece})"), [], None, False, piece, now, sha_before=None,
                      sha_after=None, backup=None, existed=True, piece=piece, created=created,
                      files=files, dirs=new_dirs, hook_entries=hooks, home=str(home))
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
        if kind == "piece":
            lines = _revert_piece(rec)
        elif kind == "file":
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


def _same(cur, want_kind: str, sha, link) -> bool:
    if cur is None:
        return False
    return cur[0] == "link" and want_kind == "link" and cur[1] == link or \
        cur[0] == "file" and want_kind == "file" and cur[1] == sha


def _drop_handlers(raw: bytes, rows: list) -> bytes | None:
    """`raw` (a hooks.json) without the handlers in `rows`; every other handler, group and key stays.
    None when none of them is there any more."""
    d = json.loads(raw.decode("utf-8"))
    hooks = d.get("hooks") if isinstance(d, dict) else None
    if not isinstance(hooks, dict):
        return None
    removed = 0
    for row in rows:
        items = hooks.get(row["event"])
        if not isinstance(items, list):
            continue
        for it in list(items):
            if isinstance(it, dict) and isinstance(it.get("hooks"), list):
                if row["handler"] in it["hooks"]:
                    it["hooks"].remove(row["handler"])
                    removed += 1
                    if not it["hooks"]:
                        items.remove(it)
                    break
            elif it == row["handler"]:
                items.remove(it)
                removed += 1
                break
        if not items:
            hooks.pop(row["event"], None)
    return _dump_json(d, raw.decode("utf-8")) if removed else None


def _revert_piece(rec: dict) -> list[str]:
    """Undo a piece from its ledger. A file is removed or restored only while it is still exactly what
    the apply left (its hash is `sha_after`); a directory goes only when it is empty afterwards.
    Anything the user changed since stays where it is and is named in the output."""
    from . import uninstall
    home = pathlib.Path(rec.get("home") or pathlib.Path.home())
    files = rec.get("files") or []
    lines, left = [], []
    if not files and not rec.get("dirs"):
        return [f"{rec['offer']} created nothing on this machine (it was already in place); nothing to remove."]
    made = {(v, t) for v, t in rec.get("created") or []}
    by_path = {f["path"]: f for f in files}
    steps = [s for s in uninstall.piece_steps(rec["piece"], home) if s.fn is not None and (s.verb, s.target) in made]
    ran_step: set = set()

    def run_step(s) -> bool:
        try:
            res = s.fn()
        except Exception as e:  # noqa: BLE001
            res = (1, f"{type(e).__name__}: {e}")
        if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], int) and res[0] != 0:
            left.append(f"{s.verb} {s.target}: {str(res[1]).strip()[-200:]}")
            return False
        ran_step.add(s.target)
        lines.append(f"{s.verb} {s.target}")
        return True

    if rec["piece"] == "routine":     # launchd jobs are unloaded before their files go, and only untouched ones
        for s in steps:
            f = by_path.get(str(s.target))
            if f and not _same(_snap_one(pathlib.Path(f["path"])), f["kind"], f["sha_after"], f["link_after"]):
                left.append(f"{s.target}: it changed after Teyla wrote it; not unloaded")
                continue
            run_step(s)
    for f in reversed(files):
        p = pathlib.Path(f["path"])
        cur = _snap_one(p)
        if cur is None:
            continue
        if _same(cur, f["kind"], f["sha_after"], f["link_after"]):
            if f["op"] == "created":
                p.unlink()
                lines.append(f"removed {p}")
            elif f.get("before_kind") == "link":
                p.unlink()
                os.symlink(f["link_before"], p)
                lines.append(f"restored the link {p}")
            else:
                try:
                    raw = pathlib.Path(f["backup"] or "").read_bytes()
                except OSError:
                    raw = None
                if raw is None or _sha(raw) != f["sha_before"]:
                    left.append(f"{p}: the copy Teyla made of it is missing or changed ({f['backup']}); left as it is")
                    continue
                if p.is_symlink():
                    p.unlink()
                _atomic_write(p, raw)
                lines.append(f"restored {p} exactly as it was before {rec['offer']}")
            continue
        # The file changed after the apply. Take back only what the apply added, if that can be told.
        mine = [h for h in rec.get("hook_entries") or [] if h["file"] == f["path"]]
        if mine and cur[0] == "file" and cur[2] is not None:
            try:
                out = _drop_handlers(cur[2], mine)
            except (ValueError, UnicodeDecodeError):
                out = None
            if out is not None:
                _atomic_write(p, out)
                lines.append(f"removed {len(mine)} hook handler(s) Teyla added from {p}; your other entries stay")
                continue
        step = next((s for s in steps if str(s.target) == f["path"] and s.target not in ran_step), None)
        if f["op"] == "modified" and step is not None and run_step(step):
            continue
        if f["op"] == "created":
            left.append(f"{p}: it changed after Teyla created it; left in place")
        else:
            left.append(f"{p}: it changed after Teyla changed it; left in place"
                        + (f" (the copy from before is {f['backup']})" if f.get("backup") else ""))
    for step in steps:                 # steps the file list did not cover (a launchd job with no file change)
        if step.target not in ran_step and str(step.target) not in by_path and rec["piece"] == "routine":
            run_step(step)
    for d in rec.get("dirs") or []:    # deepest first, and only while empty
        dp = pathlib.Path(d)
        if dp.is_symlink() or not dp.is_dir():
            continue
        try:
            dp.rmdir()
            lines.append(f"removed the empty directory {dp}")
        except OSError:
            left.append(f"{dp}: not empty; left in place")
    if left:
        lines.append("Left in place (not removed, because it is not what Teyla wrote):")
        lines += [f"  {x}" for x in left]
    return lines or [f"{rec['offer']}: nothing left to remove"]

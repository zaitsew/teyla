"""A parsed-transcript cache. Parsing a transcript is the slow part of every command that reads
sessions (`spend`, `monitor`, `lanes`, `advise`, `sessions`, `corrections`, `prose`): the files are
large and almost never change once a session ends. A parsed `Session` is stored per transcript under
`<TEYLA_HOME or ~/.teyla>/cache/sessions/`, and reused while nothing that feeds it has changed.

The key is everything `parse` reads: the transcript's absolute path, size and mtime_ns, the sorted
(name, size, mtime_ns) of its subagent files (Claude Code), the `repo_names` argument, the adapter's
PARSER_VERSION, the Session field names, and the HOME and timezone (the day a message falls on and
the global-instructions path depend on them). Anything else (a Codex title from the session index) is
passed as `extra`.

RULE: bump the adapter's PARSER_VERSION whenever its `parse` logic, or the Session it fills, changes
in a way that alters a result. A stale entry would otherwise serve the old result for an unchanged file.

The cache holds what Session holds, including the human's turn text. It is local only: mode 0600 in a
0700 directory, never sent anywhere. `TEYLA_NO_CACHE=1` turns it off; `teyla uninstall` removes it
with ~/.teyla. A corrupt or unreadable entry is ignored and rewritten; writes are atomic
(temp file + os.replace), so concurrent runs cannot corrupt an entry.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import pathlib
import pickle
import sys
import time

PRUNE_AFTER_S = 30 * 24 * 3600
_FORMAT = 1
_touched: set[str] = set()


def enabled() -> bool:
    return not os.environ.get("TEYLA_NO_CACHE")


# A command that promises to change nothing (`teyla start` before the person accepts) reads the
# cache but never writes or prunes it.
_read_only = False


def set_read_only(on: bool = True) -> None:
    global _read_only
    _read_only = on


def cache_dir() -> pathlib.Path:
    """Resolved at call time, so a test's TEYLA_HOME is obeyed."""
    home = os.environ.get("TEYLA_HOME") or (pathlib.Path.home() / ".teyla")
    return pathlib.Path(home).expanduser() / "cache" / "sessions"


def _schema() -> str:
    from . import Session
    return ",".join(f.name for f in dataclasses.fields(Session))


def make_key(path: str, adapter: str, version: int, repo_names=None, extra=None, sub_files: bool = False):
    """The key for `path`, or None when the file cannot be stat'ed (then nothing is cached)."""
    path = os.path.abspath(path)
    try:
        st = os.stat(path)
    except OSError:
        return None
    subs = []
    if sub_files:
        d = os.path.join(path[:-len(".jsonl")], "subagents")
        try:
            for e in sorted(os.scandir(d), key=lambda e: e.name):
                if e.name.endswith(".jsonl"):
                    es = e.stat()
                    subs.append((e.name, es.st_size, es.st_mtime_ns))
        except OSError:
            pass
    return (_FORMAT, adapter, version, path, st.st_size, st.st_mtime_ns, tuple(subs),
            tuple(repo_names) if repo_names else None, extra, _schema(),
            os.path.expanduser("~"), os.environ.get("TZ"), time.tzname)


def _entry_path(key) -> pathlib.Path:
    name = hashlib.sha256(f"{key[1]}\0{key[3]}".encode()).hexdigest()[:40] + ".pkl"
    return cache_dir() / name


def get(key):
    if key is None or not enabled():
        return None
    p = _entry_path(key)
    _touched.add(p.name)
    try:
        with open(p, "rb") as fh:
            stored_key, session = pickle.load(fh)
    except Exception:
        return None
    if stored_key != key:
        return None
    try:  # keep a used entry out of the prune window
        if time.time() - p.stat().st_mtime > 24 * 3600:
            os.utime(p)
    except OSError:
        pass
    return session


def put(key, session) -> None:
    if key is None or not enabled() or _read_only or session is None:
        return
    p = _entry_path(key)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(p.parent, 0o700)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            pickle.dump((key, session), fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        _touched.add(p.name)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def cached(key, build, rekey=None):
    """`build()` unless a valid entry exists. A freshly built Session is stored only when `rekey()`
    (a fresh stat of the same files) still gives the key it was read under: a live session appends
    while it is parsed, and an entry from a torn read must never be kept."""
    s = get(key)
    if s is not None:
        return s
    _note_miss()
    s = build()
    if key is not None and (rekey is None or rekey() == key):
        put(key, s)
    return s


_misses = 0
_announced = False
ANNOUNCE_AFTER = 50


def _note_miss() -> None:
    """One stderr line on a cold run that will read many logs, on a terminal only. Stdout is untouched."""
    global _misses, _announced
    if not enabled():
        return
    _misses += 1
    if _misses >= ANNOUNCE_AFTER and not _announced:
        _announced = True
        try:
            if sys.stderr.isatty():
                print("teyla: reading your session logs once; later runs are fast.", file=sys.stderr)
        except Exception:
            pass


def prune(now: float | None = None) -> int:
    """After a full load: delete entries this run did not use and nobody has used for 30 days
    (their transcript is gone, or no longer read). Returns the number removed."""
    if not enabled() or _read_only:
        return 0
    now = time.time() if now is None else now
    n = 0
    try:
        entries = list(os.scandir(cache_dir()))
    except OSError:
        return 0
    for e in entries:
        if e.name in _touched or not e.name.endswith((".pkl", ".tmp")):
            continue
        try:
            old = now - e.stat().st_mtime > PRUNE_AFTER_S
            gone = False
            if not old and e.name.endswith(".pkl"):
                # Its transcript is gone: only when the transcript's folder lists fine and the file is not
                # in it. An unmounted or unreadable root must not wipe the cache.
                with open(e.path, "rb") as fh:
                    path = pickle.load(fh)[0][3]
                gone = os.path.isdir(os.path.dirname(path)) and not os.path.exists(path)
            if old or gone:
                os.unlink(e.path)
                n += 1
        except Exception:
            pass
    return n

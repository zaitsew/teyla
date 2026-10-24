"""`teyla note` / `teyla notes` — quick text ideas, linked to a product, kept as typed.

    teyla note "text" [--product P]        keep one note; "-" reads it from stdin
    teyla notes [--product P | --inbox] [--all] [--json]    newest first; dropped ones only with --all
    teyla note link <id> <product>         file a note under another product (or `inbox`)
    teyla note drop <id> | undrop <id>     set a note aside, or bring it back

The owner said it in one line: "add a notes section - i want to quickly add ideas in text or voice and link
them to some of the product and later launch the development of them". This is the text half.

    ~/.teyla/notes/notes.jsonl     append-only, 0600, in a 0700 directory
    ~/.teyla/notes/.lock           the flock every writer takes

The file holds events, one JSON object per line, and the reader folds them into notes:

    {"ev": "add",  "id": "n4k2xq", "text": ..., "product": ..., "source": "owner", "linked_by": ..., "at": ...}
    {"ev": "link", "id": "n4k2xq", "product": ..., "linked_by": "owner", "at": ...}
    {"ev": "drop" | "undrop", "id": "n4k2xq", "at": ...}

A note is `{id, text, product, source, created, updated, linked_by, dropped}`. `text` is what was typed, trimmed
only of outer whitespace. `product` is a registry id or `inbox`. `source` is `owner` for everything typed at the
CLI; the field is there so notes an agent writes later stay apart from the owner's. `linked_by` says how the
product was chosen: `owner` (--product or `link`), `text` (the text names exactly one product), `cwd` (the
directory is inside a registered product) or "" (the inbox).

Which product, when --product is absent: the one product `registry.match_text` finds in the text, else the
registered product of the current directory, else `inbox`. A name is never invented. A text that names two
products is no match; the directory decides, and without one it goes to the inbox.

Owner words: a note linked to a registered product is also appended, as typed, to that product's intent file
(`intent.Store.add`, harness `note`, session = the note id), however short. A note moved by `link` is added
under the new product; the old entry stays, because the intent store only appends. Inbox notes reach it when
they are linked. Everything here is stdlib.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import difflib
import json
import os
import pathlib
import secrets
import sys
import time

from . import corrections, registry

try:  # POSIX only; without it the lock is skipped and concurrent writers are best effort
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

INBOX = "inbox"
SOURCE_OWNER = "owner"
LINKED_BY = ("owner", "text", "cwd", "")
LOCK_WAIT_S = 5.0
CLIP = 60
_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"       # base32, lowercase: nothing to confuse with a digit but 0/1
_HOW = {"owner": "you chose it", "text": "named in the text", "cwd": "from this directory", "": "no product matched"}


class NoteError(Exception):
    """A refusal the CLI prints as one line; nothing was written."""


# --- where ------------------------------------------------------------------------------------

def notes_dir() -> pathlib.Path:
    return corrections.teyla_home() / "notes"


def store_path() -> pathlib.Path:
    return notes_dir() / "notes.jsonl"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- the store --------------------------------------------------------------------------------

@contextlib.contextmanager
def _locked(wait_s: float = LOCK_WAIT_S):
    """The notes directory, locked for writing. A writer that cannot get the lock in `wait_s` raises
    NoteError: the caller keeps the text on screen rather than lose it silently."""
    from . import config
    config.private_dir(corrections.teyla_home())
    d = config.private_dir(notes_dir())
    fd = None
    if fcntl is not None:
        fd = os.open(d / ".lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        deadline = time.monotonic() + wait_s
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise NoteError("the notes store is locked by another process; nothing was saved, try again")
                time.sleep(0.02)
    try:
        yield
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _events() -> list[dict]:
    """Every readable event, in file order. A line that is not a JSON object (a hand edit, a write cut
    short) is skipped, never fatal."""
    try:
        raw = store_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in raw.split("\n"):              # not splitlines(): U+2028/U+2029 inside a note are text, not line ends
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict) and isinstance(ev.get("id"), str) and ev.get("ev") in ("add", "link", "drop", "undrop"):
            out.append(ev)
    return out


def fold(events: list[dict]) -> dict[str, dict]:
    """{id: note} in creation order. An event for an id with no `add` is ignored."""
    notes: dict[str, dict] = {}
    for ev in events:
        n = notes.get(ev["id"])
        at = str(ev.get("at") or "")
        if ev["ev"] == "add":
            if n is None:
                notes[ev["id"]] = {"id": ev["id"], "text": str(ev.get("text") or ""),
                                   "product": str(ev.get("product") or INBOX), "source": str(ev.get("source") or SOURCE_OWNER),
                                   "created": at, "updated": at, "linked_by": str(ev.get("linked_by") or ""),
                                   "dropped": False}
        elif n is not None:
            n["updated"] = at or n["updated"]
            if ev["ev"] == "link":
                n["product"] = str(ev.get("product") or INBOX)
                n["linked_by"] = str(ev.get("linked_by") or "")
            else:
                n["dropped"] = ev["ev"] == "drop"
    return notes


def load() -> dict[str, dict]:
    return fold(_events())


def _append(ev: dict) -> None:
    corrections._append_line(store_path(), json.dumps(ev, ensure_ascii=False) + "\n")


def _new_id(taken) -> str:
    while True:
        nid = "n" + "".join(secrets.choice(_ALPHABET) for _ in range(6))
        if nid not in taken:
            return nid


def find(notes: dict[str, dict], ref: str) -> dict:
    """The note `ref` names: its id, or a prefix of one id. Raises NoteError when none or several match."""
    ref = (ref or "").strip().lower()
    if ref in notes:
        return notes[ref]
    hits = [n for i, n in notes.items() if ref and i.startswith(ref)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise NoteError(f"no note {ref!r}. `teyla notes --all` lists them; quote the text to keep a note that starts with link, drop or undrop.")
    raise NoteError(f"{ref!r} matches {len(hits)} notes: {', '.join(n['id'] for n in hits)}")


# --- which product ----------------------------------------------------------------------------

def known_names(reg: dict) -> dict[str, str]:
    """{lowercase name: registry id} for every id and alias."""
    out = {}
    for pid, p in reg["product"].items():
        for name in (pid, *p["aliases"]):
            out.setdefault(name.lower(), pid)
    return out


def check_product(name: str, reg: dict | None = None) -> str:
    """The registered id `name` stands for (an id, an alias, any case) or `inbox`. Raises NoteError with the
    close names for anything else."""
    reg = registry.load() if reg is None else reg
    key = (name or "").strip().lower()
    if key == INBOX:
        return INBOX
    names = known_names(reg)
    if key in names:
        return names[key]
    close = difflib.get_close_matches(key, list(names), n=3, cutoff=0.5)
    ids = sorted({names[c] for c in close})
    hint = f" Close: {', '.join(ids)}." if ids else ""
    have = f" Registered: {', '.join(reg['product'])}." if reg["product"] else " No product is registered; `teyla product init` proposes them."
    raise NoteError(f"no product {name!r}.{hint}{have} `{INBOX}` keeps a note unfiled.")


def suggest(text: str, cwd=None, reg: dict | None = None) -> tuple[str, str]:
    """(product, linked_by) for a note typed without --product. Text first, only when it names exactly one
    product; then the directory, only when it belongs to a registered product; else the inbox."""
    reg = registry.load() if reg is None else reg
    found = registry.match_text(text, reg)
    if len(found) == 1:
        return found[0], "text"
    here = os.getcwd() if cwd is None else cwd
    try:
        pid = registry.resolve(here, reg=reg)
    except OSError:
        pid = ""
    if pid in reg["product"]:
        return pid, "cwd"
    return INBOX, ""


# --- write ------------------------------------------------------------------------------------

def _to_intent(note: dict, product: str) -> bool:
    """Append the note, as typed, to `product`'s intent file. False when it was not written (the store was
    busy, or the product already holds the same text)."""
    from . import intent
    if product == INBOX:
        return False
    try:
        when = _dt.datetime.now(_dt.timezone.utc)
        with intent.Store() as st:
            return st.add(product, note["text"], harness="note", session=note["id"], when=when)
    except (TimeoutError, OSError):
        return False


def add(text: str, product: str | None = None, source: str = SOURCE_OWNER, cwd=None) -> dict:
    """Keep one note and return it, with `intent` = whether the owner-words file took it. `product` is the
    --product value: checked, and recorded as chosen by the owner."""
    body = (text or "").strip()
    if not body:
        raise NoteError("an empty note; give some text, or `-` to read it from stdin")
    reg = registry.load()
    if product:
        pid, how = check_product(product, reg), "owner"
    else:
        pid, how = suggest(body, cwd, reg)
    with _locked():
        taken = {ev["id"] for ev in _events()}
        note = {"id": _new_id(taken), "text": body, "product": pid, "source": source,
                "created": _now(), "linked_by": how}
        note["updated"] = note["created"]
        _append({"ev": "add", "id": note["id"], "text": body, "product": pid, "source": source,
                 "linked_by": note["linked_by"], "at": note["created"]})
    note["dropped"] = False
    note["intent"] = _to_intent(note, pid) if pid != INBOX else False
    return note


def link(ref: str, product: str) -> tuple[dict, bool]:
    """Move a note to `product` (a name, an alias or `inbox`). Returns (note, changed). A note moved to a
    registered product is added to that product's intent file; the old entry stays."""
    pid = check_product(product)
    with _locked():
        note = find(load(), ref)
        if note["dropped"]:
            raise NoteError(f"{note['id']} is dropped; `teyla note undrop {note['id']}` first")
        changed = not (note["product"] == pid and note["linked_by"] == "owner")
        if changed:
            _append({"ev": "link", "id": note["id"], "product": pid, "linked_by": "owner", "at": _now()})
            note = find(load(), note["id"])
    if pid != INBOX:
        _to_intent(note, pid)       # also on a repeat: it retries a copy a busy intent store skipped; the store de-duplicates
    return note, changed


def set_dropped(ref: str, dropped: bool) -> tuple[dict, bool]:
    with _locked():
        note = find(load(), ref)
        if note["dropped"] == dropped:
            return note, False
        _append({"ev": "drop" if dropped else "undrop", "id": note["id"], "at": _now()})
        return find(load(), note["id"]), True


# --- read -------------------------------------------------------------------------------------

def listing(product: str | None = None, include_dropped: bool = False) -> list[dict]:
    """Notes newest first. `product` is a registered id or `inbox`."""
    rows = [n for n in load().values() if include_dropped or not n["dropped"]]
    if product:
        rows = [n for n in rows if n["product"] == product]
    order = {n["id"]: i for i, n in enumerate(rows)}            # file order breaks a tie within one second
    return sorted(rows, key=lambda n: (n["created"], order[n["id"]]), reverse=True)


def counts() -> dict:
    """{"inbox": n, "by_product": {id: n}} over open notes: what `teyla state --json` carries."""
    out = {"inbox": 0, "by_product": {}}
    for n in load().values():
        if n["dropped"]:
            continue
        if n["product"] == INBOX:
            out["inbox"] += 1
        else:
            out["by_product"][n["product"]] = out["by_product"].get(n["product"], 0) + 1
    out["by_product"] = dict(sorted(out["by_product"].items()))
    return out


# --- CLI --------------------------------------------------------------------------------------

def clip(text: str, n: int = CLIP) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[:n - 1].rstrip() + "…"


def _line(n: dict) -> str:
    return f"{n['id']}  {n['product']}  ({_HOW.get(n['linked_by'], n['linked_by'])})  {clip(n['text'])}"


def _fail(e: NoteError) -> int:
    print(f"teyla: {e}", file=sys.stderr)
    return 1


def cmd_note(args) -> int:
    words = list(args.words or [])
    verbs = {"link": 3, "drop": 2, "undrop": 2}
    if words and words[0] in verbs and len(words) == verbs[words[0]]:
        if args.product:
            print(f"teyla: --product goes with a new note; `teyla note link <id> <product>` moves one", file=sys.stderr)
            return 2
        try:
            if words[0] == "link":
                note, changed = link(words[1], words[2])
                print(("moved " if changed else "already in place: ") + _line(note))
            else:
                note, changed = set_dropped(words[1], words[0] == "drop")
                verb = "dropped" if words[0] == "drop" else "restored"
                print((f"{verb} " if changed else f"already {verb}: ") + _line(note))
        except NoteError as e:
            return _fail(e)
        return 0
    if not words:
        print('usage: teyla note "text" [--product P] | link <id> <product> | drop <id> | undrop <id>', file=sys.stderr)
        return 2
    text = sys.stdin.read() if words == ["-"] else " ".join(words)
    try:
        note = add(text, args.product)
    except NoteError as e:
        return _fail(e)
    print(_line(note))
    return 0


def cmd_notes(args) -> int:
    if args.product and args.inbox:
        print("teyla: --product and --inbox exclude each other", file=sys.stderr)
        return 2
    try:
        pid = INBOX if args.inbox else check_product(args.product) if args.product else None
    except NoteError as e:
        return _fail(e)
    rows = listing(pid, args.all)
    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return 0
    if not rows:
        print("no notes. `teyla note \"an idea\"` keeps one.")
        return 0
    for n in rows:
        print(("[dropped] " if n["dropped"] else "") + f"{n['id']}  {n['created'][:10]}  {n['product']}  {clip(n['text'])}")
    return 0


def register(sp):
    q = sp.add_parser("note", help='keep a text note, linked to a product: teyla note "idea" [--product P] | link|drop|undrop <id>')
    q.set_defaults(fn=cmd_note)
    q.add_argument("words", nargs="*", metavar='["text"|-|link <id> <product>|drop <id>|undrop <id>]')
    q.add_argument("--product", help="the registered product (id or alias); without it the text, then the directory, then `inbox` decide")
    q = sp.add_parser("notes", help="list notes, newest first")
    q.set_defaults(fn=cmd_notes)
    q.add_argument("--product", help="only this product's notes")
    q.add_argument("--inbox", action="store_true", help="only notes with no product yet")
    q.add_argument("--all", action="store_true", help="include dropped notes")
    q.add_argument("--json", action="store_true")
    return q

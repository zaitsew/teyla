"""The taste corpus: what the owner likes and dislikes, kept as evidence (docs/decisions/2026-11-08-studio-2.md, S13, S14).

    teyla taste add <url|image> [comment...] [--dislike|--mixed] [--product N] [--scope S] [--kind K] [--no-capture]
    teyla taste note <id> "sentence"            the owner's sentence; an entry with no sentence is `raw`
    teyla taste capture <id>                    capture again (screenshots, computed styles, copy lines)
    teyla taste interpret <id> [--dry]          a model proposes the claim, axes and what not to copy
    teyla taste accept <id> [--supersedes ID]   the owner's yes: the entry becomes `active`
    teyla taste reject <id>                     the owner's no: the entry is removed from the corpus
    teyla taste inbox [--all] [--json]          every entry, `raw` and `proposed` first, one line each
    teyla taste corpus render [--product N] [--out FILE]    a TASTE.md of at most 15 active entries

The corpus is `~/.teyla/taste/corpus/<YYYYMMDD>-<id>/{entry.json,evidence/}`. `TEYLA_TASTE_CORPUS` moves it; the
default follows `TEYLA_HOME`. entry.json is checked against templates/taste/entry.schema.json on every read.
The owner's fields (claim, verdict, scope, kind, axes, do_not_copy) and the model's `interpretation` are separate.
Only `accept` makes an entry `active`, and only `active` entries reach a style source. Nothing here touches the
network; capture and interpretation are in taste_capture.py.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import secrets
import shutil
import sys

from . import taste

AXES = ("density", "chrome", "color", "type", "motion", "tone")
KINDS = ("screen", "product", "copy", "motion")
VERDICTS = ("like", "dislike", "mixed")
STATUSES = ("raw", "proposed", "active", "superseded")
SCOPE_RE = re.compile(r"^(portfolio|voice|structure|product:[a-z0-9][a-z0-9._-]*)$")
MAX_RENDER = 15
MIN_PREFIX = 3
URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif"}
_SEP_WORDS = {"-", "—", "–", "--", ":"}
_COPY_WORDS = re.compile(r"\b(copy|text|wording|tone|voice|headline|microcopy|writing|words)\b", re.I)
_MOTION_WORDS = re.compile(r"\b(motion|animation|animated|transition|easing|gesture)\b", re.I)
_PRODUCT_HOSTS = ("apps.apple.com", "play.google.com", "testflight.apple.com")


class EntryError(ValueError):
    """A problem the owner can fix: a bad id, a bad flag, an entry.json that does not read."""


# --- paths ------------------------------------------------------------------------------------------

def corpus_dir() -> pathlib.Path:
    env = os.environ.get("TEYLA_TASTE_CORPUS")
    if env:
        return pathlib.Path(env).expanduser()
    home = os.environ.get("TEYLA_HOME")
    base = pathlib.Path(home).expanduser() if home else pathlib.Path.home() / ".teyla"
    return base / "taste" / "corpus"


def schema() -> dict:
    from . import templates_dir
    return json.loads((templates_dir() / "taste" / "entry.schema.json").read_text(encoding="utf-8"))


# --- the schema check (the subset the schema file uses; Teyla has no dependencies) -------------------

_TYPES = {"object": dict, "array": list, "string": str, "number": (int, float), "integer": int, "null": type(None)}


def _check(value, sch: dict, where: str, out: list[str]) -> None:
    types = sch.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        ok = any(isinstance(value, _TYPES[n]) and not (n in ("number", "integer") and isinstance(value, bool)) for n in names)
        if not ok:
            out.append(f"{where}: expected {' or '.join(names)}")
            return
    if "enum" in sch and value not in sch["enum"]:
        out.append(f"{where}: {value!r} is not one of {', '.join(map(str, sch['enum']))}")
    if isinstance(value, str):
        if "pattern" in sch and not re.search(sch["pattern"], value):
            out.append(f"{where}: {value!r} has the wrong form")
        if len(value) < sch.get("minLength", 0):
            out.append(f"{where}: empty")
    if isinstance(value, dict):
        props = sch.get("properties", {})
        for key in sch.get("required", []):
            if key not in value:
                out.append(f"{where}: missing `{key}`")
        for key, v in value.items():
            if key in props:
                _check(v, props[key], f"{where}.{key}", out)
            elif sch.get("additionalProperties") is False:
                out.append(f"{where}: unknown field `{key}`")
    if isinstance(value, list) and "items" in sch:
        for i, v in enumerate(value):
            _check(v, sch["items"], f"{where}[{i}]", out)


def validate(obj) -> list[str]:
    """Problems with an entry (an empty list when it is valid)."""
    out: list[str] = []
    _check(obj, schema(), "entry", out)
    return out


# --- entries ----------------------------------------------------------------------------------------

def now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def entry_path(d: pathlib.Path) -> pathlib.Path:
    return d / "entry.json"


def read_entry(d: pathlib.Path) -> dict:
    p = entry_path(d)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except OSError as e:
        raise EntryError(f"{p}: does not read ({e.strerror or e})") from e
    except ValueError as e:
        raise EntryError(f"{p}: not JSON ({e})") from e
    problems = validate(obj)
    if problems:
        raise EntryError(f"{p}: {'; '.join(problems[:3])}")
    return obj


def write_entry(d: pathlib.Path, entry: dict) -> None:
    problems = validate(entry)
    if problems:
        raise EntryError(f"entry {entry.get('id')}: {'; '.join(problems[:3])}")
    taste.write_json(entry_path(d), entry)


def entry_dirs() -> list[pathlib.Path]:
    root = corpus_dir()
    return sorted(p for p in root.iterdir() if p.is_dir() and entry_path(p).is_file()) if root.is_dir() else []


def load_all() -> tuple[list[tuple[pathlib.Path, dict]], list[str]]:
    """([(dir, entry)], problems). An entry that does not read is skipped and named."""
    rows, problems = [], []
    for d in entry_dirs():
        try:
            rows.append((d, read_entry(d)))
        except EntryError as e:
            problems.append(str(e))
    return rows, problems


def find(prefix: str) -> tuple[pathlib.Path, dict]:
    p = (prefix or "").strip().lower()
    if len(p) < MIN_PREFIX:
        raise EntryError(f"give an entry id (a prefix of at least {MIN_PREFIX} characters)")
    rows, _ = load_all()
    hits = [(d, e) for d, e in rows if e["id"].startswith(p) or d.name.lower().startswith(p)]
    if not hits:
        raise EntryError(f"no entry starts with {prefix!r} (teyla taste inbox lists them)")
    if len(hits) > 1:
        raise EntryError(f"{prefix!r} matches {len(hits)} entries: " + ", ".join(e["id"] for _, e in hits))
    return hits[0]


def new_id() -> str:
    used = {e["id"] for _, e in load_all()[0]}
    while True:
        i = secrets.token_hex(3)
        if i not in used:
            return i


def is_url(s: str) -> bool:
    return bool(URL_RE.match(s or ""))


def guess_kind(source: str, comment: str) -> str:
    host = re.sub(r"^https?://", "", source, flags=re.I).split("/")[0].lower() if is_url(source) else ""
    if host in _PRODUCT_HOSTS:
        return "product"
    if _MOTION_WORDS.search(comment):
        return "motion"
    if _COPY_WORDS.search(comment):
        return "copy"
    return "screen"


def norm_scope(scope: str | None, product: str | None) -> str:
    if scope and product:
        raise EntryError("give --scope or --product, not both")
    if product:
        scope = f"product:{product.strip().lower()}"
    scope = (scope or "portfolio").strip().lower()
    if scope.startswith("product:") and not SCOPE_RE.match(scope):
        raise EntryError(f"{scope!r}: a product name is lowercase letters, digits, . _ -")
    if not SCOPE_RE.match(scope):
        raise EntryError(f"scope {scope!r}: use portfolio, product:<name>, voice or structure")
    return scope


def split_words(words: list[str]) -> tuple[str, str]:
    """(target, comment): the first word is the url or file, the rest is the owner's sentence. A leading dash
    word (`url — comment`) is a separator, not part of the sentence."""
    if not words:
        raise EntryError("give a url or an image file")
    rest = list(words[1:])
    while rest and rest[0] in _SEP_WORDS:
        rest.pop(0)
    return words[0], " ".join(rest).strip()


def add(words: list[str], *, verdict: str = "like", scope: str | None = None, product: str | None = None,
        kind: str | None = None) -> tuple[pathlib.Path, dict]:
    """Create an entry (no capture). A url or image file, and the owner's sentence if there is one."""
    from . import ux_judge
    target, comment = split_words(words)
    if kind is not None and kind not in KINDS:
        raise EntryError(f"kind {kind!r}: use {', '.join(KINDS)}")
    sc = norm_scope(scope, product)
    image: pathlib.Path | None = None
    if is_url(target):
        source = target
    else:
        image = pathlib.Path(target).expanduser()
        if not image.is_file():
            raise EntryError(f"{target!r} is neither a http(s) url nor an image file")
        if image.suffix.lower() not in IMAGE_EXT or ux_judge._media_type(image.read_bytes()[:16]) is None:
            raise EntryError(f"{image}: not a PNG, JPEG or GIF")
        source = str(image.resolve())
    eid = new_id()
    d = corpus_dir() / f"{_dt.date.today():%Y%m%d}-{eid}"
    entry = {"id": eid, "created": now(), "source": source, "kind": kind or guess_kind(source, comment),
             "verdict": verdict, "claim": comment, "claim_source": "owner", "scope": sc,
             "axes": {a: None for a in AXES},
             "evidence": {"files": [], "measured": {}, "captured": None, "backend": None, "error": None},
             "do_not_copy": [], "status": "proposed" if comment else "raw", "supersedes": None, "interpretation": None}
    if not comment:
        del entry["claim_source"]
    (d / "evidence").mkdir(parents=True, exist_ok=True)
    if image is not None:
        dest = d / "evidence" / f"source{image.suffix.lower()}"
        shutil.copyfile(image, dest)
        entry["evidence"].update(files=[f"evidence/{dest.name}"], captured=now(), backend="file")
    write_entry(d, entry)
    return d, entry


def note(prefix: str, sentence: str) -> tuple[pathlib.Path, dict]:
    sentence = " ".join((sentence or "").split())
    if not sentence:
        raise EntryError('give the sentence: teyla taste note <id> "great neutral design"')
    d, e = find(prefix)
    if e["status"] == "superseded":
        raise EntryError(f"{e['id']} is superseded; add a new entry instead")
    e["claim"], e["claim_source"] = sentence, "owner"
    if e["status"] == "raw":
        e["status"] = "proposed"
    write_entry(d, e)
    return d, e


def accept(prefix: str, supersedes: str | None = None) -> tuple[pathlib.Path, dict, str | None]:
    """The owner's yes. A model proposal is adopted only where the owner left a field empty."""
    d, e = find(prefix)
    if e["status"] == "superseded":
        raise EntryError(f"{e['id']} is superseded")
    interp = e.get("interpretation") or {}
    if not e["claim"].strip():
        proposed = (interp.get("claim") or "").strip()
        if not proposed:
            raise EntryError(f"{e['id']} has no sentence: teyla taste note {e['id']} \"...\" (or interpret it first)")
        e["claim"], e["claim_source"] = proposed, "accepted-proposal"
    for a in AXES:
        if e["axes"].get(a) is None and (interp.get("axes") or {}).get(a):
            e["axes"][a] = str(interp["axes"][a])
    if not e["do_not_copy"] and interp.get("do_not_copy"):
        e["do_not_copy"] = [str(x) for x in interp["do_not_copy"]]
    old_id = None
    if supersedes:
        od, old = find(supersedes)
        if old["id"] == e["id"]:
            raise EntryError("an entry cannot supersede itself")
        if old["scope"] != e["scope"]:
            raise EntryError(f"{old['id']} is in scope {old['scope']}, {e['id']} in {e['scope']}: "
                             "a later entry supersedes an earlier one only in the same scope")
        old["status"] = "superseded"
        write_entry(od, old)
        e["supersedes"], old_id = old["id"], old["id"]
    e["status"] = "active"
    write_entry(d, e)
    return d, e, old_id


def reject(prefix: str) -> dict:
    """The owner's no. The entry and its evidence are deleted: a rejected drop is not evidence of anything."""
    d, e = find(prefix)
    root = corpus_dir().resolve()
    if d.resolve().parent != root:
        raise EntryError(f"{d}: not inside the corpus")
    shutil.rmtree(d)
    return e


# --- the inbox --------------------------------------------------------------------------------------

_ORDER = {"raw": 0, "proposed": 1, "active": 2, "superseded": 3}


def _short(source: str, n: int = 44) -> str:
    s = re.sub(r"^https?://(www\.)?", "", source).rstrip("/") if is_url(source) else pathlib.Path(source).name
    return s if len(s) <= n else s[:n - 1] + "…"


def inbox_line(e: dict) -> str:
    claim = " ".join(e["claim"].split())
    claim = f'"{claim[:70]}{"…" if len(claim) > 70 else ""}"' if claim else "(no sentence yet)"
    cap = "" if e["evidence"]["files"] else " [no evidence]"
    nxt = ""
    if e["status"] == "raw":
        nxt = f"  -> teyla taste note {e['id']} \"...\""
    elif e["status"] == "proposed":
        nxt = f"  -> teyla taste accept {e['id']}"
    return f"{e['id']}  {e['status']:<10} {e['verdict']:<7} {e['scope']:<16} {e['kind']:<7} {_short(e['source'])} {claim}{cap}{nxt}"


def inbox_rows(show_all: bool = True) -> tuple[list[dict], list[str]]:
    rows, problems = load_all()
    ents = sorted((e for _, e in rows), key=lambda e: (_ORDER[e["status"]], _neg(e["created"])))
    if not show_all:
        ents = [e for e in ents if e["status"] in ("raw", "proposed")]
    return ents, problems


def _neg(s: str) -> tuple:
    return tuple(-ord(c) for c in s)             # newest first within a status


# --- the corpus file ----------------------------------------------------------------------------------

def in_scope(e: dict, product: str | None) -> bool:
    sc = e["scope"]
    if sc in ("portfolio", "voice", "structure"):
        return True
    return bool(product) and sc == f"product:{product.strip().lower()}"


def select(rows: list[tuple[pathlib.Path, dict]], product: str | None, limit: int = MAX_RENDER) -> list[dict]:
    """Active entries in scope, at most `limit`. A product's own entries come before the portfolio's, newest first."""
    ents = [e for _, e in rows if e["status"] == "active" and in_scope(e, product)]
    ents.sort(key=lambda e: (0 if e["scope"].startswith("product:") else 1, _neg(e["created"])))
    return ents[:limit]


def _axes_text(e: dict) -> str:
    named = [f"{a}: {e['axes'][a]}" for a in AXES if e["axes"].get(a)]
    return "; ".join(named)


def _entry_md(e: dict, dislike: bool) -> list[str]:
    head = f"- **{e['id']}** ({e['scope']}, {e['kind']}) {e['claim']}"
    out = [head, f"  - source: {e['source']}"]
    axes = _axes_text(e)
    if dislike:
        named = [a for a in AXES if e["axes"].get(a)]
        out.append(f"  - constrains: {', '.join(named) if named else 'the whole claim (no axis named)'}"
                   + (f" ({axes})" if axes else ""))
    elif axes:
        out.append(f"  - axes: {axes}")
    if e["do_not_copy"]:
        out.append("  - do not copy: " + "; ".join(e["do_not_copy"]))
    if e["evidence"]["files"]:
        out.append(f"  - evidence: {e['id']} ({len(e['evidence']['files'])} files in the corpus)")
    return out


def render_corpus(rows: list[tuple[pathlib.Path, dict]], product: str | None) -> str:
    ents = select(rows, product)
    likes = [e for e in ents if e["verdict"] == "like"]
    dislikes = [e for e in ents if e["verdict"] == "dislike"]
    mixed = [e for e in ents if e["verdict"] == "mixed"]
    title = f"# Taste{f' for {product}' if product else ''}"
    L = [title, "",
         "Generated by `teyla taste corpus render`. The owner's words are quoted as written; each entry's evidence is in `~/.teyla/taste/corpus/`.",
         "A dislike is a constraint: it wins over a like on the axes it names (S14). References are never averaged.", ""]
    if not ents:
        L += ["No active entries in this scope yet. `teyla taste inbox` lists what waits for a yes.", ""]
    for name, group, dis in (("Likes", likes, False), ("Dislikes (constraints)", dislikes, True), ("Mixed", mixed, False)):
        if group:
            L += [f"## {name}", ""]
            for e in group:
                L += _entry_md(e, dis)
            L.append("")
    total = sum(1 for _, e in rows if e["status"] == "active" and in_scope(e, product))
    if total > len(ents):
        L.append(f"{total - len(ents)} older active entries in scope are left out (the limit is {MAX_RENDER}).")
    return "\n".join(L).rstrip() + "\n"


# --- the commands -------------------------------------------------------------------------------------

def _err(msg: str) -> int:
    print(f"teyla taste: {msg}", file=sys.stderr)
    return 1


def cmd(args) -> int:
    action = args.action
    words = list(getattr(args, "words", []) or [])
    try:
        if action == "add":
            verdict = "dislike" if args.dislike else "mixed" if args.mixed else "like"
            if args.dislike and args.mixed:
                return _err("give --dislike or --mixed, not both")
            d, e = add(words, verdict=verdict, scope=args.scope, product=args.product, kind=args.kind)
            print(f"added {e['id']} ({e['verdict']}, {e['scope']}, {e['kind']}, {e['status']}): {d}")
            if is_url(e["source"]) and not args.no_capture:
                from . import taste_capture
                rc, msg = taste_capture.capture_entry(d, e)
                print(msg, file=sys.stderr if rc else sys.stdout)
                d, e = d, read_entry(d)
            if e["status"] == "raw":
                print(f"raw: it is not a style source until you add a sentence: teyla taste note {e['id']} \"...\"")
            print(inbox_line(e))
            return 0
        if action in ("note", "accept", "reject", "capture", "interpret"):
            if not words:
                return _err(f"{action}: give an entry id")
            if action == "note":
                d, e = note(words[0], " ".join(words[1:]))
                print(f"noted {e['id']} ({e['status']})")
                print(inbox_line(e))
            elif action == "accept":
                d, e, old = accept(words[0], getattr(args, "supersedes", None))
                print(f"active {e['id']}" + (f"; {old} is superseded" if old else ""))
                print(inbox_line(e))
            elif action == "reject":
                e = reject(words[0])
                print(f"rejected {e['id']}: the entry and its evidence are deleted")
            elif action == "capture":
                d, e = find(words[0])
                if not is_url(e["source"]):
                    return _err(f"{e['id']} is a file; there is nothing to capture")
                from . import taste_capture
                rc, msg = taste_capture.capture_entry(d, e)
                print(msg, file=sys.stderr if rc else sys.stdout)
                return rc
            else:
                from . import taste_capture
                d, e = find(words[0])
                return taste_capture.cmd_interpret(d, e, model=args.model, dry=args.dry, as_json=args.json)
            return 0
        if action == "inbox":
            ents, problems = inbox_rows(True)
            lim = max(1, args.limit)
            if args.json:
                print(json.dumps({"corpus": str(corpus_dir()), "entries": ents[:lim], "problems": problems}, indent=1, ensure_ascii=False))
                return 0
            if not ents:
                print(f"the corpus is empty ({corpus_dir()}): teyla taste add <url> \"what you like about it\"")
            for e in ents[:lim]:
                print(inbox_line(e))
            if len(ents) > lim:
                print(f"... {len(ents) - lim} more (--limit)")
            for p in problems:
                print(f"skipped: {p}", file=sys.stderr)
            return 0
        if action == "corpus":
            if words != ["render"]:
                return _err("corpus: the one action is `render`")
            rows, problems = load_all()
            text = render_corpus(rows, args.product)
            for p in problems:
                print(f"skipped: {p}", file=sys.stderr)
            if args.out:
                taste._write_atomic(pathlib.Path(args.out).expanduser(), text)
                print(f"wrote {args.out}")
            else:
                print(text, end="")
            return 0
    except EntryError as e:
        return _err(f"{action}: {e}")
    return 2

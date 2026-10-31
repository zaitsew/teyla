"""`teyla leak` — the leak scanner every other door calls (hooks, check.sh, the agent hook).

    teyla leak [repo] [--all]        the tree (tracked files) and the local-only surfaces; --all = every repo under code_root
    teyla leak --staged              the index: `git show :path` blobs of the staged files, never the working tree
    teyla leak --outgoing [remote]   the commits (and annotated tags) the remote's tracking refs lack; default origin
    teyla leak --commits RANGE       an explicit revision range, as `scripts/leak_check.py --commits`
    teyla leak --text FILE|-         a PR body, an issue, a release note, a commit message
    teyla leak --json | --quiet | --require-gitleaks

The rules (term, email, home, secret, cyrillic) are the ones in `scripts/leak_check.py`, which this module
imports: there is one implementation. This module adds the surfaces (index, outgoing commits and tags,
publication text, `.env*` files that are not tracked, harness configs, plists, string catalogs, image
metadata), the classes (publishable, historical, local-only), the severities (blocker, triage, lang), masked
output, de-duplication, gitleaks as a second engine, and the exit code. docs/LEAK.md is the reference.

No network call: it reads git objects and files, and runs `gitleaks` (a local process) when it is installed.
Calling code uses `scan_text`, `scan_repo`, `scan_staged`, `scan_outgoing`, `scan_range`, `exit_code`, `render`.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import io
import json
import os
import plistlib
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import tomllib
import zlib
from collections import Counter
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

CLASSES = ("publishable", "historical", "local-only")
SEVERITIES = ("blocker", "triage", "lang")
ELLIPSIS = "…"
MAX_PLACES_SHOWN = 3
MAX_INFLATE = 1 << 20
DEFAULT_MAX_BYTES = 4 << 20       # one file or blob; larger ones are reported as not read (--max-bytes)
HEAD_BYTES = 8192

HARNESS_FILES = (".claude/settings.json", ".claude/settings.local.json", ".mcp.json", ".cursor/mcp.json",
                 ".vscode/tasks.json", ".codex/config.toml")
IMAGE_EXT = (".png", ".jpg", ".jpeg")
PLIST_EXT = (".plist", ".entitlements")


# --- the rules: scripts/leak_check.py, loaded once ---------------------------------------------

def _engine():
    """scripts/leak_check.py as a module: the source checkout's, else the wheel's copy (`teyla/_leak_check.py`)."""
    mod = sys.modules.get("teyla_leak_engine")
    if mod is not None:
        return mod
    here = Path(__file__).resolve()
    for cand in (here.parents[2] / "scripts" / "leak_check.py", here.parent / "_leak_check.py"):
        if cand.is_file():
            spec = importlib.util.spec_from_file_location("teyla_leak_engine", cand)
            mod = importlib.util.module_from_spec(spec)
            sys.modules["teyla_leak_engine"] = mod
            spec.loader.exec_module(mod)
            return mod
    raise RuntimeError("teyla leak: scripts/leak_check.py not found; the rules cannot load without it")


# --- findings ----------------------------------------------------------------------------------

@dataclasses.dataclass
class Finding:
    rule: str
    severity: str            # blocker | triage | lang
    cls: str                 # publishable | historical | local-only
    path: str
    line: int                # 0 when the surface has no lines (a plist value, an image tag)
    masked: str              # first two characters + … + length; a private term is `term:<index>`
    fingerprint: str         # first 12 hex of sha256(rule + path + match)
    places: list[str] = dataclasses.field(default_factory=list)
    note: str = ""
    repo: str = ""           # set by --all

    def to_dict(self) -> dict:
        d = {"rule": self.rule, "class": self.cls, "severity": self.severity, "path": self.path, "line": self.line,
             "masked": self.masked, "fingerprint": self.fingerprint, "places": list(self.places)}
        if self.note:
            d["note"] = self.note
        if self.repo:
            d["repo"] = self.repo
        return d


def mask(match: str) -> str:
    """The first two characters, an ellipsis and the length: `sk…43`."""
    return f"{match[:2]}{ELLIPSIS}{len(match)}"


_SEV_RANK = {s: i for i, s in enumerate(SEVERITIES)}
_CLS_RANK = {c: i for i, c in enumerate(CLASSES)}


class Collector:
    """Findings de-duplicated by (rule, fingerprint); every place a finding occurs is kept."""

    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str], Finding] = {}

    def add(self, rule: str, severity: str, cls: str, path: str, line: int, match: str, place: str, *,
            key: str | None = None, masked: str | None = None, note: str = "") -> None:
        fp = _engine().fingerprint(rule, path, key if key is not None else match)
        f = self.by_key.get((rule, fp))
        if f is None:
            self.by_key[(rule, fp)] = Finding(rule, severity, cls, path, line, masked or mask(match), fp, [place], note)
            return
        if place not in f.places:
            f.places.append(place)
        if _CLS_RANK[cls] < _CLS_RANK[f.cls]:           # publishable beats historical beats local-only
            f.cls, f.path, f.line = cls, path, line
        if _SEV_RANK[severity] < _SEV_RANK[f.severity]:
            f.severity = severity
        f.note = f.note or note

    def sorted(self) -> list[Finding]:
        return sorted(self.by_key.values(),
                      key=lambda f: (_SEV_RANK[f.severity], _CLS_RANK[f.cls], f.repo, f.path, f.line, f.rule))


@dataclasses.dataclass
class Coverage:
    read: list[str] = dataclasses.field(default_factory=list)
    unread: list[tuple[str, str]] = dataclasses.field(default_factory=list)   # (surface, why)
    notes: list[str] = dataclasses.field(default_factory=list)
    gitleaks_missing: bool = False
    gitleaks_why: str = ""
    # files left out on purpose (over the size cap, outside the repo, not regular): not read, so exit 2,
    # unless --allow-partial says a partial scan is acceptable
    skipped: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    def to_dict(self) -> dict:
        return {"read": self.read, "unread": [{"surface": s, "why": w} for s, w in [*self.unread, *self.skipped]],
                "notes": self.notes}


def _ident(s: str) -> str:
    return s


_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _escape(s: str) -> str:
    """Control characters (a newline in a file name) as \\xNN, so a path cannot forge output lines."""
    return _CTRL.sub(lambda m: f"\\x{ord(m.group(0)):02x}", s)


def make_scrubber(cfg) -> Callable[[str], str]:
    """A function that replaces every private term in a string with `term:<index>`. Paths, places, notes and
    error text are printed too, and a file can be named after a term. Terms of four characters or more match
    as substrings (a file `x-<term>s.txt` is still scrubbed); shorter ones keep the rule's word boundaries."""
    pats = [(i, re.compile(re.escape(t), re.I) if len(t) >= 4 else rx) for i, (t, rx) in enumerate(cfg.terms)]
    if not pats:
        return _ident

    def scrub(s: str) -> str:
        if not s:
            return s
        spans = sorted((m.start(), -m.end(), i) for i, rx in pats for m in rx.finditer(s))
        if not spans:
            return s
        out, pos = [], 0
        for a, nb, i in spans:
            if a < pos:
                continue
            out += [s[pos:a], f"term:{i}"]
            pos = -nb
        out.append(s[pos:])
        return "".join(out)

    return scrub


@dataclasses.dataclass
class Result:
    findings: list[Finding]
    coverage: Coverage
    errors: list[str] = dataclasses.field(default_factory=list)    # a malformed .leak-allow: exit 2
    scrub: Callable[[str], str] = dataclasses.field(default=_ident, repr=False, compare=False)

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocker"]


def exit_code(result: Result, require_gitleaks: bool = False, allow_partial: bool = False) -> int:
    """0: every requested surface was read and nothing blocks. 1: a blocker. 2: a surface could not be
    read, a file was skipped (unless `allow_partial`), the allow-list is malformed, or --require-gitleaks
    is unmet, and nothing blocks. A blocker outranks a coverage gap."""
    if result.blockers:
        return 1
    cov = result.coverage
    if result.errors or cov.unread or (cov.skipped and not allow_partial) or (require_gitleaks and cov.gitleaks_missing):
        return 2
    return 0


def _which(name: str) -> str | None:
    return shutil.which(name)


# --- git helpers -------------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    return _engine()._git(list(args), root)


def _git_ok(root: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=root, capture_output=True).returncode == 0


@dataclasses.dataclass
class RawEntry:
    oldmode: str
    newmode: str
    oldsha: str
    newsha: str
    status: str
    path: str


def _raw_stream(out: str):
    """("commit", sha) and ("entry", RawEntry) from `git ... -z --raw`: NUL-separated, so a path is never quoted
    or split, whatever characters it holds. (`git log` adds a `\\x01<sha>` header token before each commit.)"""
    toks = out.split("\0")
    i = 0
    while i < len(toks):
        t = toks[i].lstrip("\n")
        i += 1
        if t.startswith("\x01"):
            yield "commit", t[1:].strip()
        elif t.startswith(":"):
            f = t[1:].split()
            if len(f) >= 5 and i < len(toks):
                yield "entry", RawEntry(f[0], f[1], f[2], f[3], f[4][:1], toks[i])
                i += 1


class Oversize:
    """A blob over the size cap: its size and first bytes, never the rest."""

    def __init__(self, size: int, head: bytes) -> None:
        self.size, self.head = size, head


class BlobReader:
    """One `git cat-file --batch` process answering many requests, one at a time, so a range of commits is
    never held in memory. `get(spec, cap)` is the blob bytes, an `Oversize` over `cap`, or None."""

    def __init__(self, root: Path) -> None:
        self.p = subprocess.Popen(["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def __enter__(self) -> "BlobReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        self.p.stdout.close()
        self.p.wait()

    def get(self, spec: str, cap: int = DEFAULT_MAX_BYTES):
        if "\n" in spec:
            return None
        try:
            self.p.stdin.write(spec.encode("utf-8", "surrogateescape") + b"\n")
            self.p.stdin.flush()
            head = self.p.stdout.readline().split()
            if len(head) != 3 or head[1] != b"blob":
                return None
            size = int(head[2])
            if size > cap:
                first = self.p.stdout.read(min(size, HEAD_BYTES))
                left = size - len(first)
                while left > 0:
                    chunk = self.p.stdout.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    left -= len(chunk)
                self.p.stdout.read(1)
                return Oversize(size, first)
            data = self.p.stdout.read(size)
            self.p.stdout.read(1)
            return data
        except (OSError, ValueError):
            return None


def read_blobs(root: Path, specs: list[str], cap: int = DEFAULT_MAX_BYTES) -> list[tuple[str, "bytes | Oversize | None"]]:
    """`git cat-file --batch` over `specs` (`:path` for the index, `<sha>` for an object)."""
    if not specs:
        return []
    with BlobReader(root) as br:
        return [(spec, br.get(spec, cap)) for spec in specs]


# --- configuration -----------------------------------------------------------------------------

VISIBILITY_KEY = "teyla.visibility"
VISIBILITY_VALUES = ("public", "private")
PRIVATE_NOTE = "visibility: private (git config teyla.visibility): terms and e-mails are triage"
PUBLIC_NOTE = "visibility: public (git config teyla.visibility)"
TRIAGE_IN_PRIVATE = ("term", "email")          # Teyla's own rules; gitleaks, secrets and home paths always block


def repo_visibility(root: Path | None) -> str | None:
    """The repo's recorded visibility: `public` or `private` from the local git config value `teyla.visibility`,
    None when it is unset or holds anything else (the scanner then treats the repo as public: fail closed)."""
    if root is None:
        return None
    try:
        p = subprocess.run(["git", "-C", str(root), "config", "--get", VISIBILITY_KEY], capture_output=True, text=True,
                           timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    value = p.stdout.strip() if p.returncode == 0 else ""
    return value if value in VISIBILITY_VALUES else None


def load_config(root: Path | None):
    """The rule configuration: the private terms (env or default file) and the repo's `.leak-allow`."""
    eng = _engine()
    cfg = eng.Config()
    eng.load_terms(cfg)
    cfg.teyla = eng.is_teyla_repo(root)          # root None (a text outside a repo run): the current directory
    eng.load_allow(cfg, root)
    return cfg


# --- image metadata (struct, no pixels) --------------------------------------------------------

def exif_flags(tiff: bytes) -> list[str]:
    """`GPS` when IFD0 holds the GPS pointer (0x8825), `Artist` when it holds 0x013B."""
    if tiff[:2] == b"II":
        e = "<"
    elif tiff[:2] == b"MM":
        e = ">"
    else:
        return []
    try:
        magic, off = struct.unpack(e + "HI", tiff[2:8])
        if magic != 42:
            return []
        (n,) = struct.unpack(e + "H", tiff[off:off + 2])
        flags = []
        for i in range(min(n, 1024)):
            ent = tiff[off + 2 + 12 * i: off + 14 + 12 * i]
            if len(ent) < 12:
                break
            (tag,) = struct.unpack(e + "H", ent[:2])
            if tag == 0x8825 and "GPS" not in flags:
                flags.append("GPS")
            elif tag == 0x013B and "Artist" not in flags:
                flags.append("Artist")
        return flags
    except struct.error:
        return []


def png_chunks(data: bytes):
    """(type, body) for each chunk of a PNG, stopping at IEND or at a truncated chunk."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return
    pos = 8
    while pos + 8 <= len(data):
        n, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8: pos + 8 + n]
        if len(body) < n:
            return
        yield typ, body
        if typ == b"IEND":
            return
        pos += 12 + n


def _inflate(blob: bytes) -> tuple[bytes, str | None]:
    """The inflated bytes, up to MAX_INFLATE, and why the text may be incomplete (None when it is whole)."""
    d = zlib.decompressobj()
    try:
        out = d.decompress(blob, MAX_INFLATE)
    except zlib.error:
        return b"", "a compressed text chunk that does not inflate"
    if not d.eof:
        if len(out) >= MAX_INFLATE or d.unconsumed_tail:
            return out, f"a compressed text chunk inflates past {MAX_INFLATE} bytes"
        return out, "a compressed text chunk that ends early"
    return out, None


def png_texts(data: bytes, problems: list[str] | None = None) -> list[str]:
    """`keyword: text` for every tEXt, zTXt and iTXt chunk. A chunk that cannot be read in full adds its
    reason to `problems`: the metadata was not fully read."""
    out = []
    for typ, body in png_chunks(data):
        try:
            if typ == b"tEXt":
                kw, _, txt = body.partition(b"\0")
                out.append(f"{kw.decode('latin-1')}: {txt.decode('latin-1')}")
            elif typ == b"zTXt":
                kw, _, rest = body.partition(b"\0")
                txt, why = _inflate(rest[1:])
                if why and problems is not None:
                    problems.append(why)
                out.append(f"{kw.decode('latin-1')}: {txt.decode('latin-1')}")
            elif typ == b"iTXt":
                kw, _, rest = body.partition(b"\0")
                flag = rest[0:1]
                rest = rest[2:]
                _lang, _, rest = rest.partition(b"\0")
                _tkw, _, txt = rest.partition(b"\0")
                if flag == b"\x01":
                    txt, why = _inflate(txt)
                    if why and problems is not None:
                        problems.append(why)
                out.append(f"{kw.decode('utf-8', 'replace')}: {txt.decode('utf-8', 'replace')}")
        except (IndexError, ValueError):
            continue
    return out


def jpeg_segments(data: bytes):
    """(marker, body) for each segment before the image data starts."""
    if data[:2] != b"\xff\xd8":
        return
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            pos += 2
            continue
        if marker in (0xDA, 0xD9):
            return
        (ln,) = struct.unpack(">H", data[pos + 2:pos + 4])
        if ln < 2:
            return
        yield marker, data[pos + 4: pos + 2 + ln]
        pos += 2 + ln


def image_report(rel: str, data: bytes, problems: list[str] | None = None) -> tuple[list[str], list[str]] | None:
    """(metadata flags such as GPS and Artist, text strings to scan) for a PNG or JPEG; None when `data`
    is not one. `problems` collects the reasons the metadata was not read in full."""
    flags: list[str] = []
    texts: list[str] = []
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        texts = png_texts(data, problems)
        for typ, body in png_chunks(data):
            if typ == b"eXIf":
                flags += [f for f in exif_flags(body) if f not in flags]
        return flags, texts
    if data[:2] == b"\xff\xd8":
        for marker, body in jpeg_segments(data):
            if marker == 0xE1 and body.startswith(b"Exif\0\0"):
                flags += [f for f in exif_flags(body[6:]) if f not in flags]
            elif marker == 0xE1 and body.startswith(b"http://ns.adobe.com/xap/1.0/\0"):
                texts.append(body.decode("utf-8", "replace"))
            elif marker == 0xFE:
                texts.append(body.decode("utf-8", "replace"))
        return flags, texts
    return None


def exif_digest(data: bytes) -> str:
    """sha256 of the EXIF payload of a PNG or JPEG, so that a finding is fingerprinted by what the metadata
    holds: swapping the GPS position for another one is a new finding."""
    h = hashlib.sha256()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        for typ, body in png_chunks(data):
            if typ == b"eXIf":
                h.update(body)
    elif data[:2] == b"\xff\xd8":
        for marker, body in jpeg_segments(data):
            if marker == 0xE1 and body.startswith(b"Exif\0\0"):
                h.update(body)
    return h.hexdigest()


# --- harness configs ---------------------------------------------------------------------------

_COMMAND_KEYS = {"command", "apikeyhelper", "awsauthrefresh", "awscredentialexport", "otelheadershelper", "cmd"}
_URL_KEY_END = ("baseurl", "url", "endpoint", "uri")
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^\s'\"`<>)\]]+")
_PATHLIKE = re.compile(r"(?<![\w.:\-/})])(~/[^\s'\"|;&<>)]*|\$\{?HOME\}?/[^\s'\"|;&<>)]*|/[A-Za-z0-9._\-][^\s'\"|;&<>)]*"
                       r"|(?:\.\./)+[^\s'\"|;&<>)]*)")
_SYSTEM_PATHS = ("/bin/", "/usr/bin/", "/sbin/", "/usr/sbin/", "/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin", "/dev/tty")
_LOOPBACK = ("localhost", "::1", "0.0.0.0")


def _loopback(host: str | None) -> bool:
    return bool(host) and (host in _LOOPBACK or host.endswith(".localhost") or re.fullmatch(r"127(?:\.\d{1,3}){3}", host) is not None)


_AUTH = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*)://([^/?#]*)")


def _check_url(value: str) -> str | None:
    """The URL when it names a host that is not loopback, or whose host is interpolated (`${HOST}`: the
    place it points to is not in the file); None when it is fine."""
    m = _AUTH.match(value)
    if m is None:
        return value if value.startswith("$") else None          # a whole URL taken from the environment
    scheme, auth = m.groups()
    if scheme.lower() in ("file", "unix", "stdio"):
        return None
    hostport = auth.rsplit("@", 1)[-1]
    host = hostport[1:].split("]", 1)[0] if hostport.startswith("[") else hostport.split(":", 1)[0]
    if not host or "$" in host or "`" in host:
        return value
    return None if _loopback(host.lower()) else value


def _check_command(value: str, root: Path) -> list[str]:
    """URLs to a non-loopback host and paths outside the repo inside a command line."""
    bad = [m for m in (_check_url(u.rstrip(".,;")) for u in _URL.findall(value)) if m]
    bare = _URL.sub(" ", value)
    roots = {str(root), str(root.resolve())}

    def inside(path: str) -> bool:
        return any(path == r or path.startswith(r + os.sep) for r in roots)

    for m in _PATHLIKE.finditer(bare):
        p = m.group(1).rstrip(".,;:")
        if p.startswith(("~", "$")):
            bad.append(p)
        elif p.startswith("../"):
            if not inside(os.path.normpath(root / p)):
                bad.append(p)
        else:
            norm = os.path.normpath(p)               # `/repo/../../etc/x` and `/usr/bin/../../x` are what they resolve to
            if norm.startswith(_SYSTEM_PATHS) or norm in ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin", "/dev/tty"):
                continue
            if not inside(norm):
                bad.append(p)
    return bad


def _jsonc(text: str):
    """JSON with comments and trailing commas (a tasks.json is one)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
            out.append(c)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        else:
            out.append(c)
        i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def harness_problems(rel: str, data: bytes, root: Path) -> list[str] | None:
    """Values in a harness config that point outside the repo or at a non-loopback host; None when the
    file cannot be parsed."""
    text = data.decode("utf-8", "replace")
    try:
        obj = tomllib.loads(text) if rel.endswith(".toml") else _jsonc(text)
    except (ValueError, tomllib.TOMLDecodeError):
        return None
    bad: list[str] = []

    def walk(o, key: str = "") -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                kn = re.sub(r"[_\-]", "", str(k).lower())
                if isinstance(v, str) and kn in _COMMAND_KEYS:
                    bad.extend(_check_command(v, root))
                elif isinstance(v, list) and kn == "args" and all(isinstance(a, str) for a in v):
                    bad.extend(_check_command(" ".join(v), root))
                elif isinstance(v, str) and kn.endswith(_URL_KEY_END):
                    u = _check_url(v)
                    if u:
                        bad.append(u)
                elif isinstance(v, dict) and kn in ("env", "headers"):
                    for ek, ev in v.items():
                        if isinstance(ev, str) and _URL.match(ev):
                            u = _check_url(ev)
                            if u:
                                bad.append(u)
                else:
                    walk(v, kn)
        elif isinstance(o, list):
            for item in o:
                walk(item, key)

    walk(obj)
    return list(dict.fromkeys(bad))


def is_harness_file(rel: str) -> bool:
    return any(rel == h or rel.endswith("/" + h) for h in HARNESS_FILES)


# --- the scanner -------------------------------------------------------------------------------

def _lines(text: str):
    return enumerate(io.StringIO(text, newline=""), 1)


def _locate(raw: str, needle: str) -> int:
    """The line of `raw` holding the start of `needle`, or 0."""
    head = needle.splitlines()[0][:60] if needle.strip() else ""
    if not head:
        return 0
    for cand in (head, head.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), json.dumps(head, ensure_ascii=False)[1:-1]):
        i = raw.find(cand)
        if i >= 0:
            return raw.count("\n", 0, i) + 1
    return 0


class Scanner:
    """One repo (or none, for a text) and one configuration; each method scans one surface and adds to
    the same collector and coverage."""

    def __init__(self, root: Path | None, cfg=None, *, repo: str = "", max_bytes: int = DEFAULT_MAX_BYTES) -> None:
        self.eng = _engine()
        self.root = root
        self.cfg = cfg if cfg is not None else load_config(root)
        self.scrub = make_scrubber(self.cfg)
        self.max_bytes = max_bytes
        self.root_real = os.path.realpath(root) if root is not None else ""
        self._dir_ok: dict[str, bool] = {}
        self._big_binary = 0
        self.col = Collector()
        self.cov = Coverage()
        self.repo = repo
        self._gitleaks_noted = False
        self._tracked: set[str] | None = None
        self.visibility = repo_visibility(root)
        if self.cfg.terms_status != "ok":
            if self.cfg.terms_explicit or self.cfg.terms_status == "unreadable":
                self.cov.unread.append(("private terms", f"{self.cfg.terms_status}: {self.cfg.terms_path}"))
            else:
                self.cov.notes.append(f"no private-terms list at {self.cfg.terms_path}; the term rule did not run")
        for ex in self.cfg.expired:
            self.cov.notes.append(f"expired exception: {ex.rule} {ex.glob} (until {ex.until})")

    # -- text ---------------------------------------------------------------------------------

    def _text(self, place_label: str, gpath: str, lines, cls: str, *, lang: bool = True, cap: str | None = None,
              note: str = "", publication: bool = False) -> None:
        """`publication` marks a text that is public whatever the repo is (a PR body): the private-repo rule
        that makes terms and e-mails triage never applies to it."""
        private = self.visibility == "private" and not publication
        rules = self.eng.PathRules(gpath, self.cfg, triage=True, lang=lang)
        if rules.skip:
            return
        for no, line in lines:
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            hits = rules.hits(line)
            runs = [h for h in hits if h.rule == "cyrillic"]
            if len(runs) > 1:          # a language finding is one per line, not one per word
                hits = [h for h in hits if h.rule != "cyrillic"] + [runs[0]._replace(match="".join(h.match for h in runs))]
            for h in hits:
                sev = "triage" if cap == "triage" and h.severity == "blocker" else h.severity
                if private and sev == "blocker" and h.rule in TRIAGE_IN_PRIVATE:
                    sev = "triage"
                self.col.add(h.rule, sev, cls, gpath, no, h.match, f"{place_label}:{no}",
                             key=self.eng.fp_key(h), masked=f"term:{h.term}" if h.rule == "term" else None, note=note)

    def text(self, text: str, label: str = "<text>", cls: str = "publishable") -> None:
        """A publication text: a PR body, an issue, a release note, a commit message."""
        self._text(label, label, _lines(text), cls, publication=True)
        self.cov.read.append(f"text {label}")

    # -- one file's bytes: the shared path of the tree, the index and the commits ---------------

    def file(self, rel: str, data: bytes, cls: str, *, place: str | None = None, cap: str | None = None,
             note: str = "", keep: set[int] | None = None) -> None:
        """Scan the bytes of one file as the surfaces know it. `place` prefixes the places (`commit:ab12cd34:`).
        `keep` limits the text rules to those line numbers (the lines a commit added)."""
        pre = place or ""
        low = rel.lower()
        if low.endswith(IMAGE_EXT):
            self._image(rel, data, cls, pre)
            return
        if low.endswith(PLIST_EXT):
            self._plist(rel, data, cls, pre, cap)
        elif low.endswith(".xcstrings") and self._xcstrings(rel, data, cls, pre, cap):
            return
        if is_harness_file(rel):
            self._harness(rel, data, cls, pre, cap)
        if b"\0" in data[:HEAD_BYTES]:               # we decide what is binary, not git: .gitattributes can say -diff
            return
        lines = _lines(data.decode("utf-8", "replace"))
        if keep is not None:
            lines = [(n, ln) for n, ln in lines if n in keep]
        self._text(f"{pre}{rel}", rel, lines, cls, cap=cap, note=note)

    def _oversize(self, rel: str, size: int, head: bytes, pre: str = "") -> None:
        """A file or blob over the cap. A binary file with no structured reader would be skipped as binary at
        any size: it is counted in a note. Anything else was not read: coverage says so and the exit is 2."""
        structured = rel.lower().endswith(IMAGE_EXT + PLIST_EXT + (".xcstrings",)) or is_harness_file(rel)
        if b"\0" in head[:HEAD_BYTES] and not structured:
            self._big_binary += 1
            return
        self.cov.skipped.append((f"{pre}{rel}", f"{size} bytes, over the {self.max_bytes} byte cap (--max-bytes)"))

    def _symlink(self, rel: str, target: str, cls: str, pre: str, cap: str | None = None) -> None:
        """A symlink is its target string: scanned as text, and a target outside the repo is a finding."""
        self._text(f"{pre}{rel}", rel, _lines(target), cls, cap=cap)
        rules = self.eng.PathRules(rel, self.cfg)
        if rules.skip or rules.excepted("symlink-outside", target):
            return
        if target.startswith("~") or re.match(r"/(?:Users|home|root)(?:/|$)", target):
            sev, note = "blocker", "a symlink into a home directory: it leaks the path and, on this machine, the files"
        elif target.startswith("/"):
            sev, note = "triage", "a symlink to an absolute path outside the repo"
        else:
            joined = os.path.normpath(os.path.join(os.path.dirname(rel), target))
            if not (joined == ".." or joined.startswith("../")):
                return
            sev, note = "triage", "a symlink that points out of the repo"
        self.col.add("symlink-outside", "triage" if cap == "triage" else sev, cls, rel, 0, target, f"{pre}{rel}", note=note)

    def _image(self, rel: str, data: bytes, cls: str, pre: str) -> None:
        problems: list[str] = []
        rep = image_report(rel, data, problems)
        if rep is None:
            self.cov.notes.append(f"{rel}: not a PNG or JPEG; skipped")
            return
        flags, texts = rep
        rules = self.eng.PathRules(rel, self.cfg)
        digest = exif_digest(data)[:16] if flags else ""
        for flag in flags:
            if rules.skip or rules.excepted("image-metadata", f"{flag}:{digest}"):
                continue
            self.col.add("image-metadata", "blocker", cls, rel, 0, flag, f"{pre}{rel}", key=f"{flag}:{digest}", masked=flag,
                         note="EXIF GPS position" if flag == "GPS" else "EXIF Artist (an author name)")
        for t in texts:
            self._text(f"{pre}{rel}", rel, _lines(t), cls)
        for why in dict.fromkeys(problems):
            self.cov.unread.append((f"{pre}{rel}", f"image metadata over the read cap: {why}"))

    def _walk_strings(self, obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                yield from self._walk_strings(k)
                yield from self._walk_strings(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from self._walk_strings(v)

    def _plist(self, rel: str, data: bytes, cls: str, pre: str, cap: str | None) -> None:
        try:
            obj = plistlib.loads(data)
        except Exception:                      # plistlib raises several types for broken input
            if data[:6] == b"bplist":
                self.cov.unread.append((rel, "binary plist that plistlib cannot parse"))
            return
        raw = data.decode("utf-8", "replace") if data[:6] != b"bplist" else ""
        for s in self._walk_strings(obj):
            self._text(f"{pre}{rel}", rel, [(_locate(raw, s), ln) for ln in s.splitlines()], cls, cap=cap)

    def _xcstrings(self, rel: str, data: bytes, cls: str, pre: str, cap: str | None) -> bool:
        try:
            obj = json.loads(data)
        except ValueError:
            return False
        raw = data.decode("utf-8", "replace")
        for s in self._walk_strings(obj):
            self._text(f"{pre}{rel}", rel, [(_locate(raw, s), ln) for ln in s.splitlines()], cls, lang=False, cap=cap)
        return True

    def _harness(self, rel: str, data: bytes, cls: str, pre: str, cap: str | None) -> None:
        bad = harness_problems(rel, data, self.root or Path("/"))
        if bad is None:
            self.cov.unread.append((rel, "harness config that does not parse"))
            return
        rules = self.eng.PathRules(rel, self.cfg)
        for value in bad:
            if rules.skip or rules.excepted("harness-config", value):
                continue
            self.col.add("harness-config", "triage" if cap == "triage" else "blocker", cls, rel, 0, value, f"{pre}{rel}",
                         note="a command, URL or path outside the repo or on a non-loopback host")

    # -- tree and local-only -------------------------------------------------------------------

    def tracked(self) -> set[str]:
        if self._tracked is None:
            self._tracked = {p for p in _git(self.root, "ls-files", "-z").split("\0") if p}
        return self._tracked

    def _contained(self, d: Path) -> bool:
        """Whether the real location of directory `d` is inside the repo: a symlinked parent (`.claude`
        pointing at a home directory) is not."""
        key = str(d)
        ok = self._dir_ok.get(key)
        if ok is None:
            real = os.path.realpath(d)
            ok = real == self.root_real or real.startswith(self.root_real + os.sep)
            self._dir_ok[key] = ok
        return ok

    def _worktree_bytes(self, rel: str, cls: str, cap: str | None = None) -> bytes | None:
        """The one guarded reader of the working tree. A symlink is scanned as its target; a path that resolves
        outside the repo, a file that is not regular and a file over the cap are recorded as skipped; nothing
        large is ever read. Returns the bytes, or None when there is nothing more to scan."""
        f = self.root / rel
        try:
            st = os.lstat(f)
        except FileNotFoundError:
            return None                                      # tracked, deleted in the working tree
        except OSError:
            self.cov.unread.append((rel, "cannot be read"))
            return None
        if stat.S_ISLNK(st.st_mode):
            try:
                target = os.readlink(f)
            except OSError:
                self.cov.unread.append((rel, "symlink that cannot be read"))
                return None
            self._symlink(rel, target, cls, "", cap)
            return None
        if stat.S_ISDIR(st.st_mode):
            return None                                      # a submodule checkout
        if not stat.S_ISREG(st.st_mode):
            self.cov.skipped.append((rel, "not a regular file"))
            return None
        if not self._contained(f.parent):
            self.cov.skipped.append((rel, "resolves outside the repository (a symlinked directory)"))
            return None
        try:
            with open(f, "rb") as fh:
                data = fh.read(min(st.st_size, self.max_bytes) + 1)
        except OSError:
            self.cov.unread.append((rel, "cannot be read"))
            return None
        if len(data) > self.max_bytes:
            self._oversize(rel, max(st.st_size, len(data)), data)
            return None
        return data

    def tree(self) -> None:
        """Every tracked file in the working tree."""
        n = 0
        for rel in sorted(self.tracked()):
            data = self._worktree_bytes(rel, "publishable")
            if data is None:
                continue
            n += 1
            self.file(rel, data, "publishable")
        self.cov.read.append(f"tree ({n} tracked files)")
        self._gitleaks("tree")

    def local_only(self) -> None:
        """`.env*` files and harness configs that are present but not tracked, in ignored directories too."""
        tracked = self.tracked()
        cands = {p.name for p in self.root.glob(".env*") if p.is_file()}
        cands |= {h for h in HARNESS_FILES if (self.root / h).exists()}
        specs = [":(glob)**/.env*", *(f":(glob)**/{h}" for h in HARNESS_FILES)]
        for listing in (("--others", "--exclude-standard"), ("--others", "--ignored", "--exclude-standard")):
            for p in _git(self.root, "ls-files", "-z", *listing, "--", *specs).split("\0"):
                if p and "node_modules" not in p.split("/") and (Path(p).name.startswith(".env") or is_harness_file(p)):
                    cands.add(p)
        n = 0
        for rel in sorted(cands - tracked):
            ignored = _git_ok(self.root, "check-ignore", "-q", "--", rel)
            cap = "triage" if ignored else None
            data = self._worktree_bytes(rel, "local-only", cap)
            if data is None:
                continue
            n += 1
            note = "present only on this machine (gitignored)" if ignored else "untracked and NOT gitignored: `git add -A` would publish it"
            self.file(rel, data, "local-only", cap=cap, note=note)
        self.cov.read.append(f"local-only (.env* files and harness configs not tracked: {n})")

    # -- one blob: the shared path of the index and the commits ----------------------------------

    def _blob(self, rel: str, mode: str, data, cls: str, pre: str, keep: set[int] | None = None) -> bool:
        """Scan a blob handed back by a BlobReader. Returns whether it was read."""
        if data is None:
            self.cov.unread.append((f"{pre}{rel}", "blob could not be read"))
            return False
        if isinstance(data, Oversize):
            self._oversize(rel, data.size, data.head, pre)
            return False
        if mode == "120000":
            self._symlink(rel, data.decode("utf-8", "replace"), cls, pre)
        else:
            self.file(rel, data, cls, place=pre, keep=keep)
        return True

    # -- index ---------------------------------------------------------------------------------

    def staged(self) -> None:
        """Every index entry that differs from HEAD (any status but a deletion), read as a blob (never the
        working tree): a file, a symlink, a type change."""
        out = _git(self.root, "diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames")
        n = 0
        with BlobReader(self.root) as br:
            for kind, e in _raw_stream(out):
                if kind != "entry" or e.status == "D":
                    continue
                if e.newmode == "160000":
                    self.cov.notes.append(f"{e.path}: a submodule pointer; its content is not this repo's")
                    continue
                if e.status == "U" or set(e.newsha) == {"0"}:
                    self.cov.unread.append((e.path, "unmerged index entry"))
                    continue
                if self._blob(e.path, e.newmode, br.get(e.newsha, self.max_bytes), "publishable", ""):
                    n += 1
        self.cov.read.append(f"index ({n} staged files, read as blobs)")
        self._gitleaks("staged")

    # -- commits -------------------------------------------------------------------------------

    def _unpushed(self, revs: list[str]) -> set[str]:
        """The commits of the range that no remote-tracking ref reaches. (`--not` on the command line would
        toggle with a `--not` inside the range, so the two sets are subtracted here.)"""
        inrange = set(_git(self.root, "rev-list", *revs).split())
        if not inrange:
            return set()
        return inrange - set(_git(self.root, "rev-list", "--remotes").split())

    def commits(self, rng: str, *, label: str = "commits", all_publishable: bool = False) -> None:
        """Messages, author and committer names, the lines each commit adds, and the images, plists,
        catalogs and harness configs it adds or changes. A commit that is on a remote-tracking ref is
        `historical`: the key is already public."""
        eng = self.eng
        revs = eng.parse_range(rng)
        unpushed = None if all_publishable else self._unpushed(revs)

        def cls_of(sha: str) -> str:
            return "publishable" if unpushed is None or sha in unpushed else "historical"

        n = 0
        for sha, an, ae, cn, ce, body in eng.iter_commits(self.root, revs):
            n += 1
            c, s = cls_of(sha), sha[:8]
            self._text(f"commit:{s}:author", f"commit:{s}:author", _lines(f"{an}\n{ae}"), c)
            if (cn, ce) != (an, ae):
                self._text(f"commit:{s}:committer", f"commit:{s}:committer", _lines(f"{cn}\n{ce}"), c)
            self._text(f"commit:{s}:message", f"commit:{s}:message", _lines(body), c)
        self._commit_files(revs, cls_of)
        self.cov.read.append(f"{label} ({n} commits)")
        self._gitleaks("range", rng, cls_of)

    def _commit_files(self, revs: list[str], cls_of) -> None:
        """What each commit adds or changes, scanned from the blobs: `git log -z --raw` names the blobs with no
        path quoting, and Teyla (not git's diff, whose `-diff` attribute can hide text) decides text from binary.
        The added lines of a changed file are those its previous blob lacks."""
        out = _git(self.root, "log", "-z", "--raw", "--no-abbrev", "--no-renames", "--diff-merges=first-parent",
                   "--root", "--format=%x01%H", *revs)
        sha = ""
        with BlobReader(self.root) as br:
            for kind, e in _raw_stream(out):
                if kind == "commit":
                    sha = e
                    continue
                if e.status == "D" or e.newmode == "160000" or set(e.newsha) == {"0"}:
                    continue
                pre = f"commit:{sha[:8]}:"
                new = br.get(e.newsha, self.max_bytes)
                keep = None
                if isinstance(new, bytes) and e.status in ("M", "T") and set(e.oldsha) != {"0"} and e.oldmode not in ("120000", "160000"):
                    old = br.get(e.oldsha, self.max_bytes)
                    if isinstance(old, bytes) and b"\0" not in old[:HEAD_BYTES]:
                        seen = Counter(ln.rstrip("\r\n") for _n, ln in _lines(old.decode("utf-8", "replace")))
                        keep = set()
                        for no, ln in _lines(new.decode("utf-8", "replace")):
                            ln = ln.rstrip("\r\n")
                            if seen[ln] > 0:
                                seen[ln] -= 1
                            else:
                                keep.add(no)
                self._blob(e.path, e.newmode, new, cls_of(sha), pre, keep)

    def outgoing(self, remote: str = "origin") -> None:
        """The commits `remote`'s tracking refs lack (from HEAD), and the annotated tags on them. No network:
        run `git fetch` first when the tracking refs may be stale."""
        what = f"outgoing to {remote}"
        if _git(self.root, "rev-parse", "--is-shallow-repository").strip() == "true":
            self.cov.unread.append((what, "shallow clone: the commits the remote lacks cannot be told"))
            return
        if not _git_ok(self.root, "remote", "get-url", remote):
            self.cov.unread.append((what, f"no remote named {remote}"))
            return
        if not _git_ok(self.root, "rev-parse", "--verify", "-q", "HEAD"):
            self.cov.unread.append((what, "no commits"))
            return
        tracking = _git(self.root, "for-each-ref", "--format=%(refname)", f"refs/remotes/{remote}/").split()
        if not tracking:
            self.cov.notes.append(f"no remote-tracking refs for {remote}: every commit reachable from HEAD counts as outgoing")
        rng = f"HEAD --not --remotes={remote}"
        try:
            self.commits(rng, label=what, all_publishable=True)
        except self.eng.GitError as e:
            self.cov.unread.append((what, str(e)))
            return
        self._tags(rng)

    def _tags(self, rng: str) -> None:
        outgoing = set(_git(self.root, "rev-list", *self.eng.parse_range(rng)).split())
        n = 0
        for line in _git(self.root, "for-each-ref", "--format=%(objecttype)%09%(refname:short)%09%(*objectname)", "refs/tags").splitlines():
            kind, _, rest = line.partition("\t")
            name, _, target = rest.partition("\t")
            if kind != "tag" or target not in outgoing:
                continue
            body = _git(self.root, "cat-file", "tag", name)
            head, _, msg = body.partition("\n\n")
            tagger = "\n".join(h for h in head.splitlines() if h.startswith("tagger "))
            self._text(f"tag:{name}:tagger", f"tag:{name}:tagger", _lines(tagger[7:]), "publishable")
            self._text(f"tag:{name}:message", f"tag:{name}:message", _lines(msg), "publishable")
            n += 1
        self.cov.read.append(f"annotated tags on outgoing commits ({n})")
        self.cov.notes.append("tags on commits the remote already has were not scanned: the remote's tag list needs the network")

    # -- gitleaks, the second engine -----------------------------------------------------------

    def _no_gitleaks(self, why: str, note: str) -> None:
        self.cov.gitleaks_missing = True
        self.cov.gitleaks_why = self.cov.gitleaks_why or why
        if not self._gitleaks_noted:
            self.cov.notes.append(note)
            self._gitleaks_noted = True

    def gitleaks_text(self, text: str, label: str) -> None:
        """gitleaks over a publication text (the CLI's `--text`)."""
        self._gitleaks("text", text=text, label=label)

    def _gitleaks(self, mode: str, rng: str | None = None, cls_of=None, *, text: str = "", label: str = "") -> None:
        exe = _which("gitleaks")
        if exe is None:
            self._no_gitleaks("gitleaks is not installed",
                              "gitleaks is not installed: only Teyla's own rules ran (install it for the second engine)")
            return
        if mode == "staged" and subprocess.run([exe, "protect", "--help"], capture_output=True).returncode != 0:
            self._no_gitleaks("this gitleaks has no `protect --staged`",
                              "this gitleaks has no `protect --staged`: the index was not scanned by it")
            return
        with tempfile.TemporaryDirectory(prefix="teyla-leak-") as tmp:
            os.chmod(tmp, 0o700)
            tmpd = Path(tmp)
            stage = tmpd / "tree"
            # The repo's own .gitleaks.toml and .gitleaksignore are not read: a repo cannot switch off the second engine.
            (tmpd / "config.toml").write_text('title = "teyla"\n[extend]\nuseDefault = true\n')
            (tmpd / "ignore").write_text("")
            report = tmpd / "report.json"
            common = ["--no-banner", "--redact", "--report-format", "json", "--report-path", str(report), "--exit-code", "0",
                      "--config", str(tmpd / "config.toml"), "--gitleaks-ignore-path", str(tmpd / "ignore")]
            mb = str(max(1, -(-self.max_bytes // (1 << 20))))
            if mode == "text" and len(text.encode("utf-8", "replace")) > int(mb) << 20:
                n = len(text.encode("utf-8", "replace"))
                self.cov.gitleaks_missing = True
                self.cov.gitleaks_why = f"the text is over the engine limit ({n} bytes)"
                self.cov.notes.append(f"text over the engine limit ({n} bytes), gitleaks not run")
                return
            if mode == "tree":
                # Only the tracked files: a build directory or node_modules under the repo is not the repo.
                self._stage_tracked(stage)
                cmd = [exe, "detect", "--no-git", "--max-target-megabytes", mb, "--source", str(stage), *common]
            elif mode == "text":
                stage.mkdir()
                (stage / "text.txt").write_text(text, encoding="utf-8", errors="replace")
                cmd = [exe, "detect", "--no-git", "--max-target-megabytes", mb, "--source", str(stage), *common]
            elif mode == "staged":
                cmd = [exe, "protect", "--staged", "--source", str(self.root), *common]
            else:
                cmd = [exe, "detect", "--log-opts", rng or "", "--source", str(self.root), *common]
            p = subprocess.run(cmd, cwd=self.root or None, capture_output=True, text=True, errors="replace")
            if p.returncode != 0:
                self.cov.unread.append((f"gitleaks {mode}", (p.stderr.strip().splitlines() or ["failed"])[-1][:120]))
                return
            try:
                items = json.loads(report.read_text(encoding="utf-8") or "[]") if report.exists() else []
            except (OSError, ValueError):
                self.cov.unread.append((f"gitleaks {mode}", "report could not be read"))
                return
            br = BlobReader(self.root) if mode in ("staged", "range") else None
            try:
                self._gitleaks_items(mode, items or [], tmpd, br, cls_of, label)
            finally:
                if br is not None:
                    br.close()
        self.cov.read.append(f"gitleaks ({mode})")

    def _gl_hash(self, mode: str, tmpd: Path, br, rel: str, sha: str, start: int, end: int) -> str | None:
        """sha256 of the lines gitleaks matched. gitleaks redacts the secret and its own fingerprint leaves the
        value out, so the line is what makes a finding specific: a fixture token swapped for a live one on the
        same line is a new finding, not an exempted one."""
        if mode in ("tree", "text"):
            try:
                data = (tmpd / "tree" / rel).read_bytes()
            except OSError:
                return None
        elif mode == "staged":
            data = br.get(":" + rel, self.max_bytes)
        else:
            data = br.get(f"{sha}:{rel}", self.max_bytes)
        if not isinstance(data, bytes):
            return None
        lines = data.decode("utf-8", "replace").split("\n")
        seg = "\n".join(lines[max(start - 1, 0):max(end, start)])
        return hashlib.sha256(seg.encode("utf-8", "replace")).hexdigest()

    def _gitleaks_items(self, mode: str, items: list, tmpd: Path, br, cls_of, label: str) -> None:
        stage_prefix = str(tmpd / "tree") + os.sep
        tracked = self.tracked() if mode == "tree" else set()
        for it in items:
            rel = str(it.get("File", ""))
            for prefix in (stage_prefix, str(self.root or "") + os.sep):
                if prefix != os.sep and rel.startswith(prefix):
                    rel = rel[len(prefix):]
            if mode == "tree" and rel not in tracked:
                continue
            raw_rel = rel
            if mode == "text":
                rel = label
            rule = "gitleaks:" + str(it.get("RuleID", "unknown"))
            line = int(it.get("StartLine") or 0)
            end = int(it.get("EndLine") or line)
            sha = str(it.get("Commit") or "")
            rules = self.eng.PathRules(rel, self.cfg)
            lh = self._gl_hash(mode, tmpd, br, raw_rel, sha, line, end)
            key = f"{it.get('RuleID')}:{lh}" if lh else f"{rel}:{it.get('RuleID')}:{line}:line-unread"
            # An exception never applies to a finding whose matched text was not read: nothing ties it to a value.
            if rules.skip or not rules.sec or (lh and rules.excepted(rule, key)):
                continue
            cls = cls_of(sha) if (cls_of and sha) else "publishable"
            place = f"commit:{sha[:8]}:{rel}:{line}" if sha else f"{rel}:{line}"
            self.col.add(rule, "blocker", cls, rel, line, key, place, masked="redacted",
                         note="found by gitleaks" if lh else "found by gitleaks; line unread, so no exception applies")

    def _stage_tracked(self, stage: Path) -> None:
        """Hard links (a copy of a small file when linking fails) of the tracked regular files under `stage`
        that Teyla itself reads: the same guard, so a symlink or a file over the cap never reaches gitleaks."""
        for rel in self.tracked():
            src = self.root / rel
            try:
                st = os.lstat(src)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size > self.max_bytes or not self._contained(src.parent):
                continue
            dst = stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                try:
                    shutil.copyfile(src, dst)
                except OSError:
                    pass

    # -- result --------------------------------------------------------------------------------

    def result(self) -> Result:
        term_scrub = self.scrub

        def sc(x: str) -> str:
            return _escape(term_scrub(x))

        finds = []
        for f in self.col.sorted():
            finds.append(dataclasses.replace(f, repo=sc(self.repo), path=sc(f.path), places=[sc(x) for x in f.places],
                                             note=sc(f.note)))
        c = self.cov
        notes = list(c.notes)
        if self.visibility and any(not r.startswith("text ") for r in c.read):     # a text alone is public
            vis = PRIVATE_NOTE if self.visibility == "private" else PUBLIC_NOTE
            notes.append(f"{self.repo}: {vis}" if self.repo else vis)
        if self._big_binary:
            notes.append(f"{self._big_binary} binary file(s) over the size cap were not opened: binary files are not text-scanned")
        cov = Coverage([sc(x) for x in c.read], [(sc(a), sc(b)) for a, b in c.unread], [sc(x) for x in notes],
                       c.gitleaks_missing, c.gitleaks_why, [(sc(a), sc(b)) for a, b in c.skipped])
        return Result(finds, cov, [sc(e) for e in self.cfg.errors], term_scrub)


# --- the API other doors call ------------------------------------------------------------------

def scan_text(text: str, cfg=None, label: str = "<text>") -> list[Finding]:
    """Findings in one text (a PR body, an issue, a release note, a hook's command). `cfg` is a rule
    configuration from `load_config`; None loads the private terms from the environment or the default file."""
    sc = Scanner(None, cfg)
    sc.text(text, label)
    return sc.result().findings


def scan_repo(root: Path, cfg=None, *, local_only: bool = True) -> Result:
    sc = Scanner(root, cfg)
    sc.tree()
    if local_only:
        sc.local_only()
    return sc.result()


def scan_staged(root: Path, cfg=None) -> Result:
    sc = Scanner(root, cfg)
    sc.staged()
    return sc.result()


def scan_outgoing(root: Path, remote: str = "origin", cfg=None) -> Result:
    sc = Scanner(root, cfg)
    sc.outgoing(remote)
    return sc.result()


def scan_range(root: Path, rng: str, cfg=None) -> Result:
    sc = Scanner(root, cfg)
    sc.commits(rng)
    return sc.result()


# --- output ------------------------------------------------------------------------------------

def render(result: Result, *, require_gitleaks: bool = False, allow_partial: bool = False) -> str:
    out: list[str] = []
    lang: dict[tuple[str, str, str], list[Finding]] = {}
    for f in result.findings:
        if f.severity == "lang":                      # one line per file: a Russian doc is hundreds of lines
            lang.setdefault((f.repo, f.cls, f.path), []).append(f)
            continue
        where = f"{f.repo}:{f.path}" if f.repo else f.path
        if f.line:
            where += f":{f.line}"
        lead = "rotate first: already on the remote. " if f.cls == "historical" else ""
        out.append(f"{lead}{f.severity.upper()} {f.cls} {f.rule} {where} {f.masked} fp={f.fingerprint}")
        if f.note:
            out.append(f"    {f.note}")
        extra = [p for p in f.places if p != f"{f.path}:{f.line}"]
        if extra:
            more = f" (+{len(extra) - MAX_PLACES_SHOWN} more)" if len(extra) > MAX_PLACES_SHOWN else ""
            out.append("    also: " + ", ".join(extra[:MAX_PLACES_SHOWN]) + more)
    for (repo, cls, path), fs in lang.items():
        first = min(f.line for f in fs)
        out.append(f"LANG {cls} cyrillic {repo + ':' if repo else ''}{path}:{first} {len(fs)} line(s); `teyla lang` is the language check")
    counts = {s: sum(1 for f in result.findings if f.severity == s) for s in SEVERITIES}
    out.append(f"{counts['blocker']} blocker(s), {counts['triage']} triage, {counts['lang']} lang")
    cov = result.coverage
    for e in result.errors:
        out.append(f"error: {e}")
    out.append("coverage: read " + ("; ".join(cov.read) if cov.read else "nothing"))
    for s, why in cov.unread:
        out.append(f"coverage: NOT READ {s}: {why}")
    for s, why in cov.skipped:
        out.append(f"coverage: NOT READ {s}: {why}" + ("" if allow_partial else " (--allow-partial accepts this)"))
    if require_gitleaks and cov.gitleaks_missing:
        out.append(f"coverage: NOT READ gitleaks: --require-gitleaks was passed and {cov.gitleaks_why or 'gitleaks is not installed'}")
    for n in cov.notes:
        out.append(f"coverage: note: {n}")
    return result.scrub("\n".join(out))      # a last pass: no printed string holds a private term


def to_json(result: Result, code: int) -> str:
    doc = {"findings": [f.to_dict() for f in result.findings], "coverage": result.coverage.to_dict(),
           "errors": result.errors, "exit": code}
    return json.dumps(_scrub_values(doc, result.scrub), indent=2, ensure_ascii=False)


def _scrub_values(obj, fn):
    """`obj` with `fn` applied to every string value; keys are the schema and stay as they are."""
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, dict):
        return {k: _scrub_values(v, fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_values(v, fn) for v in obj]
    return obj


# --- CLI ---------------------------------------------------------------------------------------

def _repos_under(code_root: Path) -> list[Path]:
    if not code_root.is_dir():
        return []
    return sorted(p for p in code_root.iterdir() if p.is_dir() and (p / ".git").exists())


def _merge(results: list[Result]) -> Result:
    cov = Coverage()
    finds: list[Finding] = []
    errors: list[str] = []
    for r in results:
        finds += r.findings
        errors += r.errors
        cov.read += r.coverage.read
        cov.unread += r.coverage.unread
        cov.skipped += r.coverage.skipped
        cov.gitleaks_why = cov.gitleaks_why or r.coverage.gitleaks_why
        cov.notes += [n for n in r.coverage.notes if n not in cov.notes]
        cov.gitleaks_missing = cov.gitleaks_missing or r.coverage.gitleaks_missing
    finds.sort(key=lambda f: (_SEV_RANK[f.severity], _CLS_RANK[f.cls], f.repo, f.path, f.line, f.rule))
    return Result(finds, cov, errors, results[0].scrub if results else _ident)


def run(args) -> tuple[Result, int]:
    eng = _engine()
    if args.all:
        if args.repo or args.staged or args.outgoing or args.commits or args.text:
            raise ValueError("--all scans every repo's tree and takes no other surface or repo")
        from . import config
        parts = []
        for repo in _repos_under(config.code_root()):
            sc = Scanner(repo, None, repo=repo.name, max_bytes=args.max_bytes)
            try:
                sc.tree()
                sc.local_only()
            except eng.GitError as e:
                sc.cov.unread.append((f"{repo.name}", str(e)))
            sc.cov.read[:] = [f"{repo.name}: {r}" for r in sc.cov.read]
            sc.cov.unread[:] = [(f"{repo.name}: {s}", w) for s, w in sc.cov.unread]
            sc.cov.skipped[:] = [(f"{repo.name}: {s}", w) for s, w in sc.cov.skipped]
            parts.append(sc.result())
        if not parts:
            raise ValueError("--all: no git repo under code_root")
        res = _merge(parts)
        return res, exit_code(res, args.require_gitleaks, args.allow_partial)

    start = Path(args.repo or ".").expanduser()
    root = eng.repo_root(start) if start.exists() else None
    if args.text is None and root is None:
        raise ValueError(f"{start} is not inside a git repository")
    sc = Scanner(root, None, max_bytes=args.max_bytes)
    # A malformed .leak-allow does not stop the scan: the valid entries apply, blockers are found and reported,
    # and the config error adds exit 2 (a blocker, exit 1, outranks it).
    picked = bool(args.staged or args.outgoing or args.commits or args.text is not None)
    try:
        if args.text is not None:
            if args.text == "-":
                text, label = sys.stdin.read(), "<stdin>"
            else:
                try:
                    text, label = Path(args.text).read_text(encoding="utf-8", errors="replace"), args.text
                except OSError as e:
                    raise ValueError(f"cannot read {args.text}: {e}")
            sc.text(text, label)
            sc.gitleaks_text(text, label)
        if not picked:
            sc.tree()
            sc.local_only()
        if args.staged:
            sc.staged()
        if args.outgoing:
            sc.outgoing(args.outgoing)
        if args.commits:
            sc.commits(args.commits)
    except eng.GitError as e:
        sc.cov.unread.append(("git", str(e)))
    res = sc.result()
    return res, exit_code(res, args.require_gitleaks, args.allow_partial)


def _fallback_scrub() -> Callable[[str], str]:
    try:
        return make_scrubber(load_config(None))
    except Exception:                      # an unreadable terms file must not hide the real error
        return _ident


def cmd_leak(args) -> int:
    try:
        res, code = run(args)
    except ValueError as e:
        print(f"teyla leak: {_fallback_scrub()(str(e))}", file=sys.stderr)       # a path in the message can hold a term
        return 2
    if args.json:
        print(to_json(res, code))
    elif args.quiet:
        print(len(res.blockers))
    else:
        print(render(res, require_gitleaks=args.require_gitleaks, allow_partial=args.allow_partial))
    return code


def register(sp):
    q = sp.add_parser("leak", help="the leak scanner: tree, index, outgoing commits and publication text; private terms, e-mails, home paths, secrets")
    q.set_defaults(fn=cmd_leak)
    q.add_argument("repo", nargs="?", help="a path inside the repo to scan (default: the current directory)")
    q.add_argument("--all", action="store_true", help="every git repo under code_root: tree and local-only surfaces")
    q.add_argument("--staged", action="store_true", help="the index: the staged files read as blobs, never the working tree")
    q.add_argument("--outgoing", nargs="?", const="origin", metavar="REMOTE",
                   help="the commits (and annotated tags) the remote's tracking refs lack; default remote origin; no network")
    q.add_argument("--commits", metavar="RANGE", help="messages, authors and added lines of an explicit revision range")
    q.add_argument("--text", metavar="FILE", help="a PR body, issue or release note; - reads stdin")
    q.add_argument("--json", action="store_true", help="findings, coverage and the exit code as JSON")
    q.add_argument("--quiet", action="store_true", help="print only the number of blockers")
    q.add_argument("--require-gitleaks", action="store_true", help="exit 2 when gitleaks is missing, on any surface")
    q.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, metavar="N",
                   help=f"skip (and report as not read) a file or blob over N bytes; default {DEFAULT_MAX_BYTES}")
    q.add_argument("--allow-partial", action="store_true", help="exit 0 although files were skipped (over the cap, outside the repo)")
    return q


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="teyla leak")
    sub = ap.add_subparsers()
    register(sub)
    args = ap.parse_args(["leak", *(argv if argv is not None else sys.argv[1:])])
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

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
import importlib.util
import io
import json
import os
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib
import zlib
from pathlib import Path
from urllib.parse import urlparse

CLASSES = ("publishable", "historical", "local-only")
SEVERITIES = ("blocker", "triage", "lang")
ELLIPSIS = "…"
MAX_PLACES_SHOWN = 3
MAX_INFLATE = 1 << 20

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

    def to_dict(self) -> dict:
        return {"read": self.read, "unread": [{"surface": s, "why": w} for s, w in self.unread], "notes": self.notes}


@dataclasses.dataclass
class Result:
    findings: list[Finding]
    coverage: Coverage
    errors: list[str] = dataclasses.field(default_factory=list)    # a malformed .leak-allow: exit 2

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocker"]


def exit_code(result: Result, require_gitleaks: bool = False) -> int:
    """0: every requested surface was read and nothing blocks. 1: a blocker. 2: a surface could not be
    read (or the allow-list is malformed, or --require-gitleaks is unmet) and nothing blocks."""
    if result.blockers:
        return 1
    if result.errors or result.coverage.unread or (require_gitleaks and result.coverage.gitleaks_missing):
        return 2
    return 0


def _which(name: str) -> str | None:
    return shutil.which(name)


# --- git helpers -------------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    return _engine()._git(list(args), root)


def _git_ok(root: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=root, capture_output=True).returncode == 0


def read_blobs(root: Path, specs: list[str]) -> list[tuple[str, bytes | None]]:
    """`git cat-file --batch` over `specs` (`:path` for the index, `<sha>` for an object)."""
    if not specs:
        return []
    out: list[tuple[str, bytes | None]] = []
    p = subprocess.Popen(["git", "cat-file", "--batch"], cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL)
    assert p.stdin and p.stdout
    try:
        for spec in specs:
            if "\n" in spec:
                out.append((spec, None))
                continue
            p.stdin.write(spec.encode("utf-8") + b"\n")
            p.stdin.flush()
            head = p.stdout.readline().split()
            if len(head) != 3 or head[1] != b"blob":
                out.append((spec, None))
                continue
            size = int(head[2])
            data = p.stdout.read(size)
            p.stdout.read(1)
            out.append((spec, data))
    finally:
        p.stdin.close()
        p.wait()
    return out


# --- configuration -----------------------------------------------------------------------------

def load_config(root: Path | None):
    """The rule configuration: the private terms (env or default file) and the repo's `.leak-allow`."""
    eng = _engine()
    cfg = eng.Config()
    eng.load_terms(cfg)
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


def _inflate(blob: bytes) -> bytes:
    try:
        return zlib.decompressobj().decompress(blob, MAX_INFLATE)
    except zlib.error:
        return b""


def png_texts(data: bytes) -> list[str]:
    """`keyword: text` for every tEXt, zTXt and iTXt chunk."""
    out = []
    for typ, body in png_chunks(data):
        try:
            if typ == b"tEXt":
                kw, _, txt = body.partition(b"\0")
                out.append(f"{kw.decode('latin-1')}: {txt.decode('latin-1')}")
            elif typ == b"zTXt":
                kw, _, rest = body.partition(b"\0")
                out.append(f"{kw.decode('latin-1')}: {_inflate(rest[1:]).decode('latin-1')}")
            elif typ == b"iTXt":
                kw, _, rest = body.partition(b"\0")
                flag = rest[0:1]
                rest = rest[2:]
                _lang, _, rest = rest.partition(b"\0")
                _tkw, _, txt = rest.partition(b"\0")
                if flag == b"\x01":
                    txt = _inflate(txt)
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


def image_report(rel: str, data: bytes) -> tuple[list[str], list[str]] | None:
    """(metadata flags such as GPS and Artist, text strings to scan) for a PNG or JPEG; None when `data`
    is not one."""
    flags: list[str] = []
    texts: list[str] = []
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        texts = png_texts(data)
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


def _check_url(value: str) -> str | None:
    """The URL when it names a host that is not loopback; None when it is fine or cannot be judged."""
    if value.startswith("$") or "${" in value:
        return None
    u = urlparse(value)
    if not u.scheme or u.scheme in ("file", "unix", "stdio") or u.hostname is None:
        return None
    return None if _loopback(u.hostname) else value


def _check_command(value: str, root: Path) -> list[str]:
    """URLs to a non-loopback host and paths outside the repo inside a command line."""
    bad = [m for m in (_check_url(u.rstrip(".,;")) for u in _URL.findall(value)) if m]
    bare = _URL.sub(" ", value)
    for m in _PATHLIKE.finditer(bare):
        p = m.group(1).rstrip(".,;:")
        if p.startswith(("~", "$")) or p.startswith(_SYSTEM_PATHS):
            if p.startswith(_SYSTEM_PATHS):
                continue
            bad.append(p)
        elif p.startswith("../"):
            if not os.path.normpath(root / p).startswith(str(root) + os.sep):
                bad.append(p)
        elif not (p == str(root) or p.startswith(str(root) + os.sep)):
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

    def __init__(self, root: Path | None, cfg=None, *, repo: str = "") -> None:
        self.eng = _engine()
        self.root = root
        self.cfg = cfg if cfg is not None else load_config(root)
        self.col = Collector()
        self.cov = Coverage()
        self.repo = repo
        self._gitleaks_noted = False
        self._tracked: set[str] | None = None
        if self.cfg.terms_status != "ok":
            if self.cfg.terms_explicit or self.cfg.terms_status == "unreadable":
                self.cov.unread.append(("private terms", f"{self.cfg.terms_status}: {self.cfg.terms_path}"))
            else:
                self.cov.notes.append(f"no private-terms list at {self.cfg.terms_path}; the term rule did not run")
        for ex in self.cfg.expired:
            self.cov.notes.append(f"expired exception: {ex.rule} {ex.glob} (until {ex.until})")

    # -- text ---------------------------------------------------------------------------------

    def _text(self, place_label: str, gpath: str, lines, cls: str, *, lang: bool = True, cap: str | None = None,
              note: str = "") -> None:
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
                self.col.add(h.rule, sev, cls, gpath, no, h.match, f"{place_label}:{no}",
                             key=self.eng.fp_key(h), masked=f"term:{h.term}" if h.rule == "term" else None, note=note)

    def text(self, text: str, label: str = "<text>", cls: str = "publishable") -> None:
        """A publication text: a PR body, an issue, a release note, a commit message."""
        self._text(label, label, _lines(text), cls)
        self.cov.read.append(f"text {label}")

    # -- one file's bytes: the shared path of the tree, the index and the commits ---------------

    def file(self, rel: str, data: bytes, cls: str, *, place: str | None = None, cap: str | None = None,
             note: str = "") -> None:
        """Scan the bytes of one file as the surfaces know it. `place` prefixes the places (`commit:ab12cd34:`)."""
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
        if b"\0" in data[:8192]:
            return
        self._text(f"{pre}{rel}", rel, _lines(data.decode("utf-8", "replace")), cls, cap=cap, note=note)

    def _image(self, rel: str, data: bytes, cls: str, pre: str) -> None:
        rep = image_report(rel, data)
        if rep is None:
            self.cov.notes.append(f"{rel}: not a PNG or JPEG; skipped")
            return
        flags, texts = rep
        rules = self.eng.PathRules(rel, self.cfg)
        for flag in flags:
            if rules.skip or rules.excepted("image-metadata", flag):
                continue
            self.col.add("image-metadata", "blocker", cls, rel, 0, flag, f"{pre}{rel}", masked=flag,
                         note="EXIF GPS position" if flag == "GPS" else "EXIF Artist (an author name)")
        for t in texts:
            self._text(f"{pre}{rel}", rel, _lines(t), cls)

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

    def tree(self) -> None:
        """Every tracked file in the working tree."""
        n = 0
        for rel in sorted(self.tracked()):
            f = self.root / rel
            if f.is_symlink() or not f.is_file():
                continue
            try:
                data = f.read_bytes()
            except OSError:
                self.cov.unread.append((rel, "cannot be read"))
                continue
            n += 1
            self.file(rel, data, "publishable")
        self.cov.read.append(f"tree ({n} tracked files)")
        self._gitleaks("tree")

    def local_only(self) -> None:
        """`.env*` files and harness configs that are present but not tracked."""
        tracked = self.tracked()
        cands = {p.name for p in self.root.glob(".env*") if p.is_file()}
        cands |= {h for h in HARNESS_FILES if (self.root / h).is_file()}
        for listing in (("--others", "--exclude-standard"), ("--others", "--ignored", "--exclude-standard", "--directory")):
            for p in _git(self.root, "ls-files", "-z", *listing).split("\0"):
                if p and not p.endswith("/") and (Path(p).name.startswith(".env") or is_harness_file(p)):
                    cands.add(p)
        n = 0
        for rel in sorted(cands - tracked):
            f = self.root / rel
            if f.is_symlink() or not f.is_file():
                continue
            ignored = _git_ok(self.root, "check-ignore", "-q", "--", rel)
            try:
                data = f.read_bytes()
            except OSError:
                self.cov.unread.append((rel, "cannot be read"))
                continue
            n += 1
            note = "present only on this machine (gitignored)" if ignored else "untracked and NOT gitignored: `git add -A` would publish it"
            self.file(rel, data, "local-only", cap="triage" if ignored else None, note=note)
        self.cov.read.append(f"local-only (.env* files and harness configs not tracked: {n})")

    # -- index ---------------------------------------------------------------------------------

    def staged(self) -> None:
        """The staged files as blobs from the index (`git show :path`), never the working tree."""
        names = [p for p in _git(self.root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR").split("\0") if p]
        n = 0
        for rel, data in read_blobs(self.root, [":" + p for p in names]):
            rel = rel[1:]
            if data is None:
                self.cov.unread.append((rel, "staged blob could not be read"))
                continue
            n += 1
            self.file(rel, data, "publishable")
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
        for sha, path, lines in eng.iter_added(self.root, revs):
            self._text(f"commit:{sha[:8]}:{path}", path, lines, cls_of(sha))
        self._special_blobs(revs, cls_of)
        self.cov.read.append(f"{label} ({n} commits)")
        self._gitleaks("range", rng, cls_of)

    def _special_blobs(self, revs: list[str], cls_of) -> None:
        """Binary and structured files added or changed in the range, read from their blobs."""
        cmd = ["git", "-c", "core.quotepath=off", "log", "--raw", "--no-abbrev", "--no-renames", "--diff-filter=AM",
               "--diff-merges=first-parent", "--no-color", "--format=%x1e%H", *revs]
        p = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, errors="replace")
        if p.returncode != 0:
            self.cov.unread.append(("commit files", p.stderr.strip()))
            return
        want: list[tuple[str, str, str]] = []
        sha = ""
        for line in p.stdout.split("\n"):          # not splitlines(): it splits on \x1e too
            if line.startswith("\x1e"):
                sha = line[1:]
                continue
            m = re.match(r"^:\d+ \d+ [0-9a-f]+ ([0-9a-f]{40}) [AM]\t(.+)$", line)
            if m and set(m.group(1)) != {"0"}:
                path = m.group(2)
                low = path.lower()
                if low.endswith(IMAGE_EXT + PLIST_EXT + (".xcstrings",)) or is_harness_file(path):
                    want.append((sha, m.group(1), path))
        blobs = dict(read_blobs(self.root, sorted({b for _s, b, _p in want})))
        for sha, blob, path in want:
            data = blobs.get(blob)
            if data is None:
                self.cov.unread.append((path, f"blob in commit {sha[:8]} could not be read"))
                continue
            self._special_only(path, data, cls_of(sha), f"commit:{sha[:8]}:")

    def _special_only(self, rel: str, data: bytes, cls: str, pre: str) -> None:
        """The structured readers only: the added lines of these files are already scanned as text."""
        low = rel.lower()
        if low.endswith(IMAGE_EXT):
            self._image(rel, data, cls, pre)
        elif low.endswith(PLIST_EXT):
            self._plist(rel, data, cls, pre, None)
        elif low.endswith(".xcstrings"):
            self._xcstrings(rel, data, cls, pre, None)
        if is_harness_file(rel):
            self._harness(rel, data, cls, pre, None)

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

    def _gitleaks(self, mode: str, rng: str | None = None, cls_of=None) -> None:
        exe = _which("gitleaks")
        if exe is None:
            self.cov.gitleaks_missing = True
            if not self._gitleaks_noted:
                self.cov.notes.append("gitleaks is not installed: only Teyla's own rules ran (install it for the second engine)")
                self._gitleaks_noted = True
            return
        if mode == "staged" and subprocess.run([exe, "protect", "--help"], capture_output=True).returncode != 0:
            self.cov.notes.append("this gitleaks has no `protect --staged`: the index was not scanned by it")
            return
        with tempfile.TemporaryDirectory(prefix="teyla-leak-") as tmp:
            os.chmod(tmp, 0o700)
            tmpd = Path(tmp)
            # The repo's own .gitleaks.toml and .gitleaksignore are not read: a repo cannot switch off the second engine.
            (tmpd / "config.toml").write_text('title = "teyla"\n[extend]\nuseDefault = true\n')
            (tmpd / "ignore").write_text("")
            report = tmpd / "report.json"
            common = ["--no-banner", "--redact", "--report-format", "json", "--report-path", str(report), "--exit-code", "0",
                      "--config", str(tmpd / "config.toml"), "--gitleaks-ignore-path", str(tmpd / "ignore")]
            if mode == "tree":
                # Only the tracked files: a build directory or node_modules under the repo is not the repo.
                stage = tmpd / "tree"
                self._stage_tracked(stage)
                cmd = [exe, "detect", "--no-git", "--max-target-megabytes", "2", "--source", str(stage), *common]
            elif mode == "staged":
                cmd = [exe, "protect", "--staged", "--source", str(self.root), *common]
            else:
                cmd = [exe, "detect", "--log-opts", rng or "", "--source", str(self.root), *common]
            p = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, errors="replace")
            if p.returncode != 0:
                self.cov.unread.append((f"gitleaks {mode}", (p.stderr.strip().splitlines() or ["failed"])[-1][:120]))
                return
            try:
                items = json.loads(report.read_text(encoding="utf-8") or "[]") if report.exists() else []
            except (OSError, ValueError):
                self.cov.unread.append((f"gitleaks {mode}", "report could not be read"))
                return
            stage_prefix = str(tmpd / "tree") + os.sep
        tracked = self.tracked() if mode == "tree" else set()
        for it in items or []:
            rel = str(it.get("File", ""))
            for prefix in (stage_prefix, str(self.root) + os.sep):
                if rel.startswith(prefix):
                    rel = rel[len(prefix):]
            if mode == "tree" and rel not in tracked:
                continue
            rule = "gitleaks:" + str(it.get("RuleID", "unknown"))
            line = int(it.get("StartLine") or 0)
            sha = str(it.get("Commit") or "")
            rules = self.eng.PathRules(rel, self.cfg)
            key = f"{rel}:{it.get('RuleID')}:{line}"
            if rules.skip or not rules.sec or rules.excepted(rule, key):
                continue
            cls = cls_of(sha) if (cls_of and sha) else "publishable"
            place = f"commit:{sha[:8]}:{rel}:{line}" if sha else f"{rel}:{line}"
            self.col.add(rule, "blocker", cls, rel, line, key, place, masked="redacted", note="found by gitleaks")
        self.cov.read.append(f"gitleaks ({mode})")

    def _stage_tracked(self, stage: Path) -> None:
        """Hard links (a copy of a small file when linking fails) of the tracked files under `stage`."""
        for rel in self.tracked():
            src = self.root / rel
            if src.is_symlink() or not src.is_file():
                continue
            dst = stage / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(src, dst)
            except OSError:
                try:
                    if src.stat().st_size <= (2 << 20):
                        shutil.copyfile(src, dst)
                except OSError:
                    pass

    # -- result --------------------------------------------------------------------------------

    def result(self) -> Result:
        finds = self.col.sorted()
        for f in finds:
            f.repo = self.repo
        return Result(finds, self.cov, list(self.cfg.errors))


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

def render(result: Result, *, require_gitleaks: bool = False) -> str:
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
    if require_gitleaks and cov.gitleaks_missing:
        out.append("coverage: NOT READ gitleaks: --require-gitleaks was passed and gitleaks is not installed")
    for n in cov.notes:
        out.append(f"coverage: note: {n}")
    return "\n".join(out)


def to_json(result: Result, code: int) -> str:
    return json.dumps({"findings": [f.to_dict() for f in result.findings], "coverage": result.coverage.to_dict(),
                       "errors": result.errors, "exit": code}, indent=2, ensure_ascii=False)


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
        cov.notes += [n for n in r.coverage.notes if n not in cov.notes]
        cov.gitleaks_missing = cov.gitleaks_missing or r.coverage.gitleaks_missing
    finds.sort(key=lambda f: (_SEV_RANK[f.severity], _CLS_RANK[f.cls], f.repo, f.path, f.line, f.rule))
    return Result(finds, cov, errors)


def run(args) -> tuple[Result, int]:
    eng = _engine()
    if args.all:
        if args.repo or args.staged or args.outgoing or args.commits or args.text:
            raise ValueError("--all scans every repo's tree and takes no other surface or repo")
        from . import config
        parts = []
        for repo in _repos_under(config.code_root()):
            sc = Scanner(repo, None, repo=repo.name)
            try:
                sc.tree()
                sc.local_only()
            except eng.GitError as e:
                sc.cov.unread.append((f"{repo.name}", str(e)))
            sc.cov.read[:] = [f"{repo.name}: {r}" for r in sc.cov.read]
            sc.cov.unread[:] = [(f"{repo.name}: {s}", w) for s, w in sc.cov.unread]
            parts.append(sc.result())
        if not parts:
            raise ValueError("--all: no git repo under code_root")
        res = _merge(parts)
        return res, exit_code(res, args.require_gitleaks)

    start = Path(args.repo or ".").expanduser()
    root = eng.repo_root(start) if start.exists() else None
    if args.text is None and root is None:
        raise ValueError(f"{start} is not inside a git repository")
    sc = Scanner(root, None)
    if sc.cfg.errors:
        res = sc.result()
        return res, 2
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
    return res, exit_code(res, args.require_gitleaks)


def cmd_leak(args) -> int:
    try:
        res, code = run(args)
    except ValueError as e:
        print(f"teyla leak: {e}", file=sys.stderr)
        return 2
    if args.json:
        print(to_json(res, code))
    elif args.quiet:
        print(len(res.blockers))
    else:
        print(render(res, require_gitleaks=args.require_gitleaks))
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
    q.add_argument("--require-gitleaks", action="store_true", help="exit 2 when gitleaks is not installed")
    return q


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="teyla leak")
    sub = ap.add_subparsers()
    register(sub)
    args = ap.parse_args(["leak", *(argv if argv is not None else sys.argv[1:])])
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

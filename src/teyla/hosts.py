"""`teyla hosts` — which hosts can a repo's code reach, and does the privacy table say so?

    teyla hosts [repo...] [--all] [--write] [--json] [--quiet]

A static outbound-host inventory (docs/SHIELD.md section 5.4, decision SH9). It reads files only: no
network, no git history, nothing in the repo is executed or imported. For each repo it lists the host
literals in the code and in the manifests, by file and line, and compares them with the repo's
`docs/PRIVACY.md` table (the same shape as Teyla's own) and with `[privacy] hosts = [...]` in
`teyla.toml`. Repos are chosen as `teyla docs check` chooses them: none given means the git root of the
current directory, a name is looked up under `code_root`, a path is used as it is, `--all` is every git
repo under `code_root`. The full description is docs/HOSTS.md.

What is read:

    code        Swift, TypeScript / JavaScript, Kotlin: the content of string literals (comments are
                skipped). Python: string constants of the syntax tree (docstrings and comments are
                skipped). A `scheme://host` in a literal is a host; so are `.host = "x"`, `hostname: "x"`,
                `.host("x")` and `HTTPSConnection("x")`. A name that the code reads from the environment
                (`process.env.X_URL`, `Deno.env.get("X_URL")`, `os.environ["X_URL"]` ...) is listed as
                env-provided: its value is outside the repo.
    manifests   Info.plist (ATS exception domains, any URL value), next.config.* (`images.domains`,
                `remotePatterns`), supabase/config.toml, vercel.json, deno.json and import maps,
                Android network_security_config.xml, and the URL values of `.env.example`.

What is not read: node_modules, .build, Pods, dist, build, .venv, hidden directories, lockfiles, minified
and binary files, files over 1 MB, and tests (`tests/`, `__tests__`, `fixtures/`, `*Tests/`, `*.test.*`,
`test_*.py`). The skipped roots are named in the coverage line.

Hosts are classed before they are compared:

    ignored     placeholders (`example.com`, `example.org`, `example.net`, `example.test`, `localhost`,
                `*.local`, `*.localhost`, `*.invalid`) and XML namespaces (`www.w3.org` ...)
    local       loopback, private-range, link-local and `*.internal` hosts: listed, never a FIX
    host        everything else

Verdicts (a FIX fails the run; a WARN does not):

    FIX   undocumented   a host that no table row and no `[privacy] hosts` entry covers
    FIX   consent        a provider host whose row has an empty Consent cell, in a table that has a
                         Consent column (skipped when `[security] data = []` is declared)
    WARN  stale          a documented host that no code reaches
    WARN  todo           a row still holding "TODO (a person fills this)"
    WARN  cleartext      an `http://` URL to a non-local host, or an ATS / Android cleartext exception

A table row covers a host when the host is in the row's Host (or Where) column, either exactly or by a
wildcard suffix such as `*.supabase.co`. `--write` appends a row per undocumented host to the first
table that has a Host column (creating docs/PRIVACY.md from templates/repo/docs/PRIVACY.md when it is
missing), with "what is sent" left as TODO; it never deletes or edits a row.

Exit: 0 clean, 1 any FIX, 2 a coverage gap (no docs/PRIVACY.md and no `[privacy] hosts`; the hosts found
are listed anyway). `--quiet` prints only FIX and gap lines. Limits: a URL built at run time is missed
(it is counted as "computed"), and a grep is documentation, not control.
"""
from __future__ import annotations

import ipaddress
import json
import os
import pathlib
import plistlib
import re
import stat
import sys
import xml.etree.ElementTree as ET

from . import config, docs_check

FIX = "FIX"
WARN = "WARN"
TODO = "TODO (a person fills this)"
NOT_IN_CODE = "(not in code"
MAX_FILE_BYTES = 2_000_000
MAX_REFS_PER_HOST = 20
PRIVACY_PATH = "docs/PRIVACY.md"

SOURCE_LANG = {
    ".swift": "swift",
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "typescript", ".jsx": "typescript", ".mjs": "typescript", ".cjs": "typescript",
    ".kt": "kotlin", ".kts": "kotlin",
    ".py": "python",
}
SKIP_DIRS = {
    "node_modules", ".build", "Pods", "dist", "build", ".venv", "venv", "DerivedData", ".next", ".nuxt",
    ".turbo", ".gradle", "__pycache__", ".swiftpm", "Carthage", "vendor", ".deno", ".expo", "coverage",
    ".svelte-kit", ".vercel", ".output",
}
TEST_DIRS = {"tests", "test", "__tests__", "fixtures", "__fixtures__", "e2e"}
TEST_FILE = re.compile(
    r"(\.(test|spec)\.[A-Za-z0-9]+$)|(Tests?\.(swift|kt)$)|(^test_.*\.py$)|(_test\.py$)|(^conftest\.py$)")
SKIP_SUFFIXES = (".min.js", ".bundle.js", ".d.ts", ".lock")

PLACEHOLDER_HOSTS = {"example.com", "example.org", "example.net", "example.test", "localhost"}
PLACEHOLDER_SUFFIXES = (".local", ".localhost", ".invalid", ".example.com", ".example.org", ".example.net")
NAMESPACE_HOSTS = {
    "www.w3.org", "schemas.android.com", "schemas.microsoft.com", "json-schema.org", "ns.adobe.com",
    "purl.org", "xmlns.com", "schemas.xmlsoap.org", "www.sitemaps.org",
}
# Model and speech providers. A row for one of these needs a Consent cell when the table has that column.
PROVIDER_HOSTS = (
    "api.openai.com", "*.openai.azure.com", "api.anthropic.com", "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com", "api.x.ai", "api.mistral.ai", "api.cohere.com", "api.groq.com",
    "api.deepseek.com", "api.perplexity.ai", "openrouter.ai", "api.together.xyz", "api.replicate.com",
    "api.elevenlabs.io",
)
FILE_TLDS = {"toml", "json", "md", "py", "swift", "txt", "sh", "yaml", "yml", "plist", "ts", "js", "html",
             "css", "xml", "lock", "kt", "png", "jpg", "csv", "log", "cfg", "ini", "env", "mjs", "tsx"}

# A documented token whose last label is not a TLD (`mascot.model`, a config key written in prose) is not
# reported as a stale row. Two-letter labels are country codes and always count.
KNOWN_TLDS = {"com", "org", "net", "io", "ai", "dev", "app", "co", "edu", "gov", "info", "biz", "xyz", "cloud",
              "tech", "online", "site", "store", "page", "run", "so", "sh", "fm", "tv", "me", "cc", "ly", "gg",
              "apple", "google", "page", "wiki", "blog", "link", "live", "studio", "network", "systems", "today",
              "world", "zone", "email", "chat", "social", "digital", "media", "software", "tools", "works", "test"}

_LABEL = r"[a-z0-9_](?:[a-z0-9_-]*[a-z0-9_])?"
_HOST = re.compile(rf"^(?:\*\.)?(?:{_LABEL}\.)+(?:[a-z]{{2,}}|xn--[a-z0-9-]+)$")
_URL = re.compile(r"(?i)\b(?:https?|wss?)://([^\s/?#\"'`\\<>]*)")
_SCHEME = re.compile(r"(?i)\b(https?|wss?)://")
_MARK = "\x00"
_ENV_NAME = r"[A-Z0-9_]*(?:URL|URI|HOST|ENDPOINT)"


# --- hosts ---------------------------------------------------------------------------------------------

def normalize(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    if host.startswith("**."):
        host = host[1:]
    return host


def valid_host(host: str) -> bool:
    return bool(_HOST.match(host))


def _ip(host: str):
    try:
        return ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None


def classify(host: str, url_tail: str = "") -> str:
    """'ignore' (placeholder or namespace), 'local' (loopback / private), 'host', or 'bad' (not a host)."""
    ip = _ip(host)
    if ip is not None:
        return "local" if (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified) else "host"
    bare = host[2:] if host.startswith("*.") else host
    if not valid_host(host) and bare != "localhost":
        return "bad"
    if bare in PLACEHOLDER_HOSTS or bare.endswith(PLACEHOLDER_SUFFIXES):
        return "ignore"
    if host in NAMESPACE_HOSTS or (bare == "www.apple.com" and "/DTDs/" in url_tail):
        return "ignore"
    if bare.endswith(".internal"):
        return "local"
    return "host"


def host_from_authority(auth: str):
    """The host of a URL authority, or None when it is computed at run time. A marker (an interpolation)
    in the first label becomes a wildcard: `<marker>.supabase.co` is `*.supabase.co`."""
    host = auth.rsplit("@", 1)[-1]
    if host.startswith("["):
        host = host.split("]")[0] + "]"
    else:
        host = host.split(":", 1)[0]
    host = normalize(host.replace(_MARK, "*"))
    if "*" not in host:
        return host or None
    labels = host.split(".")
    if len(labels) < 3 or any("*" in lab for lab in labels[1:]):
        return None
    return "*." + ".".join(labels[1:])


def covers(pattern: str, host: str) -> bool:
    """Does a documented pattern cover a host? Exact, or a wildcard suffix (`*.x.com` covers `x.com`).
    A wildcard the code reaches (`*.x.com`) is covered only by a documented wildcard, never by one instance."""
    if pattern == host:
        return True
    if not pattern.startswith("*."):
        return False
    if host.startswith("*."):
        return host[1:].endswith(pattern[1:])
    return host == pattern[2:] or host.endswith(pattern[1:])


def reaches(pattern: str, host: str) -> bool:
    """Could code that reaches `host` be what a row documents? (For the stale check: a concrete row is not
    stale when the code reaches a wildcard that includes it.)"""
    if covers(pattern, host):
        return True
    return host.startswith("*.") and not pattern.startswith("*.") and pattern.endswith(host[1:])


class Ref:
    __slots__ = ("file", "line", "how", "scheme")

    def __init__(self, file: str, line: int, how: str, scheme: str = ""):
        self.file, self.line, self.how, self.scheme = file, line, how, scheme

    def asdict(self) -> dict:
        return {"file": self.file, "line": self.line, "how": self.how}


class Scan:
    """Everything one repo's files say."""

    def __init__(self):
        self.hosts: dict[str, list[Ref]] = {}
        self.local: dict[str, list[Ref]] = {}
        self.env: dict[tuple[str, str], int] = {}
        self.notes: list[dict] = []               # cleartext / ATS findings that are not about one host
        self.computed = 0
        self.files = 0
        self.by_lang: dict[str, int] = {}
        self.manifests: list[str] = []
        self.skipped_roots: set[str] = set()
        self.test_files = 0
        self.errors: list[str] = []
        self.unread: list[str] = []               # files refused by the guarded reader, with the reason
        self._seen: set = set()

    def add(self, host: str, ref: Ref, url_tail: str = "") -> None:
        kind = classify(host, url_tail)
        if kind in ("ignore", "bad"):
            return
        key = (host, ref.file, ref.line)
        if key in self._seen:
            return
        self._seen.add(key)
        bucket = self.local if kind == "local" else self.hosts
        refs = bucket.setdefault(host, [])
        if len(refs) < MAX_REFS_PER_HOST:
            refs.append(ref)
        if kind == "host" and ref.scheme in ("http", "ws"):
            self.notes.append({"check": "cleartext", "host": host, "file": ref.file, "line": ref.line,
                               "message": f"{host} is reached over {ref.scheme}:// (no TLS)",
                               "fix": "use https:// (or wss://), or document why the host cannot"})

    def add_text(self, text: str, base_line: int, file: str, how: str) -> None:
        """Every URL in a piece of text (a string literal, a JSON value, an env value)."""
        for m in _SCHEME.finditer(text):
            tail = text[m.end():m.end() + 40]
            auth = _URL.match(text, m.start()).group(1)
            host = host_from_authority(auth)
            line = base_line + text.count("\n", 0, m.start())
            if host is None or not auth:
                self.computed += 1
                continue
            self.add(host, Ref(file, line, how, m.group(1).lower()), tail)


# --- reading -------------------------------------------------------------------------------------------

def read_bytes(path: pathlib.Path, scan: "Scan | None" = None, rel: str = ""):
    """The one reader. It never follows a symlink, reads only regular files, and stops at MAX_FILE_BYTES.
    A refusal is recorded in the coverage (`unread`) so a skipped file is never silent."""
    def refuse(why: str):
        if scan is not None and len(scan.unread) < 50:
            scan.unread.append(f"{rel or path.name}: {why}")
        return None
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return refuse("not a regular file")
        if st.st_size > MAX_FILE_BYTES:
            return refuse(f"over {MAX_FILE_BYTES // 1_000_000} MB")
        with os.fdopen(fd, "rb") as f:
            fd = None
            data = f.read(MAX_FILE_BYTES + 1)
    except OSError as e:
        return refuse("symlink" if getattr(e, "errno", None) in (40, 62) else "unreadable")
    finally:
        if fd is not None:
            os.close(fd)
    if len(data) > MAX_FILE_BYTES:
        return refuse(f"over {MAX_FILE_BYTES // 1_000_000} MB")
    return data


def read_text(path: pathlib.Path, scan: "Scan | None" = None, rel: str = ""):
    data = read_bytes(path, scan, rel)
    if data is None or b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


def line_of(text: str, needle: str) -> int:
    i = text.find(needle)
    return text.count("\n", 0, i) + 1 if i >= 0 else 0


def _lines_without_comments(text: str) -> list[tuple[int, str]]:
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        s = line.lstrip()
        if s.startswith(("//", "/*", "*", "#")):
            continue
        out.append((n, line))
    return out


_INTERP = re.compile(r"\$\{[^{}\n]*\}|\\\((?:[^()\n]|\([^()\n]*\))*\)|\$[A-Za-z_][A-Za-z0-9_]*")
_ESCAPE = re.compile(r"\\/|\\x([0-9a-fA-F]{2})|\\u([0-9a-fA-F]{4})|\\u\{([0-9a-fA-F]{1,6})\}")


def _unescape(m: "re.Match") -> str:
    hexa = m.group(1) or m.group(2) or m.group(3)
    if hexa is None:
        return "/"
    code = int(hexa, 16)
    return chr(code) if code <= 0x10FFFF else m.group(0)   # `\u{110000}` is valid source, not a character


def code_line_text(line: str) -> str:
    """A source line with string escapes decoded (`\\/`, `\\x2f`, `\\u002f`) and interpolations replaced by a
    marker, so a URL written as an escaped literal or with a computed first label is still seen."""
    return _ESCAPE.sub(_unescape, _INTERP.sub(_MARK, line))


_BARE = {
    "swift": [re.compile(r"""\.host\s*=\s*"([^"\\]+)\"""")],
    "typescript": [re.compile(r"""\bhost(?:name)?\s*:\s*["']([^"'\\]+)["']""")],
    "kotlin": [re.compile(r"""\.host\(\s*"([^"\\]+)"\s*\)"""), re.compile(r"""\bhost\s*=\s*"([^"\\]+)\"""")],
    "python": [re.compile(r"""\bHTTPS?Connection\(\s*["']([^"'\\]+)["']""")],
}
_ENV = {
    "swift": [re.compile(rf"""environment\[\s*"({_ENV_NAME})"\s*\]""")],
    "typescript": [re.compile(rf"""process\.env\.({_ENV_NAME})\b"""),
                   re.compile(rf"""process\.env\[\s*["']({_ENV_NAME})["']\s*\]"""),
                   re.compile(rf"""Deno\.env\.get\(\s*["']({_ENV_NAME})["']"""),
                   re.compile(rf"""import\.meta\.env\.({_ENV_NAME})\b""")],
    "kotlin": [re.compile(rf"""System\.getenv\(\s*"({_ENV_NAME})"\s*\)""")],
    "python": [re.compile(rf"""os\.environ(?:\.get\(|\[)\s*["']({_ENV_NAME})["']"""),
               re.compile(rf"""os\.getenv\(\s*["']({_ENV_NAME})["']""")],
}


def scan_source(scan: Scan, rel: str, text: str, lang: str) -> None:
    skip: set[int] = set()
    if lang == "python":
        skip = _scan_python(scan, rel, text)
    for n, ln in _lines_without_comments(text):
        if n in skip:
            continue
        if lang != "python":
            # No quote tracking: a regex literal such as /"/ would hide the next real string. A line that
            # starts with a comment token is skipped; a URL in a trailing comment is over-reported on purpose.
            scan.add_text(code_line_text(ln), n, rel, "literal")
        for rx in _BARE[lang]:
            for m in rx.finditer(ln):
                host = normalize(m.group(1))
                if valid_host(host) and host.rsplit(".", 1)[-1] not in FILE_TLDS:
                    scan.add(host, Ref(rel, n, "host assignment"))
        for rx in _ENV[lang]:
            for m in rx.finditer(ln):
                scan.env.setdefault((m.group(1), rel), n)


def _scan_python(scan: Scan, rel: str, text: str) -> set[int]:
    """Scan the string constants; return the lines of docstrings (the regex scans skip them)."""
    import ast
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        for n, ln in _lines_without_comments(text):
            scan.add_text(ln, n, rel, "literal")
        return set()
    docs, doc_lines = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
                doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            docs.update(id(v) for v in node.values)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            scan.add_text(node.value, node.lineno, rel, "literal")
        elif isinstance(node, ast.JoinedStr):
            parts = [v.value if isinstance(v, ast.Constant) else _MARK for v in node.values]
            scan.add_text("".join(str(p) for p in parts), node.lineno, rel, "literal")
    return doc_lines


# --- manifests -----------------------------------------------------------------------------------------

def scan_plist(scan: Scan, rel: str, path: pathlib.Path) -> None:
    blob = read_bytes(path, scan, rel)
    if blob is None:
        return
    try:
        data = plistlib.loads(blob)
    except (plistlib.InvalidFileException, ValueError, ET.ParseError):
        scan.errors.append(f"{rel}: not a readable plist")
        return
    raw = blob.decode("utf-8", errors="replace") if blob[:6] != b"bplist" else ""
    ats = data.get("NSAppTransportSecurity") if isinstance(data, dict) else None
    if isinstance(ats, dict):
        if ats.get("NSAllowsArbitraryLoads") is True:
            scan.notes.append({"check": "cleartext", "host": "", "file": rel,
                               "line": line_of(raw, "NSAllowsArbitraryLoads"),
                               "message": "NSAllowsArbitraryLoads is true: App Transport Security is off for every host",
                               "fix": "remove it and list the one domain that needs an exception"})
        exceptions = ats.get("NSExceptionDomains")
        for domain, rules in (exceptions.items() if isinstance(exceptions, dict) else []):
            host = normalize(domain)
            scan.add(host, Ref(rel, line_of(raw, domain), "ATS exception"))
            if isinstance(rules, dict) and rules.get("NSExceptionAllowsInsecureHTTPLoads") is True:
                scan.notes.append({"check": "cleartext", "host": host, "file": rel, "line": line_of(raw, domain),
                                   "message": f"{host} is allowed over plain HTTP by an ATS exception",
                                   "fix": "serve it over HTTPS and drop NSExceptionAllowsInsecureHTTPLoads"})
    for value in _walk_strings(data):
        scan.add_text(value, line_of(raw, value[:40]) or 1, rel, "plist value")


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk_strings(v)


def scan_json(scan: Scan, rel: str, text: str, how: str) -> None:
    try:
        values = list(_walk_strings(json.loads(text)))
    except ValueError:
        values = [ln for _, ln in _lines_without_comments(text)]
    for v in values:
        if _SCHEME.search(v):
            scan.add_text(v, 0, rel, how)
    _fill_lines(scan, rel, text)


def _fill_lines(scan: Scan, rel: str, text: str) -> None:
    """Manifest values carry no line; find the first line that holds the host."""
    for bucket in (scan.hosts, scan.local):
        for host, refs in bucket.items():
            for r in refs:
                if r.file == rel and r.line == 0:
                    r.line = line_of(text, host.lstrip("*.")) or 1


def scan_toml(scan: Scan, rel: str, text: str) -> None:
    try:
        import tomllib
        values = list(_walk_strings(tomllib.loads(text)))
    except ValueError:
        values = [ln for _, ln in _lines_without_comments(text)]
    for v in values:
        if _SCHEME.search(v):
            scan.add_text(v, 0, rel, "supabase config")
    _fill_lines(scan, rel, text)


_NEXT_DOMAINS = re.compile(r"\bdomains\s*:\s*\[([^\]]*)\]")
_NEXT_HOSTNAME = re.compile(r"""\bhostname\s*:\s*["']([^"']+)["']""")
_QUOTED = re.compile(r"""["']([^"']+)["']""")


def scan_next_config(scan: Scan, rel: str, text: str) -> None:
    for m in _NEXT_DOMAINS.finditer(text):
        base = text.count("\n", 0, m.start()) + 1
        for q in _QUOTED.finditer(m.group(1)):
            scan.add(normalize(q.group(1)), Ref(rel, base + m.group(1).count("\n", 0, q.start()), "images.domains"))
    for m in _NEXT_HOSTNAME.finditer(text):
        scan.add(normalize(m.group(1)), Ref(rel, text.count("\n", 0, m.start()) + 1, "images.remotePatterns"))


def scan_android_network(scan: Scan, rel: str, text: str) -> None:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        scan.errors.append(f"{rel}: not readable XML")
        return
    for dom in root.iter("domain"):
        host = normalize(dom.text or "")
        if not host:
            continue
        line = line_of(text, host)
        scan.add(host, Ref(rel, line, "network_security_config"))
    for el in root.iter():
        if el.get("cleartextTrafficPermitted") == "true":
            doms = [normalize(d.text or "") for d in el.iter("domain")]
            scan.notes.append({"check": "cleartext", "host": ",".join(d for d in doms if d), "file": rel,
                               "line": line_of(text, "cleartextTrafficPermitted"),
                               "message": "cleartext traffic is permitted" + (f" for {', '.join(d for d in doms if d)}" if doms else " by default"),
                               "fix": "serve the host over HTTPS and remove the cleartext exception"})


def scan_env_example(scan: Scan, rel: str, text: str) -> None:
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        value = s.split("=", 1)[1].strip().strip("\"'")
        if _SCHEME.search(value):
            scan.add_text(value, n, rel, "env-provided")


def scan_manifest(scan: Scan, rel: str, path: pathlib.Path) -> bool:
    name = path.name
    if name.startswith("Info") and name.endswith(".plist"):
        scan_plist(scan, rel, path)
        return True
    text = read_text(path, scan, rel)
    if text is None:
        return False
    if re.fullmatch(r"next\.config\.(js|mjs|cjs|ts|mts)", name):
        scan_next_config(scan, rel, text)
        return True
    if rel.endswith("supabase/config.toml"):
        scan_toml(scan, rel, text)
        return True
    if name == "vercel.json":
        scan_json(scan, rel, text, "vercel.json")
        return True
    if name in ("deno.json", "deno.jsonc", "import_map.json"):
        scan_json(scan, rel, text, "deno imports")
        return True
    if name == "network_security_config.xml":
        scan_android_network(scan, rel, text)
        return True
    if name == ".env.example":
        scan_env_example(scan, rel, text)
        return True
    return False


# --- the walk ------------------------------------------------------------------------------------------

def is_test_dir(name: str) -> bool:
    return name.lower() in TEST_DIRS or name.endswith("Tests")


def scan_repo_files(root: pathlib.Path) -> Scan:
    scan = Scan()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = pathlib.Path(dirpath)
        keep = []
        for d in sorted(dirnames):
            rel_d = (here / d).relative_to(root).as_posix()
            if d in SKIP_DIRS or is_test_dir(d):
                scan.skipped_roots.add(rel_d)
            elif d.startswith(".") or (here / d).is_symlink():
                continue
            else:
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            path = here / f
            rel = path.relative_to(root).as_posix()
            if f.endswith(SKIP_SUFFIXES):
                continue
            if scan_manifest_candidate(f, rel):
                if scan_manifest(scan, rel, path):
                    scan.manifests.append(rel)
                    continue
            lang = SOURCE_LANG.get(path.suffix)
            if not lang:
                continue
            if TEST_FILE.search(f):
                scan.test_files += 1
                continue
            text = read_text(path, scan, rel)
            if text is None:
                continue
            scan.files += 1
            scan.by_lang[lang] = scan.by_lang.get(lang, 0) + 1
            if re.fullmatch(r"next\.config\.(js|mjs|cjs|ts|mts)", f):
                scan_manifest(scan, rel, path)
                scan.manifests.append(rel)
            scan_source(scan, rel, text, lang)
    return scan


def scan_manifest_candidate(name: str, rel: str) -> bool:
    if re.fullmatch(r"next\.config\.(js|mjs|cjs|ts|mts)", name):
        return False                          # also a source file: handled in the source branch
    return (name.startswith("Info") and name.endswith(".plist")) or rel.endswith("supabase/config.toml") \
        or name in ("vercel.json", "deno.json", "deno.jsonc", "import_map.json", "network_security_config.xml",
                    ".env.example")


# --- the privacy table ---------------------------------------------------------------------------------

class Row:
    def __init__(self, line: int, hosts: list[str], cells: list[str], consent: str | None, todo: bool, heading: str,
                 no_code: bool = False):
        self.line, self.hosts, self.cells, self.consent, self.todo, self.heading = line, hosts, cells, consent, todo, heading
        self.no_code = no_code                # "(not in code": reached by a tool or SDK, so never stale


class Table:
    def __init__(self, header: list[str], start: int):
        self.header, self.start = header, start
        self.rows: list[Row] = []
        self.end = start                      # 1-based line of the last row
        self.host_col = None
        for words in (r"hosts?", r"where|domains?|destinations?|endpoints?|server"):    # "Host" beats "Where"
            self.host_col = next((i for i, h in enumerate(header) if re.match(rf"(?i)({words})\b", h)), None)
            if self.host_col is not None:
                break
        self.consent_col = next((i for i, h in enumerate(header) if "consent" in h.lower()), None)


def _cells(line: str) -> list[str]:
    s = line.strip().replace("\\|", "\x01")
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.replace("\x01", "|").strip() for c in s.split("|")]


def hosts_in(cell: str, reached: frozenset = frozenset()) -> list[str]:
    """Host tokens of a table cell: names, wildcards, IP addresses, and the host of a URL. A token that ends
    like a file name (`check.sh`) counts only when the code reaches it."""
    found = []
    tokens = re.findall(r"`([^`]+)`|((?:https?|wss?)://[^\s`,;)]+)|((?:\d{1,3}\.){3}\d{1,3})(?![\w.])"
                        r"|([A-Za-z0-9*][A-Za-z0-9*._-]*\.[A-Za-z]{2,})", cell)
    for tok in tokens:
        for t in tok:
            if not t:
                continue
            t = t.strip()
            if _SCHEME.match(t):
                t = host_from_authority(_URL.match(t).group(1)) or ""
            elif ":" in t and "." not in t.split("/")[0] and _ip(t.strip("[]")) is not None:
                t = "[" + t.strip("[]") + "]"
            t = normalize(t.strip("*") if t.startswith("**") else t)
            if not t:
                continue
            if _ip(t) is not None:
                found.append(t)
            elif valid_host(t) and (t.rsplit(".", 1)[-1] not in FILE_TLDS or t in reached):
                found.append(t)
    return list(dict.fromkeys(found))


def parse_tables(text: str, reached: frozenset = frozenset()) -> list[Table]:
    lines = text.splitlines()
    tables: list[Table] = []
    heading = ""
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("#"):
            heading = ln.lstrip("#").strip()
        if ln.lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            t = Table(_cells(ln), i + 1)
            t.end = i + 2
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                cells = _cells(lines[j])
                hosts = hosts_in(cells[t.host_col], reached) if t.host_col is not None and t.host_col < len(cells) else []
                consent = cells[t.consent_col] if t.consent_col is not None and t.consent_col < len(cells) else None
                t.rows.append(Row(j + 1, hosts, cells, consent, "TODO (a person fills this)" in lines[j], heading,
                                  NOT_IN_CODE in lines[j]))
                t.end = j + 1
                j += 1
            tables.append(t)
            i = j
            continue
        i += 1
    return tables


def read_toml(path: pathlib.Path, scan: "Scan | None" = None, rel: str = "") -> dict:
    text = read_text(path, scan, rel) if os.path.lexists(path) else None
    if text is None:
        return {}
    try:
        import tomllib
        return tomllib.loads(text)
    except ValueError:
        return {}


def _tld_ok(host: str) -> bool:
    tld = host.rsplit(".", 1)[-1]
    return len(tld) == 2 or tld in KNOWN_TLDS


def is_provider(host: str) -> bool:
    return any(covers(p, host) for p in PROVIDER_HOSTS)


# --- the check -----------------------------------------------------------------------------------------

def check_repo(root: pathlib.Path) -> dict:
    root = root.resolve()
    scan = scan_repo_files(root)
    privacy_file = root / PRIVACY_PATH
    privacy_text = None
    if os.path.lexists(privacy_file):
        if (root / "docs").is_symlink():
            # a symlinked docs/ could hand us someone else's table and silence findings
            if len(scan.unread) < 50:
                scan.unread.append(f"{PRIVACY_PATH}: docs is a symlink, table ignored")
        else:
            privacy_text = read_text(privacy_file, scan, PRIVACY_PATH)
    tables = parse_tables(privacy_text, frozenset(scan.hosts) | frozenset(scan.local)) if privacy_text is not None else []
    toml = read_toml(root / "teyla.toml", scan, "teyla.toml")
    conf_hosts = [normalize(h) for h in (toml.get("privacy") or {}).get("hosts", []) if isinstance(h, str)]
    has_config = bool(conf_hosts) or "hosts" in (toml.get("privacy") or {})
    gap = privacy_text is None and not has_config

    doc: list[tuple[str, str, int, bool]] = []            # (pattern, file, line, may be stale)
    for t in tables:
        for r in t.rows:
            doc += [(h, PRIVACY_PATH, r.line, not r.no_code and _tld_ok(h)) for h in r.hosts if classify(h) == "host"]
    doc += [(h, "teyla.toml", 0, True) for h in conf_hosts if classify(h) == "host"]
    patterns = [d[0] for d in doc]

    findings: list[dict] = []

    def add(check, sev, host, file, line, message, fix):
        findings.append({"check": check, "severity": sev, "host": host, "file": file, "line": line,
                         "message": message, "fix": fix})

    if gap:
        add("coverage-gap", "GAP", "", PRIVACY_PATH, 0,
            f"no {PRIVACY_PATH} and no [privacy] hosts in teyla.toml: nothing to compare {len(scan.hosts)} host(s) with",
            f"run `teyla hosts {root.name} --write` to create {PRIVACY_PATH}, then fill in the rows")
    else:
        for host in sorted(scan.hosts):
            if not any(covers(p, host) for p in patterns):
                ref = scan.hosts[host][0]
                add("undocumented", FIX, host, ref.file, ref.line, f"{host} is reached but not documented",
                    f"add a row to {PRIVACY_PATH}: what is sent, when, how to turn it off")
        for pattern, file, line, may_be_stale in doc:
            if may_be_stale and not any(reaches(pattern, h) for h in scan.hosts):
                add("stale", WARN, pattern, file, line, f"{pattern} is documented but no code reaches it (stale row)",
                    "delete the row, or the host is reached in a way this scan cannot see: say so in the row")
        for t in tables:
            for r in t.rows:
                if r.todo:
                    add("todo", WARN, ",".join(r.hosts), PRIVACY_PATH, r.line, "row still holds TODO",
                        "a person fills in what is sent, when, and how to turn it off")
        security = toml.get("security") if isinstance(toml.get("security"), dict) else {}
        data_declared_empty = "data" in security and not security.get("data")
        if not data_declared_empty:
            for t in tables:
                if t.consent_col is None:
                    continue
                for r in t.rows:
                    empty = (r.consent or "").strip().strip("*_`").lower() in ("", "-", "—", "–", "none", "n/a", "todo")
                    for h in r.hosts:
                        if is_provider(h) and empty:
                            add("consent", FIX, h, PRIVACY_PATH, r.line, f"{h} is a provider host with an empty Consent cell",
                                "say what the user agrees to, and where, in the Consent column")
    for note in scan.notes:
        add(note["check"], WARN, note["host"], note["file"], note["line"], note["message"], note["fix"])

    findings.sort(key=lambda f: ({FIX: 0, "GAP": 1, WARN: 2}[f["severity"]], f["file"], f["line"], f["host"]))
    documented = sorted({h for h in scan.hosts if any(covers(p, h) for p in patterns)})
    return {
        "repo": root.name,
        "path": str(root),
        "hosts": [{"host": h, "refs": [r.asdict() for r in refs], "documented": h in documented}
                  for h, refs in sorted(scan.hosts.items())],
        "local": [{"host": h, "refs": [r.asdict() for r in refs]} for h, refs in sorted(scan.local.items())],
        "env_provided": [{"name": n, "file": f, "line": ln} for (n, f), ln in sorted(scan.env.items())],
        "findings": findings,
        "coverage": {
            "files": scan.files, "by_language": dict(sorted(scan.by_lang.items())),
            "manifests": sorted(scan.manifests), "skipped_roots": sorted(scan.skipped_roots),
            "test_files_skipped": scan.test_files, "computed_urls": scan.computed,
            "privacy_table": privacy_text is not None, "config_hosts": len(conf_hosts),
            "errors": scan.errors, "unread": scan.unread,
        },
    }


def counts(report: dict) -> dict:
    c = {FIX: 0, WARN: 0, "GAP": 0}
    for f in report["findings"]:
        c[f["severity"]] += 1
    return c


def exit_code(reports: list[dict]) -> int:
    tot = [counts(r) for r in reports]
    if any(t[FIX] for t in tot):
        return 1
    return 2 if any(t["GAP"] for t in tot) else 0


# --- --write -------------------------------------------------------------------------------------------

def _row_for(header: list[str], number: int, host: str, ref: dict) -> str:
    cells = []
    for h in header:
        hl = h.lower()
        if hl.strip() == "#":
            cells.append(str(number))
        elif re.match(r"(host|hosts|where|domain|domains|destination|endpoint|endpoints|server)\b", hl):
            cells.append(f"`{host}`")
        elif "trigger" in hl:
            cells.append(f"Found in `{ref['file']}:{ref['line']}` by `teyla hosts`; {TODO}")
        else:
            cells.append(TODO)
    return "| " + " | ".join(cells) + " |"


class WriteRefused(Exception):
    """--write will not touch this path; the message says why."""


def safe_write_target(root: pathlib.Path) -> pathlib.Path:
    """docs/PRIVACY.md inside the repo, reached without a symlink. Raises WriteRefused otherwise."""
    root = root.resolve()
    docs, path = root / "docs", root / PRIVACY_PATH
    for p in (docs, path):
        if p.is_symlink():
            raise WriteRefused(f"{p.relative_to(root)} is a symlink: refusing to write through it")
    if os.path.lexists(path) and not path.is_file():
        raise WriteRefused(f"{PRIVACY_PATH} is not a regular file")
    if os.path.lexists(docs) and not docs.is_dir():
        raise WriteRefused("docs exists and is not a directory")
    try:
        path.resolve().relative_to(root)
    except ValueError:
        raise WriteRefused(f"{PRIVACY_PATH} resolves outside the repo") from None
    return path


def write_rows(root: pathlib.Path, report: dict) -> tuple[list[str], bool]:
    """Append a row per undocumented host to the first table with a Host column. Never edits or deletes a
    row. Creates docs/PRIVACY.md from the template when it is missing. Returns (hosts written, created)."""
    path = safe_write_target(root)
    created = not os.path.lexists(path)
    if created:
        template = __import__("teyla").templates_dir() / "repo" / "docs" / "PRIVACY.md"
        text = template.read_text(encoding="utf-8").replace("{{name}}", root.name)
    else:
        data = read_bytes(path)
        if data is None:
            raise WriteRefused(f"{PRIVACY_PATH} could not be read safely (size or file type)")
        text = data.decode("utf-8", errors="replace")
    present = {h for t in parse_tables(text, frozenset(h["host"] for h in report["hosts"])) for r in t.rows for h in r.hosts}
    order = sorted(h["host"] for h in report["hosts"] if not h["documented"] and h["host"] not in present)
    if not order and not created:
        return [], False
    refs = {h["host"]: h["refs"][0] for h in report["hosts"]}
    tables = parse_tables(text)
    primary = next((t for t in tables if t.host_col is not None), None)
    lines = text.split("\n")
    n = max((int(r.cells[0]) for t in tables for r in t.rows if r.cells and r.cells[0].isdigit()), default=0)
    if order and primary is None:
        header = ["#", "Trigger", "Host", "What is sent", "Default on", "Turn it off"]
        block = ["", "## Hosts found by `teyla hosts`", "", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        block += [_row_for(header, n + i + 1, h, refs[h]) for i, h in enumerate(order)]
        while lines and lines[-1] == "":
            lines.pop()
        lines += block
    elif order:
        lines[primary.end:primary.end] = [_row_for(primary.header, n + i + 1, h, refs[h]) for i, h in enumerate(order)]
    out = "\n".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(out, encoding="utf-8")
    return order, created


# --- output --------------------------------------------------------------------------------------------

def render(reports: list[dict], quiet: bool = False, written: dict | None = None) -> str:
    L: list[str] = []
    for r in reports:
        c = counts(r)
        shown = [f for f in r["findings"] if not quiet or f["severity"] in (FIX, "GAP")]
        if quiet and not shown:
            continue
        L.append(f"{r['repo']}: {len(r['hosts'])} host(s), {c[FIX]} FIX, {c[WARN]} WARN" + (", coverage gap" if c["GAP"] else ""))
        for f in shown:
            where = f["file"] + (f":{f['line']}" if f["line"] else "")
            who = f"{f['host']}  " if f["host"] else ""
            L.append(f"  {f['severity']:<4} {f['check']:<12} {who}{where}  {f['message']}")
            L.append(f"       fix: {f['fix']}")
        if written and written.get(r["repo"]):
            L.append(f"  wrote {len(written[r['repo']])} row(s) to {PRIVACY_PATH}: {', '.join(written[r['repo']])}")
        if quiet:
            continue
        if c["GAP"]:
            L.append("  hosts found: " + (", ".join(h["host"] for h in r["hosts"]) or "none"))
        else:
            ok = [h["host"] for h in r["hosts"] if h["documented"]]
            if ok:
                L.append(f"  documented ({len(ok)}): " + ", ".join(ok))
        if r["local"]:
            L.append("  local: " + ", ".join(f"{x['host']} ({x['refs'][0]['file']}:{x['refs'][0]['line']})" for x in r["local"]))
        if r["env_provided"]:
            L.append("  env-provided (value is outside the repo): " + ", ".join(
                f"{e['name']} ({e['file']}:{e['line']})" for e in r["env_provided"]))
        cov = r["coverage"]
        langs = ", ".join(f"{k} {v}" for k, v in cov["by_language"].items()) or "no source files"
        L.append(f"  coverage: {cov['files']} source file(s) ({langs}), {len(cov['manifests'])} manifest(s); "
                 f"skipped roots: {', '.join(cov['skipped_roots']) or 'none'}; {cov['test_files_skipped']} test file(s); "
                 f"{cov['computed_urls']} computed URL(s) not resolved"
                 + (f"; not read: {'; '.join(cov['unread'][:5])}" if cov["unread"] else ""))
    if not quiet:
        t = {k: sum(counts(r)[k] for r in reports) for k in (FIX, WARN, "GAP")}
        L.append("")
        L.append(f"{len(reports)} repo(s): {t[FIX]} FIX, {t[WARN]} WARN" + (f", {t['GAP']} coverage gap" if t["GAP"] else ""))
    return "\n".join(L)


def cmd_hosts(args) -> int:
    try:
        repos = docs_check.resolve(args.repos, args.all)
    except FileNotFoundError as e:
        print(f"teyla hosts: {e}", file=sys.stderr)
        return 2
    reports, written, refused = [], {}, False
    for r in repos:
        rep = check_repo(r)
        if args.write:
            try:
                rows, created = write_rows(r.resolve(), rep)
            except WriteRefused as e:
                print(f"teyla hosts: {rep['repo']}: --write refused: {e}", file=sys.stderr)
                refused = True
            else:
                if rows or created:
                    written[rep["repo"]] = rows
                    rep = check_repo(r)
        reports.append(rep)
    code = 2 if refused else exit_code(reports)
    if args.json:
        t = {k: sum(counts(r)[k] for r in reports) for k in (FIX, WARN, "GAP")}
        print(json.dumps({"repos": reports, "totals": t, "written": written, "exit": code}, indent=1))
    else:
        out = render(reports, quiet=args.quiet, written=written)
        if out:
            print(out)
    return code


def register(sp):
    q = sp.add_parser("hosts", help="every host a repo's code can reach, by file and line, against its docs/PRIVACY.md table")
    q.set_defaults(fn=cmd_hosts)
    q.add_argument("repos", nargs="*", help="repo names under code_root or paths (default: the git root of the current directory)")
    q.add_argument("--all", action="store_true", help="every git repo under code_root")
    q.add_argument("--write", action="store_true", help="append a row per undocumented host to docs/PRIVACY.md (never deletes a row)")
    q.add_argument("--json", action="store_true")
    q.add_argument("--quiet", action="store_true", help="print only FIX and coverage-gap lines")
    return q

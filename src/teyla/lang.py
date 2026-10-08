"""`teyla lang` — where a repository holds text that is not English.

    teyla lang [repo...] [--json] [--quiet] [--commits N]

The owner's policy: everything committed to a repository is English — docs, comments, commit
messages, PR text, rule files, fixtures. The exceptions are product content addressed to users
in another language (localization files) and data a feature needs to recognise a language. This
report finds the rest, so it gets fixed over time instead of in one sweep nobody schedules.

What it reads. Tracked files only (`git ls-files -z`): text under 1 MB, no lockfiles, no vendored
directories, no binaries. It looks for runs of letters in a non-Latin script — Cyrillic, CJK
(Han, kana, Hangul), Greek, Arabic, Hebrew — and counts a line once per kind it holds. A run is
at least three letters (two for CJK), so a lone Greek letter in a formula is not a hit.
Latin-script languages (Spanish, French, German, Portuguese...) are out of scope: telling them
from English needs a language model, and a guess would be noise. The report says so.

Each hit has a kind:

    doc       a Markdown / reST / AsciiDoc file, or anything under docs/
    comment   the run sits after a comment token for the file's language (`#`, `//`, `/*`, `*`,
              `--`, `<!--`), or in a Python docstring
    string    inside quotes in code: likely user-facing, so "check: localization?"
    fixture   a test or fixture file (a comment in one is still a comment)
    other     anything else (an unquoted config value, a plain text file)

Exceptions, so localization is not noise. Matching files are not read at all:

    defaults      *.lproj/**  *.xcstrings  **/locales/**  **/i18n/**  **/l10n/**
                  **/translations/**  *.po  *.strings  **/Localizable*  **/messages/*.json
    .teyla/lang-allow   in the repo: one glob per line, `#` comments
    config        [lang] allow = ["docs/ru/**"]   (`teyla config set lang.allow=a,b`)
    .leak-allow   the `cyrillic:` and `paths:` sections of the leak guard's file are honoured
                  too, matched exactly as the guard matches them (fnmatch on the repo-relative
                  path, so `*` crosses `/`); a file allowed Cyrillic there is still checked for
                  the other scripts

In the first three lists a glob without a leading `/` matches at any depth; `**` crosses
directories, `*` does not; a glob that names a directory covers everything below it.

The JSON report keeps counts for every file but only a few sample hits: at most SAMPLES_PER_FILE
per file and MAX_SAMPLES in all, and none under --quiet, so a repo full of non-English text does
not fill memory.

`--commits N` also reads the last N commit messages on the default branch.

The weekly routine runs `teyla lang --quiet > lang.md` and leaves the counts in
`~/.teyla/lang.json`, which the digest turns into one line. It is a report: the exit code is 0
unless the command line is wrong (2).
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import pathlib
import re
import subprocess
import sys

from . import config

MAX_FILE_BYTES = 1_000_000
SAMPLE_CHARS = 80
TOP_FILES = 5
SAMPLES_PER_FILE = 5
MAX_SAMPLES = 1000   # retained sample hits in one report, all repos together
CACHE_MAX_AGE_DAYS = 14

# script -> (character ranges, minimum run). \u escapes on purpose: the repo's own leak check
# flags literal Cyrillic outside allow-listed files.
SCRIPTS = {
    "cyrillic": ("\u0400-\u052f", 3),
    "cjk": ("\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af", 2),
    "greek": ("\u0370-\u03ff\u1f00-\u1fff", 3),
    "arabic": ("\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff", 3),
    "hebrew": ("\u0590-\u05ff", 3),
}
_RUNS = {name: re.compile("[%s]{%d,}" % (chars, n)) for name, (chars, n) in SCRIPTS.items()}

DEFAULT_ALLOW = (
    "*.lproj/**", "*.xcstrings", "**/locales/**", "**/i18n/**", "**/l10n/**", "**/translations/**",
    "*.po", "*.strings", "**/Localizable*", "**/messages/*.json",
)
ALLOW_FILE = ".teyla/lang-allow"

LOCKFILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "cargo.lock",
             "poetry.lock", "uv.lock", "pipfile.lock", "package.resolved", "podfile.lock", "gemfile.lock",
             "composer.lock", "go.sum", "bun.lockb", "flake.lock", "mix.lock", "pubspec.lock"}
VENDORED = {"node_modules", "vendor", "vendored", "pods", "carthage", "third_party", "thirdparty", "bower_components",
            ".venv", "venv", "site-packages", ".build", "deriveddata", ".git"}

KINDS = ("doc", "comment", "string", "fixture", "other")

DOC_EXT = {".md", ".markdown", ".mdx", ".mdc", ".rst", ".adoc"}
DOC_DIRS = {"docs", "doc"}
TEST_DIRS = {"tests", "test", "__tests__", "fixtures", "testdata", "testing"}


# --- comment syntax per language -------------------------------------------------------------

class Syntax:
    def __init__(self, line=(), block=(), quotes="\"'", star=False, triple=False, docstring=False, multiline=""):
        self.line, self.block, self.quotes = tuple(line), tuple(block), quotes
        self.multiline = multiline  # quote characters whose strings continue onto the next line (JS template literals)
        self.star = star            # a line starting with `*` continues a block comment
        self.triple = triple        # \"\"\" and ''' open multi-line strings
        self.docstring = docstring  # ... which are comments when they open a line (Python)


_HASH = Syntax(line=("#",))
_PY = Syntax(line=("#",), triple=True, docstring=True)
_SLASH = Syntax(line=("//",), block=(("/*", "*/"),), star=True)
_SWIFT = Syntax(line=("//",), block=(("/*", "*/"),), star=True, triple=True)
_JS = Syntax(line=("//",), block=(("/*", "*/"),), quotes="\"'`", star=True, multiline="`")
_CSS = Syntax(block=(("/*", "*/"),), star=True)
_DASH = Syntax(line=("--",), block=(("/*", "*/"),), star=True)
_MARKUP = Syntax(block=(("<!--", "-->"),), quotes="\"")
_DATA = Syntax(quotes="\"")

SYNTAX: dict[str, Syntax] = {}
for _exts, _syn in (
    ((".py", ".pyi"), _PY),
    ((".sh", ".bash", ".zsh", ".rb", ".pl", ".r", ".toml", ".yaml", ".yml", ".cfg", ".conf", ".mk", ".ex", ".exs",
      ".tf", ".properties", ".gitignore", ".rake", ".gemspec"), _HASH),
    ((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"), _JS),
    ((".swift", ".kt", ".kts"), _SWIFT),
    ((".java", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".hpp", ".m", ".mm", ".cs", ".dart", ".scala", ".php",
      ".scss", ".less", ".proto", ".gradle"), _SLASH),
    ((".css",), _CSS),
    ((".sql", ".lua", ".hs"), _DASH),
    ((".html", ".htm", ".xml", ".svg", ".plist", ".vue", ".xib", ".storyboard", ".xhtml"), _MARKUP),
    ((".json", ".jsonc", ".json5"), _DATA),
):
    for _e in _exts:
        SYNTAX[_e] = _syn
NAME_SYNTAX = {"makefile": _HASH, "dockerfile": _HASH, "rakefile": _HASH, "gemfile": _HASH, "podfile": _HASH,
               "justfile": _HASH, "procfile": _HASH}


def syntax_for(rel: str) -> Syntax | None:
    p = pathlib.PurePosixPath(rel)
    return SYNTAX.get(p.suffix.lower()) or NAME_SYNTAX.get(p.name.lower())


def _spans(lines: list[str], syn: Syntax):
    """Per line: (comment spans, string spans) as [(start, end)]. Block comments and triple-quoted
    strings carry across lines; a single- or double-quoted string ends with its line."""
    block_end: str | None = None
    triple: tuple[str, str] | None = None  # (closing quotes, "comment" | "string")
    carry: str | None = None               # a template literal still open at the end of the previous line
    for line in lines:
        n = len(line)
        cs: list[tuple[int, int]] = []
        ss: list[tuple[int, int]] = []
        pos = 0
        if block_end is not None:
            end = line.find(block_end)
            if end < 0:
                yield cs + [(0, n)], ss
                continue
            cs.append((0, end + len(block_end)))
            pos, block_end = end + len(block_end), None
        elif triple is not None:
            end = line.find(triple[0])
            tgt = cs if triple[1] == "comment" else ss
            if end < 0:
                tgt.append((0, n))
                yield cs, ss
                continue
            tgt.append((0, end + 3))
            pos, triple = end + 3, None
        elif syn.star and carry is None and line.lstrip().startswith("*"):
            yield [(0, n)], ss
            continue
        quote, qstart = carry, 0
        carry = None
        while pos < n:
            ch = line[pos]
            if quote:
                if ch == "\\":
                    pos += 2
                    continue
                if ch == quote:
                    ss.append((qstart, pos + 1))
                    quote = None
                pos += 1
                continue
            if syn.triple and line.startswith(('"""', "'''"), pos):
                q3 = line[pos:pos + 3]
                kind = "comment" if syn.docstring and not line[:pos].strip() else "string"
                tgt = cs if kind == "comment" else ss
                end = line.find(q3, pos + 3)
                if end < 0:
                    tgt.append((pos, n))
                    triple = (q3, kind)
                    pos = n
                else:
                    tgt.append((pos, end + 3))
                    pos = end + 3
                continue
            hit = next((t for t in syn.line if line.startswith(t, pos)
                        and (t != "#" or pos == 0 or line[pos - 1] in " \t")), None)
            if hit:
                cs.append((pos, n))
                pos = n
                break
            opened = next(((o, c) for o, c in syn.block if line.startswith(o, pos)), None)
            if opened:
                end = line.find(opened[1], pos + len(opened[0]))
                if end < 0:
                    cs.append((pos, n))
                    block_end = opened[1]
                    pos = n
                else:
                    cs.append((pos, end + len(opened[1])))
                    pos = end + len(opened[1])
                continue
            if ch in syn.quotes:
                quote, qstart = ch, pos
            pos += 1
        if quote:
            ss.append((qstart, n))
            if quote in syn.multiline:
                carry = quote
        yield cs, ss


def _inside(spans: list[tuple[int, int]], pos: int) -> bool:
    return any(a <= pos < b for a, b in spans)


# --- paths ---------------------------------------------------------------------------------------

def glob_regex(pat: str) -> re.Pattern:
    """Gitignore-flavoured: no leading `/` = any depth; `**/` = any directories; `*` stays inside a
    name; the match also covers everything below a matched directory."""
    pat = pat.strip()
    anchored = pat.startswith("/")
    pat = pat.lstrip("/").rstrip("/")
    out, i = [], 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out.append("(?:/.*)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif pat[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pat[i]))
            i += 1
    return re.compile(("" if anchored else "(?:.*/)?") + "".join(out) + "(?:/.*)?$")


def _matcher(globs: list[str]):
    rxs = [glob_regex(g) for g in globs if g.strip()]
    return lambda rel: any(r.match(rel) for r in rxs)


def is_doc(rel: str) -> bool:
    p = pathlib.PurePosixPath(rel)
    return p.suffix.lower() in DOC_EXT or any(part.lower() in DOC_DIRS for part in p.parts[:-1])


def is_test(rel: str) -> bool:
    p = pathlib.PurePosixPath(rel)
    for part in p.parts[:-1]:
        low = part.lower()
        if low in TEST_DIRS or low.endswith("tests"):
            return True
    name = p.name.lower()
    return (name.startswith("test_") or ".test." in name or ".spec." in name
            or re.search(r"_test\.\w+$", name) is not None
            or re.search(r"tests\.(?:swift|kt|java)$", name) is not None)


def skipped(rel: str) -> bool:
    p = pathlib.PurePosixPath(rel)
    return (p.name.lower() in LOCKFILES or any(part.lower() in VENDORED for part in p.parts[:-1])
            or p.name.lower().endswith((".min.js", ".min.css", ".map")))


# --- allow lists ---------------------------------------------------------------------------------

def _glob_lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", line).strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


LEAK_SECTIONS = ("emails", "paths", "home", "cyrillic", "secrets")


def leak_glob(path: str, globs: list[str]) -> bool:
    """scripts/leak_check.py's `_glob`, verbatim: fnmatchcase on the repo-relative path (`*` crosses `/`,
    no implicit any-depth prefix). `.leak-allow` entries mean exactly what the leak guard makes them
    mean; a test compares the two."""
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def _leak_allow(repo: pathlib.Path) -> dict[str, list[str]]:
    """The `cyrillic:` and `paths:` sections of the repo's `.leak-allow`, parsed as leak_check.load_allow does."""
    try:
        text = (repo / ".leak-allow").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return {}
    out: dict[str, list[str]] = {}
    section = None
    for line in _glob_lines(text):
        if line.endswith(":") and line[:-1] in LEAK_SECTIONS:
            section = line[:-1]
        elif section:
            out.setdefault(section, []).append(line)
    return out


def config_allow(cfg: dict | None = None) -> list[str]:
    raw = ((cfg or config.load()).get("lang") or {}).get("allow") or []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    return [str(x) for x in raw]


class Allow:
    """What is exempt in one repo: whole files, and files exempt for Cyrillic only."""

    def __init__(self, repo: pathlib.Path, cfg: dict | None = None):
        globs = list(DEFAULT_ALLOW) + config_allow(cfg)
        try:
            globs += _glob_lines((repo / ALLOW_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        leak = _leak_allow(repo)
        own = _matcher(globs)
        leak_paths, leak_cyrillic = leak.get("paths", []), leak.get("cyrillic", [])
        self.files = lambda rel: own(rel) or leak_glob(rel, leak_paths)
        self.cyrillic = lambda rel: leak_glob(rel, leak_cyrillic)


# --- scanning ------------------------------------------------------------------------------------

def runs_in(line: str, only: set[str] | None = None) -> list[tuple[str, int]]:
    """[(script, start)] for every qualifying run in `line`, in order."""
    if line.isascii():
        return []
    found = []
    for name, rx in _RUNS.items():
        if only is not None and name not in only:
            continue
        found.extend((name, m.start()) for m in rx.finditer(line))
    return sorted(found, key=lambda f: f[1])


def _sample(line: str, width: int = SAMPLE_CHARS) -> str:
    line = " ".join(line.split())
    return line if len(line) <= width else line[:width - 3] + "..."


def scan_text(rel: str, text: str, scripts: set[str] | None = None) -> list[dict]:
    """[{line, kind, script, scripts, text}] — one hit per line and kind; `scripts` lists every script in that kind on the line."""
    if text.isascii():
        return []
    lines = text.splitlines()
    doc, test = is_doc(rel), is_test(rel)
    syn = None if (doc and not test) else syntax_for(rel)
    spans = _spans(lines, syn) if syn else None
    hits = []
    for no, line in enumerate(lines, 1):
        cs, ss = next(spans) if spans is not None else ([], [])
        runs = runs_in(line, scripts)
        if not runs:
            continue
        seen: dict[str, list[str]] = {}
        for script, start in runs:
            if doc and not test:
                kind = "doc"
            elif _inside(cs, start):
                kind = "comment"
            elif test:
                kind = "fixture"
            elif _inside(ss, start):
                kind = "string"
            else:
                kind = "other"
            found = seen.setdefault(kind, [])
            if script not in found:
                found.append(script)
        hits.extend(dict(line=no, kind=k, script=ss[0], scripts=ss, text=_sample(line, 200))
                    for k, ss in seen.items())
    return hits


def _git(repo: pathlib.Path, *args: str, timeout: int = 30) -> bytes | None:
    try:
        r = subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=off", *args],
                           capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def tracked_files(repo: pathlib.Path) -> list[str] | None:
    out = _git(repo, "ls-files", "-z")
    if out is None:
        return None
    return [f for f in out.decode("utf-8", "replace").split("\0") if f]


def _read_text(path: pathlib.Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def default_branch(repo: pathlib.Path) -> str:
    out = _git(repo, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if out and out.strip():
        return out.decode().strip()
    for name in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}") is not None:
            return name
    return "HEAD"


def scan_commits(repo: pathlib.Path, n: int) -> list[dict]:
    """The last `n` commit messages on the default branch that hold non-Latin text."""
    out = _git(repo, "log", f"-{n}", "--format=%H%x00%B%x1e", default_branch(repo))
    if out is None:
        return []
    rows = []
    for rec in out.decode("utf-8", "replace").split("\x1e"):
        sha, _, body = rec.strip("\n").partition("\0")
        sha = sha.strip()
        if not sha:
            continue
        lines = body.splitlines()
        hit = [(i, ln) for i, ln in enumerate(lines, 1) if runs_in(ln)]
        if hit:
            rows.append(dict(sha=sha[:7], subject=_sample(lines[0] if lines else ""), lines=len(hit),
                             sample=_sample(hit[0][1])))
    return rows


class Budget:
    """How many sample hits a report may still keep, across all repos."""

    def __init__(self, n: int | None = None):
        self.left = MAX_SAMPLES if n is None else n

    def take(self, wanted: int) -> int:
        n = max(0, min(wanted, self.left))
        self.left -= n
        return n


def scan_repo(repo: pathlib.Path, cfg: dict | None = None, commits: int = 0, budget: Budget | None = None) -> dict:
    """`budget` caps the sample hits kept (SAMPLES_PER_FILE per file); None: MAX_SAMPLES for this repo;
    Budget(0): counts only."""
    cfg = cfg or config.load()
    budget = Budget() if budget is None else budget
    rep: dict = dict(repo=repo.resolve().name, path=str(repo), files=[], counts={}, commits=[], exempt=0, error=None)
    names = tracked_files(repo)
    if names is None:
        rep["error"] = "not a readable git repository"
        return rep
    allow = Allow(repo, cfg)
    for rel in sorted(names):
        if skipped(rel):
            continue
        if allow.files(rel):
            rep["exempt"] += 1
            continue
        text = _read_text(repo / rel)
        if text is None or text.isascii():
            continue
        only = {s for s in SCRIPTS if s != "cyrillic"} if allow.cyrillic(rel) else None
        hits = scan_text(rel, text, only)
        if not hits:
            continue
        kinds: dict[str, int] = {}
        for h in hits:
            kinds[h["kind"]] = kinds.get(h["kind"], 0) + 1
        top = max(kinds, key=lambda k: (kinds[k], -KINDS.index(k)))
        first = min(hits, key=lambda h: h["line"])
        rep["files"].append(dict(path=rel, kind=top, kinds=kinds, lines=len({h["line"] for h in hits}),
                                 scripts=sorted({x for h in hits for x in h["scripts"]}), sample=_sample(first["text"]),
                                 hits_total=len(hits), hits=hits[:budget.take(SAMPLES_PER_FILE)]))
    for f in rep["files"]:
        for k, n in f["kinds"].items():
            c = rep["counts"].setdefault(k, dict(files=0, lines=0))
            c["files"] += 1
            c["lines"] += n
    rep["files"].sort(key=lambda f: (-f["lines"], f["path"]))
    if commits > 0:
        rep["commits"] = scan_commits(repo, commits)
    return rep


class UsageError(Exception):
    pass


def resolve_repos(args: list[str], cfg: dict | None = None) -> list[pathlib.Path]:
    cfg = cfg or config.load()
    if not args:
        from . import detect
        return detect.repos(cfg)
    root = config.code_root(cfg)
    out = []
    for a in args:
        p = pathlib.Path(a).expanduser() if ("/" in a or a.startswith("~") or a == ".") else root / a
        if not (p / ".git").exists():
            raise UsageError(f"{a}: not a git repository ({p})")
        out.append(p)
    return out


def report(repos: list[pathlib.Path], cfg: dict | None = None, commits: int = 0, samples: bool = True) -> dict:
    cfg = cfg or config.load()
    budget = Budget(MAX_SAMPLES if samples else 0)
    rows = [scan_repo(r, cfg, commits, budget) for r in repos]
    hit = [r for r in rows if r["files"]]
    return dict(
        scanned=len(rows), repos_with_text=len(hit),
        files=sum(len(r["files"]) for r in rows), lines=sum(f["lines"] for r in rows for f in r["files"]),
        commits=sum(len(r["commits"]) for r in rows), errors=[r["repo"] for r in rows if r["error"]],
        repos=sorted(rows, key=lambda r: (-len(r["files"]), r["repo"])),
    )


# --- output --------------------------------------------------------------------------------------

def headline(rep: dict) -> str:
    return f"non-English text: {rep['files']} file(s) in {rep['repos_with_text']} repo(s)"


def _kind_summary(r: dict) -> str:
    parts = []
    for k in KINDS:
        c = r["counts"].get(k)
        if c:
            note = " (check: localization?)" if k == "string" else ""
            parts.append(f"{k} {c['files']} file(s)/{c['lines']} line(s){note}")
    return ", ".join(parts)


def render(rep: dict, quiet: bool = False) -> str:
    out = []
    if rep["files"] or rep["commits"]:
        head = headline(rep)
        if rep["commits"]:
            head += f"; {rep['commits']} commit message(s)"
        out.append(head)
    elif not quiet:
        out.append(f"no non-Latin text in the tracked files of {rep['scanned']} repo(s)")
    for r in rep["repos"]:
        if not r["files"] and not r["commits"]:
            continue
        line = f"{r['repo']}: "
        line += f"{len(r['files'])} file(s) — {_kind_summary(r)}" if r["files"] else "no files"
        if r["commits"]:
            line += f"; {len(r['commits'])} commit message(s)"
        out.append(line)
        if quiet:
            continue
        for f in r["files"][:TOP_FILES]:
            out.append(f"  {f['path']}  [{f['kind']}]  {f['lines']} line(s)  \"{f['sample']}\"")
        if len(r["files"]) > TOP_FILES:
            out.append(f"  ... and {len(r['files']) - TOP_FILES} more file(s); --json lists them all")
        for c in r["commits"][:TOP_FILES]:
            out.append(f"  commit {c['sha']}  {c['lines']} line(s)  \"{c['subject']}\"")
        if len(r["commits"]) > TOP_FILES:
            out.append(f"  ... and {len(r['commits']) - TOP_FILES} more commit(s)")
    if rep["errors"] and not quiet:
        out.append(f"not scanned (git failed): {', '.join(rep['errors'])}")
    if not quiet:
        out.append("Only non-Latin scripts are detected; Latin-script languages (Spanish, French, German...) are not. "
                   "Localization files are exempt: .teyla/lang-allow or `teyla config set lang.allow=GLOB` adds more.")
    return "\n".join(out)


# --- the digest ----------------------------------------------------------------------------------

def cache_path() -> pathlib.Path:
    return config.TEYLA_DIR / "lang.json"


def _write_cache(rep: dict) -> None:
    try:
        cache_path().parent.mkdir(parents=True, exist_ok=True)
        cache_path().write_text(json.dumps(dict(at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
                                                files=rep["files"], repos=rep["repos_with_text"])) + "\n")
    except OSError:
        pass


def digest_candidates() -> list[dict]:
    """One digest line from the counts the weekly `teyla lang` left behind. Local and instant: it
    scans nothing, and a count older than two weeks is not reported."""
    try:
        data = json.loads(cache_path().read_text())
        at = _dt.datetime.fromisoformat(data["at"])
        files, repos = int(data["files"]), int(data["repos"])
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if files <= 0 or _dt.datetime.now(_dt.timezone.utc) - at > _dt.timedelta(days=CACHE_MAX_AGE_DAYS):
        return []
    return [dict(rank=5, id="lang:non-english", text=f"non-English text: {files} file(s) in {repos} repo(s)",
                 step="teyla lang", cmd=True)]


# --- command -------------------------------------------------------------------------------------

def cmd_lang(args) -> int:
    cfg = config.load()
    if args.commits < 0:
        print("teyla lang: --commits must be 0 or more", file=sys.stderr)
        return 2
    try:
        repos = resolve_repos(args.repos, cfg)
    except UsageError as e:
        print(f"teyla lang: {e}", file=sys.stderr)
        return 2
    rep = report(repos, cfg, args.commits, samples=args.json)
    if not args.repos:
        _write_cache(rep)
    if args.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0
    text = render(rep, quiet=args.quiet)
    if text:
        print(text)
    return 0


def register(sp):
    q = sp.add_parser("lang", help="where tracked files and commit messages hold non-English (non-Latin script) text")
    q.set_defaults(fn=cmd_lang)
    q.add_argument("repos", nargs="*", help="repos to scan (names under code_root, or paths); none: every repo")
    q.add_argument("--json", action="store_true", help="every file with its counts and a few sample hits (line, kind, script, text)")
    q.add_argument("--quiet", action="store_true", help="one line per repo with findings; nothing when clean")
    q.add_argument("--commits", type=int, default=0, metavar="N", help="also scan the last N commit messages on the default branch")
    return q

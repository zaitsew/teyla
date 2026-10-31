#!/usr/bin/env python3
"""Stop private data and non-English text from reaching this public repo.

    leak_check.py                     scan every tracked file in the working tree
    leak_check.py --commits RANGE     scan commit messages, author/committer names + emails, and the
                                      lines each commit adds (as commit:<sha>:<path>:<line>)
    leak_check.py --text FILE         scan one text (a PR body before `gh pr create`); `-` = stdin
    leak_check.py --quiet             print only the number of findings

Rules (one finding per line per rule; the match is masked in the output):

    term      a private term from $TEYLA_PRIVATE_TERMS or ~/.config/teyla/private-terms.txt
              (kept OUTSIDE the repo: this script and its tests hold no private data)
    email     any address except example.*, noreply addresses, `git@host` and `.leak-allow`
    home      /Users/<x>/ or /home/<x>/ where <x> is not a placeholder
    secret    token / key shapes and PEM private-key headers
    cyrillic  any character in U+0400-U+04FF (everything in the repo is English, except
              language data a feature needs: those files are listed in `.leak-allow`)

Private-terms file: one term per line, case-insensitive, `#` comments, and
`allow <term> in <glob>` to permit a term in matching paths (`commit:*:author` for git
authors). A term matches only between non-alphanumerics, so `-Users-name-repos-app` matches
`name` and `app` while `names` does not match `name`.

`.leak-allow` (repo root) sections, one glob per line, `#` comments:

    emails:    address globs to permit            paths:   files skipped entirely
    home:      user-name globs to permit          cyrillic: files that may hold Cyrillic
    secrets:   files that may hold fake secrets

    [exceptions]  (a header in brackets; a `name:` line ends it) one line per exception:
              `rule glob reason [until=YYYY-MM-DD] [fp=<12 hex>]`. It silences one rule on the paths its
              glob matches. An expired one is ignored and reported; a match-all glob for a secret rule
              is an error (exit 2): a whole file is never exempt from the secret rules.

Exit 0 when clean, 1 on any finding, 2 on a usage or git error. Stdlib only.

This file is the one implementation of the rules. `teyla leak` (src/teyla/leak.py) imports it for the
rules, the private-terms loader and the allow-list, and adds the surfaces (index, outgoing commits, images,
plists, harness configs), the classes and gitleaks. Keep this file free of imports from `teyla`: the pre-push
hook of a clone with no Teyla installed runs it alone.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import math
import os
import re
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from typing import Iterator, NamedTuple

CYRILLIC = re.compile("[\u0400-\u04FF]+")
EMAIL = re.compile(r"(?<![A-Za-z0-9._%+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
HOME = re.compile(r"/(?:Users|home)/([A-Za-z0-9][^/\s'\"`<>$*{}()\[\],;:|\\]*)/")

EMAIL_OK_DOMAINS = ("example.com", "example.org", "example.net")
EMAIL_OK_EXACT = {"noreply@anthropic.com", "noreply@github.com"}
EMAIL_OK_SUFFIX = ("@users.noreply.github.com",)
# `icon@2x.png` is a retina asset name, not an address. Nothing else is excused by its
# top-level domain: a name at a `.sh` or `.md` domain can be an address. Other exceptions go in `.leak-allow`.
RETINA = re.compile(r"^\d+x\.(?:png|jpe?g|gif|svg|webp|heic|pdf)$")
HOME_OK = {"me", "you", "user", "username", "name", "acme", "example", "runner", "alice", "bob",
           "shared", "guest", "yourname", "your-name", "someone", "foo", "bar"}

SECRET_RES = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY[A-Z ]*-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}"),
    re.compile(r"\bxai-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"\b(?:glpat|glptt|gldt)-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\b(?:hf|npm)_[A-Za-z0-9]{30,}"),
    re.compile(r"\bpypi-[A-Za-z0-9_\-]{40,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}(?:\.[A-Za-z0-9_\-]{4,}){1,2}"),
]

# A keyword next to a long value, with no known prefix: listed, never blocking (severity "triage").
GENERIC_SECRET = re.compile(
    r"""(?i)(?<![A-Za-z0-9])[A-Za-z0-9_.\-]*(?:api[_\-]?key|secret|token|passw(?:or)?d|private[_\-]?key|access[_\-]?key|credential)"""
    r"""[A-Za-z0-9_.\-]*["']?\s*[:=]\s*["']?([A-Za-z0-9_\-+/=.]{20,})""")
GENERIC_SKIP = ("example", "placeholder", "changeme", "your", "xxxx", "redacted", "dummy", "sample", "insert")

SECTIONS = ("emails", "paths", "home", "cyrillic", "secrets")
RULE_ORDER = ("term", "email", "home", "secret", "secret-generic", "cyrillic")
SEVERITY = {"term": "blocker", "email": "blocker", "home": "blocker", "secret": "blocker",
            "secret-generic": "triage", "cyrillic": "lang"}


class Finding(NamedTuple):
    path: str
    line: int
    rule: str
    excerpt: str


class GitError(RuntimeError):
    """A git command failed, or a revision range is not one this scanner accepts."""


class Hit(NamedTuple):
    """One match of one rule on one line, before it is formatted as a finding."""
    rule: str
    severity: str        # blocker | triage | lang
    start: int
    end: int
    match: str
    term: int | None     # index of the private term in the terms file, for rule "term"


class AllowException(NamedTuple):
    rule: str            # fnmatch pattern on the rule name
    glob: str            # fnmatch pattern on the repo path
    reason: str
    until: _dt.date | None
    fp: str | None


class Config:
    def __init__(self) -> None:
        self.terms: list[tuple[str, re.Pattern]] = []  # the position is the term's index
        self.term_allow: list[tuple[str, str]] = []   # (lower-cased term, glob)
        self.allow: dict[str, list[str]] = {s: [] for s in SECTIONS}
        self.notes: list[str] = []
        self.exceptions: list[AllowException] = []        # active ones; an expired one lands in `expired`
        self.expired: list[AllowException] = []
        self.errors: list[str] = []                   # a malformed allow-list: the caller exits 2
        self.terms_path = ""
        self.terms_explicit = False                   # $TEYLA_PRIVATE_TERMS was set
        self.terms_status = "unset"                   # ok | missing | unreadable


CONFIG_CAP = 256 * 1024       # the terms file and .leak-allow: both are small, and neither is read without a cap


def read_capped(path: Path, cap: int = CONFIG_CAP, *, follow: bool = True) -> str:
    """The text of a small config file, never more than `cap` bytes into memory. Raises OSError when it is not a
    regular file (or, with follow=False, is a symlink) and ValueError when it is over the cap."""
    flags = os.O_RDONLY | (0 if follow else getattr(os, "O_NOFOLLOW", 0)) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise OSError("not a regular file")
        data = fh.read(cap + 1)
    if len(data) > cap:
        raise ValueError(f"over {cap} bytes")
    return data.decode("utf-8")


def load_terms(cfg: Config) -> None:
    env = os.environ.get("TEYLA_PRIVATE_TERMS")
    path = Path(env).expanduser() if env else Path.home() / ".config" / "teyla" / "private-terms.txt"
    cfg.terms_path, cfg.terms_explicit = str(path), bool(env)
    try:
        raw = read_capped(path)
    except (OSError, ValueError) as e:
        cfg.terms_status = "missing" if isinstance(e, FileNotFoundError) else "unreadable"
        cfg.notes.append("no private term list; generic rules only")
        return
    cfg.terms_status = "ok"
    seen: set[str] = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"(?i)allow\s+(.+?)\s+in\s+(\S+)$", line)
        if m:
            cfg.term_allow.append((m.group(1).strip().lower(), m.group(2)))
            continue
        term = line.lower()
        if term in seen:
            continue
        seen.add(term)
        cfg.terms.append((term, re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)))


def load_allow(cfg: Config, root: Path | None) -> None:
    if root is None or not os.path.lexists(root / ".leak-allow"):
        return
    try:
        text = read_capped(root / ".leak-allow", follow=False)
    except (OSError, ValueError, UnicodeDecodeError) as e:
        why = str(e) if isinstance(e, ValueError) and not isinstance(e, UnicodeDecodeError) else "not a readable regular file"
        cfg.errors.append(f".leak-allow: allowlist unreadable ({why})")
        return
    section = None
    today = _dt.date.today()
    for no, line in enumerate(text.splitlines(), 1):
        line = re.sub(r"\s+#.*$", "", line).strip()
        if not line or line.startswith("#"):
            continue
        if line == "[exceptions]":
            section = "[exceptions]"
        elif line.endswith(":") and line[:-1] in SECTIONS:
            section = line[:-1]
        elif section == "[exceptions]":
            _add_exception(cfg, line, today, no)
        elif section:
            cfg.allow[section].append(line)


def _add_exception(cfg: Config, line: str, today: _dt.date, no: int = 0) -> None:
    """`rule glob reason... [until=YYYY-MM-DD] [fp=<12 hex>]`. An error names the line number only: the line may
    hold a token in `until=` or in the reason, and an error is printed, logged and sent to a model."""
    where = f".leak-allow:{no}: [exceptions]"
    words = line.split()
    until: _dt.date | None = None
    fp: str | None = None
    rest = []
    for w in words:
        if w.startswith("until="):
            try:
                until = _dt.date.fromisoformat(w[6:])
            except ValueError:
                cfg.errors.append(f"{where} bad date in until= (want until=YYYY-MM-DD)")
                return
        elif re.fullmatch(r"fp=[0-9a-f]{12}", w):
            fp = w[3:]
        else:
            rest.append(w)
    if len(rest) < 3:
        cfg.errors.append(f"{where} a line is `rule glob reason [until=YYYY-MM-DD]`; this one has no reason")
        return
    rule, glob, reason = rest[0], rest[1], " ".join(rest[2:])
    if any(c in rule for c in "*?[]"):
        cfg.errors.append(f"{where} the rule must be an exact rule name: a pattern exempts every file from some "
                          "secret-family rule")
        return
    if rule not in KNOWN_RULES and not re.fullmatch(r"gitleaks:[A-Za-z0-9._\-]+", rule):
        cfg.errors.append(f"{where} unknown rule; use one of {', '.join(sorted(KNOWN_RULES))} or gitleaks:<RuleID>")
        return
    bare = not glob.strip("/").strip("*") or not glob.strip("/")
    if _secret_family(rule) and fp is None and (bare or all(fnmatch.fnmatchcase(p, glob) for p in ("a", "a/b", "a/b/c.txt", ".env"))):
        cfg.errors.append(f"{where} this line exempts every file from a secret-family rule; "
                          "name the files, or the finding with fp=")
        return
    ex = AllowException(rule, glob, reason, until, fp)
    (cfg.expired if until is not None and until < today else cfg.exceptions).append(ex)


KNOWN_RULES = {"term", "email", "home", "secret", "secret-generic", "cyrillic", "harness-config", "image-metadata",
               "symlink-outside"}
SECRET_FAMILY = ("secret", "secret-generic", "harness-config", "image-metadata")


def _secret_family(rule: str) -> bool:
    """Whether a rule pattern can match a secret rule: `secret`, a harness or image finding, any `gitleaks:` rule.
    A pattern such as `*` or `gitleaks:*` can, so it counts."""
    if rule.startswith("gitleaks:") or rule.startswith("gitleaks"):
        return True
    return any(fnmatch.fnmatchcase(r, rule) for r in SECRET_FAMILY)


def fp_key(hit: Hit) -> str:
    """What a hit is fingerprinted by: its match, except a private term, which is fingerprinted by its
    index so that no output holds a hash of the term itself."""
    return f"term:{hit.term}" if hit.rule == "term" else hit.match


def fingerprint(rule: str, path: str, match: str) -> str:
    """First 12 hex of sha256(rule + path + match): stable across lines and commits."""
    return hashlib.sha256((rule + path + match).encode("utf-8", "replace")).hexdigest()[:12]


def _glob(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def _email_ok(addr: str, cfg: Config) -> bool:
    a = addr.lower()
    local, _, domain = a.partition("@")
    if local == "git" or a in EMAIL_OK_EXACT or a.endswith(EMAIL_OK_SUFFIX):
        return True
    if any(domain == d or domain.endswith("." + d) for d in EMAIL_OK_DOMAINS):
        return True
    if RETINA.match(domain):
        return True
    return any(fnmatch.fnmatchcase(a, g.lower()) for g in cfg.allow["emails"])


def _mask(s: str) -> str:
    return s[:2] + "***"


def _entropy(s: str) -> float:
    return -sum(c / len(s) * math.log2(c / len(s)) for c in map(s.count, set(s)))


class PathRules:
    """The rules that apply to one repo path: the private terms the glob lines leave in force, the
    file-level exemptions, and the exceptions. `hits(line)` is the one place a rule is evaluated."""

    def __init__(self, gpath: str, cfg: Config, triage: bool = False, lang: bool = True) -> None:
        self.cfg, self.gpath, self.triage = cfg, gpath, triage
        self.skip = _glob(gpath, cfg.allow["paths"])
        self.terms = [(i, r) for i, (t, r) in enumerate(cfg.terms)
                      if not any(t == at and fnmatch.fnmatchcase(gpath, g) for at, g in cfg.term_allow)]
        self.cyr = lang and not _glob(gpath, cfg.allow["cyrillic"])
        self.sec = not _glob(gpath, cfg.allow["secrets"])
        self.exc = [e for e in cfg.exceptions if fnmatch.fnmatchcase(gpath, e.glob)]

    def excepted(self, rule: str, match: str) -> bool:
        """`match` is what fingerprints the finding: see `fp_key`."""
        for e in self.exc:
            if fnmatch.fnmatchcase(rule, e.rule) and (e.fp is None or e.fp == fingerprint(rule, self.gpath, match)):
                return True
        return False

    def hits(self, line: str) -> list[Hit]:
        if self.skip:
            return []
        out: list[Hit] = []
        for i, r in self.terms:
            for m in r.finditer(line):
                out.append(Hit("term", "blocker", m.start(), m.end(), m.group(0), i))
        for m in EMAIL.finditer(line):
            if not _email_ok(m.group(0), self.cfg):
                out.append(Hit("email", "blocker", m.start(), m.end(), m.group(0), None))
        for m in HOME.finditer(line):
            who = m.group(1)
            if who.lower() not in HOME_OK and not any(fnmatch.fnmatchcase(who.lower(), g.lower()) for g in self.cfg.allow["home"]):
                out.append(Hit("home", "blocker", m.start(1), m.end(1), who, None))
        if self.sec:
            known: list[tuple[int, int]] = []
            for r in SECRET_RES:
                for m in r.finditer(line):
                    known.append(m.span())
                    out.append(Hit("secret", "blocker", m.start(), m.end(), m.group(0), None))
            if self.triage:
                for m in GENERIC_SECRET.finditer(line):
                    v = m.group(1)
                    if (any(k in v.lower() for k in GENERIC_SKIP) or v.count(".") > 1 or _entropy(v) < 3.5
                            or not (any(c.isdigit() for c in v) and any(c.isalpha() for c in v))
                            or any(s < m.end(1) and m.start(1) < e for s, e in known)):
                        continue
                    out.append(Hit("secret-generic", "triage", m.start(1), m.end(1), v, None))
        if self.cyr:
            for m in CYRILLIC.finditer(line):
                out.append(Hit("cyrillic", "lang", m.start(), m.end(), m.group(0), None))
        if self.exc:
            out = [h for h in out if not self.excepted(h.rule, fp_key(h))]
        return out


def scan_text(label: str, text: str, cfg: Config) -> list[Finding]:
    """Every finding in `text`, which is shown as `label` (a repo path, `commit:<sha>:message`...)."""
    return scan_lines(label, label, enumerate(text.splitlines(), 1), cfg)


def scan_lines(label: str, gpath: str, lines, cfg: Config) -> list[Finding]:
    """Findings in `lines`, an iterable of (line number, text). `label` is what is printed;
    `gpath` is the repo path the `.leak-allow` globs and `allow <term> in <glob>` lines are
    matched against (they differ for the content a commit adds: `commit:<sha>:<path>`).
    One finding per line per rule; the excerpt masks every match on the line."""
    rules = PathRules(gpath, cfg)
    out: list[Finding] = []
    for no, line in lines:
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        hits = rules.hits(line)
        if not hits:
            continue
        excerpt = _excerpt(line, [(h.start, h.end) for h in hits])
        for rule in dict.fromkeys(h.rule for h in hits):
            out.append(Finding(label, no, rule, excerpt))
    return out


def _excerpt(line: str, spans: list[tuple[int, int]]) -> str:
    """The line with every match masked to its first two characters, trimmed around the first."""
    merged: list[list[int]] = []
    for s, e in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    parts, pos = [], 0
    first = merged[0][0]
    for s, e in merged:
        parts.append(line[pos:s])
        parts.append(_mask(line[s:e]))
        pos = e
    parts.append(line[pos:])
    masked = "".join(parts)
    start = max(0, first - 30)          # text before the first match is unchanged by masking
    return ("..." if start else "") + masked[start:start + 100].strip() + ("..." if len(masked) > start + 100 else "")


# --- sources ------------------------------------------------------------------------------

def _git(args: list[str], cwd: Path) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace")
    if p.returncode != 0:
        raise GitError(f"git {args[0]} failed: {p.stderr.strip()}")
    return p.stdout


def repo_root(cwd: Path) -> Path | None:
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    return Path(p.stdout.strip()) if p.returncode == 0 else None


def scan_tree(root: Path, cfg: Config) -> list[Finding]:
    """Every tracked text file, read line by line with no size cap. A binary file (a NUL in
    its first 8 KB) is skipped."""
    out: list[Finding] = []
    for rel in _git(["ls-files", "-z"], root).split("\0"):
        f = root / rel
        if not rel or f.is_symlink() or not f.is_file():
            continue
        try:
            with open(f, "rb") as fh:
                if b"\0" in fh.read(8192):
                    continue
            with open(f, encoding="utf-8", errors="replace", newline="") as fh:
                out.extend(scan_lines(rel, rel, enumerate(fh, 1), cfg))
        except OSError:
            continue
    return out


def parse_range(rev: str) -> list[str]:
    revs = shlex.split(rev)
    if any(r.startswith("-") and r not in ("--not", "--all") and not r.startswith("--remotes") for r in revs):
        raise GitError(f"unsupported revision range: {rev}")
    return revs


def iter_commits(root: Path, revs: list[str]) -> Iterator[tuple[str, str, str, str, str, str]]:
    """(full sha, author name, author email, committer name, committer email, message) per commit."""
    fmt = "%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e"
    for rec in _git(["log", f"--format={fmt}", *revs], root).split("\x1e"):
        rec = rec.strip("\n")
        if rec:
            sha, an, ae, cn, ce, body = (rec.split("\x1f", 5) + [""] * 6)[:6]
            yield sha, an, ae, cn, ce, body


def scan_commits(root: Path, rev: str, cfg: Config) -> list[Finding]:
    """Commit metadata (messages, author and committer) and the lines each commit ADDS."""
    revs = parse_range(rev)
    out: list[Finding] = []
    for sha, an, ae, cn, ce, body in iter_commits(root, revs):
        s = sha[:8]
        out.extend(scan_text(f"commit:{s}:author", f"{an}\n{ae}", cfg))
        if (cn, ce) != (an, ae):
            out.extend(scan_text(f"commit:{s}:committer", f"{cn}\n{ce}", cfg))
        out.extend(scan_text(f"commit:{s}:message", body, cfg))
    out.extend(scan_added(root, revs, cfg))
    return out


def iter_added(root: Path, revs: list[str]) -> Iterator[tuple[str, str, list[tuple[int, str]]]]:
    """(full sha, path, [(line number in the new file, text)]) for the `+` lines of `git log -p`
    over `revs`. The diff headers give the path. Binary diffs have no hunks and are skipped. A key
    committed in one commit and removed in the next is caught here, including one written while
    resolving a merge conflict."""
    # Prefixes are explicit (a `diff.noprefix` setting would otherwise drop every path), and a
    # merge commit is diffed against its first parent, so lines written while resolving a
    # conflict are scanned too.
    cmd = ["git", "-c", "core.quotepath=off", "log", "-p", "-U0", "--no-color", "--no-ext-diff",
           "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", "--diff-merges=first-parent",
           "--format=%x1e%H", *revs]
    proc = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace")
    sha = path = ""
    in_hunk = False
    n = 0
    pending: list[tuple[int, str]] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith("\x1e"):
            if pending and path:
                yield sha, path, pending
            pending = []
            sha, path, in_hunk = line[1:], "", False
        elif line.startswith("diff --git "):
            if pending and path:
                yield sha, path, pending
            pending = []
            path, in_hunk = "", False
        elif in_hunk and line.startswith("+"):
            pending.append((n, line[1:]))
            n += 1
        elif line.startswith("@@"):
            m = re.match(r"@@ -\S+ \+(\d+)", line)
            if m:
                n, in_hunk = int(m.group(1)), True
        elif not in_hunk and line.startswith("+++ "):
            name = line[4:].split("\t")[0].strip('"')
            path = name[2:] if name.startswith("b/") else ""
    if pending and path:
        yield sha, path, pending
    err = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        raise GitError(f"git log failed: {err.strip()}")


def scan_added(root: Path, revs: list[str], cfg: Config) -> list[Finding]:
    """Findings in the added lines, as `commit:<sha>:<path>:<line>`; `.leak-allow` globs apply to
    the path exactly as they do in the tree scan."""
    out: list[Finding] = []
    for sha, path, lines in iter_added(root, revs):
        out.extend(scan_lines(f"commit:{sha[:8]}:{path}", path, lines, cfg))
    return out


def summarize(findings: list[Finding]) -> str:
    by_rule: dict[str, int] = {}
    for f in findings:
        by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
    detail = ", ".join(f"{r} {n}" for r, n in sorted(by_rule.items()))
    return f"leak_check: {len(findings)} finding(s) ({detail})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scan for private data and non-English text.")
    ap.add_argument("--commits", metavar="RANGE", help="scan messages, authors and the lines added by the commits in a git revision range")
    ap.add_argument("--text", metavar="FILE", help="scan a text file (- for stdin), e.g. a PR body")
    ap.add_argument("--quiet", action="store_true", help="print only the number of findings")
    args = ap.parse_args(argv)

    cwd = Path.cwd()
    root = repo_root(cwd)
    cfg = Config()
    load_terms(cfg)
    load_allow(cfg, root)
    if cfg.errors:
        for e in cfg.errors:
            print(f"leak_check: {e}", file=sys.stderr)
        return 2

    try:
        if args.text:
            if args.text == "-":
                text, label = sys.stdin.read(), "<stdin>"
            else:
                try:
                    text, label = Path(args.text).read_text(encoding="utf-8", errors="replace"), args.text
                except OSError as e:
                    print(f"leak_check: cannot read {args.text}: {e}", file=sys.stderr)
                    return 2
            findings = scan_text(label, text, cfg)
        elif root is None:
            print("leak_check: not inside a git repository", file=sys.stderr)
            return 2
        elif args.commits:
            findings = scan_commits(root, args.commits, cfg)
        else:
            findings = scan_tree(root, cfg)
    except GitError as e:
        print(f"leak_check: {e}", file=sys.stderr)
        return 2

    if args.quiet:
        print(len(findings))
    else:
        for note in cfg.notes:
            print(f"leak_check: note: {note}", file=sys.stderr)
        for ex in cfg.expired:
            print(f"leak_check: expired exception: {ex.rule} {ex.glob} (until {ex.until})", file=sys.stderr)
        for f in findings:
            print(f"{f.path}:{f.line}: {f.rule}: {f.excerpt}")
        if findings:
            print(summarize(findings), file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

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

Exit 0 when clean, 1 on any finding, 2 on a usage or git error. Stdlib only.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

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

SECTIONS = ("emails", "paths", "home", "cyrillic", "secrets")


class Finding(NamedTuple):
    path: str
    line: int
    rule: str
    excerpt: str


class Config:
    def __init__(self) -> None:
        self.terms: list[tuple[str, re.Pattern]] = []
        self.term_allow: list[tuple[str, str]] = []   # (lower-cased term, glob)
        self.allow: dict[str, list[str]] = {s: [] for s in SECTIONS}
        self.notes: list[str] = []


def load_terms(cfg: Config) -> None:
    env = os.environ.get("TEYLA_PRIVATE_TERMS")
    path = Path(env).expanduser() if env else Path.home() / ".config" / "teyla" / "private-terms.txt"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        cfg.notes.append("no private term list; generic rules only")
        return
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
    if root is None or not (root / ".leak-allow").is_file():
        return
    section = None
    for line in (root / ".leak-allow").read_text(encoding="utf-8").splitlines():
        line = re.sub(r"\s+#.*$", "", line).strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":") and line[:-1] in SECTIONS:
            section = line[:-1]
        elif section:
            cfg.allow[section].append(line)


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


def scan_text(label: str, text: str, cfg: Config) -> list[Finding]:
    """Every finding in `text`, which is shown as `label` (a repo path, `commit:<sha>:message`...)."""
    return scan_lines(label, label, enumerate(text.splitlines(), 1), cfg)


def scan_lines(label: str, gpath: str, lines, cfg: Config) -> list[Finding]:
    """Findings in `lines`, an iterable of (line number, text). `label` is what is printed;
    `gpath` is the repo path the `.leak-allow` globs and `allow <term> in <glob>` lines are
    matched against (they differ for the content a commit adds: `commit:<sha>:<path>`)."""
    if _glob(gpath, cfg.allow["paths"]):
        return []
    terms = [(t, r) for t, r in cfg.terms
             if not any(t == at and fnmatch.fnmatchcase(gpath, g) for at, g in cfg.term_allow)]
    cyr_ok = _glob(gpath, cfg.allow["cyrillic"])
    sec_ok = _glob(gpath, cfg.allow["secrets"])
    out: list[Finding] = []
    for no, line in lines:
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        hits: dict[str, list[tuple[int, int]]] = {}
        for _t, r in terms:
            for m in r.finditer(line):
                hits.setdefault("term", []).append(m.span())
        for m in EMAIL.finditer(line):
            if not _email_ok(m.group(0), cfg):
                hits.setdefault("email", []).append(m.span())
        for m in HOME.finditer(line):
            who = m.group(1)
            if who.lower() not in HOME_OK and not any(fnmatch.fnmatchcase(who.lower(), g.lower()) for g in cfg.allow["home"]):
                hits.setdefault("home", []).append(m.span(1))
        if not sec_ok:
            for r in SECRET_RES:
                for m in r.finditer(line):
                    hits.setdefault("secret", []).append(m.span())
        if not cyr_ok:
            for m in CYRILLIC.finditer(line):
                hits.setdefault("cyrillic", []).append(m.span())
        if not hits:
            continue
        excerpt = _excerpt(line, [s for spans in hits.values() for s in spans])
        for rule in hits:
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
        print(f"leak_check: git {args[0]} failed: {p.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)
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


def scan_commits(root: Path, rev: str, cfg: Config) -> list[Finding]:
    """Commit metadata (messages, author and committer) and the lines each commit ADDS."""
    fmt = "%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x1f%B%x1e"
    revs = shlex.split(rev)
    if any(r.startswith("-") and r not in ("--not", "--all") and not r.startswith("--remotes") for r in revs):
        print(f"leak_check: unsupported revision range: {rev}", file=sys.stderr)
        raise SystemExit(2)
    log = _git(["log", f"--format={fmt}", *revs], root)
    out: list[Finding] = []
    for rec in log.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, an, ae, cn, ce, body = (rec.split("\x1f", 5) + [""] * 6)[:6]
        s = sha[:8]
        out.extend(scan_text(f"commit:{s}:author", f"{an}\n{ae}", cfg))
        if (cn, ce) != (an, ae):
            out.extend(scan_text(f"commit:{s}:committer", f"{cn}\n{ce}", cfg))
        out.extend(scan_text(f"commit:{s}:message", body, cfg))
    out.extend(scan_added(root, revs, cfg))
    return out


def scan_added(root: Path, revs: list[str], cfg: Config) -> list[Finding]:
    """The `+` lines of `git log -p` over `revs`, as `commit:<sha>:<path>:<line in the new file>`.
    The diff headers give the path; `.leak-allow` globs apply to that path exactly as they do
    in the tree scan. Binary diffs have no hunks and are skipped. A key committed in one
    commit and removed in the next is caught here, including one written while resolving a
    merge conflict."""
    # Prefixes are explicit (a `diff.noprefix` setting would otherwise drop every path), and a
    # merge commit is diffed against its first parent, so lines written while resolving a
    # conflict are scanned too.
    cmd = ["git", "-c", "core.quotepath=off", "log", "-p", "-U0", "--no-color", "--no-ext-diff",
           "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/", "--diff-merges=first-parent",
           "--format=%x1e%H", *revs]
    proc = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace")
    out: list[Finding] = []
    sha = path = ""
    in_hunk = False
    n = 0
    pending: list[tuple[int, str]] = []

    def flush() -> None:
        nonlocal pending
        if pending and path:
            out.extend(scan_lines(f"commit:{sha}:{path}", path, pending, cfg))
        pending = []

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        if line.startswith("\x1e"):
            flush()
            sha, path, in_hunk = line[1:9], "", False
        elif line.startswith("diff --git "):
            flush()
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
    flush()
    err = proc.stderr.read() if proc.stderr else ""
    if proc.wait() != 0:
        print(f"leak_check: git log failed: {err.strip()}", file=sys.stderr)
        raise SystemExit(2)
    return out


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

    if args.quiet:
        print(len(findings))
    else:
        for note in cfg.notes:
            print(f"leak_check: note: {note}", file=sys.stderr)
        for f in findings:
            print(f"{f.path}:{f.line}: {f.rule}: {f.excerpt}")
        if findings:
            by_rule: dict[str, int] = {}
            for f in findings:
                by_rule[f.rule] = by_rule.get(f.rule, 0) + 1
            detail = ", ".join(f"{r} {n}" for r, n in sorted(by_rule.items()))
            print(f"leak_check: {len(findings)} finding(s) ({detail})", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

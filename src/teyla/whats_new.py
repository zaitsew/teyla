"""`teyla whats-new` -- a store "What's New" that names what a user would notice.

    teyla whats-new draft <repo> --version V [--since REF] [--locales en,ru,es] [--write] [--json]
    teyla whats-new check <repo> --version V [--locales en,ru,es] [--json]

`draft` lists the PRs merged since the last version tag (or --since), split into user-facing candidates and
internal items, for the session to rewrite in plain words. `--write` creates `docs/whats-new/<V>/<locale>.txt`
holding only a TODO placeholder, never the raw titles. `check` exits 1 for a locale with no file, an empty
file, the placeholder or a generic line such as "Bug fixes and improvements". Offline: git only, no model call.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import unicodedata

from .whats_new_lexicon import GENERIC_NOTES

PLACEHOLDER = "TODO: write What's New from the draft"
DEFAULT_LOCALES = ("en",)
VERSION_TAG = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_-]*?[-_/]?)?v?\d+(?:\.\d+)+(?:[-+.][0-9A-Za-z.]+)?$")
INTERNAL = re.compile(
    r"^(?:docs?|test|tests|ci|chore|refactor|review|deps?|build|style|policy|release)\b\s*[:(]"
    r"|^release\s+v?\d"                                       # "release 0.52.0"
    r"|^(?:(?:iphone|ios|ipad|mac|macos|android|tv)\s+)?build\s+\d+\b"  # "iPhone build 11", "Build 4"
    r"|\b(?:bump|dependabot|dependencies|store listing|listing|screenshots?|policy|changelog|readme|lint|typo)\b",
    re.I)
MERGE_RE = re.compile(r"^Merge pull request #(\d+) from (\S+)")
SQUASH_RE = re.compile(r"^(.*\S)\s+\(#(\d+)\)$")


def _git(repo: pathlib.Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def newest_version_tag(repo: pathlib.Path) -> str | None:
    out = _git(repo, "tag", "--list", "--sort=-creatordate")
    tags = [t.strip() for t in out.splitlines() if VERSION_TAG.match(t.strip())]
    return tags[0] if tags else None


def _head(repo: pathlib.Path) -> str:
    for ref in ("origin/main", "origin/master"):
        r = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref], capture_output=True, text=True)
        if r.returncode == 0:
            return ref
    return "HEAD"


def merged_changes(repo: pathlib.Path, since: str) -> list[dict]:
    """Every change that landed on the mainline: merge commits, squash merges and direct commits alike."""
    rng = f"{since}..{_head(repo)}"
    sep = "\x1f"
    out = _git(repo, "log", "--first-parent", f"--format=%P{sep}%s{sep}%b\x1e", rng)
    items = []
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        parents, _, rest = rec.strip("\n").partition(sep)
        subject, _, body = rest.partition(sep)
        subject = subject.strip()
        if len(parents.split()) > 1:
            m = MERGE_RE.match(subject)
            first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
            if m:
                items.append({"pr": int(m.group(1)), "title": first or m.group(2).split("/", 1)[-1].replace("-", " ")})
            else:
                items.append({"pr": None, "title": first or subject})
            continue
        m = SQUASH_RE.match(subject)
        if m:
            items.append({"pr": int(m.group(2)), "title": m.group(1).strip()})
        elif subject:
            items.append({"pr": None, "title": subject})
    return items


def split_changes(items: list[dict]) -> tuple[list[dict], list[dict]]:
    user, internal = [], []
    for it in items:
        (internal if INTERNAL.search(it["title"]) else user).append(it)
    return user, internal


def _label(it: dict) -> str:
    return f"{it['title']} (#{it['pr']})" if it["pr"] else it["title"]


def render_draft(version: str, since: str, user: list[dict], internal: list[dict]) -> str:
    lines = [f"# What's New draft for {version} (since {since})", "",
             "## User-facing candidates (rewrite as what a user would notice)", ""]
    lines += [f"- {_label(i)}" for i in user] or ["- (none: a version with nothing a user would notice is not submitted)"]
    lines += ["", "## Internal (not for the store)", ""]
    lines += [f"- {_label(i)}" for i in internal] or ["- (none)"]
    lines += ["", "## Template body", "",
              "- <one line per change a user would notice, plain words, no PR numbers>", ""]
    return "\n".join(lines)


def _locales(arg: str | None) -> list[str]:
    vals = [x.strip() for x in (arg or "").split(",") if x.strip()]
    return vals or list(DEFAULT_LOCALES)


def _dir(repo: pathlib.Path, version: str) -> pathlib.Path:
    return repo / "docs" / "whats-new" / version


def find_note(repo: pathlib.Path, version: str, locale: str) -> pathlib.Path | None:
    d = _dir(repo, version)
    lang = re.split(r"[-_]", locale)[0]
    for c in (locale, locale.replace("_", "-"), lang):
        p = d / f"{c}.txt"
        if p.is_file():
            return p
    return None


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFC", text).casefold()
    t = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in t)
    return " ".join(t.split())


_GENERIC = {_norm(g) for g in GENERIC_NOTES}


def is_generic(text: str) -> bool:
    """True when the note names nothing: the whole text, or every line of it, is a stock phrase."""
    if _norm(text) in _GENERIC:
        return True
    lines = [_norm(ln) for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    return bool(lines) and all(ln in _GENERIC for ln in lines)


def check_locale(repo: pathlib.Path, version: str, locale: str) -> tuple[bool, str]:
    p = find_note(repo, version, locale)
    if p is None:
        return False, "no file"
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return False, f"{p.name} is empty"
    if text.startswith("TODO"):
        return False, f"{p.name} is the placeholder"
    if is_generic(text):
        return False, f"{p.name} is a generic line"
    return True, p.name


def _repo(arg: str) -> pathlib.Path:
    p = pathlib.Path(arg).expanduser().resolve()
    if not p.is_dir():
        raise RuntimeError(f"not a directory: {arg}")
    return p


def cmd_whats_new(args) -> int:
    try:
        repo = _repo(args.repo)
        locales = _locales(args.locales)
        if args.action == "check":
            res = {loc: check_locale(repo, args.version, loc) for loc in locales}
            bad = {k: v[1] for k, v in res.items() if not v[0]}
            if args.json:
                print(json.dumps({"version": args.version, "ok": not bad,
                                  "locales": {k: {"ok": v[0], "detail": v[1]} for k, v in res.items()}}, indent=2))
            else:
                for loc, why in bad.items():
                    print(f"{loc}: {why}. Run teyla whats-new draft {args.repo} --version {args.version}, then write "
                          f"docs/whats-new/{args.version}/{loc}.txt")
                if not bad:
                    print(f"ok: {len(locales)} locale(s) have a What's New for {args.version}")
            return 1 if bad else 0
        since = args.since or newest_version_tag(repo)
        if not since:
            print("whats-new: no version tag found; pass --since <git-ref>", file=sys.stderr)
            return 2
        user, internal = split_changes(merged_changes(repo, since))
        written, kept = [], []
        if args.write:
            d = _dir(repo, args.version)
            for loc in locales:
                p = d / f"{loc}.txt"
                if p.exists() and p.read_text(encoding="utf-8").strip() not in ("", PLACEHOLDER):
                    kept.append(str(p.relative_to(repo)))
                    continue
                d.mkdir(parents=True, exist_ok=True)
                p.write_text(PLACEHOLDER + "\n", encoding="utf-8")
                written.append(str(p.relative_to(repo)))
        if args.json:
            print(json.dumps({"version": args.version, "since": since, "user_facing": user, "internal": internal,
                              "written": written, "kept": kept}, indent=2))
        else:
            print(render_draft(args.version, since, user, internal))
            for w in written:
                print(f"wrote {w}")
            for k in kept:
                print(f"kept {k}: it already has text; not overwritten")
        return 1 if kept else 0
    except RuntimeError as e:
        print(f"whats-new: {e}", file=sys.stderr)
        return 2


def register(sp):
    q = sp.add_parser("whats-new", help="store What's New: draft from merged PRs, check that every locale has a real note",
                      description=__doc__.split("\n\n")[0])
    q.set_defaults(fn=cmd_whats_new)
    q.add_argument("action", choices=["draft", "check"])
    q.add_argument("repo", help="path to the product repo")
    q.add_argument("--version", required=True)
    q.add_argument("--since", help="draft: the git ref to start from (default: the newest version tag)")
    q.add_argument("--locales", help="comma separated, default en (e.g. en,ru,es)")
    q.add_argument("--write", action="store_true", help="draft: create docs/whats-new/<version>/<locale>.txt placeholders")
    q.add_argument("--json", action="store_true")
    return q

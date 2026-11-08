"""`teyla freshness` -- do the README, the README images, the store text and the store screenshots still match the product.

    teyla freshness [path...] [--json] [--quiet]

A README that shows a screen from 16 releases ago, or a store "What's New" that says "Bug fixes and
improvements" on every version, is wrong in a way no test sees. For each product this command asks git how many
user-facing changes (the same split `teyla whats-new` uses: docs, tests, CI, deps and listing items do not count)
landed on the default branch since the newest commit that touched each of

    readme          README.md
    readme-images   the oldest local image README.md shows
    whats-new       docs/whats-new/ (store products only; also a generic newest note)
    listing         the store listing text
    screenshots     the store screenshots

A check is stale when at least `changes` user-facing changes (default 10) landed since that commit AND the
commit is older than `days` (default 14). A product tunes it in its teyla.toml:

    [freshness]
    changes = 10
    days = 14
    skip = ["readme-images"]
    listing = ["apps/store/listing/**"]        # default: the usual places that exist
    screenshots = ["docs/screenshots/**/*.png"]

Offline: local git only, no network, no model call. Exit 0 when nothing is stale, 1 otherwise, 2 for a path
with no teyla.toml. `--quiet` prints nothing and writes `~/.teyla/freshness.problems` (`key<TAB>text`, what the
session-start banner and the weekly digest read); the file is removed when nothing is stale.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import pathlib
import re
import sys
import tomllib
import urllib.parse

from . import productize, testflight, whats_new

DEFAULT_CHANGES = 10
DEFAULT_DAYS = 14
CHECKS = ("readme", "readme-images", "whats-new", "listing", "screenshots")
DEFAULT_LISTING = ("apps/store/listing/**", "docs/store/listing*.json", "content/store/**/*.txt",
                   "fastlane/metadata/**", "store/**/*.txt")
DEFAULT_SCREENSHOTS = ("docs/screenshots/**/*.png", "docs/store/**/*.png", "content/store/**/*.png",
                       "fastlane/screenshots/**", "brand/out/store/**")

_MD_IMG = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_IMG_SRC = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']", re.I)
_SRCSET = re.compile(r"<source\b[^>]*?\bsrcset\s*=\s*[\"']([^\"']+)[\"']", re.I)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# --- settings ---------------------------------------------------------------------

def settings(repo: pathlib.Path) -> dict:
    """The `[freshness]` table with defaults filled in. A wrong type falls back to the default."""
    try:
        data = tomllib.loads((repo / "teyla.toml").read_text())
    except (tomllib.TOMLDecodeError, OSError):
        data = {}
    t = data.get("freshness") if isinstance(data.get("freshness"), dict) else {}

    def num(key: str, default: int) -> int:
        v = t.get(key)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else default

    def strs(key: str) -> list[str]:
        v = t.get(key)
        return [x for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []

    return {"changes": num("changes", DEFAULT_CHANGES), "days": num("days", DEFAULT_DAYS),
            "skip": set(strs("skip")), "listing": strs("listing"), "screenshots": strs("screenshots")}


# --- git helpers --------------------------------------------------------------------

def _glob(pattern: str) -> str:
    return f":(glob){pattern}"


def _matches(repo: pathlib.Path, patterns: list[str]) -> list[str]:
    """The patterns that match at least one file in the work tree."""
    out = []
    for pat in patterns:
        hits = glob.glob(pat, root_dir=repo, recursive=True)
        if any((repo / h).is_file() for h in hits):
            out.append(pat)
    return out


def _user_changes(repo: pathlib.Path, sha: str, cache: dict) -> list[dict]:
    if sha not in cache:
        try:
            cache[sha] = whats_new.split_changes(whats_new.merged_changes(repo, sha))[0]
        except RuntimeError:
            cache[sha] = []
    return cache[sha]


def readme_images(repo: pathlib.Path) -> list[str]:
    """Repo-relative paths of the local files README.md shows, in order of appearance, each once."""
    readme = repo / "README.md"
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    refs = _MD_IMG.findall(text) + _IMG_SRC.findall(text)
    for srcset in _SRCSET.findall(text):
        refs += [c.strip().split()[0] for c in srcset.split(",") if c.strip()]
    root = repo.resolve()
    out: list[str] = []
    for ref in refs:
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", ref, re.I):
            continue                      # http(s), data:, mailto: and protocol-relative URLs
        ref = urllib.parse.unquote(re.split(r"[?#]", ref, maxsplit=1)[0]).lstrip("/")
        if not ref:
            continue
        p = (root / ref).resolve()
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if p.is_file() and rel not in out:
            out.append(rel)
    return out


# --- one check ----------------------------------------------------------------------

def _item(check: str, verdict: str, **kw) -> dict:
    base = {"check": check, "verdict": verdict, "since": None, "changes": None, "examples": [], "path": None,
            "text": ""}
    base.update(kw)
    return base


def _evaluate(repo, product, check, label, advice, change, cfg, cache, path=None, now=None) -> dict:
    """Stale when enough user-facing changes landed since `change` and it is old enough."""
    now = now or _now()
    if change is None:
        return _item(check, "skip", path=path)
    user = _user_changes(repo, change["sha"], cache)
    age = (now - change["when"]).days
    since = change["when"].date().isoformat()
    stale = len(user) >= cfg["changes"] and age >= cfg["days"]
    examples = [f"\"{u['title']}\"" + (f" #{u['pr']}" if u["pr"] else "") for u in user[:2]]
    text = ""
    if stale:
        eg = f" (e.g. {', '.join(examples)})" if examples else ""
        text = f"{product} {label}: {len(user)} user-facing changes since {since}{eg}. {advice}"
    return _item(check, "stale" if stale else "ok", since=since, changes=len(user), path=path,
                 examples=examples, text=text)


def _version_key(name: str):
    return (tuple(int(n) for n in re.findall(r"\d+", name)), name)


def _generic_note(repo: pathlib.Path) -> str | None:
    """`docs/whats-new/<v>/<file>` of the newest version directory when a note there is a stock phrase."""
    base = repo / "docs" / "whats-new"
    dirs = [d for d in base.iterdir() if d.is_dir()] if base.is_dir() else []
    if not dirs:
        return None
    newest = max(dirs, key=lambda d: _version_key(d.name))
    for f in sorted(newest.glob("*.txt")):
        try:
            text = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text and not text.startswith("TODO") and whats_new.is_generic(text):
            return f"docs/whats-new/{newest.name}/{f.name}"
    return None


def _ships_to_store(manifest: dict, repo: pathlib.Path) -> bool:
    dist = (manifest.get("productize") or {}).get("distribution") or {}
    play = "play" in str(dist.get("android") or "").lower()
    return testflight.in_scope(manifest) or play or (repo / "docs" / "whats-new").is_dir()


def check_product(manifest: dict, now: dt.datetime | None = None) -> dict:
    repo, product = pathlib.Path(manifest["repo"]), manifest["product"]
    cfg = settings(repo)
    cache: dict = {}
    items: list[dict] = []

    def run(check, fn):
        items.append(_item(check, "skip") if check in cfg["skip"] else fn())

    def readme():
        if not (repo / "README.md").is_file():
            return _item("readme", "stale", path="README.md", text=f"{product} README: no README.md")
        return _evaluate(repo, product, "readme", "README", "Update it to what ships today.",
                         testflight.newest_change(repo, [":(literal)README.md"]), cfg, cache, "README.md", now)

    def images():
        found = []
        for rel in readme_images(repo):
            ch = testflight.newest_change(repo, [f":(literal){rel}"])
            if ch:
                found.append((ch["when"], rel, ch))
        if not found:
            return _item("readme-images", "skip")
        _, rel, ch = min(found, key=lambda x: x[0])
        return _evaluate(repo, product, "readme-images", f"README image {rel}",
                         "Re-capture it from the current build.", ch, cfg, cache, rel, now)

    def notes():
        if not _ships_to_store(manifest, repo):
            return _item("whats-new", "skip")
        base = repo / "docs" / "whats-new"
        if not base.is_dir():
            return _item("whats-new", "stale", path="docs/whats-new/",
                         text=f"{product}: no docs/whats-new/: the next store version has no What's New")
        generic = _generic_note(repo)
        if generic:
            return _item("whats-new", "stale", path=generic, text=f"{product}: {generic} is a generic line")
        return _evaluate(repo, product, "whats-new", "docs/whats-new",
                         "Write the next What's New from them.",
                         testflight.newest_change(repo, [":(literal)docs/whats-new/"]), cfg, cache,
                         "docs/whats-new/", now)

    def group(check, label, advice, configured, defaults):
        def fn():
            pats = _matches(repo, configured or list(defaults))
            if not pats:
                return _item(check, "skip")
            return _evaluate(repo, product, check, label, advice,
                             testflight.newest_change(repo, [_glob(p) for p in pats]), cfg, cache,
                             ", ".join(pats), now)
        return fn

    run("readme", readme)
    run("readme-images", images)
    run("whats-new", notes)
    run("listing", group("listing", "store listing text", "Update the listing text to what ships today.",
                         cfg["listing"], DEFAULT_LISTING))
    run("screenshots", group("screenshots", "store screenshots", "Re-capture the screenshots.",
                             cfg["screenshots"], DEFAULT_SCREENSHOTS))
    verdict = "stale" if any(i["verdict"] == "stale" for i in items) else "ok"
    return {"product": product, "repo": str(repo), "verdict": verdict, "error": None, "checks": items}


def _error(manifest: dict, msg: str) -> dict:
    return {"product": manifest["product"], "repo": str(manifest["repo"]), "verdict": "error",
            "error": msg, "checks": []}


def run(paths: list[str] | None = None, now: dt.datetime | None = None) -> list[dict]:
    rows = []
    for mp in productize.find_manifests(paths):
        m = productize.parse(mp)
        if "error" in m:
            # In the sweep `teyla productize` already reports a broken teyla.toml; named on the command
            # line it is an error row, never a silent pass (same rule as `teyla testflight`).
            if paths:
                rows.append(_error(m, f"teyla.toml does not parse: {m['error']}"))
            continue
        rows.append(check_product(m, now))
    return rows


# --- output -------------------------------------------------------------------------

def exit_code(rows: list[dict]) -> int:
    return 0 if all(r["verdict"] == "ok" for r in rows) else 1


def _stale(r: dict) -> list[dict]:
    return [c for c in r["checks"] if c["verdict"] == "stale"]


def render_text(rows: list[dict]) -> str:
    if not rows:
        return "no product with a teyla.toml found.\n"
    out = []
    for r in rows:
        if r["verdict"] == "error":
            out.append(f"{r['product']}: {r['error']}")
            continue
        stale = _stale(r)
        if not stale:
            out.append(f"{r['product']}: ok")
            continue
        out.append(f"{r['product']}: {len(stale)} stale ({', '.join(c['check'] for c in stale)})")
        out += [f"  {c['text']}" for c in stale]
    return "\n".join(out) + "\n"


def problems_path() -> pathlib.Path:
    from . import config
    return config.TEYLA_DIR / "freshness.problems"  # call time: tests and a moved home redirect it


def problem_lines(rows: list[dict]) -> list[tuple[str, str]]:
    """(key, text) per stale check: `freshness|<product>|<check>`; an error row is `freshness|<product>|error`."""
    out = []
    for r in rows:
        if r["verdict"] == "error":
            out.append((f"freshness|{r['product']}|error", f"{r['product']}: {r['error']}"))
        out += [(f"freshness|{r['product']}|{c['check']}", c["text"]) for c in _stale(r)]
    return out


def write_problems(rows: list[dict], path: pathlib.Path | None = None) -> pathlib.Path | None:
    p = path or problems_path()
    items = problem_lines(rows)
    clean = lambda s: " ".join(str(s).split())  # noqa: E731 - one line, no tabs
    try:
        if items:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text("".join(f"{clean(k)}\t{clean(t)}\n" for k, t in items))
            os.replace(tmp, p)
            return p
        p.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def cmd_freshness(args):
    quiet = getattr(args, "quiet", False)
    if args.paths and not productize.find_manifests(args.paths):
        print("teyla: no teyla.toml at " + ", ".join(args.paths), file=sys.stderr)
        return 2
    rows = run(args.paths or None)
    if quiet:
        write_problems(rows)
        return exit_code(rows)
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
    else:
        print(render_text(rows), end="")
    return exit_code(rows)


def register(sp):
    q = sp.add_parser("freshness", help="do the README, store text and screenshots still match the product",
                      description=__doc__.split("\n\n")[0])
    q.set_defaults(fn=cmd_freshness)
    q.add_argument("paths", nargs="*")
    q.add_argument("--json", action="store_true")
    q.add_argument("--quiet", action="store_true",
                   help="print nothing; write ~/.teyla/freshness.problems (removed when nothing is stale)")
    return q

"""`teyla freshness` -- do the README, the README images, the store text and the store screenshots still match the product.

    teyla freshness [path...] [--json] [--quiet] [--fetch]

A README that shows a screen from 16 releases ago, or a store "What's New" that says "Bug fixes and
improvements" on every version, is wrong in a way no test sees. For each product this command asks git how many
user-facing changes landed on the default branch since the newest commit that touched each of

    readme          README.md
    readme-images   the oldest local image README.md shows
    whats-new       the store What's New files (docs/whats-new/, **/release_notes.txt, **/whats_new.txt,
                    **/whats-new*.txt, `[freshness] whats_new`); none yet is a skip; a generic note is stale
    listing         the store listing text
    screenshots     the store screenshots

A change is user-facing when its title is not internal (the split `teyla whats-new` uses) and it touched at
least one path that is not maintenance (docs, tests, hooks, `*.md`, `teyla.toml`, locks, brand, the store files).
A check is stale when at least `changes` user-facing changes (default 10) landed since that commit AND the
commit is older than `days` (default 14). A product tunes it in its teyla.toml:

    [freshness]
    changes = 10
    days = 14
    skip = ["readme-images"]
    whats_new = ["store/notes/*.txt"]
    listing = ["apps/store/listing/**"]        # default: the usual places that exist
    screenshots = ["docs/screenshots/**/*.png"]

Offline by default: local git only, no network, no model call, so it reads the remote-tracking refs as they
are. `--fetch` first runs `git fetch --quiet origin` in each product repo (30 s limit; a failure is noted on
the product's row and the check reads the last known refs); the weekly routine passes it. Exit 0 when nothing is stale, 1 otherwise, 2 for a path
with no teyla.toml. `--quiet` prints nothing and writes `~/.teyla/freshness.problems` (`key<TAB>text`, what the
session-start banner and the weekly digest read); the file is removed when nothing is stale.
"""
from __future__ import annotations

import datetime as dt
import posixpath
import subprocess
import json
import os
import pathlib
import re
import sys
import tomllib
import urllib.parse

from . import cloud, productize, testflight, whats_new

DEFAULT_CHANGES = 10
DEFAULT_DAYS = 14
FETCH_TIMEOUT = 30
CHECKS = ("readme", "readme-images", "whats-new", "listing", "screenshots")
DEFAULT_LISTING = ("apps/store/listing/**", "docs/store/listing*.json", "content/store/**/*.txt",
                   "fastlane/metadata/**", "store/**/*.txt")
DEFAULT_SCREENSHOTS = ("docs/screenshots/**/*.png", "docs/store/**/*.png", "content/store/**/*.png",
                       "fastlane/screenshots/**", "brand/out/store/**")

DEFAULT_NOTES = ("docs/whats-new/**", "**/whats_new.txt", "**/whats-new*.txt", "**/release_notes.txt")
NO_NOTES_YET = "no What's New file yet (a first store version has none)"
# Paths a change can touch without a user ever seeing it. Matched as globs; a pattern with no `/` also
# matches a file name at any depth. The store paths themselves are added per product.
MAINTENANCE = ("*.md", "docs/**", "tests/**", "test/**", "**/*Tests/**", "**/*Test*.swift", ".github/**",
               ".githooks/**", "scripts/leak*", ".leak-allow", "teyla.toml", "check.sh", "*.lock",
               "package-lock.json", "brand/**", "design/**")

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
            "skip": set(strs("skip")), "listing": strs("listing"), "screenshots": strs("screenshots"),
            "whats_new": strs("whats_new")}


# --- git helpers --------------------------------------------------------------------

def _glob(pattern: str) -> str:
    return f":(glob){pattern}"


class Tree:
    """The files of the repo's default branch. Counting changes and dating artifacts both use `ref`
    (`cloud.default_ref`, the resolver `testflight.newest_change` uses), and files are discovered from that
    ref, not from whatever branch is checked out. Falls back to the work tree only when git cannot answer."""

    def __init__(self, repo: pathlib.Path):
        self.repo = repo
        self.ref = cloud.default_ref(repo)
        self.files = self._ls_tree()
        self._set = set(self.files) if self.files is not None else None

    def _ls_tree(self) -> list[str] | None:
        try:
            r = subprocess.run(["git", "-C", str(self.repo), "ls-tree", "-r", "-z", "--name-only", self.ref],
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        return sorted(f for f in r.stdout.split("\0") if f)

    def listing(self) -> list[str]:
        if self.files is not None:
            return self.files
        out = []
        for dirpath, dirs, names in os.walk(self.repo):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
            out += [(pathlib.Path(dirpath) / n).relative_to(self.repo).as_posix() for n in names]
        return sorted(out)

    def has(self, rel: str) -> bool:
        return rel in self._set if self._set is not None else (self.repo / rel).is_file()

    def read(self, rel: str) -> str | None:
        if self._set is not None:
            if rel not in self._set:
                return None
            try:
                r = subprocess.run(["git", "-C", str(self.repo), "show", f"{self.ref}:{rel}"],
                                   capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                return None
            return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
        try:
            return (self.repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def match(self, patterns) -> list[str]:
        res = [_glob_re(p) for p in patterns]
        return [f for f in self.listing() if any(r.match(f) for r in res)]


def _glob_re(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def maintenance_matcher(extra: list[str] | tuple = ()):
    """A function: is this repo-relative path maintenance (docs, tests, hooks, store text) rather than product?"""
    res = [(_glob_re(g), "/" not in g) for g in (*MAINTENANCE, *extra)]

    def is_maintenance(path: str) -> bool:
        base = path.rsplit("/", 1)[-1]
        return any(r.match(path) or (bare and r.match(base)) for r, bare in res)
    return is_maintenance


def merged_changes_with_files(repo: pathlib.Path, since: str, ref: str) -> list[dict]:
    """`whats_new.merged_changes` plus the commit `sha` and the `files` each change touched on the mainline
    (a merge commit against its first parent). One git call. Same order, newest first."""
    sep = "\x1f"
    out = whats_new._git(repo, "log", "--first-parent", "-m", "--name-only",
                         f"--format=\x1e%H{sep}%P{sep}%s{sep}%b{sep}", f"{since}..{ref}")
    items = []
    for rec in out.split("\x1e"):
        if not rec.strip():
            continue
        sha, parents, subject, body, files = (rec.split(sep, 4) + [""] * 5)[:5]
        subject = subject.strip()
        title, pr = subject, None
        if len(parents.split()) > 1:
            m = whats_new.MERGE_RE.match(subject)
            first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
            title = first or (m.group(2).split("/", 1)[-1].replace("-", " ") if m else subject)
            pr = int(m.group(1)) if m else None
        else:
            m = whats_new.SQUASH_RE.match(subject)
            if m:
                title, pr = m.group(1).strip(), int(m.group(2))
        if title:
            items.append({"pr": pr, "title": title, "sha": sha,
                          "files": [f for f in files.splitlines() if f.strip()]})
    return items


def _user_changes(repo: pathlib.Path, sha: str, cache: dict) -> list[dict]:
    """The changes since `sha` a user could notice: a title that is not internal AND at least one file that
    is not maintenance."""
    if sha not in cache:
        is_maint = cache.get("_maint") or maintenance_matcher()
        try:
            items = merged_changes_with_files(repo, sha, cache["_ref"])
        except RuntimeError:
            items = []
        titled = whats_new.split_changes(items)[0]
        cache[sha] = [c for c in titled if any(not is_maint(f) for f in c["files"])]
    return cache[sha]


def readme_images(repo: pathlib.Path, tree: Tree | None = None) -> list[str]:
    """Repo-relative paths of the files README.md shows (read from the default branch), in order of
    appearance, each once."""
    tree = tree or Tree(repo)
    text = tree.read("README.md")
    if text is None:
        return []
    refs = _MD_IMG.findall(text) + _IMG_SRC.findall(text)
    for srcset in _SRCSET.findall(text):
        refs += [c.strip().split()[0] for c in srcset.split(",") if c.strip()]
    out: list[str] = []
    for ref in refs:
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", ref, re.I):
            continue                      # http(s), data:, mailto: and protocol-relative URLs
        ref = urllib.parse.unquote(re.split(r"[?#]", ref, maxsplit=1)[0]).lstrip("/")
        rel = posixpath.normpath(ref) if ref else ""
        if not rel or rel == "." or rel.startswith("../") or rel == "..":
            continue
        if tree.has(rel) and rel not in out:
            out.append(rel)
    return out


BRAND_WORDS = ("logo", "icon", "lockup", "badge", "mark")


def is_brand_image(rel: str) -> bool:
    """A logo or brand mark: it never needs re-capturing from a build."""
    low = rel.lower()
    return low.startswith("brand/") or low.endswith(".svg") or any(w in low.rsplit("/", 1)[-1] for w in BRAND_WORDS)


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


def notes_files(tree: Tree, extra: list[str]) -> list[str]:
    """Files of the default branch that hold a store What's New: docs/whats-new/, store metadata files,
    configured globs."""
    return tree.match([*DEFAULT_NOTES, *extra])


def _generic_note(tree: Tree, files: list[str]) -> str | None:
    """The first notes file whose whole text is a stock phrase. Under docs/whats-new/ only the newest
    version directory counts (older versions keep what they shipped); any other file is the current text."""
    prefix = "docs/whats-new/"
    versions = {f.split("/")[2] for f in files if f.startswith(prefix) and f.count("/") >= 3}
    newest = max(versions, key=_version_key) if versions else None
    for f in files:
        if f.startswith(prefix) and not (newest and f.startswith(f"{prefix}{newest}/")):
            continue
        text = (tree.read(f) or "").strip()
        if text and not text.startswith("TODO") and whats_new.is_generic(text):
            return f
    return None


def _ships_to_store(manifest: dict) -> bool:
    dist = (manifest.get("productize") or {}).get("distribution") or {}
    return testflight.in_scope(manifest) or "play" in str(dist.get("android") or "").lower()


def check_product(manifest: dict, now: dt.datetime | None = None) -> dict:
    repo, product = pathlib.Path(manifest["repo"]), manifest["product"]
    cfg = settings(repo)
    tree = Tree(repo)
    cache: dict = {"_ref": tree.ref, "_maint": maintenance_matcher((*(cfg["listing"] or DEFAULT_LISTING),
                                                  *(cfg["screenshots"] or DEFAULT_SCREENSHOTS),
                                                  *DEFAULT_NOTES, *cfg["whats_new"]))}
    items: list[dict] = []

    def run(check, fn):
        items.append(_item(check, "skip") if check in cfg["skip"] else fn())

    def readme():
        if not tree.has("README.md"):
            return _item("readme", "stale", path="README.md", text=f"{product} README: no README.md")
        return _evaluate(repo, product, "readme", "README", "Update it to what ships today.",
                         testflight.newest_change(repo, [":(literal)README.md"]), cfg, cache, "README.md", now)

    def images():
        found = []
        for rel in (r for r in readme_images(repo, tree) if not is_brand_image(r)):
            ch = testflight.newest_change(repo, [f":(literal){rel}"])
            if ch:
                found.append((ch["when"], rel, ch))
        if not found:
            return _item("readme-images", "skip")
        _, rel, ch = min(found, key=lambda x: x[0])
        return _evaluate(repo, product, "readme-images", f"README image {rel}",
                         "Re-capture it from the current build.", ch, cfg, cache, rel, now)

    def notes():
        files = notes_files(tree, cfg["whats_new"])
        if not files:
            # The policy asks for What's New from the second store version on; a first version has none.
            return _item("whats-new", "skip", text=NO_NOTES_YET if _ships_to_store(manifest) else "")
        generic = _generic_note(tree, files)
        if generic:
            return _item("whats-new", "stale", path=generic, text=f"{product}: {generic} is a generic line")
        where = "docs/whats-new" if any(f.startswith("docs/whats-new/") for f in files) else files[0]
        return _evaluate(repo, product, "whats-new", where, "Write the next What's New from them.",
                         testflight.newest_change(repo, [f":(literal){f}" for f in files]), cfg, cache,
                         where, now)

    notes_patterns = [*DEFAULT_NOTES, *cfg["whats_new"]]

    def group(check, label, advice, configured, defaults, drop_notes=False):
        def fn():
            notes = set(tree.match(notes_patterns)) if drop_notes else set()
            pats = [p for p in (configured or list(defaults)) if set(tree.match([p])) - notes]
            if not pats:
                return _item(check, "skip")
            spec = [_glob(p) for p in pats] + ([f":(exclude,glob){n}" for n in notes_patterns] if drop_notes else [])
            return _evaluate(repo, product, check, label, advice, testflight.newest_change(repo, spec),
                             cfg, cache, ", ".join(pats), now)
        return fn

    run("readme", readme)
    run("readme-images", images)
    run("whats-new", notes)
    run("listing", group("listing", "store listing text", "Update the listing text to what ships today.",
                         cfg["listing"], DEFAULT_LISTING, drop_notes=True))
    run("screenshots", group("screenshots", "store screenshots", "Re-capture the screenshots.",
                             cfg["screenshots"], DEFAULT_SCREENSHOTS))
    verdict = "stale" if any(i["verdict"] == "stale" for i in items) else "ok"
    return {"product": product, "repo": str(repo), "verdict": verdict, "error": None, "checks": items}


def _error(manifest: dict, msg: str) -> dict:
    return {"product": manifest["product"], "repo": str(manifest["repo"]), "verdict": "error",
            "error": msg, "checks": []}


def fetch_origin(repo: pathlib.Path) -> str | None:
    """`git fetch --quiet origin` in `repo`. None on success, else a short reason. Never raises."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin"], capture_output=True,
                           text=True, timeout=FETCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"timed out after {FETCH_TIMEOUT} s"
    except (OSError, subprocess.SubprocessError) as e:
        return type(e).__name__
    if r.returncode == 0:
        return None
    lines = [ln.strip() for ln in (r.stderr or r.stdout).splitlines() if ln.strip()]
    return (lines[0] if lines else f"exit {r.returncode}")[:120]


def run(paths: list[str] | None = None, now: dt.datetime | None = None, fetch: bool = False) -> list[dict]:
    rows = []
    for mp in productize.find_manifests(paths):
        m = productize.parse(mp)
        if "error" in m:
            # In the sweep `teyla productize` already reports a broken teyla.toml; named on the command
            # line it is an error row, never a silent pass (same rule as `teyla testflight`).
            if paths:
                rows.append(_error(m, f"teyla.toml does not parse: {m['error']}"))
            continue
        err = fetch_origin(pathlib.Path(m["repo"])) if fetch else None
        row = check_product(m, now)
        if fetch:
            row["fetch"] = "ok" if err is None else f"failed: {err}"
        rows.append(row)
    return rows


# --- output -------------------------------------------------------------------------

def exit_code(rows: list[dict]) -> int:
    return 0 if all(r["verdict"] == "ok" for r in rows) else 1


def _stale(r: dict) -> list[dict]:
    return [c for c in r["checks"] if c["verdict"] == "stale"]


HINT = "Results read local refs; `teyla freshness --fetch` refreshes them first."


def render_text(rows: list[dict], fetched: bool = False) -> str:
    if not rows:
        return "no product with a teyla.toml found.\n"
    out = []
    for r in rows:
        if r.get("fetch", "ok").startswith("failed"):
            out.append(f"{r['product']}: fetch {r['fetch']}; read the last known refs")
        if r["verdict"] == "error":
            out.append(f"{r['product']}: {r['error']}")
            continue
        stale = _stale(r)
        if not stale:
            out.append(f"{r['product']}: ok")
            continue
        out.append(f"{r['product']}: {len(stale)} stale ({', '.join(c['check'] for c in stale)})")
        out += [f"  {c['text']}" for c in stale]
    if not fetched and any(_stale(r) for r in rows if r["verdict"] != "error"):
        out.append(HINT)
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
    fetch = getattr(args, "fetch", False)
    rows = run(args.paths or None, fetch=fetch)
    if quiet:
        write_problems(rows)
        return exit_code(rows)
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
    else:
        print(render_text(rows, fetched=fetch), end="")
    return exit_code(rows)


def register(sp):
    q = sp.add_parser("freshness", help="do the README, store text and screenshots still match the product",
                      description=__doc__.split("\n\n")[0])
    q.set_defaults(fn=cmd_freshness)
    q.add_argument("paths", nargs="*")
    q.add_argument("--json", action="store_true")
    q.add_argument("--fetch", action="store_true",
                   help="git fetch origin in each product repo first (a failure is noted, not fatal)")
    q.add_argument("--quiet", action="store_true",
                   help="print nothing; write ~/.teyla/freshness.problems (removed when nothing is stale)")
    return q

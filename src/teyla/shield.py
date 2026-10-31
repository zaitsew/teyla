"""`teyla shield` — does a product keep its security contract, and how old is the proof.

A repo declares its contract in the same `teyla.toml` that holds `[productize]`:

    [security]
    tier = "public"                 # owner | family | testers | public (default: [productize] users)
    data = ["account", "location"]  # account location health messages payments files none
    trifecta = ["private-data", "outbound"]
    secrets = "runtime-env"         # runtime-env | keychain | hub | none (never: repo, client)
    hosts = "docs/PRIVACY.md"
    mcp = { auth = "bearer", url_key = false, rate_limit = true, static_tools = true }
    rls = "migrations+ab-test"      # none | migrations | migrations+ab-test
    release = ["leak", "rls-test<30d"]

    [[security.evidence]]
    what = "rls-test"
    commit = "abc1234"
    date = 2026-10-31
    how = "deno task test:tenancy"

`teyla shield check <repo> [--release] [--json]` prints one line per requirement of the tier:
OK, FIX (with the one-line fix), STALE (evidence older than its limit) or NOTE (reported, never
blocking). Some requirements are read from the repo (hooks, lockfile, RLS in migrations, a
privacy manifest); the rest cannot be read from files and are proved by dated evidence rows that
expire. `teyla shield` with no arguments prints one table for every repo that has a section.

Exit 0: no FIX (and no STALE with `--release`). Exit 1: a FIX, or a STALE with `--release`.
Exit 2: no `[security]` section, which prints the template to paste. See docs/CONTRACT.md.

Nothing here touches the network. The checks run `git`, the leak scanner and, when the command
exists, `teyla hosts` as subprocesses.
"""
from __future__ import annotations

import argparse
import datetime
import functools
import json
import os
import pathlib
import re
import subprocess
import sys
import tomllib

TIERS = ("owner", "family", "testers", "public")
RANK = {"owner": 0, "family": 1, "testers": 1, "public": 2}
DATA_CLASSES = ("account", "location", "health", "messages", "payments", "files", "none")
LEGS = ("private-data", "untrusted-content", "outbound")
SECRETS_OK = ("runtime-env", "keychain", "hub", "none")
SECRETS_BAD = ("repo", "client")
RLS_VALUES = ("none", "migrations", "migrations+ab-test")
DEFAULT_MAX_AGE = 30
SECTION_BEGIN = "# --- security contract ---"
SECTION_END = "# --- end security contract ---"
NOT_ENFORCED = "not enforced on this machine: credential separation (see SHIELD §5.7)"

# The order rows print in, and every name `release = [...]` may use.
ORDER = ("contract", "leak", "hooks", "hosts", "lockfile", "secrets", "trifecta", "rls", "rls-test",
         "privacy-manifest", "no-token-in-defaults", "mcp", "probe", "deps", "release-notes",
         "credential-separation")
ALIASES = {"mcp-probe": "probe"}
SHORT = {"contract": "cont", "leak": "leak", "hooks": "hook", "hosts": "host", "lockfile": "lock",
         "secrets": "secr", "trifecta": "trif", "rls": "rls", "rls-test": "rlst",
         "privacy-manifest": "priv", "no-token-in-defaults": "tokd", "mcp": "mcp", "probe": "prob",
         "deps": "deps", "credential-separation": "cred"}
# What evidence row proves a requirement, and the sentence that says how to produce it.
EVIDENCE = {
    "rls-test": ("rls-test", "run the tenancy test (anonymous, user A and user B on every table and RPC)"),
    "deps": ("deps", "run a dependency audit (teyla deps) and record the commit"),
    "probe": ("mcp-probe", "run teyla mcp probe against the product's own server"),
    "credential-separation": ("credential-separation", "work through the owner's steps in SHIELD §5.7"),
}
SKIP_DIRS = {".git", "node_modules", ".build", "Pods", "DerivedData", "build", ".venv", "venv", "vendor",
             "Carthage", ".gradle", "dist", "__pycache__", ".swiftpm", ".next"}
MIGRATION_GLOBS = ("supabase/migrations/*.sql", "*/supabase/migrations/*.sql")
SENSITIVE_KEY = re.compile(r"token|secret|password|api[_-]?key", re.I)
HOOKS = ("pre-commit", "pre-push")


# --- loading ---------------------------------------------------------------------

def load(repo: pathlib.Path) -> tuple[dict | None, str]:
    """({toml}, "") or (None, reason) when teyla.toml is missing or will not parse."""
    path = repo / "teyla.toml"
    if not path.is_file():
        return None, f"{repo}: no teyla.toml"
    try:
        return tomllib.loads(path.read_text(encoding="utf-8")), ""
    except (tomllib.TOMLDecodeError, OSError) as e:
        return None, f"{path}: {e}"


def template_section() -> str:
    """The [security] section of templates/repo/teyla.toml, ready to paste."""
    try:
        import teyla
        text = (teyla.templates_dir() / "repo" / "teyla.toml").read_text(encoding="utf-8")
        a, b = text.index(SECTION_BEGIN), text.index(SECTION_END)
        return text[a:b + len(SECTION_END)] + "\n"
    except (OSError, ValueError, FileNotFoundError):
        return '[security]\ndata = []\ntrifecta = []\nsecrets = "runtime-env"\nhosts = "docs/PRIVACY.md"\n'


def _date(v) -> datetime.date | None:
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    if isinstance(v, str):
        try:
            return datetime.date.fromisoformat(v.strip())
        except ValueError:
            return None
    return None


class Ctx:
    """Everything a check reads, resolved once."""

    def __init__(self, repo: pathlib.Path, data: dict, release: bool, today: datetime.date):
        self.repo, self.data, self.release, self.today = repo, data, release, today
        sec = data.get("security")
        self.sec = sec if isinstance(sec, dict) else {}
        users = (data.get("productize") or {}).get("users") if isinstance(data.get("productize"), dict) else None
        self.users = users if users in TIERS else "owner"
        explicit = self.sec.get("tier")
        self.tier = explicit if explicit in TIERS else self.users
        self.tier_explicit = explicit in TIERS
        self.rank = RANK[self.tier]
        self.mcp = self.sec["mcp"] if isinstance(self.sec.get("mcp"), dict) else None
        self.problems: list[str] = []
        self.evidence = self._evidence()
        self.release_names, self.release_limits = self._release_list()
        self.migrations = self._migrations()

    def _evidence(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        raw = self.sec.get("evidence", [])
        if not isinstance(raw, list):
            self.problems.append("security.evidence must be a list of [[security.evidence]] tables")
            return out
        for i, row in enumerate(raw, 1):
            if not isinstance(row, dict):
                self.problems.append(f"evidence row {i} is not a table")
                continue
            what = str(row.get("what", "")).strip()
            missing = [k for k in ("what", "commit", "date", "how") if not str(row.get(k, "")).strip()]
            d = _date(row.get("date"))
            if missing:
                self.problems.append(f"evidence row {i} ({what or '?'}) lacks {', '.join(missing)}")
                continue
            if d is None:
                self.problems.append(f"evidence row {i} ({what}) has a date that is not YYYY-MM-DD")
                continue
            if d > self.today:
                self.problems.append(f"evidence row {i} ({what}) is dated in the future")
                continue
            age = row.get("max_age_days")
            if age is not None and (not isinstance(age, int) or isinstance(age, bool) or age < 1):
                self.problems.append(f"evidence row {i} ({what}) max_age_days must be a positive integer")
                continue
            out.setdefault(what, []).append({"what": what, "commit": str(row["commit"]), "date": d,
                                             "how": str(row["how"]), "max_age": age})
        for rows in out.values():
            rows.sort(key=lambda r: r["date"])
        return out

    def _release_list(self) -> tuple[list[str], dict[str, int]]:
        names, limits = [], {}
        raw = self.sec.get("release", [])
        if not isinstance(raw, list):
            self.problems.append("release must be a list of requirement names")
            return names, limits
        for item in raw:
            m = re.fullmatch(r"\s*([a-z-]+)\s*(?:<\s*(\d+)\s*d)?\s*", str(item))
            name = ALIASES.get(m.group(1), m.group(1)) if m else None
            if not m or name not in ORDER or name == "contract":
                self.problems.append(f"release names {item!r}, which is not a requirement")
                continue
            names.append(name)
            if m.group(2):
                limits[name] = int(m.group(2))
        return names, limits

    def _migrations(self) -> list[pathlib.Path]:
        found: list[pathlib.Path] = []
        for g in MIGRATION_GLOBS:
            found += [p for p in self.repo.glob(g) if p.is_file()]
        return sorted(found)

    def newest(self, what: str) -> dict | None:
        rows = self.evidence.get(what)
        return rows[-1] if rows else None


def required(c: Ctx) -> list[str]:
    names = ["contract", "leak", "hooks", "hosts", "lockfile", "secrets", "trifecta"]
    rls_declared = c.sec.get("rls") in ("migrations", "migrations+ab-test")
    if c.migrations or rls_declared:
        names.append("rls")
    if c.rank >= 1:
        names += ["rls-test", "privacy-manifest", "no-token-in-defaults"]
        names.append("mcp")
        if c.mcp is not None:
            names.append("probe")
    elif c.mcp is not None:
        names.append("mcp")
    if c.rank >= 2:
        names += ["deps", "credential-separation"]
    if c.release:
        if c.rank >= 1:
            names.append("release-notes")
        names += c.release_names
    return [n for n in ORDER if n in set(names)]


# --- helpers over the file tree --------------------------------------------------

def _walk(repo: pathlib.Path, depth: int):
    """(dirpath, dirnames, filenames) down to `depth` levels, skipping build and vendor directories."""
    base = len(repo.parts)
    for root, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        if len(pathlib.Path(root).parts) - base >= depth:
            dirs[:] = []
        yield pathlib.Path(root), dirs, files


def _git(repo: pathlib.Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None


def _is_git(repo: pathlib.Path) -> bool:
    return (repo / ".git").exists()


def _tracked(repo: pathlib.Path) -> list[str]:
    """Tracked paths in a git repo; every file on disk (outside build dirs) when it is not one."""
    if _is_git(repo):
        r = _git(repo, "ls-files")
        if r is not None and r.returncode == 0:
            return r.stdout.splitlines()
    out = []
    for root, _dirs, files in _walk(repo, 6):
        out += [str((root / f).relative_to(repo)) for f in files]
    return out


@functools.lru_cache(maxsize=1)
def _commands() -> frozenset:
    try:
        from . import cli
        return frozenset(cli._commands(cli.build_parser()))
    except Exception:
        return frozenset()


def _cli_has(name: str) -> bool:
    """Does this checkout's `teyla` have the subcommand `name`? Other lanes ship `leak` and `hosts`."""
    return name in _commands()


def _run(cmd: list[str], repo: pathlib.Path, timeout: int = 180) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    except OSError as e:
        return 127, str(e)
    out = (p.stdout + p.stderr).strip()
    return p.returncode, out.splitlines()[0] if out else ""


# --- facts -----------------------------------------------------------------------

def _leak_command(repo: pathlib.Path) -> list[str] | None:
    if _cli_has("leak"):
        return [sys.executable, "-m", "teyla", "leak", "--quiet"]
    script = repo / "scripts" / "leak_check.py"
    if script.is_file():
        return [sys.executable, str(script), "--quiet"]
    import importlib.util
    try:
        if importlib.util.find_spec("teyla._leak_check") is not None:
            return [sys.executable, "-m", "teyla._leak_check", "--quiet"]
    except (ImportError, ValueError):
        pass
    return None


def _hosts_command(repo: pathlib.Path) -> list[str] | None:
    return [sys.executable, "-m", "teyla", "hosts", str(repo)] if _cli_has("hosts") else None


def check_leak(c: Ctx):
    cmd = _leak_command(c.repo)
    if cmd is None:
        return "FIX", "install the leak gate (teyla leak, or scripts/leak_check.py)"
    rc, out = _run(cmd, c.repo)
    if rc == 0:
        return "OK", "no findings"
    if rc == 1:
        return "FIX", f"the leak scan found {out or 'findings'}; run it without --quiet and remove them"
    return "FIX", f"the leak scanner failed (exit {rc}){': ' + out if out else ''}"


def check_hooks(c: Ctx):
    hooks_dir = c.repo / ".githooks"
    missing = [h for h in HOOKS if not (hooks_dir / h).is_file()]
    if missing:
        return "FIX", f"add .githooks/{' and .githooks/'.join(missing)}"
    plain = [h for h in HOOKS if not os.access(hooks_dir / h, os.X_OK)]
    if plain:
        return "FIX", f"chmod +x .githooks/{' .githooks/'.join(plain)}"
    r = _git(c.repo, "config", "--get", "core.hooksPath")
    path = r.stdout.strip() if r is not None and r.returncode == 0 else ""
    if not path:
        return "FIX", "run: git config core.hooksPath .githooks"
    target = pathlib.Path(path)
    target = target if target.is_absolute() else c.repo / target
    if target.resolve() != hooks_dir.resolve():
        return "FIX", f"core.hooksPath is {path}; set it to .githooks"
    return "OK", "pre-commit and pre-push installed"


def _has_table(text: str) -> bool:
    lines = text.splitlines()
    return any(re.match(r"\s*\|.*\|\s*$", a) and re.match(r"\s*\|[\s:|-]+\|\s*$", b) and "-" in b
               for a, b in zip(lines, lines[1:]))


def check_hosts(c: Ctx):
    rel = str(c.sec.get("hosts") or "docs/PRIVACY.md")
    path = (c.repo / rel).resolve()
    try:
        path.relative_to(c.repo.resolve())
    except ValueError:
        return "FIX", f"hosts = {rel!r} points outside the repo"
    if not path.is_file():
        return "FIX", f"write {rel}: one row per outbound host (teyla hosts --write drafts it)"
    if not _has_table(path.read_text(encoding="utf-8", errors="replace")):
        return "FIX", f"{rel} has no table of hosts"
    cmd = _hosts_command(c.repo)
    if cmd is not None:
        rc, out = _run(cmd, c.repo)
        if rc != 0:
            return "FIX", f"teyla hosts: {out or 'undocumented host (exit ' + str(rc) + ')'}"
        return "OK", f"{rel} matches the code"
    return "OK", f"{rel} exists with a table (teyla hosts not available here, so not compared with the code)"


def _lock_dirs(repo: pathlib.Path):
    """(directory, ecosystem, lockfile names) for each dependency manifest found."""
    found = []
    for root, _dirs, files in _walk(repo, 3):
        names = set(files)

        def add(eco, locks):
            found.append((root, eco, locks))
        if "package.json" in names:
            add("npm", ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb"))
        if names & {"deno.json", "deno.jsonc"}:
            add("deno", ("deno.lock",))
        if "Package.swift" in names:
            add("swift", ("Package.resolved",))
        if "project.yml" in names and "packages:" in (root / "project.yml").read_text(errors="replace"):
            add("swift", ("Package.resolved",))
        if "pyproject.toml" in names and _py_has_deps(root / "pyproject.toml"):
            add("python", ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock"))
        elif "requirements.txt" in names:
            add("python", ("uv.lock", "poetry.lock", "pdm.lock", "Pipfile.lock"))
        if "Gemfile" in names:
            add("ruby", ("Gemfile.lock",))
        if "go.mod" in names:
            add("go", ("go.sum",))
        if "Cargo.toml" in names:
            add("rust", ("Cargo.lock",))
    return found


def _py_has_deps(path: pathlib.Path) -> bool:
    try:
        d = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return True
    proj = d.get("project") or {}
    return bool(proj.get("dependencies") or proj.get("optional-dependencies")
                or d.get("dependency-groups") or (d.get("tool") or {}).get("poetry", {}).get("dependencies"))


def check_lockfile(c: Ctx):
    manifests = _lock_dirs(c.repo)
    if not manifests:
        return "OK", "n/a: no dependency manifest"
    bad = []
    for root, eco, locks in manifests:
        if not any((root / l).is_file() or (c.repo / l).is_file() for l in locks):
            bad.append(f"{eco} in {root.relative_to(c.repo) or '.'} ({locks[0]})")
    if bad:
        return "FIX", "commit a lockfile: " + "; ".join(bad)
    return "OK", "lockfile present for " + ", ".join(sorted({e for _r, e, _l in manifests}))


def _strip_sql(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"--[^\n]*", " ", text)


def _name(group: str) -> str:
    return rf'(?P<{group}>(?:"?\w+"?\.)?"?\w+"?)'


_SQL = re.compile(
    rf"\bcreate\s+(?:unlogged\s+)?table\s+(?:if\s+not\s+exists\s+)?{_name('create')}"
    rf"|\balter\s+table\s+(?:if\s+exists\s+)?(?:only\s+)?{_name('rls')}\s+enable\s+row\s+level\s+security"
    rf"|\bdrop\s+table\s+(?:if\s+exists\s+)?{_name('drop')}", re.I)


def _table_name(raw: str) -> str | None:
    name = raw.replace('"', "").lower()
    if "." in name:
        schema, _, name = name.partition(".")
        if schema != "public":
            return None                      # a private schema is not exposed by the data API
    return name


def tables_without_rls(files: list[pathlib.Path]) -> tuple[list[str], int]:
    tables: dict[str, bool] = {}
    for f in files:
        text = _strip_sql(f.read_text(encoding="utf-8", errors="replace"))
        for m in _SQL.finditer(text):
            kind = next(k for k in ("create", "rls", "drop") if m.group(k))
            name = _table_name(m.group(kind))
            if name is None:
                continue
            if kind == "create":
                tables.setdefault(name, False)
            elif kind == "rls" and name in tables:
                tables[name] = True
            elif kind == "drop":
                tables.pop(name, None)
    return sorted(t for t, ok in tables.items() if not ok), len(tables)


def check_rls(c: Ctx):
    if not c.migrations:
        return "FIX", f"rls = {c.sec.get('rls')!r} but no supabase/migrations/*.sql was found"
    bad, total = tables_without_rls(c.migrations)
    if bad:
        shown = ", ".join(bad[:5]) + (f" (+{len(bad) - 5} more)" if len(bad) > 5 else "")
        return "FIX", f"enable row level security on: {shown}"
    return "OK", f"all {total} table(s) in migrations enable row level security"


def _apple(repo: pathlib.Path) -> bool:
    for root, dirs, files in _walk(repo, 3):
        if any(d.endswith(".xcodeproj") for d in dirs):
            return True
        if "project.yml" in files and "targets:" in (root / "project.yml").read_text(errors="replace"):
            return True
    return False


def check_privacy_manifest(c: Ctx):
    if not _apple(c.repo):
        return "OK", "n/a: no Xcode project"
    for _root, _dirs, files in _walk(c.repo, 6):
        if "PrivacyInfo.xcprivacy" in files:
            return "OK", "PrivacyInfo.xcprivacy present"
    return "FIX", "add PrivacyInfo.xcprivacy to the app target"


_STORE_LINE = re.compile(r"(?i)\b(userdefaults|appstorage|sharedpreferences|preferences|prefs|defaults)\b|\.edit\(\)")
_WRITE_LINE = re.compile(r"\.set\(|setValue\(|forKey:|@AppStorage|put\w*\(|\.edit\(\)")
_LITERAL = re.compile(r'"([^"\n]*)"')


def find_token_defaults(repo: pathlib.Path) -> list[str]:
    hits = []
    for root, _dirs, files in _walk(repo, 8):
        for f in files:
            if not f.endswith((".swift", ".kt", ".kts", ".java")):
                continue
            path = root / f
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for n, line in enumerate(lines, 1):
                if line.lstrip().startswith("//") or not _STORE_LINE.search(line) or not _WRITE_LINE.search(line):
                    continue
                if any(SENSITIVE_KEY.search(lit) for lit in _LITERAL.findall(line)):
                    hits.append(f"{path.relative_to(repo)}:{n}")
    return hits


def check_no_token_in_defaults(c: Ctx):
    hits = find_token_defaults(c.repo)
    if hits:
        more = f" (+{len(hits) - 3} more)" if len(hits) > 3 else ""
        return "FIX", f"a token-named key is written to UserDefaults or SharedPreferences ({', '.join(hits[:3])}{more}); use the Keychain or the Keystore"
    return "OK", "no token-named key in UserDefaults or SharedPreferences"


def _env_ignored(c: Ctx) -> bool:
    if _is_git(c.repo):
        r = _git(c.repo, "check-ignore", "-q", ".env")
        return r is not None and r.returncode == 0
    gi = c.repo / ".gitignore"
    lines = [l.strip() for l in gi.read_text(errors="replace").splitlines()] if gi.is_file() else []
    return any(l in (".env", "/.env", ".env*", "*.env", ".env.*") for l in lines)


def check_secrets(c: Ctx):
    where = c.sec.get("secrets")
    if where in SECRETS_BAD:
        return "FIX", f"secrets live in the {where}: move them to runtime-env, keychain or hub"
    if where not in SECRETS_OK:
        return "FIX", f"declare secrets = one of {', '.join(SECRETS_OK)}"
    problems = []
    if not _env_ignored(c):
        problems.append("add .env to .gitignore")
    tracked = _tracked(c.repo)
    bad = [p for p in tracked if pathlib.PurePosixPath(p).name == ".env"
           or p.endswith((".p8", ".pem")) or re.fullmatch(r"id_rsa(\.pem)?", pathlib.PurePosixPath(p).name)]
    if bad:
        problems.append("untrack " + ", ".join(bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else ""))
    if problems:
        return "FIX", "; ".join(problems)
    return "OK", f"secrets = {where}; .env ignored; no key file tracked"


def check_trifecta(c: Ctx):
    raw = c.sec.get("trifecta", [])
    legs = [str(x) for x in raw] if isinstance(raw, list) else []
    if all(leg in legs for leg in LEGS):
        split = c.newest("executor-split")
        if split:
            return "OK", f"all three legs, with the executor split documented ({split['date']}, commit {split['commit']})"
        return "FIX", "cut a leg or document the executor split (an evidence row with what = \"executor-split\")"
    return "OK", f"{len(legs)} of 3 legs" + (f": {', '.join(legs)}" if legs else "")


def check_mcp(c: Ctx):
    if c.mcp is None:
        return "OK", "n/a: no MCP server declared"
    if c.mcp.get("url_key") is True:
        return "FIX", "the URL is the secret: move the key to an Authorization header"
    auth = str(c.mcp.get("auth", "")).lower()
    if auth in ("", "none") and c.rank >= 1:
        return "FIX", "an MCP server for other people needs auth (bearer or oauth)"
    if c.rank >= 2 and c.mcp.get("rate_limit") is not True:
        return "FIX", "a public MCP server needs a rate limit (rate_limit = true)"
    return "OK", f"auth = {auth or 'none'}, url_key = false"


def check_release_notes(c: Ctx):
    candidates = ["docs/APP-STORE.md", "docs/PLAY-STORE.md", "docs/REVIEW-NOTES.md", "store/REVIEW-NOTES.md",
                  "templates/store/REVIEW-NOTES.md"]
    pat = re.compile(r"^\s*(?:#+\s*|\*\*)?DATA\b")
    for rel in candidates:
        p = c.repo / rel
        if p.is_file() and any(pat.match(l) for l in p.read_text(encoding="utf-8", errors="replace").splitlines()):
            return "OK", f"DATA paragraph in {rel}"
    return "FIX", "add a DATA paragraph to the review notes (docs/APP-STORE.md; template: templates/store/REVIEW-NOTES.md)"


def check_contract(c: Ctx):
    problems = list(c.problems)
    explicit = c.sec.get("tier")
    if explicit is not None and explicit not in TIERS:
        problems.append(f"tier {explicit!r} is not one of {', '.join(TIERS)}")
    data = c.sec.get("data")
    if not isinstance(data, list) or not data:
        problems.append('declare data = ["account", ...] or ["none"]')
    else:
        bad = [d for d in data if d not in DATA_CLASSES]
        if bad:
            problems.append(f"unknown data class {bad[0]!r}")
        if "none" in data and len(data) > 1:
            problems.append('data = ["none"] cannot list other classes')
    legs = c.sec.get("trifecta", [])
    if not isinstance(legs, list) or [l for l in legs if l not in LEGS]:
        problems.append(f"trifecta takes {', '.join(LEGS)}")
    rls = c.sec.get("rls")
    if rls is not None and rls not in RLS_VALUES:
        problems.append(f"rls {rls!r} is not one of {', '.join(RLS_VALUES)}")
    if c.sec.get("mcp") is not None and c.mcp is None:
        problems.append("mcp must be a table")
    if problems:
        return "FIX", "; ".join(problems)
    src = "explicit" if c.tier_explicit else ("from [productize] users" if "productize" in c.data else "default")
    return "OK", f"tier {c.tier} ({src})"


def check_evidence(c: Ctx, req: str):
    what, hint = EVIDENCE[req]
    if req == "rls-test" and not (c.migrations or c.sec.get("rls") in ("migrations", "migrations+ab-test")):
        return "OK", "n/a: no database migrations"
    row = c.newest(what)
    if row is None:
        return ("NOTE" if req == "credential-separation" else "FIX"), \
            f"no evidence: {hint}, then add a [[security.evidence]] row with what = \"{what}\""
    limit = row["max_age"] or DEFAULT_MAX_AGE
    if c.release and req in c.release_limits:
        limit = min(limit, c.release_limits[req])
    age = (c.today - row["date"]).days
    if age > limit:
        status = "NOTE" if req == "credential-separation" else "STALE"
        return status, f"{age}d old, limit {limit}d: {hint}, then add a new row"
    return "OK", f"{age}d old, limit {limit}d (commit {row['commit']})"


CHECKS = {
    "contract": check_contract, "leak": check_leak, "hooks": check_hooks, "hosts": check_hosts,
    "lockfile": check_lockfile, "secrets": check_secrets, "trifecta": check_trifecta, "rls": check_rls,
    "privacy-manifest": check_privacy_manifest, "no-token-in-defaults": check_no_token_in_defaults,
    "mcp": check_mcp, "release-notes": check_release_notes,
    "rls-test": lambda c: check_evidence(c, "rls-test"), "probe": lambda c: check_evidence(c, "probe"),
    "deps": lambda c: check_evidence(c, "deps"), "credential-separation": lambda c: check_evidence(c, "credential-separation"),
}


# --- report ----------------------------------------------------------------------

def credential_state(c: Ctx) -> tuple[bool, int | None]:
    """(fresh, age in days) of the credential-separation evidence."""
    row = c.newest("credential-separation")
    if row is None:
        return False, None
    age = (c.today - row["date"]).days
    return age <= (row["max_age"] or DEFAULT_MAX_AGE), age


def check(repo: pathlib.Path, *, release: bool = False, today: datetime.date | None = None) -> dict | None:
    """The report for one repo, or None when it has no [security] section."""
    repo = pathlib.Path(repo).expanduser().resolve()
    data, _err = load(repo)
    if data is None or not isinstance(data.get("security"), dict):
        return None
    c = Ctx(repo, data, release, today or datetime.date.today())
    rows = []
    for name in required(c):
        status, detail = CHECKS[name](c)
        rows.append({"name": name, "status": status, "detail": detail})
    if c.tier_explicit and RANK[c.tier] < RANK[c.users]:
        rows.insert(1, {"name": "tier", "status": "NOTE",
                        "detail": f"tier {c.tier} is below [productize] users = {c.users}"})
    counts = {s: sum(r["status"] == s for r in rows) for s in ("OK", "FIX", "STALE", "NOTE")}
    fresh, _age = credential_state(c)
    ages = [(c.today - r["date"]).days for rs in c.evidence.values() for r in rs]
    code = 1 if counts["FIX"] or (release and counts["STALE"]) else 0
    return {"repo": repo.name, "path": str(repo), "tier": c.tier, "release": release, "exit": code,
            "ok": code == 0, "counts": counts, "requirements": rows,
            "not_enforced": [] if fresh else ["credential separation"],
            "evidence_oldest_days": max(ages) if ages else None}


def render_text(rep: dict) -> str:
    lines = [NOT_ENFORCED] if rep["not_enforced"] else []
    lines.append(f"shield {rep['repo']}: tier {rep['tier']}" + (", release" if rep["release"] else ""))
    width = max((len(r["name"]) for r in rep["requirements"]), default=10)
    for r in rep["requirements"]:
        lines.append(f"{r['status']:<5}  {r['name']:<{width}}  {r['detail']}")
    n = rep["counts"]
    lines.append(f"{n['OK']} OK, {n['FIX']} FIX, {n['STALE']} STALE, {n['NOTE']} NOTE")
    return "\n".join(lines) + "\n"


def render_table(reports: list[dict]) -> str:
    cols = [n for n in ORDER if n in SHORT]
    lines = [NOT_ENFORCED] if any(r["not_enforced"] for r in reports) else []
    head = f"{'repo':<18} {'tier':<8} " + " ".join(f"{SHORT[n]:<5}" for n in cols) + " evidence"
    lines.append(head)
    for r in reports:
        by = {x["name"]: x["status"] for x in r["requirements"]}
        cells = " ".join(f"{by.get(n, '-'):<5}" for n in cols)
        age = r["evidence_oldest_days"]
        lines.append(f"{r['repo'][:18]:<18} {r['tier']:<8} {cells} " + ("-" if age is None else f"{age}d"))
    fix = sum(r["counts"]["FIX"] for r in reports)
    lines.append(f"{len(reports)} product(s), {fix} FIX")
    return "\n".join(lines) + "\n"


# --- command ---------------------------------------------------------------------

def _repos() -> list[pathlib.Path]:
    from . import productize
    out = []
    for manifest in productize.find_manifests():
        data, _ = load(manifest.parent)
        if data is not None and isinstance(data.get("security"), dict):
            out.append(manifest.parent)
    return out


def cmd_shield(args):
    as_json = bool(getattr(args, "json", False))
    if getattr(args, "shield_cmd", None) == "check":
        repo = pathlib.Path(args.repo).expanduser()
        rep = check(repo, release=args.release)
        if rep is None:
            _data, err = load(repo.resolve())
            if as_json:
                print(json.dumps({"repo": repo.resolve().name, "exit": 2, "error": err or "no [security] section in teyla.toml",
                                  "not_enforced": ["credential separation"], "template": template_section()}, indent=2))
            else:
                print(NOT_ENFORCED)
                print(err or f"{repo}: no [security] section in teyla.toml. Paste this and fill it in:\n")
                print(template_section(), end="")
            return 2
        print(json.dumps(rep, indent=2, default=str) if as_json else render_text(rep).rstrip("\n"))
        return rep["exit"]
    reports = [r for r in (check(p) for p in _repos()) if r is not None]
    if as_json:
        print(json.dumps({"products": reports, "not_enforced": ["credential separation"] if any(r["not_enforced"] for r in reports) else []},
                         indent=2, default=str))
    elif not reports:
        print("no repo under code_root has a [security] section; run: teyla shield check <repo>")
    else:
        print(render_table(reports), end="")
    return 1 if any(r["counts"]["FIX"] for r in reports) else 0


def register(sp):
    q = sp.add_parser("shield", help="does each product keep its security contract, and how old is the proof")
    q.set_defaults(fn=cmd_shield)
    q.add_argument("--json", action="store_true")
    s = q.add_subparsers(dest="shield_cmd", required=False)
    c = s.add_parser("check", help="one repo's [security] contract against its tier")
    c.add_argument("repo", help="path to the repo (the directory holding teyla.toml)")
    c.add_argument("--release", action="store_true", help="the step before an upload: STALE evidence blocks too")
    c.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    return q

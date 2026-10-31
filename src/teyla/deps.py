"""`teyla deps` — version-matched dependency vulnerability check over the lockfiles of a repo.

    teyla deps [repo] [--all] [--json] [--quiet] [--no-cache] [--dry] [--allow-network]

Shield lane G (decision SH10; docs/DEPS.md). It reads the lockfiles with the standard
library, asks the free OSV API (`api.osv.dev`) which of the pinned versions have a known vulnerability, and
prints the ones that match with the fixed version when one exists. A HIGH or CRITICAL with a fixed version is a
FIX (exit 1). A detected ecosystem with no lockfile, or an OSV that cannot be reached, is exit 2: what was not
covered is printed. Only package names, ecosystems and versions leave the machine (PRIVACY row 32); safe mode
refuses the call without `--allow-network`. Responses are cached for a day in `~/.teyla/deps/cache.json`.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
import os
import pathlib
import re
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request

from . import __version__, config, net
from .control import state as control

OSV = "https://api.osv.dev"
BATCH = 1000
MAX_PAGES = 10                  # follow-up pages for one query
MAX_SPLIT_CALLS = 300           # extra batch calls spent isolating a rejected query, per run
TIMEOUT_S = 30
CACHE_TTL_S = 24 * 3600
SUMMARY_MAX_AGE_DAYS = 14
USER_AGENT = f"teyla-deps/{__version__}"
SKIP_DIRS = {"node_modules", "Pods", "Carthage", "DerivedData", "build", "dist", "vendor", "venv", "target", "__pycache__"}
MAX_DEPTH = 5
SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "unknown": 0}
NPM_LOCKS = ("package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "yarn.lock", "deno.lock")
_REQ = re.compile(r"^requirements[^/]*\.txt$")

Pkg = tuple[str, str, str]          # (ecosystem, name, version)


class OsvError(Exception):
    def __init__(self, msg: str, status: int = 0):
        super().__init__(msg)
        self.status = status


# --- parsers: text -> (packages, notes) -----------------------------------------------------------

def _j(text: str):
    try:
        return json.loads(text), None
    except ValueError:
        return None, "not valid JSON, skipped"


def parse_package_lock(text: str) -> tuple[list[Pkg], list[str]]:
    data, err = _j(text)
    if err or not isinstance(data, dict):
        return [], [err or "unexpected shape, skipped"]
    out: list[Pkg] = []
    pk = data.get("packages")
    if isinstance(pk, dict):
        for key, ent in pk.items():
            if not key or not isinstance(ent, dict) or ent.get("link") or "node_modules/" not in key:
                continue
            name = ent.get("name") or key.rsplit("node_modules/", 1)[1]
            if ent.get("version"):
                out.append(("npm", name, str(ent["version"])))
    else:                                               # lockfileVersion 1: nested "dependencies"
        def walk(deps):
            for name, ent in (deps or {}).items():
                if isinstance(ent, dict):
                    if ent.get("version") and not str(ent["version"]).startswith(("file:", "git", "http")):
                        out.append(("npm", name, str(ent["version"])))
                    walk(ent.get("dependencies"))
        walk(data.get("dependencies"))
    return out, []


def _npm_split(spec: str) -> tuple[str, str] | None:
    """`name@1.2.3` or `@scope/name@1.2.3` -> (name, version); a `_peer` or `(peer)` suffix is dropped."""
    i = spec.find("@", 1)
    if i <= 0:
        return None
    name, ver = spec[:i], re.split(r"[_(]", spec[i + 1:])[0]
    return (name, ver) if name and ver and ver[0].isdigit() else None


def parse_pnpm_lock(text: str) -> tuple[list[Pkg], list[str]]:
    out, inside = [], False
    for ln in text.splitlines():
        if ln and not ln[0].isspace() and not ln.startswith("#"):
            inside = ln.strip() == "packages:"
            continue
        m = re.match(r"^  ['\"]?(/?[^\s'\":][^'\"]*?)['\"]?:\s*(?:\{.*)?$", ln) if inside else None
        if not m:
            continue
        key = m.group(1).lstrip("/").split("(")[0]
        v5 = re.match(r"^(@[^/@]+/[^/@]+|[^/@]+)/(\d[^/]*)$", key)      # lockfileVersion 5: /name/1.2.3_peer
        hit = (v5.group(1), re.split(r"_", v5.group(2))[0]) if v5 else _npm_split(key)
        if hit:
            out.append(("npm", hit[0], hit[1]))
    return out, ([] if out else ["no `packages:` entries found"])


def _yarn_name(spec: str) -> str | None:
    """The package a block header names. An alias (`alias@npm:lodash@^4.17.0`) resolves to the real package."""
    if "@npm:" in spec:
        before, after = spec.split("@npm:", 1)
        j = after.rfind("@")
        return after[:j] if j > 0 else before
    i = spec.rfind("@")
    return spec[:i] if i > 0 and not spec.startswith("__metadata") else None


def parse_yarn_lock(text: str) -> tuple[list[Pkg], list[str]]:
    out, name = [], None
    for ln in text.splitlines():
        if ln and not ln[0].isspace() and not ln.startswith("#") and ln.rstrip().endswith(":"):
            name = _yarn_name(ln.rstrip()[:-1].split(",")[0].strip().strip("\"'"))
            continue
        m = re.match(r"^\s+version:?\s+\"?([^\"\s]+)\"?\s*$", ln)
        if m and name and "use.local" not in m.group(1) and m.group(1)[:1].isdigit():
            out.append(("npm", name, m.group(1)))
            name = None
    return out, ([] if out else ["no entries found"])


def parse_deno_lock(text: str) -> tuple[list[Pkg], list[str]]:
    data, err = _j(text)
    if err or not isinstance(data, dict):
        return [], [err or "unexpected shape, skipped"]
    pk = data.get("packages") if isinstance(data.get("packages"), dict) else {}      # v3: packages.npm / packages.jsr
    npm = data.get("npm") if isinstance(data.get("npm"), dict) else pk.get("npm")    # v4: top-level npm / jsr
    if isinstance(npm, dict) and isinstance(npm.get("packages"), dict) and "specifiers" in npm:
        npm = npm["packages"]                                                         # v2: npm.packages
    jsr = data.get("jsr") if isinstance(data.get("jsr"), dict) else pk.get("jsr")
    out, notes = [], []
    for key in (npm if isinstance(npm, dict) else {}):
        hit = _npm_split(key)
        if hit:
            out.append(("npm", hit[0], hit[1]))
    if isinstance(jsr, dict) and jsr:
        notes.append(f"{len(jsr)} jsr package(s) skipped (no OSV ecosystem)")
    if not isinstance(npm, dict) and not isinstance(jsr, dict) and not (pk or data.get("specifiers")):
        notes.append(f"unrecognised shape (version {data.get('version', '?')}): no packages read")
    return out, notes


def clean_url(url: str) -> str | None:
    """`host/path` of an http(s) URL: userinfo, query, fragment, port-less scheme and a trailing `.git` are dropped, so a
    token in a URL can never become part of a name that is sent. None for anything that is not http(s)."""
    try:
        u = urllib.parse.urlsplit(url.strip())
        host = (u.hostname or "").lower()
        port = f":{u.port}" if u.port else ""
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not host or len(u.path) < 2:
        return None
    path = re.sub(r"(?:\.git)?/*$", "", u.path)
    return f"{host}{port}{path}"


_CREDENTIAL = re.compile(r"\bhttps?://[^/\s\"'@]+@")


def parse_package_resolved(text: str) -> tuple[list[Pkg], list[str]]:
    data, err = _j(text)
    if err or not isinstance(data, dict):
        return [], [err or "unexpected shape, skipped"]
    pins = data.get("pins") or (data.get("object") or {}).get("pins") or []
    out, skipped = [], 0
    for p in pins:
        url = p.get("location") or p.get("repositoryURL") or ""
        ver = (p.get("state") or {}).get("version")
        name = clean_url(url)
        if name and ver:
            out.append(("SwiftURL", name.lower(), str(ver)))
        else:
            skipped += 1
    notes = [f"{skipped} pin(s) skipped (a branch, a revision or a non-HTTPS source: no OSV ecosystem)"] if skipped else []
    return out, notes


def _toml(text: str):
    try:
        return tomllib.loads(text), None
    except tomllib.TOMLDecodeError:
        return None, "not valid TOML, skipped"


def parse_uv_lock(text: str) -> tuple[list[Pkg], list[str]]:
    data, err = _toml(text)
    if err:
        return [], [err]
    out = []
    for p in data.get("package", []):
        src = p.get("source") or {}
        if p.get("name") and p.get("version") and "registry" in src:
            out.append(("PyPI", p["name"], str(p["version"])))
    return out, []


def parse_poetry_lock(text: str) -> tuple[list[Pkg], list[str]]:
    data, err = _toml(text)
    if err:
        return [], [err]
    out = []
    for p in data.get("package", []):
        if p.get("name") and p.get("version") and (p.get("source") or {}).get("type", "legacy") in ("legacy", "pypi"):
            out.append(("PyPI", p["name"], str(p["version"])))
    return out, []


def parse_requirements(text: str) -> tuple[list[Pkg], list[str]]:
    out, unpinned = [], 0
    for raw in text.splitlines():
        ln = raw.split(" #")[0].split(";")[0].strip().rstrip("\\").strip()
        if not ln or ln.startswith(("#", "-", ".", "/")) or "://" in ln:
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([A-Za-z0-9._+!-]+)$", ln)
        if m:
            out.append(("PyPI", m.group(1), m.group(2)))
        elif re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*", ln):
            unpinned += 1
    return out, ([f"{unpinned} unpinned requirement(s) not checked (only `==` pins are)"] if unpinned else [])


def parse_gemfile_lock(text: str) -> tuple[list[Pkg], list[str]]:
    out, section = [], ""
    for ln in text.splitlines():
        if ln and not ln[0].isspace():
            section = ln.strip()
            continue
        m = re.match(r"^    ([A-Za-z0-9_.-]+) \(([0-9][^)\s]*)\)$", ln)
        if m and section == "GEM":
            v = re.match(r"[0-9][0-9A-Za-z.]*", m.group(2))
            out.append(("RubyGems", m.group(1), v.group(0) if v else m.group(2)))
    return out, []


def parse_go_sum(text: str) -> tuple[list[Pkg], list[str]]:
    seen, out = set(), []
    for ln in text.splitlines():
        parts = ln.split()
        if len(parts) >= 2 and not parts[1].endswith("/go.mod") and parts[1].startswith("v"):
            key = (parts[0], parts[1])
            if key not in seen:
                seen.add(key)
                out.append(("Go", parts[0], parts[1][1:].split("+")[0]))
    return out, []


PARSERS = {"package-lock.json": parse_package_lock, "npm-shrinkwrap.json": parse_package_lock,
           "pnpm-lock.yaml": parse_pnpm_lock, "yarn.lock": parse_yarn_lock, "deno.lock": parse_deno_lock,
           "Package.resolved": parse_package_resolved, "uv.lock": parse_uv_lock, "poetry.lock": parse_poetry_lock,
           "Gemfile.lock": parse_gemfile_lock, "go.sum": parse_go_sum}


def parser_for(name: str):
    return parse_requirements if _REQ.match(name) else PARSERS.get(name)


# --- discovery: which lockfiles exist, which manifests have none ----------------------------------

def _walk(repo: pathlib.Path):
    """(relative dir, file names) for every directory down to MAX_DEPTH; hidden and build directories pruned."""
    for root, dirs, files in os.walk(repo):
        rel = pathlib.Path(root).relative_to(repo)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        if len(rel.parts) >= MAX_DEPTH:
            dirs[:] = []
        yield rel, files


def _ancestors(rel: pathlib.Path):
    yield rel
    yield from rel.parents


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _pkg_json_has_deps(text: str) -> bool:
    d, _ = _j(text)
    return isinstance(d, dict) and any(d.get(k) for k in ("dependencies", "devDependencies", "optionalDependencies"))


def _pyproject_has_deps(text: str) -> bool:
    d, _ = _toml(text)
    if not isinstance(d, dict):
        return False
    proj = d.get("project") or {}
    poetry = ((d.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
    return bool(proj.get("dependencies") or proj.get("optional-dependencies") or d.get("dependency-groups")
                or set(poetry) - {"python"})


def scan_repo(repo: pathlib.Path) -> dict:
    """{path, name, lockfiles: [{file, packages}], gaps, notes}. Reads files; makes no network call."""
    locks, gaps, notes = [], [], []
    by_dir: dict[pathlib.Path, set[str]] = {}
    manifests = []
    for rel, files in _walk(repo):
        names = set(files)
        by_dir[rel] = names
        for f in sorted(names):
            if parser_for(f):
                locks.append(rel / f)
            if f in ("package.json", "pyproject.toml", "Package.swift", "Gemfile", "go.mod"):
                manifests.append(rel / f)
    resolved_anywhere = any(p.name == "Package.resolved" for p in locks)

    def covered(rel_dir: pathlib.Path, wanted: tuple[str, ...]) -> bool:
        return any(w in by_dir.get(a, ()) for a in _ancestors(rel_dir) for w in wanted)

    for m in manifests:
        d, text = m.parent, _read(repo / m)
        if m.name == "package.json" and _pkg_json_has_deps(text) and not covered(d, NPM_LOCKS):
            gaps.append(f"{m}: no lockfile (package-lock.json, pnpm-lock.yaml, yarn.lock or deno.lock)")
        elif m.name == "pyproject.toml" and _pyproject_has_deps(text) and not covered(d, ("uv.lock", "poetry.lock")) \
                and not any(_REQ.match(f) for f in by_dir.get(d, ())):
            gaps.append(f"{m}: no lockfile (uv.lock or poetry.lock)")
        elif m.name == "Package.swift" and ".package(" in text and not resolved_anywhere:
            gaps.append(f"{m}: no Package.resolved")
        elif m.name == "Gemfile" and re.search(r"(?m)^\s*gem\s", text) and not covered(d, ("Gemfile.lock",)):
            gaps.append(f"{m}: no Gemfile.lock")
        elif m.name == "go.mod" and re.search(r"(?m)^\s*require\b", text) and not covered(d, ("go.sum",)):
            gaps.append(f"{m}: no go.sum")
    entries = []
    for lf in locks:
        text = _read(repo / lf)
        pkgs, n = parser_for(lf.name)(text)
        entries.append({"file": str(lf), "packages": sorted(set(pkgs))})
        notes += [f"{lf}: {x}" for x in n]
        if _CREDENTIAL.search(text):
            notes.append(f"{lf}: credential in lockfile: a URL carries userinfo (the value is not shown or sent); remove it and rotate it")
    return {"path": str(repo), "name": repo.name, "lockfiles": entries, "gaps": gaps, "notes": notes}


# --- versions and severity ------------------------------------------------------------------------

def vkey(v: str) -> tuple:
    """A tolerant version order: the numbers first; a pre-release word (rc1, beta) sorts before the release."""
    v = v.lstrip("vV").split("+")[0]
    m = re.match(r"\d+(?:\.\d+)*", v)
    nums = tuple(int(x) for x in m.group(0).split(".")) if m else ()
    rest = v[m.end():] if m else v
    pre = bool(re.match(r"[-.]?(a|b|c|rc|alpha|beta|pre|dev|snapshot)", rest, re.I))
    return (nums + (0,) * (8 - len(nums)), 0 if pre else 1, rest)


_CVSS = {"AV": {"N": .85, "A": .62, "L": .55, "P": .2}, "AC": {"L": .77, "H": .44}, "UI": {"N": .85, "R": .62},
         "C": {"H": .56, "L": .22, "N": 0}, "I": {"H": .56, "L": .22, "N": 0}, "A": {"H": .56, "L": .22, "N": 0}}


def _roundup(x: float) -> float:
    i = round(x * 100000)
    return i / 100000.0 if i % 10000 == 0 else (math.floor(i / 10000) + 1) / 10.0


def cvss3_score(vector: str) -> float | None:
    """The CVSS v3.x base score of a vector string; None for anything else (v2, v4, malformed)."""
    if not vector.startswith("CVSS:3"):
        return None
    try:
        m = dict(p.split(":") for p in vector.split("/")[1:])
        changed = m["S"] == "C"
        pr = {"N": .85, "L": .68 if changed else .62, "H": .5 if changed else .27}[m["PR"]]
        iss = 1 - (1 - _CVSS["C"][m["C"]]) * (1 - _CVSS["I"][m["I"]]) * (1 - _CVSS["A"][m["A"]])
        impact = 7.52 * (iss - .029) - 3.25 * (iss - .02) ** 15 if changed else 6.42 * iss
        expl = 8.22 * _CVSS["AV"][m["AV"]] * _CVSS["AC"][m["AC"]] * pr * _CVSS["UI"][m["UI"]]
    except (KeyError, ValueError):
        return None
    if impact <= 0:
        return 0.0
    return _roundup(min((1.08 if changed else 1) * (impact + expl), 10))


def label(score: float | None, word: str | None = None) -> str:
    if score is not None:
        return "critical" if score >= 9 else "high" if score >= 7 else "medium" if score >= 4 else "low" if score > 0 else "unknown"
    return {"critical": "critical", "high": "high", "moderate": "medium", "medium": "medium", "low": "low"}.get((word or "").lower(), "unknown")


def severity_of(v: dict) -> tuple[str, float | None]:
    score = None
    for s in v.get("severity") or []:
        score = cvss3_score(str(s.get("score", ""))) if score is None else score
    word = (v.get("database_specific") or {}).get("severity")
    for a in v.get("affected") or []:
        word = word or (a.get("database_specific") or {}).get("severity") or (a.get("ecosystem_specific") or {}).get("severity")
    return label(score, word), score


def _norm(eco: str, name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower() if eco == "PyPI" else name.lower()


def compact(v: dict) -> dict:
    """What the cache keeps of one OSV record."""
    sev, score = severity_of(v)
    aff = []
    for a in v.get("affected") or []:
        pk = a.get("package") or {}
        fixed = [e["fixed"] for r in a.get("ranges") or [] if r.get("type") in ("ECOSYSTEM", "SEMVER")
                 for e in r.get("events") or [] if e.get("fixed")]
        aff.append({"eco": pk.get("ecosystem", "").split(":")[0], "name": pk.get("name", ""), "fixed": fixed})
    return {"id": v.get("id", ""), "aliases": sorted(v.get("aliases") or []), "sev": sev, "score": score,
            "summary": str(v.get("summary") or "")[:100], "affected": aff, "withdrawn": bool(v.get("withdrawn"))}


def pick_fixed(version: str, candidates: list[str]) -> str | None:
    later = [c for c in candidates if vkey(c) > vkey(version)]
    return min(later, key=vkey) if later else None


# --- the OSV call, the cache ------------------------------------------------------------------------

def _fetch(url: str, payload: dict | None = None) -> dict:
    """The one network call. Tests replace this function; none touches the network."""
    if not url.startswith(OSV + "/"):
        raise ValueError("only api.osv.dev is called")
    data = json.dumps(payload, separators=(",", ":")).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:        # noqa: S310 (host checked above)
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise OsvError(f"HTTP {e.code}", e.code) from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise OsvError(str(getattr(e, "reason", e))) from e


def cache_path() -> pathlib.Path:
    return control.home() / "deps" / "cache.json"


def _load_cache(now: float) -> dict:
    try:
        c = json.loads(cache_path().read_text())
        return {k: {i: e for i, e in (c.get(k) or {}).items() if now - e.get("at", 0) < CACHE_TTL_S} for k in ("q", "v")}
    except (OSError, ValueError, AttributeError):
        return {"q": {}, "v": {}}


def _save_cache(c: dict) -> None:
    p = cache_path()
    try:
        config.private_dir(p.parent)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(c))
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except OSError:
        pass


class _Budget:
    def __init__(self, calls: int):
        self.calls = calls


def _query(chunk: list[Pkg], budget: _Budget) -> tuple[dict[Pkg, list[str]], list[Pkg]]:
    """({package: vuln ids}, packages not covered) for one batch. A rejected batch (HTTP 4xx) is split in halves
    until the failing queries stand alone, within the budget; a package whose pages do not end is not covered and
    not cached. An unreachable OSV (no answer, HTTP 5xx) raises."""
    queries = [{"package": {"name": n, "ecosystem": e}, "version": v} for e, n, v in chunk]
    try:
        results = _fetch(f"{OSV}/v1/querybatch", {"queries": queries}).get("results") or []
    except OsvError as e:
        if e.status < 400 or e.status >= 500:
            raise
        if len(chunk) == 1 or budget.calls <= 0:
            return {}, list(chunk)
        budget.calls -= 1
        mid = len(chunk) // 2
        a, fa = _query(chunk[:mid], budget)
        b, fb = _query(chunk[mid:], budget)
        return {**a, **b}, fa + fb
    ids: dict[Pkg, set[str]] = {}
    pending: dict[Pkg, str] = {}
    for p, r in zip(chunk, results):
        r = r or {}
        ids[p] = {v["id"] for v in r.get("vulns") or [] if v.get("id")}
        if r.get("next_page_token"):
            pending[p] = r["next_page_token"]
    for _ in range(MAX_PAGES):
        if not pending:
            break
        keys = list(pending)
        qs = [{**{"package": {"name": p[1], "ecosystem": p[0]}, "version": p[2]}, "page_token": pending[p]} for p in keys]
        res = _fetch(f"{OSV}/v1/querybatch", {"queries": qs}).get("results") or []
        pending = {}
        for p, r in zip(keys, res):
            r = r or {}
            ids[p] |= {v["id"] for v in r.get("vulns") or [] if v.get("id")}
            if r.get("next_page_token"):
                pending[p] = r["next_page_token"]
    missing = [p for p in chunk if p not in ids or p in pending]          # no result row, or pages never ended
    return {p: sorted(i) for p, i in ids.items() if p not in pending}, missing


def lookup(pkgs: set[Pkg], *, use_cache: bool = True, now: float | None = None) -> tuple[dict[Pkg, list[dict]], list[str]]:
    """{package: [vuln, ...]} for the packages OSV answered for, plus notes. A package OSV did not answer for is
    absent from the result (the caller counts it as not covered). Raises OsvError when OSV cannot be reached.
    Only names, ecosystems and versions are sent."""
    now = _dt.datetime.now().timestamp() if now is None else now
    cache = _load_cache(now) if use_cache else {"q": {}, "v": {}}
    notes, ids_of = [], {}
    todo = []
    for p in sorted(pkgs):
        e = cache["q"].get("\x00".join(p))
        if e is None:
            todo.append(p)
        else:
            ids_of[p] = e["ids"]
    by_eco: dict[str, list[Pkg]] = {}
    for p in todo:
        by_eco.setdefault(p[0], []).append(p)
    budget = _Budget(MAX_SPLIT_CALLS)
    for eco, plist in by_eco.items():
        failed: list[Pkg] = []
        for i in range(0, len(plist), BATCH):
            got, bad = _query(plist[i:i + BATCH], budget)
            failed += bad
            for p, ids in got.items():
                ids_of[p] = ids
                cache["q"]["\x00".join(p)] = {"at": now, "ids": ids}
        if failed:
            notes.append(f"OSV did not answer for {len(failed)} {eco} package(s): not covered")
    for vid in sorted({i for ids in ids_of.values() for i in ids}):
        if vid not in cache["v"]:
            cache["v"][vid] = {**compact(_fetch(f"{OSV}/v1/vulns/{vid}")), "at": now}
    _save_cache(cache)
    out: dict[Pkg, list[dict]] = {}
    for p, ids in ids_of.items():
        eco, name, ver = p
        vulns = []
        for vid in ids:
            c = cache["v"][vid]
            if c.get("withdrawn"):
                continue
            fixed = sorted({f for a in c["affected"] if a["eco"] == eco and _norm(eco, a["name"]) == _norm(eco, name) for f in a["fixed"]})
            vulns.append({"id": c["id"], "aliases": list(c["aliases"]), "sev": c["sev"], "score": c["score"],
                          "summary": c["summary"], "fixed": fixed})
        out[p] = merge_aliases(vulns)
    return out, notes


def merge_aliases(vulns: list[dict]) -> list[dict]:
    """GHSA, PYSEC and CVE records of one flaw count once: records that share an id or alias are merged."""
    groups: list[dict] = []
    for v in sorted(vulns, key=lambda v: (not v["id"].startswith("GHSA-"), v["id"])):
        ids = {v["id"], *v["aliases"]}
        hit = next((g for g in groups if g["_ids"] & ids), None)
        if hit is None:
            groups.append({**v, "_ids": ids, "fixed": list(v["fixed"])})
            continue
        hit["_ids"] |= ids
        hit["aliases"] = sorted(set(hit["aliases"]) | ids - {hit["id"]})
        hit["fixed"] = sorted(set(hit["fixed"]) | set(v["fixed"]))
        if SEV_RANK[v["sev"]] > SEV_RANK[hit["sev"]]:
            hit["sev"], hit["score"] = v["sev"], v["score"]
    for g in groups:
        g.pop("_ids")
    return groups


# --- evaluation -------------------------------------------------------------------------------------

def evaluate(scan: dict, found: dict[Pkg, list[dict]] | None) -> dict:
    """The report of one repo. `found` None means OSV was not reached: nothing is claimed about the packages."""
    rows, checked, uncovered = [], 0, 0
    for lf in scan["lockfiles"]:
        for p in lf["packages"]:
            p = tuple(p)
            if found is None:
                continue
            if p not in found:
                uncovered += 1
                continue
            checked += 1
            vulns = found[p]
            if not vulns:
                continue
            worst = max(vulns, key=lambda v: (SEV_RANK[v["sev"]], v["score"] or 0))
            fixes = [f for f in (pick_fixed(p[2], v["fixed"]) for v in vulns) if f]
            fixed = max(fixes, key=vkey) if fixes else None
            rows.append({"ecosystem": p[0], "name": p[1], "version": p[2], "lockfile": lf["file"], "severity": worst["sev"],
                         "score": worst["score"], "id": worst["id"], "aliases": worst["aliases"], "count": len(vulns),
                         "fixed": fixed, "fix": SEV_RANK[worst["sev"]] >= 3 and any(
                             pick_fixed(p[2], v["fixed"]) for v in vulns if SEV_RANK[v["sev"]] >= 3)})
    rows.sort(key=lambda r: (not r["fix"], -SEV_RANK[r["severity"]], r["name"], r["version"]))
    return {"repo": scan["name"], "path": scan["path"], "lockfiles": [l["file"] for l in scan["lockfiles"]],
            "packages": sum(len(l["packages"]) for l in scan["lockfiles"]), "checked": checked, "vulnerable": rows,
            "fix": sum(1 for r in rows if r["fix"]), "not_covered": uncovered, "gaps": scan["gaps"], "notes": scan["notes"]}


def exit_code(reports: list[dict], unreachable: bool) -> int:
    if unreachable or any(r["gaps"] or r["not_covered"] for r in reports):
        return 2
    return 1 if any(r["fix"] for r in reports) else 0


def row_lines(r: dict) -> list[str]:
    tag = "FIX" if r["fix"] else "   "
    more = f" (+{r['count'] - 1} more)" if r["count"] > 1 else ""
    cve = next((a for a in r["aliases"] if a.startswith("CVE-")), r["aliases"][0] if r["aliases"] else "")
    ident = r["id"] + (f" / {cve}" if cve else "")
    tail = f"fixed in {r['fixed']}" if r["fixed"] else "no fix known"
    out = [f"  {tag}  {r['severity']:<8} {r['name']} {r['version']}  {ident}{more}  {tail}"]
    if r["fix"]:
        out.append(f"             bump {r['name']} to {r['fixed']} in {r['lockfile']}")
    return out


def render_repo(r: dict, quiet: bool, unreachable: bool, terse: bool = False) -> list[str]:
    body = []
    if not quiet:
        for row in r["vulnerable"]:
            body += row_lines(row)
    else:
        for row in r["vulnerable"]:
            if row["fix"]:
                body += row_lines(row)
    body += [f"  GAP  {g}" for g in r["gaps"]]
    if r["not_covered"] and not unreachable:
        body.append(f"  NOT COVERED  {r['not_covered']} package(s): OSV did not answer for them")
    if not quiet:
        body += [f"  note {n}" for n in r["notes"]]
    if (quiet or terse) and not body and not unreachable:
        return []
    if unreachable:
        head = f"{r['repo']}: {r['packages']} package(s) in {len(r['lockfiles'])} lockfile(s), NOT checked (OSV unreachable)"
    else:
        head = (f"{r['repo']}: {r['checked']} package(s) checked in {len(r['lockfiles'])} lockfile(s), "
                f"{len(r['vulnerable'])} vulnerable, {r['fix']} FIX" if r["lockfiles"] else f"{r['repo']}: " + ("no lockfile" if r["gaps"] else "no lockfile to check"))
    return [head] + body


def render_table(reports: list[dict]) -> list[str]:
    w = max([4] + [len(r["repo"]) for r in reports])
    out = [f"{'repo':<{w}}  packages  vulnerable  FIX  gaps"]
    for r in reports:
        out.append(f"{r['repo']:<{w}}  {r['packages']:>8}  {len(r['vulnerable']):>10}  {r['fix']:>3}  {len(r['gaps']):>4}")
    return out


# --- weekly digest ----------------------------------------------------------------------------------

def summary_path() -> pathlib.Path:
    return control.home() / "deps" / "summary.json"


def write_summary(reports: list[dict]) -> None:
    body = {"at": _dt.datetime.now(_dt.timezone.utc).isoformat(), "repos": len(reports), "fix": sum(r["fix"] for r in reports),
            "fix_repos": sum(1 for r in reports if r["fix"]), "gaps": sum(len(r["gaps"]) for r in reports)}
    try:
        config.private_dir(summary_path().parent)
        summary_path().write_text(json.dumps(body) + "\n")
    except OSError:
        pass


def digest_candidates() -> list[dict]:
    """One digest line while the last weekly `teyla deps --all` found a FIX. Reads a small local file only."""
    try:
        d = json.loads(summary_path().read_text())
        at = _dt.datetime.fromisoformat(d["at"])
        fix, repos = int(d["fix"]), int(d["fix_repos"])
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if fix <= 0 or _dt.datetime.now(_dt.timezone.utc) - at > _dt.timedelta(days=SUMMARY_MAX_AGE_DAYS):
        return []
    return [dict(rank=1, id="deps:fix", text=f"dependency FIX: {fix} vulnerable package(s) with a fixed version in {repos} repo(s)",
                 step="teyla deps --all", cmd=True)]


# --- command ----------------------------------------------------------------------------------------

def cmd_deps(args) -> int:
    from . import lang
    cfg = config.load()
    if args.all and args.repo:
        print("teyla deps: give a repo or --all, not both", file=sys.stderr)
        return 2
    try:
        repos = lang.resolve_repos([] if args.all else [args.repo or "."], cfg)
    except lang.UsageError as e:
        print(f"teyla deps: {e}", file=sys.stderr)
        return 2
    scans = [scan_repo(r) for r in repos]
    pkgs = {tuple(p) for s in scans for lf in s["lockfiles"] for p in lf["packages"]}
    if args.dry:
        eco: dict[str, int] = {}
        for p in pkgs:
            eco[p[0]] = eco.get(p[0], 0) + 1
        print(f"would send {len(pkgs)} unique (ecosystem, name, version) triple(s) from {sum(len(s['lockfiles']) for s in scans)} "
              f"lockfile(s) in {len(scans)} repo(s) to {OSV}/v1/querybatch" + (f": {', '.join(f'{k} {v}' for k, v in sorted(eco.items()))}" if eco else "")
              + "; nothing is sent or written")
        return 0
    unreachable, notes, found = False, [], None
    if pkgs:
        if not net.gate("deps (it sends package names and versions to api.osv.dev)", quiet=args.quiet):
            return 0 if args.quiet else 2
        try:
            found, notes = lookup(pkgs, use_cache=not args.no_cache)
        except OsvError as e:
            unreachable = True
            print(f"teyla deps: OSV unreachable ({e}); no package was checked", file=sys.stderr)
    else:
        found = {}
    reports = [evaluate(s, found) for s in scans]
    if notes and reports:
        reports[0]["notes"] += notes
    code = exit_code(reports, unreachable)
    if args.all and not unreachable:
        write_summary(reports)
    if args.json:
        print(json.dumps({"repos": reports, "fix": sum(r["fix"] for r in reports), "unreachable": unreachable, "exit": code}, indent=1))
        return code
    lines = [ln for r in reports for ln in render_repo(r, args.quiet, unreachable, args.all)]
    if lines:
        print("\n".join(lines))
    if args.all and not args.quiet:
        print("\n".join(render_table(reports)))
        print(f"{sum(r['fix'] for r in reports)} FIX, {sum(len(r['gaps']) for r in reports)} gap(s), "
              f"{sum(r['not_covered'] for r in reports)} package(s) not covered; exit {code}")
    return code


def register(sp):
    q = sp.add_parser("deps", help="known vulnerabilities in the pinned dependency versions of a repo, from its lockfiles via OSV")
    q.set_defaults(fn=cmd_deps)
    q.add_argument("repo", nargs="?", help="a repo name under code_root or a path (default: the current directory)")
    q.add_argument("--all", action="store_true", help="every repo under code_root, a summary table, the worst exit code")
    q.add_argument("--json", action="store_true", help="print the report as JSON")
    q.add_argument("--quiet", action="store_true", help="print only FIXes and gaps")
    q.add_argument("--no-cache", action="store_true", help="ignore the one-day cache and ask OSV again")
    q.add_argument("--dry", action="store_true", help="print what would be sent (counts only); send and write nothing")
    q.add_argument("--allow-network", action="store_true", help="safe mode: allow the OSV call for this one run")
    return q

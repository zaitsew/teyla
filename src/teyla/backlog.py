"""GitHub data for `teyla state`: the owner's open PRs, issues assigned to the owner, and the open
issue count of each active repo.

The snapshot must stay fast, so it never calls `gh`. It reads `~/.teyla/state-backlog.json` (0600) and,
when that is older than 30 minutes, starts one detached `teyla state --refresh-backlog`, the same way
the spend figure is refreshed. One refresh makes three calls, never one per repo:

    1. GraphQL search `is:pr is:open author:@me`      the PRs, with the head commit the review ledger names
    2. `gh search issues --assignee @me --state open`  the issues assigned to the owner
    3. one GraphQL query with an alias per active repo  open issue count and the repo's current name

The third call is also how a renamed repo is found: GitHub answers an old name with the current one, so
two local clones of one repo (`vpn`, `home-vpn`) end up under one product.

No `gh`, safe mode, or a failing call: the lists are empty or keep their last value, never an error.
A failed refresh leaves its lock in place, which holds the next attempt back for five minutes.

`pr_states` answers a different question for `teyla asks`: is the PR an ask points to merged or closed? It
reads the open PRs above first, then `~/.teyla/pr-state.json` (entries live 30 minutes), and asks GitHub
once for the rest, in batches. Any failure leaves a URL unknown, never an error.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from typing import Callable

from . import asks, net
from .control import state as control

FRESH_S = 1800
LOCK_STALE_S = 300
GH_TIMEOUT_S = 60
LIMIT = 100
COUNTS_BATCH = 40                  # aliases per GraphQL query
VERSION = 1

Runner = Callable[[list[str]], "tuple[int, str, str]"]

PR_QUERY = ("query($q:String!){search(query:$q,type:ISSUE,first:%d){nodes{... on PullRequest{"
            "number title url createdAt isDraft headRefOid repository{nameWithOwner}}}}}" % LIMIT)
_SLUG = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REMOTE = re.compile(r'\[remote "origin"\][^\[]*?\burl\s*=\s*(\S+)')
_GITHUB_URL = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")

PR_TTL_S = 1800                    # a PR state read from GitHub is trusted this long
PR_BACKOFF_S = 300                 # after a failed query, no new one for this long
PR_KEEP_S = 7 * 86400
PR_BATCH = 40                      # PRs per GraphQL query
_PR_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/(\d+)(?:[/?#].*)?$")

EMPTY = {"at": 0.0, "prs": [], "issues": [], "counts": {}, "canonical": {}}


def cache_path() -> pathlib.Path:
    return control.home() / "state-backlog.json"


def lock_path() -> pathlib.Path:
    return control.home() / "state-backlog.lock"


def default_runner(argv: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(argv, capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    return r.returncode, r.stdout, r.stderr


# --- merge-approved repos ---------------------------------------------------------------------

def parse_merge_approved(text: str) -> set[str]:
    """The `owner/repo` names of the fenced block around the line "MERGE-APPROVED REPOS" (the line may sit
    inside the fence or just above it): the first token of each line that has a "/", lower case. A
    comment line starts with "#", so a URL inside a comment is never read as a repo."""
    out: set[str] = set()
    lines = text.splitlines()
    at = next((i for i, ln in enumerate(lines) if "MERGE-APPROVED REPOS" in ln), None)
    if at is None:
        return out
    inside = sum(1 for ln in lines[:at] if ln.strip().startswith("```")) % 2 == 1
    rest = lines[at + 1:]
    if not inside:                          # the fence opens after the marker line
        opens = next((i for i, ln in enumerate(rest) if ln.strip().startswith("```")), None)
        if opens is None:
            return out
        rest = rest[opens + 1:]
    for ln in rest:
        if ln.strip().startswith("```"):
            break                           # the closing fence
        tok = ln.split()[0] if ln.split() else ""
        if _SLUG.match(tok):
            out.add(tok.lower())
    return out


def claude_md_path() -> pathlib.Path:
    return pathlib.Path.home() / ".claude" / "CLAUDE.md"


def merge_approved(cfg: dict | None = None, claude_md: pathlib.Path | None = None) -> set[str]:
    """`[state] merge_approved` when set, else the list in `~/.claude/CLAUDE.md`; empty when neither exists."""
    listed = ((cfg or {}).get("state") or {}).get("merge_approved")
    if isinstance(listed, list) and listed:
        return {str(x).strip().lower() for x in listed if "/" in str(x)}
    try:
        return parse_merge_approved((claude_md or claude_md_path()).read_text(errors="replace"))
    except OSError:
        return set()


# --- repos ------------------------------------------------------------------------------------

def remote_slug(path) -> str:
    """`owner/name` of a clone's origin on GitHub, read from .git/config (no subprocess); "" when there is none."""
    try:
        text = (pathlib.Path(path) / ".git" / "config").read_text(errors="replace")
    except OSError:
        return ""
    m = _REMOTE.search(text)
    g = _GITHUB_URL.search(m.group(1)) if m else None
    return f"{g.group(1)}/{g.group(2)}" if g else ""


# --- the cache --------------------------------------------------------------------------------

def load() -> dict:
    """The cache with every field present; EMPTY when it is missing or unreadable."""
    try:
        c = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return dict(EMPTY, prs=[], issues=[], counts={}, canonical={})
    if not isinstance(c, dict) or c.get("version") != VERSION:
        return dict(EMPTY, prs=[], issues=[], counts={}, canonical={})
    out = dict(EMPTY, prs=[], issues=[], counts={}, canonical={})
    for k, kind in (("prs", list), ("issues", list), ("counts", dict), ("canonical", dict)):
        if isinstance(c.get(k), kind):
            out[k] = c[k]
    try:
        out["at"] = float(c.get("at") or 0)
    except (TypeError, ValueError):
        pass
    return out


def view(now: float, *, refresh: bool = True) -> dict:
    """The cached backlog. A stale or missing cache starts one background refresh (when `refresh`)."""
    c = load()
    if refresh and now - c["at"] >= FRESH_S:
        spawn_refresh(now)
    return c


def spawn_refresh(now: float | None = None) -> None:
    """Start one detached refresh. The lock is created exclusively; one older than five minutes is stale."""
    now = asks._now() if now is None else now
    lock = lock_path()
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.close(os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            if now - lock.stat().st_mtime < LOCK_STALE_S:
                return
            os.utime(lock, (now, now))      # stale: take it over
        subprocess.Popen([sys.executable, "-m", "teyla", "state", "--refresh-backlog"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError):
        pass


# --- the three calls --------------------------------------------------------------------------

def _epoch(ts) -> float:
    try:
        return _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _call(runner: Runner, argv: list[str]) -> str | None:
    """stdout of a successful call; None on any failure."""
    try:
        rc, out, _err = runner(argv)
    except (OSError, subprocess.SubprocessError):
        return None
    return out if rc == 0 else None


def fetch_prs(runner: Runner) -> list[dict] | None:
    out = _call(runner, ["gh", "api", "graphql", "-f", f"query={PR_QUERY}",
                         "-f", "q=is:pr is:open author:@me archived:false sort:created-asc"])
    try:
        nodes = json.loads(out or "")["data"]["search"]["nodes"]
    except (ValueError, KeyError, TypeError):
        return None
    if not isinstance(nodes, list):
        return None
    rows = []
    for n in nodes:
        if not isinstance(n, dict) or n.get("number") is None:
            continue
        repo = ((n.get("repository") or {}).get("nameWithOwner")) or ""
        if not _SLUG.match(repo):
            continue
        rows.append({"repo": repo, "number": int(n["number"]), "title": str(n.get("title") or ""),
                     "url": str(n.get("url") or ""), "created": _epoch(n.get("createdAt")),
                     "head": str(n.get("headRefOid") or "").lower(), "draft": bool(n.get("isDraft"))})
    return rows


def fetch_issues(runner: Runner) -> list[dict] | None:
    out = _call(runner, ["gh", "search", "issues", "--assignee", "@me", "--state", "open", "--limit", str(LIMIT),
                         "--json", "number,title,url,createdAt,repository,labels"])
    try:
        items = json.loads(out or "")
    except ValueError:
        return None
    if not isinstance(items, list):
        return None
    rows = []
    for n in items:
        if not isinstance(n, dict) or n.get("number") is None:
            continue
        repo = ((n.get("repository") or {}).get("nameWithOwner")) or ""
        if not _SLUG.match(repo):
            continue
        labels = [str(x.get("name")) for x in n.get("labels") or [] if isinstance(x, dict) and x.get("name")]
        rows.append({"repo": repo, "number": int(n["number"]), "title": str(n.get("title") or ""),
                     "url": str(n.get("url") or ""), "created": _epoch(n.get("createdAt")), "labels": labels})
    return rows


def counts_query(slugs: list[str]) -> str:
    parts = []
    for i, s in enumerate(slugs):
        owner, name = s.split("/", 1)
        parts.append(f'r{i}: repository(owner: "{owner}", name: "{name}") '
                     f'{{ nameWithOwner issues(states: OPEN) {{ totalCount }} }}')
    return "query { " + " ".join(parts) + " }"


def fetch_counts(slugs: list[str], runner: Runner) -> tuple[dict, dict] | None:
    """({canonical full name, lower case: open issues}, {asked name, lower case: canonical name}). A repo
    GitHub does not know is left out; gh exits 1 on a partial answer, so the body is read either way."""
    slugs = sorted({s for s in slugs if _SLUG.match(s)})
    counts: dict[str, int] = {}
    canonical: dict[str, str] = {}
    for i in range(0, len(slugs), COUNTS_BATCH):
        chunk = slugs[i:i + COUNTS_BATCH]
        try:
            _rc, out, _err = runner(["gh", "api", "graphql", "-f", f"query={counts_query(chunk)}"])
            data = json.loads(out or "")["data"]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        for j, s in enumerate(chunk):
            r = data.get(f"r{j}")
            if not isinstance(r, dict) or not _SLUG.match(str(r.get("nameWithOwner") or "")):
                continue
            full = r["nameWithOwner"]
            total = (r.get("issues") or {}).get("totalCount")
            if isinstance(total, int):
                counts[full.lower()] = total
            canonical[s.lower()] = full
    return counts, canonical


def refresh(slugs: list[str], now: float | None = None, runner: Runner | None = None) -> int:
    """Make the three calls and rewrite the cache. A part that fails keeps its previous value; the
    cache is stamped fresh only when all three worked, and on a failure the lock stays as a back-off."""
    now = asks._now() if now is None else now
    if runner is None:
        if not shutil.which("gh"):
            lock_path().unlink(missing_ok=True)
            return 0
        runner = default_runner
    old = load()
    prs, issues, cnt = fetch_prs(runner), fetch_issues(runner), fetch_counts(slugs, runner)
    new = {"version": VERSION, "at": now if None not in (prs, issues, cnt) else old["at"],
           "prs": old["prs"] if prs is None else prs,
           "issues": old["issues"] if issues is None else issues,
           "counts": old["counts"] if cnt is None else cnt[0],
           "canonical": old["canonical"] if cnt is None else cnt[1]}
    asks._atomic_write(cache_path(), json.dumps(new))
    if None in (prs, issues, cnt):
        return 1
    lock_path().unlink(missing_ok=True)
    return 0


# --- PR state, for `teyla asks` ----------------------------------------------------------------

def pr_state_path() -> pathlib.Path:
    return control.home() / "pr-state.json"


def canonical_pr_url(url) -> str:
    """`https://github.com/owner/repo/pull/N`, lower case; "" when `url` is not a GitHub PR link."""
    m = _PR_URL.match(str(url or "").strip())
    return f"https://github.com/{m.group(1)}/{m.group(2)}/pull/{int(m.group(3))}".lower() if m else ""


def pr_states_query(refs: list[tuple[str, str, int]]) -> str:
    parts = [f'p{i}: repository(owner: "{o}", name: "{n}") {{ pullRequest(number: {num}) '
             f'{{ state mergedAt closedAt }} }}' for i, (o, n, num) in enumerate(refs)]
    return "query { " + " ".join(parts) + " }"


def fetch_pr_states(urls: list[str], runner: Runner) -> dict | None:
    """{canonical url: {"state": OPEN|MERGED|CLOSED, "at": epoch of the merge or close, 0 when open}}.
    A PR GitHub does not know is left out. None when a call or its parsing failed. gh exits 1 on a
    partial answer, so the body is read either way."""
    refs = []
    for u in sorted({canonical_pr_url(x) for x in urls} - {""}):
        o, n, num = u.split("/")[3], u.split("/")[4], int(u.split("/")[6])
        if _SLUG.match(f"{o}/{n}"):
            refs.append((o, n, num))
    out: dict[str, dict] = {}
    for i in range(0, len(refs), PR_BATCH):
        chunk = refs[i:i + PR_BATCH]
        try:
            _rc, body, _err = runner(["gh", "api", "graphql", "-f", f"query={pr_states_query(chunk)}"])
            data = json.loads(body or "")["data"]
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        for j, (o, n, num) in enumerate(chunk):
            r = data.get(f"p{j}")
            pr = r.get("pullRequest") if isinstance(r, dict) else None
            if not isinstance(pr, dict):
                continue
            state = str(pr.get("state") or "").upper()
            if state not in ("OPEN", "MERGED", "CLOSED"):
                continue
            when = _epoch(pr.get("mergedAt") if state == "MERGED" else pr.get("closedAt")) if state != "OPEN" else 0.0
            out[f"https://github.com/{o}/{n}/pull/{num}".lower()] = {"state": state, "at": when}
    return out


def _load_pr_cache() -> dict:
    try:
        c = json.loads(pr_state_path().read_text())
    except (OSError, ValueError):
        c = {}
    if not isinstance(c, dict) or c.get("version") != VERSION or not isinstance(c.get("prs"), dict):
        return {"version": VERSION, "failed": 0.0, "prs": {}}
    try:
        failed = float(c.get("failed") or 0)
    except (TypeError, ValueError):
        failed = 0.0
    prs = {k: v for k, v in c["prs"].items() if isinstance(v, dict) and v.get("state") in ("OPEN", "MERGED", "CLOSED")}
    return {"version": VERSION, "failed": failed, "prs": prs}


def pr_states(urls: list[str], now: float, *, runner: Runner | None = None, fetch: bool = True) -> dict:
    """{canonical url: {"state", "at"}} for the PR links in `urls` whose state is known; others are left out.

    Order: the open PRs of the backlog cache (when that cache is under 30 minutes old), then
    `pr-state.json` entries under 30 minutes old, then one batched GraphQL query. Without `fetch`
    (`teyla state` must stay fast) a cache entry of any age is used and GitHub is not asked. Without
    `gh`, in safe mode, after a failed query within five minutes, or on a parse error, the unknown stay unknown."""
    wanted = {canonical_pr_url(u) for u in urls} - {""}
    known: dict[str, dict] = {}
    bl = load()
    if now - bl["at"] < FRESH_S:
        open_now = {canonical_pr_url(p.get("url")) for p in bl["prs"] if isinstance(p, dict)}
        known.update({u: {"state": "OPEN", "at": 0.0} for u in wanted & open_now})
    cache = _load_pr_cache()
    for u in wanted - set(known):
        e = cache["prs"].get(u)
        try:
            seen = float((e or {}).get("seen") or 0)
        except (TypeError, ValueError):
            seen = 0.0
        if e and (not fetch or now - seen < PR_TTL_S):
            known[u] = {"state": e["state"], "at": float(e.get("at") or 0)}
    missing = sorted(wanted - set(known))
    if not (fetch and missing) or now - cache["failed"] < PR_BACKOFF_S or not net.allowed():
        return known                        # safe mode closes the network here, as everywhere
    if runner is None:
        if not shutil.which("gh"):
            return known
        runner = default_runner
    got = fetch_pr_states(missing, runner)
    if got is None:
        cache["failed"] = now
    else:
        cache["failed"] = 0.0
        known.update(got)
        for u, e in got.items():
            cache["prs"][u] = {**e, "seen": now}
    cache["prs"] = {u: e for u, e in cache["prs"].items() if now - float(e.get("seen") or 0) < PR_KEEP_S}
    try:
        asks._atomic_write(pr_state_path(), json.dumps(cache))
    except OSError:
        pass
    return known

"""`teyla leak --published [owner]` — the audit of what is already public on GitHub for an owner.

Every PUBLIC repo of the owner (a user or an org) is read through `gh` and its text goes through the same
scanner rules as every other surface (`leak.Scanner`, so the same masking and the same private terms):

    the repo description and homepage        (from the repo list, no extra request)
    the README                               (1 request)
    the last 100 commits on the default branch: author and committer name and e-mail, and the message (1)
    open and recently closed issues and pull requests, titles and bodies (90 days, at most 200 items) (2 to 4)
    release notes, newest 50                 (1)

Private repos are never fetched, and neither are forks (their text and commits belong to someone else). A
finding is class `historical`: the text is already public, so the fix is at the source and a credential is
rotated first. Safe mode refuses without `--allow-network`. The one network path is the `gh` child process
with the owner's own login; each `gh` call counts against `--max-requests`. Nothing is cached.

docs/LEAK.md is the reference; docs/PRIVACY.md row 35 is the network ledger entry.
"""
from __future__ import annotations

import base64
import binascii
import bisect
import copy
import datetime as _dt
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

HEADER = "already public: fix the source and, for a credential, rotate first"
DEFAULT_MAX_REQUESTS = 400
REPO_LIST_LIMIT = 200
ITEMS_PER_REPO = 200
RELEASES_PER_REPO = 50
COMMITS_PER_REPO = 100
RECENT_DAYS = 90
SUMMARY_MAX_AGE_DAYS = 14
GH_TIMEOUT = 60

_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO = re.compile(r"^(?!\.{1,2}$)[A-Za-z0-9_.][A-Za-z0-9._-]{0,99}$")     # `.github` is a repo; `.` and `..` are not
TEYLA_REPO = "zaitsew/teyla"
_GH_URL = re.compile(r"github\.com[:/]+([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/", re.I)


class CapHit(Exception):
    """The request budget is spent."""


class Budget:
    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.used = 0

    def take(self) -> None:
        if self.used >= self.cap:
            raise CapHit()
        self.used += 1


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _gh(budget: Budget, argv: list[str]) -> tuple[int, str, str]:
    """One `gh` call: (exit code, stdout, stderr). Raises CapHit before it would exceed the budget."""
    budget.take()
    try:
        p = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=GH_TIMEOUT,
                           env=_env(), stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return 124, "", "gh timed out"
    except OSError as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def _env() -> dict:
    import os
    env = dict(os.environ)
    env["GH_PROMPT_DISABLED"] = "1"
    env["NO_COLOR"] = "1"
    return env


def _json(out: str):
    try:
        return json.loads(out)
    except ValueError:
        return None


def _why(rc: int, out: str, err: str) -> str:
    """A short, single-line reason for a failed call. The message comes from gh, never from the text we scanned."""
    msg = (err.strip() or out.strip() or f"exit {rc}").splitlines()[0]
    return msg[:160]


def _not_found(rc: int, out: str, err: str) -> bool:
    blob = (err + out).lower()
    return "404" in blob or "not found" in blob


# --- owners ------------------------------------------------------------------------------------

def owners_from_remotes(code_root: Path) -> list[str]:
    """The distinct GitHub owners in the remote URLs of the git repos directly under `code_root`. Local only."""
    owners: dict[str, str] = {}
    if not code_root.is_dir():
        return []
    for repo in sorted(p for p in code_root.iterdir() if p.is_dir() and (p / ".git").exists()):
        try:
            p = subprocess.run(["git", "-C", str(repo), "config", "--get-regexp", r"^remote\..*\.url$"],
                               capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in p.stdout.splitlines():
            m = _GH_URL.search(line.partition(" ")[2])
            if m:
                owners.setdefault(m.group(1).lower(), m.group(1))
    return sorted(owners.values(), key=str.lower)


# --- the audit ---------------------------------------------------------------------------------

class Audit:
    def __init__(self, cfg, budget: Budget) -> None:
        from . import leak
        self.leak = leak
        self.sc = leak.Scanner(None, cfg)
        self.sc.cfg.teyla = False         # the `[teyla]` terms apply to Teyla's repo only, whatever the current directory
        self.cov = self.sc.cov
        self._gl: list[tuple[str, str]] = []      # (path, text) of the repo being audited, for gitleaks
        self._gl_size = 0
        self.budget = budget
        self.repos_scanned = 0
        self.repos_skipped_private = 0
        self.repos_skipped_fork = 0
        self.repos_unaudited: list[str] = []

    # one text, as one place. `label` is the place prefix, `gpath` the path the finding carries.
    def scan(self, full: str, surface: str, text: str, place: str | None = None) -> None:
        if not text:
            return
        self.sc._text(place or f"{full}/{surface}", f"{full}/{surface}", self.leak._lines(text), "historical",
                      lang=False, note=HEADER)
        self._gl.append((f"{full}/{surface}", text))
        self._gl_size += len(text.encode("utf-8", "replace"))
        if self._gl_size > min(self.sc.max_bytes, 1 << 20) // 2:
            self.flush_gitleaks()

    def flush_gitleaks(self) -> None:
        """The texts read so far, as one text through gitleaks (the engine `--text` uses), findings class historical."""
        parts, self._gl, self._gl_size = self._gl, [], 0
        if not parts:
            return
        starts, chunks, n = [], [], 1
        for path, text in parts:
            t = text if text.endswith("\n") else text + "\n"
            starts.append((n, path))
            chunks.append(t)
            n += t.count("\n")

        def locate(line: int) -> tuple[str, int]:
            first, path = starts[max(bisect.bisect_right([a for a, _ in starts], line) - 1, 0)]
            return path, line - first + 1
        self.sc.gitleaks_text("".join(chunks), "published", cls="historical", note=HEADER, locate=locate)

    def contents(self, full: str, path: str) -> str | None:
        """One root file of a repo as text; None when it is absent or unreadable (the latter is noted as unread)."""
        rc, out, err = _gh(self.budget, ["api", f"repos/{full}/contents/{path}"])
        if rc != 0:
            if not _not_found(rc, out, err):
                self.unread(f"{full}: {path}", _why(rc, out, err))
            return None
        doc = _json(out)
        if not isinstance(doc, dict) or doc.get("encoding") != "base64":
            self.unread(f"{full}: {path}", "unexpected answer")
            return None
        try:
            return base64.b64decode(doc.get("content") or "").decode("utf-8", "replace")
        except (binascii.Error, ValueError):
            self.unread(f"{full}: {path}", "content is not base64")
            return None

    def begin_repo(self, full: str) -> tuple:
        """Per-repo rule configuration: `[teyla]` terms only when this repo is Teyla's (the repo zaitsew/teyla, or a
        root pyproject.toml with `[project] name = "teyla"`), and the repo's own `.leak-allow` (2 requests at most).
        Returns what `end_repo` restores."""
        cfg = self.sc.cfg
        saved = (copy.deepcopy(cfg.allow), list(cfg.exceptions), list(cfg.expired), len(cfg.errors))
        eng = self.leak._engine()
        allow = self.contents(full, ".leak-allow")
        is_teyla = full.lower() == TEYLA_REPO
        pyproject = None if is_teyla else self.contents(full, "pyproject.toml")
        with tempfile.TemporaryDirectory(prefix="teyla-leak-pub-") as tmp:
            root = Path(tmp)
            if pyproject is not None:
                (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
                is_teyla = eng._pyproject_name(root) == "teyla"
            if allow is not None:
                (root / ".leak-allow").write_text(allow, encoding="utf-8")
                eng.load_allow(cfg, root)
                self.cov.notes.append(f"{full}: its .leak-allow was applied (exception globs match {full}/<surface>)")
        cfg.errors[saved[3]:] = [f"{full}: {e}" for e in cfg.errors[saved[3]:]]
        cfg.teyla = is_teyla
        return saved

    def end_repo(self, saved: tuple) -> None:
        cfg = self.sc.cfg
        cfg.allow, cfg.exceptions[:], cfg.expired[:] = saved[0], saved[1], saved[2]
        cfg.teyla = False

    def unread(self, what: str, why: str) -> None:
        self.cov.unread.append((what, why))

    # -- surfaces --

    def readme(self, full: str) -> None:
        rc, out, err = _gh(self.budget, ["api", f"repos/{full}/readme"])
        if rc != 0:
            if not _not_found(rc, out, err):
                self.unread(f"{full}: README", _why(rc, out, err))
            return
        doc = _json(out)
        if not isinstance(doc, dict) or doc.get("encoding") != "base64":
            self.unread(f"{full}: README", "unexpected answer")
            return
        try:
            raw = base64.b64decode(doc.get("content") or "")
        except (binascii.Error, ValueError):
            self.unread(f"{full}: README", "content is not base64")
            return
        if len(raw) > self.sc.max_bytes:
            self.cov.skipped.append((f"{full}: README", f"{len(raw)} bytes, over the {self.sc.max_bytes} byte cap"))
            return
        self.scan(full, "README", raw.decode("utf-8", "replace"))

    def commits(self, full: str) -> None:
        rc, out, err = _gh(self.budget, ["api", f"repos/{full}/commits?per_page={COMMITS_PER_REPO}"])
        if rc != 0:
            if "409" in err or "empty" in err.lower():          # a repo with no commits
                return
            self.unread(f"{full}: commits", _why(rc, out, err))
            return
        items = _json(out)
        if not isinstance(items, list):
            self.unread(f"{full}: commits", "unexpected answer")
            return
        for it in items[:COMMITS_PER_REPO]:
            c = (it or {}).get("commit") or {}
            sha = str((it or {}).get("sha") or "")[:8] or "?"
            lines = []
            for role in ("author", "committer"):
                who = c.get(role) or {}
                ident = f"{who.get('name') or ''} <{who.get('email') or ''}>"
                if role == "committer" and lines and lines[0].partition(": ")[2] == ident:
                    continue                      # the same person: one line is enough
                lines.append(f"{role}: {ident}")
            lines.append(str(c.get("message") or ""))
            self.scan(full, "commits", "\n".join(lines), place=f"{full}/commit:{sha}")

    def issues(self, full: str) -> None:
        cutoff = _now() - _dt.timedelta(days=RECENT_DAYS)
        since = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        taken = 0
        for state in ("open", "closed"):
            page = 1
            while taken < ITEMS_PER_REPO:
                q = f"state={state}&per_page=100&page={page}" + (f"&since={quote(since)}" if state == "closed" else "")
                rc, out, err = _gh(self.budget, ["api", f"repos/{full}/issues?{q}"])
                if rc != 0:
                    if "410" in err or "disabled" in err.lower():       # issues turned off on the repo
                        break
                    self.unread(f"{full}: {state} issues and pull requests", _why(rc, out, err))
                    break
                items = _json(out)
                if not isinstance(items, list):
                    self.unread(f"{full}: {state} issues and pull requests", "unexpected answer")
                    break
                for it in items:
                    if taken >= ITEMS_PER_REPO:
                        break
                    if not isinstance(it, dict):
                        continue
                    if state == "closed" and not _recent(it.get("closed_at"), cutoff):
                        continue
                    taken += 1
                    kind = "pr" if "pull_request" in it else "issue"
                    n = it.get("number")
                    self.scan(full, f"{kind}#{n}", f"{it.get('title') or ''}\n{it.get('body') or ''}")
                if len(items) < 100:
                    break
                page += 1
        if taken >= ITEMS_PER_REPO:
            self.cov.notes.append(f"{full}: issues and pull requests capped at {ITEMS_PER_REPO}")

    def releases(self, full: str) -> None:
        rc, out, err = _gh(self.budget, ["api", f"repos/{full}/releases?per_page={RELEASES_PER_REPO}"])
        if rc != 0:
            if not _not_found(rc, out, err):
                self.unread(f"{full}: releases", _why(rc, out, err))
            return
        items = _json(out)
        if not isinstance(items, list):
            self.unread(f"{full}: releases", "unexpected answer")
            return
        for it in items[:RELEASES_PER_REPO]:
            if isinstance(it, dict):
                tag = str(it.get("tag_name") or "?")
                self.scan(full, f"release:{tag}", f"{it.get('name') or ''}\n{it.get('body') or ''}")

    def repo(self, row: dict, owner: str) -> None:
        name = str(row.get("name") or "")
        full = str(row.get("nameWithOwner") or f"{owner}/{name}")
        if not _REPO.match(name) or full.count("/") != 1 or not _OWNER.match(full.split("/")[0]):
            self.unread(f"{owner}: a repo with an unusable name", "not fetched")
            return
        saved = self.begin_repo(full)
        try:
            self.scan(full, "description", str(row.get("description") or ""))
            self.scan(full, "homepage", str(row.get("homepageUrl") or ""))
            self.readme(full)
            self.commits(full)
            self.issues(full)
            self.releases(full)
        finally:
            self.flush_gitleaks()
            self.end_repo(saved)
        self.repos_scanned += 1


def _recent(stamp, cutoff: _dt.datetime) -> bool:
    try:
        return _dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")) >= cutoff
    except ValueError:
        return False


def audit_owner(a: Audit, owner: str) -> None:
    """The public repos of one owner. Raises CapHit when the request budget runs out mid-way."""
    rc, out, err = _gh(a.budget, ["repo", "list", owner, "--visibility", "public", "--limit", str(REPO_LIST_LIMIT),
                                  "--json", "name,nameWithOwner,description,homepageUrl,url,visibility,isPrivate,isFork"])
    if rc != 0:
        a.unread(f"{owner}: repo list", _why(rc, out, err))
        return
    rows = _json(out)
    if not isinstance(rows, list):
        a.unread(f"{owner}: repo list", "unexpected answer")
        return
    if len(rows) >= REPO_LIST_LIMIT:
        a.cov.notes.append(f"{owner}: the repo list is capped at {REPO_LIST_LIMIT}; later repos were not listed")
    todo = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("isPrivate") or str(row.get("visibility") or "public").lower() != "public":
            a.repos_skipped_private += 1                 # never fetched: the audit is about what is public
        elif row.get("isFork"):
            a.repos_skipped_fork += 1
        else:
            todo.append(row)
    for i, row in enumerate(todo):
        try:
            a.repo(row, owner)
        except CapHit:
            a.repos_unaudited += [str(r.get("nameWithOwner") or r.get("name")) for r in todo[i:]]
            raise


def run(args) -> tuple:
    """(Result, exit code). Raises ValueError for a usage error, as leak.run does."""
    from . import config, leak, net
    if any([args.all, args.staged, args.outgoing, args.commits, args.text is not None]):
        raise ValueError("--published reads GitHub and takes no other surface")
    cap = args.max_requests
    if cap < 1:
        raise ValueError("--max-requests must be at least 1")
    owners = [o for o in [args.published or args.repo] if o]
    if owners and not _OWNER.match(owners[0]):
        raise ValueError(f"{owners[0]!r} is not a GitHub user or org name")
    if not owners:
        owners = owners_from_remotes(config.code_root())
        if not owners:
            raise ValueError("--published: no owner given, and no github.com remote under code_root names one")
    a = Audit(leak.load_config(None), Budget(cap))
    cap_hit = False
    if getattr(args, "allow_network", False):
        net.allow_for_this_command(True)
    if not net.gate("`teyla leak --published` (it reads your public GitHub repos through gh)"):
        a.unread("published", "safe mode is on; nothing was read (--allow-network opens this one run)")
        return a.sc.result(), 2
    if shutil.which("gh") is None:
        a.unread("gh", "the GitHub CLI is not installed or not on PATH; the published audit needs it")
    else:
        for owner in owners:
            try:
                audit_owner(a, owner)
            except CapHit:
                cap_hit = True
                break
        a.cov.read.append(f"published: {', '.join(owners)}: {a.repos_scanned} public repo(s); README, last {COMMITS_PER_REPO} commits, "
                          f"issues and pull requests of {RECENT_DAYS} days, releases, description and homepage")
    if a.repos_skipped_private:
        a.cov.notes.append(f"{a.repos_skipped_private} private repo(s) in the list were skipped, not fetched")
    if a.repos_skipped_fork:
        a.cov.notes.append(f"{a.repos_skipped_fork} fork(s) skipped: their text and commits are not the owner's")
    if cap_hit:
        a.cov.notes.append(f"request cap hit ({cap}): {a.repos_scanned} repo(s) audited, {len(a.repos_unaudited)} not; "
                           f"raise --max-requests")
        if a.repos_scanned == 0:
            a.unread("published", f"the {cap}-request cap was spent before anything was scanned")
    if not any(r.startswith("gitleaks") for r in a.cov.read) and not a.cov.gitleaks_missing:
        a.cov.gitleaks_missing = True              # --require-gitleaks must not pass when no text went through it
        a.cov.gitleaks_why = "no published text was passed to it"
    res = a.sc.result()
    code = leak.exit_code(res, args.require_gitleaks, args.allow_partial)
    if a.repos_scanned or res.findings:
        write_summary(res, owners, a.repos_scanned)
    return res, code


def render(res, **kw) -> str:
    from . import leak
    return HEADER + "\n" + leak.render(res, **kw)


# --- the weekly digest -------------------------------------------------------------------------

def summary_path() -> Path:
    from .control import state as control
    return control.home() / "leak" / "published.json"


def write_summary(res, owners: list[str], repos: int) -> None:
    from . import config
    blockers = len(res.blockers)
    body = {"at": _now().isoformat(), "owners": len(owners), "repos": repos, "blockers": blockers,
            "triage": sum(1 for f in res.findings if f.severity == "triage")}
    try:
        config.private_dir(summary_path().parent)
        summary_path().write_text(json.dumps(body) + "\n")
    except OSError:
        pass


def digest_candidates() -> list[dict]:
    """One digest line while the last published audit found blockers. Reads a small local file only."""
    try:
        d = json.loads(summary_path().read_text())
        at = _dt.datetime.fromisoformat(d["at"])
        n, repos = int(d["blockers"]), int(d["repos"])
    except (OSError, ValueError, KeyError, TypeError):
        return []
    if n <= 0 or _now() - at > _dt.timedelta(days=SUMMARY_MAX_AGE_DAYS):
        return []
    return [dict(rank=1, id="leak:published", text=f"{n} already-public finding(s) across {repos} public repo(s)",
                 step="teyla leak --published", cmd=True)]

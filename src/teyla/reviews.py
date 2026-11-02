"""`teyla reviews` — the review debt: merged PRs nobody reviewed.

A policy that asks for a cross-provider review of every non-trivial PR before merge is only as good as
the record that it happened. The review script appends one line per review to a ledger, and a merge
gate refuses `gh pr merge` without a ledger entry unless a skip reason is given (which is logged too).
This command reads that ledger against GitHub and says, per repo under `code_root`, which PRs merged in
the last N days were reviewed, which merged with a P1 still open, which were skipped on purpose, and
which slipped through.

Ledger (`review.ledger`, default `~/.cache/review-ledger.tsv`): tab-separated, no header, one line per review

    <ISO-UTC time> <repo short name> <reviewed commit sha> <mode: branch|commit|diff> <P1> <P2> <reviewer>

A skip is a line whose mode is `skip`; its last field is the reason (and may name the PR as `#123` or
`PR 123`). A short line, an unknown mode or a count that is not a number is "unparsed": counted, never fatal.

A PR is, in this order:
  reviewed      a ledger entry names any commit of the PR (a sha, or a prefix of 7+ characters either way),
                its head commit or its merge commit;
    open P1     ... and the newest such entry (latest commit of the PR, then latest line) reported P1 > 0;
                a later reviewed commit with no P1 (the fix) makes it plain "reviewed" again;
  exempt        changed lines < `review.min_lines` (default 7), or every file is *.md or under docs/ —
                the same exemption the merge gate applies;
  skipped       a skip line names one of its commits, or its number;
  unreviewed    none of the above.

A merged PR whose review still lists a P1 is settled with `teyla reviews settle` (see `settle` below): it writes
the skip line that `classify` already honours, after checking the evidence in git.

PRs come from one `gh pr list --state merged` call per repo, never in safe mode (unless the command line
carries --allow-network). Without gh, or when gh fails, the repo is skipped with a note; a missing ledger
is one line and exit 0. The weekly routine files `teyla reviews --quiet`, and `teyla digest` names the debt
from the summary this command leaves in `~/.teyla/reviews.json`.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import shutil
import subprocess
from typing import Callable

from . import config

MODES = {"branch", "commit", "diff", "diff-file"}   # "branch:<paths>" counts as branch
UNMATCHABLE = {"dirty"}                                # a review of uncommitted work names no commit
SKIP = "skip"
DEFAULT_LEDGER = "~/.cache/review-ledger.tsv"
DEFAULT_MIN_LINES = 7
SUMMARY_NAME = "reviews.json"
SUMMARY_MAX_AGE_DAYS = 10
GH_LIMIT = 100
# One search query per repo. `gh pr list --json commits` also fetches each commit's authors, and
# 100 PRs x 100 commits x 100 authors is over GitHub's 500,000-node limit: every repo failed.
# This asks only for the commit ids: 100 x (100 + 100) nodes.
PR_QUERY = ("query($q:String!){search(query:$q,type:ISSUE,first:%d){nodes{... on PullRequest{"
            "number title url mergedAt additions deletions headRefOid mergeCommit{oid} "
            "files(first:100){nodes{path}} commits(first:100){nodes{commit{oid}}}}}}}" % GH_LIMIT)
# One PR by number, for `settle`: the same fields as PR_QUERY.
PR_ONE_QUERY = ("query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){"
                "pullRequest(number:$number){number title url state mergedAt additions deletions headRefOid "
                "mergeCommit{oid} files(first:100){nodes{path}} commits(first:100){nodes{commit{oid}}}}}}")
SETTLE_READER = "teyla-reviews-settle"
SETTLE_OUTCOMES = ("fixed", "false")
SETTLE_REASON_MAX = 120                      # review-gate cuts a skip reason at the same length
_SHA = re.compile(r"^[0-9a-f]{7,64}$")
_TARGET = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)#(\d+)$")
_PR_URL = re.compile(r"github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")
_PR_REF = re.compile(r"(?:\bPR\s*#?|#|/pull/)(\d+)\b", re.I)

Runner = Callable[[list[str]], "tuple[int, str, str]"]


# --- config -----------------------------------------------------------------------------------

def ledger_path(cfg: dict | None = None) -> pathlib.Path:
    raw = str(((cfg or config.load()).get("review") or {}).get("ledger") or DEFAULT_LEDGER)
    return pathlib.Path(os.path.expanduser(raw))


def min_lines(cfg: dict | None = None) -> int:
    try:
        return int(((cfg or config.load()).get("review") or {}).get("min_lines", DEFAULT_MIN_LINES))
    except (TypeError, ValueError):
        return DEFAULT_MIN_LINES


def summary_path() -> pathlib.Path:
    return config.TEYLA_DIR / SUMMARY_NAME  # call time: tests and a moved home redirect TEYLA_DIR


# --- the ledger -------------------------------------------------------------------------------

def parse_ledger(text: str) -> dict:
    """{"reviews": [...], "skips": [...], "unparsed": n}. A review is {time, repo, sha, mode, p1, p2,
    reviewer, seq}; a skip is {time, repo, sha, reason, seq}. seq is the line order, the tie-break
    for "newest". Blank lines are ignored; nothing here raises."""
    reviews, skips, unparsed = [], [], 0
    for seq, raw in enumerate(text.splitlines()):
        if not raw.strip():
            continue
        f = [x.strip() for x in raw.split("\t")]
        if len(f) < 4:
            unparsed += 1
            continue
        when, repo, sha = f[0], f[1].lower(), f[2].lower()
        mode, _, detail = f[3].partition(":")       # codex-review writes "branch:<paths>", review-gate "skip:<why>"
        mode = mode.lower()
        pr = None
        m = _PR_URL.search(repo)                    # review-gate names the PR by its URL: owner/name
        if m:
            repo, pr = m.group(1).lower(), int(m.group(2))
        if mode == SKIP:
            skips.append({"time": when, "repo": repo, "sha": sha if _SHA.match(sha) else "", "pr": pr,
                          "reason": detail.strip() or (f[-1] if len(f) > 4 else ""), "seq": seq})
            continue
        if mode in UNMATCHABLE or sha == "-":       # reviewed, but no commit to match a PR against
            continue
        if mode not in MODES or len(f) < 6 or not _SHA.match(sha):
            unparsed += 1
            continue
        try:
            p1, p2 = int(f[4]), int(f[5])
        except ValueError:
            unparsed += 1
            continue
        reviews.append({"time": when, "repo": repo, "sha": sha, "mode": mode, "p1": p1, "p2": p2,
                        "reviewer": f[6] if len(f) > 6 else "", "seq": seq})
    return {"reviews": reviews, "skips": skips, "unparsed": unparsed}


def load_ledger(path: pathlib.Path) -> dict | None:
    """None when there is no ledger file (or it cannot be read)."""
    try:
        return parse_ledger(path.read_text(errors="replace"))
    except OSError:
        return None


def _same_sha(a: str, b: str) -> bool:
    a, b = a.lower(), b.lower()
    return len(a) >= 7 and len(b) >= 7 and (a.startswith(b) or b.startswith(a))


# --- classification ---------------------------------------------------------------------------

def _is_docs(path: str) -> bool:
    return path.lower().endswith(".md") or path.startswith("docs/")


def is_exempt(pr: dict, threshold: int) -> bool:
    changed = int(pr.get("additions") or 0) + int(pr.get("deletions") or 0)
    if changed < threshold:
        return True
    paths = [str(f.get("path") or "") for f in pr.get("files") or [] if isinstance(f, dict)]
    return bool(paths) and all(_is_docs(p) for p in paths)


def pr_commits(pr: dict) -> list[str]:
    """The PR's commit shas in order, then its head and merge commits (the reviewable tips)."""
    shas = [str(c.get("oid") or "") for c in pr.get("commits") or [] if isinstance(c, dict)]
    head = str(pr.get("headRefOid") or "")
    merge = str((pr.get("mergeCommit") or {}).get("oid") or "") if isinstance(pr.get("mergeCommit"), dict) else ""
    for extra in (head, merge):
        if extra and extra not in shas:
            shas.append(extra)
    return [s.lower() for s in shas if s]


def classify(pr: dict, repo_names: set[str], ledger: dict, threshold: int) -> dict:
    """{"state": reviewed|open_p1|exempt|skipped|unreviewed, ...} for one merged PR."""
    shas = pr_commits(pr)
    hits = []
    for r in ledger["reviews"]:
        if r["repo"] not in repo_names:
            continue
        for pos, s in enumerate(shas):
            if _same_sha(r["sha"], s):
                hits.append((pos, r["seq"], r))
                break
    newest = max(hits, key=lambda h: (h[0], h[1]))[2] if hits else None
    if newest and newest["p1"] == 0:
        return {"state": "reviewed", "p1": 0, "reviewer": newest["reviewer"]}
    number = pr.get("number")
    for s in ledger["skips"]:                       # a logged skip outranks an open P1: it says why
        if s["repo"] not in repo_names:
            continue
        if s.get("pr") is not None:                 # an explicit PR target: its reason may name others
            hit = s["pr"] == number
        else:
            hit = number is not None and any(int(m) == number for m in _PR_REF.findall(s["reason"]))
        if hit or (s["sha"] and any(_same_sha(s["sha"], c) for c in shas)):
            return {"state": "skipped", "reason": s["reason"]}
    if newest:
        return {"state": "open_p1", "p1": newest["p1"], "reviewer": newest["reviewer"], "sha": newest["sha"]}
    if is_exempt(pr, threshold):
        return {"state": "exempt"}
    return {"state": "unreviewed"}


STATES = ("reviewed", "open_p1", "exempt", "skipped", "unreviewed")


# --- gh ---------------------------------------------------------------------------------------

def _gh_runner(argv: list[str]) -> tuple[int, str, str]:
    r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout, r.stderr


def merged_prs(slug: str, since: _dt.date, runner: Runner) -> tuple[list[dict] | None, str]:
    """(PRs, note). None plus a reason when gh failed; the note is also set when the list was cut."""
    argv = ["gh", "api", "graphql", "-f", f"query={PR_QUERY}",
            "-f", f"q=repo:{slug} is:pr is:merged merged:>={since.isoformat()} sort:updated-desc"]
    try:
        rc, out, err = runner(argv)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"gh failed: {e.__class__.__name__}"
    if rc != 0:
        line = (err or out).strip().splitlines()
        return None, "gh failed" + (f": {line[0][:100]}" if line else f" (exit {rc})")
    try:
        nodes = json.loads(out or "{}")["data"]["search"]["nodes"]
    except (ValueError, KeyError, TypeError):
        return None, "gh returned something that is not a search result"
    if not isinstance(nodes, list):
        return None, "gh returned something that is not a list"
    rows = [_flat(n) for n in nodes if isinstance(n, dict) and n.get("number") is not None]
    note = f"only the newest {GH_LIMIT} merged PRs were listed" if len(rows) >= GH_LIMIT else ""
    return rows, note


def _flat(node: dict) -> dict:
    """A search node in the shape `gh pr list --json` gives: commits [{oid}], files [{path}]."""
    def items(conn):
        return (conn or {}).get("nodes") or [] if isinstance(conn, dict) else []
    return {**node,
            "commits": [{"oid": (c.get("commit") or {}).get("oid")} for c in items(node.get("commits")) if isinstance(c, dict)],
            "files": [f for f in items(node.get("files")) if isinstance(f, dict)]}


def _repos(paths: list[str] | None, cfg: dict) -> list[pathlib.Path]:
    from . import cloud
    root = config.code_root(cfg)
    if not paths:
        return cloud.discover_repos(cfg)
    out = []
    for p in paths:
        cand = pathlib.Path(p).expanduser()
        if not (cand.is_absolute() or "/" in p or p.startswith("~")) and (root / p).is_dir():
            cand = root / p
        out.append(cand)
    return out


# --- the report -------------------------------------------------------------------------------

def scan(paths: list[str] | None = None, days: int = 7, cfg: dict | None = None, runner: Runner | None = None,
         today: _dt.date | None = None, network: bool | None = None) -> dict:
    """The whole report as data. `runner(argv) -> (rc, stdout, stderr)` stands in for gh; `network`
    overrides the safe-mode gate (None: ask net.allowed)."""
    from . import cloud, net
    cfg = cfg or config.load()
    today = today or _dt.date.today()
    since = today - _dt.timedelta(days=days)
    rep = {"days": days, "ledger": str(ledger_path(cfg)), "ledger_found": False, "unparsed": 0, "repos": [],
           "notes": [], "totals": {k: 0 for k in ("merged",) + STATES}, "gh_called": False, "gh_failed": 0}
    ledger = load_ledger(ledger_path(cfg))
    if ledger is None:
        rep["notes"].append(f"no ledger at {rep['ledger']} — nothing to compare merged PRs against "
                            f"(the review script creates it on its first review)")
        return rep
    rep["ledger_found"], rep["unparsed"] = True, ledger["unparsed"]
    allowed = net.allowed(cfg) if network is None else network
    if not allowed:
        rep["notes"].append("safe mode: gh not called (by hand: teyla reviews --allow-network)")
        return rep
    if runner is None:
        if not shutil.which("gh"):
            rep["notes"].append("gh is not installed: merged PRs cannot be listed")
            return rep
        runner = _gh_runner
    threshold = min_lines(cfg)
    for repo in _repos(paths, cfg):
        slug = cloud.origin_slug(repo)
        if not slug:
            if paths:
                rep["notes"].append(f"{repo.name}: no GitHub origin, skipped")
            continue
        rep["gh_called"] = True
        prs, note = merged_prs(slug, since, runner)
        if prs is None:
            rep["gh_failed"] += 1
            rep["notes"].append(f"{slug}: {note}, skipped")
            continue
        if note:
            rep["notes"].append(f"{slug}: {note}")
        names = {repo.name.lower(), slug.split("/", 1)[1].lower(), slug.lower()}
        row = {"repo": repo.name, "slug": slug, "merged": 0, **{k: 0 for k in STATES}, "prs": []}
        for pr in prs:
            merged_at = str(pr.get("mergedAt") or "")
            if merged_at and merged_at[:10] < since.isoformat():
                continue
            c = classify(pr, names, ledger, threshold)
            row["merged"] += 1
            row[c["state"]] += 1
            row["prs"].append({"number": pr.get("number"), "title": str(pr.get("title") or ""),
                               "url": str(pr.get("url") or ""), "state": c["state"],
                               **{k: v for k, v in c.items() if k != "state"}})
        rep["repos"].append(row)
        for k in ("merged",) + STATES:
            rep["totals"][k] += row[k]
    return rep


def totals_line(rep: dict) -> str:
    t = rep["totals"]
    return (f"review debt: {t['unreviewed']} unreviewed, {t['open_p1']} merged with an open P1, "
            f"{t['skipped']} skipped of {t['merged']} merged PRs ({rep['days']}d)")


def debt(rep: dict) -> int:
    return rep["totals"]["unreviewed"] + rep["totals"]["open_p1"]


def render(rep: dict, quiet: bool = False) -> str:
    out = []
    if not rep["ledger_found"]:
        return "\n".join(rep["notes"])
    if not rep["repos"] and rep["notes"] and (not rep["gh_called"] or rep.get("gh_failed")):
        return "\n".join(f"review debt: not checked — {n}" for n in rep["notes"])
    if not quiet and rep["repos"]:
        out += [f"{'repo':20} {'merged':>6} {'exempt':>6} {'reviewed':>8} {'open-P1':>7} {'skipped':>7} {'unreviewed':>10}",
                "-" * 71]
        for r in rep["repos"]:
            out.append(f"{r['repo'][:20]:20} {r['merged']:>6} {r['exempt']:>6} {r['reviewed']:>8} "
                       f"{r['open_p1']:>7} {r['skipped']:>7} {r['unreviewed']:>10}")
        out.append("")
    for r in rep["repos"]:
        bad = [p for p in r["prs"] if p["state"] in ("open_p1", "unreviewed")]
        for p in sorted(bad, key=lambda p: (p["state"] != "open_p1", p.get("number") or 0)):
            tag = "merged with an open P1" if p["state"] == "open_p1" else "unreviewed"
            out.append(f"  {r['repo']} #{p['number']} {tag}: {p['title'][:80]}  {p['url']}")
    if quiet:
        for r in rep["repos"]:
            for p in r["prs"]:
                if p["state"] == "skipped":
                    out.append(f"  {r['repo']} #{p['number']} skipped ({p.get('reason', '')[:60]}): {p['title'][:60]}")
    if out and out[-1] != "":
        out.append("")
    out.append(totals_line(rep))
    if rep["unparsed"]:
        out.append(f"{rep['unparsed']} ledger line(s) unparsed (short, unknown mode or non-numeric counts)")
    out += [f"note: {n}" for n in rep["notes"]]
    return "\n".join(out)


def write_summary(rep: dict, now: _dt.datetime | None = None) -> None:
    """What the digest reads: only a run that asked GitHub about every repo leaves one. A failed
    query (expired login, outage) keeps the last summary, which ages out on its own."""
    if not rep["gh_called"] or rep.get("gh_failed"):
        return
    t = rep["totals"]
    body = {"when": (now or _dt.datetime.now(_dt.timezone.utc)).isoformat(timespec="seconds"),
            "days": rep["days"], "merged": t["merged"], "unreviewed": t["unreviewed"],
            "open_p1": t["open_p1"], "skipped": t["skipped"], "line": totals_line(rep)}
    p = summary_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, indent=1) + "\n")
        os.replace(tmp, p)
    except OSError:
        pass


def digest_line(now: _dt.datetime | None = None) -> str | None:
    """The totals line for the weekly digest: only while unreviewed + open-P1 > 0 and the summary is recent."""
    try:
        d = json.loads(summary_path().read_text())
        when = _dt.datetime.fromisoformat(str(d["when"]))
        if when.tzinfo is None:
            when = when.replace(tzinfo=_dt.timezone.utc)
        age = (now or _dt.datetime.now(_dt.timezone.utc)) - when
        if age > _dt.timedelta(days=SUMMARY_MAX_AGE_DAYS):
            return None
        if int(d.get("unreviewed") or 0) + int(d.get("open_p1") or 0) <= 0:
            return None
        return str(d["line"])
    except (OSError, ValueError, KeyError, TypeError):
        return None



# --- settle -----------------------------------------------------------------------------------

def _git(repo: pathlib.Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return r.returncode, r.stdout


def _default_ref(repo: pathlib.Path) -> str | None:
    for cand in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", f"{cand}^{{commit}}")[0] == 0:
            return cand
    return None


def _rev(repo: pathlib.Path, sha: str) -> str | None:
    rc, out = _git(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    return out.strip() if rc == 0 and out.strip() else None


def _fetch_pr(owner: str, name: str, number: int, runner: Runner) -> tuple[dict | None, str]:
    argv = ["gh", "api", "graphql", "-f", f"query={PR_ONE_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}",
            "-F", f"number={number}"]
    try:
        rc, out, err = runner(argv)
    except (OSError, subprocess.SubprocessError) as e:
        return None, f"gh failed: {e.__class__.__name__}"
    if rc != 0:
        line = (err or out).strip().splitlines()
        return None, "gh failed" + (f": {line[0][:100]}" if line else f" (exit {rc})")
    try:
        node = json.loads(out or "{}")["data"]["repository"]["pullRequest"]
    except (ValueError, KeyError, TypeError):
        return None, "gh returned something that is not a pull request"
    if not isinstance(node, dict):
        return None, f"{owner}/{name}#{number} does not exist"
    return _flat(node), ""


def settle(target: str, outcome: str, decision: str, reason: str, commit: str | None = None, *,
           cfg: dict | None = None, runner: Runner | None = None, network: bool | None = None,
           dry: bool = False) -> tuple[int, str]:
    """Record that the open P1 of a merged PR was handled, as one `skip` line in the ledger. (exit code, message).

    The ledger line is what `review-gate` writes at merge, so `classify` reads it as `skipped` and `attention`
    drops the PR. The evidence stays in git: `decision` is a file on the repo's default branch that names the
    PR, and for `fixed`, `commit` is on that branch and after the commit the review looked at. The ledger is
    never edited, only appended to, and only when every check passes. Whether the commit really fixes the
    finding is the decision file's claim, not something this command can prove."""
    from . import cloud, net
    cfg = cfg or config.load()
    m = _TARGET.match(target.strip())
    if not m:
        return 2, f"target must look like owner/repo#number, not {target!r}"
    owner, name, number = m.group(1), m.group(2), int(m.group(3))
    slug = f"{owner}/{name}"
    reason = " ".join((reason or "").split())
    if outcome not in SETTLE_OUTCOMES:
        return 2, f"outcome must be one of {', '.join(SETTLE_OUTCOMES)}, not {outcome!r}"
    if outcome == "fixed" and not commit:
        return 2, "--commit is required for outcome fixed: the commit that fixes the finding"
    if outcome == "false" and commit:
        return 2, "--commit belongs to outcome fixed; for a false finding say why in --reason"
    if outcome == "false" and not reason:
        return 2, "a false finding needs a --reason"
    if not decision:
        return 2, "--decision is required: the file in the repo that records the evidence"
    path = pathlib.PurePosixPath(decision)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return 2, f"--decision must be a path inside the repo, not {decision!r}"
    ledger_file = ledger_path(cfg)
    if not ledger_file.is_file():
        return 2, f"no ledger at {ledger_file}: nothing to settle"
    if not (net.allowed(cfg) if network is None else network):
        return 2, "safe mode: gh not called (by hand: teyla reviews settle ... --allow-network)"
    repo = next((r for r in cloud.discover_repos(cfg) if (cloud.origin_slug(r) or "").lower() == slug.lower()), None)
    if repo is None:
        return 2, f"no repo under code_root has origin {slug}"
    ref = _default_ref(repo)
    if ref is None:
        return 2, f"{repo.name}: no default branch found (origin/HEAD, origin/main, main)"
    rc, text = _git(repo, "show", f"{ref}:{path.as_posix()}")
    if rc != 0:
        return 2, (f"{decision} is not on the default branch ({ref}); merge the decision first "
                   f"(and `git fetch` if it was merged from another checkout)")
    if not re.search(rf"(?<![\w/]){re.escape('#' + str(number))}(?!\d)", text):
        return 2, f"{decision} does not name #{number}: the decision must say which PR it settles"
    if runner is None:
        if not shutil.which("gh"):
            return 2, "gh is not installed: the pull request cannot be read"
        runner = _gh_runner
    pr, note = _fetch_pr(owner, name, number, runner)
    if pr is None:
        return 2, note
    if not pr.get("mergedAt"):
        return 2, f"{slug}#{number} is not merged"
    ledger = load_ledger(ledger_file)
    names = {repo.name.lower(), name.lower(), slug.lower()}
    verdict = classify(pr, names, ledger or {"reviews": [], "skips": [], "unparsed": 0}, min_lines(cfg))
    if verdict["state"] != "open_p1":
        return 2, f"nothing to settle: {slug}#{number} is {verdict['state']}"
    if outcome == "fixed":
        fix = _rev(repo, commit or "")
        if fix is None:
            return 2, f"{commit} is not a commit in {repo.name}"
        reviewed = _rev(repo, verdict["sha"])
        if reviewed is None:
            return 2, f"the reviewed commit {verdict['sha'][:10]} is not in {repo.name}; fetch it first"
        if _git(repo, "merge-base", "--is-ancestor", fix, ref)[0] != 0:
            return 2, f"{commit[:10]} is not on the default branch ({ref})"
        if fix == reviewed or _git(repo, "merge-base", "--is-ancestor", reviewed, fix)[0] != 0:
            return 2, f"{commit[:10]} must come after the reviewed commit {reviewed[:10]}"
    head = str(pr.get("headRefOid") or "")
    url = str(pr.get("url") or f"https://github.com/{slug}/pull/{number}")
    why = f"settled({outcome}) {path.as_posix()}" + (f" - {reason}" if reason else "")
    row = "\t".join([_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), url, head or "-",
                     f"skip:{why[:SETTLE_REASON_MAX]}", "-", "-", SETTLE_READER])
    if dry:
        return 0, f"dry run, nothing written. The ledger line would be:\n{row}"
    try:
        with open(ledger_file, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            if fh.tell():
                fh.seek(-1, os.SEEK_END)
                lead = "" if fh.read(1) == b"\n" else "\n"
            else:
                lead = ""
        with open(ledger_file, "a") as fh:
            fh.write(lead + row + "\n")
    except OSError as e:
        return 2, f"the ledger could not be written: {e.__class__.__name__}"
    return 0, f"settled {slug}#{number} ({outcome}): one skip line appended to {ledger_file}"

# --- CLI --------------------------------------------------------------------------------------

def cmd_reviews(args) -> int:
    if args.repos and args.repos[0] == "settle":
        if len(args.repos) != 2:
            print("usage: teyla reviews settle OWNER/REPO#N --outcome fixed|false --decision PATH --reason TEXT [--commit SHA]")
            return 2
        rc, msg = settle(args.repos[1], args.outcome or "", args.decision or "", args.reason or "", args.commit,
                         dry=args.dry)
        print(msg)
        return rc
    rep = scan(args.repos or None, days=args.days)
    if not args.repos:
        write_summary(rep)
    if args.json:
        print(json.dumps(rep, indent=1))
    else:
        print(render(rep, quiet=args.quiet))
    return 0


def register(sp):
    q = sp.add_parser("reviews", help="review debt: merged PRs never reviewed, merged with an open P1, or skipped")
    q.set_defaults(fn=cmd_reviews)
    q.add_argument("repos", nargs="*", help="repo names under code_root or paths (default: every git repo under code_root)")
    q.add_argument("--days", type=int, default=7, help="window of merged PRs (default: 7)")
    q.add_argument("--json", action="store_true")
    q.add_argument("--quiet", action="store_true", help="the totals line and the PRs that need a look, no per-repo table")
    q.add_argument("--allow-network", action="store_true", help="safe mode: allow gh for this one run")
    q.add_argument("--outcome", choices=SETTLE_OUTCOMES, help="settle: fixed (a later commit fixed the P1) or false (it was wrong)")
    q.add_argument("--commit", help="settle, outcome fixed: the commit that fixes it, on the default branch and after the review")
    q.add_argument("--decision", help="settle: a file on the default branch (docs/decisions/...) that names the PR and shows the evidence")
    q.add_argument("--reason", help="settle: one line, required for a false finding")
    q.add_argument("--dry", action="store_true", help="settle: print the ledger line, write nothing")
    return q

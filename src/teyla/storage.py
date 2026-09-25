"""`teyla storage` — what agent-driven development is holding on this machine, and the part
of it that is safe to give back.

    teyla storage [--json] [--no-sizes]          the report: disk, worktrees, build output, caches, RAM
    teyla storage clean [--apply] [--auto]       remove the SAFE rows; a dry run unless --apply

Measured on the machine this was written on (2026-09-25): 35 agent worktrees under
`<repo>/.claude/worktrees` held 20 GB, 33 of them clean and already on the remote; 13 more
under `~/.worktrees` held 9 GB; four iOS simulators were booted at once. Nothing there is
work — it is what a parallel agent leaves behind when its PR merges.

What counts as SAFE is the rule in the owner's CLAUDE.md, applied mechanically:

- **a worktree** is SAFE when it is clean (`git status --porcelain` empty), its HEAD is on a
  remote branch (`git branch -r --contains HEAD`), nothing has touched it for `idle_days`
  (`agent_idle_days` for a subagent's `.claude/worktrees/agent-*`, which nothing resumes),
  no process has its working directory inside it, it is not locked, its own reflog points
  at no commit that exists nowhere else, no other worktree lives inside it, and it holds no
  git-ignored file that is not build output (`git worktree remove` deletes ignored files
  even without `--force`: a `.env`, local notes). `.teyla/corrections.jsonl` is appended to
  the main checkout's copy first. Every fact is checked again right before removal; the
  tree goes with `git worktree remove` — never `rm` — and without `--force`. The branch is kept.
- **a build directory** (`build`, `.build`, `.next`, `dist`, `target`, `DerivedData`, …) is
  SAFE when git ignores it, tracks nothing inside it, it is not part of a nested clone, no
  LaunchAgent names it, and its repo has been idle for `build_idle_days`. It is output the
  next build writes again.

When `lsof` cannot answer, nothing counts as unused and nothing is removed.

Everything else is REVIEW or KEEP, with the command that would clear it: dependency trees
(`node_modules`, `.venv`) break a routine that runs from them until reinstalled; package
caches are cleared by their own tool; session transcripts are what `teyla monitor` reads;
simulators and Docker are managed by their own apps. Teyla never deletes those.

`clean --auto` is what the daily routine runs: it applies only when
`teyla config set storage.auto_clean=true`, and says nothing otherwise. Every removal is
appended to `~/.teyla/storage.log`.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

from . import config

LOG_PATH = config.TEYLA_DIR / "storage.log"

# Output the next build writes again. Only ever removed when git ignores the directory.
REGENERABLE = {"build", ".build", ".next", "dist", "target", "DerivedData", ".turbo", ".parcel-cache",
               ".svelte-kit", ".expo", "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
# Regenerable too, but a launchd routine may run out of them: reported, never removed.
DEPENDENCIES = {"node_modules", ".venv", "venv", "Pods"}
# Never descended into while looking for the two sets above.
_NO_DESCEND = {".git", ".claude", ".worktrees"} | REGENERABLE | DEPENDENCIES
MAX_DEPTH = 4
# Git-ignored entries a worktree may hold that are output, not work. `git worktree remove`
# deletes ignored files without --force, so anything else ignored keeps the tree.
HARMLESS_IGNORED = REGENERABLE | DEPENDENCIES | {"__pycache__", ".swiftpm", ".DS_Store", ".temp", ".cache", ".gradle", ".kotlin",
                                                 "next-env.d.ts", ".eslintcache"}
HARMLESS_SUFFIXES = (".xcodeproj", ".tsbuildinfo", ".pyc", ".xcworkspace")
# Session-local permission grants, not work.
HARMLESS_PATHS = {".claude/settings.local.json"}
# Ignored, but work: moved into the main checkout's copy before the tree goes.
RESCUE = ".teyla/corrections.jsonl"
# Build/dependency rows smaller than this are counted, not listed, in the text report.
SHOW_MIN = 50 * 1024 ** 2

# Free space below either threshold is a doctor WARN.
LOW_FREE_FRACTION = 0.15
LOW_FREE_BYTES = 25 * 1024 ** 3


# --- small helpers --------------------------------------------------------------

def _git(cwd, *args, timeout=60) -> tuple[int, str]:
    try:
        # --no-optional-locks: a plain `git status` rewrites the index, and the index mtime is
        # how idleness is measured — the scan would otherwise make every tree look fresh.
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(cwd), *args],
                           capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, r.stdout


def du(path) -> int:
    """Bytes on disk under `path` (`du -sk`: follows no symlinks, counts hard links once)."""
    try:
        r = subprocess.run(["du", "-sk", str(path)], capture_output=True, text=True, timeout=600)
        return int(r.stdout.split()[0]) * 1024 if r.stdout else 0
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0


def human(n: int | None) -> str:
    if n is None:
        return "-"
    for unit in ("B", "K", "M", "G", "T"):
        if abs(n) < 1024 or unit == "T":
            return f"{n:.0f}{unit}" if unit in ("B", "K") else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n}"


def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in ("1", "true", "yes", "on")


def settings(cfg: dict | None = None) -> dict:
    s = (cfg or config.load()).get("storage") or {}
    def _int(k, d):
        try:
            return int(s.get(k, d))
        except (TypeError, ValueError):
            return d
    return {"auto_clean": _truthy(s.get("auto_clean", False)),
            "idle_days": _int("idle_days", 3), "agent_idle_days": _int("agent_idle_days", 1),
            "build_idle_days": _int("build_idle_days", 14)}


def is_agent_worktree(path: str) -> bool:
    """`<repo>/.claude/worktrees/agent-<hex>`: a subagent's isolated checkout. Nothing resumes
    it once its parent has the result, so it is finished sooner than a session's worktree."""
    p = pathlib.PurePath(path)
    return p.name.startswith("agent-") and p.parent.name == "worktrees" and p.parent.parent.name == ".claude"


def process_cwds() -> list[str] | None:
    """The working directory of every process this user can see. A directory some process
    sits in is in use, whatever git says about it. None when lsof could not answer: that
    is "unknown", never "nothing is in use", and nothing is removed on it."""
    try:
        r = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    cwds = {os.path.realpath(line[1:]) for line in r.stdout.splitlines() if line.startswith("n/")}
    return sorted(cwds) or None  # this process has a cwd; an empty answer is a failed one


def _in_use(path: str, cwds: list[str] | None) -> bool:
    if cwds is None:
        return True
    real = os.path.realpath(path)
    return any(c == real or c.startswith(real + os.sep) for c in cwds)


def _mtime(p) -> float:
    try:
        return os.stat(p).st_mtime
    except OSError:
        return 0.0


def _idle_days(*paths, now: float | None = None) -> float:
    latest = max((_mtime(p) for p in paths), default=0.0)
    return ((now or time.time()) - latest) / 86400 if latest else 1e9


def repos(root: pathlib.Path, extra: list[pathlib.Path] = ()) -> list[pathlib.Path]:
    """Main checkouts directly under the code root (one level, as the layout says), plus
    `extra` roots that are git repos themselves (the ops root)."""
    found = sorted(p for p in root.iterdir() if p.is_dir() and (p / ".git").is_dir()) if root.is_dir() else []
    return found + [p for p in extra if (p / ".git").is_dir() and p not in found]


# --- worktrees --------------------------------------------------------------------

def _harmless(entry: str) -> bool:
    e = entry.rstrip("/")
    if e in HARMLESS_PATHS:
        return True
    # The entry's own name only: `--ignored=matching` lists an ignored directory as `build/`,
    # so a listed `build/signing.p12` means build/ itself is tracked and that file is not output.
    name = e.rsplit("/", 1)[-1]
    return name in HARMLESS_IGNORED or name.endswith(HARMLESS_SUFFIXES)


def ignored_work(path: str) -> tuple[list[str], list[str]]:
    """(ignored entries that are work, files to rescue). `git status` does not show ignored
    files, and `git worktree remove` deletes them without --force: a `.env` holding a key,
    `.teyla/corrections.jsonl`, local notes."""
    rc, out = _git(path, "status", "--porcelain", "--ignored=matching", "--untracked-files=all")
    if rc != 0:
        return ["(git status failed)"], []
    work, rescue = [], []
    for line in out.splitlines():
        if not line.startswith("!! "):
            continue
        entry = line[3:].strip().strip('"')
        if _harmless(entry):
            continue
        if entry.rstrip("/") == ".teyla":
            files = [str(p.relative_to(path)) for p in pathlib.Path(path, ".teyla").rglob("*") if p.is_file()]
            if files and all(f == RESCUE for f in files):
                rescue.append(RESCUE)
                continue
        if entry == RESCUE:
            rescue.append(RESCUE)
            continue
        work.append(entry)
    return work, rescue


def _patch_ids(path: str, args: list[str], stdin: str | None = None) -> set[str] | None:
    try:
        show = subprocess.run(["git", "--no-optional-locks", "-C", path, *args], input=stdin,
                              capture_output=True, text=True, timeout=300)
        # --verbatim: --stable ignores whitespace, and indentation is meaning in Python or YAML.
        pid = subprocess.run(["git", "-C", path, "patch-id", "--verbatim"], input=show.stdout,
                             capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if show.returncode != 0 or pid.returncode != 0:
        return None
    return {line.split()[0] for line in pid.stdout.splitlines() if line.strip()}


def _automatic_merge(path: str, sha: str) -> bool:
    """True when the merge commit's tree is exactly what git merges on its own."""
    rc, parents = _git(path, "rev-list", "--parents", "-n", "1", sha)
    ps = parents.split()[1:]
    if rc != 0 or len(ps) != 2:
        return False
    rc, tree = _git(path, "rev-parse", f"{sha}^{{tree}}")
    rc2, merged = _git(path, "merge-tree", "--write-tree", ps[0], ps[1])
    return rc == 0 and rc2 == 0 and merged.split()[:1] == tree.split()[:1]


def reflog_only_commits(path: str) -> bool:
    """True when this worktree's own HEAD reflog points at work no branch, tag or remote
    holds — a detached HEAD that committed and moved on. Removing the tree deletes that
    reflog, the last reference to the commit. A commit whose change (patch-id) a remote
    branch already carries is a superseded copy — reset and re-committed, rebased,
    cherry-picked — not work; a merge is work unless its tree is git's own automatic merge."""
    rc, out = _git(path, "reflog", "--format=%H", "HEAD")  # all of it: git's own expiry bounds it
    shas = sorted(set(out.split())) if rc == 0 else []
    if not shas:
        return False
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", path, "rev-list", "--stdin",
                            "--not", "--remotes", "--branches", "--tags"],
                           input="\n".join(shas) + "\n", capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return True
    if r.returncode != 0:
        return True
    orphans = r.stdout.split()
    if not orphans:
        return False
    if len(orphans) > 100:
        return True
    rc, merges = _git(path, "rev-list", "--no-walk", "--merges", *orphans)
    merges = set(merges.split()) if rc == 0 else set(orphans)
    for m in merges:
        if not _automatic_merge(path, m):
            return True  # a conflict resolution or an edit in a merge is work
    orphans = [o for o in orphans if o not in merges]
    if not orphans:
        return False
    rc, dates = _git(path, "show", "-s", "--format=%ct", *orphans)
    try:
        since = min(int(d) for d in dates.split()) - 30 * 86400
    except ValueError:
        return True
    plain = ["--no-color", "--no-textconv", "--no-ext-diff", "--binary", "--format=commit %H"]
    mine = _patch_ids(path, ["show", *plain, *orphans])
    theirs = _patch_ids(path, ["log", "-p", *plain, "--no-merges", "--remotes", f"--since={since}"])
    if mine is None or theirs is None:
        return True
    return bool(mine - theirs)


def assess(path: str, cwds: list[str] | None, limit: int, others: list[str] = (), locked: bool = False,
           now: float | None = None) -> dict:
    """Everything that decides whether a worktree may go. `why` empty = SAFE."""
    rc, gitdir = _git(path, "rev-parse", "--absolute-git-dir")
    gitdir = gitdir.strip() if rc == 0 else ""
    idle = _idle_days(path, *(os.path.join(gitdir, p) for p in ("index", "HEAD", os.path.join("logs", "HEAD")) if gitdir),
                      now=now)
    _, st = _git(path, "status", "--porcelain", "--untracked-files=all")
    dirty = len([l for l in st.splitlines() if l.strip()])
    _, on_remote = _git(path, "branch", "-r", "--contains", "HEAD")
    pushed = bool(on_remote.strip())
    work, rescue = ignored_work(path)
    busy = [n for n in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD",
                        "BISECT_LOG", "sequencer") if gitdir and os.path.exists(os.path.join(gitdir, n))]
    real = os.path.realpath(path) + os.sep
    nested = [o for o in others if os.path.realpath(o).startswith(real)]
    why = []
    if not gitdir:
        why.append("git cannot read it")
    if locked:
        why.append("locked")
    if busy:
        why.append(f"a git operation is in progress ({busy[0]})")
    if dirty:
        why.append(f"{dirty} uncommitted change(s)")
    if not pushed:
        why.append("HEAD is on no remote branch")
    if reflog_only_commits(path):
        why.append("its reflog holds commits nothing else contains")
    if nested:
        why.append(f"{len(nested)} other worktree(s) inside it")
    if work:
        why.append("ignored files that are not build output: " + ", ".join(work[:4]) + (" …" if len(work) > 4 else ""))
    if cwds is None:
        why.append("could not check for processes (lsof failed)")
    elif _in_use(path, cwds):
        why.append("a process is working in it")
    recent = idle < limit
    if recent:
        why.append(f"touched {idle:.1f}d ago (< {limit}d)")
    return {"idle_days": round(idle, 1), "dirty": dirty, "pushed": pushed, "rescue": rescue, "why": why,
            "only_recent": recent and len(why) == 1}


def _parse_worktrees(text: str) -> list[dict]:
    out, cur = [], {}
    for line in text.splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v or True
    return out


def worktrees(repo: pathlib.Path, cwds: list[str] | None, idle_days: int, sizes: bool = True,
              now: float | None = None, agent_idle_days: int | None = None) -> list[dict]:
    """Every linked worktree of `repo` (the main checkout is not one), with a verdict."""
    rc, out = _git(repo, "worktree", "list", "--porcelain")
    if rc != 0:
        return []
    listed = _parse_worktrees(out)
    paths = [w["worktree"] for w in listed if w.get("worktree")]
    rows = []
    for w in listed[1:]:
        path = w.get("worktree")
        if not path:
            continue
        row = {"kind": "worktree", "repo": repo.name, "main": str(repo), "path": path,
               "branch": str(w.get("branch", "")).removeprefix("refs/heads/") or "(detached)"}
        if w.get("prunable") or not os.path.isdir(path):
            # An unmounted volume or a path launchd may not read looks the same: report only.
            row.update(verdict="REVIEW", reason="directory missing; if it is really gone: git -C "
                       f"{repo} worktree prune", action="none", bytes=0, only_recent=False)
            rows.append(row)
            continue
        limit = agent_idle_days if agent_idle_days is not None and is_agent_worktree(path) else idle_days
        a = assess(path, cwds, limit, others=[p for p in paths if p != path], locked=bool(w.get("locked")), now=now)
        row.update({k: a[k] for k in ("idle_days", "dirty", "pushed", "rescue", "only_recent")},
                   limit=limit, locked=bool(w.get("locked")),
                   verdict="KEEP" if a["why"] else "SAFE",
                   reason="; ".join(a["why"]) or (f"clean, on the remote, idle {a['idle_days']:.0f}d"
                                                  + (f"; {RESCUE} is kept in the main checkout" if a["rescue"] else "")),
                   action="git worktree remove", bytes=du(path) if sizes else None)
        rows.append(row)
    return rows


# --- build output -----------------------------------------------------------------

def _find_dirs(repo: pathlib.Path) -> list[pathlib.Path]:
    found = []
    base_depth = len(repo.parts)
    for dirpath, dirnames, _ in os.walk(repo):
        depth = len(pathlib.Path(dirpath).parts) - base_depth
        keep = []
        for d in dirnames:
            if os.path.exists(os.path.join(dirpath, d, ".git")):
                continue  # a nested clone or worktree: its files are not this repo's to judge
            if d in REGENERABLE or d in DEPENDENCIES:
                if not os.path.islink(os.path.join(dirpath, d)):  # a link points at someone else's data
                    found.append(pathlib.Path(dirpath, d))
            elif d not in _NO_DESCEND and depth + 1 < MAX_DEPTH and not os.path.islink(os.path.join(dirpath, d)):
                keep.append(d)
        dirnames[:] = keep
    return found


def repo_idle_days(repo: pathlib.Path, now: float | None = None) -> float:
    """Days since anything happened in the checkout: the index, HEAD, a fetch, a commit."""
    g = repo / ".git"
    rc, ct = _git(repo, "log", "-1", "--format=%ct")
    commit = float(ct.strip()) if rc == 0 and ct.strip().isdigit() else 0.0
    by_files = _idle_days(g / "index", g / "HEAD", g / "FETCH_HEAD", g / "logs" / "HEAD", now=now)
    by_commit = ((now or time.time()) - commit) / 86400 if commit else 1e9
    return min(by_files, by_commit)


SHIPPED_SUFFIXES = (".xcarchive", ".dSYM", ".ipa", ".dmg", ".pkg", ".aab", ".apk")


def _shipped(d: pathlib.Path) -> str:
    """The first archive, symbol bundle or installer under `d` (three levels), or ''."""
    base = len(d.parts)
    for dirpath, dirnames, filenames in os.walk(d):
        for n in dirnames + filenames:
            if n.endswith(SHIPPED_SUFFIXES):
                return n
        if len(pathlib.Path(dirpath).parts) - base >= 3:
            dirnames[:] = []
    return ""


def launch_references() -> str:
    """The text of every LaunchAgent plist and Teyla wrapper: a build dir named in one is
    something a routine runs, whatever the repo's git activity says."""
    texts = []
    for pat in (pathlib.Path.home() / "Library" / "LaunchAgents").glob("*.plist"), config.TEYLA_DIR.glob("*.sh"):
        for p in pat:
            try:
                texts.append(p.read_text(errors="replace"))
            except OSError:
                pass
    return "\n".join(texts)


def artifacts(repo: pathlib.Path, cwds: list[str] | None, build_idle_days: int, sizes: bool = True,
              now: float | None = None, launched: str = "") -> list[dict]:
    rows = []
    idle = repo_idle_days(repo, now=now)
    # A session in <repo>/.claude/worktrees/x is working in its own tree, not in this checkout.
    own = os.path.realpath(repo / ".claude" / "worktrees") + os.sep
    in_use = _in_use(str(repo), None if cwds is None else [c for c in cwds if not c.startswith(own)])
    for d in _find_dirs(repo):
        rel = str(d.relative_to(repo))
        rc, _ = _git(repo, "check-ignore", "-q", rel)
        if rc != 0:
            continue  # tracked, or not ignored: source, not output
        row = {"kind": "build" if d.name in REGENERABLE else "deps", "repo": repo.name, "main": str(repo),
               "path": str(d), "idle_days": round(idle, 1)}
        why = []
        if d.name in DEPENDENCIES:
            why.append("dependencies — a routine may run from them; reinstall to recreate")
        elif cwds is None:
            why.append("could not check for processes (lsof failed)")
        elif in_use:
            why.append("a process is working in the repo")
        elif str(d) in launched or str(repo) + "/" in launched or os.path.realpath(repo) + "/" in launched:
            why.append("a LaunchAgent or Teyla wrapper names this repo")
        elif _shipped(d):
            why.append(f"holds a shipped build ({_shipped(d)}): a rebuild is not the same file")
        elif idle < build_idle_days:
            why.append(f"repo active {idle:.1f}d ago (< {build_idle_days}d)")
        verdict = "SAFE" if not why else ("REVIEW" if d.name in DEPENDENCIES or "shipped" in why[0] else "KEEP")
        row.update(verdict=verdict, reason="; ".join(why) or f"ignored build output, repo idle {idle:.0f}d",
                   action="rm (git-ignored)", bytes=du(d) if sizes else None)
        rows.append(row)
    return rows


# --- caches and stores Teyla only reports -------------------------------------------

def _caches() -> list[tuple[str, str, str, str]]:
    """(name, path, verdict, the command or reason). REVIEW = a tool's own cache, cleared by
    that tool; KEEP = not Teyla's to clear."""
    h = str(pathlib.Path.home())
    L = f"{h}/Library"
    return [
        ("Xcode DerivedData", f"{L}/Developer/Xcode/DerivedData", "REVIEW", "rm -rf ~/Library/Developer/Xcode/DerivedData/*   (Xcode rebuilds it; quit Xcode first)"),
        ("iOS simulators", f"{L}/Developer/CoreSimulator/Devices", "REVIEW", "xcrun simctl delete unavailable   (then erase what you no longer use: xcrun simctl delete <udid>)"),
        ("iOS device support", f"{L}/Developer/Xcode/iOS DeviceSupport", "REVIEW", "delete the folders for iOS versions no device of yours runs"),
        ("npm cache", f"{h}/.npm", "REVIEW", "npm cache clean --force"),
        ("pnpm store", f"{L}/pnpm", "REVIEW", "pnpm store prune"),
        ("bun cache", f"{h}/.bun/install/cache", "REVIEW", "bun pm cache rm"),
        ("uv cache", f"{h}/.cache/uv", "REVIEW", "uv cache prune"),
        ("pip cache", f"{L}/Caches/pip", "REVIEW", "pip cache purge"),
        ("Gradle caches", f"{h}/.gradle/caches", "REVIEW", "rm -rf ~/.gradle/caches   (the next Android build downloads again)"),
        ("Homebrew", f"{L}/Caches/Homebrew", "REVIEW", "brew cleanup -s"),
        ("Codex runtimes", f"{h}/.cache/codex-runtimes", "REVIEW", "Codex re-downloads what it needs"),
        ("Hugging Face models", f"{h}/.cache/huggingface", "REVIEW", "huggingface-cli delete-cache   (models you downloaded; pick)"),
        ("Docker", f"{L}/Containers/com.docker.docker", "REVIEW", "docker system prune   (Docker Desktop → Troubleshoot to shrink the disk image)"),
        ("Claude Code transcripts", f"{h}/.claude/projects", "KEEP", "what `teyla monitor` reads"),
        ("Codex sessions", f"{h}/.codex/sessions", "KEEP", "what `teyla monitor` reads"),
        ("Grok sessions", f"{h}/.grok/sessions", "KEEP", "what `teyla monitor` reads"),
        ("Claude desktop VM", f"{L}/Application Support/Claude/vm_bundles", "KEEP", "managed by the Claude app"),
    ]


def caches(sizes: bool = True) -> list[dict]:
    rows = []
    for name, path, verdict, how in _caches():
        if os.path.exists(path):
            rows.append({"kind": "cache", "name": name, "path": path, "verdict": verdict, "reason": how,
                         "bytes": du(path) if sizes else None})
    return rows


# --- RAM ------------------------------------------------------------------------------

def booted_simulators() -> list[str]:
    if not shutil.which("xcrun"):
        return []
    try:
        r = subprocess.run(["xcrun", "simctl", "list", "devices", "booted", "-j"], capture_output=True, text=True, timeout=30)
        data = json.loads(r.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    return [d.get("name", "?") for devs in (data.get("devices") or {}).values() for d in devs if d.get("state") == "Booted"]


def memory_by_app(top: int = 8) -> list[tuple[str, int, int]]:
    """(process name, RSS bytes, process count), largest first."""
    try:
        r = subprocess.run(["ps", "-axo", "rss=,comm="], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    agg: dict[str, list[int]] = {}
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        name = parts[1].rsplit("/", 1)[-1]
        a = agg.setdefault(name, [0, 0])
        a[0] += int(parts[0]) * 1024; a[1] += 1
    return sorted(((k, v[0], v[1]) for k, v in agg.items()), key=lambda t: -t[1])[:top]


# --- the report ----------------------------------------------------------------------

def disk(path: pathlib.Path | None = None) -> dict:
    u = shutil.disk_usage(str(path or pathlib.Path.home()))
    return {"total": u.total, "used": u.used, "free": u.free, "free_fraction": u.free / u.total if u.total else 0}


def scan(root: pathlib.Path | None = None, sizes: bool = True, cfg: dict | None = None,
         cwds: list[str] | None = None, now: float | None = None) -> dict:
    s = settings(cfg)
    extra = [] if root else [config.ops_root(cfg)]
    root = root or config.code_root(cfg)
    cwds = process_cwds() if cwds is None else cwds
    launched = launch_references()
    wt, art = [], []
    for repo in repos(root, extra):
        wt += worktrees(repo, cwds, s["idle_days"], sizes=sizes, now=now, agent_idle_days=s["agent_idle_days"])
        art += artifacts(repo, cwds, s["build_idle_days"], sizes=sizes, now=now, launched=launched)
    return {"root": str(root), "settings": s, "disk": disk(), "worktrees": wt, "artifacts": art}


def reclaimable(rep: dict) -> int:
    return sum(r.get("bytes") or 0 for r in rep["worktrees"] + rep["artifacts"] if r["verdict"] == "SAFE")


def render(rep: dict, cache_rows: list[dict], sims: list[str], mem: list[tuple[str, int, int]]) -> str:
    d, s = rep["disk"], rep["settings"]
    home = str(pathlib.Path.home())
    short = lambda p: p.replace(home, "~", 1)
    L = [f"disk    {human(d['free'])} free of {human(d['total'])} ({d['free_fraction']:.0%})"]
    safe = [r for r in rep["worktrees"] + rep["artifacts"] if r["verdict"] == "SAFE"]
    L.append(f"safe    {human(reclaimable(rep))} in {len(safe)} item(s) — `teyla storage clean --apply` removes them"
             + ("" if s["auto_clean"] else "; `teyla config set storage.auto_clean=true` makes the daily routine do it"))
    L.append("")
    L.append(f"worktrees ({len(rep['worktrees'])}; SAFE = clean, on the remote, not in use, idle ≥ "
             f"{s['agent_idle_days']}d for agent-*, ≥ {s['idle_days']}d otherwise)")
    recent = [r for r in rep["worktrees"] if r["verdict"] == "KEEP" and r.get("only_recent")]
    for r in sorted((r for r in rep["worktrees"] if r not in recent), key=lambda r: (r["verdict"] != "SAFE", -(r.get("bytes") or 0))):
        L.append(f"  {r['verdict']:6} {human(r.get('bytes')):>6}  {short(r['path'])}  — {r['reason']}")
    if recent:
        size = sum(r.get("bytes") or 0 for r in recent) if rep["worktrees"] and recent[0].get("bytes") is not None else None
        L.append(f"  KEEP   {human(size):>6}  {len(recent)} more, clean and pushed but touched recently — SAFE once idle")
    L.append("")
    L.append(f"build output (git-ignored; SAFE = repo idle ≥ {s['build_idle_days']}d) and dependencies (REVIEW; ≥ {human(SHOW_MIN)} shown)")
    arts = [r for r in rep["artifacts"] if r["verdict"] == "SAFE" or r.get("bytes") is None or r["bytes"] >= SHOW_MIN]
    for r in sorted(arts, key=lambda r: (r["verdict"] != "SAFE", -(r.get("bytes") or 0))):
        L.append(f"  {r['verdict']:6} {human(r.get('bytes')):>6}  {short(r['path'])}  — {r['reason']}")
    if len(arts) < len(rep["artifacts"]):
        L.append(f"  {len(rep['artifacts']) - len(arts)} smaller not shown (--json lists them)")
    if cache_rows:
        L.append("")
        L.append("caches and stores (Teyla never deletes these; the command clears them)")
        for r in sorted(cache_rows, key=lambda r: -(r.get("bytes") or 0)):
            L.append(f"  {r['verdict']:6} {human(r.get('bytes')):>6}  {r['name']:24} {r['reason']}")
    L.append("")
    L.append("memory")
    if sims:
        L.append(f"  {len(sims)} simulator(s) booted: {', '.join(sims)}")
        if len(sims) > 1:
            L.append("  → each runs a full iOS userland; xcrun simctl shutdown all   (or shut down the ones no session is using)")
    for name, rss, n in mem:
        L.append(f"  {human(rss):>6}  {n:3}× {name}")
    return "\n".join(L)


# --- clean ----------------------------------------------------------------------------

def _log(line: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as f:
            f.write(f"{_dt.datetime.now().isoformat(timespec='seconds')} {line}\n")
    except OSError:
        pass


def rescue(worktree: str, main: str) -> None:
    """Append the worktree's `.teyla/corrections.jsonl` lines the main checkout lacks."""
    src = pathlib.Path(worktree, RESCUE)
    if not src.is_file():
        return
    dst = pathlib.Path(main, RESCUE)
    have = set(dst.read_text(errors="replace").splitlines()) if dst.is_file() else set()
    new = [l for l in src.read_text(errors="replace").splitlines() if l.strip() and l not in have]
    if new:
        dst.parent.mkdir(parents=True, exist_ok=True)
        lead = "\n" if dst.is_file() and dst.stat().st_size and not dst.read_bytes().endswith(b"\n") else ""
        with dst.open("a") as fh:
            fh.write(lead + "\n".join(new) + "\n")


def _remove_worktree(r: dict) -> tuple[int, str]:
    # The scan may be minutes old (du ran in between): decide again, on fresh facts.
    cwds = process_cwds()
    rc, out = _git(r["main"], "worktree", "list", "--porcelain")
    listed = _parse_worktrees(out) if rc == 0 else []
    me = next((w for w in listed if w.get("worktree") == r["path"]), None)
    if me is None:
        return 1, "no longer a registered worktree"
    a = assess(r["path"], cwds, r["limit"], others=[w["worktree"] for w in listed if w.get("worktree") != r["path"]],
               locked=bool(me.get("locked")))
    if a["why"]:
        return 1, "changed since the scan: " + "; ".join(a["why"])
    try:
        rescue(r["path"], r["main"])
    except OSError as e:
        return 1, f"could not keep {RESCUE}: {e}"
    # No --force: git refuses a tree with changes the checks above missed.
    return _git(r["main"], "worktree", "remove", r["path"], timeout=600)


def _remove_build(r: dict) -> tuple[int, str]:
    rel = os.path.relpath(r["path"], r["main"])
    if os.path.islink(r["path"]):
        return 1, "is a symlink"
    if _git(r["main"], "check-ignore", "-q", rel)[0] != 0:
        return 1, "no longer git-ignored"
    rc, top = _git(r["path"], "rev-parse", "--show-toplevel")
    if rc != 0 or os.path.realpath(top.strip()) != os.path.realpath(r["main"]):
        return 1, "belongs to another repository"
    rc, tracked = _git(r["main"], "ls-files", "--", rel)
    if rc != 0 or tracked.strip():
        return 1, "git tracks files inside it"
    for dirpath, dirnames, filenames in os.walk(r["path"]):
        if ".git" in dirnames or ".git" in filenames:
            return 1, f"holds a git repository ({os.path.relpath(dirpath, r['path'])})"
    try:
        shutil.rmtree(r["path"])
        return 0, ""
    except OSError as e:
        return 1, str(e)


def clean(rep: dict, apply: bool = False) -> list[str]:
    out = []
    for r in rep["worktrees"] + rep["artifacts"]:
        if r["verdict"] != "SAFE":
            continue
        if r.get("bytes") is None:
            r["bytes"] = du(r["path"])  # sized here, not in the scan: only what goes is measured
        size = human(r.get("bytes"))
        if not apply:
            out.append(f"would remove {size:>6}  {r['path']}")
            continue
        rc, msg = _remove_worktree(r) if r["kind"] == "worktree" else _remove_build(r)
        if rc == 0:
            out.append(f"removed {size:>6}  {r['path']}")
            _log(f"removed {r.get('bytes') or 0} {r['kind']} {r['path']}")
        else:
            out.append(f"kept             {r['path']}: {msg.strip()[:200]}")
    return out


# --- doctor ---------------------------------------------------------------------------

def doctor_checks(cfg: dict | None = None) -> list[dict]:
    """Cheap: free space, and how many worktrees are finished — no sizes."""
    out = []
    d = disk()
    if d["free_fraction"] < LOW_FREE_FRACTION or d["free"] < LOW_FREE_BYTES:
        out.append({"level": "WARN", "name": "storage:disk", "detail": f"{human(d['free'])} free ({d['free_fraction']:.0%})",
                    "fix": "teyla storage   (what is safe to remove, and the command for the rest)"})
    else:
        out.append({"level": "OK", "name": "storage:disk", "detail": f"{human(d['free'])} free ({d['free_fraction']:.0%})", "fix": None})
    s = settings(cfg)
    rep = scan(sizes=False, cfg=cfg)
    n = sum(1 for r in rep["worktrees"] if r["verdict"] == "SAFE")
    if n >= 5 and not s["auto_clean"]:
        out.append({"level": "WARN", "name": "storage:worktrees",
                    "detail": f"{n} worktree(s) are finished (clean, on the remote, idle ≥ {s['agent_idle_days']}d agent / {s['idle_days']}d session)",
                    "fix": "teyla storage clean --apply   (or: teyla config set storage.auto_clean=true)"})
    elif n:
        out.append({"level": "INFO", "name": "storage:worktrees", "detail": f"{n} finished worktree(s)"
                    + ("; the daily routine removes them" if s["auto_clean"] else ""), "fix": "teyla storage clean --apply"})
    return out


# --- CLI ------------------------------------------------------------------------------

def cmd_storage(args):
    cfg = config.load()
    if args.action == "clean":
        if args.auto and not settings(cfg)["auto_clean"]:
            return 0
        rep = scan(sizes=False, cfg=cfg)
        lines = clean(rep, apply=args.apply or args.auto)
        if not (args.quiet and not lines):
            for line in lines or ["nothing is safe to remove"]:
                print(line)
            if not (args.apply or args.auto) and lines:
                print(f"dry run: {human(reclaimable(rep))} — `teyla storage clean --apply` removes these")
        return 0
    sizes = not args.no_sizes
    rep = scan(sizes=sizes, cfg=cfg)
    cache_rows = caches(sizes=sizes)
    sims, mem = booted_simulators(), memory_by_app()
    if args.json:
        rep["caches"] = cache_rows; rep["simulators_booted"] = sims
        rep["memory"] = [{"name": n, "rss": b, "count": c} for n, b, c in mem]
        rep["reclaimable"] = reclaimable(rep)
        print(json.dumps(rep, indent=2))
    else:
        print(render(rep, cache_rows, sims, mem))
    return 0


def register(sp):
    q = sp.add_parser("storage", help="what agent work holds on disk and in RAM, and removing the part that is safe to")
    q.set_defaults(fn=cmd_storage)
    q.add_argument("action", nargs="?", choices=["report", "clean"], default="report")
    q.add_argument("--json", action="store_true")
    q.add_argument("--no-sizes", action="store_true", help="report: skip `du` (fast; verdicts only)")
    q.add_argument("--apply", action="store_true", help="clean: remove the SAFE rows (default: dry run)")
    q.add_argument("--auto", action="store_true", help="clean: apply only if storage.auto_clean is true; silent otherwise (the daily routine)")
    q.add_argument("--quiet", action="store_true", help="clean: print nothing when nothing was removed")
    return q

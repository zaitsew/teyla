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
  no process has its working directory inside it, and it is not locked. It goes with
  `git worktree remove` — never `rm` — and without `--force`, so git refuses anything the
  check missed. The branch is kept.
- **a build directory** (`build`, `.build`, `.next`, `dist`, `target`, `DerivedData`, …) is
  SAFE when git ignores it and its repo has been idle for `build_idle_days`. It is output
  the next build writes again.

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


def process_cwds() -> list[str]:
    """The working directory of every process this user can see. A directory some process
    sits in is in use, whatever git says about it."""
    try:
        r = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return sorted({os.path.realpath(line[1:]) for line in r.stdout.splitlines() if line.startswith("n/")})


def _in_use(path: str, cwds: list[str]) -> bool:
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


def worktrees(repo: pathlib.Path, cwds: list[str], idle_days: int, sizes: bool = True,
              now: float | None = None, agent_idle_days: int | None = None) -> list[dict]:
    """Every linked worktree of `repo` (the main checkout is not one), with a verdict."""
    rc, out = _git(repo, "worktree", "list", "--porcelain")
    if rc != 0:
        return []
    rows = []
    for w in _parse_worktrees(out)[1:]:
        path = w.get("worktree")
        if not path:
            continue
        row = {"kind": "worktree", "repo": repo.name, "main": str(repo), "path": path,
               "branch": str(w.get("branch", "")).removeprefix("refs/heads/") or "(detached)"}
        if w.get("prunable") or not os.path.isdir(path):
            row.update(verdict="SAFE", reason="directory is gone; only git's record of it is left",
                       action="prune", bytes=0)
            rows.append(row)
            continue
        gitdir = ""
        try:
            gitdir = pathlib.Path(path, ".git").read_text().split("gitdir:", 1)[1].strip()
        except (OSError, IndexError):
            pass
        idle = _idle_days(path, os.path.join(gitdir, "index"), os.path.join(gitdir, "HEAD"),
                          os.path.join(gitdir, "logs", "HEAD"), now=now)
        _, st = _git(path, "status", "--porcelain")
        dirty = len([l for l in st.splitlines() if l.strip()])
        _, on_remote = _git(path, "branch", "-r", "--contains", "HEAD")
        pushed = bool(on_remote.strip())
        limit = agent_idle_days if agent_idle_days is not None and is_agent_worktree(path) else idle_days
        why = []
        if w.get("locked"):
            why.append("locked")
        if dirty:
            why.append(f"{dirty} uncommitted change(s)")
        if not pushed:
            why.append("HEAD is on no remote branch")
        if _in_use(path, cwds):
            why.append("a process is working in it")
        recent = idle < limit
        if recent:
            why.append(f"touched {idle:.1f}d ago (< {limit}d)")
        row.update(idle_days=round(idle, 1), dirty=dirty, pushed=pushed, only_recent=recent and len(why) == 1,
                   verdict="KEEP" if why else "SAFE",
                   reason="; ".join(why) or f"clean, on the remote, idle {idle:.0f}d",
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


def artifacts(repo: pathlib.Path, cwds: list[str], build_idle_days: int, sizes: bool = True,
              now: float | None = None) -> list[dict]:
    rows = []
    idle = repo_idle_days(repo, now=now)
    # A session in <repo>/.claude/worktrees/x is working in its own tree, not in this checkout.
    own = os.path.realpath(repo / ".claude" / "worktrees") + os.sep
    in_use = _in_use(str(repo), [c for c in cwds if not c.startswith(own)])
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
        elif in_use:
            why.append("a process is working in the repo")
        elif idle < build_idle_days:
            why.append(f"repo active {idle:.1f}d ago (< {build_idle_days}d)")
        verdict = "SAFE" if not why else ("REVIEW" if d.name in DEPENDENCIES else "KEEP")
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
    wt, art = [], []
    for repo in repos(root, extra):
        wt += worktrees(repo, cwds, s["idle_days"], sizes=sizes, now=now, agent_idle_days=s["agent_idle_days"])
        art += artifacts(repo, cwds, s["build_idle_days"], sizes=sizes, now=now)
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


def clean(rep: dict, apply: bool = False) -> list[str]:
    out = []
    for r in rep["worktrees"] + rep["artifacts"]:
        if r["verdict"] != "SAFE":
            continue
        if r.get("bytes") is None and r.get("action") != "prune":
            r["bytes"] = du(r["path"])  # sized here, not in the scan: only what goes is measured
        size = human(r.get("bytes"))
        if not apply:
            out.append(f"would remove {size:>6}  {r['path']}")
            continue
        if r["kind"] == "worktree" and r["action"] == "prune":
            rc, msg = _git(r["main"], "worktree", "prune")
        elif r["kind"] == "worktree":
            # No --force: if anything changed since the scan, git refuses and the tree stays.
            rc, msg = _git(r["main"], "worktree", "remove", r["path"], timeout=600)
        else:
            rc2, _ = _git(r["main"], "check-ignore", "-q", os.path.relpath(r["path"], r["main"]))
            if rc2 != 0:
                out.append(f"skipped  {r['path']}: no longer git-ignored"); continue
            try:
                shutil.rmtree(r["path"]); rc, msg = 0, ""
            except OSError as e:
                rc, msg = 1, str(e)
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

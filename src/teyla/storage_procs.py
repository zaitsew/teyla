"""`teyla storage procs` — dev processes that an agent session left behind in a folder that is gone.

    teyla storage procs [--json]               one line per orphan: pid, RSS, age, command, why
    teyla storage procs --kill [--dry]         SIGTERM them, SIGKILL the ones that stay; --dry only reports

Agents start `xcodebuild`, `swift-build`, `next dev`, `vite`, `python -m http.server` and the like
inside a throwaway worktree or a temp folder, then the worktree is removed and the process keeps
running, holding hundreds of megabytes. A process is an *orphan* only when ALL of this holds:

- it belongs to the current user and has no terminal (`tty` is `??`): nothing a person is looking at;
- its command line matches `storage.orphan_patterns` (regexes; default: Xcode/SwiftPM builds, node,
  npm/pnpm/yarn/bun/deno, vite/next, `-m http.server`, supabase);
- it has run at least `storage.orphan_min_age_min` minutes (default 30);
- it is not this process or one of its ancestors;
- `lsof` could say where it sits, and its working directory, or a path on its command line, lies in
  a folder that agents create and that no longer exists: `~/.worktrees/<repo>/<branch>`,
  `<repo>/.claude/worktrees/<name>`, the first folder below `/tmp`, `/private/tmp` or `$TMPDIR`, or
  below a root in `storage.orphan_roots`. When `lsof` or `ps` fails, nothing is an orphan.

`--kill` signals each process only after checking again that the pid still runs the same command
since the same start time, so a recycled pid is never signalled. SIGTERM first, up to 10 s of grace,
then SIGKILL for the ones that are still the same process. The optional sims agent runs
`storage procs --kill --quiet` every 10 minutes when `storage.orphan_kill = true`.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
import re
import subprocess
import time
from typing import Callable

from . import storage

DEFAULT_PATTERNS = (
    r"(^|/)(xcodebuild|swift-build|swift-frontend|swift-test|swiftc)(\s|$)",
    r"XCBBuildService|SWBBuildService",
    r"(^|/)(node|npm|npx|pnpm|yarn|bun|deno|vite|supabase)(\s|$)",
    r"next-server|\bnext (dev|start)\b",
    r"-m http\.server",
)
GRACE_STEPS = 20          # x 0.5 s between SIGTERM and SIGKILL
PS_FORMAT = "pid=,ppid=,uid=,tty=,rss=,etime=,lstart=,command="
LSTART_WORDS = 5          # "Thu Oct  8 12:00:00 2026"
CLAUDE_WORKTREE = re.compile(r"^(.*?/\.claude/worktrees/[^/]+)(?:/|$)")
NO_TTY = {"??", "?", "-"}


def settings(cfg: dict | None = None) -> dict:
    patterns = storage.conf_list(cfg, "orphan_patterns") or list(DEFAULT_PATTERNS)
    return {"patterns": patterns,
            "min_age_min": storage.conf_int(cfg, "orphan_min_age_min", 30),
            "roots": storage.conf_list(cfg, "orphan_roots"),
            "kill": storage._truthy(storage._conf(cfg, "orphan_kill"))}


# --- the machine, behind runners tests replace ---------------------------------------------

def run_command(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """(exit code, stdout). 127 when the tool is missing, 124 on a timeout."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError:
        return 127, ""
    return r.returncode, r.stdout


@dataclasses.dataclass
class Ctx:
    run: Callable = run_command
    kill: Callable = os.kill
    sleep: Callable = time.sleep
    uid: int = dataclasses.field(default_factory=os.getuid)
    self_pid: int = dataclasses.field(default_factory=os.getpid)
    home: pathlib.Path = dataclasses.field(default_factory=pathlib.Path.home)
    tmpdir: str = dataclasses.field(default_factory=lambda: os.environ.get("TMPDIR", ""))


# --- reading ps and lsof ---------------------------------------------------------------------

def parse_etime(text: str) -> int | None:
    """`[[dd-]hh:]mm:ss` in seconds; None when it is not that."""
    m = re.fullmatch(r"(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+)", text.strip())
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def parse_ps(text: str) -> list[dict]:
    """Rows of `ps -axo pid=,ppid=,uid=,tty=,rss=,etime=,lstart=,command=`; malformed lines are dropped."""
    rows = []
    for line in text.splitlines():
        parts = line.split(None, 6 + LSTART_WORDS)
        if len(parts) < 6 + LSTART_WORDS + 1:
            continue
        pid, ppid, uid, tty, rss, etime = parts[:6]
        age = parse_etime(etime)
        if not (pid.isdigit() and ppid.isdigit() and uid.isdigit() and rss.isdigit()) or age is None:
            continue
        rows.append({"pid": int(pid), "ppid": int(ppid), "uid": int(uid), "tty": tty, "rss_kb": int(rss),
                     "age_s": age, "lstart": " ".join(parts[6:6 + LSTART_WORDS]), "command": parts[6 + LSTART_WORDS].strip()})
    return rows


def list_processes(ctx: Ctx) -> list[dict] | None:
    rc, out = ctx.run(["ps", "-axo", PS_FORMAT])
    rows = parse_ps(out) if rc == 0 else []
    return rows or None


def lookup(ctx: Ctx, pid: int) -> dict | None:
    """The current ps row of one pid; None when there is no such process."""
    rc, out = ctx.run(["ps", "-o", PS_FORMAT, "-p", str(pid)])
    rows = [r for r in parse_ps(out) if r["pid"] == pid] if rc in (0, 1) else []
    return rows[0] if rows else None


def working_dirs(ctx: Ctx, pids: list[int]) -> dict[int, str] | None:
    """{pid: cwd} from one `lsof` call. None when lsof could not answer."""
    if not pids:
        return {}
    rc, out = ctx.run(["lsof", "-a", "-d", "cwd", "-Fn", "-p", ",".join(str(p) for p in pids)], 120)
    if rc in (124, 127) or not out.strip():
        return None
    cwds, pid = {}, None
    for line in out.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n/") and pid is not None:
            cwds.setdefault(pid, line[1:])
    return cwds


def ancestors(rows: list[dict], pid: int) -> set[int]:
    parent = {r["pid"]: r["ppid"] for r in rows}
    out, cur = {pid}, pid
    while cur in parent and parent[cur] not in out and parent[cur] > 0:
        cur = parent[cur]
        out.add(cur)
    return out


# --- which folders count ---------------------------------------------------------------------

def _aliases(path: str) -> list[str]:
    """macOS spells /tmp and /var as /private/tmp and /private/var; both are the same folder."""
    path = path.rstrip("/")
    if not path:
        return []
    return [path, path.removeprefix("/private") if path.startswith("/private/") else "/private" + path]


def roots(cfg: dict | None, ctx: Ctx) -> list[tuple[str, int]]:
    """(root, depth): an agent's folder is the `depth` path components below the root."""
    out: list[tuple[str, int]] = [(a, 2) for a in _aliases(str(ctx.home / ".worktrees"))]
    flat = ["/tmp", ctx.tmpdir] + [os.path.expanduser(r) for r in storage.conf_list(cfg, "orphan_roots")]
    for r in flat:
        out += [(a, 1) for a in _aliases(r)]
    return out


def agent_folder(path: str, rts: list[tuple[str, int]]) -> str | None:
    """The folder an agent made that `path` is inside, or None when `path` is somewhere else."""
    if not path.startswith("/"):
        return None
    m = CLAUDE_WORKTREE.match(path)
    if m:
        return m.group(1)
    for root, depth in rts:
        if path.startswith(root + "/"):
            parts = [p for p in path[len(root) + 1:].split("/") if p]
            if len(parts) >= depth:
                return root + "/" + "/".join(parts[:depth])
    return None


def why_orphan(cwd: str | None, command: str, rts: list[tuple[str, int]]) -> str:
    """The reason this process sits in a folder that is gone, or '' when it does not."""
    seen = set()
    if cwd:
        folder = agent_folder(cwd, rts)
        if folder and storage._gone(folder):
            return f"cwd {cwd} is gone"
        seen.add(cwd)
    for path in re.findall(r"/[^\s\"'=:,;]+", command):
        folder = agent_folder(path, rts)
        if folder and folder not in seen and storage._gone(folder):
            return f"names a deleted path {folder}"
        if folder:
            seen.add(folder)
    return ""


# --- finding ---------------------------------------------------------------------------------

def find(cfg: dict | None = None, ctx: Ctx | None = None) -> dict:
    """{"orphans": [row, ...], "error": str | None}. Each row: pid, ppid, rss_kb, age_s, lstart,
    command, cwd, reason. A failed ps or lsof gives no orphans and an error."""
    ctx = ctx or Ctx()
    s = settings(cfg)
    procs = list_processes(ctx)
    if procs is None:
        return {"orphans": [], "error": "could not list processes (ps failed)"}
    patterns, bad = [], []
    for p in s["patterns"]:
        try:
            patterns.append(re.compile(p))
        except re.error:
            bad.append(p)
    skip = ancestors(procs, ctx.self_pid)
    cands = [r for r in procs
             if r["uid"] == ctx.uid and r["tty"] in NO_TTY and r["pid"] not in skip and r["pid"] > 1
             and r["age_s"] >= s["min_age_min"] * 60 and any(rx.search(r["command"]) for rx in patterns)]
    err = f"ignored invalid storage.orphan_patterns: {bad}" if bad else None
    if not cands:
        return {"orphans": [], "error": err}
    cwds = working_dirs(ctx, [r["pid"] for r in cands])
    if cwds is None:
        return {"orphans": [], "error": "could not read working directories (lsof failed)"}
    rts, out = roots(cfg, ctx), []
    for r in cands:
        cwd = cwds.get(r["pid"])
        if cwd is None:   # lsof did not name this process: nothing is known about where it sits
            continue
        reason = why_orphan(cwd, r["command"], rts)
        if reason:
            out.append({**{k: r[k] for k in ("pid", "ppid", "rss_kb", "age_s", "lstart", "command")}, "cwd": cwd, "reason": reason})
    out.sort(key=lambda r: -r["rss_kb"])
    return {"orphans": out, "error": err}


def total_rss(orphans: list[dict]) -> int:
    """Bytes."""
    return sum(r["rss_kb"] for r in orphans) * 1024


# --- killing ---------------------------------------------------------------------------------

def _same(ctx: Ctx, row: dict) -> bool:
    """The pid still runs this process: same start time and command, not a recycled pid."""
    now = lookup(ctx, row["pid"])
    return now is not None and now["lstart"] == row["lstart"] and now["command"] == row["command"]


def _label(r: dict) -> str:
    return f"pid {r['pid']} ({storage.human(r['rss_kb'] * 1024)}) {short(r['command'], 60)}"


def short(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n - 1] + "…"


def reap(cfg: dict | None = None, dry: bool = False, ctx: Ctx | None = None, found: dict | None = None) -> dict:
    """SIGTERM every orphan, give them 10 s, SIGKILL the ones that are still the same process.
    Returns the lines describing what was (or, with dry, would be) done, and the RSS freed (bytes)."""
    ctx = ctx or Ctx()
    found = found or find(cfg, ctx)
    rows, lines, freed, killed = found["orphans"], [], 0, []
    if found["error"] and not rows:
        return {"lines": [found["error"]], "killed": [], "freed": 0, "orphans": rows, "error": found["error"]}
    if dry:
        lines = [f"would kill {_label(r)} — {r['reason']}" for r in rows]
        return {"lines": lines, "killed": [], "freed": 0, "orphans": rows, "error": found["error"]}
    pending = []
    for r in rows:
        if not _same(ctx, r):
            lines.append(f"skipped {_label(r)}: it is gone or the pid was reused")
            continue
        try:
            ctx.kill(r["pid"], 15)
            pending.append(r)
        except ProcessLookupError:
            killed.append((r, "exited"))
        except OSError as e:
            lines.append(f"could not signal {_label(r)}: {e}")
    for _ in range(GRACE_STEPS):
        if not any(lookup(ctx, r["pid"]) for r in pending):
            break
        ctx.sleep(0.5)
    for r in pending:
        if not _same(ctx, r):                      # exited (or the pid already belongs to someone else)
            killed.append((r, "terminated"))
            continue
        try:
            ctx.kill(r["pid"], 9)
            killed.append((r, "killed with SIGKILL"))
        except ProcessLookupError:
            killed.append((r, "terminated"))
        except OSError as e:
            lines.append(f"could not kill {_label(r)}: {e}")
    for r, how in killed:
        freed += r["rss_kb"] * 1024
        lines.append(f"{how} {_label(r)} — {r['reason']}")
        storage._log(f"procs {how} pid {r['pid']} {short(r['command'], 120)}")
    return {"lines": lines, "killed": [r["pid"] for r, _ in killed], "freed": freed, "orphans": rows, "error": found["error"]}


# --- CLI ---------------------------------------------------------------------------------------

def render(found: dict, home: str | None = None) -> list[str]:
    rows = found["orphans"]
    home = home or str(pathlib.Path.home())
    if not rows:
        return [found["error"] or "no orphan processes"]
    out = [f"{len(rows)} orphan process(es), {storage.human(total_rss(rows))} RSS — their worktree or temp folder is gone"]
    for r in rows:
        age = r["age_s"]
        age_s = f"{age // 86400}d" if age >= 86400 else (f"{age // 3600}h" if age >= 3600 else f"{age // 60}m")
        out.append(f"  {r['pid']:>6} {storage.human(r['rss_kb'] * 1024):>6} {age_s:>4}  {short(r['command'], 80)}")
        out.append(f"           {r['reason'].replace(home, '~')}")
    if found["error"]:
        out.append(found["error"])
    return out


def cmd_procs(args, cfg: dict) -> int:
    ctx = Ctx()
    if getattr(args, "kill", False):
        res = reap(cfg, dry=getattr(args, "dry", False), ctx=ctx)
        if args.json:
            print(json.dumps(res, indent=2))
            return 0
        stamp = time.strftime("%F %T")
        for line in res["lines"] if args.quiet else res["lines"] or ["no orphan processes"]:
            print(f"{stamp} {line}")
        if res["killed"] and not args.quiet:
            print(f"{stamp} freed about {storage.human(res['freed'])} RSS")
        return 0
    found = find(cfg, ctx)
    if args.json:
        print(json.dumps(found, indent=2))
    elif not (args.quiet and not found["orphans"]):
        for line in render(found):
            print(line)
    return 0

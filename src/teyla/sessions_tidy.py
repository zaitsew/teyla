"""`teyla sessions` — archive the AI sessions where nothing is needed from the owner.

The Claude desktop app archives a session after 7 idle days, including one that ends on a question to
the owner: 27 of the 40 open questions in `teyla asks` sat in the archive. This is the inverse step: it
archives only a session that waits on nothing. `teyla asks` already knows which ones wait, and this
module reuses its collectors and settle rules instead of re-reading questions itself.

    teyla sessions tidy [--idle-hours 24] [--json]    the plan: what would be archived, and why the rest stays
    teyla sessions tidy --apply                       Codex: `codex archive <uuid>` for each candidate (mode on only)
    teyla sessions record <session-id>...             log Claude desktop sessions an agent archived with the app's tool
    teyla sessions undo [--last | <id-prefix>...]     Codex: `codex unarchive`; Claude: prints the ids to unarchive
    teyla sessions log [--days 7] [--json]            what was archived, or would have been
    teyla sessions report                             the dry-week verdict
    teyla sessions mode [dry|on|off]                  show or set the mode (default dry)

A session is archived only when ALL of this holds (`docs/SESSIONS.md`):

1. it is not archived and has been idle for `--idle-hours`;
2. `teyla asks` has no ask for it that is not done: open, snoozed, muted and duplicate asks keep it;
3. it has no open PR, and every PR it names has a known state (unknown keeps it);
4. its worktree, if it still exists, is clean and its HEAD is on a remote branch (the app removes the
   worktree on archive);
5. Codex: an interactive session, not a `codex exec` run or a spawned agent.

State is `~/.teyla/sessions-tidy.json` (mode, dry_until) and the append-only `~/.teyla/sessions-tidy.jsonl`
(one row per archive, would-archive and undo). Both are private (mode 600). Nothing leaves the machine
except the PR lookup `teyla asks` already makes.
"""
from __future__ import annotations

import collections
import dataclasses
import datetime as dt
import json
import os
import pathlib
import re
import subprocess
import sys

from . import asks, backlog, registry
from .adapters import claude_code, codex, iter_jsonl, text_of
from .control import state

MODES = ("dry", "on", "off")
DEFAULT_IDLE_HOURS = 24.0
DRY_DAYS = 7
CODEX_MAX_DAYS = 120            # no Codex rollout older than this is looked at
GIT_TIMEOUT_S = 20
CODEX_TIMEOUT_S = 60
WOULD, ARCHIVED, UNARCHIVED = "would_archive", "archived", "unarchived"
ACTIONS = (WOULD, ARCHIVED, UNARCHIVED)
TRANSCRIPT_TAIL = 4 * 1024 * 1024


def state_path() -> pathlib.Path:
    return state.home() / "sessions-tidy.json"


def log_path() -> pathlib.Path:
    return state.home() / "sessions-tidy.jsonl"


def _now() -> float:
    return dt.datetime.now(dt.timezone.utc).timestamp()


def _iso(epoch: float) -> str:
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- mode and the log ---------------------------------------------------------------------------

def load_cfg() -> dict:
    try:
        d = json.loads(state_path().read_text())
    except (OSError, ValueError):
        d = {}
    d = d if isinstance(d, dict) else {}
    if d.get("mode") not in MODES:
        d["mode"] = "dry"
    return d


def save_cfg(cfg: dict) -> None:
    asks._atomic_write(state_path(), json.dumps(cfg, indent=1, sort_keys=True) + "\n")


def seed_dry_until(cfg: dict, now: float) -> dict:
    """The first run starts the dry week."""
    if not cfg.get("dry_until"):
        cfg["dry_until"] = (dt.datetime.fromtimestamp(now) + dt.timedelta(days=DRY_DAYS)).date().isoformat()
        save_cfg(cfg)
    return cfg


def read_log() -> list[dict]:
    rows = []
    try:
        for line in log_path().read_text().splitlines():
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict) and o.get("action") in ACTIONS and o.get("session"):
                rows.append(o)
    except OSError:
        pass
    return rows


def append_log(rows: list[dict]) -> None:
    if not rows:
        return
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode())
    finally:
        os.close(fd)


def _log_row(now: float, run: str, row: "Row", action: str, reason: str = "") -> dict:
    return {"ts": _iso(now), "run": run, "harness": row.harness, "session": row.session, "title": row.title,
            "product": row.product, "action": action, "reason": reason or row.reason}


def last_actions(rows: list[dict]) -> dict[str, dict]:
    last: dict[str, dict] = {}
    for r in rows:
        last[r["session"]] = r
    return last


# --- the machine, behind functions tests replace --------------------------------------------------

def git_out(args: list[str], cwd: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return p.returncode, p.stdout


def run_codex(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(["codex", *args], capture_output=True, text=True, timeout=CODEX_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return p.returncode, (p.stderr or p.stdout).strip()


# --- the plan -------------------------------------------------------------------------------------

@dataclasses.dataclass
class Row:
    harness: str          # claude-desktop | codex
    session: str          # desktop sessionId (local_...), Codex uuid
    title: str
    product: str
    idle_hours: float
    verdict: str          # archive | keep
    reason: str
    cli_session: str = ""

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["idle_hours"] = round(self.idle_hours, 1)
        return d


def waiting_keys(items: list) -> set[str]:
    """Session ids that `teyla asks` still lists: desktop sessionId and cliSessionId / Codex uuid."""
    keys: set[str] = set()
    for a in items:
        if a.status == "done":
            continue
        if a.session:
            keys.add(a.session)
        if a.link.startswith(asks.OPEN_LINK):
            keys.add(a.link[len(asks.OPEN_LINK):])
    return keys


def worktree_problem(path: str, git=None) -> str:
    """"" when the worktree is gone, or clean with its HEAD on a remote branch; else why not."""
    git = git or git_out
    if not path or not os.path.isdir(path):
        return ""
    rc, out = git(["status", "--porcelain"], path)
    if rc != 0 or out.strip():
        return "worktree has unpushed work"
    rc, out = git(["branch", "-r", "--contains", "HEAD"], path)
    if rc != 0 or not out.strip():
        return "worktree has unpushed work"
    return ""


def pr_problem(prs: list, now: float, fetch: bool, runner) -> str:
    urls = [str(p["url"]) for p in prs if isinstance(p, dict) and p.get("url")]
    if not urls:
        return ""
    try:
        states = backlog.pr_states(urls, now, runner=runner, fetch=fetch)
    except Exception:  # noqa: BLE001 — no answer is "unknown", and unknown keeps the session
        return "PR state unknown"
    seen = []
    for u in urls:
        s = states.get(backlog.canonical_pr_url(u))
        if not s:
            return "PR state unknown"
        seen.append(s["state"])
    return "open PR" if "OPEN" in seen else ""


def _desktop_row(d: dict, now: float, idle_hours: float, waiting: set[str], fetch: bool, runner, git, reg: dict) -> Row | None:
    if d.get("isArchived"):
        return None
    sid, cli = str(d.get("sessionId") or ""), str(d.get("cliSessionId") or "")
    if not sid:
        return None
    last = asks._epoch(d.get("lastActivityAt") or d.get("createdAt"))
    title = str(d.get("title") or "")
    cwd = d.get("cwd") or d.get("originCwd")
    product = registry.explain(cwd, session=(cli, sid), texts=(title, ""), reg=reg)[0]
    idle = (now - last) / 3600 if last else 0.0
    row = Row("claude-desktop", sid, asks.clip(title, asks.TITLE_MAX), product, idle, "keep", "", cli)
    if last is None:
        row.reason = "no activity time"
    elif idle < idle_hours:
        row.reason = "active recently"
    elif sid in waiting or (cli and cli in waiting):
        row.reason = "open ask"
    else:
        row.reason = (pr_problem(d.get("prs") or [], now, fetch, runner)
                      or worktree_problem(str(d.get("worktreePath") or ""), git))
    if not row.reason:
        row.verdict, row.reason = "archive", "nothing is waiting on you"
    return row


def _rollout_sid(path: str) -> str:
    m = re.match(r"rollout-\d{4}-\d\d-\d\dT\d\d-\d\d-\d\d-(.+)\.jsonl$", os.path.basename(path))
    return m.group(1) if m else os.path.basename(path)


def _codex_head(path: str) -> dict | None:
    """session_meta of an interactive rollout; None for `codex exec`, a spawned agent or a review run."""
    meta: dict = {}
    head = iter_jsonl(path)
    try:
        for n, o in enumerate(head):
            p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
            if o.get("type") == "session_meta":
                meta = p
                if asks._is_automation(p):
                    return None
            elif o.get("type") == "response_item" and p.get("type") == "message" and p.get("role") == "user":
                txt = asks._codex_user_text(p)
                if txt.startswith(asks._REVIEW_PROMPTS):
                    return None
                if txt and not txt.startswith("# AGENTS.md instructions"):
                    break
            if n > 40:
                break
    finally:
        head.close()
    return meta


def _codex_rows(now: float, idle_hours: float, waiting: set[str], reg: dict, root: str | None) -> list[Row]:
    root = codex.DEFAULT_ROOT if root is None else root
    if not root or not os.path.isdir(root):
        return []
    titles = codex._load_titles(codex.DEFAULT_INDEX)
    out = []
    for f in codex._rollouts(root, now - CODEX_MAX_DAYS * 86400):
        try:
            mtime = os.stat(f).st_mtime
            meta = _codex_head(f)
        except OSError:
            continue
        if meta is None:
            continue
        sid = str(meta.get("session_id") or meta.get("id") or "") or _rollout_sid(f)
        title = titles.get(sid) or ""
        idle = (now - mtime) / 3600
        product = registry.explain(meta.get("cwd"), session=sid, texts=(title, ""), reg=reg)[0]
        row = Row("codex", sid, asks.clip(title, asks.TITLE_MAX), product, idle, "keep", "")
        if idle < idle_hours:
            row.reason = "active recently"
        elif sid in waiting:
            row.reason = "open ask"
        else:
            row.verdict, row.reason = "archive", "nothing is waiting on you"
        out.append(row)
    return out


def plan(now: float | None = None, idle_hours: float = DEFAULT_IDLE_HOURS, *, fetch: bool = True, runner=None,
         git=None, desktop: str | None = None, codex_root: str | None = None) -> list[Row]:
    """Every unarchived desktop session and interactive Codex session with a verdict, archive rows first."""
    now = _now() if now is None else now
    desktop = asks.desktop_root() if desktop is None else desktop
    sessions = asks._desktop_sessions(desktop) if os.path.isdir(desktop) else []
    oldest = min((asks._epoch(d.get("lastActivityAt") or d.get("createdAt")) or now
                  for d in sessions if not d.get("isArchived")), default=now)
    days = max(asks.DEFAULT_DAYS, int((now - oldest) / 86400) + 2)
    items = asks.collect(days, now, desktop=desktop, codex_root=codex_root, fetch=fetch, runner=runner)
    waiting = waiting_keys(items)
    reg = registry.load()
    rows = [r for d in sessions if (r := _desktop_row(d, now, idle_hours, waiting, fetch, runner, git, reg))]
    rows += _codex_rows(now, idle_hours, waiting, reg, codex_root)
    rows.sort(key=lambda r: (r.verdict != "archive", -r.idle_hours))
    return rows


def payload(cfg: dict, rows: list[Row], idle_hours: float) -> dict:
    return {"mode": cfg["mode"], "dry_until": cfg.get("dry_until", ""), "idle_hours": idle_hours,
            "rows": [r.to_dict() for r in rows]}


def log_would_archive(rows: list[Row], now: float, run: str) -> int:
    """One would_archive row per session, until the session is archived or undone."""
    last = last_actions(read_log())
    new = [_log_row(now, run, r, WOULD) for r in rows
           if r.verdict == "archive" and (last.get(r.session) or {}).get("action") in (None, UNARCHIVED)]
    append_log(new)
    return len(new)


# --- output ---------------------------------------------------------------------------------------

def render_plan(cfg: dict, rows: list[Row]) -> str:
    mode = cfg["mode"]
    head = {"dry": f"mode dry (dry week until {cfg.get('dry_until', '?')}): nothing is archived",
            "on": "mode on", "off": "mode off: the plan is shown, nothing is archived"}[mode]
    todo = [r for r in rows if r.verdict == "archive"]
    lines = [head, ""]
    if todo:
        verb = "would archive" if mode != "on" else "to archive"
        lines.append(f"{len(todo)} {verb}:")
        for r in todo:
            lines.append(f"  {r.harness:<14} {r.session[:20]:<20} {r.idle_hours / 24:5.1f}d  {r.product or '-':<14} {r.title}")
    else:
        lines.append("nothing to archive")
    kept = collections.Counter(r.reason for r in rows if r.verdict == "keep")
    if kept:
        lines += ["", f"kept {sum(kept.values())}: " + ", ".join(f"{n} {why}" for why, n in kept.most_common())]
    return "\n".join(lines)


# --- commands -------------------------------------------------------------------------------------

def cmd_tidy(args, now: float | None = None) -> int:
    now = _now() if now is None else now
    cfg = load_cfg()
    if cfg["mode"] == "dry":
        cfg = seed_dry_until(cfg, now)
    idle = DEFAULT_IDLE_HOURS if args.idle_hours is None else args.idle_hours
    if args.apply and cfg["mode"] != "on":
        msg = (f"refused: mode is {cfg['mode']}; run `teyla sessions report` after the dry week "
               "(until " + str(cfg.get("dry_until", "?")) + "), then `teyla sessions mode on`")
        print(msg, file=sys.stderr)
        return 2
    rows = plan(now, idle, fetch=not getattr(args, "no_fetch", False))
    run = _iso(now)
    if cfg["mode"] == "dry":
        log_would_archive(rows, now, run)
    done: list[Row] = []
    failed: list[tuple[Row, str]] = []
    if args.apply:
        for r in rows:
            if r.verdict == "archive" and r.harness == "codex":
                rc, err = run_codex(["archive", r.session])
                if rc == 0:
                    done.append(r)
                else:
                    failed.append((r, err))
        append_log([_log_row(now, run, r, ARCHIVED) for r in done])
    if args.json:
        out = payload(cfg, rows, idle)
        out["archived"] = [r.session for r in done]
        print(json.dumps(out, indent=1))
    else:
        print(render_plan(cfg, rows))
        for r in done:
            print(f"archived {r.session}")
        for r, err in failed:
            print(f"codex archive failed for {r.session}: {err}", file=sys.stderr)
        if args.apply:
            todo = [r.session for r in rows if r.verdict == "archive" and r.harness != "codex"]
            if todo:
                print("Claude desktop: archive_session each, then `teyla sessions record " + " ".join(todo) + "`")
    return 1 if failed else 0


def cmd_record(args, now: float | None = None) -> int:
    now = _now() if now is None else now
    if not args.words:
        print("usage: teyla sessions record <session-id>...", file=sys.stderr)
        return 64
    desktop = asks.desktop_root()
    known = asks._desktop_sessions(desktop) if os.path.isdir(desktop) else []
    reg = registry.load()
    run, rows, code = _iso(now), [], 0
    for sid in args.words:
        hit = [d for d in known if str(d.get("sessionId") or "") == sid] or \
              [d for d in known if str(d.get("sessionId") or "").startswith(sid)]
        if len(hit) > 1:
            print(f"{sid}: matches {len(hit)} sessions; give more of the id", file=sys.stderr)
            code = 1
            continue
        d = hit[0] if hit else {}
        full = str(d.get("sessionId") or sid)
        title = asks.clip(str(d.get("title") or ""), asks.TITLE_MAX)
        product = registry.explain(d.get("cwd") or d.get("originCwd"), session=(d.get("cliSessionId"), full),
                                   texts=(title, ""), reg=reg)[0] if d else ""
        row = Row("claude-desktop", full, title, product, 0.0, "archive", "archived by an agent",
                  str(d.get("cliSessionId") or ""))
        rows.append(_log_row(now, run, row, ARCHIVED))
        print(f"recorded {full}" + ("" if d else " (not in the desktop metadata)"))
    append_log(rows)
    return code


def cmd_undo(args, now: float | None = None) -> int:
    now = _now() if now is None else now
    log = read_log()
    live = [r for r in last_actions(log).values() if r["action"] == ARCHIVED]
    if args.last:
        runs = [r["run"] for r in log if r["action"] == ARCHIVED]
        pick = [r for r in live if runs and r.get("run") == runs[-1]] if runs else []
    elif args.words:
        pick = []
        for pre in args.words:
            hit = [r for r in live if r["session"].startswith(pre) or (pre in r["session"])]
            if len(hit) != 1:
                print(f"{pre}: " + ("no archived session matches" if not hit else f"matches {len(hit)}; give more of the id"),
                      file=sys.stderr)
                return 1
            pick += hit
    else:
        print("usage: teyla sessions undo --last | <id-prefix>...", file=sys.stderr)
        return 64
    if not pick:
        print("nothing to undo")
        return 0
    run, out, claude, code = _iso(now), [], [], 0
    for r in pick:
        row = Row(r["harness"], r["session"], r.get("title", ""), r.get("product", ""), 0.0, "keep", "undone")
        if r["harness"] == "codex":
            rc, err = run_codex(["unarchive", r["session"]])
            if rc != 0:
                print(f"codex unarchive failed for {r['session']}: {err}", file=sys.stderr)
                code = 1
                continue
            print(f"unarchived {r['session']}")
        else:
            claude.append(r["session"])
        out.append(_log_row(now, run, row, UNARCHIVED, "undone"))
    append_log(out)
    if claude:
        print("Claude desktop: call unarchive_session for " + " ".join(claude))
    return code


def window(days: float, now: float) -> list[dict]:
    cut = _iso(now - days * 86400)
    return [r for r in read_log() if str(r.get("ts", "")) >= cut]


def cmd_log(args, now: float | None = None) -> int:
    now = _now() if now is None else now
    rows = window(args.days if args.days is not None else 7, now)
    if args.json:
        print(json.dumps(rows, indent=1))
        return 0
    if not rows:
        print("nothing logged in this window")
        return 0
    for r in rows:
        print(f"{r['ts']}  {r['action']:<13} {r['harness']:<14} {str(r['session'])[:20]:<20} {r.get('title', '')}  ({r.get('reason', '')})")
    return 0


def _ts(row: dict) -> float:
    return asks._epoch(row.get("ts")) or 0.0


def _claude_human_after(cli_id: str, cwd: str, ts: float, projects: str | None) -> bool:
    projects = claude_code.DEFAULT_ROOT if projects is None else projects
    path = asks.find_transcript(cli_id, cwd, projects) if os.path.isdir(projects) else None
    if not path:
        return False
    try:
        for o in iter_jsonl(path, tail_bytes=TRANSCRIPT_TAIL):
            if o.get("type") != "user" or o.get("isMeta") or o.get("isSidechain"):
                continue
            when = asks._epoch(o.get("timestamp"))
            if when is None or when <= ts:
                continue
            content = (o.get("message") or {}).get("content") if isinstance(o.get("message"), dict) else None
            if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                continue
            txt = text_of(content).strip()
            if txt and asks._is_reply(txt):
                return True
    except OSError:
        pass
    return False


def _codex_human_after(sid: str, ts: float, root: str | None) -> bool:
    for path in codex.locate(sid, root):
        try:
            for o in iter_jsonl(path, tail_bytes=TRANSCRIPT_TAIL):
                p = o.get("payload") if isinstance(o.get("payload"), dict) else {}
                if o.get("type") != "response_item" or p.get("type") != "message" or p.get("role") != "user":
                    continue
                when = asks._epoch(o.get("timestamp"))
                if when is None or when <= ts:
                    continue
                clean = asks._codex_user_text(p)
                if clean and not clean.startswith("# AGENTS.md instructions") and "<INSTRUCTIONS>" not in clean[:300] \
                        and asks._is_reply(clean):
                    return True
        except OSError:
            continue
    return False


def mistakes(rows: list[dict], desktop: str | None = None, projects: str | None = None,
             codex_root: str | None = None) -> list[dict]:
    """Logged sessions that got a human prompt after they were logged: the rule archived one it should not have."""
    desktop = asks.desktop_root() if desktop is None else desktop
    meta = {str(d.get("sessionId")): d for d in (asks._desktop_sessions(desktop) if os.path.isdir(desktop) else [])}
    out, seen = [], set()
    for r in rows:
        sid = r["session"]
        if sid in seen or r["action"] == UNARCHIVED:
            continue
        seen.add(sid)
        ts = _ts(r)
        if r["harness"] == "codex":
            bad = _codex_human_after(sid, ts, codex_root)
        else:
            d = meta.get(sid)
            last = asks._epoch((d or {}).get("lastActivityAt")) or 0.0
            bad = bool(d) and last > ts and _claude_human_after(
                str(d.get("cliSessionId") or ""), d.get("cwd") or "", ts, projects)
        if bad:
            out.append(r)
    return out


def cmd_report(args, now: float | None = None) -> int:
    now = _now() if now is None else now
    rows = window(args.days if args.days is not None else 30, now)
    flagged = [r for r in rows if r["action"] in (WOULD, ARCHIVED)]
    sessions = {r["session"]: r for r in flagged}
    bad = mistakes(flagged)
    cfg = load_cfg()
    by_h = collections.Counter(r["harness"] for r in sessions.values())
    by_p = collections.Counter(r.get("product") or "-" for r in sessions.values())
    n_would = sum(1 for r in sessions.values() if r["action"] == WOULD)
    n_done = len(sessions) - n_would
    print(f"sessions tidy report (mode {cfg['mode']}, dry_until {cfg.get('dry_until') or '-'})")
    print(f"would_archive {n_would} · archived {n_done}")
    if sessions:
        print("by harness: " + ", ".join(f"{h} {n}" for h, n in by_h.most_common()))
        print("by product: " + ", ".join(f"{p} {n}" for p, n in by_p.most_common()))
    print(f"mistakes: {len(bad)}")
    for r in bad:
        print(f"  - {r.get('title') or r['session']} ({r['harness']}, {r['session'][:20]}): got a human prompt after {r['ts']}")
    if not sessions:
        print("no rows yet: run `teyla sessions tidy` for a few days first")
    elif not bad:
        print("verdict: 0 mistakes: recommend `teyla sessions mode on`")
    else:
        print("verdict: keep dry: " + "; ".join(r.get("title") or r["session"] for r in bad))
    return 0


def cmd_mode(args, now: float | None = None) -> int:
    now = _now() if now is None else now
    cfg = load_cfg()
    if not args.words:
        print(f"mode {cfg['mode']}" + (f" · dry_until {cfg['dry_until']}" if cfg.get("dry_until") else
                                       " · the dry week starts at the first `teyla sessions tidy`"))
        return 0
    want = args.words[0]
    if want not in MODES or len(args.words) > 1:
        print("usage: teyla sessions mode [dry|on|off]", file=sys.stderr)
        return 64
    cfg["mode"] = want
    if want == "dry":
        cfg["dry_until"] = ""
        cfg = seed_dry_until(cfg, now)
    save_cfg(cfg)
    print(f"mode {want}" + (f" · dry_until {cfg['dry_until']}" if want == "dry" else ""))
    return 0


ACTIONS_CMD = {"tidy": cmd_tidy, "record": cmd_record, "undo": cmd_undo, "log": cmd_log, "report": cmd_report,
               "mode": cmd_mode}


def cmd_sessions(args) -> int:
    words = list(args.words or [])
    if not words or words[0] not in ACTIONS_CMD:
        print("usage: teyla sessions tidy|record|undo|log|report|mode  (docs/SESSIONS.md)", file=sys.stderr)
        return 64
    args.words = words[1:]
    return ACTIONS_CMD[words[0]](args)


def add_args(q) -> None:
    """The extra words and flags of `teyla sessions` (it already lists sessions; `tidy` and friends come after it).
    `--days` is the parser's own: an int."""
    q.add_argument("words", nargs="*", help="tidy | record <session-id>... | undo [--last|<id-prefix>...] | log | report | mode [dry|on|off]; none lists sessions")
    q.add_argument("--idle-hours", type=float, help=f"tidy: idle at least this long (default {DEFAULT_IDLE_HOURS:g})")
    q.add_argument("--apply", action="store_true", help="tidy: archive the Codex candidates (mode on only)")
    q.add_argument("--last", action="store_true", help="undo: everything the last archive run did")
    q.add_argument("--json", action="store_true", help="tidy, log: JSON")
    q.add_argument("--no-fetch", action="store_true", help="tidy: read PR states from caches only")

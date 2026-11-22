"""`teyla dispatch` starts new work, `teyla say` corrects a running session. See docs/DISPATCH.md.

    teyla dispatch <product> [--harness codex|claude] [--model M] [--json] [--dry] -- <text>
    teyla say <ref> [--json] [--dry] -- <text>

`dispatch` never touches the main checkout. It fetches, cuts a worktree at
~/.worktrees/<repo>/task/<yyyymmdd-hhmm>-<slug> from origin/<default branch>, and starts one
detached session there: Codex through `codex-lane` (which waits for the machine guard), or a
Claude background session behind `teyla load --wait`. The free text is always its own argv entry,
after `--`; no shell ever sees it.

`say` never resumes a live session: two writers on one transcript. A live interactive Codex session
takes `codex queue` (delivered after the current turn). Everything else gets the text on the
clipboard and the session's link opened.

Every subprocess goes through `answer.run` or `spawn` and every path is a parameter, so tests
replace those and never start `git`, `codex` or `claude`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid

from . import answer, config, state
from .control import state as control_state

CODEX_MODEL = "gpt-6.1-sol"
CLAUDE_MODEL = "claude-sonnet-5-5"
DEFAULT_PERMISSION_MODE = "acceptEdits"
HEADER = ("Task from the owner via Teyla. Work only in this worktree and branch. Follow the repo's rules. "
          "End with the session-end card.")
SETTLE_S = 2.0                   # how long a fresh process may take to die before it counts as started
GIT_TIMEOUT = 120
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}")
SLUG_MAX = 40
MIN_PREFIX = 6


# --- plumbing ---------------------------------------------------------------------------------

def worktrees_root() -> pathlib.Path:
    return pathlib.Path.home() / ".worktrees"


def dispatch_dir() -> pathlib.Path:
    return control_state.home() / "dispatch"


def journal_path() -> pathlib.Path:
    return control_state.home() / "dispatch.jsonl"


def codex_lane() -> str:
    """The lane wrapper: it pins the Standard tier and waits for the machine guard."""
    return shutil.which("codex-lane") or str(pathlib.Path.home() / "ops" / "bin" / "codex-lane")


def git(repo: str | pathlib.Path, *args: str, timeout: int = GIT_TIMEOUT) -> tuple[int, str]:
    return answer.run(["git", "-C", str(repo), *args], timeout=timeout)


def spawn(cmd: list[str], cwd: str, log: str, settle_s: float = SETTLE_S) -> tuple[int | None, int, str]:
    """Start `cmd` on its own (new session, stdin closed, output to the 0600 `log`).
    Returns (pid, exit code or 0, last output line): a command that dies inside `settle_s` reports its
    exit code, one still running reports 0."""
    try:
        p = pathlib.Path(log)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "ab") as out:
            proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                    start_new_session=True)
    except FileNotFoundError:
        return None, 127, f"{cmd[0]}: not found"
    except OSError as e:
        return None, 126, str(e)
    end = time.monotonic() + settle_s
    while time.monotonic() < end:
        code = proc.poll()
        if code is not None:
            return proc.pid, code, answer._tail(pathlib.Path(log).read_text(errors="replace"))
        time.sleep(0.1)
    return proc.pid, 0, answer._tail(pathlib.Path(log).read_text(errors="replace"))


def append_journal(row: dict) -> None:
    """One JSON line per dispatch, owner-only: it holds the task text's log path and the worktree."""
    p = journal_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "ab") as f:
        f.write((json.dumps(row, sort_keys=True) + "\n").encode())


# --- dispatch ---------------------------------------------------------------------------------

def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:SLUG_MAX].strip("-")
    return s or "task"


def branch_name(text: str, now: dt.datetime) -> str:
    return f"task/{now.strftime('%Y%m%d-%H%M')}-{slug(text)}"


def resolve_repo(product: str, index: dict | None = None) -> tuple[pathlib.Path | None, str]:
    """A product name from the repo index, or a path to a git checkout."""
    if "/" in product or product.startswith(("~", ".")):
        path = pathlib.Path(product).expanduser()
        if path.is_dir() and (path / ".git").exists():
            return path.resolve(), ""
        return None, f"{product}: not a git checkout"
    index = state.repo_index() if index is None else index
    for name, path in index.items():
        if name == product:
            return pathlib.Path(path), ""
    low = [(n, p) for n, p in index.items() if n.lower() == product.lower()]
    if len(low) == 1:
        return pathlib.Path(low[0][1]), ""
    return None, f"unknown product {product!r}; known: {', '.join(sorted(index)[:12]) or 'none'}"


def default_branch(repo: pathlib.Path) -> str | None:
    """The remote's default branch, from local refs only (a fetch has already refreshed them)."""
    code, out = git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and out.startswith("origin/") and len(out) > len("origin/"):
        return out[len("origin/"):]
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{name}")[0] == 0:
            return name
    return None


def prompt_for(text: str) -> str:
    return HEADER + "\n\n" + text


def codex_cmd(wt: str, prompt: str, model: str, common_dir: str | None) -> list[str]:
    # `codex exec` has no --full-auto in this build: it never asks for approval, so the sandbox is the
    # only gate. The worktree's git data lives in the main repo's .git, outside the worktree.
    cmd = [codex_lane(), "-m", model, "-C", wt, "-s", "workspace-write"]
    if common_dir:
        cmd += ["--add-dir", common_dir]
    return cmd + ["--", prompt]


def claude_cmd(prompt: str, model: str, mode: str, name: str) -> list[str]:
    # the prompt starts with HEADER, so it can never be read as a flag
    inner = ["claude", "--bg", "--model", model, "--permission-mode", mode, "--name", name, prompt]
    # the wait for a free slot comes first; "$@" keeps the prompt out of the shell's parsing
    return ["sh", "-c", 'teyla load --wait --kind lane && exec "$@"', "teyla-dispatch", *inner]


def permission_mode() -> str:
    mode = ((config.load().get("dispatch") or {}).get("claude_permission_mode") or DEFAULT_PERMISSION_MODE)
    return mode if mode in answer.PERMISSION_MODES else DEFAULT_PERMISSION_MODE


def describe(cmd: list[str], cwd: str | None = None) -> str:
    c = " ".join(shlex.quote(x) for x in cmd)
    return f"(cd {shlex.quote(cwd)} && {c})" if cwd else c


def dispatch(product: str, text: str, harness: str = "codex", model: str | None = None, dry: bool = False,
             now: dt.datetime | None = None, index: dict | None = None, wt_root: pathlib.Path | None = None,
             settle_s: float = SETTLE_S) -> dict:
    base = {"ok": False, "via": "", "detail": "", "id": "", "worktree": "", "link": ""}
    via = "codex-exec" if harness == "codex" else "claude-bg"
    if config.safe_mode():
        base["detail"] = "refused: safe mode is on, dispatch starts model sessions"
        return base
    if harness not in ("codex", "claude"):
        base["detail"] = f"unknown harness {harness!r}; use codex or claude"
        return base
    model = model or (CODEX_MODEL if harness == "codex" else CLAUDE_MODEL)
    if not MODEL_RE.fullmatch(model):
        base["detail"] = f"refused: {model!r} is not a model name"
        return base
    if not text.strip():
        base["detail"] = "nothing to do: the task text is empty"
        return base
    repo, err = resolve_repo(product, index)
    if repo is None:
        base["detail"] = err
        return base
    now = now or dt.datetime.now()
    wt_root = worktrees_root() if wt_root is None else wt_root
    if not dry:
        fcode, fout = git(repo, "fetch", "--quiet", "origin")
        fetch_note = "" if fcode == 0 else f" (fetch failed: {fout or fcode}; used the last known origin)"
    else:
        fetch_note = ""
    default = default_branch(repo)
    if default is None:
        base["detail"] = f"{repo}: cannot tell the default branch (no origin/HEAD, origin/main or origin/master)"
        return base
    branch = branch_name(text, now)
    wt = wt_root / repo.name / branch
    if wt.exists():
        base["detail"] = f"refused: {wt} already exists"
        return base
    rid = str(uuid.uuid4())
    log = str(dispatch_dir() / f"{rid}.log")
    prompt = prompt_for(text)
    code, gdir = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = gdir if code == 0 and gdir.startswith("/") else None
    if harness == "codex":
        cmd = codex_cmd(str(wt), prompt, model, common)
    else:
        cmd = claude_cmd(prompt, model, permission_mode(), f"{repo.name}: {branch.split('/', 1)[1]}")
    add = ["git", "-C", str(repo), "worktree", "add", "--no-track", "-b", branch, str(wt), f"origin/{default}"]
    link = "file://" + str(wt)
    if dry:
        plan = describe(add) + "  &&  " + describe(cmd, str(wt))
        return {"ok": True, "via": via, "detail": "would run: " + plan, "id": rid, "worktree": str(wt),
                "link": link, "branch": branch, "dry": True}
    code, out = git(repo, "worktree", "add", "--no-track", "-b", branch, str(wt), f"origin/{default}")
    if code != 0:
        base["detail"] = f"git worktree add failed: {out or code}"
        return base
    pid, code, out = spawn(cmd, str(wt), log, settle_s=settle_s)
    if code != 0:
        base.update(detail=f"{via} did not start: {out or f'exit {code}'}; the worktree {wt} is kept",
                    id=rid, worktree=str(wt), link=link)
        return base
    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    append_journal({"id": rid, "product": repo.name, "harness": harness, "worktree": str(wt), "branch": branch,
                    "started": started, "pid": pid, "log": log})
    detail = f"started on {branch} from origin/{default}; log {log}{fetch_note}"
    return {"ok": True, "via": via, "detail": detail, "id": rid, "worktree": str(wt), "link": link}


# --- say --------------------------------------------------------------------------------------

def session_id(row: dict) -> str:
    """The id inside a running row's link: codex://threads/<uuid>, or the epitaxy link's local_<id>."""
    return str(row.get("link") or "").rstrip("/").rsplit("/", 1)[-1]


def find_running(ref: str, rows: list[dict]) -> tuple[dict | None, str]:
    """A running row by its `id`, by its session id, or by a prefix of either (at least 6 characters)."""
    ref = ref.strip()
    if not ref:
        return None, "no session given"
    keys = [(str(r.get("id") or ""), session_id(r), r) for r in rows]
    hits = [r for i, s, r in keys if ref in (i, s, r.get("link"))]
    if not hits and len(ref) >= MIN_PREFIX:
        hits = [r for i, s, r in keys if i.startswith(ref) or s.startswith(ref)]
    if len(hits) == 1:
        return hits[0], ""
    if hits:
        return None, f"{ref!r} matches {len(hits)} running sessions; give more characters"
    return None, f"no running session {ref!r}"


def say_plan(row: dict, text: str) -> dict:
    sid = session_id(row)
    if row.get("harness") == "codex" and sid:
        return {"via": "codex-queue", "cmd": ["codex", "queue", "--thread", sid, f"--message={text}"], "cwd": None,
                "detail": "queued; delivered after the current turn"}
    link = str(row.get("link") or "")
    if link.startswith(answer.OPENABLE):
        return {"via": "opened", "cmd": ["open", link], "cwd": None, "copy": True}
    return {}


def say(ref: str, text: str, dry: bool = False, now: float | None = None, rows: list[dict] | None = None) -> dict:
    base = {"ok": False, "via": "", "detail": "", "id": ""}
    rows = state.running(time.time() if now is None else now) if rows is None else rows
    row, err = find_running(ref, rows)
    if row is None:
        base["detail"] = err
        return base
    rid = str(row.get("id") or session_id(row))
    step = say_plan(row, text)
    if not step:
        return {**base, "id": rid, "detail": "this session has no link to open and no queue to use"}
    if dry:
        return {"ok": True, "via": step["via"], "detail": "would run: " + answer.describe(step), "id": rid,
                "dry": True}
    ok, detail = answer.execute(step, text)
    return {"ok": ok, "via": step["via"] if ok else "", "detail": detail, "id": rid}


# --- CLI --------------------------------------------------------------------------------------

def _emit(res: dict, args, done: str) -> int:
    if args.json:
        print(json.dumps(res))
    else:
        print(res["detail"] if args.dry or not res["ok"] else f"{done} {res['id']} via {res['via']}: {res['detail']}",
              file=sys.stdout if res["ok"] else sys.stderr)
    return 0 if res["ok"] else 1


def cmd_dispatch(args) -> int:
    words = list(args.words or [])
    if len(words) < 2 or not " ".join(words[1:]).strip():
        print("usage: teyla dispatch <product> [--harness codex|claude] [--model M] [--json] [--dry] -- <text>",
              file=sys.stderr)
        return 64
    res = dispatch(words[0], " ".join(words[1:]).strip(), harness=args.harness, model=args.model, dry=args.dry)
    return _emit(res, args, "dispatched")


def cmd_say(args) -> int:
    words = list(args.words or [])
    if len(words) < 2 or not " ".join(words[1:]).strip():
        print("usage: teyla say <ref> [--json] [--dry] -- <text>", file=sys.stderr)
        return 64
    res = say(words[0], " ".join(words[1:]).strip(), dry=args.dry)
    return _emit(res, args, "sent to")


def register(sp):
    q = sp.add_parser("dispatch", help="start new work in a fresh worktree (Codex by default)")
    q.set_defaults(fn=cmd_dispatch)
    q.add_argument("words", nargs="*", help="<product> <text...>")
    q.add_argument("--harness", choices=("codex", "claude"), default="codex")
    q.add_argument("--model", default=None, help=f"default {CODEX_MODEL} (codex) or {CLAUDE_MODEL} (claude)")
    q.add_argument("--json", action="store_true")
    q.add_argument("--dry", action="store_true", help="print the plan, change nothing")
    q = sp.add_parser("say", help="correct a running session: queue into Codex, or copy and open the window")
    q.set_defaults(fn=cmd_say)
    q.add_argument("words", nargs="*", help="<ref> <text...>")
    q.add_argument("--json", action="store_true")
    q.add_argument("--dry", action="store_true", help="print the command it would run, run nothing")
    return q

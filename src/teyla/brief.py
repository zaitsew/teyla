"""`teyla brief` — the sprint contract: a goal, a slice and a budget, enforced at the Agent call.

A build session starts with `teyla brief <product> --goal ... --usd 120 --hours 8`. The contract is a
TOML file under `<teyla dir>/briefs/<product>/<YYYY-MM-DD-HHMM>.toml`, and `briefs/<product>/active`
names the one in force. Budget is Teyla's list-price estimate (API list price) for the session plus all
its subagents; subscription use and billed spend differ.

A hook cannot stop a running worker, so the brake sits where new work starts. `teyla brief --hook` is
a Claude Code PreToolUse hook for the Agent and Task tools:

- under 80% of the budget (dollars or hours, whichever is further along): exit 0;
- 80% to 100%: exit 2, "start no new lane";
- 100% and over: exit 2, "checkpoint now": running lanes finish their commit, the lead writes the
  handoff and asks the owner one question.

The hook binds each session it sees to the active contract (a contract opened with `--session ID` is
pinned: it counts only its listed sessions and never auto-binds another), sums `session_cost` over the bound
sessions, logs every refusal to `briefs/refusals.tsv`, and fails open on any error: a broken gate must
not stop work. `teyla brief <product> --raise-usd N --reason "..."` is the owner's override.
Nothing here leaves the machine.

Wire it in `~/.claude/settings.json` (docs/COMMANDS.md has the same block):

    {"hooks": {"PreToolUse": [{"matcher": "Agent|Task",
      "hooks": [{"type": "command", "command": "teyla brief --hook", "timeout": 5}]}]}}
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import subprocess
import sys
import tomllib

from . import config

WARN_PCT = 80.0
HOOK_TOOLS = ("Agent", "Task")
LIST_PRICE_SENTENCE = ("Budget = Teyla's list-price estimate (API list price) for this session plus all its "
                       "subagents. Subscription use and billed spend differ.")
WARN_MSG = "sprint budget at {pct:.0f}% (${spend:.2f} of ${usd:g}, {hrs:.1f}h of {hours:g}h): start no new lane. Finish the running ones."
STOP_MSG = ("sprint budget spent ({pct:.0f}%): checkpoint now — let running lanes finish their commit, "
            "write the handoff, and ask the owner one question.")


def briefs_dir() -> pathlib.Path:
    return config.TEYLA_DIR / "briefs"  # call time: tests and a moved home redirect TEYLA_DIR


# ---------------------------------------------------------------- product resolution

def _git(cwd: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=2)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def repo_root(cwd: str) -> pathlib.Path:
    """The main repo a cwd belongs to, worktrees resolved to the repo they were cut from."""
    cwd = os.path.abspath(cwd)
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if common:
        p = pathlib.Path(common)
        if p.name == ".git":
            return p.parent
    m = re.search(r"^(.*?)/\.claude/worktrees/[^/]+", cwd)
    if m:
        return pathlib.Path(m.group(1))
    m = re.search(r"/\.worktrees/([^/]+)/[^/]+", cwd)
    if m:
        return pathlib.Path(m.group(1))  # only the name matters when git could not answer
    top = _git(cwd, "rev-parse", "--show-toplevel")
    return pathlib.Path(top or cwd)


def product_of(cwd: str) -> str:
    """`[product] name` in the repo's teyla.toml, else the repo directory name."""
    root = repo_root(cwd)
    try:
        name = tomllib.loads((root / "teyla.toml").read_text()).get("product", {}).get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception:
        pass
    return root.name


# ---------------------------------------------------------------- contract files

def _safe(product: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "-", product).strip("-") or "product"


def _q(s) -> str:
    return json.dumps(str(s), ensure_ascii=False)


def _scalar(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return _q(v)


def dumps(c: dict) -> str:
    lines = []
    for k, v in c.items():
        if k == "raises":
            continue
        if isinstance(v, list):
            lines.append(f"{k} = [" + ", ".join(_scalar(x) for x in v) + "]")
        else:
            lines.append(f"{k} = {_scalar(v)}")
    for r in c.get("raises", []):
        lines.append("\n[[raises]]")
        lines += [f"{k} = {_scalar(v)}" for k, v in r.items()]
    return "\n".join(lines) + "\n"


def _write(path: pathlib.Path, c: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dumps(c))
    os.replace(tmp, path)


def active_path(product: str) -> pathlib.Path | None:
    d = briefs_dir() / _safe(product)
    try:
        name = (d / "active").read_text().strip()
    except OSError:
        return None
    return d / name if name else None


def load_active(product: str) -> tuple[pathlib.Path, dict] | None:
    p = active_path(product)
    if p is None or not p.is_file():
        return None
    return p, tomllib.loads(p.read_text())


def split_sessions(values) -> list[str]:
    """Session ids from repeated flags, each possibly a comma list; order kept, duplicates dropped."""
    out: list[str] = []
    for v in values or []:
        for part in str(v).split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return out


def blocking_active(product: str) -> tuple[pathlib.Path, dict] | None:
    """The active contract of a product when it is unclosed and not expired (twice its hours old), else None."""
    try:
        found = load_active(product)
        if not found or found[1].get("closed"):
            return None
        c = found[1]
        age_h = (_now() - _parse(c["started"])).total_seconds() / 3600.0
        if age_h >= 2 * float(c.get("hours") or 0):
            return None
        return found
    except Exception:
        return None


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse(ts: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def create(product: str, *, goal: str = "", slice_: str = "", platform: str = "", usd: float, hours: float,
           gates: list[str] | None = None, repo: str = ".", sessions: list[str] | None = None,
           replace: bool = True) -> tuple[pathlib.Path, dict]:
    """Open a contract. With replace=False, raise ActiveContract when another is active, unclosed and unexpired.
    The check, the close of the previous one and the activation run under one exclusive per-product lock."""
    import fcntl
    d = briefs_dir() / _safe(product)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".open.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not replace:
            old = blocking_active(product)
            if old:
                raise ActiveContract(old)
        return _create_locked(d, product, goal, slice_, platform, usd, hours, gates, repo, sessions)


class ActiveContract(Exception):
    def __init__(self, found):
        super().__init__(found[0].name)
        self.path, self.contract = found


def _create_locked(d, product, goal, slice_, platform, usd, hours, gates, repo, sessions):
    prev = load_active(product) if active_path(product) else None
    if prev:
        pc = prev[1]
        pc["closed"] = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
        _write(prev[0], pc)
    now = _now()
    path = d / (now.strftime("%Y-%m-%d-%H%M") + ".toml")
    n = 2
    while path.exists():  # two contracts in one minute
        path = d / (now.strftime("%Y-%m-%d-%H%M") + f"-{n}.toml")
        n += 1
    c = {"product": product, "started": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "goal": goal, "slice": slice_,
         "platform": platform, "usd": float(usd), "hours": float(hours), "gates": list(gates or []),
         "repo": str(pathlib.Path(repo).expanduser().resolve()), "sessions": list(sessions or [])}
    if sessions:
        c["pinned"] = True  # the hook never auto-binds a session that is not listed
    _write(path, c)
    (d / "active").write_text(path.name + "\n")
    return path, c


# ---------------------------------------------------------------- spend and percent

def standing(c: dict) -> dict:
    """spend, elapsed hours and the percent used of a contract (the further of dollars and hours)."""
    from .session_cost import session_cost
    spend = 0.0
    for sid in c.get("sessions") or []:
        spend += session_cost(str(sid))["usd"]
    return _standing_from(c, spend)


def _standing_from(c: dict, spend: float) -> dict:
    usd, hours = float(c.get("usd") or 0), float(c.get("hours") or 0)
    hrs = max(0.0, (_now() - _parse(c["started"])).total_seconds() / 3600.0)
    parts = []
    if usd > 0:
        parts.append(spend / usd)
    if hours > 0:
        parts.append(hrs / hours)
    return {"spend": spend, "hours_elapsed": hrs, "usd": usd, "hours": hours,
            "pct": 100.0 * max(parts or [0.0])}


def render(path: pathlib.Path, c: dict, st: dict) -> str:
    out = [f"Sprint contract: {c.get('product')} ({path.name})" + ("  [closed]" if c.get("closed") else ""),
           f"  goal      {c.get('goal') or '-'}", f"  slice     {c.get('slice') or '-'}",
           f"  platform  {c.get('platform') or '-'}", f"  budget    ${st['usd']:g} and {st['hours']:g}h",
           f"  spent     ${st['spend']:.2f} and {st['hours_elapsed']:.1f}h ({st['pct']:.0f}%)",
           f"  started   {c.get('started')}", f"  repo      {c.get('repo')}",
           f"  sessions  {len(c.get('sessions') or [])}" + ("  (pinned: only these count)" if c.get("pinned") else "")]
    for g in c.get("gates") or []:
        out.append(f"  gate      {g}")
    for r in c.get("raises") or []:
        out.append(f"  raised    +${r.get('usd')} by {r.get('by')} at {r.get('at')}: {r.get('reason')}")
    out += ["", "At 80% the lead starts no new lane. At 100% it checkpoints, lets running lanes finish their commit,",
            "and asks the owner one question.", LIST_PRICE_SENTENCE]
    return "\n".join(out)


# ---------------------------------------------------------------- the hook

def _log_refusal(product: str, sid: str, pct: float, spend: float, tool: str) -> None:
    try:
        d = briefs_dir()
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "refusals.tsv", "a") as fh:
            fh.write("\t".join([_now().strftime("%Y-%m-%dT%H:%M:%SZ"), product, sid, tool, f"{pct:.0f}", f"{spend:.2f}"]) + "\n")
    except OSError:
        pass


def bind(path: pathlib.Path, sid: str) -> dict:
    """Add `sid` to the contract's sessions under an exclusive lock, so two sessions binding at once both land."""
    import fcntl
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        c = tomllib.loads(path.read_text())
        sessions = [str(x) for x in c.get("sessions") or []]
        if sid not in sessions:
            sessions.append(sid)
            c["sessions"] = sessions
            _write(path, c)
        return c


def _expired_note(path: pathlib.Path, product: str, sid: str) -> str:
    """One stderr note per session that the contract has expired; "" after the first."""
    seen = path.with_suffix(".expired")
    try:
        if sid in seen.read_text().split():
            return ""
    except OSError:
        pass
    try:
        with open(seen, "a") as fh:
            fh.write(sid + "\n")
    except OSError:
        pass
    return f"sprint contract for {product} has expired: close it with `teyla brief {product} --close`.\n"


def hook(stdin_text: str) -> tuple[int, str]:
    """(exit code, stderr text). Any error answers (0, "")."""
    try:
        data = json.loads(stdin_text or "{}")
        tool = data.get("tool_name")
        if tool not in HOOK_TOOLS:
            return 0, ""
        cwd = data.get("cwd") or os.getcwd()
        product = product_of(cwd)
        found = load_active(product)
        if not found:
            return 0, ""
        path, c = found
        if c.get("closed"):
            return 0, ""
        sid = str(data.get("session_id") or "")
        sessions = [str(s) for s in c.get("sessions") or []]
        age_h = (_now() - _parse(c["started"])).total_seconds() / 3600.0
        if sid and sid not in sessions and c.get("pinned"):
            return 0, ""  # a pinned contract counts only its listed sessions
        if sid and sid not in sessions:
            if age_h >= 2 * float(c.get("hours") or 0):
                # Past the binding window: this session is not under the contract and passes.
                return 0, _expired_note(path, product, sid)
            c = bind(path, sid)
            sessions = [str(s) for s in c.get("sessions") or []]
        from .session_cost import session_cost
        spend = 0.0
        for s in sessions:
            spend += session_cost(s, data.get("transcript_path") if s == sid else None)["usd"]
        st = _standing_from(c, spend)
        pct = st["pct"]
        if pct < WARN_PCT:
            return 0, ""
        _log_refusal(product, sid, pct, spend, str(tool))
        if pct < 100:
            return 2, WARN_MSG.format(pct=pct, spend=spend, usd=st["usd"], hrs=st["hours_elapsed"], hours=st["hours"]) + "\n"
        return 2, STOP_MSG.format(pct=pct) + "\n"
    except Exception:
        return 0, ""


# ---------------------------------------------------------------- command

def cmd_brief(args) -> int:
    if getattr(args, "hook", False):
        code, err = hook(sys.stdin.read())
        if err:
            sys.stderr.write(err)
        return code
    cwd = os.path.abspath(args.repo or ".")
    product = args.product or product_of(cwd)
    as_json = bool(getattr(args, "json", False))
    pin_ids = split_sessions(getattr(args, "session", None))
    add_ids = split_sessions(getattr(args, "add_session", None))
    creating = any([args.goal, args.slice, args.platform, args.usd is not None, args.hours is not None, args.gate])
    if args.raise_usd is not None:
        found = load_active(product)
        if not found:
            print(f"teyla brief: no active contract for {product}", file=sys.stderr)
            return 2
        if not args.reason:
            print("teyla brief: --raise-usd needs --reason", file=sys.stderr)
            return 2
        path, c = found
        c["usd"] = float(c["usd"]) + args.raise_usd
        who = os.environ.get("USER") or "owner"
        c.setdefault("raises", []).append({"at": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "by": who,
                                           "usd": float(args.raise_usd), "reason": args.reason})
        _write(path, c)
        print(f"{product}: budget raised by ${args.raise_usd:g} to ${c['usd']:g} ({args.reason})")
        return 0
    if add_ids:
        found = load_active(product)
        if not found:
            print(f"teyla brief: no active contract for {product}", file=sys.stderr)
            return 2
        if not found[1].get("pinned"):
            print(f"teyla brief: the active contract for {product} is not pinned (it auto-binds); "
                  "--add-session needs a contract opened with --session", file=sys.stderr)
            return 2
        for sid in add_ids:
            c = bind(found[0], sid)
        print(f"{product}: {len(add_ids)} session(s) added; {len(c['sessions'])} in the contract.")
        return 0
    if args.close:
        found = load_active(product)
        if not found:
            print(f"teyla brief: no active contract for {product}", file=sys.stderr)
            return 2
        path, c = found
        st = standing(c)
        c["closed"] = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
        _write(path, c)
        (path.parent / "active").unlink(missing_ok=True)
        print(f"{product}: contract closed at ${st['spend']:.2f} ({st['pct']:.0f}%).")
        return 0
    if creating:
        if args.usd is None or args.hours is None:
            print("teyla brief: a new contract needs --usd and --hours", file=sys.stderr)
            return 2
        try:
            path, c = create(product, goal=args.goal or "", slice_=args.slice or "", platform=args.platform or "",
                             usd=args.usd, hours=args.hours, gates=args.gate, repo=cwd, sessions=pin_ids,
                             replace=bool(getattr(args, "replace", False)))
        except ActiveContract as e:
            print(f"teyla brief: {product} already has an active contract ({e.path.name}: "
                  f"{e.contract.get('goal') or 'no goal'}). Close it with `teyla brief {product} --close`, "
                  "or open this one with --replace.", file=sys.stderr)
            return 1
        if not pin_ids:
            print("note: auto-binding counts every session of this product that starts a subagent. "
                  "To count only your own, pin it: add --session ID (repeatable), or --add-session ID later.",
                  file=sys.stderr)
    else:
        found = load_active(product)
        if not found:
            print(f"{product}: no active sprint contract. Start one: teyla brief {product} --goal ... --usd N --hours N")
            return 1
        path, c = found
    st = standing(c)
    if as_json:
        print(json.dumps({"path": str(path), "contract": c, "standing": st, "note": LIST_PRICE_SENTENCE}, indent=2))
    else:
        print(render(path, c, st))
    return 0


def register(sp):
    q = sp.add_parser("brief", help="the sprint contract: a goal, a slice and a budget, enforced at the Agent call")
    q.set_defaults(fn=cmd_brief)
    q.add_argument("product", nargs="?", help="product name (default: from --repo / the current directory)")
    q.add_argument("--goal"); q.add_argument("--slice"); q.add_argument("--platform")
    q.add_argument("--usd", type=float, help="budget in dollars at list price")
    q.add_argument("--hours", type=float, help="time budget in hours")
    q.add_argument("--gate", action="append", help="a gate the sprint must pass (repeatable)")
    q.add_argument("--repo", metavar="PATH", default=".")
    q.add_argument("--json", action="store_true")
    q.add_argument("--close", action="store_true", help="close the active contract")
    q.add_argument("--raise-usd", type=float, metavar="N", help="the owner's override: raise the dollar budget by N")
    q.add_argument("--reason", help="with --raise-usd: why")
    q.add_argument("--session", action="append", metavar="ID",
                   help="pin the contract to this session (repeatable, or a comma list): no other session is auto-bound")
    q.add_argument("--add-session", action="append", metavar="ID", help="add a session to the pinned active contract")
    q.add_argument("--replace", action="store_true", help="open a contract although another is active (it is closed)")
    q.add_argument("--hook", action="store_true", help="PreToolUse hook for Agent|Task (reads JSON on stdin)")
    return q

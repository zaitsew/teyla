"""`teyla remind` — a tiny dated to-do list for the things only a human can do, surfaced by
`teyla doctor` instead of living in some note nobody re-reads until it is overdue.

    teyla remind add "<what>" <YYYY-MM-DD> [--how "<the fix>"]   file one
    teyla remind list                                            everything, in the order filed
    teyla remind done <n>                                        clear the n-th (1-based, as listed)

Stored in `~/.teyla/reminders.toml` as an array of `[[reminder]]` tables — `what`, `due`
(ISO date) and an optional `how`, the command or step that clears it. `teyla doctor` turns
every reminder into a line of its own: OK while `due` is more than 30 days out, WARN once
inside that window, FIX once `due` has passed — `how` printed as the fix on the latter two.
A one-off fact like "the Apple Sign In client secret expires 2027-03-11" needs exactly
this — not a wiki page, not a calendar invite on a machine that is not always open — so it
comes back at the right time on its own, on the same channel every other pending fix
already surfaces on.
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import sys

from . import config

REMINDERS_PATH = config.TEYLA_DIR / "reminders.toml"

# Inside this many days of `due`, doctor WARNs; past `due`, it's a FIX regardless of how
# far past. 30 days matches the other "should not be a surprise" windows in the codebase
# (routine staleness, policy drift) — long enough to act without pressure, short enough
# that "due in 30 days" still means something.
WARN_WINDOW_DAYS = 30


def _esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def load(path: pathlib.Path | None = None) -> list[dict]:
    """Every reminder, in file order. A missing or unparseable file is an empty list —
    nothing is due, which is a fine answer to start from."""
    p = path or REMINDERS_PATH
    if not p.exists():
        return []
    import tomllib
    try:
        data = tomllib.loads(p.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return []
    out = []
    for r in data.get("reminder") or []:
        if isinstance(r, dict) and r.get("what") and r.get("due"):
            out.append({"what": str(r["what"]), "due": str(r["due"]), "how": str(r.get("how") or "")})
    return out


def save(reminders: list[dict], path: pathlib.Path | None = None) -> None:
    p = path or REMINDERS_PATH
    lines = ["# ~/.teyla/reminders.toml — dated to-dos surfaced by `teyla doctor`.", ""]
    for r in reminders:
        lines.append("[[reminder]]")
        lines.append(f'what = "{_esc(r["what"])}"')
        lines.append(f'due = "{_esc(r["due"])}"')
        if r.get("how"):
            lines.append(f'how = "{_esc(r["how"])}"')
        lines.append("")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines).rstrip("\n") + "\n")


def parse_due(due: str) -> _dt.date:
    """Raises ValueError with a message worth printing when `due` is not YYYY-MM-DD."""
    try:
        return _dt.date.fromisoformat(due)
    except ValueError:
        raise ValueError(f"bad date {due!r}; want YYYY-MM-DD") from None


def add(what: str, due: str, how: str = "", path: pathlib.Path | None = None) -> str:
    what = what.strip()
    if not what:
        return "nothing to remind: <what> is empty"
    try:
        parse_due(due)
    except ValueError as e:
        return str(e)
    reminders = load(path)
    reminders.append({"what": what, "due": due, "how": how.strip()})
    save(reminders, path)
    return f"added: {what} (due {due})"


def done(n: int, path: pathlib.Path | None = None) -> str:
    reminders = load(path)
    if not (1 <= n <= len(reminders)):
        return f"no reminder #{n}; {len(reminders)} present — see `teyla remind list`"
    gone = reminders.pop(n - 1)
    save(reminders, path)
    return f"done: {gone['what']}"


def days_until(due: str, today: _dt.date | None = None) -> int:
    return (parse_due(due) - (today or _dt.date.today())).days


def render_list(reminders: list[dict], today: _dt.date | None = None) -> str:
    if not reminders:
        return "no reminders."
    lines = []
    for i, r in enumerate(reminders, 1):
        d = days_until(r["due"], today)
        when = f"overdue by {-d}d" if d < 0 else ("due today" if d == 0 else f"in {d}d")
        line = f"{i}. {r['what']} — due {r['due']} ({when})"
        if r.get("how"):
            line += f" — {r['how']}"
        lines.append(line)
    return "\n".join(lines)


def due_checks(reminders: list[dict] | None = None, today: _dt.date | None = None) -> list[dict]:
    """One row per reminder, shaped for `doctor._check`: {level, name, detail, fix}. FIX
    once `due` has passed, `how` (or a note that none was recorded) as the fix; WARN inside
    the 30-day window, `how` as the fix; OK otherwise — tracked, but nothing to do yet, so
    the row still shows the reminder exists without asking for attention it doesn't need."""
    reminders = reminders if reminders is not None else load()
    out = []
    for r in reminders:
        try:
            d = days_until(r["due"], today)
        except ValueError:
            continue
        name = r["what"] if len(r["what"]) <= 40 else r["what"][:39] + "…"
        if d < 0:
            out.append({"level": "FIX", "name": name, "detail": f"was due {r['due']} ({-d}d overdue)",
                       "fix": r.get("how") or "no fix recorded — teyla remind list"})
        elif d <= WARN_WINDOW_DAYS:
            out.append({"level": "WARN", "name": name, "detail": f"due {r['due']} (in {d}d)",
                       "fix": r.get("how") or None})
        else:
            out.append({"level": "OK", "name": name, "detail": f"due {r['due']} (in {d}d, not yet due)",
                       "fix": None})
    return out


def cmd_remind(args):
    action = args.action
    if action == "add":
        if not args.arg1 or not args.arg2:
            print('usage: teyla remind add "<what>" <YYYY-MM-DD> [--how "<the fix>"]', file=sys.stderr)
            return 64
        result = add(args.arg1, args.arg2, how=getattr(args, "how", None) or "")
        print(result)
        return 1 if result.startswith(("bad date", "nothing to remind")) else 0
    if action == "list":
        print(render_list(load()))
        return 0
    if action == "done":
        if not args.arg1:
            print("usage: teyla remind done <n>", file=sys.stderr)
            return 64
        try:
            n = int(args.arg1)
        except ValueError:
            print(f"not a number: {args.arg1}", file=sys.stderr)
            return 64
        result = done(n)
        print(result)
        return 1 if result.startswith("no reminder") else 0
    return 1  # pragma: no cover — argparse choices already rule this out


def register(sp):
    q = sp.add_parser("remind", help="dated to-dos surfaced by `teyla doctor` — things only a human can do")
    q.set_defaults(fn=cmd_remind)
    q.add_argument("action", choices=["add", "list", "done"])
    q.add_argument("arg1", nargs="?", help='add: "<what>"; done: <n>')
    q.add_argument("arg2", nargs="?", help="add: <YYYY-MM-DD>")
    q.add_argument("--how", help='add: the fix, e.g. "run bash ~/.teyla/apple-client-secret.sh"')
    return q

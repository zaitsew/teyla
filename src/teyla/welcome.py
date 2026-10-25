"""What bare `teyla` prints: a welcome of at most 15 lines. It never fails and it never waits.

    T█ Teyla 0.31.0
    Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost
    and what's waiting on you, and fixes the waste. Nothing leaves your machine.

      $412   spent in the last 7 days        teyla spend
      3      questions waiting on you        teyla asks
      2      notes in your Inbox             teyla notes --inbox

    Next
      teyla start   Find where the money goes, and fix it one change at a time
      ...

Rules (docs/TODAY.md has the same list):

  - Sessions on the machine: the three numbers, each with the command that opens it. None: one line
    saying so, and `teyla start` first.
  - The first next command is `teyla start` until the person has applied or declined an offer (a
    change in ~/.teyla/changes.jsonl, or a finished `teyla start`). After that it is `teyla today`.
  - Nothing here is computed. Spend and questions come from the cache in `figures` (see there for how
    stale they can be); the notes are one small file. A cache that is missing or older than 10 minutes
    starts one background refresh. The call takes tens of milliseconds, not the minute a diagnosis takes.
"""
from __future__ import annotations

import sys
import textwrap

from . import __version__, figures
from .spend import _money
from .ui import Style, pad

MAX_LINES = 15
PROMISE = ("Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's "
           "waiting on you, and fixes the waste. Nothing leaves your machine.")
NO_SESSIONS = "No agent sessions found yet. Use Claude Code or Codex for a day, then run `teyla start`."

START = ("teyla start", "Find where the money goes, and fix it one change at a time")
TODAY = ("teyla today", "What waits on you, the Inbox and the week's spend")
SPEND = ("teyla spend", "What the last 7 days cost, and which part bought nothing")
DOCTOR = ("teyla doctor", "Check that Teyla can see your tools, with the fix for each gap")
HELP = ("teyla help", "Every command, in groups")


def next_commands(sessions: bool, onboarded: bool) -> list[tuple[str, str]]:
    """The three commands to try next. See the module docstring for the rule."""
    if not sessions:
        return [START, DOCTOR, HELP]
    if not onboarded:
        return [START, TODAY, HELP]
    return [TODAY, SPEND, HELP]


def _row(value: str, label: str, command: str, st: Style, role: str | None = None) -> str:
    v = st.paint(value, role) if role else value
    return "  " + pad(v, 10) + pad(label, 31) + st.command(command)


def numbers(st: Style, at: float | None = None) -> list[str]:
    """The three live numbers. Spend and questions from the cache, the Inbox read now."""
    at = figures.now() if at is None else at
    spend, spend_age = figures.cached("spend", at)
    qs, q_age = figures.cached("questions", at)
    if spend is None or qs is None or figures.stale(spend_age) or figures.stale(q_age):
        figures.spawn_refresh()
    from . import notes
    try:
        inbox = notes.counts()["inbox"]
    except Exception:  # noqa: BLE001 — a note file Teyla cannot read leaves the Inbox figure out
        inbox = None
    note = lambda age: ("  " + st.quiet(figures.age_note(age))) if figures.age_note(age) else ""
    rows = []
    if spend is None:
        rows.append(_row("...", "spent in the last 7 days", "counting now, ask again in a minute", st))
    else:
        rows.append(_row(_money(float(spend["this_week"])), "spent in the last 7 days", "teyla spend", st) + note(spend_age))
    if qs is None:
        rows.append(_row("...", "questions waiting on you", "counting now", st))
    else:
        n = int(qs["waiting"])
        rows.append(_row(str(n), "question waiting on you" if n == 1 else "questions waiting on you", "teyla asks", st,
                         "needs-you" if n else None) + note(q_age))
    if inbox is not None:
        rows.append(_row(str(inbox), "note in your Inbox" if inbox == 1 else "notes in your Inbox", "teyla notes --inbox", st,
                         "needs-you" if inbox else None))
    return rows


def offers_line(st: Style) -> str:
    """One line quoting the last `teyla start`, when it left changes that save money."""
    priced = [o for o in figures.open_offers() if o["high"] > 0]
    if not priced:
        return ""
    lo, hi = sum(o["low"] for o in priced), sum(o["high"] for o in priced)
    span = _money(hi) if round(lo) == round(hi) else f"{_money(lo)}-{_money(hi)}"
    return ("  " + st.paint(f"{len(priced)} change{'s' if len(priced) != 1 else ''} could save about {span} a month", "saving")
            + "  " + st.command("teyla start" if not figures.onboarded() else "teyla apply " + priced[0]["id"]))


def render(st: Style | None = None, at: float | None = None) -> str:
    st = st or Style()
    sessions = figures.has_sessions()
    L = [f"{st.mark()} {st.bold('Teyla')} {__version__}"]
    L += textwrap.wrap(PROMISE, width=min(st.width(), 80))
    L.append("")
    if sessions:
        L += numbers(st, at)
        extra = offers_line(st)
        if extra:
            L.append(extra)
    else:
        L.append(NO_SESSIONS)
    L += ["", st.bold("Next")]
    L += [f"  {pad(st.command(c), 13)}{d}" for c, d in next_commands(sessions, figures.onboarded())]
    return "\n".join(L[:MAX_LINES])


def run(stream=None) -> int:
    """Print the welcome. Whatever goes wrong, the person still gets the header and where to go next."""
    out = sys.stdout if stream is None else stream
    try:
        text = render(Style(out))
    except Exception:  # noqa: BLE001 — bare `teyla` is the first thing a new user types: no traceback
        text = f"Teyla {__version__}\n{PROMISE}\n\nRun `teyla help` for the commands, or `teyla doctor` to check this machine."
    print(text, file=out)
    return 0

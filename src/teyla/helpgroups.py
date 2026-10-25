"""`teyla help` and `teyla --help`: the commands in six groups, in under 40 lines.

Every command is in exactly one group of `GROUPS`; `tests/test_help.py` fails when a registered command
has none. The default help names the commands in `FEATURED` and counts the rest; `teyla help --all`
lists every command with its one-line description; `teyla help <command>` and `teyla <command> --help`
show one command's own options.
"""
from __future__ import annotations

import difflib
import sys

from . import __version__
from .ui import Style, pad

# group -> [(command, one line)]. The order is the order shown.
GROUPS: dict[str, list[tuple[str, str]]] = {
    "Start": [
        ("start", "Find where the money goes, and fix it one change at a time"),
        ("apply", "Make the changes that `start` offers (each can be undone)"),
        ("undo", "Put back only the setting Teyla changed"),
        ("changes", "Every change Teyla made to your tools, and whether it is undone"),
        ("doctor", "Check that Teyla can see your tools, with the fix for each gap"),
        ("prompt", "Print a paste-able prompt for an AI agent (onboard, work account)"),
    ],
    "Daily": [
        ("today", "What waits on you, the Inbox, the week's spend, one next step"),
        ("asks", "Every question an AI session left waiting on you"),
        ("note", "Keep a note, linked to a product"),
        ("notes", "List your notes, newest first"),
        ("answer", "Answer a question inside the session that asked it"),
        ("say", "Correct a session that is running"),
        ("state", "One snapshot for the Mac app: questions, tasks, products"),
        ("digest", "The weekly digest: the top three things worth doing"),
        ("remind", "Dated to-dos that only a human can do"),
        ("dispatch", "Start new work in a fresh worktree"),
    ],
    "Products": [
        ("products", "Usage of every product, in one table"),
        ("product", "The product registry: repos, aliases, stage"),
        ("productize", "What stands between each product and its second user"),
        ("platform", "The shared resources every product reuses"),
        ("testflight", "Did the iOS build reach a person"),
        ("play", "Did the Android build reach a person"),
        ("reviews", "Merged PRs that were never reviewed, or merged with a P1 open"),
        ("routines", "Whether each product's scheduled checks ran"),
        ("check", "Confirm a manual check in a product's teyla.toml"),
        ("docs", "Does a repo's README describe the product as it is now"),
        ("ux", "Does a product's UI follow the shared UX standard"),
        ("intent", "Your long prompts, verbatim, per product"),
        ("scaffold", "Start a new repo with the standard files"),
        ("probe-sql", "One read-only Supabase query for a usage probe"),
        ("cloud", "Readiness of cloud sessions per repo"),
    ],
    "Spend": [
        ("spend", "What the AI work cost, and which part bought nothing"),
        ("monitor", "Adoption report: tokens, models, corrections, advice"),
        ("advise", "Just the findings of the report, each with one action"),
        ("sessions", "One line per session"),
        ("lanes", "Subagent lanes by type and model: cost and review findings"),
        ("grok-cost", "What Grok CLI sessions cost at list price"),
        ("models", "The model ladder and price drift"),
        ("connectors", "Usage of each connector (MCP server)"),
        ("prose", "How long and padded the agent's final replies are"),
    ],
    "Setup": [
        ("config", "Show ~/.teyla/config.toml, or set one key"),
        ("policy", "One policy file wired into every harness"),
        ("harness", "Teyla's skills and hooks in Cursor, Codex, Grok and Hermes"),
        ("plugin", "Install or remove a Claude Code plugin by hand"),
        ("plugins", "Quality pass over your installed Claude Code plugins"),
        ("routine", "Install or check the daily and weekly routines"),
        ("update", "Check GitHub for a newer release and install it"),
        ("uninstall", "Undo every write Teyla made on this machine"),
        ("relay", "The iPhone relay: on, off, pair, sync"),
        ("rule", "Append a one-sentence rule to a repo's rules"),
        ("rules", "Propose rules from your corrections; list stale ones"),
        ("tidy", "Find duplicates and dead references in rules and memory"),
        ("wiki", "A facts wiki the model maintains"),
        ("storage", "What agent work holds on disk and in RAM, and cleaning it"),
        ("load", "Machine load: snapshot, verdict, wait for a free slot"),
        ("guard", "The machine guard that runs by itself"),
        ("crash", "After a crash: what happened and what led to it"),
        ("schedules", "Every scheduled task on this machine, and whether it ran"),
        ("feedback", "One shareable file: setup, redacted report, questionnaire"),
    ],
    "Advanced": [
        ("corrections", "Correction-shaped turns from your sessions, clustered"),
        ("correct", "Record a correction and say how to promote it"),
        ("harvest", "Tool spine and corrections of sessions touching a path"),
        ("lang", "Where tracked files hold non-English text"),
        ("voice", "Check a draft against a voice chart"),
        ("reel", "A session and its git history as a terminal-story video"),
        ("run", "Run one control-plane routine: draft, gate, act, receipt"),
        ("inbox", "The queue of control-plane runs that stopped at a gate"),
        ("kill", "The kill switch for control-plane runs"),
        ("triggers", "Clock triggers as launchd agents"),
        ("promote", "Move a routine to a looser gate, on evidence"),
        ("receipts", "The receipts for one control-plane routine"),
    ],
}

# The commands the default help names. The rest of a group is counted.
FEATURED = {
    "Start": ["start", "apply", "undo", "doctor"],
    "Daily": ["today", "asks", "note", "answer"],
    "Products": ["products", "product", "testflight"],
    "Spend": ["spend", "monitor", "lanes"],
    "Setup": ["config", "policy", "update", "uninstall"],
    "Advanced": [],
}

MAX_LINES = 39                   # "under 40 lines"


def group_of(command: str) -> str | None:
    for g, rows in GROUPS.items():
        if any(c == command for c, _ in rows):
            return g
    return None


def groups(everything: bool = False) -> list[tuple[str, list[tuple[str, str]], int]]:
    """(group, rows to show, commands left out) for each group."""
    out = []
    for g, rows in GROUPS.items():
        rows = list(rows)
        if everything:
            out.append((g, rows, 0))
            continue
        pick = [(c, d) for c, d in rows if c in FEATURED[g]]
        out.append((g, pick, len(rows) - len(pick)))
    return out


def render(everything: bool = False, st: Style | None = None) -> str:
    st = st or Style()
    L = [f"{st.mark()} {st.bold('Teyla')} {__version__}  what your AI agent sessions cost, and what waits on you",
         f"Usage: teyla {st.command('<command>')} [options]      teyla {st.command('<command>')} --help for one command", ""]
    for g, rows, left in groups(everything):
        L.append(st.bold(g))
        L += [f"  {pad(st.command(c), 12)}{d}" for c, d in rows]
        if left:
            more = f"{left} more" if g != "Advanced" else f"{left} commands for rules, the control plane and debugging"
            L.append(st.quiet(f"  {more}: ") + st.command("teyla help --all"))
        if everything:
            L.append("")
    if not everything:
        L += ["", f"Run {st.command('teyla')} for your numbers, or {st.command('teyla start')} to begin."]
    return "\n".join(L).rstrip("\n")


def unknown(word: str, commands, err=None) -> int:
    """`teyla x` for a word that is no command: one line, the nearest command, then the help. Exit 2."""
    err = sys.stderr if err is None else err
    real = sorted(set(commands) | {"help"})
    near = difflib.get_close_matches(word, real, n=1, cutoff=0.6)
    hint = f" Did you mean '{near[0]}'?" if near else ""
    print(f"Unknown command '{word}'.{hint}", file=err)
    print(render(False, Style(err)), file=err)
    return 2


def cmd_help(rest: list[str]) -> int:
    """`teyla help [--all | <command>]`."""
    if rest and rest[0] in ("-a", "--all", "all"):
        print(render(True))
        return 0
    if rest and not rest[0].startswith("-"):
        from . import cli
        return cli.main([rest[0], "--help"])
    print(render(False))
    return 0

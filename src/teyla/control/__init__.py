"""The Teyla control plane: the loop that runs a routine, and the gate it stops at.

`routines.py` reports on work scheduled *elsewhere*. This package is the part
that runs it here, under stated capabilities, and writes down what happened.

    teyla run <product>:<routine> [--dry] [--force]
    teyla inbox [list|show <id>|approve <id>|reject <id> [--note]]
    teyla kill [on|off|status] [--reason]
    teyla triggers [list|install <product:routine>|uninstall <product:routine>]
    teyla promote <product:routine> --gate B|C [--force] [--note]
    teyla receipts <product:routine> [-n 10]

The design constraint the whole package exists to satisfy is one sentence from
the manual: **the model is subject to the loop, not the author of it.** So the
loop is code — `engine.py` — and the model is invoked in exactly one place inside
it, the Draft step in `harness.py`. It cannot decide to skip the gate, because
nothing it emits is consulted about whether the gate happens.

Wire it up from `cli.py` with `control.register(sp)`.

Module map:

    manifest.py   the `[[routine]]` control-plane fields, parsed and validated
    state.py      ~/.teyla — kill switch, inbox, receipts; and where runs are filed
    grants.py     capability strings -> a decision about one tool call
    hook.py       the PreToolUse hook that makes those decisions binding
    rules.py      which rules govern this run, matched by scope and never by vibe
    harness.py    running one step: a command, or a model behind claude/codex/grok
    engine.py     the loop: kill -> idempotency -> grants -> draft -> gate -> receipt
    inbox.py      the queue, and approve/reject
    triggers.py   clock triggers as launchd agents
    promote.py    earned autonomy, refused without evidence
"""
from __future__ import annotations

import sys

__all__ = ["register"]


def cmd_run(args) -> int:
    from .engine import RunRefused, run
    from .manifest import ManifestError
    try:
        return run(args.ref, dry=args.dry, force=args.force, repo=args.repo)
    except (RunRefused, ManifestError, ValueError) as e:
        print(f"teyla run: {e}", file=sys.stderr)
        return 1


def cmd_kill(args) -> int:
    from . import state as S
    action = args.action or "status"
    if action == "on":
        print(S.kill_on(args.reason))
        print("  `teyla run` now refuses, and the PreToolUse hook denies every tool call.")
        return 0
    if action == "off":
        print(S.kill_off())
        return 0
    for line in S.kill_status():
        print(line)
    return 0


def cmd_receipts(args) -> int:
    from . import state as S
    rows = S.receipts_for(args.ref)
    if not rows:
        print(f"no receipts for {args.ref} in {S.receipts_path()}")
        return 0
    rows = rows[-(args.n or 10):]
    print(f"{'when':22} {'run':24} {'gate':4} {'outcome':10} {'calls':>5} {'den':>4} {'wr':>3} {'snd':>3}  summary")
    for r in rows:
        ac = r.get("action_counts") or {}
        print(f"{str(r.get('ts'))[:22]:22} {str(r.get('run_id'))[:24]:24} {str(r.get('gate')):4} "
              f"{str(r.get('outcome')):10} {ac.get('total', 0):5} {ac.get('denied', 0):4} "
              f"{ac.get('writes', 0):3} {ac.get('sends', 0):3}  {str(r.get('summary', ''))[:60]}")
    cost = sum(r.get("cost_usd") or 0 for r in rows)
    if cost:
        print(f"\nAPI-equivalent cost over these {len(rows)} runs: ${cost:.4f}")
    return 0


def cmd_inbox(args) -> int:
    from . import inbox
    return {
        "list": inbox.cmd_list, "show": inbox.cmd_show,
        "approve": inbox.cmd_approve, "reject": inbox.cmd_reject,
    }[args.inbox_action or "list"](args)


def cmd_triggers(args) -> int:
    from . import triggers
    from .engine import RunRefused
    from .manifest import ManifestError
    try:
        return {
            "list": triggers.cmd_list, "install": triggers.cmd_install,
            "uninstall": triggers.cmd_uninstall,
        }[args.triggers_action or "list"](args)
    except (RunRefused, ManifestError, ValueError) as e:
        print(f"teyla triggers: {e}", file=sys.stderr)
        return 1


def cmd_promote(args) -> int:
    from .promote import cmd_promote as run_promote
    from .engine import RunRefused
    from .manifest import ManifestError
    try:
        return run_promote(args)
    except (RunRefused, ManifestError, ValueError) as e:
        print(f"teyla promote: {e}", file=sys.stderr)
        return 1


def register(sp):
    """Add every control-plane subcommand to `cli.py`'s argparse subparsers object."""
    q = sp.add_parser("run", help="run one control-plane routine: draft, gate, act, receipt")
    q.set_defaults(fn=cmd_run)
    q.add_argument("ref", help="<product>:<routine>, as named in the product's teyla.toml")
    q.add_argument("--dry", action="store_true", help="print the plan — run id, key, grants, rules, steps — and create nothing")
    q.add_argument("--force", action="store_true", help="run even though a receipt already exists for this idempotency key")
    q.add_argument("--repo", help="skip the product search and read this repo's teyla.toml")

    q = sp.add_parser("inbox", help="the queue of runs that stopped at a gate")
    q.set_defaults(fn=cmd_inbox, inbox_action="list", all=False, id=None, note=None)
    isp = q.add_subparsers(dest="inbox_action")
    i = isp.add_parser("list"); i.set_defaults(fn=cmd_inbox)
    i.add_argument("--all", action="store_true", help="include items already approved or rejected")
    for name, helptext in (("show", "the draft, the rules, the grants and the actions"),
                            ("approve", "run the act step under the same grants and write a linked receipt"),
                            ("reject", "record the decision; with --note, record the note as a correction candidate")):
        a = isp.add_parser(name, help=helptext); a.set_defaults(fn=cmd_inbox)
        a.add_argument("id")
        if name in ("approve", "reject"):
            a.add_argument("--note", help="what was wrong; a rejection with a note becomes a rule candidate")

    q = sp.add_parser("kill", help="the kill switch: teyla run refuses and every tool call is denied")
    q.set_defaults(fn=cmd_kill, action="status", reason=None)
    q.add_argument("action", nargs="?", choices=["on", "off", "status"], default="status")
    q.add_argument("--reason", help="why — written into the file and shown at every refusal")

    q = sp.add_parser("triggers", help="clock triggers as launchd agents")
    q.set_defaults(fn=cmd_triggers, triggers_action="list", ref=None)
    tsp = q.add_subparsers(dest="triggers_action")
    t = tsp.add_parser("list"); t.set_defaults(fn=cmd_triggers)
    for name in ("install", "uninstall"):
        a = tsp.add_parser(name); a.set_defaults(fn=cmd_triggers)
        a.add_argument("ref", help="<product>:<routine>")
        if name == "install":
            a.add_argument("--no-load", action="store_true", help="write the plist but do not launchctl it")

    q = sp.add_parser("promote", help="move a routine to gate B or C, on evidence from its receipts")
    q.set_defaults(fn=cmd_promote)
    q.add_argument("ref", help="<product>:<routine>")
    q.add_argument("--gate", required=True, choices=["B", "C"])
    q.add_argument("--force", action="store_true", help="promote without the evidence; recorded as forced")
    q.add_argument("--note", help="why you forced it")

    q = sp.add_parser("receipts", help="the receipts for one routine, newest last")
    q.set_defaults(fn=cmd_receipts)
    q.add_argument("ref", help="<product>:<routine>")
    q.add_argument("-n", type=int, default=10)
    return sp

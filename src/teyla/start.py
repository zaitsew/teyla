"""`teyla start`, `apply`, `undo` and `changes`: diagnose your agent spend, then fix it one change at a time.

    teyla start                  the summary card, the checklist of packs, then each offer of a chosen pack:
                                 [y]es / [n]o / [e]xplain / [q]uit
    teyla start --agent          writes nothing; prints JSON {summary_text, diagnosis, offers, features} for an AI
                                 agent to relay
    teyla start --json           the same JSON, for scripts
    teyla apply O1 O3 [--yes]    make those changes (--dry: show them only)
    teyla undo O1 | <change-id>  put back only the key Teyla wrote (--force: even when it was changed since)
    teyla changes [--json]       every change Teyla made, and whether it is undone

Without a terminal and without --agent or --yes nothing waits for input: the summary and the
`teyla apply` commands are printed instead. `docs/START.md` has the flow and every offer.
"""
from __future__ import annotations

import json
import sys

from . import changes, diagnose, features as features_mod, figures, offers as offers_mod
from .offers import plural
from .spend import _money

CARD_MAX_LINES = 12
NOTHING_TO_SUGGEST = "No changes to suggest: your settings already match."


def _range(o) -> str:
    s = o.saving_usd_month
    lo, hi = _money(s["low"]), _money(s["high"])
    return hi if lo == hi else f"{lo}-{hi}"


def summary_text(diag: dict, offers: list, for_agent: bool = False) -> str:
    """The card a human reads first: numbers first, at most CARD_MAX_LINES lines. `for_agent` leaves out the
    closing line that tells a person at a terminal how to go on: an agent asks one offer per question
    (AGENTS.md), and that line would tell it to apply several at once."""
    if diag["empty"]:
        return diagnose.EMPTY_MESSAGE
    L = []
    harnesses = ", ".join(f"{h} {_money(v)}" for h, v in list(diag["by_harness"].items())[:3] if v >= 1)
    L.append(f"Last {plural(diag['days'], 'day')}: {_money(diag['total_usd'])} at API list price over {plural(diag['sessions'], 'session')} "
             f"on {plural(diag['active_days'], 'day')}" + (f" ({harnesses})." if harnesses else "."))
    bits = []
    if diag["context_usd"]:
        bits.append(f"{diag['context_share'] * 100:.0f}% of it ({_money(diag['context_usd'])}) was re-reading and storing context")
    if diag["long_sessions"]:
        bits.append(f"{plural(diag['long_sessions'], 'session')} ran past {diag['long_context_tokens'] // 1000}k tokens of context "
                    f"and cost {_money(diag['long_sessions_usd'])}")
    if bits:
        L.append("; ".join(bits) + ".")
    if diag["subagent_usd"]:
        L.append(f"Subagents cost {_money(diag['subagent_usd'])}; Opus ran {diag['subagent_opus_share'] * 100:.0f}% of that.")
    if diag["waiting_asks"]:
        n = diag["waiting_asks"]
        L.append(f"{plural(n, 'question')} {'is' if n == 1 else 'are'} waiting on you (`teyla asks`).")
    live = [o for o in offers if o.applies]
    if not live or len(L) + 1 + len(live) + 1 <= CARD_MAX_LINES:
        L.append(diag["note"])                # with no room it is dropped here and stays in the JSON
    if not live:
        L.append(NOTHING_TO_SUGGEST)
    else:
        go = "Go through them with `teyla start`, or apply some: `teyla apply " + " ".join(o.id for o in live[:2]) + " --yes`."
        room = CARD_MAX_LINES - len(L) - (0 if for_agent else 1)
        shown = live if len(live) <= room else live[:max(0, room - 1)]
        for o in shown:
            L.append(f"  {o.id} {o.title}: " + (f"about {_range(o)} a month" if o.saving_usd_month else o.short))
        if len(shown) < len(live):
            L.append(f"  +{len(live) - len(shown)} more: " + ", ".join(o.id for o in live[len(shown):]))
        if not for_agent:
            L.append(go)
    return "\n".join(L[:CARD_MAX_LINES])


def payload(days: int, inputs=None, for_agent: bool = False) -> tuple[dict, list]:
    inp = inputs or diagnose.collect(days)
    diag = diagnose.diagnose(days, inp)
    offers = offers_mod.build(days, inp, diag)
    return dict(summary_text=summary_text(diag, offers, for_agent), diagnosis=diag,
                offers=[o.to_dict() for o in offers], features=features_mod.rows(offer_list=offers)), offers


# --- showing an offer --------------------------------------------------------------------------

def saving_line(o) -> str:
    if o.saving_usd_month:
        return f"Saving: about {_range(o)} a month at list price. {o.basis}"
    return f"Brings: {o.benefit}" + (f" {o.basis}" if o.basis else "")


def offer_block(o, explain: bool = False) -> str:
    L = [f"{o.id}  {o.title}", f"  Change:    {o.change['summary']}", f"  {saving_line(o)}",
         f"  Trade-off: {o.tradeoff}", f"  Undo:      {o.undo}"]
    if explain:
        L.append(f"  Detail:    {o.explain}")
    return "\n".join(L)


def _apply_one(o, out, owner: str | None = None) -> bool:
    try:
        rec, lines = offers_mod.apply(o, owner=owner)
    except changes.ChangeError as e:
        print(f"{o.id}: {e}", file=sys.stderr)
        return False
    except Exception as e:  # noqa: BLE001 — a sync that fails half-way must say so, not trace back
        print(f"{o.id}: failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False
    out.append((o, rec))
    for line in lines[:6]:
        print(f"  {line}")
    if any(str(line).startswith(offers_mod.PLUGIN_FAILED) for line in lines):
        print(f"{o.id}: partly applied: the hooks are in place, Teyla's Claude Code plugin is not.", file=sys.stderr)
        return False
    return True


def _done_summary(done: list) -> None:
    if not done:
        print("\nNothing changed.")
        return
    print("\nChanged:")
    for o, rec in done:
        print(f"  {rec['id']}  {o.change['summary']}")
    undoable = [rec for _, rec in done if rec.get("kind") != "command"]
    if undoable:
        print("Undo any of them: " + "  ".join(f"teyla undo {rec['id']}" for rec in undoable))
    for o, rec in done:
        if rec.get("kind") == "command":
            print(f"{o.id}: {o.undo}")
    print("See them all: teyla changes")


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip().lower()
    except EOFError:
        return "q"


def pack_block(p, todo: list[str]) -> str:
    return "\n".join([f"{p.title}  ({p.id})", f"  Problem:   {p.need}", f"  Brings:    {p.does}"]
                     + [f"  Change:    {line}" for line in todo])


def _interactive(offers: list, pl: dict, packs: list | None = None) -> int:
    """Walk the offers, then the rest of each chosen pack (its switches, hooks and jobs). The first screen
    learns of the run (`figures.record_start`) on every way out: `finished` once the person has answered."""
    done: list = []
    answered = False
    figures.record_start(pl, False)                 # the 60 s diagnosis is kept even if the run is interrupted
    for o in [x for x in offers if x.applies]:
        print("\n" + offer_block(o))
        while True:
            a = _ask("Apply it? [y]es / [n]o / [e]xplain / [q]uit  ")
            if a in ("e", "explain"):
                print("  " + o.explain)
            elif a in ("y", "yes"):
                _apply_one(o, done)
                answered = True
                break
            elif a in ("n", "no", ""):
                answered = True
                break
            elif a in ("q", "quit"):
                _done_summary(done)
                figures.record_start(pl, answered)
                return 0
            else:
                print("  y, n, e or q")
    home = features_mod._home()
    for p in packs or []:
        todo = features_mod.plan(p, home, {}, with_offers=False)
        if not todo:
            continue
        print("\n" + pack_block(p, todo))
        while True:
            a = _ask("Turn it on? [y]es / [n]o / [e]xplain / [q]uit  ")
            if a in ("e", "explain"):
                print(f"  Undo: `teyla features off {p.id}`. Try it with: {p.commands[0]}")
            elif a in ("y", "yes"):
                try:
                    for line in features_mod.turn_on(p, home, with_offers=False)[:6]:
                        print(f"  {line}")
                except Exception as e:  # noqa: BLE001 — a pack that fails half-way must say so, not trace back
                    print(f"{p.id}: failed: {type(e).__name__}: {e}", file=sys.stderr)
                answered = True
                break
            elif a in ("n", "no", ""):
                answered = True
                break
            elif a in ("q", "quit"):
                _done_summary(done)
                figures.record_start(pl, answered)
                return 0
            else:
                print("  y, n, e or q")
    _done_summary(done)
    figures.record_start(pl, True)
    return 0


def _checklist(pl: dict) -> list | None:
    """The packs the person ticks, recorded; None when they quit. Packs left out and off get their hooks
    quieted (`features.quiet_unchosen`)."""
    rs = pl.get("features") or features_mod.rows()
    picked = features_mod.pick(rs, _ask)
    if picked is None:
        return None
    features_mod.record_choice(picked)
    for line in features_mod.quiet_unchosen(picked, rs):
        print(f"  {line}")
    return [features_mod.BY_ID[i] for i in picked]


def cmd_start(args) -> int:
    if not (args.agent or args.json):       # stdout stays the card; the wait is announced on stderr
        n = diagnose.count_sessions(args.days)
        print(f"Reading {plural(n, 'session') if n is not None else 'your sessions'} from the last {plural(args.days, 'day')}…", file=sys.stderr)
    pl, offers = payload(args.days, for_agent=bool(args.agent))
    if args.agent or args.json:
        print(json.dumps(pl, indent=2))
        return 0
    print(pl["summary_text"])
    live = [o for o in offers if o.applies]
    settled = not live and not pl["diagnosis"]["empty"]      # nothing to answer: the first screen can move on
    if args.yes:
        done: list = []
        for o in live:
            print("\n" + offer_block(o))
            _apply_one(o, done)
        _done_summary(done)
        figures.record_start(pl, not pl["diagnosis"]["empty"])
        return 0 if len(done) == len(live) else 1
    if not _is_tty():
        figures.record_start(pl, settled)
        if pl["diagnosis"]["empty"]:
            return 0
        if live:
            print("\nNot a terminal, so nothing was asked. To apply: teyla apply "
                  + " ".join(o.id for o in live) + " --yes   (add --dry to see each change first)")
        print("Pick the packs you need: teyla features, then teyla features on <pack>")
        return 0
    packs = _checklist(pl)
    if packs is None:
        print("\nNothing changed.")
        figures.record_start(pl, settled)
        return 0
    ids = {p.id for p in packs}
    return _interactive([o for o in offers if features_mod.OFFER_PACK.get(o.id) in ids], pl, packs)


def cmd_apply(args) -> int:
    owner = (args.owner or "").strip() or None
    if args.owner is not None and not owner:
        print("--owner needs a name", file=sys.stderr)
        return 2
    offers = {o.id: o for o in offers_mod.build(with_savings=False)}
    code = 0
    done: list = []
    for ref in args.offers:
        o = offers.get(ref.upper())
        if o is None:
            print(f"no offer {ref!r}: the offers are {', '.join(offers)}", file=sys.stderr)
            return 2
        if not o.applies:
            print(f"{o.id}: nothing to do: {o.reason}")
            continue
        print(f"{o.id}  {o.title}\n  Change:    {o.change['summary']}\n  Trade-off: {o.tradeoff}\n  Undo:      {o.undo}")
        if args.dry:
            continue
        if not args.yes:
            if not _is_tty():
                print(f"{o.id}: not applied: nothing can ask here. Run `teyla apply {o.id} --yes` to confirm it.", file=sys.stderr)
                code = 1
                continue
            if _ask("Apply it? [y]es / [n]o  ") not in ("y", "yes"):
                continue
        if not _apply_one(o, done, owner if o.id == "O5" else None):
            code = 1
    if args.dry:
        print("\n--dry: nothing was written.")
    else:
        _done_summary(done)
        if done:
            figures.record_start(None, True)        # the first screen stops asking for `teyla start`
    return code


def cmd_undo(args) -> int:
    code = 0
    for ref in args.refs:
        rows = changes.resolve(ref)
        if not rows:
            print(f"nothing to undo for {ref!r}: `teyla changes` lists what Teyla changed", file=sys.stderr)
            code = 1
            continue
        for rec in rows:
            try:
                lines = changes.revert(rec, force=args.force)
            except changes.ChangeError as e:
                print(str(e), file=sys.stderr)
                code = 1
                continue
            print(f"undid {rec['id']}")
            for line in lines:
                print(f"  {line}")
    return code


def cmd_changes(args) -> int:
    rows = changes.changes()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("Teyla has changed nothing on this machine yet.")
        return 0
    for c in rows:
        if c.get("kind") == "command":
            print(f"{c['id']}  {c['offer']}  ran `{c['command']}` at {c['at']}  [{'undone ' + c['undone'] if c['undone'] else 'active; teyla uninstall reverses it'}]")
            continue
        what = ".".join(c["key_path"]) or "file"
        state = f"undone {c['undone']}" if c["undone"] else "active"
        old = changes.ABSENT if not c.get("old_present") else json.dumps(c["old"])
        print(f"{c['id']}  {c['offer']}  {c['file']}  {what}: {old} -> {json.dumps(c['new'])}  [{state}]")
    return 0


def register(sp):
    q = sp.add_parser("start", help="diagnose your agent spend and fix it with one keystroke; --agent: JSON for an AI to relay, writes nothing")
    q.set_defaults(fn=cmd_start)
    q.add_argument("--days", type=int, default=30, help="window to diagnose (default 30)")
    q.add_argument("--agent", action="store_true", help="print JSON {summary_text, diagnosis, offers}; write nothing")
    q.add_argument("--json", action="store_true", help="the same JSON, for scripts")
    q.add_argument("--yes", action="store_true", help="apply every applicable offer without asking")
    q = sp.add_parser("apply", help="make the changes of the named offers (O1..O7); each can be undone")
    q.set_defaults(fn=cmd_apply)
    q.add_argument("offers", nargs="+", metavar="OFFER")
    q.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    q.add_argument("--dry", action="store_true", help="show the changes, write nothing")
    q.add_argument("--owner", metavar="NAME", help="O5: the name the starter POLICY.md carries (default: the login name)")
    q = sp.add_parser("undo", help="revert a change by its id or by its offer id; touches only the key Teyla wrote")
    q.set_defaults(fn=cmd_undo)
    q.add_argument("refs", nargs="+", metavar="CHANGE_OR_OFFER")
    q.add_argument("--force", action="store_true", help="revert even when the key was changed after Teyla wrote it")
    q = sp.add_parser("changes", help="every change Teyla made to your tools' settings, and whether it is undone")
    q.set_defaults(fn=cmd_changes)
    q.add_argument("--json", action="store_true")
    return q

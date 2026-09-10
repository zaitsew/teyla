"""`teyla inbox` — the queue a gate A run stops at, and the record of what you decided.

`~/.teyla/inbox.jsonl`, append-only. An approval is a new line, not an edit to the
line above it; so is a rejection. The file is the history and `list` is only a
replay of it — which is what makes "who approved this, when, and did they have to
say anything" answerable months later.

Two decisions, and they are not symmetrical:

**approve** runs the routine's `act` step under grants recomputed from the
product's *current* `teyla.toml`, and refuses if that manifest now grants more
than the draft ran under — printing the difference.

It used to copy the original run's `grants.json` instead, on the reasoning that
the thing you are approving is the run you actually read. That was right about
the intent and wrong about the file: `grants.json` sat in the run directory, and
a routine holding `fs.write:runs/**` could write to it. Approving then replayed
whatever the run had left there. Both halves are needed, so both are here: the
grants come from the manifest (which the run cannot edit), and a manifest that
has widened since the draft stops the approval rather than riding along with it.
A manifest that has *narrowed* is fine — you get the smaller of the two.

**reject** records the note as a correction candidate in the product repo's
`.teyla/corrections.jsonl` — the same file `/teyla:correct` writes. A rejection
with a reason is the raw material of a rule; a rejection without one is just a
run that did not happen, and the `--note` is what decides which you have.
"""
from __future__ import annotations

import json
import pathlib

from . import grants as G
from . import harness as H
from . import rules as R
from . import state as S
from .engine import (RunRefused, _command_step_allowed, act as run_act, resolve,
                     write_receipt)


def _status(item: dict) -> str:
    d = item.get("decision")
    if d:
        return d
    return item.get("state", "unknown")


def cmd_list(args) -> int:
    items = S.fold_inbox()
    if not items:
        print(f"inbox empty ({S.inbox_path()})")
        return 0
    rows = list(items.values())
    if getattr(args, "all", False) is False:
        rows = [r for r in rows if not r.get("decision")] or rows
    rows.sort(key=lambda r: r.get("ts") or "")
    print(f"{'id':24} {'status':10} {'gate':4} {'routine':28} summary")
    for r in rows:
        note = f"  (note: {r['note']})" if r.get("note") else ""
        print(f"{r.get('id', '?'):24} {_status(r):10} {r.get('gate', '?'):4} "
              f"{str(r.get('routine', '?'))[:28]:28} {str(r.get('summary', ''))[:70]}{note}")
    open_n = sum(1 for r in items.values() if not r.get("decision"))
    print(f"\n{open_n} open, {len(items)} total")
    return 0


def cmd_show(args) -> int:
    item = S.inbox_item(args.id)
    if item is None:
        print(f"no inbox item with id {args.id!r} in {S.inbox_path()}")
        return 1
    print(f"id       {item.get('id')}")
    print(f"routine  {item.get('routine')}   gate {item.get('gate')}")
    print(f"state    {_status(item)}" + (f"   note: {item['note']}" if item.get("note") else ""))
    print(f"when     {item.get('ts')}")
    print(f"run dir  {item.get('run_dir')}")
    run_dir = pathlib.Path(item.get("run_dir") or ".")
    # The canonical receipt, from ~/.teyla. The copy beside the draft is for reading
    # in the repo; what gets summarised here should be the one out of the run's reach.
    r = S.receipt_for_run(args.id)
    if r is None:
        ctl = S.control_run_dir(args.id) / "receipt.json"
        for candidate in (ctl, run_dir / "receipt.json"):
            if candidate.exists():
                try:
                    r = json.loads(candidate.read_text())
                    break
                except ValueError:
                    continue
    if r:
        print(f"outcome  {r.get('outcome')} — {r.get('summary')}")
        print(f"rules    {', '.join(r.get('rule_ids') or []) or '(none)'}")
        print(f"grants   {', '.join(r.get('capabilities') or []) or '(nothing)'}")
        ac = r.get("action_counts") or {}
        print(f"actions  {ac.get('total', 0)} calls, {ac.get('denied', 0)} denied, "
              f"{ac.get('writes', 0)} writes, {ac.get('sends', 0)} sends")
        if r.get("actions_tampered"):
            print(f"WARNING  actions log tampered: {r['actions_tampered']} line(s) dropped")
    for name in ("draft.md", "critic.md", "undo.md"):
        f = run_dir / name
        if f.exists() and f.read_text().strip():
            print(f"\n--- {name} ---")
            print(f.read_text().rstrip())
    if not item.get("decision"):
        print(f"\napprove: teyla inbox approve {item.get('id')}")
        print(f"reject:  teyla inbox reject {item.get('id')} --note \"what was wrong\"")
    return 0


def cmd_approve(args) -> int:
    item = S.inbox_item(args.id)
    if item is None:
        print(f"no inbox item with id {args.id!r}")
        return 1
    if item.get("decision"):
        print(f"item {args.id} is already {item['decision']}" + (f" (note: {item['note']})" if item.get("note") else ""))
        return 1

    reason = S.kill_reason()
    if reason is not None:
        print(f"REFUSED: the kill switch is on — {reason}")
        return 1

    ref = item.get("routine") or ""
    repo = item.get("repo")
    try:
        routine = resolve(ref, repo=repo)
    except (RunRefused, ValueError) as e:
        print(f"cannot run the act step: {e}")
        return 1

    if routine.act is None:
        S.add_inbox_decision(run_id=args.id, decision="approve", note=None)
        print(f"approved {args.id} — {ref} declares no `act` step, so nothing was run.")
        print("  The approval is recorded; the draft is yours to use.")
        return 0

    # What the draft ran under, read from ~/.teyla/receipts.jsonl — the copy the run
    # had no way to write. Never from the `grants.json` or `receipt.json` sitting in
    # the product repo.
    orig_receipt = S.receipt_for_run(args.id) or {}
    was = list(orig_receipt.get("capabilities") or item.get("capabilities") or [])
    now_caps = list(routine.capabilities)
    widened = [c for c in now_caps if c not in was]
    if widened:
        print(f"REFUSED: {ref} has widened its capabilities since this draft was written.")
        print(f"  the draft ran under: {', '.join(was) or '(nothing)'}")
        print(f"  the manifest now says: {', '.join(now_caps) or '(nothing)'}")
        for c in widened:
            print(f"  + {c}")
        print("\n  Approving would act under grants you never reviewed. Re-run the routine so a")
        print("  fresh draft is produced under the current manifest, then approve that.")
        return 1
    dropped = [c for c in was if c not in now_caps]

    when = S.now()
    run_id = S.new_run_id(when)
    run_dir = S.run_dir_for(routine.repo, routine.name, run_id, when)

    ok_cmd, why_cmd = _command_step_allowed(routine.act, routine, run_dir=run_dir)
    if not ok_cmd:
        print(f"REFUSED: the `act` command is not covered by {ref}'s capabilities — {why_cmd}")
        return 1

    run_dir.mkdir(parents=True, exist_ok=True)
    ctl_dir = S.control_run_dir(run_id)
    ctl_dir.mkdir(parents=True, exist_ok=True)

    doc = G.build(routine, run_id=run_id, run_dir=run_dir,
                  grants_path=ctl_dir / "grants.json",
                  state_path=ctl_dir / "grants-state.json",
                  actions_path=ctl_dir / "actions.jsonl")
    doc["control_dir"] = str(ctl_dir)
    doc["approved_from"] = args.id
    (ctl_dir / "grants.json").write_text(json.dumps(doc, indent=2))
    G.write_state(ctl_dir / "grants-state.json", dict(G.ZERO_STATE))
    (ctl_dir / "actions.jsonl").touch()
    S.hmac_key()

    draft = ""
    draft_file = pathlib.Path(item.get("run_dir") or ".") / "draft.md"
    if draft_file.exists():
        draft = draft_file.read_text(errors="replace")
    (run_dir / "draft.md").write_text(draft)

    rules = R.load(routine.repo, routine.context_paths())
    env = H.step_env(None, run_id=run_id, grants_path=ctl_dir / "grants.json", run_dir=run_dir, repo=routine.repo)
    timeout_s = max(1, int((doc.get("caps") or {}).get("max_minutes", 20))) * 60

    # The switch, once more, immediately before the thing that acts. `cmd_approve`
    # checked it on the way in, and everything between then and here is time in which
    # someone could have reached for it.
    reason = S.kill_reason()
    if reason is not None:
        print(f"REFUSED: the kill switch is on — {reason}")
        return 1

    S.mark_run_active(run_id)
    try:
        res, undo_available = run_act(routine, rules, env=env, timeout_s=timeout_s,
                                      run_dir=run_dir, ctl_dir=ctl_dir, draft=draft)
    finally:
        S.clear_run_active(run_id)

    from .engine import _read_actions, _merge_tokens, act_hash
    actions, counts, tampered = _read_actions(ctl_dir)
    tokens, cost = _merge_tokens(res)
    outcome = "ok" if res.ok else "failed"
    summary = (f"approved from {args.id} · acted · "
               f"{'undo available' if undo_available else 'NO UNDO AVAILABLE'}") if res.ok \
        else f"approved from {args.id} · act step failed: {res.error}"
    if tampered:
        summary = f"{summary} · actions log tampered: {tampered} lines"

    receipt = {
        "ts": S.stamp(), "run_id": run_id, "key": f"approve:{args.id}", "routine": ref,
        "product": routine.product, "repo": str(routine.repo), "gate": routine.gate,
        "rule_ids": R.ids(rules), "capabilities": list(doc.get("capabilities") or []),
        "run_dir": str(run_dir), "control_dir": str(ctl_dir), "act_hash": act_hash(routine),
        "approved_from": args.id, "undo_available": undo_available,
        "outcome": outcome, "summary": summary, "actions": actions, "action_counts": counts,
        "actions_tampered": tampered,
        "tokens": tokens, "cost_usd": cost, "duration_s": round(res.duration_s, 2),
        "caps_exceeded": [], "finished": S.stamp(),
    }
    write_receipt(ctl_dir, receipt, copy_to=run_dir)
    S.add_inbox_decision(run_id=args.id, decision="approve", note=getattr(args, "note", None),
                         extra={"acted_run_id": run_id})
    S.add_inbox_item(run_id=run_id, ref=ref, gate=routine.gate, state="acted",
                     summary=summary, run_dir=str(run_dir), repo=str(routine.repo),
                     extra={"approved_from": args.id, "undo_available": undo_available})

    print(f"{outcome.upper()}: approved {args.id} -> act run {run_id}")
    print(f"  {summary}")
    if dropped:
        print(f"  narrowed since the draft (the smaller list applies): {', '.join(dropped)}")
    if tampered:
        print(f"  ACTIONS LOG TAMPERED: {tampered} line(s) failed their signature and were dropped.")
    print(f"  undo:    {run_dir / 'undo.md'}")
    print(f"  receipt: {ctl_dir / 'receipt.json'}")
    return 0 if res.ok else 1


def cmd_reject(args) -> int:
    item = S.inbox_item(args.id)
    if item is None:
        print(f"no inbox item with id {args.id!r}")
        return 1
    if item.get("decision"):
        print(f"item {args.id} is already {item['decision']}")
        return 1
    note = getattr(args, "note", None)
    S.add_inbox_decision(run_id=args.id, decision="reject", note=note)
    print(f"rejected {args.id}")
    if not note:
        print("  No --note given, so nothing was recorded as a correction. A rejection without a")
        print("  reason teaches the routine nothing — re-run with --note next time.")
        return 0
    draft = ""
    d = pathlib.Path(item.get("run_dir") or ".") / "draft.md"
    if d.exists():
        draft = d.read_text(errors="replace")
    path = S.record_correction(item.get("repo") or ".", ref=item.get("routine") or "?",
                               run_id=args.id, note=note, draft_excerpt=draft)
    print(f"  correction candidate recorded in {path}")
    print("  Promote it to a rule with `/teyla:rule`, or let `teyla harvest` pick it up.")
    return 0

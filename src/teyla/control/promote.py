"""`teyla promote` — moving a routine off gate A, on evidence.

The manual sets the bar and this file only enforces it: a gate is earned by a run
of clean history, not granted because the routine has been fine lately. The
evidence required here:

* **10 consecutive clean receipts at the routine's current gate**, counted back
  from the newest and stopping dead at the first that is not clean. Consecutive
  is the whole point: "10 of the last 40 were fine" is not a safety record, and
  counting the last ten while ignoring the failure just before them was the same
  mistake in a smaller window;
* clean means `ok` or `needs-you` (a `blocked` or `failed` run ends the streak);
* and an inbox item that was **approved without a `--note`**. A note means you had
  to say something, and a run you had to correct is not a run that would have been
  safe unattended. It is why `reject --note` writes a correction: the notes are
  the signal.
* every one of them run against **the act step as it is written now**. Each
  receipt carries a hash of the act spec; a receipt whose hash differs was
  evidence about a different step, and it ends the streak. Otherwise a routine
  could bank ten harmless drafts, have its `act` rewritten to something else
  entirely, and cash the streak in for gate B on runs that never exercised it.
* and every one of them run under **the capabilities and caps as they are written
  now**. Each receipt carries a `grants_hash` over the sorted capability list plus
  the caps; a receipt whose hash differs is evidence about a differently-armed
  run, and it ends the streak too. The act step was only half of it: a routine
  that banks ten clean drafts under `fs.write:runs/**` and then adds `net:*` and
  `max_sends = 50` has ten receipts that say nothing about the thing being
  promoted.

Refusal prints the evidence rather than the verdict. "9 clean, then a failure on
2026-09-02" tells you what to do next; "refused" does not.

`--force` overrides, and records `forced: true` with the note in
`~/.teyla/promotions.jsonl`. It exists because there are legitimate reasons to
skip the wait, and none of them should be invisible afterwards.
"""
from __future__ import annotations

import pathlib
import re

from . import state as S

WINDOW = 10
CLEAN_OUTCOMES = ("ok", "needs-you")


def _why_unclean(row: dict, act_hash: str | None, grants_hash: str | None = None) -> str | None:
    """What disqualifies this receipt, or None if it is clean."""
    if row["outcome"] not in CLEAN_OUTCOMES:
        return f"outcome {row['outcome']}"
    if row.get("tampered"):
        return f"actions log tampered: {row['tampered']} lines"
    if row["decision"] != "approved":
        return f"inbox item {row['decision']}"
    if row["note"]:
        return f"approved with a note — {row['note']!r}"
    if act_hash is not None and row.get("act_hash") != act_hash:
        return (f"ran against a different `act` step (receipt {row.get('act_hash') or 'unrecorded'}, "
                f"manifest now {act_hash})")
    if grants_hash is not None and row.get("grants_hash") != grants_hash:
        return (f"ran under different capabilities or caps (receipt "
                f"{row.get('grants_hash') or 'unrecorded'}, manifest now {grants_hash})")
    return None


def evidence(ref: str, current_gate: str, act_hash: str | None = None,
             grants_hash: str | None = None) -> dict:
    """The **trailing run of clean receipts** for `ref` at `current_gate`, newest last,
    plus the receipt that ended it. Pure read — it decides nothing.

    Walking backwards and stopping at the first unclean receipt is what makes the
    streak consecutive. `act_hash` and `grants_hash`, when given, are the act step
    and the capability list as the manifest has them now; a receipt from a different
    act step, or from a differently-armed run, ends the streak."""
    receipts = [r for r in S.receipts_for(ref) if r.get("gate") == current_gate]
    receipts = [r for r in receipts if not r.get("approved_from")]
    items = S.fold_inbox()

    def annotate(r: dict) -> dict:
        item = items.get(r.get("run_id")) or {}
        return {
            "run_id": r.get("run_id"),
            "ts": r.get("ts"),
            "outcome": r.get("outcome"),
            "decision": item.get("decision") or "(open)",
            "note": item.get("note"),
            "act_hash": r.get("act_hash"),
            "grants_hash": r.get("grants_hash"),
            "tampered": r.get("actions_tampered") or 0,
        }

    streak: list[dict] = []
    broke_at = None
    for r in reversed(receipts):
        row = annotate(r)
        why = _why_unclean(row, act_hash, grants_hash)
        if why is not None:
            row["why"] = why
            broke_at = row
            break
        streak.append(row)
        if len(streak) >= WINDOW:
            break
    streak.reverse()
    return {"ref": ref, "gate": current_gate, "total": len(receipts),
            "rows": streak, "broke_at": broke_at, "act_hash": act_hash,
            "grants_hash": grants_hash}


def verdict(ev: dict) -> tuple[bool, list[str]]:
    rows = ev["rows"]
    problems: list[str] = []
    if len(rows) < WINDOW:
        problems.append(f"{len(rows)} consecutive clean receipt(s) at gate {ev['gate']}; "
                        f"{WINDOW} are required")
        broke = ev.get("broke_at")
        if broke:
            problems.append(f"the streak ends at {broke['run_id']} ({broke['ts']}): {broke['why']}")
        elif ev.get("total", 0) > len(rows):
            problems.append(f"{ev['total']} receipt(s) on file at this gate")
    return (not problems), problems


# --- the manifest edit -----------------------------------------------------------------


def set_gate(text: str, routine_name: str, gate: str) -> str:
    """Rewrite one routine's `gate` in a teyla.toml, leaving every byte outside that
    routine's block untouched.

    Line-scanned rather than round-tripped through a TOML writer, because there is no
    TOML writer in the stdlib and re-emitting the file would silently reformat comments
    and ordering that a human wrote on purpose. Raises if the routine's block cannot be
    identified, so the caller can print the edit instead of guessing at it."""
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if re.match(r"^\s*\[\[routine\]\]\s*$", ln)]
    if not starts:
        raise ValueError("no [[routine]] table in this teyla.toml")

    name_re = re.compile(r'^\s*name\s*=\s*["\']' + re.escape(routine_name) + r'["\']\s*$')
    gate_re = re.compile(r'^(\s*)gate\s*=\s*["\'][ABC]["\']\s*$')
    table_re = re.compile(r"^\s*\[")

    for idx, start in enumerate(starts):
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if table_re.match(lines[j]):
                end = j
                break
        block = lines[start + 1 : end]
        if not any(name_re.match(b) for b in block):
            continue
        for k, b in enumerate(block):
            m = gate_re.match(b)
            if m:
                block[k] = f'{m.group(1)}gate = "{gate}"\n'
                return "".join(lines[: start + 1] + block + lines[end:])
        # No `gate` line in the block: insert one right after `name`.
        for k, b in enumerate(block):
            if name_re.match(b):
                block.insert(k + 1, f'gate = "{gate}"\n')
                return "".join(lines[: start + 1] + block + lines[end:])
    raise ValueError(f"no [[routine]] block with name = \"{routine_name}\"")


# --- command ------------------------------------------------------------------------


def cmd_promote(args) -> int:
    from .engine import resolve
    routine = resolve(args.ref)
    target = args.gate
    if target not in ("B", "C"):
        print("--gate must be B or C")
        return 1
    if target == routine.gate:
        print(f"{routine.ref} is already at gate {target}")
        return 0
    if target == "C" and routine.critic is None:
        print(f"{routine.ref}: gate C needs a `critic` in teyla.toml before it can be promoted.")
        return 1
    if routine.act is None:
        print(f"{routine.ref}: gate {target} acts on its own and the routine declares no `act` step.")
        return 1

    from .engine import act_hash as act_hash_of, grants_hash as grants_hash_of
    current_act = act_hash_of(routine)
    current_grants = grants_hash_of(routine)
    ev = evidence(routine.ref, routine.gate, current_act, current_grants)
    ok, problems = verdict(ev)

    print(f"{routine.ref}: gate {routine.gate} -> {target}")
    print(f"evidence — consecutive clean receipts at gate {routine.gate}, newest last "
          f"({ev['total']} on file, act {current_act}, grants {current_grants}):")
    if not ev["rows"]:
        print("  (none)")
    for r in ev["rows"]:
        note = f"  note: {r['note']!r}" if r["note"] else ""
        print(f"  {r['ts']}  {r['run_id']:24} {str(r['outcome']):10} {r['decision']}{note}")
    if ev.get("broke_at"):
        b = ev["broke_at"]
        print(f"  ── streak ends here ──")
        print(f"  {b['ts']}  {b['run_id']:24} {b['why']}")

    if not ok and not getattr(args, "force", False):
        print("\nREFUSED — earned autonomy is not granted on request:")
        for p in problems:
            print(f"  - {p}")
        print(f"\nRun it at gate {routine.gate} until {WINDOW} consecutive receipts are clean and every")
        print("inbox item was approved without a note, then try again. Editing the `act` step")
        print("resets the streak, because the evidence was about the step it replaced — and so")
        print("does editing `capabilities` or `caps`, for the same reason.")
        print("Override with --force.")
        return 1

    manifest = pathlib.Path(routine.repo) / "teyla.toml"
    try:
        new_text = set_gate(manifest.read_text(), routine.name, target)
    except (OSError, ValueError) as e:
        print(f"\ncould not edit {manifest}: {e}")
        print(f"Make the edit by hand: in the [[routine]] block named \"{routine.name}\", set gate = \"{target}\".")
        return 1
    manifest.write_text(new_text)

    S.append_jsonl(S.promotions_path(), {
        "ts": S.stamp(), "routine": routine.ref, "from": routine.gate, "to": target,
        "forced": bool(getattr(args, "force", False)),
        "note": getattr(args, "note", None),
        "problems": problems,
        "act_hash": current_act,
        "grants_hash": current_grants,
        "evidence": ev["rows"],
        "streak_broke_at": ev.get("broke_at"),
    })
    if not ok:
        print("\nFORCED. The evidence above did not support this; it is recorded in the promotion")
        print(f"receipt at {S.promotions_path()} with the problems listed.")
    print(f"\npromoted: {manifest} now has gate = \"{target}\" for {routine.name}")
    if target == "B":
        print("Gate B acts and then shows you what it did. Check the undo actually works before")
        print("you stop reading the receipts.")
    return 0

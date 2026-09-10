"""`teyla promote` — moving a routine off gate A, on evidence.

The manual sets the bar and this file only enforces it: a gate is earned by a run
of clean history, not granted because the routine has been fine lately. The
evidence required here:

* the **last 10 receipts at the routine's current gate**, and there must be ten —
  a routine with four good runs has not shown you anything yet;
* every one of them `ok` or `needs-you` (a `blocked`, `failed` run resets it);
* every one of them with an inbox item that was **approved**, and approved
  **without a `--note`**. A note means you had to say something, and a run you had
  to correct is not a run that would have been safe unattended. That is the whole
  test, and it is why `reject --note` writes a correction: the notes are the
  signal.

Refusal prints the evidence rather than the verdict. "9 of 10, one approved with a
note on 2026-09-02" tells you what to do next; "refused" does not.

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


def evidence(ref: str, current_gate: str) -> dict:
    """The last `WINDOW` receipts for `ref` at `current_gate`, each annotated with what
    its inbox item says. Pure read — it decides nothing."""
    receipts = [r for r in S.receipts_for(ref) if r.get("gate") == current_gate]
    receipts = [r for r in receipts if not r.get("approved_from")]
    window = receipts[-WINDOW:]
    items = S.fold_inbox()
    rows = []
    for r in window:
        item = items.get(r.get("run_id")) or {}
        rows.append({
            "run_id": r.get("run_id"),
            "ts": r.get("ts"),
            "outcome": r.get("outcome"),
            "decision": item.get("decision") or "(open)",
            "note": item.get("note"),
        })
    return {"ref": ref, "gate": current_gate, "total": len(receipts), "rows": rows}


def verdict(ev: dict) -> tuple[bool, list[str]]:
    rows = ev["rows"]
    problems = []
    if len(rows) < WINDOW:
        problems.append(f"only {len(rows)} receipt(s) at gate {ev['gate']}; {WINDOW} are required")
    for r in rows:
        if r["outcome"] not in CLEAN_OUTCOMES:
            problems.append(f"{r['run_id']}: outcome {r['outcome']}")
        elif r["decision"] != "approved":
            problems.append(f"{r['run_id']}: inbox item {r['decision']}")
        elif r["note"]:
            problems.append(f"{r['run_id']}: approved with a note — {r['note']!r}")
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

    ev = evidence(routine.ref, routine.gate)
    ok, problems = verdict(ev)

    print(f"{routine.ref}: gate {routine.gate} -> {target}")
    print(f"evidence — last {WINDOW} receipts at gate {routine.gate} ({ev['total']} on file):")
    if not ev["rows"]:
        print("  (none)")
    for r in ev["rows"]:
        note = f"  note: {r['note']!r}" if r["note"] else ""
        print(f"  {r['ts']}  {r['run_id']:24} {str(r['outcome']):10} {r['decision']}{note}")

    if not ok and not getattr(args, "force", False):
        print("\nREFUSED — earned autonomy is not granted on request:")
        for p in problems:
            print(f"  - {p}")
        print(f"\nRun it at gate {routine.gate} until {WINDOW} consecutive receipts are clean and every")
        print("inbox item was approved without a note, then try again. Override with --force.")
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
        "evidence": ev["rows"],
    })
    if not ok:
        print("\nFORCED. The evidence above did not support this; it is recorded in the promotion")
        print(f"receipt at {S.promotions_path()} with the problems listed.")
    print(f"\npromoted: {manifest} now has gate = \"{target}\" for {routine.name}")
    if target == "B":
        print("Gate B acts and then shows you what it did. Check the undo actually works before")
        print("you stop reading the receipts.")
    return 0

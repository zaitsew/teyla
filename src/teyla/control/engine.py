"""`teyla run` — the loop itself.

    trigger -> load rules -> draft -> GATE -> act -> receipt

Every box is code in this file except one. The Draft step calls a model; nothing
else does. That is the point of the whole package: the model cannot skip the gate
because the model is not the thing that reaches it.

Order matters and is fixed:

1. **Kill switch.** Checked before anything is created. A run that has already
   written its directory before checking is a run the switch did not stop.
2. **Idempotency.** The key is computed from the manifest, not from the output, so
   it is knowable before the expensive part. A key with a finished receipt is a
   skip, and a skip is exit 0 with a sentence, never silence.
3. **Grants.** Written to disk before the step starts, because the hook reads them
   from a file and an in-memory grant enforces nothing.
4. **Draft**, under a wall-clock cap, with `TEYLA_GRANTS` in the environment.
5. **Gate**, per the manifest: A stops, B acts and writes an undo, C asks a critic
   first and acts only on PASS.
6. **Receipt**, always — including for the runs that failed, blocked or skipped.
   A receipt written only on success is a success log, and the runs worth reading
   about later are the other ones.
"""
from __future__ import annotations

import hashlib
import json
import pathlib

from . import grants as G
from . import harness as H
from . import rules as R
from . import state as S
from .manifest import Routine, load as load_manifest

GATE_A, GATE_B, GATE_C = "A", "B", "C"


class RunRefused(RuntimeError):
    """The run did not start: the kill switch, an unresolvable routine, a bad manifest."""


# --- resolution -------------------------------------------------------------------


def resolve(ref: str, *, repo=None) -> Routine:
    """`"<product>:<routine>"` -> the Routine, by searching the configured repo roots
    for a `teyla.toml` whose `[product].name` matches. `repo` short-circuits the
    search when the caller already knows where it lives."""
    product, name = S.split_ref(ref)
    candidates = [pathlib.Path(repo) / "teyla.toml"] if repo else S.find_product_manifests()
    tried = []
    for man in candidates:
        if not man.exists():
            continue
        if S.product_name(man) != product:
            tried.append(f"{man} (product {S.product_name(man)!r})")
            continue
        for r in load_manifest(man):
            if r.name == name:
                return r
        known = ", ".join(x.name for x in load_manifest(man)) or "(none)"
        raise RunRefused(f"product {product!r} has no control-plane routine {name!r}. Declared: {known}")
    roots = ", ".join(str(p) for p in S.repo_roots())
    raise RunRefused(f"no product named {product!r} found under {roots}. Looked at: {', '.join(tried) or '(nothing)'}")


# --- idempotency --------------------------------------------------------------------


def idempotency_key(routine: Routine, *, run_id: str, when=None) -> str:
    """The key a receipt is filed under, and the thing a second run of the same day
    collides with.

    `date`       — once per calendar day. The default, and right for anything a clock
                   trigger fires: two 07:00 digests on one morning is the failure.
    `none`       — never collides. For routines that are meant to run repeatedly.
    `input-hash` — collides when the inputs are byte-identical: the manifest snapshot
                   plus the current contents of every declared context path. Re-running
                   after the input changed is a new run; re-running over the same input
                   is not.
    """
    mode = routine.idempotency
    if mode == "none":
        return f"none:{run_id}"
    if mode == "date":
        day = (when or S.now()).strftime("%Y-%m-%d")
        return f"date:{routine.ref}:{day}"
    h = hashlib.sha256()
    h.update(json.dumps(routine.snapshot(), sort_keys=True, default=str).encode())
    for c in routine.context_paths():
        p = (routine.repo / c).expanduser()
        h.update(b"\x00" + str(c).encode())
        try:
            if p.is_dir():
                for f in sorted(p.rglob("*")):
                    if f.is_file():
                        h.update(str(f.relative_to(p)).encode() + b":" + f.read_bytes())
            elif p.exists():
                h.update(p.read_bytes())
        except OSError:
            h.update(b"<unreadable>")
    return f"hash:{h.hexdigest()[:16]}"


# --- receipt ------------------------------------------------------------------------


def _read_actions(run_dir: pathlib.Path) -> tuple[list[dict], dict]:
    rows = S.read_jsonl(run_dir / "actions.jsonl")
    compact = [{"tool": r.get("tool"), "decision": r.get("decision"), "detail": r.get("detail", "")} for r in rows]
    counts = {"total": len(rows),
              "allowed": sum(1 for r in rows if r.get("decision") == "allow"),
              "denied": sum(1 for r in rows if r.get("decision") == "deny")}
    st = G.read_state(run_dir / "grants-state.json")
    counts["writes"] = st.get("writes", 0)
    counts["sends"] = st.get("sends", 0)
    return compact, counts


def _merge_tokens(*results) -> tuple[dict | None, float | None]:
    tokens: dict = {}
    cost = None
    for r in results:
        if r is None:
            continue
        for k, v in (r.tokens or {}).items():
            tokens[k] = tokens.get(k, 0) + v
        if r.cost_usd is not None:
            cost = (cost or 0.0) + r.cost_usd
    return (tokens or None), cost


def write_receipt(run_dir: pathlib.Path, receipt: dict) -> dict:
    (run_dir / "receipt.json").write_text(json.dumps(receipt, indent=2, default=str))
    S.record_receipt(receipt)
    return receipt


# --- the run -----------------------------------------------------------------------


def run(ref: str, *, dry: bool = False, force: bool = False, repo=None, out=print) -> int:
    reason = S.kill_reason()
    if reason is not None:
        out(f"REFUSED: the kill switch is on — {reason}")
        out(f"  {S.kill_path()}\n  clear it with: teyla kill off")
        return 1

    routine = resolve(ref, repo=repo)
    when = S.now()
    run_id = S.new_run_id(when)
    key = idempotency_key(routine, run_id=run_id, when=when)

    prior = S.receipt_for_key(key)
    if prior and not force:
        out(f"SKIPPED: {routine.ref} already has a finished receipt for idempotency key {key}")
        out(f"  run {prior.get('run_id')} at {prior.get('ts')} — outcome {prior.get('outcome')}")
        out("  re-run it anyway with --force")
        return 0

    rules = R.load(routine.repo, routine.context_paths())
    run_dir = S.run_dir_for(routine.repo, routine.name, run_id, when)

    if dry:
        out("DRY RUN — nothing will be created.")
        out(f"  routine     {routine.ref}   gate {routine.gate}")
        out(f"  repo        {routine.repo}")
        out(f"  run dir     {run_dir}")
        out(f"  key         {key}   ({routine.idempotency}){'  [would skip, use --force]' if prior else ''}")
        out(f"  trigger     {routine.trigger.type}" + (f" at {routine.trigger.at} {routine.trigger.tz} on {','.join(routine.trigger.days)}" if routine.trigger.type == "clock" else ""))
        out(f"  draft       {_describe_step(routine.step)}")
        out(f"  act         {_describe_step(routine.act) if routine.act else '(none)'}")
        out(f"  critic      {routine.critic.harness if routine.critic else '(none)'}")
        out(f"  caps        {', '.join(f'{k}={v}' for k, v in routine.caps.items())}")
        out(f"  grants      {', '.join(routine.capabilities) or '(nothing)'}")
        out(f"  rules       {', '.join(R.ids(rules)) or '(none matched this scope)'}")
        return 0

    run_dir.mkdir(parents=True, exist_ok=True)
    grants_path = run_dir / "grants.json"
    state_path = run_dir / "grants-state.json"
    actions_path = run_dir / "actions.jsonl"
    doc = G.build(routine, run_id=run_id, run_dir=run_dir, grants_path=grants_path,
                  state_path=state_path, actions_path=actions_path)
    grants_path.write_text(json.dumps(doc, indent=2))
    G.write_state(state_path, {"writes": 0, "sends": 0, "calls": 0, "denied": 0})
    actions_path.touch()

    (run_dir / "run.json").write_text(json.dumps({
        "run_id": run_id, "started": when.isoformat(timespec="seconds"), "key": key,
        "manifest": routine.snapshot(), "grants": doc, "rules": [
            {"id": r["id"], "globs": r["globs"], "source": r["source"]} for r in rules
        ],
    }, indent=2, default=str))

    env = H.step_env(None, run_id=run_id, grants_path=grants_path, run_dir=run_dir, repo=routine.repo)
    timeout_s = max(1, int(routine.caps.get("max_minutes", 20))) * 60

    draft_res = _execute(routine.step, routine, rules, env=env, timeout_s=timeout_s,
                         run_dir=run_dir, out_name="draft-raw")
    (run_dir / "draft.md").write_text(draft_res.output or "")
    if draft_res.stderr:
        (run_dir / "draft.stderr.txt").write_text(draft_res.stderr)

    base = {
        "ts": S.stamp(), "run_id": run_id, "key": key, "routine": routine.ref,
        "product": routine.product, "repo": str(routine.repo), "gate": routine.gate,
        "rule_ids": R.ids(rules), "capabilities": list(routine.capabilities),
        "run_dir": str(run_dir),
    }

    if not draft_res.ok:
        return _finish(run_dir, base, out, outcome="failed", results=[draft_res], when=when,
                       summary=f"gate {routine.gate} · draft step failed: {draft_res.error}")

    if routine.gate == GATE_A:
        S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="needs-you",
                         summary=_first_line(draft_res.output), run_dir=str(run_dir), repo=str(routine.repo),
                         extra={"has_act": routine.act is not None})
        return _finish(run_dir, base, out, outcome="needs-you", results=[draft_res], when=when,
                       summary=f"gate A · draft ready, waiting for you · {len(rules)} rule(s)",
                       tail=[f"  inbox: teyla inbox show {run_id}"])

    critic_verdict = None
    critic_res = None
    if routine.gate == GATE_C:
        critic_step = _critic_as_step(routine)
        critic_res = _execute(critic_step, routine, rules, env=env, timeout_s=timeout_s,
                              run_dir=run_dir, out_name="critic-raw", draft=draft_res.output, critic=True)
        (run_dir / "critic.md").write_text(critic_res.output or "")
        critic_verdict = _read_verdict(critic_res.output)
        base["critic"] = critic_verdict
        if not critic_res.ok or critic_verdict != "PASS":
            S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="blocked",
                             summary=f"critic said {critic_verdict or 'nothing parseable'} — {_first_line(critic_res.output)}",
                             run_dir=str(run_dir), repo=str(routine.repo), extra={"has_act": True})
            why = critic_res.error or f"critic returned {critic_verdict or 'no PASS/FAIL first line'}"
            return _finish(run_dir, base, out, outcome="blocked", results=[draft_res, critic_res], when=when,
                           summary=f"gate C · not acted: {why}",
                           tail=[f"  inbox: teyla inbox show {run_id}"])

    act_res, undo_available = act(routine, rules, env=env, timeout_s=timeout_s, run_dir=run_dir,
                                  draft=draft_res.output)
    base["undo_available"] = undo_available
    if not act_res.ok:
        S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="failed",
                         summary=f"act step failed: {act_res.error}", run_dir=str(run_dir),
                         repo=str(routine.repo), extra={"has_act": True})
        return _finish(run_dir, base, out, outcome="failed", results=[draft_res, critic_res, act_res], when=when,
                       summary=f"gate {routine.gate} · act step failed: {act_res.error}")

    S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="acted",
                     summary=f"acted — review · {_first_line(draft_res.output)}", run_dir=str(run_dir),
                     repo=str(routine.repo), extra={"has_act": True, "undo_available": undo_available})
    undo_note = "undo available" if undo_available else "NO UNDO AVAILABLE"
    return _finish(run_dir, base, out, outcome="ok", results=[draft_res, critic_res, act_res], when=when,
                   summary=f"gate {routine.gate} · acted · {undo_note} · {len(rules)} rule(s)",
                   tail=[f"  undo:  {run_dir / 'undo.md'}", f"  inbox: teyla inbox show {run_id}"])


def act(routine: Routine, rules, *, env, timeout_s, run_dir: pathlib.Path, draft: str | None) -> tuple[H.StepResult, bool]:
    """Run the act step and settle the undo question.

    The act step is invited to write its own undo into `$TEYLA_UNDO`. When it does
    not, this writes the note itself and flags it — because "no undo available" said
    out loud in the receipt is the fact that decides whether this routine should have
    been at gate B at all, and a missing file is easy to read as an oversight."""
    res = _execute(routine.act, routine, rules, env=env, timeout_s=timeout_s,
                   run_dir=run_dir, out_name="act-raw", draft=draft)
    (run_dir / "act.md").write_text(res.output or "")
    undo = run_dir / "undo.md"
    available = undo.exists() and bool(undo.read_text().strip())
    if not available:
        undo.write_text(
            "no undo available\n\n"
            "The act step did not write an undo. Nothing here can reverse what it did; "
            "reversing it is a manual job.\n\n"
            f"routine: {routine.ref}\nrun dir: {run_dir}\n\n"
            "To fix this for next time, have the act step write its reversal to $TEYLA_UNDO.\n"
        )
    return res, available


# --- helpers -----------------------------------------------------------------------


def _execute(step, routine: Routine, rules, *, env, timeout_s, run_dir, out_name,
             draft=None, critic=False) -> H.StepResult:
    if step.kind == "command":
        return H.run_command_step(step, cwd=routine.repo, env=env, timeout_s=timeout_s)
    prompt = H.build_prompt(step, R.render(rules), repo=routine.repo, draft=draft, critic=critic)
    (run_dir / f"{out_name}.prompt.md").write_text(prompt)
    grouped = {k: list(v) for k, v in (G.load(run_dir / "grants.json").get("grants") or {}).items()}
    return H.run_agent_step(step, cwd=routine.repo, env=env, timeout_s=timeout_s, grants=grouped,
                            caps=routine.caps, prompt=prompt, out_path=run_dir / f"{out_name}.txt")


def _critic_as_step(routine: Routine):
    from .manifest import Step
    return Step(kind="agent", harness=routine.critic.harness, skill=routine.critic.skill,
                prompt=routine.critic.prompt, context=routine.step.context)


def _read_verdict(text: str | None) -> str | None:
    for line in (text or "").strip().splitlines():
        line = line.strip().strip("*_# `").upper()
        if not line:
            continue
        if line.startswith("PASS"):
            return "PASS"
        if line.startswith("FAIL"):
            return "FAIL"
        return None
    return None


def _first_line(text: str | None, n: int = 120) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:n]
    return "(empty draft)"


def _describe_step(step) -> str:
    if step is None:
        return "(none)"
    if step.kind == "command":
        return f"command: {step.run}"
    ctx = f" context={','.join(step.context)}" if step.context else ""
    skill = f" skill={step.skill}" if step.skill else ""
    return f"agent: {step.harness}{skill}{ctx}"


def _finish(run_dir, base: dict, out, *, outcome: str, results, when, summary: str, tail=()) -> int:
    actions, counts = _read_actions(run_dir)
    tokens, cost = _merge_tokens(*results)
    duration = round(sum(r.duration_s for r in results if r is not None), 2)
    caps_exceeded = []
    doc = {}
    try:
        doc = G.load(run_dir / "grants.json")
    except (OSError, ValueError):
        pass
    limit = (doc.get("caps") or {}).get("max_output_tokens")
    produced = (tokens or {}).get("output_tokens")
    if limit is not None and produced is not None and produced > limit:
        caps_exceeded.append(f"max_output_tokens ({produced} > {limit})")

    receipt = dict(base)
    receipt.update({
        "outcome": outcome, "summary": summary, "actions": actions, "action_counts": counts,
        "tokens": tokens, "cost_usd": cost, "duration_s": duration,
        "caps_exceeded": caps_exceeded, "finished": S.stamp(),
    })
    write_receipt(run_dir, receipt)

    out(f"{outcome.upper()}: {base['routine']} — {summary}")
    out(f"  run {base['run_id']}  key {base['key']}")
    out(f"  rules: {', '.join(base['rule_ids']) or '(none)'}")
    out(f"  tool calls: {counts['total']} ({counts['allowed']} allowed, {counts['denied']} denied), "
        f"writes {counts['writes']}, sends {counts['sends']}")
    if caps_exceeded:
        out(f"  CAPS EXCEEDED: {'; '.join(caps_exceeded)}")
    out(f"  receipt: {run_dir / 'receipt.json'}")
    for t in tail:
        out(t)
    return 0 if outcome in ("ok", "needs-you", "skipped") else 1

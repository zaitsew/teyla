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
import zoneinfo

from . import grants as G
from . import harness as H
from . import rules as R
from . import state as S
from .manifest import Routine, group_capabilities, load as load_manifest

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


def local_day(routine: Routine, when=None) -> str:
    """The calendar day *the routine's trigger means*.

    A routine that fires at 07:00 Europe/Madrid rolls over at midnight in Madrid, not
    at midnight UTC. Keying on the UTC date meant the 07:00 run and a re-run at 01:30
    the next Madrid morning shared a key — and, in the other direction, that a routine
    firing at 23:30 Madrid got a fresh key an hour later. Falls back to the machine's
    local zone when the manifest declares none, and to UTC if even that is unreadable."""
    when = when or S.now()
    name = getattr(routine.trigger, "tz", None)
    if name:
        try:
            return when.astimezone(zoneinfo.ZoneInfo(str(name))).strftime("%Y-%m-%d")
        except (zoneinfo.ZoneInfoNotFoundError, ValueError, OSError):
            pass
    try:
        return when.astimezone().strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return when.strftime("%Y-%m-%d")


def context_files(routine: Routine) -> list[tuple[str, pathlib.Path]]:
    """Every file a routine's `context` actually names, as `(relative path, path)`.

    Context entries are globs — `notes/**`, `*.md` — and the old key hashed them as
    if they were literal filenames, so a routine whose context was `notes/**` hashed
    one non-existent path and got the same key forever however much the notes moved.
    Expanded here, sorted, so the hash is over the tree and is stable across runs."""
    repo = pathlib.Path(routine.repo).expanduser()
    seen: dict[str, pathlib.Path] = {}

    def take(p: pathlib.Path) -> None:
        try:
            if not p.is_file():
                return
            rel = _norm_rel(p, repo)
        except OSError:
            return
        if rel is not None:
            seen.setdefault(rel, p)

    for spec in routine.context_paths():
        spec = str(spec).strip()
        if not spec:
            continue
        if any(ch in spec for ch in "*?["):
            try:
                matches = sorted(repo.glob(spec))
            except (OSError, ValueError, IndexError):
                matches = []
            for m in matches:
                if m.is_dir():
                    for f in sorted(m.rglob("*")):
                        take(f)
                else:
                    take(m)
            continue
        p = (repo / spec).expanduser()
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                take(f)
        else:
            take(p)
    return sorted(seen.items())


def _norm_rel(p: pathlib.Path, repo: pathlib.Path) -> str | None:
    try:
        return str(p.resolve().relative_to(repo.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        try:
            return str(p.relative_to(repo)).replace("\\", "/")
        except ValueError:
            return str(p).replace("\\", "/")


def idempotency_key(routine: Routine, *, run_id: str, when=None) -> str:
    """The key a receipt is filed under, and the thing a second run of the same day
    collides with.

    `date`       — once per calendar day, in the trigger's own timezone. The default,
                   and right for anything a clock trigger fires: two 07:00 digests on
                   one morning is the failure.
    `none`       — never collides. For routines that are meant to run repeatedly.
    `input-hash` — collides when the inputs are byte-identical: the manifest snapshot
                   plus the current contents of every file the context globs expand
                   to. Re-running after the input changed is a new run; re-running
                   over the same input is not.
    """
    mode = routine.idempotency
    if mode == "none":
        return f"none:{run_id}"
    if mode == "date":
        return f"date:{routine.ref}:{local_day(routine, when)}"

    h = hashlib.sha256()
    h.update(json.dumps(routine.snapshot(), sort_keys=True, default=str).encode())
    for rel, path in context_files(routine):
        # Length-prefixed, so that two files cannot be rearranged into the same
        # byte stream: ("ab", "c") and ("a", "bc") must not hash alike.
        h.update(b"\x00" + rel.encode("utf-8") + b"\x00")
        try:
            data = path.read_bytes()
        except OSError:
            data = b"<unreadable>"
        h.update(str(len(data)).encode() + b":")
        h.update(data)
    return f"hash:{routine.ref}:{h.hexdigest()[:16]}"


# --- receipt ------------------------------------------------------------------------


def _read_actions(ctl_dir: pathlib.Path) -> tuple[list[dict], dict, int]:
    """The verified action log for one run, from `~/.teyla/runs/<id>/`.

    Only lines whose HMAC checks out are counted. `tampered` is how many did not,
    and it reaches the receipt as a sentence rather than being quietly dropped: a
    receipt that silently ignores a forged line is exactly the clean receipt the
    forgery was for."""
    rows, tampered = S.read_signed_jsonl(ctl_dir / "actions.jsonl")
    compact = [{"tool": r.get("tool"), "decision": r.get("decision"), "detail": r.get("detail", "")} for r in rows]
    counts = {"total": len(rows),
              "allowed": sum(1 for r in rows if r.get("decision") == "allow"),
              "denied": sum(1 for r in rows if r.get("decision") == "deny")}
    st = G.read_state(ctl_dir / "grants-state.json")
    counts["writes"] = st.get("writes", 0)
    counts["sends"] = st.get("sends", 0)
    if tampered:
        counts["tampered"] = tampered
    return compact, counts, tampered


def act_hash(routine: Routine) -> str:
    """A hash of the act step's bytes, bound into every receipt.

    Promotion is earned by ten clean runs of *this* act step. Without this, a
    routine could accumulate its streak drafting harmlessly, have its `act` rewritten
    to something else entirely, and cash the streak in for gate B on the strength of
    runs that never exercised the new step. A changed act resets the streak."""
    spec = routine.act.as_dict() if routine.act is not None else None
    body = json.dumps(spec, sort_keys=True, default=str).encode()
    return hashlib.sha256(body).hexdigest()[:16]


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


def write_receipt(ctl_dir: pathlib.Path, receipt: dict, *, copy_to: pathlib.Path | None = None) -> dict:
    """The receipt, canonical under `~/.teyla/runs/<id>/` where the run could not have
    written it, plus a readable copy in the product's run directory. The copy is
    convenience; nothing reads it back to make a decision."""
    ctl_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(receipt, indent=2, default=str)
    (ctl_dir / "receipt.json").write_text(body)
    S.record_receipt(receipt)
    if copy_to is not None:
        try:
            copy_to.mkdir(parents=True, exist_ok=True)
            (copy_to / "receipt.json").write_text(body)
        except OSError:
            pass
    return receipt


def _command_step_allowed(step, routine: Routine, *, run_dir=None) -> tuple[bool, str]:
    """A `command` step is a shell command that never passes a PreToolUse hook, so it
    was the one place a routine could do anything its manifest did not grant. It gets
    the same check a Bash tool call gets — the same function, on the same grants.

    `run_dir` supplies `$TEYLA_UNDO` and friends, because writing the reversal to
    `$TEYLA_UNDO` is the documented shape of an act step and the check has to be able
    to read it."""
    if step is None or step.kind != "command":
        return True, ""
    grouped = group_capabilities(routine.capabilities)
    env = {}
    if run_dir is not None:
        env = {"TEYLA_UNDO": str(pathlib.Path(run_dir) / "undo.md"),
               "TEYLA_RUN_DIR": str(run_dir), "TEYLA_REPO": str(routine.repo)}
    return G.shell_allowed(step.run or "", grouped.get("shell") or [],
                           fs_write=grouped.get("fs.write") or [], repo=routine.repo, env=env)


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
        out(f"  control dir {S.control_run_dir(run_id)}   (grants, counters, actions, receipt)")
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
    ctl_dir = S.control_run_dir(run_id)
    ctl_dir.mkdir(parents=True, exist_ok=True)
    grants_path = ctl_dir / "grants.json"
    state_path = ctl_dir / "grants-state.json"
    actions_path = ctl_dir / "actions.jsonl"
    doc = G.build(routine, run_id=run_id, run_dir=run_dir, grants_path=grants_path,
                  state_path=state_path, actions_path=actions_path)
    doc["control_dir"] = str(ctl_dir)
    grants_path.write_text(json.dumps(doc, indent=2))
    G.write_state(state_path, dict(G.ZERO_STATE))
    actions_path.touch()
    S.hmac_key()  # mint it before the first hook call races two of them into existence

    (ctl_dir / "run.json").write_text(json.dumps({
        "run_id": run_id, "started": when.isoformat(timespec="seconds"), "key": key,
        "manifest": routine.snapshot(), "grants": doc, "rules": [
            {"id": r["id"], "globs": r["globs"], "source": r["source"]} for r in rules
        ],
    }, indent=2, default=str))

    base = {
        "ts": S.stamp(), "run_id": run_id, "key": key, "routine": routine.ref,
        "product": routine.product, "repo": str(routine.repo), "gate": routine.gate,
        "rule_ids": R.ids(rules), "capabilities": list(routine.capabilities),
        "run_dir": str(run_dir), "control_dir": str(ctl_dir), "act_hash": act_hash(routine),
    }

    # A `command` step never meets the hook, so its command is checked here against the
    # same grants a Bash tool call would be checked against. Both steps, not just `act`:
    # an ungoverned draft step is the same hole with a different name.
    for label, step in (("step", routine.step), ("act", routine.act)):
        ok, why = _command_step_allowed(step, routine, run_dir=run_dir)
        if not ok:
            return _finish(ctl_dir, base, out, outcome="blocked", results=[], when=when,
                           run_dir=run_dir,
                           summary=(f"gate {routine.gate} · not run: the `{label}` command is not "
                                    f"covered by this routine's capabilities — {why}"),
                           tail=["  Declare what it needs in `capabilities`, or narrow the command."])

    S.mark_run_active(run_id)
    try:
        env = H.step_env(None, run_id=run_id, grants_path=grants_path, run_dir=run_dir, repo=routine.repo)
        timeout_s = max(1, int(routine.caps.get("max_minutes", 20))) * 60

        draft_res = _execute(routine.step, routine, rules, env=env, timeout_s=timeout_s,
                             run_dir=run_dir, ctl_dir=ctl_dir, out_name="draft-raw")
        (run_dir / "draft.md").write_text(draft_res.output or "")
        if draft_res.stderr:
            (run_dir / "draft.stderr.txt").write_text(draft_res.stderr)

        if not draft_res.ok:
            return _finish(ctl_dir, base, out, outcome="failed", results=[draft_res], when=when,
                           run_dir=run_dir,
                           summary=f"gate {routine.gate} · draft step failed: {draft_res.error}")

        if routine.gate == GATE_A:
            S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="needs-you",
                             summary=_first_line(draft_res.output), run_dir=str(run_dir), repo=str(routine.repo),
                             extra={"has_act": routine.act is not None, "control_dir": str(ctl_dir)})
            return _finish(ctl_dir, base, out, outcome="needs-you", results=[draft_res], when=when,
                           run_dir=run_dir,
                           summary=f"gate A · draft ready, waiting for you · {len(rules)} rule(s)",
                           tail=[f"  inbox: teyla inbox show {run_id}"])

        critic_verdict = None
        critic_res = None
        if routine.gate == GATE_C:
            critic_step = _critic_as_step(routine)
            critic_res = _execute(critic_step, routine, rules, env=env, timeout_s=timeout_s,
                                  run_dir=run_dir, ctl_dir=ctl_dir, out_name="critic-raw",
                                  draft=draft_res.output, critic=True)
            (run_dir / "critic.md").write_text(critic_res.output or "")
            critic_verdict = _read_verdict(critic_res.output)
            base["critic"] = critic_verdict
            if not critic_res.ok or critic_verdict != "PASS":
                S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="blocked",
                                 summary=f"critic said {critic_verdict} — {_first_line(critic_res.output)}",
                                 run_dir=str(run_dir), repo=str(routine.repo),
                                 extra={"has_act": True, "control_dir": str(ctl_dir)})
                why = critic_res.error or f"critic returned {critic_verdict}"
                return _finish(ctl_dir, base, out, outcome="blocked", results=[draft_res, critic_res],
                               when=when, run_dir=run_dir,
                               summary=f"gate C · not acted: {why}",
                               tail=[f"  inbox: teyla inbox show {run_id}"])

        # The kill switch, again, here. It was checked before the run started, and the
        # draft (and the critic) may have taken twenty minutes since — which is exactly
        # the window someone reaches for the switch in. A switch that is only read
        # before the cheap half of the loop does not stop the half that acts.
        reason = S.kill_reason()
        if reason is not None:
            S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="blocked",
                             summary=f"kill switch went on before the act step — {reason}",
                             run_dir=str(run_dir), repo=str(routine.repo),
                             extra={"has_act": True, "control_dir": str(ctl_dir)})
            return _finish(ctl_dir, base, out, outcome="blocked",
                           results=[draft_res, critic_res], when=when, run_dir=run_dir,
                           summary=f"gate {routine.gate} · not acted: the kill switch went on — {reason}",
                           tail=[f"  the draft is at {run_dir / 'draft.md'}",
                                 f"  inbox: teyla inbox show {run_id}"])

        act_res, undo_available = act(routine, rules, env=env, timeout_s=timeout_s, run_dir=run_dir,
                                      ctl_dir=ctl_dir, draft=draft_res.output)
        base["undo_available"] = undo_available
        if not act_res.ok:
            S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="failed",
                             summary=f"act step failed: {act_res.error}", run_dir=str(run_dir),
                             repo=str(routine.repo), extra={"has_act": True, "control_dir": str(ctl_dir)})
            return _finish(ctl_dir, base, out, outcome="failed", results=[draft_res, critic_res, act_res],
                           when=when, run_dir=run_dir,
                           summary=f"gate {routine.gate} · act step failed: {act_res.error}")

        S.add_inbox_item(run_id=run_id, ref=routine.ref, gate=routine.gate, state="acted",
                         summary=f"acted — review · {_first_line(draft_res.output)}", run_dir=str(run_dir),
                         repo=str(routine.repo),
                         extra={"has_act": True, "undo_available": undo_available, "control_dir": str(ctl_dir)})
        undo_note = "undo available" if undo_available else "NO UNDO AVAILABLE"
        return _finish(ctl_dir, base, out, outcome="ok", results=[draft_res, critic_res, act_res],
                       when=when, run_dir=run_dir,
                       summary=f"gate {routine.gate} · acted · {undo_note} · {len(rules)} rule(s)",
                       tail=[f"  undo:  {run_dir / 'undo.md'}", f"  inbox: teyla inbox show {run_id}"])
    finally:
        S.clear_run_active(run_id)


def act(routine: Routine, rules, *, env, timeout_s, run_dir: pathlib.Path,
        ctl_dir: pathlib.Path | None = None, draft: str | None) -> tuple[H.StepResult, bool]:
    """Run the act step and settle the undo question.

    The act step is invited to write its own undo into `$TEYLA_UNDO`. When it does
    not, this writes the note itself and flags it — because "no undo available" said
    out loud in the receipt is the fact that decides whether this routine should have
    been at gate B at all, and a missing file is easy to read as an oversight."""
    res = _execute(routine.act, routine, rules, env=env, timeout_s=timeout_s,
                   run_dir=run_dir, ctl_dir=ctl_dir, out_name="act-raw", draft=draft)
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
             ctl_dir=None, draft=None, critic=False) -> H.StepResult:
    if step.kind == "command":
        return H.run_command_step(step, cwd=routine.repo, env=env, timeout_s=timeout_s)
    prompt = H.build_prompt(step, R.render(rules), repo=routine.repo, draft=draft, critic=critic)
    (run_dir / f"{out_name}.prompt.md").write_text(prompt)
    grants_src = pathlib.Path(ctl_dir or run_dir) / "grants.json"
    try:
        grouped = {k: list(v) for k, v in (G.load(grants_src).get("grants") or {}).items()}
    except (OSError, ValueError):
        grouped = {k: list(v) for k, v in group_capabilities(routine.capabilities).items()}
    return H.run_agent_step(step, cwd=routine.repo, env=env, timeout_s=timeout_s, grants=grouped,
                            caps=routine.caps, prompt=prompt, out_path=run_dir / f"{out_name}.txt")


def _critic_as_step(routine: Routine):
    from .manifest import Step
    return Step(kind="agent", harness=routine.critic.harness, skill=routine.critic.skill,
                prompt=routine.critic.prompt, context=routine.step.context)


def _read_verdict(text: str | None) -> str:
    """The critic's first line, read strictly: exactly `PASS`, or it is a `FAIL`.

    It used to strip markdown, upper-case, and accept any line *starting* with PASS —
    so `PASS, though I could not check the pricing rule` read as a pass, and so did
    `**PASSED**` and a stray `Passing this along`. The output contract in the prompt
    asks for one word; anything else is a critic that did not follow it, and a critic
    that did not follow the contract is not evidence that the draft is safe. Nothing
    is inferred and nothing is `None`: unparseable is FAIL."""
    lines = (text or "").splitlines()
    first = lines[0].strip() if lines else ""
    return "PASS" if first == "PASS" else "FAIL"


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


def _finish(ctl_dir, base: dict, out, *, outcome: str, results, when, summary: str,
            tail=(), run_dir=None) -> int:
    ctl_dir = pathlib.Path(ctl_dir)
    actions, counts, tampered = _read_actions(ctl_dir)
    tokens, cost = _merge_tokens(*results)
    duration = round(sum(r.duration_s for r in results if r is not None), 2)
    caps_exceeded = []
    doc = {}
    try:
        doc = G.load(ctl_dir / "grants.json")
    except (OSError, ValueError):
        pass
    limit = (doc.get("caps") or {}).get("max_output_tokens")
    produced = (tokens or {}).get("output_tokens")
    if limit is not None and produced is not None and produced > limit:
        caps_exceeded.append(f"max_output_tokens ({produced} > {limit})")

    if tampered:
        summary = f"{summary} · actions log tampered: {tampered} lines"

    receipt = dict(base)
    receipt.update({
        "outcome": outcome, "summary": summary, "actions": actions, "action_counts": counts,
        "actions_tampered": tampered,
        "tokens": tokens, "cost_usd": cost, "duration_s": duration,
        "caps_exceeded": caps_exceeded, "finished": S.stamp(),
    })
    write_receipt(ctl_dir, receipt, copy_to=pathlib.Path(run_dir) if run_dir else None)

    out(f"{outcome.upper()}: {base['routine']} — {summary}")
    out(f"  run {base['run_id']}  key {base['key']}")
    out(f"  rules: {', '.join(base['rule_ids']) or '(none)'}")
    out(f"  tool calls: {counts['total']} ({counts['allowed']} allowed, {counts['denied']} denied), "
        f"writes {counts['writes']}, sends {counts['sends']}")
    if tampered:
        out(f"  ACTIONS LOG TAMPERED: {tampered} line(s) failed their signature and were dropped.")
    if caps_exceeded:
        out(f"  CAPS EXCEEDED: {'; '.join(caps_exceeded)}")
    out(f"  receipt: {ctl_dir / 'receipt.json'}")
    for t in tail:
        out(t)
    return 0 if outcome in ("ok", "needs-you", "skipped") else 1

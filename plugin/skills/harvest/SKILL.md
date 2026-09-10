---
name: harvest
description: Turn past sessions that touched a given path into a proposed skill, a candidate-rules list, and a routine.yml manifest. Use after doing a task manually two or more times, or when asked to "harvest this", "turn this into a skill", "codify what we've been doing in <path>", or "make a routine for this". Reads real transcripts — never invents a procedure that was not actually run.
argument-hint: <path> — the folder whose work should be harvested, relative to the current repo
---

# Harvest

Build a skill from what **actually happened**, not from what the procedure ought
to be. The whole value is that this reads the record. A speculative skill is
worse than none: it looks authoritative and is wrong in exactly the places where
the real work was messy.

Argument: a path inside this repo. Everything below is scoped to sessions that
touched that path.

## The one rule

> Something goes in the skill **only if it was done the same way every time.**
> Everything that varied, and everything that was corrected, goes in
> `candidate-rules.md` instead — never silently into the skill.

Variation is information. If the first run used one subject line format and the
third used another, you have not found a step; you have found a decision that
nobody has made yet. Writing it into the skill as though it were settled hides
an open question and freezes an arbitrary choice. Surface it instead.

Two runs is the minimum. With one run you cannot tell a procedure from an
accident — say so and stop.

## Step 1–2 — get the harvest input

Run:

```sh
teyla harvest "$1"
```

`teyla harvest` finds every session (in this project's Claude Code transcript
slug, derived from the current working directory) that touched the path,
refuses below two sessions, and prints — per matching session — its ordered
tool spine and its correction-shaped human turns. If it reports fewer than two
sessions, stop and report that. Do not harvest from a single session.

If `teyla` is not installed on this machine, fall back to the inline
equivalent. First find the sessions:

```sh
SLUG="-$(pwd | sed 's|^/||; s|/|-|g; s|\.|-|g')"
TARGET="$1"
grep -l -- "$TARGET" ~/.claude/projects/"$SLUG"/*.jsonl
```

If that returns fewer than two files, stop and report it. Otherwise pull the
tool spine per matching session:

```sh
/usr/bin/python3 - "$TARGET" ~/.claude/projects/"$SLUG"/*.jsonl <<'PY'
import json, sys, collections
target, files = sys.argv[1], sys.argv[2:]
for f in files:
    seq, tools = [], collections.Counter()
    hit = False
    for line in open(f):
        try: o = json.loads(line)
        except: continue
        if target in line: hit = True
        if o.get("type") != "assistant": continue
        for b in o.get("message", {}).get("content", []) or []:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                tools[b["name"]] += 1
                arg = b.get("input", {})
                detail = arg.get("command") or arg.get("file_path") or arg.get("query") or ""
                seq.append((b["name"], str(detail)[:100]))
    if not hit: continue
    print(f"\n=== {f.split('/')[-1]}  ({len(seq)} calls)")
    print("tools:", dict(tools))
    for n, d in seq: print(f"  {n:<12} {d}")
PY
```

Either way, read the sequences side by side. You are looking for the **common
spine**: the steps that appear in every session, in the same order.

## Step 3 — find the corrections

Corrections are where the real rules hide. Read the user turns in those same
sessions and pull anything that pushed back on output already produced: "no",
"not like that", "shorter", "don't", "actually", "I said", "again", a rewrite of
something you just wrote.

Be strict about what counts. A correction is the user rejecting or changing work
you already did. It is **not** a new instruction, a clarifying answer to your own
question, or a change of subject. Over-counting corrections produces a rules file
full of noise, and a rules file nobody trusts gets ignored wholesale.

Read the surrounding turns for each candidate — the correction's *content* is
what matters, and it is rarely in the sentence itself.

## Step 4 — emit four artifacts

Write all four into `<path>/harvest-<YYYY-MM-DD>/`. Never overwrite an existing
skill or rules file — emit proposals and let the repo owner merge them.

### 1. The proposed skill → `SKILL.draft.md`

Only the common spine from step 2. Frontmatter with `name` and a `description`
that names the real trigger phrases.

**Under one screen.** If it does not fit, you have included things that varied —
go back and move them to the rules file. Length here is a symptom, not a style
preference: a long skill means you failed to distinguish the procedure from the
instances.

Each step states what was done, not why. No hedging, no "you may want to" — if
it was conditional, it varied, so it is not in this file.

### 2. `candidate-rules.md`

Everything that varied or was corrected. Explicitly **not** in the skill.

Group into three sections, and keep them separate — they need different actions
from the repo owner:

- **Corrections observed** — one line per correction, with the session file and
  what was rejected. These are the strongest rule candidates: someone already
  paid for this knowledge once.
- **Varied between runs** — the step, plus what it looked like each time. State
  the variants concretely; "the tone varied" is useless, "run 1 opened with a
  question, runs 2–3 opened with a claim" is a decision someone can make.
- **Done once, unclear if load-bearing** — appeared in one session only.

Every entry ends with the proposed rule as one sentence, and the path glob it
should be scoped to. Do not promote anything to `.claude/rules/` yourself — use
`/teyla:rule` for that, and only once asked.

### 3. `routine.yml`

Fill the `routine.yml` template (see `~/ops/.claude/templates/routine.yml` if
present, otherwise emit the same shape from memory: `routine`, `trigger`,
`skill`, `scope`, `context`, `gate`, `capabilities`, `done`). Propose values for
`artifact`, `trigger`, `scope`, and `capabilities`.

**`capabilities` lists only tools you actually observed being used** in step 2's
tool counts. Not tools that seem useful, not tools a similar routine would want
— only names that appeared. An over-broad capability list is how a routine
quietly acquires powers nobody granted it, and it is invisible in review because
an unused permission looks harmless right up until something uses it.

If a step in the spine had no corresponding tool call, say so in a comment
rather than inferring a capability to cover it.

### 4. `done-test.md` — **ask, do not decide**

Draft what "this routine succeeded" would mean, then **ask** rather than writing
it in as settled. Present it as a question with your draft as the proposal:

> Proposed done-test for x-outbound: *a run is done when N drafts exist in
> `runs/<date>/` and each has a named recipient.* Is that the test, or is done
> "drafts are sent", or "replies came back"?

This one is not yours to decide. A done-test is the definition of success for
work the repo owner owns and you only execute — and a wrong done-test is worse
than none, because the routine will confidently report success on the wrong
thing. The transcripts show what was produced; they do not show what the owner
was trying to achieve. Only they know that. Ask.

## Report

End with: how many sessions matched, how many steps made it into the spine, how
many went to candidate-rules and why, and the done-test question. If the spine
came out thinner than expected, say that plainly — a two-step skill honestly
harvested beats an eight-step one that was half invented.

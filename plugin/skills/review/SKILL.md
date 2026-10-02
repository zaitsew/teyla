---
name: review
description: One lean review pass on this branch's diff before asking for a merge — P1/P2 only, cross-provider when a review CLI exists, else one fresh same-provider sub-agent. Use when asked to "review this", "review before merge", "second opinion on the diff", or before opening/merging a PR or MR. At most two rounds per change.
argument-hint: "[--commit <sha>] — review only that fix commit (round two)"
---

# Review

POLICY §2, without needing any CLI: one pass on the **diff**, never the whole tree; P1/P2
only; at most two rounds per change. A diff review costs a fraction of a whole-tree pass
(~90k tokens against ~310k) and catches the bug before anything is built on it.

## 1. The diff

```sh
base=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/main)
git diff "$(git merge-base "$base" HEAD)"          # round one: the whole change
git show <sha>                                      # round two (--commit <sha>): the fix only
```

Empty diff → say so and stop. Skip the review for docs, icons, copy, renames, one-line
config and dependency bumps with no code; say it was skipped and why.

## 2. Who reviews — the first that exists

1. **Another provider.** `~/ops/bin/codex-review` if it is executable, else `codex-review`
   or `claude-review` on PATH. Run it from the repo (`--commit <sha>` for round two), in the
   background, and wait for it: no polling, no second copy. Label the result
   "cross-provider review".
2. **Otherwise one fresh sub-agent** of this harness. In Claude Code: the Agent tool with
   `model: "opus"` (or the strongest available), given **only** the diff and the rules
   below, plus: "read at most 8 files beyond the diff; no skills; no sub-agents; no repo
   exploration". Elsewhere: a new session of the same harness with the same brief. Label the
   result "same-provider review" — it shares this model's blind spots and catches less.

Never review it yourself in this context: you wrote it.

## 3. The rules the reviewer gets

- **P1**: correctness, data loss, security, credentials or money, a crash.
- **P2**: a real bug with a concrete trigger.
- Nothing else: no style, naming, refactors, "consider", missing tests.
- One line per finding: `P1 path:line — defect — scenario that triggers it`.
- No findings: exactly `No P1/P2`.

## 4. Rounds

- Round one: the full diff, once, before the merge.
- Round two only if a P1 was fixed, only on that fix commit (`--commit <sha>`), and the
  reviewer is shown the open P1s it is checking.
- No round three. Merge what was reviewed; anything new goes in its own PR/MR.

Fix every P1 before merging; P2s by judgement, saying which were left and why.

## 5. Report

Under one screen: who reviewed (cross-provider / same-provider, which model), the round, the
findings verbatim (or `No P1/P2`), and for each P1 the fix commit.

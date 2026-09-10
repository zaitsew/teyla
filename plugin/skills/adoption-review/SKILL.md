---
name: adoption-review
description: Run the Teyla adoption review: `teyla monitor`, read the findings, and turn the top three into concrete changes (a rule in .claude/rules, a model: override, a session split). Trigger phrases: "adoption review", "how am I using AI", "token report", "teyla report".
argument-hint: (none) — reviews the last 30 days by default
---

# Adoption review

A monitor run is diagnosis, not action. It tells you what happened; it does not
by itself change anything. This skill closes that loop: run it, read it, and
turn the findings into edits that actually land in the repo.

## Step 1 — run the monitor

```sh
mkdir -p runs/teyla
teyla monitor --days 30 --out "runs/teyla/$(date +%F).md"
```

If `teyla` is not installed, say so and stop — this skill has no fallback for
`monitor` (unlike `harvest`, it needs the full adapter set, not a one-off
grep-and-parse).

## Step 2 — read it

Read the file `teyla monitor` just wrote. Each finding carries a severity, an
id, a title, an evidence line, and a suggested action. Read the evidence line
for every finding you plan to act on — a finding without evidence you can quote
back is not one to act on yet.

## Step 3 — propose at most three changes

Pick the top three findings by severity (ties broken by whichever has the
clearest evidence line). For each, propose one concrete change, not a
direction. "Write better prompts" is not a change; these are:

- **A rule** — a one- or two-sentence constraint for `.claude/rules/<slug>.md`,
  scoped with a `globs:` frontmatter. Use `/teyla:rule` to add it.
- **A `model:` override** — a specific model name, for a specific command or
  agent definition, with the finding's evidence as the reason in the commit
  message or a comment.
- **A session split** — naming the specific task that should stop sharing a
  session with another (e.g. "stop running X inside the ops root session; give
  it its own project root"), when the evidence is long-session token bloat or
  cross-task drift.

State each proposal as: **finding → evidence → proposed change**. Skip a
finding rather than force it into one of these three shapes if it genuinely
doesn't fit — do not invent a fourth category to accommodate it.

## Step 4 — apply the ones that are file edits

Rule additions and `model:` overrides are file edits — make them, using
`/teyla:rule` for rules. A session split is not a file edit here; it's a
recommendation to report, since it's a change to how the human works, not to a
file this plugin can rewrite unattended.

## Step 5 — report

List: how many findings the monitor produced, the three you picked and why,
which ones you applied and to what files, and which ones need a human decision
(the session splits, and anything you skipped). Do not report a change as
applied unless the file edit actually happened.

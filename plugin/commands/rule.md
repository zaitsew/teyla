---
description: Append a one-sentence rule to .claude/rules/ in the current repo, and mirror it in AGENTS.md if one exists
argument-hint: <rule text> [--scope <glob>]
---

Record this rule: $ARGUMENTS

Parse `$ARGUMENTS`: everything up to a literal `--scope` token is the rule text;
whatever follows `--scope` is the glob. If no `--scope` is given, the glob is
`**`.

Follow the conventions in `~/ops/.claude/rules/README.md` if present, otherwise
these (same conventions, restated): a rule is one or two sentences, states the
constraint and not the reasoning, and lives in a file named for what it
constrains, with a `globs:` frontmatter scoping when it loads.

## 1. Pick the file

Derive a short kebab-case slug from the rule text's subject (a few words, not
the whole sentence — e.g. "Outbound drafts open with a claim, not a question."
→ `outbound-drafts`). The file is `.claude/rules/<slug>.md`.

## 2. Check for a duplicate first

Before writing anything, grep the *exact* rule sentence (or a very close
paraphrase) across all of `.claude/rules/*.md`:

```sh
grep -rl -F -- "<rule text>" .claude/rules/ 2>/dev/null
```

If it's already there, **say so and stop** — do not write a duplicate. Report
which file already has it.

## 3. Write it

If `.claude/rules/<slug>.md` doesn't exist yet, create it with frontmatter:

```markdown
---
globs: <scope>
---

- <rule text>
```

If the file already exists (same slug, a different rule in the same cluster),
append a new bullet line to it instead of overwriting, and leave its existing
`globs:` alone unless the new scope is strictly broader — in that case ask
before widening it.

## 4. Mirror into AGENTS.md, conditionally

Check whether `AGENTS.md` exists in the repo root **and is a real file, not a
symlink**:

```sh
if [ -f AGENTS.md ] && [ ! -L AGENTS.md ]; then echo mirror; fi
```

If it is a real file, add (or append to) a `## Rules` section at the end of it
with the same bullet: `- <rule text>`. If `AGENTS.md` doesn't exist, or exists
only as a symlink (commonly pointing at `CLAUDE.md` or vice versa — mirroring
into a symlink would write through it and duplicate the rule on the other
side), skip the mirror step silently.

## 5. Report

State: the file written (or the duplicate found and where), the scope glob
used, and whether AGENTS.md was updated, skipped because it doesn't exist, or
skipped because it's a symlink.

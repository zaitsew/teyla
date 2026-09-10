---
name: wiki-pass
description: File this session's facts into the LLM-maintained wiki — write or update markdown pages from sources, mark them agent-drafted, and let a human confirm. Trigger phrases — "wiki pass", "update the wiki", "file this in the wiki", "what do we know about X", "add to the wiki". Not for how-tos (that's a skill) or never/always constraints (that's a rule) — this skill only files facts, and says where the rest goes.
argument-hint: [path to the wiki] [fact or topic] — both optional; defaults below
---

# Wiki pass

File what this session (or the human) knows as facts into a wiki: a
directory of markdown pages a human reviews rather than writes. See
docs/WIKI.md for the full conventions (frontmatter, bi-temporal bodies, the
90-day staleness rule). This skill is the mechanism; it never writes a
how-to or a constraint into a page — see step 3.

## Step 1 — locate the wiki

In order: the path given as an argument; else `wiki/` in the current
directory; else `~/ops/wiki`. If none of those exist, offer to run
`teyla wiki init <path>` and stop until the human picks a location.

## Step 2 — gather the sources

The facts to file are: whatever was decided or established in the current
session, plus any files or URLs the human names. For each fact, note its
source precisely enough to go in the page's `sources` list — a session id,
a file path, a URL, or `"conversation with <role>"`. A fact with no source is
not ready to file.

## Step 3 — sort each fact: page, supersede, or not-a-fact

For each fact, in order:

1. **Is it a how-to or a constraint, not a fact?** A "how do I do X" is a
   skill; a "must always/never be true" is a rule. Do not write it into the
   wiki. Say where it actually belongs (`.claude/skills/` or
   `.claude/rules/`, per docs/MANUAL.md §1) and move on.
2. **Does an existing page in `pages/` already cover this topic?** Update it
   in place, bi-temporally — never delete the old fact, supersede it:
   *"Until <date>, X. Since then, Y."*
3. **Is this a new, well-formed topic** (not just one stray fact)? Create
   `pages/<slug>.md` with full frontmatter.
4. **Otherwise** — one fact, no home yet — append a line to `inbox.md` with
   its source. Do not force a page into existence for a single fact.

## Step 4 — write with the right provenance

Every page or inbox line you touch gets `confirmed_by: agent`,
`status: draft`, today's date as `last_verified`, and its `sources` list.
Never write `confirmed_by: human` yourself — only
`teyla wiki confirm <path> <slug>`, run by or for the human, does that.

## Step 5 — update index.md and log.md

Add or update the page's line in `index.md` (title, one-sentence summary,
last-verified date). Append one line to `log.md` for every page you touched
or created: date, what changed, source, `confirmed by: agent`.

## Step 6 — lint

Run `teyla wiki lint <path>`. Fix anything it reports — a missing frontmatter
field, an unindexed page, an index entry with no page — before finishing.
Do not report success with a failing lint.

## Step 7 — commit and open a PR/MR, if the wiki is a git repo

If `<path>` is inside a git working tree: create a branch, commit the pages
you touched with a message naming the topic, and open a PR (`gh pr create`)
or GitLab MR (`glab mr create` if available; otherwise print the exact
`git push` command and the MR URL pattern to open by hand). If it is not a
git repo (e.g. a plain folder in `~/ops` tracked by the ops repo itself),
just leave the files written — the ops repo's own commit conventions apply.

## Report

End with: pages added, pages updated (with what changed), inbox items added,
and — if a new fact conflicted with what a page already said — the one-line
question that conflict raises, instead of silently picking a side. Name
anything you routed to a skill or a rule instead of the wiki, and where.

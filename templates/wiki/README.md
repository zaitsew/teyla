# This is a facts wiki

An agent writes and updates the pages in `pages/`. A human reviews, confirms,
or corrects — the human never has to write a page from scratch, only judge one.

- `index.md` — one line per page: title, summary, last verified.
- `pages/<slug>.md` — one page per topic, with frontmatter (`title`, `summary`,
  `sources`, `last_verified`, `confirmed_by`, `status`) and a prose body.
- `inbox.md` — facts that do not have a page yet.
- `log.md` — append-only history of every change, and who confirmed it.

## Only facts live here

A fact is *what is currently the case*. A "how to do X" is a skill, and a
"must always/never" is a rule — both belong somewhere else, and a page here
says where when one turns up.

## The loop

1. The agent runs a wiki pass and writes or updates pages, each marked
   `confirmed_by: agent`, `status: draft`.
2. A human reads the diff — a PR, a GitLab MR, or `git diff` — and either:
   - **merges it** → the page should be marked `confirmed_by: human`,
     `status: confirmed` (`teyla wiki confirm <path> <slug>` does this and
     logs it),
   - **edits it** → the edit is the correction; the next pass reads it as the
     new truth,
   - **or says "add X"** → a new page.
3. `teyla wiki status <path>` shows drafts, confirmed pages, and anything not
   verified in 90 days (`stale`). `teyla wiki lint <path>` checks the wiki is
   internally consistent (every page indexed, every page's required
   frontmatter present, sources non-empty).

## Superseding, never deleting

When a fact changes, the page says so in place, bi-temporally: "Until
2026-09-05, X. Since then, Y." Nothing is deleted — the history of what was
true is itself a fact.

# The facts wiki

Karpathy's "LLM wiki": an agent writes and maintains a directory of markdown
pages from the sources it has — sessions, files, URLs, a human's own words.
The human's job shrinks to review, confirm, or correct. This is the "fact"
leg of the skill / rule / fact split (docs/MANUAL.md §1) given a real store,
instead of an implicit "somewhere in NOTES.md."

## Layout

A wiki is a directory, plain enough to live in a GitHub repo, a GitLab Wiki
(a git repo of `.md` files — this layout works there unchanged), or `~/ops`:

```
index.md      one line per page: title, one-sentence summary, last-verified date
pages/<slug>.md
inbox.md      facts the agent could not file — no page fits, or the shape of one isn't clear yet
log.md        append-only: date, what changed, source, who confirmed
```

`teyla wiki init <path>` creates this from `templates/wiki/`, and is
idempotent — an existing file is left alone.

## Page frontmatter

```yaml
---
title: Acme pricing model
summary: Acme charges per seat, billed annually.
sources:
  - session 2026-09-01-4f2a
  - conversation with the founder
last_verified: 2026-09-09
confirmed_by: agent
status: draft
---
```

- `title`, `summary` — one sentence each.
- `sources` — a list: a session id, a file path, a URL, or `"conversation
  with <role>"`. Never empty — a page with no source is a claim, not a fact.
- `last_verified` — the date the fact was last checked, not the date the page
  was created.
- `confirmed_by` — `human` or `agent`.
- `status` — `draft` (agent-written, unconfirmed), `confirmed` (a human
  merged it), or `stale` (unverified for 90 days — computed by `teyla wiki
  status`, not hand-set).

The body is prose. When a fact changes, the page stays **bi-temporal** — it
says so in place: *"Until 2026-09-05, pricing was per-message. Since then,
Acme charges per seat."* Nothing is deleted; superseded is not the same as
gone, and the history of what was believed true is itself a fact worth
keeping.

## The three-objects rule

Only facts go in the wiki. A "how do I do this" is a skill
(`.claude/skills/<name>/SKILL.md`); a "must always/never be true" is a rule
(`.claude/rules/*.md`). If a wiki pass turns up either, it does not get
written here — the pass says where it went instead. A wiki that accumulates
procedures and constraints alongside facts rots exactly the way docs/MANUAL.md
§1 describes: contradictory prose in about a month.

## The human loop

1. An agent runs a wiki pass (the `wiki-pass` skill) and writes or updates
   pages, each `confirmed_by: agent`, `status: draft`.
2. A human reads the diff — a PR, a GitLab MR, or `git diff` — and:
   - **merges it** → `teyla wiki confirm <path> <slug>` sets
     `confirmed_by: human`, `status: confirmed`, `last_verified: today`, and
     appends the change to `log.md`;
   - **edits it** → the edit itself is the correction; the next pass reads
     the page as it now stands;
   - **or says "add X"** → a new page, filed the same way.
3. A page not verified in 90 days shows as `stale` in `teyla wiki status`,
   whatever its declared `status` says — the fact that decays is
   `last_verified`, not a field a human remembered to flip.

## Review modes

"A human reads the diff" above assumes a PR. Not every wiki lives somewhere a
PR is possible, so pick the mode that matches where the wiki actually lives:

- **PR** — the wiki is a git repo on GitHub or GitLab that takes merge
  requests (this repo, `~/ops`, most team wikis-as-code). The agent pushes a
  branch and opens the PR/MR; nothing lands until it is merged. Gate position
  A: nothing leaves without approval of that exact version.
- **Local diff, then push** — a GitLab *project* wiki is itself a git repo,
  but it is a special one: it takes no merge request at all, ever. `git push`
  to it publishes straight to the team. The loop is: run `teyla wiki lint`,
  read `git diff` yourself, then push. Gate position B — act-and-tell — is
  what this actually is: the agent has already written the pages before you
  read anything, and the "review" is you checking a diff that is one `git
  push` away from being live, not a PR someone else can still reject. Do not
  describe this as "opening an MR for review"; there is no MR to open.
- **Export / edit / re-import** — Confluence, or any wiki that is not files
  in a git repo. Not built. The loop it needs: export the space (or the pages
  a wiki pass touched) to markdown, run the same agent pass over the export,
  diff against the export, apply the edit by hand or via Confluence's API,
  and re-import. Every step here is a placeholder until a Confluence backend
  exists — `teyla wiki` assumes files on disk, full stop.

## Commands

| command | does |
|---|---|
| `teyla wiki init <path>` | scaffold the layout (idempotent) |
| `teyla wiki status <path> [--json]` | counts: pages, drafts, confirmed, stale, inbox items |
| `teyla wiki lint <path>` | every page has required frontmatter and non-empty sources; every page is indexed; every index entry resolves to a real page. Exit 1 on failure |
| `teyla wiki confirm <path> <slug>` | flip a page to human-confirmed and log it |

`teyla wiki status` exits 1 when there are drafts or stale pages, so a
routine can nag on it the same way `teyla routines` does for launchd jobs and
manual checks.

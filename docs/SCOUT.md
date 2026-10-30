# The design scout

Status: shipped in Sprint 1 of [Studio](STUDIO.md) (decision S9, lane D). `teyla scout design` reads the design
feeds once a week, lists what changed, and proposes at most two rule changes a week, each one tied to a problem
you have already seen in a product. It never edits a rule.

```
teyla scout design --dry          # which URLs it would read; fetches and writes nothing
teyla scout design                # this week: the weekly file and at most two proposals
teyla scout design --week 2026-W44 --no-model
```

Quick start: `teyla scout design --dry`, then `teyla scout design`. It needs network (safe mode refuses it without
`--allow-network`) and, to draft a rule, `claude` on the PATH. `--no-model` writes proposals without a drafted rule.
The Friday weekly routine runs it (`teyla routine install --if-stale` adds the line to an old wrapper).

## The sources

[`templates/design/SOURCES.md`](../templates/design/SOURCES.md) is the list. A row is read when its **Kind** is
`rss`, `atom` or `hig`; a `hig` row lists the Apple HIG page slugs, one JSON request each. Rows of the kinds `html`
and `x` are never fetched. The section "Needs a priced yes (X reads cost $0.005 a post)" is off: the scout skips
that section and has no fetcher for X, so adding a fetcher is the step that needs the §11 yes. `--sources FILE`
reads another list. Each fetch uses only the Python standard library over HTTPS, with a 15-second timeout, a
4 MB cap, and the user agent `teyla-scout/<version>`. A feed that declares XML entities is refused.

## The weekly file

`~/.teyla/scout/design/<week>.md` (an ISO week such as `2026-W44`): at most 20 items, each with its title, source,
date, URL and one line. With no `--week`, the week is the current one and the items are those of the last 7 days;
with `--week`, that week's Monday to Sunday. The 20 are chosen by taking turns across the sources, newest first, so a
chatty feed cannot fill the file. A feed that failed is listed under "Not read"; the run fails (exit 1) only when
no source could be read at all.

## The proposals

A finding becomes a proposal only when it meets an **observed product problem of the last 30 days**:

| Problem | Where it is read |
|---|---|
| A decision | `design/decisions/*.json` of a product repo, dated in the last 30 days, not a `reject` |
| A capture | `~/.teyla/review/queue.db`, opened read-only, created in the last 30 days |
| A `teyla ux check` FIX | The current FIX findings of the product repo |

The products are the `--repo` names, else every repo under `code_root` with a `DESIGN.md` or a `design/` folder.
An item meets a problem when they share a design word (tab, toolbar, button, contrast, search, onboarding,
empty, error, and so on) and at least one more word. That is a pointer to look, not a proof, so the model
has a veto: it gets the item, the problem and the titles of the standard's rules, and answers with one rule
sentence in the standard's wording, or with an empty rule when the item does not bear on the problem or the
standard already says it. An empty rule ends that proposal. A run makes at most 6 such calls. When no model
answers, the proposal is written with "not drafted".

At most **two proposals a week** are written, counting those already written for that week, and an item is never
proposed twice. Each is `~/.teyla/scout/design/proposals/<date>-<slug>.md`:

```
# Proposal: <item title>
Week: 2026-W44
Date: 2026-10-30
Status: proposed. Nothing is applied until a person opens a PR and the owner confirms.
Source: <source>, <date> <https://...>
## Quote            one line of the item's own summary
## Product problem it meets      the decision, capture or FIX, with where to find it
## Proposed rule    one sentence
## Next             how a person or a lane turns it into a PR
```

A proposal older than 30 days is deleted on the next run. The scout never touches `templates/design/`, a
product's `design/rules/` or `DESIGN.md`: a person or a lane opens the PR, and a product rule becomes a rule only
through `teyla taste confirm`. Trends never change a rule on their own.

## What leaves the Mac

The HTTPS fetches of the sources, and one `claude -p` call per drafted proposal (a few hundred words: the item's
title, source and one line, the problem text, and the rule titles). [PRIVACY.md](PRIVACY.md), row 26.

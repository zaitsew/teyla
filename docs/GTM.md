# GTM: the cockpit

`teyla gtm` answers two questions. Today: what waits for you, and did you send enough? This week: which goal moved,
where does the funnel leak, and what is the target for next week? It reads; it never sends.

```
teyla gtm init            write ~/.teyla/gtm/goals.toml with neutral example goals; edit it
teyla gtm                 today: approvals, items to send, replies, distribution vs target, outcomes vs targets, deadlines
teyla gtm week            the weekly review: funnel and conversion per goal, stalled items, channels, next targets
teyla gtm week --week 2026-W45   a past week, from the numbers saved when `teyla gtm` ran in it
teyla gtm doctor          each source: ok, stale, broken or missing
```

`--json` on `gtm`, `gtm today` and `gtm week` prints the objects below. Exit 0, also when a source is missing; 1 when a
saved week does not exist or `init` would overwrite; 2 for usage.

## Three counters that never mix

| Counter | What it counts | Where it comes from |
|---|---|---|
| **Preparation** | ideas, drafts, cuts, videos, and any source stage that is neither of the other two | the growth ledger's `idea`, `draft`, `cut`, `video` rows; source stages such as `drafted` |
| **Distribution** | posts you published, approaches you sent | ledger `published` rows and your own `attempt` rows of kind `post`, `comment`, `reply`, `email`, `dm`, `outreach`, `ad`; source stages `posted`, `approached`, `sent`, `invited`, `applied` |
| **Outcomes** | what came back | ledger `response` (replied) and `call`, `meeting`, `icp-meeting` (conversation); source stages `replied`, `conversation`, `intro`, `signed_up`, `activated`, `retained`, `offer_fit`, `offer`, `proposal`, `won`, `paid`, `revenue` |

Preparation is agent throughput. It is shown so you can see the factory runs, and it is never a success metric. An
`attempt` row logged from an agent session (`by: agent`) is a claim: it counts 0 for distribution and shows as
`claimed_by_agents`. Commits are not a GTM number and appear on no GTM screen.

A stage is classed by its last part, so `network.sent` is distribution and `investor.conversation` is an outcome.

## Goals: `~/.teyla/gtm/goals.toml`

Goals, titles, deadlines and targets are personal, so they live only in this file (mode 0600), never in a repo.
`teyla gtm init` writes an example with neutral names:

```toml
version = 1

[distribution]
per_day = 10                     # posts + approaches you send per day

[[goal]]
id = "relationships"
title = "Conversations with founders and executives"
done_when = "A hire, a consulting deal or a product sale"
deadline = "2027-03-01"
funnel = ["identified", "approached", "replied", "conversation", "intro", "offer_fit"]
offer_fit = ["hire", "consulting", "product"]   # decided after the conversation
sources = ["growth", "outreach", "batrack", "contacts"]
stage_prefix = "network"         # `network.sent` feeds this goal; `investor.sent` does not
[goal.map]                       # a source's stage name -> this funnel's stage name
sent = "approached"
[goal.weekly]
approached = 60
conversation = 15
intro = 3
offer_fit = 1
```

| Key | Meaning |
|---|---|
| `id`, `title` | the goal's key and the line the screens show |
| `done_when` | optional: one line on what reaching the goal means; the screens show it under the title |
| `deadline` | `YYYY-MM-DD`; the screens show the days left |
| `funnel` | the stages in order. Conversion is each stage's count over the stage before |
| `offer_fit` | the options of the `offer_fit` stage; sources report them under `offer_fit` |
| `sources` | the source ids that feed this goal. `growth` is the growth ledger |
| `stage_prefix` | a source stage `<prefix>.<stage>` feeds only the goal with that prefix; an unprefixed stage feeds every goal that lists the source |
| `map` | renames a source stage (by its full name or its last part) to a funnel stage |
| `[goal.drafts]` | optional matcher for growth drafts: lists `products`, `platforms`, `kinds`. A draft counts for the goal when every listed field matches; the first goal in file order that matches wins. An empty table matches nothing |
| `weekly` | the weekly target per stage. `gtm week` lists what was missed and repeats the targets as next week's |

`[[source]]` entries name a read-only command or a file (see below). A broken line becomes a `goals:` doctor line,
never a crash.

## Drafts and goals

Each waiting growth draft (the `teyla growth review` queue) belongs to at most one goal. The order of precedence:

1. a manual tag: `teyla growth tag ID... --goal GOAL` writes `goal` on the item; `--goal none` writes `goal: ""` and
   rules no longer apply. A tag naming a goal that is gone is ignored;
2. the first goal whose `[goal.drafts]` matches the draft;
3. no goal. These drafts count under `untagged_drafts`.

A source that reports `waiting.approve` under a prefix (`network.approve`) counts for the goal with that `stage_prefix`,
when the source is in the goal's `sources`. An unprefixed `approve` count cannot be told apart, so it counts as untagged.

## Sources: how a product feeds the cockpit

A source is a document a product writes or prints. Teyla reads it, in this order for each id:

1. a `[[source]]` entry in `goals.toml`: `command = ["/path/exporter", "--json"]` (run without a shell, 20 s timeout,
   stdin closed) or `file = "~/path/source.json"`;
2. a file dropped in `~/.teyla/gtm/sources/<id>.json`;
3. the built-in adapter for `batrack` and every repo in growth's `outreach_repos`: the product's cached usage
   probe (`teyla products` refreshes it). Counters named `gtm_<stage>` and `gtm_waiting_<kind>` map themselves;
   `drafts_open` (or `drafts`) is `waiting.approve`, and only `_week`/`_7d` counters count as this week.

`TEYLA_GTM_DIR` moves the whole folder (tests use it; sibling products honour the same variable). Teyla makes no network
call for GTM: a product with a hosted backend writes its own file or ships a local exporter.

A goal that names a source nobody feeds shows one `missing` doctor line. A source that fails shows one `broken` line.
Neither fails the command.

### Source schema, version 1

```json
{
  "source": "outreach",
  "version": 1,
  "updated": "2026-11-07T10:00:00Z",
  "week": "2026-W45",
  "counts":   {"network.sent": 9, "network.replied": 3, "network.conversation": 2, "investor.sent": 1},
  "today":    {"network.sent": 2},
  "waiting":  {"approve": 4, "send": 5, "reply": 2, "follow_up": 1},
  "stalled":  {"network.replied": 1},
  "channels": {"linkedin": {"network.replied": 2}, "email": {"network.replied": 1}},
  "offer_fit": {"network.hire": 1, "network.consulting": 0, "network.product": 1},
  "links":    {"approve": "https://example.com/queue"}
}
```

| Field | Required | Meaning |
|---|---|---|
| `source` | yes | the id goals name. Lowercase; `-` and spaces become `_` |
| `updated` | yes | ISO 8601. Older than 7 days: `stale`, counts still shown |
| `counts` | yes | this ISO week's movements into each stage, never all-time totals. Whole numbers 0..100000 |
| `week` | no | the ISO week `counts` covers. Another week: `stale`, and its counts count 0 |
| `today` | no | today's movements. Ignored unless `updated` is today |
| `waiting` | no | what waits for the owner: `approve`, `send`, `reply`, `follow_up`. A prefixed key counts under its last part |
| `stalled` | no | items sitting in a stage longer than the product's own limit |
| `channels` | no | per channel, stage counts; `gtm week` shows the outcome stages, so you see which channel produced results |
| `offer_fit` | no | offer-fit decisions this week, by option |
| `links` | no | per waiting kind, the product's own page for it. Only `http(s)` URLs are kept; the Admin app's Open button opens them |

A source carries counts and links to its own queue: never a person's name, a handle or message text.

## `teyla gtm today --json`

```json
{
  "version": 1, "day": "2026-11-07", "week": "2026-W45", "has_goals": true,
  "approve":   {"total": 6, "by_source": {"growth": 4, "outreach": 2}, "links": {"outreach": "https://example.com/queue"}},
  "send":      {"total": 5, "by_source": {"outreach": 5}, "links": {}},
  "reply":     {"total": 2, "by_source": {"outreach": 2}, "links": {}},
  "follow_up": {"total": 0, "by_source": {}, "links": {}},
  "distribution": {"today": 3, "target": 10, "week": 21, "claimed_by_agents": 0},
  "preparation":  {"today": 40, "week": 283},
  "outcomes":     {"today": 1, "week": 9},
  "week_end": "2026-11-08",
  "goals": [{"id": "relationships", "title": "...", "done_when": "...", "deadline": "2027-03-01", "days_left": 114,
             "weeks_left": 17, "short": 12, "fed_by": ["growth"], "unfed": ["contacts"],
             "drafts": {"total": 5, "growth": 4, "by_source": {"growth": 4, "outreach": 1}},
             "targets": [{"stage": "conversation", "count": 6, "target": 15, "counter": "outcomes",
                          "history": [{"week": "2026-W38", "count": null}, "...", {"week": "2026-W45", "count": 6}]}]}],
  "untagged_drafts": 1, "draft_goals": {"g1107-ab3d": "relationships"},
  "next": [{"kind": "reply", "count": 2, "label": "answer 2 replies", "sources": ["outreach"]},
           {"kind": "approve", "count": 6, "label": "approve or skip 6 drafts", "command": "teyla growth review", "sources": ["outreach", "growth"]}],
  "sources": [{"id": "growth", "state": "ok", "via": "growth ledger", "line": "..."}],
  "doctor": ["contacts: missing: a goal names it, but nothing feeds it: ..."]
}
```

`next` is the ordered list the screens lead with: replies, approvals, sends, follow-ups, then the distribution gap.
`approve.by_source.growth` is the growth review queue (`teyla growth review`), held drafts excluded.
Each goal's `drafts` counts the drafts waiting for it (see "Drafts and goals"); `untagged_drafts` counts those no goal
claims, and `draft_goals` maps each waiting growth item id to its goal (at most 500), so an app can show the goal beside a draft.
Each target names its `counter`. `short` adds up how far this week's outcome targets are from their numbers; a
distribution target (approaches) never counts toward it. `history` holds the stage's count in the eight weeks ending with
this one, read from the saved weeks; `null` is a week no run saved.

## `teyla gtm week --json`

`{version, week, start, end, day, has_goals, counters, goals, channels, formats, sources, doctor}`.
`counters` holds `preparation`, `distribution` and `outcomes`, each with `week`, `today` and `by_stage`. Each goal has
`funnel` (`stage`, `count`, `target`, `conversion`, `counter`, `stalled`), `offer_fit`, `fed_by`, `unfed`, `stalled`,
`missed` (stage: how many short of the target) and `next_targets`. `channels` keeps the outcome stages per channel;
`formats` counts this week's published posts by `platform/format`.

Each run of `teyla gtm` or `teyla gtm week` saves the current week to `~/.teyla/gtm/weeks/<YYYY-Www>.json`, so a past
week can be reviewed after the sources moved on.

## In the apps

The admin build of Teyla for Mac opens on Today; the iPhone shows a Today card through the relay. Both read
`teyla gtm today --json`. The store build has neither.

Today puts the goals first. The goal with the most to do leads as a large card. It has one row per outcome target and
one circle per unit of the weekly number. A circle fills only when a real outcome came back; a draft or a send never
fills one. Under the rows, "Next" names the work that moves the goal: replies first, then the drafts for this goal
("2 replies to answer, then 8 drafts for this goal"). A quiet footer, "11 drafts have no goal. Assign them on Growth.",
appears while drafts wait that no goal claims; each draft on the Growth page has a goal menu that runs `teyla growth tag`. The other goals sit
below as thin rows, and a goal with no number asks for one. Sent, Came back and Prepared stay one quiet line at the top. The activity
graph (posts, comments, emails and meetings) follows the goals. With no goals file, Today opens on a three-step setup
that writes the first goal with `teyla gtm goal add`.

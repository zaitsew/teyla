# teyla asks

One list of every question an AI session left waiting on you. A session ends on a
question, the desktop app archives it, and nobody reads it again. In 14 days 40 Claude
Code sessions ended that way and 1 got an answer. `teyla asks` finds them.

## Use

    teyla asks                       open items, one group per product, parked products muted
    teyla asks --flat                the old list: one header per product, oldest product first
    teyla asks --html --open         the same as one page (~/.teyla/asks.html), readable on a phone
    teyla asks done <id> [--note T]  close one; a prefix of 3+ characters is enough
    teyla asks undo <id>...          reopen a done one, or an ask Teyla closed (see below)
    teyla asks snooze <id> <days>    hide one until the days pass
    teyla asks done --older-than 3   close every question older than 3 days (--product P for one)
    teyla asks --all --json          include done, snoozed and muted items; machine-readable
    teyla asks --days 60 --product P widen the window, or keep one product
    teyla asks --why <id>            which rule put one ask under its product, and what it matched
    teyla product assign <id> <P>    a question sits under the wrong product: move its session

The product of an item comes from the product registry, not from a guess at the directory name:
see [PRODUCTS.md](PRODUCTS.md). Sessions the registry does not place are listed under `unassigned`.

## Which product, and why

An ask is filed by this order: your `[assign]` correction, the repo of the session's PR link, the
registered directory the session ran in, a product named in the session title or the question, an
unregistered checkout, else `unassigned`. A session that ran outside any repo, or asked about another
product, still lands on the right one when its PR link or title names it. `--json` gives each ask
`attributed_by` (`assign`, `pr`, `path`, `text`, `checkout` or `unassigned`), and `--why` prints the
evidence on one line:

    teyla asks --why 4dba3b64
    4dba3b64 → app-b (by pr: PR example/app-b)

Gates and reminders have a fixed product and an empty `attributed_by`.

## Whole questions

A question never starts in the middle of a sentence.

- **A clipped tail.** A final message is cut to 400 characters from the front so the question
  survives. When the cut falls inside a sentence, the question starts at that sentence's first word
  instead, up to the 600-character limit; a sentence too long for that is skipped, and the question
  starts at the next one. A question that begins with an ellipsis, a lowercase letter or a closing
  bracket or punctuation mark is backed up the same way, across a paragraph break if need be. Text with no
  sentence end keeps the old cut and its leading ellipsis.
- **A bare instruction.** A short instruction that makes no sense alone (fewer than 7 words, no
  question mark, an imperative verb or a lowercase letter first) is stored as `<session title>:
  <instruction>`.

Both change the stored question, not only the display. The limit stays 600 characters.

## Grouped by product

The default listing prints one header per product, `<display name>  <n> waiting  [stage]`, and the
product's asks under it, oldest first. Products with `focus = true` come first, then the rest by their
oldest ask, and `unassigned` is last. `--flat` prints the old list. `--json` keeps its keys and adds
`groups`, `[{product, display_name, stage, focus, count, ids}]`, plus `muted` (a count) and
`muted_products`. `--html` uses the same groups, with headings only.

## Asks you can trust: resolved and collapsed

Two kinds of ask never needed you, and `teyla asks` closes them itself. The default listing hides
both and ends with one line:

    filtered: 3 resolved (PR merged/closed), 2 duplicates — teyla asks --all

`teyla asks --all` shows them, marked `done` or `duplicate`, with the reason under the question.
`teyla asks undo <id>` brings one back.

**Resolved by PR state.** An ask whose `pr` link points to a PR that is MERGED or CLOSED, and became
so after the ask's last activity, is done. It is recorded in `~/.teyla/asks.json` like a manual
`done`, with the note `auto: PR merged <url>` (or `closed`). A PR merged before the ask was written
does not count. The state is read from, in order:

1. the open PRs in the backlog cache (`state-backlog.json`, when under 30 minutes old): open;
2. `~/.teyla/pr-state.json`, entries under 30 minutes old;
3. one batched `gh api graphql` query for the rest (state, `mergedAt`, `closedAt`).

Only `teyla asks` runs the query. `teyla state`, the relay and the other readers use the caches and
never wait on the network. Without `gh`, in safe mode, with no network, on an error or an answer that
does not parse, nothing resolves and nothing fails. After a failed query the next one waits five minutes.

**Duplicates.** Within one product, a `question` ask that repeats a newer one collapses into the newer:

- the same session and the same normalised question (lower case, whitespace collapsed, `*`, `_` and
  backticks removed); or
- a token-set Jaccard of at least 0.8 over the words of 3 or more letters, when both questions have at
  least 6 such words.

The kept ask shows `(+N similar)`, and `--json` gives it `dupes: [ids]`. The collapsed ones are hidden,
not marked done. When the kept ask is done, its duplicates are done too, with the note
`auto: duplicate of <id>`. Asks of different products never collapse; neither do `blocked` asks,
gates and reminders. An older ask that was already closed by hand stays as it is.

**Undo.** `teyla asks undo <id>...` removes the done mark. An ask you undo is remembered (`undone` in
`asks.json`): neither check touches it again. Undoing a kept ask also puts the duplicates that were
closed because of it back under it; undoing a hidden duplicate shows it as its own ask.

`teyla asks --json` adds `resolved` and `duplicates` (counts); `teyla state --json` adds the same two
numbers to `totals`. The version of the snapshot stays 2.

## Parked products stay quiet

An ask in a product with `stage = "parked"` is muted: it is left out of the list and out of the
session-start count, and the listing ends with one line:

    2 muted in parked products (atlas, lens) — teyla asks --all, or teyla product wake <id>

`teyla asks --all` shows muted asks, and so does `teyla asks --product <parked id>`. `teyla product wake
<id>` ends the muting. `teyla state --json` keeps muted asks in `asks[]` with `muted: true`, ranked last
and left out of the brief and of `totals.questions`.

Muting never hides a critical ask. An ask is critical when its kind is `blocked`, or its title,
question or context contains one of these words (case-insensitive, whole words; `*` lets the word go on):

| Class | Terms |
|---|---|
| Security | security, vulnerab*, leak*, secret*, credential*, token expired |
| Money | charge*, billing, invoice, payment, price |
| Release failure | rejected, rejection, crash*, build failed, release failed, upload failed |

A critical ask in a parked product shows in its group, marked `parked`. The list is
`CRITICAL_TERMS` in `src/teyla/asks.py`.

The header reads "N waiting on you (M in archived sessions)". Each item shows the question
word for word, a short context line, the options the agent offered, and a link that reopens the
session (`claude://claude.ai/epitaxy/local_...`, or `codex resume <id>` for Codex).

## Where items come from

| Source | An item is |
|---|---|
| Claude desktop session metadata | a session whose summary is `blocked` or has a `needs_action` line |
| Claude Code transcripts | a last turn that calls `wrap_up` with an `ask`, or ends with a question |
| Codex rollouts | a `request_user_input_async` call with no output, or a final message ending in a question |
| Teyla | a pending gated run (`teyla inbox`); a reminder overdue or due within 7 days |

A desktop session and its transcript are one item. Question text priority: the `ask`, then
`needs_action`, then the trailing question. `codex exec` runs, spawned agents and `claude -p`
sessions are automation and are skipped. Everything is read-only; secrets are scrubbed and
text is cut at 600 characters (see Whole questions).

An item closes by itself when a later human prompt appears in its session. Done and snoozed
items live in `~/.teyla/asks.json`. The default window is 21 days.

## Session start

The daily routine and a background refresh (at most hourly, started by the session-start hook)
run `teyla asks --quiet`, which writes `~/.teyla/asks.count`. The hook prints that one line when
the file is under 3 days old: "3 questions wait for you — teyla asks". It scans nothing itself.
The count is what the default listing shows, so muted asks are not in it.
Reminders are not counted; they already reach the banner.

## Privacy

`teyla asks` output holds session text. It never goes into `monitor --share` or `feedback`;
`tests/test_share_leaks.py` plants a waiting session and checks that. Override the desktop
metadata root with `TEYLA_CLAUDE_SESSIONS` (tests do).

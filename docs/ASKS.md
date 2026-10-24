# teyla asks

One list of every question an AI session left waiting on you. A session ends on a
question, the desktop app archives it, and nobody reads it again. In 14 days 40 Claude
Code sessions ended that way and 1 got an answer. `teyla asks` finds them.

## Use

    teyla asks                       open items, one group per product, parked products muted
    teyla asks --flat                the old list: one header per product, oldest product first
    teyla asks --html --open         the same as one page (~/.teyla/asks.html), readable on a phone
    teyla asks done <id> [--note T]  close one; a prefix of 3+ characters is enough
    teyla asks snooze <id> <days>    hide one until the days pass
    teyla asks done --older-than 3   close every question older than 3 days (--product P for one)
    teyla asks --all --json          include done, snoozed and muted items; machine-readable
    teyla asks --days 60 --product P widen the window, or keep one product
    teyla product assign <id> <P>    a question sits under the wrong product: move its session

The product of an item comes from the product registry, not from a guess at the directory name:
see [PRODUCTS.md](PRODUCTS.md). Sessions the registry does not place are listed under `unassigned`.

## Grouped by product

The default listing prints one header per product, `<display name>  <n> waiting  [stage]`, and the
product's asks under it, oldest first. Products with `focus = true` come first, then the rest by their
oldest ask, and `unassigned` is last. `--flat` prints the old list. `--json` keeps its keys and adds
`groups`, `[{product, display_name, stage, focus, count, ids}]`, plus `muted` (a count) and
`muted_products`. `--html` uses the same groups, with headings only.

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
text is cut at 600 characters.

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

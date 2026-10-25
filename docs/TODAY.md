# The first screen: `teyla`, `teyla today`, `teyla help`

Three screens, each short enough to read without scrolling. None of them changes anything on your machine.

| you type | you get | lines |
|---|---|---|
| `teyla` | a welcome: what Teyla is, three live numbers, the next three commands | at most 15 |
| `teyla today` | the daily screen: questions waiting by product, the Inbox, the week's spend, one next step | about 25 |
| `teyla help` | the commands in six groups | under 40 |

## `teyla`

```
T█ Teyla 0.30.0
Teyla reads your Claude Code and Codex sessions on your Mac, shows what they
cost and what's waiting on you, and fixes the waste. Nothing leaves your machine.

  $412      spent in the last 7 days       teyla spend
  3         questions waiting on you       teyla asks
  2         notes in your Inbox            teyla notes --inbox

Next
  teyla start  Find where the money goes, and fix it one change at a time
  teyla today  What waits on you, the Inbox and the week's spend
  teyla help   Every command, in groups
```

- **No sessions on the machine:** one line says so ("Use Claude Code or Codex for a day, then run
  `teyla start`") instead of the numbers, and `teyla start` comes first.
- **The first next command** is `teyla start` until you have applied or declined an offer: there is a change in
  `~/.teyla/changes.jsonl`, or a finished `teyla start` is on record. After that it is `teyla today`, then `teyla spend`
  and `teyla help`.
- **One more line** appears while `teyla start` has offers with a dollar saving that are not in force: "2 changes could
  save about $120-$240 a month".
- **It is fast and it never fails.** The call takes tens of milliseconds. A failure inside it still prints the header and
  the way on. It never ends in an argparse error or a traceback.

### Which numbers are cached

Counting spend means reading every session of two weeks (5 seconds to a minute), so the welcome never counts. It reads
`~/.teyla/first-screen.json`.

| figure | source | how stale it can be |
|---|---|---|
| spend, last 7 days | cache | A cache older than 10 minutes starts one background refresh (`teyla today --refresh-cache`, at most once per 5 minutes). Shown with "as of 3h ago" once older than 6 hours. Not shown after 7 days. |
| questions waiting | cache | Same rules. `teyla today` and the refresh store it. |
| notes in the Inbox | read now | Not stale. One small file. |
| "could save" line | `~/.teyla/start-report.json`, written by `teyla start` | As old as the last `teyla start`. |

With sessions but no cache yet, the welcome says "counting now" for the two cached rows and starts the count.

## `teyla today`

```
Today  Sun 25 Oct

Waiting on you: 8 questions in 3 products
  Atlas  5 waiting  [building]
    a1b2c3d4   9d critical  Which signing key should the release use?
    e5f6a7b8   4d  Dark icon or light icon?
    c9d0e1f2   2d  Rename the onboarding screen?
    +2 more
  Cellar  2 waiting
    ...
  +1 more in 1 other product: teyla asks

Inbox: 2 notes with no product yet  teyla notes --inbox
    n4k2xq7   2d  Try a dark icon
    n8m3zr2   5d  Ask about the export format
Spend: $412 in the last 7 days, $380 in the 7 before (+8%). API list price.

Next: Answer the oldest critical question: Atlas, 9d old.
      teyla asks --product atlas
```

- **Waiting on you.** Products in the order `teyla asks` uses: `focus` products first, then by the oldest question,
  `unassigned` last. Inside a product the critical questions come first (`asks.is_critical`: a blocked session, or a
  security, money or release-failure matter), then the oldest. At most 3 per product, then "+N more". About 11 lines in
  all; what does not fit is counted on the last line. Parked products stay quiet, as in `teyla asks`.
- **Inbox.** Notes with no product yet: the count and the newest 3. `teyla note link <id> <product>` files one.
- **Spend.** The last 7 days against the 7 before, at API list price (a subscription bills differently), with the change in
  percent. No percentage when the week before cost nothing. It comes from the cache above. With no cache at all, the text
  screen counts once in the foreground and says so on stderr; `--json` never waits and reports `"spend": null`.
  `--fresh` counts again.
- **Next: the suggestion rule.** One action, the first that matches:

  1. **An offer.** The offer from `teyla start` with the biggest dollar saving that is not in force. Offers with no dollar
     figure never win this step. Command: `teyla apply <id>`.
  2. **A critical question.** Else the oldest waiting question that is critical. Command: `teyla asks --product <id>`.
  3. **The Inbox.** Else the Inbox, when it holds a note. Command: `teyla notes --inbox`.
  4. **A question.** Else the oldest waiting question. Command: `teyla asks --product <id>`.
  5. **Nothing.** Else "Nothing needs you today."

  The rule lives in `today.suggest`; a test per branch keeps the text and the code together.

### `teyla today --json`

For the Mac app and the web page. `version` is 1.

```json
{"version": 1, "generated": "2026-10-25T12:00:00Z", "sessions": true,
 "questions": {"waiting": 8, "products": [
   {"product": "atlas", "name": "Atlas", "stage": "building", "focus": true, "count": 5,
    "asks": [{"id": "a1b2c3d4", "age_s": 777600, "critical": true, "question": "Which signing key ...", "link": "claude://..."}]}]},
 "notes": {"inbox": 2, "newest": [{"id": "n4k2xq7", "text": "Try a dark icon", "created": "2026-10-23T09:00:00Z", "age_s": 172800}]},
 "spend": {"this_week": 412.0, "last_week": 380.0, "change_pct": 8, "as_of": "2026-10-25T11:58:00Z", "source": "cache", "note": ""},
 "suggestion": {"kind": "critical", "text": "Answer the oldest critical question: Atlas, 9d old.", "command": "teyla asks --product atlas"}}
```

`questions.products[].asks` lists every waiting question of the product, critical first; the text screen shows three.
`spend` is `null` when no count exists yet; `source` is `cache` or `fresh`; `note` is "as of 3h ago" for an old figure.
`suggestion.kind` is `offer`, `critical`, `inbox`, `question` or `none`.

## `teyla help`

Six groups: Start, Daily, Products, Spend, Setup, Advanced. The short help names the commands you will use first and
counts the rest. `teyla help --all` lists every command with one line each. `teyla help <command>` and
`teyla <command> --help` print one command's own options, as before.

Every command is in exactly one group (`src/teyla/helpgroups.py`). A test fails when a command is registered without a
group, or listed twice.

A word that is not a command prints "Unknown command 'spnd'. Did you mean 'spend'?", then the help, and exits 2. A missing
optional package or an unreadable file under `~/.teyla` prints one line with the fix. `TEYLA_DEBUG=1` brings the traceback
back.

## Colour

Colours are the brand's (`docs/BRAND.md`, `src/teyla/brand.py`): the mark is a bold `T` in the primary colour and an amber
`█`; amber also marks what waits on you, green a saving. `NO_COLOR`, `TERM=dumb` and output that is not a terminal give
plain text with no escape codes.

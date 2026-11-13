# Operating

One section per operating piece. Each piece reports; none changes anything on its own.

## Outcome scoreboard

`teyla today score` shows outcomes, not agent output: two-way conversations, testers who reached first value,
posts published and the decisions waiting on you. One screen of about 20 lines. `--json` prints the same
facts (`version`, `generated`, `week`, `start`, `end`, `metrics`, `hard_dates`).

```
teyla today score               # the screen
teyla today score --json        # for the weekly brief and the apps
teyla today score --refresh     # run the live `teyla testflight` check first (network)
```

The week is the ISO week, Monday to Sunday, in local dates. The command writes no file and makes no network
call. `--refresh` is the one exception: it asks App Store Connect through your release tool, as `teyla
testflight` does, and honours safe mode (`--allow-network`).

Every metric is `{value, source, reason?, ...}`. A number with no source prints `not_measured` and one line
saying what is missing.

| metric | what it counts | source |
|---|---|---|
| `posts_published` | posts you recorded this week | growth ledger |
| `sale_attempts` | posts, marketing and ICP meetings; `breakdown` has the three | growth ledger |
| `conversations` | calls, meetings and ICP meetings you logged; `replies` is an extra field; `with_next_step` is `not_measured` because the ledger keeps no owner or date per conversation | growth ledger |
| `first_value` | per focus product, installs with a successful usage `task` event named by the product's `first_value` | usage capture |
| `open_decisions` | open questions not muted and not reminders or reports; `oldest_days`, `over_14_days`, `by_age`, `critical`; `design_picks` lists open design cards with their age; `decision_minutes` is `not_measured` | asks, design cards |
| `builds_to_try` | platforms where the newest upload is under 7 days old and installable | `~/.teyla/testflight.json` |

Notes:

- A usage batch carries an install id, not a tester id. `first_value` counts installs (devices), not people.
- Set the focus products with `teyla product core <id>` and the task with
  `teyla product set <id> first_value=<task>`. The task is the `id` of a usage `task` event.
- Teyla records no verdict on a build. A build stays in `builds_to_try` until its upload is a week old.
- `teyla testflight` (also `--json` and `--quiet`, the daily routine's form) writes the cache. Older than 48 hours,
  it is still shown and marked stale.

### Today on the iPhone (Lab)

Settings > Lab > Today screen replaces the Home tab with three things: the top 3 decisions, the post card and builds to try.
Off keeps Home. "Stack" lists the three groups. "One next thing" puts one large card first (the oldest blocked decision,
else the post card when a post is due, else the newest build, else the top decision) and the rest below it, small.
The Mac adds `today.builds_to_try` to the relay snapshot from the same cache as the scoreboard row above: it reads
`~/.teyla/testflight.json`, makes no network call and writes nothing. A count you cannot measure arrives as
`not_measured` with a reason, and the phone prints the reason instead of a zero. An older Mac sends no `today`; the
phone says so in one line. Builds have no tap: Teyla holds no link that opens TestFlight on one build.

### Dates

Optional goals with a deadline go in `~/.teyla/config.toml`. The scoreboard prints the days left for each.
With no table, the block is left out.

```toml
[dates]
launch = "2027-03-01"
race = "2027-04-18"
```

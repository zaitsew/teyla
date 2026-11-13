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

### Dates

Optional goals with a deadline go in `~/.teyla/config.toml`. The scoreboard prints the days left for each.
With no table, the block is left out.

```toml
[dates]
launch = "2027-03-01"
race = "2027-04-18"
```

## Sprint slots

`teyla brief slots` shows the two sprint slots and what holds them. It warns at a third sprint. It refuses
nothing: no hook, and the exit code is 0.

```
teyla brief slots               # the screen
teyla brief slots --json        # version, generated, limit, in_flight, over_limit, slots, no_contract
```

A sprint holds its slot from its contract (`teyla brief <product> --goal ... --usd N --hours N`) until you
close it. A build waiting for your verdict still holds the slot. A contract past its hours stays counted and
shows `overdue`, with the hours elapsed against the budget.

Each slot lists what it waits at, first match first, every match shown:

| waits at | source |
|---|---|
| `gate` | the contract's `--gate` list |
| `decision` | open design cards for the product, with their age |
| `question` | open asks for the product, not muted: count, oldest age and title |
| `build` | builds to try for the product, from `~/.teyla/testflight.json` |
| agents working | none of the above |

With three or more open contracts the screen prints a `WARN` line and `over_limit` is true. The limit is two.
Set another with `[slots] limit = N` in `~/.teyla/config.toml`.

"Also active, no contract" lists products with a session in the last 24 hours and no open contract. Bug-fix
sessions may run outside the limit, so they never trigger the warning. The list carries the command that opens
a contract so the slot is counted.

The command reads local files only. It writes nothing and makes no network call.

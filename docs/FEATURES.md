# Packs: Teyla as a kit

Teyla does many jobs. You need some of them. A **pack** is one job: the problem, what Teyla does about it,
and the settings, hooks or jobs it takes. `teyla start` opens with a checklist of the packs, and only the ticked
ones are turned on.

```bash
teyla features                  # every pack: ● on  ◐ partly  ○ off, and a problem seen on this Mac
teyla features on load disk     # turn packs on; each change is shown first and asked (--yes, --dry)
teyla features off load         # switches off, O1 to O4 undone (--quiet: and never remind me)
teyla features choose cost load # record the checklist answer, change nothing else
teyla features --json           # the same list, for an AI agent
```

## The packs

**Automatic** packs change settings, hooks or launchd jobs, so they work without you.

| Pack | Problem | What turns on |
|---|---|---|
| `cost` Token cost | Long sessions re-read their whole context every turn; subagents run on the top model. | O1 to O4 (`autoCompactWindow`, Sonnet subagents, a Haiku `scout`, Codex medium effort) and `hooks.context_budget` |
| `load` Machine guard | Parallel agents boot simulators and builds until the Mac swaps, hangs or panics. | `guard.enabled`, `guard.agent` (a launchd agent, every 60 s) and the plugin's admission hook |
| `disk` Disk cleanup | Worktrees, DerivedData, simulators and caches fill the disk. | `storage.sims_agent` (every 10 min) and `storage.sweep_agent` (hourly) |
| `inbox` Questions and ideas | A session ends on a question and nobody reads it again. | O6 (hooks and the plugin) and `intent.enabled` |
| `policy` One policy | Each agent has its own rules, so a correction made in one is unknown to the next. | O5 (`teyla policy sync`) |
| `daily` Morning check | Nobody runs the checks, so a broken hook goes unseen for weeks. | O7 (a daily and a weekly launchd job) |

**Toolkit** packs install nothing. Their commands work on any repo when you call them; choosing one records
that you use it.

| Pack | Problem | Commands |
|---|---|---|
| `security` Security | A secret or a private name ends up in a commit, a PR or a public repo. | the plugin's leak guard, `leak install`, `shield`, `deps`, `hosts`, `mcp probe` |
| `design` UX and UI | Screens ship with noise, weak hierarchy and unreviewed copy. | `ux check`, `ux judge`, `ux shots`, `taste`, `kit` |
| `ship` Ship and test | A build is uploaded but no tester can install it; PRs merge unreviewed. | `portfolio`, `testflight`, `play`, `reviews`, `review`, `productize` |
| `writing` Writing | Replies and docs are long and padded; a README describes last month. | `prose`, `voice check`, `docs check`, `lang`, `copy` |

A pack is **on** when every part that applies on this Mac is in place, **partly** when some are. A switch whose
default is already the pack's value (`guard.enabled` is true out of the box) counts only once you set it, so a
fresh Mac reads "off" for a guard that runs nowhere.

## The checklist

`teyla start` prints the summary card, then the checklist. The packs already on, the packs whose problem was
seen here, and on a first run `cost` and `inbox`, start ticked. Type numbers to switch boxes, Enter to go on.
Teyla then asks the offers of the ticked packs one at a time, then the rest of each ticked pack.

Teyla's Claude Code plugin carries the hooks of several packs. When a pack is left out and still off, Teyla
writes its quiet value while the key is at its default: `guard.enabled = false` for `load`, `intent.enabled =
false` for `inbox`. A key you set yourself stays as it is.

## Reminders

`teyla doctor` adds one `feature:<pack>` row (WARN) when a pack is not on, is not muted, and its problem shows up:

| Pack | Seen when |
|---|---|
| `load` | doctor's `machine:crash` warns (a kernel panic or a watchdog reset), or `machine:load` is CRITICAL |
| `disk` | doctor's `storage:disk` warns: free space under `guard.disk_warn_gb` (25 GB) |
| `cost` | the last `teyla start` priced up to $20 a month or more of token waste in O1 to O4 |
| `inbox` | 3 or more questions wait on you (the first-screen cache) |

The session-start banner shows a new row once, for example
`teyla: new — feature:disk WARN: the disk is down to 9.1 GB free; the Disk cleanup pack is off`.
The row's fix is `teyla features on <pack>`; `teyla features off <pack> --quiet` stops the reminder for good.
The reminders read files Teyla already keeps; nothing leaves the machine.

## Settings

```toml
[features]
chosen = ["cost", "load"]   # ticked in the checklist, or turned on since
muted  = []                 # packs that never remind
```

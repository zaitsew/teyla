# The console: Teyla's admin sections

Status: 2026-11-04. The Mac and iPhone apps become one admin for a solo founder's development,
products and go-to-market. This file is the data contract every section follows.

## Seven destinations

The same words on both devices. Each screen answers one question and leads with one number.

| Section | The question | The number |
|---|---|---|
| Home | What needs me now? | Decisions due |
| Decisions | What can only I answer? | Open decisions |
| Products | Which product gets the next push? | Products nobody has tried to sell yet |
| Growth | Did every channel get its post today? | Posts today against the target, and qualified conversations this week |
| Money | What leaves my accounts? | Forecast cash per month, kept apart from list-price equivalents |
| Operations | What failed or needs capacity? | Unresolved failures |
| Playbook | What have we learned and standardized? | Unresolved contradictions |

Settings sits at the foot of the sidebar. The phone shows Home, Decisions, Products, Growth and More.
A CLI command does not get its own screen. Model news, quotes and CPU graphs are parts of a screen.

## Data

`teyla console [SECTION] --json` returns one object per section. A failing source gives that section
`{"error": "..."}`; the others still load. The cache is `~/.teyla/console-cache.json`, mode 0600.
`teyla state` carries the compact part under `console`, so the phone reads it through the relay.

Every section has `headline: {label, value, detail}`. Numbers are never invented: an unknown value
is `null`, and the screen shows a dash with the reason. List-price figures are always labelled.

### operations (`console_operations.py`)
- `machine`: `verdict`, `reason`, `ram_gb`, `swap_used_gb`, `swap_total_gb`, `compressor_gb`, `pressure`,
  `disk_free_gb`, `disk_total_gb`, `cpu_load`, `cores`, `sims`, `builds`, `agents {claude, codex, grok}`, `lanes`,
  `top [{name, gb}]`, `series {disk [], swap []}` (24 h, `[epoch, GB]` pairs, at most 96).
- `leave`: `ok`, `blockers []`. Can the owner close the lid and go: the machine is not WORSENING or CRITICAL, the disk is
  over the guard's critical line, and no headless agent lane or build is running. `ok` is `null` when the machine
  could not be read.
- `failures [{title, detail, severity, product, kind, action}]`, from `attention`, offline. The headline counts those with
  severity `act`; `info` rows are sources that are old or unread.
- `schedules`: `counts {attention, ok, other}`, `rows [{source, name, state, cadence, last_run, note}]`, worst first.
- `harnesses [{name, installed, version, policy, note}]` (`policy`: `synced`, `not wired` or `null`), and
  `policy_sync {status, drift [], inbox, repos {ok, differ, missing, none, to_fix []}, last_sync}`: `drift` lists the
  generated `~/.codex/AGENTS.md` and `~/.grok/AGENTS.md` that differ from what `teyla policy sync` would write, `inbox`
  the hand edits waiting for review, `repos` the AGENTS.md / CLAUDE.md pairs.
- `security {shield_issues, leak_findings, deps_vulns, unreviewed_prs, as_of {leak, deps, reviews}, notes []}`, from the
  last cached `teyla leak --published`, `teyla deps --all` and `teyla reviews` runs. `shield_issues` stays `null`: shield
  keeps no result between runs.
- `notes {part: reason}`: a part that failed or was late is `null` and says why here; the others still load.
- `compact`: the headline, `machine {verdict, disk_free_gb}`, `leave_ok` and the top three failures.

### money (`console_money.py`)
- `subscriptions [{name, monthly_usd, category, renews, credits_usd, note}]`, from the owner's
  `~/.teyla/subscriptions.toml`. Bills not listed there are `null`, never estimated.
- `spend {days7, days30}`, each `{list_usd, billed_usd}`, plus `by_product []`, `by_model []`, `by_day []`.
- `credits []`, `cloud []`, `actions {minutes_used, minutes_included}`.

### playbook (`console_playbook.py`)
- `guidelines [{id, title, path, updated, summary}]`: design standard, writing, voice, policy.
- `models`: `ladder []`, `new []`, `drift []`, `arena {as_of, url, top []}`. A ranking is a shortlist,
  never an automatic switch.
- `knowledge {wiki, intent, corrections, taste}`.
- `you {quotes [{text, date, product}], insights [{label, value, detail}], postcard {then, now},
  delegation [{chore, count, last, path, who, status}]}`. Local only. It stays off the relay unless the owner turns it on.

### growth (`growth.py`)
- `target {posts_per_day_per_channel}`, `today [{platform, language, posted, target}]`, `last_public_days`, `pipeline {ideas, filming, cutting, review, ready, live}`, `episodes []`, `next_ride`,
  `trends [{title, score, hook, source, url}]`, `outreach {drafts, sent_week, replies_week, calls_week, sources []}`,
  `ads []`, `channels [{platform, language, connected, last_post}]`.
- Stored in `~/.teyla/growth/`, never in a repo.

### products (in `teyla product show`)
- `sale_attempts {posts, marketing, icp_meetings, last}` per product. Zero attempts means "not tried yet".
  That product gets the next marketing slot. Teyla never proposes closing a product nobody tried to sell.

## Limits every section keeps

- Teyla publishes only what the owner approved, and it never sends a DM or cold email by itself:
  platforms ban automated DMs, likes and follows, and cold-email law varies by country.
- Anything that starts a charge needs the owner's explicit yes, with the price.
- A new network call needs a row in `docs/PRIVACY.md`.
- The phone's snapshot stays small: `compact()` per section, and no quote or draft in it unless asked for.

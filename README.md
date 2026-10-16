# Teyla

**A local-first toolkit for working with AI agents.** It cuts token spend, keeps your Mac standing while a dozen agents build on it, and gives Claude Code, Codex, Grok, Hermes and Cursor one policy and the same skills and hooks, so you can switch harness without losing your rules. It also takes an app from a tool for one person to a build on someone else's phone (iOS / App Store, Android / Google Play, web), runs routines under guardrails, and makes corrections stick.

Teyla reads the transcripts already on your disk, and no data leaves your machine. Every outbound call (release checks, self-updates, `gh`, the model catalogue, the platform probes) is listed in the network table of [`prompts/onboard.md`](prompts/onboard.md), and safe mode refuses each one unless you pass `--allow-network`.

## Spend fewer tokens

Agent work gets expensive through a few habits that usage dashboards do not name: subagents that silently inherit the top model, build lanes that drift up to Opus, sessions that re-read 300k tokens of context on every turn, and a headless loop that calls a model 500 times a day. Teyla puts a dollar figure on each, at API list price, and names the fix.

```bash
teyla spend --days 7              # what the week cost, and which part bought nothing (W1–W8, each with a fix)
teyla spend --by-day              # per day: subagent cost by model family; Opus creeping into build lanes shows here
teyla lanes --days 7              # per subagent type and model: turns, peak context, dollars, review P1s per unit
teyla monitor --days 30           # tokens by model and project, cache-read ratio, giant sessions, headless calls, with advice
teyla grok-cost --last --cwd .    # what the Grok lane that just ended cost
```

- **Budgets that speak up.** `teyla spend --alert` runs daily: a session over `spend.alert_session_usd`, a project or a whole day over its budget, a product API spike. The first line shows at the next session start, with the top three sessions and the top model.
- **One model ladder, read by every harness.** `~/.agents/POLICY.md` says which model orchestrates, which does volume and which triages, and every harness gets the same copy ([The policy](#the-policy)). The advice flags the drift: subagents inheriting the parent model (A1), output on the top tier (A2), lanes that name the top tier explicitly (A20), and Opus past `spend.opus_share_max` in the weekly digest.
- **New models, cheaper models.** `teyla models watch` says when a provider ships a model worth moving to, the ladder entry it would replace and its price, and which repos still name a superseded id in live code.
- **Context that stays small.** Advice A3/A4 catch giant sessions and a high cache-read ratio. The opt-in `context-budget` hook has the model write a handoff before Claude Code compacts, and puts it back afterwards.

## Keep the machine alive

Every agent on a laptop shares one CPU, one RAM and one swap file, and none of them sees the others. Ten sessions that each boot "just one" simulator and run "just one" build fill swap together, and the kernel panics. Teyla is the scheduler they are missing.

```bash
teyla load                                          # OK / BUSY / CRITICAL: RAM, swap, compressor, load, disk, sims, builds, agents
teyla load --wait --kind build && xcodebuild ...    # wait for a free slot instead of piling on
teyla config set guard.agent=true && teyla routine install   # the every-minute guard: alerts, load records, idle Gradle daemons stopped
teyla storage                                       # worktrees, build output, caches and simulators holding disk and RAM
teyla crash                                         # after a panic: what the machine looked like in the 30 minutes before
```

- **Admission control, on by default.** The plugin's machine guard asks `teyla load --admit` before a command that starts heavy work: `xcodebuild`, `swift build`, `gradle`, `simctl boot`, `codex exec`, `claude -p`, `grok -p`. While the Mac is overloaded, or `guard.max_builds` / `max_sims` / `max_lanes` are reached, the call is refused with the numbers and what to do instead. It fails open and costs about 3 ms on an ordinary command. `teyla harness sync` wires it into Codex and Grok too.
- **The guard tick.** Once a minute: a row in `~/.teyla/load.tsv`, an alert at the next session start and one macOS notification while the machine is CRITICAL, idle Gradle and Kotlin daemons stopped, and a temp sweep when free disk runs low (APFS swap shares the disk).
- **Cleanup agents.** `teyla storage sims --reap` shuts down idle simulators, `storage procs --kill` stops dev servers and builds whose worktree is gone, `storage sweep` removes what agents leave behind (DerivedData, temp builds, caches, old logs). Each checks age and running processes first, and each has a dry run.
- **Forensics.** `teyla crash` reads the kernel panics, watchdog resets and jetsam events, and lines each up with the load records from just before it, with advice computed from those numbers.

## Switch harnesses without losing your setup

Your rules, skills and hooks usually live in one harness. Move a project from Claude Code to Codex, hand a lane to Grok, or open it in Cursor, and the model there has never heard of them. Teyla keeps one source and renders it into each harness in the form that harness reads.

```bash
teyla policy sync        # ~/.agents/POLICY.md + your own rules → Claude Code, Codex, Grok, Hermes, Cursor
teyla harness sync       # the plugin's skills and hooks (machine guard, correction capture, session start) into the others
teyla harness status     # what is wired where
teyla harness verify --live   # can each harness do work now: version, auth, last quota error, one live call that checks the policy arrived
```

- **One policy, five copies.** `~/.agents/POLICY.md` is imported by `~/.claude/CLAUDE.md` and generated into `~/.codex/AGENTS.md`, `~/.grok/AGENTS.md`, Hermes' `SOUL.md` and a Cursor skill. A rule someone adds to a generated copy from inside Codex is filed in `teyla policy inbox` before the next sync, never silently overwritten.
- **The same skills and commands.** `/teyla:rule` and `/teyla:correct` become `teyla rule` / `teyla correct` for harnesses with no slash commands, and per-repo rules go to `AGENTS.md` as well as `.claude/rules/`.
- **One report across all of them.** `teyla monitor` and `teyla spend` read the sessions of every harness, so a lane that moved harness still shows up in the week's numbers (Cursor's store has turns and models but no token counts).
- **Harnesses you do not use stay out of the way:** `teyla config set harness.disabled=hermes,grok`. What each harness can and cannot do is in [docs/HARNESSES.md](docs/HARNESSES.md).

## Ship apps to a person: iOS, Android, web

A tool built for one person becomes an app for four only when it has accounts, per-user data, a backend off the laptop, a way onto other people's phones, and a build that actually reaches them. Teyla checks each of those from a `[productize]` block in the repo's `teyla.toml` and from one manifest of the resources you buy once.

```bash
teyla productize --owner-steps   # every product against R1–R10, then one numbered list of what only you can do
teyla platform                   # shared resources: secrets, server, domain, identity, mail, Apple, Google Play, model key
teyla testflight                 # did the newest uploaded build reach the tester, per product and platform
teyla play                       # the same for Android: internal track status and closed-test age on Google Play
teyla scaffold ~/repos/app --name app --kind ios   # a repo born with a release doc, check.sh, .env.example and teyla.toml
```

- **One primary platform (R10).** Each product names a `primary` platform, and every other platform needs a dated trigger in `[productize.triggers]`, such as `android = "2026-10-06: two testers have no iPhone"`. Secondary platforms catch up in parity trains from the `synced-to` commit in `docs/PARITY.md` (policy; no command reads that file yet).
- **iOS and the App Store.** `teyla platform` checks the App Store Connect API key (three ids in `~/.appstoreconnect/config.env`, the `.p8` at mode 600) and that your upload tool (`[apple] release_tool`) is executable. `teyla testflight` asks that tool whether `[apple] tester` can install the newest build, and exits 1 while one is behind. The daily routine runs it, and the session banner names a build that never reached anyone. `scaffold --kind ios` writes `docs/RELEASE.md`: releases go through the API key, never the Xcode GUI or a password.
- **Android and Google Play.** `teyla platform` checks the Play Console account and the upload keystore (back it up: it cannot be regenerated). R4 accepts `play-internal` or `play` as Android's distribution path. A personal Play account needs a 14-day closed test before production, so the policy starts it the day the Android trigger fires. `teyla play` is the Play twin of `testflight`: it asks your Play tool (`[android] release_tool`, run as `<tool> status --package ID --json`) for each product's `[release] android_package`, and reports the newest version code on the internal track with its release status (a draft or halted release is a problem: testers cannot install it; a first draft is flagged as possibly in Google's review, which the API does not expose), what production serves (version code, status, rollout fraction; `completed` there does not prove Google's review passed), and whether a closed test is live. The 14-day closed test is a personal-account rule: set `[android] account = "organization"` and a missing closed test is never a problem, and a personal account stops needing it once production is live. Internal older than production is a problem. It exits 1 while a product is behind, and the daily routine runs it into the banner and the digest like `testflight`.
- **Distribution off the laptop (R4).** Each platform has its bar: TestFlight or the App Store for iOS and macOS, Play for Android, the Chrome Web Store for an extension, the Connect IQ store or Garmin Connect for a Garmin watch.
- **The rest of the gap.** R1 accounts instead of a shared key, R2 per-user rows, R3 a backend that is not your Mac, R5 a getting-started page, R6 secrets named in `.env.example`, R7 a cost cap on a metered model key, R8 a real mail sender for a public target, R9 a first screen that signs in and never shows sample data as the user's own. `templates/platform/` provisions the shared server: a droplet, Caddy, one site per product.
- **Release cadence.** The policy's platforms section: at most one internal upload per app per day, one version in review at a time, and a store at most two weeks behind the build the owner uses. More in [Productizing](#productizing) and [docs/PRODUCTIZE.md](docs/PRODUCTIZE.md).

## Routines, rules and the rest

- **Is the automated half running?** `teyla routines` and `teyla schedules` check every launchd job, cron line, desktop task and scheduled workflow against its last run ([Routines and checks](#routines-and-checks)).
- **Corrections that stick.** The plugin captures correction-shaped prompts and turns repeats into rules ([The plugin](#the-plugin)).
- **Review debt.** `teyla reviews` matches merged PRs against the review ledger.
- **Runs with guardrails.** `teyla run product:routine` runs a routine under capability grants (`fs.write:<glob>`, `shell:<verb>`, `net:<host>`, `send:<channel>`), caps and an idempotency key. It stops at a gate for your approval in `teyla inbox` and leaves a receipt. `teyla kill on` stops every run and denies every tool call. A routine earns gate B or C with ten consecutive clean receipts (`teyla promote`). See [docs/CONTROL-PLANE.md](docs/CONTROL-PLANE.md).
- **Cloud sessions.** `teyla cloud check|prep|inbox`: what a cloud VM lacks in each repo, the files that give it your shipping rules, and the branches it left with no PR ([Cloud sessions](#cloud-sessions)).
- **Connectors and plugins.** `teyla connectors` shows, per MCP server, reads and writes, the empty and error rate, and the round-trips between human turns (advice C1–C4). `teyla plugins` runs a skill / rule / fact quality pass over installed Claude Code plugins.
- **Clean instruction files.** `teyla tidy` finds duplicates, dead imports and stale dated lines in rule and memory files. `teyla lang` keeps a repo's prose in English and leaves localization alone. `teyla rules stale` lists rules that expired or never fired. Every rule and policy write refuses invisible characters (bidi controls, zero-width, tags).
- **A facts wiki.** `teyla wiki` keeps facts as plain markdown pages that the agent writes and you confirm ([docs/WIKI.md](docs/WIKI.md)).
- **Maintains itself, and leaves cleanly.** `teyla update` installs new releases, `teyla routine catch-up` runs the daily or weekly job launchd skipped while the Mac was off, `teyla remind` keeps dated to-dos only you can act on, and `teyla uninstall` reverses every file Teyla wrote.
- **An adoption report.** `teyla monitor` also reports correction rates and repeated corrections, and `--share` writes a redacted version (pseudonymous projects, connectors and private skills; no session ids, paths or correction text).

## Install

```bash
uv tool install git+https://github.com/zaitsew/teyla      # or: pipx install git+https://github.com/zaitsew/teyla
teyla policy init --owner "Your Name" && teyla policy sync   # one POLICY.md (+ your CLAUDE.md rules) → Claude Code, Codex, Grok, Hermes, Cursor
teyla plugin install zaitsew/teyla   # the Claude Code plugin with the machine guard (or: claude plugin marketplace add zaitsew/teyla)
teyla harness sync                   # the same skills and hooks in Cursor, Codex, Grok and Hermes
teyla routine install                # daily: update, doctor, policy sync, spend alert; weekly: monitor, routines, products, models
teyla doctor                         # everything that must be true here, and the fix for each thing that is not
teyla spend --days 7 && teyla load   # the two numbers to look at first
```

After that it keeps itself current: `teyla update` (run daily by the routine, and at session
start by the plugin hook on machines where launchd is off limits) installs a newer published
release by its commit sha and checks the version it built (`update.pin` freezes it,
`update.channel=none` stops the routine),
merges template changes into your `POLICY.md` three-way so your edits survive, refreshes the
plugin copy Claude Code actually loads, and rewrites the launchd wrappers if the binary moved.
`teyla doctor` is the checklist; what is *new* in it shows at the next session start, and
once a week the digest names the three things worth doing (see [What gets read](#what-gets-read)).

**On a work laptop** (a managed Mac, a TLS-inspecting proxy, the employer's code in every transcript), switch on safe mode first:

```bash
uv tool install "teyla[work] @ git+https://github.com/zaitsew/teyla"   # [work] = truststore: the OS keychain holds the proxy's root CA
teyla policy init --work --owner "Your Name" && teyla policy sync     # approved providers only, same-provider reviews; sets safe.enabled=true
teyla config set products.repos=<repo>,<repo>                          # the only repos whose ./check.sh usage Teyla may run
teyla doctor                                                           # first line: safe: on (network off, no auto-update, no repo commands)
```

Safe mode (`teyla config set safe.enabled=true`, or `TEYLA_SAFE=1`): nothing reaches the network unless you pass `--allow-network` to the command you typed (`teyla update --allow-network`); the session hook and the daily routine never update Teyla (unless you opt in with `teyla config set safe.auto_update=true`: then the daily `teyla update --quiet`, and only it, may fetch the latest published release; a pin still freezes it, and the plugin's `/plugin` lines stay yours to type); `teyla products` runs `check.sh` only in `products.repos`; `routines --issues` is refused; `teyla plugin install|refresh` print the `claude plugin ...` commands instead of editing Claude Code's plugin registry (with `update.pin` set, the plugin is added at the same tag: `zaitsew/teyla#v<pin>`); no keychain query. [`docs/WORK.md`](docs/WORK.md) is the page for a work laptop: what safe mode guarantees, how to move to a new release, daily use.

No `uv`? `pipx install git+https://github.com/zaitsew/teyla`, or `git clone` and run `PYTHONPATH=src python3 -m teyla`. Python 3.11+, nothing else.

**Handing it to a second machine:** [`docs/HANDOVER.md`](docs/HANDOVER.md) lists every practice that travels and what to adapt; [`prompts/work-account-kickoff.md`](prompts/work-account-kickoff.md) is the paste-able version; [`prompts/work-account-update.md`](prompts/work-account-update.md) updates a machine that already has Teyla and switches on its self-maintenance. **Handing it to an agent instead of a person:** paste [`prompts/onboard.md`](prompts/onboard.md) into Claude Code, Codex or Grok on the new machine. It installs, wires the policy, installs the plugin, runs the first review, and produces the feedback file. Corporate machines: no data leaves the machine; every network call (release checks, the daily self-update) and every file Teyla writes are listed there, and `teyla uninstall --dry` lists what is on this machine (`teyla uninstall` reverses it). `teyla prompt onboard` prints the copy that shipped with the installed version.

## Commands

### Tokens and spend

| command | what you get |
|---|---|
| `teyla spend [--days N] [--json]` · `--alert` | what the last N days cost at API list price and which part bought nothing (W1–W8, each with a fix). `--alert` is the daily check: a session over `spend.alert_session_usd` in the last day, a project (`spend.budget.<project>`) or the whole day (`spend.daily_budget_usd`) over its budget yesterday, Actions past 80%, a product API spike. Each line names the amount, the budget, the top three sessions and the top model. The current alerts go to `~/.teyla/spend.alert` (removed when there are none), and the session-start banner shows the first line; the same alert is not said again the next day unless it grew by 25% (`--no-write` prints without touching either) |
| `teyla spend --by-day [--days N] [--json]` | one row per day: total cost, subagent cost, and subagent cost/calls by model family (Opus / Sonnet / Haiku / Fable / other), with the top tier's share and Opus's share. Opus and Sonnet are one ladder tier, so only the family column shows Opus creeping into build lanes. Cost is split by the day each message was sent |
| `teyla lanes [--days N] [--project SUBSTR] [--json]` | one row per (subagent type, model) over the transcripts' subagent files: units, median turns, median peak context, median and total dollars, and from the review ledger the units matched to a review (by a commit sha in the lane's transcript), first-round P1 per matched unit and units with at least one P1. P1 per unit is confounded by task difficulty: a prompt to look, not a verdict |
| `teyla monitor [--days N] [--json]` | tokens by model and project, API-equivalent cost, orchestrator-tier share, subagent model mix, correction rate, cache-read ratio, giant sessions, governance-file edits, model ladder/price drift, headless calls per day by harness and project with their cost — plus advice A1–A20, and a "Cloud sessions" section from git |
| `teyla advise` | just the findings, each with the number that triggered it and one action |
| `teyla grok-cost [--last\|--session ID] [--cwd PATH] [--days N] [--by project\|session] [--json]` | what Grok CLI sessions cost at list price, ranked by dollars not tokens. `--last --cwd <repo>` is the one line an orchestrator reads when a `grok -p` lane ends (cost, calls, tokens, cached %, tools, context, effort, title); the default is the last 7 days by project (worktrees and `~/repos/<repo>` collapse to `<repo>`, a `<repo>-grok-empty` temp dir to `<repo>`, other temp dirs to `tmp`); `--by session` is the top 20. `teyla monitor`/`advise` add A13/A14 |
| `teyla models [--days N] \| --json \| --refresh` | credential presence, models available on this machine, newest catalogue entries with cost, and what `~/.agents/POLICY.md`'s ladder names — per provider, plus drift flags; exits 1 on drift |
| `teyla models watch [--refresh] [--json] [--ack [ID...]] [--seed FILE]` | the weekly "did a provider ship something to move to?": models in the catalogue that are not in `~/.teyla/models-known.json` (first run seeds it), the ladder entry each would replace, its price, and which git repos under `code_root` still name a superseded id in live code or config (tests, price tables, docs and changelogs, and migrations are history and only counted on one line); exits 1 while new models are unacknowledged; the weekly routine runs it and the digest names new models |
| `teyla models --write-policy [--dry]` | rewrite the ladder table between `<!-- ladder:start/end -->` in POLICY.md: keep what still resolves, replace what doesn't with the newest of the same family, print the diff |
| `teyla models --write-prices` | `~/.teyla/prices.json` from the models.dev catalogue, tiered from the ladder; `pricing.py` prefers it over its built-in table when present |

### The machine

| command | what you get |
|---|---|
| `teyla load [--json] [--record] [--quiet] [--admit build\|sim\|lane] [--wait --kind KIND]` | how loaded this Mac is right now, from one `sysctl` and one `ps` call (well under 150 ms): RAM, swap, compressor, memory pressure, load per core, free disk, booted simulators, build drivers and the compilers they fan out into, Gradle/Kotlin daemons, Claude Code / Codex / Grok sessions and headless lanes, Chrome, VMs, the top apps by RSS. The first line is a verdict: OK, BUSY or CRITICAL (exit 0, 1, 2), each reason with its number and threshold (`[guard]` in config: `swap_*_pct`, `compressor_*_pct`, `load_*_per_core`, `disk_warn_gb` 25 / `disk_crit_gb` 10 — APFS swap shares the disk, so a full disk hangs a Mac under memory pressure — `max_sims`, `max_builds`). `--admit KIND` is the admission check an agent hook calls: silent exit 0, or a refusal written for an AI agent (why, then reuse a booted simulator, wait, or free capacity) and exit 2; it fails open when `ps` fails or `guard.enabled=false`. `--wait --kind KIND` polls until a slot is free (exit 0) or `guard.wait_timeout_s` (exit 3). `--record` appends a TSV line to `~/.teyla/load.tsv` (bounded to ~2 MB) for crash forensics; `teyla doctor` shows `machine:load` and WARNs at CRITICAL |
| `teyla guard tick [--quiet] [--dry]` \| `status` | the machine guard running by itself: one tick = record a `load.tsv` row, keep `~/.teyla/load.alert` while the verdict is CRITICAL ("machine CRITICAL since 20:21 — swap 11.7 GB = 45% of RAM; … Do not start builds or boot simulators; run teyla load." and the top apps; removed after three ticks below CRITICAL; the session-start hook shows it first while it is under 5 minutes old; one macOS notification per incident, at most every 30 min, none in safe mode), and stop Gradle/Kotlin daemons idle for `guard.gradle_idle_min` (30; 0 = off: no Gradle client running and ~0 CPU; same pid/start-time/command re-check and SIGTERM-then-SIGKILL as `storage procs --kill`; each stop is logged in `~/.teyla/storage.log`), and under `[storage] sweep_urgent_free_gb` (20) free run `storage sweep --temp` itself, at most every 15 minutes (`guard.disk_sweep=false` turns that off). `--dry` changes nothing. It never raises and calls no `simctl` or `lsof`. The opt-in launchd agent `com.zaitsew.teyla.load` runs it every minute: `teyla config set guard.agent=true && teyla routine install` (`teyla doctor` shows `routine:load`; `guard.alert=false` turns the file and notification off). `status` prints the last rows, the alert and the state |
| `teyla storage [--json]` · `teyla storage clean [--apply]` | the disk and RAM agent work holds: every worktree (SAFE = clean, on the remote, idle, no process in it — removed with `git worktree remove`, branch kept), git-ignored build output of idle repos, caches with the command that clears each, booted simulators. Dry run unless `--apply`; `teyla config set storage.auto_clean=true` lets the daily routine do it |
| `teyla storage sims [--reap] [--dry] [--json]` | booted simulators: in use, or idle N min. `--reap` shuts down idle ones (`storage.sim_idle_min` 30, `storage.sim_max_booted` 3) and deletes shut-down devices matching `storage.sim_prune_pattern` (empty = never) after `storage.sim_prune_days` (3). `storage.sims_agent=true` makes `teyla routine install` run it every 10 minutes |
| `teyla storage procs [--kill] [--dry] [--json]` | dev processes an agent left behind whose worktree or temp folder is gone (`xcodebuild`, `swift-build`, `node`/`vite`/`next` dev servers, `python -m http.server`, ... per `storage.orphan_patterns`, matched on the executable or the interpreted script, never on other arguments): pid, RSS, age, command, why. Only the working directory decides that the folder is gone. Yours only, no terminal, running at least `storage.orphan_min_age_min` (30), never this process or its ancestors; when `ps` or `lsof` fails, nothing is an orphan. `--kill` sends SIGTERM, waits 10 s, then SIGKILL to the ones that are still the same process (pid and start time checked again, a kqueue exit watch read right before each signal). `storage.orphan_kill=true` makes the `storage.sims_agent` run it every 10 minutes; `teyla storage` and `teyla doctor` report the RAM they hold |
| `teyla storage sweep [--temp] [--dry] [--json]` | removes what agents leave behind, each category with its own age and process check: temp builds, release leftovers, old simulators, DerivedData, runtime and package caches, Docker, archived Grok sessions, old logs. `--temp` is the hourly subset; `--dry` shows the bytes only. Tuned by `storage.sweep_*` and `storage.docker_superseded_repos`; `storage.sweep_agent=true` schedules it, and the weekly routine then runs the full sweep. Log: `~/Library/Logs/teyla-sweep.log` |
| `teyla crash [--days N] [--json] [--ack]` | after a crash, what happened and what the machine looked like right before. Reads the kernel panics, watchdog resets and jetsam events in `/Library/Logs/DiagnosticReports` (and `Retired/`, and the user folder), newest first, one per incident: `2026-10-09 20:25 kernel panic — Kernel data abort; panicked task simctl (pid 27899); compressor OK, 21 swapfiles; last kext autofs`. The time is the real panic time from the report's epoch block, not the time it was written after the reboot. Under each panic: the `teyla load --record` rows from the 30 minutes before (peak swap, load, compressor, simulators, builds, agents, top apps; or "no load records — the recorder agent was off") and the nearest jetsam event within 2 h with its top apps and kills. It ends with 2–4 lines of advice computed from those numbers (simulators, Gradle/Kotlin daemons, the biggest app, swap over 40% of RAM). An unacknowledged panic or watchdog reset makes `teyla doctor` WARN `machine:crash` (so the session-start banner shows it) and heads the weekly digest; `teyla crash --ack` marks the listed incidents seen (`~/.teyla/state/crash.seen`). Unreadable folders are reported, never a crash |

### Policy and harnesses

| command | what you get |
|---|---|
| `teyla policy init [--claude-md --ops-root-init]\|status\|sync\|sync-repo` | `~/.agents/POLICY.md` imported by `~/.claude/CLAUDE.md`; `~/.codex/AGENTS.md` and `~/.grok/AGENTS.md` generated from POLICY.md + your own rules in `~/.claude/CLAUDE.md` (Codex cannot import a file; a plain symlink while CLAUDE.md holds only the import); appended to Hermes `SOUL.md`; `AGENTS.md ⇄ CLAUDE.md` in repos; `sync --quiet` is what the daily routine runs (silent when nothing changed, never creates POLICY.md or edits CLAUDE.md) |
| `teyla policy inbox [--done FILE\|--all]` | the hand edits `policy sync` found in a generated copy (a rule added to `~/.codex/AGENTS.md` from inside Codex) before it overwrote the copy, newest first with their added-line counts; `--done FILE` deletes one once you moved what should stay into `~/.agents/POLICY.md` or `~/.claude/CLAUDE.md`, `--all` deletes every one. `teyla doctor` warns `policy:inbox` while any wait |
| `teyla policy ack [--note]` · `teyla policy refresh [--dry] [--resolved]` | `ack` records that you reviewed the current `~/.claude/CLAUDE.md` (A10 then flags only later edits); `refresh` merges template changes into `~/.agents/POLICY.md` three-way, so your edits survive |
| `teyla harness status\|sync` | the plugin's skills and hooks, and the policy, in Cursor, Codex, Grok and Hermes — see [docs/HARNESSES.md](docs/HARNESSES.md) |
| `teyla config set harness.disabled=hermes,grok` | harnesses this machine does not use: `doctor`, `harness status\|sync\|verify` and `policy sync` skip them entirely (no health, credit, hook or auth lines), and `doctor` prints one `disabled: hermes, grok` line. Names: claude-code, codex, grok, hermes, cursor; an unknown one is a warning |
| `teyla harness verify [--live]` | can each harness do work now: version, auth (shape and dates, never a secret), the newest quota/auth error it recorded, interactive vs batch sessions in 7 days; `--live` sends one line through `claude -p`, `codex exec`, `grok -p`, `hermes -z` and checks the policy reached it |
| `teyla tidy [paths...] [--json] [--apply] [--quiet]` | the rule and memory files (`~/.agents/POLICY.md`, `~/.claude/CLAUDE.md`, project memory and its `MEMORY.md`, each repo's `CLAUDE.md`, `AGENTS.md`, `.claude/rules/*.md`) checked for exact and near duplicates (also across POLICY.md and CLAUDE.md), dead `@` imports and links, memory files missing from the index or from frontmatter, files over `tidy.max_kb`, whitespace junk, Cyrillic prose in a repo file, and dated "until / for now / TODO" lines older than `tidy.stale_days`; read-only by default, each finding with file:line and a fix. `--apply` fixes only whitespace, blank runs, list tabs and an exact duplicate bullet, after a backup in `~/.teyla/tidy-backup/<date-time>/`; it refuses symlinks and generated files. Code fences (including the `MERGE-APPROVED` list) and `<!-- teyla:protect -->` regions are never touched or reported on. The weekly routine writes `tidy.md`; the digest says "md tidy: N finding(s) in M file(s)" |
| `teyla lang [repo...] [--json] [--quiet] [--commits N]` | the "everything in a repo is English" check: tracked text files (and with `--commits N` the last N commit messages) holding non-Latin script — Cyrillic, CJK, Greek, Arabic, Hebrew — counted by kind (`doc`, `comment`, `string` = "check: localization?", `fixture`, `other`) with the top files and a sample line. Latin-script languages are not detected. Localization paths (`*.lproj`, `*.xcstrings`, `locales/`, `i18n/`, `l10n/`, `translations/`, `*.po`, `*.strings`, `Localizable*`, `messages/*.json`, `strings/*.json`, Android `res/values-*/{strings,plurals,arrays}.xml`), a repo's `.teyla/lang-allow` (the per-repo exemption list: globs, `#` comments, any depth unless it starts with `/`), `[lang] allow` in config (every repo; `teyla config set lang.allow=GLOB`) and the `cyrillic:` section of `.leak-allow` are exempt. Always exits 0 (2 on a usage error); the weekly routine runs it with `--quiet` and the digest names the count |

### Routines, schedules and reviews

| command | what you get |
|---|---|
| `teyla routines [path...] [--json] [--issues]` | every product's `teyla.toml`: routines that must run without you (loaded? last run? stale?) and manual checks you confirm (ok / broken / untested / re-test); `--issues` opens a GitHub issue per broken check |
| `teyla routine catch-up [--dry] [--quiet]` | runs the daily or weekly job when launchd skipped it (the Mac was off at its minute) and repairs the wrappers; `--dry` lists the missed runs. The session-start hook starts it in the background once a day |
| `teyla routine install [--if-stale] [--dry]\|status` | Teyla's own LaunchAgents: the daily one (update, doctor, policy sync, spend alert, schedules, testflight, play) and the Friday 20:45 weekly (monitor, routines, products, models, reviews) filed into a dated folder |
| `teyla play [path...] [--json] [--quiet] [--allow-network]` | did the Android build reach a person (POLICY §11/§14): for each product with a `play-internal` or `play` Android path, or `[release] android_package` in its `teyla.toml`, asks your release tool (`[android] release_tool` in `~/.teyla/platform.toml`, run as `status --package ID --json`) for the newest version code on the internal track and its status, and what production serves (`completed` or `inProgress`, with the rollout fraction), and the closed test (`alpha`) with the days Teyla has seen it live out of 14 (counted from `~/.teyla/play-seen.json`; the API gives no start date; personal accounts only, `[android] account = "organization"` drops the count and the requirement, and a live production release makes it moot for a personal one). Exits 1 while a product has nothing on internal, an internal release that is not `completed` (a first draft says Play Console may show it in review: the API does not expose review state), internal older than production, no live closed test (distribution `play`, personal account, nothing live on production), or could not be read. Network, so safe mode needs `--allow-network`. `--quiet` prints nothing and writes `~/.teyla/play.problems` for the banner and the digest; the daily routine runs it |
| `teyla schedules [--json] [--quiet] [--all] [--allow-network]` <br> `teyla schedules forget KEY [KEY...]` | every scheduled task outside a repo, and whether it ran: Claude desktop scheduled tasks (`~/.claude/scheduled-tasks/*/SKILL.md` against the app's own `scheduled-tasks.json`; a definition the app never registered is UNREGISTERED), launchd agents with a schedule (last exit from `launchctl list`, run times from the plist's log files; disabled and renamed `.bak`/`.disabled` ones too), Claude cloud routines (only as last known from session transcripts) and GitHub `schedule:` workflows (last run via `gh`, not in safe mode), plus the `teyla.toml` routines. Verdicts: OK, STALE, FAILING, DISABLED, UNREGISTERED, MISSING DEFINITION, NEVER RAN, DONE, VANISHED, UNKNOWN. `~/.teyla/schedules.json` keeps every id ever seen, so a task that disappears shows as VANISHED for 30 days. Default output lists what is not OK; `--all` lists everything, `--json` the full list, `--quiet` prints nothing and writes `~/.teyla/schedules.problems` for the banner and the digest (the daily routine runs it). Exit 1 while any task is STALE, FAILING, UNREGISTERED, MISSING DEFINITION, NEVER RAN or VANISHED. `teyla schedules forget KEY [KEY...]` acknowledges a VANISHED task you removed on purpose (a dropped desktop task, a routine deleted from `teyla.toml`): it leaves the registry and the banner the same day. KEY is the id from `--json` (`claude-desktop:my-task`) or a unique name; a task that still exists is refused, since the next run would register it again. `schedules.ignore_prefixes` in the config names vendor launchd labels to skip |
| `teyla testflight [path...] [--json] [--quiet] [--allow-network]` | did the build reach a person (POLICY §11): for each product with a TestFlight or App Store path, asks your release tool (`[apple] release_tool`, `tester` in `~/.teyla/platform.toml`; `[release] apple_bundle_id` in the repo's `teyla.toml`) for the newest uploaded build and the newest the tester can install, one line per platform with what blocks the gap; exits 1 while any is behind, has nothing installable or could not be read. Network, so safe mode needs `--allow-network`. `--quiet` prints nothing and writes `~/.teyla/testflight.problems` (one line per platform behind, removed when all are current) for the banner and the digest; the daily routine runs it |
| `teyla reviews [--days N] [--json] [--quiet] [repo...]` | the review debt: for each repo under `code_root` with a GitHub remote, the PRs merged in the last N days (7) against the review ledger (`review.ledger`, default `~/.cache/review-ledger.tsv`, one TSV line per review: time, repo, commit sha, mode, P1, P2, reviewer): reviewed, merged with an open P1 (the newest reviewed commit still had one), skipped (a `skip` line), exempt (under `review.min_lines` changed lines, or docs only) or unreviewed, with the URL of each PR that needs a look. One `gh` call per repo, none in safe mode (`--allow-network` for one run); the weekly routine files it and the digest names the debt |
| `teyla digest [--write]` | the weekly digest: at most five lines — the top three actions across advice, doctor, routines and checks, each with its command, plus a streak note |
| `teyla check <product> <check> ok\|broken [--note TEXT]` | confirm a manual check: sets `status` and today's `confirmed` in that product's `teyla.toml`, editing only those lines |
| `teyla remind add "<what>" <YYYY-MM-DD> [--how "..."]` \| `list` \| `done <n>` | dated to-dos only a human can act on (a key that expires, a trial that ends); `teyla doctor` shows each as OK, then WARN within 30 days, then FIX once overdue |

### Rules and corrections

| command | what you get |
|---|---|
| `teyla sessions` / `teyla corrections --cluster` | one line per session; correction-shaped turns clustered into rule candidates |
| `teyla rule "<sentence>" [--scope <glob>]` · `teyla correct "<what was wrong>"` | what `/teyla:rule` and `/teyla:correct` do, as a CLI every harness's skill can call |
| `teyla rules propose [--write]` · `teyla rules stale` | a proposed rule diff from human corrections only (hook guesses ignored), hit counts on existing rules; expired and never-hit rules as removal candidates |
| `teyla harvest <path>` | tool spines and corrections from every session that touched a path — the input to the harvest skill (skill = what was done the same way every time; everything else = candidate rules) |
| `teyla wiki init\|status\|lint\|confirm` | the facts store as an LLM-maintained wiki: the agent writes pages, you confirm or correct; works unchanged as a GitLab Wiki |

### Products and the control plane

| command | what you get |
|---|---|
| `teyla platform [init\|env-example] [--json] [--no-net]` | the resources you buy once (secrets, server, domain, identity, mail, Apple, Google Play, model key) from `~/.teyla/platform.toml`, each MISSING row with the URL and the file it goes in; `init` writes the manifest, `env-example` prints the secrets skeleton (names only); exit 1 while one is missing or unreachable |
| `teyla productize [paths...] [--json] [--owner-steps]` | each repo's `[productize]` block against R1–R10 (identity, tenancy, backend, distribution, onboarding doc, secrets, cost cap, mail, first screen, primary platform); `--owner-steps` is one numbered list of what only you can do, platform first; exit 1 while any is unmet |
| `teyla scaffold <path> --name X --kind cli\|app\|service\|ios [--license apache\|mit\|none]` | a repo born plug-and-play: `check.sh`, `.env.example`, `AGENTS.md`, `teyla.toml`, an ADR log, a `workflow_dispatch`-only CI; `app`/`service` add the `[productize]` block, `docs/GETTING-STARTED.md` and droplet fragments; `ios` adds `docs/RELEASE.md` |
| `teyla products` | real-usage counters from every repo's `./check.sh usage` — the "built, not used" detector; `products.repos` in config limits which repos' code it runs |
| `teyla run <product:routine>` | the control plane: grants, caps, idempotency, gates A/B/C, a receipt naming the rules the run obeyed — see [docs/CONTROL-PLANE.md](docs/CONTROL-PLANE.md) |
| `teyla inbox list\|show\|approve\|reject [--note]` | runs that stopped at a gate; `approve` runs the act step under the same grants and writes a linked receipt, `reject --note` records a correction candidate |
| `teyla kill on [--reason]\|off\|status` | the kill switch: `~/.teyla/KILL`, under which `teyla run` refuses and the PreToolUse hook denies every tool call |
| `teyla triggers list\|install [--no-load]\|uninstall <ref>` | clock triggers as LaunchAgents (`com.teyla.<product>.<routine>`) |
| `teyla promote <ref> --gate B\|C [--note]` · `teyla receipts <ref> [-n N]` | earned autonomy: a gate moves only after ten consecutive clean receipts at the current one; the audit trail |

### Cloud

| command | what you get |
|---|---|
| `teyla cloud check [repo...] [--json]` | what a cloud session (Claude Code on the web, `claude --cloud`) would lack in each repo — the VM clones the repo and nothing from your home directory: instructions that defer to a home-directory policy file, `.claude/` git-ignored, no shipping rules or cloud done state, no SessionStart/Stop hooks, a `merge-approved:` line missing or drifted from your list, Mac-only gate steps with no printed skip, secret names with no manifest, a public repo. BLOCK/WARN/OK per item, exit 1 on any BLOCK; `teyla doctor` shows `cloud-ready n/N repos` |
| `teyla cloud prep <repo> [--dry] [--allow-public] [--fix-gitignore]` | writes what a cloud session needs into the repo, between `teyla:cloud` markers: a passive Shipping policy in `AGENTS.md` (+ `@AGENTS.md` in `CLAUDE.md`), SessionStart/Stop hooks in `.claude/settings.json`, `.claude/rules/cloud.md` (the cloud-only done steps), `docs/cloud-setup.md`. See [Cloud sessions](#cloud-sessions) |
| `teyla cloud inbox [--days N]` | what cloud sessions left for a local one: branches with `Claude-Session:` commits and no PR (with the `gh pr create` line), and open PRs labelled `needs-mac` |

### Everything else

| command | what you get |
|---|---|
| `teyla doctor [--json] [--refresh] [--no-repos]` | everything that must be true on this machine, each FIX/WARN with its fix |
| `teyla update [--check] [--force] [--wire]` | install a newer published release by its commit sha, then re-wire the policy, plugin and routines; `--check` only reports |
| `teyla plugin install <src>\|uninstall <name>\|refresh [--force]` | install the Claude Code plugin by editing its registry (no `claude` CLI needed); `refresh` brings the loaded copy to this version |
| `teyla plugins [name\|path] [--json]` | the installed Claude Code plugins: version loaded vs working copy, and a skill / rule / fact quality pass over each |
| `teyla connectors [--days N] [--json] [--project]` | per MCP connector: calls, read/write split, empty and error rate, round-trips between human turns, rediscovery calls; advice C1–C4 |
| `teyla feedback` | one redacted markdown file: environment, the shareable report, and a questionnaire — the way a second user tells the maintainer what is missing |
| `teyla uninstall [--dry] [--keep-data]` | every file Teyla wrote on this machine (`--dry`), then the undo: LaunchAgents unloaded, the policy import line, symlinks, Hermes sections, harness skills and hooks, the plugin, `~/.teyla`. Touches only what carries Teyla's marker, label or symlink target; keeps and lists `~/.agents/POLICY.md` and repo-level `.teyla/` and rules |
| `teyla prompt [name]` | the paste-able prompts (onboard, work-account-kickoff, …) that shipped with the installed version |

### Session Reel

`teyla reel` turns one agent session and the git history it produced into a short vertical "terminal story": large
type, no scrolling noise, nothing you did not mean to show.

| command | what you get |
|---|---|
| `teyla reel list [--since 24h] [--repo NAME] [--all]` | the sessions of Claude Code and Codex in the window, with repo, span, commits and PRs |
| `teyla reel story <session-id> [--ask TEXT] [--seconds 45] [-o story.json]` | the redacted Story: title, ask, at most a dozen beats (edits, test runs, commits, PRs, reviews, sub-agent lanes), totals |
| `teyla reel check <session-id\|story.json>` | every string a reel would show, then how many were dropped by reason (`secret`, `private-term`, `email`, `path`, `too-long`) |
| `teyla reel render <session-id\|story.json> [-o DIR] [--seconds 45]` | `reel.mp4` (1080×1920, 30 fps, H.264), `reel.srt`, `story.json`, `reel.txt` (every string in the video) and `contact.png` (nine keyframes) in `~/Movies/teyla-reel/<date>-<repo>-<id>/` |

Redaction drops a string rather than masking it, and runs on every string before it can enter a Story. It reuses
the secret patterns and the private-terms list of `scripts/leak_check.py` (`~/.config/teyla/private-terms.txt` or
`$TEYLA_PRIVATE_TERMS`). Assistant prose and tool output are never read into a Story. See [`docs/reel.md`](docs/reel.md).

`render` needs the optional extra and ffmpeg: `pip install 'teyla[reel]'` (Pillow) and `ffmpeg` on `PATH`
(`brew install ffmpeg`). Frames are drawn in memory and piped to ffmpeg; no image files are written besides
`contact.png`. Without Pillow or ffmpeg, `render` says what is missing and still writes `story.json`, `reel.txt`
and `reel.srt` (exit 1). `--no-video` skips the mp4, `--font PATH` replaces Menlo / DejaVu Sans Mono. Check
`reel.txt` before posting: it is the audit trail, and a string that is not in it is not in the video.

### The advice rules

| id | fires when | action |
|---|---|---|
| A1 | >50% of subagent calls inherited the parent model | pass `model:` explicitly; cheap tier reads, mid tier builds, top tier reviews |
| A2 | >60% of output tokens on the orchestrate tier | route volume work down the ladder |
| A3 | sessions >8 MB or >12 active h | one session per project, compacted in place (`autoCompactWindow` 335000, or the machine's own value); one PR per logical unit |
| A4 | cache-read per output token >150× | compaction at ~300k (`autoCompactWindow` − 35k), subagents for reading |
| A5 | correction rate on human turns (never a `claude -p`/`codex exec`/`grok -p`/`hermes -z` prompt, a retry after an API error, or a harness-injected turn) | cluster them; two occurrences = a rule |
| A6 | many subagents, no review skill ever run | `/review`, `/codex review`, `/grok review` before money, keys, other people's data |
| A7 | sessions launched from a parent directory | launch from the repo root |
| A8 | a harness without the policy | `teyla policy sync` |
| A9 | the same correction shape twice (fingerprints, no text in the report; retries never count) | write the rule |
| A10 | a session wrote to `~/.claude/CLAUDE.md`: [high] only for edits after your last `teyla policy ack`, with how many; never acked → one [medium], once per version of the file | diff it; the governance file is the human's; `teyla policy ack` after reviewing |
| A11 | `teyla models` finds ladder/price drift | `teyla models --write-policy` |
| A12 | connector calls (`mcp__*`) are most of the tool calls | tokens are not the lever: `teyla connectors` |
| A13 | one project is over half of the week's Grok list-price cost (and the week is over $10) | `teyla grok-cost --by session --cwd <path>`; split or cap the loop |
| A14 | one Grok session cost over $10 | `teyla grok-cost --session <id>`; end long lanes at a merge |
| A15 | ≥3 turns in a week ended with the agent asking permission for the next step and the human answering a bare "yes" (only when POLICY.md declares `ask-permission`) | do the step and report it; ask only about product decisions or real blockers |
| A16 | a workflow runs on push, pull_request or schedule (only when POLICY.md declares `no-actions`) | `on: workflow_dispatch` only; `teyla doctor` lists every file |
| A17 | one project drives more than 200 headless calls a day through one harness (7-day average), or its headless calls doubled week over week (from 100 a week) — `claude -p`, `codex exec`, `grok -p` | check the routine means to call that often: cap it, batch items per call, or move it to a cheaper provider; the report's "Headless calls" table has calls/day and cost per harness and project |
| A18 | a harness recorded quota/balance or auth errors in the window (Grok 402 "usage balance exhausted", Hermes "missing access_token", `claude -p` "OAuth session expired", a Codex rate limit reached) — [high] while no later call succeeded | the exact fix (`hermes model`, `claude auth login`, top up); `teyla harness verify` |
| A19 | a cloud session's branch has commits and no PR after 24 h (found from `Claude-Session:` commit trailers; PR state from `gh`, never asked in safe mode) | `gh pr create --repo <owner/name> --head <branch> --fill`, then build and review it locally |
| A20 | in one project, more than 30% of subagent calls (from 10 calls) name an orchestrate-tier model explicitly (`model: "fable"`) — A1 only sees calls that inherit; evidence has the count, the share and the top tier's share of that project's subagent cost. `spend.a20_share`, `spend.a20_min_calls` set the thresholds; `spend.a20_models=opus,...` counts more names as top tier | route volume lanes to the volume tier (`model: sonnet`); keep the top tier for review and design, passed on that call only |

Spend thresholds are config, not constants: `teyla config set spend.alert_session_usd=250 spend.w1_usd=15 spend.daily_budget_usd=300 spend.budget.<project>=40` (the project as `teyla spend` names it: the repo directory, or the repo of a `~/.worktrees/<repo>/<branch>`). Budgets are API-equivalent dollars for one local calendar day; unset or 0 is off. `spend.opus_share_max` (default 0.25) is the share of the week's subagent cost Opus may take before `teyla digest` names it ("Opus ran 41% of subagent cost (37 lanes)", step `teyla lanes --days 7`); POLICY says Opus only with a stated reason.

### Policy detectors

A rule in POLICY.md that nobody measures holds until the first busy week: a no-Actions rule
can be broken repeatedly while it sits in every harness's context. Rules that
files or transcripts can prove broken get a detector, and **the policy declares which run** —
a user whose POLICY.md lacks the rule is never nagged about it:

```markdown
<!-- teyla:detect no-actions -->
```

anywhere in `~/.agents/POLICY.md` switches that detector on. An id Teyla does not know is a
`teyla doctor` WARN, never silently ignored. Built in:

| id | on by | checks | reported by |
|---|---|---|---|
| `no-actions` | the marker, or a heading like `## 10. GitHub Actions are off` | `.github/workflows/*.yml\|yaml` of every git repo under `code_root` and `ops_root` — in the working tree and on `origin/HEAD`, and says which — for `on:` push / pull_request / pull_request_target / schedule (string, list and map forms) | `teyla doctor` (`actions:<repo>` WARN with the file and the fix), advice A16 |
| `ask-permission` | the marker (in the template's §4), or the §4 wording "not about permission" | Claude Code and Codex turns whose last paragraph asks permission for one step ("Want me to push them?") that the human answered with a bare yes; choices ("A or B?"), blockers (keys, payments, merges, deploys, deletes) and real answers do not count | advice A15 |

Prices in `pricing.py` are a table you edit, or `~/.teyla/prices.json` (`teyla models --write-prices`) which overrides it when present. Cost is labelled "API-equivalent" because you may be on a subscription.

## Routines and checks

Some work must run without you: a launchd sync, a cron job, a `pg_cron`
schedule, a GitHub Actions workflow, a bare script. Some work only you can
confirm: does the feature actually behave the way it's supposed to, from the
outside, right now? Both halves rot the same way — silently — so both get
tracked in one place: a `teyla.toml` at the repo root.

```toml
[product]
name = "my-app"
usage = "./check.sh usage"          # optional command printing key=value counters

[[routine]]                          # must run without the human
name = "nightly-sync"
kind = "launchd"                     # launchd | cron | pg_cron | github-actions | script
label = "com.example.sync"             # launchd label / cron marker / workflow name
every = "1d"                         # expected cadence: 15m, 1h, 1d, 7d, or any <n>m|h|d; a `script` routine may omit label and every
log = "~/Library/Logs/app-sync.log" # optional; mtime = last run
# paused = "2026-10-14: owner keeps it off until the product is reviewed"   # optional; see below

[[check]]                            # the human tests by hand and confirms
name = "log an entry from a photo"
how = "app → New → photo → caption"
status = "broken"                    # ok | broken | untested
confirmed = 2026-09-09               # date of last confirmation
```

`teyla routines [path...]` (default: every git repo under `~/repos` with a
`teyla.toml`) prints one table per product:

- **Routine row** — name · kind · loaded (launchd: `launchctl list` for the
  label; cron: grep `crontab -l`; github-actions: `gh run list -w <label>
  -L1` if `gh` is on PATH, else `unknown`; pg_cron/script: `unknown` unless a
  `log` is given) · last run (log mtime, else `?`) · verdict: `ok` /
  `NOT LOADED` / `STALE` (last run older than 2× the declared cadence) /
  `unknown`, or `paused` / `PAUSED BUT LOADED` (below).
- **Check row** — name · status · confirmed · age in days · verdict: `ok` /
  `BROKEN` / `UNTESTED` / `RE-TEST` (confirmed more than 30 days ago).

A routine the owner deliberately leaves off carries `paused = "<ISO date>: <reason>"`
(a malformed value is a manifest error). Its row says `paused` with the reason, and it is never a
problem: not in the exit code, the banner or the digest, and `teyla schedules` lists it as `DISABLED`
(`paused: <reason>`). If it is loaded anyway, the verdict is `PAUSED BUT LOADED` — the file and the
machine disagree — and that is a problem. Delete the key to bring the routine back under watch.

It ends with one summary line — `N routines not running, M checks broken, K
untested/re-test` — and exits 1 when `N + M > 0`, so a cron job can alert on
it. `--json` gives the same shape as data.

Confirming a check is one command — `teyla check app-a "gate shows today's drafts" ok` (or
`broken --note "what you saw"`) — which rewrites only that block's `status`/`confirmed`/`note`
lines and keeps every comment. When a session starts in a repo whose check has been BROKEN
or UNTESTED for more than 14 days (or was never confirmed), the product line names that command.

`teyla routine install` writes and loads Teyla's own weekly launchd job
(`~/Library/LaunchAgents/com.zaitsew.teyla.weekly.plist`, Friday 20:45) that
runs `teyla monitor`, `teyla routines`, `teyla products`, `teyla models` and `teyla reviews` and files the
output under `<runs_root>/<date>/` (`runs_root` defaults to `<ops_root>/runs`; set it with
`teyla config set runs_root=~/path`). `teyla routine status`
shows whether it is loaded and its last log lines.

## What gets read

Weekly reports that nobody opens, and a session-start line that repeats the same "1 fix(es), 2 warning(s)" on
every start, are both ignored within days. So:

- **The banner shows only what changed.** `teyla doctor` and `teyla routines` precompute
  `~/.teyla/banner.items`; the session-start hook compares it with what it showed last time
  (`~/.teyla/banner.seen`, keyed by name and level) and prints
  `teyla: new — app-a routine daily NOT LOADED; 2 known (teyla doctor)`, or nothing. A WARN
  that becomes a FIX is new again. Reminders appear on the day they fall due, the day after,
  then weekly.
- **The weekly digest is five lines.** The weekly routine runs `teyla digest --write`:
  `~/.teyla/digest.md` with the top three actions — doctor FIX items, monitor advice,
  routines not running, checks broken or untested for more than 14 days — each with its one
  command, and a streak note when the same advice fired three weeks running. The next
  session start shows its headline once; `teyla digest` prints it; on macOS a notification
  says it was written (`teyla config set digest.notify=false` to stop that).

## Productizing

An app built for one person fails to become an app for four in the same six ways every
time: one shared key instead of accounts, no `user_id` on any table, a backend running on
the builder's laptop, no distribution path off that laptop, the builder's own model key on
someone else's device, and no page telling a newcomer what to do first. None of it is
hard. All of it is invisible until somebody is waiting.

Two commands. `teyla platform` is the resources you buy once and reuse for every product —
a server, a domain, an identity provider, a mail sender, the Apple key and upload tool, a Play
Console account and upload keystore, a model key, a secrets file —
declared in `~/.teyla/platform.toml`, which holds identifiers and env-var *names* and never
a value:

```
resource  state    what to do
secrets   ok       ~/.config/teyla/platform.env 0600; 4/5 names present
server    MISSING  provision it: bash .../provision-droplet.sh --yes (needs DIGITALOCEAN_ACCESS_TOKEN),
                   then paste the IP as host = in ~/.teyla/platform.toml
mail      MISSING  create the key at https://resend.com/api-keys -> paste as RESEND_API_KEY= in
                   ~/.config/teyla/platform.env
apple     ok       3 ids, 1 key(s), release tool found
```

Every missing row names the URL where the thing is created and the file and key where its
value goes; the command exits 1 while anything is missing.

`teyla productize` reads a `[productize]` block in each repo's `teyla.toml` — who it serves,
who it should serve, platforms, identity, tenancy, backend, distribution, secrets, cost cap
— and says what is in the way:

```
app-a            owner→family  9/9 met
    [owner] internal TestFlight group — App Store Connect -> add two Apple IDs
notes            owner→family  1/9 met  unmet: R1 identity=shared-key, R2 tenancy=single,
                 R3 backend=local-mac, R4 ios=none, R5 onboarding_doc unset,
                 R7 cost_cap unset (llm=app-key), R9 first_run=none, sample_data unset,
                 R10 primary unset, ios: no trigger, web: no trigger
    [agent] platforms: primary unset, ios: no trigger, web: no trigger — write [productize] primary
            and a dated [productize.triggers] entry per other platform, from the repo's history
            and the owner's requests

1 product(s) with unmet requirements, 8 requirement(s) unmet
```

It also checks the first screen (R9): family and public products must open on a sign-in (skippable
only when the app genuinely needs no account) and must never show sample data as the user's own.
R8 wants a mail sender the platform owns for a public target, or sign-in codes reach only your
inbox. R10 wants one `primary` platform and a dated reason for every other one; it applies even to
an owner-only product, and an unmet R10 becomes a step for the agent.

`--owner-steps` collapses every product *and* the platform into one numbered list of things
only you can do, platform first, because one mail sender unblocks three products.
`teyla scaffold --kind app` writes the block, a `docs/GETTING-STARTED.md` addressed to a
person who is not you, and `deploy/droplet/` fragments for the shared server; the server
itself is three scripts (`provision-droplet.sh`, `setup-server.sh` for Ubuntu 24.04 with Docker,
ufw and one Caddy, `add-product.sh <name> <port>`), a `Caddyfile` and a runbook in `templates/platform/`.

The method — why this happens, what to build instead from the first commit, what the shared
platform costs, and what changes at twenty users — is [`docs/PRODUCTIZE.md`](docs/PRODUCTIZE.md).

## Cloud sessions

A cloud session (Claude Code on the web, `claude --cloud`, "Continue in the cloud" from the
desktop app) runs on a Linux VM that clones the repo and nothing else. Your user `CLAUDE.md`,
`POLICY.md`, skills, plugins (even ones the repo's settings declare), hooks and memory are not
there; neither are codex, grok, Xcode or your keys. It does read the repo's `CLAUDE.md`,
`.claude/rules/`, `.claude/skills/` and `.claude/settings.json` hooks, and it can push only to its
own branch. In practice a cloud run often ends on a pushed branch with no
PR, and a local session has to find, build and merge it the next day.

```bash
teyla cloud check                     # every repo: what a cloud session would lack; exit 1 on a blocker
teyla cloud prep ~/repos/app --dry    # the files it would write, as a diff
teyla cloud prep ~/repos/app          # write them (private repos; --allow-public otherwise), then commit as a PR
teyla cloud inbox                     # cloud branches with no PR, and PRs labelled needs-mac
```

`prep` writes plain files, because a cloud VM does not install plugins:

- `AGENTS.md`: a Shipping section of passive policy only (one PR per logical unit, merge-not-squash,
  no force-push, no CI on push/PR (short ubuntu deploy jobs on push to main allowed) when your
  policy says so, report honestly, ask about product decisions not permission) and
  `merge-approved: yes|no`, derived from your MERGE-APPROVED list, plus one line saying it is policy
  and not a task. `teyla cloud check` fails when the line drifts from the list. AGENTS.md is read
  by every model run in the repo, headless one-shot calls (`claude -p`, `grok -p`) included, so it
  carries no step that ends a session.
- `.claude/rules/cloud.md`: the cloud definition of done, under a header that limits it to
  `CLAUDE_CODE_REMOTE=true`: the gate ran and its output is in the PR body, the branch is pushed, a
  PR is open, it carries the `needs-mac` label when a Mac-only step was skipped, a second opinion is
  a "same-provider review", and, in a merge-approved repo, the merge. Re-run `teyla cloud prep` in a
  repo prepped before 0.19.2: it replaces the old section in place (`teyla cloud check` warns).
- `.claude/settings.json`: a SessionStart hook that orients the session (branch, gate, what skips
  without a Mac) and a Stop hook that sends it back once while work is unpushed or has no PR. Both
  do nothing unless `CLAUDE_CODE_REMOTE=true`.
- `docs/cloud-setup.md`: the setup script to paste into the claude.ai environment (uv and the repo's
  dependencies, including subdirectories two levels down with a lockfile of their own; no secrets), and each secret name from `.env.example` with where it goes. HTTP API
  keys go in the environment's API credentials (Pro/Max). Apple `.p8` keys never leave the Mac.

Nothing personal is written: no home-directory paths, no other repo names, no list. The text is
checked before any write. A repo that is public, or whose visibility `gh` cannot tell, is refused
unless you pass `--allow-public`.

**Cloud vs local.**
- **Cloud:** well-specified work whose gate runs on Linux (SQL, Deno, web, Python, docs), parallel spikes,
  and PR babysitting.
- **Local, or Remote Control on the laptop:** anything that needs Xcode or a simulator, deploys, TestFlight
  and App Store releases, launchd routines, cross-provider review with codex/grok, and the final merge of a
  `needs-mac` PR.

`teyla cloud inbox` and advice A19 are how the local half finds the cloud half's work.

## The policy

`templates/POLICY.md` is the one file every harness reads. Its spine:

1. **The model ladder.** The most capable model of a provider orchestrates; cheaper tiers do volume and triage (for Anthropic: Fable → Opus / Sonnet → Haiku). Say which model did what. `teyla models` keeps this table current against models.dev, each CLI's own cache, and which credentials are actually on this machine; `--write-policy` proposes the update.
2. **Second opinions across providers** before non-trivial designs and anything touching money, credentials or other people's data. One pass.
3. **Tool ladder**: connector/MCP → CLI/API → browser extension → computer use. Fall one rung at a time and say so.
4. **Ask about product decisions with a proposed default; never ask for permission to proceed.**
5. **Stop only at a real blocker** (a key, a payment, a sign-in): do everything around it, open the exact page, name the exact file and line, hand over one line.
6. **Plug-and-play is the definition of done.**
7. **Merge only where you said so**; everywhere else open the PR and stop. Merge, never squash; never force-push.
8. **Say what is unverified.**
9. **"Did it run?" is answered from the record** (`teyla routines`, `teyla schedules`), not by reading code.
10. **One machine, a budget**: the guard decides when a build, simulator or lane may start, not the agent.
11. **Platforms and releases**: one primary platform, ports in trains, a build is done when it reaches a person.

`templates/POLICY.work.md` is the work-laptop variant (approved providers only, same-provider reviews).

**Edits to a generated copy are kept.** `policy sync` keeps the sha256 of everything it writes (`~/.teyla/state/policy-written.json`, with a copy of the text). Before it overwrites a copy whose hash no longer matches, it files the difference (the lines added and removed since the last write) in `~/.teyla/policy-inbox/<harness>-<date-time>.md`, with the instruction to move what should stay into `~/.agents/POLICY.md` or `~/.claude/CLAUDE.md`, the two sources; only then does it overwrite. For the Hermes `SOUL.md` only Teyla's own section is compared, never your text around it. With no record yet (the first sync after an upgrade) the copy is compared with what sync would write now, and only added lines count. The daily routine runs `teyla policy sync --quiet`, so an edit made in Codex today reaches the inbox tomorrow morning instead of vanishing silently at the next manual sync. `teyla policy inbox` lists what waits, `teyla doctor` warns while anything does, and the session-start line says how many.

## The plugin

`plugin/` is a Claude Code plugin with no server behind it:

- `/teyla:rule <sentence> [--scope glob]` → `.claude/rules/<slug>.md` (+ mirrored into `AGENTS.md`)
- `/teyla:correct <what was wrong>` → `~/.teyla/corrections/<repo>-<hash>.jsonl` (outside the repo, 0600, secrets replaced by `[redacted]`), then proposes the rule
- skills: **harvest** (sessions → skill draft + candidate rules + routine manifest + a done-test *question*), **adoption-review** (`teyla monitor` → three concrete edits), **wiki-pass** (this session's facts → wiki pages as a PR you confirm or correct; see [docs/WIKI.md](docs/WIKI.md)), and **tidy** (`teyla tidy --json` → proposed rewrites of dated anecdotes, duplicates and one-off history in the rule files, as a diff you approve)
- a `SessionStart` hook that orients each session: the machine CRITICAL alert and the spend alert first, then what is new since the last start, the weekly digest headline once, and the product's routines line; once a day it starts the update check and `teyla routine catch-up` in the background, and `teyla policy sync --quiet` when a generated copy is stale
- a `PreToolUse` hook on every tool call: while `~/.teyla/KILL` exists every call is denied, and during a `teyla run` the run's grants and caps are enforced (it fails closed)
- a `UserPromptSubmit` hook that captures correction-shaped prompts silently, into the same store (it needs the `teyla` CLI installed: the scrubber lives there, and with no scrubber nothing is written). `teyla corrections --recorded` lists what was stored; `teyla config set corrections.store=repo` keeps the pre-0.12 in-repo file instead. Either way `.teyla/` is added to the repo's `.git/info/exclude`, so an agent's `git add -A` cannot commit it
- **`/teyla:review`**: one P1/P2-only review of the branch's diff before a merge — a `codex-review`/`claude-review` script on PATH when there is one (cross-provider), else one fresh sub-agent given only the diff ("same-provider review"); at most two rounds
- **the machine guard** (`machine-guard.sh`, PreToolUse on `Bash`; on by default, no opt-in): before a shell command that starts heavy work — `xcodebuild`, `swift build|test`, `gradle`/`gradlew` with a task, `cargo build|test`, `bazel build|test` (kind `build`); `simctl boot|create|clone` (`sim`); `codex exec`, `codex-lane`, `codex-review`, `claude-review`, `claude -p`, `grok -p` (`lane`) — it asks `teyla load --admit KIND`. While the Mac is overloaded (or `guard.max_builds` / `max_sims` / `max_lanes` are reached) the call is refused with the numbers and what to do instead. Read-only invocations (`xcodebuild -list`, `simctl list|io|launch|shutdown|...`) are never gated. Agents that must build anyway wait for a slot: `teyla load --wait --kind build && xcodebuild ...`. Switch it off with `teyla config set guard.enabled=false`, or per shell with `TEYLA_GUARD=0`. It fails open (a missing or broken `teyla` never blocks work) and an ordinary command costs about 3 ms over the shell's own start and starts no Python and no `awk` (a command that merely names one of these tools, say a `.swift` file, pays one `awk`, about 2 ms more). `teyla harness sync` wires it into Codex and Grok too ([docs/HARNESSES.md](docs/HARNESSES.md))
- two opt-in hooks, off by default (`teyla config set hooks.context_budget=true hooks.land_check=true`), for a machine that has no equivalent of your own:

  | hook | event | what it does |
  |---|---|---|
  | `context-budget.sh` | UserPromptSubmit, PostToolUse, SessionStart (compact) | at 240k tokens of context, then every 30k, the model writes a handoff to `~/.teyla/handoff/`; after Claude Code compacts (at ~300k with `"autoCompactWindow": 335000` in `~/.claude/settings.json`) it is put back once. Off, it costs one `awk` and starts no Python |
  | `land-check.sh` | Stop (Claude Code; Codex via `teyla harness sync`) | once per session, uncommitted files or commits on no remote are named with how to land them: open the PR/MR and merge only when the repo is in the `MERGE-APPROVED REPOS` block of `~/.claude/CLAUDE.md`, else stop at the PR/MR. Never a block |

```bash
claude plugin marketplace add zaitsew/teyla    # or a local path: claude plugin marketplace add ~/repos/teyla
claude plugin install teyla@teyla
```

## Where nothing can be installed

`prompts/adoption-review.md` is a self-contained prompt with the miner embedded: upload it to any Claude Code session, get `teyla-report.md` with aggregates only (no text, no paths; tool, skill and model names only; corrections as fingerprints), share it back by hand. `prompts/work-account-plugin-review.md` is the same idea for a corporate setup with a custom plugin and connectors.

## Prior art

- [gstack](https://github.com/garrytan/gstack) — pre-built role skills for Claude Code. Teyla harvests skills from *your* transcripts and adds the monitor and the policy; it uses gstack's review skills rather than replacing them.
- [TRACE](https://arxiv.org/abs/2606.13174) / [tellonce](https://github.com/YujunZhou/tellonce) — corrections compiled into enforced rules; the academic version of Teyla's rule loop.
- [ccusage](https://ccusage.com), claude-code-otel, cc-analyzer, cctime — token, cost and time dashboards across Claude Code, Codex and others. Teyla adds the correction, subagent-model and session-shape signals and the advice; it does not replace them.
- [AGENTS.md](https://www.morphllm.com/agents-md-guide) — the cross-harness instruction file Teyla syncs to.

Read [docs/MANUAL.md](docs/MANUAL.md) for the whole method: skill / rule / fact, routines and the run loop, the nine-stage spine for building software, session discipline, and the numbers behind each threshold.

## Licence

Apache-2.0.

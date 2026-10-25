# Guide: Teyla in depth

The [README](../README.md) says what Teyla is and what to paste. This page holds the depth, in the same order as the README:
[install and update](#install-and-update), [cost and waste](#cost-and-waste), [what's waiting on you](#whats-waiting-on-you),
[your products and notes](#your-products-and-notes), [one policy for every agent](#one-policy-for-every-agent),
[privacy](#privacy-and-safe-mode) and [undo](#undo-and-uninstall). Every command with its flags is in [COMMANDS.md](COMMANDS.md).

## Words used in Teyla

- **List price.** What the tokens of a session would cost through the provider's API. A subscription bills differently, so the figure is a measure of work, not your invoice.
- **Context.** Everything a session has read and written so far. The agent re-reads all of it on every turn, so a long session costs more per turn than a short one.
- **Context window and compaction.** The most text a model holds at once. Near the limit the tool *compacts*: it replaces the conversation with a summary and goes on. Offer O1 makes that happen earlier.
- **Subagent.** A helper agent that a session starts for one side task, with its own model and context.
- **Harness.** The tool an agent runs in: Claude Code, Codex, Grok, Cursor or Hermes.
- **Hook.** A small script that a harness runs at a set moment: when a session starts, before a tool call, when you send a prompt.
- **Routine.** A job that runs by itself, under launchd (the macOS scheduler), such as the daily check.
- **Product.** A repo, or a few, that you ship as one thing. Teyla files questions, notes and cost under a product.
- **Policy.** One `POLICY.md` with your rules for agents, written once and copied into every harness.

## Install and update

```bash
uv tool install --python 3.12 git+https://github.com/zaitsew/teyla   # or: pipx install git+https://github.com/zaitsew/teyla (Python 3.11+)
teyla start                          # what your agents cost, and seven changes you can accept one by one and undo
teyla policy init --owner "Your Name" && teyla policy sync   # one POLICY.md (+ your CLAUDE.md rules) → Claude Code, Codex, Grok, Hermes, Cursor
teyla plugin install zaitsew/teyla   # the Claude Code plugin with the machine guard (or: claude plugin marketplace add zaitsew/teyla)
teyla harness sync                   # the same skills and hooks in Cursor, Codex, Grok and Hermes
teyla routine install                # daily: update, doctor, policy sync, spend alert; weekly: monitor, routines, products, models
teyla doctor                         # everything that must be true here, and the fix for each thing that is not
teyla asks                           # every question an AI session left waiting on you
teyla product init                   # which repo is which product (a proposal; --write saves it)
teyla spend --days 7 && teyla load   # the two numbers to look at first
```

Offers O5, O6 and O7 in `teyla start` run the policy, harness and routine lines for you, each after its own yes. O5 names the policy's owner with `teyla apply O5 --owner NAME` (the default is your login name). O6 also installs the Claude Code plugin when it is missing.

After that it keeps itself current: `teyla update` (run daily by the routine, and at session
start by the plugin hook on machines where launchd is off limits) installs a newer published
release by its commit sha and checks the version it built (`update.pin` freezes it,
`update.channel=none` stops the routine),
merges template changes into your `POLICY.md` three-way so your edits survive, refreshes the
plugin copy Claude Code actually loads, and rewrites the launchd wrappers if the binary moved.
`teyla doctor` is the checklist; what is *new* in it shows at the next session start, and
once a week the digest names the three things worth doing (see [What gets read](#what-gets-read)).

No `uv`? `pipx install git+https://github.com/zaitsew/teyla`, or `git clone` and run `PYTHONPATH=src python3 -m teyla`. Python 3.11 or newer, nothing else. With `uv`, `--python 3.12` makes it use Python 3.12 and download it (about 25 MB) when the Mac has none in the 3.11 to 3.13 range.

**Handing it to a second machine:** [`docs/HANDOVER.md`](HANDOVER.md) lists every practice that travels and what to adapt; [`prompts/work-account-kickoff.md`](../prompts/work-account-kickoff.md) is the paste-able version; [`prompts/work-account-update.md`](../prompts/work-account-update.md) updates a machine that already has Teyla and switches on its self-maintenance. **Handing it to an agent instead of a person:** paste "Set up https://github.com/zaitsew/teyla" into Claude Code or Codex; it follows [`AGENTS.md`](../AGENTS.md). For a machine with a longer brief, paste [`prompts/onboard.md`](../prompts/onboard.md) into Claude Code, Codex or Grok on the new machine. It installs, wires the policy, installs the plugin, runs the first review, and produces the feedback file. Corporate machines: no data leaves the machine; every network call (release checks, the daily self-update) and every file Teyla writes are listed there, and `teyla uninstall --dry` lists what is on this machine (`teyla uninstall` reverses it). `teyla prompt onboard` prints the copy that shipped with the installed version.

## Cost and waste

Agent work gets expensive through a few habits that usage dashboards do not name: subagents that inherit the top model, build lanes that drift up to Opus, sessions that re-read 300k tokens each turn. Teyla puts a dollar figure on each, at list price, and names the fix.

### Find the waste: `teyla start`

`teyla start` reads the sessions of the last 30 days (Claude Code, Codex, Grok, Hermes and Cursor), prints a card of at most 12 lines, then offers seven changes one at a time: `[y]es / [n]o / [e]xplain / [q]uit`. It never changes anything without a yes, saves a backup before it writes, and logs each change so that `teyla undo` can reverse it.

| id | change | where it writes |
|---|---|---|
| O1 | Compact long sessions earlier (`autoCompactWindow` 335000) | one key in `~/.claude/settings.json` |
| O2 | Run subagents on Sonnet unless they say otherwise | one key in `~/.claude/settings.json` |
| O3 | Add a cheap read-only `scout` agent on Haiku | `~/.claude/agents/scout.md`, only if absent |
| O4 | Run Codex at medium reasoning effort | one line in `~/.codex/config.toml` |
| O5 | Give every agent the same rules (`teyla policy sync`) | the rules link of each installed harness |
| O6 | Keep your prompts and questions (`teyla harness sync`, plus `teyla plugin install zaitsew/teyla` when Claude Code has no Teyla plugin) | hooks and skills in each installed harness; the Claude Code plugin |
| O7 | Check in every morning (`teyla routine install`) | two launchd jobs |

O1 to O3 show a saving in dollars a month, counted from your own sessions as a range with its basis. O4 to O7 say what they bring instead, because no honest dollar figure exists. How each saving is counted: [START.md](START.md).

```bash
teyla start --days 14       # another window; savings are scaled to a month
teyla apply O1 O3 --yes     # make those changes without the questions (--dry shows them and writes nothing)
teyla start --agent         # JSON for an AI agent to relay; writes nothing
```

`teyla web` shows the same diagnosis and offers on a page, with Apply and Undo buttons ([WEB.md](WEB.md)).

### Spend fewer tokens

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

### Keep the machine alive

Every agent on a laptop shares one CPU, one RAM and one swap file, and none of them sees the others. Ten sessions that each boot "just one" simulator and run "just one" build fill swap together, and the kernel panics. Teyla is the scheduler they are missing.

```bash
teyla load                                          # OK / BUSY / CRITICAL: RAM, swap, compressor, load, disk, sims, builds, agents
teyla load --wait --kind build && xcodebuild ...    # wait for a free slot instead of piling on
teyla config set guard.agent=true && teyla routine install   # the every-minute guard: alerts, load records, idle Gradle daemons stopped
teyla storage                                       # worktrees, build output, caches and simulators holding disk and RAM
teyla crash                                         # after a panic: what the machine looked like in the 30 minutes before
```

- **Admission control, on by default.** The plugin's machine guard asks `teyla load --admit` before a command that starts heavy work: `xcodebuild`, `swift build`, `gradle`, `simctl boot`, `codex exec`, `claude -p`, `grok -p`. While the Mac is overloaded, memory is getting worse (swap-out rate, swap growth, disk running out), the last ten minutes had either, or `guard.max_builds` / `max_sims` / `max_lanes` are reached, the call is refused with the numbers and what to do instead. Each decision is logged to `~/.teyla/guard-decisions.tsv`; `teyla load` shows the last hour's admits and refusals, and `teyla load --replay` shows what the thresholds would have decided on the recorded days. It fails open and costs about 3 ms on an ordinary command. `teyla harness sync` wires it into Codex and Grok too.
- **The guard tick.** Once a minute: a row in `~/.teyla/load.tsv`, an alert at the next session start and one macOS notification while the machine is CRITICAL, idle Gradle and Kotlin daemons stopped, and a temp sweep when free disk runs low (APFS swap shares the disk).
- **Cleanup agents.** `teyla storage sims --reap` shuts down idle simulators, `storage procs --kill` stops dev servers and builds whose worktree is gone, `storage sweep` removes what agents leave behind (DerivedData, temp builds, caches, old logs). Each checks age and running processes first, and each has a dry run.
- **Forensics.** `teyla crash` reads the kernel panics, watchdog resets and jetsam events, and lines each up with the load records from just before it, with advice computed from those numbers.

`teyla storage` lists what holds disk and RAM. The plugin's machine guard fails open: a missing or broken `teyla` never blocks work.

## What's waiting on you

### Questions an agent left open: `teyla asks`

A session ends on a question, the desktop app archives it, and nobody reads it again. In a 14-day sample from one machine, 40 Claude Code sessions ended that way and 1 got an answer.

```bash
teyla asks                      # open questions by product, oldest first, with a link that reopens the session
teyla asks --html --open        # the same as one page for your phone
teyla asks done <id>            # close one; snooze <id> <days> hides it
```

You get the question word for word, its age and the options the agent offered. Details: [ASKS.md](ASKS.md).

### The daily screen: `teyla`, `teyla today`, `teyla help`

Bare `teyla` prints a welcome of at most 15 lines: what Teyla is, three live numbers (spend of the last 7 days, questions waiting, notes in the Inbox) and the next three commands. `teyla today` is the daily screen: the questions waiting by product, the Inbox, this week's spend against last week's, and one next step chosen by a written rule. `teyla help` lists the commands in six groups. None of them changes anything. Details and the cache rules: [TODAY.md](TODAY.md).

### The dashboard: `teyla web`

`teyla web` opens a page in your browser with five tabs: Start (the diagnosis and the offers), Today, Products, Notes and Spend. It listens on 127.0.0.1 only, behind a per-run token, and stops after two hours with no request. It calls the same functions as the commands, so a figure on the page is the figure the command prints. Details and the security model: [WEB.md](WEB.md).

### The Mac app

**Teyla for Mac** is one window and a menu-bar icon. It opens with a one-sentence brief, orders the questions by what each unblocks, shows the sessions running now, and sends your answer into the session that asked. It updates live and reads everything through the CLI. On a Mac where Teyla has seen no sessions, the window offers "Run diagnosis" and shows the same card as `teyla start`.

```bash
brew install xcodegen                       # once
cd apps/mac && ./install.sh                 # builds Teyla.app into ~/Applications (macOS 15, Xcode)
teyla state                                 # what the window shows, in the terminal
teyla answer <id> -- "<text>"               # send an answer without opening the session
```

The app is ad-hoc signed for local use. If it cannot find `teyla`, the window shows the install command. A global shortcut (⌥Space by default) opens a quick note. Details: [apps/mac/README.md](../apps/mac/README.md), [APP.md](APP.md). To answer from an iPhone, see [RELAY.md](RELAY.md).

### What gets read

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

## Your products and notes

### Products

Teyla files every question, running session and finished task under a product. You write the map once, in `~/.teyla/products.toml`; a session that is not on the map is `unassigned`, and nothing is guessed.

```bash
teyla product init           # propose one product per git repo under your code root (prints; --write saves)
teyla product                # one line per product
teyla product show <id>      # one product: questions, notes, recent sessions and cost, repos
teyla product set <id> stage=beta focus=true
```

How a session finds its product, and the file's keys: [PRODUCTS.md](PRODUCTS.md).

### Notes

An idea arrives while you work on something else. `teyla note` keeps it as you typed it and files it under a product, or in the Inbox. No model reads or rewrites it.

```bash
teyla note "Weekly digest should list parked products too"
teyla notes                  # newest first; --inbox shows the unfiled ones
teyla note link <id> <product>
```

The Mac app and `teyla web` add the same notes. Details: [NOTES.md](NOTES.md).

### Your own words

You write a long prompt, an agent turns it into a plan, and a later session works from the plan. The detail is gone. Teyla keeps the source.

```bash
teyla intent backfill --days 30   # keep the long prompts already in your transcripts
teyla intent [product]            # list them; `teyla intent path <product>` prints the file
```

Prompts of 400 characters or more go to `~/.teyla/intent/<product>.md`, outside the repo, with secrets scrubbed. No model summarises them. Session start points at the file, and the policy says a plan quotes the sentences it serves. Details: [INTENT.md](INTENT.md).

### Whether a build reached a person

An app for one person becomes an app for four only with accounts, per-user data, a backend off your laptop and a build on other people's phones.

```bash
teyla productize --owner-steps   # every product against R1 to R10, then one list of what only you can do
teyla platform                   # the shared resources you buy once: server, domain, mail, Apple, Google Play
teyla testflight                 # did the newest uploaded build reach your tester (iOS)
teyla play                       # the same for the Android internal track
```

Each product names one primary platform; any other needs a dated trigger. Details: [PRODUCTIZE.md](PRODUCTIZE.md).

### Routines and checks

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

### Whether the automated half ran

Launchd jobs, cron lines, desktop tasks and scheduled workflows fail silently.

```bash
teyla routines     # every routine and manual check in each repo's teyla.toml: ok, NOT LOADED, STALE
teyla schedules    # every scheduled task on this machine, its last run, and what vanished
teyla reviews      # merged PRs that never got a review
```

`teyla run product:routine` runs a routine under capability grants and stops at a gate for your approval in `teyla inbox`. Details: [CONTROL-PLANE.md](CONTROL-PLANE.md).

## One policy for every agent

Your rules live in one harness. Switch to another and the model has never heard of them. Teyla keeps one source and renders it into each harness in the form that harness reads.

```bash
teyla policy sync            # ~/.agents/POLICY.md and your own rules into Claude Code, Codex, Grok, Hermes, Cursor
teyla harness sync           # the same skills and hooks in the others
teyla harness verify --live  # can each harness do work now, and did the policy arrive
```

An edit made inside a generated copy is filed in `teyla policy inbox`, never overwritten silently. What each harness can and cannot do: [HARNESSES.md](HARNESSES.md).

### The policy

`templates/POLICY.md` is a short generic starter (about 70 lines) that `teyla policy init` copies to `~/.agents/POLICY.md`; every harness then reads that one file. Replace its `<placeholders>` with your own. Its spine:

1. **The model ladder.** The most capable model of a provider orchestrates; cheaper tiers do volume and triage. Say which model did what. `teyla models` keeps this table current against models.dev, each CLI's own cache, and which credentials are actually on this machine; `--write-policy` proposes the update.
2. **Second opinions from another provider** before non-trivial designs and anything touching money, credentials or other people's data. One pass.
3. **Ask about product decisions with a proposed default; never ask for permission to proceed.**
4. **Merge only where you allowed it**; everywhere else open the PR and stop. Merge, never squash; never force-push.
5. **The laptop is the gate**: run your check before every push; no CI on every push.
6. **State the price before anything paid.**
7. **Say what is unverified.**
8. **Writing and reporting**: the answer first, short sentences, a session-end card.

A policy written from an older, longer template, or by hand, carries no `teyla-template:` marker. `teyla policy refresh` never merges template changes into such a file; it is yours.

`templates/POLICY.work.md` is the work-laptop variant (approved providers only, same-provider reviews).

**Edits to a generated copy are kept.** `policy sync` keeps the sha256 of everything it writes (`~/.teyla/state/policy-written.json`, with a copy of the text). Before it overwrites a copy whose hash no longer matches, it files the difference (the lines added and removed since the last write) in `~/.teyla/policy-inbox/<harness>-<date-time>.md`, with the instruction to move what should stay into `~/.agents/POLICY.md` or `~/.claude/CLAUDE.md`, the two sources; only then does it overwrite. For the Hermes `SOUL.md` only Teyla's own section is compared, never your text around it. With no record yet (the first sync after an upgrade) the copy is compared with what sync would write now, and only added lines count. The daily routine runs `teyla policy sync --quiet`, so an edit made in Codex today reaches the inbox tomorrow morning instead of vanishing silently at the next manual sync. `teyla policy inbox` lists what waits, `teyla doctor` warns while anything does, and the session-start line says how many.

### Switch harnesses without losing your setup

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
- **Harnesses you do not use stay out of the way:** `teyla config set harness.disabled=hermes,grok`. What each harness can and cannot do is in [docs/HARNESSES.md](HARNESSES.md).

### How agents write

Replies run long and open with filler. The policy sets one contract: the answer first, short sentences, a ban list, and a session-end card of at most 12 lines.

```bash
teyla prose --days 7   # reply length, long sentences, ban-list hits and preambles, per harness and project
```

You get numbers per project, and the weekly digest names a median over 150 words. Details: [WRITING.md](WRITING.md).

### The plugin

`plugin/` is a Claude Code plugin with no server behind it:

- `/teyla:rule <sentence> [--scope glob]` → `.claude/rules/<slug>.md` (+ mirrored into `AGENTS.md`)
- `/teyla:correct <what was wrong>` → `~/.teyla/corrections/<repo>-<hash>.jsonl` (outside the repo, 0600, secrets replaced by `[redacted]`), then proposes the rule
- skills: **harvest** (sessions → skill draft + candidate rules + routine manifest + a done-test *question*), **adoption-review** (`teyla monitor` → three concrete edits), **wiki-pass** (this session's facts → wiki pages as a PR you confirm or correct; see [docs/WIKI.md](WIKI.md)), and **tidy** (`teyla tidy --json` → proposed rewrites of dated anecdotes, duplicates and one-off history in the rule files, as a diff you approve)
- a `SessionStart` hook that orients each session: the machine CRITICAL alert and the spend alert first, then what is new since the last start, the weekly digest headline once, and the product's routines line; once a day it starts the update check and `teyla routine catch-up` in the background, and `teyla policy sync --quiet` when a generated copy is stale
- a `PreToolUse` hook on every tool call: while `~/.teyla/KILL` exists every call is denied, and during a `teyla run` the run's grants and caps are enforced (it fails closed)
- a `UserPromptSubmit` hook that captures correction-shaped prompts silently, into the same store (it needs the `teyla` CLI installed: the scrubber lives there, and with no scrubber nothing is written). `teyla corrections --recorded` lists what was stored; `teyla config set corrections.store=repo` keeps the pre-0.12 in-repo file instead. Either way `.teyla/` is added to the repo's `.git/info/exclude`, so an agent's `git add -A` cannot commit it
- **`/teyla:review`**: one P1/P2-only review of the branch's diff before a merge — a `codex-review`/`claude-review` script on PATH when there is one (cross-provider), else one fresh sub-agent given only the diff ("same-provider review"); at most two rounds
- **the machine guard** (`machine-guard.sh`, PreToolUse on `Bash`; on by default, no opt-in): before a shell command that starts heavy work — `xcodebuild`, `swift build|test`, `gradle`/`gradlew` with a task, `cargo build|test`, `bazel build|test` (kind `build`); `simctl boot|create|clone` (`sim`); `codex exec`, `codex-lane`, `codex-review`, `claude-review`, `claude -p`, `grok -p` (`lane`) — it asks `teyla load --admit build|sim|lane`. While the Mac is overloaded (or `guard.max_builds` / `max_sims` / `max_lanes` are reached) the call is refused with the numbers and what to do instead. Read-only invocations (`xcodebuild -list`, `simctl list|io|launch|shutdown|...`) are never gated. Agents that must build anyway wait for a slot: `teyla load --wait --kind build && xcodebuild ...`. Switch it off with `teyla config set guard.enabled=false`, or per shell with `TEYLA_GUARD=0`. It fails open (a missing or broken `teyla` never blocks work) and an ordinary command costs about 3 ms over the shell's own start and starts no Python and no `awk` (a command that merely names one of these tools, say a `.swift` file, pays one `awk`, about 2 ms more). `teyla harness sync` wires it into Codex and Grok too ([docs/HARNESSES.md](HARNESSES.md))
- two opt-in hooks, off by default (`teyla config set hooks.context_budget=true hooks.land_check=true`), for a machine that has no equivalent of your own:

  | hook | event | what it does |
  |---|---|---|
  | `context-budget.sh` | UserPromptSubmit, PostToolUse, SessionStart (compact) | at 240k tokens of context, then every 30k, the model writes a handoff to `~/.teyla/handoff/`; after Claude Code compacts (at ~300k with `"autoCompactWindow": 335000` in `~/.claude/settings.json`) it is put back once. Off, it costs one `awk` and starts no Python |
  | `land-check.sh` | Stop (Claude Code; Codex via `teyla harness sync`) | once per session, uncommitted files or commits on no remote are named with how to land them: open the PR/MR and merge only when the repo is in the `MERGE-APPROVED REPOS` block of `~/.claude/CLAUDE.md`, else stop at the PR/MR. Never a block |

```bash
claude plugin marketplace add zaitsew/teyla    # or a local path: claude plugin marketplace add ~/repos/teyla
claude plugin install teyla@teyla
```

### Routines, rules and the rest

- **Is the automated half running?** `teyla routines` and `teyla schedules` check every launchd job, cron line, desktop task and scheduled workflow against its last run ([Routines and checks](#routines-and-checks)).
- **Corrections that stick.** The plugin captures correction-shaped prompts and turns repeats into rules ([The plugin](#the-plugin)).
- **Review debt.** `teyla reviews` matches merged PRs against the review ledger.
- **Runs with guardrails.** `teyla run product:routine` runs a routine under capability grants (`fs.write:<glob>`, `shell:<verb>`, `net:<host>`, `send:<channel>`), caps and an idempotency key. It stops at a gate for your approval in `teyla inbox` and leaves a receipt. `teyla kill on` stops every run and denies every tool call. A routine earns gate B or C with ten consecutive clean receipts (`teyla promote`). See [docs/CONTROL-PLANE.md](CONTROL-PLANE.md).
- **Cloud sessions.** `teyla cloud check|prep|inbox`: what a cloud VM lacks in each repo, the files that give it your shipping rules, and the branches it left with no PR ([Cloud sessions](#cloud-sessions)).
- **Connectors and plugins.** `teyla connectors` shows, per MCP server, reads and writes, the empty and error rate, and the round-trips between human turns (advice C1–C4). `teyla plugins` runs a skill / rule / fact quality pass over installed Claude Code plugins.
- **Clean instruction files.** `teyla tidy` finds duplicates, dead imports and stale dated lines in rule and memory files. `teyla lang` keeps a repo's prose in English and leaves localization alone. `teyla rules stale` lists rules that expired or never fired. Every rule and policy write refuses invisible characters (bidi controls, zero-width, tags).
- **A facts wiki.** `teyla wiki` keeps facts as plain markdown pages that the agent writes and you confirm ([docs/WIKI.md](WIKI.md)).
- **Maintains itself, and leaves cleanly.** `teyla update` installs new releases, `teyla routine catch-up` runs the daily or weekly job launchd skipped while the Mac was off, `teyla remind` keeps dated to-dos only you can act on, and `teyla uninstall` reverses every file Teyla wrote.
- **An adoption report.** `teyla monitor` also reports correction rates and repeated corrections, and `--share` writes a redacted version (pseudonymous projects, connectors and private skills; no session ids, paths or correction text).

### Cloud sessions

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

### Where nothing can be installed

`prompts/adoption-review.md` is a self-contained prompt with the miner embedded: upload it to any Claude Code session, get `teyla-report.md` with aggregates only (no text, no paths; tool, skill and model names only; corrections as fingerprints), share it back by hand. `prompts/work-account-plugin-review.md` is the same idea for a corporate setup with a custom plugin and connectors.

## Privacy and safe mode

Teyla reads the transcripts and config already on your disk. It has no server, no account and no telemetry, and it never uploads a transcript. Every call that leaves your machine has a row in [PRIVACY.md](PRIVACY.md): the command, the host, what is sent, whether it runs without a flag, and what safe mode does. `tests/test_privacy_calls.py` fails when code starts a network call that the table does not list.

On a managed work laptop, switch on safe mode: `teyla policy init --work`. Nothing then reaches the network unless you pass `--allow-network` to the command you typed. Safe mode also stops self-update and runs repo commands only in the repos you list. `teyla uninstall --dry` lists every file Teyla wrote. See [WORK.md](WORK.md).

## Undo and uninstall

Every change an offer makes is logged in `~/.teyla/changes.jsonl` (mode 0600) with the file, the key, the old value and a hash of the file after the write. Before a write, the file is copied to `<file>.teyla-bak-<UTC time>`.

```bash
teyla changes              # every change Teyla made, and whether it is undone
teyla undo O1              # put back only the key Teyla wrote; later edits to the file survive
teyla undo O1 --force      # when the key itself changed since: put the old value back anyway
teyla uninstall --dry      # print every action, touch nothing
teyla uninstall            # unwire every harness, remove Teyla's hooks, links and jobs
teyla uninstall --keep-data   # the same, and keep ~/.teyla
uv tool uninstall teyla    # then remove the command; with pipx: pipx uninstall teyla
```

`teyla undo` covers O1 to O4. O5, O6 and O7 run `policy sync`, `harness sync` and `routine install`, and `teyla undo` points to `teyla uninstall` for them, which removes all of Teyla's links, hooks and jobs at once. When O6 also installed the Claude Code plugin, `teyla plugin uninstall teyla` removes that part alone. The rules for exact reversal are in [START.md](START.md#undo).

## More documents

- [START](START.md): `teyla start`: the diagnosis, the seven offers, how a saving is counted, how to undo
- [COMMANDS](COMMANDS.md): every command with its flags (`teyla help --all` prints the same list)
- [WEB](WEB.md), [TODAY](TODAY.md), [APP](APP.md), [RELAY](RELAY.md): the dashboard, the first screens, the Mac app and the iPhone relay
- [ASKS](ASKS.md), [PRODUCTS](PRODUCTS.md), [NOTES](NOTES.md), [INTENT](INTENT.md), [WRITING](WRITING.md): questions, products, notes, your words, how agents write
- [HARNESSES](HARNESSES.md): what each harness reads and what differs
- [PRODUCTIZE](PRODUCTIZE.md): from an app you use to an app four people use
- [CONTROL-PLANE](CONTROL-PLANE.md): runs, gates, receipts and the kill switch
- [WIKI](WIKI.md): the facts store
- [WORK](WORK.md): safe mode for a work laptop
- [PRIVACY](PRIVACY.md): every call that leaves your machine
- [BRAND](BRAND.md), [UX](UX.md): the mark, the colours, the voice, and the UX standard
- [MANUAL](MANUAL.md): the whole method and the numbers behind each threshold
- [ROADMAP](ROADMAP.md): what is next

## Prior art

- [gstack](https://github.com/garrytan/gstack) — pre-built role skills for Claude Code. Teyla harvests skills from *your* transcripts and adds the monitor and the policy; it uses gstack's review skills rather than replacing them.
- [TRACE](https://arxiv.org/abs/2606.13174) / [tellonce](https://github.com/YujunZhou/tellonce) — corrections compiled into enforced rules; the academic version of Teyla's rule loop.
- [ccusage](https://ccusage.com), claude-code-otel, cc-analyzer, cctime — token, cost and time dashboards across Claude Code, Codex and others. Teyla adds the correction, subagent-model and session-shape signals and the advice; it does not replace them.
- [AGENTS.md](https://www.morphllm.com/agents-md-guide) — the cross-harness instruction file Teyla syncs to.

Read [docs/MANUAL.md](MANUAL.md) for the whole method: skill / rule / fact, routines and the run loop, the nine-stage spine for building software, session discipline, and the numbers behind each threshold.

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

Every command, with flags: [docs/COMMANDS.md](docs/COMMANDS.md); `teyla --help` prints the same list.

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

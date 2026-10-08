# Teyla

**A local-first toolkit and method for working with AI agents.** It measures how you actually use Claude Code, Codex, Grok and Hermes, tells you what to change, keeps one policy across all of them, turns repeated work into routines, and makes your corrections stick.

Local-first. No data leaves your machine — the only outbound calls are GitHub release checks and self-updates (listed in [`prompts/onboard.md`](prompts/onboard.md)). `--share` produces a redacted report: pseudonymous projects, connectors and private skills; no session ids, paths or correction text.

```bash
uv tool install git+https://github.com/zaitsew/teyla      # or: pipx install git+https://github.com/zaitsew/teyla
teyla policy init --owner "Your Name" && teyla policy sync   # one POLICY.md (+ your CLAUDE.md rules) → Claude Code, Codex, Grok, Hermes, Cursor
teyla plugin install zaitsew/teyla   # the Claude Code plugin (or: claude plugin marketplace add zaitsew/teyla)
teyla harness sync                   # the same skills and hooks in Cursor, Codex, Grok and Hermes
teyla routine install                # daily: update, doctor, policy sync; weekly: monitor, routines, products, models
teyla doctor                         # everything that must be true here, and the fix for each thing that is not
teyla monitor --days 30              # the adoption report, with advice
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

## Why

Agentic coding makes shipping cheap and leaves the expensive questions unanswered: is any of it used, which model did the work, what did the same correction cost the third time, and what runs without you. Teyla was built after measuring a real setup and finding the tooling was never the bottleneck. What was missing:

- **A monitor.** Usage dashboards count tokens. As of September 2026 none we found reports correction-shaped turns, repeated corrections, the model your subagents silently inherited, governance-file edits, or sessions that ran 40 hours without a reset.
- **One policy.** Which model orchestrates and which does volume; when to get a second opinion from another provider; when to ask; when to stop. Written once, read by every harness.
- **Routines.** The work you prompt your way through every morning ("did it run?", "TestFlight status?") is a script and a digest, not a session.
- **Corrections that stick.** "Never use npm here, always pnpm" said four times is a rule nobody wrote down.
- **Productizing from day one.** A repo born with `AGENTS.md`, a first-run check, `.env.example`, a licence and CI is a repo someone else can use.

## What it does

| command | what you get |
|---|---|
| `teyla monitor [--days N] [--json]` | tokens by model and project, API-equivalent cost, orchestrator-tier share, subagent model mix, correction rate, cache-read ratio, giant sessions, governance-file edits, model ladder/price drift, headless calls per day by harness and project with their cost — plus advice A1–A20, and a "Cloud sessions" section from git |
| `teyla advise` | just the findings, each with the number that triggered it and one action |
| `teyla spend [--days N] [--json]` · `--alert` | what the last N days cost at API list price and which part bought nothing (W1–W8, each with a fix). `--alert` is the daily check: a session over `spend.alert_session_usd` in the last day, a project (`spend.budget.<project>`) or the whole day (`spend.daily_budget_usd`) over its budget yesterday, Actions past 80%, a product API spike. Each line names the amount, the budget, the top three sessions and the top model. The current alerts go to `~/.teyla/spend.alert` (removed when there are none), and the session-start banner shows the first line; the same alert is not said again the next day unless it grew by 25% (`--no-write` prints without touching either) |
| `teyla spend --by-day [--days N] [--json]` | one row per day: total cost, subagent cost, and subagent cost/calls by model tier (orchestrate / volume / triage / unknown) with the top tier's share. Cost is split by the day each message was sent |
| `teyla grok-cost [--last\|--session ID] [--cwd PATH] [--days N] [--by project\|session] [--json]` | what Grok CLI sessions cost at list price, ranked by dollars not tokens. `--last --cwd <repo>` is the one line an orchestrator reads when a `grok -p` lane ends (cost, calls, tokens, cached %, tools, context, effort, title); the default is the last 7 days by project (worktrees and `~/repos/<repo>` collapse to `<repo>`, a `<repo>-grok-empty` temp dir to `<repo>`, other temp dirs to `tmp`); `--by session` is the top 20. `teyla monitor`/`advise` add A13/A14 |
| `teyla sessions` / `teyla corrections --cluster` | one line per session; correction-shaped turns clustered into rule candidates |
| `teyla policy init [--claude-md --ops-root-init]\|status\|sync\|sync-repo` | `~/.agents/POLICY.md` imported by `~/.claude/CLAUDE.md`; `~/.codex/AGENTS.md` and `~/.grok/AGENTS.md` generated from POLICY.md + your own rules in `~/.claude/CLAUDE.md` (Codex cannot import a file; a plain symlink while CLAUDE.md holds only the import); appended to Hermes `SOUL.md`; `AGENTS.md ⇄ CLAUDE.md` in repos; `sync --quiet` is what the daily routine runs (silent when nothing changed, never creates POLICY.md or edits CLAUDE.md) |
| `teyla policy inbox [--done FILE\|--all]` | the hand edits `policy sync` found in a generated copy (a rule added to `~/.codex/AGENTS.md` from inside Codex) before it overwrote the copy, newest first with their added-line counts; `--done FILE` deletes one once you moved what should stay into `~/.agents/POLICY.md` or `~/.claude/CLAUDE.md`, `--all` deletes every one. `teyla doctor` warns `policy:inbox` while any wait |
| `teyla harvest <path>` | tool spines and corrections from every session that touched a path — the input to the harvest skill (skill = what was done the same way every time; everything else = candidate rules) |
| `teyla scaffold <path> --name X --kind cli\|app\|service\|ios` | a repo born plug-and-play |
| `teyla products` | real-usage counters from every repo's `./check.sh usage` — the "built, not used" detector; `products.repos` in config limits which repos' code it runs |
| `teyla routines [path...] \| --json` | is the automated half actually running, is the manual half actually confirmed working — from every repo's `teyla.toml` |
| `teyla routine install\|status` | Teyla's own Friday 20:45 launchd weekly (monitor, routines, products) |
| `teyla routines [--issues]` | every product's `teyla.toml`: routines that must run without you (loaded? last run? stale?) and manual checks you confirm (ok / broken / untested / re-test); `--issues` opens a GitHub issue per broken check |
| `teyla routine install\|status` | Teyla's own weekly LaunchAgent: monitor + routines + products reports into a dated folder |
| `teyla wiki init\|status\|lint\|confirm` | the facts store as an LLM-maintained wiki: the agent writes pages, you confirm or correct; works unchanged as a GitLab Wiki |
| `teyla feedback` | one redacted markdown file: environment, the shareable report, and a questionnaire — the way a second user tells the maintainer what is missing |
| `teyla models [--days N] \| --json \| --refresh` | credential presence, models available on this machine, newest catalogue entries with cost, and what `~/.agents/POLICY.md`'s ladder names — per provider, plus drift flags; exits 1 on drift |
| `teyla models watch [--refresh] [--json] [--ack [ID...]] [--seed FILE]` | the weekly "did a provider ship something to move to?": models in the catalogue that are not in `~/.teyla/models-known.json` (first run seeds it), the ladder entry each would replace, its price, and which git repos under `code_root` still name a superseded id; exits 1 while new models are unacknowledged; the weekly routine runs it and the digest names new models |
| `teyla reviews [--days N] [--json] [--quiet] [repo...]` | the review debt: for each repo under `code_root` with a GitHub remote, the PRs merged in the last N days (7) against the review ledger (`review.ledger`, default `~/.cache/review-ledger.tsv`, one TSV line per review: time, repo, commit sha, mode, P1, P2, reviewer): reviewed, merged with an open P1 (the newest reviewed commit still had one), skipped (a `skip` line), exempt (under `review.min_lines` changed lines, or docs only) or unreviewed, with the URL of each PR that needs a look. One `gh` call per repo, none in safe mode (`--allow-network` for one run); the weekly routine files it and the digest names the debt |
| `teyla models --write-policy [--dry]` | rewrite the ladder table between `<!-- ladder:start/end -->` in POLICY.md: keep what still resolves, replace what doesn't with the newest of the same family, print the diff |
| `teyla models --write-prices` | `~/.teyla/prices.json` from the models.dev catalogue, tiered from the ladder; `pricing.py` prefers it over its built-in table when present |
| `teyla lang [repo...] [--json] [--quiet] [--commits N]` | the "everything in a repo is English" check: tracked text files (and with `--commits N` the last N commit messages) holding non-Latin script — Cyrillic, CJK, Greek, Arabic, Hebrew — counted by kind (`doc`, `comment`, `string` = "check: localization?", `fixture`, `other`) with the top files and a sample line. Latin-script languages are not detected. Localization paths (`*.lproj`, `*.xcstrings`, `locales/`, `i18n/`, `l10n/`, `translations/`, `*.po`, `*.strings`, `Localizable*`, `messages/*.json`), a repo's `.teyla/lang-allow` (globs, `#` comments), `[lang] allow` in config and the `cyrillic:` section of `.leak-allow` are exempt. Always exits 0 (2 on a usage error); the weekly routine runs it with `--quiet` and the digest names the count |
| `teyla run <product:routine>` | the control plane: grants, caps, idempotency, gates A/B/C, a receipt naming the rules the run obeyed — see [docs/CONTROL-PLANE.md](docs/CONTROL-PLANE.md) |
| `teyla inbox` · `teyla kill` · `teyla triggers` · `teyla promote` · `teyla receipts` | the needs-you inbox, the kill switch, clock triggers as LaunchAgents, earned autonomy on ten clean approvals, the audit trail |
| `teyla harness status\|sync` | the plugin's skills and hooks, and the policy, in Cursor, Codex, Grok and Hermes — see [docs/HARNESSES.md](docs/HARNESSES.md) |
| `teyla config set harness.disabled=hermes,grok` | harnesses this machine does not use: `doctor`, `harness status\|sync\|verify` and `policy sync` skip them entirely (no health, credit, hook or auth lines), and `doctor` prints one `disabled: hermes, grok` line. Names: claude-code, codex, grok, hermes, cursor; an unknown one is a warning |
| `teyla harness verify [--live]` | can each harness do work now: version, auth (shape and dates, never a secret), the newest quota/auth error it recorded, interactive vs batch sessions in 7 days; `--live` sends one line through `claude -p`, `codex exec`, `grok -p`, `hermes -z` and checks the policy reached it |
| `teyla rule "<sentence>" [--scope <glob>]` · `teyla correct "<what was wrong>"` | what `/teyla:rule` and `/teyla:correct` do, as a CLI every harness's skill can call |
| `teyla rules propose [--write]` · `teyla rules stale` | a proposed rule diff from human corrections only (hook guesses ignored), hit counts on existing rules; expired and never-hit rules as removal candidates |
| `teyla doctor` | what Teyla can see on this machine |
| `teyla digest [--write]` | the weekly digest: at most five lines — the top three actions across advice, doctor, routines and checks, each with its command, plus a streak note |
| `teyla check <product> <check> ok\|broken [--note TEXT]` | confirm a manual check: sets `status` and today's `confirmed` in that product's `teyla.toml`, editing only those lines |
| `teyla uninstall [--dry] [--keep-data]` | every file Teyla wrote on this machine (`--dry`), then the undo: LaunchAgents unloaded, the policy import line, symlinks, Hermes sections, harness skills and hooks, the plugin, `~/.teyla`. Touches only what carries Teyla's marker, label or symlink target; keeps and lists `~/.agents/POLICY.md` and repo-level `.teyla/` and rules |
| `teyla prompt [name]` | the paste-able prompts (onboard, work-account-kickoff, …) that shipped with the installed version |
| `teyla cloud check [repo...] [--json]` | what a cloud session (Claude Code on the web, `claude --cloud`) would lack in each repo — the VM clones the repo and nothing from your home directory: instructions that defer to a home-directory policy file, `.claude/` git-ignored, no shipping rules or cloud done state, no SessionStart/Stop hooks, a `merge-approved:` line missing or drifted from your list, Mac-only gate steps with no printed skip, secret names with no manifest, a public repo. BLOCK/WARN/OK per item, exit 1 on any BLOCK; `teyla doctor` shows `cloud-ready n/N repos` |
| `teyla cloud prep <repo> [--dry] [--allow-public] [--fix-gitignore]` | writes what a cloud session needs into the repo, between `teyla:cloud` markers: a Shipping section in `AGENTS.md` (+ `@AGENTS.md` in `CLAUDE.md`), SessionStart/Stop hooks in `.claude/settings.json`, `.claude/rules/cloud.md`, `docs/cloud-setup.md`. See [Cloud sessions](#cloud-sessions) |
| `teyla cloud inbox [--days N]` | what cloud sessions left for a local one: branches with `Claude-Session:` commits and no PR (with the `gh pr create` line), and open PRs labelled `needs-mac` |
| `teyla storage [--json]` · `teyla storage clean [--apply]` | the disk and RAM agent work holds: every worktree (SAFE = clean, on the remote, idle, no process in it — removed with `git worktree remove`, branch kept), git-ignored build output of idle repos, caches with the command that clears each, booted simulators. Dry run unless `--apply`; `teyla config set storage.auto_clean=true` lets the daily routine do it |
| `teyla storage sims [--reap] [--dry] [--json]` | booted simulators: in use, or idle N min. `--reap` shuts down idle ones (`storage.sim_idle_min` 30, `storage.sim_max_booted` 3) and deletes shut-down devices matching `storage.sim_prune_pattern` (empty = never) after `storage.sim_prune_days` (3). `storage.sims_agent=true` makes `teyla routine install` run it every 10 minutes |
| `teyla storage procs [--kill] [--dry] [--json]` | dev processes an agent left behind whose worktree or temp folder is gone (`xcodebuild`, `swift-build`, `node`/`vite`/`next` dev servers, `python -m http.server`, ... per `storage.orphan_patterns`, matched on the executable or the interpreted script, never on other arguments): pid, RSS, age, command, why. Only the working directory decides that the folder is gone. Yours only, no terminal, running at least `storage.orphan_min_age_min` (30), never this process or its ancestors; when `ps` or `lsof` fails, nothing is an orphan. `--kill` sends SIGTERM, waits 10 s, then SIGKILL to the ones that are still the same process (pid and start time checked again, a kqueue exit watch read right before each signal). `storage.orphan_kill=true` makes the `storage.sims_agent` run it every 10 minutes; `teyla storage` and `teyla doctor` report the RAM they hold |
| `teyla storage sweep [--temp] [--dry] [--json]` | removes what agents leave behind, each category with its own age and process check: temp builds, release leftovers, old simulators, DerivedData, runtime and package caches, Docker, archived Grok sessions, old logs. `--temp` is the hourly subset; `--dry` shows the bytes only. Tuned by `storage.sweep_*` and `storage.docker_superseded_repos`; `storage.sweep_agent=true` schedules it, and the weekly routine then runs the full sweep. Log: `~/Library/Logs/teyla-sweep.log` |
| `teyla remind add "<what>" <YYYY-MM-DD> [--how "..."]` \| `list` \| `done <n>` | dated to-dos only a human can act on (a key that expires, a trial that ends); `teyla doctor` shows each as OK, then WARN within 30 days, then FIX once overdue |

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
| A13 | one project is over half of the week's Grok list-price cost (and the week is over $10) | `teyla grok-cost --by session --cwd <path>`; split or cap the loop |
| A14 | one Grok session cost over $10 | `teyla grok-cost --session <id>`; end long lanes at a merge |
| A15 | ≥3 turns in a week ended with the agent asking permission for the next step and the human answering a bare "yes" (only when POLICY.md declares `ask-permission`) | do the step and report it; ask only about product decisions or real blockers |
| A16 | a workflow runs on push, pull_request or schedule (only when POLICY.md declares `no-actions`) | `on: workflow_dispatch` only; `teyla doctor` lists every file |
| A17 | one project drives more than 200 headless calls a day through one harness (7-day average), or its headless calls doubled week over week (from 100 a week) — `claude -p`, `codex exec`, `grok -p` | check the routine means to call that often: cap it, batch items per call, or move it to a cheaper provider; the report's "Headless calls" table has calls/day and cost per harness and project |
| A18 | a harness recorded quota/balance or auth errors in the window (Grok 402 "usage balance exhausted", Hermes "missing access_token", `claude -p` "OAuth session expired", a Codex rate limit reached) — [high] while no later call succeeded | the exact fix (`hermes model`, `claude auth login`, top up); `teyla harness verify` |
| A19 | a cloud session's branch has commits and no PR after 24 h (found from `Claude-Session:` commit trailers; PR state from `gh`, never asked in safe mode) | `gh pr create --repo <owner/name> --head <branch> --fill`, then build and review it locally |
| A20 | in one project, more than 30% of subagent calls (from 10 calls) name an orchestrate-tier model explicitly (`model: "fable"`) — A1 only sees calls that inherit; evidence has the count, the share and the top tier's share of that project's subagent cost. `spend.a20_share`, `spend.a20_min_calls` set the thresholds; `spend.a20_models=opus,...` counts more names as top tier | route volume lanes to the volume tier (`model: sonnet`); keep the top tier for review and design, passed on that call only |

Spend thresholds are config, not constants: `teyla config set spend.alert_session_usd=250 spend.w1_usd=15 spend.daily_budget_usd=300 spend.budget.<project>=40` (the project as `teyla spend` names it: the repo directory, or the repo of a `~/.worktrees/<repo>/<branch>`). Budgets are API-equivalent dollars for one local calendar day; unset or 0 is off.

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
  `unknown`.
- **Check row** — name · status · confirmed · age in days · verdict: `ok` /
  `BROKEN` / `UNTESTED` / `RE-TEST` (confirmed more than 30 days ago).

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
a server, a domain, an identity provider, a mail sender, the Apple key, a secrets file —
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
app-a     owner->family  7/7 met
    [owner] internal TestFlight group - App Store Connect -> add two Apple IDs
notes     owner->family  1/7 met  unmet: R1 identity=shared-key, R2 tenancy=single,
                                        R3 backend=local-mac, R4 ios=none,
                                        R5 onboarding_doc unset, R7 cost_cap unset (llm=app-key)
    [agent] no per-user rows - add user_id + RLS, backfill existing rows to the owner
```

It also checks the first screen: family and public products must open on a sign-in (skippable
only when the app genuinely needs no account) and must never show sample data as the user's own.

`--owner-steps` collapses every product *and* the platform into one numbered list of things
only you can do, platform first, because one mail sender unblocks three products.
`teyla scaffold --kind app` writes the block, a `docs/GETTING-STARTED.md` addressed to a
person who is not you, and `deploy/droplet/` fragments for the shared server; the server
itself is five scripts and a runbook in `templates/platform/`.

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

- `AGENTS.md`: a Shipping section (one PR per logical unit, merge-not-squash, no force-push, no
  CI on push/PR (short ubuntu deploy jobs on push to main allowed) when your policy says so, report honestly, ask about product decisions not
  permission) and `merge-approved: yes|no`, derived from your MERGE-APPROVED list. `teyla cloud
  check` fails when the line drifts from the list.
- The cloud definition of done: the gate ran and its output is in the PR body, the branch is pushed,
  a PR is open, and it carries the `needs-mac` label when a Mac-only step was skipped. Second opinion:
  "same-provider review".
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

1. **The model ladder.** The most capable model of a provider orchestrates; cheaper tiers do volume. Anthropic: Fable 5.1 → Opus 5 / Sonnet 5 → Haiku 4.5. OpenAI: GPT-6 Astra → GPT-6 → mini. xAI: Grok 4.6 → Grok 4.5. Say which model did what. `teyla models` keeps this table current against models.dev, each CLI's own cache, and which credentials are actually on this machine; `--write-policy` proposes the update.
2. **Second opinions across providers** before non-trivial designs and anything touching money, credentials or other people's data. One pass.
3. **Tool ladder**: connector/MCP → CLI/API → browser extension → computer use. Fall one rung at a time and say so.
4. **Ask about product decisions with a proposed default; never ask for permission to proceed.**
5. **Stop only at a real blocker** (a key, a payment, a sign-in): do everything around it, open the exact page, name the exact file and line, hand over one line.
6. **Plug-and-play is the definition of done.**
7. **Say what is unverified.**

**Edits to a generated copy are kept.** `policy sync` keeps the sha256 of everything it writes (`~/.teyla/state/policy-written.json`, with a copy of the text). Before it overwrites a copy whose hash no longer matches, it files the difference (the lines added and removed since the last write) in `~/.teyla/policy-inbox/<harness>-<date-time>.md`, with the instruction to move what should stay into `~/.agents/POLICY.md` or `~/.claude/CLAUDE.md`, the two sources; only then does it overwrite. For the Hermes `SOUL.md` only Teyla's own section is compared, never your text around it. With no record yet (the first sync after an upgrade) the copy is compared with what sync would write now, and only added lines count. The daily routine runs `teyla policy sync --quiet`, so an edit made in Codex today reaches the inbox tomorrow morning instead of vanishing silently at the next manual sync. `teyla policy inbox` lists what waits, `teyla doctor` warns while anything does, and the session-start line says how many.

## The plugin

`plugin/` is a Claude Code plugin with no server behind it:

- `/teyla:rule <sentence> [--scope glob]` → `.claude/rules/<slug>.md` (+ mirrored into `AGENTS.md`)
- `/teyla:correct <what was wrong>` → `~/.teyla/corrections/<repo>-<hash>.jsonl` (outside the repo, 0600, secrets replaced by `[redacted]`), then proposes the rule
- skills: **harvest** (sessions → skill draft + candidate rules + routine manifest + a done-test *question*), **adoption-review** (`teyla monitor` → three concrete edits), and **wiki-pass** (this session's facts → wiki pages as a PR you confirm or correct; see [docs/WIKI.md](docs/WIKI.md))
- a `UserPromptSubmit` hook that captures correction-shaped prompts silently, into the same store (it needs the `teyla` CLI installed: the scrubber lives there, and with no scrubber nothing is written). `teyla corrections --recorded` lists what was stored; `teyla config set corrections.store=repo` keeps the pre-0.12 in-repo file instead. Either way `.teyla/` is added to the repo's `.git/info/exclude`, so an agent's `git add -A` cannot commit it
- **`/teyla:review`**: one P1/P2-only review of the branch's diff before a merge — a `codex-review`/`claude-review` script on PATH when there is one (cross-provider), else one fresh sub-agent given only the diff ("same-provider review"); at most two rounds
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

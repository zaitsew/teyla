# Teyla

**A local-first toolkit and method for working with AI agents.** It measures how you actually use Claude Code, Codex, Grok and Hermes, tells you what to change, keeps one policy across all of them, turns repeated work into routines, and makes your corrections stick.

Local-first. No data leaves your machine — the only outbound calls are GitHub release checks and self-updates (listed in [`prompts/onboard.md`](prompts/onboard.md)). `--share` produces a redacted report: pseudonymous projects, connectors and private skills; no session ids, paths or correction text.

```bash
uv tool install git+https://github.com/zaitsew/teyla      # or: pipx install git+https://github.com/zaitsew/teyla
teyla policy init --owner "Your Name" && teyla policy sync   # one POLICY.md → Claude Code, Codex, Grok, Hermes
teyla plugin install zaitsew/teyla   # the Claude Code plugin (or: claude plugin marketplace add zaitsew/teyla)
teyla harness sync                   # the same skills and hooks in Cursor, Codex, Grok and Hermes
teyla routine install                # daily: update + doctor; weekly: monitor, routines, products, models
teyla doctor                         # everything that must be true here, and the fix for each thing that is not
teyla monitor --days 30              # the adoption report, with advice
```

After that it keeps itself current: `teyla update` (run daily by the routine, and at session
start by the plugin hook on machines where launchd is off limits) installs a newer published
release by its commit sha and checks the version it built (`update.pin` freezes it,
`update.channel=none` stops the routine),
merges template changes into your `POLICY.md` three-way so your edits survive, refreshes the
plugin copy Claude Code actually loads, and rewrites the launchd wrappers if the binary moved.
`teyla doctor` is the checklist; its one-line summary shows at the next session start.

**On a work laptop** (a managed Mac, a TLS-inspecting proxy, the employer's code in every transcript), switch on safe mode first:

```bash
uv tool install "teyla[work] @ git+https://github.com/zaitsew/teyla"   # [work] = truststore: the OS keychain holds the proxy's root CA
teyla policy init --work --owner "Your Name" && teyla policy sync     # approved providers only, same-provider reviews; sets safe.enabled=true
teyla config set products.repos=<repo>,<repo>                          # the only repos whose ./check.sh usage Teyla may run
teyla doctor                                                           # first line: safe: on (network off, no auto-update, no repo commands)
```

Safe mode (`teyla config set safe.enabled=true`, or `TEYLA_SAFE=1`): nothing reaches the network unless you pass `--allow-network` to the command you typed (`teyla update --allow-network`); the session hook and the daily routine never update Teyla; `teyla products` runs `check.sh` only in `products.repos`; `routines --issues` is refused; `teyla plugin install|refresh` print the `claude plugin ...` commands instead of editing Claude Code's plugin registry; no keychain query.

No `uv`? `pipx install git+https://github.com/zaitsew/teyla`, or `git clone` and run `PYTHONPATH=src python3 -m teyla`. Python 3.11+, nothing else.

**Handing it to a second machine:** [`docs/HANDOVER.md`](docs/HANDOVER.md) lists every practice that travels and what to adapt; [`prompts/work-account-kickoff.md`](prompts/work-account-kickoff.md) is the paste-able version; [`prompts/work-account-update.md`](prompts/work-account-update.md) updates a machine that already has Teyla and switches on its self-maintenance. **Handing it to an agent instead of a person:** paste [`prompts/onboard.md`](prompts/onboard.md) into Claude Code, Codex or Grok on the new machine. It installs, wires the policy, installs the plugin, runs the first review, and produces the feedback file. Corporate machines: no data leaves the machine; every network call (release checks, the daily self-update) and every file Teyla writes are listed there, and `teyla uninstall --dry` lists what is on this machine (`teyla uninstall` reverses it). `teyla prompt onboard` prints the copy that shipped with the installed version.

## Why

Agentic coding makes shipping cheap and leaves the expensive questions unanswered: is any of it used, which model did the work, what did the same correction cost the third time, and what runs without you. Teyla was built after measuring one real setup and finding the tooling was never the bottleneck. What was missing:

- **A monitor.** Usage dashboards count tokens. As of September 2026 none we found reports correction-shaped turns, repeated corrections, the model your subagents silently inherited, governance-file edits, or sessions that ran 40 hours without a reset.
- **One policy.** Which model orchestrates and which does volume; when to get a second opinion from another provider; when to ask; when to stop. Written once, read by every harness.
- **Routines.** The work you prompt your way through every morning ("did it run?", "TestFlight status?") is a script and a digest, not a session.
- **Corrections that stick.** "Never use npm here, always pnpm" said four times is a rule nobody wrote down.
- **Productizing from day one.** A repo born with `AGENTS.md`, a first-run check, `.env.example`, a licence and CI is a repo someone else can use.

## What it does

| command | what you get |
|---|---|
| `teyla monitor [--days N] [--json]` | tokens by model and project, API-equivalent cost, orchestrator-tier share, subagent model mix, correction rate, cache-read ratio, giant sessions, governance-file edits, model ladder/price drift — plus advice A1–A16 |
| `teyla advise` | just the findings, each with the number that triggered it and one action |
| `teyla grok-cost [--last\|--session ID] [--cwd PATH] [--days N] [--by project\|session] [--json]` | what Grok CLI sessions cost at list price, ranked by dollars not tokens. `--last --cwd <repo>` is the one line an orchestrator reads when a `grok -p` lane ends (cost, calls, tokens, cached %, tools, context, effort, title); the default is the last 7 days by project (worktrees and `~/repos/<repo>` collapse to `<repo>`, a `<repo>-grok-empty` temp dir to `<repo>`, other temp dirs to `tmp`); `--by session` is the top 20. `teyla monitor`/`advise` add A13/A14 |
| `teyla sessions` / `teyla corrections --cluster` | one line per session; correction-shaped turns clustered into rule candidates |
| `teyla policy init [--claude-md --ops-root-init]\|status\|sync\|sync-repo` | `~/.agents/POLICY.md` imported by `~/.claude/CLAUDE.md`, symlinked as `~/.codex/AGENTS.md` and `~/.grok/AGENTS.md`, appended to Hermes `SOUL.md`; `AGENTS.md ⇄ CLAUDE.md` in repos |
| `teyla harvest <path>` | tool spines and corrections from every session that touched a path — the input to the harvest skill (skill = what was done the same way every time; everything else = candidate rules) |
| `teyla scaffold <path> --name X --kind cli\|app\|service\|ios` | a repo born plug-and-play |
| `teyla products` | real-usage counters from every repo's `./check.sh usage` — the "built, not used" detector; `products.repos` in config limits which repos' code it runs |
| `teyla routines [path...] \| --json` | is the automated half actually running, is the manual half actually confirmed working — from every repo's `teyla.toml` |
| `teyla routine install\|status` | Teyla's own Monday 07:30 launchd weekly (monitor, routines, products) |
| `teyla routines [--issues]` | every product's `teyla.toml`: routines that must run without you (loaded? last run? stale?) and manual checks you confirm (ok / broken / untested / re-test); `--issues` opens a GitHub issue per broken check |
| `teyla routine install\|status` | Teyla's own weekly LaunchAgent: monitor + routines + products reports into a dated folder |
| `teyla wiki init\|status\|lint\|confirm` | the facts store as an LLM-maintained wiki: the agent writes pages, you confirm or correct; works unchanged as a GitLab Wiki |
| `teyla feedback` | one redacted markdown file: environment, the shareable report, and a questionnaire — the way a second user tells the maintainer what is missing |
| `teyla models [--days N] \| --json \| --refresh` | credential presence, models available on this machine, newest catalogue entries with cost, and what `~/.agents/POLICY.md`'s ladder names — per provider, plus drift flags; exits 1 on drift |
| `teyla models --write-policy [--dry]` | rewrite the ladder table between `<!-- ladder:start/end -->` in POLICY.md: keep what still resolves, replace what doesn't with the newest of the same family, print the diff |
| `teyla models --write-prices` | `~/.teyla/prices.json` from the models.dev catalogue, tiered from the ladder; `pricing.py` prefers it over its built-in table when present |
| `teyla run <product:routine>` | the control plane: grants, caps, idempotency, gates A/B/C, a receipt naming the rules the run obeyed — see [docs/CONTROL-PLANE.md](docs/CONTROL-PLANE.md) |
| `teyla inbox` · `teyla kill` · `teyla triggers` · `teyla promote` · `teyla receipts` | the needs-you inbox, the kill switch, clock triggers as LaunchAgents, earned autonomy on ten clean approvals, the audit trail |
| `teyla harness status\|sync` | the plugin's skills and hooks, and the policy, in Cursor, Codex, Grok and Hermes — see [docs/HARNESSES.md](docs/HARNESSES.md) |
| `teyla rule "<sentence>" [--scope <glob>]` · `teyla correct "<what was wrong>"` | what `/teyla:rule` and `/teyla:correct` do, as a CLI every harness's skill can call |
| `teyla doctor` | what Teyla can see on this machine |
| `teyla uninstall [--dry] [--keep-data]` | every file Teyla wrote on this machine (`--dry`), then the undo: LaunchAgents unloaded, the policy import line, symlinks, Hermes sections, harness skills and hooks, the plugin, `~/.teyla`. Touches only what carries Teyla's marker, label or symlink target; keeps and lists `~/.agents/POLICY.md` and repo-level `.teyla/` and rules |
| `teyla prompt [name]` | the paste-able prompts (onboard, work-account-kickoff, …) that shipped with the installed version |
| `teyla storage [--json]` · `teyla storage clean [--apply]` | the disk and RAM agent work holds: every worktree (SAFE = clean, on the remote, idle, no process in it — removed with `git worktree remove`, branch kept), git-ignored build output of idle repos, caches with the command that clears each, booted simulators. Dry run unless `--apply`; `teyla config set storage.auto_clean=true` lets the daily routine do it |
| `teyla remind add "<what>" <YYYY-MM-DD> [--how "..."]` \| `list` \| `done <n>` | dated to-dos only a human can act on (a key that expires, a trial that ends); `teyla doctor` shows each as OK, then WARN within 30 days, then FIX once overdue |

### The advice rules

| id | fires when | action |
|---|---|---|
| A1 | >50% of subagent calls inherited the parent model | pass `model:` explicitly; cheap tier reads, mid tier builds, top tier reviews |
| A2 | >60% of output tokens on the orchestrate tier | route volume work down the ladder |
| A3 | sessions >8 MB, >12 h, or ≥3 compactions | one session per logical unit; end it after the PR merges |
| A4 | cache-read per output token >150× | shorter sessions, subagents for reading |
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

### Policy detectors

A rule in POLICY.md that nobody measures holds until the first busy week: the no-Actions rule
was broken three times in September 2026 while it sat in every harness's context. Rules that
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
| `ask-permission` | the marker (in the template's §4), or the §4 wording "not about permission" | Claude Code and Codex turns whose last paragraph asks permission for one step ("Want me to push them?", "Делать?") that the human answered with a bare yes; choices ("A or B?"), blockers (keys, payments, merges, deploys, deletes) and real answers do not count | advice A15 |

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

`teyla routine install` writes and loads Teyla's own weekly launchd job
(`~/Library/LaunchAgents/com.zaitsew.teyla.weekly.plist`, Monday 07:30) that
runs `teyla monitor`, `teyla routines` and `teyla products` and files the
output under `<ops_root>/runs/<date>/` (or `<ops_root>/startup/os/ai-dev/runs/` where that
tree exists). `teyla routine status`
shows whether it is loaded and its last log lines.

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
apple     ok       3 ids, 1 key(s), ~/ops/bin/testflight
```

Every missing row names the URL where the thing is created and the file and key where its
value goes; the command exits 1 while anything is missing.

`teyla productize` reads a `[productize]` block in each repo's `teyla.toml` — who it serves,
who it should serve, platforms, identity, tenancy, backend, distribution, secrets, cost cap
— and says what is in the way:

```
cellar    owner->family  7/7 met
    [owner] internal TestFlight group - App Store Connect -> add two Apple IDs
lang      owner->family  1/7 met  unmet: R1 identity=shared-key, R2 tenancy=single,
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

## The policy

`templates/POLICY.md` is the one file every harness reads. Its spine:

1. **The model ladder.** The most capable model of a provider orchestrates; cheaper tiers do volume. Anthropic: Fable 5.1 → Opus 5 / Sonnet 5 → Haiku 4.5. OpenAI: GPT-6 Astra → GPT-6 → mini. xAI: Grok 4.6 → Grok 4.5. Say which model did what. `teyla models` keeps this table current against models.dev, each CLI's own cache, and which credentials are actually on this machine; `--write-policy` proposes the update.
2. **Second opinions across providers** before non-trivial designs and anything touching money, credentials or other people's data. One pass.
3. **Tool ladder**: connector/MCP → CLI/API → browser extension → computer use. Fall one rung at a time and say so.
4. **Ask about product decisions with a proposed default; never ask for permission to proceed.**
5. **Stop only at a real blocker** (a key, a payment, a sign-in): do everything around it, open the exact page, name the exact file and line, hand over one line.
6. **Plug-and-play is the definition of done.**
7. **Say what is unverified.**

## The plugin

`plugin/` is a Claude Code plugin with no server behind it:

- `/teyla:rule <sentence> [--scope glob]` → `.claude/rules/<slug>.md` (+ mirrored into `AGENTS.md`)
- `/teyla:correct <what was wrong>` → `~/.teyla/corrections/<repo>-<hash>.jsonl` (outside the repo, 0600, secrets replaced by `[redacted]`), then proposes the rule
- skills: **harvest** (sessions → skill draft + candidate rules + routine manifest + a done-test *question*), **adoption-review** (`teyla monitor` → three concrete edits), and **wiki-pass** (this session's facts → wiki pages as a PR you confirm or correct; see [docs/WIKI.md](docs/WIKI.md))
- a `UserPromptSubmit` hook that captures correction-shaped prompts silently, into the same store (it needs the `teyla` CLI installed: the scrubber lives there, and with no scrubber nothing is written). `teyla corrections --recorded` lists what was stored; `teyla config set corrections.store=repo` keeps the pre-0.12 in-repo file instead. Either way `.teyla/` is added to the repo's `.git/info/exclude`, so an agent's `git add -A` cannot commit it

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

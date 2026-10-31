# Shield: nothing leaves that was not meant to

Status: concept and roadmap, 2026-10-31. Wave 1 starts the same night. Decisions are numbered
SH1–SH14 so later docs can cite them.

Shield is the part of Teyla that owns what must not leave: secrets, the owner's own data, and
the users' data. It is the leak gate every repo runs before a commit, a push and a PR; the hook
that stops an agent from publishing a secret or reading a credential file; the security contract
a product declares in `teyla.toml` and proves before a release; the outbound-host inventory; the
tests that an MCP server cannot be turned against its owner; and the weekly read of what the
dependency set and the stores now require.

## 1. Why

The owner on 2026-10-31, translated from Russian:

- "When the UX, UI and copy work is done, go through cybersecurity as well: how do we make sure
  nothing leaks, so that the product is safe both for me and for users."
- "Confidential information must not leak to the network, and products and GitHub must not
  include confidential information or information specific to me."
- "Should this be part of Teyla or a separate product?"
- "The system must be as AI-native as possible and lead to the best result; it must be resilient
  to attacks and anticipate expectations."
- "Research it seriously together with Grok and Codex, work out a detailed concept and roadmap,
  and launch an autonomous sprint."

Earlier, 2026-10-02 (`teyla intent teyla`): "what about using Teyla for my work tasks from the
work laptop; we already did a sprint to raise security. Think whether more is needed." That
sprint produced safe mode (`net.py`) and the privacy ledger. This one covers the rest.

## 2. What exists, and why it did not add up

| Piece | Where | What it does today |
|---|---|---|
| Leak check | `scripts/leak_check.py`, run by `./check.sh` and `.githooks/pre-push` | Tracked files, commit messages, authors and the lines commits add: private terms from a list outside the repo, e-mail addresses, home paths, 14 secret shapes, Cyrillic. Allowlist in `.leak-allow`. 43 tests |
| Private terms | `~/.config/teyla/private-terms.txt` | 46 lines: the owner's names, products, hosts. Never in a repo |
| Privacy ledger | `docs/PRIVACY.md`, `tests/test_privacy_calls.py` | Every call that leaves the Mac is a numbered row; a static tripwire fails when a module gains a network pattern without a row |
| Safe mode | `src/teyla/net.py`, `teyla config set safe.enabled=true` | One gate every outbound call asks; `--allow-network` for a command typed by hand |
| Scrubber | `corrections.scrub()`, `monitor.redact()` | Secret-shaped strings become `[redacted]` before a correction or a report is stored |
| Kill switch, grants | `plugin/hooks/pre-tool-use.sh`, `teyla.control` | `~/.teyla/KILL` denies every tool call; a `teyla run` enforces its declared capabilities |
| Machine guard | `plugin/hooks/machine-guard.sh`, `teyla load` | Refuses a build, a simulator or a headless lane while the Mac is overloaded |
| Review gate | `~/ops/bin/review-gate` (the owner's hook) | Refuses `gh pr merge` without a cross-provider review in the ledger, or with an unfixed P1 |
| Product manifest | `[productize]` in `teyla.toml`, `teyla productize` | Who the product serves, identity, tenancy, backend, secrets, ten requirements |
| Policy | `~/.agents/POLICY.md` §2, §11, §15 | Mandatory review for money, credentials and user data; nothing paid without a double yes; store review rules |

Across ten product repos on 2026-10-31 (a Haiku scout, read-only): no repo runs a secret scan;
half have no git hooks at all; the private-terms list is enforced in Teyla's repo and nowhere
else. Owner data sits in public docs. No repo has a `SECURITY.md`, a privacy ledger or a threat
model. The per-server findings (authorisation, keys in URLs, rate limits) are in the owner's
private notes, not here: SH1 keeps findings in private configuration until they are fixed, and
each one became a generic check in §5.5 instead of a sentence in a public document.

What the pieces miss, in five lines:

1. **The gate exists in one repo.** The leak check guards Teyla; the products ship with none.
   An agent that commits a key into a product repo meets nothing until the key is on GitHub.
2. **The agent publishes outside the tree.** PR bodies, issue comments, commit messages and
   release notes never pass a hook. `CONTRIBUTING.md` asks for a manual `--text` check; nobody
   runs it at 3 a.m.
3. **Nothing says what a product sends where.** The ledger is Teyla's own. A product's hosts
   live in its code, unlisted; a new host is a one-line change nobody reviews as a disclosure.
4. **Nothing proves the server side.** RLS, MCP authorisation, rate limits and SSRF guards are
   written once and never tested from the attacker's seat.
5. **Security is remembered, not declared.** POLICY §2 says which PRs need a `--high` review;
   no file in a product says its tier, its data classes and what must hold before a release.

## 3. The research behind the decisions

Four sources on 2026-10-31: a Codex consult (GPT-6 Astra, high effort, read-only on this
checkout), a web research pass (Claude Sonnet 5.5, ~110 fetched pages), a Grok 4.7 pass over X
and the open web for the last 90 days ($1.43, 692k input tokens, 81% cached), and a Haiku 5.5
scout over ten product repos. The findings that shaped the design:

- **Agents double the leak rate.** GitGuardian measured Claude Code-assisted public commits at a
  3.2% secret-leak rate against a 1.5% baseline, counted 24,008 secrets in public MCP config
  files, and found 64% of secrets valid in 2022 still valid in 2026
  ([GitGuardian, 2026-03-17](https://blog.gitguardian.com/the-state-of-secrets-sprawl-2026-pr/)).
  Scanning without same-day rotation is a log, not a defence.
- **The scanner must see the index, not the worktree.** A pre-commit hook that reads working-tree
  files passes a secret that is staged but not saved, and blocks one that is saved but not staged.
  Gitleaks 8.30.1 is installed and scans `--staged` and `--log-opts` ranges with `--redact`
  ([Gitleaks](https://github.com/gitleaks/gitleaks)); it receives security patches only, with
  Betterleaks as the named successor, so it stays a second engine behind Teyla's own rules.
- **Pushing is not the only way out.** PixelLeak (2026-09-30): agents uploaded 13,000+ internal
  screenshots to 900+ public repos; one agent created a public repo to host a screenshot it could
  not attach ([Help Net Security](https://www.helpnetsecurity.com/2026/09/30/ai-coding-agents-github-screenshot-leak/)).
  Publication payloads (PR bodies, issues, gists, new public repos) need the same gate as commits.
- **The repo can attack the agent.** The October `testmetest` campaign planted
  `.claude/settings.json`, `.cursor/mcp.json`, `.gemini/settings.json` and `.vscode/tasks.json`
  in 42 hijacked repos; CVE-2026-21852 had Claude Code apply `ANTHROPIC_BASE_URL` from repo
  settings before the trust prompt (fixed in 2.0.65)
  ([devops.com](https://devops.com/two-github-campaigns-one-weak-point-stolen-developer-credentials/),
  [Check Point, 2026-02-25](https://blog.checkpoint.com/research/check-point-researchers-expose-critical-claude-code-flaws/)).
  Harness config files in a repo are a surface the leak gate reads.
- **Prompt injection is not solved by a better model.** Anthropic: "far from a solved problem",
  1.4% attack success with safeguards under 100 adaptive attempts
  ([Anthropic, 2025-11-24](https://www.anthropic.com/research/prompt-injection-defenses)); auto
  mode's classifier misses 17% of real overeager actions
  ([Anthropic, 2026-03-25](https://anthropic.com/engineering/claude-code-auto-mode)); Log-To-Leak
  exfiltrated through a poisoned MCP description on 62–100% of model–server pairs
  ([arXiv 2610.36108](https://arxiv.org/abs/2610.36108)). The reliable move is Willison's: cut one
  leg of the lethal trifecta, usually egress
  ([Willison, 2025-06-16](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/)); Meta's
  Rule of Two says the same ([Meta, 2025-10-31](https://ai.meta.com/blog/practical-ai-agent-security/)).
  Codex's framing: a label saying "untrusted data" is context, not containment; test
  authorisation and captured effects, not labels.
- **The public key is not the breach; the missing policy is.** Of 1,072 vibe-coded Supabase
  apps, 172 let anyone delete rows with no login; the "98% flawed" figure counts missing headers
  ([Symbiotic, 2026-06](https://symbioticsec.ai/blog/we-scanned-1-072-vibe-coded-apps-98-had-security-flaws)).
  Moltbook: public key plus no RLS exposed 1.5M tokens
  ([Wiz, 2026-02](https://wiz.io/blog/exposed-moltbook-database-reveals-millions-of-api-keys)).
  RLS enabled is not enough: `security definer` views and privileged roles bypass it
  ([Supabase docs](https://supabase.com/docs/guides/database/postgres/row-level-security)). The
  test is anonymous, user A and user B against every table, bucket and RPC.
- **Autonomous attackers use old bugs.** NorForge's Cairn report (2026-10-19): one operator's
  agents hit 1,200+ sites, breached 100+ in about 23 hours each, through unauthenticated RCE,
  SQL injection, uploads and deserialisation; the attackers' own open panels were the softest
  target in the story ([NorForge](https://norforge.com/blog/inside_cairn)). For small Next.js
  sites the same habit finds an unpatched React Server Components bug (CVE-2025-55182) and an
  admin route without a session. Patch cadence and authorisation beat exotic defences.
- **The agent's own config is a secret store.** OpenCode Console (2026-10-17) exposed linked
  provider keys; Warp lost agent logs; Command Code revoked every key on 2026-10-28; the Gheist
  wave used stolen GitHub tokens to plant workflows that print CI secrets on 13,500+ branches
  ([summary](https://www.drchaos.com/blog/opencode-console-breach-stolen-ai-api-keys),
  [theinjection.dev](https://theinjection.dev/learn/credential-theft/)). Transcripts, harness
  configs and tokens in the home directory are in scope for the gate, read-only.
- **On Apple platforms the failures are small and known.** A token in `UserDefaults` is a plist
  anyone with the Mac can read; `kSecAttrSynchronizable` puts a Keychain item in iCloud; a key
  in the binary is extractable; a required-reason API without a `PrivacyInfo.xcprivacy` reason
  is upload failure ITMS-91053. Static rules catch all four.
- **Prices (2026-10-31, vendor pages).** GitHub push protection: free on public repos; on
  private repos it is GitHub Secret Protection at $19 per active committer per month on a Team
  plan, the charge POLICY §11 was written about. Doppler $8 per user per month after three users;
  Infisical Pro $20 per identity per month; 1Password Individual $3.99 per month; GitGuardian
  Starter free for 25 developers. Gitleaks, TruffleHog, OSV-Scanner, Invariant's `mcp-scan`,
  Promptfoo and the Supabase security advisors are free. Everything in this concept runs on the
  standard library, gitleaks and the subscriptions already paid for: **$0 added**.
- **What Codex called theatre.** A hostname grep without runtime capture (documentation, not
  control); label-only injection tests; a weekly scout that summarises generic threats without
  matching installed versions; a checklist of permanent checked boxes; a red team before
  isolation and recovery exist. And what every candidate list missed: credential separation
  (a worker with production, merge or deploy credentials can bypass every local hook through
  the GitHub API), dependency patching, cross-tenant tests, backup restoration, security-event
  visibility and incident response.

## 4. Decisions

- **SH1. Shield is part of Teyla, not a separate product.** Teyla already holds the leak check,
  the private-terms convention, the privacy ledger, safe mode, the hooks, the product manifest
  and the review ledger; a second repo would copy all of it and drift. Teyla's users are solo
  builders with agents, who have the same problem. Three locations, as Codex put it: Teyla holds
  the generic detectors, hook adapters, schemas, templates and tests; a product repo holds its
  security contract and its own regression tests; private local configuration (`~/.config/teyla/`,
  `~/.teyla/`) holds the confidential terms, infrastructure mappings, findings and exceptions.
  Public Teyla fixtures use invented products and identities, never the owner's portfolio.
  Shield promises **documented, restricted disclosure**, not "nothing can leak": a remote model
  reads its context, an MCP client reads its results. What must never reach a provider stays
  outside the agent's readable environment.
- **SH2. Deterministic checks decide; models investigate and propose.** A merge gate, a
  pre-push hook, a release check and a hook refusal are code with fixed rules and exit codes. A
  model classifies a finding, explains its impact, drafts a regression test, proposes a fix,
  writes synthetic attack cases. A model never grants a permission, clears a secret finding,
  edits a trusted baseline, approves its own exception or declares a release authorised.
- **SH3. One scanner, four doors.** `teyla leak` is the scanner; it is called from the agent
  hook (SH6), the pre-commit hook (the **index**, never the working tree), the pre-push hook
  (every outgoing ref, commits the remote lacks, tags and their messages) and `./check.sh` (the
  tree). Teyla's own rules (terms, e-mail, home path, secret shapes, Cyrillic) run first;
  gitleaks runs as a second engine when it is on the PATH, scoped to the same range, with
  `--redact`. One scanner means one allowlist, one output shape and one place to add a rule.
- **SH4. A scan answers "these findings in these surfaces", never "this cannot leak".** Exit 0:
  every requested surface read, no blocker. Exit 1: a blocker. Exit 2: a surface could not be
  read (no private-terms file, a shallow clone, an unreadable archive, gitleaks missing where
  the contract requires it); gates refuse both 1 and 2. Findings are classified **publishable**
  (in the tree or in an outgoing commit), **historical** (in reachable history, already on the
  remote: rotate first, rewrite later) or **local-only** (an ignored `.env`, a transcript). Output
  masks the match to its first two characters and never prints a private term; `--json` carries a
  keyed fingerprint per finding so an exception can name exactly one.
- **SH5. The private-terms list is the most sensitive file, and it is treated as one.** It
  stays in `~/.config/teyla/` (directory 0700, file 0600), outside every repo, every synced folder
  and every model context; a hook refuses to read it (SH6); `teyla leak` never prints a term.
  `teyla leak terms --suggest` proposes entries from facts the machine already knows (git
  author, the home user, the computer name, tester e-mails and bundle ids in `teyla.toml`, hosts
  in `platform.toml`), shows them masked, and appends only on `--yes`. Passwords and API keys
  never go in the list: the secret detectors cover them, the Keychain holds them. Identifiers
  that must ship (a public project URL, a publishable key) are not confidential; authorisation
  protects the data behind them, and the contract (SH8) says so.
- **SH6. The agent boundary is a hook, and it covers publishing, not only pushing.** A
  PreToolUse hook scans the text an agent is about to publish: `gh pr create|edit|comment|review`,
  `gh issue create|comment`, `gh release`, `gh gist`, `git commit -m` and `-F`, `git tag -m`. It
  refuses a read of a credential path (`~/.ssh/id_*`, `~/.aws/credentials`, the private-terms
  file, `~/.appstoreconnect/private_keys`, harness auth and config files), a Keychain dump
  (`security find-generic-password -w`, `dump-keychain`), and `gh repo edit --visibility public`
  on an existing repo (creating a new public repo stays allowed: the owner asks for it in
  kickoffs). Bash matching cannot stop every encoded payload; the hook is one door of four, not
  the wall. Two failure modes, chosen by what a wrong answer costs: the coarse path (is this a
  publication or a credential read at all?) fails open with a one-line warning, like the machine
  guard, because a guard that blocks every `ls` over its own bug gets uninstalled; but once a
  command is classified as a publication, a credential read or a visibility change, a scanner
  that cannot run is a refusal, not a pass. These commands are rare and explicit, and the cost of
  a wrong refusal is one retry. A publication has no second door inside git, so the weekly
  routine audits what was published anyway: `teyla leak --published` reads the week's PR bodies,
  issue comments, releases and gists through the GitHub API and reports a finding as
  historical (rotate first, then edit the text).
- **SH7. Cut a leg of the trifecta per product, in the contract.** Every MCP server and agent
  declares which legs it has: private data, untrusted content, outbound channel. A public
  research server has no private data. A personal-data server has no arbitrary URL fetch, no
  mail, no shell, no posting tool, and authorises every returned record. A coding worker has
  no production secret and no publishing credential. A research-to-action flow produces a
  proposal; a separate executor validates recipients and permissions. The tests (5.5) assert
  effects, not labels: a direct unauthorised call fails without a model in the loop; wrong-user
  reads fail; a synthetic secret never appears in a captured request, log or unrelated response.
- **SH8. A product declares its security contract and proves it with evidence that expires.**
  `[security]` in `teyla.toml`: tier (from `[productize] users`), data classes, trifecta legs,
  where secrets live, which hosts are documented, what the release requires. `teyla shield check`
  reads repo facts where it can (hooks installed, leak clean, hosts documented, lockfile pinned,
  RLS in migrations, a privacy manifest present, no token-named key in `UserDefaults`) and
  dated evidence where it cannot (an anonymous/A/B tenancy test run, a dependency audit), each
  with a commit and an age limit. A permanent checked box is theatre; a stale receipt is a FIX.
  The release path (POLICY §14, §15) runs it before an upload.
- **SH9. The outbound inventory starts static and becomes runtime.** `teyla hosts <repo>`
  extracts host literals from Swift, TypeScript, Deno, Kotlin and Python, plus manifests
  (ATS exceptions, image domains, edge-function config), and compares them with the product's
  `docs/PRIVACY.md`, the same table Teyla keeps for itself: an undocumented host is a FIX. Codex
  is right that a grep is documentation, not control: wave 2 adds the runtime adapters, a fetch
  wrapper for the web products that refuses an undocumented host, and a debug-build check on
  Apple platforms, both fed from the same table.
- **SH10. Dependency exposure is version-matched; the feeds scout comes later, with caps.**
  `teyla deps` reads every lockfile and asks the free OSV API for the installed versions; a
  known vulnerability with a fix available is a FIX. A weekly `teyla scout security` over feeds
  (platform policy changes, new attack classes) follows in wave 2 with the design scout's caps:
  feeds only, at most two proposals a week, never edits a rule, and an applicable advisory
  bypasses the cap.
- **SH11. Credential separation is the control that makes the others hold.** A worker lane
  edits and tests with no production, repository-administration, merge or deploy credential; a
  separate publisher step checks immutable inputs before pushing, merging or releasing. Today
  every session runs under the owner's `gh` login, so every local gate is bypassable through the
  API by the agent it guards. This is the owner's step list in §9: a fine-grained token per
  lane, no Actions scope, the review gate and the leak gate outside worker write access. Until
  then the gates are a seat belt, and the doc says so.
- **SH12. Nothing is bought.** The whole system is stdlib Python, gitleaks and the subscriptions
  already paid. GitHub Secret Protection ($19 per committer per month on private repos), a
  secrets manager, a hosted scanner and an X read API are §11 questions with their price in the
  label, asked twice, and none is needed for wave 1 or 2.
- **SH13. The machine is a budget.** No lane in Shield starts a build, a simulator or a database
  container; the MCP tests run against an in-process fake server in Teyla and against a staging
  URL in a product. A probe has a request budget and a time budget.
- **SH14. A red team comes after isolation, against staging, with caps.** Synthetic accounts and
  data, explicit targets, a fixed request and time budget, third-party hosts blocked, no real
  payment or message, cleanup, and findings written locally or to a private issue tracker the
  owner named. An unrestricted attack agent against production is one more vulnerability.

## 5. How it works

### 5.1 The leak gate

```
teyla leak [repo|--all]                 the tree (tracked files) and the local-only surfaces
teyla leak --staged                     the index: what the next commit would publish
teyla leak --outgoing [remote]          commits, tags and messages the remote lacks
teyla leak --commits <range>            an explicit range, as leak_check.py --commits
teyla leak --text <file|->              a PR body, an issue, a release note before it is sent
teyla leak --json                       findings with class, rule, fingerprint, masked excerpt
teyla leak --published [owner]          the week's PR bodies, issue comments, releases and gists, read back through the API (weekly)
teyla leak install [repo]               .githooks/pre-commit and pre-push, core.hooksPath
teyla leak terms --suggest [--yes]      private-term candidates from the machine, masked
```

**Surfaces.** Tracked text files (as today); the index as blobs (`git show :path`); outgoing
commits as `leak_check.py --commits` does, plus annotated tags; publication texts; `.env*` files
that are ignored or untracked but present (local-only); harness config files in the repo
(`.claude/settings.json`, `.cursor/mcp.json`, `.vscode/tasks.json`, `.mcp.json`: a `base_url`, a
`command` or a hook pointing outside the repo is a FIX, the `testmetest` class); `Info.plist` and
`.entitlements` through `plistlib`; `.xcstrings` through `json`; PNG text chunks and JPEG EXIF
GPS and author fields in images (a screenshot with a location is a FIX). Screenshot pixels are
not read: an e-mail shown on screen needs OCR and eyes, and the doc says so.

**Rules.** Teyla's five (term, email, home, secret, cyrillic) and gitleaks' default set, merged
as `gitleaks:<rule-id>`. Cyrillic stays a language-policy finding (`teyla lang`), reported with
`lang` severity, never as a leak. High-confidence secrets and private terms are blockers;
entropy-only matches and undocumented example values are **triage**, listed but not blocking,
so the owner is never trained to type an override. A finding is deduplicated by rule, path and
fingerprint; the same secret in ten commits is one finding with ten places.

**Allowlist.** `.leak-allow` keeps its sections. An exception names one finding: its rule, its
path glob, a reason, and an expiry date where the reason is temporary. A whole file is never
exempt from the secret rules. Editing `.leak-allow`, the private-terms list, the hook or the
scanner is itself a change the review gate treats as touching credentials (`--high`).

**Install.** `teyla leak install` writes `.githooks/pre-commit` (`teyla leak --staged`) and
`.githooks/pre-push` (`teyla leak --outgoing "$remote"`), sets `core.hooksPath`, and chains an
existing hook rather than replacing it. Where `teyla` is not installed the hook prints one line
and exits 2: a missing scanner is a coverage gap, not a pass. `TEYLA_LEAK=0` skips a hook for
one command, logged to `~/.teyla/leak-skips.log` so the skip is on record.

**What it does not do.** It does not rewrite history and it does not rotate a key. A historical
finding's first line is "rotate this credential today"; history rewriting is a separate,
deliberate step and never automatic.

### 5.2 The agent boundary

`plugin/hooks/leak-guard.sh`, PreToolUse on Bash and Read, pure `sh` on the common path like the
machine guard: a coarse `case` over the command, and only a command that publishes text or
touches a credential path pays for the Python classifier. Publishing: the body text (inline,
`-F file`, `--body-file`, a heredoc) goes through the leak rules; a finding is exit 2 with the
masked excerpt and the fix ("remove the key from the PR body; it is in the Keychain as X"). A
credential-path read, a Keychain dump and a visibility change are exit 2 with the reason. The
hook is registered in the plugin's `hooks.json` for Claude Code and documented for Codex and
Grok. It never reads the private-terms file itself for output; it calls `teyla leak --text -`.

### 5.3 The security contract

```toml
[security]
tier = "public"                        # owner | family | testers | public (from [productize] users)
data = ["account", "location", "messages"]
trifecta = ["private-data", "outbound"] # legs this product's agent surface has; the third is cut
secrets = "runtime-env"                 # runtime-env | keychain | hub | none (never: repo, client)
hosts = "docs/PRIVACY.md"               # the outbound table teyla hosts compares against
mcp = { auth = "bearer", url_key = false, rate_limit = true, static_tools = true }
rls = "migrations+ab-test"              # none | migrations | migrations+ab-test
release = ["leak", "hosts", "deps", "rls-test<30d", "privacy-manifest"]

[[security.evidence]]
what = "rls-test"
commit = "abc1234"
date = 2026-10-31
how = "deno task test:tenancy (anon, A, B on every table and RPC)"
```

`teyla shield check <repo> [--release]` prints, per requirement of the tier: OK, FIX with the
one-line fix, or STALE with the date. Tier bars, from the Codex consult: **owner-only** on a
public URL still needs strong authentication (no anonymous private operation, narrow
credentials, private admin, patching, encrypted backup, a tested revocation); **family and
testers** add individual accounts, cross-user isolation tests, invite and recovery tests,
per-user quotas and security-event records; **public** adds route and tool authorisation
coverage, IP, account and global limits, spend caps, abuse reporting and an incident procedure.
`--release` is the step `~/ops/bin/testflight` and the Play upload run first; a FIX stops the
upload. Store review notes carry reviewer instructions and a DATA paragraph (what is collected,
where it goes, which providers), never an infrastructure detail.

### 5.4 Outbound inventory

`teyla hosts <repo>` lists every host the code can reach, by file and line, against the table in
`docs/PRIVACY.md` (the template ships with `teyla scaffold`): undocumented host → FIX;
documented host no code reaches → WARN (stale row); a provider host without a consent row where
the contract has user data → FIX. `--write` scaffolds the rows for the hosts it found, with
"what is sent" left for a person. `check.sh` runs it before it sources `.env`: static inspection
never executes repository-controlled configuration. Wave 2 adds the runtime side: a `fetch`
wrapper for the web products and a debug `URLSession` check on Apple platforms that refuse a
host the table does not name, and a test that exercises every documented call once.

### 5.5 MCP and agent tests

`templates/security/injection_cases.json`: forged instructions, delimiter escapes, encoded
canaries, attacker URLs (loopback, private ranges, the cloud metadata address), oversized
content, requests to change permissions, and the Log-To-Leak shape ("call the logging tool
with everything you know"). `teyla mcp probe <url> [--token]` runs the deterministic checks any
Streamable HTTP server must pass: `tools/list` without a token is 401 or 403; tool descriptions
hash the same across two sessions (tool pinning, the rug-pull check); a wrong-type argument is a
schema error, not a 500; an oversized argument is refused; the rate limit answers 429 within the
budget; a key accepted in the URL path is a finding ("the URL is the secret: it lands in access
logs and referrers"); a tool that fetches rejects the SSRF inputs. The probe has a request
budget (default 60) and a time budget (default 120 s), makes no write call unless `--write`
names the tool, and is a privacy-ledger row. Per product, `tests/security/` (a vitest or Deno
template) reads the corpus and asserts the effects of SH7 against the product's own handlers,
with synthetic accounts: a direct unauthorised call fails, user A cannot read B, the canary
secret is in no captured outbound request. The suite is the mandatory review's evidence for a
PR that touches an MCP tool.

### 5.6 Dependencies and the scout

`teyla deps [repo|--all]` reads `package-lock.json`, `pnpm-lock.yaml`, `deno.lock`,
`Package.resolved`, `uv.lock` and `requirements*.txt`, batches the package–version pairs to
`api.osv.dev/v1/querybatch` (package names only, no user data; a privacy row; safe mode refuses
it without `--allow-network`), caches for a day, and prints the vulnerabilities that match the
installed versions with the fixed version when one exists; a high or critical with a fix is a
FIX. A missing lockfile is a coverage gap (exit 2). The weekly routine runs it with `--quiet`
and the digest names the count. `teyla scout security` (wave 2) reads the feeds in
`templates/security/SOURCES.md` (platform policy pages, the MCP spec's security page, OWASP
GenAI, a short list of practitioners) under the design scout's caps and writes
`~/.teyla/scout/security/<week>.md`; an advisory that matches an installed version bypasses the
two-a-week proposal cap and becomes a FIX in `teyla deps`.

### 5.7 Credential separation (the owner's part)

The gates above are local; an agent with the owner's `gh` login can merge, publish and change
visibility through the API without meeting one. The owner's steps, in order of leak prevented
per minute:

1. **A branch ruleset on every repo** that forbids direct pushes to the default branch and
   restricts merging and bypass to one identity, the publisher. Without it a token that can push
   a branch can push `main`, and separation is a label.
2. **A worker token per lane**, fine-grained: contents write (it needs to push its branch) and
   pull-request write (it needs to open the PR) on the repos it edits; no Actions, no
   administration, no secrets, no pages, no merge rights (the ruleset above denies it the merge
   even with contents write). A worker can therefore publish a PR body and a branch, which is
   why the agent hook scans publication text and the pre-push hook scans outgoing commits on
   the worker's own machine, and why the weekly `--published` audit reads what landed anyway.
3. **The publisher identity** (`gh auth` on the owner's account, or a second token with merge
   rights) runs only in the publishing step, after the review gate and the leak gate, from a
   directory outside every worktree (`~/ops/bin`), on immutable inputs: the reviewed commit sha,
   not a branch name.
4. **Provider keys** in the Keychain or the accounts hub, read at call time by the process that
   needs them, never exported into a lane's environment.
5. **A diff of `~/.claude/settings.json` and `~/.codex/config.toml`** against a known-good copy
   in the weekly routine (the habit the October installer campaign taught).

None of this is a lane; `teyla shield check` reports which of these hold on this machine, and
the doc keeps the promise honest until they do.

## 6. Roadmap

Three waves. Wave 1 is the sprint this document launches; it runs on the volume model in
worktrees, one PR per lane, each reviewed by the other provider before merge (`--high` for the
lanes that handle credentials or user data: A, B, C, E, F). No lane starts a build or a simulator;
the tests are `pytest` and an in-process fake server. Lanes that touch `cli.py`, `COMMANDS.md`,
`docs/PRIVACY.md` and the privacy tripwire merge one at a time.

### Wave 1 — the gate exists (this sprint)

| Lane | Ships | Done when |
|---|---|---|
| A `teyla leak` | `src/teyla/leak.py`: surfaces (tree, `--staged`, `--outgoing`, `--commits`, `--text`, local-only `.env`, harness configs, plists, string catalogs, image metadata), classes, masked output, `--json`, gitleaks as second engine, exit 0/1/2; `docs/LEAK.md` | run on any repo under the code root and on a PR body; the existing `leak_check.py` tests pass against the new module; a planted key in an ignored `.env` is reported local-only, in the index as publishable |
| B install + terms | `teyla leak install` (pre-commit on the index, pre-push on outgoing refs, `core.hooksPath`, chaining, `TEYLA_LEAK=0` logged); `teyla leak terms --suggest [--yes]` from machine facts, masked, 0600/0700 | hooks installed in a scratch repo refuse a staged key and an outgoing commit with a private term; a missing scanner exits 2; the suggest output contains no unmasked value |
| C agent hook | `plugin/hooks/leak-guard.sh` + `hooks.json`: publication bodies scanned, credential-path reads refused, Keychain dumps refused, `gh repo edit --visibility public` refused; the coarse path fails open with one warning line, a classified publication or credential read fails closed; `sh` tests like the machine guard's | a `gh pr create --body` with a planted key is refused with the masked excerpt; a read of the private-terms file is refused; a broken scanner lets `ls` through and refuses `gh pr create` with the reason |
| D hosts | `teyla hosts <repo> [--write]` for Swift, TypeScript, Deno, Kotlin, Python and manifests, compared with `docs/PRIVACY.md`; `templates/repo/docs/PRIVACY.md`; `check.sh` template runs security steps before `.env` | an undocumented host is a FIX with file and line; Teyla's own table passes; the scaffold writes rows a person completes |
| E contract | `[security]` in `templates/repo/teyla.toml`; `teyla shield check <repo> [--release]` with tier requirements and dated, expiring evidence; `templates/store/REVIEW-NOTES.md` DATA paragraph | a fresh scaffold prints the tier's FIX list; a stale evidence row is STALE; `--release` exit 1 on a FIX; the release script's doc names it as the step before upload |
| F MCP probe + corpus | `teyla mcp probe <url> [--token] [--write <tool>]` with request and time budgets; `templates/security/injection_cases.json`; `templates/security/tests/` for Deno and vitest; `docs/PRIVACY.md` row; tests against an in-process fake server | the fake server fails three checks and the probe names each with the fix; the corpus loads in both test templates; the probe refuses to run without a budget |
| G deps | `teyla deps [repo|--all]` over the lockfiles → OSV querybatch, cached a day, safe-mode gated, PRIVACY row, the weekly routine's line | a lockfile with a known vulnerable version is a FIX with the fixed version; no lockfile is exit 2; the weekly digest carries the count |

Wave 1 ends with `teyla leak` run on every repo under the code root, the findings written to
`~/.teyla/shield/<date>.md` (local, never in a repo), and the owner-data findings in public repos
fixed in their own PRs where the repo allows it.

### Wave 2 — one product proves the contract

A product with an MCP server, a database with user rows and a store build pilots the whole
contract: `[security]` filled, `teyla shield check --release` green, the MCP test suite in its
repo with the corpus against its real handlers (synthetic accounts: anonymous, A, B on every
table, RPC and tool), the runtime egress wrapper, the privacy manifest and the DATA paragraph in
its review notes. `teyla scout security` starts under caps. The hooks roll out to every repo
(`teyla leak install --all`, one PR per repo). Credential separation (§5.7) is the owner's step
list, checked by `teyla shield check` on the machine. A capped red team against the pilot's
staging (SH14) with a written target list, synthetic data and cleanup.

### Wave 3 — the fleet and the week

`teyla shield` prints one table for every product: tier, hooks, leak, hosts, deps, evidence age,
the last probe. The weekly routine runs leak, `leak --published`, deps, hosts and the harness-config diff and the
digest names the FIX count per product; a product that goes `family`, `testers` or `public` in
`[productize]` gets the tier's requirements the same day. Second-platform parity trains carry
the contract. A second MCP server adopts the suite from the pilot's PR as its template.

## 7. Deliberately not built

- **A separate security product or repo.** SH1. A second home for the same rules drifts.
- **Model-decided gates.** A model that can be talked into a pass is not a gate (SH2). Models
  classify, explain and draft; code decides.
- **History rewriting on a finding.** Rotation first; a rewrite is a deliberate step that the
  owner runs with a clean mirror, never a hook's side effect.
- **A paid secret scanner or secrets manager.** The free engines cover the repos; the Keychain and
  the accounts hub hold the keys. Prices are in §9 for the day a team joins.
- **An unrestricted red-team agent.** Only against staging, with synthetic data, targets, budgets
  and cleanup written down first (SH14). An attack lane that can reach production, payments or a
  third party is a vulnerability with a budget.
- **Runtime egress control in wave 1.** The static inventory ships first because it costs an
  afternoon and already turns an undocumented host into a FIX; the fetch wrapper and the debug
  session check follow in the pilot, where they can be tested against a real product.
- **Screenshot OCR.** Image metadata is scanned; pixels are the owner's eyes and the store review
  checklist (POLICY §15).
- **Private terms in the repo**, in any form: not as a hash list, not as a regex, not as an
  allowlist entry. The list stays in `~/.config/teyla/`.
- **An X-posting or public-disclosure step.** Findings stay local. A public advisory for a product
  the owner ships is the owner's call per case.
- **Telemetry about findings.** `teyla leak` sends nothing anywhere; `teyla deps` sends package
  names and versions to OSV and nothing else, under safe mode.

## 8. Risks

| Risk | Where it bites | What holds it |
|---|---|---|
| The private-terms list leaks through a tool that reads it (a hook's own output, a transcript, a model context) | The most sensitive file becomes the most copied | SH5: masked output everywhere, the agent hook refuses the path, `teyla leak` never prints a term, the file is 0600 outside every synced folder |
| A hook bug lets a real leak through | A publication with a key while the scanner is broken | Publications, credential reads and visibility changes fail closed once classified; only the coarse path fails open; `--outgoing` runs again on push; the weekly `--published` audit reads what landed |
| Allowlist fatigue: a triage finding every commit trains the owner to type the override | The gate becomes noise | Blockers only for high-confidence rules; triage listed, not blocking; one exception names one finding, with an expiry |
| An agent with the owner's login bypasses every local gate through the API | Merge, publish, visibility | SH11, §5.7: credential separation is named as the control that is still missing, and `teyla shield check` reports it |
| gitleaks absent or stale on a machine | Coverage differs by machine | Exit 2 where the contract requires the second engine; the stdlib rules always run |
| A static host inventory misses a computed URL | An undocumented endpoint | Reported as a limit; the pilot's runtime wrapper in wave 2 |
| OSV's data lags a disclosure; a lockfile is missing | A vulnerable version passes | Exit 2 on a missing lockfile; the feeds scout in wave 2 |
| A probe against a third party's server | A request budget spent on someone else's infrastructure, or an abuse report | The probe runs only against a URL in the product's own contract or an explicit `--i-own-this` flag, and makes no write call without `--write <tool>` |
| Seven lanes on a machine that is CRITICAL | Swap, a kernel panic, a lost worktree | SH13: `pytest` only, no build, no simulator, no container; lanes queue behind `teyla load --wait` |
| The doc promises more than the gates deliver | A false sense of safety | §5.7 and this table are in the public doc; the first line of `teyla shield check` prints what is not enforced on this machine |

## 9. Owner decisions

Decided here with a default; the default stands when nothing is said.

1. **Where Shield lives: Teyla.** Default yes (SH1). A separate repo only if a second person
   needs it without Teyla.
2. **Hooks in every repo.** Default: wave 2 installs `pre-commit` and `pre-push` in every repo
   under the code root, one PR each; the agent hook ships in the plugin now.
3. **The pilot product.** Default: the product with an MCP server, user rows and a store build
   whose contract is furthest from green after wave 1's run; proposed in the sprint card.
4. **Credential separation.** Default: the owner creates one fine-grained GitHub token for lanes
   this week (§5.7). Until then the doc says the gates are bypassable through the API.
5. **Paid tools (POLICY §11, stated, not bought).** GitHub Secret Protection for private repos:
   $19 per active committer per month, one committer today, so about $19 per month per
   organisation that enables it; push protection is already free on public repos. A hosted secrets
   manager: Doppler from $8 per user per month, Infisical Pro from $20 per user per month,
   1Password Teams from $3.99 per user per month. An X API tier for a security feed: not needed;
   the scout reads public pages. **Recommendation: buy none now.** The free engines plus the
   Keychain and the hub cover one person; revisit when a second committer joins.
6. **Fixing owner data already in public repos.** Default: wave 1's run lists each finding
   masked, and a fix PR follows per merge-approved repo; history stays, because the data is
   already public and a rewrite buys nothing.
7. **The red team.** Default: wave 2, staging only, synthetic data, a written target list and a
   request budget, after the pilot's suite is green.

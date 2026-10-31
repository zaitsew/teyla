# Privacy: every call that leaves your machine

Teyla reads your session logs, your repos and your config on your Mac. It has no server, no account,
no telemetry and no analytics SDK. It never uploads a transcript. Nothing about your sessions leaves your Mac unless you turn on a feature that says so; today
that is one row (14, the model brief), off by default.

It does make the calls below. Each row names the command that triggers it, the host, what is sent,
and whether it runs without you asking. "Default on" means it runs with a stock install and no flag.

**One switch closes most of them.** `teyla config set safe.enabled=true` (or `TEYLA_SAFE=1`) is safe
mode: every row marked "safe mode: closed" stops, and a command you type by hand can open one call
with `--allow-network`. The gate is `src/teyla/net.py`.

## Teyla's own calls

| # | Trigger | Host | What is sent | Default on | Safe mode |
|---|---|---|---|---|---|
| 1 | The update check: `teyla doctor` (when the cached answer is over a day old), the session-start hook (once a day, in the background, once Teyla is set up), `teyla update --check` | `api.github.com` | A GET for the latest release and commit of `zaitsew/teyla`. It sends only the version, as the User-Agent `teyla/<version>`. The result is cached in `~/.teyla/update-check.json`. `teyla doctor` is not read-only: it also writes `~/.teyla/doctor.json`, `doctor.summary` and `banner.items`, and makes this one call when the cache is stale (`teyla doctor --refresh` always). | Yes | closed |
| 2 | `teyla update` (the daily routine runs it, if you installed the routine) | `github.com`, and `pypi.org` for build tools (not in code: `uv` and `pip` reach it) | `uv tool install` or `pip` fetches the new release. No user data. | Only if the routine is installed | closed |
| 3 | `teyla models --refresh` | `models.dev` | A GET of the public model catalogue. No user data. | No (needs `--refresh`) | closed |
| 4 | `teyla plugin install owner/repo`, and offer O6 of `teyla start` when you say yes and Claude Code has no Teyla plugin (it installs `zaitsew/teyla`) | `github.com` | `git clone` or `git pull` of the repo you named, or of `zaitsew/teyla` for O6. | No (you name the repo, or say yes to O6) | closed |
| 32 | `teyla deps` (also in the Friday weekly routine as `teyla deps --all --quiet`) | `api.osv.dev` | A POST of `/v1/querybatch` with package names, ecosystems and versions read from lockfiles (`{"package": {"name", "ecosystem"}, "version"}`, at most 1000 per request), then a GET of `/v1/vulns/<id>` for each vulnerability id not already cached. The user agent is `teyla-deps/<version>`. Never a path, a repo name, a lockfile name or anything about you. Cached for a day in `~/.teyla/deps/cache.json` (mode 0600). `--dry` prints the counts and sends nothing. | Yes, once a week where the Friday weekly routine is installed; you can also run it by hand | closed |

## Calls through tools you already have

These run `gh`, `git`, `ssh` or an agent CLI as a child process. Teyla adds no credentials: the tool
sends its own, from your own login.

| # | Trigger | Host | What is sent | Default on | Safe mode |
|---|---|---|---|---|---|
| 5 | `teyla state` (the Mac app and the relay call it): the open-PR and assigned-issue lists, refreshed in the background every 30 minutes (`gh api graphql`, `gh search issues`) | `api.github.com` via `gh` | Your `gh` token; repo names of products on this machine; search terms `--assignee @me`. Cached in `~/.teyla/state-backlog.json`. | Yes, when `gh` is installed and signed in | closed |
| 6 | `teyla reviews` (`gh api graphql`; the weekly routine runs it) | `api.github.com` via `gh` | Your `gh` token; the PR numbers it lists. | Yes, when `gh` is installed | closed |
| 7 | `teyla routines` and `teyla schedules`: workflow run status (`gh run list`, `gh repo view`) | `api.github.com` via `gh` | Your `gh` token; the repo and workflow names. | Yes, when `gh` is installed | closed |
| 8 | `teyla routines --issues`: files an issue when a routine is stale (`gh issue create`) | `api.github.com` via `gh` | The issue title and body: a routine's name and its last-run time. | No (needs `--issues`) | closed |
| 9 | `teyla cloud ...`: repo visibility and PR lists (`gh repo view`, `gh pr list`) | `api.github.com` via `gh` | Your `gh` token; the repo slug. | When you run a `teyla cloud` command | closed |
| 10 | `teyla spend`: GitHub Actions minutes (`gh api /user`, `/user/orgs`, `/orgs/<org>`) | `api.github.com` via `gh` | Your `gh` token; your login and org names. | Yes, when `gh` is installed | closed |
| 11 | `teyla dispatch` (`git fetch origin` in the repo you name) | The repo's own remote | Nothing beyond what `git fetch` sends. | When you run `teyla dispatch` | refused |
| 12 | `teyla platform ...`: the server and domain probes (`ssh`, DNS lookup) | The hosts you list in `~/.teyla/platform.toml` | `ssh -o BatchMode=yes <user>@<host> true`; a DNS lookup of each domain. | When you run `teyla platform` (`--no-net` skips them) | closed |
| 13 | `teyla testflight` and `teyla play` (the daily routine runs both) | App Store Connect, Google Play, through the release tool you set in `[apple] release_tool` and `[android] release_tool` | The bundle id or package name and your tester e-mail from `teyla.toml`. Teyla holds no key; your tool does. | Only for products whose `teyla.toml` names a bundle id or package. `teyla portfolio --refresh` (started detached by `teyla state` when its cache is over 6 hours old) runs these same calls and the `gh` calls of row 5 and the review ledger; it adds no new destination and caches the result in `~/.teyla/portfolio-cache.json` (mode 0600) | closed |
| 34 | `teyla shield check <repo> --identity` (see [SHIELD.md](SHIELD.md) section 9.4) | `api.github.com` via `gh` | Read-only GETs of `/user`, `/repos/<owner>/<repo>`, `/repos/<owner>/<repo>/rulesets` (pages of 100, then each active branch ruleset), and `/repos/<owner>/<repo>/branches/<default>/protection`. The repo slug comes from the `upstream` or `origin` remote (or `--github-repo`). Your `gh` token goes to GitHub only, as `gh` sends it; Teyla never reads or prints it. The answer is used for one verdict line and is not stored. | No (needs `--identity`; no routine or hook passes it) | closed |

## Calls that carry content to a model provider

These use your own `claude`, `codex` or `grok` login. The text goes to that provider under your account.

| # | Trigger | Host | What is sent | Default on | Safe mode |
|---|---|---|---|---|---|
| 14 | The model brief, only when you turn it on: `teyla state` and the Mac app start `teyla state --refresh-brief` in the background | Anthropic, through `claude -p` (Haiku) | Up to 15 open questions from your sessions, each field cut to 400 characters. No tools, no settings, no saved session. | **No, opt-in**: `teyla config set state.model_brief=true` turns it on, `=false` turns it off | closed |
| 15 | `teyla intent cover ... --model` | Anthropic, through `claude -p` | The plan file and the unresolved sentences from your own prompts. | No (needs `--model`) | closed |
| 16 | `teyla voice check ... --model` | Anthropic, through `claude -p` | The draft text. | No (needs `--model`) | closed |
| 17 | `teyla harness verify --live` | Each installed provider, through its CLI | One fixed line asking for a policy section title. | No (needs `--live`; no routine or hook runs it) | not gated |
| 18 | `teyla run` (a routine step), `teyla dispatch`, `teyla answer` | Your provider, through `claude`, `codex` or `grok` | The prompt in your `teyla.toml` routine, or the answer or task you typed. | No (you start it) | `run` and `dispatch`: refused. `answer`: not gated |
| 19 | `teyla spend`, provider cost reports | `api.openai.com`, `api.anthropic.com` | Your admin API key from the Keychain, in an `Authorization` header, and a date range. | No: with no key in the Keychain there is no call | closed |
| 20 | `teyla probe-sql <ref> "<query>"` and `teyla products` | `api.supabase.com` | The read-only SQL you wrote, and your Supabase access token. | No: needs `supabase login` or `SUPABASE_ACCESS_TOKEN` and a product with a probe | closed |
| 23 | `teyla review triage <id>` (not `--dry`) | Anthropic, through `claude -p` (Sonnet) | One review capture (the comment, the screen, the tapped element), the product's `DESIGN.md` (first 12,000 characters), the confirmed rules that match the screen, and the last 20 design decisions. No tools, no settings, no saved session. | No (you run it on a capture) | closed |
| 24 | `teyla review pull --testflight <app-id>` | `api.appstoreconnect.apple.com`, and the screenshot URL Apple returns in the answer | A read-only GET of the app's beta screenshot feedback, signed with a 15-minute token made from the key the release tool already uses (`~/.appstoreconnect/`); the key file is read only by `openssl` and never sent. Then one GET of each new screenshot, without the token. The tester's e-mail is dropped. | No (needs `--testflight`) | closed |
| 25 | `teyla ux judge A.png B.png` and `--calibrate` (not `--dry`) | Anthropic, through `claude -p` (Sonnet) | The two screenshots you name (PNG, JPEG or GIF, at most 5 MB each, as image blocks) and the product's `DESIGN.md` (first 12,000 characters) when `--repo` is given. A calibration run sends each decided pair. No tools, no settings, no saved session. | No (you run it) | closed |
| 26 | `teyla scout design` (not `--dry`), also in the Friday weekly routine | The hosts in `templates/design/SOURCES.md` (Apple, MacStories, Daring Fireball, Nielsen Norman Group, Smashing, and similar feeds), over HTTPS, and `developer.apple.com` for the HIG pages; and Anthropic, through `claude -p` (Sonnet), once per drafted proposal | A plain GET of each feed and each listed Apple HIG page: the user agent `teyla-scout/<version>` and nothing about you. The model call, only when an item meets a product problem, gets the item's title, source and one line, the problem text (from a decision, a review capture or a `ux check` FIX) and the titles of the standard's rules. `--no-model` makes no model call. | Yes, once a week, where the Friday weekly routine is installed (`--quiet`); you can also run it by hand | closed |
| 27 | `teyla kit image` and `teyla kit compare` | `generativelanguage.googleapis.com` (Gemini API, Nano Banana 2.1) or `api.openai.com` (gpt-image-2), whichever the kit's `mascot.model` or `--model` names | The scene text, the mascot's character sheet, and up to six reference images from `brand/mascot/`, with your own API key (`GEMINI_API_KEY` or `OPENAI_API_KEY`, or the Keychain), read at call time and never stored. The price is printed first and the command refuses without `--yes`. | No (needs `--yes`) | closed |
| 28 | `teyla reel product --voice` | `api.openai.com` (speech) | The voice-over text (the captions of the copy table, or the script you give) and your own `OPENAI_API_KEY` or Keychain `openai-api-key`. The price is printed first and the command refuses without `--yes`. | No (needs `--voice` and `--yes`) | closed |
| 29 | `teyla copy write <brief>` (not `--dry`) | Anthropic, through `claude -p` (Sonnet) | One call per language: the screen's job, primary action and states, the glossary terms and the voice chart of that language, the rules, and the screen's current strings in that language. No other language's text. No tools, no settings, no saved session. | No (you run it on a brief) | closed |
| 30 | `teyla copy judge <copy.json> --model` | OpenAI, through `codex-lane` (`codex exec`, read-only, GPT-6.1 Sol) | One call: the table's rows that passed the code checks (key, control, state, budget, the en/es/ru strings), the voice charts, the glossary and the rules. | No (needs `--model`) | closed |
| 31 | `teyla copy apply <copy.json> <repo> --pr` | The product repo's own remote, and `api.github.com` via `gh` | `git push` of a new branch that holds the changed string catalogs; a PR title and a body listing the changed keys. Your `gh` token. | No (needs `--pr`) | closed |

## Calls to a server you name

| # | Trigger | Host | What is sent | Default on | Safe mode |
|---|---|---|---|---|---|
| 33 | `teyla mcp probe <url>` (see [MCP-SECURITY.md](MCP-SECURITY.md)) | The one host in the URL you give, only if the current repo's `teyla.toml` or `docs/PRIVACY.md` names it, or you pass `--i-own-this` | JSON-RPC 2.0 POSTs: `initialize`, `tools/list` and `tools/call`, with the texts of `templates/security/injection_cases.json` (attacker URLs, canary strings, one 1 MB string) as arguments, and your `--token` in an `Authorization` header over https or to a loopback host. At most `--budget` requests (default 60) in `--seconds` (default 120). No redirect is followed. It calls no write-like tool unless `--write TOOL` names it. | No (you run it) | closed |

## Sync you switch on

| # | Trigger | Where | What is sent | Default on |
|---|---|---|---|---|
| 21 | `teyla relay on` | A folder in iCloud Drive (`~/Library/Mobile Documents/com~apple~CloudDocs/Teyla`) | The text of your open questions and your session titles, signed. Apple holds the keys unless you turn on Advanced Data Protection. See [RELAY.md](RELAY.md). | No |

## A server on your own Mac

| # | Trigger | Where | What is sent | Default on |
|---|---|---|---|---|
| 22 | `teyla web` | `127.0.0.1` only, a random port, until you stop it or 2 hours pass with no request | Nothing leaves the Mac. Your browser on this Mac reads the dashboard; every request needs a per-run token. See [WEB.md](WEB.md). | No |

## The MCP server

`teyla mcp` (with no subcommand) talks to an MCP client over stdio. It opens no socket and makes no network call itself. Its tools
run commands listed above: `teyla_routines` is row 7, and `teyla_answer` is row 18, so it starts a local `claude` or
`codex` process exactly as `teyla answer` does. `teyla_asks`, `teyla_intent`, `teyla_load` and `teyla_monitor` read
local files only. No tool reaches `--issues`, `--model`, `--share`, `--allow-network` or any other call that
needs a flag. The text it returns goes to the MCP client you connected, under that client's own policy. `teyla mcp probe` is a different command: it is a client, and it is row 32.

## Not a call

`teyla cloud prep` writes a setup script for a cloud sandbox that contains a `curl` line for the `uv`
installer. Teyla does not run it. `teyla start`, `teyla monitor`, `teyla advise` and `teyla doctor`'s
checks other than row 1 read local files only.

## URLs in the code that are not calls

`teyla hosts` reads Teyla's own source and lists every host literal. These appear in it and are never
fetched by Teyla.

| Where | Host | What it is |
|---|---|---|
| `teyla platform` (`src/teyla/platform.py`) | `dash.cloudflare.com`, `supabase.com`, `resend.com`, `app.mailgun.com`, `account.postmarkapp.com`, `appstoreconnect.apple.com`, `play.google.com`, `platform.openai.com` | Setup links printed in a hint. Teyla opens none of them. |
| `teyla cloud` (`src/teyla/cloud.py`) | `claude.ai` | A string matched against local `git log` output (the session trailer). No request. |
| `teyla cloud prep` (`src/teyla/cloud_prep.py`) | `astral.sh` | The `curl` line in the setup script it writes. Teyla does not run it. |

## Keeping this list true

`tests/test_privacy_calls.py` fails when a module under `src/teyla` starts using a network API or a
network tool and is not in its allowlist. When you add a call: add the module to that list, add a row
here, and say whether it runs without a flag.

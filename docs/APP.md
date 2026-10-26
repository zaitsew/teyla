# Teyla for Mac — the coordinator window

Teyla for Mac is one window and a menu-bar icon. Every morning it says in one sentence what
matters today. Below that come the questions only you can answer, ordered by what each one
unblocks, and then where each product stands. You answer in the window, and the answer goes
into the session that asked.

Status: version 1 shipped on 2026-10-16 (Mac). Version 2 (results, tasks, new tasks, voice, iPhone) is
in development from 2026-10-17; its contract is below. The design is variant B, "morning brief".

## How it works

The app holds no data of its own. It runs two commands of the Teyla CLI:

| Command | Does |
|---|---|
| `teyla state --json` | One snapshot: the brief, questions, products, running sessions, today's spend. |
| `teyla answer <id> <text> [--json]` | Delivers an answer to the session behind a question, then marks it done. |
| `teyla start --json` | The first-run diagnosis and its offers (read-only). |
| `teyla apply <offer id> --yes` | Makes one offered change, after a backup. |
| `teyla product show <id> --json [--quick]` | One product's page. |
| `teyla product set <id> stage=<s>` · `focus=true\|false` | Changes a product's stage or focus. |

The app re-runs `teyla state --json` within 2 s of a change under the session stores
(`~/Library/Application Support/Claude/claude-code-sessions`, `~/.claude/projects`,
`~/.codex/sessions`), and every 60 s otherwise.

## The window: first run, sidebar, product pages

The window has three states.

1. **`teyla` not found.** The command is looked for in this order: the file picked with "Choose…" (stored in
   UserDefaults), `$TEYLA_BIN`, the `PATH` of a login shell (`/bin/zsh -lc 'command -v teyla'`, asked once and
   remembered until "Check again"), then `~/.local/bin`, `/opt/homebrew/bin` and `/usr/local/bin`. When none runs,
   the window shows `uv tool install --python 3.12 git+https://github.com/zaitsew/teyla` with Copy, "Check again" and "Choose…".
2. **Welcome.** `teyla` runs, and the snapshot has no question, product, session, task or result: the window shows the
   lockup, the promise sentence and "Run diagnosis". The button runs `teyla start --json` and the window shows a
   seconds counter, since it reads 30 days of sessions. When the report arrives the sidebar appears and the
   Diagnosis page shows it. If `teyla start` fails, the window shows the error and "Try again".
3. **The shell.** A sidebar (Today, Diagnosis, Products) and the page it points at. Products lists the registered
   products (and `unassigned` when it has anything), with the focus star and the waiting count.

**Diagnosis page.** The total at API list price and the facts under it (`diagnosis` in `teyla start --json`),
then one card per applicable offer: title, saving or benefit, trade-off, undo, and "Apply…". Offers that do not
apply sit under "Left out" with the reason. "Apply…" opens one sheet that names the file and the key
(`change.file`, `change.key_path`) or the command, and says a backup is made first; an offer whose undo
text names `teyla uninstall` (O5 to O7) says that `teyla undo` does not reverse it. Confirm runs `teyla apply <id>
--yes` and shows the lines it printed under "Changed:". Offer ids are checked (`O` and digits) before they reach
the command line. The diagnosis is not kept between launches.

**Product page.** From `teyla product show <id> --json` (`docs/PRODUCTS.md`). The app asks for `--quick` first
(header, questions, notes) and then for the full page (sessions, spend), because the second reads 30 days of
sessions. The stage menu runs `teyla product set <id> stage=<stage>`, the star `focus=true|false`. Questions that
the window also has are shown as the usual cards, so they can be answered there; notes use the Notes section's row
(Link…, Drop). A registered product has a page; a repo that only shows activity does not.

Sample data for previews: `TEYLA_STATE_FIXTURE` also reads `start.v1.json` and `product.v1.json` beside it
(`TEYLA_START_FIXTURE`, `TEYLA_PRODUCT_FIXTURE` name other files); applying and setting are simulated.

## Delivering an answer

`teyla answer` tries these in order and reports which one worked:

1. **Codex:** `codex exec resume <session> <text>`, run in the session's own directory (the `cwd` in its
   `session_meta`) and left running in the background (`via: codex-resume`). If it fails to start,
   `codex queue --thread <session> --message <text>` (`via: codex-queue`): it exits 0, but the message
   waits until the session is opened in the Codex app, and `detail` says so.
2. **Claude Code and the Claude desktop app:** `claude --bg --resume <cliSessionId> <text>`,
   run in the session's own directory with its permission mode. The session continues in the
   background under the same id. `claude agents` lists it.
3. **Fallback:** the answer goes to the clipboard and the session opens in its app.

Verified on 2026-10-16: `claude -p --resume <id>` continues a session under the same id and
the same transcript file. `codex exec resume <uuid> <text>` continues a Codex session under the same id
headlessly; `codex queue` exits 0 but runs nothing until the session is opened in the app. Not verified yet: whether the desktop app shows a background
continuation of an archived session without reopening it, and `codex exec resume` on an archived thread.

## The snapshot (version 1)

`tests/fixtures/state.json` is the reference. Fields:

- `version`: 1. `generated`: ISO time.
- `brief`: `{line, source}`. `line` is one sentence of at most 25 words. `source` is `rules`
  or `model`. Can be null.
- `totals`: `{questions, running, spent_today_usd}`. `spent_today_usd` can be null.
- `asks[]`: the open questions, best first. Each has the `teyla asks --json` fields plus:
  - `unblocks`: short text such as "the iPhone release", or "".
  - `rank`: 1 = first.
  - `delivery`: `codex`, `claude`, or `open` — what `teyla answer` will try first.
  - `muted`: true for an ask in a parked product that is not critical. It is ranked last and is not in the
    brief or in `totals.questions`. The app hides it by default.
- `products[]`: `{name, waiting, muted, state, line, last_activity}`. `waiting` counts the asks that are not
  muted; `muted` counts the asks hidden by parking.
  - `state` is `waiting`, `active`, `shipped` or `quiet`.
  - `line` is one line of status, for example "iPhone 1.1.5 (126) in TestFlight".
- `running[]`: sessions active in the last 10 minutes: `{product, title, harness, model, since, link}`.

`teyla answer --json` prints `{ok, via, detail, id}`; `--dry` adds `"dry": true` and runs nothing.
`via` is `codex-resume`, `codex-queue`, `claude-bg` or `opened`.

Notes on the CLI as built:

- `teyla state` reads today's spend from `~/.teyla/state-spend.json` and refreshes it in a detached
  process when it is older than 10 minutes, so `spent_today_usd` is null until the first refresh lands.
- `brief.source` is `model` when a model-written brief is cached for exactly the current set of open
  questions (`~/.teyla/state-brief.json`, written by a detached `teyla state --refresh-brief` that sends the
  newest 15 questions, blocked first, to Claude Haiku in one `claude -p` call with no tools). The brief and
  the order and `unblocks` of the questions then come from the model; questions it did not rank keep their
  rule values and follow. Otherwise `source` is `rules` and a refresh starts, so a new question shows rule
  values for a few seconds. A failed or invalid reply keeps the previous cache; a failed attempt is not
  repeated for 5 minutes. Opt-in: it runs only with `[state] model_brief = true` (`teyla config set state.model_brief=true`), never in safe mode, and not without `claude` on PATH.
- `running[]` lists interactive sessions only: Codex rollouts started by `codex exec` (`originator`
  `codex_exec`, `source` `exec`) and Claude desktop sessions titled "You are reviewing..." are review and
  lane runs, not sessions you work in.
- `running[].since` is when the session was created, not when it last moved.
- `teyla asks --json` is unchanged; the session id `teyla answer` needs is kept off its JSON.

## Version 2 (from 2026-10-17)

Version 2 adds what got done, the tasks only the owner can do, new tasks, corrections to a
running session, voice, and the iPhone. Every field is additive: a version 1 client ignores the
new ones, and a version 2 client treats a missing field as empty.
`tests/fixtures/state.v2.json` is the reference.

### New snapshot fields

- `version`: 2.
- `totals`: adds `tasks` and `done` (counts of the lists below).
- `totals`: also `resolved` (asks closed because their PR is merged or closed) and `duplicates` (asks collapsed
  into a newer one). Both are already left out of `asks[]` and `questions`; an `asks[]` item may carry `dupes: [ids]`.
- `tasks[]`: things only the owner can do that are not questions, oldest first:
  `{id, kind, product, title, detail, link, age_s}`.
  - `kind: merge`: an open PR in a repo that is not merge-approved (the list in
    `~/.claude/CLAUDE.md`), with a review and no open P1. `id` is `pr:<owner/repo>#<n>`.
  - `kind: task`: an open GitHub issue assigned to the owner. `id` is `issue:<owner/repo>#<n>`.
- `done[]`: sessions that ended a turn in the last 24 hours, newest first:
  `{id, product, title, status, result[], needs, links[], ended, harness, link}`.
  - `status`: `done`, `needs_you`, `blocked`, `failed` or `review_ready`.
  - `result`: at most 3 short lines. `needs`: one line, or "".
  - Source: the Claude desktop turn summary (`postTurnSummary`), else the last assistant message's
    session-end card, else its first line. Headless lane and review runs are left out.
- `products[]` also carries the product registry (`~/.teyla/products.toml`, `docs/PRODUCTS.md`): `id` (the registry id;
  equal to `name`), `display_name`, `stage` (`idea`, `building`, `beta`, `live`, `parked`, or ""), `focus` (bool),
  `primary` (`ios`, `web`, ... or "") and `registered` (false when the product is only a repo with activity).
  Every registered product is listed, parked ones too, with stage `parked`. `unassigned` is a product like the others
  (`registered` false) and comes last; it is listed only when something waits under it. `asks[].product`,
  `running[].product` and `done[].product` are registry ids, or `unassigned`: the old `(no repo)`, `(home)`,
  `(scratch)` and `unknown` are gone.
- `products[]`: adds `issues` (open GitHub issues), `prs_waiting` (open PRs that wait on the
  owner's merge), `next` (one line, the next step, or "") and `repo` (its path, or "").
  Products that are one repo under two names are merged into one row.
- `running[]`: adds `id` (what `teyla say` takes) and `correct`: `codex-queue` when a correction
  can be queued into the live session, `open` when the window can only open it.
- `relay`: `{on, paired, folder, synced}` — whether the iPhone relay is on, whether a phone is
  paired, the folder, and when the Mac last wrote the snapshot there.
- `notes`: `{inbox, by_product}` — how many open text notes (`teyla note`, `docs/NOTES.md`) wait with no
  product yet, and how many per registered product. Dropped notes are not counted; without a notes file it
  is `{inbox: 0, by_product: {}}`. An additive field, so the version stays 2.

Notes on the CLI as built (version 2):

- `done[]` lists a Claude desktop session from its turn summary. `completed` is `done`; `review_ready` and
  `blocked` keep their name; `failed` and `error` are `failed`; any `needs_action` makes it `needs_you`. `result` is the summary detail split at line breaks and `;`, at most 3 lines. Without a summary, the card
  in the last assistant message of the transcript is used, else its first line cut to 120 characters. A Codex
  rollout counts when its last event is a finished turn. A session whose turn is still open, an archived one,
  and one listed in `running[]` are left out. At most 40 rows.
- `links` holds up to 3 GitHub PR or issue URLs from that text, plus the PRs the desktop app recorded.
- `tasks[]` and the issue counts come from GitHub through a cache, `~/.teyla/state-backlog.json` (0600). The
  snapshot never calls `gh`: a detached `teyla state --refresh-backlog` rewrites the cache when it is older than
  30 minutes. One refresh makes three calls: a PR search (`is:pr is:open author:@me`, with each head commit),
  `gh search issues --assignee @me`, and one query for the open issue count of every repo that moved in the
  last 30 days. In safe mode, or without `gh`, the lists are empty and nothing starts.
- A `merge` task is listed for every open, non-draft PR of the owner in a repo that is not merge-approved.
  `detail` says whether the head commit is in the review ledger (`review.ledger`), whether the last review of
  it has an open P1, or whether the review was skipped. The merge-approved list is the fenced block after
  "MERGE-APPROVED REPOS" in `~/.claude/CLAUDE.md`; `[state] merge_approved = ["owner/repo", ...]` replaces it.
- A product is named after its GitHub repo. Two clones of one repo, or a clone whose remote was renamed, share
  one row; the asks, tasks, results and sessions of both carry that name. Two repos with different GitHub names
  stay two rows. `next` is the `needs` of the product's newest `done[]` row.
- `running[]` also finds a Codex session resumed after days, because it goes by file time and not by the date
  folder. `correct` is `codex-queue` for an interactive Codex session and `open` for everything else.
- Runs listed in `~/.teyla/dispatch.jsonl` count as sessions you work in: a Codex `exec` run, a Claude run
  found by the transcript folder of its worktree, and a desktop session titled "You are reviewing..." whose
  directory is inside a dispatched worktree appear in `running[]` and `done[]`.
- `relay` is read from `~/.teyla/relay.json` and `~/.teyla/relay.key`; without them it is `{on: false,
  paired: false, folder: "", synced: ""}`.
- `teyla state` (text) adds a short "Tasks" and a short "Done" section within its 15 lines.

### New commands

| Command | Does |
|---|---|
| `teyla say <running-id> [--json] -- <text>` | Sends a correction to a running session. Codex: `codex queue`, which delivers it after the current turn. Claude: copies the text and opens the session. Never resumes a live session. |
| `teyla dispatch <product> [--harness codex\|claude] [--json] [--dry] -- <text>` | Starts a new session in a fresh worktree under `~/.worktrees/<repo>/`. Codex by default, through `codex-lane` and the machine guard. |
| `teyla relay on\|off\|status [--json]` | Turns the iPhone relay on or off. |
| `teyla relay pair [--json] [--rotate]` | Prints the pairing string the window shows as a QR code, creating the shared key the first time. `--rotate` replaces the key; every phone pairs again. |
| `teyla note --suggest "<text>" --json [--cwd DIR]` | The product a note would get, how (`text`, `cwd` or `""`), and the picker's `candidates` (registered ids, focus first, parked last). Writes nothing. `-` reads the text from stdin. |
| `teyla note - --product <id> --json` | Keeps the note read from stdin and prints it as JSON (the `teyla notes --json` keys, plus `intent`). `link <id> <product>` and `drop <id>` take `--json` too. |
| `teyla notes --json` | The open notes, newest first, as a list of `{id, text, product, source, created, updated, linked_by, dropped}`. |
| `teyla relay sync` | One pass: writes the snapshot, then delivers every signed outbox entry. A launchd agent runs it when the outbox changes and every 60 s. |

`say` and `dispatch` print `{ok, via, detail, id}` like `teyla answer`; `dispatch` adds
`worktree` and `link`. `via` for `say` is `codex-queue` or `opened`; for `dispatch` it is
`codex-exec` or `claude-bg`.

### The relay (Mac ↔ iPhone)

The relay folder is `~/Library/Mobile Documents/com~apple~CloudDocs/Teyla/` (iCloud Drive/Teyla).
The phone picks it once with the document picker and keeps a bookmark. Anyone who can write to
that folder is untrusted: both directions are signed with a key the two devices share.

- `state.teyla`: written by the Mac. Line 1 is the signature (64 hex characters), then `\n`,
  then the snapshot JSON bytes exactly as signed. The phone verifies the signature over those
  bytes before it decodes or shows anything; a bad signature shows "Waiting for the Mac" and
  nothing else. One file, so iCloud never delivers a snapshot without its signature.
- `outbox/<uuid>.json`: written by the phone, one per action:
  `{v: 1, id: <uuid>, kind: answer|say|dispatch, target: <ask id | running id | product>,
  about: <hex sha256 of the text the owner saw>, text, created: <ISO time>, device, sig}`.
  For `answer`, `about` hashes the question; for `say`, the session title; for `dispatch`, the
  product name. The Mac refuses an entry whose `about` does not match what it has now, so a
  question changed after the owner read it is never answered.
- `sent/<uuid>.json`: written by the Mac: `{id, ok, via, detail, done_at}`. The outbox entry
  is removed. The phone shows the result and deletes `sent/` entries it has shown.

Signing. The key is 32 random bytes: `~/.teyla/relay.key` (0600) on the Mac, the Keychain on the
phone. The pairing string is `teyla-pair:v1:<base64url key, no padding>`. Each signature is the
lowercase hex HMAC-SHA256 of a message:

- snapshot: `teyla-state-v1\n` followed by the JSON bytes;
- outbox entry: the lines `teyla-outbox-v1`, `v`, `id`, `kind`, `target`, `about`, `created`,
  `device`, then `text`, joined with `\n`, UTF-8. `text` is last, so a newline inside it is safe.
  No other field is signed and no JSON canonical form is needed. Every field but `text` must
  match a strict pattern with no line break, so the split is unambiguous: `v` digits, `id` a UUID,
  `kind` one of the three, `target` `[A-Za-z0-9_.:#/-]{1,200}`, `about` 64 hex, `created` an ISO
  time, `device` `[A-Za-z0-9 ._-]{1,64}`. Both sides reject an entry that does not, before
  checking its signature.

`tests/fixtures/relay-vector.json` holds a key, a snapshot, an entry and both expected
signatures; the Mac and the phone each reproduce them in a test.

Checks and delivery, at most once:

1. Refuse an entry with a bad or missing signature, an `id` already in the journal, `created`
   older than 7 days or more than 10 minutes ahead, `text` over 8,000 characters, an unknown
   `kind`, a `target` that does not exist, or an `about` that does not match.
2. Claim it: create `~/.teyla/relay-journal/<id>.json` with `O_EXCL` (state `claimed`), then
   deliver, then rewrite the journal entry as `done` with the result and write `sent/`.
3. After a crash, a `claimed` entry is never retried: `sent/` gets `ok: false`, "interrupted;
   check the session, then send again".
4. A relay answer never falls back to the clipboard: when only "copy and open" is possible,
   `sent/` gets `ok: false`, "needs the Mac", and the question stays open.
5. Rejected entries go to `sent/` with `ok: false` and the reason.

Dispatched work. `teyla dispatch` appends `{id, product, harness, worktree, branch, started,
pid, log}` to `~/.teyla/dispatch.jsonl`. `running[]` and `done[]` include headless runs whose
working directory is a worktree in that file, although they leave out every other headless run.

### Voice

Speech is recognised on the device (Apple Speech, on-device only) in English, Spanish and
Russian; no audio leaves it. Push-to-talk fills the text field; nothing is sent until the owner
taps Send. The Mac window has a global shortcut for push-to-talk.

### Notes (quick note and the Notes section)

The Mac keeps no notes; `teyla note` and `teyla notes` do ([NOTES.md](NOTES.md)).

- **Quick note.** A global shortcut opens a small floating panel without bringing Teyla forward. The
  shortcut is optional and recorded in Settings; it is ⌥Space until the owner records another or clears
  it. Return saves, Shift-Return adds a line, Esc closes and keeps the draft. While the owner types, the
  app asks `teyla note --suggest` (300 ms after the last key) and pre-selects the product; the chip row
  changes it with a click or ⌘0 (Inbox) and ⌘1–⌘9 (the first nine candidates). Save runs
  `teyla note - --product <id> --json` with the text on stdin. A failed save keeps the panel open with
  the error and the text.
- **Shortcut rules.** A recorded combination needs ⌘, ⌥ or ⌃, and cannot be push-to-talk (⌥⌘Space). If
  registration fails (another app owns it), Settings says so and the shortcut stays off; the menu-bar item
  still opens the panel. Labels in the menu bar and the Notes section show the shortcut that is active, or none.
- **Notes section.** Under "Needs you": the Inbox count and the newest five open notes with their product
  chip, age and two lines of text. Link… runs `teyla note link`, Drop runs `teyla note drop`; the list is
  read again after each action. The data is `teyla notes --json`, not the snapshot.

## Version 3: the portfolio (from 2026-10-26)

Version 3 adds one object, `portfolio`: where every registered product stands, per platform, and
whether it is on track. The window draws the Portfolio screen and the platform row on each product
page from it; the phone gets it through the relay with no new file. Every other field is as in
version 2. `apps/mac/TeylaTests/Fixtures/state.sample.v3.json` is the reference.

- `portfolio.version`: 1.
- `portfolio.checked`: `{stores, github}` — when the network pass last read App Store Connect and
  Google Play (`stores`) and GitHub (`github`); "" when never. The snapshot never calls the network:
  `teyla portfolio --refresh` runs that pass and writes `~/.teyla/portfolio-cache.json` (0600), and
  `teyla state` starts it detached when the cache is older than 6 hours.
- `portfolio.counts`: `{on_track, at_risk, off_track, parked}`.
- `portfolio.products[]`, worst health first, then focus, then last activity:
  - `id`, `title`, `stage`, `focus`, `primary`, `repo`: as in `products[]`.
  - `users`, `target`: `[productize]` in the repo's `teyla.toml` (`owner`, `family`, `testers`,
    `public`, or "").
  - `health`: `on_track`, `at_risk`, `off_track` or `parked`. `reasons[]`: at most 3 short lines
    that explain it, worst first; empty when on track.
  - `platforms[]`, primary first: `{platform, role, channel, version, build, state, detail, as_of, link}`.
    `platform`: `ios`, `macos`, `android`, `web`, `watch`. `role`: `primary` or `secondary`.
    `channel`: `testflight`, `app_store`, `play`, `web` or `local`. `state`: `live` (a public store
    version, or a site URL the repo's `teyla.toml` declares; Teyla does not fetch it), `in_review`, `current` (the newest build reached the owner),
    `behind` (a newer build exists that the owner cannot install yet), `blocked` (only the owner can
    clear it; `detail` says how), `none` (no build yet) or `unknown` (not checked, or the check failed).
    `detail` is one line for a person. `as_of` is when that row was read.
  - `prs`: `{open, waiting, merged_7d, unreviewed_7d}` — open PRs, PRs that wait on the owner's
    merge, PRs merged in 7 days, and merged in 7 days with no review in the ledger.
  - `activity`: `{last, sessions_7d, spend_7d_usd}`.
  - `waiting`, `oldest_wait_days`, `tasks`: open questions, the age of the oldest, owner tasks.
  - `milestone`: the next `[productize]` target and what is left ("family: 2 of 9 requirements
    left"), or "". `next`: one line, the next step, or "".

Health rules, applied in order; the first that matches wins and every match adds a reason:

1. `parked` when the stage is `parked`.
2. `off_track` when the primary platform is `blocked`, or `behind` for more than 2 days; when a
   question waits more than 7 days; or when a PR merged in 7 days has an open P1.
3. `at_risk` when any platform is `blocked` or `behind`; when a question waits more than 3 days;
   when a PR merged in 7 days was never reviewed; or when a `building` or `beta` product had no
   session for 14 days.
4. `on_track` otherwise.

### New command

| Command | Does |
|---|---|
| `teyla portfolio [--json] [--refresh] [--product ID]` | The portfolio object; text is one line per product. `--refresh` runs the network pass first (TestFlight, Play, GitHub), within safe mode's rules. |

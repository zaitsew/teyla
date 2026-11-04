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
| `teyla attention --json` | What is wrong on this Mac's backend now (the Operations page). |
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
   diagnosis page shows it. If `teyla start` fails, the window shows the error and "Try again".
3. **The shell.** A sidebar and the page it points at: Home, Decisions (with the count of decisions waiting on
   you) and Products, then Growth, Money, Operations (with the count of failures that need you) and Playbook below a
   gap, and Settings at the foot (the diagnosis opens from Operations, which stays selected while it shows). The sidebar lists no single product. A product page opens from a card, a row, or the product name on a
   question. ⌘K opens the command bar from any page.

**Home.** A page that scrolls. Top to bottom:

1. **The pulse strip and the Next line.** Five tiles: Decisions (opens the page), Running, Posts today
   (`console.growth`), Cash per month (`console.money`, with the week at API list prices as its small line) and Disk free
   (`console.operations.machine`, with the verdict and the failures). A figure with no source shows a dash and the reason,
   never a zero. Under them, one line of at most 10 words names the top decision and opens it: `brief.line` when
   `brief.source` is `model` and it fits, otherwise a rule line, the product and the question's first words. A slot for
   the day's quote draws nothing while it is empty. `teyla.home.header` set to `sentence` shows one line of at most 12
   words and a caption instead.
2. A **Week / Month / Year** switch, 44 pt high, for the whole page. It changes the numbers and nothing else: it never
   moves a product or reorders a section. The choice is remembered (`teyla.home.period` in the app's defaults).
3. **People use these.** One hero card per product in `portfolio.home` section `users`: icon (`icon_jpeg`, else the
   first letter of the name on an indigo tint), name, stage, `summary`, three big numbers (active users, new users,
   users in total) for the chosen period, commits for the period with a 12-week bar chart, agent spend for the period,
   and a Monetization chip. The chip reads "Off" while `metrics.money.enabled` is false; when it is true it shows MRR and
   paying users. The bars always show 12 weeks, whatever the period.
4. **Decisions.** The top five that are fresh, with "See all N". The board does not put them here; this position is a
   decision of the owner's.
5. **Being built.** A medium card per product in section `building`: icon or letter, name, two lines of `summary`,
   commits for the period, a small bar chart.
6. **Quiet.** A plain list for section `quiet`: small icon or letter, name, one line of `summary`, and "N commits this
   week" (always the 7-day count).
7. A row "Teyla closed N questions" when Teyla closed some, and "Running now (N)", folded.

The app takes the sections and their order from `portfolio.home` and never ranks: an id without a product row is
skipped, an id listed twice stays in the first section, and a section with no products is hidden. A number that is
`null` shows "—", never 0, and empty `weeks` draws no chart at all. Icons are decoded from base64 once per product and
cached, not on every redraw. Nothing on Home shows a percentage or a health word; health stays on All products. A card
and a row are each one button that opens the product page.

An older `teyla` command sends no `portfolio.home`. Home then shows the core products (`portfolio.core`) as one plain
list titled "Products", with the line "Update the teyla command to rank them by users and activity."

The star pins a product to the front of its section: `teyla product core <ids...>` makes exactly those products
starred (`--clear` empties the list), the CLI ranks starred products first within each section, and the window reads
state again. The star is on the product page and on All products, not on Home. Six can be pinned. The store build has no
CLI, so it shows the stars and cannot change them.

**Decisions.** Every question that waits on you, grouped Pay, Decide, Do when the CLI triaged them (one list,
ranked by what each unblocks, when it did not); questions older than 7 days fold into "Older · N". Below: "Teyla
suggests closing N" (opens to the list) with "Accept these N" and an Undo afterwards, one line "Agents can settle
N" (opens to cards; nothing runs until you click "Use default"), "Only you" (`tasks[]`), the notes, and "Done since yesterday", folded.

**All products.** One row per registered product: health, reasons, platforms and PRs, spend. The star is the same
star as on the product page.

### Triage and what Teyla closed (optional snapshot fields)

The window reads two fields when the CLI gives them and works the same without them.

- `asks[].triage`: `{bucket, action, default, why, source}`. `bucket`: `owner` (waits on you), `agent` (a
  session can settle it with `default` once you click; nothing dispatches it by itself) or `close` (Teyla suggests closing it; it stays open until you accept with
  `teyla asks accept-close`). An unknown or missing bucket reads as `owner`,
  so a value this app cannot read never hides a question. `action`: `pay`, `decide` or `do`; it picks the group
  on the Decisions page. `default` is the proposed answer and `why` the reason, both shown on the card. "Use
  default" sends `default` as the answer. It is never offered for `pay`: a payment waits for your own answer.
  Only `owner` questions count in the sidebar badge, the brief caption, the notifications and the menu bar.
- `auto_closed`: `{count, items: [{id, title, product, reason}]}`: questions Teyla closed. Home shows
  "Teyla closed N questions" only when `count` is above zero; "Review" lists them with the reason, and Undo runs
  `teyla asks undo <id>`.

**Diagnosis page** (opened from Tools). The total at API list price and the facts under it (`diagnosis` in `teyla start --json`),
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
| `teyla relay connect [--json]` | The whole setup: turns the relay on, creates the key if there is none, writes the first snapshot, then opens Teyla for Mac with the pairing URL (`teyla-pair:v1:<key>`). Prints the pairing string only when it cannot open the app. |
| `teyla relay on\|off\|status [--json]` | Turns the iPhone relay on or off. |
| `teyla relay pair [--json] [--rotate]` | Prints the pairing string that Teyla on the Mac shows as a QR code (Connect iPhone), creating the shared key the first time. `--rotate` replaces the key; every phone pairs again. |
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
  `{v: 1, id: <uuid>, kind: answer|say|dispatch|close|reopen, target: <ask id | running id | product | closed ask id>,
  about: <hex sha256 of the text the owner saw>, text, created: <ISO time>, device, sig}`.
  For `answer`, `about` hashes the question; for `say`, the session title; for `dispatch`, the
  product name. The Mac refuses an entry whose `about` does not match what it has now, so a
  question changed after the owner read it is never answered.
  `close` and `reopen` (added with the iPhone Decisions screen) carry the fixed text `close` or `reopen`
  and run one command each, with the target as its only argument: `close` runs `teyla asks accept-close <id>`
  for a question whose triage bucket is `close` (`about` hashes its question, as for an answer), and `reopen`
  runs `teyla asks undo <id>` (`about` hashes the id, because a closed question is no longer in the
  snapshot; `asks undo` refuses one that is not closed). A Mac whose Teyla predates them answers `malformed entry`
  and does nothing. No other command is built from an entry.
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
  `kind` one of the five, `target` `[A-Za-z0-9_.:#/-]{1,200}`, `about` 64 hex, `created` an ISO
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
- **Notes section.** On the Decisions page, below the questions: the Inbox count and the newest five open notes with their product
  chip, age and two lines of text. Link… runs `teyla note link`, Drop runs `teyla note drop`; the list is
  read again after each action. The data is `teyla notes --json`, not the snapshot.

## Version 3: the portfolio (from 2026-10-26)

Version 3 adds one object, `portfolio`: where every registered product stands, per platform, and
whether it is on track. The window draws the All products screen and the platform row on each product
page from it; the phone gets it through the relay with no new file. Every other field is as in
version 2. `apps/mac/TeylaTests/Fixtures/state.sample.v3.json` is the reference.

- `portfolio.version`: 1.
- `portfolio.checked`: `{stores, github}` — when the network pass last read App Store Connect and
  Google Play (`stores`) and GitHub (`github`); "" when never. The snapshot never calls the network:
  `teyla portfolio --refresh` runs that pass and writes `~/.teyla/portfolio-cache.json` (0600), and
  `teyla state` starts it detached when the cache is older than 6 hours.
- `portfolio.counts`: `{on_track, at_risk, off_track, parked}`.
- `portfolio.core`: up to 6 product ids, the products the home screen leads with. `portfolio.core_source`:
  `star` when any product has `focus` (the core is exactly the starred ones, by spend over 7 days), else `rule`
  (not parked, and a weekly user or $40 of spend in 7 days; ranked by spend). `teyla product core` shows and
  sets it (`docs/PRODUCTS.md`).
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
    `detail` is one line for a person. `as_of` is when that row was read. `review_unknown`: true when the
    store API cannot say whether review passed (a Google Play draft may sit in review), else false.
    The newest track decides on Google Play: a production release at a code at or above the internal one is
    `current`, not `behind`. Until a whole store pass has worked (`checked.stores` is ""), a platform reads
    `unknown`, never `behind`.
  - `prs`: `{open, waiting, merged_7d, unreviewed_7d, open_p1}` — open PRs, PRs that wait on the owner's
    merge, PRs merged in 7 days, merged in 7 days with no review in the ledger, and merged in 7 days with
    an open P1.
  - `activity`: `{last, sessions_7d, spend_7d_usd}`.
  - `waiting`, `oldest_wait_days`, `tasks`: open questions, the age of the oldest, owner tasks.
  - `milestone`: the next `[productize]` target and what is left ("family: 2 of 9 requirements
    left"), or "". `next`: one line, the next step, or "".
  - `facts[]`: short strings for what health does not count: questions that wait and PRs merged without a
    review. Nothing is hidden; it is only not a reason.
  - `progress`: facts only, no percentages, no model text. Built from caches; the snapshot never calls the
    network.

    ```json
    {"can_install": [{"platform": "ios", "version": "1.4.0", "build": "52", "channel": "testflight", "state": "current"}],
     "shipped_7d": {"prs": 9, "top": ["Add the sign-in screen", "Fix the sync retry"]},
     "users": {"weekly": 4, "total": 12, "label": "4 active this week, 12 total"},
     "milestone": "family: 2 of 9 requirements left", "blocker": "", "quiet_days": 0,
     "line": "family: 2 of 9 requirements left"}
    ```

    `can_install`: the platforms with a known build, primary first, same fields and `state` as `platforms[]`;
    a platform with no known build is left out, never shown as behind. `shipped_7d.prs`: PRs merged in 7
    days, without the mechanical ones (release bumps, "Regenerate ... leak gate", merge commits);
    `top`: up to 3 of their titles, newest first, empty when the cache holds no titles (an older cache has
    none until the next `teyla portfolio --refresh`). `users`: the weekly and total user
    counts from the counters of the last usage probes, by `teyla products` or the refresh pass (`wau=` or `weekly_users=`; `users=` or
    `users_total=`, summed over the product's repos), or `null` when there is no cache or no such counter.
    `blocker`: the product's top owner question, cut to 12 words, or "" when it has none (see "Ask triage"). `quiet_days`: whole days since
    the last activity, `null` when there is none. `line`: one sentence of at most 12 words, the first that
    exists of: open P1s, the milestone, the primary platform's build, "Quiet for N days"; never a session title.

Health measures the product, not the owner's queue. Applied in order; the first that matches wins and every
match adds a reason:

1. `parked` when the stage is `parked`.
2. `off_track` when the primary platform is `blocked`, or `behind` for more than 2 days; or when a PR
   merged in 7 days has an open P1.
3. `at_risk` when any other platform is `blocked` or `behind`, or when a `building` or `beta` product had
   no session for 14 days.
4. `on_track` otherwise.

A question that waits, and a PR merged without a review, no longer change health: they stay as the raw
counts (`waiting`, `oldest_wait_days`, `prs.unreviewed_7d`) and as `facts[]`. An open P1 stays a reason.

### Home: sections and metrics (additions to version 3)

Home ranks the products by itself and shows, for each, what it is and how it did over a week, a month and a
year. Old clients keep working: every field above stays, and these are only added. Everything is built from
caches and local files; the snapshot still makes no network call.

`portfolio.home.sections` always holds three objects, in this order, even when one is empty:

```json
{"home": {"sections": [{"id": "users", "ids": ["sample-app"]}, {"id": "building", "ids": ["sample-tool"]}, {"id": "quiet", "ids": []}]}}
```

Every product id is in exactly one section. The rule uses 7-day signals only, so the week / month / year switch
on a client never moves a product or reorders a section:

| Section | Who | Order |
|---|---|---|
| `users` | not parked, and `active` 7d > 0 or `new` 7d > 0 | starred (`focus`) first, then active 7d, new 7d, commits 7d (more first), then id |
| `building` | not parked, not in `users`, and commits 7d >= 5 (`BUILDING_MIN_COMMITS`) | starred first, commits 7d, id |
| `quiet` | parked products, and the rest | starred first, commits 7d, commits 30d, id |

A count that is `null` sorts after every real number.

Each `portfolio.products[]` row also has:

- `summary`: one line of at most 140 characters, or "". The first that exists of: `[productize] summary` in a
  repo's `teyla.toml`; the registry field (`teyla product set <id> summary="..."`); the first prose paragraph of
  the repo's `README.md` (headings, badges, images, HTML, tables and lists skipped).
- `icon_jpeg`: base64 of an 88 px JPEG (quality 70), or "". Taken from the largest PNG of an
  `AppIcon.appiconset` in the product's repos, else the first of `public/apple-touch-icon.png`,
  `public/icon.png`, `public/logo.png`, `app/icon.png`, `icon.png`. Converted by macOS `sips` during the refresh
  pass and cached by source path and modification time. Over 8 KB of base64 it is dropped, and without `sips`
  (Linux) there is none. The phone reads it through the relay, so it stays small.
- `metrics`:

```json
{"users":   {"total": 12, "active": {"7d": 4, "30d": 6, "365d": 9}, "new": {"7d": 1, "30d": 3, "365d": 9}},
 "commits": {"7d": 21, "30d": 80, "365d": 640, "weeks": [30, 12, 8, 9, 15, 20, 25, 18, 22, 16, 11, 21]},
 "spend_usd": {"7d": 210.5, "30d": 790.0, "365d": 5200.0},
 "money":   {"enabled": false, "mrr_usd": null, "paying": null, "revenue_usd": {"7d": null, "30d": null, "365d": null}}}
```

`null` means Teyla does not count it. It is never zero, and a client shows a dash. Nothing is estimated.

- `users`: from the usage cache (the counters `teyla products` last printed), summed over the product's repos;
  `null` when no repo prints the key. `total`: `users_total=`, `total_users=`, `users=`, `user_count=` or
  `accounts=`. `active` 7d: `wau=`, `weekly_users=`, `weekly_active=`, `active_users_7d=`, `users_7d=` or
  `active_7d=`; 30d: `mau=` or `active_30d=`; 365d: `active_365d=`. `new` 7d: `new_7d=` or `users_new_7d=`;
  30d: `new_30d=` or `users_new_30d=`; 365d: `new_365d=` or `users_new_365d=`.
- `commits`: from local git, no network, computed in the refresh pass. Non-merge commits on `origin/HEAD`
  (`HEAD` when the repo has none) over the last 7, 30 and 365 days, summed over the repos. These paths are left
  out because a fleet-wide policy sync touches them in every repo: `AGENTS.md`, `CLAUDE.md`, `teyla.toml`,
  `.claude`, `.github`, `.githooks`, `docs`, `README.md`, `CHANGELOG.md`, `.agents`, `check.sh`. `weeks`: 12
  buckets of 7 days ending now, oldest first, so the last one equals `7d`. All four are `null` / `[]` (empty)
  when git cannot answer for any repo or the refresh has not run yet.
- `spend_usd`: `7d` equals `activity.spend_7d_usd` (0.0 when there was none). `30d` and `365d` come from the
  same local transcripts and are `null` until the next refresh after an upgrade.
- `money`: `enabled` is `[monetization] enabled = true` in a repo's `teyla.toml`; absent means `false`. While
  it is `false` every other field is `null`, even when a probe prints revenue. When it is `true`, the values come
  from the usage keys `mrr_usd=`, `paying_users=`, `revenue_7d_usd=`, `revenue_30d_usd=` and
  `revenue_365d_usd=` (summed over the repos; `null` for a key nobody prints).

The refresh pass (`teyla portfolio --refresh`) gained a fourth, local part, `metrics`: commits and icons. Like
`activity` it needs no network, so it also runs in safe mode, and a part that fails keeps its old rows. The
cache keeps `metrics` next to `activity`; an older cache without it loads with empty metrics.

The store part also keeps the first error per tool in the cache's `store_errors`, emptied by each store pass, and
`teyla doctor` shows them as `stores:play` and `stores:testflight` rows. That field is not in the snapshot.

The pass also runs the usage probes, the walk of `teyla products`, so the user numbers are as fresh as the rest. Each
probe is that repo's own code and may call its backend, so this part runs only with the network part: not in safe mode
unless `--allow-network` is given, and then only in `[products] repos`. The counters stay in
`~/.teyla/products-cache.json`, whose `at` says when they last ran. A probe that fails, or exits 0 with no numbers,
keeps the repo's last good row.

### New command

| Command | Does |
|---|---|
| `teyla portfolio [--json] [--refresh] [--product ID]` | The portfolio object; text is one line per product. `--refresh` runs the network pass first (TestFlight, Play, GitHub, usage probes), within safe mode's rules. |

## The store build (Mac App Store and TestFlight)

The Mac App Store requires App Sandbox, and a sandboxed app cannot run `teyla`, read `~/.claude` or
open a login shell. So the store build is a client of the signed relay folder, like the iPhone app
(see "The relay"), and the build `install.sh` makes stays the full, unsandboxed app.

| | Full app (`Teyla` target) | Store build (`TeylaStore` target) |
|---|---|---|
| Bundle id | `com.zaitsew.teyla.local` | `com.zaitsew.teyla` (the iPhone app's id: universal purchase) |
| Sandbox | off, ad-hoc signed | on, hardened runtime, `STORE` compile condition |
| Data | runs `teyla state --json` | reads `state.teyla` from the relay folder, verifies the signature, decodes snapshot v3 |
| Actions | `teyla answer`, `say`, `dispatch` | signed `outbox/<uuid>.json` entries; the result is `sent/<uuid>.json` |
| Refresh | session-store watcher, 60 s timer | folder watcher, 10 s timer |

Entitlements: `app-sandbox`, `files.user-selected.read-write` (the folder the owner picks),
`files.bookmarks.app-scope` (the folder stays chosen across launches) and `device.audio-input`
(dictation). No network, no temporary exceptions. Voice stays on the device.

Setup. With no folder bookmark and no key, the window shows "Connect Teyla on this Mac" with one primary step: "Copy command
and open Terminal". It copies `uv tool install --python 3.12 git+https://github.com/zaitsew/teyla && teyla relay connect`,
opens Terminal (`NSWorkspace`, bundle id `com.apple.Terminal`) and says "Paste it in Terminal and press Return. Teyla connects
by itself." The sandboxed app cannot type into Terminal, so one paste is the least it needs. "Let your coding agent do it"
copies a one-sentence prompt that asks an agent with a terminal to run the same line. `teyla relay connect` turns the relay
on, makes the key, runs one sync and opens `teyla-pair:v1:<key>` in the store build (below).

The pairing link. The store target alone registers the URL scheme `teyla-pair` (`CFBundleURLTypes` in `project.yml`); the
full `Teyla` target must not. `AppDelegate.application(_:open:)` hands the link to `StoreSession.receive(url:)` and brings
the window forward. Any web page can open such a link, so the rules are:

| State when the link arrives | Result |
|---|---|
| No key | Pairs, and leaves sample mode if it was on. |
| The same key | The key does not change. The folder panel still opens if no folder is chosen, and the sample is left. |
| A stored key that could not be read | Nothing changes. The window says the key could not be read. |
| A different key | The stored key stays. A pending value is set and the window asks "Replace the pairing with this Mac?" |
| A different link while one waits | The waiting key is kept and marked as a conflict. Replace then stores nothing, and the window says two links arrived. Only the owner's answer clears it. |
| Not a `teyla-pair:v1:` link with a 32-byte key | Rejected; nothing changes. |

Once a key is stored and no folder is chosen, the folder panel opens at once. The panel opens on `iCloud Drive/Teyla` when that
folder exists, with the prompt "Use this folder" and a message that this is the only click needed (`FolderPanelPlan`). If it
does not exist, the panel opens on iCloud Drive with New Folder allowed and says to create or pick a folder named Teyla. A
chosen folder with no `state.teyla` is kept, with a notice that the Mac has not written yet and to run `teyla relay connect`.

"Connect by hand" (a disclosure on the same screen) keeps the manual path: the three commands, a folder button and a field for
the pairing string, in either order. The key goes to the login Keychain and the folder to a security-scoped bookmark.

Sample mode. "See a sample" (also what App Review sees) loads the bundled `Teyla/Store/sample.v3.json`, a
made-up snapshot with questions, tasks, running and finished sessions, products and a portfolio, so every screen
has content. A banner reads "Sample data — connect to see yours" until the owner connects. Every send is
simulated and says "Sample: nothing was sent"; nothing is written to disk. `Tools/make_store_sample.py` rebuilds
the file from `tests/fixtures/state.v2.json`.

What the store build leaves out, because it needs the command line: notes and the quick-note panel, the first-run
diagnosis, the Operations page, editing a product's stage or focus, snooze and "mark done", and the Codex/Claude choice for a new
task (the Mac chooses). These controls are not drawn, rather than drawn and disabled. Product pages are
built from the snapshot: the open questions and the recent sessions, without spend.

Connect iPhone. Both builds have it (File → Connect iPhone…, and Settings → iPhone). One sheet shows a large QR code with two steps:
install Teyla from TestFlight, then point the iPhone camera at the code. The camera opens Teyla on the iPhone because it
registers the same `teyla-pair` scheme as the store build. The code clears after 5 minutes and when the sheet closes; the
string sits behind a small "Copy pairing string". The full app has one button: it runs `teyla relay on` when the relay is off,
then `teyla relay pair --json`, so it no longer waits behind the toggle. The store build runs no command: it encodes the key
in its Keychain with `RelayCrypto.pairingString(for:)` (base64url, no padding, the inverse of `parsePairing`), and offers the
entry once it is connected to a Mac (a key and a folder).

A bad signature shows nothing from the file ("The snapshot's signature does not match your pairing"). The
snapshot and the answers sit in iCloud Drive as readable text, which Apple can read unless the owner turns on
Advanced Data Protection; the signature stops others from forging an action, not from reading.

First launch of the full app after the id change copies the four settings it keeps (the `teyla` file, the default
product, the voice language and the quick-note shortcut) from the old `com.zaitsew.teyla` domain, once.

## Ask triage (from 2026-11-02, additive, still version 3)

The app decodes these fields as optional. Nothing was renamed or removed.

- `asks[].triage`: `{bucket, action, default, why, source}`, absent when no rule or cached model answer decides
  the ask. `bucket` is `owner` (needs you), `agent` (an agent can act on it with nothing from you) or `close`
  (looks closable). `action` is `pay`, `decide` or `do` for `owner`, else "". `default` is a proposed answer, or "".
  `why` is at most 12 words. `source` is `rule` or `model`. An ask with no `triage` is an ordinary owner
  question: draw it with the owner questions.
- `asks[]` is ordered owner (or no triage), then agent, then close, then muted; `rank` follows that order.
- `totals.questions` and `products[].waiting` (and `portfolio.products[].waiting`) count owner questions only:
  an ask counts unless its bucket is `agent` or `close`. `totals.questions_raw` and `waiting_raw` (on both
  product lists) keep the count of every ask that is not muted, so the difference is visible.
- `portfolio.products[].progress.blocker` is the product's top owner question, at most 12 words, or "".
- `auto_closed`: `{count, items: [{id, title, product, reason}]}`: the questions Teyla closed on its own
  (`auto:` reasons in the done store) in the last 24 hours, newest first. A question you closed yourself, one
  `teyla answer` closed, and one `accept-close` closed are not in it. `count` is the full number; `items`
  lists at most 50. It is `{"count": 0, "items": []}` when there is none.
- `tasks[]` leaves out a merge task when a closed question about merging that PR exists and no open question names it.
- The brief is written from the owner questions only.

A `close` question stays open. `teyla asks accept-close` closes them together and prints
`undo: teyla asks undo <ids>`; `teyla asks triage` prints the buckets and calls no model. Rules and the cache are
described in [ASKS.md](ASKS.md).

## Admin sections: the console report (from 2026-11-04)

Growth, Money, Operations and Playbook read one command, `teyla console --json` (the cache at
`~/.teyla/console-cache.json`, 30 minutes old at most; `--refresh` rebuilds it, and Money's rebuild takes about half a
minute). The report has four sections. A section that failed is `{"error": "..."}`; the others still load. The app
(`Core/ConsoleReport.swift`, `App/ConsoleModel.swift`) paints the cache first, reads again when a page opens with a
report older than 5 minutes, and keeps the last report when a read fails, with a note that says so. A key the report
does not carry shows a dash with the reason, never a zero. The store build has no admin sections
(`Capabilities.console`). Every page shows "Updated N min ago" and a "Check again" button.

Preview hooks: `TEYLA_CONSOLE_FIXTURE` (default `console.v1.json` beside the state sample) and
`TEYLA_PREVIEW_SNAPSHOT_VIEW=growth|money|operations|playbook`.

## Money page (from 2026-11-04)

The page reads `console.money`. Cash and list price are kept apart on purpose: cash is the sum of the subscriptions the
owner lists (`~/.teyla/subscriptions.toml`), and list price is what the local AI sessions would cost at API prices, which
a subscription bills differently. List price is always labelled "Not cash" and is never added to cash. Top to bottom:
four figures (cash per month, next renewal, credits included, Actions minutes); the subscriptions, the dearest first,
with a dash and the reason for a row that has no price; what the AI providers billed in 30 days (a dash with the reason
when there is no admin key); the list-price section with a 7 or 30 day switch, three figures (at list price, of which
subagents, billed by the API), the last 30 days as bars, and by product and by model with a bar against the largest row
(six rows, then "Show all"); and the cloud and GitHub Actions rows. A cloud row that is also a subscription is not
repeated. Dollars show whole for a round amount and two decimals otherwise; an amount under one cent reads "less than
$0.01", never zero. One considered layout, no variants.

## Playbook page (from 2026-11-04)

The page reads `console.playbook`. Each part loads on its own: a part that fails shows its reason in place and the rest
stay. Top to bottom: four figures (unresolved contradictions, guidelines, models to look at, corrections in 30 days);
the contradictions (a rule you wrote, then corrected twice or more); the guidelines, each of which opens its file when the
report says the file exists; the model ladder per provider (plans and reviews, builds, quick jobs), where the ladder
differs from the catalogue, new catalogue models nobody has looked at, and the arena shortlist, where every row says
"candidate, not a decision"; counts of what is kept (your words, corrections, wiki pages, design decisions); and what
the sessions say about you: the quote of the day (others behind "Show more"), the prompt figures, a then-and-now card,
and the chores to hand off, the open ones first. Backticks the source writes around commands are dropped. The page reads
this Mac's own files only and sends nothing. One considered layout, no variants.

## Growth page (from 2026-11-04)

The page reads `console.growth` plus the draft files. `teyla console` carries counts only, and `teyla growth review` has
no `--json`, so the drafts waiting for you come from `~/.teyla/growth/items/*.json` (or under `TEYLA_HOME`), read as
they are: status `review` or `checked`, not an episode, not a master idea, not held by the editor, best editor score
first. The app never changes an item file. Items that cannot be read are counted in a note, not hidden.

Top to bottom: four figures (slots filled today, drafts waiting for you, days of approved drafts ahead, days since
anything went public); the channels, one row each, with today's posts against the target; **Waiting for you**, the
main block; the pipeline from ideas to posted this week; what is in the works (episodes and the next ride); trend
ideas (each opens its page and only starts a draft); and outreach counts.

A draft opens to its full text, hook, first comment, facts, sources, editor score and critique, and the voice and leak
checks. Three actions run `teyla growth approve`, `reject --reason` and `edit --body`. Approve is off while a check
failed or never ran, with the reason beside it. **Approving only marks a draft: nothing in the app posts, sends or
publishes.** The allow-list in `ToolCommands` refuses every other `growth` command. Outreach is counts only.

Two layouts sit behind the Layout switch while you choose: the review queue first, or the channel board first. The
loser and the switch are removed once you pick. Sale attempts per product belong to the Product page.

## Product page: users and selling (from 2026-11-04)

Between "Needs you" and the notes, a product page shows four figures: active users this week, sale attempts, what
shipped in 7 days, and feedback and crashes. Users and shipped come from the portfolio report; a product with no usage
counter shows a dash and says so. **Feedback, store reviews and crashes have no source yet, so that figure is a dash with
that reason, never a zero.**

Sale attempts are counted from `~/.teyla/growth/ledger.jsonl` (or under `TEYLA_HOME`) the way `teyla growth
sale-attempts` counts them: a published post or an attempt of kind `post`, marketing (kind `ad` or `outreach`) and ICP
meetings (kind `icp-meeting`). No command prints this as JSON, so the app reads the ledger read-only. Zero reads "Not tried
yet. Next in line."; the page never proposes closing a product nobody tried to sell. A parked product reads "Not tried
yet. Parked." Lines that are not JSON are counted in a note. The block is off in the store build (`Capabilities.console`).
Preview hook: `TEYLA_LEDGER_FIXTURE` (default `ledger.v1.jsonl` beside the state sample). One considered layout.

## Settings page (from 2026-11-04)

The sidebar's Settings button opens a page in the main window (the store build keeps the Settings window, and ⌘, still opens
it). The page reads `~/.teyla/config.toml` (or under `TEYLA_HOME`) directly and read-only; no command runs. It shows four
figures (keys set, work mode, automatic clean-up, updates), then the file in plain groups: Folders, Updates, Machine guard,
Disk clean-up, What Teyla keeps, Products and agents. A key the file does not set shows its default, grey. Then the names
under `[env]`, this app's own switches (voice language, quick-note shortcut, Connect iPhone) and the file's path with a
"Show in Finder" button. A count says how many keys the groups do not list.

**No secret is shown.** The parser drops the value of every key under `[env]` and of any key whose last part contains key,
token, secret, password or credential, so it never reaches a view (`TeylaConfigTests` checks that no such value appears in
a row). A missing file reads as the defaults; a file that cannot be read is an error, never "all defaults". Lines the small
TOML reader cannot parse are counted, not guessed. The page does not write the file. Preview hooks: `TEYLA_CONFIG_FIXTURE`
(default `config.v1.toml` beside the state sample), view `config`. One considered layout.

## Tools and the command bar (from 2026-11-02)

**Operations** (from 2026-11-04; it was the Tools page). The page reads `console.operations` and, top to bottom, shows:
four figures (unresolved failures, safe to leave, disk free, swap used); what is still running when the Mac cannot be
left; the machine with 24-hour lines of disk free and swap used (from `series`), memory, load, agents, work in flight
and the biggest apps; the failures; the scheduled tasks worst first (late, gone, not loaded, never ran, unknown), with the
calm ones behind "Show all"; the harnesses and whether their AGENTS.md copies match the policy, with the fix command to
copy; and the security counts with the date of each scan. A count the report lacks is a dash with the reason (the shield
result is not kept between runs). The cards below keep the behaviour of the old Tools page.

**Failure cards.** A failure that `teyla attention` also lists gets that item's card, with its actions. Any other
failure shows its sentence and, when the report names a command, the command with a Copy button. The app does not run it.

**Tools** (the actions part of Operations). It was a sidebar item under All products. It shows what is wrong on this Mac's backend now, from one command,
`teyla attention --json` (`docs/COMMANDS.md` has the schema). The command reads local state only and makes no network
call; a source that fails, times out or has a cache older than a day comes back as an `unknown` item, so a failure never
reads as calm. The app reads it at launch, when the page opens with a report older than 10 minutes, after an action, and
on "Check again". It takes up to half a minute on a loaded Mac, so it never runs on the 60 s timer.

- Top line: "Nothing needs you here." only for a report that was read and holds no item, with what was checked and is fine
  under it (`quiet`: 14 scheduled tasks fine, builds current, disk free). Otherwise "N things need you and M more to look
  at". A failed read says so in the danger colour and keeps the last list, marked with its age; the sidebar badge then
  shows "!" instead of a count. The badge counts items with `severity == "act"` only.
- Items are cards: kind symbol, the sentence, one line with a number, optional facts (an offer's trade-off and undo, a
  doctor row's fix) and the actions. "Needs you" cards come first, then "Worth a look". An item with no action says that
  nothing in the app can fix it yet.
- An action goes in steps. With a `preview` the app runs the preview first (always a dry run) and shows its last 14 lines;
  the exact command and the button come after. Without one, the exact command and the button come first. A `destructive`
  action says "This cannot be undone." above the command. Only `portfolio --refresh`, which reads and writes a cache,
  runs on one click. After a run the report is read again, the result stays in a notice, and the snapshot is refreshed.
- Allow-list (`Core/ToolCommands.swift`): `schedules forget <id>…`, `storage sweep [--dry]`, `apply O<n> --yes|--dry`,
  `portfolio --refresh`. A command from the report that is not on the list is refused and shown as refused, as is a
  preview that is not a dry run. Nothing that charges money, sends a message, deploys or submits to a store is on it.
- The "First-run diagnosis" section at the bottom opens the diagnosis page. The store build has no Operations page and no
  command bar actions (`Capabilities.tools`).

**Command bar (⌘K, View menu → Command Bar…).** A sheet with a text field over a fixed list: Go to Home, Decisions, All
products, Growth, Money, Operations, Playbook; Open <product> for each product with a page; New task; Refresh; and the actions currently on the Tools
page. Matching is plain text (a word that starts a word of the title, then a keyword, then any part of the title or of an
action's command); no model is asked. The arrow keys move, Return chooses, Escape closes. An action entry shows its exact
command and "asks before it runs"; choosing it opens that card at its preview or confirm step and never runs it from the
bar. ⌘N, ⌘0 and the other shortcuts are unchanged.

Preview hooks: `TEYLA_PREVIEW_OPEN=operations` (or `tools`) and `command-bar[:<query>]`, with `TEYLA_ATTENTION_FIXTURE` (default
`attention.v1.json` beside the state sample; `attention.empty.v1.json` is the empty report).

## The iPhone app: Home and Decisions (from 2026-11-02)

The iPhone app has three tabs: Home, Decisions and Products. It reads the same snapshot as the Mac app through the
relay and shares `HomeLogic.swift` with it, so the grouping, the ranking and the wording are the same.

- **Home.** The same page as the Mac's Home, in one column. Top to bottom: the pulse strip, the Next line (it opens
  the Decisions tab) and the sync line; a
  **Week / Month / Year** switch (44 pt high, for the whole page, remembered as `teyla.home.period`); **People use
  these** (a full-width card per product: icon or letter, name, stage, `summary`, active / new / total users for the
  period, commits with a 12-week bar chart, agent spend, and a Monetization row that reads "Off" while
  `metrics.money.enabled` is false, else MRR and paying users); **Decisions** (the top five of the last 7 days, "See
  all N", with the note "Only you can answer these"); **Being built** (one list: icon or letter, name, one line of
  `summary`, commits for the period; the first 6, then "Show all N" opens the rest in place); **Quiet** (a plain
  list: small icon or letter, name, one line of `summary`, "N commits this week"; the first 5, then "Show all N");
  then "Running now (N)", folded. A card or a row opens the product page. The sections and their order come from
  `portfolio.home` and are never re-ranked; the switch changes numbers only. A `null` shows "—", never 0; empty
  `weeks` draws no chart; there is no percentage and no health word. Icons are decoded once and cached. A card is one
  VoiceOver element (name, active, new, total, commits); at the accessibility text sizes the three big numbers stack
  instead of clipping. The star is set on the Mac; the phone only shows the result.
- **Decisions.** The owner's questions grouped Pay, Decide, Do, an "Older" fold, "Teyla suggests closing N",
  "Agents can settle N", "Teyla closed N", the tasks only the owner can do, and what got done.
- **From the phone.** Answering a question works, and "Use default" sends the proposed answer except for a
  payment. Accepting a suggested close and undoing a close work too, through two new outbox kinds, `close` and
  `reopen` (see the relay). "Agents can settle" has no bulk send: each answer resumes a session.
- **Older Mac.** When the Mac's Teyla sends no `portfolio.home` (before 0.36), Home says "Update Teyla on your Mac"
  instead of the product sections and the decisions still show; a Mac that refuses `close` or `reopen` as a malformed
  entry gets the same advice. The sample (`Teyla/Resources/sample-state.json`, written by
  `apps/ios/Tools/add_home_sample.py`) has 18 invented products, so all three sections and both "Show all" buttons
  appear in sample mode.
- **Mac only.** The Operations page, the ⌘K command bar and `teyla attention` stay on the Mac: they run commands on
  the Mac, and the phone sends only the five relay kinds.

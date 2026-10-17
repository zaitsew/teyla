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

The app re-runs `teyla state --json` within 2 s of a change under the session stores
(`~/Library/Application Support/Claude/claude-code-sessions`, `~/.claude/projects`,
`~/.codex/sessions`), and every 60 s otherwise.

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
- `products[]`: `{name, waiting, state, line, last_activity}`.
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
  repeated for 5 minutes. Off with `[state] model_brief = false`, in safe mode, or without `claude` on PATH.
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
- `products[]`: adds `issues` (open GitHub issues), `prs_waiting` (open PRs that wait on the
  owner's merge), `next` (one line, the next step, or "") and `repo` (its path, or "").
  Products that are one repo under two names are merged into one row.
- `running[]`: adds `id` (what `teyla say` takes) and `correct`: `codex-queue` when a correction
  can be queued into the live session, `open` when the window can only open it.
- `relay`: `{on, paired, folder, synced}` — whether the iPhone relay is on, whether a phone is
  paired, the folder, and when the Mac last wrote the snapshot there.

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

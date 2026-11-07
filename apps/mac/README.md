# Teyla for Mac

A native macOS window and menu-bar icon that briefs you each morning in one sentence. Below it:
the questions only you can answer (ordered by what each unblocks), the tasks only you can do,
what got done since yesterday, where each product stands, and what runs now. You answer in the
window, correct a running session, or start a new task, by typing or by voice. It holds no data
of its own: it runs the Teyla CLI. The design and the data contract are in
[`docs/APP.md`](../../docs/APP.md).

## Quick start

```sh
brew install xcodegen                 # once
# make sure `teyla` is on your PATH (see the repo README)
cd apps/mac && ./install.sh           # builds Release, copies it to ~/Applications/Teyla Admin.app
open ~/Applications/"Teyla Admin.app"
```

No CLI yet? Preview with the sample data (writes are simulated, nothing is delivered or started):

```sh
open -n --env TEYLA_STATE_FIXTURE="$PWD/../../tests/fixtures/state.v2.json" ~/Applications/"Teyla Admin.app"
```

Requires macOS 15 and Xcode. The app is ad-hoc signed for local use only. Its bundle id is `com.zaitsew.teyla.local`;
a first launch copies the settings kept under the old id `com.zaitsew.teyla` (see below).

## Two builds

| Target | Bundle id | For |
|---|---|---|
| `Teyla` | `com.zaitsew.teyla.local` | The full app `install.sh` installs: runs the `teyla` command, not sandboxed. |
| `TeylaStore` | `com.zaitsew.teyla` | The Mac App Store and TestFlight build: App Sandboxed, reads the signed relay folder like the iPhone app, no command line. Version 0.32.0, build 2. |

The store build's design is in [`docs/APP.md`](../../docs/APP.md#the-store-build-mac-app-store-and-testflight). It has no
network access; its entitlements are `app-sandbox`, `files.user-selected.read-write`, `files.bookmarks.app-scope`
and `device.audio-input` (`Teyla/TeylaStore.entitlements`). Without a paired Mac it shows "Connect Teyla on this Mac":
"Copy command and open Terminal" (one paste: `uv tool install … && teyla relay connect`), "Let your coding agent do it",
"See a sample", and "Connect by hand" for the manual steps. `teyla relay connect` hands the key to the app as a
`teyla-pair:v1:<key>` link (only the `TeylaStore` target registers the `teyla-pair` scheme), and the folder panel then opens
on `iCloud Drive/Teyla` ("Use this folder"). A link with a different key asks before it replaces the stored one.
The sample is bundled (`Teyla/Store/sample.v3.json`, rebuilt by
`python3 Tools/make_store_sample.py`) and every send in it is simulated.

```sh
# Build it unsigned, for a compile check
teyla load --wait --kind build && xcodebuild -project Teyla.xcodeproj -scheme TeylaStore \
    -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build
# Preview the sample without a pairing (an argument-domain default, not stored):
open -n path/to/Teyla.app --args -storeSampleMode YES
```

Signing and upload use the App Store Connect key, never a password: `DEVELOPMENT_TEAM` stays empty in the project and
the release script passes the team. Version 0.32.0, build number `CURRENT_PROJECT_VERSION` 2 (1 went to TestFlight on 26 October).

## Activity graph

Growth opens with an Activity card: the contribution graph of your marketing and sales activity, fed by `teyla growth activity`.
A "+1" button (⌘L) logs one post, comment, email, meeting and so on with `teyla growth log`. Two layouts exist to compare:

```sh
defaults write com.zaitsew.teyla.local teyla.activity.layout quarter   # 17 weeks, large squares, the streak as a big number
defaults write com.zaitsew.teyla.local teyla.activity.layout year      # 53 weeks (the default)
defaults delete com.zaitsew.teyla.local teyla.activity.layout          # back to the default
```

A preview reads `TeylaTests/Fixtures/activity.v1.json` beside the state sample (`TEYLA_ACTIVITY_FIXTURE` names another file);
`python3 Tools/make_activity_fixture.py` writes it. Details: [`docs/APP.md`](../../docs/APP.md), "Activity graph".

## Today

The admin build opens on **Today** (the first row of the sidebar; the store build opens on Home and has no Today). It answers
what waits for you, did enough go out, and which goal moved. It reads `teyla gtm today --json` (the contract is in
[`docs/GTM.md`](../../docs/GTM.md)) and the drafts the Growth page already reads, and it never posts or sends: Approve only marks
a draft, and Open goes to the item's own page. No commit counts appear on it.

It shows the ordered next actions, the drafts waiting for approval, what waits to be sent or answered per source (an Open button
when the source gave a page), today's distribution against the daily target, this week's outcomes against each goal's targets
with the days left, and the source checks folded at the bottom. The "+1" button and ⌘L work here as on Growth.

| Key | Does |
|---|---|
| ↑ / ↓ or K / J | move the selected draft |
| A | approve the selected draft (it only marks it) |
| S | skip to the next draft; the draft does not change |
| O | open the draft's first source page, or the full draft on Growth when it has none |
| ⌘R | read again |
| ⌘L | log a "+1" |

Reject needs a reason, so it is a button that opens a small form. Two layouts exist to compare (they differ in structure):

```sh
defaults write com.zaitsew.teyla.local teyla.today.layout queue   # the next draft large, the actions beside it, a number strip (the default)
defaults write com.zaitsew.teyla.local teyla.today.layout board   # three counters and goal progress first, the queue as a list below
defaults delete com.zaitsew.teyla.local teyla.today.layout        # back to the default
```

A preview reads `TeylaTests/Fixtures/gtm-today.v1.json` beside the state sample (`TEYLA_GTM_FIXTURE` names another file). A `teyla`
without `gtm` shows one line, "Update the teyla command to see Today.". Screenshots, with the sample data:
`TEYLA_STATE_FIXTURE=TeylaTests/Fixtures/state.sample.v3.json TEYLA_PREVIEW_SNAPSHOT=out.png TEYLA_PREVIEW_SNAPSHOT_VIEW=today
TEYLA_PREVIEW_APPEARANCE=dark Teyla -teyla.today.layout board` (the launch argument sets the layout for that run only).

## First run

- **No `teyla` found:** the window gives `uv tool install --python 3.12 git+https://github.com/zaitsew/teyla` with Copy, "Check again"
  and "Choose…". The file you choose is stored in UserDefaults (`teylaBinaryPath`) and tried first.
- **No data yet:** the window shows the Teyla lockup, the promise and "Run diagnosis". It runs `teyla start --json` (read-only,
  up to about a minute) and then lists each offer with its saving or benefit, trade-off and undo. "Apply…" shows one sheet
  that names the file and key, then runs `teyla apply <id> --yes`. "Diagnosis" stays in the sidebar.
- **Product pages:** click a product card on Home, a row in All products, a note chip, or the product name on a question. The page shows the stage
  (menu), the focus star, waiting questions, notes (Link…, Drop), the last 10 sessions and the spend over 7 and 30 days.

## What the window shows

| Section | Content | Action |
|---|---|---|
| Home: sentence | `brief.line`, then one quiet line: decisions waiting, sessions running, spend labelled "API-equivalent". | None. |
| Home: core products | One card per `portfolio.core` product (up to 6): title, star, one line of progress, what can be installed, PRs merged in 7 days, users, milestone, blocker, "Quiet for N days" from 14 days. | Click opens the product page; the star adds or removes the product (`teyla product core`). |
| Home: decisions | The top five questions that wait on you, then "See all N". With triage, Teyla's proposed answer shows on the card. | Answer with an option, "Use default" or text; snooze; mark done. |
| Home: "Teyla closed N" | Shown only when Teyla closed questions (`auto_closed`). | Review the reasons; Undo reopens one (`teyla asks undo`). |
| Decisions | Every question that waits on you, grouped Pay, Decide, Do when triaged, else one ranked list; those older than 7 days fold into "Older · N". Then "Agents are handling N", Only you (`tasks[]`), the Notes section and "Done since yesterday", folded. | As on Home; "Close — no longer needed" on an older one; Open (the link) on a task; Open session on a result. |
| Notes | The Inbox count and the newest five open notes, on the Decisions page: product chip, age, the text clipped to two lines. | Link… (a product menu) or Drop; New note opens the panel. |
| Home: running now | Folded, "Running now (N)". Each session active in the last 10 minutes. | Codex: a one-line correction field (`teyla say`). Others: Open. |

Notes:

- **New task** (toolbar, ⌘N, menu-bar item): product (default: the selected one), Codex (default)
  or Claude, and a text field with a mic. Send runs `teyla dispatch`; the sheet shows the worktree
  and an Open button for the session.
- **Voice**: Apple Speech with `requiresOnDeviceRecognition = true`, in English, Spanish or Russian
  (picker in the sheet and Settings; remembered). If the language is not installed for on-device
  use, the app says how to add it (System Settings → Keyboard → Dictation) and does not start; it
  never falls back to server recognition. Hold a mic button to talk, or click to start and stop.
  Text lands in the field; nothing is sent until Send.
- **⌥⌘Space** (Carbon `RegisterEventHotKey`, no Accessibility permission): brings the window forward
  and dictates into the new-task sheet. Settings shows whether the shortcut registered.
- **Quick note**: a global shortcut (default **⌥Space**, optional) opens a small floating panel
  over any app, without bringing Teyla forward. Type, and the product chip pre-selects itself
  ("named in the text" or "from Inbox", 300 ms after you stop typing); ⌘1–⌘9 or a click changes it,
  ⌘0 is the Inbox. ⏎ saves (`teyla note - --product <id> --json`, the text on stdin), ⇧⏎ adds a
  line, Esc closes and keeps the draft. A failed save keeps the panel open with the error. The
  menu-bar item "Quick note" opens it too and shows the shortcut that is active, or none.
- **Settings** (⌘,): **Quick note shortcut**: click the field, press a combination with ⌘, ⌥ or ⌃;
  Esc cancels, Clear turns the shortcut off. ⌥⌘Space is refused (push-to-talk). If another app owns
  the combination, Settings says so and the shortcut stays off; the menu-bar item still works. Voice language; iPhone relay on or off (`teyla relay on|off`) with when the Mac last synced; **Connect iPhone…**
  (also File → Connect iPhone…, both builds) opens a sheet with a large QR code and two steps (install Teyla from TestFlight,
  point the iPhone camera at the code). The full app turns the relay on when it is off, then runs `teyla relay pair --json`;
  the store build encodes the key in its Keychain. The code clears after 5 minutes and when the sheet closes; "Copy pairing string"
  copies the text behind it.
- **Notifications**: one local notification per new question, with the question as text. Clicking
  it scrolls to the card. Questions already open at launch are not announced.
- **Window**: closing it never strands you. Window → Teyla (⌘0), the menu-bar item and the Dock icon
  reopen it. `LSApplicationCategoryType` is `public.app-category.developer-tools`.

- **All products** (sidebar, needs `teyla` 0.32): one row per registered product with its health (on track, at risk,
  off track, parked), the first reason, a strip of platforms with version, build and state, PR counts, waiting
  questions, last activity and 7-day spend. Filter: All or Needs attention; parked products are hidden until you
  tick "Show parked". A click opens the product page, which shows the same health and platform details.
- **Status** (toolbar): "Updating…" while the state or the open product page loads, "Up to date" under 2 minutes,
  "Stale · N min" when older (a sleep, a hung command), "Offline" on an error. The tooltip shows exact times and when
  the stores and GitHub were last checked. The window also refreshes when the Mac wakes.
- **Width**: question cards and prose stop at 720 pt; Home is 1,100 pt wide at most and fits two or three product cards to a row.

## Where it reads data

- `teyla state --json` for the snapshot. Actions: `teyla answer <id> --json -- <text>`,
  `teyla say <running-id> --json -- <text>`, `teyla dispatch <product> --harness codex|claude --json -- <text>`,
  `teyla relay on|off`, `teyla relay pair --json`, `teyla asks snooze`, `teyla asks done`. Free text
  always follows `--`. Notes: `teyla notes --json`, `teyla note --suggest - --json --cwd <home>` and
  `teyla note - --product <id> --json` (both with the text on stdin, never as an argument),
  `teyla note link <id> <product> --json`, `teyla note drop <id> --json` ([NOTES.md](../../docs/NOTES.md)). The binary is looked up in this order: the file chosen in the app, `$TEYLA_BIN`, the `PATH` of a login shell
  (`/bin/zsh -lc 'command -v teyla'`, asked once), `~/.local/bin/teyla`, `/opt/homebrew/bin/teyla`, `/usr/local/bin/teyla`.
  The first screen also runs `teyla start --json` and `teyla apply <id> --yes`; product pages run `teyla product show <id> --json [--quick]`
  and `teyla product set <id> stage=<s>|focus=<bool>`.
- It re-reads within 2 s of a change under `~/Library/Application Support/Claude/claude-code-sessions`,
  `~/.claude/projects` and `~/.codex/sessions` (missing ones are skipped), every 60 s, and when
  the window gets focus.
- `TEYLA_STATE_FIXTURE=<path>` reads a JSON file instead of running the CLI and simulates every
  write. Use `tests/fixtures/state.v2.json`, or `apps/mac/TeylaTests/Fixtures/state.sample.v2.json` for the first run
  and the product page: `start.v1.json` and `product.v1.json` beside it are the diagnosis and the page. The notes come from `notes.v1.json` beside it
  (or `TEYLA_NOTES_FIXTURE`); link and drop change the list on screen only.
- The pairing string is read from any string value of the `relay pair --json` output, or from plain
  text, and shown only if it matches `teyla-pair:v1:` plus 43 base64url characters.

## Development

```sh
cd apps/mac && teyla load --wait --kind build && xcodegen generate
teyla load --wait --kind build && xcodebuild test -project Teyla.xcodeproj -scheme Teyla -destination 'platform=macOS'
```

The tests cover the store build's logic (the signed snapshot, a bad signature showing nothing, the outbox entry against
`tests/fixtures/relay-vector.json`, simulated sample sends, the settings move), model decoding, formatting, CLI argument building (free text after `--`), fixture
writes, the pairing string and its QR code (read back with `CIDetector`), the pairing string encoder (a round trip, and the string `teyla relay pair` prints),
the `teyla-pair:` link rules (no key, the same key, a different key waiting for a yes, a bad link, the folder panel after pairing) and the folder panel's default, voice rules and
push-to-talk, the new-task defaults, the one-notification-per-question tracker, the note commands
(text on stdin, checked against a stand-in `teyla`), the suggestion and notes JSON, the picker keys,
the shortcut keymap, storage and conflict rule, the diagnosis and product-page JSON (samples from the real CLI), the
binary search order, and the apply and product-set commands. They compile the
`Teyla/Core` sources, the store backend and the iPhone app's relay client directly, so no app is launched. The generated `Teyla.xcodeproj` and `build/`
are not committed.

Views use the tokens in `Teyla/UI/Tokens.swift` (the iPhone has the same names in `apps/ios/Teyla/UI/Tokens.swift`). `Typo` has exactly
five levels (`pageTitle`, `section`, `cardTitle`, `body`, `caption`) plus `number` for big figures. A view picks a level and may change its
weight; it never sets a size, a gap, a radius or a colour. `tests/test_app_design_tokens.py` fails on a literal.

### The visual grammar

`Teyla/UI/Grammar.swift` holds the pieces every page is built from. The iPhone target compiles the same file. A new page uses these before it
makes anything of its own.

| Component | Use it for | How |
|---|---|---|
| `Page` | The scaffold of a page: scroll view, gutter, column width, gap between blocks | `Page(maxWidth: Space.readingPage) { ... }`; the default width is `Space.pageMax` |
| `PageHeader` | The title of a page and one line of context, once per page | `PageHeader(title: "Money", context: "Bills against list price")`, with an optional trailing control |
| `SectionHeader` | The title of a block, the rule for what is in it, a count | `SectionHeader(title: "Failures", note: "Unresolved, newest first", count: 3)` |
| `StatStrip` + `StatTile` | One figure each: a label, a number, one small line. `value: nil` shows a dash, and `detail` says why | `StatStrip { StatTile(label: "Disk free", value: "27 GB", detail: "OK", tone: .neutral) }`; `action:` makes it a button |
| `Scorecard` | A thing with a score: identity, a row of numbers, a footer | `Scorecard(title:, badge:, summary:, numbers: [ScoreNumber(value:, label:)]) { icon } footer: { ... }` |
| `RowGroup` + `RowCard` | A list: one surface, a line between rows, one line of title and one of detail | `RowGroup { RowCard(title:, detail:) { leading } trailing: { ... } }` |
| `SegmentSwitch` | A few options, one chosen: Week / Month / Year, All / Needs attention | `SegmentSwitch(options: [(.week, "Week")], selection: $period)`; `fills: true` on a phone |
| `SparklineView` | Small bars per week; the newest stands out | `SparklineView(heights:, label:)` |
| `EmptyState` | A block with nothing in it: what is missing and the next step, at most two sentences | `EmptyState(title: "No bills listed.", detail: "Add them to subscriptions.toml.")` |
| `ErrorRow` | A block that failed: says which and why, and the rest of the page keeps working | `ErrorRow(section: "Money", message: why) { retry }` |
| `ClampedText` | Anything a person or a model wrote: stops after `lines` and offers More | `ClampedText(text: long, lines: 3)` |
| `.surface()` | The fill and hairline of a card | `.surface(radius: Radius.panel)` |

Rules that keep it tidy: one number per tile; a figure with no source is `nil`, never 0; list-price figures say so in their label; every text has
a `lineLimit` and a way to read the rest (`ClampedText`, a `.help` tooltip, or the page the row opens).

**Home's header.** The default is the pulse strip and one Next line. To compare with a strict one-line sentence:
`defaults write com.zaitsew.teyla.local teyla.home.header sentence`; `defaults delete` the key to go back. In a preview,
`TEYLA_PREVIEW_HOME_HEADER=sentence`. `TeylaTests/Fixtures/state.sample.longtext.json` is the fixture for long text.

**Samples.** `python3 Tools/make_fixtures.py` rebuilds `TeylaTests/Fixtures/*.json` from the real CLI, run on a made-up HOME
(`--keep` prints its path). Run it again when the CLI's JSON changes.

**Icon.** `swift Tools/make_icon.swift` redraws every size into `Teyla/Assets.xcassets`.

**Screenshots.** With `TEYLA_STATE_FIXTURE` set, these variables shape the preview (they are ignored
otherwise): `TEYLA_PREVIEW_APPEARANCE=light|dark`, `TEYLA_PREVIEW_SIZE=<w>x<h>`,
`TEYLA_PREVIEW_SCROLL=end`, `TEYLA_PREVIEW_OPEN=new-task|quick-note|settings|pair (the Connect iPhone sheet)|diagnosis|home|decisions|portfolio|product:<id>|focus:<ask id>`,
`TEYLA_PREVIEW_SNAPSHOT=<path.png>` with `TEYLA_PREVIEW_SNAPSHOT_VIEW=home|decisions|portfolio|product:<id>|tools|settings|window|connect-phone|setup|setup-hand|setup-paired` (draws that view in one image at `TEYLA_PREVIEW_WIDTH` and quits; `window` is the window with its toolbar;
`setup` is the store build's first screen), `TEYLA_PREVIEW_DRAFT=<text>`, `TEYLA_PREVIEW_START_DELAY=<seconds>` (how long the simulated diagnosis takes)
and `TEYLA_PREVIEW_NO_BINARY=1` (shows the not-found screen). The welcome is `state.empty.v1.json`. Capture a window with `screencapture -l <window id>`.

## Not verified on a real run

The store build's `teyla-pair:` link arriving from `teyla relay connect`, the folder panel opening on `iCloud Drive/Teyla`
(the sandbox may hide that folder from the existence check, which falls back to the iCloud Drive view), "Copy command and open
Terminal" launching Terminal, and the alert for a different key were built to the APIs and covered by logic tests, but not
exercised in a signed, sandboxed run. The preview hooks work in the store build too, in sample mode
(`open -n Teyla.app --args -storeSampleMode YES`, with the `TEYLA_PREVIEW_*` variables).

The quick-note shortcut press, typing into the panel from another app, and the recorder's key capture
were built to the APIs but not exercised headlessly. Notification delivery and click-through, the ⌥⌘Space press and on-device recognition need a
logged-in desktop with the permissions granted; they were built to the APIs but not exercised
headlessly. `teyla say`, `dispatch` and `relay` are called as documented in `docs/APP.md`; the
`relay pair --json` key name is not in the contract, so the app searches for the string.

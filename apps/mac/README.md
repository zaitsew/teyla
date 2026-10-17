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
cd apps/mac && ./install.sh           # builds Release, copies Teyla.app to ~/Applications
open ~/Applications/Teyla.app
```

No CLI yet? Preview with the sample data (writes are simulated, nothing is delivered or started):

```sh
open -n --env TEYLA_STATE_FIXTURE="$PWD/../../tests/fixtures/state.v2.json" ~/Applications/Teyla.app
```

Requires macOS 15 and Xcode. The app is ad-hoc signed for local use only.

## What the window shows

| Section | Content | Action |
|---|---|---|
| Needs you | Questions, ranked by what they unblock. | Answer with an option or text; snooze; mark done. |
| Only you | `tasks[]`: a PR to merge, an issue assigned to you, with its age. | Open (the link). |
| Done since yesterday | `done[]` as cards: status chip, product, title, at most 3 result lines, the needs line, links. Four show; the rest are one click away. | Open session. |
| Products | State, issues and PRs waiting, the next step. Click a product to make it the default for new tasks. | |
| Running now | Each session active in the last 10 minutes. | Codex: a one-line correction field (`teyla say`). Others: Open. |

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
- **Settings** (⌘,): voice language; iPhone relay on or off (`teyla relay on|off`); **Pair iPhone**
  runs `teyla relay pair --json` and shows the pairing string as a QR code (cleared after 5 minutes
  and when Settings closes), with when the Mac last synced.
- **Notifications**: one local notification per new question, with the question as text. Clicking
  it scrolls to the card. Questions already open at launch are not announced.
- **Window**: closing it never strands you. Window → Teyla (⌘0), the menu-bar item and the Dock icon
  reopen it. `LSApplicationCategoryType` is `public.app-category.developer-tools`.

## Where it reads data

- `teyla state --json` for the snapshot. Actions: `teyla answer <id> --json -- <text>`,
  `teyla say <running-id> --json -- <text>`, `teyla dispatch <product> --harness codex|claude --json -- <text>`,
  `teyla relay on|off`, `teyla relay pair --json`, `teyla asks snooze`, `teyla asks done`. Free text
  always follows `--`. The binary is looked up in this order: `$TEYLA_BIN`, `~/.local/bin/teyla`,
  `/opt/homebrew/bin/teyla`, `/usr/local/bin/teyla`.
- It re-reads within 2 s of a change under `~/Library/Application Support/Claude/claude-code-sessions`,
  `~/.claude/projects` and `~/.codex/sessions` (missing ones are skipped), every 60 s, and when
  the window gets focus.
- `TEYLA_STATE_FIXTURE=<path>` reads a JSON file instead of running the CLI and simulates every
  write. Use `tests/fixtures/state.v2.json`.
- The pairing string is read from any string value of the `relay pair --json` output, or from plain
  text, and shown only if it matches `teyla-pair:v1:` plus 43 base64url characters.

## Development

```sh
cd apps/mac && teyla load --wait --kind build && xcodegen generate
teyla load --wait --kind build && xcodebuild test -project Teyla.xcodeproj -scheme Teyla -destination 'platform=macOS'
```

The tests cover model decoding, formatting, CLI argument building (free text after `--`), fixture
writes, the pairing string and its QR code (read back with `CIDetector`), voice rules and
push-to-talk, the new-task defaults and the one-notification-per-question tracker. They compile the
`Teyla/Core` sources directly, so no app is launched. The generated `Teyla.xcodeproj` and `build/`
are not committed.

Views use the tokens in `Teyla/UI/Tokens.swift` (spacing, type, colour roles); no literals.

**Icon.** `swift Tools/make_icon.swift` redraws every size into `Teyla/Assets.xcassets`.

**Screenshots.** With `TEYLA_STATE_FIXTURE` set, these variables shape the preview (they are ignored
otherwise): `TEYLA_PREVIEW_APPEARANCE=light|dark`, `TEYLA_PREVIEW_SIZE=<w>x<h>`,
`TEYLA_PREVIEW_SCROLL=end`, `TEYLA_PREVIEW_OPEN=new-task|settings|pair|focus:<ask id>` and
`TEYLA_PREVIEW_DRAFT=<text>`. Capture a window with `screencapture -l <window id>`.

## Not verified on a real run

Notification delivery and click-through, the ⌥⌘Space press and on-device recognition need a
logged-in desktop with the permissions granted; they were built to the APIs but not exercised
headlessly. `teyla say`, `dispatch` and `relay` are called as documented in `docs/APP.md`; the
`relay pair --json` key name is not in the contract, so the app searches for the string.

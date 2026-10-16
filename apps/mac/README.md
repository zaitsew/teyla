# Teyla for Mac

A native macOS window and menu-bar icon that briefs you each morning in one sentence, lists the
questions only you can answer (ordered by what each unblocks), and sends your answer into the
session that asked. It holds no data of its own: it runs the Teyla CLI. The design and the data
contract are in [`docs/APP.md`](../../docs/APP.md).

## Quick start

```sh
brew install xcodegen                 # once
# make sure `teyla` is on your PATH (see the repo README)
cd apps/mac && ./install.sh           # builds Release, copies Teyla.app to ~/Applications
open ~/Applications/Teyla.app
```

No CLI yet? Preview with the sample data (answers are simulated, nothing is delivered):

```sh
open -n --env TEYLA_STATE_FIXTURE="$PWD/../../tests/fixtures/state.json" ~/Applications/Teyla.app
```

Requires macOS 15 and Xcode. The app is ad-hoc signed for local use only.

## Where it reads data

- `teyla state --json` for the snapshot; `teyla answer <id> <text> --json`, `teyla asks snooze`
  and `teyla asks done` for actions. The binary is looked up in this order: `$TEYLA_BIN`,
  `~/.local/bin/teyla`, `/opt/homebrew/bin/teyla`, `/usr/local/bin/teyla`.
- It re-reads within 2 s of a change under `~/Library/Application Support/Claude/claude-code-sessions`,
  `~/.claude/projects` and `~/.codex/sessions` (missing ones are skipped), every 60 s, and when
  the window gets focus.
- `TEYLA_STATE_FIXTURE=<path>` reads a JSON file instead of running the CLI, and simulates
  answers, snoozes and "done" so nothing is delivered. Use `tests/fixtures/state.json`.

## Development

```sh
cd apps/mac && teyla load --wait --kind build && xcodegen generate
teyla load --wait --kind build && xcodebuild test -project Teyla.xcodeproj -scheme Teyla -destination 'platform=macOS'
```

The tests cover model decoding of the fixture and the binary lookup order; they compile the
`Teyla/Core` sources directly, so no app is launched. The generated `Teyla.xcodeproj` and
`build/` are not committed.

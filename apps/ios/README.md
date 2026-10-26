# Teyla for iPhone

The iPhone client of Teyla for Mac. It shows what the Mac shows: the morning brief, the questions
only you can answer, the tasks only you can do, what got done, what runs now, and where each product
stands. You answer by text or voice, correct a Codex session, or start a new task. It holds no data
of its own and talks to no server: it reads and writes a folder in iCloud Drive, and the Mac does the
work. The contract is in [`docs/APP.md`](../../docs/APP.md) ("The relay").

## Quick start

```sh
brew install xcodegen                                    # once
cd apps/ios && xcodegen generate && open Teyla.xcodeproj  # build and run on a simulator or your iPhone
# on the Mac: teyla relay on, then teyla relay pair
# in the app: choose the iCloud Drive "Teyla" folder, then scan the QR code (or paste the pairing string)
```

Preview without a Mac: launch with `TEYLA_STATE_FIXTURE=<repo>/tests/fixtures/state.v2.json` (an
environment variable or the launch argument `-TEYLA_STATE_FIXTURE <path>`). The app then skips onboarding
and signature checks, and sends nothing.

No Mac yet? Onboarding offers "See a sample": the whole app with made-up data from
`Teyla/Resources/sample-state.json`, a banner with a Pair button, and every send simulated
("Sample: nothing was sent"). Launch with `TEYLA_SAMPLE=1` (or `-TEYLA_SAMPLE YES`) to start there, and with
`-TEYLA_TAB portfolio`, `-TEYLA_OPEN <product>` or `-TEYLA_OLDER open` to open a tab, a product or the
"Older" fold. `Tools/screenshots.sh` uses these to make the store screenshots.

Requires iOS 18 and Xcode. Camera scanning needs a real device; on a simulator, paste the string.

## How it works

- **Reading.** `state.teyla` is read through `NSFileCoordinator`. If iCloud has not delivered it,
  the app asks for the download and shows "Syncing". The first line of the file is an HMAC-SHA256
  signature; the app checks it with the shared key before it decodes anything. A bad signature shows
  "Waiting for the Mac" and nothing else. It refreshes every 15 s while open and on pull-to-refresh, and
  warns when the Mac last wrote more than 10 minutes ago.
- **Writing.** Each action is one signed file, `outbox/<uuid>.json`, written atomically. The app shows
  "Waiting for the Mac" until the Mac writes `sent/<uuid>.json`, then shows the result and deletes that file.
- **The key** is the 32 bytes from the pairing string. It lives in the Keychain
  (`AfterFirstUnlockThisDeviceOnly`), never in the folder.
- **Voice** uses Apple Speech with `requiresOnDeviceRecognition = true`, in English, Spanish or Russian.
  A language without an on-device model does not start; there is no server fallback. The text fills the
  field and nothing is sent until you tap Send.
- **Shared code.** `Models.swift` and `Format.swift` come from `apps/mac/Teyla/Core`, so both apps decode
  the snapshot the same way. Everything else here is iPhone-only.

## Development

```sh
cd apps/ios && teyla load --wait --kind build && xcodegen generate
teyla load --wait --kind build && xcodebuild test -project Teyla.xcodeproj -scheme Teyla \
  -destination 'platform=iOS Simulator,name=iPhone 17'
```

The tests reproduce `tests/fixtures/relay-vector.json` (the state signature, the entry message and the
entry signature), reject entries with a line break in any field, check `state.teyla` parsing and a bad
signature, and decode `tests/fixtures/state.v2.json`.

## Release

The store listing, review notes and App Privacy answers are in [`docs/APP-STORE.md`](../../docs/APP-STORE.md).
Store readiness (POLICY 15): the icon is `Teyla/Assets.xcassets/AppIcon.appiconset` (one opaque 1024 px
image, made by `swift Tools/make_icon.swift`); `Teyla/PrivacyInfo.xcprivacy` declares no tracking, no collected
data and one required-reason API (UserDefaults, `CA92.1`); `ITSAppUsesNonExemptEncryption` is `NO`; the target is
iPhone only (`TARGETED_DEVICE_FAMILY` 1). The version is 0.32.0; the build number is `CURRENT_PROJECT_VERSION`
and `DEVELOPMENT_TEAM` is empty, so the release script passes both.

TestFlight waits on an App Store Connect record for `com.zaitsew.teyla`, which is made in the website
(Apps, +, New App); see `docs/APP-STORE.md` for the fields.

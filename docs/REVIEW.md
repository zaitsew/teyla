# Review by tapping and talking

Studio's capture side. A product links the `TeylaReview` package into its TestFlight Internal build. The owner opens review mode, taps the element that is wrong, says what is wrong, and the phone sends one signed capture to the Mac through the iCloud relay. The concept is in [STUDIO.md](STUDIO.md) (decision S3, section 5.1). The relay is described in [RELAY.md](RELAY.md).

This page is the contract between the phone and the Mac-side inbox: the folder layout, every field of `capture.json`, the signature and the status chain. The machine-readable form of the format is [templates/review/capture.schema.json](../templates/review/capture.schema.json).

## Adopt it in three steps

1. **Add the package.** In Xcode, File > Add Package Dependencies > Add Local, pick `packages/review-ios` (or the repo URL with that subdirectory). Link `TeylaReview` to the app target. Then switch review mode on for the configurations that go to testers, and only those (next paragraph). Optional: add a build phase that writes `git rev-parse --short HEAD` to an Info.plist key `TeylaCommit`.
2. **Mark screens and elements.** Each screen gets `.reviewScreen("trip.timeline")` on its root. Each element worth pointing at gets `.reviewAnchor("trip.timeline.addButton", role: .button, strings: ["timeline.add"])`. The id is `screen.element`. The source file and line are filled in by the compiler.
3. **Add the entry point.** Put `ReviewMenuButton()` (or `Button("Review") { TeylaReview.present() }`) in the debug menu. Optional: `TeylaReview.configure { $0.shake = true }` adds the shake shortcut. Then open `ReviewSettingsView()` once on the phone: paste the pairing string that `teyla relay pair` prints, and pick the `Teyla` folder in iCloud Drive.

**The switch is a runtime key, not a compile flag.** A Swift package is compiled with its own flags and never sees the app's `SWIFT_ACTIVE_COMPILATION_CONDITIONS`, so a flag set in the app cannot turn the package on or off. Review mode is on only when the app's Info.plist has the key `TeylaReviewEnabled` set to `YES`. Fill it from a build setting that exists in the Debug and TestFlight configurations and nowhere else:

```
// Info.plist
TeylaReviewEnabled = $(TEYLA_REVIEW_ENABLED)

// Debug.xcconfig and TestFlight.xcconfig (or the Debug and Release-TestFlight build settings)
TEYLA_REVIEW_ENABLED = YES

// App Store configuration: define nothing. The key expands to an empty string and review mode is off.
```

With the key absent, empty or anything but `YES`, `true` or `1`, `TeylaReview.isEnabled` is false and every entry point does nothing: `present()` returns, `ReviewMenuButton` and `ReviewSettingsView` draw nothing, `.reviewAnchor` and `.reviewScreen` record nothing, the shake shortcut stays off, and `pair(_:)` signs and copies nothing. The overlay also refuses to open when the build came from the App Store (`BuildChannel`), whatever the key says. The code is still linked in every configuration, but it has no active path in an App Store build. To strip it from the binary as well, resolve the package with the environment variable `TEYLA_REVIEW=0`, which removes the overlay code at compile time (the public API stays, as no-ops). A SwiftPM package trait would do the same from the app side, but traits need a newer tools version than the Xcode on the owner's Mac guarantees, so the runtime key is the supported switch.

If the product has a voice mode, tell the package: `TeylaReview.configure { $0.hostAudioInUse = { voice.isRunning }; $0.willBegin = { voice.pause() }; $0.didEnd = { voice.resume() } }`. The package records the audio session before review mode opens and puts it back when it closes. Speech recognition inside the overlay is off by default (`$0.speech = true` turns it on and needs the two microphone and speech Info.plist strings). The first dictation path is the microphone key on the iOS keyboard.

## What a capture is

One folder, named by the capture's id (a lowercase UUID), written first to the app's Documents (`Documents/TeylaReview/captures/<id>/`) and then copied to the relay:

```
iCloud Drive/Teyla/
  outbox/review/<id>/        written by the phone
    capture.png              the frozen screen, in pixels
    capture.json             the format below
    capture.sig              64 hex characters and a newline
  review-status/<id>.json    written by the Mac: Received, PR ready, Verified on device
```

The phone copies into a hidden `.tmp-<id>` folder in `outbox/review/` and renames it, so a folder without the dot is complete on the phone. iCloud still delivers its files one at a time. A reader must therefore take a capture only when all three files are present and the signature verifies, and must otherwise try again on the next pass. `capture.sig` arrives last on the phone but may arrive in any order on the Mac.

`outbox/review/` is a directory, so the relay's own sync, which reads `outbox/*.json`, never sees it.

## capture.json, version 1

Keys are snake_case. A key that is absent means the value is unknown; `null` is never written. Numbers in points are rounded to two decimals. A reader ignores keys it does not know and refuses a `v` other than 1.

| Key | Type | Meaning |
|---|---|---|
| `v` | integer, always `1` | Format version |
| `id` | string, lowercase UUID | The capture. The same id seen twice is one capture |
| `created` | string, `YYYY-MM-DDTHH:MM:SSZ`, UTC | When the owner pressed Send |
| `device` | string, `[A-Za-z0-9 ._-]{1,64}` | The device class (`iPhone`, `iPad`), never the name the owner gave the device |
| `app.bundle_id` | string | The product's bundle id |
| `app.name` | string, optional | Display name |
| `app.version`, `app.build` | strings | `CFBundleShortVersionString`, `CFBundleVersion` |
| `app.commit` | string, optional, 7 to 40 lowercase hex | From the Info.plist key `TeylaCommit`. Absent when the product does not set it |
| `app.configuration` | `debug`, `testflight` or `local` | How the build reached the phone. An App Store build never captures |
| `environment.os` | string | `iOS 19.1` |
| `environment.model` | string | Hardware identifier, `iPhone16,2` |
| `environment.locale` | string | `es_ES` |
| `environment.language` | string, optional | `es` |
| `environment.appearance` | `light` or `dark` | |
| `environment.dynamic_type` | `xSmall`, `small`, `medium`, `large`, `xLarge`, `xxLarge`, `xxxLarge`, `accessibilityMedium`, `accessibilityLarge`, `accessibilityXLarge`, `accessibilityXXLarge`, `accessibilityXXXLarge` or `unspecified` | The content size category |
| `environment.screen` | `{width, height, scale}`, numbers | The window in points and its scale. `width` and `height` are the coordinate space of every `x`, `y` and `bounds` below |
| `screen` | string, optional, `[A-Za-z0-9_.:#/-]{1,200}` | The route the product registered with `.reviewScreen` or `TeylaReview.screen`. Falls back to the tapped element's screen, then to the screen most anchors share |
| `tap` | object, optional | Absent when the owner did not tap |
| `tap.x`, `tap.y` | numbers | The tap in window points |
| `tap.accessibility_identifier`, `tap.accessibility_label` | strings, optional | What UIKit reports under the tap. SwiftUI hides most elements, so these are often absent |
| `element` | object, optional | The element the tap resolved to. Absent when nothing was under the tap |
| `element.id` | string | The anchor id, or the accessibility identifier |
| `element.matched_by` | `anchor` or `accessibility_identifier` | An anchor wins. The identifier is the fallback, and then only `id` is set |
| `element.screen`, `element.parent` | strings, optional | Screen id and the id of the anchor it sits in |
| `element.role` | `button`, `text`, `field`, `image`, `list`, `cell`, `toggle`, `container` or `other` | |
| `element.bounds` | `{x, y, width, height}` | Window points |
| `element.strings` | array of strings, at most 20 | String-catalog keys the element shows. Keys, never the text |
| `element.source` | `{file, line}` | `#fileID` and line of the `.reviewAnchor` call, for example `SampleApp/ListView.swift` and 88 |
| `anchors` | array of anchor objects, at most 200 | Every anchor on screen when the owner pressed Review, oldest registration first. An anchor has the keys `id`, `role`, `bounds` and optionally `screen`, `parent`, `strings`, `source`, as above |
| `comment.text` | string, 1 to 8,000 characters | What the owner typed or dictated |
| `comment.input` | `text` or `speech` | `speech` only when the package's own recognizer wrote it. Keyboard dictation is `text` |
| `comment.language` | string, optional | The device language when the comment was written |
| `screenshot.file` | `capture.png` | |
| `screenshot.width`, `screenshot.height` | integers | PNG size in pixels |
| `screenshot.scale` | number | Pixels per point |
| `screenshot.sha256` | 64 lowercase hex | Of the PNG, so `capture.json` names the picture it ships with |
| `microphone.host_audio_in_use` | boolean | Whether the product itself was using the microphone when review mode opened |
| `microphone.category` | string, optional | The AVAudioSession category at that moment |

An example. The schema accepts it, and `tests/test_review_capture.py` checks that it does:

```json
{
  "v": 1,
  "id": "3b9f1d2e-6a41-4c7e-9d0a-5e2f8b7c1a64",
  "created": "2026-10-30T21:14:05Z",
  "device": "iPhone",
  "app": {"bundle_id": "com.example.sampleapp", "name": "Sample App", "version": "1.4.0", "build": "212", "commit": "3f9c2ab", "configuration": "testflight"},
  "environment": {"os": "iOS 19.1", "model": "iPhone16,2", "locale": "es_ES", "language": "es", "appearance": "dark", "dynamic_type": "large", "screen": {"width": 390, "height": 844, "scale": 1}},
  "screen": "sample.list",
  "tap": {"x": 331.5, "y": 782, "accessibility_identifier": "addButton", "accessibility_label": "Add"},
  "element": {"id": "sample.list.addButton", "matched_by": "anchor", "screen": "sample.list", "parent": "sample.list.footer", "role": "button",
              "bounds": {"x": 300, "y": 752, "width": 60, "height": 60}, "strings": ["list.add"], "source": {"file": "SampleApp/ListView.swift", "line": 88}},
  "anchors": [
    {"id": "sample.list.footer", "screen": "sample.list", "role": "container", "bounds": {"x": 0, "y": 732, "width": 390, "height": 112}, "source": {"file": "SampleApp/ListView.swift", "line": 80}},
    {"id": "sample.list.addButton", "screen": "sample.list", "parent": "sample.list.footer", "role": "button", "bounds": {"x": 300, "y": 752, "width": 60, "height": 60}, "strings": ["list.add"], "source": {"file": "SampleApp/ListView.swift", "line": 88}}
  ],
  "comment": {"text": "The add button is too small and too close to the home indicator. Make it bigger and move it up.", "input": "text", "language": "en"},
  "screenshot": {"file": "capture.png", "width": 390, "height": 844, "scale": 1, "sha256": "0b9e7c0e5f8a1d3c2f6a4b7d9e1c3a5f7b9d1e3c5a7f9b1d3e5c7a9f1b3d5e7c"},
  "microphone": {"host_audio_in_use": false, "category": "AVAudioSessionCategoryPlayback"}
}
```

The files `tests/fixtures/review-capture/` hold a full capture (JSON, PNG, signature, a status answer) and `tests/fixtures/review-vector.json` holds the key and the expected signatures. The phone and the Mac each reproduce them in a test.

## How a tap becomes an element

1. The owner taps the frozen picture at a point in window coordinates.
2. The package hit-tests the anchors by bounds. The smallest anchor that contains the point wins; on a tie the later registration wins. The left and top edges are inside, the right and bottom edges are outside.
3. With no anchor under the tap, the package walks the UIKit views at that point, in the app's own views and not in the overlay that sits on top of them, and takes the first accessibility identifier it finds (`matched_by: accessibility_identifier`).
4. With neither, the capture has no `element`, and the comment is about the screen.

An anchor reads its bounds from a hidden view behind the content when the capture is taken, not when the view appears, so a scrolled list reports where its rows are now. Two views that share an id are both kept. The package does not read the full accessibility tree: a TestFlight process cannot, and the anchors are enough.

## Signing

A capture is signed with the relay key, the same 32 bytes that sign the relay's outbox actions ([APP.md](APP.md), "Signing"). The phone keeps the key in the Keychain, after the first unlock, on this device only. The pairing string is `teyla-pair:v1:<base64url key>`; `ReviewSettingsView` or `TeylaReview.pair(_:)` stores it.

`capture.sig` holds the lowercase hex HMAC-SHA256 of this message, UTF-8, lines joined with `\n`:

```
teyla-review-v1
<id>
<created>
<SHA-256 of the bytes of capture.json, lowercase hex>
<SHA-256 of the bytes of capture.png, lowercase hex>
```

The hashes make the JSON form irrelevant: the Mac hashes the bytes it received. The Mac refuses a capture with a missing or wrong signature, an `id` that is not a UUID, a folder name different from `id`, or a `created` more than 10 minutes in the future.

Without a key the phone still saves the capture in Documents and shows "Saved on phone", but it writes no `capture.sig` and does not copy to the relay: the Mac would refuse it. When the owner pairs, the package signs every capture saved before, from the bytes on disk, and copies them. It signs and copies again each time the app becomes active, after the owner picks the folder, and on each copy attempt, so a capture never stays unsigned once a key exists. A signer that cannot hold the key (a web overlay, another client) must add exactly the file `capture.sig` above, computed on a device that has the key, or send through the Mac's local endpoint instead.

## When saving fails

The owner's words are never dropped silently. Send saves on the phone before the overlay closes. If the write fails (a full disk, for example), the overlay stays open, shows the reason in red above the buttons ("Could not save the capture on this device. Your comment and the screenshot are still here. Free some space, then tap Retry."), keeps the comment, and turns Send into Retry. A retry reuses the same capture id, so it overwrites the failed attempt. Cancel is the only way out without a saved capture. A failed copy to the relay is not an error: the capture is safe in Documents and is copied on the next attempt.

## Status chain

```
Saved on phone  ->  Received  ->  PR ready  ->  Verified on device
saved_on_phone      received      pr_ready      verified_on_device
```

The package writes the first state, in `status.json` inside the capture's folder in Documents. When it accepts a state from the Mac, it writes that state to the same `status.json`, so the highest accepted state is kept on the phone and an older signed file, a missing file or an offline folder never moves the shown state backwards. The Mac writes the rest to `review-status/<id>.json` in the relay folder:

```json
{"v": 1, "id": "<id>", "status": "pr_ready", "updated": "2026-10-30T22:03:00Z", "pr": "https://github.com/example/sampleapp/pull/12", "sig": "<hex>"}
```

`status` is one of `received`, `pr_ready`, `verified_on_device`. `pr` is optional. `sig` is the lowercase hex HMAC-SHA256, with the same key, of these lines joined with `\n`: `teyla-review-status-v1`, `id`, `status`, `updated`, and `pr` (an empty line when there is none). The phone ignores a status file whose signature does not verify, whose `id` is not the file's name, or that is behind the state it already shows. The chain only moves forward, and the state it reached survives the file. `ReviewSettingsView` lists the captures with their status; `TeylaReview.status(of:)` returns it.

## Fallbacks

- **TestFlight feedback.** A tester who has no overlay (a family member, a build without the flag) sends a screenshot with a note through TestFlight's own share-feedback. The Mac reads it from App Store Connect, `GET /v1/apps/{id}/betaFeedbackScreenshotSubmissions`, with the API key in `~/.appstoreconnect/`, and files each one as a capture without element data: no `tap`, no `element`, no `anchors`, and a `comment` from the tester's note. The Mac writes these captures itself, in this format, with the fields it knows (the device model and OS from the feedback, the build from TestFlight). They never pass through the outbox, so they have no `capture.sig`.
- **Web overlay.** For web products, a short script included only when the page URL has `?review=1` posts the same capture shape to a local endpoint on the Mac, reached over a private tunnel. The element is found by `data-review-anchor` attributes instead of `.reviewAnchor`; the JSON keys are the ones above.

Both reach the same inbox as a phone capture.

## Privacy

Nothing leaves the owner's devices. The capture is written to the app's Documents and to the owner's own iCloud Drive folder; the package makes no network call and contains no analytics, no SDK and no third-party code. The picture holds whatever the screen showed, so review mode is for builds the owner tests, never for App Store builds (the package refuses to open in one). `device` is the device class, not the name the owner gave the phone. `element.strings` holds string keys, not the text of the screen. Speech recognition, when switched on, runs on the device only and the audio is not kept.

iCloud Drive encrypts the folder in transit and at rest, but Apple holds the keys unless the owner turns on Advanced Data Protection ([RELAY.md](RELAY.md), "Privacy"). The signature stops anyone who can write to the folder from sending a capture. It does not hide the screenshot.

## Files

| Path | Holds |
|---|---|
| `packages/review-ios/` | The Swift package: `Sources/TeylaReview/Core` (format, registry, hit test, signing, store, audio guard), `Sources/TeylaReview/UI` (overlay, presenter, shake, speech, settings) and `Tests/TeylaReviewTests` |
| `templates/review/capture.schema.json` | JSON Schema for `capture.json` |
| `tests/test_review_capture.py` | Validates the fixture capture, this page's example and the signing vector against the schema |

Run the package tests on the Mac, without a simulator, with `swift test --package-path packages/review-ios`.

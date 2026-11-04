# Review by tapping and talking

Studio's capture side. A product links the `TeylaReview` package into its TestFlight Internal build (iOS) or its Mac test build. The owner opens review mode, taps or clicks the element that is wrong, says what is wrong, and the device sends one signed capture to the Mac through the iCloud relay, or an unsigned one to the shared channel. The concept is in [STUDIO.md](STUDIO.md) (decision S3, section 5.1). The relay is described in [RELAY.md](RELAY.md).

This page is the contract between the phone and the Mac-side inbox: the folder layout, every field of `capture.json`, the signature and the status chain. The machine-readable form of the format is [templates/review/capture.schema.json](../templates/review/capture.schema.json).

## Adopt it in three steps

1. **Add the package.** In Xcode, File > Add Package Dependencies > Add Local, pick `packages/review-ios` (or the repo URL with that subdirectory). Link `TeylaReview` to the app target. Then switch review mode on for the configurations that go to testers, and only those (next paragraph). Optional: add a build phase that writes `git rev-parse --short HEAD` to an Info.plist key `TeylaCommit`.
2. **Mark screens and elements.** Each screen gets `.reviewScreen("trip.timeline")` on its root. Each element worth pointing at gets `.reviewAnchor("trip.timeline.addButton", role: .button, strings: ["timeline.add"])`. The id is `screen.element`. The source file and line are filled in by the compiler.
3. **Add the entry point.** Put `ReviewMenuButton()` (or `Button("Review") { TeylaReview.present() }`) in the debug menu. Optional: `TeylaReview.configure { $0.shake = true }` adds the shake shortcut. **On a Mac** there is no shake: add `.commands { ReviewCommands() }` to the scene and `ReviewMenuButton()` to a Settings pane ("On the Mac" below). Then open `ReviewSettingsView()` once on the phone: paste the pairing string that `teyla relay pair` prints, and pick the `Teyla` folder in iCloud Drive.

**The switch is a runtime key, and a store build is a separate archive.** A Swift package is compiled with its own flags and never sees the app's `SWIFT_ACTIVE_COMPILATION_CONDITIONS`, so a flag set in the app cannot turn the package on or off. Review mode is on only when the app's Info.plist has the key `TeylaReviewEnabled` set to `YES`, `true` or `1`. Fill it from a build setting:

```
// Info.plist
TeylaReviewEnabled = $(TEYLA_REVIEW_ENABLED)

// Debug.xcconfig and TestFlight.xcconfig (or the Debug and Release-TestFlight build settings)
TEYLA_REVIEW_ENABLED = YES

// Store archive: TEYLA_REVIEW_ENABLED = NO
```

With the key absent, empty or anything else, `TeylaReview.isEnabled` is false and every entry point does nothing: `present()` returns, `ReviewMenuButton` and `ReviewSettingsView` draw nothing, `.reviewAnchor` and `.reviewScreen` record nothing, the shake shortcut stays off, and `pair(_:)` signs and copies nothing.

**Why the key alone is not enough.** The same binary goes from TestFlight to the App Store, and App Review runs it in the sandbox exactly as TestFlight does. A build that carries review mode in TestFlight therefore carries it in review and, if it is promoted, in the store. So:

1. **A store archive is a separate archive of the same commit.** Build it with `TEYLA_REVIEW_ENABLED=NO` for the app and `TEYLA_REVIEW=0` in the environment that resolves the package. `TEYLA_REVIEW=0` removes the overlay code at compile time (the public API stays, as no-ops). A SwiftPM package trait would do the same from the app side, but traits need a newer tools version than the Xcode on the owner's Mac guarantees, so the environment variable is the supported switch.
2. **Check it before upload.** `teyla review store-check PATH` reads the finished artifact and proves it holds no entry point (next section). Upload only on exit 0.
3. **A TestFlight build is never promoted to the store.** Because the store archive is a second archive, the build the testers used and the build the store ships are two different builds of one commit. This costs one more archive per release. It is the only way to know the store binary has no review code.
4. **The install-channel check stays as a second lock.** The overlay also refuses to open when `BuildChannel` reads the install as an App Store build, whatever the key says. This lock is weaker than the archive, because it relies on what the platform reports about the install. It catches a mistake in step 1, it does not replace it.

If the product has a voice mode, tell the package: `TeylaReview.configure { $0.hostAudioInUse = { voice.isRunning }; $0.willBegin = { voice.pause() }; $0.didEnd = { voice.resume() } }`. The package records the audio session before review mode opens and puts it back when it closes. Speech recognition inside the overlay is off by default (`$0.speech = true` turns it on). The two Info.plist strings `NSSpeechRecognitionUsageDescription` and `NSMicrophoneUsageDescription` are needed on iOS **even when speech stays off**, because the package links Speech: Apple refused Iron U build 37 with ITMS-90683 by email after processing. The Mac build compiles that code out and needs neither. The first dictation path is the microphone key on the iOS keyboard.

## Checking an artifact before upload

`teyla review store-check PATH [--json]` proves that a production artifact holds no review entry point. It prints one line per check, never prints a key's value, and makes no network call. Exit 0: clean. Exit 1: it names what it found. Exit 2: the path cannot be read, or the type is unknown.

| Artifact | Checks |
|---|---|
| `.xcarchive` (every `Products/Applications/*.app`), `.app`, `.ipa`, `.pkg` (a Mac export) | Info.plist `TeylaReviewEnabled` is absent or off by the package's own rule (`parseEnabled`: `YES`, `true`, `1` are on); `TeylaReviewChannelKey` and `TeylaReviewChannelURL` are absent or empty; the main executable and the embedded frameworks do not contain the marker `TEYLA_REVIEW_IOS_ACTIVE`. A Mac bundle keeps its plist at `Contents/Info.plist` and its executable in `Contents/MacOS`; both layouts are read, for a `.app` and for an `.xcarchive`. A `.pkg` is expanded with `pkgutil --expand-full` into a temporary folder (macOS only; without `pkgutil` the check exits 2) and every `.app` in it is checked the same way |
| `.aab`, `.apk` | no `.dex` file contains the bytes `teyla/review/ReviewOverlay` |
| a folder (a web `dist`) | no file contains `TEYLA_REVIEW_WEB_ACTIVE` |

The Swift marker is a string in `Core/ReviewMarker.swift` that exists only under `#if TEYLA_REVIEW`. `TeylaReview.present()` stores it, so a release build keeps it through dead stripping whenever the product calls the entry point (a product does, from `ReviewMenuButton`). `tests/test_review_marker.py` builds a tiny executable that links the package, in release mode, and checks both directions: the marker is in the binary with the overlay compiled in, and absent with `TEYLA_REVIEW=0`. Measured on 2026-11-04, `swift build -c release` for macOS (dead stripping on): the probe holds the marker with the overlay compiled in and does not hold it with `TEYLA_REVIEW=0`, so stripping works. The probe links the macOS overlay; an iOS archive is checked by `store-check` the same way. The marker is longer than 15 bytes on purpose, because Swift keeps shorter strings inline and they leave nothing to find. A minified Android build (R8) may rename the overlay class, which would hide it from the dex check: an Android client must keep that class name (a `-keep` rule), or the check proves nothing.

## The Mac install channel

On iOS the receipt file tells TestFlight (`sandboxReceipt`) from the App Store (`receipt`). On macOS the receipt file is named `receipt` in TestFlight too, as far as we know, so the iOS rule would read a Mac TestFlight build as an App Store build and the form would never open. On macOS the package asks StoreKit instead: `AppTransaction.shared`, whose `environment` is `.xcode`, `.sandbox` or `.production`. `TeylaReview.configure` starts the request once when review mode is on, and the answer is cached. Until it arrives, and when it fails (no network, an unverified transaction), the channel reads as `.appStore`, so the overlay stays closed. The decision is the pure function `BuildChannel.detectMac(isDebug:environment:)`: debug builds are `debug`, `.sandbox` is `testflight`, `.xcode` is `local`, everything else is `appStore`. `BuildChannel.permitsReview` is the one rule that turns a channel into "the form may open": every channel but `appStore`. So `.xcode` and `.sandbox` open the form; `.production`, an error and no answer refuse it. The iOS path is unchanged.

**Not verified:** this has not run on a real Mac TestFlight build. The unit tests cover the decision; whether TestFlight really reports `.sandbox` on macOS is the thing to check on the first Mac TestFlight build.

## On the Mac

**Opening it.** A Mac has no shake. A product adds `.commands { ReviewCommands() }` to its scene, which puts "Report a problem…" in the Help menu with **Control-Option-Command-F**, and `ReviewMenuButton()` in a Settings pane for the same action (`ReviewStrings.reportProblem` is the wording). Both draw nothing until `BuildChannel` allows review mode ("The Mac install channel"), so a store build shows neither. The shortcut is `ReviewShortcut.mac`. No system shortcut uses Control, Option and Command together (checked in the machine's `com.apple.symbolichotkeys`: none does). The neighbours are Find (Command-F), Find and Replace (Option-Command-F) and Enter Full Screen (Control-Command-F); `ReviewShortcut.knownClashes` lists them and a test keeps ours away from them. A product that binds the same keys itself wins the clash, not the package.

**The picture.** The key window's content view is drawn with `NSView.cacheDisplay(in:to:)` into a bitmap at the screen's backing scale (`screenshot.scale` is 2 on a Retina display). The title bar is not in it. All coordinates in the capture are window points counted from the **top left of the content view**, as on iOS; the package converts from AppKit's bottom-left origin (`MacGeometry`). The PNG is composited on the window background colour, so a see-through sidebar leaves no holes.

**The limit.** `cacheDisplay` reads what the view hierarchy draws. Content that the GPU or a media layer draws (a MapKit map, a Metal or SceneKit view, a video) can come out blank or transparent. The package finds views of those kinds (`CAMetalLayer`, `MKMapView`, `MTKView`, `SCNView`, `SKView`, `AVPlayerView`), samples their pixels in the picture, and when one is blank (99.5% of the samples one colour or transparent) or the whole window is transparent, the comment step of the form shows `ReviewStrings.blankNote` beside the preview caption: "A map, video or 3D area can come out blank in this picture. If that is the problem, say so in your comment." The capture format has no key for it, so the owner reads it in the comment. `ScreenCaptureKit` would read the real pixels, but it asks the tester for a screen-recording permission, so it is not the default.

**Measured, 2026-11-04** (a throwaway SwiftUI app with an 800 x 300 point `Map`, macOS 27.2 on a Retina display): the map came out **blank**, a flat window-background grey, and the detector reported its frame as a blank area. Metal was not tried: no `CAMetalLayer` app was built, so a Metal view is covered by the same detector and not by a measurement.

**The form.** A window of its own opens beside the app, sized to the screen (at least 760 x 520 points, at most 90% of the visible area): the frozen picture on the left, the form on the right, 320 points wide. Click a spot, or drag around an area (a drag of 12 points or more); then Next, type, Send. Escape or Exit closes it, the red button closes it, and none of them sends anything. The app's own window is not touched. The form is text only: `comment.input` is `"text"`, `microphone` is `{"host_audio_in_use": <what the product says>}` with no `category`, and the Mac keyboard's dictation key types into the field like any other input. The first-send notice, the caption above Send, `requiresHealthConsent` and the refused states are the iOS code (`ReviewOverlay`, `ReviewSession`, `ChannelDelivery`), not a copy.

**The element.** The click is hit-tested against the anchors first. With no anchor under it, the package asks the window's accessibility tree at that point (`accessibilityHitTest`, then up the parents), and then the AppKit view chain, for the first identifier and label. SwiftUI keeps most elements in the accessibility tree and not in the view tree. An element that overlaps a `.reviewPrivate()` area, or whose frame is not known while a private area exists, lends neither identifier nor label.

**`.reviewPrivate()`.** The view's frame, plus 2 points, is painted black in the PNG before the form shows it, hashes it, saves it or sends it. A view that cannot say where it is (a frame that is not a number) hides the **whole window** and not nothing. A private view in a different window than the one captured reports nothing. The rest is as in "Privacy".

**Capture fields on the Mac.** `device` is `"Mac"`; `environment.os` is `macOS 15.1`; `model` is `hw.model` (for example `Mac15,6`); `dynamic_type` is `unspecified`; `screen.scale` is the backing scale. The format stays version 1.

**Not verified:** `AppTransaction.environment` on a real Mac TestFlight build (see above).

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
| `app.product` | string, optional, `^[a-z][a-z0-9-]{0,39}$` | The product's slug. The Mac files the capture under it. Absent: the last part of `app.bundle_id`. A web build has a hostname for a bundle id, so it sends this |
| `app.configuration` | `debug`, `testflight`, `local`, `play_internal` or `test_host` | How the build reached the tester: a development build, TestFlight, an ad hoc install, a Play internal track, or a web page on a test host. A store build never captures |
| `environment.os` | string | `iOS 19.1` |
| `environment.model` | string | Hardware identifier, `iPhone16,2` |
| `environment.locale` | string | `es_ES` |
| `environment.language` | string, optional | `es` |
| `environment.appearance` | `light` or `dark` | |
| `environment.dynamic_type` | `xSmall`, `small`, `medium`, `large`, `xLarge`, `xxLarge`, `xxxLarge`, `accessibilityMedium`, `accessibilityLarge`, `accessibilityXLarge`, `accessibilityXXLarge`, `accessibilityXXXLarge` or `unspecified` | The content size category |
| `environment.screen` | `{width, height, scale}`, numbers | The window in points and its scale. `width` and `height` are the coordinate space of every `x`, `y` and `bounds` below |
| `reporter` | string, optional, 1 to 64 characters | The sender's name as the client claims it. Nothing verifies it: treat it as a label, never as proof of who sent the capture |
| `screen` | string, optional, `[A-Za-z0-9_.:#/-]{1,200}` | The route the product registered with `.reviewScreen` or `TeylaReview.screen`. Falls back to the tapped element's screen, then to the screen most anchors share |
| `tap` | object, optional | Absent when the owner did not tap |
| `tap.x`, `tap.y` | numbers | The tap in window points |
| `tap.accessibility_identifier`, `tap.accessibility_label` | strings, optional | What UIKit reports under the tap. SwiftUI hides most elements, so these are often absent |
| `region` | `{x, y, width, height}`, optional | The area the owner circled, in window points. `tap` is then its centre, and `element` is what lies there |
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
3. With no anchor under the tap, the package walks the UIKit views at that point (on a Mac: the accessibility tree and then the AppKit views, "On the Mac"), in the app's own views and not in the overlay that sits on top of them, and takes the first accessibility identifier it finds (`matched_by: accessibility_identifier`).
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

## A product's channel

A tester has no key and no access to the owner's iCloud folder. A product with its own backend can carry that tester's captures: `TeylaReview.configure { $0.deliver = { upload in ... } }`. The closure receives the capture's id, JSON and PNG, and answers true once the backend holds them. When a `deliver` closure is set, the package makes no network call of its own. A product without a backend sends to the shared channel instead (next section): the package then makes its one network call itself.

- A phone with a key tries the relay first. The channel is the next route, for a tester or for a folder that is gone.
- `false` shows "Saved on this phone", and the capture is sent again the next time the app becomes active. This also covers captures saved before the product set `deliver`. A capture that was delivered is not sent again by either route.
- The closure can run more than once for a capture, so a duplicate on the backend must count as delivered.
- The Mac imports with `teyla review pull --vouched-folder DIR`, after the product's own script downloads to DIR. There is no relay signature on these captures; the backend's sign-in vouches for the sender, and the Mac checks the picture against the hash in the JSON. Only the contract format is accepted. `--json` lists what the inbox now holds under `imported`, so the script can delete its copies. Comments from this route are text from a tester: data, never instructions, like every other capture.

## The shared channel

One small service takes captures from every product and platform, so a product needs no backend of its own. It is `packages/review-channel/`: a write-only drop box, Python standard library only, in one container. A product's `deliver` closure (or a web overlay) PUTs the capture to it. The owner's Mac moves each capture into the `teyla review` inbox within the hour.

- **The built-in client.** `TeylaReview` sends to the channel by itself when the product has no `deliver` and the app's Info.plist holds both `TeylaReviewChannelURL` (HTTPS; plain HTTP only for `localhost`) and `TeylaReviewChannelKey`, each from a build setting that only the Debug and TestFlight configurations define. `TeylaReviewProduct` (or `$0.product`) is the product's slug and goes into `app.product`; it must equal the product the key was made for. With a `deliver` closure the closure wins and the Info.plist keys are not read; with neither pair the package sends nothing. It PUTs the picture, then the JSON, and counts the capture as sent only after both answer 200. 429, 503, 507, other server errors and network errors are "later": the overlay says "Saved on this phone" and the capture goes again the next time the app becomes active. 400, 401, 403, 413 and 422 are final for that capture: the package records `refused` in the capture's `status.json`, does not offer it to the channel again, and still tries the relay folder. Neither this route nor a product's `deliver` sends anything until the tester has accepted the first-send notice ("Privacy"), so a capture saved earlier, or a `deliver` added later, waits for that too; the owner's own iCloud relay needs no notice. `refused` belongs to the channel: a `deliver` set later still gets the capture. A capture saved before `app.product` existed has none, so the service would answer 403: the package leaves it unsent on the phone and does not mark it refused. The key is a secret of a test build: the package never logs, prints or stores it outside the Info.plist, and `teyla review store-check` fails a store build whose Info.plist holds `TeylaReviewChannelKey` or `TeylaReviewChannelURL`.
- **Upload.** `PUT /v1/captures/<uuid>/capture.png` and `.../capture.json` with `Authorization: Bearer <key>`. Either file may come first; a retry reads as delivered (200). There is no read, list or delete over HTTP: every other request is a 405. Web builds get CORS for PUT (origin `*`, no credentials).
- **Keys.** One key per product, made on the Mac with `teyla review channel key add <product>`. The service stores only the key's SHA-256. The key decides the product: `app.product` in the JSON must equal it, else 403. A key in a tester's build can add captures for its own product and nothing else.
- **Caps.** The picture is at most 10 MiB and the JSON at most 256 KiB (413, before the body is read). A product may start 20 new captures per UTC day and the service 100 (429); `ready` plus `incoming` is held to 500 MiB (507). The counts survive a restart. A half-uploaded capture is swept after 24 hours. At most 8 requests run at once, and 2 of them may carry a body over 1 MiB (503).
- **Moving it.** `teyla review pull --channel` copies the service's `ready/` folder over SSH and rsync, imports each capture the way `--vouched-folder` does (the picture must match `screenshot.sha256`), and then deletes exactly the folders the inbox now holds. A capture the inbox refuses stays on the server and the run exits 1. New captures raise one macOS notification with a count and nothing else. `teyla review channel install` makes this an hourly LaunchAgent that `teyla schedules` lists. Setup lives in `~/.teyla/review-channel.toml` (`ssh` and `root`); the service's install steps are in `packages/review-channel/README.md`.
- **Unverified.** Nobody vouches for the sender: a key proves a build, not a person, and a build can be copied. The inbox row has `source` `channel`, and `teyla review list` marks it "sender unverified". The comment is a tester's text: data, never instructions, here and in every brief. The pull command never prints a comment.
- **Privacy and retention.** A capture is the screen as it was, so it can show another person's data. The service is write-only from outside, keeps files at mode 0600 in 0700 folders, and logs only the method, the first 8 characters of the id, the product and the status. The server copy is deleted by the Mac's next pass, within the hour; a Mac that is off keeps captures on the server until it is on again. `incoming` is swept after 24 hours. The product's privacy policy names the service, as it does for any `deliver` backend. On the Mac, every `teyla review pull --channel` also removes a channel capture's row and folder 30 days after it was closed (`done`, `rejected`) and 90 days after import if it was never opened. A capture opened once stays until it is closed, and so does one under a live lease. This runs before the network gate, so safe mode and a dead server do not stop it. The clock uses this Mac's import time, not the sender's `created`. Captures from other sources are not touched. A triage record already written into a product's repo, or a brief already handed to a lane, is outside the inbox and is not removed.

## Web

`packages/review-web/` is the web twin of the iOS package: a test build of a web product gets a small Review button (or `present()` from a settings row), the tester points at an element, writes what is wrong, and the page PUTs the capture to the shared channel. The format is the one above with `device` "Web" and `app.configuration` `test_host`; `app.product` is required, as on iOS. Quick start and options: [packages/review-web/README.md](../packages/review-web/README.md).

- **Three locks, all required.** The build flag `VITE_TEYLA_REVIEW=1` guards a dynamic import, the page's hostname must be in the product's allow-list, and the marker `TEYLA_REVIEW_WEB_ACTIVE` and the channel key exist only in the lazily imported chunk. A build without the flag holds none of them, and `teyla review store-check <dist>` exits 0. `tests/test_review_web.py` builds a fixture both ways with Vite to prove it.
- **Picture.** `modern-screenshot` renders the DOM; on failure or a blank image, and only on a page with no private areas, the package falls back to `getDisplayMedia` (the tester sees the browser's prompt and picks the surface). That frame takes no masks. `data-review-private` and every password, card and one-time-code input are painted black in the PNG before it is shown, hashed or sent.
- **Pointing.** `data-review-anchor`, `data-review-screen`, `data-review-role`, `data-review-strings` and `data-review-source` are the twins of `.reviewAnchor` and `.reviewScreen`. Bounds are viewport CSS pixels.
- **The channel.** It already answers a browser (CORS preflight 204, origin `*`), so the service needs no change for web. The key is a build-time secret of a test build; a product serves the test build only on the hostnames it allow-lists.
- **Unsent captures** wait in IndexedDB (20 captures, 40 MiB, 14 days) and go again on load, `online` and when the tab is visible; the form keeps what the tester wrote if saving fails. Speech is off by default and no audio is ever sent.
- **Vendoring.** A product copies `packages/review-web/src` with `packages/review-web/scripts/teyla-review-sync-web`, next to its `scripts/teyla-review-sync` for the Swift package.

## Fallbacks

- **TestFlight feedback.** A tester who has no overlay (a family member, a build without the flag) sends a screenshot with a note through TestFlight's own share-feedback. The Mac reads it from App Store Connect, `GET /v1/apps/{id}/betaFeedbackScreenshotSubmissions`, with the API key in `~/.appstoreconnect/`, and files each one as a capture without element data: no `tap`, no `element`, no `anchors`, and a `comment` from the tester's note. The Mac writes these captures itself, in this format, with the fields it knows (the device model and OS from the feedback, the build from TestFlight). They never pass through the outbox, so they have no `capture.sig`.
- **Web overlay.** See "Web" above: it sends to the shared channel, and the Mac files the capture like any other.

Both reach the same inbox as a phone capture.

## Privacy

**What the owner sees.** Opening review mode shrinks the frozen app into a framed picture with a "Review mode" label, so it never reads as a hang. Step 1: tap a spot or circle an area, or go on about the whole screen. Step 2: write, or dictate when `speech` is on. The picture shrinks again for the keyboard. Step 3: the overlay says whether the capture was sent or only saved on this phone. A product translates the words with `$0.strings`.

**What the tester sees before a capture leaves the phone.**
- **First-send notice.** The first time a tester presses Send in a build that can reach a server (a `deliver` closure or the channel keys), a dialog says what is sent (the picture of the screen, the comment, the app's name and build, the device class and system, the element pointed at), who receives it (the developer, through a review server), why, and how long it is kept: the server copy is gone within the hour, the owner's Mac copy 30 days after the report is closed and 90 days if it is never opened. OK sends; Cancel sends and saves nothing. The answer is kept once per install. The words are `ReviewStrings.notice*`, English by default. The 30 and 90 day limits are the policy the notice states; this package does not delete anything on the Mac.
- **The picture.** The overlay shows the frozen screen throughout, and that picture is the exact PNG that is saved and sent. A caption above Send says so.
- **`.reviewPrivate()`.** A SwiftUI modifier that hides a view from every capture: its frame, as of the moment the picture is taken, plus a 2 pt margin, is painted black in the PNG before the overlay shows it and before it is hashed, saved or sent. Use it on other people's names and messages, and on health values. It registers like `.reviewAnchor`; it does nothing in a build with review mode off. A tap or circle that touches a masked area records no `element`, no `tap.accessibility_identifier` and no `tap.accessibility_label`; a view that overlaps a masked area lends no label or identifier to a nearby tap; and an anchor that overlaps one loses its `strings`. Anchor ids, roles, bounds and source lines stay: they are the developer's names and geometry. A comment is whatever the tester types.
- **Health consent.** `TeylaReview.configure { $0.requiresHealthConsent = true }` adds a checkbox (`strings.healthConsent`) that must be ticked before Send is enabled. It is asked for each capture.
- **The comment is never logged.** The comment is a tester's text; the package does not print or log it.

By default nothing leaves the device unless the Info.plist keys `TeylaReviewChannelURL` and `TeylaReviewChannelKey` are both set or a product sets `$0.deliver`. With neither, the capture is written to the app's Documents and to the owner's own iCloud Drive folder; the package makes no network call and contains no analytics, no SDK and no third-party code. With a `deliver` closure the capture goes through the product's own backend ("A product's channel" above), and that product's privacy policy covers it; with the Info.plist keys it goes to the shared channel ("The shared channel"), and the first-send notice above tells the tester where. `strings.deliveryNote` adds a line under the comment field. The picture holds whatever the screen showed, so review mode is for builds the owner tests, never for App Store builds (the package refuses to open in one). `device` is the device class, not the name the owner gave the phone. `element.strings` holds string keys, not the text of the screen. Speech recognition, when switched on, runs on the device only and the audio is not kept.

iCloud Drive encrypts the folder in transit and at rest, but Apple holds the keys unless the owner turns on Advanced Data Protection ([RELAY.md](RELAY.md), "Privacy"). The signature stops anyone who can write to the folder from sending a capture. It does not hide the screenshot.

## Files

| Path | Holds |
|---|---|
| `packages/review-ios/` | The Swift package: `Sources/TeylaReview/Core` (format, registry, hit test, signing, store, audio guard, and shared by both platforms: `ReviewSession`, `ReviewBitmap` for blackout and blank detection, `MacGeometry`, `ReviewShortcut`), `Sources/TeylaReview/UI` (overlay, shake, speech, settings; iOS: `ReviewPresenter`; macOS: `MacProbe`, `MacProbeViews`, `MacReviewPresenter`, `ReviewCommands`) and `Tests/TeylaReviewTests` |
| `packages/review-web/` | The web package: `src/` (gate, picture, masking, anchors, form, queue, channel client), `fixture/` and `tests/`, `scripts/teyla-review-sync-web` |
| `packages/review-channel/` | The shared channel service: `server.py`, Dockerfile, compose and Caddy fragments, install steps |
| `src/teyla/review_channel.py` | The Mac side: `pull --channel`, the key commands and the hourly agent |
| `templates/review/capture.schema.json` | JSON Schema for `capture.json` |
| `src/teyla/review_gate.py` | `teyla review store-check` |
| `tests/test_review_gate.py`, `tests/test_review_marker.py` | The store check on hand-made artifacts, and the Swift marker in real release builds |
| `tests/test_review_web.py` | The web package built both ways with Vite, the store check on each, and a real capture sent to the service |
| `tests/test_review_capture.py` | Validates the fixture capture, this page's example and the signing vector against the schema |
| `tests/test_review_channel_server.py`, `tests/test_review_channel.py` | The service against a real local port, and the Mac side with `ssh` and `rsync` replaced by local programs |

Run the package tests on the Mac, without a simulator, with `swift test --package-path packages/review-ios`, and the web package's with `npm ci && npm run check` in `packages/review-web`.

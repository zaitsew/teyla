# TeylaReview

A debug overlay for SwiftUI apps (iOS 17+ and macOS 14+): freeze the screen, tap or click an element, say what is wrong,
and send the capture to the Mac through the iCloud relay or the shared channel. Full guide, capture format and privacy:
[docs/REVIEW.md](../../docs/REVIEW.md).

Review mode is off until the app's Info.plist sets `TeylaReviewEnabled` to `YES` (from a build setting
defined only in Debug and TestFlight); an App Store configuration defines nothing and stays inert. A store build is a separate archive built with
`TEYLA_REVIEW=0`, checked with `teyla review store-check` before upload.

## Quick start

1. Add the package, call `TeylaReview.configure { $0.product = "my-product" }` at launch and put `ReviewMenuButton()` in a debug menu.
2. In Debug and TestFlight only, define these build settings and map them into the Info.plist:

   | Info.plist key | Build setting | Value |
   |---|---|---|
   | `TeylaReviewEnabled` | `TEYLA_REVIEW_ENABLED` | `YES` |
   | `TeylaReviewChannelURL` | `TEYLA_REVIEW_CHANNEL_URL` | the shared channel's HTTPS address |
   | `TeylaReviewChannelKey` | `TEYLA_REVIEW_CHANNEL_KEY` | the product's key from `teyla review channel key add <product>`; keep it in an uncommitted `.xcconfig` |
   | `TeylaReviewProduct` | `TEYLA_REVIEW_PRODUCT` | the product slug, if you do not set `$0.product` |

3. On iOS, add the two purpose strings to the app's Info.plist **even if the app never dictates**: `NSSpeechRecognitionUsageDescription`
   and `NSMicrophoneUsageDescription`. The package links the Speech framework for the optional dictation button, and Apple's
   upload check (ITMS-90683, found on Iron U build 37) refuses a build that references Speech without the first string. It
   refuses it by email, after processing, not in Xcode. The strings are shown only if the app turns `$0.speech` on. The Mac
   needs neither: the Speech and AVAudioSession code is compiled out on macOS, where the form is text only.
4. Build, open review mode, send a capture; it reaches `teyla review list` within the hour.
5. Before a store upload: `teyla review store-check <archive>` must exit 0. It fails when `TeylaReviewChannelKey` or `TeylaReviewChannelURL` holds a value.

Nothing leaves the device unless both channel keys are set or you set `$0.deliver`. The first Send shows a notice (what is sent, who
gets it, why, how long); the words are `ReviewStrings.notice*`. Mark views a tester must not have to send with `.reviewPrivate()`;
`$0.requiresHealthConsent = true` adds a checkbox before Send.

## Usage capture (test builds)

Records which screens and actions a tester uses, how long a named job takes, dead ends and repeat taps, so a design decision can be
measured before and after. Debug and TestFlight only: every call returns at once in an App Store build. No content, no titles, no free
text; only ids you declare. Details, wire and privacy: [docs/REVIEW.md](../../docs/REVIEW.md), "Usage capture".

```swift
TeylaUsage.configure(screens: ["trip.timeline", "settings.main"], actions: ["trip.addButton", "plan.save"], tasks: ["plan.day"])
TimelineView().usageScreen("trip.timeline")                      // or TeylaUsage.screen("trip.timeline")
TeylaUsage.action("plan.save", result: .done)                    // .done .cancelled .error .undone
TeylaUsage.task("plan.day", .start); TeylaUsage.task("plan.day", .success)
TeylaUsage.setVariant(decision: "nav", variant: "bottom-bar")    // from a Lab switch; every later event carries it
```

Put `.usageConsentNotice()` once on the root view: a tester who is not the owner sees Allow / Not now (`ReviewStrings.usage*`) before anything
leaves the device. The owner's device, paired with `teyla relay pair`, sends on its own. It sends through the shared channel (the same
Info.plist keys as captures), so with no channel keys nothing is sent. Also: `.usageTap("id")` counts taps on an element, and
`TeylaUsage.sheetDismissed(_:changed:)` reports a sheet closed with nothing changed. Read the result with `teyla usage <product>`.

## On a Mac

A Mac has no shake, so the way in is a menu item and a shortcut:

```swift
WindowGroup { ContentView() }
    .commands { ReviewCommands() }          // Help > "Report a problem…", Control-Option-Command-F

Settings { Form { ReviewMenuButton() } }    // the same action as a Settings row
```

Both draw nothing until review mode is allowed for this install. On the Mac that takes a moment after launch: the package
asks StoreKit (`AppTransaction.shared`) and allows the form for `.xcode` and `.sandbox` only. `.production`, an error or no
answer keeps it closed. The window is frozen with `NSView.cacheDisplay` at the screen's backing scale, and a window of its
own opens with the picture on the left and the form on the right: click a spot or drag around an area, type, press Send.
Escape, Exit or the red button closes it with nothing sent. The form is text only (`comment.input` is `"text"`); the Mac
keyboard's own dictation key (Fn twice) types into it.

`.reviewAnchor`, `.reviewScreen` and `.reviewPrivate()` work as on iOS. `.reviewPrivate()` paints the view black in the
saved and sent picture. `ReviewSettingsView` shows nothing on the Mac: the shared channel needs no pairing.
**Limit:** a map, a video or a Metal or 3D view can come out blank in `cacheDisplay`. The form then says so, in the
comment step, and the tester says so in the comment (docs/REVIEW.md, "On the Mac").

```
swift test --package-path packages/review-ios     # on the Mac, no simulator
```

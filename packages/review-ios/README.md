# TeylaReview

A debug overlay for SwiftUI apps (iOS 17+): freeze the screen, tap an element, say what is wrong, and
send the capture to the Mac through the iCloud relay. Full guide, capture format and privacy:
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

3. Build, open review mode, send a capture; it reaches `teyla review list` within the hour.
4. Before a store upload: `teyla review store-check <archive>` must exit 0. It fails when `TeylaReviewChannelKey` or `TeylaReviewChannelURL` holds a value.

Nothing leaves the device unless both channel keys are set or you set `$0.deliver`. The first Send shows a notice (what is sent, who
gets it, why, how long); the words are `ReviewStrings.notice*`. Mark views a tester must not have to send with `.reviewPrivate()`;
`$0.requiresHealthConsent = true` adds a checkbox before Send.

```
swift test --package-path packages/review-ios     # on the Mac, no simulator
```

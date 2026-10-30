# TeylaReview

A debug overlay for SwiftUI apps (iOS 17+): freeze the screen, tap an element, say what is wrong, and
send the capture to the Mac through the iCloud relay. Full guide, capture format and privacy:
[docs/REVIEW.md](../../docs/REVIEW.md).

Review mode is off until the app's Info.plist sets `TeylaReviewEnabled` to `YES` (from a build setting
defined only in Debug and TestFlight); an App Store configuration defines nothing and stays inert.

```
swift test --package-path packages/review-ios     # on the Mac, no simulator
```

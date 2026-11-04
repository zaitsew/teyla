# Feedback capture in {{name}}'s test builds

A tester points at what is wrong and writes why. The report reaches the owner's Mac with status `new`. Nothing starts work from a report without the owner. Store builds never contain this.

`teyla productize` checks this as R11. The full guide is `docs/REVIEW.md` in Teyla, and each package has a README.

## Wire it on the primary platform

| Platform | Package | Entry point | Store build |
|---|---|---|---|
| iOS | `packages/review-ios` | Shake, Settings row | Separate archive with `TEYLA_REVIEW_ENABLED=NO` and `TEYLA_REVIEW=0` |
| macOS | `packages/review-ios` | Help menu, Control-Option-Command-F | Same as iOS |
| Android | `packages/review-android` | Shake, Settings row; on TV the Settings row only | `release` links the no-op module |
| Web | `packages/review-web` | Small button on a test host | A build without `VITE_TEYLA_REVIEW=1` |

1. Vendor the package as its README says.
2. Make a channel key: `teyla review channel key add {{name}}`. It goes only into test builds.
3. iOS: the package references the Speech framework, so the Info.plist needs `NSSpeechRecognitionUsageDescription` and `NSMicrophoneUsageDescription`, even if the app itself never dictates. Without them Apple refuses the build, and says so only by email.
4. Mark anything that shows another person's data as private: `.reviewPrivate()` in SwiftUI, `Modifier.reviewPrivate()` in Compose, `data-review-private` on the web.
5. Run `teyla review privacy --product {{name}}`. Put the note in `strings.deliveryNote` and the paragraph in the privacy policy.
6. Before any store upload, run `teyla review store-check <artifact>`. It must exit 0.

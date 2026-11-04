# review-android

Feedback capture for an Android product's test builds. A tester shakes the phone (or opens a Settings row, the only way on a TV), points at the spot that is wrong, writes what is wrong, and the app sends one capture to the shared review channel. It is the Android twin of `packages/review-ios` and `packages/review-web`: the format is `capture.json` v1 ([docs/REVIEW.md](../../docs/REVIEW.md)) with `device` `Android`.

Two Gradle library modules have one public API:

| Module | Linked in | Holds |
|---|---|---|
| `teyla-review` | `debug` and `internal` | The overlay, the queue, the channel client and the class `teyla.review.ReviewOverlay` |
| `teyla-review-noop` | `release` | The same public API with empty bodies, no activity, no permission, no class named `ReviewOverlay` |

A store build never has the real module, so it has no entry point, no key and no code that can read the screen.

## Quick start

1. Vendor it: from the product's repo root, `~/repos/teyla/packages/review-android/scripts/teyla-review-sync-android`. It copies the two modules to `vendor/teyla-review-android`.
2. In `settings.gradle.kts`, include them where they sit:
   ```kotlin
   include(":teyla-review"); project(":teyla-review").projectDir = file("vendor/teyla-review-android/teyla-review")
   include(":teyla-review-noop"); project(":teyla-review-noop").projectDir = file("vendor/teyla-review-android/teyla-review-noop")
   ```
   The product's root build must already apply the Android Gradle plugin, the Kotlin Android plugin and the Compose compiler plugin (the toolchain the modules were built with: AGP 8.9.1, Kotlin 2.0.21, Compose BOM 2024.12.01, compileSdk 36, minSdk 26). The modules name no plugin version.
3. Add an `internal` build type next to `debug` and `release`, and link the modules by build type. The application id stays the same in all of them: no `applicationIdSuffix`.
   ```kotlin
   buildTypes {
       create("internal") { initWith(getByName("release")); matchingFallbacks += "release"; signingConfig = signingConfigs.getByName("upload") }
   }
   dependencies {
       debugImplementation(project(":teyla-review"))
       "internalImplementation"(project(":teyla-review"))
       releaseImplementation(project(":teyla-review-noop"))
   }
   ```
4. Ask the owner for a channel key: `teyla review channel key add <product>`. Define it as `BuildConfig` fields **only in `debug` and `internal`** (`buildConfigField("String", "TEYLA_REVIEW_KEY", ...)`, read from a Gradle property or a CI secret, never from a file in the repo). `fixture/build.gradle.kts` shows the pattern.
5. Call `TeylaReview.install` once from `Application.onCreate`, in a source set that only `debug` and `internal` compile (`fixture/src/review`), with a do-nothing twin in `src/release`:
   ```kotlin
   TeylaReview.install(app, ReviewConfig(product = "my-app", channelUrl = BuildConfig.TEYLA_REVIEW_URL, channelKey = BuildConfig.TEYLA_REVIEW_KEY))
   ```
   Because `release` links the no-op module, the same call is also safe in `src/main`; the split only keeps the key out of the release build.
6. Put `ReviewSettingsRow()` in a Settings screen. It draws nothing when review mode is off. On a TV it is the only entry point and it works with a D-pad.
7. Optional: `Modifier.reviewScreen("trip.timeline")` on each screen's root, `Modifier.reviewAnchor("trip.timeline.addButton", ReviewRole.Button, listOf("timeline.add"))` on elements worth pointing at, and `Modifier.reviewPrivate()` on anything that shows another person's data.
8. Build the production artifact and check it: `teyla review store-check app-release.aab` must exit 0. The `internal` artifact must report the marker, or the check proves nothing.

`ReviewConfig` also takes `deliver` (a closure, as on iOS: answer true once the product's backend holds the capture; the package then makes no network call of its own), `name`, `version`, `build`, `commit`, `configuration` (`debug`, `play_internal` or `local`; by default `debug` for a debuggable build and `play_internal` otherwise), `shake`, `requiresHealthConsent` and `strings`. Without a slug and a route (`deliver`, or both channel values) review mode stays off and logs one line without the key.

## The switch

| Lock | What it does |
|---|---|
| Linking | Only `debug` and `internal` have the real module. `release` has the no-op, so the overlay, the activity, the permissions and the key are not in the artifact. |
| Marker | The real module has the class `teyla.review.ReviewOverlay`. Its consumer ProGuard rule keeps the name under R8, so `teyla review store-check` finds it in an internal `.dex` and finds nothing in a release one. `tests/test_review_android.py` checks that the no-op has no such class and the two APIs match; `tests/test_review_android_build.py` builds a fixture both ways. |
| Key | The channel key is a `BuildConfig` field of the two review build types, so a release build has no value to leak. |

There is no install-channel check as on iOS: Play internal testing and production install through the same store app, so the build you link is the only lock. A test build is therefore never promoted to production: build the production artifact separately, with `release`.

## What a capture holds

`capture.png` is the activity window, copied with `PixelCopy` at the screen's pixel size (halved once if the PNG is over 9.5 MB, since the channel refuses 10 MiB). `capture.json` carries the fields of the iOS capture: `app` (package name as `bundle_id`, label, `versionName`, `versionCode`, `commit` if the product passes one, `product`, `configuration`), `environment` (`Android 15`, `Build.MODEL`, locale, light or dark, window size in dp and the screen density), `screen`, `tap` or `region`, `element` and `anchors` (from the modifiers, bounds in dp from the window's top left), `comment` and `screenshot` (pixel size, pixels per dp, sha256). `microphone.host_audio_in_use` is `false`.

**What it cannot see.** `PixelCopy` of the activity window shows that window only: a dialog, a popup or a system sheet is a window of its own and is not in the picture. A map, video or `SurfaceView` can come out blank; the form says so beside the preview when the picture is one colour. A tap that lands on something with no anchor records the point and no element: Compose has no accessibility identifier to fall back on, so name the elements that matter.

## Privacy

The picture shows the screen as the tester saw it, so it can show another person's data. `Modifier.reviewPrivate()` registers the composable's bounds; at capture time each one, plus 2 dp, is painted black in the PNG **before** the form shows it and before it is hashed, saved or sent. A tap or area that touches a masked area records no `element`, and an anchor that overlaps one loses its `strings`. A composable that cannot report its bounds (they are not a number, or reading them fails) hides the **whole window**.

**Password fields are not detected.** Compose has no password type that the library can see from outside, so a `PasswordVisualTransformation` field, a card field or a one-time-code field is **not** masked unless the product marks it with `reviewPrivate()`. Mark every one of them. (A classic `View` password field is not covered either; this package is for Compose screens.)

**`FLAG_SECURE`.** A window that sets `FLAG_SECURE` is protected on purpose, and a copy of it comes out black. The package does not send that picture as if it were the screen: it checks the flag first, shows `strings.secureScreen` ("This screen is protected from screenshots by the app, so review mode cannot take a picture of it. Nothing was sent.") and opens nothing. A product that wants feedback on such a screen sets the flag off in its `internal` build.

Nothing leaves the device until the tester has accepted the first-send notice (what is sent, who gets it, why, how long it is kept), once per install. The comment is never logged, and the key is never logged or stored outside the build. The package contains no analytics, no SDK and no third-party code beyond AndroidX and Compose. The only network call is the PUT to the channel (picture, then JSON, `Authorization: Bearer <key>`, no cookies, no redirects), or none when the product supplies `deliver`.

**`requiresHealthConsent`** adds a checkbox that must be ticked before Send, for each capture.

**Dictation is not part of this package.** The form is a normal text field, so the keyboard's own dictation key works and is recorded as `comment.input: "text"`. A speech recogniser would need `RECORD_AUDIO`, and a library manifest that asks for the microphone would put it into every product that links the module; the manifest has only `INTERNET` and `ACCESS_NETWORK_STATE`.

## When it cannot send

Captures wait as files in the app's private storage (`files/teyla-review/queue`): at most 20 captures, 40 MiB and 14 days. They go again at app start and when the network returns. A capture is deleted only after the channel answered 200 for both files. 400, 401, 403, 413 and 422 are final for that capture (it stays on the device as `refused` and is not offered again); 429, 5xx and network errors are "later". If the queue cannot save a capture the form stays open with a Retry button, so the tester's words are not lost.

## Entry points and the TV

Shake: three jolts above 2.7 g within a second, from `SensorManager`, while an activity is resumed. Settings row: `ReviewSettingsRow()`. When `UiModeManager.currentModeType` is `UI_MODE_TYPE_TELEVISION` there is no shake, and the form works with a D-pad: the arrow keys move a cross over the picture, OK chooses the spot, and at the picture's edge an arrow key leaves it for the buttons. There is no area drag on a TV; "About the whole screen" is always there.

## Not verified here

No emulator or device run has happened. The JVM tests cover the format, masking on a pixel buffer, the queue, the channel answers and the TV decision; the build test proves the marker survives R8 in the `internal` variant and is absent from `release`. `PixelCopy`, the shake sensor, the Compose form with touch and with a D-pad, the notice, and a PUT to a live channel are written but have not run on Android.

## Layout and checks

```
teyla-review/        the real module (src/main/kotlin/teyla/review, consumer-rules.pro, src/test)
teyla-review-noop/   the same public API, empty
fixture/             a tiny app that links the real module in debug and internal, the no-op in release
scripts/             teyla-review-sync-android
```

`./gradlew :teyla-review:testDebugUnitTest` runs the JVM tests; `./check.sh` at the repo root runs them when a JDK and the Android SDK are present and prints a skip line when not. `TEYLA_REVIEW_ANDROID_BUILD=1 pytest tests/test_review_android_build.py` builds the fixture and runs the store check on it. Needs about 2 GB of disk and the Gradle cache; run `teyla load --wait --kind build` first.

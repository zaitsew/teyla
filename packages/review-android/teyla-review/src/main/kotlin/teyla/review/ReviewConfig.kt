package teyla.review

/** What `deliver` receives: one capture, as the shared channel would. `json` is `capture.json`, `png` is `capture.png`. */
class ReviewUpload(val id: String, val json: String, val png: ByteArray)

/**
 * Review mode's settings, passed to [TeylaReview.install] once.
 *
 * Where a capture goes: `deliver` when the product sets it (the package then makes no network call of its
 * own), otherwise the shared channel at `channelUrl` with the write-only `channelKey`. With neither, review
 * mode stays off, because a capture would have nowhere to go.
 *
 * The key is a secret of a test build: pass it from `BuildConfig` fields that only the `debug` and `internal`
 * build types define, never from a file in the repo.
 */
class ReviewConfig(
    /** The product's slug, `^[a-z][a-z0-9-]{0,39}$`. The channel key is bound to it. */
    val product: String,
    val channelUrl: String? = null,
    val channelKey: String? = null,
    /** Answer true once the product's backend holds the capture. It can run more than once for one capture. */
    val deliver: ((ReviewUpload) -> Boolean)? = null,
    /** Display name. Default: the app's label. */
    val name: String? = null,
    /** Default: the package's `versionName`. */
    val version: String? = null,
    /** Default: the package's `versionCode`. */
    val build: String? = null,
    /** 7 to 40 lowercase hex characters. Default: absent. */
    val commit: String? = null,
    /** `debug`, `play_internal` or `local`. Default: `debug` for a debuggable build, else `play_internal`. */
    val configuration: String? = null,
    /** Shake the device to open review mode. Never on a TV. */
    val shake: Boolean = true,
    /** Adds a checkbox that must be ticked before Send, for each capture. */
    val requiresHealthConsent: Boolean = false,
    val strings: ReviewStrings = ReviewStrings(),
)

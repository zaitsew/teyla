package teyla.review

import android.app.Activity
import android.app.Application
import android.util.Log

/**
 * Feedback capture for a product's test builds. Install it once, from `Application.onCreate`, in the `debug`
 * and `internal` build types only; the `release` build type links the no-op module with the same API.
 */
object TeylaReview {
    @Volatile private var enabled = false

    /** True after a successful [install]. False means every entry point does nothing. */
    val isEnabled: Boolean get() = enabled

    /**
     * Starts review mode: the shake shortcut (not on a TV), the retry of unsent captures at start and when the
     * network returns. Without a product slug and a place to send to (`deliver`, or `channelUrl` and
     * `channelKey`) it logs one line without the key and review mode stays off.
     */
    fun install(application: Application, config: ReviewConfig) {
        if (!isUsable(config)) {
            Log.w("TeylaReview", "needs a product slug and a deliver closure or a channel URL and key; review mode stays off")
            return
        }
        synchronized(this) {
            if (enabled) return
            ReviewOverlay.install(application, config)
            enabled = true
        }
    }

    /** Opens review mode on [activity]'s window: the Settings row calls this. */
    fun present(activity: Activity) {
        if (enabled) ReviewOverlay.present(activity)
    }

    /** Names the current screen when `reviewScreen` cannot; null clears it. */
    fun screen(id: String?) {
        ReviewState.currentScreen = id?.takeIf { Regex("^[A-Za-z0-9_.:#/-]{1,200}$").matches(it) }
    }

    /** Sends what waits in the queue now. It also runs at start and when the network returns. */
    fun flush() {
        if (enabled) ReviewOverlay.flush()
    }
}

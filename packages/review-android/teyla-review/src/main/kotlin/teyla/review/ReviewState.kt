package teyla.review

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper

/** Process-wide state of review mode. Nothing here is written to disk. */
internal object ReviewState {
    val registry = Registry()

    @Volatile var currentScreen: String? = null
    @Volatile var strings: ReviewStrings = ReviewStrings()
}

internal fun activityOf(context: Context): Activity? {
    var c: Context? = context
    while (c is ContextWrapper) {
        if (c is Activity) return c
        c = c.baseContext
    }
    return null
}

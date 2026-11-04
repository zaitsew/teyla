package teyla.review

import android.app.Activity
import android.app.Application

/** The release twin: every call does nothing, and nothing is registered, stored or sent. */
object TeylaReview {
    val isEnabled: Boolean = false

    fun install(application: Application, config: ReviewConfig) {}

    fun present(activity: Activity) {}

    fun screen(id: String?) {}

    fun flush() {}
}

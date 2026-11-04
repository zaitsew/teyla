package teyla.review.fixture

import android.app.Application

/** The release twin: no key, no address. The no-op module would ignore them anyway. */
object ReviewSetup {
    fun install(app: Application) {}
}

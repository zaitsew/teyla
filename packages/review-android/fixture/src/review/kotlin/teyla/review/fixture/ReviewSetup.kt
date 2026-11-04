package teyla.review.fixture

import android.app.Application
import teyla.review.ReviewConfig
import teyla.review.TeylaReview

/** Compiled into `debug` and `internal` only. The key comes from BuildConfig fields that `release` does not define. */
object ReviewSetup {
    fun install(app: Application) {
        TeylaReview.install(
            app,
            ReviewConfig(product = "fixture", channelUrl = BuildConfig.TEYLA_REVIEW_URL, channelKey = BuildConfig.TEYLA_REVIEW_KEY),
        )
    }
}

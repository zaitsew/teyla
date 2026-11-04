package teyla.review.fixture

import android.app.Application

class FixtureApp : Application() {
    override fun onCreate() {
        super.onCreate()
        ReviewSetup.install(this)
    }
}

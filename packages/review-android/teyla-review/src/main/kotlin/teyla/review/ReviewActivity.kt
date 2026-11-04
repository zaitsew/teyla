package teyla.review

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme

/** The one screen of review mode. It shows the frozen picture and the form; the app behind it is untouched. */
internal class ReviewActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val session = ReviewOverlay.session
        if (session == null) { // the process was restarted behind the form: there is no picture to show
            finish()
            return
        }
        setContent {
            MaterialTheme(colorScheme = if (isSystemInDarkTheme()) darkColorScheme() else lightColorScheme()) {
                Surface(color = MaterialTheme.colorScheme.background) {
                    ReviewFlow(session, ReviewState.strings, onClose = { finish() })
                }
            }
        }
    }

    override fun onDestroy() {
        if (isFinishing) ReviewOverlay.closeSession()
        super.onDestroy()
    }
}

package teyla.review.fixture

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import teyla.review.ReviewRole
import teyla.review.ReviewSettingsRow
import teyla.review.reviewAnchor
import teyla.review.reviewPrivate
import teyla.review.reviewScreen

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            Column(Modifier.reviewScreen("fixture.home").padding(16.dp)) {
                Text("Fixture", Modifier.reviewAnchor("fixture.home.title", ReviewRole.Text))
                Text("secret value", Modifier.reviewPrivate())
                ReviewSettingsRow()
            }
        }
    }
}

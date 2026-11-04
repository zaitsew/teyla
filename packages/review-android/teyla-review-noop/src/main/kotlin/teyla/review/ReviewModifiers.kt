package teyla.review

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

/** What kind of element an anchor is. The words are the capture format's. */
enum class ReviewRole(val wire: String) {
    Button("button"),
    Text("text"),
    Field("field"),
    Image("image"),
    List("list"),
    Cell("cell"),
    Toggle("toggle"),
    Container("container"),
    Other("other"),
}

fun Modifier.reviewPrivate(): Modifier = this

fun Modifier.reviewAnchor(id: String, role: ReviewRole = ReviewRole.Other, strings: List<String> = emptyList()): Modifier = this

fun Modifier.reviewScreen(id: String): Modifier = this

@Composable
fun ReviewSettingsRow(modifier: Modifier = Modifier) {
}

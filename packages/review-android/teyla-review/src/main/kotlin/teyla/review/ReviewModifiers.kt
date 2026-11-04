package teyla.review

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.node.GlobalPositionAwareModifierNode
import androidx.compose.ui.node.ModifierNodeElement
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

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

/**
 * Hides this composable from every capture: its bounds, as of the moment the picture is taken, plus a 2 dp
 * margin, are painted black in the PNG before the form shows it, hashes it, saves it or sends it. Use it on
 * other people's names and messages, and on health values. Compose cannot tell a password field from any
 * other text field, so a password field needs this modifier too: nothing is masked automatically.
 */
fun Modifier.reviewPrivate(): Modifier = this then BoundsElement(Kind.Private, "", ReviewRole.Other, emptyList())

/** Names an element the tester may point at. The id is `screen.element`, for example `trip.timeline.addButton`. */
fun Modifier.reviewAnchor(id: String, role: ReviewRole = ReviewRole.Other, strings: List<String> = emptyList()): Modifier =
    this then BoundsElement(Kind.Anchor, id, role, strings)

/** Marks the root of a screen. Anchors inside it carry its id as their `screen`. */
fun Modifier.reviewScreen(id: String): Modifier = this then BoundsElement(Kind.Screen, id, ReviewRole.Container, emptyList())

/** A Settings row that opens review mode. It is the only way in on a TV, and it works with a D-pad. It draws nothing when review mode is off. */
@Composable
fun ReviewSettingsRow(modifier: Modifier = Modifier) {
    if (!TeylaReview.isEnabled) return
    val context = LocalContext.current
    val label = ReviewState.strings.button
    Row(
        modifier = modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .clickable { activityOf(context)?.let { TeylaReview.present(it) } }
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodyLarge)
    }
}

private data class BoundsElement(val kind: Kind, val id: String, val role: ReviewRole, val strings: List<String>) :
    ModifierNodeElement<BoundsNode>() {
    override fun create() = BoundsNode(kind, id, role, strings)

    override fun update(node: BoundsNode) { node.change(kind, id, role, strings) }
}

private class BoundsNode(var kind: Kind, var id: String, var role: ReviewRole, var strings: List<String>) :
    androidx.compose.ui.Modifier.Node(), GlobalPositionAwareModifierNode {
    private var coordinates: LayoutCoordinates? = null
    private var key: Long? = null

    override fun onAttach() { register() }

    override fun onDetach() { unregister(); coordinates = null }

    override fun onGloballyPositioned(coordinates: LayoutCoordinates) { this.coordinates = coordinates }

    fun change(kind: Kind, id: String, role: ReviewRole, strings: List<String>) {
        this.kind = kind; this.id = id; this.role = role; this.strings = strings
        unregister(); register()
    }

    private fun register() {
        key = ReviewState.registry.add(kind, id, role, strings) {
            // Read now, not when the node was last placed: a scrolled list reports where its rows are.
            coordinates?.takeIf { it.isAttached }?.boundsInWindow()?.let { Frame(it.left.toDouble(), it.top.toDouble(), it.width.toDouble(), it.height.toDouble()) }
        }
    }

    private fun unregister() { key?.let { ReviewState.registry.remove(it) }; key = null }
}

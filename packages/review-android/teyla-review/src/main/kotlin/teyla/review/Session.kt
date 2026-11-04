package teyla.review

import java.time.Instant

/** What one opening of review mode froze. Both the privacy rules and the field choices live in [recordFor],
 *  so they are written once and tested. Every frame and anchor is in dp, from the top left of the window. */
internal class Frozen(
    val id: String,
    val app: AppFacts,
    val environment: EnvironmentFacts,
    /** The screen the product registered with `TeylaReview.screen`, if any. */
    val currentScreen: String?,
    /** Already free of the `strings` that overlap a private frame. */
    val anchors: List<Anchor>,
    /** The rectangles painted black in the picture, grown by the margin. */
    val frames: List<Frame>,
    val sha256: String,
    val pixelWidth: Int,
    val pixelHeight: Int,
    val pixelScale: Double,
)

internal class Draft(val tap: Point?, val region: Frame?, val text: String, val input: String = "text")

internal fun recordFor(f: Frozen, d: Draft, now: Instant = Instant.now()): BuildInput {
    // A tap or area that touches a private area records no element: the picture hides it, so the JSON must not name it.
    val priv = touchesPrivate(d.tap, d.region, f.frames)
    val point = d.tap ?: d.region?.let { Point(it.x + it.width / 2, it.y + it.height / 2) }
    val hit = if (!priv && point != null) hitTest(f.anchors, point.x, point.y) else null
    return BuildInput(
        id = f.id, now = now, app = f.app, environment = f.environment,
        screen = screenFor(f.currentScreen, hit, f.anchors),
        tap = point, region = d.region, element = hit, anchors = f.anchors,
        text = d.text.trim(), input = d.input, sha256 = f.sha256,
        pixelWidth = f.pixelWidth, pixelHeight = f.pixelHeight, pixelScale = f.pixelScale,
    )
}

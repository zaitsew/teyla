package teyla.review

/** Margin painted around a private area, in dp (iOS: 2 pt). */
internal const val PRIVATE_MARGIN = 2.0

internal fun rectsIntersect(a: Frame, b: Frame): Boolean =
    a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height

/** The left and top edges are inside, the right and bottom edges are outside. */
internal fun inFrame(r: Frame, x: Double, y: Double): Boolean =
    x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height

/** The smallest anchor that contains the point wins; on a tie the later registration wins. */
internal fun hitTest(anchors: List<Anchor>, x: Double, y: Double): Anchor? {
    var best: Anchor? = null
    var bestArea = Double.POSITIVE_INFINITY
    for (a in anchors) {
        if (!inFrame(a.bounds, x, y)) continue
        if (a.bounds.area <= bestArea) {
            best = a
            bestArea = a.bounds.area
        }
    }
    return best
}

/** The screen the capture is about: the one the product set, else the hit anchor's, else the one most anchors share. */
internal fun screenFor(current: String?, hit: Anchor?, anchors: List<Anchor>): String? {
    if (!current.isNullOrEmpty()) return current
    if (!hit?.screen.isNullOrEmpty()) return hit?.screen
    val counts = LinkedHashMap<String, Int>()
    for (a in anchors) a.screen?.takeIf { it.isNotEmpty() }?.let { counts[it] = (counts[it] ?: 0) + 1 }
    var best: String? = null
    var n = 0
    for ((s, c) in counts) if (c > n) { best = s; n = c }
    return best
}

/** What a tap or area may say about the element under it. A tap in a private area keeps no element: the
 *  picture hides it, so the JSON must not name it. */
internal fun touchesPrivate(point: Point?, region: Frame?, frames: List<Frame>): Boolean =
    frames.any { f ->
        (point != null && inFrame(f, point.x, point.y)) || (region != null && rectsIntersect(f, region))
    }

/** An anchor that overlaps a private area loses its `strings`: the keys of the text it shows. Ids, roles and bounds stay. */
internal fun redactAnchors(anchors: List<Anchor>, frames: List<Frame>): List<Anchor> =
    anchors.map { a -> if (a.strings.isNotEmpty() && frames.any { rectsIntersect(it, a.bounds) }) a.copy(strings = emptyList()) else a }

/** A private area grown by the margin. A frame that is not a finite number stays as it is: the painter hides the whole picture for it. */
internal fun grown(f: Frame): Frame =
    if (!f.isFinite) f else Frame(f.x - PRIVATE_MARGIN, f.y - PRIVATE_MARGIN, f.width + 2 * PRIVATE_MARGIN, f.height + 2 * PRIVATE_MARGIN)

internal fun intersectsWindow(r: Frame, w: Double, h: Double): Boolean =
    r.x < w && r.y < h && r.x + r.width > 0 && r.y + r.height > 0

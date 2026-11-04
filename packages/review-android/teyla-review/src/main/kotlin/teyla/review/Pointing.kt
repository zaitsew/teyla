package teyla.review

/** How the picture on the form maps to the window, and how a D-pad moves the cross. All pure, so they run on the JVM. */

/** Where the picture sits inside its box when it is scaled to fit. */
internal class Fit(val offsetX: Double, val offsetY: Double, val width: Double, val height: Double)

internal fun fitInside(boxW: Double, boxH: Double, aspect: Double): Fit {
    if (boxW <= 0 || boxH <= 0 || aspect <= 0) return Fit(0.0, 0.0, 0.0, 0.0)
    val w = minOf(boxW, boxH * aspect)
    val h = w / aspect
    return Fit((boxW - w) / 2, (boxH - h) / 2, w, h)
}

/** A touch in the box, as a point in window dp; null when it falls outside the picture. */
internal fun toWindow(fit: Fit, px: Double, py: Double, windowWidthDp: Double, windowHeightDp: Double): Point? {
    if (fit.width <= 0 || fit.height <= 0) return null
    val fx = (px - fit.offsetX) / fit.width
    val fy = (py - fit.offsetY) / fit.height
    if (fx < 0 || fx > 1 || fy < 0 || fy > 1) return null
    return Point(fx * windowWidthDp, fy * windowHeightDp)
}

/** A drag shorter than this is a tap, not an area (dp, as on the other platforms). */
internal const val MIN_AREA = 12.0

/** The area a drag drew, or null when it was shorter than [MIN_AREA] in both directions. */
internal fun areaOf(a: Point, b: Point): Frame? {
    val w = Math.abs(a.x - b.x)
    val h = Math.abs(a.y - b.y)
    if (w < MIN_AREA && h < MIN_AREA) return null
    return Frame(minOf(a.x, b.x), minOf(a.y, b.y), w, h)
}

internal enum class Dir { Left, Right, Up, Down }

/** The cross after one arrow key. `moved` is false when it already sits on that edge: the key is then left to the
 *  system, so focus can leave the picture for the buttons. */
internal class Cursor(val at: Point, val moved: Boolean)

internal fun moveCursor(at: Point, dir: Dir, step: Double, windowWidthDp: Double, windowHeightDp: Double): Cursor {
    val dx = when (dir) { Dir.Left -> -step; Dir.Right -> step; else -> 0.0 }
    val dy = when (dir) { Dir.Up -> -step; Dir.Down -> step; else -> 0.0 }
    val nx = (at.x + dx).coerceIn(0.0, windowWidthDp)
    val ny = (at.y + dy).coerceIn(0.0, windowHeightDp)
    return Cursor(Point(nx, ny), nx != at.x || ny != at.y)
}

/** Holding a key moves the cross faster: 12 dp at first, up to 6 times that after 25 repeats. */
internal fun stepFor(repeatCount: Int): Double = 12.0 * (1 + minOf(repeatCount, 25) / 5.0)

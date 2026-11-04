package teyla.review

import java.security.MessageDigest

/** Pixel work that needs no Android class, so the tests run on the JVM: painting private areas black and
 *  finding a picture that came out empty. ARGB, 8 bits per channel, rows from the top. */
internal class PixelBuffer(val width: Int, val height: Int, val argb: IntArray) {
    init { require(argb.size == width * height) { "pixel count does not match the size" } }
}

internal const val BLACK = 0xFF000000.toInt()

/** At or above this share of one colour a picture counts as blank (iOS and web use the same number). */
internal const val BLANK_LIMIT = 0.995

/**
 * Paints every rectangle (in dp, with the origin at the top left) solid black, grown outward to whole
 * pixels. A rectangle that cannot be placed, or a scale that is not a positive number, hides the whole
 * picture: a mask that cannot be placed fails towards hiding.
 */
internal fun blackOut(px: PixelBuffer, frames: List<Frame>, scale: Double) {
    fun fill(x0: Int, y0: Int, x1: Int, y1: Int) {
        val xa = maxOf(0, x0)
        val xb = minOf(px.width, x1)
        val ya = maxOf(0, y0)
        val yb = minOf(px.height, y1)
        for (y in ya until yb) for (x in xa until xb) px.argb[y * px.width + x] = BLACK
    }
    for (r in frames) {
        if (!r.isFinite || !(scale > 0)) {
            fill(0, 0, px.width, px.height)
            continue
        }
        fill(
            Math.floor(r.x * scale).toInt(), Math.floor(r.y * scale).toInt(),
            Math.ceil((r.x + r.width) * scale).toInt(), Math.ceil((r.y + r.height) * scale).toInt(),
        )
    }
}

/**
 * The share of sampled pixels that are one colour: the most common colour, each channel rounded to steps
 * of 8, over a grid of at most 48 by 48 samples. A transparent pixel is one colour whatever its other
 * channels say. 1 means nothing was drawn.
 */
internal fun emptyFraction(px: PixelBuffer): Double {
    if (px.width <= 0 || px.height <= 0) return 0.0
    val cols = minOf(48, px.width)
    val rows = minOf(48, px.height)
    val counts = HashMap<Int, Int>()
    for (r in 0 until rows) for (c in 0 until cols) {
        val x = ((px.width - 1).toLong() * c / maxOf(cols - 1, 1)).toInt()
        val y = ((px.height - 1).toLong() * r / maxOf(rows - 1, 1)).toInt()
        val p = px.argb[y * px.width + x]
        val alpha = p ushr 24
        val key = if (alpha == 0) -1 else (((p shr 16) and 0xFF) shr 3 shl 16) or (((p shr 8) and 0xFF) shr 3 shl 8) or ((p and 0xFF) shr 3)
        counts[key] = (counts[key] ?: 0) + 1
    }
    return (counts.values.maxOrNull() ?: 0).toDouble() / (cols * rows)
}

internal fun isBlank(px: PixelBuffer): Boolean = emptyFraction(px) >= BLANK_LIMIT

/** The channel refuses a picture over 10 MiB. A PNG a little under that is halved in each direction, if the picture keeps at least one pixel per dp. */
internal const val PNG_SOFT_LIMIT = 9_500_000

internal fun shrinkFactor(pngBytes: Int, pixelsPerDp: Double): Double =
    if (pngBytes > PNG_SOFT_LIMIT && pixelsPerDp / 2 >= 1.0) 0.5 else 1.0

/** `WindowManager.LayoutParams.FLAG_SECURE`, written out so the check runs on the JVM. */
internal const val FLAG_SECURE = 0x00002000

internal fun isSecure(windowFlags: Int): Boolean = (windowFlags and FLAG_SECURE) != 0

internal fun sha256Hex(bytes: ByteArray): String =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

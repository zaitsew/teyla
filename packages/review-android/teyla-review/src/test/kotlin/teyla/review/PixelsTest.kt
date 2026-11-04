package teyla.review

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PixelsTest {
    private val white = 0xFFFFFFFF.toInt()

    private fun buffer(w: Int, h: Int, color: Int = white) = PixelBuffer(w, h, IntArray(w * h) { color })

    private fun blackAt(px: PixelBuffer, x: Int, y: Int) = px.argb[y * px.width + x] == BLACK

    @Test fun aFrameIsPaintedBlackAtTheScale() {
        val px = buffer(40, 40)
        blackOut(px, listOf(Frame(5.0, 5.0, 5.0, 5.0)), 2.0) // 10..20 in pixels
        assertTrue(blackAt(px, 10, 10)); assertTrue(blackAt(px, 19, 19))
        assertFalse(blackAt(px, 9, 10)); assertFalse(blackAt(px, 20, 19)); assertFalse(blackAt(px, 10, 20))
        assertEquals(100, px.argb.count { it == BLACK })
    }

    @Test fun aFractionalFrameGrowsOutwardToWholePixels() {
        val px = buffer(20, 20)
        blackOut(px, listOf(Frame(2.2, 2.2, 1.0, 1.0)), 1.0) // 2.2..3.2 covers pixels 2 and 3
        assertTrue(blackAt(px, 2, 2)); assertTrue(blackAt(px, 3, 3)); assertFalse(blackAt(px, 4, 4))
    }

    @Test fun aFrameOutsideThePictureIsClipped() {
        val px = buffer(10, 10)
        blackOut(px, listOf(Frame(-5.0, -5.0, 8.0, 8.0), Frame(8.0, 8.0, 100.0, 100.0)), 1.0)
        assertTrue(blackAt(px, 0, 0)); assertTrue(blackAt(px, 2, 2)); assertFalse(blackAt(px, 3, 3))
        assertTrue(blackAt(px, 9, 9)); assertFalse(blackAt(px, 7, 7))
    }

    @Test fun aFrameThatCannotBePlacedHidesTheWholePicture() {
        for (bad in listOf(Frame(Double.NaN, 0.0, 1.0, 1.0), Frame(0.0, Double.POSITIVE_INFINITY, 1.0, 1.0))) {
            val px = buffer(8, 8)
            blackOut(px, listOf(bad), 2.0)
            assertEquals(64, px.argb.count { it == BLACK })
        }
        val px = buffer(8, 8)
        blackOut(px, listOf(Frame(0.0, 0.0, 1.0, 1.0)), 0.0) // a scale that is not positive
        assertEquals(64, px.argb.count { it == BLACK })
    }

    @Test fun maskedPixelsCarryNoOriginalColour() {
        val px = buffer(10, 10, 0xFF123456.toInt())
        blackOut(px, listOf(Frame(0.0, 0.0, 10.0, 10.0)), 1.0)
        assertTrue(px.argb.all { it == BLACK })
    }

    @Test fun aSingleColourPictureIsBlankAndAnImageIsNot() {
        assertTrue(isBlank(buffer(100, 100)))
        assertTrue(isBlank(buffer(100, 100, 0)))
        val img = buffer(100, 100)
        for (y in 0 until 100) for (x in 0 until 100) if ((x / 10 + y / 10) % 2 == 0) img.argb[y * 100 + x] = 0xFF204080.toInt()
        assertFalse(isBlank(img))
        assertEquals(0.5, emptyFraction(img), 0.1)
    }

    @Test fun aLittleNoiseStillCountsAsOneColour() {
        val px = buffer(200, 200, 0xFF808080.toInt())
        px.argb[5] = 0xFF858585.toInt() // inside one 8-step bucket
        assertTrue(isBlank(px))
    }

    @Test fun aPictureTheSizeOfAnOnePixelBoxStillWorks() {
        assertTrue(isBlank(buffer(1, 1)))
        assertEquals(0.0, emptyFraction(PixelBuffer(0, 0, IntArray(0))), 0.0)
    }

    @Test fun aHugePictureIsHalvedOnlyWhenTheScaleKeepsAtLeastOnePixelPerDp() {
        assertEquals(1.0, shrinkFactor(1_000_000, 3.0), 0.0)
        assertEquals(0.5, shrinkFactor(9_600_000, 3.0), 0.0)
        assertEquals(0.5, shrinkFactor(9_600_000, 2.0), 0.0)
        assertEquals(1.0, shrinkFactor(9_600_000, 1.5), 0.0)
    }
}

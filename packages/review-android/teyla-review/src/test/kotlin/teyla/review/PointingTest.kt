package teyla.review

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PointingTest {
    @Test fun aPictureIsCentredAndScaledToFit() {
        val f = fitInside(400.0, 400.0, 0.5) // a portrait window in a square box
        assertEquals(200.0, f.width, 1e-9); assertEquals(400.0, f.height, 1e-9)
        assertEquals(100.0, f.offsetX, 1e-9); assertEquals(0.0, f.offsetY, 1e-9)
        val wide = fitInside(400.0, 100.0, 0.5)
        assertEquals(50.0, wide.width, 1e-9); assertEquals(100.0, wide.height, 1e-9)
    }

    @Test fun aTouchMapsToWindowDpAndOneOutsideThePictureIsNull() {
        val f = fitInside(400.0, 400.0, 0.5) // 100..300 across, the whole height
        assertEquals(Point(206.0, 446.0), toWindow(f, 200.0, 200.0, 412.0, 892.0))
        assertEquals(Point(0.0, 0.0), toWindow(f, 100.0, 0.0, 412.0, 892.0))
        assertNull(toWindow(f, 50.0, 200.0, 412.0, 892.0))
        assertNull(toWindow(f, 200.0, 401.0, 412.0, 892.0))
        assertNull(toWindow(fitInside(0.0, 0.0, 1.0), 1.0, 1.0, 10.0, 10.0))
    }

    @Test fun aDragIsAnAreaOnlyFromTwelveDp() {
        assertNull(areaOf(Point(10.0, 10.0), Point(20.0, 20.0)))
        assertEquals(Frame(10.0, 10.0, 12.0, 0.0), areaOf(Point(22.0, 10.0), Point(10.0, 10.0)))
        assertEquals(Frame(5.0, 5.0, 30.0, 20.0), areaOf(Point(35.0, 25.0), Point(5.0, 5.0)))
    }

    @Test fun theCrossMovesAndStopsAtTheEdgeWhereTheKeyIsLeftToTheSystem() {
        val mid = Point(100.0, 100.0)
        assertEquals(Point(88.0, 100.0), moveCursor(mid, Dir.Left, 12.0, 200.0, 400.0).at)
        assertTrue(moveCursor(mid, Dir.Down, 12.0, 200.0, 400.0).moved)
        val edge = moveCursor(Point(200.0, 100.0), Dir.Right, 12.0, 200.0, 400.0)
        assertFalse(edge.moved); assertEquals(Point(200.0, 100.0), edge.at)
        assertFalse(moveCursor(Point(100.0, 0.0), Dir.Up, 12.0, 200.0, 400.0).moved)
        assertEquals(200.0, moveCursor(Point(195.0, 100.0), Dir.Right, 12.0, 200.0, 400.0).at.x, 0.0) // clamped, and it did move
    }

    @Test fun holdingAKeyMovesTheCrossFaster() {
        assertEquals(12.0, stepFor(0), 1e-9)
        assertTrue(stepFor(10) > stepFor(5))
        assertEquals(stepFor(25), stepFor(500), 1e-9)
        assertNotNull(stepFor(1))
    }

    @Test fun sendNeedsACommentAndNoSaveUnderWay() {
        assertFalse(canSend("", false, false, false))
        assertFalse(canSend("  \n", false, false, false))
        assertTrue(canSend("x", false, false, false))
        assertFalse(canSend("x", true, false, false))
    }

    @Test fun theHealthBoxMustBeTickedWhenTheProductRequiresIt() {
        assertFalse(canSend("x", false, true, false))
        assertTrue(canSend("x", false, true, true))
        assertTrue(canSend("x", false, false, false))
    }

    private class Mem(var v: Boolean = false) : KeyValue {
        override fun getBoolean(key: String) = v
        override fun putBoolean(key: String, value: Boolean) { v = value }
    }

    @Test fun theNoticeShowsUntilItIsAcceptedOnce() {
        val kv = Mem()
        assertTrue(isNeeded(true, kv))
        accept(kv)
        assertFalse(isNeeded(true, kv))
        assertFalse(isNeeded(false, Mem()))
    }

    @Test fun aStoreThatFailsShowsTheNoticeAgainAndNeverCrashes() {
        val broken = object : KeyValue {
            override fun getBoolean(key: String): Boolean = throw IllegalStateException()
            override fun putBoolean(key: String, value: Boolean) { throw IllegalStateException() }
        }
        assertTrue(isNeeded(true, broken))
        accept(broken)
        assertTrue(isNeeded(true, null))
    }

    @Test fun aWindowWithFlagSecureIsRefused() {
        assertTrue(isSecure(0x2000))
        assertTrue(isSecure(0x2000 or 0x80))
        assertFalse(isSecure(0x80))
    }
}

package teyla.review

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RegistryTest {
    private fun frame(x: Double, y: Double, w: Double, h: Double): () -> Frame? = { Frame(x, y, w, h) }

    @Test fun boundsAreReadWhenTheSnapshotIsTakenAndConvertedToDp() {
        val r = Registry()
        var y = 200.0
        r.add(Kind.Anchor, "s.row", ReviewRole.Cell, listOf("k")) { Frame(100.0, y, 200.0, 100.0) }
        assertEquals(Frame(50.0, 100.0, 100.0, 50.0), r.snapshot(400.0, 800.0, 2.0).anchors[0].bounds)
        y = 400.0 // the list scrolled
        assertEquals(Frame(50.0, 200.0, 100.0, 50.0), r.snapshot(400.0, 800.0, 2.0).anchors[0].bounds)
    }

    @Test fun aRemovedEntryIsGoneAndOrderIsRegistrationOrder() {
        val r = Registry()
        val a = r.add(Kind.Anchor, "a", ReviewRole.Other, emptyList(), frame(0.0, 0.0, 10.0, 10.0))
        r.add(Kind.Anchor, "b", ReviewRole.Other, emptyList(), frame(0.0, 0.0, 10.0, 10.0))
        assertEquals(listOf("a", "b"), r.snapshot(100.0, 100.0, 1.0).anchors.map { it.id })
        r.remove(a)
        assertEquals(listOf("b"), r.snapshot(100.0, 100.0, 1.0).anchors.map { it.id })
        assertEquals(1, r.count())
    }

    @Test fun anAnchorOffTheWindowOrWithNoBoxIsLeftOut() {
        val r = Registry()
        r.add(Kind.Anchor, "off", ReviewRole.Other, emptyList(), frame(500.0, 0.0, 10.0, 10.0))
        r.add(Kind.Anchor, "empty", ReviewRole.Other, emptyList(), frame(5.0, 5.0, 0.0, 0.0))
        r.add(Kind.Anchor, "gone", ReviewRole.Other, emptyList()) { null }
        r.add(Kind.Anchor, "ok", ReviewRole.Other, emptyList(), frame(5.0, 5.0, 10.0, 10.0))
        assertEquals(listOf("ok"), r.snapshot(100.0, 100.0, 1.0).anchors.map { it.id })
    }

    @Test fun atMostTwoHundredAnchors() {
        val r = Registry()
        repeat(250) { r.add(Kind.Anchor, "a.$it", ReviewRole.Other, emptyList(), frame(0.0, 0.0, 5.0, 5.0)) }
        assertEquals(200, r.snapshot(100.0, 100.0, 1.0).anchors.size)
    }

    @Test fun aPrivateAreaIsGrownByTwoDpAndAnOffscreenOneHidesNothing() {
        val r = Registry()
        r.add(Kind.Private, "", ReviewRole.Other, emptyList(), frame(20.0, 20.0, 40.0, 20.0)) // 10, 10, 20, 10 dp at 2x
        r.add(Kind.Private, "", ReviewRole.Other, emptyList(), frame(5000.0, 0.0, 10.0, 10.0))
        r.add(Kind.Private, "", ReviewRole.Other, emptyList()) { null }
        assertEquals(listOf(Frame(8.0, 8.0, 24.0, 14.0)), r.snapshot(100.0, 100.0, 2.0).privateFrames)
    }

    @Test fun aPrivateAreaThatCannotSayWhereItIsHidesTheWholeWindow() {
        val r = Registry()
        r.add(Kind.Private, "", ReviewRole.Other, emptyList()) { Frame(Double.NaN, 0.0, 1.0, 1.0) }
        r.add(Kind.Private, "", ReviewRole.Other, emptyList()) { throw IllegalStateException("detached") }
        val frames = r.snapshot(100.0, 100.0, 1.0).privateFrames
        assertEquals(2, frames.size)
        assertTrue(frames.none { it.isFinite })
        val px = PixelBuffer(10, 10, IntArray(100) { -1 })
        blackOut(px, frames, 1.0)
        assertTrue(px.argb.all { it == BLACK })
    }

    @Test fun anAnchorOverlappingAPrivateAreaLosesItsStrings() {
        val r = Registry()
        r.add(Kind.Anchor, "s.name", ReviewRole.Text, listOf("k.name"), frame(10.0, 10.0, 30.0, 10.0))
        r.add(Kind.Private, "", ReviewRole.Other, emptyList(), frame(12.0, 12.0, 10.0, 5.0))
        val s = r.snapshot(100.0, 100.0, 1.0)
        assertTrue(s.anchors[0].strings.isEmpty())
    }

    @Test fun anAnchorTakesTheSmallestScreenAroundItsCentre() {
        val r = Registry()
        r.add(Kind.Screen, "outer", ReviewRole.Container, emptyList(), frame(0.0, 0.0, 100.0, 100.0))
        r.add(Kind.Screen, "inner", ReviewRole.Container, emptyList(), frame(0.0, 50.0, 100.0, 50.0))
        r.add(Kind.Anchor, "a.top", ReviewRole.Other, emptyList(), frame(10.0, 10.0, 10.0, 10.0))
        r.add(Kind.Anchor, "a.low", ReviewRole.Other, emptyList(), frame(10.0, 60.0, 10.0, 10.0))
        assertEquals(listOf("outer", "inner"), r.snapshot(100.0, 100.0, 1.0).anchors.map { it.screen })
    }

    @Test
    fun aPictureWaitsUntilThePrivateAreasHoldStill() {
        val still = StillWatch(needed = 2)
        val a = Frame(0.0, 0.0, 10.0, 10.0)
        val moved = Frame(0.0, 5.0, 10.0, 10.0)
        assertFalse(still.observe(listOf(a)))
        assertFalse(still.observe(listOf(a)))
        assertFalse(still.observe(listOf(moved)))
        assertFalse(still.observe(listOf(moved)))
        assertTrue(still.observe(listOf(moved)))
    }

    @Test
    fun anAreaThatAppearsCountsAsMovement() {
        val still = StillWatch(needed = 1)
        val a = Frame(0.0, 0.0, 10.0, 10.0)
        assertFalse(still.observe(emptyList()))
        assertFalse(still.observe(listOf(a)))
        assertTrue(still.observe(listOf(a)))
    }

    @Test
    fun theOrderOfTheAreasIsNotMovement() {
        val still = StillWatch(needed = 1)
        val a = Frame(0.0, 0.0, 10.0, 10.0)
        val b = Frame(0.0, 20.0, 10.0, 10.0)
        assertFalse(still.observe(listOf(a, b)))
        assertTrue(still.observe(listOf(b, a)))
    }
}

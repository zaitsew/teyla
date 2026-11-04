package teyla.review

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AnchorsTest {
    private fun a(id: String, x: Double, y: Double, w: Double, h: Double, screen: String? = null, strings: List<String> = emptyList()) =
        Anchor(id, ReviewRole.Button, Frame(x, y, w, h), screen, strings)

    @Test fun theSmallestAnchorWinsAndTheLaterOneOnATie() {
        val big = a("big", 0.0, 0.0, 100.0, 100.0)
        val small = a("small", 10.0, 10.0, 20.0, 20.0)
        val twin = a("twin", 10.0, 10.0, 20.0, 20.0)
        assertEquals("small", hitTest(listOf(big, small), 15.0, 15.0)?.id)
        assertEquals("twin", hitTest(listOf(big, small, twin), 15.0, 15.0)?.id)
        assertEquals("big", hitTest(listOf(big, small), 50.0, 50.0)?.id)
    }

    @Test fun leftAndTopEdgesAreInsideRightAndBottomAreOutside() {
        val box = a("b", 10.0, 10.0, 20.0, 20.0)
        assertEquals("b", hitTest(listOf(box), 10.0, 10.0)?.id)
        assertNull(hitTest(listOf(box), 30.0, 15.0))
        assertNull(hitTest(listOf(box), 15.0, 30.0))
        assertNull(hitTest(emptyList(), 1.0, 1.0))
    }

    @Test fun theScreenIsTheProductsThenTheHitsThenTheMostCommon() {
        val one = a("x.one", 0.0, 0.0, 5.0, 5.0, "x")
        val two = a("y.two", 0.0, 0.0, 5.0, 5.0, "y")
        val three = a("y.three", 0.0, 0.0, 5.0, 5.0, "y")
        assertEquals("set", screenFor("set", one, listOf(one, two)))
        assertEquals("x", screenFor(null, one, listOf(one, two)))
        assertEquals("y", screenFor(null, null, listOf(one, two, three)))
        assertNull(screenFor(null, null, listOf(a("n", 0.0, 0.0, 1.0, 1.0))))
    }

    @Test fun aTapOrAnAreaInAPrivateFrameIsPrivate() {
        val f = listOf(Frame(10.0, 10.0, 20.0, 20.0))
        assertTrue(touchesPrivate(Point(10.0, 10.0), null, f))
        assertFalse(touchesPrivate(Point(30.0, 10.0), null, f))
        assertTrue(touchesPrivate(null, Frame(25.0, 25.0, 50.0, 50.0), f))
        assertFalse(touchesPrivate(null, Frame(30.0, 30.0, 5.0, 5.0), f))
        assertFalse(touchesPrivate(null, null, f))
    }

    @Test fun anAnchorOverlappingAPrivateAreaLosesItsStringsButKeepsItsIdAndBounds() {
        val hidden = a("h", 10.0, 10.0, 20.0, 20.0, "s", listOf("k.name"))
        val other = a("o", 200.0, 200.0, 20.0, 20.0, "s", listOf("k.other"))
        val out = redactAnchors(listOf(hidden, other), listOf(Frame(0.0, 0.0, 15.0, 15.0)))
        assertTrue(out[0].strings.isEmpty()); assertEquals("h", out[0].id); assertEquals(hidden.bounds, out[0].bounds)
        assertEquals(listOf("k.other"), out[1].strings)
    }

    private fun frozen(anchors: List<Anchor>, frames: List<Frame>) = Frozen(
        Samples.id, Samples.app, Samples.env, null, redactAnchors(anchors, frames), frames, Samples.sha, 100, 200, 2.0,
    )

    @Test fun aTapOnAnAnchorNamesItInTheCapture() {
        val box = a("s.btn", 10.0, 10.0, 20.0, 20.0, "s", listOf("k"))
        val rec = recordFor(frozen(listOf(box), emptyList()), Draft(Point(15.0, 15.0), null, " hi "), Instant.EPOCH)
        assertEquals("s.btn", rec.element?.id)
        assertEquals("s", rec.screen)
        assertEquals("hi", rec.text)
        assertTrue(encodeCapture(rec).contains("\"matched_by\":\"anchor\""))
    }

    @Test fun aTapInAPrivateAreaRecordsNoElementAndNoStrings() {
        val box = a("s.name", 10.0, 10.0, 20.0, 20.0, "s", listOf("k.secret"))
        val rec = recordFor(frozen(listOf(box), listOf(Frame(8.0, 8.0, 24.0, 24.0))), Draft(Point(15.0, 15.0), null, "x"), Instant.EPOCH)
        assertNull(rec.element)
        val json = encodeCapture(rec)
        assertFalse(json.contains("\"element\""))
        assertFalse(json.contains("k.secret"))
        assertTrue(json.contains("s.name")) // ids, roles and bounds stay
    }

    @Test fun anAreaTapsAtItsCentreAndRecordsTheRegion() {
        val box = a("s.btn", 40.0, 40.0, 20.0, 20.0, "s")
        val rec = recordFor(frozen(listOf(box), emptyList()), Draft(null, Frame(30.0, 30.0, 40.0, 40.0), "x"), Instant.EPOCH)
        assertEquals(Point(50.0, 50.0), rec.tap)
        assertEquals("s.btn", rec.element?.id)
        assertTrue(encodeCapture(rec).contains("\"region\":{\"x\":30,\"y\":30,\"width\":40,\"height\":40}"))
    }

    @Test fun aWholeScreenCaptureHasNoTapAndNoElement() {
        val rec = recordFor(frozen(listOf(a("s.btn", 0.0, 0.0, 9.0, 9.0, "s")), emptyList()), Draft(null, null, "x"), Instant.EPOCH)
        assertNull(rec.tap); assertNull(rec.element); assertEquals("s", rec.screen)
    }

    @Test fun theMarginGrowsAFrameByTwoDp() {
        assertEquals(Frame(8.0, 8.0, 24.0, 24.0), grown(Frame(10.0, 10.0, 20.0, 20.0)))
        assertFalse(grown(Frame(Double.NaN, 0.0, 1.0, 1.0)).isFinite)
    }
}

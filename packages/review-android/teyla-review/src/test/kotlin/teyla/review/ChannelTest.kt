package teyla.review

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ChannelTest {
    private val cfg = ChannelConfig("https://review.example", "k-secret")
    private fun entry(id: String = Samples.id) = QueueEntry(id, 0, "{\"v\":1}", byteArrayOf(1, 2, 3))

    private class Fake(val answers: List<Int>) : Transport {
        val calls = ArrayList<List<String>>()
        override fun put(url: String, key: String, contentType: String, body: ByteArray): Int {
            calls.add(listOf(url, key, contentType, body.size.toString()))
            val a = answers[minOf(calls.size - 1, answers.size - 1)]
            if (a < 0) throw IOException("down")
            return a
        }
    }

    @Test fun statusesMeanWhatTheWebPackageSays() {
        assertEquals(ChannelResult.Delivered, resultForStatus(200))
        for (s in listOf(400, 401, 403, 413, 422)) assertEquals("$s", ChannelResult.Refused, resultForStatus(s))
        for (s in listOf(404, 405, 429, 500, 502, 503, 507, 204, 301)) assertEquals("$s", ChannelResult.Retry, resultForStatus(s))
    }

    @Test fun thePictureGoesFirstThenTheJsonWithTheBearerKey() {
        val t = Fake(listOf(200, 200))
        assertEquals(ChannelResult.Delivered, sendCapture(cfg, entry(), t))
        assertEquals(listOf("https://review.example/v1/captures/${Samples.id}/capture.png", "k-secret", "image/png", "3"), t.calls[0])
        assertEquals("https://review.example/v1/captures/${Samples.id}/capture.json", t.calls[1][0])
        assertEquals("application/json", t.calls[1][2])
    }

    @Test fun itStopsAtTheFirstAnswerThatIsNotOk() {
        val t = Fake(listOf(429, 200))
        assertEquals(ChannelResult.Retry, sendCapture(cfg, entry(), t))
        assertEquals(1, t.calls.size)
        val u = Fake(listOf(200, 403))
        assertEquals(ChannelResult.Refused, sendCapture(cfg, entry(), u))
        assertEquals(2, u.calls.size)
    }

    @Test fun noNetworkReadsAsLater() {
        assertEquals(ChannelResult.Retry, sendCapture(cfg, entry(), Fake(listOf(-1))))
    }

    @Test fun anIdThatIsNotALowercaseUuidIsRefusedWithoutACall() {
        val t = Fake(listOf(200))
        assertEquals(ChannelResult.Refused, sendCapture(cfg, entry("../etc"), t))
        assertEquals(ChannelResult.Refused, sendCapture(cfg, entry(Samples.id.uppercase()), t))
        assertTrue(t.calls.isEmpty())
    }

    @Test fun theChannelNeedsHttpsAndBothValues() {
        assertEquals("https://review.example", parseChannel("https://review.example/", "k")?.baseUrl)
        assertEquals("https://review.example/base", parseChannel("https://review.example/base//", "k")?.baseUrl)
        assertEquals("http://localhost:8099", parseChannel("http://localhost:8099", "k")?.baseUrl)
        assertEquals("http://127.0.0.1:8099", parseChannel("http://127.0.0.1:8099", "k")?.baseUrl)
        assertNull(parseChannel("http://review.example", "k"))
        assertNull(parseChannel("ftp://review.example", "k"))
        assertNull(parseChannel("https://user:pw" + "@review.example", "k"))
        assertNull(parseChannel("https://review.example", ""))
        assertNull(parseChannel("", "k"))
        assertNull(parseChannel(null, "k"))
        assertNull(parseChannel("https://review.example", null))
        assertNull(parseChannel("\$(CHANNEL_URL)", "k"))
        assertNull(parseChannel("https://review.example", "null"))
        assertNull(parseChannel("not a url", "k"))
    }

    @Test fun aProductsDeliverWinsAndAnswersTrueOrLater() {
        val seen = ArrayList<String>()
        val route = routeFor(ReviewConfig("p", channelUrl = "https://review.example", channelKey = "k", deliver = { seen.add(it.id); true }))
        assertTrue(route is Route.Product)
        val t = Fake(listOf(200))
        assertEquals(ChannelResult.Delivered, deliverWith(route!!, entry(), t))
        assertEquals(listOf(Samples.id), seen)
        assertTrue("no network call of its own", t.calls.isEmpty())
        assertEquals(ChannelResult.Retry, deliverWith(Route.Product { false }, entry(), t))
        assertEquals(ChannelResult.Retry, deliverWith(Route.Product { throw IllegalStateException() }, entry(), t))
    }

    @Test fun reviewIsUsableOnlyWithASlugAndARoute() {
        assertTrue(isUsable(ReviewConfig("sample-app", channelUrl = "https://review.example", channelKey = "k")))
        assertTrue(isUsable(ReviewConfig("sample-app", deliver = { true })))
        assertTrue(!isUsable(ReviewConfig("sample-app")))
        assertTrue(!isUsable(ReviewConfig("Sample", deliver = { true })))
        assertTrue(!isUsable(ReviewConfig("sample-app", channelUrl = "https://review.example")))
        assertTrue(routeFor(ReviewConfig("sample-app", channelUrl = "https://review.example", channelKey = "k")) is Route.Channel)
    }
}

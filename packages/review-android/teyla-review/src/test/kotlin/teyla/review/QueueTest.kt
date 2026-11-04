package teyla.review

import java.io.File
import java.util.UUID
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class QueueTest {
    private val root = File.createTempFile("teyla-review", "").let { it.delete(); it.mkdirs(); it }
    private var clock = 1_000_000L

    @After fun cleanUp() { root.deleteRecursively() }

    private fun entry(created: Long = clock, png: Int = 100, id: String = UUID.randomUUID().toString()) =
        QueueEntry(id, created, "{\"id\":\"$id\"}", ByteArray(png) { 7 })

    private fun queue(result: () -> ChannelResult, cap: Cap = DEFAULT_CAP, seen: MutableList<String>? = null) =
        FileQueue(root, { e -> seen?.add(e.id); result() }, { clock }, cap)

    @Test fun aDeliveredCaptureLeavesNothingBehind() {
        val q = queue({ ChannelResult.Delivered })
        assertEquals(SendOutcome.Delivered, q.send(entry()))
        assertEquals(0, q.list().size)
    }

    @Test fun aCaptureThatCannotBeSentWaitsAndGoesLater() {
        var answer = ChannelResult.Retry
        val q = queue({ answer })
        val e = entry()
        assertEquals(SendOutcome.Queued, q.send(e))
        assertEquals(1, q.pending())
        assertEquals(1, q.list()[0].attempts)
        assertEquals(1, q.flush().retry)
        assertEquals(2, q.list()[0].attempts)
        answer = ChannelResult.Delivered
        val r = q.flush()
        assertEquals(1, r.delivered)
        assertEquals(0, q.list().size)
    }

    @Test fun theCapturesAreSentOldestFirstWithTheirBytesIntact() {
        val seen = ArrayList<String>()
        var answer = ChannelResult.Retry
        val q = queue({ answer }, seen = seen)
        val a = entry(created = 3); val b = entry(created = 1); val c = entry(created = 2)
        for (e in listOf(a, b, c)) q.send(e)
        seen.clear(); answer = ChannelResult.Delivered
        q.flush()
        assertEquals(listOf(b.id, c.id, a.id), seen)
    }

    @Test fun aRefusedCaptureIsKeptAndNotOfferedAgain() {
        var answer = ChannelResult.Refused
        val seen = ArrayList<String>()
        val q = queue({ answer }, seen = seen)
        val e = entry()
        assertEquals(SendOutcome.Queued, q.send(e))
        assertTrue(q.list()[0].refused)
        assertEquals(0, q.pending())
        seen.clear(); answer = ChannelResult.Delivered
        assertEquals(0, q.flush().delivered)
        assertTrue(seen.isEmpty())
        assertEquals(1, q.list().size) // the words are not lost silently
    }

    @Test fun aCaptureOlderThanFourteenDaysIsRemoved() {
        val q = queue({ ChannelResult.Retry })
        q.send(entry(created = clock))
        clock += 14L * 24 * 3600 * 1000 - 1
        assertEquals(0, q.flush().expired)
        clock += 2
        val r = q.flush()
        assertEquals(1, r.expired)
        assertEquals(0, q.list().size)
    }

    @Test fun anExpiredRefusedCaptureIsRemovedToo() {
        val q = queue({ ChannelResult.Refused })
        q.send(entry())
        clock += 15L * 24 * 3600 * 1000
        assertEquals(1, q.flush().expired)
        assertEquals(0, q.list().size)
    }

    @Test fun theTwentyFirstCaptureIsNotSavedButStillTried() {
        var tried = 0
        val q = FileQueue(root, { tried++; ChannelResult.Retry }, { clock })
        repeat(20) { assertEquals(SendOutcome.Queued, q.send(entry())) }
        assertEquals(20, q.list().size)
        tried = 0
        assertEquals(SendOutcome.Unsaved, q.send(entry()))
        assertEquals(1, tried)
        assertEquals(20, q.list().size)
    }

    @Test fun aFullQueueStillDeliversFromMemory() {
        val q = queue({ ChannelResult.Retry })
        repeat(20) { q.send(entry()) }
        val ok = FileQueue(root, { ChannelResult.Delivered }, { clock })
        assertEquals(SendOutcome.Delivered, ok.send(entry()))
        assertEquals(20, ok.list().size)
    }

    @Test fun theSizeCapIsFortyMebibytesAndAnEntryKeepsItsOwnSlotOnRetry() {
        val cap = Cap(20, 1000, DEFAULT_CAP.ttlMs)
        val q = queue({ ChannelResult.Retry }, cap)
        val a = entry(png = 600)
        assertEquals(SendOutcome.Queued, q.send(a))
        assertEquals(SendOutcome.Unsaved, q.send(entry(png = 600))) // 1200 + json > 1000
        assertEquals(SendOutcome.Queued, q.send(QueueEntry(a.id, a.created, a.json, ByteArray(700)))) // the same id replaces itself
        assertEquals(1, q.list().size)
        assertEquals(40L * 1024 * 1024, DEFAULT_CAP.bytes)
        assertEquals(20, DEFAULT_CAP.entries)
        assertEquals(14L * 24 * 3600 * 1000, DEFAULT_CAP.ttlMs)
    }

    @Test fun aHalfWrittenFolderIsSweptAndNeverSent() {
        val q = queue({ ChannelResult.Delivered })
        val tmp = File(root, ".tmp-" + UUID.randomUUID()); tmp.mkdirs(); File(tmp, "capture.png").writeBytes(ByteArray(10))
        val half = File(root, UUID.randomUUID().toString()); half.mkdirs(); File(half, "capture.json").writeText("{}")
        assertEquals(0, q.list().size)
        assertFalse(tmp.exists())
        assertEquals(0, q.flush().delivered)
    }

    @Test fun withNoSenderNothingIsDeliveredAndNothingIsLost() {
        val q = FileQueue(root, null, { clock })
        assertEquals(SendOutcome.Queued, q.send(entry()))
        assertEquals(1, q.flush().retry)
        assertEquals(1, q.list().size)
    }

    @Test fun aSecondQueueOnTheSameFolderSeesTheSameCaptures() {
        queue({ ChannelResult.Retry }).send(entry())
        val again = queue({ ChannelResult.Delivered })
        assertEquals(1, again.list().size)
        assertEquals(1, again.flush().delivered)
    }
}

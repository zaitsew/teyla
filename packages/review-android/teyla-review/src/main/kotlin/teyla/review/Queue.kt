package teyla.review

import java.io.File
import java.util.Properties

/**
 * Captures that have not reached the server wait here, in files in the app's private storage, with caps,
 * and go out again later. A capture is saved first and sent second; its folder is deleted only after the
 * server answered 200 for both files. Layout: `<root>/<id>/capture.json`, `capture.png`, `meta`.
 */
internal class QueueEntry(
    val id: String,
    val created: Long,
    val json: String,
    val png: ByteArray,
    val attempts: Int = 0,
    /** The server will never take it (bad key, wrong product, too large). Kept so the words are not lost silently. */
    val refused: Boolean = false,
)

/** What the folder says about an entry, without reading the picture. */
internal class Stored(val id: String, val created: Long, val bytes: Long, val attempts: Int, val refused: Boolean)

internal class Cap(val entries: Int, val bytes: Long, val ttlMs: Long)

internal val DEFAULT_CAP = Cap(entries = 20, bytes = 40L * 1024 * 1024, ttlMs = 14L * 24 * 3600 * 1000)

internal class QueueFullException : Exception("The review queue is full.")

/** `Delivered`: the server has it. `Queued`: it waits here. `Unsaved`: it is nowhere but memory. */
internal enum class SendOutcome { Delivered, Queued, Unsaved }

internal class FlushReport(var delivered: Int = 0, var retry: Int = 0, var refused: Int = 0, var expired: Int = 0)

internal class FileQueue(
    private val root: File,
    private val deliver: ((QueueEntry) -> ChannelResult)?,
    private val now: () -> Long = System::currentTimeMillis,
    private val cap: Cap = DEFAULT_CAP,
) {
    private val lock = Any()

    private fun dir(id: String) = File(root, id)

    private fun readMeta(d: File): Triple<Long, Int, Boolean>? = try {
        val p = Properties()
        File(d, "meta").inputStream().use { p.load(it) }
        Triple(p.getProperty("created").toLong(), p.getProperty("attempts", "0").toInt(), p.getProperty("refused", "false") == "true")
    } catch (e: Exception) {
        null
    }

    private fun writeMeta(d: File, created: Long, attempts: Int, refused: Boolean) {
        val p = Properties()
        p.setProperty("created", created.toString())
        p.setProperty("attempts", attempts.toString())
        p.setProperty("refused", refused.toString())
        val tmp = File(d, "meta.tmp")
        tmp.outputStream().use { p.store(it, null) }
        if (!tmp.renameTo(File(d, "meta"))) { // renameTo replaces on Android; keep a fallback for other file systems
            File(d, "meta").delete()
            if (!tmp.renameTo(File(d, "meta"))) throw java.io.IOException("could not write meta")
        }
    }

    /** Every complete entry. A folder that is not a capture's is left alone; an unfinished `.tmp-` one is removed. */
    fun list(): List<Stored> = synchronized(lock) {
        val out = ArrayList<Stored>()
        for (d in root.listFiles().orEmpty()) {
            if (!d.isDirectory) continue
            if (d.name.startsWith(".tmp-")) { d.deleteRecursively(); continue }
            if (!isUuid(d.name)) continue
            val m = readMeta(d) ?: continue
            val json = File(d, JSON_NAME)
            val png = File(d, PNG_NAME)
            if (!json.isFile || !png.isFile) continue
            out.add(Stored(d.name, m.first, json.length() + png.length(), m.second, m.third))
        }
        out.sortedBy { it.created }
    }

    private fun load(s: Stored): QueueEntry? = try {
        val d = dir(s.id)
        QueueEntry(s.id, s.created, File(d, JSON_NAME).readText(Charsets.UTF_8), File(d, PNG_NAME).readBytes(), s.attempts, s.refused)
    } catch (e: Exception) {
        null
    }

    private fun remove(id: String) { synchronized(lock) { dir(id).deleteRecursively() } }

    /** Writes the entry whole or not at all, in a hidden folder that is renamed when it is complete. */
    private fun write(e: QueueEntry, attempts: Int, refused: Boolean) = synchronized(lock) {
        root.mkdirs()
        val tmp = File(root, ".tmp-${e.id}")
        tmp.deleteRecursively()
        if (!tmp.mkdirs()) throw java.io.IOException("could not create ${tmp.name}")
        try {
            File(tmp, JSON_NAME).writeText(e.json, Charsets.UTF_8)
            File(tmp, PNG_NAME).writeBytes(e.png)
            writeMeta(tmp, e.created, attempts, refused)
            val final = dir(e.id)
            final.deleteRecursively()
            if (!tmp.renameTo(final)) throw java.io.IOException("could not move ${tmp.name}")
        } catch (x: Exception) {
            tmp.deleteRecursively()
            throw x
        }
    }

    private fun save(e: QueueEntry) = synchronized(lock) {
        val others = list().filter { it.id != e.id }
        val bytes = others.sumOf { it.bytes } + e.json.toByteArray(Charsets.UTF_8).size + e.png.size
        if (others.size + 1 > cap.entries || bytes > cap.bytes) throw QueueFullException()
        write(e, e.attempts, false)
    }

    private fun mark(e: QueueEntry, attempts: Int, refused: Boolean) {
        try { synchronized(lock) { if (dir(e.id).isDirectory) writeMeta(dir(e.id), e.created, attempts, refused) } } catch (_: Exception) {}
    }

    /** Save, then try once. Reuses the entry's slot when the same id is sent again (a retry). */
    fun send(entry: QueueEntry): SendOutcome {
        val saved = try { save(entry); true } catch (e: Exception) { false }
        val result = deliver?.invoke(entry) ?: ChannelResult.Retry
        if (result == ChannelResult.Delivered) {
            if (saved) remove(entry.id)
            return SendOutcome.Delivered
        }
        if (!saved) return SendOutcome.Unsaved
        mark(entry, entry.attempts + 1, result == ChannelResult.Refused)
        return SendOutcome.Queued
    }

    private val flushLock = Any()

    /** Send everything that waits, oldest first. Two calls at once run one after the other, and the second finds nothing left. */
    fun flush(): FlushReport = synchronized(flushLock) {
        val report = FlushReport()
        val all = try { list() } catch (e: Exception) { return report }
        for (s in all) {
            if (now() - s.created > cap.ttlMs) { remove(s.id); report.expired++; continue }
            if (s.refused) continue
            if (deliver == null) { report.retry++; continue }
            val e = load(s) ?: continue
            when (deliver.invoke(e)) {
                ChannelResult.Delivered -> { remove(s.id); report.delivered++ }
                ChannelResult.Refused -> { mark(e, s.attempts, true); report.refused++ }
                ChannelResult.Retry -> { mark(e, s.attempts + 1, false); report.retry++ }
            }
        }
        report
    }

    fun pending(): Int = try { list().count { !it.refused } } catch (e: Exception) { 0 }
}

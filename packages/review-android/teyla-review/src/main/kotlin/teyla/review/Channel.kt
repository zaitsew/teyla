package teyla.review

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

/** The built-in client for the shared review channel (packages/review-channel): PUT the picture, then the
 *  JSON, each with the write-only bearer key. The only network call the package makes. */
internal enum class ChannelResult { Delivered, Retry, Refused }

internal class ChannelConfig(val baseUrl: String, val key: String)

/** Statuses that will not change by asking again. 429, 503, 507, 5xx and a network error read as "later". */
internal val PERMANENT = setOf(400, 401, 403, 413, 422)

internal fun resultForStatus(status: Int): ChannelResult = when {
    status == 200 -> ChannelResult.Delivered
    status in PERMANENT -> ChannelResult.Refused
    else -> ChannelResult.Retry
}

private fun text(v: String?): String? {
    val t = v?.trim() ?: return null
    return if (t.isEmpty() || t.startsWith("\$(") || t == "null" || t == "undefined") null else t
}

/** Null unless both values are present and non-empty and the URL is HTTPS (plain HTTP only for a loopback host, for local development). */
internal fun parseChannel(url: String?, key: String?): ChannelConfig? {
    val u = text(url) ?: return null
    val k = text(key) ?: return null
    val uri = try { URI(u) } catch (e: Exception) { return null }
    val host = uri.host ?: return null
    val loopback = host == "localhost" || host == "127.0.0.1" || host == "[::1]" || host == "::1"
    val ok = uri.scheme == "https" || (uri.scheme == "http" && loopback)
    if (!ok || uri.userInfo != null) return null
    val port = if (uri.port >= 0) ":" + uri.port else ""
    return ChannelConfig(uri.scheme + "://" + host + port + uri.path.trimEnd('/'), k)
}

/** One PUT. Returns the status, or throws IOException when there is no answer. */
internal fun interface Transport {
    @Throws(IOException::class)
    fun put(url: String, key: String, contentType: String, body: ByteArray): Int
}

internal object HttpTransport : Transport {
    private const val TIMEOUT_MS = 30_000

    override fun put(url: String, key: String, contentType: String, body: ByteArray): Int {
        val c = URL(url).openConnection() as HttpURLConnection
        try {
            c.requestMethod = "PUT"
            c.connectTimeout = TIMEOUT_MS
            c.readTimeout = TIMEOUT_MS
            c.instanceFollowRedirects = false
            c.useCaches = false
            c.doOutput = true
            c.setFixedLengthStreamingMode(body.size)
            c.setRequestProperty("Authorization", "Bearer $key")
            c.setRequestProperty("Content-Type", contentType)
            c.outputStream.use { it.write(body) }
            val status = c.responseCode
            // Drain the answer so the connection can close cleanly. Its text is never read or logged.
            try { (if (status >= 400) c.errorStream else c.inputStream)?.use { it.skip(Long.MAX_VALUE) } } catch (_: IOException) {}
            return status
        } finally {
            c.disconnect()
        }
    }
}

internal fun putOne(cfg: ChannelConfig, id: String, file: String, body: ByteArray, contentType: String, transport: Transport): ChannelResult =
    try {
        resultForStatus(transport.put("${cfg.baseUrl}/v1/captures/$id/$file", cfg.key, contentType, body))
    } catch (e: IOException) {
        ChannelResult.Retry // no network, a timeout or a cancelled request: try again later
    } catch (e: RuntimeException) {
        ChannelResult.Retry
    }

/** The picture first, then the JSON. Stops at the first answer that is not 200. */
internal fun sendCapture(cfg: ChannelConfig, entry: QueueEntry, transport: Transport = HttpTransport): ChannelResult {
    if (!isUuid(entry.id)) return ChannelResult.Refused
    val png = putOne(cfg, entry.id, PNG_NAME, entry.png, "image/png", transport)
    if (png != ChannelResult.Delivered) return png
    return putOne(cfg, entry.id, JSON_NAME, entry.json.toByteArray(Charsets.UTF_8), "application/json", transport)
}

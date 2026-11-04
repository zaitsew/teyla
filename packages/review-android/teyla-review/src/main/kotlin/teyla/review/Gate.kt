package teyla.review

import kotlin.math.sqrt

/** `Configuration.UI_MODE_TYPE_MASK` and `UI_MODE_TYPE_TELEVISION`. Written out so the decision runs on the JVM. */
internal const val UI_MODE_TYPE_MASK = 0x0f
internal const val UI_MODE_TYPE_TELEVISION = 0x04

/** A TV reports `UI_MODE_TYPE_TELEVISION` through `UiModeManager.currentModeType`. */
internal fun isTelevision(uiModeType: Int): Boolean = (uiModeType and UI_MODE_TYPE_MASK) == UI_MODE_TYPE_TELEVISION

/** Which entry points are on. The Settings row is always there; the shake is for a handheld with an accelerometer only. */
internal data class EntryPoints(val settingsRow: Boolean, val shake: Boolean)

internal fun entryPoints(uiModeType: Int, hasAccelerometer: Boolean, shakeRequested: Boolean): EntryPoints =
    EntryPoints(settingsRow = true, shake = shakeRequested && hasAccelerometer && !isTelevision(uiModeType))

/**
 * A shake is three jolts above 2.7 g within one second, each at least 100 ms after the last. After one,
 * the detector stays quiet for two seconds. Feed it accelerometer samples with their times in milliseconds.
 */
internal class ShakeDetector(
    private val thresholdG: Double = 2.7,
    private val jolts: Int = 3,
    private val windowMs: Long = 1000,
    private val spacingMs: Long = 100,
    private val cooldownMs: Long = 2000,
) {
    private val times = ArrayDeque<Long>()
    private var quietUntil = Long.MIN_VALUE

    fun onSample(x: Float, y: Float, z: Float, atMs: Long): Boolean {
        if (atMs < quietUntil) return false
        val g = sqrt((x * x + y * y + z * z).toDouble()) / 9.80665
        if (g <= thresholdG) return false
        if (times.isNotEmpty() && atMs - times.last() < spacingMs) return false
        times.addLast(atMs)
        while (times.isNotEmpty() && atMs - times.first() > windowMs) times.removeFirst()
        if (times.size < jolts) return false
        times.clear()
        quietUntil = atMs + cooldownMs
        return true
    }
}

/** How the channel and the product's own `deliver` become one sender. With a `deliver` the package makes no network call of its own. */
internal sealed class Route {
    class Product(val deliver: (ReviewUpload) -> Boolean) : Route()
    class Channel(val config: ChannelConfig) : Route()
}

internal fun routeFor(config: ReviewConfig): Route? {
    config.deliver?.let { return Route.Product(it) }
    return parseChannel(config.channelUrl, config.channelKey)?.let { Route.Channel(it) }
}

/** Review mode is on only with a slug and a place to send to. */
internal fun isUsable(config: ReviewConfig): Boolean = isSlug(config.product) && routeFor(config) != null

/** The result of one delivery attempt for a capture, from whichever route is set. */
internal fun deliverWith(route: Route, entry: QueueEntry, transport: Transport = HttpTransport): ChannelResult = when (route) {
    is Route.Channel -> sendCapture(route.config, entry, transport)
    is Route.Product -> try {
        if (route.deliver(ReviewUpload(entry.id, entry.json, entry.png))) ChannelResult.Delivered else ChannelResult.Retry
    } catch (e: Exception) {
        ChannelResult.Retry
    }
}

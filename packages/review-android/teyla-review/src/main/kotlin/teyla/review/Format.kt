package teyla.review

import java.math.BigDecimal
import java.math.RoundingMode
import java.time.Instant
import java.time.temporal.ChronoUnit
import java.util.UUID

/** capture.json, format v1 (docs/REVIEW.md, templates/review/capture.schema.json). The fields are the iOS
 *  and web packages' in the same order. A key that is unknown is absent; `null` is never written. */
internal const val FORMAT_VERSION = 1
internal const val PNG_NAME = "capture.png"
internal const val JSON_NAME = "capture.json"
internal const val MAX_ANCHORS = 200
internal const val MAX_COMMENT = 8000

/** A rectangle in the unit of whoever holds it (px in the registry, dp in a capture). */
internal data class Frame(val x: Double, val y: Double, val width: Double, val height: Double) {
    val isFinite: Boolean get() = x.isFinite() && y.isFinite() && width.isFinite() && height.isFinite()
    val area: Double get() = width * height
}

internal data class Anchor(
    val id: String,
    val role: ReviewRole,
    val bounds: Frame,
    val screen: String? = null,
    val strings: List<String> = emptyList(),
)

internal data class Point(val x: Double, val y: Double)

internal data class ScreenFacts(val width: Double, val height: Double, val scale: Double)

internal data class EnvironmentFacts(
    val os: String,
    val model: String,
    val locale: String,
    val language: String?,
    val dark: Boolean,
    val screen: ScreenFacts,
)

internal data class AppFacts(
    val bundleId: String,
    val name: String?,
    val version: String,
    val build: String,
    val commit: String?,
    val product: String,
    val configuration: String,
)

internal val CONFIGURATIONS = setOf("debug", "play_internal", "local")

internal fun round2(n: Double): Double = BigDecimal.valueOf(n).setScale(2, RoundingMode.HALF_UP).toDouble()

internal fun isSlug(value: String?): Boolean = value != null && Regex("^[a-z][a-z0-9-]{0,39}$").matches(value)

internal fun isCommit(value: String?): Boolean = value != null && Regex("^[0-9a-f]{7,40}$").matches(value)

internal fun isUuid(id: String): Boolean =
    Regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$").matches(id)

/** A random lowercase UUID v4. The channel accepts only lowercase. */
internal fun newId(): String = UUID.randomUUID().toString().lowercase()

/** `YYYY-MM-DDTHH:MM:SSZ`, UTC, no fraction. */
internal fun isoSeconds(at: Instant): String = at.truncatedTo(ChronoUnit.SECONDS).toString()

// ---- JSON: a writer small enough to read, so the library needs no serialization dependency --------------

internal object Json {
    fun quote(s: String): String {
        val b = StringBuilder(s.length + 2).append('"')
        for (c in s) {
            when {
                c == '"' -> b.append("\\\"")
                c == '\\' -> b.append("\\\\")
                c == '\n' -> b.append("\\n")
                c == '\r' -> b.append("\\r")
                c == '\t' -> b.append("\\t")
                c < ' ' || c == ' ' || c == ' ' -> b.append("\\u").append("%04x".format(c.code))
                else -> b.append(c)
            }
        }
        return b.append('"').toString()
    }

    /** A number rounded to two decimals and written without an exponent or a trailing `.0`. */
    fun num(d: Double): String = BigDecimal.valueOf(round2(d)).stripTrailingZeros().toPlainString()

    fun bool(b: Boolean): String = if (b) "true" else "false"

    /** Pairs with a null value are left out. Values are already-encoded JSON. */
    fun obj(vararg pairs: Pair<String, String?>): String =
        pairs.filter { it.second != null }.joinToString(",", "{", "}") { quote(it.first) + ":" + it.second }

    fun arr(items: List<String>): String = items.joinToString(",", "[", "]")
}

private fun frame(f: Frame): String =
    Json.obj("x" to Json.num(f.x), "y" to Json.num(f.y), "width" to Json.num(f.width), "height" to Json.num(f.height))

private fun strings(list: List<String>): String? =
    list.filter { it.isNotEmpty() }.take(20).map { Json.quote(it.take(200)) }.takeIf { it.isNotEmpty() }?.let { Json.arr(it) }

private fun anchor(a: Anchor): String = Json.obj(
    "id" to Json.quote(a.id.take(200)),
    "screen" to a.screen?.takeIf { it.isNotEmpty() }?.let { Json.quote(it.take(200)) },
    "role" to Json.quote(a.role.wire),
    "bounds" to frame(a.bounds),
    "strings" to strings(a.strings),
)

internal class BuildInput(
    val id: String,
    val now: Instant,
    val app: AppFacts,
    val environment: EnvironmentFacts,
    val screen: String?,
    val tap: Point?,
    val region: Frame?,
    /** The anchor under the tap, if any. */
    val element: Anchor?,
    val anchors: List<Anchor>,
    val text: String,
    val input: String,
    val sha256: String,
    val pixelWidth: Int,
    val pixelHeight: Int,
    /** Pixels per point. */
    val pixelScale: Double,
)

/** The capture as the format writes it, keys in the order the iOS package uses. */
internal fun encodeCapture(i: BuildInput): String {
    val e = i.environment
    val a = i.app
    val app = Json.obj(
        "bundle_id" to Json.quote(a.bundleId.take(200)),
        "name" to a.name?.takeIf { it.isNotEmpty() }?.let { Json.quote(it.take(200)) },
        "version" to Json.quote(a.version.take(64)),
        "build" to Json.quote(a.build.take(64)),
        "commit" to a.commit?.takeIf { isCommit(it) }?.let { Json.quote(it) },
        "product" to Json.quote(a.product),
        "configuration" to Json.quote(a.configuration),
    )
    val env = Json.obj(
        "os" to Json.quote(e.os.take(64)),
        "model" to Json.quote(e.model.take(64)),
        "locale" to Json.quote(e.locale.take(64)),
        "language" to e.language?.takeIf { it.length >= 2 }?.let { Json.quote(it.take(16)) },
        "appearance" to Json.quote(if (e.dark) "dark" else "light"),
        "dynamic_type" to Json.quote("unspecified"),
        "screen" to Json.obj(
            "width" to Json.num(e.screen.width),
            "height" to Json.num(e.screen.height),
            "scale" to Json.num(maxOf(1.0, e.screen.scale)),
        ),
    )
    val el = i.element
    val element = el?.let {
        Json.obj(
            "id" to Json.quote(it.id.take(200)),
            "matched_by" to Json.quote("anchor"),
            "screen" to it.screen?.takeIf { s -> s.isNotEmpty() }?.let { s -> Json.quote(s.take(200)) },
            "role" to Json.quote(it.role.wire),
            "bounds" to frame(it.bounds),
            "strings" to strings(it.strings),
        )
    }
    val comment = Json.obj(
        "text" to Json.quote(i.text.take(MAX_COMMENT)),
        "input" to Json.quote(i.input),
        "language" to e.language?.takeIf { it.length >= 2 }?.let { Json.quote(it.take(16)) },
    )
    return Json.obj(
        "v" to FORMAT_VERSION.toString(),
        "id" to Json.quote(i.id),
        "created" to Json.quote(isoSeconds(i.now)),
        "device" to Json.quote("Android"),
        "app" to app,
        "environment" to env,
        "screen" to i.screen?.takeIf { it.isNotEmpty() }?.let { Json.quote(it.take(200)) },
        "tap" to i.tap?.let { Json.obj("x" to Json.num(it.x), "y" to Json.num(it.y)) },
        "region" to i.region?.let { frame(it) },
        "element" to element,
        "anchors" to Json.arr(i.anchors.take(MAX_ANCHORS).map { anchor(it) }),
        "comment" to comment,
        "screenshot" to Json.obj(
            "file" to Json.quote(PNG_NAME),
            "width" to i.pixelWidth.toString(),
            "height" to i.pixelHeight.toString(),
            "scale" to Json.num(maxOf(1.0, i.pixelScale)),
            "sha256" to Json.quote(i.sha256),
        ),
        "microphone" to Json.obj("host_audio_in_use" to Json.bool(false)),
    )
}

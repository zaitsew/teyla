package teyla.review

import java.io.File
import java.time.Instant

/** One capture with every optional field, the same in every test. */
internal object Samples {
    val app = AppFacts("com.example.sampleapp", "Sample App", "1.4.0", "212", "3f9c2ab", "sample-app", "play_internal")
    val env = EnvironmentFacts("Android 15", "Pixel 9", "es_ES", "es", true, ScreenFacts(412.0, 892.0, 2.625))
    val footer = Anchor("sample.list.footer", ReviewRole.Container, Frame(0.0, 800.0, 412.0, 92.0), "sample.list")
    val add = Anchor("sample.list.addButton", ReviewRole.Button, Frame(340.0, 810.0, 56.0, 56.0), "sample.list", listOf("list.add"))
    val id = "3b9f1d2e-6a41-4c7e-9d0a-5e2f8b7c1a64"
    val sha = "0b9e7c0e5f8a1d3c2f6a4b7d9e1c3a5f7b9d1e3c5a7f9b1d3e5c7a9f1b3d5e7c"

    fun input(text: String = "The add button is too small. \"Make\" it bigger.") = BuildInput(
        id = id, now = Instant.parse("2026-11-04T21:14:05.987Z"), app = app, environment = env, screen = "sample.list",
        tap = Point(368.004, 838.0), region = null, element = add, anchors = listOf(footer, add), text = text, input = "text",
        sha256 = sha, pixelWidth = 1082, pixelHeight = 2342, pixelScale = 2.625,
    )

    /** The golden file, in the Teyla repo's tests/fixtures. Null in a copy that has no tests folder. */
    fun golden(): File? = System.getProperty("teyla.fixtures")?.let { File(it, "review-android-capture.json") }
}

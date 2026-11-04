package teyla.review

import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FormatTest {
    @Test fun theGoldenCaptureIsWhatTheEncoderWrites() {
        val json = encodeCapture(Samples.input())
        val golden = Samples.golden() ?: return // a vendored copy has no tests folder
        if (System.getProperty("teyla.golden.update") == "1") golden.writeText(json + "\n")
        assertEquals("tests/fixtures/review-android-capture.json is out of date: rerun with -Dteyla.golden.update=1", golden.readText().trimEnd(), json)
    }

    @Test fun keysComeInTheOrderTheOtherPlatformsWriteThem() {
        val json = encodeCapture(Samples.input())
        val order = listOf("\"v\"", "\"id\"", "\"created\"", "\"device\"", "\"app\"", "\"environment\"", "\"screen\":\"sample", "\"tap\"", "\"element\"", "\"anchors\"", "\"comment\"", "\"screenshot\"", "\"microphone\"")
        var at = -1
        for (k in order) {
            val i = json.indexOf(k, at + 1)
            assertTrue("$k after $at", i > at)
            at = i
        }
    }

    @Test fun theDeviceIsAndroidAndTheTimeHasNoFraction() {
        val json = encodeCapture(Samples.input())
        assertTrue(json.contains("\"device\":\"Android\""))
        assertTrue(json.contains("\"created\":\"2026-11-04T21:14:05Z\""))
    }

    @Test fun anAbsentValueIsLeftOutAndNullIsNeverWritten() {
        val bare = Samples.input().let {
            BuildInput(it.id, it.now, AppFacts("a.b", null, "1", "2", null, "p", "debug"), it.environment.copy(language = null), null, null, null, null, emptyList(), "x", "text", it.sha256, 10, 10, 1.0)
        }
        val json = encodeCapture(bare)
        assertFalse(json.contains("null"))
        for (k in listOf("\"tap\"", "\"region\"", "\"element\"", "\"commit\"", "\"name\"", "\"language\"", "\"screen\":\"")) assertFalse(k, json.contains(k))
        assertTrue(json.contains("\"anchors\":[]"))
    }

    @Test fun numbersAreRoundedToTwoDecimalsWithoutAnExponent() {
        assertEquals("368", Json.num(368.004))
        assertEquals("331.5", Json.num(331.5))
        assertEquals("0.01", Json.num(0.005))
        assertEquals("12345678", Json.num(12345678.0))
        assertEquals("2.63", Json.num(2.625))
    }

    @Test fun textIsEscaped() {
        assertEquals("\"a\\\"b\\\\c\\n\\u0001\"", Json.quote("a\"b\\c\n\u0001"))
        val json = encodeCapture(Samples.input("line1\nline2 \"q\" \\ é ✓"))
        assertTrue(json.contains("line1\\nline2 \\\"q\\\" \\\\ é ✓"))
    }

    @Test fun aBadCommitIsDroppedAndTheScaleIsAtLeastOne() {
        val i = Samples.input()
        val json = encodeCapture(BuildInput(i.id, i.now, i.app.copy(commit = "XYZ"), i.environment.copy(screen = ScreenFacts(400.0, 800.0, 0.75)), i.screen, i.tap, null, null, i.anchors, "x", "text", i.sha256, 10, 10, 0.75))
        assertFalse(json.contains("commit"))
        assertTrue(json.contains("\"scale\":1}"))
    }

    @Test fun theCommentIsCutAtEightThousandCharactersAndAnchorsAtTwoHundred() {
        val i = Samples.input("x".repeat(9000))
        val many = (1..250).map { Anchor("a.$it", ReviewRole.Other, Frame(0.0, 0.0, 1.0, 1.0)) }
        val json = encodeCapture(BuildInput(i.id, i.now, i.app, i.environment, null, null, null, null, many, i.text, "text", i.sha256, 1, 1, 1.0))
        assertEquals(8000, Regex("x{100,}").find(json.substringAfter("\"comment\""))!!.value.length)
        assertEquals(200, Regex("\"id\":\"a\\.").findAll(json).count())
    }

    @Test fun idsSlugsAndCommits() {
        assertTrue(isUuid(newId()))
        assertFalse(isUuid(newId().uppercase()))
        assertTrue(isSlug("sample-app")); assertTrue(isSlug("a-1")); assertFalse(isSlug("Sample")); assertFalse(isSlug("1a")); assertFalse(isSlug("a".repeat(41)))
        assertTrue(isCommit("3f9c2ab")); assertFalse(isCommit("3f9c2a")); assertFalse(isCommit("3F9C2AB"))
        assertEquals("2026-11-04T21:14:05Z", isoSeconds(Instant.parse("2026-11-04T21:14:05.999Z")))
        assertEquals("2026-11-04T21:14:00Z", isoSeconds(Instant.parse("2026-11-04T21:14:00Z")))
    }
}

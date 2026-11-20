package teyla.review

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Runs the one list of cases every platform reads: packages/review-channel/test-vectors/scrub.json. A vendored copy has
 *  no tests folder, so the file is absent there and the vector tests do nothing. */
class ScrubTest {
    private class Case(val name: String, val input: String, val expected: String)

    private fun vectors(): Pair<List<Case>, List<Case>>? {
        val dir = System.getProperty("teyla.vectors") ?: return null
        val file = File(dir, "scrub.json").takeIf { it.isFile } ?: return null
        val text = file.readText(Charsets.UTF_8)
        return section(text, "text") to section(text, "label")
    }

    /** A reader just big enough for this one file: an array of objects whose three keys hold JSON strings. */
    private fun section(text: String, key: String): List<Case> {
        val start = text.indexOf("\"$key\": [")
        require(start >= 0) { key }
        val end = text.indexOf("\n ]", start)
        val body = text.substring(start, end)
        val cases = ArrayList<Case>()
        var i = 0
        while (true) {
            val at = body.indexOf("\"name\": ", i)
            if (at < 0) break
            val (name, a) = string(body, at + 8)
            val (input, b) = string(body, body.indexOf("\"input\": ", a) + 9)
            val (expected, c) = string(body, body.indexOf("\"expected\": ", b) + 12)
            cases.add(Case(name, input, expected))
            i = c
        }
        return cases
    }

    /** The JSON string that starts at [from] (an opening quote), and the index after it. */
    private fun string(s: String, from: Int): Pair<String, Int> {
        require(s[from] == '"')
        val b = StringBuilder()
        var i = from + 1
        while (s[i] != '"') {
            if (s[i] == '\\') {
                i++
                when (val e = s[i]) {
                    'n' -> b.append('\n'); 't' -> b.append('\t'); 'r' -> b.append('\r')
                    'u' -> { b.append(s.substring(i + 1, i + 5).toInt(16).toChar()); i += 4 }
                    else -> b.append(e)
                }
            } else b.append(s[i])
            i++
        }
        return b.toString() to i + 1
    }

    @Test fun theSharedTextVectorsPass() {
        val (text, _) = vectors() ?: return
        assertTrue("the vectors were read", text.size >= 30)
        for (c in text) {
            assertEquals(c.name, c.expected, scrub(c.input))
            assertEquals(c.name + " (twice)", c.expected, scrub(c.expected))
        }
    }

    @Test fun theSharedLabelVectorsPass() {
        val (_, labels) = vectors() ?: return
        assertTrue(labels.size >= 3)
        for (c in labels) assertEquals(c.name, c.expected, scrubLabel(c.input))
    }

    @Test fun theLabelCapIsTwoHundred() = assertEquals(200, LABEL_CAP)

    @Test fun aCaptureCarriesNoRawEmailPhoneOrTokenInAnyTextField() {
        val secretAnchor = Samples.add.copy(id = "id.jane@example.com", strings = listOf("jane@example.com", "ok"))
        val i = Samples.input("mail jane@example.com, key sk_live_abcdefghijklmnop1234, https://example.com/x?token=abc")
        val json = encodeCapture(
            BuildInput(i.id, i.now, i.app, i.environment, "page jane@example.com", i.tap, null, secretAnchor,
                listOf(Samples.footer, secretAnchor), i.text, "text", i.sha256, 10, 10, 1.0),
        )
        for (raw in listOf("jane@example.com", "sk_live_abcdefghijklmnop1234", "token=abc")) assertFalse(raw, json.contains(raw))
        assertTrue(json.contains("mail [email], key [token], https://example.com/x?token=[token]"))
    }
}

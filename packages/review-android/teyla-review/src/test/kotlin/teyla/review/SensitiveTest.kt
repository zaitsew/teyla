package teyla.review

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** SEC-9: password, card and one-time-code fields are masked without `reviewPrivate()`. The rules and their place in the
 *  registry run here; reading a live window (`SensitiveViews`) needs a device and is not covered by a JVM test. */
class SensitiveTest {
    // android.text.InputType: TYPE_CLASS_TEXT 1, TYPE_CLASS_NUMBER 2, TYPE_CLASS_PHONE 3, variations 0x80 / 0x90 / 0xe0 / 0x10.
    @Test fun passwordInputTypesAreSensitive() {
        assertTrue(isSensitiveInputType(0x1 or 0x80))     // textPassword
        assertTrue(isSensitiveInputType(0x1 or 0x90))     // textVisiblePassword
        assertTrue(isSensitiveInputType(0x1 or 0xe0))     // textWebPassword
        assertTrue(isSensitiveInputType(0x2 or 0x10))     // numberPassword
        assertTrue(isSensitiveInputType(0x1 or 0x80 or 0x8000)) // flags do not hide it
    }

    @Test fun otherInputTypesAreNot() {
        assertFalse(isSensitiveInputType(0x1))            // plain text
        assertFalse(isSensitiveInputType(0x1 or 0x20))    // email address
        assertFalse(isSensitiveInputType(0x2))            // number
        assertFalse(isSensitiveInputType(0x2 or 0x2000))  // signed decimal number
        assertFalse(isSensitiveInputType(0x3))            // phone
        assertFalse(isSensitiveInputType(0))
    }

    @Test fun secretAutofillHintsAreSensitive() {
        for (h in listOf("password", "newPassword", "creditCardNumber", "creditCardSecurityCode", "smsOTPCode")) {
            assertTrue(h, isSensitiveField(0x1, arrayOf("username", h)))
        }
        assertFalse(isSensitiveField(0x1, arrayOf("username", "emailAddress")))
        assertFalse(isSensitiveField(0x1, null))
        assertTrue(isSensitiveField(0x1, null, hidesText = true))
    }

    @Test fun aSensitiveFieldIsMaskedLikeAPrivateAreaAndHidesTheStringsUnderIt() {
        val r = Registry()
        r.add(Kind.Anchor, "login.form", ReviewRole.Container, listOf("login.title"), { Frame(0.0, 0.0, 400.0, 400.0) })
        val s = r.snapshot(400.0, 800.0, 2.0) { listOf(Frame(100.0, 200.0, 200.0, 60.0)) }
        // 2 px per dp: the field is 50, 100, 100 x 30 dp, grown by the 2 dp margin.
        assertEquals(listOf(Frame(48.0, 98.0, 104.0, 34.0)), s.privateFrames)
        assertTrue(s.anchors[0].strings.isEmpty())
    }

    @Test fun aSensitiveFieldOffTheWindowHidesNothingAndATappedOneRecordsNoElement() {
        val r = Registry()
        assertTrue(r.snapshot(400.0, 800.0, 1.0) { listOf(Frame(900.0, 0.0, 10.0, 10.0)) }.privateFrames.isEmpty())
        val s = r.snapshot(400.0, 800.0, 1.0) { listOf(Frame(10.0, 10.0, 100.0, 30.0)) }
        assertTrue(touchesPrivate(Point(50.0, 20.0), null, s.privateFrames))
    }

    @Test fun aScanThatFailsHidesTheWholePicture() {
        val r = Registry()
        val s = r.snapshot(400.0, 800.0, 1.0) { throw IllegalStateException("no window") }
        assertEquals(1, s.privateFrames.size)
        assertFalse(s.privateFrames[0].isFinite)
    }
}

package teyla.review

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class GateTest {
    // android.content.res.Configuration: UI_MODE_TYPE_NORMAL 1, DESK 2, CAR 3, TELEVISION 4, APPLIANCE 5, WATCH 6, VR_HEADSET 7
    @Test fun onlyTheTelevisionModeIsATelevision() {
        assertTrue(isTelevision(4))
        assertTrue(isTelevision(0x14)) // night bits set above the type
        for (t in listOf(0, 1, 2, 3, 5, 6, 7)) assertFalse("$t", isTelevision(t))
    }

    @Test fun aTelevisionHasTheSettingsRowAndNoShake() {
        assertEquals(EntryPoints(settingsRow = true, shake = false), entryPoints(4, hasAccelerometer = true, shakeRequested = true))
    }

    @Test fun aPhoneShakesWhenItHasAnAccelerometerAndTheProductAsksForIt() {
        assertEquals(EntryPoints(true, true), entryPoints(1, true, true))
        assertEquals(EntryPoints(true, false), entryPoints(1, false, true))
        assertEquals(EntryPoints(true, false), entryPoints(1, true, false))
    }

    private val shake = 9.80665f * 3f // 3 g along one axis

    @Test fun threeJoltsInOneSecondAreAShake() {
        val d = ShakeDetector()
        assertFalse(d.onSample(shake, 0f, 0f, 1000))
        assertFalse(d.onSample(-shake, 0f, 0f, 1200))
        assertTrue(d.onSample(shake, 0f, 0f, 1400))
    }

    @Test fun joltsTooFarApartOrTooCloseTogetherAreNot() {
        val far = ShakeDetector()
        assertFalse(far.onSample(shake, 0f, 0f, 0)); assertFalse(far.onSample(shake, 0f, 0f, 600)); assertFalse(far.onSample(shake, 0f, 0f, 1200))
        val close = ShakeDetector()
        for (t in 0..90 step 10) assertFalse(close.onSample(shake, 0f, 0f, t.toLong())) // one jolt, sampled often
    }

    @Test fun gravityAndAWalkAreNotAShake() {
        val d = ShakeDetector()
        for (t in 0..5000 step 20) assertFalse(d.onSample(0f, 9.80665f, 0f, t.toLong()))
        for (t in 0..5000 step 200) assertFalse(d.onSample(0f, 9.80665f * 1.8f, 0f, t.toLong()))
    }

    @Test fun afterAShakeTheDetectorIsQuietForTwoSeconds() {
        val d = ShakeDetector()
        d.onSample(shake, 0f, 0f, 1000); d.onSample(shake, 0f, 0f, 1200)
        assertTrue(d.onSample(shake, 0f, 0f, 1400))
        for (t in listOf(1600L, 1800L, 2000L, 2200L, 2400L, 3300L)) assertFalse("$t", d.onSample(shake, 0f, 0f, t))
        assertFalse(d.onSample(shake, 0f, 0f, 3500)); assertFalse(d.onSample(shake, 0f, 0f, 3700))
        assertTrue(d.onSample(shake, 0f, 0f, 3900))
    }
}

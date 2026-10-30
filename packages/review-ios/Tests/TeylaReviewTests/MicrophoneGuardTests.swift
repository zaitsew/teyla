import XCTest
@testable import TeylaReview

private final class FakeSession: AudioSessionControlling {
    var categoryName = "AVAudioSessionCategoryPlayback"
    var modeName = "AVAudioSessionModeDefault"
    var optionsRaw: UInt = 0
    var active: Bool?
    var restores: [(String, String, UInt)] = []
    var failRestore = false

    func restore(category: String, mode: String, options: UInt) throws {
        if failRestore { throw NSError(domain: "fake", code: 1) }
        restores.append((category, mode, options))
        categoryName = category; modeName = mode; optionsRaw = options
    }

    func setActive(_ active: Bool) throws { self.active = active }
}

final class MicrophoneGuardTests: XCTestCase {
    func testBeginRecordsTheHostState() {
        let s = FakeSession()
        s.categoryName = "AVAudioSessionCategoryPlayAndRecord"
        let g = MicrophoneGuard(session: s)
        let state = g.begin()
        XCTAssertTrue(state.hostAudioInUse)                       // record-capable category, no closure: assume in use
        XCTAssertEqual(g.info, MicrophoneInfo(hostAudioInUse: true, category: "AVAudioSessionCategoryPlayAndRecord"))
    }

    func testThePlaybackCategoryIsNotMicrophoneUse() {
        let g = MicrophoneGuard(session: FakeSession())
        XCTAssertFalse(g.begin().hostAudioInUse)
    }

    func testTheProductsOwnAnswerWins() {
        let s = FakeSession()
        s.categoryName = "AVAudioSessionCategoryPlayAndRecord"
        XCTAssertFalse(MicrophoneGuard(session: s, hostAudioInUse: { false }).begin().hostAudioInUse)
        XCTAssertTrue(MicrophoneGuard(session: FakeSession(), hostAudioInUse: { true }).begin().hostAudioInUse)
    }

    func testEndTouchesNothingWhenReviewModeNeverTookTheMicrophone() {
        let s = FakeSession()
        let g = MicrophoneGuard(session: s)
        g.begin()
        XCTAssertTrue(g.end())
        XCTAssertTrue(s.restores.isEmpty)
        XCTAssertNil(s.active)
    }

    func testEndRestoresWhatSpeechCaptureChanged() {
        let s = FakeSession()
        s.categoryName = "AVAudioSessionCategoryPlayAndRecord"
        s.modeName = "AVAudioSessionModeVoiceChat"
        s.optionsRaw = 4
        let g = MicrophoneGuard(session: s, hostAudioInUse: { true })
        g.begin()
        g.markTaken()
        s.categoryName = "AVAudioSessionCategoryRecord"; s.modeName = "AVAudioSessionModeMeasurement"; s.optionsRaw = 0
        XCTAssertTrue(g.end())
        XCTAssertEqual(s.restores.count, 1)
        XCTAssertEqual(s.restores[0].0, "AVAudioSessionCategoryPlayAndRecord")
        XCTAssertEqual(s.restores[0].1, "AVAudioSessionModeVoiceChat")
        XCTAssertEqual(s.restores[0].2, 4)
        XCTAssertEqual(s.active, true)                              // the product was using it: leave it active
    }

    func testEndDeactivatesWhenTheProductWasNotUsingTheMicrophone() {
        let s = FakeSession()
        let g = MicrophoneGuard(session: s, hostAudioInUse: { false })
        g.begin()
        g.markTaken()
        s.categoryName = "AVAudioSessionCategoryRecord"
        XCTAssertTrue(g.end())
        XCTAssertEqual(s.categoryName, "AVAudioSessionCategoryPlayback")
        XCTAssertEqual(s.active, false)
    }

    func testEndReportsARefusalAndForgetsTheState() {
        let s = FakeSession()
        s.failRestore = true
        let g = MicrophoneGuard(session: s)
        g.begin()
        g.markTaken()
        XCTAssertFalse(g.end())
        XCTAssertNil(g.saved)
        XCTAssertTrue(g.end())                                      // a second end has nothing to do
    }
}

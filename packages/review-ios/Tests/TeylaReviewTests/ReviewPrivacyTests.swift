import XCTest
@testable import TeylaReview

final class ReviewPrivacyTests: XCTestCase {
    private func defaults() -> UserDefaults { UserDefaults(suiteName: "teyla.review.tests." + UUID().uuidString)! }

    // MARK: the first-send notice

    func testTheNoticeIsNeededOnceAndOnlyWhenACaptureCanLeave() {
        let d = defaults()
        XCTAssertTrue(ReviewNotice.isNeeded(sendsToServer: true, defaults: d))
        XCTAssertFalse(ReviewNotice.isNeeded(sendsToServer: false, defaults: d))     // relay only: the owner's own devices
        ReviewNotice.accept(defaults: d)
        XCTAssertFalse(ReviewNotice.isNeeded(sendsToServer: true, defaults: d))
        XCTAssertTrue(ReviewNotice.isAccepted(defaults: d))
    }

    func testTheNoticeSaysWhatWhoWhyAndHowLong() {
        let text = ReviewStrings().noticeMessage
        XCTAssertTrue(text.contains("picture of this screen"))
        XCTAssertTrue(text.contains("Who gets it"))
        XCTAssertTrue(text.contains("Why:"))
        XCTAssertTrue(text.contains("within the hour"))
        XCTAssertTrue(text.contains("30 days after the report is closed"))
        XCTAssertTrue(text.contains("90 days if it is never opened"))
    }

    func testAProductCanReplaceEveryNoticeWord() {
        var s = ReviewStrings()
        s.noticeCaptured = "A"; s.noticeRecipient = "B"; s.noticeWhy = "C"; s.noticeRetention = "D"
        XCTAssertEqual(s.noticeMessage, "A\n\nB\n\nC\n\nD")
    }

    // MARK: the health checkbox

    func testSendNeedsACommentAndTheHealthBoxWhenRequired() {
        XCTAssertFalse(ReviewNotice.canSend(comment: "  ", sending: false, requiresHealthConsent: false, healthConsentGiven: false))
        XCTAssertTrue(ReviewNotice.canSend(comment: "x", sending: false, requiresHealthConsent: false, healthConsentGiven: false))
        XCTAssertFalse(ReviewNotice.canSend(comment: "x", sending: false, requiresHealthConsent: true, healthConsentGiven: false))
        XCTAssertTrue(ReviewNotice.canSend(comment: "x", sending: false, requiresHealthConsent: true, healthConsentGiven: true))
        XCTAssertFalse(ReviewNotice.canSend(comment: "x", sending: true, requiresHealthConsent: false, healthConsentGiven: true))
    }

    func testHealthConsentIsOffByDefault() {
        XCTAssertFalse(TeylaReview.Configuration().requiresHealthConsent)
    }

    // MARK: the product slug

    func testTheProductComesFromTheConfigurationThenThePlist() {
        XCTAssertEqual(AppProbe.product(configured: "sample-app", plist: "other"), "sample-app")
        XCTAssertEqual(AppProbe.product(configured: nil, plist: " my-app "), "my-app")
        XCTAssertNil(AppProbe.product(configured: nil, plist: nil))
        XCTAssertNil(AppProbe.product(configured: nil, plist: "$(PRODUCT_SLUG)"))
        XCTAssertNil(AppProbe.product(configured: "Not A Slug", plist: nil))
        XCTAssertEqual(AppProbe.product(configured: "Bad", plist: "good-1"), "good-1")
        XCTAssertNil(AppProbe.product(configured: String(repeating: "a", count: 41), plist: nil))
        XCTAssertNotNil(AppProbe.product(configured: String(repeating: "a", count: 40), plist: nil))
        XCTAssertNil(AppProbe.product(configured: "1abc", plist: nil))
    }

    func testTheProductIsInTheJSONOnlyWhenSet() throws {
        var app = Fixtures.app
        var json = String(decoding: try CaptureCoding.encoder().encode(app), as: UTF8.self)
        XCTAssertFalse(json.contains("\"product\""))
        app.product = "sample-app"
        json = String(decoding: try CaptureCoding.encoder().encode(app), as: UTF8.self)
        XCTAssertTrue(json.contains("\"product\" : \"sample-app\""))
    }

    // MARK: masking

    func testAFrameIsGrownSnappedAndCutToTheWindow() {
        let window = CGRect(x: 0, y: 0, width: 390, height: 844)
        let out = ReviewMasking.rects(for: [CGRect(x: 20.3, y: 100.1, width: 100, height: 20)], in: window, scale: 3)
        XCTAssertEqual(out.count, 1)
        let r = out[0]
        XCTAssertTrue(r.contains(CGRect(x: 20.3, y: 100.1, width: 100, height: 20)))          // never smaller than the view
        XCTAssertLessThanOrEqual(r.minX, 20.3 - ReviewMasking.padding + 0.001)
        XCTAssertGreaterThanOrEqual(r.minX, 20.3 - ReviewMasking.padding - 1.0 / 3)           // and no bigger than a pixel past the margin
        XCTAssertEqual((r.minX * 3).rounded(), r.minX * 3, accuracy: 1e-9)                    // on a whole pixel
        XCTAssertEqual((r.maxY * 3).rounded(), r.maxY * 3, accuracy: 1e-9)
    }

    func testAFrameHalfOutsideTheWindowIsCut() {
        let window = CGRect(x: 0, y: 0, width: 390, height: 844)
        let out = ReviewMasking.rects(for: [CGRect(x: 350, y: 800, width: 100, height: 100)], in: window, scale: 2)
        XCTAssertEqual(out, [CGRect(x: 348, y: 798, width: 42, height: 46)])
    }

    func testEmptyOffscreenAndBrokenFramesAreDropped() {
        let window = CGRect(x: 0, y: 0, width: 390, height: 844)
        let frames = [CGRect.zero, CGRect(x: 10, y: 10, width: 0, height: 50), CGRect(x: 1000, y: 1000, width: 40, height: 40),
                      CGRect.null, CGRect(x: -500, y: 0, width: 100, height: 100)]
        XCTAssertEqual(ReviewMasking.rects(for: frames, in: window, scale: 3), [])
        XCTAssertEqual(ReviewMasking.rects(for: [CGRect(x: 0, y: 0, width: 10, height: 10)], in: window, scale: 0), [])
    }

    func testTheRegistryReadsFramesWhenAskedAndDropsGoneViews() {
        let r = PrivateRegistry()
        let a = UUID(), b = UUID(), c = UUID()
        var aFrame: CGRect? = CGRect(x: 0, y: 0, width: 50, height: 20)
        r.register(token: a, bounds: { aFrame })
        r.register(token: b, bounds: { nil })                                   // the view is gone
        r.register(token: c, bounds: { CGRect(x: 5, y: 5, width: 0, height: 0) })   // in another tab: no area
        XCTAssertEqual(r.snapshot(), [CGRect(x: 0, y: 0, width: 50, height: 20)])
        aFrame = CGRect(x: 0, y: 300, width: 50, height: 20)                    // it scrolled
        XCTAssertEqual(r.snapshot(), [CGRect(x: 0, y: 300, width: 50, height: 20)])
        r.remove(token: a)
        XCTAssertEqual(r.snapshot(), [])
    }

    // MARK: nothing about a private view reaches capture.json

    private let frames = [CGRect(x: 20, y: 100, width: 200, height: 40)]
    private func anchor(_ id: String, _ rect: CGRect, strings: [String]) -> Anchor {
        Fixtures.anchor(id, rect, strings: strings)
    }

    func testATapInsideAPrivateRegionKeepsNoElementIdentifierOrLabel() {
        let hit = anchor("profile.weight", CGRect(x: 20, y: 100, width: 200, height: 40), strings: ["profile.weight.title"])
        let out = ReviewRedaction.pointed(hit: hit, identifier: "weightValue", label: "Weight 72 kg",
                                          point: CGPoint(x: 50, y: 120), region: nil, frames: frames)
        XCTAssertNil(out.hit); XCTAssertNil(out.identifier); XCTAssertNil(out.label)
    }

    func testACircledAreaThatTouchesAPrivateRegionKeepsNothingEither() {
        let out = ReviewRedaction.pointed(hit: anchor("a", .zero, strings: []), identifier: "x", label: "y",
                                          point: CGPoint(x: 300, y: 300), region: CGRect(x: 200, y: 130, width: 150, height: 200), frames: frames)
        XCTAssertNil(out.hit); XCTAssertNil(out.identifier); XCTAssertNil(out.label)
    }

    func testATapOutsideEveryPrivateRegionIsUnchanged() {
        let hit = anchor("list.add", CGRect(x: 300, y: 700, width: 60, height: 60), strings: ["list.add"])
        let out = ReviewRedaction.pointed(hit: hit, identifier: "add", label: "Add", point: CGPoint(x: 330, y: 730), region: nil, frames: frames)
        XCTAssertEqual(out.hit, hit); XCTAssertEqual(out.identifier, "add"); XCTAssertEqual(out.label, "Add")
        XCTAssertEqual(ReviewRedaction.pointed(hit: hit, identifier: "add", label: "Add", point: CGPoint(x: 330, y: 730), region: nil, frames: []).label, "Add")
    }

    func testAnAnchorThatOverlapsAPrivateRegionLosesItsStringKeys() {
        let over = anchor("profile.row", CGRect(x: 0, y: 90, width: 390, height: 60), strings: ["profile.weight.value"])
        let clear = anchor("list.add", CGRect(x: 300, y: 700, width: 60, height: 60), strings: ["list.add"])
        let out = ReviewRedaction.anchors([over, clear], frames: frames)
        XCTAssertEqual(out[0].strings, [])
        XCTAssertEqual(out[0].id, "profile.row")
        XCTAssertEqual(out[1].strings, ["list.add"])
    }

    func testTheWrittenCaptureHoldsNoTraceOfAPrivateTap() throws {
        let hit = anchor("profile.weight", CGRect(x: 20, y: 100, width: 200, height: 40), strings: ["profile.weight.title"])
        let anchors = ReviewRedaction.anchors([hit], frames: frames)
        let out = ReviewRedaction.pointed(hit: hit, identifier: "weightValue", label: "Weight 72 kg",
                                          point: CGPoint(x: 50, y: 120), region: nil, frames: frames)
        let record = CaptureBuilder.make(
            now: Date(), device: "iPhone", app: Fixtures.app, environment: Fixtures.environment, screen: "profile",
            tap: TapInfo(x: 50, y: 120, accessibilityIdentifier: out.identifier, accessibilityLabel: out.label),
            element: out.hit, accessibilityElementID: out.identifier, anchors: anchors, text: "wrong", input: .text, language: "en",
            pngSHA256: String(repeating: "0", count: 64), pixelWidth: 390, pixelHeight: 844, scale: 1,
            microphone: MicrophoneInfo(hostAudioInUse: false, category: nil))
        let json = String(decoding: try CaptureCoding.encoder().encode(record), as: UTF8.self)
        for secret in ["Weight 72 kg", "weightValue", "profile.weight.title"] { XCTAssertFalse(json.contains(secret), secret) }
        XCTAssertNil(record.element)
    }
}

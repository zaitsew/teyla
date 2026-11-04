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
}

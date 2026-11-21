import XCTest
@testable import TeylaReview

/// The scrub rules (`ReviewScrub`) against the one list of cases every platform reads:
/// packages/review-channel/test-vectors/scrub.json.
final class ReviewScrubTests: XCTestCase {
    private struct Case: Decodable { let name: String; let input: String; let expected: String }
    private struct Vectors: Decodable { let text: [Case]; let label: [Case] }

    private func vectors() throws -> Vectors {
        let url = Fixtures.repoRoot.appendingPathComponent("packages/review-channel/test-vectors/scrub.json")
        return try JSONDecoder().decode(Vectors.self, from: Data(contentsOf: url))
    }

    func testTheSharedTextVectorsPass() throws {
        let cases = try vectors().text
        XCTAssertGreaterThanOrEqual(cases.count, 30)
        for c in cases {
            XCTAssertEqual(ReviewScrub.scrub(c.input), c.expected, c.name)
            XCTAssertEqual(ReviewScrub.scrub(c.expected), c.expected, c.name + " (twice)")
        }
    }

    func testTheSharedLabelVectorsPass() throws {
        let cases = try vectors().label
        XCTAssertGreaterThanOrEqual(cases.count, 3)
        for c in cases { XCTAssertEqual(ReviewScrub.scrubLabel(c.input), c.expected, c.name) }
    }

    func testTheLabelCapIsTwoHundred() { XCTAssertEqual(ReviewScrub.labelCap, 200) }

    // MARK: every text field of a capture

    func testACaptureCarriesNoRawEmailPhoneOrTokenInAnyTextField() throws {
        let anchor = Anchor(id: "id.jane@example.com", screen: "screen jane@example.com", parent: nil, role: .button,
                            bounds: CGRect(x: 0, y: 0, width: 10, height: 10), strings: ["jane@example.com", "ok"],
                            file: "A.swift", line: 1, seq: 0)
        let tap = TapInfo(x: 1, y: 2, accessibilityIdentifier: "ident +34 600 123 456",
                          accessibilityLabel: "label jane@example.com " + String(repeating: "q", count: 300))
        let record = CaptureBuilder.make(
            now: Date(timeIntervalSince1970: 0), device: "iPhone", app: Fixtures.app, environment: Fixtures.environment,
            screen: "page jane@example.com", tap: tap, element: anchor, accessibilityElementID: nil, anchors: [anchor],
            text: "mail jane@example.com, key sk_live_abcdefghijklmnop1234, https://example.com/x?token=abc", input: .text,
            language: "en", pngSHA256: String(repeating: "0", count: 64), pixelWidth: 1, pixelHeight: 1, scale: 1,
            microphone: MicrophoneInfo(hostAudioInUse: false, category: nil))
        let json = String(decoding: try CaptureCoding.encoder().encode(record), as: UTF8.self)
        for raw in ["jane@example.com", "sk_live_abcdefghijklmnop1234", "token=abc", "600 123 456"] {
            XCTAssertFalse(json.contains(raw), raw)
        }
        XCTAssertEqual(record.comment.text, "mail [email], key [token], https://example.com/x?token=[token]")
        XCTAssertEqual(record.tap?.accessibilityIdentifier, "ident [phone]")
        let label = try XCTUnwrap(record.tap?.accessibilityLabel)
        XCTAssertEqual(label.count, 200, "the label is cut to 200 characters")
        XCTAssertTrue(label.hasPrefix("label [email] qqq"))
    }

    func testAnUncappedAccessibilityLabelIsCut() {
        let tap = TapInfo(x: 0, y: 0, accessibilityIdentifier: nil, accessibilityLabel: String(repeating: "x", count: 5000))
        let record = CaptureBuilder.make(
            now: Date(timeIntervalSince1970: 0), device: "iPhone", app: Fixtures.app, environment: Fixtures.environment,
            screen: nil, tap: tap, element: nil, accessibilityElementID: nil, anchors: [], text: "t", input: .text, language: nil,
            pngSHA256: String(repeating: "0", count: 64), pixelWidth: 1, pixelHeight: 1, scale: 1,
            microphone: MicrophoneInfo(hostAudioInUse: false, category: nil))
        XCTAssertEqual(record.tap?.accessibilityLabel?.count, 200)
    }
}

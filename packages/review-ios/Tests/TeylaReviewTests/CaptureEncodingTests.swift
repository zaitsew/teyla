import CoreGraphics
import XCTest
@testable import TeylaReview

final class CaptureEncodingTests: XCTestCase {
    private func object(_ r: CaptureRecord) throws -> [String: Any] {
        try JSONSerialization.jsonObject(with: CaptureCoding.encoder().encode(r)) as! [String: Any]
    }

    private let button = Fixtures.anchor("sample.list.addButton", CGRect(x: 300, y: 752, width: 60, height: 60), seq: 2,
                                         parent: "sample.list.footer", strings: ["list.add"])

    func testTopLevelKeysAreTheSchemasRequiredKeysPlusTheOptionalOnesWeFill() throws {
        let json = try object(Fixtures.record(element: button, anchors: [button]))
        let schema = try JSONSerialization.jsonObject(
            with: Data(contentsOf: Fixtures.repoRoot.appendingPathComponent("templates/review/capture.schema.json"))) as! [String: Any]
        let required = Set(schema["required"] as! [String])
        let allowed = Set((schema["properties"] as! [String: Any]).keys)
        let keys = Set(json.keys)
        XCTAssertTrue(required.isSubset(of: keys), "missing: \(required.subtracting(keys))")
        XCTAssertTrue(keys.isSubset(of: allowed), "unknown: \(keys.subtracting(allowed))")
    }

    func testKeysAreSnakeCaseAndNilIsLeftOut() throws {
        let json = try object(Fixtures.record())
        XCTAssertEqual(json["v"] as? Int, 1)
        XCTAssertNil(json["element"])
        let app = json["app"] as! [String: Any]
        XCTAssertEqual(app["bundle_id"] as? String, "com.example.sampleapp")
        XCTAssertEqual(app["configuration"] as? String, "testflight")
        let env = json["environment"] as! [String: Any]
        XCTAssertEqual(env["dynamic_type"] as? String, "large")
        let mic = json["microphone"] as! [String: Any]
        XCTAssertEqual(mic["host_audio_in_use"] as? Bool, false)
        let tap = json["tap"] as! [String: Any]
        XCTAssertNil(tap["accessibility_identifier"])
        XCTAssertFalse(json.values.contains { $0 is NSNull })
    }

    func testElementFromAnAnchor() throws {
        let json = try object(Fixtures.record(element: button, anchors: [button]))
        let el = json["element"] as! [String: Any]
        XCTAssertEqual(el["id"] as? String, "sample.list.addButton")
        XCTAssertEqual(el["matched_by"] as? String, "anchor")
        XCTAssertEqual(el["parent"] as? String, "sample.list.footer")
        XCTAssertEqual(el["role"] as? String, "button")
        XCTAssertEqual(el["strings"] as? [String], ["list.add"])
        let bounds = el["bounds"] as! [String: Double]
        XCTAssertEqual(bounds, ["x": 300, "y": 752, "width": 60, "height": 60])
        let source = el["source"] as! [String: Any]
        XCTAssertEqual(source["file"] as? String, "SampleApp/ListView.swift")
        XCTAssertEqual(source["line"] as? Int, 12)
    }

    func testElementFromAnAccessibilityIdentifierWhenNoAnchorMatches() throws {
        let r = CaptureBuilder.make(
            now: Date(), device: "iPhone", app: Fixtures.app, environment: Fixtures.environment, screen: nil, tap: nil,
            element: nil, accessibilityElementID: "legacyButton", anchors: [], text: "x", input: .speech, language: nil,
            pngSHA256: String(repeating: "a", count: 64), pixelWidth: 1, pixelHeight: 1, scale: 1,
            microphone: MicrophoneInfo(hostAudioInUse: true, category: nil))
        let json = try object(r)
        let el = json["element"] as! [String: Any]
        XCTAssertEqual(el["id"] as? String, "legacyButton")
        XCTAssertEqual(el["matched_by"] as? String, "accessibility_identifier")
        XCTAssertNil(el["bounds"])
        XCTAssertEqual((json["comment"] as! [String: Any])["input"] as? String, "speech")
    }

    func testNumbersAreRoundedToTwoDecimals() throws {
        let a = Fixtures.anchor("a.b", CGRect(x: 10.123456, y: 20.999, width: 30.004, height: 40), seq: 1)
        let el = try object(Fixtures.record(element: a))["element"] as! [String: Any]
        XCTAssertEqual(el["bounds"] as! [String: Double], ["x": 10.12, "y": 21, "width": 30, "height": 40])
    }

    func testCommentIsCappedAndAnchorsAreCapped() throws {
        let many = (0..<250).map { Fixtures.anchor("a.n\($0)", CGRect(x: 0, y: 0, width: 5, height: 5), seq: $0) }
        let r = Fixtures.record(anchors: many, text: String(repeating: "x", count: 9000))
        XCTAssertEqual(r.anchors.count, 200)
        XCTAssertEqual(r.comment.text.count, 8000)
    }

    func testRoundTrip() throws {
        let r = Fixtures.record(element: button, anchors: [button])
        let back = try CaptureCoding.decoder().decode(CaptureRecord.self, from: CaptureCoding.encoder().encode(r))
        XCTAssertEqual(back, r)
    }

    func testIdIsLowercaseUUIDAndCreatedIsUTCSeconds() {
        let r = Fixtures.record(id: UUID(uuidString: "3B9F1D2E-6A41-4C7E-9D0A-5E2F8B7C1A64")!)
        XCTAssertEqual(r.id, "3b9f1d2e-6a41-4c7e-9d0a-5e2f8b7c1a64")
        XCTAssertEqual(CaptureCoding.iso(Date(timeIntervalSince1970: 0)), "1970-01-01T00:00:00Z")
        XCTAssertEqual(CaptureCoding.parseISO("2026-10-30T21:14:05Z")?.timeIntervalSince1970, 1_793_394_845)
    }

    func testTheFixtureCaptureDecodes() throws {
        let data = try Data(contentsOf: Fixtures.captureDir.appendingPathComponent("capture.json"))
        let r = try CaptureCoding.decoder().decode(CaptureRecord.self, from: data)
        XCTAssertEqual(r.v, 1)
        XCTAssertEqual(r.element?.id, "sample.list.addButton")
        XCTAssertEqual(r.element?.matchedBy, .anchor)
        XCTAssertEqual(r.anchors.count, 3)
        XCTAssertEqual(r.environment.dynamicType, "large")
        XCTAssertEqual(r.comment.input, .text)
        XCTAssertEqual(r.app.configuration, .testflight)
    }

    func testStatusChain() {
        XCTAssertEqual(ReviewStatus.allCases.map(\.rawValue), ["saved_on_phone", "received", "pr_ready", "verified_on_device"])
        XCTAssertEqual(ReviewStatus.allCases.map(\.title), ["Saved on phone", "Received", "PR ready", "Verified on device"])
        XCTAssertLessThan(ReviewStatus.savedOnPhone, .received)
        XCTAssertLessThan(ReviewStatus.prReady, .verifiedOnDevice)
        XCTAssertEqual(max(ReviewStatus.received, .prReady), .prReady)
    }

    func testDeviceFieldFollowsTheRelaysPattern() {
        XCTAssertEqual(AppProbe.sanitizeDevice("Ana's iPhone\n"), "Anas iPhone")
        XCTAssertEqual(AppProbe.sanitizeDevice("☃"), "device")
        XCTAssertEqual(AppProbe.sanitizeDevice(String(repeating: "a", count: 90)).count, 64)
    }

    func testBuildChannelNeverOpensInAnAppStoreBuild() {
        XCTAssertEqual(BuildChannel.detect(isDebug: true, receiptName: "receipt", receiptExists: true), .debug)
        XCTAssertEqual(BuildChannel.detect(isDebug: false, receiptName: "sandboxReceipt", receiptExists: true), .testflight)
        XCTAssertEqual(BuildChannel.detect(isDebug: false, receiptName: "receipt", receiptExists: true), .appStore)
        XCTAssertEqual(BuildChannel.detect(isDebug: false, receiptName: "receipt", receiptExists: false), .local)
        XCTAssertEqual(BuildChannel.detect(isDebug: false, receiptName: nil, receiptExists: false), .local)
    }

    func testCommitMustBeLowercaseHex() {
        XCTAssertTrue(AppProbe.isCommit("3f9c2ab"))
        XCTAssertFalse(AppProbe.isCommit("3F9C2AB"))
        XCTAssertFalse(AppProbe.isCommit("abc"))
        XCTAssertFalse(AppProbe.isCommit("zzzzzzz"))
    }
}

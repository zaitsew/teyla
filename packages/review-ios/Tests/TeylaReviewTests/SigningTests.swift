import XCTest
@testable import TeylaReview

final class SigningTests: XCTestCase {
    func testPairingStringGivesTheKey() throws {
        let v = Fixtures.vector
        let key = try XCTUnwrap(RelayKey(pairing: v["pairing"]!))
        XCTAssertEqual(Hex.encode(key.bytes), v["key_hex"])
        XCTAssertEqual(RelayKey(pairing: "  " + v["pairing"]! + "\n"), key)
        XCTAssertNil(RelayKey(pairing: "teyla-pair:v2:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"))
        XCTAssertNil(RelayKey(pairing: "teyla-pair:v1:AAEC"))
        XCTAssertNil(RelayKey(pairing: "nonsense"))
    }

    func testCaptureSignatureVector() throws {
        let v = Fixtures.vector
        let key = try XCTUnwrap(RelayKey(hex: v["key_hex"]!))
        let json = try Data(contentsOf: Fixtures.captureDir.appendingPathComponent("capture.json"))
        let png = try Data(contentsOf: Fixtures.captureDir.appendingPathComponent("capture.png"))
        XCTAssertEqual(ReviewSigner.sha256Hex(json), v["capture_json_sha256"])
        XCTAssertEqual(ReviewSigner.sha256Hex(png), v["capture_png_sha256"])
        let record = try CaptureCoding.decoder().decode(CaptureRecord.self, from: json)
        let message = ReviewSigner.captureMessage(id: record.id, created: record.created,
                                                  jsonSHA256: ReviewSigner.sha256Hex(json), pngSHA256: ReviewSigner.sha256Hex(png))
        XCTAssertEqual(message, v["capture_message"])
        XCTAssertEqual(ReviewSigner.sign(message, key: key), v["capture_sig"])
        XCTAssertTrue(ReviewSigner.verify(message, signature: v["capture_sig"]!, key: key))
        let onDisk = try String(contentsOf: Fixtures.captureDir.appendingPathComponent("capture.sig"), encoding: .utf8)
        XCTAssertTrue(ReviewSigner.verify(message, signature: onDisk, key: key))     // trailing newline is fine
    }

    func testStatusSignatureVector() throws {
        let v = Fixtures.vector
        let key = try XCTUnwrap(RelayKey(hex: v["key_hex"]!))
        let data = try Data(contentsOf: Fixtures.captureDir.appendingPathComponent("status.json"))
        let status = try CaptureCoding.decoder().decode(RemoteStatus.self, from: data)
        let message = ReviewSigner.statusMessage(id: status.id, status: status.status.rawValue, updated: status.updated, pr: status.pr)
        XCTAssertEqual(message, v["status_message"])
        XCTAssertEqual(ReviewSigner.sign(message, key: key), v["status_sig"])
        XCTAssertEqual(status.sig, v["status_sig"])
        XCTAssertEqual(status.status, .prReady)
    }

    func testAnyChangedLineBreaksTheSignature() throws {
        let v = Fixtures.vector
        let key = try XCTUnwrap(RelayKey(hex: v["key_hex"]!))
        let message = v["capture_message"]!
        XCTAssertFalse(ReviewSigner.verify(message + "x", signature: v["capture_sig"]!, key: key))
        XCTAssertFalse(ReviewSigner.verify(message, signature: String(v["capture_sig"]!.dropLast()) + "0", key: key))
        XCTAssertFalse(ReviewSigner.verify(message, signature: "not hex", key: key))
        XCTAssertFalse(ReviewSigner.verify(message, signature: "", key: key))
        let other = try XCTUnwrap(RelayKey(bytes: Data(repeating: 7, count: 32)))
        XCTAssertFalse(ReviewSigner.verify(message, signature: v["capture_sig"]!, key: other))
    }

    func testHex() {
        XCTAssertEqual(Hex.encode([0, 15, 255]), "000fff")
        XCTAssertEqual(Hex.decode("000FFF"), Data([0, 15, 255]))
        XCTAssertNil(Hex.decode("abc"))
        XCTAssertNil(Hex.decode("zz"))
    }
}

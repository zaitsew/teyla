import UIKit
import XCTest

/// tests/fixtures/taste-drop-vector.json is the contract with src/teyla/taste_wire.py: both reproduce it.
private struct TasteVector: Decodable {
    var key_hex: String
    var id: String
    var created: String
    var json: String
    var message: String
    var sig: String
}

private func tasteVector() throws -> TasteVector {
    let here = URL(fileURLWithPath: #filePath)
    let url = here.deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("tests/fixtures/taste-drop-vector.json")
    return try JSONDecoder().decode(TasteVector.self, from: Data(contentsOf: url))
}

final class TasteTests: XCTestCase {
    private let key = Data((0..<32).map { UInt8($0) })

    private func request(url: String? = "https://example.com/a", image: Bool = false, sentence: String = "calm, lots of air",
                         verdict: String = "like") -> TasteRequest {
        TasteRequest(id: "5b0c1d2e-3f40-4a51-8b62-73c4d5e6f708", created: "2026-11-09T10:00:00Z", verdict: verdict,
                     url: image ? nil : url, imageFile: image ? TasteInput.imageName : nil, sentence: sentence)
    }

    private func tempDir() throws -> URL {
        let dir = FileManager.default.temporaryDirectory.appending(path: "taste-\(UUID().uuidString)", directoryHint: .isDirectory)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: dir) }
        return dir
    }

    func testTheVectorIsReproducedExactly() throws {
        let v = try tasteVector()
        let drop = try TasteDrop.make(request(), image: nil, device: "iPhone", key: Data(RelayCrypto.decodeHex(Array(v.key_hex.utf8))!))
        XCTAssertEqual(String(decoding: drop.json, as: UTF8.self), v.json)
        XCTAssertEqual(TasteDrop.message(id: v.id, created: v.created, json: Data(v.json.utf8), image: nil), v.message)
        XCTAssertEqual(drop.sig, v.sig)
    }

    func testTheFileCarriesEveryKeyIncludingNulls() throws {
        let drop = try TasteDrop.make(request(image: true), image: Data([0xFF, 0xD8, 0xFF, 0xE0]), device: "iPhone", key: key)
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: drop.json) as? [String: Any])
        XCTAssertEqual(Set(obj.keys), ["v", "id", "created", "device", "verdict", "url", "image", "sentence"])
        XCTAssertTrue(obj["url"] is NSNull)
        XCTAssertEqual(obj["image"] as? String, "image.jpg")
    }

    func testThePictureIsPartOfTheSignature() throws {
        let a = try TasteDrop.make(request(image: true), image: Data([1, 2, 3]), device: "iPhone", key: key)
        let b = try TasteDrop.make(request(image: true), image: Data([1, 2, 4]), device: "iPhone", key: key)
        XCTAssertNotEqual(a.sig, b.sig)
    }

    func testRefusals() {
        let img = Data([1])
        XCTAssertThrowsError(try TasteDrop.make(request(url: "file:///etc/passwd"), image: nil, device: "iPhone", key: key))
        XCTAssertThrowsError(try TasteDrop.make(request(verdict: "love"), image: nil, device: "iPhone", key: key))
        XCTAssertThrowsError(try TasteDrop.make(request(image: true), image: nil, device: "iPhone", key: key))
        XCTAssertThrowsError(try TasteDrop.make(request(sentence: String(repeating: "x", count: 8001)), image: nil, device: "iPhone", key: key))
        var both = request()
        both.imageFile = "image.jpg"
        XCTAssertThrowsError(try TasteDrop.make(both, image: img, device: "iPhone", key: key))
        var badID = request()
        badID.id = "../x"
        XCTAssertThrowsError(try TasteDrop.make(badID, image: nil, device: "iPhone", key: key))
    }

    func testLinksAreChecked() {
        XCTAssertEqual(TasteInput.link(from: " https://example.com/a?b=1 "), "https://example.com/a?b=1")
        XCTAssertNil(TasteInput.link(from: "javascript:alert(1)"))
        XCTAssertNil(TasteInput.link(from: "https://exa mple.com"))
        XCTAssertNil(TasteInput.link(from: "ftp://example.com"))
        XCTAssertEqual(TasteInput.firstLink(inText: "Nice page https://example.com/x today"), "https://example.com/x")
    }

    func testABigPictureIsShrunkUnderTheCap() throws {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 2000, height: 2000), format: format)
        let noisy = renderer.pngData { ctx in
            var g = SystemRandomNumberGenerator()
            for _ in 0..<3000 {
                UIColor(red: .random(in: 0...1, using: &g), green: .random(in: 0...1, using: &g),
                        blue: .random(in: 0...1, using: &g), alpha: 1).setFill()
                ctx.fill(CGRect(x: .random(in: 0..<2000, using: &g), y: .random(in: 0..<2000, using: &g), width: 60, height: 60))
            }
        }
        let jpeg = try XCTUnwrap(TasteInput.jpeg(from: noisy, maxBytes: 300_000))
        XCTAssertLessThanOrEqual(jpeg.count, 300_000)
        XCTAssertEqual(Array(jpeg.prefix(3)), [0xFF, 0xD8, 0xFF])
        XCTAssertNil(TasteInput.jpeg(from: Data("not an image".utf8)))
    }

    func testTheQueueRoundTrips() throws {
        let queue = TasteQueue(root: try tempDir().appending(path: "q"))
        try queue.enqueue(request(image: true), image: Data([9, 9]))
        let pending = queue.pending()
        XCTAssertEqual(pending.count, 1)
        XCTAssertEqual(pending[0].request, request(image: true))
        XCTAssertEqual(pending[0].image, Data([9, 9]))
        queue.remove(id: pending[0].request.id)
        XCTAssertTrue(queue.pending().isEmpty)
    }

    func testTheDropIsWrittenAsAFolderTheMacReads() throws {
        let folder = try tempDir()
        let drop = try TasteDrop.make(request(image: true), image: Data([0xFF, 0xD8, 0xFF, 0xE0]), device: "iPhone", key: key)
        try RelayStore(folder: folder).writeTaste(drop)
        let dir = folder.appending(path: "outbox/taste/\(drop.id)")
        XCTAssertEqual(try Data(contentsOf: dir.appending(path: "taste.json")), drop.json)
        XCTAssertEqual(try String(contentsOf: dir.appending(path: "taste.sig"), encoding: .utf8), drop.sig)
        XCTAssertEqual(try Data(contentsOf: dir.appending(path: "image.jpg")), Data([0xFF, 0xD8, 0xFF, 0xE0]))
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: folder.appending(path: "outbox/taste").path), [drop.id])
    }
}

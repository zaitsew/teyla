import XCTest
@testable import TeylaReview

final class CaptureStoreTests: XCTestCase {
    private var dir: URL!
    private var store: CaptureStore!
    private var relay: URL!
    private let png = Data([0x89, 0x50, 0x4E, 0x47, 1, 2, 3])
    private var key: RelayKey { RelayKey(hex: Fixtures.vector["key_hex"]!)! }

    override func setUp() {
        dir = Fixtures.tempDir()
        store = CaptureStore(root: dir.appendingPathComponent("captures"), now: { Date(timeIntervalSince1970: 1_793_394_900) })
        relay = dir.appendingPathComponent("Teyla")
        try! FileManager.default.createDirectory(at: relay, withIntermediateDirectories: true)
    }

    override func tearDown() { try? FileManager.default.removeItem(at: dir) }

    func testSaveWritesTheThreeFilesAndAStatus() throws {
        let record = Fixtures.record()
        let saved = try store.save(record: record, png: png, key: key)
        XCTAssertTrue(saved.signed)
        for name in ["capture.json", "capture.png", "capture.sig", "status.json"] {
            XCTAssertTrue(FileManager.default.fileExists(atPath: saved.folder.appendingPathComponent(name).path), name)
        }
        XCTAssertEqual(store.readLocalStatus(id: record.id)?.status, .savedOnPhone)
    }

    func testTheSavedSignatureVerifiesOverTheBytesOnDisk() throws {
        let record = Fixtures.record()
        let saved = try store.save(record: record, png: png, key: key)
        let json = try Data(contentsOf: saved.folder.appendingPathComponent("capture.json"))
        let onDiskPNG = try Data(contentsOf: saved.folder.appendingPathComponent("capture.png"))
        let sig = try String(contentsOf: saved.folder.appendingPathComponent("capture.sig"), encoding: .utf8)
        let message = ReviewSigner.captureMessage(id: record.id, created: record.created,
                                                  jsonSHA256: ReviewSigner.sha256Hex(json), pngSHA256: ReviewSigner.sha256Hex(onDiskPNG))
        XCTAssertTrue(ReviewSigner.verify(message, signature: sig, key: key))
        let decoded = try CaptureCoding.decoder().decode(CaptureRecord.self, from: json)
        XCTAssertEqual(decoded.screenshot.sha256, ReviewSigner.sha256Hex(png))     // the record names the picture it ships with
    }

    func testWithoutAKeyThereIsNoSignatureAndNothingGoesToTheRelay() throws {
        let record = Fixtures.record()
        let saved = try store.save(record: record, png: png, key: nil)
        XCTAssertFalse(saved.signed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: saved.folder.appendingPathComponent("capture.sig").path))
        XCTAssertThrowsError(try store.copyToRelay(id: record.id, relayRoot: relay)) { XCTAssertEqual($0 as? ReviewError, .unsigned) }
        XCTAssertFalse(FileManager.default.fileExists(atPath: relay.appendingPathComponent("outbox").path))
    }

    func testCopyToRelayPutsTheFolderUnderOutboxReview() throws {
        let record = Fixtures.record()
        try store.save(record: record, png: png, key: key)
        XCTAssertEqual(try store.copyToRelay(id: record.id, relayRoot: relay), .copied)
        let dest = relay.appendingPathComponent("outbox/review/\(record.id)")
        let names = Set(try FileManager.default.contentsOfDirectory(atPath: dest.path))
        XCTAssertEqual(names, ["capture.json", "capture.png", "capture.sig"])          // status.json stays on the phone
        let left = try FileManager.default.contentsOfDirectory(atPath: relay.appendingPathComponent("outbox/review").path)
        XCTAssertEqual(left, [record.id])                                              // no .tmp- folder remains
        XCTAssertNotNil(store.readLocalStatus(id: record.id)?.relayCopied)
        XCTAssertEqual(store.readLocalStatus(id: record.id)?.status, .savedOnPhone)
    }

    func testCopyingTwiceIsOneCapture() throws {
        let record = Fixtures.record()
        try store.save(record: record, png: png, key: key)
        XCTAssertEqual(try store.copyToRelay(id: record.id, relayRoot: relay), .copied)
        XCTAssertEqual(try store.copyToRelay(id: record.id, relayRoot: relay), .alreadyThere)
    }

    func testCopyOfAnUnknownIdFails() {
        XCTAssertThrowsError(try store.copyToRelay(id: "nope", relayRoot: relay)) { XCTAssertEqual($0 as? ReviewError, .notSaved) }
    }

    func testListIsNewestFirst() throws {
        var older = CaptureStore(root: store.root, now: { Date(timeIntervalSince1970: 1_793_000_000) })
        let a = Fixtures.record(), b = Fixtures.record()
        try older.save(record: a, png: png, key: key)
        older.now = { Date(timeIntervalSince1970: 1_793_500_000) }
        try older.save(record: b, png: png, key: key)
        XCTAssertEqual(store.list(), [b.id, a.id])
    }

    // MARK: the Mac's answer

    private func writeRemote(id: String, status: ReviewStatus, pr: String? = nil, signedWith: RelayKey?) throws {
        let updated = "2026-10-30T22:03:00Z"
        let message = ReviewSigner.statusMessage(id: id, status: status.rawValue, updated: updated, pr: pr)
        let sig = signedWith.map { ReviewSigner.sign(message, key: $0) } ?? String(repeating: "0", count: 64)
        let remote = RemoteStatus(v: 1, id: id, status: status, updated: updated, pr: pr, sig: sig)
        let folder = relay.appendingPathComponent("review-status")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try CaptureCoding.encoder().encode(remote).write(to: folder.appendingPathComponent(id + ".json"))
    }

    func testASignedStatusFromTheMacMovesTheChainForward() throws {
        let record = Fixtures.record()
        try store.save(record: record, png: png, key: key)
        try writeRemote(id: record.id, status: .prReady, pr: "https://github.com/example/sampleapp/pull/12", signedWith: key)
        XCTAssertEqual(store.status(id: record.id, relayRoot: relay, key: key), .prReady)
    }

    func testAForgedOrUnsignedStatusIsIgnored() throws {
        let record = Fixtures.record()
        try store.save(record: record, png: png, key: key)
        try writeRemote(id: record.id, status: .verifiedOnDevice, signedWith: nil)
        XCTAssertEqual(store.status(id: record.id, relayRoot: relay, key: key), .savedOnPhone)
        try writeRemote(id: record.id, status: .verifiedOnDevice, signedWith: RelayKey(bytes: Data(repeating: 9, count: 32)))
        XCTAssertEqual(store.status(id: record.id, relayRoot: relay, key: key), .savedOnPhone)
        XCTAssertEqual(store.status(id: record.id, relayRoot: nil, key: key), .savedOnPhone)
        XCTAssertEqual(store.status(id: record.id, relayRoot: relay, key: nil), .savedOnPhone)
    }

    func testAStatusForAnotherCaptureIsIgnored() throws {
        let a = Fixtures.record(), b = Fixtures.record()
        try store.save(record: a, png: png, key: key)
        try writeRemote(id: b.id, status: .received, signedWith: key)
        // file named for `a` but holding `b`'s id
        try FileManager.default.moveItem(at: relay.appendingPathComponent("review-status/\(b.id).json"),
                                         to: relay.appendingPathComponent("review-status/\(a.id).json"))
        XCTAssertEqual(store.status(id: a.id, relayRoot: relay, key: key), .savedOnPhone)
    }

    func testTheFixtureStatusFileVerifies() throws {
        let key = try XCTUnwrap(RelayKey(hex: Fixtures.vector["key_hex"]!))
        let fixtureRecord = try CaptureCoding.decoder().decode(
            CaptureRecord.self, from: Data(contentsOf: Fixtures.captureDir.appendingPathComponent("capture.json")))
        try store.save(record: fixtureRecord, png: png, key: key)
        let folder = relay.appendingPathComponent("review-status")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        try FileManager.default.copyItem(at: Fixtures.captureDir.appendingPathComponent("status.json"),
                                         to: folder.appendingPathComponent(fixtureRecord.id + ".json"))
        XCTAssertEqual(store.status(id: fixtureRecord.id, relayRoot: relay, key: key), .prReady)
    }
}

final class RelayFolderTests: XCTestCase {
    func testNothingChosenMeansNoAccess() {
        let defaults = UserDefaults(suiteName: "teyla.review.tests." + UUID().uuidString)!
        let folder = RelayFolder(defaults: defaults)
        XCTAssertFalse(folder.isChosen)
        XCTAssertNil(folder.withAccess { $0 })
    }

    func testARememberedFolderIsResolved() throws {
        let defaults = UserDefaults(suiteName: "teyla.review.tests." + UUID().uuidString)!
        let dir = Fixtures.tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let folder = RelayFolder(defaults: defaults)
        try folder.remember(dir)
        XCTAssertTrue(folder.isChosen)
        let got = folder.withAccess { $0.standardizedFileURL.resolvingSymlinksInPath().path }
        XCTAssertEqual(got, dir.standardizedFileURL.resolvingSymlinksInPath().path)
        folder.forget()
        XCTAssertFalse(folder.isChosen)
    }
}

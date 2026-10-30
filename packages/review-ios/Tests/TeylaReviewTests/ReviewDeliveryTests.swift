import XCTest
@testable import TeylaReview

final class ReviewDeliveryTests: XCTestCase {
    private var dir: URL!
    private var relay: URL!
    private var folder: RelayFolder!
    private let png = Data([0x89, 0x50, 0x4E, 0x47, 1, 2, 3])
    private var key: RelayKey { RelayKey(hex: Fixtures.vector["key_hex"]!)! }

    override func setUp() {
        dir = Fixtures.tempDir()
        relay = dir.appendingPathComponent("Teyla")
        try! FileManager.default.createDirectory(at: relay, withIntermediateDirectories: true)
        folder = RelayFolder(defaults: UserDefaults(suiteName: "teyla.review.tests." + UUID().uuidString)!)
        try! folder.remember(relay)
    }

    override func tearDown() { try? FileManager.default.removeItem(at: dir) }

    private func store() -> CaptureStore { CaptureStore(root: dir.appendingPathComponent("captures")) }
    private func outbox(_ id: String) -> URL { relay.appendingPathComponent("outbox/review/\(id)") }

    func testASuccessfulSaveReturnsNoFailureAndCopiesWhenPaired() {
        let record = Fixtures.record()
        let failure = ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(key), relayFolder: folder)
        XCTAssertNil(failure)
        XCTAssertTrue(FileManager.default.fileExists(atPath: outbox(record.id).appendingPathComponent("capture.sig").path))
    }

    func testAFailedLocalSaveIsReportedAndNothingIsCopied() throws {
        // The captures folder cannot be created: its parent is a regular file.
        let blocker = dir.appendingPathComponent("blocker")
        try Data([1]).write(to: blocker)
        let broken = CaptureStore(root: blocker.appendingPathComponent("captures"))
        let record = Fixtures.record()
        let failure = ReviewDelivery.save(record: record, png: png, store: broken, keyStore: MemoryKeyStore(key), relayFolder: folder)
        XCTAssertEqual(failure, ReviewDelivery.saveFailureMessage)
        XCTAssertFalse(FileManager.default.fileExists(atPath: outbox(record.id).path))
    }

    func testARetryAfterAFailedSaveSucceedsOnceTheFolderIsWritable() throws {
        let blocker = dir.appendingPathComponent("blocker")
        try Data([1]).write(to: blocker)
        let record = Fixtures.record()
        let root = blocker.appendingPathComponent("captures")
        XCTAssertNotNil(ReviewDelivery.save(record: record, png: png, store: CaptureStore(root: root), keyStore: MemoryKeyStore(key), relayFolder: folder))
        try FileManager.default.removeItem(at: blocker)                               // space freed
        XCTAssertNil(ReviewDelivery.save(record: record, png: png, store: CaptureStore(root: root), keyStore: MemoryKeyStore(key), relayFolder: folder))
        XCTAssertEqual(CaptureStore(root: root).list(), [record.id])
    }

    func testPairingLaterSignsAndCopiesWhatWasSavedBefore() {
        let record = Fixtures.record()
        XCTAssertNil(ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder))
        XCTAssertFalse(FileManager.default.fileExists(atPath: outbox(record.id).path))   // unsigned: stays on the phone
        ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(key), relayFolder: folder)
        let dest = outbox(record.id)
        XCTAssertTrue(FileManager.default.fileExists(atPath: dest.appendingPathComponent("capture.sig").path))
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.relayCopied)
    }

    func testRetryWithoutAKeyDoesNothing() {
        let record = Fixtures.record()
        _ = ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder)
        ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder)
        XCTAssertFalse(FileManager.default.fileExists(atPath: outbox(record.id).path))
    }
}

final class ReviewSwitchTests: XCTestCase {
    func testOnlyAnExplicitYesTurnsReviewModeOn() {
        XCTAssertTrue(TeylaReview.parseEnabled("YES"))
        XCTAssertTrue(TeylaReview.parseEnabled(" true "))
        XCTAssertTrue(TeylaReview.parseEnabled("1"))
        XCTAssertTrue(TeylaReview.parseEnabled(true))
        XCTAssertFalse(TeylaReview.parseEnabled(nil))                       // key absent: the App Store configuration
        XCTAssertFalse(TeylaReview.parseEnabled(""))                        // key present, build setting undefined
        XCTAssertFalse(TeylaReview.parseEnabled("$(TEYLA_REVIEW_ENABLED)")) // unexpanded placeholder
        XCTAssertFalse(TeylaReview.parseEnabled("NO"))
        XCTAssertFalse(TeylaReview.parseEnabled(false))
    }

    func testTheTestHostHasNoKeySoReviewModeIsOff() {
        TeylaReview.enabledOverride = nil
        XCTAssertFalse(TeylaReview.isEnabled)
        XCTAssertFalse(TeylaReview.isActive)
    }
}

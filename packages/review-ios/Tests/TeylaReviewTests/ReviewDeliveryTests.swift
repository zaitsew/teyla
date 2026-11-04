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

    func testASaveOnAPairedPhoneIsSentToTheRelay() async {
        let record = Fixtures.record()
        let outcome = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(key), relayFolder: folder, deliver: nil)
        XCTAssertEqual(outcome, .sent)
        XCTAssertTrue(FileManager.default.fileExists(atPath: outbox(record.id).appendingPathComponent("capture.sig").path))
    }

    func testAFailedLocalSaveIsReportedAndNothingIsCopied() async throws {
        // The captures folder cannot be created: its parent is a regular file.
        let blocker = dir.appendingPathComponent("blocker")
        try Data([1]).write(to: blocker)
        let broken = CaptureStore(root: blocker.appendingPathComponent("captures"))
        let record = Fixtures.record()
        let outcome = await ReviewDelivery.save(record: record, png: png, store: broken, keyStore: MemoryKeyStore(key), relayFolder: folder, deliver: nil)
        XCTAssertEqual(outcome, .failed)
        XCTAssertFalse(FileManager.default.fileExists(atPath: outbox(record.id).path))
    }

    func testARetryAfterAFailedSaveSucceedsOnceTheFolderIsWritable() async throws {
        let blocker = dir.appendingPathComponent("blocker")
        try Data([1]).write(to: blocker)
        let record = Fixtures.record()
        let root = blocker.appendingPathComponent("captures")
        let failed = await ReviewDelivery.save(record: record, png: png, store: CaptureStore(root: root), keyStore: MemoryKeyStore(key), relayFolder: folder, deliver: nil)
        XCTAssertEqual(failed, .failed)
        try FileManager.default.removeItem(at: blocker)                               // space freed
        let sent = await ReviewDelivery.save(record: record, png: png, store: CaptureStore(root: root), keyStore: MemoryKeyStore(key), relayFolder: folder, deliver: nil)
        XCTAssertEqual(sent, .sent)
        XCTAssertEqual(CaptureStore(root: root).list(), [record.id])
    }

    func testPairingLaterSignsAndCopiesWhatWasSavedBefore() async {
        let record = Fixtures.record()
        let saved = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: nil)
        XCTAssertEqual(saved, .savedOnPhone)
        XCTAssertFalse(FileManager.default.fileExists(atPath: outbox(record.id).path))   // unsigned: stays on the phone
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(key), relayFolder: folder, deliver: nil)
        let dest = outbox(record.id)
        XCTAssertTrue(FileManager.default.fileExists(atPath: dest.appendingPathComponent("capture.sig").path))
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.relayCopied)
    }

    func testRetryWithoutAKeyOrChannelDoesNothing() async {
        let record = Fixtures.record()
        _ = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: nil)
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: nil)
        XCTAssertFalse(FileManager.default.fileExists(atPath: outbox(record.id).path))
    }

    // MARK: the product's channel

    private final class Channel: @unchecked Sendable {
        private let lock = NSLock()
        private var received: [ReviewUpload] = []
        var accepts: Bool
        init(accepts: Bool) { self.accepts = accepts }
        var uploads: [ReviewUpload] { lock.lock(); defer { lock.unlock() }; return received }
        var deliver: ReviewDeliver {
            { [self] upload in
                lock.lock(); defer { lock.unlock() }
                received.append(upload)
                return accepts
            }
        }
    }

    func testAChannelTakesACaptureFromAPhoneWithNoKey() async {
        let record = Fixtures.record()
        let channel = Channel(accepts: true)
        let outcome = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: channel.deliver, noticeAccepted: { true })
        XCTAssertEqual(outcome, .sent)
        XCTAssertEqual(channel.uploads.map(\.id), [record.id])
        XCTAssertEqual(channel.uploads.first?.png, png)
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.delivered)
        XCTAssertFalse(FileManager.default.fileExists(atPath: outbox(record.id).path))
    }

    func testACaptureAChannelRefusedSaysSavedAndGoesOnTheNextRetry() async {
        let record = Fixtures.record()
        let channel = Channel(accepts: false)
        let outcome = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: channel.deliver, noticeAccepted: { true })
        XCTAssertEqual(outcome, .savedOnPhone)
        XCTAssertNil(store().readLocalStatus(id: record.id)?.delivered)
        channel.accepts = true
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: channel.deliver, noticeAccepted: { true })
        XCTAssertEqual(channel.uploads.count, 2)
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.delivered)
    }

    func testRetrySendsACaptureSavedBeforeTheChannelExisted() async {
        let record = Fixtures.record()
        _ = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: nil)
        let channel = Channel(accepts: true)
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: channel.deliver, noticeAccepted: { true })
        XCTAssertEqual(channel.uploads.map(\.id), [record.id])
    }

    func testADeliveredCaptureIsNotSentAgainByAnyRoute() async {
        let record = Fixtures.record()
        let channel = Channel(accepts: true)
        _ = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: channel.deliver, noticeAccepted: { true })
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(key), relayFolder: folder, deliver: channel.deliver, noticeAccepted: { true })
        XCTAssertEqual(channel.uploads.count, 1)
        XCTAssertFalse(FileManager.default.fileExists(atPath: outbox(record.id).path))
    }

    func testAPairedPhoneUsesTheRelayAndNotTheChannel() async {
        let record = Fixtures.record()
        let channel = Channel(accepts: true)
        let outcome = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(key), relayFolder: folder, deliver: channel.deliver, noticeAccepted: { true })
        XCTAssertEqual(outcome, .sent)
        XCTAssertTrue(channel.uploads.isEmpty)
    }

    func testAPairedPhoneFallsBackToTheChannelWhenTheFolderIsGone() async {
        let record = Fixtures.record()
        let channel = Channel(accepts: true)
        let noFolder = RelayFolder(defaults: UserDefaults(suiteName: "teyla.review.tests." + UUID().uuidString)!)
        let outcome = await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(key), relayFolder: noFolder, deliver: channel.deliver, noticeAccepted: { true })
        XCTAssertEqual(outcome, .sent)
        XCTAssertEqual(channel.uploads.count, 1)
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

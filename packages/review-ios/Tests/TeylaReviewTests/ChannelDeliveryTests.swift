import XCTest
@testable import TeylaReview

/// Answers every request from `handler` and records what it was asked. Nothing leaves the process.
final class StubProtocol: URLProtocol {
    struct Seen { let method: String; let url: URL; let authorization: String?; let contentType: String?; let body: Data }
    nonisolated(unsafe) static var handler: (@Sendable (Seen) -> Result<Int, URLError>)?
    nonisolated(unsafe) private static var log: [Seen] = []
    private static let lock = NSLock()

    static var seen: [Seen] { lock.lock(); defer { lock.unlock() }; return log }
    static func reset(_ handler: (@Sendable (Seen) -> Result<Int, URLError>)? = nil) {
        lock.lock(); log = []; lock.unlock()
        self.handler = handler
    }

    static func session() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubProtocol.self]
        return URLSession(configuration: configuration)
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        var body = request.httpBody ?? Data()
        if let stream = request.httpBodyStream {
            stream.open()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let n = stream.read(&buffer, maxLength: buffer.count)
                if n <= 0 { break }
                body.append(buffer, count: n)
            }
            stream.close()
        }
        let seen = Seen(method: request.httpMethod ?? "", url: request.url!, authorization: request.value(forHTTPHeaderField: "Authorization"),
                        contentType: request.value(forHTTPHeaderField: "Content-Type"), body: body)
        Self.lock.lock(); Self.log.append(seen); Self.lock.unlock()
        switch Self.handler?(seen) ?? .success(200) {
        case .success(let status):
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: nil)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data())
            client?.urlProtocolDidFinishLoading(self)
        case .failure(let error):
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class ChannelDeliveryTests: XCTestCase {
    private var dir: URL!
    private var folder: RelayFolder!
    private let png = Data([0x89, 0x50, 0x4E, 0x47, 9, 8, 7])
    private let secret = "channel-key-value-do-not-print"
    private var config: ChannelConfig { ChannelConfig(url: "https://channel.example.test", key: secret)! }

    override func setUp() {
        dir = Fixtures.tempDir()
        folder = RelayFolder(defaults: UserDefaults(suiteName: "teyla.review.tests." + UUID().uuidString)!)
        StubProtocol.reset()
    }

    override func tearDown() {
        StubProtocol.reset()
        try? FileManager.default.removeItem(at: dir)
    }

    /// A capture as this version writes it: with `app.product`.
    private func record(product: String? = "sample-app") -> CaptureRecord {
        var app = Fixtures.app
        app.product = product
        return Fixtures.record(app: app)
    }

    private func store() -> CaptureStore { CaptureStore(root: dir.appendingPathComponent("captures")) }

    private func deliver() -> ReviewDeliver {
        let root = dir.appendingPathComponent("captures")
        return ChannelDelivery.deliver(
            config: config, session: StubProtocol.session(),
            isRefused: { CaptureStore(root: root).readLocalStatus(id: $0)?.refused != nil },
            markRefused: { CaptureStore(root: root).markRefused(id: $0) })
    }

    private func save(_ record: CaptureRecord, deliver: ReviewDeliver?) async -> ReviewSaveOutcome {
        await ReviewDelivery.save(record: record, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: deliver, noticeAccepted: { true })
    }

    private func retry(_ deliver: ReviewDeliver?) async {
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: deliver, noticeAccepted: { true })
    }

    // MARK: the plist keys

    func testBothKeysMustBePresentAndNonEmpty() {
        XCTAssertNotNil(ChannelConfig(url: "https://channel.example.test", key: "k"))
        XCTAssertNil(ChannelConfig(url: nil, key: "k"))
        XCTAssertNil(ChannelConfig(url: "https://channel.example.test", key: nil))
        XCTAssertNil(ChannelConfig(url: "", key: "k"))
        XCTAssertNil(ChannelConfig(url: "https://channel.example.test", key: "   "))
        XCTAssertNil(ChannelConfig(url: "$(TEYLA_REVIEW_CHANNEL_URL)", key: "k"))      // an unexpanded build setting
        XCTAssertNil(ChannelConfig(url: "https://channel.example.test", key: "$(TEYLA_REVIEW_CHANNEL_KEY)"))
        XCTAssertNil(ChannelConfig(url: 42, key: "k"))
    }

    func testThePlainHTTPKeyLeakIsRefusedExceptOnLoopback() {
        XCTAssertNil(ChannelConfig(url: "http://channel.example.test", key: "k"))
        XCTAssertNotNil(ChannelConfig(url: "http://localhost:8080", key: "k"))
        XCTAssertNotNil(ChannelConfig(url: "http://127.0.0.1:8080", key: "k"))
        XCTAssertNil(ChannelConfig(url: "ftp://channel.example.test", key: "k"))
    }

    func testTheKeyNeverAppearsInADescription() {
        XCTAssertFalse("\(config)".contains(secret))
        XCTAssertFalse(String(reflecting: config).contains(secret))
    }

    func testTheTestHostHasNoChannelSoNothingIsDelivered() async {
        XCTAssertNil(TeylaReview.bundleChannel)
        let record = record()
        StubProtocol.reset()
        let outcome = await save(record, deliver: nil)
        XCTAssertEqual(outcome, .savedOnPhone)
        XCTAssertTrue(StubProtocol.seen.isEmpty)
    }

    // MARK: the wire

    func testASuccessPutsThePictureThenTheJSONWithTheBearerKey() async {
        let record = record()
        let outcome = await save(record, deliver: deliver())
        XCTAssertEqual(outcome, .sent)
        let seen = StubProtocol.seen
        XCTAssertEqual(seen.map(\.method), ["PUT", "PUT"])
        XCTAssertEqual(seen.map { $0.url.path }, ["/v1/captures/\(record.id)/capture.png", "/v1/captures/\(record.id)/capture.json"])
        XCTAssertEqual(seen.map(\.authorization), ["Bearer " + secret, "Bearer " + secret])
        XCTAssertEqual(seen.map(\.contentType), ["image/png", "application/json"])
        XCTAssertEqual(seen[0].body, png)
        XCTAssertEqual(seen[1].body, store().upload(id: record.id)?.json)
        XCTAssertFalse(seen.contains { $0.url.absoluteString.contains(secret) })      // the key travels in a header only
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.delivered)
        XCTAssertNil(store().readLocalStatus(id: record.id)?.refused)
    }

    func testAnIDThatIsNotALowercaseUUIDIsNeverSent() async {
        let upload = ReviewUpload(id: "../../etc", json: Data("{}".utf8), png: png)
        let result = await ChannelDelivery.send(upload, config: config, session: StubProtocol.session())
        XCTAssertEqual(result, .refused)
        let upper = ReviewUpload(id: UUID().uuidString.uppercased(), json: Data(), png: png)
        let second = await ChannelDelivery.send(upper, config: config, session: StubProtocol.session())
        XCTAssertEqual(second, .refused)
        XCTAssertTrue(StubProtocol.seen.isEmpty)
    }

    // MARK: later

    func testABusyServerSaysSavedAndTheNextRetrySucceeds() async {
        let record = record()
        StubProtocol.reset { $0.url.lastPathComponent == "capture.json" ? .success(503) : .success(200) }
        let first = await save(record, deliver: deliver())
        XCTAssertEqual(first, .savedOnPhone)
        XCTAssertNil(store().readLocalStatus(id: record.id)?.delivered)
        XCTAssertNil(store().readLocalStatus(id: record.id)?.refused)          // 503 is not a refusal
        StubProtocol.reset()                                                    // the server is back
        await retry(deliver())
        XCTAssertEqual(StubProtocol.seen.map { $0.url.lastPathComponent }, ["capture.png", "capture.json"])
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.delivered)
    }

    func testTheDailyCapAndANetworkErrorAreAlsoLater() async {
        let a = record(), b = record()
        StubProtocol.reset { _ in .success(429) }
        let capped = await save(a, deliver: deliver())
        XCTAssertEqual(capped, .savedOnPhone)
        StubProtocol.reset { _ in .failure(URLError(.notConnectedToInternet)) }
        let offline = await save(b, deliver: deliver())
        XCTAssertEqual(offline, .savedOnPhone)
        XCTAssertNil(store().readLocalStatus(id: a.id)?.refused)
        XCTAssertNil(store().readLocalStatus(id: b.id)?.refused)
    }

    func testTheStatusMappingKeepsTheListsApart() {
        XCTAssertEqual(ChannelDelivery.result(forStatus: 200), .delivered)
        for status in [401, 403, 413, 422, 400] { XCTAssertEqual(ChannelDelivery.result(forStatus: status), .refused, "\(status)") }
        for status in [429, 503, 507, 500, 405, 302] { XCTAssertEqual(ChannelDelivery.result(forStatus: status), .retryLater, "\(status)") }
    }

    // MARK: for good

    func testARefusalIsRememberedAndNeverRetriedForever() async {
        let record = record()
        StubProtocol.reset { _ in .success(401) }
        let outcome = await save(record, deliver: deliver())
        XCTAssertEqual(outcome, .savedOnPhone)
        XCTAssertEqual(StubProtocol.seen.count, 1)                              // the picture was refused: the JSON is not tried
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.refused)
        XCTAssertNil(store().readLocalStatus(id: record.id)?.delivered)
        await retry(deliver())
        await retry(deliver())
        XCTAssertEqual(StubProtocol.seen.count, 1)                              // no further request, ever
    }

    func testARefusedJSONAfterAnAcceptedPictureIsAlsoFinal() async {
        let record = record()
        StubProtocol.reset { $0.url.lastPathComponent == "capture.json" ? .success(403) : .success(200) }
        _ = await save(record, deliver: deliver())
        XCTAssertEqual(StubProtocol.seen.count, 2)
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.refused)
        await retry(deliver())
        XCTAssertEqual(StubProtocol.seen.count, 2)
    }

    func testARefusedCaptureStillTakesTheRelayRoute() async {
        let record = record()
        StubProtocol.reset { _ in .success(403) }
        _ = await save(record, deliver: deliver())
        let relay = dir.appendingPathComponent("Teyla")
        try! FileManager.default.createDirectory(at: relay, withIntermediateDirectories: true)
        try! folder.remember(relay)
        let key = RelayKey(hex: Fixtures.vector["key_hex"]!)!
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(key), relayFolder: folder, deliver: deliver(), noticeAccepted: { true })
        XCTAssertNotNil(store().readLocalStatus(id: record.id)?.relayCopied)
    }

    func testAStatusFileFromBeforeRefusalsStillReads() throws {
        let old = #"{"v":1,"id":"a","status":"saved_on_phone","updated":"2026-11-01T10:00:00Z"}"#
        let decoded = try JSONDecoder().decode(LocalStatus.self, from: Data(old.utf8))
        XCTAssertNil(decoded.refused)
    }

    // MARK: captures from before app.product existed

    func testACaptureWithoutAProductIsKeptLocallyNotSentAndNotRefused() async {
        let old = record(product: nil)
        let outcome = await save(old, deliver: deliver())
        XCTAssertEqual(outcome, .savedOnPhone)
        await retry(deliver())
        XCTAssertTrue(StubProtocol.seen.isEmpty)                                 // the service would answer 403
        XCTAssertNil(store().readLocalStatus(id: old.id)?.refused)               // and it is not marked for that
        XCTAssertNil(store().readLocalStatus(id: old.id)?.delivered)
    }

    func testAProductWithBadCharactersCountsAsNone() {
        XCTAssertTrue(ChannelDelivery.hasProduct(Data(#"{"app":{"product":"sample-app"}}"#.utf8)))
        XCTAssertFalse(ChannelDelivery.hasProduct(Data(#"{"app":{"product":"Sample App"}}"#.utf8)))
        XCTAssertFalse(ChannelDelivery.hasProduct(Data(#"{"app":{}}"#.utf8)))
        XCTAssertFalse(ChannelDelivery.hasProduct(Data("not json".utf8)))
    }

    // MARK: a refusal belongs to the route that gave it

    func testAChannelRefusalDoesNotBlockACustomDeliverSetLater() async {
        let r = record()
        StubProtocol.reset { _ in .success(403) }
        _ = await save(r, deliver: deliver())
        XCTAssertNotNil(store().readLocalStatus(id: r.id)?.refused)
        let uploads = UploadLog()
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder,
                                          deliver: uploads.deliver, noticeAccepted: { true })
        XCTAssertEqual(uploads.ids, [r.id])
        XCTAssertNotNil(store().readLocalStatus(id: r.id)?.delivered)
    }

    // MARK: the notice comes first, on every route

    func testNoRouteSendsBeforeTheNoticeWasAccepted() async {
        let r = record()
        let uploads = UploadLog()
        let channel = deliver()
        let custom = await ReviewDelivery.save(record: r, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder,
                                               deliver: uploads.deliver, noticeAccepted: { false })
        XCTAssertEqual(custom, .savedOnPhone)
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: uploads.deliver, noticeAccepted: { false })
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: channel, noticeAccepted: { false })
        XCTAssertTrue(uploads.ids.isEmpty)
        XCTAssertTrue(StubProtocol.seen.isEmpty)
        XCTAssertNil(store().readLocalStatus(id: r.id)?.delivered)
        // The tester accepts: the same pending capture goes out.
        await ReviewDelivery.retryPending(store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: uploads.deliver, noticeAccepted: { true })
        XCTAssertEqual(uploads.ids, [r.id])
    }

    func testTheDefaultReadsTheStoredAnswerAndTheTestHostHasNone() async {
        XCTAssertFalse(ReviewNotice.isAccepted())            // a clean test host: a pending capture would wait
        let r = record()
        let uploads = UploadLog()
        let outcome = await ReviewDelivery.save(record: r, png: png, store: store(), keyStore: MemoryKeyStore(), relayFolder: folder, deliver: uploads.deliver)
        XCTAssertEqual(outcome, .savedOnPhone)
        XCTAssertTrue(uploads.ids.isEmpty)
    }

    func testThePairedRelayDoesNotNeedTheNotice() async {
        let relay = dir.appendingPathComponent("Teyla")
        try! FileManager.default.createDirectory(at: relay, withIntermediateDirectories: true)
        try! folder.remember(relay)
        let key = RelayKey(hex: Fixtures.vector["key_hex"]!)!
        let outcome = await ReviewDelivery.save(record: record(), png: png, store: store(), keyStore: MemoryKeyStore(key), relayFolder: folder,
                                                deliver: nil, noticeAccepted: { false })
        XCTAssertEqual(outcome, .sent)                        // the owner's own iCloud folder, not a server
    }
}

/// A custom `deliver` that records what it was handed.
final class UploadLog: @unchecked Sendable {
    private let lock = NSLock()
    private var received: [String] = []
    var ids: [String] { lock.lock(); defer { lock.unlock() }; return received }
    var deliver: ReviewDeliver {
        { [self] upload in
            lock.lock(); defer { lock.unlock() }
            received.append(upload.id)
            return true
        }
    }
}

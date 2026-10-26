import Foundation
import os

/// Why the store build shows no data, or old data, or could not send.
enum StoreError: LocalizedError, Equatable {
    /// No relay folder and key, and not in sample mode.
    case notConnected
    /// The folder has no `state.teyla` yet.
    case waiting
    /// iCloud has the file and is still delivering it.
    case downloading
    /// The signature is missing or does not match the pairing key. Nothing from the file is shown.
    case untrusted
    case unreadable(String)
    /// The question or session is no longer in the snapshot.
    case gone(String)
    /// The entry is in the outbox and the Mac has not written `sent/<id>.json`.
    case noReply

    var errorDescription: String? {
        switch self {
        case .notConnected:
            return "Teyla is not connected to a Mac yet."
        case .waiting:
            return "Waiting for the Mac. The folder has no snapshot yet: run teyla relay on there, or choose the folder it uses."
        case .downloading:
            return "iCloud is still delivering the Mac's snapshot."
        case .untrusted:
            return "The snapshot's signature does not match your pairing, so Teyla shows nothing from it. Pair again in Settings."
        case .unreadable(let why):
            return why
        case .gone(let what):
            return what
        case .noReply:
            return "Waiting for the Mac. The action is in the folder and is delivered when the Mac reads it. "
                + "Check teyla relay status there before you send it again."
        }
    }

    /// After these the window drops what it showed before: it cannot be trusted or has gone.
    var clearsSnapshot: Bool {
        switch self {
        case .waiting, .untrusted, .unreadable, .notConnected: return true
        case .downloading, .gone, .noReply: return false
        }
    }
}

/// The store build's data source (docs/APP.md, "The store build"): the signed relay folder the owner picked,
/// read like the iPhone app reads it, or the bundled sample. Answers, corrections and new tasks are signed
/// outbox entries; the result is the Mac's `sent/<id>.json`. In sample mode every send is simulated.
final class StoreBackend: TeylaBackend, Sendable {
    struct Timing: Sendable {
        /// How often `sent/` is read while an action waits, and how long to wait before giving up.
        var poll: Duration = .milliseconds(1500)
        var reply: Duration = .seconds(90)
        /// How long a simulated send takes.
        var simulated: Duration = .milliseconds(700)
    }

    private enum Source: Sendable {
        case none
        case sample
        case relay(RelayStore, Data)
    }

    private struct Inner: Sendable {
        var source: Source = .none
        var last: Snapshot?
    }

    private let inner = OSAllocatedUnfairLock(initialState: Inner())
    private let timing: Timing
    private let sampleData: @Sendable () -> Data?
    private let deviceName: @Sendable () -> String

    static let sampleMessage = "Sample: nothing was sent"

    init(timing: Timing = Timing(),
         sampleData: @escaping @Sendable () -> Data? = { StoreBackend.bundledSample() },
         deviceName: @escaping @Sendable () -> String = { RelayCrypto.sanitizedDevice(Host.current().localizedName ?? "", fallback: "Mac") }) {
        self.timing = timing
        self.sampleData = sampleData
        self.deviceName = deviceName
    }

    static func bundledSample() -> Data? {
        Bundle.main.url(forResource: "sample.v3", withExtension: "json").flatMap { try? Data(contentsOf: $0) }
    }

    // MARK: Source

    func useSample() { inner.withLock { $0 = Inner(source: .sample, last: nil) } }

    func useRelay(folder: URL, key: Data) {
        inner.withLock { $0 = Inner(source: .relay(RelayStore(folder: folder), key), last: nil) }
    }

    func disconnect() { inner.withLock { $0 = Inner() } }

    var usesFixture: Bool { inner.withLock { if case .sample = $0.source { return true } else { return false } } }

    // MARK: Reading

    func state() async throws -> Snapshot {
        let source = inner.withLock { $0.source }
        switch source {
        case .none:
            throw StoreError.notConnected
        case .sample:
            guard let data = sampleData(), let snapshot = try? JSONDecoder().decode(Snapshot.self, from: data) else {
                throw StoreError.unreadable("The bundled sample could not be read.")
            }
            return remember(snapshot)
        case .relay(let store, let key):
            let read = await Task.detached(priority: .utility) { store.readState() }.value
            // A reconnect while the file was read: this answer belongs to the old pairing, so it is dropped.
            guard case .relay(let now, let nowKey) = inner.withLock({ $0.source }),
                  now.folder == store.folder, nowKey == key else { return try await state() }
            do {
                switch read {
                case .missing: throw StoreError.waiting
                case .downloading: throw StoreError.downloading
                case .failed(let why): throw StoreError.unreadable(why)
                case .data(let file): return remember(try Self.snapshot(from: file, key: key))
                }
            } catch let failure as StoreError where failure.clearsSnapshot {
                // Nothing from a file that is gone or no longer verifies may be answered from the cache.
                inner.withLock { $0.last = nil }
                throw failure
            }
        }
    }

    /// Checks the signature first; nothing is decoded before it matches (docs/APP.md).
    static func snapshot(from file: Data, key: Data) throws -> Snapshot {
        switch RelayCrypto.verifyStateFile(file, key: key) {
        case .malformed, .badSignature:
            throw StoreError.untrusted
        case .valid(let json):
            guard let snapshot = try? JSONDecoder().decode(Snapshot.self, from: json) else {
                throw StoreError.unreadable("The Mac's snapshot could not be read. Update Teyla on the Mac.")
            }
            return snapshot
        }
    }

    private func remember(_ snapshot: Snapshot) -> Snapshot {
        inner.withLock { $0.last = snapshot }
        return snapshot
    }

    // MARK: Sending

    func answer(id: String, text: String) async throws -> AnswerResult {
        if usesFixture { return try await simulate(id: id) }
        guard let ask = lastSnapshot?.asks.first(where: { $0.id == id }) else {
            throw StoreError.gone("This question is no longer in the snapshot. Refresh and try again.")
        }
        return try await send(.answer, target: id, aboutText: ask.question, text: text)
    }

    func say(ref: String, text: String) async throws -> AnswerResult {
        if usesFixture { return try await simulate(id: ref) }
        guard let session = lastSnapshot?.running.first(where: { $0.ref == ref }) else {
            throw StoreError.gone("This session is no longer running. Refresh and try again.")
        }
        return try await send(.say, target: ref, aboutText: session.title, text: text)
    }

    /// The relay carries a product and a text; the Mac chooses the tool, so `harness` is not sent.
    func dispatch(product: String, harness: Harness, text: String) async throws -> AnswerResult {
        if usesFixture { return try await simulate(id: product) }
        return try await send(.dispatch, target: product, aboutText: product, text: text)
    }

    private var lastSnapshot: Snapshot? { inner.withLock { $0.last } }

    private func simulate(id: String) async throws -> AnswerResult {
        try await Task.sleep(for: timing.simulated)
        return AnswerResult(ok: true, via: "sample", detail: Self.sampleMessage, id: id)
    }

    /// Signs and writes one outbox entry, then waits for the Mac's `sent/` answer.
    private func send(_ kind: OutboxKind, target: String, aboutText: String, text: String) async throws -> AnswerResult {
        guard case .relay(let store, let key) = inner.withLock({ $0.source }) else { throw StoreError.notConnected }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let entry = try OutboxEntry.make(kind: kind, target: target, aboutText: aboutText, text: trimmed,
                                         device: deviceName(), key: key)
        try await Task.detached(priority: .userInitiated) { try store.writeOutbox(entry) }.value
        let id = entry.id
        let deadline = ContinuousClock.now + timing.reply
        while ContinuousClock.now < deadline {
            try await Task.sleep(for: timing.poll)
            let found = await Task.detached(priority: .utility) { store.readSent(ids: [id]).first }.value
            if let result = found {
                // The result is in hand; the Mac's file can go.
                await Task.detached(priority: .utility) { store.deleteSent(id: id) }.value
                guard result.ok else {
                    let why = result.detail.trimmingCharacters(in: .whitespacesAndNewlines)
                    throw TeylaError.failed(code: 1, message: why.isEmpty ? "The Mac could not deliver this." : String(why.prefix(300)))
                }
                return AnswerResult(ok: true, via: result.via, detail: result.detail, id: result.id)
            }
        }
        throw StoreError.noReply
    }

    // MARK: The command line

    /// There is no command to find. (Not a protocol default: on a concrete `TeylaCLI` an async default would
    /// win over the actor's own method and answer nil.)
    func binaryPath() async -> String? { nil }

    // MARK: Product pages

    func productPage(id: String, quick: Bool) async throws -> ProductPageData {
        let snapshot: Snapshot
        if let last = lastSnapshot { snapshot = last } else { snapshot = try await state() }
        return Self.page(for: id, in: snapshot, quick: quick)
    }

    /// The command writes the product page; here it is made from the snapshot: the header, the open questions,
    /// and the recent work (running sessions and sessions that ended). Spend is left out, and notes do not exist.
    static func page(for id: String, in snapshot: Snapshot, quick: Bool) -> ProductPageData {
        let product = snapshot.products.first { $0.name == id }
        let portfolio = snapshot.portfolio?.product(id)
        let header = ProductHeader(id: id, name: product?.title ?? portfolio?.title ?? "",
                                   stage: product?.stage ?? portfolio?.stage ?? "",
                                   focus: product?.focus ?? portfolio?.focus ?? false,
                                   primary: product?.primary ?? portfolio?.primary ?? "",
                                   registered: product?.registered ?? (portfolio != nil))
        let asks = snapshot.asks.filter { $0.product == id }.map {
            ProductAsk(id: $0.id, ageSeconds: $0.ageSeconds, critical: false, question: $0.question, link: $0.link)
        }
        guard !quick else { return ProductPageData(product: header, asks: asks, generated: snapshot.generated) }
        let running = snapshot.running.filter { $0.product == id }.map {
            ProductSession(id: $0.id, at: $0.since, harness: $0.harness, model: $0.model, title: $0.title)
        }
        let ended = snapshot.done.filter { $0.product == id }.map {
            ProductSession(id: $0.id, at: $0.ended, harness: $0.harness, title: $0.title)
        }
        let sessions = Array((running + ended).sorted { ($0.date ?? .distantPast) > ($1.date ?? .distantPast) }.prefix(10))
        return ProductPageData(product: header, asks: asks, sessions: sessions, generated: snapshot.generated)
    }
}

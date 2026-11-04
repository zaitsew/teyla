import Foundation

/// What became of a capture when the owner pressed Send. The overlay says this in words, so a
/// capture that stayed on the phone never reads as sent.
enum ReviewSaveOutcome: Equatable, Sendable {
    /// In the relay folder or accepted by the product's channel, on its way to the Mac.
    case sent
    /// In the app's Documents only: no route took it yet. `retryPending` tries again later.
    case savedOnPhone
    /// Not written. The comment and the screenshot are still in memory, so the owner can retry.
    case failed
}

/// One saved capture, as a product's own channel receives it.
public struct ReviewUpload: Sendable {
    public let id: String
    public let json: Data
    public let png: Data

    public init(id: String, json: Data, png: Data) {
        self.id = id
        self.json = json
        self.png = png
    }
}

/// Hands a capture to the product's channel. True only once the channel holds it. A capture sent
/// twice must count as delivered, because a retry cannot tell a lost answer from a lost upload.
public typealias ReviewDeliver = @Sendable (ReviewUpload) async -> Bool

/// Save on the phone first; then try the relay folder, then the product's channel.
enum ReviewDelivery {
    /// A failed copy or upload is not a failure: the capture is safe in Documents.
    static func save(
        record: CaptureRecord, png: Data,
        store: CaptureStore = CaptureStore(root: CaptureStore.defaultRoot()),
        keyStore: RelayKeyStoring = TeylaReview.keyStore,
        relayFolder: RelayFolder = TeylaReview.relayFolder,
        deliver: ReviewDeliver? = TeylaReview.effectiveDeliver,
        noticeAccepted: @Sendable () -> Bool = { ReviewNotice.isAccepted() }
    ) async -> ReviewSaveOutcome {
        let key = keyStore.load()
        do {
            try store.save(record: record, png: png, key: key)
        } catch {
            return .failed
        }
        let sent = await send(id: record.id, store: store, key: key, relayFolder: relayFolder, deliver: deliver, noticeAccepted: noticeAccepted)
        return sent ? .sent : .savedOnPhone
    }

    private static let retryLock = NSLock()
    private static var retrying = false

    private static func beginRetry() -> Bool {
        retryLock.lock()
        defer { retryLock.unlock() }
        guard !retrying else { return false }
        retrying = true
        return true
    }

    private static func endRetry() {
        retryLock.lock()
        retrying = false
        retryLock.unlock()
    }

    /// Signs every capture saved before pairing when there is a key, then sends every saved capture
    /// that no route has taken yet. Call it when the app becomes active, after the owner pairs, and
    /// after the owner picks the folder. A second call while one runs does nothing.
    static func retryPending(
        store: CaptureStore = CaptureStore(root: CaptureStore.defaultRoot()),
        keyStore: RelayKeyStoring = TeylaReview.keyStore,
        relayFolder: RelayFolder = TeylaReview.relayFolder,
        deliver: ReviewDeliver? = TeylaReview.effectiveDeliver,
        noticeAccepted: @Sendable () -> Bool = { ReviewNotice.isAccepted() }
    ) async {
        guard beginRetry() else { return }
        defer { endRetry() }
        let key = keyStore.load()
        if let key { store.signPending(key: key) }
        for id in store.list() {
            let status = store.readLocalStatus(id: id)
            guard status?.relayCopied == nil, status?.delivered == nil else { continue }
            _ = await send(id: id, store: store, key: key, relayFolder: relayFolder, deliver: deliver, noticeAccepted: noticeAccepted)
        }
    }

    /// The relay needs a key, because the Mac refuses an unsigned capture there. The product's
    /// channel does not: the signed-in account vouches for the capture instead. No route to a server,
    /// custom or built in, is tried until the tester has accepted the first-send notice: a capture
    /// saved earlier, or a `deliver` set later, must not leave the phone unannounced.
    private static func send(
        id: String, store: CaptureStore, key: RelayKey?, relayFolder: RelayFolder, deliver: ReviewDeliver?,
        noticeAccepted: @Sendable () -> Bool
    ) async -> Bool {
        if let key, relayFolder.withAccess({ (try? store.copyToRelay(id: id, relayRoot: $0, key: key)) != nil }) == true {
            return true
        }
        guard let deliver, noticeAccepted(), let upload = store.upload(id: id), await deliver(upload) else { return false }
        store.markDelivered(id: id)
        return true
    }
}

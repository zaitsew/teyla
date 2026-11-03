import Foundation

/// What became of a capture when the owner pressed Send. The overlay says this in words, so a
/// capture that stayed on the phone never reads as sent.
enum ReviewSaveOutcome: Equatable, Sendable {
    /// In the relay folder, on its way to the Mac.
    case sent
    /// In the app's Documents only: no key, no folder, or the copy failed. `retryPending` copies it later.
    case savedOnPhone
    /// Not written. The comment and the screenshot are still in memory, so the owner can retry.
    case failed
}

/// Save on the phone first; then, if there is a key and a folder, copy to the relay outbox.
enum ReviewDelivery {
    /// A failed copy to the relay is not a failure: the capture is safe in Documents.
    static func save(
        record: CaptureRecord, png: Data,
        store: CaptureStore = CaptureStore(root: CaptureStore.defaultRoot()),
        keyStore: RelayKeyStoring = TeylaReview.keyStore,
        relayFolder: RelayFolder = TeylaReview.relayFolder
    ) -> ReviewSaveOutcome {
        let key = keyStore.load()
        do {
            try store.save(record: record, png: png, key: key)
        } catch {
            return .failed
        }
        guard let key else { return .savedOnPhone }             // unsigned: it stays on the phone until the owner pairs
        let copied = relayFolder.withAccess { (try? store.copyToRelay(id: record.id, relayRoot: $0, key: key)) != nil } ?? false
        return copied ? .sent : .savedOnPhone
    }

    /// Signs every capture saved before pairing, then copies every saved capture that has not
    /// reached the relay. Call it when the app becomes active, after the owner pairs, and after the
    /// owner picks the folder.
    static func retryPending(
        store: CaptureStore = CaptureStore(root: CaptureStore.defaultRoot()),
        keyStore: RelayKeyStoring = TeylaReview.keyStore,
        relayFolder: RelayFolder = TeylaReview.relayFolder
    ) {
        guard let key = keyStore.load() else { return }
        store.signPending(key: key)
        for id in store.list() where store.readLocalStatus(id: id)?.relayCopied == nil {
            _ = relayFolder.withAccess { try? store.copyToRelay(id: id, relayRoot: $0, key: key) }
        }
    }
}

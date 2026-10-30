import Foundation

/// Save on the phone first; then, if there is a key and a folder, copy to the relay outbox.
enum ReviewDelivery {
    /// Shown in the overlay when the phone could not write the capture. The comment and the
    /// screenshot are still in memory, so the owner can retry.
    static let saveFailureMessage =
        "Could not save the capture on this device. Your comment and the screenshot are still here. Free some space, then tap Retry."

    /// Returns nil when the capture is saved on the phone, else the message to show. A failed copy to
    /// the relay is not a failure: the capture is safe in Documents and `retryPending` copies it later.
    static func save(
        record: CaptureRecord, png: Data,
        store: CaptureStore = CaptureStore(root: CaptureStore.defaultRoot()),
        keyStore: RelayKeyStoring = TeylaReview.keyStore,
        relayFolder: RelayFolder = TeylaReview.relayFolder
    ) -> String? {
        let key = keyStore.load()
        do {
            try store.save(record: record, png: png, key: key)
        } catch {
            return saveFailureMessage
        }
        guard let key else { return nil }                       // unsigned: it stays on the phone until the owner pairs
        _ = relayFolder.withAccess { try? store.copyToRelay(id: record.id, relayRoot: $0, key: key) }
        return nil
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

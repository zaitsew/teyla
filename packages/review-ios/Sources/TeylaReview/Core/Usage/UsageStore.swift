import CryptoKit
import Foundation

/// Usage events on the device: a ring buffer (the oldest are dropped first) with at most one batch in
/// flight. A batch keeps its id until the server has it, so a retry after a lost answer is not a second copy.
final class UsageStore {
    struct Batch: Codable, Equatable {
        var id: String
        var events: [UsageEvent]
    }

    struct State: Codable, Equatable {
        var v = 1
        var events: [UsageEvent] = []
        var pending: Batch?
    }

    static let defaultMaxEvents = 5_000
    static let defaultMaxBytes = 1_000_000

    let url: URL?
    let maxEvents: Int
    let maxBytes: Int
    private let lock = NSLock()
    private var state = State()
    private var unsaved = 0
    /// False from the moment a pending batch is made until a save that holds it succeeds.
    private var pendingSaved = true
    private let writer: (Data, URL) throws -> Void

    /// `url` nil keeps everything in memory (tests). `writer` is how the state reaches disk; tests pass one that fails.
    init(url: URL?, maxEvents: Int = defaultMaxEvents, maxBytes: Int = defaultMaxBytes,
         writer: @escaping (Data, URL) throws -> Void = { data, url in try data.write(to: url, options: .atomic) }) {
        self.url = url
        self.writer = writer
        self.maxEvents = max(1, maxEvents)
        self.maxBytes = max(1_000, maxBytes)
        if let url, let data = try? Data(contentsOf: url), let saved = try? JSONDecoder().decode(State.self, from: data) {
            state = saved
            trim()
        }
    }

    /// Application Support is shared by unsandboxed macOS apps, so the folder carries the bundle id: two
    /// apps on one Mac never read or send each other's events.
    static func defaultURL(bundleID: String? = Bundle.main.bundleIdentifier) -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        let safe = folderName(for: bundleID)
        return base.appendingPathComponent("TeylaReview", isDirectory: true)
            .appendingPathComponent(safe, isDirectory: true).appendingPathComponent("usage.json")
    }

    static let maxFolderName = 120

    /// The storage folder for a bundle id: the id with unsafe characters replaced. An id longer than the limit
    /// keeps a prefix and ends in 16 hex characters of the SHA-256 of the whole id, so two long ids that share
    /// their first characters never share a folder. A shorter id keeps the name it always had.
    static func folderName(for bundleID: String?) -> String {
        let id = bundleID ?? "unknown-app"
        let clean = String(id.drop(while: { $0 == "." }).map { $0.isLetter || $0.isNumber || $0 == "." || $0 == "-" ? $0 : "_" })
        guard clean.count > maxFolderName else { return clean }
        let hash = SHA256.hash(data: Data(id.utf8)).prefix(8).map { String(format: "%02x", $0) }.joined()
        return String(clean.prefix(maxFolderName - 17)) + "-" + hash
    }

    var events: [UsageEvent] { lock.lock(); defer { lock.unlock() }; return state.events }
    var pending: Batch? { lock.lock(); defer { lock.unlock() }; return state.pending }
    var count: Int { lock.lock(); defer { lock.unlock() }; return state.events.count + (state.pending?.events.count ?? 0) }

    func append(_ event: UsageEvent) {
        lock.lock()
        state.events.append(event)
        trim()
        unsaved += 1
        let due = unsaved >= 50
        lock.unlock()
        if due { flush() }
    }

    /// The pending batch if one is waiting, else the oldest events (up to the limits) as a new batch.
    /// A new batch is written to disk before it is returned, so a crash during the upload cannot
    /// make the next launch send the same events under another id.
    func nextBatch(maxEvents: Int, maxBytes: Int, makeID: () -> String = { UUID().uuidString.lowercased() }) -> Batch? {
        lock.lock()
        if let pending = state.pending, !pending.events.isEmpty {
            let saved = pendingSaved
            lock.unlock()
            // A batch that never reached disk is not sent: after a crash the next launch would send
            // the same events again under another id.
            if !saved && !flush() { return nil }
            return self.pending
        }
        state.pending = nil
        guard !state.events.isEmpty else { lock.unlock(); return nil }
        var take = 0, bytes = 0
        let encoder = JSONEncoder()
        for event in state.events {
            let size = (try? encoder.encode(event).count) ?? 200
            if take >= maxEvents || (take > 0 && bytes + size > maxBytes) { break }
            take += 1
            bytes += size
        }
        let batch = Batch(id: makeID(), events: Array(state.events.prefix(take)))
        state.events.removeFirst(take)
        state.pending = batch
        pendingSaved = false
        unsaved += 1
        lock.unlock()
        // The id is on disk before the upload starts. When the save fails the batch waits for the next attempt.
        guard flush(), pending?.id == batch.id else { return nil }
        return batch
    }

    /// The server has the batch: it leaves the device.
    func confirm(batchID: String) {
        lock.lock()
        if state.pending?.id == batchID { state.pending = nil }
        unsaved += 1
        lock.unlock()
        flush()
    }

    /// Nothing recorded stays: a declined tester.
    func purge() {
        lock.lock()
        state = State()
        pendingSaved = true
        unsaved = 0
        lock.unlock()
        if let url { try? FileManager.default.removeItem(at: url) }
    }

    /// Writes the state. True when it is on disk, or there is nothing to write; false when the write failed.
    @discardableResult
    func flush() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        unsaved = 0
        guard let url else { return true }
        // Nothing recorded and nothing on disk: a build that records nothing leaves no file.
        if state.events.isEmpty, state.pending == nil, !FileManager.default.fileExists(atPath: url.path) { return true }
        guard var data = try? JSONEncoder().encode(state) else { return false }
        // The byte cap: drop the oldest tenth until the file fits.
        while data.count > maxBytes, !(state.events.isEmpty && state.pending == nil) {
            if state.events.isEmpty { state.pending = nil } else { state.events.removeFirst(max(1, state.events.count / 10)) }
            guard let again = try? JSONEncoder().encode(state) else { return false }
            data = again
        }
        do {
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try writer(data, url)
        } catch {
            return false
        }
        pendingSaved = true
        return true
    }

    /// Called with the lock held. Pending events count against the cap, and go last.
    private func trim() {
        var over = state.events.count + (state.pending?.events.count ?? 0) - maxEvents
        guard over > 0 else { return }
        let fromEvents = min(over, state.events.count)
        state.events.removeFirst(fromEvents)
        over -= fromEvents
        if over > 0, var pending = state.pending {
            pending.events.removeFirst(min(over, pending.events.count))
            state.pending = pending.events.isEmpty ? nil : pending
        }
    }
}

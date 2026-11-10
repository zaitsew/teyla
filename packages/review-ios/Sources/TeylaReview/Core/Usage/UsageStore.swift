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

    /// `url` nil keeps everything in memory (tests).
    init(url: URL?, maxEvents: Int = defaultMaxEvents, maxBytes: Int = defaultMaxBytes) {
        self.url = url
        self.maxEvents = max(1, maxEvents)
        self.maxBytes = max(1_000, maxBytes)
        if let url, let data = try? Data(contentsOf: url), let saved = try? JSONDecoder().decode(State.self, from: data) {
            state = saved
            trim()
        }
    }

    static func defaultURL() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        return base.appendingPathComponent("TeylaReview", isDirectory: true).appendingPathComponent("usage.json")
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
    func nextBatch(maxEvents: Int, maxBytes: Int, makeID: () -> String = { UUID().uuidString.lowercased() }) -> Batch? {
        lock.lock(); defer { lock.unlock() }
        if let pending = state.pending, !pending.events.isEmpty { return pending }
        state.pending = nil
        guard !state.events.isEmpty else { return nil }
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
        unsaved += 1
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
        unsaved = 0
        lock.unlock()
        if let url { try? FileManager.default.removeItem(at: url) }
    }

    func flush() {
        lock.lock()
        defer { lock.unlock() }
        unsaved = 0
        guard let url else { return }
        // Nothing recorded and nothing on disk: a build that records nothing leaves no file.
        if state.events.isEmpty, state.pending == nil, !FileManager.default.fileExists(atPath: url.path) { return }
        guard var data = try? JSONEncoder().encode(state) else { return }
        // The byte cap: drop the oldest tenth until the file fits.
        while data.count > maxBytes, !(state.events.isEmpty && state.pending == nil) {
            if state.events.isEmpty { state.pending = nil } else { state.events.removeFirst(max(1, state.events.count / 10)) }
            guard let again = try? JSONEncoder().encode(state) else { return }
            data = again
        }
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? data.write(to: url, options: .atomic)
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

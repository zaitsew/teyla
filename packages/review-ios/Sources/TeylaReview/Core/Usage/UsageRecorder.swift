import Foundation

/// Turns the app's calls into usage events. Every entry point first asks `isActive` (debug or TestFlight
/// with review mode on) and `mayRecord` (the tester has not declined); a store build fails the first and
/// records nothing. The clock is injected so the dead-end and repeat-tap rules are testable.
final class UsageRecorder {
    static let deadEndWithin: TimeInterval = 2
    static let repeatTapWindow: TimeInterval = 1
    static let repeatTapCount = 3
    /// A return to the foreground after this long closes the old session with an `end` and opens a new one.
    static let sessionGap: TimeInterval = 30 * 60
    static let maxDecisions = 20

    let store: UsageStore
    private let isActive: () -> Bool
    private let mayRecord: () -> Bool
    private let now: () -> Date
    private let build: () -> String
    private let lock = NSLock()

    private var allow = UsageAllowList()
    private var variants: [String: String] = [:]
    private var current: (id: String, at: Date, suppressed: Bool)?
    private var taps: [String: [Date]] = [:]
    private var taskStarts: [String: Date] = [:]
    private var active = false
    private var lastBackground: Date?

    init(store: UsageStore, isActive: @escaping () -> Bool, mayRecord: @escaping () -> Bool = { true },
         now: @escaping () -> Date = Date.init, build: @escaping () -> String) {
        self.store = store
        self.isActive = isActive
        self.mayRecord = mayRecord
        self.now = now
        self.build = build
    }

    private var enabled: Bool { isActive() && mayRecord() }

    // MARK: setup

    /// The routes, action ids and task names that may be recorded. An entry that is not a plain id
    /// (letters, digits, dot, dash, underscore) is ignored, so a title cannot end up on the list.
    func configure(screens: [String], actions: [String], tasks: [String]) {
        guard isActive() else { return }
        lock.lock(); defer { lock.unlock() }
        allow = UsageAllowList(
            screens: Set(screens.filter(UsageID.isValid)),
            actions: Set(actions.filter(UsageID.isValid)),
            tasks: Set(tasks.filter(UsageID.isValid)))
    }

    var declared: UsageAllowList { lock.lock(); defer { lock.unlock() }; return allow }

    func setVariant(decision: String, variant: String) {
        guard isActive(), UsageID.isToken(decision), UsageID.isToken(variant) else { return }
        lock.lock(); defer { lock.unlock() }
        guard variants[decision] != nil || variants.count < Self.maxDecisions else { return }
        variants[decision] = variant
    }

    func clearVariant(decision: String) {
        lock.lock(); defer { lock.unlock() }
        variants[decision] = nil
    }

    // MARK: events

    func screen(_ route: String) {
        guard enabled else { return }
        let id = UsageID.normalize(route)
        let n = now()
        lock.lock(); defer { lock.unlock() }
        guard allow.screens.contains(id) else { return }
        if let cur = current, cur.id == id { return }       // the same screen appearing again
        if let cur = current, !cur.suppressed, n.timeIntervalSince(cur.at) <= Self.deadEndWithin {
            append(.deadEnd, id: cur.id, r: "screen", ms: millis(n.timeIntervalSince(cur.at)), at: n)
        }
        append(.screen, id: id, at: n)
        current = (id, n, false)
    }

    /// A sheet closed. When nothing in it changed, it was a dead end.
    func sheetDismissed(_ route: String, changed: Bool) {
        guard enabled, !changed else { return }
        let id = UsageID.normalize(route)
        let n = now()
        lock.lock(); defer { lock.unlock() }
        guard allow.screens.contains(id) else { return }
        append(.deadEnd, id: id, r: "sheet", at: n)
    }

    func action(_ rawID: String, result: UsageActionResult) {
        guard enabled else { return }
        let id = UsageID.normalize(rawID)
        lock.lock(); defer { lock.unlock() }
        guard allow.actions.contains(id) else { return }
        append(.action, id: id, r: result.rawValue, at: now())
    }

    /// A tap on an element. Three within a second on the same one is a `repeat_tap`.
    func tap(_ rawID: String) {
        guard enabled else { return }
        let id = UsageID.normalize(rawID)
        let n = now()
        lock.lock(); defer { lock.unlock() }
        guard allow.actions.contains(id) else { return }
        var recent = (taps[id] ?? []).filter { n.timeIntervalSince($0) <= Self.repeatTapWindow }
        recent.append(n)
        if recent.count >= Self.repeatTapCount {
            append(.repeatTap, id: id, at: n)
            taps[id] = []
        } else {
            taps[id] = recent
        }
    }

    func task(_ name: String, _ phase: UsageTaskPhase) {
        guard enabled else { return }
        let n = now()
        lock.lock(); defer { lock.unlock() }
        guard allow.tasks.contains(name) else { return }
        switch phase {
        case .start:
            taskStarts[name] = n
            append(.task, id: name, r: phase.rawValue, at: n)
        case .success, .cancel:
            let ms = taskStarts.removeValue(forKey: name).map { millis(n.timeIntervalSince($0)) }
            append(.task, id: name, r: phase.rawValue, ms: ms, at: n)
        }
    }

    // MARK: session

    func appBecameActive() {
        guard enabled else { return }
        let n = now()
        lock.lock(); defer { lock.unlock() }
        guard !active else { return }
        active = true
        if let left = lastBackground, n.timeIntervalSince(left) > Self.sessionGap {
            append(.session, r: "end", at: left)
            taskStarts = [:]
        }
        lastBackground = nil
        append(.session, r: "start", at: n)
        if current != nil { current?.suppressed = true }     // a screen that was open while away is not a dead end
    }

    func appWentToBackground() {
        guard enabled else { return }
        let n = now()
        lock.lock()
        guard active else { lock.unlock(); return }
        active = false
        lastBackground = n
        append(.session, r: "background", at: n)
        lock.unlock()
        store.flush()
    }

    func appWillTerminate() {
        guard enabled else { return }
        let n = now()
        lock.lock()
        if active { append(.session, r: "background", at: n) }
        append(.session, r: "end", at: n)
        active = false
        lock.unlock()
        store.flush()
    }

    // MARK: helpers

    private func millis(_ seconds: TimeInterval) -> Int { max(0, Int((seconds * 1000).rounded())) }

    /// Called with the lock held.
    private func append(_ kind: UsageEvent.Kind, id: String? = nil, r: String? = nil, ms: Int? = nil, at date: Date) {
        store.append(UsageEvent(
            t: Int(date.timeIntervalSince1970), k: kind, id: id, r: r, ms: ms, b: build(),
            d: variants.isEmpty ? nil : variants))
    }
}

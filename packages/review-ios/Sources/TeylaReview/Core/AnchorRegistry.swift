import CoreGraphics
import Foundation

/// One registered element: what `.reviewAnchor("screen.element")` records.
struct Anchor: Equatable {
    var id: String
    var screen: String?
    var parent: String?
    var role: ReviewRole
    var bounds: CGRect          // window coordinates, in points, as of the snapshot
    var strings: [String]
    var file: String
    var line: Int
    var seq: Int                // registration order: later is on top when two anchors tie
}

/// The anchors that are on screen now. A view registers under its own token, not its id, so two
/// rows that share an id (a list cell) both stay. Bounds are read when a capture is taken, not
/// when the view appears, so a scrolled list still reports where its rows are.
final class AnchorRegistry: @unchecked Sendable {
    static let shared = AnchorRegistry()

    private struct Entry {
        var anchor: Anchor
        var bounds: () -> CGRect?     // nil: the view is gone
    }

    private let lock = NSLock()
    private var entries: [UUID: Entry] = [:]
    private var counter = 0
    private var current: String?

    func register(
        token: UUID, id: String, screen: String?, parent: String?, role: ReviewRole, strings: [String],
        file: String, line: Int, bounds: @escaping () -> CGRect?
    ) {
        lock.lock(); defer { lock.unlock() }
        let seq: Int
        if let old = entries[token] { seq = old.anchor.seq } else { counter += 1; seq = counter }
        let anchor = Anchor(id: id, screen: screen, parent: parent, role: role, bounds: .zero, strings: strings,
                            file: file, line: line, seq: seq)
        entries[token] = Entry(anchor: anchor, bounds: bounds)
    }

    func remove(token: UUID) {
        lock.lock(); defer { lock.unlock() }
        entries[token] = nil
    }

    func reset() {
        lock.lock(); defer { lock.unlock() }
        entries = [:]; counter = 0; current = nil
    }

    var currentScreen: String? {
        lock.lock(); defer { lock.unlock() }
        return current
    }

    func setScreen(_ id: String?) {
        lock.lock(); defer { lock.unlock() }
        current = id
    }

    /// Every anchor with its bounds as of now, oldest registration first. Anchors with empty
    /// bounds (a view in another tab, or not in a window) are left out; anchors whose view is
    /// gone are dropped from the registry.
    func snapshot() -> [Anchor] {
        lock.lock()
        let list = Array(entries)
        lock.unlock()
        var out: [Anchor] = []
        var gone: [UUID] = []
        for (token, e) in list {
            guard let rect = e.bounds() else { gone.append(token); continue }
            var a = e.anchor
            a.bounds = rect
            if rect.width > 0, rect.height > 0 { out.append(a) }
        }
        if !gone.isEmpty {
            lock.lock()
            for token in gone { entries[token] = nil }
            lock.unlock()
        }
        return out.sorted { $0.seq < $1.seq }
    }

    /// The screen an anchor belongs to: the screen modifier above it, else the part of its id before
    /// the last dot ("trip.timeline.addButton" is on "trip.timeline"), else the registered screen.
    static func resolveScreen(id: String, environment: String?, current: String?) -> String? {
        if let environment, !environment.isEmpty { return environment }
        if let dot = id.lastIndex(of: "."), dot != id.startIndex { return String(id[..<dot]) }
        return current
    }
}

enum HitTester {
    /// The smallest anchor that contains the point; the later registration wins a tie. The left
    /// and top edges are inside, the right and bottom edges are outside.
    static func hit(x: Double, y: Double, in anchors: [Anchor]) -> Anchor? {
        var best: Anchor?
        for a in anchors {
            let r = a.bounds
            guard r.width > 0, r.height > 0 else { continue }
            guard x >= Double(r.minX), x < Double(r.maxX), y >= Double(r.minY), y < Double(r.maxY) else { continue }
            guard let b = best else { best = a; continue }
            let areaA = r.width * r.height, areaB = b.bounds.width * b.bounds.height
            if areaA < areaB || (areaA == areaB && a.seq > b.seq) { best = a }
        }
        return best
    }

    /// The screen to write in the capture: the one registered with `TeylaReview.screen`, else the
    /// hit element's, else the one most anchors share.
    static func screen(current: String?, hit: Anchor?, anchors: [Anchor]) -> String? {
        if let current, !current.isEmpty { return current }
        if let s = hit?.screen { return s }
        var counts: [String: Int] = [:]
        for a in anchors { if let s = a.screen { counts[s, default: 0] += 1 } }
        return counts.max { $0.value < $1.value || ($0.value == $1.value && $0.key > $1.key) }?.key
    }
}

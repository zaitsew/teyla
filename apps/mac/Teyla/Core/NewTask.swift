import Foundation

/// Which tool starts a new task. Codex is the default.
enum Harness: String, CaseIterable, Identifiable, Sendable {
    case codex, claude

    var id: String { rawValue }
    var label: String { self == .codex ? "Codex" : "Claude" }
}

enum NewTask {
    /// Products a task can start in: a real name (not the "(no repo)" bucket).
    static func products(_ all: [Product]) -> [Product] {
        all.filter { !$0.name.isEmpty && !$0.name.hasPrefix("(") }
    }

    /// The product the sheet opens with: the selected one when it is still listed, else the first.
    static func defaultProduct(selected: String?, among all: [Product]) -> String? {
        let names = products(all).map(\.name)
        if let selected, names.contains(selected) { return selected }
        return names.first
    }

    static func canSend(product: String?, text: String) -> Bool {
        guard let product, !product.isEmpty else { return false }
        return !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

/// Remembers which questions were already shown to the owner as a notification. The first
/// snapshot only seeds the set, so launching the app never notifies about questions that were
/// already open, and a question is announced at most once per run.
struct AskTracker: Equatable {
    private var known: Set<String> = []
    private var seeded = false

    mutating func fresh(in asks: [Ask], hidden: Set<String>) -> [Ask] {
        defer {
            known.formUnion(asks.map(\.id))
            seeded = true
        }
        guard seeded else { return [] }
        return asks.filter { !known.contains($0.id) && !hidden.contains($0.id) }
    }
}

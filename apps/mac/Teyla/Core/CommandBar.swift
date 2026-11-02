import Foundation

/// One line of the ⌘K command bar. The list is fixed: it holds go-to pages, New task, Refresh, and the actions the
/// Tools page shows right now. No model is asked, and nothing the owner types becomes a command.
struct CommandEntry: Identifiable, Equatable, Sendable {
    enum Kind: Equatable, Sendable {
        case go(AppRoute)
        case newTask
        case refresh
        /// An action on the Tools page: choosing it opens that card at its preview or confirm step; it never runs by itself.
        case tool(itemID: String, action: ToolAction)
    }

    var id: String
    var title: String
    /// The line under the title: the exact command for a tool action, else a few words.
    var detail: String
    var symbol: String
    var kind: Kind
    /// Other words the entry is found by, besides its title.
    var keywords: [String] = []

    /// True for an entry that can change the machine, so the bar names its command and says a confirm follows.
    var changesState: Bool {
        if case .tool(_, let action) = kind { return ToolCommands.effect(action.command) != .reads }
        return false
    }
}

enum CommandBar {
    /// The entries for the current state. A product appears by name when it has a page to open.
    static func entries(products: [(id: String, name: String)], report: AttentionReport?, capabilities: Capabilities) -> [CommandEntry] {
        var out: [CommandEntry] = [
            CommandEntry(id: "go:home", title: "Go to Home", detail: "Core products and top decisions", symbol: "house", kind: .go(.home),
                         keywords: ["home", "core"]),
            CommandEntry(id: "go:decisions", title: "Go to Decisions", detail: "Questions that wait on you", symbol: "tray", kind: .go(.decisions),
                         keywords: ["decisions", "questions", "asks"]),
            CommandEntry(id: "go:portfolio", title: "Go to All products", detail: "Every product, with its health", symbol: "square.grid.2x2",
                         kind: .go(.portfolio), keywords: ["products", "portfolio"]),
        ]
        if capabilities.tools {
            out.append(CommandEntry(id: "go:tools", title: "Go to Tools", detail: "What is wrong on this Mac's backend", symbol: "wrench.and.screwdriver",
                                    kind: .go(.tools), keywords: ["tools", "attention", "backend"]))
        }
        for product in products where ProductCommands.isProductID(product.id) && !product.id.hasPrefix("(") {
            out.append(CommandEntry(id: "product:\(product.id)", title: "Open \(product.name)", detail: "Product page", symbol: "shippingbox",
                                    kind: .go(.product(product.id)), keywords: [product.id]))
        }
        out.append(CommandEntry(id: "new-task", title: "New task", detail: "⌘N", symbol: "square.and.pencil", kind: .newTask, keywords: ["dispatch", "start"]))
        out.append(CommandEntry(id: "refresh", title: "Refresh", detail: "Read everything again", symbol: "arrow.clockwise", kind: .refresh, keywords: ["reload", "update"]))
        if capabilities.tools, let report {
            for item in report.items {
                for action in item.actions where ToolCommands.check(action.command).isAllowed {
                    out.append(CommandEntry(id: "tool:\(item.id):\(action.id)", title: "\(action.label): \(item.title)",
                                            detail: ToolCommands.display(action.command), symbol: item.symbol,
                                            kind: .tool(itemID: item.id, action: action), keywords: [item.kind]))
                }
            }
        }
        return out
    }

    /// Plain matching, no model: every word of the query must start a word in the title or a keyword, or sit inside the title.
    /// Entries that start with the query come first; the order the entries came in breaks ties.
    static func filter(_ entries: [CommandEntry], query: String) -> [CommandEntry] {
        let words = query.lowercased().split(whereSeparator: { $0.isWhitespace }).map(String.init)
        guard !words.isEmpty else { return entries }
        var scored: [(score: Int, index: Int, entry: CommandEntry)] = []
        for (index, entry) in entries.enumerated() {
            guard let score = score(entry, words: words) else { continue }
            scored.append((score, index, entry))
        }
        return scored.sorted { ($0.score, $0.index) < ($1.score, $1.index) }.map(\.entry)
    }

    /// Lower is better; nil is no match.
    private static func score(_ entry: CommandEntry, words: [String]) -> Int? {
        let title = entry.title.lowercased()
        let titleWords = title.split(whereSeparator: { !$0.isLetter && !$0.isNumber }).map(String.init)
        let keys = entry.keywords.map { $0.lowercased() }
        // A tool action is also found by its command: "sweep" finds "Free space".
        var command = ""
        if case .tool = entry.kind { command = entry.detail.lowercased() }
        var total = 0
        for word in words {
            if title.hasPrefix(word) {
                total += 0
            } else if titleWords.contains(where: { $0.hasPrefix(word) }) {
                total += 1
            } else if keys.contains(where: { $0.hasPrefix(word) }) {
                total += 2
            } else if title.contains(word) {
                total += 3
            } else if !command.isEmpty, command.contains(word) {
                total += 4
            } else {
                return nil
            }
        }
        return total
    }

    /// The highlighted row after an arrow key; it stops at the ends instead of wrapping, so Return never lands somewhere unseen.
    static func moved(_ selection: Int, by step: Int, count: Int) -> Int {
        guard count > 0 else { return 0 }
        return min(max(selection + step, 0), count - 1)
    }

    /// The row to highlight after the list changed.
    static func clamped(_ selection: Int, count: Int) -> Int {
        guard count > 0 else { return 0 }
        return min(max(selection, 0), count - 1)
    }
}

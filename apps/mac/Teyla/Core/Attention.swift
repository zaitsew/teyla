import Foundation

// `teyla attention --json` (docs/COMMANDS.md): what is wrong on this Mac's backend now. Decoding is lenient like the
// snapshot's: an unknown field is ignored, and one item the app cannot read is skipped rather than blanking the list.
// The one thing it never does is turn a failure into calm: the page says "Nothing needs you here" only for a report
// that was read and holds no item.

/// A command the CLI already has, with the preview that shows its effect first.
struct ToolAction: Decodable, Equatable, Hashable, Sendable, Identifiable {
    var label: String
    /// Arguments of `teyla`, without the leading "teyla".
    var command: [String]
    var preview: [String]?
    /// True when the command removes something or cannot be undone: it always asks, with the exact command shown.
    var destructive: Bool

    var id: String { command.joined(separator: " ") }

    enum CodingKeys: String, CodingKey { case label, command, preview, destructive }

    init(label: String, command: [String], preview: [String]? = nil, destructive: Bool = false) {
        self.label = label
        self.command = command
        self.preview = preview
        self.destructive = destructive
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        command = try c.decode([String].self, forKey: .command)
        label = c.lenient(.label, "Run")
        let preview: [String]? = c.optional(.preview)
        self.preview = (preview?.isEmpty ?? true) ? nil : preview
        destructive = c.lenient(.destructive, true)         // an unreadable flag is treated as the careful answer
    }
}

/// A line of context under an item's sentence: an offer's trade-off and undo, a doctor row's fix.
struct ToolFact: Decodable, Equatable, Hashable, Sendable {
    var label: String
    var text: String

    enum CodingKeys: String, CodingKey { case label, text }

    init(label: String, text: String) {
        self.label = label
        self.text = text
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        label = c.lenient(.label, "")
        text = try c.decode(String.self, forKey: .text)
    }
}

struct AttentionItem: Decodable, Equatable, Hashable, Sendable, Identifiable {
    var id: String
    /// `schedule`, `p1`, `disk`, `offer`, `doctor`, `build`, `guard` or `unknown`. A kind this app does not know reads as `unknown`.
    var kind: String
    var title: String
    var detail: String
    var product: String
    /// `act` needs the owner; `info` is worth a look. Anything else reads as `act`: an unreadable severity is not calm.
    var severity: String
    var facts: [ToolFact]
    var actions: [ToolAction]

    enum CodingKeys: String, CodingKey { case id, kind, title, detail, product, severity, facts, actions }

    init(id: String, kind: String = "unknown", title: String, detail: String = "", product: String = "",
         severity: String = "act", facts: [ToolFact] = [], actions: [ToolAction] = []) {
        self.id = id
        self.kind = kind
        self.title = title
        self.detail = detail
        self.product = product
        self.severity = severity
        self.facts = facts
        self.actions = actions
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = try c.decode(String.self, forKey: .title)
        let kind = c.lenient(.kind, "unknown")
        self.kind = Self.kinds.contains(kind) ? kind : "unknown"
        detail = c.lenient(.detail, "")
        product = c.lenient(.product, "")
        let severity = c.lenient(.severity, "act")
        self.severity = severity == "info" ? "info" : "act"
        let facts: [LossyBox<ToolFact>] = c.lenient(.facts, [])
        self.facts = facts.compactMap(\.value)
        let actions: [LossyBox<ToolAction>] = c.lenient(.actions, [])
        self.actions = actions.compactMap(\.value)
    }

    static let kinds: Set<String> = ["schedule", "p1", "disk", "offer", "doctor", "build", "guard", "unknown"]

    var needsYou: Bool { severity == "act" }

    /// The SF Symbol of the kind. The card never relies on the symbol alone: the title says the same.
    var symbol: String {
        switch kind {
        case "schedule": return "clock.badge.exclamationmark"
        case "p1": return "exclamationmark.bubble"
        case "disk": return "internaldrive"
        case "offer": return "sparkles"
        case "doctor": return "stethoscope"
        case "build": return "shippingbox"
        case "guard": return "gauge.with.dots.needle.67percent"
        default: return "questionmark.circle"
        }
    }
}

struct AttentionReport: Decodable, Equatable, Sendable {
    var version: Int
    var generated: String
    var items: [AttentionItem]
    /// What was checked and is fine, as the CLI printed it: counts and short words ("disk": "23 GB free").
    var quiet: [String: String]

    enum CodingKeys: String, CodingKey { case version, generated, items, quiet }

    init(version: Int = 1, generated: String = "", items: [AttentionItem] = [], quiet: [String: String] = [:]) {
        self.version = version
        self.generated = generated
        self.items = items
        self.quiet = quiet
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // A report with no `items` key is not a report: refuse it rather than show "Nothing needs you here".
        let items = try c.decode([LossyBox<AttentionItem>].self, forKey: .items)
        self.items = items.compactMap(\.value)
        version = c.lenient(.version, 1)
        generated = c.lenient(.generated, "")
        let raw: [String: QuietValue] = c.lenient(.quiet, [:])
        quiet = raw.mapValues(\.text)
        // An item the app could not read is a fault of its own, not a smaller list.
        if items.contains(where: { $0.value == nil }) {
            self.items.append(AttentionItem(id: "unknown:app", kind: "unknown", title: "Some items could not be read",
                                            detail: "This version of Teyla did not understand \(items.filter { $0.value == nil }.count) item(s) the command printed.",
                                            severity: "info"))
        }
    }

    /// Items that need the owner: the sidebar badge counts these only.
    var actCount: Int { items.filter(\.needsYou).count }

    static func decode(_ data: Data) throws -> AttentionReport {
        do {
            return try JSONDecoder().decode(AttentionReport.self, from: data)
        } catch {
            throw TeylaError.badOutput("not an attention report")
        }
    }

    /// The quiet line: what was checked and is fine, in one sentence. Empty when the command printed no counts.
    var quietLine: String { Self.quietLine(quiet) }

    static func quietLine(_ quiet: [String: String]) -> String {
        var parts: [String] = []
        for key in quietOrder {
            guard let value = quiet[key], !value.isEmpty else { continue }
            parts.append(phrase(key, value))
        }
        for key in quiet.keys.sorted() where !quietOrder.contains(key) {
            if let value = quiet[key], !value.isEmpty { parts.append("\(key.replacingOccurrences(of: "_", with: " ")) \(value)") }
        }
        return parts.joined(separator: " · ")
    }

    private static let quietOrder = ["schedules", "schedules_unverified", "builds", "disk", "guard", "doctor", "offers"]

    private static func phrase(_ key: String, _ value: String) -> String {
        switch key {
        case "schedules": return "\(value) scheduled tasks fine"
        case "schedules_unverified": return "\(value) not verifiable"
        case "builds": return "\(value) builds current"
        case "disk": return "disk \(value)"
        case "guard": return "machine \(value)"
        case "doctor": return "doctor \(value)"
        case "offers": return "offers \(value)"
        default: return "\(key) \(value)"
        }
    }
}

/// A quiet value is a number or a word; the page shows both as text.
private struct QuietValue: Decodable {
    let text: String

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let s = try? c.decode(String.self) {
            text = s
        } else if let i = try? c.decode(Int.self) {
            text = String(i)
        } else if let d = try? c.decode(Double.self) {
            text = String(d)
        } else if let b = try? c.decode(Bool.self) {
            text = b ? "yes" : "no"
        } else {
            text = ""
        }
    }
}

/// What the Tools page is doing: nothing yet, reading, a report, or a failure. A failure keeps the last report, if any,
/// and says so: the page never shows an old "all good" as if it were new.
enum AttentionPhase: Equatable, Sendable {
    case idle
    case loading
    case ready
    case failed(String)
}

/// What the Tools page says about itself. Plain words, no model.
enum ToolsPage {
    /// The page's one sentence. "Nothing needs you here" is said for a report that was read and is empty, and for nothing else.
    static func headline(report: AttentionReport?, phase: AttentionPhase) -> String {
        if case .failed = phase {
            return report == nil ? "Teyla could not read what is wrong on this Mac." : "The last read failed. This list may be out of date."
        }
        guard let report else { return "Reading what is wrong on this Mac…" }
        let (act, info) = sections(report)
        if report.items.isEmpty { return "Nothing needs you here." }
        if act.isEmpty { return "\(info.count) \(info.count == 1 ? "thing" : "things") to look at." }
        let first = "\(act.count) \(act.count == 1 ? "thing needs" : "things need") you"
        return info.isEmpty ? first + "." : first + " and \(info.count) more to look at."
    }

    static func sections(_ report: AttentionReport) -> (act: [AttentionItem], info: [AttentionItem]) {
        (report.items.filter(\.needsYou), report.items.filter { !$0.needsYou })
    }

    /// "Read 3 min ago", from the moment the app got the report.
    static func ageLine(readAt: Date?, now: Date) -> String {
        guard let readAt else { return "" }
        let s = max(0, Int(now.timeIntervalSince(readAt)))
        if s < 60 { return "Read just now" }
        if s < 3600 { return "Read \(s / 60) min ago" }
        if s < 86_400 { return "Read \(s / 3600) h ago" }
        return "Read \(s / 86_400) d ago"
    }

    /// The card's lead words for a run that finished or stopped.
    static func runLine(_ run: ToolRun) -> String {
        switch run {
        case .previewing: return "Reading the preview…"
        case .preview: return "Preview"
        case .confirming: return "This will run"
        case .running: return "Running…"
        case .done: return "Done"
        case .failed: return "It did not work"
        case .refused: return "Not run"
        }
    }
}

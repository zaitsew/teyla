import Foundation

// The words of the startup page (docs/STARTUP.md). The CLI decides every fact: the stage, the rungs, the metrics. This file
// only turns what it sends into short sentences. A figure the CLI sends as null is a dash with the reason, never a zero.
// Nothing here suggests closing a product: zero sale attempts reads "not tried yet" (POLICY section 19).
// It holds no view, so a test runs it and the iPhone app can compile it by path.

/// The four product types the owner can choose (`teyla product set <id> type=<type>`). Teyla never infers one.
enum StartupType: String, CaseIterable, Sendable {
    case venture
    case indie
    case openSource = "open-source"
    case personal

    var title: String {
        switch self {
        case .venture: return "Venture"
        case .indie: return "Indie"
        case .openSource: return "Open source"
        case .personal: return "Personal"
        }
    }

    /// The one measure the type is judged by, in the words of docs/STARTUP.md.
    var northStar: String {
        switch self {
        case .venture: return "Weekly growth of revenue, or of weekly users while it does not charge."
        case .indie: return "Revenue above its AI cost."
        case .openSource: return "People other than the author using it every week."
        case .personal: return "You still use it after 30 days."
        }
    }

    /// A type the CLI sent that this app does not know reads as its own words, never as another type.
    static func title(of raw: String) -> String {
        StartupType(rawValue: raw)?.title ?? raw.capitalized
    }
}

/// A rung's status as the CLI sends it.
enum RungState: String, Sendable {
    case met, missing, unknown, stale
    case notApplicable = "not_applicable"

    var word: String {
        switch self {
        case .met: return "Met"
        case .missing: return "Missing"
        case .unknown: return "Unknown"
        case .stale: return "Stale"
        case .notApplicable: return "Not applicable"
        }
    }

    /// An SF Symbol that says it without colour: a tick, an empty circle, a question mark, a clock, a dash.
    var symbol: String {
        switch self {
        case .met: return "checkmark.circle.fill"
        case .missing: return "circle"
        case .unknown: return "questionmark.circle"
        case .stale: return "clock.badge.exclamationmark"
        case .notApplicable: return "minus.circle"
        }
    }

    static func word(for raw: String) -> String { RungState(rawValue: raw)?.word ?? raw.capitalized }
}

/// One figure of the metrics: a label, a value (nil is a dash) and the reason or the small line under it.
struct StartupTile: Equatable, Sendable {
    var label: String
    var value: String?
    var detail: String
}

struct StartupGroup: Equatable, Sendable {
    var id: String
    var title: String
    var tiles: [StartupTile]
    /// A line under the group: what an agent logged, or why the whole group is off.
    var note = ""
}

enum StartupText {
    // MARK: The head of the page

    /// The sentence a person reads first: the next fact the product is missing.
    static func sentence(_ block: StartupBlock) -> String {
        if let next = block.next, !next.text.isEmpty { return next.text }
        if block.next != nil { return "One step on the ladder is not met yet." }
        return "Every step of this ladder is met."
    }

    /// "Venture", or "Type not chosen" for a product whose type nobody set.
    static func typeWord(_ block: StartupBlock) -> String {
        block.typeSet ? StartupType.title(of: block.type) : "Type not chosen"
    }

    /// What a product with no type does: it reads as venture, and the page says so.
    static func typeNote(_ block: StartupBlock) -> String? {
        block.typeSet ? nil : "No type is chosen, so the venture ladder is used until you choose one."
    }

    /// When the usage was read, in words. A stale read says what that costs: a stale step earns nothing.
    static func asOf(_ block: StartupBlock, now: Date) -> String {
        guard let raw = block.asOf, let date = ISODate.parse(raw) else {
            return "No usage probe has reported, so the usage steps are unknown."
        }
        let when = Format.ago(seconds: now.timeIntervalSince(date))
        if block.stale {
            return "Usage was read \(when). That is stale: steps that read usage earn nothing until it is read again."
        }
        return "Usage was read \(when)."
    }

    // MARK: The ladder

    /// The rungs in the order the CLI sends them. `next` marks the first one that is not met.
    static func isNext(_ rung: StartupRung, in block: StartupBlock) -> Bool { block.next?.rung == rung.id }

    // MARK: The metrics

    static func count(_ value: Int?) -> String? { value.map { "\($0)" } }

    private static let noProbe = "No usage probe reports this."

    /// The groups to show. A personal product is not for sale, so it has no marketing or sales group.
    static func groups(_ block: StartupBlock) -> [StartupGroup] {
        let m = block.metrics
        var out: [StartupGroup] = []
        if block.type != "personal" {
            out.append(marketing(m.marketing, sales: m.sales))
            out.append(sales(m.sales))
        }
        out.append(usage(m.usage, personal: block.type == "personal"))
        out.append(money(m.money))
        out.append(growth(m.growth))
        return out
    }

    private static func marketing(_ m: StartupMarketing, sales: StartupSales) -> StartupGroup {
        let untried = (m.posts ?? 0) + (m.adsOutreach ?? 0) + (sales.icpMeetings ?? 0) == 0
            && m.posts != nil && m.adsOutreach != nil && sales.icpMeetings != nil
        return StartupGroup(id: "marketing", title: "Marketing", tiles: [
            StartupTile(label: "Posts", value: count(m.posts),
                        detail: m.posts == nil ? "The growth ledger was not read." : (untried ? "Not tried yet." : "Published on a channel.")),
            StartupTile(label: "Posts, 7 days", value: count(m.posts7d),
                        detail: m.posts7d == nil ? "The growth ledger was not read." : "Published in the last 7 days."),
            StartupTile(label: "Ads and outreach", value: count(m.adsOutreach),
                        detail: m.adsOutreach == nil ? "The growth ledger was not read." : "Ads and outreach you logged."),
        ])
    }

    private static func sales(_ s: StartupSales) -> StartupGroup {
        let missing = "The growth ledger was not read."
        let last: String
        if s.icpMeetings == nil {
            last = Format.dash
        } else if s.last.isEmpty {
            last = "None yet"
        } else if let day = MoneyLogic.day(s.last) {
            last = MoneyLogic.shortDay(day)
        } else {
            last = s.last
        }
        return StartupGroup(id: "sales", title: "Sales", tiles: [
            StartupTile(label: "ICP conversations", value: count(s.icpMeetings),
                        detail: s.icpMeetings == nil ? missing : "With a person who fits."),
            StartupTile(label: "ICP, 30 days", value: count(s.icpMeetings30d),
                        detail: s.icpMeetings30d == nil ? missing : "Conversations in the last 30 days."),
            StartupTile(label: "Last attempt", value: last == Format.dash ? nil : last,
                        detail: s.icpMeetings == nil ? missing : "Any post, ad, outreach or meeting."),
        ], note: claimed(s.claimed))
    }

    /// An attempt an agent logged is a claim. It counts once the owner logs it himself.
    static func claimed(_ n: Int) -> String {
        guard n > 0 else { return "" }
        return n == 1 ? "1 attempt was logged by an agent and is not counted. Log it yourself to count it."
                      : "\(n) attempts were logged by agents and are not counted. Log them yourself to count them."
    }

    private static func usage(_ u: StartupUsage, personal: Bool) -> StartupGroup {
        let external = personal ? "Personal: only your own use counts." : noProbe
        return StartupGroup(id: "usage", title: "Usage", tiles: [
            StartupTile(label: "People outside", value: count(u.external),
                        detail: u.external == nil ? external : (u.externalAssumed ? "Assumed: accounts minus yours." : "Outside accounts.")),
            StartupTile(label: "Weekly users", value: count(u.wau),
                        detail: u.wau == nil ? noProbe : (personal ? "Your own use this week." : "Outside people active this week.")),
            StartupTile(label: "Back at day 7", value: count(u.retained7d),
                        detail: u.retained7d == nil ? (personal ? "Personal: not measured." : noProbe) : "Outside people who came back."),
            StartupTile(label: "New, 7 days", value: count(u.new7d),
                        detail: u.new7d == nil ? noProbe : "New accounts this week."),
        ])
    }

    private static func money(_ m: StartupMoney) -> StartupGroup {
        let cost = StartupTile(label: "AI cost, 30 days", value: MoneyLogic.usd(m.aiCost30dUSD),
                               detail: m.aiCost30dUSD == nil ? "No session spend was read." : "List price of the AI sessions.")
        // Charging off: payers, MRR and revenue have nothing to say, so one tile says it once.
        guard m.enabled else {
            return StartupGroup(id: "money", title: "Monetization", tiles: [
                StartupTile(label: "Charging", value: "Off", detail: "It does not take payment yet."),
                cost,
            ])
        }
        return StartupGroup(id: "money", title: "Monetization", tiles: [
            StartupTile(label: "Charging", value: "On", detail: "The product takes payment."),
            StartupTile(label: "Payers", value: count(m.paying), detail: m.paying == nil ? noProbe : "People who pay."),
            StartupTile(label: "MRR", value: MoneyLogic.usd(m.mrrUSD), detail: m.mrrUSD == nil ? noProbe : "Monthly recurring revenue."),
            StartupTile(label: "Revenue, 30 days", value: MoneyLogic.usd(m.revenue30dUSD),
                        detail: m.revenue30dUSD == nil ? noProbe : "Cash received."),
            cost,
        ])
    }

    private static func growth(_ g: StartupGrowth) -> StartupGroup {
        let on = g.on == "revenue" ? "revenue" : "weekly users"
        let rate: String?
        let detail: String
        if let pct = g.weeklyPct {
            rate = (pct >= 0 ? "+" : "") + pct.formatted(.number.precision(.fractionLength(0...1)).locale(Locale(identifier: "en_US"))) + "%"
            detail = "A week, on \(on), over \(g.weeks) weeks."
        } else {
            rate = nil
            detail = "Needs 4 weeks of snapshots, has \(g.weeks)."
        }
        return StartupGroup(id: "growth", title: "Growth", tiles: [
            StartupTile(label: "Weekly growth", value: rate, detail: detail),
        ])
    }

    // MARK: The count on the page

    /// "2 of 15 boxes checked." A count, never a percent.
    static func ycCount(_ yc: StartupYCSummary) -> String {
        "\(yc.checked) of \(yc.total) boxes checked."
    }
}

// MARK: Commands

/// The command lines the startup page runs. Each one is an argv for the `teyla` command: no shell, no quoting.
enum StartupCommands {
    /// The longest answer the CLI takes (`MAX_ANSWER` in `startup_yc.py`).
    static let maxAnswer = 2000

    /// `teyla product set <id> type=<type>`.
    static func typeArguments(id: String, type: StartupType) -> [String] {
        ["product", "set", id, "type=\(type.rawValue)"]
    }

    /// `teyla startup --json`, read for its `focus` id.
    static let focusArguments = ["startup", "--json"]

    /// `teyla startup yc <id> --json`.
    static func sheetArguments(id: String) -> [String] { ["startup", "yc", id, "--json"] }

    /// `teyla startup yc -- answer <id> <box> <text>`. The `--` comes first so an answer that starts with a dash is
    /// text, not an option.
    static func answerArguments(id: String, box: String, text: String) -> [String] {
        ["startup", "yc", "--", "answer", id, box, text]
    }

    /// A box id is lower-case words joined by underscores. Anything else never reaches the command line.
    static func isBoxID(_ box: String) -> Bool {
        !box.isEmpty && box.allSatisfy { ($0 >= "a" && $0 <= "z") || $0 == "_" }
    }

    /// The `focus` of `teyla startup --json`: the product the startup page leads with. nil when there is none or the
    /// output is not what was expected.
    static func focus(from data: Data) -> String? {
        guard let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        guard let id = object["focus"] as? String, ProductCommands.isProductID(id) else { return nil }
        return id
    }
}

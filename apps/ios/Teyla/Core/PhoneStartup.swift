import Foundation

// The startup block of a portfolio product (docs/STARTUP.md). The Mac computes it; the phone decodes and words it.
// An older Mac sends no block, and a product the Mac could not compute sends null: both read as nil here.
// This file is iPhone-only, so the Mac app's `Models.swift` stays untouched. No UI types, so the tests can reach it.
// The block carries fixed labels and numbers only. YC answers never reach the phone (the relay is signed, not encrypted).

struct PhoneStartup: Equatable, Sendable {
    struct Next: Equatable, Sendable {
        var rung: String
        var text: String
    }

    struct Rung: Equatable, Sendable, Identifiable {
        var id: String
        var title: String
        /// `met`, `missing`, `unknown`, `stale`, `not_applicable`; anything else reads as unknown.
        var status: String
        var detail: String
    }

    struct Marketing: Equatable, Sendable {
        var posts: Int?
        var posts7d: Int?
        var adsOutreach: Int?
    }

    struct Sales: Equatable, Sendable {
        var icpMeetings: Int?
        var icpMeetings30d: Int?
        var last: String
        /// Rows an agent logged: the Mac counts them for nothing.
        var claimed: Int
    }

    struct Usage: Equatable, Sendable {
        var external: Int?
        var externalAssumed: Bool
        var wau: Int?
        var retained7d: Int?
        var new7d: Int?
    }

    struct Money: Equatable, Sendable {
        var enabled: Bool?
        var paying: Int?
        var mrrUSD: Double?
        var revenue30dUSD: Double?
        var aiCost30dUSD: Double?
    }

    struct Growth: Equatable, Sendable {
        var weeklyPct: Double?
        var weeks: Int
        /// `wau` or `revenue`: what the rate is measured on.
        var on: String
    }

    struct YC: Equatable, Sendable {
        var eligible: Bool
        var checked: Int
        var total: Int
        var nextBox: String?
    }

    var type: String
    var typeSet: Bool
    var stage: String
    var stageTitle: String
    var parked: Bool
    var asOf: String
    var stale: Bool
    var next: Next?
    var rungs: [Rung]
    var marketing: Marketing
    var sales: Sales
    var usage: Usage
    var money: Money
    var growth: Growth
    var yc: YC?
}

extension PhoneStartup: Decodable {
    private enum Keys: String, CodingKey {
        case type, stage, parked, stale, next, rungs, metrics, yc
        case typeSet = "type_set"
        case stageTitle = "stage_title"
        case asOf = "as_of"
    }

    private enum MetricKeys: String, CodingKey { case marketing, sales, usage, money, growth }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        type = c.lenient(.type, "")
        // A block that does not say the type was not chosen is not claimed to be unchosen.
        typeSet = c.lenient(.typeSet, true)
        stage = c.lenient(.stage, "")
        stageTitle = c.lenient(.stageTitle, "")
        parked = c.lenient(.parked, false)
        asOf = c.lenient(.asOf, "")
        stale = c.lenient(.stale, false)
        next = c.optional(.next)
        rungs = (c.lenient(.rungs, [LossyBox<Rung>]()).compactMap(\.value))
        let m = (try? c.nestedContainer(keyedBy: MetricKeys.self, forKey: .metrics))
        marketing = m?.optional(.marketing) ?? Marketing(posts: nil, posts7d: nil, adsOutreach: nil)
        sales = m?.optional(.sales) ?? Sales(icpMeetings: nil, icpMeetings30d: nil, last: "", claimed: 0)
        usage = m?.optional(.usage) ?? Usage(external: nil, externalAssumed: false, wau: nil, retained7d: nil, new7d: nil)
        money = m?.optional(.money) ?? Money(enabled: nil, paying: nil, mrrUSD: nil, revenue30dUSD: nil, aiCost30dUSD: nil)
        growth = m?.optional(.growth) ?? Growth(weeklyPct: nil, weeks: 0, on: "")
        yc = c.optional(.yc)
    }
}

extension PhoneStartup.Next: Decodable {
    private enum Keys: String, CodingKey { case rung, text }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        rung = c.lenient(.rung, "")
        text = c.lenient(.text, "")
    }
}

extension PhoneStartup.Rung: Decodable {
    private enum Keys: String, CodingKey { case id, title, status, detail }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        id = try c.decode(String.self, forKey: .id)
        title = c.lenient(.title, "")
        status = c.lenient(.status, "unknown")
        detail = c.lenient(.detail, "")
    }
}

extension PhoneStartup.Marketing: Decodable {
    private enum Keys: String, CodingKey {
        case posts
        case posts7d = "posts_7d"
        case adsOutreach = "ads_outreach"
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        posts = c.optional(.posts)
        posts7d = c.optional(.posts7d)
        adsOutreach = c.optional(.adsOutreach)
    }
}

extension PhoneStartup.Sales: Decodable {
    private enum Keys: String, CodingKey {
        case last, claimed
        case icpMeetings = "icp_meetings"
        case icpMeetings30d = "icp_meetings_30d"
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        icpMeetings = c.optional(.icpMeetings)
        icpMeetings30d = c.optional(.icpMeetings30d)
        last = c.lenient(.last, "")
        claimed = c.lenient(.claimed, 0)
    }
}

extension PhoneStartup.Usage: Decodable {
    private enum Keys: String, CodingKey {
        case external, wau
        case externalAssumed = "external_assumed"
        case retained7d = "retained_7d"
        case new7d = "new_7d"
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        external = c.optional(.external)
        externalAssumed = c.lenient(.externalAssumed, false)
        wau = c.optional(.wau)
        retained7d = c.optional(.retained7d)
        new7d = c.optional(.new7d)
    }
}

extension PhoneStartup.Money: Decodable {
    private enum Keys: String, CodingKey {
        case enabled, paying
        case mrrUSD = "mrr_usd"
        case revenue30dUSD = "revenue_30d_usd"
        case aiCost30dUSD = "ai_cost_30d_usd"
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        enabled = c.optional(.enabled)
        paying = c.optional(.paying)
        mrrUSD = c.optional(.mrrUSD)
        revenue30dUSD = c.optional(.revenue30dUSD)
        aiCost30dUSD = c.optional(.aiCost30dUSD)
    }
}

extension PhoneStartup.Growth: Decodable {
    private enum Keys: String, CodingKey {
        case weeks, on
        case weeklyPct = "weekly_pct"
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        weeklyPct = c.optional(.weeklyPct)
        weeks = c.lenient(.weeks, 0)
        on = c.lenient(.on, "")
    }
}

extension PhoneStartup.YC: Decodable {
    private enum Keys: String, CodingKey {
        case eligible, checked, total
        case nextBox = "next_box"
    }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        eligible = c.lenient(.eligible, false)
        checked = c.lenient(.checked, 0)
        total = c.lenient(.total, 0)
        nextBox = c.optional(.nextBox)
    }
}

/// The startup blocks of one snapshot, by product id. Read from the same bytes as the snapshot, beside the shared models.
enum PhoneStartupIndex {
    private struct Root: Decodable {
        struct Portfolio: Decodable {
            var products: [LossyBox<Item>]?
        }
        struct Item: Decodable {
            var id: String
            var startup: PhoneStartup?

            private enum Keys: String, CodingKey { case id, startup }
            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: Keys.self)
                id = try c.decode(String.self, forKey: .id)
                startup = c.optional(.startup)
            }
        }
        var portfolio: Portfolio?
    }

    /// A product with no block, or with null, is not in the result. Bytes that do not decode give an empty result.
    static func decode(_ data: Data) -> [String: PhoneStartup] {
        guard let root = try? JSONDecoder().decode(Root.self, from: data),
              let items = root.portfolio?.products else { return [:] }
        var found: [String: PhoneStartup] = [:]
        for case let item? in items.map(\.value) {
            if let block = item.startup { found[item.id] = block }
        }
        return found
    }
}

/// What a rung or a metric says. Every figure has a word beside it, and a null is a dash with its reason.
enum StartupFormat {
    /// Where a figure is when no source reports it.
    static let noSource = "No source reports it yet."
    static let notTriedYet = "Not tried yet."
    static let assumedNote = "Assumed: your own account is taken out."

    // MARK: Header

    static func typeWord(_ type: String) -> String {
        switch type {
        case "venture": return "Venture"
        case "indie": return "Indie"
        case "open-source": return "Open source"
        case "personal": return "Personal"
        default: return type.isEmpty ? "Type unknown" : type.prefix(1).uppercased() + type.dropFirst()
        }
    }

    /// "Built \u{00B7} Venture", "Built \u{00B7} Type not chosen", with "Parked" at the end when it is.
    static func headline(_ s: PhoneStartup) -> String {
        var parts = [s.stageTitle.isEmpty ? "Stage not known" : s.stageTitle]
        parts.append(s.typeSet ? typeWord(s.type) : "Type not chosen")
        if s.parked { parts.append("Parked") }
        return parts.joined(separator: " \u{00B7} ")
    }

    /// Text only: the phone cannot run the command that sets the type.
    static let typeNotChosen = "Until you choose a type on your Mac, Teyla uses the venture ladder."

    /// The one sentence that leads the page. nil when the Mac sent none and the ladder still has a rung to reach.
    static func nextSentence(_ s: PhoneStartup) -> String? {
        if let text = s.next?.text, !text.isEmpty { return text }
        if s.next == nil, !s.rungs.isEmpty, s.rungs.allSatisfy({ $0.status == "met" || $0.status == "not_applicable" }) {
            return "Every rung of this ladder is met."
        }
        return nil
    }

    /// "As of 3 h ago", or, for a stale block, why it earns nothing.
    static func asOfLine(_ s: PhoneStartup, now: Date) -> String {
        let when = PhoneFormat.secondsSince(s.asOf, now: now).map { "As of \(PhoneFormat.ago($0))" } ?? "As-of time not known"
        return s.stale ? "Stale: usage is older than 7 days. \(when)." : when
    }

    // MARK: Rungs

    static func statusWord(_ status: String) -> String {
        switch status {
        case "met": return "Met"
        case "missing": return "Not yet"
        case "stale": return "Stale"
        case "not_applicable": return "Not for this type"
        default: return "Unknown"
        }
    }

    static func statusSymbol(_ status: String) -> String {
        switch status {
        case "met": return "checkmark.circle.fill"
        case "missing": return "circle"
        case "stale": return "clock.badge.exclamationmark"
        case "not_applicable": return "minus.circle"
        default: return "questionmark.circle"
        }
    }

    /// The status word of the rung, and "next" after it for the one the Mac named.
    static func rungWord(_ rung: PhoneStartup.Rung, next: PhoneStartup.Next?) -> String {
        let word = statusWord(rung.status)
        guard let next, next.rung == rung.id, rung.status != "met" else { return word }
        return "\(word) \u{00B7} next"
    }

    // MARK: Metrics

    static func count(_ value: Int?) -> String? { value.map(String.init) }

    static func usd(_ value: Double?) -> String? { value.map { Format.spent($0) } }

    /// "+6.2%" or "-1.5%". A rate, not a score: the sign is always shown.
    static func rate(_ value: Double?) -> String? {
        value.map { String(format: "%+.1f%%", $0) }
    }

    private static func weeksWord(_ n: Int) -> String { n == 1 ? "1 week" : "\(n) weeks" }

    /// The five groups, in the contract's order. A null figure is a dash (`value` nil) and its note says why.
    static func groups(_ s: PhoneStartup) -> [(title: String, rows: [ConsoleRow])] {
        let sells = s.type != "personal"
        let m = s.marketing, a = s.sales, u = s.usage, c = s.money, g = s.growth
        let neverTried = sells && m.posts == 0 && (m.adsOutreach ?? 0) == 0 && (a.icpMeetings ?? 0) == 0

        func row(_ title: String, _ value: String?, _ note: String = "", missing: String = noSource) -> ConsoleRow {
            ConsoleRow(title: title, value: value, note: value == nil ? missing : note)
        }
        let assumed = u.externalAssumed ? assumedNote : ""

        let marketing = [
            row("Posts in total", count(m.posts), neverTried ? notTriedYet : ""),
            row("Posts, last 7 days", count(m.posts7d)),
            row("Ads and outreach", count(m.adsOutreach)),
        ]
        let claimed = a.claimed > 0 ? "\(a.claimed) logged by agents, not counted." : ""
        let sales = [
            row("ICP conversations", count(a.icpMeetings), claimed),
            row("ICP conversations, last 30 days", count(a.icpMeetings30d)),
            row("Last attempt", a.last.isEmpty ? nil : a.last, missing: sells ? "No attempt yet." : "Not used for this type."),
        ]
        let usage = [
            row("External people", count(u.external), assumed),
            row("Weekly users", count(u.wau), assumed),
            row("Back at day 7", count(u.retained7d), assumed),
            row("New in 7 days", count(u.new7d)),
        ]
        let off = c.enabled == false
        let moneyMissing = off ? "Monetization is off, so nothing is reported." : noSource
        let money = [
            row("Monetization", c.enabled.map { $0 ? "On" : "Off" }),
            row("Payers", count(c.paying), missing: moneyMissing),
            row("MRR", usd(c.mrrUSD), missing: moneyMissing),
            row("Revenue, last 30 days", usd(c.revenue30dUSD), missing: moneyMissing),
            row("AI cost, last 30 days", usd(c.aiCost30dUSD)),
        ]
        let basis = g.on == "revenue" ? "revenue" : g.on == "wau" ? "weekly users" : ""
        let growthNote = basis.isEmpty ? "Over \(weeksWord(g.weeks))." : "Over \(weeksWord(g.weeks)), on \(basis)."
        let growth = [
            row("Weekly growth", rate(g.weeklyPct), growthNote,
                missing: g.weeks >= 4 ? noSource : "Needs 4 weeks of snapshots. \(weeksWord(g.weeks)) so far."),
        ]
        return [("Marketing", marketing), ("Sales", sales), ("Usage", usage), ("Monetization", money), ("Growth", growth)]
    }

    // MARK: YC

    /// The questions of the YC sheet, by box id (docs/STARTUP.md). The block carries only the id. The answers stay on the Mac.
    static let boxQuestions: [String: String] = [
        "building": "What are you building?",
        "customer": "Pick one customer",
        "does": "What does it do for them?",
        "using": "Are they using it?",
        "pay": "What do they pay?",
        "why_you": "Why you?",
        "custom": "Is it custom software per customer?",
        "goal": "What is the Demo Day goal?",
        "who": "Who does what?",
        "talked": "How many customers have you talked to?",
        "sell": "How do you sell it?",
        "demo": "Show us the demo",
        "first_live": "When did the first customer go live?",
        "need": "What do they need most?",
        "commit": "Can you commit to the batch?",
    ]

    /// "2 of 15 boxes", never a percent.
    static func ycCount(_ yc: PhoneStartup.YC) -> String {
        "\(yc.checked) of \(yc.total) boxes"
    }

    /// "2 of 15 boxes", or "All 15 boxes are checked." when none is left.
    static func ycHeadline(_ yc: PhoneStartup.YC) -> String {
        yc.total > 0 && yc.checked >= yc.total ? "All \(yc.total) boxes are checked." : ycCount(yc)
    }

    /// The next box's question; nil when every box is checked or the id is not in the table.
    static func ycNextQuestion(_ yc: PhoneStartup.YC) -> String? {
        guard yc.total == 0 || yc.checked < yc.total, let id = yc.nextBox else { return nil }
        return boxQuestions[id]
    }

    static let ycOnMac = "The sheet and its answers are on your Mac."

    // MARK: Products list

    /// "Built", or "Built \u{00B7} Not tried to sell yet": the earned stage beside the selling line. nil with neither.
    static func rowLine(_ startup: PhoneStartup?, selling: String?) -> String? {
        let stage = startup.map(\.stageTitle).flatMap { $0.isEmpty ? nil : $0 }
        let parts = [stage, selling].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " \u{00B7} ")
    }
}

import Foundation

// What the Home and Decisions screens decide, kept free of UI so it can be tested: who a question belongs to,
// how decisions are grouped, which products sit in which Home section and what each card says, and what the star
// does. Foundation only: the iPhone app compiles this file too.

// MARK: Decisions

enum TriageBucket: Equatable, Sendable {
    case owner, agent, close
}

/// The three kinds of decision on the Decisions page when triage is present.
enum DecisionGroup: Int, CaseIterable, Identifiable, Sendable {
    case pay, decide, doIt

    var id: Int { rawValue }

    var title: String {
        switch self {
        case .pay: return "Pay"
        case .decide: return "Decide"
        case .doIt: return "Do"
        }
    }
}

extension Ask {
    /// A question without triage belongs to the owner, and so does one with a bucket this app does not know:
    /// nothing is hidden by a value it cannot read.
    var bucket: TriageBucket {
        switch triage?.bucketRaw {
        case "agent": return .agent
        case "close": return .close
        default: return .owner
        }
    }

    var isOwnerAsk: Bool { bucket == .owner }

    /// `pay` and `do` keep their own group; everything else, including no action, is a decision.
    var decisionGroup: DecisionGroup {
        switch triage?.actionRaw {
        case "pay": return .pay
        case "do": return .doIt
        default: return .decide
        }
    }

    /// Teyla's proposed answer, or nil when it gives none.
    var proposedAnswer: String? {
        let text = triage?.proposed.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return text.isEmpty ? nil : text
    }

    /// One click sends the proposed answer. Never for a payment: silence or a stray click must not approve a charge,
    /// so a `pay` question shows the proposal and still waits for the owner's own answer.
    var canUseProposedAnswer: Bool { proposedAnswer != nil && decisionGroup != .pay }
}

enum Decisions {
    /// How many decisions Home shows before "See all".
    static let homeLimit = 5

    struct Split: Equatable {
        /// Waiting on the person, in rank order.
        var owner: [Ask]
        /// Agents handle these with the proposed default.
        var agent: [Ask]
        /// Teyla suggests closing these. They stay open until the owner accepts them, so they are always on the page.
        var close: [Ask]
    }

    static func split(_ asks: [Ask]) -> Split {
        Split(owner: asks.filter { $0.bucket == .owner },
              agent: asks.filter { $0.bucket == .agent },
              close: asks.filter { $0.bucket == .close })
    }

    /// "Teyla suggests closing 3"; nil when none.
    static func closeLine(count: Int) -> String? { count > 0 ? "Teyla suggests closing \(count)" : nil }

    /// True when the CLI triaged at least one question: the Decisions page then groups them.
    static func hasTriage(_ asks: [Ask]) -> Bool { asks.contains { $0.triage != nil } }

    struct Group: Equatable, Identifiable {
        var kind: DecisionGroup
        var asks: [Ask]
        var id: Int { kind.rawValue }

        /// "Pay · 2".
        var heading: String { "\(kind.title) · \(asks.count)" }
    }

    /// Pay, Decide, Do, each in rank order; an empty group is left out.
    static func grouped(_ owner: [Ask]) -> [Group] {
        DecisionGroup.allCases.compactMap { kind in
            let asks = owner.filter { $0.decisionGroup == kind }
            return asks.isEmpty ? nil : Group(kind: kind, asks: asks)
        }
    }

    /// The decisions on Home: the first five, in rank order.
    static func homeList(_ fresh: [Ask]) -> [Ask] { Array(fresh.prefix(homeLimit)) }

    /// "See all 17" when more decisions wait than Home shows; nil otherwise.
    static func seeAll(total: Int, shown: Int) -> String? { total > shown ? "See all \(total)" : nil }

    /// "Agents can settle 20"; nil when none. Nothing runs by itself: each one waits for a click, so it never says "handling".
    static func agentLine(count: Int) -> String? { count > 0 ? "Agents can settle \(count)" : nil }

    static func countLabel(_ count: Int) -> String { "\(count) \(count == 1 ? "decision" : "decisions")" }

    /// The line under the Decisions heading.
    static func summary(count: Int) -> String {
        switch count {
        case 0: return "Nothing waits on you."
        case 1: return "1 decision waits on you."
        default: return "\(count) decisions wait on you, best first."
        }
    }
}

// MARK: What Teyla closed

enum AutoClosedText {
    /// "Teyla closed 3 questions".
    static func heading(count: Int) -> String { "Teyla closed \(count) \(count == 1 ? "question" : "questions")" }
}

extension AutoClosed {
    /// What is left after the owner undid some in this window: the items not undone, and the count less those.
    func remaining(undone: Set<String>) -> (count: Int, items: [AutoClosedItem]) {
        let gone = items.filter { undone.contains($0.id) }.count
        return (max(0, count - gone), items.filter { !undone.contains($0.id) })
    }
}

// MARK: The header line

enum HomeText {
    /// "2 decisions waiting · 3 sessions running · $2,127 API-equivalent this week". The spend is what the work would
    /// cost at API list prices, not a bill, so the caption says "API-equivalent".
    static func caption(decisions: Int, running: Int, spend: (usd: Double, window: String)?) -> String {
        var parts = [
            decisions == 0 ? "No decisions waiting" : "\(Decisions.countLabel(decisions)) waiting",
            "\(running) \(running == 1 ? "session" : "sessions") running",
        ]
        if let spend { parts.append("\(dollars(spend.usd)) API-equivalent \(spend.window)") }
        return parts.joined(separator: " · ")
    }

    /// The last 7 days across the portfolio when the CLI has it, else today's spend; nil when neither is known.
    static func spend(portfolio: Portfolio?, todayUSD: Double?) -> (usd: Double, window: String)? {
        let week = portfolio?.products.reduce(0) { $0 + $1.activity.spend7dUSD } ?? 0
        if week > 0 { return (week, "this week") }
        if let todayUSD { return (todayUSD, "today") }
        return nil
    }

    /// Whole dollars from $100, cents below that.
    static func dollars(_ usd: Double) -> String {
        usd >= 100
            ? usd.formatted(.currency(code: "USD").locale(Locale(identifier: "en_US")).precision(.fractionLength(0)))
            : Format.spent(usd)
    }

    /// What Home says when the snapshot has no portfolio at all (a teyla command before 0.35).
    static let noPortfolio = "Update the teyla command to see your products (needs 0.35)."
}

// MARK: The pulse strip

/// What a figure means, and so what colour it takes. Green is for money saved and nothing else.
enum StatTone: Equatable, Sendable {
    case neutral, needsYou, danger, saving
}

/// One tile of the strip at the top of Home. No value means a dash, and `detail` says why.
struct PulseTile: Equatable, Identifiable, Sendable {
    enum Kind: String, Sendable { case decisions, running, posts, cash, machine }

    var kind: Kind
    var label: String
    var value: String?
    var detail: String
    var tone = StatTone.neutral

    var id: String { kind.rawValue }
}

enum HomePulse {
    /// Why a console figure is a dash when there is no console at all.
    static let notRead = "Not read yet"

    static func tiles(decisions: [Ask], running: Int, spend: (usd: Double, window: String)?, console: Console?) -> [PulseTile] {
        [decisionsTile(decisions), runningTile(running), postsTile(console?.growth), cashTile(console?.money, spend: spend),
         machineTile(console?.operations)]
    }

    static func decisionsTile(_ asks: [Ask]) -> PulseTile {
        let pay = asks.filter { $0.decisionGroup == .pay }.count
        let detail = asks.isEmpty ? "Nothing waits on you" : pay > 0 ? "\(pay) to pay" : "Only you can answer"
        return PulseTile(kind: .decisions, label: "Decisions", value: "\(asks.count)", detail: detail,
                         tone: asks.isEmpty ? .neutral : .needsYou)
    }

    static func runningTile(_ count: Int) -> PulseTile {
        PulseTile(kind: .running, label: "Running", value: "\(count)", detail: count == 1 ? "agent session" : "agent sessions")
    }

    static func postsTile(_ section: ConsoleSection?) -> PulseTile {
        let headline = section?.headline
        return PulseTile(kind: .posts, label: "Posts today", value: headline.flatMap(text),
                         detail: reason(section) ?? headline?.detail ?? "")
    }

    /// The owner's listed subscriptions; the small line is the week at API list prices, labelled as such.
    static func cashTile(_ section: ConsoleSection?, spend: (usd: Double, window: String)?) -> PulseTile {
        let usd = section?.monthlyUSD ?? section?.headline?.number
        let week = (section?.listUSD7d).map { (usd: $0, window: "this week") } ?? spend
        let detail = week.map { "\(HomeText.dollars($0.usd)) list price \($0.window)" }
        return PulseTile(kind: .cash, label: "Cash per month", value: usd.map(HomeText.dollars),
                         detail: detail ?? reason(section) ?? section?.headline?.detail ?? "")
    }

    static func machineTile(_ section: ConsoleSection?) -> PulseTile {
        let verdict = section?.machine?.verdict?.trimmingCharacters(in: .whitespacesAndNewlines).uppercased() ?? ""
        let disk = section?.machine?.diskFreeGB
        var parts: [String] = []
        if !verdict.isEmpty { parts.append("Machine \(verdict.lowercased())") }
        if let failures = section?.headline?.number, failures > 0 {
            parts.append("\(Int(failures)) \(failures == 1 ? "failure" : "failures")")
        }
        // The number is the disk, so only a critical machine colours it; "busy" is said in the small line.
        return PulseTile(kind: .machine, label: "Disk free", value: disk.map { "\(Int($0.rounded())) GB" },
                         detail: reason(section) ?? parts.joined(separator: ", "),
                         tone: disk != nil && verdict == "CRITICAL" ? .danger : .neutral)
    }

    /// "4/6" stays as sent, a number loses its ".0"; nil is a dash.
    private static func text(_ headline: ConsoleHeadline) -> String? {
        if let text = headline.text, !text.isEmpty { return text }
        return headline.number.map { $0 == $0.rounded() ? "\(Int($0))" : "\($0)" }
    }

    /// Why a section has no figure: no section at all, or the source failed.
    private static func reason(_ section: ConsoleSection?) -> String? {
        guard let section else { return notRead }
        return section.error.map { "Could not read: \($0)" }
    }
}

// MARK: The Next line

/// The one line under the strip: the top decision, and a click away from it.
struct HomeNextLine: Equatable, Sendable {
    var text: String
    /// The question it opens; nil when nothing waits.
    var askID: String?
}

/// How the top of Home reads. `pulse` is the default; `sentence` keeps a strict one-line headline.
enum HomeHeaderStyle: String, CaseIterable, Sendable {
    case pulse, sentence

    static let storageKey = "teyla.home.header"

    static func from(stored: String) -> HomeHeaderStyle { HomeHeaderStyle(rawValue: stored) ?? .pulse }
}

enum HomeNext {
    static let maxWords = 10
    static let sentenceMaxWords = 12
    static let nothing = "Nothing waits on you."

    static func wordCount(_ text: String) -> Int { text.split(whereSeparator: \.isWhitespace).count }

    /// The first `limit` words, with an ellipsis when some were cut.
    static func clip(_ text: String, words limit: Int) -> String {
        let words = text.split(whereSeparator: \.isWhitespace)
        guard words.count > limit else { return words.joined(separator: " ") }
        return words.prefix(limit).joined(separator: " ") + "…"
    }

    /// A model's line only when it obeys the limit and speaks of the question the tap opens; otherwise the rule line:
    /// product, then the question's first words. `rankFirst` is the highest-ranked question, which the brief leads
    /// with. `top` differs from it when that question sits in the Older fold, and the brief would then name another.
    static func line(brief: Brief?, top: Ask?, rankFirst: Ask?) -> HomeNextLine {
        guard let top else { return HomeNextLine(text: nothing, askID: nil) }
        if top.id == rankFirst?.id, let model = modelLine(brief, limit: maxWords) {
            return HomeNextLine(text: model, askID: top.id)
        }
        let product = Format.product(top.product)
        let room = max(1, maxWords - wordCount(product))
        return HomeNextLine(text: "\(product): \(clip(top.question, words: room))", askID: top.id)
    }

    /// The comparison variant: one sentence of at most 12 words.
    static func sentence(brief: Brief?, decisions: Int, top: Ask?, rankFirst: Ask?) -> String {
        if top?.id == rankFirst?.id, let model = modelLine(brief, limit: sentenceMaxWords) { return model }
        guard let top else { return nothing }
        return "\(Decisions.summaryShort(count: decisions)) Top: \(clip(Format.product(top.product), words: 3))."
    }

    private static func modelLine(_ brief: Brief?, limit: Int) -> String? {
        guard let brief, brief.source == "model" else { return nil }
        let line = brief.line.trimmingCharacters(in: .whitespacesAndNewlines)
        return !line.isEmpty && !line.contains("\n") && wordCount(line) <= limit ? line : nil
    }
}

extension Decisions {
    /// "3 decisions wait."
    static func summaryShort(count: Int) -> String {
        count == 1 ? "1 decision waits." : "\(count) decisions wait."
    }
}

// MARK: A product's one line

enum ProductLine {
    static let maxWords = 12
    static let maxCharacters = 80

    /// The line under a product's name: why it needs attention, else its next step when that reads as a short English
    /// line, else how many items are open, else its milestone. A raw next step is a session's words, in any language
    /// and any length, so it never shows as it came.
    static func text(_ product: PortfolioProduct) -> String? {
        if let reason = product.reasons.first, !reason.isEmpty { return reason }
        if let next = shortEnglish(product.next) { return "Next: \(next)" }
        let open = product.waiting + product.prs.waiting
        if open > 0 { return "\(open) open \(open == 1 ? "item" : "items")" }
        return product.milestone.isEmpty ? nil : product.milestone
    }

    /// The text when it is one line of at most 12 words and 80 characters in Latin script; nil otherwise.
    static func shortEnglish(_ raw: String) -> String? {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !text.contains("\n"), text.count <= maxCharacters,
              HomeNext.wordCount(text) <= maxWords else { return nil }
        let letters = text.unicodeScalars.filter { CharacterSet.letters.contains($0) }
        guard letters.allSatisfy({ $0.value < 0x250 }) else { return nil }
        return text
    }
}

// MARK: Core product cards

/// What can be installed and what cannot yet, from a product's platform rows. Only `current` and `live` are
/// installable. `in_review`, `behind` and `blocked` are named by their state; a row with no build is left out.
struct InstallSummary: Equatable, Sendable {
    /// "iOS 1.4.0 (52)", "Web".
    var installable: [String]
    /// "Android 1.3.0 (14) behind", "Mac 1.1 in review".
    var pending: [String]

    init(installable: [String] = [], pending: [String] = []) {
        self.installable = installable
        self.pending = pending
    }

    init(_ rows: [PlatformStatus]) {
        var installable: [String] = []
        var pending: [String] = []
        for row in rows {
            let name = [PortfolioText.platformName(row.platform), PortfolioText.build(row)]
                .filter { !$0.isEmpty }.joined(separator: " ")
            switch row.state {
            case .current, .live:
                if !installable.contains(name) { installable.append(name) }
            case .inReview, .behind, .blocked:
                let text = "\(name) \(PortfolioText.stateWord(row.state))"
                if !pending.contains(text) { pending.append(text) }
            case .none, .unknown:
                break
            }
        }
        self.init(installable: installable, pending: pending)
    }

    var isEmpty: Bool { installable.isEmpty && pending.isEmpty }
}

/// One card on Home. No health, no percentage, no session title.
struct CoreCard: Equatable, Identifiable, Sendable {
    var id: String
    var title: String
    var starred: Bool
    /// `progress.line`, at most 12 words.
    var line: String
    var install: InstallSummary
    /// "4 PRs merged in 7 days".
    var shipped: String
    /// The newest merged PR title, when the cache has one.
    var latest: String?
    /// "4 active this week, 12 total"; nil when the usage is unknown.
    var users: String?
    var milestone: String?
    /// The one thing in the way; shown in the needs-you amber.
    var blocker: String?
    /// "Quiet for 21 days", only from 14 days.
    var quiet: String?
}

enum CoreCards {
    /// Quiet shows from this many days.
    static let quietFromDays = 14

    /// The cards for `portfolio.core`, in that order. An id the portfolio does not list is skipped.
    static func cards(_ portfolio: Portfolio) -> [CoreCard] {
        portfolio.core.compactMap { id in portfolio.product(id).map(card) }
    }

    static func card(_ product: PortfolioProduct) -> CoreCard {
        let progress = product.progress
        let milestone = progress?.milestone ?? product.milestone
        let line = nonEmpty(progress?.line) ?? nonEmpty(milestone) ?? nonEmpty(product.next) ?? ""
        let prs = progress?.shippedPRs ?? product.prs.merged7d
        let blocker = nonEmpty(progress?.blocker)
        let quiet = progress?.quietDays.flatMap { $0 >= quietFromDays ? quietText(days: $0) : nil }
        return CoreCard(
            id: product.id,
            title: product.title.isEmpty ? Format.product(product.id) : product.title,
            starred: product.focus,
            line: line,
            install: InstallSummary(progress?.canInstall ?? product.platforms),
            shipped: shippedText(prs: prs),
            latest: progress?.shippedTop.first.flatMap { nonEmpty($0) },
            users: nonEmpty(progress?.users?.label),
            // The line is often the milestone itself; say it once.
            milestone: nonEmpty(milestone).flatMap { $0 == line ? nil : $0 },
            blocker: blocker,
            quiet: quiet.flatMap { $0 == line ? nil : $0 })
    }

    static func shippedText(prs: Int) -> String {
        prs == 0 ? "Nothing merged in 7 days" : "\(prs) \(prs == 1 ? "PR" : "PRs") merged in 7 days"
    }

    static func quietText(days: Int) -> String { "Quiet for \(days) days" }

    private static func nonEmpty(_ text: String?) -> String? {
        guard let text = text?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else { return nil }
        return text
    }

    /// Cards per row: as many as fit, at most 3, at least 1.
    static func columns(width: CGFloat, minCard: CGFloat, spacing: CGFloat) -> Int {
        guard width > 0 else { return 1 }
        return min(3, max(1, Int((width + spacing) / (minCard + spacing))))
    }
}

// MARK: The star

/// A star pins a product first within its Home section: `teyla product core <ids...>` makes exactly those products
/// starred, and the CLI ranks starred products first. The `core` list stays in the state for older clients.
enum CoreEdit {
    /// Home shows at most this many products (the CLI's own limit).
    static let limit = 6

    /// The ids to hand to `teyla product core` after the star on `id` was clicked: the starred products, plus `id` or
    /// without it. The `core` list plays no part, so a product picked by rule is never pinned by accident.
    static func toggled(_ id: String, in portfolio: Portfolio) -> [String] {
        let starred = portfolio.products.filter(\.focus).map(\.id)
        return starred.contains(id) ? starred.filter { $0 != id } : starred + [id]
    }

    /// Taking a star off is always allowed; adding one is not once the list is full.
    static func canToggle(_ id: String, in portfolio: Portfolio) -> Bool {
        let starred = portfolio.products.contains { $0.id == id && $0.focus }
        return starred || toggled(id, in: portfolio).count <= limit
    }

    static let fullHelp = "Six products can be pinned. Unpin one first."

    /// The tooltip and the VoiceOver label of a star. A star pins a product to the front of its Home section.
    static func help(starred: Bool, source: String, canToggle: Bool) -> String {
        if !canToggle { return fullHelp }
        return starred ? "Unpin from the front of its section" : "Pin to the front of its section"
    }

    /// The portfolio as it will read once the command has run, so the star answers at once.
    static func applying(_ ids: [String], to portfolio: Portfolio) -> Portfolio {
        var next = portfolio
        for index in next.products.indices { next.products[index].focus = ids.contains(next.products[index].id) }
        guard !ids.isEmpty else {
            next.coreSource = "rule"
            return next
        }
        let kept = portfolio.core.filter { ids.contains($0) }
        next.core = Array((kept + ids.filter { !kept.contains($0) }).prefix(limit))
        next.coreSource = "star"
        return next
    }
}

/// The command lines the Home screen adds. Ids come from the snapshot; one that starts with "-" or holds a space
/// never reaches the command line.
enum HomeCommands {
    static func isSafeID(_ id: String) -> Bool { ProductCommands.isProductID(id) }

    /// `teyla product core <ids...>`, or `--clear` for an empty list.
    static func coreArguments(ids: [String]) -> [String]? {
        guard ids.allSatisfy(isSafeID) else { return nil }
        return ids.isEmpty ? ["product", "core", "--clear"] : ["product", "core"] + ids
    }

    /// `teyla asks undo <id>`: reopens a question Teyla closed.
    static func undoArguments(id: String) -> [String]? {
        isSafeID(id) ? ["asks", "undo", id] : nil
    }

    /// `teyla asks accept-close <ids...>`: exactly the questions on screen, never "whatever is in the bucket now".
    static func acceptCloseArguments(ids: [String]) -> [String]? {
        guard !ids.isEmpty, ids.allSatisfy(isSafeID) else { return nil }
        return ["asks", "accept-close"] + ids
    }
}

// MARK: Home sections (the Scoreboard)

/// The period the whole Home page shows. It changes numbers only: never who is in a section or in what order.
enum HomePeriod: String, CaseIterable, Identifiable, Sendable {
    case week = "7d", month = "30d", year = "365d"

    var id: String { rawValue }

    /// The label on the switch.
    var label: String {
        switch self {
        case .week: return "Week"
        case .month: return "Month"
        case .year: return "Year"
        }
    }

    /// "this week", for a sentence about the period.
    var phrase: String {
        switch self {
        case .week: return "this week"
        case .month: return "this month"
        case .year: return "this year"
        }
    }

    /// What the stored choice becomes when it holds a value this build does not know.
    static func from(stored: String) -> HomePeriod { HomePeriod(rawValue: stored) ?? .week }
}

/// The three sections, in the order the page shows them.
enum HomeSectionKind: String, CaseIterable, Identifiable, Sendable {
    case users, building, quiet

    var id: String { rawValue }

    /// The visible title. These three words are the contract with the owner's design.
    var title: String {
        switch self {
        case .users: return "People use these"
        case .building: return "Being built"
        case .quiet: return "Quiet"
        }
    }

    /// The line under the title: the rule that put a product here.
    var note: String {
        switch self {
        case .users: return "Active or new users in the last 7 days, most active first"
        case .building: return "5 or more commits this week, no users counted yet. Most commits first"
        case .quiet: return "Under 5 commits this week and no new users"
        }
    }
}

struct HomeSection: Equatable, Identifiable, Sendable {
    var kind: HomeSectionKind
    var products: [PortfolioProduct]

    var id: String { kind.rawValue }
}

/// What Home draws: the three sections when the CLI sends `portfolio.home`, else the old core list as plain rows.
enum HomeLayout: Equatable, Sendable {
    case sections([HomeSection])
    case legacy([CoreCard])

    var isEmpty: Bool {
        switch self {
        case .sections(let sections): return sections.allSatisfy { $0.products.isEmpty }
        case .legacy(let cards): return cards.isEmpty
        }
    }
}

enum HomeSections {
    /// The sections in the order the CLI ranked them. This never sorts: the CLI knows the star, the signals and the ties.
    /// An id without a product row is skipped, and an id the CLI lists twice stays in the first section that has it.
    /// A section the CLI did not send is empty. Empty sections stay in the list; the view hides them.
    static func layout(_ portfolio: Portfolio) -> HomeLayout {
        guard let home = portfolio.home else { return .legacy(CoreCards.cards(portfolio)) }
        var seen = Set<String>()
        let sections = HomeSectionKind.allCases.map { kind -> HomeSection in
            let ids = home.sections.first { $0.id == kind.rawValue }?.ids ?? []
            let products = ids.compactMap { id -> PortfolioProduct? in
                guard !seen.contains(id), let product = portfolio.product(id) else { return nil }
                seen.insert(id)
                return product
            }
            return HomeSection(kind: kind, products: products)
        }
        return .sections(sections)
    }

    /// "3 with users · 15 being built · 20 quiet", for VoiceOver on the page; nothing for a legacy layout.
    static func counts(_ sections: [HomeSection]) -> String {
        sections.filter { !$0.products.isEmpty }
            .map { "\($0.products.count) \($0.kind.rawValue)" }
            .joined(separator: ", ")
    }
}

// MARK: Numbers and words

enum HomeNumbers {
    /// What a number that is not counted looks like. Never "0".
    static let dash = "\u{2014}"

    private static let grouped: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.locale = Locale(identifier: "en_US")
        formatter.numberStyle = .decimal
        formatter.usesGroupingSeparator = true
        formatter.maximumFractionDigits = 0
        return formatter
    }()

    /// "—" for nil, "2,944" below 10,000, then "12.3k" and "1.2M". A big number must fit a card.
    static func count(_ value: Int?) -> String {
        guard let value else { return dash }
        let magnitude = abs(value)
        if magnitude < 10_000 { return grouped.string(from: NSNumber(value: value)) ?? String(value) }
        if magnitude < 1_000_000 { return compact(Double(value) / 1_000, suffix: "k") }
        return compact(Double(value) / 1_000_000, suffix: "M")
    }

    /// One decimal below 100, none above; a trailing ".0" is dropped. 10,400 reads "10.4k", 120,000 reads "120k".
    private static func compact(_ scaled: Double, suffix: String) -> String {
        if abs(scaled) >= 100 { return "\(Int(scaled.rounded()))\(suffix)" }
        let tenths = (scaled * 10).rounded() / 10
        return tenths == tenths.rounded() ? "\(Int(tenths))\(suffix)" : "\(tenths)\(suffix)"
    }

    /// "$957", "$2,127", "—". Whole dollars: a card is not a bill.
    static func dollars(_ value: Double?) -> String {
        guard let value else { return dash }
        let whole = grouped.string(from: NSNumber(value: abs(value).rounded())) ?? String(Int(abs(value).rounded()))
        return (value < 0 ? "-$" : "$") + whole
    }

    /// "135 commits"; "1 commit"; "— commits" when not counted.
    static func commits(_ value: Int?) -> String {
        "\(count(value)) \(value == 1 ? "commit" : "commits")"
    }
}

/// The little bar chart of commits per week.
enum Sparkline {
    /// Bar heights from 0 to 1, oldest first. Empty weeks give no chart at all (never a flat line). Twelve real zeros
    /// give twelve bars at the baseline (height 0). A negative count is read as 0.
    static func heights(weeks: [Int]) -> [Double] {
        guard !weeks.isEmpty else { return [] }
        let top = weeks.map { max(0, $0) }.max() ?? 0
        guard top > 0 else { return weeks.map { _ in 0 } }
        return weeks.map { Double(max(0, $0)) / Double(top) }
    }

    /// "Commits per week, last 12 weeks: 135 this week", or nil when there is no chart.
    static func label(weeks: [Int]) -> String? {
        guard let last = weeks.last else { return nil }
        return "Commits per week, last \(weeks.count) weeks: \(HomeNumbers.count(last)) this week"
    }
}

/// The letter on a product with no icon.
enum Monogram {
    /// The first letter or digit of the name, upper-cased; "?" for an empty name.
    static func letter(for name: String) -> String {
        guard let first = name.trimmingCharacters(in: .whitespacesAndNewlines).first(where: { $0.isLetter || $0.isNumber })
        else { return "?" }
        return String(first).uppercased()
    }
}

/// What one product's card says for a period. Plain strings: the view only places them.
struct HomeFacts: Equatable, Sendable {
    var id: String
    var name: String
    /// "Live", "Beta"; "" when the registry has no stage.
    var stage: String
    var summary: String
    var monogram: String
    var active: String
    var new: String
    var total: String
    var commits: String
    var commitsCount: String
    /// "$957 agent spend this week", or "Agent spend: not counted yet".
    var spend: String
    var weeks: [Int]
    var sparkHeights: [Double]
    var sparkLabel: String?
    var money: String
    var moneyEnabled: Bool
    /// The whole card as one VoiceOver sentence.
    var spoken: String
}

enum HomeFactsBuilder {
    static let noSummary = "No description yet."

    static func name(_ product: PortfolioProduct) -> String {
        let title = product.title.trimmingCharacters(in: .whitespacesAndNewlines)
        return title.isEmpty ? Format.product(product.id) : title
    }

    /// The description: the summary, else the progress line, else nothing to read (the view says it has none).
    static func summary(_ product: PortfolioProduct) -> String {
        let text = product.summary.trimmingCharacters(in: .whitespacesAndNewlines)
        if !text.isEmpty { return text }
        return product.progress?.line.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    /// "MRR $1,200 · 14 paying" when monetization is on, "Off" when it is not.
    static func money(_ money: MoneyMetrics) -> String {
        guard money.enabled else { return "Off" }
        return "\(HomeNumbers.dollars(money.mrrUSD)) MRR \u{00B7} \(HomeNumbers.count(money.paying)) paying"
    }

    static func spend(_ metrics: ProductMetrics, period: HomePeriod) -> String {
        guard let usd = metrics.spendUSD[period] else { return "Agent spend: not counted yet" }
        return "\(HomeNumbers.dollars(usd)) agent spend \(period.phrase)"
    }

    static func facts(_ product: PortfolioProduct, period: HomePeriod) -> HomeFacts {
        let metrics = product.metrics
        let name = name(product)
        let stage = product.stage.trimmingCharacters(in: .whitespacesAndNewlines).capitalized
        let weeks = metrics.commits.weeks
        let commits = metrics.commits.counts[period]
        let active = HomeNumbers.count(metrics.users.active[period])
        let new = HomeNumbers.count(metrics.users.new[period])
        let total = HomeNumbers.count(metrics.users.total)
        let spendLine = spend(metrics, period: period)
        let moneyLine = money(metrics.money)
        let sparkLabel = Sparkline.label(weeks: weeks)
        var spoken = [name + (stage.isEmpty ? "" : ", " + stage),
                      "Active users \(active), new \(new), \(total) in total",
                      "\(HomeNumbers.commits(commits)) \(period.phrase)", spendLine,
                      "Monetization \(moneyLine)"]
        if let sparkLabel { spoken.append(sparkLabel) }
        return HomeFacts(id: product.id, name: name, stage: stage, summary: summary(product),
                         monogram: Monogram.letter(for: name), active: active, new: new, total: total,
                         commits: HomeNumbers.commits(commits), commitsCount: HomeNumbers.count(commits),
                         spend: spendLine, weeks: weeks, sparkHeights: Sparkline.heights(weeks: weeks),
                         sparkLabel: sparkLabel, money: moneyLine, moneyEnabled: metrics.money.enabled,
                         spoken: spoken.joined(separator: ". ") + ".")
    }

    /// The Quiet row: always the 7-day number, whatever period the page shows. "4 commits", "— commits" when not counted.
    static func quietCount(_ product: PortfolioProduct) -> String {
        HomeNumbers.commits(product.metrics.commits.counts.d7)
    }

    /// "4 commits this week". A phone row splits it over two lines: `quietCount` and `HomePeriod.week.phrase`.
    static func quietCommits(_ product: PortfolioProduct) -> String {
        "\(quietCount(product)) \(HomePeriod.week.phrase)"
    }
}

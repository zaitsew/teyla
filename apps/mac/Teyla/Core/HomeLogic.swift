import Foundation

// What the Home and Decisions screens decide, kept free of UI so it can be tested: who a question belongs to,
// how decisions are grouped, what a core product card says, and what the star does to the core list.

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

    /// "Agents are handling 20"; nil when none.
    static func agentLine(count: Int) -> String? { count > 0 ? "Agents are handling \(count)" : nil }

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

    /// The quiet line under "Core products" while the list is picked by rule. Without a star (the store build) it only says how.
    static func coreNote(source: String, canStar: Bool) -> String? {
        guard source == "rule" else { return nil }
        return canStar ? "Picked by usage and spend. A star sets the list by hand." : "Picked by usage and spend."
    }

    /// The empty state of the core grid: what goes here and the one action that fills it.
    static func coreEmpty(hasPortfolio: Bool, canStar: Bool) -> String {
        if !hasPortfolio { return "Update the teyla command to see your products (needs 0.35)." }
        return canStar ? "No core products yet. Star a product in All products to put it here." : "No core products yet."
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

/// A star sets the core list: `teyla product core <ids...>` makes exactly those products starred.
enum CoreEdit {
    /// Home shows at most this many products (the CLI's own limit).
    static let limit = 6

    /// The ids to hand to `teyla product core` after the star on `id` was clicked.
    /// - With stars: the starred products, plus `id` or without it.
    /// - Picked by rule: nothing is starred yet, so the list on screen is pinned, with `id` added if it was not on it.
    static func toggled(_ id: String, in portfolio: Portfolio) -> [String] {
        let starred = portfolio.products.filter(\.focus).map(\.id)
        if !starred.isEmpty {
            return starred.contains(id) ? starred.filter { $0 != id } : starred + [id]
        }
        return portfolio.core.contains(id) ? portfolio.core : portfolio.core + [id]
    }

    /// Taking a star off is always allowed; adding one is not once the list is full.
    static func canToggle(_ id: String, in portfolio: Portfolio) -> Bool {
        let starred = portfolio.products.contains { $0.id == id && $0.focus }
        return starred || toggled(id, in: portfolio).count <= limit
    }

    static let fullHelp = "Home shows 6 products. Take one out first."

    /// The tooltip and the VoiceOver label of a star.
    static func help(starred: Bool, source: String, canToggle: Bool) -> String {
        if !canToggle { return fullHelp }
        if starred { return "Take out of the core list" }
        return source == "rule" ? "Star to set the core list by hand" : "Add to the core list"
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

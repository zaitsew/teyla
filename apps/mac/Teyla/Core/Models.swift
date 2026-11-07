import Foundation

// The snapshot contract (versions 1 to 3) is documented in docs/APP.md. Decoding is lenient on
// purpose: unknown fields are ignored, and a missing or null field falls back to an empty
// value, so a newer CLI never blanks the window.

extension KeyedDecodingContainer {
    /// The value for `key`, or `fallback` when the key is missing, null or of another type.
    func lenient<T: Decodable>(_ key: Key, _ fallback: T) -> T {
        ((try? decodeIfPresent(T.self, forKey: key)) ?? nil) ?? fallback
    }

    func optional<T: Decodable>(_ key: Key) -> T? {
        (try? decodeIfPresent(T.self, forKey: key)) ?? nil
    }
}

/// Decodes one array element, turning a failure into nil instead of failing the whole array.
struct LossyBox<T: Decodable>: Decodable {
    let value: T?
    init(from decoder: Decoder) throws {
        value = try? T(from: decoder)
    }
}

struct Snapshot: Decodable, Equatable, Sendable {
    var version: Int
    var generated: String
    var brief: Brief?
    var totals: Totals
    var asks: [Ask]
    var products: [Product]
    var running: [RunningSession]
    /// Version 2: things only the owner can do that are not questions.
    var tasks: [OwnerTask]
    /// Version 2: sessions that ended a turn in the last 24 hours, newest first.
    var done: [DoneItem]
    /// Version 2: the iPhone relay; nil from a version 1 CLI.
    var relay: Relay?
    /// Version 3: where every product stands, per platform; nil from an older CLI.
    var portfolio: Portfolio?
    /// Questions Teyla closed itself in the last 24 hours; nil from a CLI that does not close any.
    var autoClosed: AutoClosed?
    /// The compact console: one headline per admin section; nil until the first `teyla console` refresh.
    var console: Console?
    /// The activity graph in counts only (the last 17 weeks); nil from a Mac that does not send it.
    var activity: ActivityGlimpse?
    /// The GTM Today card in counts only (docs/GTM.md); nil from a Mac that does not send it, and the phone then hides the card.
    var gtm: GtmGlimpse?

    enum CodingKeys: String, CodingKey {
        case version, generated, brief, totals, asks, products, running, tasks, done, relay, portfolio, console, activity, gtm
        case autoClosed = "auto_closed"
    }

    init(version: Int = 1, generated: String = "", brief: Brief? = nil, totals: Totals = Totals(),
         asks: [Ask] = [], products: [Product] = [], running: [RunningSession] = [],
         tasks: [OwnerTask] = [], done: [DoneItem] = [], relay: Relay? = nil, portfolio: Portfolio? = nil,
         autoClosed: AutoClosed? = nil, console: Console? = nil, activity: ActivityGlimpse? = nil, gtm: GtmGlimpse? = nil) {
        self.version = version
        self.generated = generated
        self.brief = brief
        self.totals = totals
        self.asks = asks
        self.products = products
        self.running = running
        self.tasks = tasks
        self.done = done
        self.relay = relay
        self.portfolio = portfolio
        self.autoClosed = autoClosed
        self.console = console
        self.activity = activity
        self.gtm = gtm
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        console = c.optional(.console)
        activity = c.optional(.activity)
        gtm = c.optional(.gtm)
        version = c.lenient(.version, 1)
        generated = c.lenient(.generated, "")
        brief = c.optional(.brief)
        totals = c.lenient(.totals, Totals())
        // A malformed entry is dropped, not fatal.
        let asks: [LossyBox<Ask>] = c.lenient(.asks, [])
        let products: [LossyBox<Product>] = c.lenient(.products, [])
        let running: [LossyBox<RunningSession>] = c.lenient(.running, [])
        let tasks: [LossyBox<OwnerTask>] = c.lenient(.tasks, [])
        let done: [LossyBox<DoneItem>] = c.lenient(.done, [])
        self.asks = asks.compactMap(\.value)
        self.products = products.compactMap(\.value)
        self.running = running.compactMap(\.value)
        self.tasks = tasks.compactMap(\.value)
        self.done = done.compactMap(\.value)
        relay = c.optional(.relay)
        portfolio = c.optional(.portfolio)
        autoClosed = c.optional(.autoClosed)
    }

    var generatedDate: Date? { ISODate.parse(generated) }
}

struct Brief: Decodable, Equatable, Sendable {
    var line: String
    var source: String

    enum CodingKeys: String, CodingKey { case line, source }

    init(line: String, source: String = "rules") {
        self.line = line
        self.source = source
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        line = c.lenient(.line, "")
        source = c.lenient(.source, "")
    }
}

struct Totals: Decodable, Equatable, Sendable {
    var questions: Int
    var running: Int
    var spentTodayUSD: Double?
    var tasks: Int
    var done: Int

    enum CodingKeys: String, CodingKey {
        case questions, running, tasks, done
        case spentTodayUSD = "spent_today_usd"
    }

    init(questions: Int = 0, running: Int = 0, spentTodayUSD: Double? = nil, tasks: Int = 0, done: Int = 0) {
        self.questions = questions
        self.running = running
        self.spentTodayUSD = spentTodayUSD
        self.tasks = tasks
        self.done = done
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        questions = c.lenient(.questions, 0)
        running = c.lenient(.running, 0)
        spentTodayUSD = c.optional(.spentTodayUSD)
        tasks = c.lenient(.tasks, 0)
        done = c.lenient(.done, 0)
    }
}

struct Ask: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var kind: String
    var product: String
    var title: String
    var question: String
    var context: String
    var options: [String]
    var archived: Bool
    var link: String
    var pr: String
    var harness: String
    var status: String
    var ts: String
    var ageSeconds: Double
    var unblocks: String
    var rank: Int
    /// What `teyla answer` will try first: `codex`, `claude` or `open`.
    var delivery: String
    /// Who should handle it and what Teyla proposes; nil from a CLI that does not triage.
    var triage: Triage?

    enum CodingKeys: String, CodingKey {
        case id, kind, product, title, question, context, options, archived, link, pr
        case harness, status, ts, unblocks, rank, delivery, triage
        case ageSeconds = "age_s"
    }

    init(id: String, product: String = "", question: String = "", options: [String] = [],
         unblocks: String = "", rank: Int = 0, link: String = "", ageSeconds: Double = 0, triage: Triage? = nil) {
        self.id = id
        self.kind = "question"
        self.product = product
        self.title = ""
        self.question = question
        self.context = ""
        self.options = options
        self.archived = false
        self.link = link
        self.pr = ""
        self.harness = ""
        self.status = "open"
        self.ts = ""
        self.ageSeconds = ageSeconds
        self.unblocks = unblocks
        self.rank = rank
        self.delivery = ""
        self.triage = triage
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // An ask without an id cannot be answered, so that one is required.
        id = try c.decode(String.self, forKey: .id)
        kind = c.lenient(.kind, "question")
        product = c.lenient(.product, "")
        title = c.lenient(.title, "")
        question = c.lenient(.question, "")
        context = c.lenient(.context, "")
        options = c.lenient(.options, [])
        archived = c.lenient(.archived, false)
        link = c.lenient(.link, "")
        pr = c.lenient(.pr, "")
        harness = c.lenient(.harness, "")
        status = c.lenient(.status, "open")
        ts = c.lenient(.ts, "")
        ageSeconds = c.lenient(.ageSeconds, 0)
        unblocks = c.lenient(.unblocks, "")
        rank = c.lenient(.rank, 0)
        delivery = c.lenient(.delivery, "")
        triage = c.optional(.triage)
    }
}

/// Who a question belongs to, from `asks[].triage` (a later CLI): `owner` (the person), `agent` (a session can
/// settle it with the proposed default) or `close` (Teyla closes it). An unknown bucket reads as `owner`, so a
/// question is never hidden by a value this app does not know.
struct Triage: Decodable, Equatable, Sendable {
    var bucketRaw: String
    /// `pay`, `decide` or `do`; "" when the CLI gives none.
    var actionRaw: String
    /// The answer Teyla proposes ("default" in the JSON).
    var proposed: String
    var why: String
    /// `rule` or `model`.
    var source: String

    enum CodingKeys: String, CodingKey {
        case why, source, action, bucket
        case proposed = "default"
    }

    init(bucket: String = "owner", action: String = "", proposed: String = "", why: String = "", source: String = "rule") {
        self.bucketRaw = bucket
        self.actionRaw = action
        self.proposed = proposed
        self.why = why
        self.source = source
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bucketRaw = c.lenient(.bucket, "owner")
        actionRaw = c.lenient(.action, "")
        proposed = c.lenient(.proposed, "")
        why = c.lenient(.why, "")
        source = c.lenient(.source, "")
    }
}

/// Questions Teyla closed on its own in the last 24 hours (`auto_closed`, a later CLI). Each can be undone.
struct AutoClosed: Decodable, Equatable, Sendable {
    var count: Int
    var items: [AutoClosedItem]

    enum CodingKeys: String, CodingKey { case count, items }

    init(count: Int? = nil, items: [AutoClosedItem] = []) {
        self.items = items
        self.count = count ?? items.count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let items: [LossyBox<AutoClosedItem>] = c.lenient(.items, [])
        self.items = items.compactMap(\.value)
        count = c.lenient(.count, self.items.count)
    }
}

struct AutoClosedItem: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var title: String
    var product: String
    var reason: String

    enum CodingKeys: String, CodingKey { case id, title, product, reason }

    init(id: String, title: String = "", product: String = "", reason: String = "") {
        self.id = id
        self.title = title
        self.product = product
        self.reason = reason
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = c.lenient(.title, "")
        product = c.lenient(.product, "")
        reason = c.lenient(.reason, "")
    }
}

enum ProductState: String, Sendable {
    case waiting, active, shipped, quiet
}

struct Product: Decodable, Equatable, Identifiable, Sendable {
    var name: String
    var waiting: Int
    var stateRaw: String
    var line: String
    var lastActivity: String
    /// Version 2: open GitHub issues, PRs waiting on the owner's merge, the next step, the repo path.
    var issues: Int
    var prsWaiting: Int
    var next: String
    var repo: String
    /// The registry (docs/PRODUCTS.md): the name to show, the stage ("" when unset), the focus star, the primary platform.
    var displayName: String
    var stage: String
    var focus: Bool
    var primary: String
    /// False for a repo that only shows activity and has no registry entry: it gets no product page.
    var registered: Bool

    var id: String { name }
    var title: String { displayName.isEmpty ? Format.product(name) : displayName }
    /// A registered product has a page, and so does `unassigned`, the bucket for sessions nobody filed.
    var hasPage: Bool { registered || name == "unassigned" }
    /// Unknown states are treated as quiet.
    var state: ProductState { ProductState(rawValue: stateRaw) ?? .quiet }

    enum CodingKeys: String, CodingKey {
        case name, waiting, line, issues, next, repo, stage, focus, primary, registered
        case displayName = "display_name"
        case stateRaw = "state"
        case lastActivity = "last_activity"
        case prsWaiting = "prs_waiting"
    }

    init(name: String, waiting: Int = 0, state: String = "quiet", line: String = "", lastActivity: String = "",
         issues: Int = 0, prsWaiting: Int = 0, next: String = "", repo: String = "",
         displayName: String = "", stage: String = "", focus: Bool = false, primary: String = "", registered: Bool = false) {
        self.name = name
        self.displayName = displayName
        self.stage = stage
        self.focus = focus
        self.primary = primary
        self.registered = registered
        self.waiting = waiting
        self.stateRaw = state
        self.line = line
        self.lastActivity = lastActivity
        self.issues = issues
        self.prsWaiting = prsWaiting
        self.next = next
        self.repo = repo
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        waiting = c.lenient(.waiting, 0)
        stateRaw = c.lenient(.stateRaw, "quiet")
        line = c.lenient(.line, "")
        lastActivity = c.lenient(.lastActivity, "")
        issues = c.lenient(.issues, 0)
        prsWaiting = c.lenient(.prsWaiting, 0)
        next = c.lenient(.next, "")
        repo = c.lenient(.repo, "")
        displayName = c.lenient(.displayName, "")
        stage = c.lenient(.stage, "")
        focus = c.lenient(.focus, false)
        primary = c.lenient(.primary, "")
        registered = c.lenient(.registered, false)
    }
}

struct RunningSession: Decodable, Equatable, Identifiable, Sendable {
    var product: String
    var title: String
    var harness: String
    var model: String
    var since: String
    var link: String
    /// Version 2: the reference `teyla say` takes ("" from a version 1 CLI).
    var ref: String
    /// Version 2: `codex-queue` when a correction can be queued into the live session, else `open`.
    var correct: String

    var id: String { link.isEmpty ? "\(product)/\(title)/\(since)" : link }

    enum CodingKeys: String, CodingKey {
        case product, title, harness, model, since, link, correct
        case ref = "id"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        product = c.lenient(.product, "")
        title = c.lenient(.title, "")
        harness = c.lenient(.harness, "")
        model = c.lenient(.model, "")
        since = c.lenient(.since, "")
        link = c.lenient(.link, "")
        ref = c.lenient(.ref, "")
        correct = c.lenient(.correct, "open")
    }
}

/// Version 2: something only the owner can do that is not a question.
struct OwnerTask: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    /// `merge` (a PR waiting on the owner) or `task` (an issue assigned to the owner).
    var kind: String
    var product: String
    var title: String
    var detail: String
    var link: String
    var ageSeconds: Double

    enum CodingKeys: String, CodingKey {
        case id, kind, product, title, detail, link
        case ageSeconds = "age_s"
    }

    init(id: String, kind: String = "task", product: String = "", title: String = "", detail: String = "",
         link: String = "", ageSeconds: Double = 0) {
        self.id = id
        self.kind = kind
        self.product = product
        self.title = title
        self.detail = detail
        self.link = link
        self.ageSeconds = ageSeconds
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = c.lenient(.kind, "task")
        product = c.lenient(.product, "")
        title = c.lenient(.title, "")
        detail = c.lenient(.detail, "")
        link = c.lenient(.link, "")
        ageSeconds = c.lenient(.ageSeconds, 0)
    }
}

/// Version 2: one session that ended a turn, as a card.
struct DoneItem: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var product: String
    var title: String
    /// `done`, `needs_you`, `blocked`, `failed` or `review_ready`.
    var status: String
    var result: [String]
    var needs: String
    var links: [String]
    var ended: String
    var harness: String
    var link: String

    enum CodingKeys: String, CodingKey {
        case id, product, title, status, result, needs, links, ended, harness, link
    }

    init(id: String, product: String = "", title: String = "", status: String = "done", result: [String] = [],
         needs: String = "", links: [String] = [], ended: String = "", harness: String = "", link: String = "") {
        self.id = id
        self.product = product
        self.title = title
        self.status = status
        self.result = result
        self.needs = needs
        self.links = links
        self.ended = ended
        self.harness = harness
        self.link = link
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        product = c.lenient(.product, "")
        title = c.lenient(.title, "")
        status = c.lenient(.status, "done")
        result = c.lenient(.result, [])
        needs = c.lenient(.needs, "")
        links = c.lenient(.links, [])
        ended = c.lenient(.ended, "")
        harness = c.lenient(.harness, "")
        link = c.lenient(.link, "")
    }
}

/// Version 2: the iPhone relay state.
struct Relay: Decodable, Equatable, Sendable {
    var on: Bool
    var paired: Bool
    var folder: String
    var synced: String

    enum CodingKeys: String, CodingKey { case on, paired, folder, synced }

    init(on: Bool = false, paired: Bool = false, folder: String = "", synced: String = "") {
        self.on = on
        self.paired = paired
        self.folder = folder
        self.synced = synced
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        on = c.lenient(.on, false)
        paired = c.lenient(.paired, false)
        folder = c.lenient(.folder, "")
        synced = c.lenient(.synced, "")
    }
}

// MARK: Version 3: the portfolio

/// Where every registered product stands. Worst health first, as the CLI sends it.
struct Portfolio: Decodable, Equatable, Sendable {
    var version: Int
    /// When the network pass last read the stores and GitHub; "" when never.
    var checkedStores: String
    var checkedGitHub: String
    var counts: HealthCounts
    var products: [PortfolioProduct]
    /// Up to 6 product ids the home screen leads with, best first; empty from an older CLI.
    var core: [String]
    /// `star` (the owner starred products) or `rule` (picked by usage and spend); "" from an older CLI.
    var coreSource: String
    /// The three Home sections, already ranked; nil from a CLI that does not send `home`.
    var home: PortfolioHome?

    enum CodingKeys: String, CodingKey {
        case version, checked, counts, products, core, home
        case coreSource = "core_source"
    }
    enum CheckedKeys: String, CodingKey { case stores, github }

    init(version: Int = 1, checkedStores: String = "", checkedGitHub: String = "",
         counts: HealthCounts = HealthCounts(), products: [PortfolioProduct] = [],
         core: [String] = [], coreSource: String = "", home: PortfolioHome? = nil) {
        self.version = version
        self.checkedStores = checkedStores
        self.checkedGitHub = checkedGitHub
        self.counts = counts
        self.products = products
        self.core = core
        self.coreSource = coreSource
        self.home = home
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = c.lenient(.version, 1)
        let checked = try? c.nestedContainer(keyedBy: CheckedKeys.self, forKey: .checked)
        checkedStores = checked?.lenient(.stores, "") ?? ""
        checkedGitHub = checked?.lenient(.github, "") ?? ""
        counts = c.lenient(.counts, HealthCounts())
        let products: [LossyBox<PortfolioProduct>] = c.lenient(.products, [])
        self.products = products.compactMap(\.value)
        core = c.lenient(.core, [])
        coreSource = c.lenient(.coreSource, "")
        home = c.optional(.home)
    }

    func product(_ id: String) -> PortfolioProduct? { products.first { $0.id == id } }
}

/// `portfolio.home`: which product sits in which Home section, already ranked by the CLI. The app never re-ranks.
struct PortfolioHome: Decodable, Equatable, Sendable {
    var sections: [HomeSectionIDs]

    enum CodingKeys: String, CodingKey { case sections }

    init(sections: [HomeSectionIDs] = []) { self.sections = sections }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let rows: [LossyBox<HomeSectionIDs>] = c.lenient(.sections, [])
        sections = rows.compactMap(\.value)
    }
}

struct HomeSectionIDs: Decodable, Equatable, Sendable {
    /// `users`, `building` or `quiet`; another value is ignored by the app.
    var id: String
    var ids: [String]

    enum CodingKeys: String, CodingKey { case id, ids }

    init(id: String, ids: [String] = []) {
        self.id = id
        self.ids = ids
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        ids = c.lenient(.ids, [])
    }
}

// MARK: Per-product metrics

/// One number for each of the three periods Home can show. A period the CLI does not count is nil, never zero.
struct PeriodValues<Value: Decodable & Equatable & Sendable>: Decodable, Equatable, Sendable {
    var d7: Value?
    var d30: Value?
    var d365: Value?

    enum CodingKeys: String, CodingKey {
        case d7 = "7d", d30 = "30d", d365 = "365d"
    }

    init(d7: Value? = nil, d30: Value? = nil, d365: Value? = nil) {
        self.d7 = d7
        self.d30 = d30
        self.d365 = d365
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        d7 = c.optional(.d7)
        d30 = c.optional(.d30)
        d365 = c.optional(.d365)
    }

    /// `period` is chosen by the person; the value of the others is untouched.
    subscript(period: HomePeriod) -> Value? {
        switch period {
        case .week: return d7
        case .month: return d30
        case .year: return d365
        }
    }
}

struct UserMetrics: Decodable, Equatable, Sendable {
    var total: Int?
    var active: PeriodValues<Int>
    var new: PeriodValues<Int>

    enum CodingKeys: String, CodingKey { case total, active, new }

    init(total: Int? = nil, active: PeriodValues<Int> = PeriodValues(), new: PeriodValues<Int> = PeriodValues()) {
        self.total = total
        self.active = active
        self.new = new
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = c.optional(.total)
        active = c.lenient(.active, PeriodValues())
        new = c.lenient(.new, PeriodValues())
    }
}

struct CommitMetrics: Decodable, Equatable, Sendable {
    var counts: PeriodValues<Int>
    /// Commits per week for the last 12 weeks, oldest first; empty when git could not answer. Empty draws no chart.
    var weeks: [Int]

    enum CodingKeys: String, CodingKey { case weeks }

    init(counts: PeriodValues<Int> = PeriodValues(), weeks: [Int] = []) {
        self.counts = counts
        self.weeks = weeks
    }

    init(from decoder: Decoder) throws {
        counts = (try? PeriodValues<Int>(from: decoder)) ?? PeriodValues()
        let c = try decoder.container(keyedBy: CodingKeys.self)
        weeks = c.lenient(.weeks, [])
    }
}

struct MoneyMetrics: Decodable, Equatable, Sendable {
    /// Monetization is switched on for this product. While false, every other value is nil.
    var enabled: Bool
    var mrrUSD: Double?
    var paying: Int?
    var revenueUSD: PeriodValues<Double>

    enum CodingKeys: String, CodingKey {
        case enabled, paying
        case mrrUSD = "mrr_usd"
        case revenueUSD = "revenue_usd"
    }

    init(enabled: Bool = false, mrrUSD: Double? = nil, paying: Int? = nil,
         revenueUSD: PeriodValues<Double> = PeriodValues()) {
        self.enabled = enabled
        self.mrrUSD = mrrUSD
        self.paying = paying
        self.revenueUSD = revenueUSD
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled = c.lenient(.enabled, false)
        mrrUSD = c.optional(.mrrUSD)
        paying = c.optional(.paying)
        revenueUSD = c.lenient(.revenueUSD, PeriodValues())
    }
}

/// What Home shows per product. A CLI before this field sends none; every value is then nil ("—").
struct ProductMetrics: Decodable, Equatable, Sendable {
    var users: UserMetrics
    var commits: CommitMetrics
    var spendUSD: PeriodValues<Double>
    var money: MoneyMetrics

    enum CodingKeys: String, CodingKey {
        case users, commits, money
        case spendUSD = "spend_usd"
    }

    init(users: UserMetrics = UserMetrics(), commits: CommitMetrics = CommitMetrics(),
         spendUSD: PeriodValues<Double> = PeriodValues(), money: MoneyMetrics = MoneyMetrics()) {
        self.users = users
        self.commits = commits
        self.spendUSD = spendUSD
        self.money = money
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        users = c.lenient(.users, UserMetrics())
        commits = c.lenient(.commits, CommitMetrics())
        spendUSD = c.lenient(.spendUSD, PeriodValues())
        money = c.lenient(.money, MoneyMetrics())
    }
}

struct HealthCounts: Decodable, Equatable, Sendable {
    var onTrack: Int
    var atRisk: Int
    var offTrack: Int
    var parked: Int

    enum CodingKeys: String, CodingKey {
        case parked
        case onTrack = "on_track"
        case atRisk = "at_risk"
        case offTrack = "off_track"
    }

    init(onTrack: Int = 0, atRisk: Int = 0, offTrack: Int = 0, parked: Int = 0) {
        self.onTrack = onTrack
        self.atRisk = atRisk
        self.offTrack = offTrack
        self.parked = parked
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        onTrack = c.lenient(.onTrack, 0)
        atRisk = c.lenient(.atRisk, 0)
        offTrack = c.lenient(.offTrack, 0)
        parked = c.lenient(.parked, 0)
    }
}

/// Unknown values decode as `.onTrack` for health and `.unknown` for a platform state.
enum Health: String, Sendable {
    case onTrack = "on_track", atRisk = "at_risk", offTrack = "off_track", parked
}

enum PlatformState: String, Sendable {
    case live, inReview = "in_review", current, behind, blocked, none, unknown
}

struct PlatformStatus: Decodable, Equatable, Identifiable, Sendable {
    var platform: String
    var role: String
    var channel: String
    var version: String
    var build: String
    var stateRaw: String
    var detail: String
    var asOf: String
    var link: String

    var id: String { "\(platform)/\(channel)" }
    var state: PlatformState { PlatformState(rawValue: stateRaw) ?? .unknown }
    var isPrimary: Bool { role == "primary" }
    /// An AI directory listing (Claude, ChatGPT, Gemini), not a device platform.
    var isDirectory: Bool { role == "directory" }

    enum CodingKeys: String, CodingKey {
        case platform, role, channel, version, build, detail, link
        case stateRaw = "state"
        case asOf = "as_of"
    }

    init(platform: String, role: String = "secondary", channel: String = "", version: String = "", build: String = "",
         state: String = "unknown", detail: String = "", asOf: String = "", link: String = "") {
        self.platform = platform
        self.role = role
        self.channel = channel
        self.version = version
        self.build = build
        self.stateRaw = state
        self.detail = detail
        self.asOf = asOf
        self.link = link
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        platform = try c.decode(String.self, forKey: .platform)
        role = c.lenient(.role, "secondary")
        channel = c.lenient(.channel, "")
        version = c.lenient(.version, "")
        build = c.lenient(.build, "")
        stateRaw = c.lenient(.stateRaw, "unknown")
        detail = c.lenient(.detail, "")
        asOf = c.lenient(.asOf, "")
        link = c.lenient(.link, "")
    }
}

struct PRCounts: Decodable, Equatable, Sendable {
    var open: Int
    var waiting: Int
    var merged7d: Int
    var unreviewed7d: Int
    /// PRs merged in 7 days that still have an open P1 finding.
    var openP1: Int

    enum CodingKeys: String, CodingKey {
        case open, waiting
        case merged7d = "merged_7d"
        case unreviewed7d = "unreviewed_7d"
        case openP1 = "open_p1"
    }

    init(open: Int = 0, waiting: Int = 0, merged7d: Int = 0, unreviewed7d: Int = 0, openP1: Int = 0) {
        self.open = open
        self.waiting = waiting
        self.merged7d = merged7d
        self.unreviewed7d = unreviewed7d
        self.openP1 = openP1
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        open = c.lenient(.open, 0)
        waiting = c.lenient(.waiting, 0)
        merged7d = c.lenient(.merged7d, 0)
        unreviewed7d = c.lenient(.unreviewed7d, 0)
        openP1 = c.lenient(.openP1, 0)
    }
}

struct Activity: Decodable, Equatable, Sendable {
    var last: String
    var sessions7d: Int
    var spend7dUSD: Double

    enum CodingKeys: String, CodingKey {
        case last
        case sessions7d = "sessions_7d"
        case spend7dUSD = "spend_7d_usd"
    }

    init(last: String = "", sessions7d: Int = 0, spend7dUSD: Double = 0) {
        self.last = last
        self.sessions7d = sessions7d
        self.spend7dUSD = spend7dUSD
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        last = c.lenient(.last, "")
        sessions7d = c.lenient(.sessions7d, 0)
        spend7dUSD = c.lenient(.spend7dUSD, 0)
    }
}

struct PortfolioProduct: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var title: String
    var stage: String
    var focus: Bool
    var primary: String
    var users: String
    var target: String
    var healthRaw: String
    var reasons: [String]
    var platforms: [PlatformStatus]
    var prs: PRCounts
    var activity: Activity
    var waiting: Int
    var oldestWaitDays: Double
    var tasks: Int
    var milestone: String
    var next: String
    var repo: String
    /// What health does not count (questions that wait, unreviewed merges); shown nowhere on Home.
    var facts: [String]
    /// Facts about progress; nil from a CLI before 0.35.
    var progress: ProductProgress?
    /// One line about what the product is; "" when the CLI has none.
    var summary: String
    /// Base64 of a small JPEG icon; "" when there is none. Decoded once per product by the Mac UI, never here.
    var iconJPEG: String
    var metrics: ProductMetrics
    /// The earned stage, the ladder and the metrics (docs/STARTUP.md). nil from a CLI before the startup page, and when
    /// the CLI could not compute it. The app shows it and computes nothing.
    var startup: StartupBlock?

    var health: Health { Health(rawValue: healthRaw) ?? .onTrack }

    enum CodingKeys: String, CodingKey {
        case id, title, stage, focus, primary, users, target, reasons, platforms, prs, activity
        case waiting, tasks, milestone, next, repo, facts, progress, summary, metrics, startup
        case healthRaw = "health"
        case iconJPEG = "icon_jpeg"
        case oldestWaitDays = "oldest_wait_days"
    }

    init(id: String, title: String = "", stage: String = "", focus: Bool = false, primary: String = "",
         users: String = "", target: String = "", health: String = "on_track", reasons: [String] = [],
         platforms: [PlatformStatus] = [], prs: PRCounts = PRCounts(), activity: Activity = Activity(),
         waiting: Int = 0, oldestWaitDays: Double = 0, tasks: Int = 0, milestone: String = "", next: String = "",
         repo: String = "", facts: [String] = [], progress: ProductProgress? = nil,
         summary: String = "", iconJPEG: String = "", metrics: ProductMetrics = ProductMetrics(),
         startup: StartupBlock? = nil) {
        self.id = id
        self.title = title
        self.stage = stage
        self.focus = focus
        self.primary = primary
        self.users = users
        self.target = target
        self.healthRaw = health
        self.reasons = reasons
        self.platforms = platforms
        self.prs = prs
        self.activity = activity
        self.waiting = waiting
        self.oldestWaitDays = oldestWaitDays
        self.tasks = tasks
        self.milestone = milestone
        self.next = next
        self.repo = repo
        self.facts = facts
        self.progress = progress
        self.summary = summary
        self.iconJPEG = iconJPEG
        self.metrics = metrics
        self.startup = startup
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = c.lenient(.title, "")
        stage = c.lenient(.stage, "")
        focus = c.lenient(.focus, false)
        primary = c.lenient(.primary, "")
        users = c.lenient(.users, "")
        target = c.lenient(.target, "")
        healthRaw = c.lenient(.healthRaw, "on_track")
        reasons = c.lenient(.reasons, [])
        let platforms: [LossyBox<PlatformStatus>] = c.lenient(.platforms, [])
        self.platforms = platforms.compactMap(\.value)
        prs = c.lenient(.prs, PRCounts())
        activity = c.lenient(.activity, Activity())
        waiting = c.lenient(.waiting, 0)
        oldestWaitDays = c.lenient(.oldestWaitDays, 0)
        tasks = c.lenient(.tasks, 0)
        milestone = c.lenient(.milestone, "")
        next = c.lenient(.next, "")
        repo = c.lenient(.repo, "")
        facts = c.lenient(.facts, [])
        progress = c.optional(.progress)
        summary = c.lenient(.summary, "")
        iconJPEG = c.lenient(.iconJPEG, "")
        metrics = c.lenient(.metrics, ProductMetrics())
        startup = c.optional(.startup)
    }
}

/// Progress as facts, no percentages: what can be installed, what shipped, who uses it, the one thing in the way.
struct ProductProgress: Decodable, Equatable, Sendable {
    /// The platforms with a known build, primary first. Only `current` and `live` rows can be installed;
    /// `in_review`, `behind` and `blocked` rows are listed so the window can say so.
    var canInstall: [PlatformStatus]
    var shippedPRs: Int
    /// Up to 3 titles of the PRs merged in 7 days, newest first.
    var shippedTop: [String]
    /// nil when the usage counters are unknown.
    var users: UsersFact?
    var milestone: String
    var blocker: String
    /// Whole days since the last activity; nil when there is none.
    var quietDays: Int?
    /// At most 12 words.
    var line: String

    enum CodingKeys: String, CodingKey {
        case users, milestone, blocker, line
        case canInstall = "can_install"
        case shipped = "shipped_7d"
        case quietDays = "quiet_days"
    }
    enum ShippedKeys: String, CodingKey { case prs, top }

    init(canInstall: [PlatformStatus] = [], shippedPRs: Int = 0, shippedTop: [String] = [], users: UsersFact? = nil,
         milestone: String = "", blocker: String = "", quietDays: Int? = nil, line: String = "") {
        self.canInstall = canInstall
        self.shippedPRs = shippedPRs
        self.shippedTop = shippedTop
        self.users = users
        self.milestone = milestone
        self.blocker = blocker
        self.quietDays = quietDays
        self.line = line
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let rows: [LossyBox<PlatformStatus>] = c.lenient(.canInstall, [])
        canInstall = rows.compactMap(\.value)
        let shipped = try? c.nestedContainer(keyedBy: ShippedKeys.self, forKey: .shipped)
        shippedPRs = shipped?.lenient(.prs, 0) ?? 0
        shippedTop = shipped?.lenient(.top, []) ?? []
        users = c.optional(.users)
        milestone = c.lenient(.milestone, "")
        blocker = c.lenient(.blocker, "")
        quietDays = c.optional(.quietDays)
        line = c.lenient(.line, "")
    }
}

struct UsersFact: Decodable, Equatable, Sendable {
    var weekly: Int
    var total: Int
    /// A sentence for a person: "4 active this week, 12 total".
    var label: String

    enum CodingKeys: String, CodingKey { case weekly, total, label }

    init(weekly: Int = 0, total: Int = 0, label: String = "") {
        self.weekly = weekly
        self.total = total
        self.label = label
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        weekly = c.lenient(.weekly, 0)
        total = c.lenient(.total, 0)
        label = c.lenient(.label, "")
    }
}

// MARK: The startup block (docs/STARTUP.md)

/// `startup` on a portfolio product: the earned stage, the ladder, the metrics and the YC count. Fixed labels and numbers
/// only: customer text never travels in it, because the relay is signed and not encrypted. An unknown figure is `nil`.
struct StartupBlock: Decodable, Equatable, Sendable {
    /// `venture`, `indie`, `open-source` or `personal`. A product with no chosen type reads as `venture`.
    var type: String
    var typeSet: Bool
    /// `built`, `tried`, ... or `none`; `stageTitle` is the word to show ("Built", "Not built", "Not known").
    var stage: String
    var stageTitle: String
    var parked: Bool
    /// When the usage probe was read; nil when no probe reports.
    var asOf: String?
    var stale: Bool
    /// The first rung that is not met; nil when the whole ladder is met.
    var next: StartupNext?
    var rungs: [StartupRung]
    var metrics: StartupMetrics
    var yc: StartupYCSummary?

    enum CodingKeys: String, CodingKey {
        case type, stage, parked, stale, next, rungs, metrics, yc
        case typeSet = "type_set"
        case stageTitle = "stage_title"
        case asOf = "as_of"
    }

    init(type: String = "venture", typeSet: Bool = true, stage: String = "none", stageTitle: String = "Not built",
         parked: Bool = false, asOf: String? = nil, stale: Bool = false, next: StartupNext? = nil,
         rungs: [StartupRung] = [], metrics: StartupMetrics = StartupMetrics(), yc: StartupYCSummary? = nil) {
        self.type = type
        self.typeSet = typeSet
        self.stage = stage
        self.stageTitle = stageTitle
        self.parked = parked
        self.asOf = asOf
        self.stale = stale
        self.next = next
        self.rungs = rungs
        self.metrics = metrics
        self.yc = yc
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        // A block with no type is not a block: the whole thing reads as absent, never as a guess.
        type = try c.decode(String.self, forKey: .type)
        typeSet = c.lenient(.typeSet, false)
        stage = c.lenient(.stage, "none")
        stageTitle = c.lenient(.stageTitle, "Not known")
        parked = c.lenient(.parked, false)
        asOf = c.optional(.asOf)
        stale = c.lenient(.stale, false)
        next = c.optional(.next)
        let rungs: [LossyBox<StartupRung>] = c.lenient(.rungs, [])
        self.rungs = rungs.compactMap(\.value)
        metrics = c.lenient(.metrics, StartupMetrics())
        yc = c.optional(.yc)
    }
}

struct StartupNext: Decodable, Equatable, Sendable {
    var rung: String
    var text: String
    var command: String

    init(rung: String, text: String = "", command: String = "") {
        self.rung = rung
        self.text = text
        self.command = command
    }

    enum CodingKeys: String, CodingKey { case rung, text, command }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        rung = try c.decode(String.self, forKey: .rung)
        text = c.lenient(.text, "")
        command = c.lenient(.command, "")
    }
}

struct StartupRung: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var title: String
    /// `met`, `missing`, `unknown`, `stale` or `not_applicable`.
    var status: String
    var detail: String

    init(id: String, title: String = "", status: String = "unknown", detail: String = "") {
        self.id = id
        self.title = title.isEmpty ? id.capitalized : title
        self.status = status
        self.detail = detail
    }

    enum CodingKeys: String, CodingKey { case id, title, status, detail }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let id: String = try c.decode(String.self, forKey: .id)
        self.init(id: id, title: c.lenient(.title, ""), status: c.lenient(.status, "unknown"), detail: c.lenient(.detail, ""))
    }
}

/// The five groups of at most 15 figures. A group that is absent reads as all-unknown, never as zeros.
struct StartupMetrics: Decodable, Equatable, Sendable {
    var marketing = StartupMarketing()
    var sales = StartupSales()
    var usage = StartupUsage()
    var money = StartupMoney()
    var growth = StartupGrowth()

    enum CodingKeys: String, CodingKey { case marketing, sales, usage, money, growth }

    init() {}

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        marketing = c.lenient(.marketing, StartupMarketing())
        sales = c.lenient(.sales, StartupSales())
        usage = c.lenient(.usage, StartupUsage())
        money = c.lenient(.money, StartupMoney())
        growth = c.lenient(.growth, StartupGrowth())
    }
}

struct StartupMarketing: Decodable, Equatable, Sendable {
    var posts: Int?
    var posts7d: Int?
    var adsOutreach: Int?

    enum CodingKeys: String, CodingKey {
        case posts
        case posts7d = "posts_7d"
        case adsOutreach = "ads_outreach"
    }

    init(posts: Int? = nil, posts7d: Int? = nil, adsOutreach: Int? = nil) {
        self.posts = posts
        self.posts7d = posts7d
        self.adsOutreach = adsOutreach
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        posts = c.optional(.posts)
        posts7d = c.optional(.posts7d)
        adsOutreach = c.optional(.adsOutreach)
    }
}

struct StartupSales: Decodable, Equatable, Sendable {
    var icpMeetings: Int?
    var icpMeetings30d: Int?
    /// The newest day (YYYY-MM-DD) of any attempt; "" when there is none.
    var last: String
    /// Attempts an agent logged. They count for nothing until the owner logs them himself.
    var claimed: Int

    enum CodingKeys: String, CodingKey {
        case last, claimed
        case icpMeetings = "icp_meetings"
        case icpMeetings30d = "icp_meetings_30d"
    }

    init(icpMeetings: Int? = nil, icpMeetings30d: Int? = nil, last: String = "", claimed: Int = 0) {
        self.icpMeetings = icpMeetings
        self.icpMeetings30d = icpMeetings30d
        self.last = last
        self.claimed = claimed
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        icpMeetings = c.optional(.icpMeetings)
        icpMeetings30d = c.optional(.icpMeetings30d)
        last = c.lenient(.last, "")
        claimed = c.lenient(.claimed, 0)
    }
}

struct StartupUsage: Decodable, Equatable, Sendable {
    /// People other than the owner who have an account.
    var external: Int?
    /// True when `external` is the accounts minus one for the owner, because no probe prints outside counts.
    var externalAssumed: Bool
    var wau: Int?
    var retained7d: Int?
    var new7d: Int?

    enum CodingKeys: String, CodingKey {
        case external, wau
        case externalAssumed = "external_assumed"
        case retained7d = "retained_7d"
        case new7d = "new_7d"
    }

    init(external: Int? = nil, externalAssumed: Bool = false, wau: Int? = nil, retained7d: Int? = nil, new7d: Int? = nil) {
        self.external = external
        self.externalAssumed = externalAssumed
        self.wau = wau
        self.retained7d = retained7d
        self.new7d = new7d
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        external = c.optional(.external)
        externalAssumed = c.lenient(.externalAssumed, false)
        wau = c.optional(.wau)
        retained7d = c.optional(.retained7d)
        new7d = c.optional(.new7d)
    }
}

struct StartupMoney: Decodable, Equatable, Sendable {
    var enabled: Bool
    var paying: Int?
    var mrrUSD: Double?
    var revenue30dUSD: Double?
    /// The list price of the AI sessions in 30 days, not cash.
    var aiCost30dUSD: Double?

    enum CodingKeys: String, CodingKey {
        case enabled, paying
        case mrrUSD = "mrr_usd"
        case revenue30dUSD = "revenue_30d_usd"
        case aiCost30dUSD = "ai_cost_30d_usd"
    }

    init(enabled: Bool = false, paying: Int? = nil, mrrUSD: Double? = nil, revenue30dUSD: Double? = nil, aiCost30dUSD: Double? = nil) {
        self.enabled = enabled
        self.paying = paying
        self.mrrUSD = mrrUSD
        self.revenue30dUSD = revenue30dUSD
        self.aiCost30dUSD = aiCost30dUSD
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        enabled = c.lenient(.enabled, false)
        paying = c.optional(.paying)
        mrrUSD = c.optional(.mrrUSD)
        revenue30dUSD = c.optional(.revenue30dUSD)
        aiCost30dUSD = c.optional(.aiCost30dUSD)
    }
}

struct StartupGrowth: Decodable, Equatable, Sendable {
    /// nil until four weeks of snapshots exist.
    var weeklyPct: Double?
    var weeks: Int
    /// What the rate is measured on: `revenue` or `wau`.
    var on: String

    enum CodingKeys: String, CodingKey {
        case weeks, on
        case weeklyPct = "weekly_pct"
    }

    init(weeklyPct: Double? = nil, weeks: Int = 0, on: String = "wau") {
        self.weeklyPct = weeklyPct
        self.weeks = weeks
        self.on = on
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        weeklyPct = c.optional(.weeklyPct)
        weeks = c.lenient(.weeks, 0)
        on = c.lenient(.on, "wau")
    }
}

/// The count on the product page: counts only, never an answer. `eligible` is false for a product that is not a venture.
struct StartupYCSummary: Decodable, Equatable, Sendable {
    var eligible: Bool
    var checked: Int
    var total: Int
    var nextBox: String?

    enum CodingKeys: String, CodingKey {
        case eligible, checked, total
        case nextBox = "next_box"
    }

    init(eligible: Bool = false, checked: Int = 0, total: Int = 15, nextBox: String? = nil) {
        self.eligible = eligible
        self.checked = checked
        self.total = total
        self.nextBox = nextBox
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        eligible = c.lenient(.eligible, false)
        checked = c.lenient(.checked, 0)
        total = c.lenient(.total, 15)
        nextBox = c.optional(.nextBox)
    }
}

/// `teyla answer`, `teyla say` and `teyla dispatch` print `{ok, via, detail, id}`; `dispatch` adds
/// `worktree` and `link`. `via` is `codex-queue`, `codex-resume`, `codex-exec`, `claude-bg` or `opened`.
struct AnswerResult: Decodable, Equatable, Sendable {
    var ok: Bool
    var via: String
    var detail: String
    var id: String
    var worktree: String
    var link: String

    enum CodingKeys: String, CodingKey { case ok, via, detail, id, worktree, link }

    init(ok: Bool, via: String, detail: String = "", id: String = "", worktree: String = "", link: String = "") {
        self.ok = ok
        self.via = via
        self.detail = detail
        self.id = id
        self.worktree = worktree
        self.link = link
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = c.lenient(.ok, false)
        via = c.lenient(.via, "")
        detail = c.lenient(.detail, "")
        id = c.lenient(.id, "")
        worktree = c.lenient(.worktree, "")
        link = c.lenient(.link, "")
    }
}

enum ISODate {
    static func parse(_ s: String) -> Date? {
        guard !s.isEmpty else { return nil }
        if let d = try? Date(s, strategy: .iso8601) { return d }
        let fractional = Date.ISO8601FormatStyle(includingFractionalSeconds: true)
        return try? Date(s, strategy: fractional)
    }

    static func format(_ date: Date) -> String {
        date.formatted(.iso8601)
    }
}

// MARK: The console

/// `console` in `teyla state` (docs/CONSOLE.md). Every part is optional: a failing source sends `error`, an unknown
/// figure sends null, and the screen shows a dash with the reason.
struct Console: Decodable, Equatable, Sendable {
    var operations: ConsoleSection?
    var money: ConsoleSection?
    var playbook: ConsoleSection?
    var growth: ConsoleSection?
    /// The same four sections, read in full for the iPhone's screens (`ConsoleCompact.swift`).
    var compact: ConsoleCompact

    enum CodingKeys: String, CodingKey { case operations, money, playbook, growth }

    init(operations: ConsoleSection? = nil, money: ConsoleSection? = nil, playbook: ConsoleSection? = nil,
         growth: ConsoleSection? = nil, compact: ConsoleCompact = ConsoleCompact()) {
        self.operations = operations
        self.money = money
        self.playbook = playbook
        self.growth = growth
        self.compact = compact
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        operations = c.optional(.operations)
        money = c.optional(.money)
        playbook = c.optional(.playbook)
        growth = c.optional(.growth)
        compact = (try? ConsoleCompact(from: decoder)) ?? ConsoleCompact()
    }
}

/// One section's compact part: what Home reads. The section screens read the full `teyla console` report.
struct ConsoleSection: Decodable, Equatable, Sendable {
    var headline: ConsoleHeadline?
    var error: String?
    /// Operations: the machine's verdict and free disk.
    var machine: ConsoleMachine?
    /// Money: the listed subscriptions per month, and the last 7 days at API list prices.
    var monthlyUSD: Double?
    var listUSD7d: Double?

    enum CodingKeys: String, CodingKey {
        case headline, error, machine
        case monthlyUSD = "monthly_usd"
        case listUSD7d = "list_usd_7d"
    }

    init(headline: ConsoleHeadline? = nil, error: String? = nil, machine: ConsoleMachine? = nil,
         monthlyUSD: Double? = nil, listUSD7d: Double? = nil) {
        self.headline = headline
        self.error = error
        self.machine = machine
        self.monthlyUSD = monthlyUSD
        self.listUSD7d = listUSD7d
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
        error = c.optional(.error)
        machine = c.optional(.machine)
        monthlyUSD = c.optional(.monthlyUSD)
        listUSD7d = c.optional(.listUSD7d)
    }
}

/// `{label, value, detail}`. The value is a string, a number or null; the number stays a number for the formatter.
struct ConsoleHeadline: Decodable, Equatable, Sendable {
    var label: String
    var text: String?
    var number: Double?
    var detail: String

    enum CodingKeys: String, CodingKey { case label, value, detail }

    init(label: String = "", text: String? = nil, number: Double? = nil, detail: String = "") {
        self.label = label
        self.text = text
        self.number = number
        self.detail = detail
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        label = c.lenient(.label, "")
        detail = c.lenient(.detail, "")
        text = try? c.decode(String.self, forKey: .value)
        number = try? c.decode(Double.self, forKey: .value)
    }
}

struct ConsoleMachine: Decodable, Equatable, Sendable {
    var verdict: String?
    var diskFreeGB: Double?

    enum CodingKeys: String, CodingKey {
        case verdict
        case diskFreeGB = "disk_free_gb"
    }

    init(verdict: String? = nil, diskFreeGB: Double? = nil) {
        self.verdict = verdict
        self.diskFreeGB = diskFreeGB
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        verdict = c.optional(.verdict)
        diskFreeGB = c.optional(.diskFreeGB)
    }
}

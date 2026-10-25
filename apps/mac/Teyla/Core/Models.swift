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

    enum CodingKeys: String, CodingKey {
        case version, generated, brief, totals, asks, products, running, tasks, done, relay, portfolio
    }

    init(version: Int = 1, generated: String = "", brief: Brief? = nil, totals: Totals = Totals(),
         asks: [Ask] = [], products: [Product] = [], running: [RunningSession] = [],
         tasks: [OwnerTask] = [], done: [DoneItem] = [], relay: Relay? = nil, portfolio: Portfolio? = nil) {
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
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
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

    enum CodingKeys: String, CodingKey {
        case id, kind, product, title, question, context, options, archived, link, pr
        case harness, status, ts, unblocks, rank, delivery
        case ageSeconds = "age_s"
    }

    init(id: String, product: String = "", question: String = "", options: [String] = [],
         unblocks: String = "", rank: Int = 0, link: String = "", ageSeconds: Double = 0) {
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

    enum CodingKeys: String, CodingKey { case version, checked, counts, products }
    enum CheckedKeys: String, CodingKey { case stores, github }

    init(version: Int = 1, checkedStores: String = "", checkedGitHub: String = "",
         counts: HealthCounts = HealthCounts(), products: [PortfolioProduct] = []) {
        self.version = version
        self.checkedStores = checkedStores
        self.checkedGitHub = checkedGitHub
        self.counts = counts
        self.products = products
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
    }

    func product(_ id: String) -> PortfolioProduct? { products.first { $0.id == id } }
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

    enum CodingKeys: String, CodingKey {
        case open, waiting
        case merged7d = "merged_7d"
        case unreviewed7d = "unreviewed_7d"
    }

    init(open: Int = 0, waiting: Int = 0, merged7d: Int = 0, unreviewed7d: Int = 0) {
        self.open = open
        self.waiting = waiting
        self.merged7d = merged7d
        self.unreviewed7d = unreviewed7d
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        open = c.lenient(.open, 0)
        waiting = c.lenient(.waiting, 0)
        merged7d = c.lenient(.merged7d, 0)
        unreviewed7d = c.lenient(.unreviewed7d, 0)
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

    var health: Health { Health(rawValue: healthRaw) ?? .onTrack }

    enum CodingKeys: String, CodingKey {
        case id, title, stage, focus, primary, users, target, reasons, platforms, prs, activity
        case waiting, tasks, milestone, next, repo
        case healthRaw = "health"
        case oldestWaitDays = "oldest_wait_days"
    }

    init(id: String, title: String = "", stage: String = "", focus: Bool = false, primary: String = "",
         users: String = "", target: String = "", health: String = "on_track", reasons: [String] = [],
         platforms: [PlatformStatus] = [], prs: PRCounts = PRCounts(), activity: Activity = Activity(),
         waiting: Int = 0, oldestWaitDays: Double = 0, tasks: Int = 0, milestone: String = "", next: String = "",
         repo: String = "") {
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

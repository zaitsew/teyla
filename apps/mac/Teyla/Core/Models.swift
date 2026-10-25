import Foundation

// The snapshot contract (versions 1 and 2) is documented in docs/APP.md. Decoding is lenient on
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

    enum CodingKeys: String, CodingKey {
        case version, generated, brief, totals, asks, products, running, tasks, done, relay
    }

    init(version: Int = 1, generated: String = "", brief: Brief? = nil, totals: Totals = Totals(),
         asks: [Ask] = [], products: [Product] = [], running: [RunningSession] = [],
         tasks: [OwnerTask] = [], done: [DoneItem] = [], relay: Relay? = nil) {
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

    var id: String { name }
    /// Unknown states are treated as quiet.
    var state: ProductState { ProductState(rawValue: stateRaw) ?? .quiet }

    enum CodingKeys: String, CodingKey {
        case name, waiting, line, issues, next, repo
        case stateRaw = "state"
        case lastActivity = "last_activity"
        case prsWaiting = "prs_waiting"
    }

    init(name: String, waiting: Int = 0, state: String = "quiet", line: String = "", lastActivity: String = "",
         issues: Int = 0, prsWaiting: Int = 0, next: String = "", repo: String = "") {
        self.name = name
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

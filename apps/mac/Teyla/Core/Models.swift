import Foundation

// The snapshot contract (version 1) is documented in docs/APP.md. Decoding is lenient on
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

    enum CodingKeys: String, CodingKey {
        case version, generated, brief, totals, asks, products, running
    }

    init(version: Int = 1, generated: String = "", brief: Brief? = nil, totals: Totals = Totals(),
         asks: [Ask] = [], products: [Product] = [], running: [RunningSession] = []) {
        self.version = version
        self.generated = generated
        self.brief = brief
        self.totals = totals
        self.asks = asks
        self.products = products
        self.running = running
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
        self.asks = asks.compactMap(\.value)
        self.products = products.compactMap(\.value)
        self.running = running.compactMap(\.value)
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

    enum CodingKeys: String, CodingKey {
        case questions, running
        case spentTodayUSD = "spent_today_usd"
    }

    init(questions: Int = 0, running: Int = 0, spentTodayUSD: Double? = nil) {
        self.questions = questions
        self.running = running
        self.spentTodayUSD = spentTodayUSD
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        questions = c.lenient(.questions, 0)
        running = c.lenient(.running, 0)
        spentTodayUSD = c.optional(.spentTodayUSD)
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

    var id: String { name }
    /// Unknown states are treated as quiet.
    var state: ProductState { ProductState(rawValue: stateRaw) ?? .quiet }

    enum CodingKeys: String, CodingKey {
        case name, waiting, line
        case stateRaw = "state"
        case lastActivity = "last_activity"
    }

    init(name: String, waiting: Int = 0, state: String = "quiet", line: String = "", lastActivity: String = "") {
        self.name = name
        self.waiting = waiting
        self.stateRaw = state
        self.line = line
        self.lastActivity = lastActivity
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        waiting = c.lenient(.waiting, 0)
        stateRaw = c.lenient(.stateRaw, "quiet")
        line = c.lenient(.line, "")
        lastActivity = c.lenient(.lastActivity, "")
    }
}

struct RunningSession: Decodable, Equatable, Identifiable, Sendable {
    var product: String
    var title: String
    var harness: String
    var model: String
    var since: String
    var link: String

    var id: String { link.isEmpty ? "\(product)/\(title)/\(since)" : link }

    enum CodingKeys: String, CodingKey { case product, title, harness, model, since, link }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        product = c.lenient(.product, "")
        title = c.lenient(.title, "")
        harness = c.lenient(.harness, "")
        model = c.lenient(.model, "")
        since = c.lenient(.since, "")
        link = c.lenient(.link, "")
    }
}

/// `teyla answer --json` prints `{ok, via, detail, id}`. `via` is `codex-queue`, `codex-resume`,
/// `claude-bg` or `opened`.
struct AnswerResult: Decodable, Equatable, Sendable {
    var ok: Bool
    var via: String
    var detail: String
    var id: String

    enum CodingKeys: String, CodingKey { case ok, via, detail, id }

    init(ok: Bool, via: String, detail: String = "", id: String = "") {
        self.ok = ok
        self.via = via
        self.detail = detail
        self.id = id
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = c.lenient(.ok, false)
        via = c.lenient(.via, "")
        detail = c.lenient(.detail, "")
        id = c.lenient(.id, "")
    }
}

enum ISODate {
    static func parse(_ s: String) -> Date? {
        guard !s.isEmpty else { return nil }
        if let d = try? Date(s, strategy: .iso8601) { return d }
        let fractional = Date.ISO8601FormatStyle(includingFractionalSeconds: true)
        return try? Date(s, strategy: fractional)
    }
}

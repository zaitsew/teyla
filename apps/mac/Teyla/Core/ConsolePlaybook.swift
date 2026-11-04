import Foundation

// The Playbook section of `teyla console --json` (docs/CONSOLE.md): what the owner has learned and standardized.
// Guidelines, the model ladder with what changed around it, knowledge counts, and what the sessions say about the
// owner. A part of the section can fail on its own (`{"error": ...}`); the others still load. A model from the arena
// board is a candidate, never a decision, and the page says so on every row.

/// A scalar the report prints as text or as a number: shown as text either way.
struct PlaybookScalar: Decodable, Equatable, Sendable {
    var text: String

    init(text: String) { self.text = text }

    init(from decoder: Decoder) throws {
        let one = try decoder.singleValueContainer()
        if let string = try? one.decode(String.self) { text = string; return }
        if let int = try? one.decode(Int.self) { text = int.formatted(.number.locale(Locale(identifier: "en_US"))); return }
        if let double = try? one.decode(Double.self) {
            text = double.formatted(.number.precision(.fractionLength(0...1)).locale(Locale(identifier: "en_US")))
            return
        }
        throw DecodingError.typeMismatch(String.self, .init(codingPath: decoder.codingPath, debugDescription: "not a scalar"))
    }
}

struct PlaybookGuideline: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var title: String
    var path: String?
    var updated: Date?
    var summary: String
    var exists: Bool?
    var count: Int?

    enum CodingKeys: String, CodingKey { case id, title, path, updated, summary, exists, count }

    init(id: String, title: String, path: String? = nil, updated: Date? = nil, summary: String = "", exists: Bool? = nil, count: Int? = nil) {
        self.id = id
        self.title = title
        self.path = path
        self.updated = updated
        self.summary = summary
        self.exists = exists
        self.count = count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = try c.decode(String.self, forKey: .title)
        id = c.lenient(.id, title)
        path = c.optional(.path)
        let day: String? = c.optional(.updated)
        updated = day.flatMap(MoneyLogic.day)
        summary = c.lenient(.summary, "")
        exists = c.optional(.exists)
        count = c.optional(.count)
    }
}

struct PlaybookLadderRow: Decodable, Equatable, Sendable, Identifiable {
    var provider: String
    var label: String
    var note: String
    var orchestrate: [String]
    var volume: [String]
    var triage: [String]

    var id: String { provider }

    enum CodingKeys: String, CodingKey { case provider, label, note, orchestrate, volume, triage }

    init(provider: String, label: String = "", note: String = "", orchestrate: [String] = [], volume: [String] = [], triage: [String] = []) {
        self.provider = provider
        self.label = label
        self.note = note
        self.orchestrate = orchestrate
        self.volume = volume
        self.triage = triage
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        provider = try c.decode(String.self, forKey: .provider)
        label = c.lenient(.label, provider)
        note = c.lenient(.note, "")
        orchestrate = c.lenient(.orchestrate, [])
        volume = c.lenient(.volume, [])
        triage = c.lenient(.triage, [])
    }
}

/// A place where the ladder and the catalogue disagree. The report gives a dictionary, or only a sentence.
struct PlaybookDrift: Decodable, Equatable, Sendable, Identifiable {
    var flag: String?
    var provider: String?
    var entry: String?
    var detail: String?

    var id: String { [flag, provider, entry, detail].compactMap { $0 }.joined(separator: "|") }

    enum CodingKeys: String, CodingKey { case flag, provider, entry, detail }

    init(flag: String? = nil, provider: String? = nil, entry: String? = nil, detail: String? = nil) {
        self.flag = flag
        self.provider = provider
        self.entry = entry
        self.detail = detail
    }

    init(from decoder: Decoder) throws {
        if let sentence = try? decoder.singleValueContainer().decode(String.self) {
            detail = sentence
            return
        }
        let c = try decoder.container(keyedBy: CodingKeys.self)
        flag = c.optional(.flag)
        provider = c.optional(.provider)
        entry = c.optional(.entry)
        detail = c.optional(.detail)
    }
}

/// A catalogue model nobody has looked at yet.
struct PlaybookNewModel: Decodable, Equatable, Sendable, Identifiable {
    var provider: String?
    var modelID: String
    var name: String?
    var date: Date?
    var price: String?
    var replaces: String?

    var id: String { "\(provider ?? "")/\(modelID)" }

    enum CodingKeys: String, CodingKey { case provider, id, name, date, seen, price, replaces }

    init(provider: String? = nil, modelID: String, name: String? = nil, date: Date? = nil, price: String? = nil, replaces: String? = nil) {
        self.provider = provider
        self.modelID = modelID
        self.name = name
        self.date = date
        self.price = price
        self.replaces = replaces
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modelID = try c.decode(String.self, forKey: .id)
        provider = c.optional(.provider)
        name = c.optional(.name)
        let day: String? = c.optional(.date) ?? c.optional(.seen)
        date = day.flatMap(MoneyLogic.day)
        price = c.optional(.price)
        replaces = c.optional(.replaces)
    }
}

struct PlaybookArenaRow: Decodable, Equatable, Sendable, Identifiable {
    var model: String
    var score: Double?
    var cost: Double?
    var pareto: Bool?
    var inLadder: Bool?
    var status: String?

    var id: String { model }

    enum CodingKeys: String, CodingKey {
        case model, score, cost, pareto, status
        case inLadder = "in_ladder"
    }

    init(model: String, score: Double? = nil, cost: Double? = nil, pareto: Bool? = nil, inLadder: Bool? = nil, status: String? = nil) {
        self.model = model
        self.score = score
        self.cost = cost
        self.pareto = pareto
        self.inLadder = inLadder
        self.status = status
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        model = try c.decode(String.self, forKey: .model)
        score = c.optional(.score)
        cost = c.optional(.cost)
        pareto = c.optional(.pareto)
        inLadder = c.optional(.inLadder)
        status = c.optional(.status)
    }
}

struct PlaybookArena: Decodable, Equatable, Sendable {
    var asOf: Date?
    var url: String?
    var stale: Bool?
    var top: [PlaybookArenaRow]
    var note: String
    var status: String

    enum CodingKeys: String, CodingKey { case asOf = "as_of", url, stale, top, note, status }

    init(asOf: Date? = nil, url: String? = nil, stale: Bool? = nil, top: [PlaybookArenaRow] = [], note: String = "", status: String = "") {
        self.asOf = asOf
        self.url = url
        self.stale = stale
        self.top = top
        self.note = note
        self.status = status
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let day: String? = c.optional(.asOf)
        asOf = day.flatMap(MoneyLogic.day)
        url = c.optional(.url)
        stale = c.optional(.stale)
        let rows: [LossyBox<PlaybookArenaRow>] = c.lenient(.top, [])
        top = rows.compactMap(\.value)
        note = c.lenient(.note, "")
        status = c.lenient(.status, "")
    }
}

struct PlaybookModels: Decodable, Equatable, Sendable {
    var ladder: [PlaybookLadderRow]
    var drift: [PlaybookDrift]
    var new: [PlaybookNewModel]
    var newNote: String
    var arena: PlaybookArena?
    var policy: String

    enum CodingKeys: String, CodingKey { case ladder, drift, new, arena, policy, newNote = "new_note" }

    init(ladder: [PlaybookLadderRow] = [], drift: [PlaybookDrift] = [], new: [PlaybookNewModel] = [], newNote: String = "",
         arena: PlaybookArena? = nil, policy: String = "") {
        self.ladder = ladder
        self.drift = drift
        self.new = new
        self.newNote = newNote
        self.arena = arena
        self.policy = policy
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let ladderRows: [LossyBox<PlaybookLadderRow>] = c.lenient(.ladder, [])
        ladder = ladderRows.compactMap(\.value)
        let driftRows: [LossyBox<PlaybookDrift>] = c.lenient(.drift, [])
        drift = driftRows.compactMap(\.value)
        let newRows: [LossyBox<PlaybookNewModel>] = c.lenient(.new, [])
        new = newRows.compactMap(\.value)
        newNote = c.lenient(.newNote, "")
        arena = c.optional(.arena)
        policy = c.lenient(.policy, "")
    }
}

// MARK: Knowledge

struct PlaybookWiki: Decodable, Equatable, Sendable {
    var path: String?
    var pages: Int?
    var drafts: Int?
    var confirmed: Int?
    var stale: Int?
    var inbox: Int?

    enum CodingKeys: String, CodingKey { case path, pages, drafts, confirmed, stale, inbox }

    init(path: String? = nil, pages: Int? = nil, drafts: Int? = nil, confirmed: Int? = nil, stale: Int? = nil, inbox: Int? = nil) {
        self.path = path
        self.pages = pages
        self.drafts = drafts
        self.confirmed = confirmed
        self.stale = stale
        self.inbox = inbox
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        path = c.optional(.path)
        pages = c.optional(.pages)
        drafts = c.optional(.drafts)
        confirmed = c.optional(.confirmed)
        stale = c.optional(.stale)
        inbox = c.optional(.inbox)
    }
}

struct PlaybookIntent: Decodable, Equatable, Sendable {
    var entries: Int?
    var products: Int?
    var recent: Int?

    enum CodingKeys: String, CodingKey { case entries, products, recent }

    init(entries: Int? = nil, products: Int? = nil, recent: Int? = nil) {
        self.entries = entries
        self.products = products
        self.recent = recent
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entries = c.optional(.entries)
        products = c.optional(.products)
        recent = c.optional(.recent)
    }
}

struct PlaybookCorrections: Decodable, Equatable, Sendable {
    var total: Int?
    var last30: Int?
    var repos: Int?

    enum CodingKeys: String, CodingKey { case total, last30, repos }

    init(total: Int? = nil, last30: Int? = nil, repos: Int? = nil) {
        self.total = total
        self.last30 = last30
        self.repos = repos
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = c.optional(.total)
        last30 = c.optional(.last30)
        repos = c.optional(.repos)
    }
}

struct PlaybookTaste: Decodable, Equatable, Sendable {
    var total: Int?
    var repos: Int?
    var fix: Int?
    var rule: Int?
    var reject: Int?

    enum CodingKeys: String, CodingKey { case total, repos, fix, rule, reject }

    init(total: Int? = nil, repos: Int? = nil, fix: Int? = nil, rule: Int? = nil, reject: Int? = nil) {
        self.total = total
        self.repos = repos
        self.fix = fix
        self.rule = rule
        self.reject = reject
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        total = c.optional(.total)
        repos = c.optional(.repos)
        fix = c.optional(.fix)
        rule = c.optional(.rule)
        reject = c.optional(.reject)
    }
}

struct PlaybookKnowledge: Decodable, Equatable, Sendable {
    var wiki: ConsoleLoad<PlaybookWiki>
    var intent: ConsoleLoad<PlaybookIntent>
    var corrections: ConsoleLoad<PlaybookCorrections>
    var taste: ConsoleLoad<PlaybookTaste>

    enum CodingKeys: String, CodingKey { case wiki, intent, corrections, taste }

    init(wiki: ConsoleLoad<PlaybookWiki> = .missing, intent: ConsoleLoad<PlaybookIntent> = .missing,
         corrections: ConsoleLoad<PlaybookCorrections> = .missing, taste: ConsoleLoad<PlaybookTaste> = .missing) {
        self.wiki = wiki
        self.intent = intent
        self.corrections = corrections
        self.taste = taste
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        wiki = c.load(.wiki)
        intent = c.load(.intent)
        corrections = c.load(.corrections)
        taste = c.load(.taste)
    }
}

// MARK: You

struct PlaybookQuote: Decodable, Equatable, Sendable, Identifiable {
    var text: String
    var day: Date?
    var product: String?
    var score: Double?

    var id: String { "\(day.map { String($0.timeIntervalSince1970) } ?? "")|\(text)" }

    enum CodingKeys: String, CodingKey { case text, day, product, score }

    init(text: String, day: Date? = nil, product: String? = nil, score: Double? = nil) {
        self.text = text
        self.day = day
        self.product = product
        self.score = score
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        text = try c.decode(String.self, forKey: .text)
        let when: String? = c.optional(.day)
        day = when.flatMap(MoneyLogic.day)
        product = c.optional(.product)
        score = c.optional(.score)
    }
}

struct PlaybookInsight: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var label: String
    var value: String?
    var detail: String

    enum CodingKeys: String, CodingKey { case id, label, value, detail }

    init(id: String, label: String, value: String? = nil, detail: String = "") {
        self.id = id
        self.label = label
        self.value = value
        self.detail = detail
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        label = try c.decode(String.self, forKey: .label)
        id = c.lenient(.id, label)
        let scalar: PlaybookScalar? = c.optional(.value)
        value = scalar?.text
        detail = c.lenient(.detail, "")
    }
}

struct PlaybookPostcard: Decodable, Equatable, Sendable {
    var week: String?
    var then: PlaybookQuote?
    var commits: Int?
    var tags: Int?
    var latestTag: String?

    enum CodingKeys: String, CodingKey { case week, then, now }
    enum NowKeys: String, CodingKey { case commits, tags, latestTag = "latest_tag" }

    init(week: String? = nil, then: PlaybookQuote? = nil, commits: Int? = nil, tags: Int? = nil, latestTag: String? = nil) {
        self.week = week
        self.then = then
        self.commits = commits
        self.tags = tags
        self.latestTag = latestTag
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        week = c.optional(.week)
        then = c.optional(.then)
        if let now = try? c.nestedContainer(keyedBy: NowKeys.self, forKey: .now) {
            commits = now.optional(.commits)
            tags = now.optional(.tags)
            latestTag = now.optional(.latestTag)
        }
    }
}

/// A chore the owner keeps being asked for, and the way to hand it off.
struct PlaybookChore: Decodable, Equatable, Sendable, Identifiable {
    var chore: String
    var label: String
    var count: Int?
    var asks: Int?
    var corrections: Int?
    var last: Date?
    var products: [String]
    var path: String
    var who: String
    var status: String
    var verified: String

    var id: String { chore }

    enum CodingKeys: String, CodingKey { case chore, label, count, asks, corrections, last, products, path, who, status, verified }

    init(chore: String, label: String = "", count: Int? = nil, asks: Int? = nil, corrections: Int? = nil, last: Date? = nil,
         products: [String] = [], path: String = "", who: String = "", status: String = "", verified: String = "") {
        self.chore = chore
        self.label = label
        self.count = count
        self.asks = asks
        self.corrections = corrections
        self.last = last
        self.products = products
        self.path = path
        self.who = who
        self.status = status
        self.verified = verified
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        chore = try c.decode(String.self, forKey: .chore)
        label = c.lenient(.label, chore)
        count = c.optional(.count)
        asks = c.optional(.asks)
        corrections = c.optional(.corrections)
        let day: String? = c.optional(.last)
        last = day.flatMap(MoneyLogic.day)
        products = c.lenient(.products, [])
        path = c.lenient(.path, "")
        who = c.lenient(.who, "")
        status = c.lenient(.status, "")
        verified = c.lenient(.verified, "")
    }
}

struct PlaybookRuleHit: Decodable, Equatable, Sendable, Identifiable {
    var rule: String
    var since: Date?
    var after: Int?

    var id: String { rule }

    enum CodingKeys: String, CodingKey { case rule, since, after }

    init(rule: String, since: Date? = nil, after: Int? = nil) {
        self.rule = rule
        self.since = since
        self.after = after
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        rule = try c.decode(String.self, forKey: .rule)
        let day: String? = c.optional(.since)
        since = day.flatMap(MoneyLogic.day)
        after = c.optional(.after)
    }
}

struct PlaybookContradictions: Decodable, Equatable, Sendable {
    var count: Int?
    var checked: Int?
    var corrections: Int?
    var rules: [PlaybookRuleHit]
    var detail: String

    enum CodingKeys: String, CodingKey { case count, checked, corrections, rules, detail }

    init(count: Int? = nil, checked: Int? = nil, corrections: Int? = nil, rules: [PlaybookRuleHit] = [], detail: String = "") {
        self.count = count
        self.checked = checked
        self.corrections = corrections
        self.rules = rules
        self.detail = detail
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        count = c.optional(.count)
        checked = c.optional(.checked)
        corrections = c.optional(.corrections)
        let rows: [LossyBox<PlaybookRuleHit>] = c.lenient(.rules, [])
        rules = rows.compactMap(\.value)
        detail = c.lenient(.detail, "")
    }
}

struct PlaybookYou: Decodable, Equatable, Sendable {
    /// False when this build has no `teyla you`; `reason` says why.
    var available: Bool
    var reason: String?
    var quoteOfTheDay: PlaybookQuote?
    var quotes: [PlaybookQuote]
    var insights: [PlaybookInsight]
    var postcard: PlaybookPostcard?
    var delegation: [PlaybookChore]
    var contradictions: PlaybookContradictions?
    var notes: [String]
    var localOnly: Bool?

    enum CodingKeys: String, CodingKey {
        case available, reason, quotes, insights, postcard, delegation, contradictions, notes
        case quoteOfTheDay = "quote_of_the_day", localOnly = "local_only"
    }

    init(available: Bool = true, reason: String? = nil, quoteOfTheDay: PlaybookQuote? = nil, quotes: [PlaybookQuote] = [],
         insights: [PlaybookInsight] = [], postcard: PlaybookPostcard? = nil, delegation: [PlaybookChore] = [],
         contradictions: PlaybookContradictions? = nil, notes: [String] = [], localOnly: Bool? = nil) {
        self.available = available
        self.reason = reason
        self.quoteOfTheDay = quoteOfTheDay
        self.quotes = quotes
        self.insights = insights
        self.postcard = postcard
        self.delegation = delegation
        self.contradictions = contradictions
        self.notes = notes
        self.localOnly = localOnly
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        available = c.lenient(.available, true)
        reason = c.optional(.reason)
        quoteOfTheDay = c.optional(.quoteOfTheDay)
        let quoteRows: [LossyBox<PlaybookQuote>] = c.lenient(.quotes, [])
        quotes = quoteRows.compactMap(\.value)
        let insightRows: [LossyBox<PlaybookInsight>] = c.lenient(.insights, [])
        insights = insightRows.compactMap(\.value)
        postcard = c.optional(.postcard)
        let choreRows: [LossyBox<PlaybookChore>] = c.lenient(.delegation, [])
        delegation = choreRows.compactMap(\.value)
        contradictions = c.optional(.contradictions)
        notes = c.lenient(.notes, [])
        localOnly = c.optional(.localOnly)
    }
}

struct PlaybookReport: Decodable, Equatable, Sendable, ConsoleSectionData {
    var headline: ConsoleHeadline?
    var guidelines: [PlaybookGuideline]
    var models: ConsoleLoad<PlaybookModels>
    var knowledge: ConsoleLoad<PlaybookKnowledge>
    var you: ConsoleLoad<PlaybookYou>

    enum CodingKeys: String, CodingKey { case headline, guidelines, models, knowledge, you }

    init(headline: ConsoleHeadline? = nil, guidelines: [PlaybookGuideline] = [], models: ConsoleLoad<PlaybookModels> = .missing,
         knowledge: ConsoleLoad<PlaybookKnowledge> = .missing, you: ConsoleLoad<PlaybookYou> = .missing) {
        self.headline = headline
        self.guidelines = guidelines
        self.models = models
        self.knowledge = knowledge
        self.you = you
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
        let rows: [LossyBox<PlaybookGuideline>] = c.lenient(.guidelines, [])
        guidelines = rows.compactMap(\.value)
        models = c.load(.models)
        knowledge = c.load(.knowledge)
        you = c.load(.you)
    }
}

// MARK: What the page says

enum PlaybookLogic {
    /// What the arena rows say about themselves when the report does not.
    static let candidateWord = "candidate, not a decision"

    /// "30 Oct", or nil.
    static func day(_ date: Date?) -> String? { date.map(MoneyLogic.shortDay) }

    /// A ladder tier as one line, or a dash.
    static func tier(_ names: [String]) -> String { names.isEmpty ? Format.dash : plain(names.joined(separator: " · ")) }

    /// The guideline's own line: "Updated 30 Oct", "21 files, updated 3 Nov", or why it cannot be opened.
    static func guidelineDetail(_ row: PlaybookGuideline) -> String {
        if row.exists == false { return "The file is missing." }
        var parts: [String] = []
        if let count = row.count { parts.append("\(count) file\(count == 1 ? "" : "s")") }
        if let updated = day(row.updated) { parts.append("updated \(updated)") }
        return parts.joined(separator: ", ")
    }

    /// A guideline opens only when the report says its file exists and gives a path.
    static func openable(_ row: PlaybookGuideline) -> URL? {
        guard row.exists != false, let path = row.path, !path.isEmpty else { return nil }
        return URL(fileURLWithPath: NSString(string: path).expandingTildeInPath)
    }

    /// The sentence for one place where the ladder and the catalogue disagree.
    static func driftText(_ drift: PlaybookDrift) -> String {
        if let detail = drift.detail, !detail.isEmpty { return plain(detail) }
        let parts = [drift.provider, drift.entry, drift.flag].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? "The ladder differs from the catalogue." : parts.joined(separator: " · ")
    }

    /// "OpenAI · $1/$5 · replaces Sol · seen 3 Nov", whatever of it is known.
    static func newModelDetail(_ model: PlaybookNewModel) -> String {
        var parts: [String] = []
        if let provider = model.provider, !provider.isEmpty { parts.append(MoneyLogic.providerName(provider)) }
        if let price = model.price, !price.isEmpty { parts.append(price) }
        if let replaces = model.replaces, !replaces.isEmpty { parts.append("replaces \(replaces)") }
        if let seen = day(model.date) { parts.append("seen \(seen)") }
        return parts.joined(separator: " · ")
    }

    /// Models the ladder has not looked at yet, plus drift, as the one figure the top of the page shows.
    static func modelsToLook(_ models: PlaybookModels?) -> Int? {
        models.map { $0.new.count + $0.drift.count }
    }

    /// The arena row's line: "score 1,510 · cost 0.35 · on the ladder".
    static func arenaDetail(_ row: PlaybookArenaRow) -> String {
        var parts: [String] = []
        if let score = row.score { parts.append("score \(score.formatted(.number.precision(.fractionLength(0...1)).locale(Locale(identifier: "en_US"))))") }
        if let cost = row.cost { parts.append("cost \(cost.formatted(.number.precision(.fractionLength(0...2)).locale(Locale(identifier: "en_US"))))") }
        if row.pareto == true { parts.append("best for its cost") }
        if let inLadder = row.inLadder { parts.append(inLadder ? "on the ladder" : "not on the ladder") }
        return parts.isEmpty ? "No figures." : parts.joined(separator: " · ")
    }

    /// Every arena row says it is a candidate: the row's own words, else the standard ones.
    static func arenaStatus(_ row: PlaybookArenaRow, board: PlaybookArena) -> String {
        if let status = row.status, !status.isEmpty { return status }
        return board.status.isEmpty ? candidateWord : board.status
    }

    /// "As of 30 Oct, stale" or the report's own note when there is no snapshot.
    static func arenaNote(_ arena: PlaybookArena?) -> String {
        guard let arena else { return "" }
        guard let asOf = day(arena.asOf) else { return plain(arena.note) }
        return "As of \(asOf)\(arena.stale == true ? ", out of date" : ""). Candidates, not decisions."
    }

    /// A count as text, or nil.
    static func count(_ value: Int?) -> String? {
        value.map { $0.formatted(.number.locale(Locale(identifier: "en_US"))) }
    }

    /// The wiki line, naming its path when the wiki is empty so the owner knows where to put pages.
    static func wikiDetail(_ wiki: PlaybookWiki) -> String {
        if (wiki.pages ?? 0) == 0 {
            let path = wiki.path.flatMap { MoneyLogic.fileLine($0) }
            return path.map { "No page yet in \($0)." } ?? "No page yet."
        }
        let parts = [("draft", wiki.drafts), ("confirmed", wiki.confirmed), ("stale", wiki.stale), ("in the inbox", wiki.inbox)]
            .compactMap { word, number in number.map { "\($0) \(word)" } }
        return parts.joined(separator: " · ")
    }

    static func intentDetail(_ intent: PlaybookIntent) -> String {
        var parts: [String] = []
        if let products = intent.products { parts.append("\(products) product\(products == 1 ? "" : "s")") }
        if let recent = intent.recent { parts.append("\(recent) recent") }
        return parts.isEmpty ? "Your own words, kept." : parts.joined(separator: " · ")
    }

    static func correctionsDetail(_ corrections: PlaybookCorrections) -> String {
        var parts: [String] = []
        if let last = corrections.last30 { parts.append("\(last) in the last 30 days") }
        if let repos = corrections.repos { parts.append("\(repos) repo\(repos == 1 ? "" : "s")") }
        return parts.isEmpty ? "Things you told an agent twice." : parts.joined(separator: " · ")
    }

    static func tasteDetail(_ taste: PlaybookTaste) -> String {
        let parts = [("fix", taste.fix), ("rule", taste.rule), ("reject", taste.reject)].compactMap { word, number in number.map { "\($0) \(word)" } }
        return parts.isEmpty ? "Design decisions you made." : parts.joined(separator: " · ")
    }

    /// "3 Oct · sample-app", whatever of it is known.
    static func attribution(_ quote: PlaybookQuote) -> String {
        [day(quote.day), quote.product].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    /// Quotes other than the one of the day, the best first (then the newest).
    static func otherQuotes(_ you: PlaybookYou) -> [PlaybookQuote] {
        let today = you.quoteOfTheDay?.text
        return you.quotes.filter { $0.text != today }.sorted {
            let (a, b) = ($0.score ?? 0, $1.score ?? 0)
            if a != b { return a > b }
            return ($0.day ?? .distantPast) > ($1.day ?? .distantPast)
        }
    }

    /// Chores still open come first; handed-off ones follow, by how often the owner was asked.
    static func choresInOrder(_ rows: [PlaybookChore]) -> [PlaybookChore] {
        rows.sorted {
            let (a, b) = (isOpen($0), isOpen($1))
            if a != b { return a }
            return ($0.count ?? 0) > ($1.count ?? 0)
        }
    }

    /// Report text without the backticks the source writes around commands: the page shows plain words.
    static func plain(_ text: String) -> String { text.replacingOccurrences(of: "`", with: "") }

    /// Chores shown before "Show more".
    static let choresShown = 4

    /// "handed off" as "Handed off": the first letter only.
    static func sentence(_ text: String) -> String { text.prefix(1).uppercased() + text.dropFirst() }

    static func isOpen(_ chore: PlaybookChore) -> Bool { chore.status.lowercased() == "open" }

    /// "asked 16 times · last 1 Nov · for sample-app".
    static func choreDetail(_ chore: PlaybookChore) -> String {
        var parts: [String] = []
        if let asks = chore.asks ?? chore.count { parts.append("asked \(asks) time\(asks == 1 ? "" : "s")") }
        if let last = day(chore.last) { parts.append("last \(last)") }
        if !chore.products.isEmpty { parts.append(chore.products.prefix(3).joined(separator: ", ")) }
        return parts.joined(separator: " · ")
    }

    /// The headline of the Contradictions part: a count, or a dash when the report could not check.
    static func contradictionRow(_ hit: PlaybookRuleHit) -> String {
        var parts: [String] = []
        if let after = hit.after { parts.append("\(after) corrections since") }
        if let since = day(hit.since) { parts.append("rule dated \(since)") }
        return parts.joined(separator: " · ")
    }
}

import Foundation

// The Today cockpit: what waits for the owner, did enough go out, and which goal moved. The numbers come from
// `teyla gtm today --json` (version 1, docs/GTM.md); nothing is counted here. Decoding is lenient: unknown fields are
// ignored and a missing optional field takes its default. `distribution.target` may be null (no goals file yet).
// There are no commit counts anywhere in this contract, and none are shown. No view code here.

/// One kind of waiting work: how many, from which source, and the source's own page when it has one.
struct GtmWaiting: Equatable, Sendable, Decodable {
    var total = 0
    var bySource: [String: Int] = [:]
    /// Only `http(s)` links reach the app; the Open button opens them.
    var links: [String: String] = [:]

    init(total: Int = 0, bySource: [String: Int] = [:], links: [String: String] = [:]) {
        self.total = total
        self.bySource = bySource
        self.links = links
    }

    private enum Keys: String, CodingKey { case total, bySource = "by_source", links }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        bySource = c.lenient(.bySource, [:])
        total = c.lenient(.total, bySource.values.reduce(0, +))
        links = c.lenient(.links, [:])
    }

    /// Sources that hold something, the biggest first, then by name.
    var sources: [(id: String, count: Int)] {
        bySource.filter { $0.value > 0 }.map { (id: $0.key, count: $0.value) }
            .sorted { $0.count != $1.count ? $0.count > $1.count : $0.id < $1.id }
    }
}

struct GtmDistribution: Equatable, Sendable, Decodable {
    var today = 0
    /// nil: no goals file, so there is no daily target.
    var target: Int?
    var week = 0
    var claimedByAgents = 0

    init(today: Int = 0, target: Int? = nil, week: Int = 0, claimedByAgents: Int = 0) {
        self.today = today
        self.target = target
        self.week = week
        self.claimedByAgents = claimedByAgents
    }

    private enum Keys: String, CodingKey { case today, target, week, claimedByAgents = "claimed_by_agents" }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        today = c.lenient(.today, 0)
        target = c.optional(.target)
        week = c.lenient(.week, 0)
        claimedByAgents = c.lenient(.claimedByAgents, 0)
    }
}

struct GtmTarget: Equatable, Sendable, Decodable {
    var stage: String
    var count: Int
    var target: Int

    init(stage: String, count: Int, target: Int) {
        self.stage = stage
        self.count = count
        self.target = target
    }

    private enum Keys: String, CodingKey { case stage, count, target }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        stage = try c.decode(String.self, forKey: .stage)
        count = c.lenient(.count, 0)
        target = c.lenient(.target, 0)
    }
}

struct GtmGoal: Equatable, Sendable, Decodable, Identifiable {
    var id: String
    var title: String
    var deadline: String?
    var daysLeft: Int?
    var targets: [GtmTarget]

    init(id: String, title: String, deadline: String? = nil, daysLeft: Int? = nil, targets: [GtmTarget] = []) {
        self.id = id
        self.title = title
        self.deadline = deadline
        self.daysLeft = daysLeft
        self.targets = targets
    }

    private enum Keys: String, CodingKey { case id, title, deadline, daysLeft = "days_left", targets }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        id = try c.decode(String.self, forKey: .id)
        title = c.lenient(.title, id)
        deadline = c.optional(.deadline)
        daysLeft = c.optional(.daysLeft)
        let boxes: [LossyBox<GtmTarget>] = c.lenient(.targets, [])
        targets = boxes.compactMap(\.value)
    }
}

/// One line of the ordered "what next" list.
struct GtmNext: Equatable, Sendable, Decodable, Identifiable {
    var kind: String
    var count: Int
    var label: String
    var command: String?
    var sources: [String]

    var id: String { kind }

    init(kind: String, count: Int, label: String, command: String? = nil, sources: [String] = []) {
        self.kind = kind
        self.count = count
        self.label = label
        self.command = command
        self.sources = sources
    }

    private enum Keys: String, CodingKey { case kind, count, label, command, sources }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        kind = try c.decode(String.self, forKey: .kind)
        count = c.lenient(.count, 0)
        label = c.lenient(.label, kind)
        command = c.optional(.command)
        sources = c.lenient(.sources, [])
    }
}

struct GtmSource: Equatable, Sendable, Decodable, Identifiable {
    var id: String
    var state: String
    var via: String
    var line: String

    init(id: String, state: String = "ok", via: String = "", line: String = "") {
        self.id = id
        self.state = state
        self.via = via
        self.line = line
    }

    private enum Keys: String, CodingKey { case id, state, via, line }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        id = try c.decode(String.self, forKey: .id)
        state = c.lenient(.state, "ok")
        via = c.lenient(.via, "")
        line = c.lenient(.line, "")
    }
}

/// The `today` object of `teyla gtm today --json`.
struct GtmToday: Equatable, Sendable, Decodable {
    var version = 1
    var day = ""
    var week = ""
    var hasGoals = false
    var approve = GtmWaiting()
    var send = GtmWaiting()
    var reply = GtmWaiting()
    var followUp = GtmWaiting()
    var distribution = GtmDistribution()
    var preparationToday = 0
    var preparationWeek = 0
    var outcomesToday = 0
    var outcomesWeek = 0
    var goals: [GtmGoal] = []
    var next: [GtmNext] = []
    var sources: [GtmSource] = []
    var doctor: [String] = []

    init() {}

    private enum Keys: String, CodingKey {
        case version, day, week, approve, send, reply, distribution, preparation, outcomes, goals, next, sources, doctor
        case hasGoals = "has_goals", followUp = "follow_up"
    }

    private struct Pair: Decodable {
        var today = 0
        var week = 0

        init() {}

        private enum Keys: String, CodingKey { case today, week }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            today = c.lenient(.today, 0)
            week = c.lenient(.week, 0)
        }
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        version = c.lenient(.version, 1)
        day = c.lenient(.day, "")
        week = c.lenient(.week, "")
        hasGoals = c.lenient(.hasGoals, false)
        approve = c.lenient(.approve, GtmWaiting())
        send = c.lenient(.send, GtmWaiting())
        reply = c.lenient(.reply, GtmWaiting())
        followUp = c.lenient(.followUp, GtmWaiting())
        distribution = c.lenient(.distribution, GtmDistribution())
        let preparation: Pair = c.lenient(.preparation, Pair())
        preparationToday = preparation.today
        preparationWeek = preparation.week
        let outcomes: Pair = c.lenient(.outcomes, Pair())
        outcomesToday = outcomes.today
        outcomesWeek = outcomes.week
        let goalBoxes: [LossyBox<GtmGoal>] = c.lenient(.goals, [])
        goals = goalBoxes.compactMap(\.value)
        let nextBoxes: [LossyBox<GtmNext>] = c.lenient(.next, [])
        next = nextBoxes.compactMap(\.value)
        let sourceBoxes: [LossyBox<GtmSource>] = c.lenient(.sources, [])
        sources = sourceBoxes.compactMap(\.value)
        doctor = c.lenient(.doctor, [])
    }

    static func decode(_ data: Data) throws -> GtmToday {
        do {
            return try JSONDecoder().decode(GtmToday.self, from: data)
        } catch {
            throw TeylaError.badOutput("the Today report")
        }
    }

    /// The waiting group of a `next` kind.
    func waiting(_ kind: String) -> GtmWaiting {
        switch kind {
        case "approve": approve
        case "send": send
        case "reply": reply
        case "follow_up": followUp
        default: GtmWaiting()
        }
    }
}

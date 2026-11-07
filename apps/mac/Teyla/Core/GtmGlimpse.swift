import Foundation

// What the Mac puts in the relay snapshot for the phone's Today card (`gtm`, built by `relay.gtm_view()`; docs/GTM.md):
// counts, the owner's own goal titles and weekly targets, and the ordered next actions as kinds and counts. No source names,
// no links, no doctor lines. nil from a Mac that does not send it, and the phone then hides the card.
// Decoding is lenient. No view code here: the iPhone app compiles this file by path.

struct GtmGlimpse: Decodable, Equatable, Sendable {
    struct Distribution: Decodable, Equatable, Sendable {
        var today = 0
        /// nil: no goal sets a daily target.
        var target: Int?
        var week = 0

        init(today: Int = 0, target: Int? = nil, week: Int = 0) {
            self.today = today
            self.target = target
            self.week = week
        }

        private enum Keys: String, CodingKey { case today, target, week }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            today = c.lenient(.today, 0)
            target = c.optional(.target)
            week = c.lenient(.week, 0)
        }
    }

    struct Target: Decodable, Equatable, Sendable {
        var stage: String
        var count: Int
        var target: Int

        init(stage: String, count: Int = 0, target: Int = 0) {
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

    struct Goal: Decodable, Equatable, Sendable, Identifiable {
        var id: String
        var title: String
        var daysLeft: Int?
        var targets: [Target]

        init(id: String, title: String, daysLeft: Int? = nil, targets: [Target] = []) {
            self.id = id
            self.title = title
            self.daysLeft = daysLeft
            self.targets = targets
        }

        private enum Keys: String, CodingKey { case id, title, daysLeft = "days_left", targets }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            id = try c.decode(String.self, forKey: .id)
            title = c.lenient(.title, id)
            daysLeft = c.optional(.daysLeft)
            let boxes: [LossyBox<Target>] = c.lenient(.targets, [])
            targets = boxes.compactMap(\.value)
        }
    }

    struct Next: Decodable, Equatable, Sendable {
        var kind: String
        var count: Int

        init(kind: String, count: Int = 0) {
            self.kind = kind
            self.count = count
        }

        private enum Keys: String, CodingKey { case kind, count }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: Keys.self)
            kind = try c.decode(String.self, forKey: .kind)
            count = c.lenient(.count, 0)
        }
    }

    var day = ""
    var approve = 0
    var send = 0
    var reply = 0
    var followUp = 0
    var distribution = Distribution()
    var outcomesWeek = 0
    var hasGoals = false
    var goals: [Goal] = []
    var next: [Next] = []

    init() {}

    private enum Keys: String, CodingKey {
        case day, approve, send, reply, distribution, goals, next
        case followUp = "follow_up", outcomesWeek = "outcomes_week", hasGoals = "has_goals"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        day = c.lenient(.day, "")
        approve = c.lenient(.approve, 0)
        send = c.lenient(.send, 0)
        reply = c.lenient(.reply, 0)
        followUp = c.lenient(.followUp, 0)
        distribution = c.lenient(.distribution, Distribution())
        outcomesWeek = c.lenient(.outcomesWeek, 0)
        hasGoals = c.lenient(.hasGoals, false)
        let goalBoxes: [LossyBox<Goal>] = c.lenient(.goals, [])
        goals = goalBoxes.compactMap(\.value)
        let nextBoxes: [LossyBox<Next>] = c.lenient(.next, [])
        next = nextBoxes.compactMap(\.value)
    }

    var waitingTotal: Int { approve + send + reply + followUp }

    /// "6 drafts to approve, 5 items to send, 2 replies to answer": only what is above zero; "Nothing waits for you."
    var waitingSpoken: String {
        let parts = [(approve, "approve"), (send, "send"), (reply, "reply"), (followUp, "follow_up")]
            .filter { $0.0 > 0 }.map { TodayLogic.waitingWords($0.1, count: $0.0) }
        return parts.isEmpty ? "Nothing waits for you." : parts.joined(separator: ", ") + "."
    }

    /// Today's sends over the daily target, 0 to 1; nil with no target.
    var distributionFraction: Double? {
        TodayLogic.distributionFraction(GtmDistribution(today: distribution.today, target: distribution.target))
    }

    var distributionFigure: String { TodayLogic.distributionFigure(GtmDistribution(today: distribution.today, target: distribution.target)) }

    /// One sentence for VoiceOver over the whole card.
    var spoken: String {
        var parts = [waitingSpoken]
        parts.append(TodayLogic.distributionSpoken(GtmDistribution(today: distribution.today, target: distribution.target, week: distribution.week)))
        parts.append("\(outcomesWeek) \(outcomesWeek == 1 ? "outcome" : "outcomes") this week.")
        return parts.joined(separator: " ")
    }
}

import Foundation

// The activity graph: every post, comment, reply, email, DM, call, meeting and response the owner logs counts +1, drawn as
// the contribution graph GitHub shows. The numbers come from `teyla growth activity --json` (version 1); nothing is counted
// here. An older `teyla` without that command shows one line, "Update the teyla command to see activity.", and nothing breaks.
// Decoding is lenient: unknown fields are ignored and a missing optional field takes its default.
// No view code here: the iPhone app has its own copy of the grid logic and reads the relay snapshot instead.

/// The kinds `teyla growth log --kind` takes. A fixed list: the app never builds a command from any other text.
enum ActivityKind {
    static let all = ["post", "comment", "reply", "email", "dm", "call", "meeting", "icp-meeting", "ad", "outreach", "response"]

    static func isKnown(_ kind: String) -> Bool { all.contains(kind) }

    /// The name in a picker.
    static func label(_ kind: String) -> String {
        switch kind {
        case "post": "Post"
        case "comment": "Comment"
        case "reply": "Reply"
        case "email": "Email"
        case "dm": "DM"
        case "call": "Call"
        case "meeting": "Meeting"
        case "icp-meeting": "ICP meeting"
        case "ad": "Ad"
        case "outreach": "Outreach"
        case "response": "Got a response"
        default: kind
        }
    }

    /// "2 comments", "1 email", "3 replies": the count with the kind in the right number.
    static func counted(_ kind: String, _ count: Int) -> String {
        if kind == "response" { return count == 1 ? "1 response" : "\(count) responses" }
        let one: String
        let many: String
        switch kind {
        case "post": (one, many) = ("post", "posts")
        case "comment": (one, many) = ("comment", "comments")
        case "reply": (one, many) = ("reply", "replies")
        case "email": (one, many) = ("email", "emails")
        case "dm": (one, many) = ("DM", "DMs")
        case "call": (one, many) = ("call", "calls")
        case "meeting": (one, many) = ("meeting", "meetings")
        case "icp-meeting": (one, many) = ("ICP meeting", "ICP meetings")
        case "ad": (one, many) = ("ad", "ads")
        case "outreach": (one, many) = ("outreach", "outreach")
        default: (one, many) = (kind, kind)
        }
        return "\(count) \(count == 1 ? one : many)"
    }
}

struct ActivityDay: Equatable, Sendable, Decodable {
    var day: String
    var count: Int
    /// 0 (nothing) to 4 (the busiest days), as the command decides.
    var level: Int
    var kinds: [String: Int]

    init(day: String, count: Int = 0, level: Int = 0, kinds: [String: Int] = [:]) {
        self.day = day
        self.count = count
        self.level = level
        self.kinds = kinds
    }

    private enum Keys: String, CodingKey { case day, count, level, kinds }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        day = try c.decode(String.self, forKey: .day)
        count = (try? c.decodeIfPresent(Int.self, forKey: .count)) ?? 0
        level = (try? c.decodeIfPresent(Int.self, forKey: .level)) ?? 0
        kinds = (try? c.decodeIfPresent([String: Int].self, forKey: .kinds)) ?? [:]
    }
}

struct ActivityReport: Equatable, Sendable, Decodable {
    var today = ""
    var weeks = 53
    var start = ""
    var days: [ActivityDay] = []
    var total = 0
    var todayCount = 0
    var weekCount = 0
    var streak = 0
    var longest = 0
    var byKind: [String: Int] = [:]
    var meetings = 0
    var responses = 0
    /// Rows an agent logged: a claim, shown as a note and never counted.
    var claimed = 0
    var kinds: [String] = ActivityKind.all

    init() {}

    private enum Keys: String, CodingKey {
        case today, weeks, start, days, total, streak, longest, outcomes, claimed, kinds
        case todayCount = "today_count", weekCount = "week_count", byKind = "by_kind"
    }

    private enum OutcomeKeys: String, CodingKey { case meetings, responses }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        func int(_ key: Keys) -> Int { (try? c.decodeIfPresent(Int.self, forKey: key)) ?? 0 }
        today = (try? c.decodeIfPresent(String.self, forKey: .today)) ?? ""
        weeks = (try? c.decodeIfPresent(Int.self, forKey: .weeks)) ?? 53
        start = (try? c.decodeIfPresent(String.self, forKey: .start)) ?? ""
        // One damaged day is skipped; the rest of the graph still draws.
        let boxes = (try? c.decodeIfPresent([LossyBox<ActivityDay>].self, forKey: .days)) ?? []
        days = boxes.compactMap(\.value)
        total = int(.total)
        todayCount = int(.todayCount)
        weekCount = int(.weekCount)
        streak = int(.streak)
        longest = int(.longest)
        byKind = (try? c.decodeIfPresent([String: Int].self, forKey: .byKind)) ?? [:]
        claimed = int(.claimed)
        if let o = try? c.nestedContainer(keyedBy: OutcomeKeys.self, forKey: .outcomes) {
            meetings = (try? o.decodeIfPresent(Int.self, forKey: .meetings)) ?? 0
            responses = (try? o.decodeIfPresent(Int.self, forKey: .responses)) ?? 0
        }
        if let list = try? c.decodeIfPresent([String].self, forKey: .kinds), !list.isEmpty { kinds = list }
        if today.isEmpty { today = days.last?.day ?? "" }
        if start.isEmpty { start = days.first?.day ?? "" }
    }

    static func decode(_ data: Data) throws -> ActivityReport {
        do {
            return try JSONDecoder().decode(ActivityReport.self, from: data)
        } catch {
            throw TeylaError.badOutput("the activity report")
        }
    }

    /// The kinds the picker offers: the command's own list, narrowed to the kinds the app is allowed to log.
    var loggableKinds: [String] {
        let known = kinds.filter(ActivityKind.isKnown)
        return known.isEmpty ? ActivityKind.all : known
    }
}

/// What the Mac puts in the relay snapshot for the phone: counts only (no notes, no products), the last 17 weeks of days, and the
/// year total. nil from a Mac that does not send it, and the phone then hides the card.
struct ActivityGlimpse: Decodable, Equatable, Sendable {
    var today = ""
    var start = ""
    var days: [ActivityDay] = []
    var todayCount = 0
    var weekCount = 0
    var streak = 0
    var longest = 0
    /// The year's total as the Mac counted it; the sum of the days when the Mac sent none.
    var total = 0
    var kinds: [String] = ActivityKind.all
    /// GitHub's contribution calendar for the same weeks (the iPhone widget's second grid); nil from a Mac without `gh`.
    var github: ActivitySeries?

    init() {}

    private enum Keys: String, CodingKey {
        case today, start, days, streak, longest, total, kinds, github
        case todayCount = "today_count", weekCount = "week_count"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        func int(_ key: Keys) -> Int { (try? c.decodeIfPresent(Int.self, forKey: key)) ?? 0 }
        let boxes = (try? c.decodeIfPresent([LossyBox<ActivityDay>].self, forKey: .days)) ?? []
        days = boxes.compactMap(\.value)
        today = (try? c.decodeIfPresent(String.self, forKey: .today)) ?? days.last?.day ?? ""
        start = (try? c.decodeIfPresent(String.self, forKey: .start)) ?? days.first?.day ?? ""
        todayCount = int(.todayCount)
        weekCount = int(.weekCount)
        streak = int(.streak)
        longest = int(.longest)
        total = (try? c.decodeIfPresent(Int.self, forKey: .total)) ?? days.reduce(0) { $0 + $1.count }
        if let list = try? c.decodeIfPresent([String].self, forKey: .kinds), !list.isEmpty { kinds = list }
        github = try? c.decodeIfPresent(ActivitySeries.self, forKey: .github)
    }

    /// The kinds the phone's picker offers: the Mac's list, narrowed to the kinds the relay accepts.
    var loggableKinds: [String] {
        let known = kinds.filter(ActivityKind.isKnown)
        return known.isEmpty ? ActivityKind.all : known
    }

    var spoken: String { ActivityLogic.spoken(today: todayCount, streak: streak, total: total) }
}

/// A second graph next to the growth one: GitHub's contribution calendar (`teyla growth activity --github`), counts and levels
/// only. `at` is when the Mac last fetched it (epoch seconds), 0 when unknown.
struct ActivitySeries: Decodable, Equatable, Sendable {
    var start = ""
    var days: [ActivityDay] = []
    var todayCount = 0
    var weekCount = 0
    var streak = 0
    var longest = 0
    var total = 0
    var at = 0

    init() {}

    private enum Keys: String, CodingKey {
        case start, days, streak, longest, total, at
        case todayCount = "today_count", weekCount = "week_count"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Keys.self)
        func int(_ key: Keys) -> Int { (try? c.decodeIfPresent(Int.self, forKey: key)) ?? 0 }
        let boxes = (try? c.decodeIfPresent([LossyBox<ActivityDay>].self, forKey: .days)) ?? []
        days = boxes.compactMap(\.value)
        start = (try? c.decodeIfPresent(String.self, forKey: .start)) ?? days.first?.day ?? ""
        todayCount = int(.todayCount)
        weekCount = int(.weekCount)
        streak = int(.streak)
        longest = int(.longest)
        total = (try? c.decodeIfPresent(Int.self, forKey: .total)) ?? days.reduce(0) { $0 + $1.count }
        at = int(.at)
    }
}

/// Which of the two layouts the card uses; the owner picks one with
/// `defaults write com.zaitsew.teyla.local teyla.activity.layout quarter`.
enum ActivityLayout: String, CaseIterable, Sendable {
    /// The full 53 weeks, small cells.
    case year
    /// The last 17 weeks, larger cells, the streak as a big number.
    case quarter

    static let key = "teyla.activity.layout"

    var weeks: Int { self == .year ? 53 : 17 }

    static func stored(_ raw: String?) -> ActivityLayout { raw.flatMap(ActivityLayout.init(rawValue:)) ?? .year }
}

/// One column of the grid: seven rows, Monday first. A day before the first day or after the last is nil.
struct ActivityColumn: Equatable, Sendable {
    var days: [ActivityDay?]
}

enum ActivityLogic {
    static let updateMessage = "Update the teyla command to see activity."

    private static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        return calendar
    }

    /// Monday = 0 ... Sunday = 6, or nil for text that is not a day.
    static func weekdayIndex(_ day: String) -> Int? {
        guard let date = MoneyLogic.day(day) else { return nil }
        let weekday = calendar.component(.weekday, from: date)      // Sunday = 1
        return (weekday + 5) % 7
    }

    /// The grid: one column per ISO week, Monday first, the newest week last, at most `weeks` columns.
    static func columns(_ days: [ActivityDay], weeks: Int) -> [ActivityColumn] {
        guard let first = days.first, let lead = weekdayIndex(first.day) else { return [] }
        var slots: [ActivityDay?] = Array(repeating: nil, count: lead) + days.map { Optional($0) }
        while slots.count % 7 != 0 { slots.append(nil) }
        var columns = stride(from: 0, to: slots.count, by: 7).map { ActivityColumn(days: Array(slots[$0 ..< $0 + 7])) }
        if columns.count > weeks { columns = Array(columns.suffix(weeks)) }
        return columns
    }

    /// Month names above the grid: a column gets one when its first day starts a month the previous label did not name.
    /// Two labels never sit closer than `gap` columns, so they cannot run into each other.
    static func monthLabels(_ columns: [ActivityColumn], gap: Int = 3) -> [(column: Int, name: String)] {
        var labels: [(column: Int, name: String)] = []
        var lastMonth = -1
        for (index, column) in columns.enumerated() {
            guard let day = column.days.compactMap({ $0 }).first, let date = MoneyLogic.day(day.day) else { continue }
            let month = calendar.component(.month, from: date)
            guard month != lastMonth else { continue }
            lastMonth = month
            if let previous = labels.last, index - previous.column < gap { continue }
            // The first column labels its month only when the month is not almost over.
            if index == 0, calendar.component(.day, from: date) > 21 { continue }
            labels.append((index, monthName(date)))
        }
        return labels
    }

    private static func monthName(_ date: Date) -> String {
        var style = Date.FormatStyle().month(.abbreviated)
        style.locale = Locale(identifier: "en_GB")
        style.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        return date.formatted(style)
    }

    private static func weekdayName(_ date: Date) -> String {
        var style = Date.FormatStyle().weekday(.abbreviated)
        style.locale = Locale(identifier: "en_GB")
        style.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        return date.formatted(style)
    }

    /// "Thu 6 Nov: 3 — 2 comments, 1 email", or "Thu 6 Nov: No activity".
    static func tooltip(_ day: ActivityDay, kindOrder: [String] = ActivityKind.all) -> String {
        guard let date = MoneyLogic.day(day.day) else { return day.day }
        let when = "\(weekdayName(date)) \(MoneyLogic.shortDay(date))"
        guard day.count > 0 else { return "\(when): No activity" }
        let ordered = day.kinds.filter { $0.value > 0 }.sorted { a, b in
            let ia = kindOrder.firstIndex(of: a.key) ?? Int.max
            let ib = kindOrder.firstIndex(of: b.key) ?? Int.max
            return ia == ib ? a.key < b.key : ia < ib
        }
        guard !ordered.isEmpty else { return "\(when): \(day.count)" }
        return "\(when): \(day.count) — " + ordered.map { ActivityKind.counted($0.key, $0.value) }.joined(separator: ", ")
    }

    /// "412 this year · today 3 · streak 5 days (longest 21)".
    static func summary(_ report: ActivityReport) -> String {
        "\(report.total) in the last year · today \(report.todayCount) · streak \(days(report.streak)) (longest \(report.longest))"
    }

    /// "Meetings held 4 · Responses 11".
    static func outcomes(_ report: ActivityReport) -> String {
        "Meetings held \(report.meetings) · Responses \(report.responses)"
    }

    /// "2 logged by an agent, not counted", or nil.
    static func claimedNote(_ report: ActivityReport) -> String? {
        report.claimed > 0 ? "\(report.claimed) logged by an agent, not counted" : nil
    }

    /// What VoiceOver reads for the card: one element.
    static func spoken(_ report: ActivityReport) -> String {
        spoken(today: report.todayCount, streak: report.streak, total: report.total)
    }

    static func spoken(today: Int, streak: Int, total: Int) -> String {
        "Activity: \(today) today, streak \(days(streak)), \(total) this year"
    }

    /// The line under the card after a "+1" from the phone: waiting, logged, or the Mac's own reason for refusing.
    static func resultWords(label: String, ok: Bool?, detail: String) -> String {
        guard let ok else { return "\(label): waiting for your Mac." }
        let why = detail.trimmingCharacters(in: .whitespacesAndNewlines)
        if ok { return "\(label): logged on your Mac." }
        return why.isEmpty ? "\(label): your Mac could not log it." : "\(label): \(why)"
    }

    static func days(_ n: Int) -> String { n == 1 ? "1 day" : "\(n) days" }

    /// The line the Home page and the menu would show: "Activity: today 3 · streak 5".
    static func oneLine(_ report: ActivityReport) -> String { "Activity: today \(report.todayCount) · streak \(report.streak)" }
}


/// Coalesces reads: a request made while a read is in flight is not lost, it runs once more when that read ends.
struct CoalescedRead: Equatable {
    private(set) var reading = false
    private(set) var dirty = false

    /// A read is wanted. True means start it now; false means one is running and will run again afterwards.
    mutating func request() -> Bool {
        if reading { dirty = true; return false }
        reading = true
        return true
    }

    /// The read ended. True means a request came in meanwhile, so read again (the gate stays busy).
    mutating func finish() -> Bool {
        if dirty { dirty = false; return true }
        reading = false
        return false
    }
}

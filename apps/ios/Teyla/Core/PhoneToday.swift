import Foundation

// The Today screen (Lab): what it shows and in which order. No view code here, so the tests cover it.
// Three groups: decisions, content, builds to try. Variant A lists them; variant B puts one next thing on top.

/// The Lab switch `teyla.lab.today`: off keeps the current Home.
enum TodayVariant: String, CaseIterable, Identifiable, Sendable {
    case off, a, b

    static let storageKey = "teyla.lab.today"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .off: return "Off"
        case .a: return "Stack"
        case .b: return "One next thing"
        }
    }

    static func from(stored: String) -> TodayVariant { TodayVariant(rawValue: stored) ?? .off }
}

/// What variant B shows large.
enum TodayNext: Equatable {
    case decision(Ask)
    case content
    case build(TodayBuild)
    case nothing
}

enum PhoneToday {
    /// Decisions on the screen: the top three, in rank order.
    static let decisionLimit = 3
    /// Builds in the compact list of variant B.
    static let compactBuildLimit = 3

    static func decisions(_ owner: [Ask]) -> [Ask] { Array(owner.prefix(decisionLimit)) }

    /// The oldest decision that blocks something. The phone has the question's kind only, so "critical" is `blocked`.
    static func oldestCritical(_ owner: [Ask]) -> Ask? {
        owner.filter { $0.kind == "blocked" }.max { $0.ageSeconds < $1.ageSeconds }
    }

    /// Newest upload first; the Mac already sorts, this keeps the phone correct for any order.
    static func newestFirst(_ builds: [TodayBuild]) -> [TodayBuild] {
        builds.enumerated().sorted { a, b in
            a.element.uploaded != b.element.uploaded ? a.element.uploaded > b.element.uploaded : a.offset < b.offset
        }.map(\.element)
    }

    /// The one next action: the oldest critical decision, else the post when one is due, else the newest build,
    /// else the top decision. Nothing when all three are empty.
    static func next(owner: [Ask], contentDue: Bool, builds: [TodayBuild]) -> TodayNext {
        if let critical = oldestCritical(owner) { return .decision(critical) }
        if contentDue { return .content }
        if let build = newestFirst(builds).first { return .build(build) }
        if let top = owner.first { return .decision(top) }
        return .nothing
    }

    /// Why the builds section has no number: the Mac's reason, or the older-Mac sentence. Nil when there is a count.
    static func buildsCaption(_ today: TodayData?) -> String? {
        guard let builds = today?.buildsToTry else {
            return "This Mac sends no build list. Update Teyla on the Mac."
        }
        if builds.count != nil { return nil }
        return builds.reason.isEmpty ? "Builds are not measured." : "Builds are not measured: \(builds.reason)."
    }

    /// The builds to show; empty when not measured.
    static func builds(_ today: TodayData?) -> [TodayBuild] {
        guard let builds = today?.buildsToTry, builds.count != nil else { return [] }
        return newestFirst(builds.builds)
    }

    static func buildTitle(_ build: TodayBuild) -> String { Format.product(build.product) }

    static func buildDetail(_ build: TodayBuild) -> String { "\(build.platform) \u{00B7} build \(build.build)" }

    /// `2026-11-12` as a day in the user's calendar; nil when the text is not a date.
    static func uploadedDate(_ build: TodayBuild) -> Date? {
        let parts = build.uploaded.prefix(10).split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return Calendar.current.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2]))
    }

    static func uploadedWords(_ build: TodayBuild) -> String {
        guard let date = uploadedDate(build) else { return build.uploaded }
        return "Uploaded " + date.formatted(.dateTime.day().month(.abbreviated))
    }

    static func buildSpoken(_ build: TodayBuild) -> String {
        "\(buildTitle(build)), \(build.platform), build \(build.build). \(uploadedWords(build))."
    }
}

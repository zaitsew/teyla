import Foundation

// The two commands that write the goals file: `teyla gtm goal add` and `teyla gtm goal set`. The app builds an argument array
// from checked parts and never a shell string. Every value goes in as `--flag=value`, so a title that starts with a dash cannot
// be read as a flag. No view code here.

/// One weekly number: a stage and how many a week.
struct GtmWeeklyNumber: Equatable, Sendable {
    var stage: String
    var count: Int
}

enum GtmGoalCommands {
    /// The stages the forms offer, in the order a person meets them.
    static let stages = ["conversation", "intro", "replied", "activated", "signed_up", "proposal", "paid"]
    static let countRange = 1 ... 500
    static let perDayRange = 1 ... 200
    static let titleLimit = 200

    /// A stage is lowercase words joined by underscores, as in goals.toml.
    static func isStage(_ text: String) -> Bool {
        !text.isEmpty && text.count <= 40 && text.allSatisfy { $0.isASCII && ($0.isLowercase || $0.isNumber || $0 == "_") }
    }

    static func isGoalID(_ text: String) -> Bool {
        !text.isEmpty && text.count <= 60 && !text.hasPrefix("-") && text.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "_" || $0 == "-") }
    }

    /// "YYYY-MM-DD" with a real month and day shape; the command checks the calendar.
    static func isDate(_ text: String) -> Bool {
        let parts = text.split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0].count == 4, parts[1].count == 2, parts[2].count == 2,
              parts.allSatisfy({ $0.allSatisfy { $0.isASCII && $0.isNumber } }) else { return false }
        return (1 ... 12).contains(Int(parts[1]) ?? 0) && (1 ... 31).contains(Int(parts[2]) ?? 0)
    }

    /// One line of text for a title or a "done when": trimmed, no line breaks, not empty, not too long.
    static func line(_ text: String?) -> String? {
        guard let text else { return nil }
        let one = text.replacingOccurrences(of: "\n", with: " ").replacingOccurrences(of: "\r", with: " ")
            .trimmingCharacters(in: .whitespaces)
        return one.isEmpty ? nil : String(one.prefix(titleLimit))
    }

    private static func weekly(_ numbers: [GtmWeeklyNumber]) -> [String]? {
        var out: [String] = []
        for number in numbers {
            guard isStage(number.stage), countRange.contains(number.count) else { return nil }
            out.append("--weekly=\(number.stage)=\(number.count)")
        }
        return out
    }

    /// `gtm goal add --title=T [--weekly=STAGE=N] [--deadline=D] [--done-when=T] [--per-day=N] --json`; nil when a part is invalid.
    static func addArguments(title: String, weekly numbers: [GtmWeeklyNumber], deadline: String?, doneWhen: String?, perDay: Int?) -> [String]? {
        guard let title = line(title), let weekly = weekly(numbers) else { return nil }
        var argv = ["gtm", "goal", "add", "--title=\(title)"] + weekly
        if let deadline {
            guard isDate(deadline) else { return nil }
            argv.append("--deadline=\(deadline)")
        }
        if let note = line(doneWhen) { argv.append("--done-when=\(note)") }
        if let perDay {
            guard perDayRange.contains(perDay) else { return nil }
            argv.append("--per-day=\(perDay)")
        }
        return argv + ["--json"]
    }

    /// `gtm goal set ID [--weekly=STAGE=N] [--title=T] [--deadline=D] [--done-when=T] --json`; nil when a part is invalid.
    static func setArguments(id: String, weekly numbers: [GtmWeeklyNumber], title: String? = nil, deadline: String? = nil, doneWhen: String? = nil) -> [String]? {
        guard isGoalID(id), let weekly = weekly(numbers) else { return nil }
        var argv = ["gtm", "goal", "set", id] + weekly
        if let title { guard let one = line(title) else { return nil }; argv.append("--title=\(one)") }
        if let deadline {
            guard isDate(deadline) else { return nil }
            argv.append("--deadline=\(deadline)")
        }
        if let doneWhen { guard let one = line(doneWhen) else { return nil }; argv.append("--done-when=\(one)") }
        return argv + ["--json"]
    }

    /// A day as "YYYY-MM-DD" in the calendar's own time zone: the day the person picked.
    static func dateString(_ date: Date, calendar: Calendar = .current) -> String {
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", parts.year ?? 0, parts.month ?? 0, parts.day ?? 0)
    }
}

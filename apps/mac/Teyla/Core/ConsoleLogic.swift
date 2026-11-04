import Foundation

/// The words around the admin sections: their names, the question each one answers, and the "updated" line.
/// The Mac and iPhone apps show the same words (docs/CONSOLE.md, "Seven destinations").
enum ConsoleText {
    struct Page: Equatable, Sendable {
        var title: String
        var question: String
        var symbol: String
    }

    static let growth = Page(title: "Growth", question: "Did every channel get its post today?", symbol: "megaphone")
    static let money = Page(title: "Money", question: "What leaves your accounts?", symbol: "creditcard")
    static let operations = Page(title: "Operations", question: "What failed or needs capacity?", symbol: "gauge.with.dots.needle.67percent")
    static let playbook = Page(title: "Playbook", question: "What you have learned and standardized", symbol: "book")

    /// "Updated 3 min ago". The time the command built the report when it says, else when this window got it.
    /// Nothing before a report exists: a page never claims it is current.
    static func updated(generated: Date?, readAt: Date?, now: Date) -> String {
        guard let moment = generated ?? readAt else { return "" }
        let seconds = now.timeIntervalSince(moment)
        return seconds < 60 ? "Updated just now" : "Updated \(Format.elapsed(seconds: seconds)) ago"
    }

    /// What a page says when its report is old because the last read failed.
    static let staleNote = "The last read failed. What you see may be out of date."

    /// Why a section has no data when the report has no such key (an older teyla command).
    static func missing(_ name: String) -> String {
        "\(name) is not in this report. Update the teyla command, then check again."
    }
}

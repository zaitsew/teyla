import Foundation

// The words and the keyboard rules of the Today screen, kept apart from the views so tests can reach them.
// Nothing here counts anything: every figure comes from `GtmToday`. No commit counts appear on this screen.

/// What a key does on the Today screen.
enum TodayAction: Equatable, Sendable {
    case previous, next, approve, skip, open
}

/// Which of the two layouts the screen uses (STANDARD R18). Both show the same parts; the structure differs.
/// `defaults write com.zaitsew.teyla.local teyla.today.layout queue|board`.
enum TodayLayout: String, CaseIterable, Sendable {
    /// The next item is the screen: the selected draft large, the actions beside it, the numbers in a strip.
    case queue
    /// The numbers are the screen: three counters, goal progress, the queue as a list below.
    case board

    static let key = "teyla.today.layout"

    static func stored(_ raw: String?) -> TodayLayout { raw.flatMap(TodayLayout.init(rawValue:)) ?? .queue }
}

enum TodayLogic {
    static let updateMessage = "Update the teyla command to see Today."

    // MARK: Keys

    /// The letter typed on the screen, or nil when it means nothing here. Letters work in either case. As in a list, j moves
    /// down and k moves up; the arrow keys do the same and are mapped by the view.
    static func action(for characters: String) -> TodayAction? {
        switch characters.lowercased() {
        case "j": return .next
        case "k": return .previous
        case "a": return .approve
        case "s": return .skip
        case "o": return .open
        default: return nil
        }
    }

    /// The selected index after a move, kept inside the list. An empty list has none.
    static func moved(_ index: Int?, by step: Int, count: Int) -> Int? {
        guard count > 0 else { return nil }
        let from = index ?? (step >= 0 ? -1 : count)
        return min(max(from + step, 0), count - 1)
    }

    /// Skip moves on to the next draft without changing this one; on the last it stays.
    static func skipped(_ index: Int?, count: Int) -> Int? { moved(index, by: 1, count: count) }

    /// The selected draft's id after the list changed. The same draft stays selected. When it left (approved, rejected), the
    /// draft that took its place is selected, or the last one; with nothing selected yet the first is.
    static func settled(selected: String?, old: [String], new: [String]) -> String? {
        guard !new.isEmpty else { return nil }
        if let selected, new.contains(selected) { return selected }
        if let selected, let at = old.firstIndex(of: selected) { return new[min(at, new.count - 1)] }
        return new[0]
    }

    // MARK: Links

    /// Only a web address opens; any other text is never opened.
    static func webLink(_ text: String?) -> URL? {
        guard let text, let url = URL(string: text), ["http", "https"].contains(url.scheme?.lowercased() ?? ""), url.host != nil else { return nil }
        return url
    }

    /// The source's own page for a waiting kind, when it gave one.
    static func link(_ waiting: GtmWaiting, source: String) -> URL? { webLink(waiting.links[source]) }

    // MARK: Words

    /// "replies", "drafts to approve": the plain name of a waiting kind, the count in the right number.
    static func waitingWords(_ kind: String, count: Int) -> String {
        let n = count == 1
        switch kind {
        case "approve": return n ? "1 draft to approve" : "\(count) drafts to approve"
        case "send": return n ? "1 item to send" : "\(count) items to send"
        case "reply": return n ? "1 reply to answer" : "\(count) replies to answer"
        case "follow_up": return n ? "1 follow-up due" : "\(count) follow-ups due"
        default: return "\(count) \(kind)"
        }
    }

    static func kindTitle(_ kind: String) -> String {
        switch kind {
        case "approve": "Approve"
        case "send": "Send"
        case "reply": "Replies"
        case "follow_up": "Follow up"
        default: kind.capitalized
        }
    }

    /// The source id as the owner reads it: "outreach" stays, "my_source" becomes "my source".
    static func sourceName(_ id: String) -> String { id.replacingOccurrences(of: "_", with: " ") }

    /// "3 of 10 today", or "3 today" when no goal sets a target.
    static func distributionFigure(_ d: GtmDistribution) -> String {
        d.target.map { "\(d.today) of \($0)" } ?? "\(d.today)"
    }

    static func distributionDetail(_ d: GtmDistribution) -> String {
        var parts: [String] = []
        parts.append(d.target == nil ? "No daily target: add one in goals.toml." : "\(d.week) sent this week.")
        if d.claimedByAgents > 0 { parts.append("\(d.claimedByAgents) claimed by agents, not counted.") }
        return parts.joined(separator: " ")
    }

    static func distributionFraction(_ d: GtmDistribution) -> Double? {
        guard let target = d.target, target > 0 else { return nil }
        return min(Double(d.today) / Double(target), 1)
    }

    static func distributionSpoken(_ d: GtmDistribution) -> String {
        let sent = d.today == 1 ? "1 post or approach sent today" : "\(d.today) posts and approaches sent today"
        guard let target = d.target else { return sent + ", no daily target set." }
        return sent + " of a target of \(target)."
    }

    static func outcomesDetail(_ t: GtmToday) -> String {
        t.outcomesToday == 0 ? "None yet today." : "\(t.outcomesToday) today."
    }

    static func outcomesSpoken(_ t: GtmToday) -> String {
        "\(t.outcomesWeek) \(t.outcomesWeek == 1 ? "outcome" : "outcomes") this week, \(t.outcomesToday) today."
    }

    static func waitingTotal(_ t: GtmToday) -> Int { t.approve.total + t.send.total + t.reply.total + t.followUp.total }

    static func waitingDetail(_ t: GtmToday) -> String {
        let parts = [("approve", t.approve), ("send", t.send), ("reply", t.reply), ("follow_up", t.followUp)]
            .filter { $0.1.total > 0 }
            .map { waitingWords($0.0, count: $0.1.total) }
        return parts.isEmpty ? "Nothing waits for you." : parts.joined(separator: ", ")
    }

    static func waitingSpoken(_ t: GtmToday) -> String {
        let total = waitingTotal(t)
        return total == 0 ? "Nothing waits for you." : "\(total) \(total == 1 ? "item waits" : "items wait") for you: \(waitingDetail(t))."
    }

    /// "114 days left", "1 day left", "Due today", "Past the deadline"; nil when the goal has no deadline.
    static func daysLeftWords(_ days: Int?) -> String? {
        guard let days else { return nil }
        if days < 0 { return "Past the deadline" }
        if days == 0 { return "Due today" }
        return days == 1 ? "1 day left" : "\(days) days left"
    }

    /// "conversation" stays; "offer_fit" reads "offer fit".
    static func stageName(_ stage: String) -> String {
        stage.replacingOccurrences(of: "_", with: " ").replacingOccurrences(of: ".", with: " ")
    }

    static func fraction(_ target: GtmTarget) -> Double {
        target.target > 0 ? min(Double(target.count) / Double(target.target), 1) : 0
    }

    static func targetWords(_ target: GtmTarget) -> String { "\(target.count) of \(target.target)" }

    /// One sentence for VoiceOver: "Conversations with founders. 6 of 15 conversations, 2 of 3 intros. 114 days left."
    static func goalSpoken(_ goal: GtmGoal) -> String {
        let targets = goal.targets.map { "\(targetWords($0)) \(stageName($0.stage))" }.joined(separator: ", ")
        return [goal.title, targets.isEmpty ? "No weekly target." : targets + " this week.", daysLeftWords(goal.daysLeft)]
            .compactMap { $0 }.joined(separator: ". ").replacingOccurrences(of: "..", with: ".")
    }

    /// The ordered next actions as sentences, for the list and for VoiceOver.
    static func nextWords(_ next: GtmNext) -> String { next.label }

    static func sourceState(_ state: String) -> String {
        switch state {
        case "ok": "ok"
        case "stale": "out of date"
        case "broken": "broken"
        case "missing": "missing"
        default: state
        }
    }

    static func updated(readAt: Date?, now: Date) -> String {
        guard let readAt else { return "Not read yet" }
        let seconds = Int(now.timeIntervalSince(readAt))
        if seconds < 60 { return "Updated just now" }
        let minutes = seconds / 60
        return minutes < 60 ? "Updated \(minutes) min ago" : "Updated \(minutes / 60) h ago"
    }
}

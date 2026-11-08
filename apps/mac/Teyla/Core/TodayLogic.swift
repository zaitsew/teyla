import Foundation

// The words and the choices of the Today screen (which goal leads, what is next, how a row reads), kept apart from the views
// so tests can reach them.
// Nothing here counts anything: every figure comes from `GtmToday`. No commit counts appear on this screen.

enum TodayLogic {
    static let updateMessage = "Update the teyla command to see Today."

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

    /// The source id as the owner reads it: "outreach" stays, "my_source" becomes "my source".
    static func sourceName(_ id: String) -> String { id.replacingOccurrences(of: "_", with: " ") }

    /// "3 of 10 today", or "3 today" when no goal sets a target.
    static func distributionFigure(_ d: GtmDistribution) -> String {
        d.target.map { "\(d.today) of \($0)" } ?? "\(d.today)"
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

    static func sourceState(_ state: String) -> String {
        switch state {
        case "ok": "ok"
        case "stale": "out of date"
        case "broken": "broken"
        case "missing": "missing"
        default: state
        }
    }

    // MARK: Stages

    /// A stage as a person reads it: "conversation" is "Conversations", "signed_up" is "Sign-ups", "offer_fit" is "Offer fit".
    static func stageLabel(_ stage: String) -> String {
        switch stage {
        case "conversation": return "Conversations"
        case "intro": return "Intros"
        case "offer_fit": return "Offer fit"
        case "activated": return "Activated"
        case "signed_up": return "Sign-ups"
        case "replied": return "Replies"
        case "proposal": return "Proposals"
        case "paid": return "Paying"
        default:
            let words = stageName(stage)
            return words.prefix(1).uppercased() + words.dropFirst()
        }
    }

    /// The label inside a sentence: "1 of 15 conversations this week".
    static func stageNoun(_ stage: String) -> String { stageLabel(stage).lowercased() }

    /// VoiceOver for one row of circles.
    static func beadsSpoken(_ target: GtmTarget) -> String { "\(target.count) of \(target.target) \(stageNoun(target.stage)) this week" }

    /// A row draws one circle per unit up to this many; a bigger number draws a thin bar instead.
    static let beadLimit = 30

    enum Beads: Equatable, Sendable {
        case circles(total: Int, filled: Int)
        case bar(fraction: Double)
    }

    /// Circles for a target up to `beadLimit`, a bar above it. A circle fills only for a real count: never above the number.
    static func beads(_ target: GtmTarget) -> Beads {
        let total = max(target.target, 0)
        if total > beadLimit { return .bar(fraction: fraction(target)) }
        return .circles(total: total, filled: min(max(target.count, 0), total))
    }

    // MARK: The featured goal

    /// The goal that leads: the largest shortfall, the first in the file on a tie. A goal with no outcome target is skipped
    /// unless none has one. nil with no goals.
    static func featuredIndex(_ goals: [GtmGoal]) -> Int? {
        guard !goals.isEmpty else { return nil }
        let candidates = goals.indices.filter { !goals[$0].outcomeTargets.isEmpty }
        guard !candidates.isEmpty else { return 0 }
        return candidates.reduce(candidates[0]) { best, next in goals[next].short > goals[best].short ? next : best }
    }

    static func featured(_ goals: [GtmGoal]) -> GtmGoal? { featuredIndex(goals).map { goals[$0] } }

    /// Every goal but the featured one, in file order.
    static func others(_ goals: [GtmGoal]) -> [GtmGoal] {
        let lead = featuredIndex(goals)
        return goals.indices.filter { $0 != lead }.map { goals[$0] }
    }

    enum Pace: Equatable, Sendable {
        case behind(Int)
        case onPace
    }

    /// nil when the goal has no outcome target, so there is nothing to be behind on.
    static func pace(_ goal: GtmGoal) -> Pace? {
        guard !goal.outcomeTargets.isEmpty else { return nil }
        return goal.short > 0 ? .behind(goal.short) : .onPace
    }

    static func paceWords(_ pace: Pace) -> String {
        switch pace {
        case .behind(let short): "Behind this week · \(short) short"
        case .onPace: "On pace this week"
        }
    }

    private static let months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    private static let weekdays = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

    private static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .current
        return calendar
    }

    /// "2027-03-01" as a date at noon UTC, so no time zone moves the day. nil for anything else.
    static func date(_ iso: String?) -> Date? {
        guard let iso else { return nil }
        let parts = iso.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, iso.count == 10 else { return nil }
        return calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2], hour: 12))
    }

    /// "2027-03-01" reads "1 March"; nil for anything that is not a date.
    static func deadlineWords(_ iso: String?) -> String? {
        guard let date = date(iso) else { return nil }
        let parts = calendar.dateComponents([.day, .month], from: date)
        guard let day = parts.day, let month = parts.month else { return nil }
        return "\(day) \(months[month - 1])"
    }

    /// "16 weeks left", "1 week left", "Last week"; "Past the deadline" once it is behind us. nil with no deadline.
    static func weeksLeftWords(weeks: Int?, days: Int?) -> String? {
        if let days, days < 0 { return "Past the deadline" }
        guard let weeks else { return nil }
        if weeks <= 0 { return "Last week" }
        return weeks == 1 ? "1 week left" : "\(weeks) weeks left"
    }

    /// The line under a goal's title: what done means, the deadline, the weeks left. "No deadline" when there is none.
    static func goalMeta(_ goal: GtmGoal) -> String {
        var parts: [String] = []
        if let note = goal.doneWhen?.trimmingCharacters(in: .whitespaces), !note.isEmpty { parts.append(note) }
        if let deadline = deadlineWords(goal.deadline) {
            parts.append(deadline)
            if let left = weeksLeftWords(weeks: goal.weeksLeft, days: goal.daysLeft) { parts.append(left) }
        } else {
            parts.append("No deadline")
        }
        return parts.joined(separator: " · ")
    }

    /// "Saturday, 7 November" from the report's day.
    static func dayWords(_ iso: String) -> String? {
        guard let date = date(iso) else { return nil }
        let parts = calendar.dateComponents([.day, .month, .weekday], from: date)
        guard let day = parts.day, let month = parts.month, let weekday = parts.weekday else { return nil }
        return "\(weekdays[weekday - 1]), \(day) \(months[month - 1])"
    }

    /// "week ends today", "week ends tomorrow", "week ends in 3 days"; nil when the command sent no week end.
    static func weekEndWords(day: String, weekEnd: String) -> String? {
        guard let from = date(day), let to = date(weekEnd) else { return nil }
        let days = calendar.dateComponents([.day], from: from, to: to).day ?? 0
        if days <= 0 { return "week ends today" }
        return days == 1 ? "week ends tomorrow" : "week ends in \(days) days"
    }

    /// The header's line: "Saturday, 7 November · week ends tomorrow".
    static func contextLine(_ today: GtmToday?) -> String {
        guard let today else { return "" }
        return [dayWords(today.day), weekEndWords(day: today.day, weekEnd: today.weekEnd)].compactMap { $0 }.joined(separator: " · ")
    }

    // MARK: The quiet strip

    /// The ticks of "Sent": at most `tickLimit`, the filled ones are what went out today. nil with no daily target.
    static let tickLimit = 20

    static func sentTicks(_ d: GtmDistribution) -> (total: Int, filled: Int)? {
        guard let target = d.target, target > 0 else { return nil }
        if target <= tickLimit { return (target, min(d.today, target)) }
        // A target above the limit is drawn at the limit, the fill scaled to match.
        let scaled = Int((Double(min(d.today, target)) / Double(target) * Double(tickLimit)).rounded(.up))
        return (tickLimit, min(scaled, tickLimit))
    }

    /// Replies and follow-ups that came back and wait for an answer.
    static func cameBack(_ t: GtmToday) -> Int { t.reply.total + t.followUp.total }

    static func cameBackWords(_ t: GtmToday) -> String {
        let n = cameBack(t)
        return n == 0 ? "none waiting" : "\(n) waiting"
    }

    /// Drafts agents prepared and wait for the owner. Agent work: it is never drawn in the accent colour.
    static func prepared(_ t: GtmToday) -> Int { t.approve.total }

    static func stripSpoken(_ t: GtmToday) -> String {
        let sent = t.distribution.target.map { "Sent \(t.distribution.today) of \($0) today." } ?? "Sent \(t.distribution.today) today."
        let back = cameBack(t) == 0 ? "Nothing came back is waiting." : "\(cameBack(t)) that came back \(cameBack(t) == 1 ? "is" : "are") waiting."
        return "\(sent) \(back) \(prepared(t)) prepared."
    }

    // MARK: Next for the featured goal

    static let nextKinds = ["reply", "approve", "send", "follow_up"]

    /// What to do next, from the command's ordered list: the first reply, approval, send or follow-up.
    struct NextStep: Equatable, Sendable {
        var kind: String
        var title: String
        var detail: String?
        var button: String
        /// The first source page the command gave for this kind. nil: the button goes to Growth.
        var link: URL?
    }

    /// "2 replies to answer, then 8 drafts for this goal"; "8 drafts for this goal" with no replies; nil with neither.
    static func goalNextTitle(replies: Int, goalDrafts: Int) -> String? {
        let own = goalDrafts == 1 ? "1 draft for this goal" : "\(goalDrafts) drafts for this goal"
        if replies > 0 {
            let first = waitingWords("reply", count: replies)
            return first.prefix(1).uppercased() + first.dropFirst() + (goalDrafts > 0 ? ", then \(own)" : "")
        }
        guard goalDrafts > 0 else { return nil }
        return own.prefix(1).uppercased() + own.dropFirst()
    }

    /// The footer sentence for drafts no goal claims, and the words of the link that goes to Growth. nil with none.
    static func untaggedWords(_ count: Int) -> (text: String, action: String)? {
        guard count > 0 else { return nil }
        return count == 1 ? ("1 draft has no goal.", "Assign it on Growth.") : ("\(count) drafts have no goal.", "Assign them on Growth.")
    }

    /// The featured goal's next step: replies first, then this goal's drafts, else the command's own ordered list.
    static func nextStep(_ today: GtmToday, goal: GtmGoal?) -> NextStep? {
        if let goal, let title = goalNextTitle(replies: today.reply.total, goalDrafts: goal.drafts) {
            if today.reply.total > 0, let base = nextStep(today), base.kind == "reply" {
                return NextStep(kind: "reply", title: title, detail: base.detail, button: base.button, link: base.link)
            }
            if today.reply.total == 0 {
                return NextStep(kind: "approve", title: title, detail: nextDetail("approve"), button: "Review drafts", link: nil)
            }
        }
        return nextStep(today)
    }

    static func nextStep(_ today: GtmToday) -> NextStep? {
        guard let next = today.next.first(where: { nextKinds.contains($0.kind) }) else { return nil }
        let link = next.sources.lazy.compactMap { link(today.waiting(next.kind), source: $0) }.first
        let title = next.label.prefix(1).uppercased() + next.label.dropFirst()
        let button: String
        switch next.kind {
        case "reply": button = "Answer replies"
        case "approve": button = "Review drafts"
        case "send": button = "Open the list"
        default: button = "Open follow-ups"
        }
        // Drafts are reviewed on Growth, so the approve step never carries a link.
        return NextStep(kind: next.kind, title: title, detail: nextDetail(next.kind), button: button, link: next.kind == "approve" ? nil : link)
    }

    /// The one line under the next step.
    static func nextDetail(_ kind: String) -> String? {
        switch kind {
        case "reply": "Replies first: they are conversations already started."
        case "approve": "Approve or skip; nothing is sent from Teyla."
        case "send": "You send them; Teyla only lists them."
        case "follow_up": "Follow up from the page of the source."
        default: nil
        }
    }

    /// The next step from a kind and a count alone, as the phone gets it: "2 replies to answer".
    static func nextTitle(kind: String, count: Int) -> String {
        let words = waitingWords(kind, count: count)
        return words.prefix(1).uppercased() + words.dropFirst()
    }

    // MARK: Drafts and goals

    /// The goal a waiting growth draft counts for, from `draft_goals`; nil for "no goal" (a draft with an explicit "none" too).
    static func draftGoal(_ draftID: String, in today: GtmToday) -> GtmGoal? {
        today.draftGoals[draftID].flatMap { id in today.goals.first { $0.id == id } }
    }

    /// The label of a draft's goal menu: the goal's title, or "No goal".
    static func draftGoalTitle(_ draftID: String, in today: GtmToday) -> String { draftGoal(draftID, in: today)?.title ?? "No goal" }

    // MARK: Other goals

    /// The target a thin row draws: the first outcome target. nil: the goal has no number yet.
    static func rowTarget(_ goal: GtmGoal) -> GtmTarget? { goal.outcomeTargets.first }

    /// The `--weekly` pairs for "Set a number": the new number, and the old stage at 0 when the stage changed, because
    /// `teyla gtm goal set` merges numbers and would otherwise keep both.
    static func weeklyChange(stage: String, count: Int, replacing old: String?) -> [GtmWeeklyNumber] {
        var out = [GtmWeeklyNumber(stage: stage, count: count)]
        if let old, !old.isEmpty, old != stage { out.append(GtmWeeklyNumber(stage: old, count: 0)) }
        return out
    }

    /// "0 of 12", with " · source not connected" when the goal names a source nothing feeds and no source answers for it.
    static func rowCount(_ goal: GtmGoal, target: GtmTarget) -> String {
        let words = targetWords(target)
        return goal.fedBy.isEmpty && !goal.unfed.isEmpty ? words + " · source not connected" : words
    }

    // MARK: The footer

    /// Sources that did not answer cleanly.
    static func sourcesNotOK(_ t: GtmToday) -> Int { t.sources.filter { $0.state != "ok" }.count }

    static func sourcesWords(_ count: Int) -> String { count == 1 ? "1 source not connected" : "\(count) sources not connected" }

    // MARK: Goal detail

    /// Squares for the weeks to a deadline, this week first; at most 52.
    static func weekSquares(weeksLeft: Int?) -> Int? { weeksLeft.map { min(max($0, 0) + 1, 52) } }

    /// "W45" from "2026-W45".
    static func weekShort(_ week: String) -> String { week.split(separator: "-").last.map(String.init) ?? week }

    /// The strength of a history cell, 0 to 3: how close the week came to the weekly number. nil: no run saved that week.
    static func cellLevel(count: Int?, target: Int) -> Int? {
        guard let count else { return nil }
        guard count > 0, target > 0 else { return 0 }
        let ratio = Double(count) / Double(target)
        return ratio >= 1 ? 3 : ratio >= 0.5 ? 2 : 1
    }

    // MARK: Starting a goal

    /// A starter chip on the first-run page: the words it puts in the title and the stage it picks.
    struct Starter: Equatable, Sendable, Identifiable {
        var id: String { name }
        var name: String
        var title: String
        var stage: String
    }

    static let starters = [
        Starter(name: "Conversations", title: "Conversations that lead to work", stage: "conversation"),
        Starter(name: "Testers", title: "Activated testers", stage: "activated"),
        Starter(name: "Customers", title: "Paying customers", stage: "paid"),
        Starter(name: "Investors", title: "Investor conversations", stage: "conversation"),
    ]

    static let defaultWeekly = 5
    static let defaultPerDay = 10

    /// The stages a picker offers: the usual ones, and the goal's own when it uses another.
    static func stageOptions(current: String?) -> [String] {
        guard let current, !GtmGoalCommands.stages.contains(current) else { return GtmGoalCommands.stages }
        return [current] + GtmGoalCommands.stages
    }

    /// "16 weeks to 1 March" for the goal's detail; nil with no deadline.
    static func weeksToWords(_ goal: GtmGoal) -> String? {
        guard let deadline = deadlineWords(goal.deadline), let weeks = goal.weeksLeft else { return nil }
        return weeks <= 0 ? "Last week before \(deadline)" : "\(weeks) \(weeks == 1 ? "week" : "weeks") to \(deadline)"
    }
}

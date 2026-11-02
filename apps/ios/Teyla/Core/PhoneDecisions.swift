import Foundation

// What the Home and Decisions tabs decide on the phone, kept out of the views so it can be tested.
// Who a question belongs to, the groups and the wording come from `HomeLogic.swift`, which the Mac app shares.

/// The questions on the Decisions tab, split the way the Mac splits them.
struct DecisionLists: Equatable {
    /// Waiting on the owner and not older than 7 days, in rank order.
    var fresh: [Ask]
    /// Waiting on the owner more than 7 days.
    var older: [Ask]
    /// An agent can settle these with Teyla's proposed default.
    var agent: [Ask]
    /// Teyla suggests closing these; they stay open until the owner accepts.
    var close: [Ask]
    /// True when the CLI triaged at least one question; the owner's questions are then grouped Pay, Decide, Do.
    var hasTriage: Bool

    var owner: [Ask] { fresh + older }

    init(asks: [Ask], snapshot: Snapshot, now: Date) {
        let split = Decisions.split(asks)
        let folded = PhoneFormat.splitAsks(split.owner, snapshot: snapshot, now: now)
        fresh = folded.fresh
        older = folded.older
        agent = split.agent
        close = split.close
        hasTriage = Decisions.hasTriage(asks)
    }
}

enum PhoneHome {
    static let updateTitle = "Update Teyla on your Mac"
    static let updateText = "Home needs a newer Teyla on your Mac to show your products by users and activity. The rest of the app keeps working."

    /// True when the Mac's Teyla is too old to send `portfolio.home` (before 0.36): no portfolio, or one without the
    /// three Home sections. The phone then says so and ranks nothing itself.
    static func needsMacUpdate(_ portfolio: Portfolio?) -> Bool {
        sections(portfolio) == nil
    }

    /// The three sections in the CLI's order, or nil when the Mac sends none. The phone never ranks: an id without a
    /// product row is skipped, and a section with no products stays in the list for the view to hide.
    static func sections(_ portfolio: Portfolio?) -> [HomeSection]? {
        guard let portfolio, portfolio.home != nil, case .sections(let sections) = HomeSections.layout(portfolio)
        else { return nil }
        return sections
    }

    /// What Home says when the Mac sends the sections and every one is empty.
    static let noProducts = "No products yet."

    /// The note under "Decisions", the same style as the three product sections.
    static let decisionsNote = "Only you can answer these"

    /// The brief: the Mac's sentence, else a count.
    static func briefLine(_ snapshot: Snapshot) -> String {
        if let line = snapshot.brief?.line, !line.isEmpty { return line }
        let n = Decisions.split(snapshot.asks).owner.count
        return n == 0 ? "Nothing needs you right now." : "\(n) \(n == 1 ? "question needs" : "questions need") you."
    }
}

// MARK: Closing from the phone

/// Where the closing requests sent from this phone stand. The Mac closes a question when it reads the entry;
/// until then the question is still open on every screen.
struct CloseProgress: Equatable {
    /// Close requests the Mac has not answered yet.
    var waiting = 0
    /// Questions the Mac closed for this phone and that nobody reopened: they can still be undone.
    var closed: [String] = []
    /// Reopen requests for those, not answered yet.
    var reopening = 0
    /// The first thing that went wrong, in words.
    var failure: String?
    /// True when a send was a sample or a preview: nothing was closed.
    var simulated = false

    var isEmpty: Bool { waiting == 0 && closed.isEmpty && reopening == 0 && failure == nil && !simulated }
}

enum CloseTracking {
    /// "Closing 3…", "Closed 3", "Reopening 3…".
    static func line(_ progress: CloseProgress) -> String? {
        if progress.waiting > 0 { return "Closing \(progress.waiting)\u{2026}" }
        if progress.reopening > 0 { return "Reopening \(progress.reopening)\u{2026}" }
        if !progress.closed.isEmpty { return "Closed \(progress.closed.count)" }
        return nil
    }

    static func progress(_ pending: [PendingAction]) -> CloseProgress {
        var result = CloseProgress()
        var accepted: [String] = []
        for action in pending where action.kind == .close {
            guard let outcome = action.outcome else {
                result.waiting += 1
                continue
            }
            if !outcome.ok {
                result.failure = result.failure ?? failureLine(outcome)
            } else if outcome.via == SampleData.via {
                result.simulated = true
            } else {
                accepted.append(action.target)
            }
        }
        // Reopen requests count only for questions this phone closed; the ones for Teyla's own closes have their own rows.
        let reopens = pending.filter { $0.kind == .reopen && accepted.contains($0.target) }
        let reopened = Set(reopens.filter { $0.outcome?.ok == true }.map(\.target))
        result.closed = accepted.filter { !reopened.contains($0) }
        for action in reopens {
            guard let outcome = action.outcome else {
                result.reopening += 1
                continue
            }
            if !outcome.ok { result.failure = result.failure ?? failureLine(outcome) }
        }
        return result
    }

    /// An old Mac refuses the two kinds as "malformed entry"; say what to do instead.
    static func failureLine(_ outcome: PendingAction.Outcome) -> String {
        if outcome.detail.hasPrefix("malformed entry") {
            return "This Mac's Teyla cannot do that yet. Update Teyla on your Mac."
        }
        return PhoneFormat.outcomeLine(outcome)
    }
}

import Foundation

/// Phone-only text helpers. The shared ones are in `Format` (apps/mac/Teyla/Core/Format.swift).
enum PhoneFormat {
    /// The Mac is called stale after this many seconds without a write to the relay folder.
    static let staleAfter: TimeInterval = 600

    /// "Mac synced just now", "Mac synced 4 min ago", "Mac synced 3 h ago".
    static func synced(secondsAgo: Double) -> String {
        let s = max(0, Int(secondsAgo))
        switch s {
        case ..<60: return "Mac synced just now"
        case ..<3600: return "Mac synced \(s / 60) min ago"
        case ..<86_400: return "Mac synced \(s / 3600) h ago"
        default: return "Mac synced \(s / 86_400) d ago"
        }
    }

    /// "just now", "5 min ago", "7h ago", "2d ago".
    static func ago(_ seconds: Double) -> String {
        let text = Format.age(seconds: seconds)
        return text == "just now" ? text : "\(text) ago"
    }

    static func isStale(secondsAgo: Double) -> Bool { secondsAgo > staleAfter }

    /// When the Mac last wrote the snapshot: `relay.synced`, else `generated`.
    static func syncDate(of snapshot: Snapshot) -> Date? {
        if let synced = snapshot.relay?.synced, let date = ISODate.parse(synced) { return date }
        return snapshot.generatedDate
    }

    /// Age of an item in the snapshot now: its `age_s` plus the time since the snapshot was written.
    static func age(_ ageSeconds: Double, snapshot: Snapshot, now: Date) -> Double {
        let base = snapshot.generatedDate.map { max(0, now.timeIntervalSince($0)) } ?? 0
        return ageSeconds + base
    }

    /// A question that has waited longer than this folds into "Older" on Today.
    static let olderAfter: TimeInterval = 7 * 86_400

    /// Splits the open questions into fresh ones and ones that waited more than 7 days. Both keep the
    /// order the Mac ranked them in.
    static func splitAsks(_ asks: [Ask], snapshot: Snapshot, now: Date) -> (fresh: [Ask], older: [Ask]) {
        var fresh: [Ask] = []
        var older: [Ask] = []
        for ask in asks {
            if age(ask.ageSeconds, snapshot: snapshot, now: now) > olderAfter {
                older.append(ask)
            } else {
                fresh.append(ask)
            }
        }
        return (fresh, older)
    }

    /// How long ago an ISO time was, in seconds; nil when it does not parse.
    static func secondsSince(_ iso: String, now: Date) -> Double? {
        ISODate.parse(iso).map { max(0, now.timeIntervalSince($0)) }
    }

    /// Only web links open on the phone; `claude://` and `codex://` belong to the Mac.
    static func webURL(_ link: String) -> URL? {
        guard let url = URL(string: link.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme?.lowercased(), scheme == "https" || scheme == "http", url.host() != nil
        else { return nil }
        return url
    }

    /// "github.com/example/atlas/pull/301" for a link button.
    static func linkLabel(_ url: URL) -> String {
        let host = (url.host() ?? "").replacingOccurrences(of: "www.", with: "")
        return host + url.path()
    }

    /// The `sent/` line under a card: what the Mac did with the entry.
    static func outcomeLine(_ outcome: PendingAction.Outcome) -> String {
        if outcome.ok { return Format.sentLine(via: outcome.via) }
        let detail = outcome.detail.trimmingCharacters(in: .whitespacesAndNewlines)
        return detail.isEmpty ? "The Mac could not deliver this" : String(detail.prefix(300))
    }

    static func decodeSnapshot(_ data: Data) throws -> Snapshot {
        try JSONDecoder().decode(Snapshot.self, from: data)
    }
}

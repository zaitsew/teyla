import Foundation

// The Morning post card's logic: the prompt, the day rollover, the post-link check and the device-only record.
// Nothing here talks to a network. The record lives in this iPhone's UserDefaults and never goes to the relay.

enum PostNetwork: String, Codable, CaseIterable, Sendable {
    case linkedIn = "linkedin"
    case x
}

/// A post the owner marked as posted. The link is added on a later day, or skipped.
struct PostedRecord: Codable, Equatable, Sendable {
    var day: String
    var networks: [String]
    var url: String?
    var skipped = false
}

struct MorningCardState: Codable, Equatable, Sendable {
    var day: String
    /// The answer text of the day.
    var answer = ""
    var linkedIn: String?
    var x: String?
    /// `PostDraft.Source` raw value of the shown drafts.
    var source: String?
    /// Networks whose button the owner tapped today, in order.
    var copied: [String] = []
    /// Set by "Posted": today's post, and the networks it covers.
    var posted: PostedRecord?
    /// Yesterday's (or an older) posted record, kept only for the link ask.
    var previous: PostedRecord?

    init(day: String) { self.day = day }

    var hasDrafts: Bool { linkedIn != nil && x != nil }

    /// A fresh state for `newDay`. Today's posted record moves to `previous`; anything else is dropped.
    func rolled(to newDay: String) -> MorningCardState {
        guard newDay != day else { return self }
        var next = MorningCardState(day: newDay)
        next.previous = posted ?? previous
        return next
    }

    mutating func markCopied(_ network: PostNetwork) {
        if !copied.contains(network.rawValue) { copied.append(network.rawValue) }
    }

    mutating func markPosted() {
        posted = PostedRecord(day: day, networks: copied)
    }

    /// The record whose link the card asks for: posted on an earlier day, with no link and not skipped.
    var linkAsk: PostedRecord? {
        guard let record = previous, record.day < day, record.url == nil, !record.skipped else { return nil }
        return record
    }

    mutating func saveLink(_ url: String) -> Bool {
        guard MorningCardLogic.validPostURL(url) != nil, previous != nil else { return false }
        previous?.url = url.trimmingCharacters(in: .whitespacesAndNewlines)
        return true
    }

    mutating func skipLink() { previous?.skipped = true }
}

enum MorningCardLogic {
    static let storageKey = "teyla.morningCard.v1"
    static let labKey = "teyla.lab.morningCard"
    static let titleLimit = 80
    static let fallbackPrompt = "What did you ship or learn yesterday?"
    static let secondsLimit = 60

    // MARK: Prompt

    /// The newest merged PR title the snapshot carries (`portfolio.products[].progress.shipped_7d`): products ordered by last activity, newest first;
    /// the first title of the first product that has one.
    static func shippedTitle(in snapshot: Snapshot?) -> String? {
        guard let products = snapshot?.portfolio?.products else { return nil }
        let dated = products.enumerated().map { (index: $0.offset, date: ISODate.parse($0.element.activity.last), product: $0.element) }
        let ordered = dated.sorted { a, b in
            switch (a.date, b.date) {
            case let (x?, y?): return x != y ? x > y : a.index < b.index
            case (_?, nil): return true
            case (nil, _?): return false
            default: return a.index < b.index
            }
        }
        for row in ordered {
            if let title = row.product.progress?.shippedTop.first(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }) {
                return title.trimmingCharacters(in: .whitespacesAndNewlines)
            }
        }
        return nil
    }

    static func truncated(_ title: String, limit: Int = titleLimit) -> String {
        guard title.count > limit else { return title }
        return String(title.prefix(limit - 1)).trimmingCharacters(in: .whitespaces) + "\u{2026}"
    }

    static func prompt(title: String?) -> String {
        guard let title, !title.trimmingCharacters(in: .whitespaces).isEmpty else { return fallbackPrompt }
        return "Yesterday you shipped \u{201C}\(truncated(title))\u{201D}. What surprised you?"
    }

    static func prompt(snapshot: Snapshot?) -> String { prompt(title: shippedTitle(in: snapshot)) }

    // MARK: Days

    static func dayKey(_ date: Date, calendar: Calendar = .current) -> String {
        let c = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    // MARK: Post link

    /// https only, on linkedin.com, x.com or twitter.com (or a subdomain of them).
    static func validPostURL(_ text: String) -> URL? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.lowercased().hasPrefix("https://"), let url = URL(string: t), let host = url.host?.lowercased() else { return nil }
        let ok = ["linkedin.com", "x.com", "twitter.com"].contains { host == $0 || host.hasSuffix("." + $0) }
        return ok ? url : nil
    }

    // MARK: Hand-off URLs

    static let linkedInURL = URL(string: "https://www.linkedin.com/feed/?shareActive=true")!

    static func xIntentURL(text: String) -> URL? {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-._~")
        guard let q = text.addingPercentEncoding(withAllowedCharacters: allowed) else { return nil }
        return URL(string: "https://x.com/intent/post?text=\(q)")
    }

    // MARK: Storage

    static func load(defaults: UserDefaults = .standard, now: Date = Date(), calendar: Calendar = .current) -> MorningCardState {
        let today = dayKey(now, calendar: calendar)
        guard let data = defaults.data(forKey: storageKey),
              let state = try? JSONDecoder().decode(MorningCardState.self, from: data)
        else { return MorningCardState(day: today) }
        return state.rolled(to: today)
    }

    static func save(_ state: MorningCardState, defaults: UserDefaults = .standard) {
        if let data = try? JSONEncoder().encode(state) { defaults.set(data, forKey: storageKey) }
    }
}

import Foundation

/// Small text helpers, kept free of UI so they can be tested.
enum Format {
    /// "wine-cellar" becomes "Wine Cellar"; "(no repo)" becomes "Other".
    static func product(_ name: String) -> String {
        if name.isEmpty || name.hasPrefix("(") { return "Other" }
        return name.split(whereSeparator: { $0 == "-" || $0 == "_" })
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }

    /// Products worth a row: something waits on the owner, a session runs there, or it shipped.
    /// The rest is one line, so the column stays short.
    static func splitProducts(_ products: [Product], running: [RunningSession]) -> (shown: [Product], rest: Int) {
        let busy = Set(running.map(\.product))
        let shown = products.filter { $0.waiting > 0 || $0.prsWaiting > 0 || $0.state == .shipped || busy.contains($0.name) }
        return (shown, products.count - shown.count)
    }

    /// "just now", "5 min", "7h", "2d".
    static func age(seconds: Double) -> String {
        let s = max(0, Int(seconds))
        switch s {
        case ..<60: return "just now"
        case ..<3600: return "\(s / 60) min"
        case ..<86_400: return "\(s / 3600)h"
        default: return "\(s / 86_400)d"
        }
    }

    /// A duration for the "Running now" list: "14 min", "2 h".
    static func duration(seconds: Double) -> String {
        let s = max(0, Int(seconds))
        switch s {
        case ..<60: return "<1 min"
        case ..<3600: return "\(s / 60) min"
        case ..<86_400: return "\(s / 3600) h"
        default: return "\(s / 86_400) d"
        }
    }

    /// "claude-sonnet-5-5" becomes "Sonnet"; unknown shapes are returned as they are.
    static func model(_ id: String) -> String {
        let parts = id.split(separator: "-").map(String.init)
        if parts.first == "claude", parts.count > 1 { return parts[1].capitalized }
        return id
    }

    static func spent(_ usd: Double) -> String {
        usd.formatted(.currency(code: "USD").locale(Locale(identifier: "en_US")))
    }

    /// "3 questions · 2 sessions running · $4.10 at API prices today"; spend is left out when unknown.
    static func subline(questions: Int, running: Int, spentUSD: Double?) -> String {
        var parts = [
            "\(questions) \(questions == 1 ? "question" : "questions")",
            "\(running) \(running == 1 ? "session" : "sessions") running",
        ]
        if let spentUSD { parts.append("\(spent(spentUSD)) at API prices today") }
        return parts.joined(separator: " · ")
    }

    /// "45 s", "5 min", "3 h", "2 d": an elapsed time without "ago", for a label that has its own words.
    static func elapsed(seconds: Double) -> String {
        let s = max(0, Int(seconds))
        switch s {
        case ..<60: return "\(s) s"
        case ..<3600: return "\(s / 60) min"
        case ..<86_400: return "\(s / 3600) h"
        default: return "\(s / 86_400) d"
        }
    }

    /// "just now", "5 min ago", "3 h ago", "2 d ago".
    static func ago(seconds: Double) -> String {
        seconds < 60 ? "just now" : "\(elapsed(seconds: seconds)) ago"
    }

    /// "3 issues · 1 PR waiting"; a count of zero is left out, and nothing is returned when both are zero.
    static func counts(issues: Int, prsWaiting: Int) -> String {
        var parts: [String] = []
        if issues > 0 { parts.append("\(issues) \(issues == 1 ? "issue" : "issues")") }
        if prsWaiting > 0 { parts.append("\(prsWaiting) \(prsWaiting == 1 ? "PR" : "PRs") waiting") }
        return parts.joined(separator: " · ")
    }

    /// The chip on a result card: `done`, `needs_you`, `blocked`, `failed`, `review_ready`.
    /// An unknown status is shown as written, with the underscores removed.
    static func statusLabel(_ status: String) -> String {
        switch status {
        case "done": return "Done"
        case "needs_you": return "Needs you"
        case "blocked": return "Blocked"
        case "failed": return "Failed"
        case "review_ready": return "Ready for review"
        default:
            let text = status.replacingOccurrences(of: "_", with: " ")
            return text.prefix(1).uppercased() + text.dropFirst()
        }
    }

    /// The kind of an owner task: `merge` or `task`.
    static func taskKind(_ kind: String) -> String {
        kind == "merge" ? "Merge" : "Task"
    }

    /// A short label for a link on a result card: a GitHub pull request or issue becomes
    /// "example/atlas#301"; any other URL is shown as host and path.
    static func linkLabel(_ link: String) -> String {
        guard let url = URL(string: link), let host = url.host else { return link }
        let parts = url.path.split(separator: "/").map(String.init)
        if host == "github.com", parts.count >= 4, parts[2] == "pull" || parts[2] == "issues" {
            return "\(parts[0])/\(parts[1])#\(parts[3])"
        }
        let path = url.path == "/" ? "" : url.path
        return host + path
    }

    /// The relay line in Settings: "Paired · synced 2 min ago".
    static func relayLine(_ relay: Relay?, now: Date) -> String {
        guard let relay, relay.on else { return "Relay is off." }
        if !relay.paired { return "Relay is on. No iPhone is paired." }
        guard let synced = ISODate.parse(relay.synced) else { return "Paired · not synced yet" }
        let ago = age(seconds: now.timeIntervalSince(synced))
        return ago == "just now" ? "Paired · synced just now" : "Paired · synced \(ago) ago"
    }

    /// The line under a delivered correction (`teyla say`).
    static func saidLine(via: String) -> String {
        switch via {
        case "codex-queue": return "Queued: Codex reads it after the current turn"
        case "opened": return "Copied to the clipboard and opened the session"
        case "fixture": return "Queued (preview only, nothing was delivered)"
        case "sample": return "Sample: nothing was sent"
        case "": return "Sent to the session"
        default: return "Sent to the session via \(via)"
        }
    }

    /// The line under a started task (`teyla dispatch`).
    static func startedLine(via: String, worktree: String) -> String {
        let how = via == "fixture" ? "Started (preview only, nothing was started)"
            : via == "sample" ? "Sample: nothing was sent" : "Started"
        return worktree.isEmpty ? how : "\(how) in \(worktree)"
    }

    /// The line under a delivered answer.
    static func sentLine(via: String) -> String {
        switch via {
        case "opened": return "Copied to the clipboard and opened the session"
        case "fixture": return "Sent (preview only, nothing was delivered)"
        case "sample": return "Sample: nothing was sent"
        case "": return "Sent to the session"
        default: return "Sent to the session via \(via)"
        }
    }
}

/// A session link is either a URL (`claude://…`, `codex://…`) or, for Claude Code sessions, a
/// shell command such as `claude --resume <id>` that has to be pasted into a terminal.
enum SessionLink: Equatable {
    case url(URL)
    case command(String)
    case none

    init(_ link: String) {
        let text = link.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty {
            self = .none
        } else if text.range(of: #"^[A-Za-z][A-Za-z0-9+.\-]*://\S+$"#, options: .regularExpression) != nil,
                  let url = URL(string: text) {
            self = .url(url)
        } else {
            self = .command(text)
        }
    }
}

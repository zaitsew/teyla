import Foundation

/// Small text helpers, kept free of UI so they can be tested.
enum Format {
    /// "cellar" becomes "Cellar"; names that already have capitals are left alone.
    static func product(_ name: String) -> String {
        guard let first = name.first, first.isLowercase else { return name }
        return first.uppercased() + name.dropFirst()
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

    /// "3 questions · 2 sessions running · $4.10 spent today"; spend is left out when unknown.
    static func subline(questions: Int, running: Int, spentUSD: Double?) -> String {
        var parts = [
            "\(questions) \(questions == 1 ? "question" : "questions")",
            "\(running) \(running == 1 ? "session" : "sessions") running",
        ]
        if let spentUSD { parts.append("\(spent(spentUSD)) spent today") }
        return parts.joined(separator: " · ")
    }

    /// The toolbar text: "Live · updated 4 s ago".
    static func updated(secondsAgo: Int) -> String {
        let s = max(0, secondsAgo)
        if s < 60 { return "Live · updated \(s) s ago" }
        return "Live · updated \(s / 60) min ago"
    }

    /// The line under a delivered answer.
    static func sentLine(via: String) -> String {
        switch via {
        case "opened": return "Copied to the clipboard and opened the session"
        case "fixture": return "Sent (preview only, nothing was delivered)"
        case "": return "Sent to the session"
        default: return "Sent to the session via \(via)"
        }
    }
}

import Foundation

// Text and filters for the Portfolio screen, kept free of UI so they can be tested.

extension Health {
    /// The word on a health pill. The pill also carries an icon, so colour is never the only signal.
    var title: String {
        switch self {
        case .offTrack: return "Off track"
        case .atRisk: return "At risk"
        case .onTrack: return "On track"
        case .parked: return "Parked"
        }
    }

    var symbol: String {
        switch self {
        case .offTrack: return "exclamationmark.octagon"
        case .atRisk: return "exclamationmark.triangle"
        case .onTrack: return "checkmark.circle"
        case .parked: return "pause.circle"
        }
    }

    /// Off track and at risk are what the owner should look at.
    var needsAttention: Bool { self == .offTrack || self == .atRisk }
}

enum PortfolioFilter: String, CaseIterable, Identifiable, Sendable {
    case all
    case needsAttention

    var id: String { rawValue }

    var title: String {
        switch self {
        case .all: return "All"
        case .needsAttention: return "Needs attention"
        }
    }

    /// Parked products are hidden unless `showParked` is on. "Needs attention" never lists a parked product.
    func apply(_ products: [PortfolioProduct], showParked: Bool) -> [PortfolioProduct] {
        switch self {
        case .all: return products.filter { showParked || $0.health != .parked }
        case .needsAttention: return products.filter { $0.health.needsAttention }
        }
    }
}

enum PortfolioText {
    /// "2 off track · 3 at risk · 14 on track"; a zero is left out, and parked is added only when there are some.
    static func summary(_ counts: HealthCounts) -> String {
        var parts: [String] = []
        if counts.offTrack > 0 { parts.append("\(counts.offTrack) off track") }
        if counts.atRisk > 0 { parts.append("\(counts.atRisk) at risk") }
        if counts.onTrack > 0 { parts.append("\(counts.onTrack) on track") }
        if counts.parked > 0 { parts.append("\(counts.parked) parked") }
        return parts.isEmpty ? "No products yet" : parts.joined(separator: " · ")
    }

    /// "Stores checked 3 h ago · GitHub 20 min ago"; "never" when a pass has not run.
    static func checked(stores: String, github: String, now: Date) -> String {
        func part(_ iso: String) -> String {
            guard let date = ISODate.parse(iso) else { return "never" }
            return Format.ago(seconds: now.timeIntervalSince(date))
        }
        return "Stores checked \(part(stores)) · GitHub \(part(github))"
    }

    static func platformName(_ id: String) -> String {
        switch id.lowercased() {
        case "ios": return "iOS"
        case "macos": return "macOS"
        case "android": return "Android"
        case "web": return "Web"
        case "watch": return "Watch"
        default: return id.prefix(1).uppercased() + id.dropFirst()
        }
    }

    static func stateWord(_ state: PlatformState) -> String {
        switch state {
        case .live: return "live"
        case .inReview: return "in review"
        case .current: return "current"
        case .behind: return "behind"
        case .blocked: return "blocked"
        case .none: return "no build"
        case .unknown: return "unchecked"
        }
    }

    /// "1.4.0 (52)", "1.4.0", "(52)" or "": the version and build of a platform row.
    static func build(_ platform: PlatformStatus) -> String {
        switch (platform.version.isEmpty, platform.build.isEmpty) {
        case (false, false): return "\(platform.version) (\(platform.build))"
        case (false, true): return platform.version
        case (true, false): return "(\(platform.build))"
        case (true, true): return ""
        }
    }

    /// One chip on the platform strip: "iOS 1.4.0 (52) · current".
    static func chip(_ platform: PlatformStatus) -> String {
        let name = platformName(platform.platform)
        let version = build(platform)
        let head = version.isEmpty ? name : "\(name) \(version)"
        return "\(head) · \(stateWord(platform.state))"
    }

    /// SF Symbol names to try, best first; the first that exists on this macOS is used.
    static func symbols(for platform: String) -> [String] {
        switch platform.lowercased() {
        case "ios": return ["iphone"]
        case "macos": return ["macbook", "laptopcomputer"]
        case "web": return ["globe"]
        case "watch": return ["applewatch"]
        case "android": return ["smartphone", "apps.iphone"]
        default: return ["square.dashed"]
        }
    }

    /// "3 open · 14 merged 7d"; a zero count is kept for merged, left out for open. Unreviewed merges are added when there are some.
    static func prs(_ prs: PRCounts) -> String {
        var parts: [String] = []
        if prs.open > 0 { parts.append("\(prs.open) open") }
        parts.append("\(prs.merged7d) merged 7d")
        if prs.unreviewed7d > 0 { parts.append("\(prs.unreviewed7d) unreviewed") }
        return parts.joined(separator: " · ")
    }

    /// "TestFlight", "App Store", "Google Play", "Web", "Local".
    static func channelName(_ channel: String) -> String {
        switch channel {
        case "testflight": return "TestFlight"
        case "app_store": return "App Store"
        case "play": return "Google Play"
        case "web": return "Web"
        case "local": return "Local"
        default: return channel.isEmpty ? "" : channel.prefix(1).uppercased() + channel.dropFirst()
        }
    }

    /// "2 waiting · oldest 9 d" or "Nothing waiting".
    static func waiting(_ product: PortfolioProduct) -> String {
        guard product.waiting > 0 else { return "Nothing waiting" }
        let base = "\(product.waiting) waiting"
        return product.oldestWaitDays >= 1 ? "\(base) · oldest \(Int(product.oldestWaitDays)) d" : base
    }

    /// "Active 2 h ago" or "No sessions yet".
    static func lastActivity(_ activity: Activity, now: Date) -> String {
        guard let date = ISODate.parse(activity.last) else { return "No sessions yet" }
        let ago = Format.ago(seconds: now.timeIntervalSince(date))
        return ago == "just now" ? "Active just now" : "Active \(ago)"
    }

    /// "$210.50 in 7 days".
    static func spend(_ activity: Activity) -> String {
        "\(Format.spent(activity.spend7dUSD)) in 7 days"
    }
}

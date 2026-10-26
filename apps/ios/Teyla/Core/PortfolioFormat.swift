import Foundation

/// The two lists on the Portfolio tab.
enum PortfolioFilter: String, CaseIterable, Identifiable, Sendable {
    case all
    case attention

    var id: String { rawValue }
    var title: String { self == .all ? "All" : "Needs attention" }
}

/// Text and ordering for the Portfolio tab. No UI types here, so the tests can reach it.
/// The shared models are in `apps/mac/Teyla/Core/Models.swift`; this file is iPhone-only.
enum PortfolioFormat {
    // MARK: Health

    static func healthLabel(_ health: Health) -> String {
        switch health {
        case .offTrack: return "off track"
        case .atRisk: return "at risk"
        case .onTrack: return "on track"
        case .parked: return "parked"
        }
    }

    /// Health is always shown as a word and a symbol, never as a colour alone.
    static func healthSymbol(_ health: Health) -> String {
        switch health {
        case .offTrack: return "exclamationmark.octagon"
        case .atRisk: return "exclamationmark.triangle"
        case .onTrack: return "checkmark.circle"
        case .parked: return "pause.circle"
        }
    }

    /// The counts the CLI sent, or counts taken from the rows when it sent none.
    static func counts(of portfolio: Portfolio) -> HealthCounts {
        let sent = portfolio.counts
        if sent.onTrack + sent.atRisk + sent.offTrack + sent.parked > 0 { return sent }
        var counts = HealthCounts()
        for product in portfolio.products {
            switch product.health {
            case .offTrack: counts.offTrack += 1
            case .atRisk: counts.atRisk += 1
            case .onTrack: counts.onTrack += 1
            case .parked: counts.parked += 1
            }
        }
        return counts
    }

    /// "2 off track · 3 at risk · 14 on track". A part with no products is left out.
    static func headline(for portfolio: Portfolio) -> String {
        let counts = counts(of: portfolio)
        let parts = [(counts.offTrack, "off track"), (counts.atRisk, "at risk"),
                     (counts.onTrack, "on track"), (counts.parked, "parked")]
            .filter { $0.0 > 0 }
            .map { "\($0.0) \($0.1)" }
        return parts.isEmpty ? "No products are registered yet" : parts.joined(separator: " \u{00B7} ")
    }

    /// Off track and at risk. The CLI sends the list worst first, and this keeps that order.
    static func needsAttention(_ product: PortfolioProduct) -> Bool {
        product.health == .offTrack || product.health == .atRisk
    }

    static func visible(_ products: [PortfolioProduct], filter: PortfolioFilter) -> [PortfolioProduct] {
        filter == .all ? products : products.filter(needsAttention)
    }

    // MARK: Products

    static func title(_ product: PortfolioProduct) -> String {
        product.title.isEmpty ? Format.product(product.id) : product.title
    }

    /// "Beta", or "Beta \u{00B7} testers".
    static func stageLine(_ product: PortfolioProduct) -> String {
        var parts: [String] = []
        if !product.stage.isEmpty { parts.append(product.stage.prefix(1).uppercased() + product.stage.dropFirst()) }
        if !product.users.isEmpty { parts.append(product.users) }
        return parts.joined(separator: " \u{00B7} ")
    }

    static func waitingLine(_ count: Int) -> String { "\(count) waiting" }

    // MARK: Platforms

    static func platformName(_ platform: String) -> String {
        switch platform {
        case "ios": return "iOS"
        case "macos": return "macOS"
        case "android": return "Android"
        case "web": return "Web"
        case "watch": return "Watch"
        default: return platform.isEmpty ? "Other" : platform.prefix(1).uppercased() + platform.dropFirst()
        }
    }

    static func platformSymbol(_ platform: String) -> String {
        switch platform {
        case "ios": return "iphone"
        case "macos": return "desktopcomputer"
        case "android": return "smartphone"
        case "web": return "globe"
        case "watch": return "applewatch"
        default: return "square.stack.3d.up"
        }
    }

    static func stateLabel(_ state: PlatformState) -> String {
        switch state {
        case .live: return "live"
        case .inReview: return "in review"
        case .current: return "current"
        case .behind: return "behind"
        case .blocked: return "blocked"
        case .none: return "no build yet"
        case .unknown: return "not checked"
        }
    }

    /// "iOS 1.4.0 (52) \u{00B7} current".
    static func platformLine(_ platform: PlatformStatus) -> String {
        var name = platformName(platform.platform)
        if !platform.version.isEmpty { name += " \(platform.version)" }
        if !platform.build.isEmpty { name += " (\(platform.build))" }
        return "\(name) \u{00B7} \(stateLabel(platform.state))"
    }

    /// "checked 3h ago" for a row that was read from a store or a site; nil for a local row.
    static func checkedAgo(_ iso: String, now: Date) -> String? {
        guard !iso.isEmpty else { return nil }
        guard let seconds = PhoneFormat.secondsSince(iso, now: now) else { return nil }
        return "checked \(PhoneFormat.ago(seconds))"
    }

    /// "Stores checked 3h ago \u{00B7} GitHub checked 12 min ago"; "never" when the pass has not run.
    static func checkedLine(_ portfolio: Portfolio, now: Date) -> String {
        func part(_ name: String, _ iso: String) -> String {
            guard let seconds = PhoneFormat.secondsSince(iso, now: now) else { return "\(name) not checked yet" }
            return "\(name) checked \(PhoneFormat.ago(seconds))"
        }
        return [part("Stores", portfolio.checkedStores), part("GitHub", portfolio.checkedGitHub)]
            .joined(separator: " \u{00B7} ")
    }

    // MARK: Detail

    static func spendLine(_ activity: Activity) -> String {
        "\(Format.spent(activity.spend7dUSD)) at API prices in 7 days"
    }

    static func sessionsLine(_ activity: Activity, now: Date) -> String {
        let sessions = "\(activity.sessions7d) \(activity.sessions7d == 1 ? "session" : "sessions") in 7 days"
        guard let seconds = PhoneFormat.secondsSince(activity.last, now: now) else { return sessions }
        return "Last session \(PhoneFormat.ago(seconds)) \u{00B7} \(sessions)"
    }

    /// The open questions of one product, in the order the Mac ranked them.
    static func questions(for product: PortfolioProduct, in asks: [Ask]) -> [Ask] {
        asks.filter { $0.product == product.id }
    }
}

/// What the screenshot script and the tests can set on launch (environment or `-KEY value`).
struct LaunchOptions: Equatable, Sendable {
    var tab: String?
    var openProduct: String?
    /// Opens the "Older" fold on Today.
    var olderOpen: Bool

    init(environment: [String: String] = ProcessInfo.processInfo.environment,
         defaults: UserDefaults = .standard) {
        func read(_ key: String) -> String? {
            let value = environment[key] ?? defaults.string(forKey: key)
            return value.flatMap { $0.isEmpty ? nil : $0 }
        }
        tab = read("TEYLA_TAB")
        openProduct = read("TEYLA_OPEN")
        olderOpen = read("TEYLA_OLDER") == "open"
    }
}

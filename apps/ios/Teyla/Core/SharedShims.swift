import Foundation

// `HomeLogic.swift` is shared with the Mac app. It takes three small helpers from Mac-only files
// (`PortfolioLogic.swift`, `ProductPage.swift`); these are their phone twins, with the same wording.

enum PortfolioText {
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

    /// "1.4.0 (52)", "1.4.0", "(52)" or "".
    static func build(_ platform: PlatformStatus) -> String {
        switch (platform.version.isEmpty, platform.build.isEmpty) {
        case (false, false): return "\(platform.version) (\(platform.build))"
        case (false, true): return platform.version
        case (true, false): return "(\(platform.build))"
        case (true, true): return ""
        }
    }
}

enum ProductCommands {
    /// An id that does not start with "-" and holds no space.
    static func isProductID(_ id: String) -> Bool {
        guard let first = id.first, first != "-" else { return false }
        return id.allSatisfy { !$0.isWhitespace }
    }
}

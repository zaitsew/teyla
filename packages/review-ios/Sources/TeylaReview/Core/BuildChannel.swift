import Foundation

/// How this build reached the phone. The overlay never opens in an App Store build, even when
/// the TEYLA_REVIEW flag leaked into one.
public enum BuildChannel: String, Codable, Sendable {
    case debug
    case testflight
    case local          // a development or ad hoc install: no receipt
    case appStore

    static func detect(isDebug: Bool, receiptName: String?, receiptExists: Bool) -> BuildChannel {
        if isDebug { return .debug }
        if receiptName == "sandboxReceipt" { return .testflight }
        return receiptExists ? .appStore : .local
    }

    static var current: BuildChannel {
        #if DEBUG
        let debug = true
        #else
        let debug = false
        #endif
        let url = Bundle.main.appStoreReceiptURL
        let exists = url.map { FileManager.default.fileExists(atPath: $0.path) } ?? false
        return detect(isDebug: debug, receiptName: url?.lastPathComponent, receiptExists: exists)
    }
}

enum AppProbe {
    /// The product's identity. `TeylaCommit` is an optional Info.plist key a build phase fills with
    /// `git rev-parse --short HEAD`; without it the capture has no commit.
    static func current(bundle: Bundle = .main, channel: BuildChannel = .current) -> AppInfo {
        let info = bundle.infoDictionary ?? [:]
        let commit = (info["TeylaCommit"] as? String).flatMap { Self.isCommit($0) ? $0 : nil }
        return AppInfo(
            bundleId: bundle.bundleIdentifier ?? "unknown",
            name: (info["CFBundleDisplayName"] as? String) ?? (info["CFBundleName"] as? String),
            version: (info["CFBundleShortVersionString"] as? String) ?? "0",
            build: (info["CFBundleVersion"] as? String) ?? "0",
            commit: commit, configuration: channel)
    }

    static func isCommit(_ text: String) -> Bool {
        (7...40).contains(text.count) && text.utf8.allSatisfy { ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102) }
    }

    /// The `device` field is signed in the relay's scheme: letters, digits, space, dot, underscore,
    /// hyphen, at most 64. It is the device class, never the name the owner gave the phone.
    static func sanitizeDevice(_ text: String) -> String {
        let allowed = Set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 ._-")
        let cleaned = String(text.filter { allowed.contains($0) }.prefix(64))
        return cleaned.isEmpty ? "device" : cleaned
    }
}

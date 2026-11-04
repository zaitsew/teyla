import Foundation
#if os(macOS)
import StoreKit
#endif

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

    /// The environment StoreKit's `AppTransaction` reports. Only the Mac path reads it.
    enum StoreEnvironment: Equatable, Sendable {
        case xcode, sandbox, production
    }

    /// The Mac decision. On macOS the App Store receipt file is named `receipt` in TestFlight too, as
    /// far as we know, so the file name cannot tell the two apart; `AppTransaction.environment` can.
    /// Until StoreKit has answered, and when it fails, `environment` is nil and the channel reads as
    /// the App Store: the overlay stays closed (fail closed).
    static func detectMac(isDebug: Bool, environment: StoreEnvironment?) -> BuildChannel {
        if isDebug { return .debug }
        switch environment {
        case .xcode: return .local
        case .sandbox: return .testflight
        case .production, nil: return .appStore
        }
    }

    static var current: BuildChannel {
        #if DEBUG
        let debug = true
        #else
        let debug = false
        #endif
        #if os(macOS)
        return detectMac(isDebug: debug, environment: MacStoreEnvironment.cached)
        #else
        let url = Bundle.main.appStoreReceiptURL
        let exists = url.map { FileManager.default.fileExists(atPath: $0.path) } ?? false
        return detect(isDebug: debug, receiptName: url?.lastPathComponent, receiptExists: exists)
        #endif
    }
}

#if os(macOS)
/// The answer of `AppTransaction.shared`, asked once at `TeylaReview.configure` and cached. NOT yet
/// verified on a real Mac TestFlight build (docs/REVIEW.md).
enum MacStoreEnvironment {
    private static let lock = NSLock()
    private static var value: BuildChannel.StoreEnvironment?
    private static var started = false

    static var cached: BuildChannel.StoreEnvironment? {
        lock.lock(); defer { lock.unlock() }
        return value
    }

    static func set(_ environment: BuildChannel.StoreEnvironment?) {
        lock.lock(); defer { lock.unlock() }
        value = environment
    }

    /// Starts the asynchronous refresh the first time it is called. A failure leaves the cache empty.
    static func refreshOnce() {
        lock.lock()
        let first = !started
        started = true
        lock.unlock()
        guard first else { return }
        Task.detached(priority: .utility) {
            set(await fetch())
        }
    }

    static func fetch() async -> BuildChannel.StoreEnvironment? {
        guard let result = try? await AppTransaction.shared else { return nil }
        guard case .verified(let transaction) = result else { return nil }
        return map(transaction.environment)
    }

    static func map(_ environment: AppStore.Environment) -> BuildChannel.StoreEnvironment? {
        if environment == .production { return .production }
        if environment == .sandbox { return .sandbox }
        if environment == .xcode { return .xcode }
        return nil
    }
}
#endif

enum AppProbe {
    /// The product's identity. `TeylaCommit` is an optional Info.plist key a build phase fills with
    /// `git rev-parse --short HEAD`; without it the capture has no commit.
    static func current(
        bundle: Bundle = .main, channel: BuildChannel = .current, configuredProduct: String? = TeylaReview.configuration.product
    ) -> AppInfo {
        let info = bundle.infoDictionary ?? [:]
        let commit = (info["TeylaCommit"] as? String).flatMap { Self.isCommit($0) ? $0 : nil }
        return AppInfo(
            bundleId: bundle.bundleIdentifier ?? "unknown",
            name: (info["CFBundleDisplayName"] as? String) ?? (info["CFBundleName"] as? String),
            version: (info["CFBundleShortVersionString"] as? String) ?? "0",
            build: (info["CFBundleVersion"] as? String) ?? "0",
            commit: commit, product: product(configured: configuredProduct, plist: info[ChannelConfig.productInfoKey]),
            configuration: channel)
    }

    /// The slug `app.product` carries: the configuration value, else the Info.plist key
    /// `TeylaReviewProduct`. Anything that is not a slug (`^[a-z][a-z0-9-]{0,39}$`) is left out.
    static func product(configured: String?, plist: Any?) -> String? {
        for candidate in [configured, ChannelConfig.text(plist)] {
            if let candidate, isSlug(candidate) { return candidate }
        }
        return nil
    }

    static func isSlug(_ text: String) -> Bool {
        guard (1...40).contains(text.utf8.count), let first = text.utf8.first, first >= 97, first <= 122 else { return false }
        return text.utf8.allSatisfy { ($0 >= 97 && $0 <= 122) || ($0 >= 48 && $0 <= 57) || $0 == 45 }
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

import Foundation

/// The first-send notice and the checks that sit before Send. No UIKit, so the tests run on the Mac.
enum ReviewNotice {
    static let acceptedKey = "teyla.review.noticeAccepted"

    /// True once the tester pressed OK on the notice, on this install.
    static func isAccepted(defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: acceptedKey)
    }

    static func accept(defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: acceptedKey)
    }

    /// The notice appears before a send that can leave the device, until the tester has accepted it once.
    static func isNeeded(sendsToServer: Bool, defaults: UserDefaults = .standard) -> Bool {
        sendsToServer && !isAccepted(defaults: defaults)
    }

    /// Whether Send is enabled: a comment, no save under way, and the health checkbox ticked when
    /// the product requires it.
    static func canSend(comment: String, sending: Bool, requiresHealthConsent: Bool, healthConsentGiven: Bool) -> Bool {
        !sending && !comment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && (!requiresHealthConsent || healthConsentGiven)
    }
}

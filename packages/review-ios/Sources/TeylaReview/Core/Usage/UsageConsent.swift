import Foundation

/// Who may send usage events. The owner's device (paired with the owner's Mac) sends on its own. Any other
/// tester sends only after pressing Allow on the one-time notice. "Not now" is final: nothing is recorded
/// or sent, and the answer is never overridden by pairing or by a later build.
enum UsageConsent {
    enum State: String { case unset, allowed, declined }

    static let key = "teyla.usage.consent"

    static func state(defaults: UserDefaults = .standard) -> State {
        defaults.string(forKey: key).flatMap(State.init(rawValue:)) ?? .unset
    }

    static func set(_ state: State, defaults: UserDefaults = .standard) {
        defaults.set(state.rawValue, forKey: key)
    }

    /// Events are kept on the device until the tester answers; a declined answer keeps none.
    static func mayRecord(state: State) -> Bool { state != .declined }

    static func maySend(isOwnerDevice: Bool, state: State) -> Bool {
        state != .declined && (isOwnerDevice || state == .allowed)
    }

    static func noticeNeeded(isOwnerDevice: Bool, state: State) -> Bool {
        !isOwnerDevice && state == .unset
    }
}

enum UsageInstall {
    static let key = "teyla.usage.installID"

    /// A random id made on first use and kept in the app's own defaults. It is not the vendor id, the advertising
    /// id or anything derived from the device, and it is gone when the app is deleted.
    static func id(defaults: UserDefaults = .standard) -> String {
        if let saved = defaults.string(forKey: key), UUID(uuidString: saved) != nil { return saved }
        let made = UUID().uuidString.lowercased()
        defaults.set(made, forKey: key)
        return made
    }
}

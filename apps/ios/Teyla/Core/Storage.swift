import Foundation
import Security

/// Where the shared relay key lives. The Keychain on the phone; a stub in tests.
protocol KeyStore: Sendable {
    func load() -> Data?
    func save(_ key: Data) throws
    func delete()
}

struct KeychainError: Error, LocalizedError {
    let status: OSStatus
    var errorDescription: String? { "The Keychain refused the key (error \(status))." }
}

/// The 32-byte relay key as a generic password, readable after the first unlock and never
/// copied to another device or a backup.
struct KeychainKeyStore: KeyStore {
    var service = "com.zaitsew.teyla.relay"
    var account = "relay-key"

    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    func load() -> Data? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess else { return nil }
        return out as? Data
    }

    func save(_ key: Data) throws {
        delete()
        var q = query
        q[kSecValueData as String] = key
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(q as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError(status: status) }
    }

    func delete() {
        SecItemDelete(query as CFDictionary)
    }
}

/// One thing the owner sent from the phone, kept until its result has been shown.
struct PendingAction: Codable, Identifiable, Equatable, Sendable {
    struct Outcome: Codable, Equatable, Sendable {
        var ok: Bool
        var via: String
        var detail: String
    }

    /// The outbox entry id.
    var id: String
    var kind: OutboxKind
    /// The question id, running-session reference or product the action is about.
    var target: String
    /// A short name for lists: the product, or the session title.
    var label: String
    var text: String
    var created: Date
    /// nil until the Mac has written `sent/<id>.json`.
    var outcome: Outcome?

    var isWaiting: Bool { outcome == nil }
}

protocol PendingStore: Sendable {
    func load() -> [PendingAction]
    func save(_ actions: [PendingAction])
}

struct DefaultsPendingStore: PendingStore, @unchecked Sendable {
    var defaults: UserDefaults = .standard
    var key = "pendingActions"

    func load() -> [PendingAction] {
        guard let data = defaults.data(forKey: key) else { return [] }
        return (try? JSONDecoder().decode([PendingAction].self, from: data)) ?? []
    }

    func save(_ actions: [PendingAction]) {
        defaults.set(try? JSONEncoder().encode(actions), forKey: key)
    }
}

/// Fixture mode and tests: nothing is written anywhere.
final class MemoryPendingStore: PendingStore, @unchecked Sendable {
    private var items: [PendingAction] = []
    func load() -> [PendingAction] { items }
    func save(_ actions: [PendingAction]) { items = actions }
}

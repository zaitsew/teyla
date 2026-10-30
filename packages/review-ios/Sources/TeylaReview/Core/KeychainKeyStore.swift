import Foundation
import Security

/// The relay key in the Keychain, readable after the first unlock and never synced off the device.
/// A product pairs once: `TeylaReview.pair(...)` with the string `teyla relay pair` prints.
final class KeychainKeyStore: RelayKeyStoring {
    private let service: String
    private let account = "relay-key"

    init(service: String = "teyla.review") { self.service = service }

    private var base: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: account]
    }

    func load() -> RelayKey? {
        var query = base
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &out) == errSecSuccess, let data = out as? Data else { return nil }
        return RelayKey(bytes: data)
    }

    func save(_ key: RelayKey) -> Bool {
        delete()
        var item = base
        item[kSecValueData as String] = key.bytes
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(item as CFDictionary, nil) == errSecSuccess
    }

    func delete() { SecItemDelete(base as CFDictionary) }
}

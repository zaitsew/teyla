import Foundation
import Security

/// The relay key in the login keychain. The sandbox lets the app keep its own items there without an entitlement.
/// `kSecAttrAccessible` is left out: it belongs to the iOS and data-protection keychains, not to this one.
struct MacKeyStore: KeyStore {
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
        let status = SecItemAdd(q as CFDictionary, nil)
        guard status == errSecSuccess else { throw KeychainError(status: status) }
    }

    func delete() {
        SecItemDelete(query as CFDictionary)
    }
}

/// The folder the owner chose with the open panel, kept as an app-scope security-scoped bookmark so the
/// sandbox grants access again at the next launch.
enum StoreFolder {
    static let defaultsKey = "relayFolderBookmark.scoped"

    static func save(_ url: URL, defaults: UserDefaults = .standard) throws {
        let data = try url.bookmarkData(options: .withSecurityScope, includingResourceValuesForKeys: nil, relativeTo: nil)
        defaults.set(data, forKey: defaultsKey)
    }

    /// The saved folder. The caller opens its security scope. A stale bookmark is renewed.
    static func resolve(defaults: UserDefaults = .standard) -> URL? {
        guard let data = defaults.data(forKey: defaultsKey) else { return nil }
        var stale = false
        guard let url = try? URL(resolvingBookmarkData: data, options: .withSecurityScope, relativeTo: nil,
                                 bookmarkDataIsStale: &stale) else { return nil }
        if stale {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            try? save(url, defaults: defaults)
        }
        return url
    }

    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: defaultsKey)
    }
}

/// Calls `handler` (after a short pause) when something in the folder changes: the Mac wrote `state.teyla`
/// or a `sent/` entry. iCloud replaces files by renaming, which is a write to the folder itself.
final class FolderWatcher: @unchecked Sendable {
    private var source: DispatchSourceFileSystemObject?
    private let queue = DispatchQueue(label: "com.zaitsew.teyla.relay-folder")
    private var pending: DispatchWorkItem?

    init?(folder: URL, handler: @escaping @Sendable () -> Void) {
        let fd = open(folder.path, O_EVTONLY)
        guard fd >= 0 else { return nil }
        let source = DispatchSource.makeFileSystemObjectSource(fileDescriptor: fd, eventMask: [.write, .rename, .extend],
                                                               queue: queue)
        source.setEventHandler { [weak self] in
            guard let self else { return }
            self.pending?.cancel()
            let work = DispatchWorkItem(block: handler)
            self.pending = work
            self.queue.asyncAfter(deadline: .now() + 0.4, execute: work)
        }
        source.setCancelHandler { close(fd) }
        self.source = source
        source.resume()
    }

    func stop() {
        pending?.cancel()
        source?.cancel()
        source = nil
    }

    deinit { stop() }
}

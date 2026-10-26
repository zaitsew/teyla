import Foundation
import Observation

/// What the store build is connected to: nothing yet (the setup screen), the bundled sample, or the Mac's
/// relay folder. It keeps the folder (a security-scoped bookmark) and the pairing key (Keychain), and tells
/// the `StoreBackend` which source to read. The window reads `mode` to decide what to draw.
@MainActor
@Observable
final class StoreSession {
    enum Mode: Equatable {
        case setup
        case sample
        case connected
    }

    private(set) var mode: Mode = .setup
    private(set) var folderName: String?
    private(set) var hasKey = false
    /// Why the last step of the setup failed.
    var notice: String?

    @ObservationIgnored let backend: StoreBackend
    /// Called after the source changed, so the window clears what it shows and reads again.
    @ObservationIgnored var changed: () -> Void = {}

    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored private let keyStore: KeyStore
    @ObservationIgnored private let bookmark: BookmarkStore
    @ObservationIgnored private var folderURL: URL?
    @ObservationIgnored private var scopedURL: URL?
    @ObservationIgnored private var key: Data?
    @ObservationIgnored private var watcher: FolderWatcher?
    @ObservationIgnored private var onFolderChange: (@Sendable () -> Void)?

    static let sampleKey = "storeSampleMode"

    init(backend: StoreBackend = StoreBackend(), defaults: UserDefaults = .standard,
         keyStore: KeyStore = MacKeyStore(), bookmark: BookmarkStore = .scoped) {
        self.backend = backend
        self.defaults = defaults
        self.keyStore = keyStore
        self.bookmark = bookmark
        key = keyStore.load()
        hasKey = key != nil
        openFolder(bookmark.resolve(defaults))
        apply(announce: false)
    }

    var hasFolder: Bool { folderURL != nil }
    var isSample: Bool { mode == .sample }

    // MARK: Setup steps

    /// The owner chose the relay folder in the open panel.
    func chooseFolder(_ url: URL) {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            try bookmark.save(url, defaults)
        } catch {
            notice = "Could not keep access to that folder: \(error.localizedDescription)"
            return
        }
        notice = nil
        openFolder(bookmark.resolve(defaults) ?? url)
        apply()
    }

    /// Returns false when the string is not a pairing string.
    @discardableResult
    func pair(with string: String) -> Bool {
        guard let newKey = RelayCrypto.parsePairing(string) else {
            notice = RelayError.badPairing.localizedDescription
            return false
        }
        do {
            try keyStore.save(newKey)
        } catch {
            notice = error.localizedDescription
            return false
        }
        notice = nil
        key = newKey
        hasKey = true
        apply()
        return true
    }

    func useSample() {
        defaults.set(true, forKey: Self.sampleKey)
        apply()
    }

    /// The banner's "Connect": leaves the sample for the setup screen (or the Mac, if one is already chosen).
    func leaveSample() {
        defaults.set(false, forKey: Self.sampleKey)
        apply()
    }

    /// Forgets the Mac: the key and the folder. The setup screen comes back.
    func forgetMac() {
        keyStore.delete()
        bookmark.clear(defaults)
        defaults.set(false, forKey: Self.sampleKey)
        openFolder(nil)
        key = nil
        hasKey = false
        notice = nil
        apply()
    }

    /// Pairs again with the same folder: the key goes, the folder stays.
    func pairAgain() {
        keyStore.delete()
        key = nil
        hasKey = false
        notice = nil
        apply()
    }

    // MARK: Watching

    /// Calls `handler` when the relay folder changes. It is set again whenever the folder changes.
    func watch(_ handler: @escaping @Sendable () -> Void) {
        onFolderChange = handler
        restartWatcher()
    }

    // MARK: Internals

    private func openFolder(_ url: URL?) {
        scopedURL?.stopAccessingSecurityScopedResource()
        scopedURL = nil
        folderURL = url
        folderName = url?.lastPathComponent
        if let url, url.startAccessingSecurityScopedResource() { scopedURL = url }
    }

    private func apply(announce: Bool = true) {
        if defaults.bool(forKey: Self.sampleKey) {
            mode = .sample
            backend.useSample()
        } else if let folderURL, let key {
            mode = .connected
            backend.useRelay(folder: folderURL, key: key)
        } else {
            mode = .setup
            backend.disconnect()
        }
        restartWatcher()
        if announce { changed() }
    }

    private func restartWatcher() {
        watcher?.stop()
        watcher = nil
        guard mode == .connected, let folderURL, let onFolderChange else { return }
        watcher = FolderWatcher(folder: folderURL, handler: onFolderChange)
    }
}

/// How the relay folder is remembered. The default is the app-scope security-scoped bookmark; tests pass a plain one.
struct BookmarkStore: Sendable {
    var save: @Sendable (URL, UserDefaults) throws -> Void
    var resolve: @Sendable (UserDefaults) -> URL?
    var clear: @Sendable (UserDefaults) -> Void

    static let scoped = BookmarkStore(
        save: { try StoreFolder.save($0, defaults: $1) },
        resolve: { StoreFolder.resolve(defaults: $0) },
        clear: { StoreFolder.clear(defaults: $0) })
}

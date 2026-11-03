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
    /// A different key that arrived by `teyla-pair:` link while one is stored. It replaces nothing until the owner
    /// confirms, because any web page can open such a link.
    private(set) var pendingKey: Data?

    @ObservationIgnored let backend: StoreBackend
    /// Called after the source changed, so the window clears what it shows and reads again.
    @ObservationIgnored var changed: () -> Void = {}
    /// Opens the folder panel. Called once a key has arrived by link and no folder is chosen yet.
    @ObservationIgnored var requestFolder: () -> Void = {}

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
    /// Whether a different key is waiting for the owner's yes.
    var hasPendingPairing: Bool { pendingKey != nil }

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
        // A folder the Mac has not written to yet is kept, with a plain notice: the Mac fills it in.
        notice = FolderPanelPlan.hasSnapshot(in: url) ? nil : FolderPanelPlan.emptyFolderNotice
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

    // MARK: Pairing by link

    /// What a `teyla-pair:` link did.
    enum LinkOutcome: Equatable {
        /// The key was stored (the first one, or a replacement the owner confirmed).
        case paired
        /// The same key as the stored one: nothing changed.
        case unchanged
        /// A different key while one is stored: waiting for the owner's yes.
        case needsConfirmation
        /// Not a pairing link.
        case rejected
        /// The stored key could not be read, so nothing changed; `notice` says so.
        case unreadable
    }

    /// The key in a `teyla-pair:v1:<key>` link, or nil for anything else.
    static func pairingKey(from url: URL) -> Data? {
        guard url.scheme?.lowercased() == "teyla-pair" else { return nil }
        var text = url.absoluteString
        while text.hasSuffix("/") { text.removeLast() }
        return RelayCrypto.parsePairing(text)
    }

    /// `teyla relay connect` opens `teyla-pair:v1:<key>` in this app. With no key yet it pairs (and leaves the sample).
    /// The same key changes nothing. A different key never replaces the stored one by itself: any web page can open
    /// this link, so it waits for the owner's yes. Once a key is stored and no folder is chosen, the folder panel opens.
    @discardableResult
    func receive(url: URL) -> LinkOutcome {
        guard let new = Self.pairingKey(from: url) else {
            notice = "That is not a Teyla pairing link."
            return .rejected
        }
        // The launch may have read the Keychain while it was unavailable: read again before calling it empty.
        if key == nil, let loaded = keyStore.load() {
            key = loaded
            hasKey = true
            apply()
        }
        guard let stored = key else {
            guard keyStore.isKnownEmpty() else {
                notice = "Teyla could not read its stored key, so it changed nothing. Unlock your Keychain and open the link again."
                return .unreadable
            }
            guard store(key: new) else { return .rejected }
            leaveSampleMode()
            apply()
            askForFolderIfMissing()
            return .paired
        }
        if stored == new {
            pendingKey = nil
            if isSample {
                leaveSampleMode()
                apply()
            }
            askForFolderIfMissing()
            return .unchanged
        }
        pendingKey = new
        return .needsConfirmation
    }

    /// The owner said yes to replacing the pairing.
    func confirmPendingPairing() {
        guard let new = pendingKey else { return }
        pendingKey = nil
        guard store(key: new) else { return }
        leaveSampleMode()
        apply()
        askForFolderIfMissing()
    }

    /// The owner said no: the stored key stays.
    func declinePendingPairing() {
        pendingKey = nil
    }

    private func store(key new: Data) -> Bool {
        do {
            try keyStore.save(new)
        } catch {
            notice = error.localizedDescription
            return false
        }
        notice = nil
        key = new
        hasKey = true
        return true
    }

    private func leaveSampleMode() {
        defaults.set(false, forKey: Self.sampleKey)
    }

    private func askForFolderIfMissing() {
        if !hasFolder { requestFolder() }
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
        pendingKey = nil
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

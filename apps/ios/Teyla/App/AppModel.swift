import Foundation
import Observation
import UIKit

/// What the screen shows about the link to the Mac.
enum Connection: Equatable {
    /// Reading for the first time.
    case reading
    /// No file, or a file that failed the signature check. Nothing from it is shown.
    case waiting
    /// The file is in iCloud and being downloaded.
    case syncing
    case live
    /// Sample data from `TEYLA_STATE_FIXTURE`; nothing is read or written.
    case fixture
}

@MainActor
@Observable
final class AppModel {
    private(set) var snapshot: Snapshot?
    private(set) var connection: Connection = .reading
    private(set) var pending: [PendingAction]
    private(set) var isRefreshing = false
    private(set) var folderName: String?
    private(set) var hasKey: Bool
    /// Set when sending fails before anything reached the folder.
    var sendError: String?
    /// The onboarding step the owner has finished (`done` screen shown once).
    private(set) var setupFinished: Bool
    /// Forces an onboarding step for screenshots (`TEYLA_ONBOARDING_STEP`); never set in normal use.
    let forcedStep: Int?

    let fixtureURL: URL?
    var isFixture: Bool { fixtureURL != nil }

    private let keyStore: KeyStore
    private let pendingStore: PendingStore
    private let defaults: UserDefaults
    private var folderURL: URL?
    private var scopedURL: URL?
    private var key: Data?
    /// `kind:target` of the sends being written now; a second tap on the same card waits for the first.
    private(set) var sending: Set<String> = []
    /// A refresh was asked for while one was running (re-pairing, a new folder): run once more.
    private var refreshAgain = false

    private static let finishedKey = "setupFinished"

    init(environment: [String: String] = ProcessInfo.processInfo.environment,
         defaults: UserDefaults = .standard,
         keyStore: KeyStore = KeychainKeyStore()) {
        self.defaults = defaults
        self.keyStore = keyStore
        let fixturePath = environment["TEYLA_STATE_FIXTURE"] ?? defaults.string(forKey: "TEYLA_STATE_FIXTURE")
        fixtureURL = fixturePath.flatMap { $0.isEmpty ? nil : URL(fileURLWithPath: $0) }
        forcedStep = (environment["TEYLA_ONBOARDING_STEP"] ?? defaults.string(forKey: "TEYLA_ONBOARDING_STEP"))
            .flatMap(Int.init)
        pendingStore = fixtureURL == nil ? DefaultsPendingStore(defaults: defaults) : MemoryPendingStore()
        pending = pendingStore.load()
        let loaded = fixtureURL == nil ? keyStore.load() : nil
        key = loaded
        hasKey = loaded != nil
        setupFinished = defaults.bool(forKey: Self.finishedKey)
        if fixtureURL == nil { openFolder(FolderBookmark.resolve(defaults: defaults)) }
    }

    // MARK: Setup

    var hasFolder: Bool { folderURL != nil }

    /// 0 folder, 1 pair, 2 done, 3 the main screen.
    var setupStep: Int {
        if let forcedStep { return min(max(forcedStep, 0), 3) }
        if isFixture { return 3 }
        if !hasFolder { return 0 }
        if !hasKey { return 1 }
        return setupFinished ? 3 : 2
    }

    func chooseFolder(_ url: URL) {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            try FolderBookmark.save(url, defaults: defaults)
        } catch {
            sendError = "Could not keep access to that folder: \(error.localizedDescription)"
            return
        }
        openFolder(FolderBookmark.resolve(defaults: defaults))
        Task { await refresh() }
    }

    /// Returns false when the string is not a pairing string.
    @discardableResult
    func pair(with string: String) -> Bool {
        guard let newKey = RelayCrypto.parsePairing(string) else { return false }
        do {
            try keyStore.save(newKey)
        } catch {
            sendError = error.localizedDescription
            return false
        }
        key = newKey
        hasKey = true
        Task { await refresh() }
        return true
    }

    func finishSetup() {
        defaults.set(true, forKey: Self.finishedKey)
        setupFinished = true
    }

    /// Forgets the Mac: the key, the folder and anything waiting to be sent.
    func forgetMac() {
        keyStore.delete()
        FolderBookmark.clear(defaults: defaults)
        defaults.set(false, forKey: Self.finishedKey)
        scopedURL?.stopAccessingSecurityScopedResource()
        scopedURL = nil
        folderURL = nil
        folderName = nil
        key = nil
        hasKey = false
        setupFinished = false
        snapshot = nil
        connection = .reading
        setPending([])
    }

    func restartPairing() {
        keyStore.delete()
        key = nil
        hasKey = false
        setupFinished = false
        snapshot = nil
        connection = .reading
    }

    private func openFolder(_ url: URL?) {
        scopedURL?.stopAccessingSecurityScopedResource()
        scopedURL = nil
        folderURL = url
        folderName = url?.lastPathComponent
        if let url, url.startAccessingSecurityScopedResource() { scopedURL = url }
    }

    // MARK: Reading

    func refresh() async {
        guard !isRefreshing else {
            refreshAgain = true
            return
        }
        isRefreshing = true
        defer { isRefreshing = false }
        repeat {
            refreshAgain = false
            await refreshOnce()
        } while refreshAgain
    }

    private func refreshOnce() async {
        if let fixtureURL {
            loadFixture(fixtureURL)
            return
        }
        guard let folderURL, let key else { return }
        let store = RelayStore(folder: folderURL)
        let read = await Task.detached(priority: .utility) { store.readState() }.value
        // The folder or the key changed while the file was being read (a new pairing): this read was
        // verified against the old key, so it is dropped, not shown. The refresh that pairing asked for runs next.
        guard self.folderURL == folderURL, self.key == key else { return }
        switch read {
        case .missing, .failed:
            snapshot = nil
            connection = .waiting
        case .downloading:
            connection = .syncing
        case .data(let file):
            switch RelayCrypto.verifyStateFile(file, key: key) {
            case .valid(let json):
                if let decoded = try? PhoneFormat.decodeSnapshot(json) {
                    snapshot = decoded
                    connection = .live
                } else {
                    snapshot = nil
                    connection = .waiting
                }
            case .malformed, .badSignature:
                // Nothing from an unsigned or wrongly signed file reaches the screen.
                snapshot = nil
                connection = .waiting
            }
        }
        await collectSent(store)
        prune()
    }

    private func loadFixture(_ url: URL) {
        guard let data = try? Data(contentsOf: url), let decoded = try? PhoneFormat.decodeSnapshot(data) else {
            snapshot = nil
            connection = .waiting
            return
        }
        snapshot = decoded
        connection = .fixture
    }

    // MARK: Sending

    func action(for kind: OutboxKind, target: String) -> PendingAction? {
        pending.last { $0.kind == kind && $0.target == target }
    }

    func isSending(_ kind: OutboxKind, target: String) -> Bool {
        sending.contains("\(kind.rawValue):\(target)")
    }

    /// Sent from this phone and no longer on a card: new tasks, and answers or corrections whose question or
    /// session the Mac has since dropped. Their result stays visible until it is dismissed.
    func sentWithoutCard(in snapshot: Snapshot) -> [PendingAction] {
        pending.filter { action in
            switch action.kind {
            case .dispatch: return true
            case .answer: return !snapshot.asks.contains { $0.id == action.target }
            case .say: return !snapshot.running.contains { $0.ref == action.target }
            }
        }
    }

    /// Builds, signs and writes one outbox entry. Returns true when it was handed to the folder
    /// (or, in fixture mode, accepted), so the caller can clear its field.
    @discardableResult
    func send(kind: OutboxKind, target: String, aboutText: String, label: String, text: String) async -> Bool {
        let slot = "\(kind.rawValue):\(target)"
        guard !sending.contains(slot) else { return false }
        sending.insert(slot)
        defer { sending.remove(slot) }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let device = RelayCrypto.sanitizedDevice(UIDevice.current.name)
        if isFixture {
            guard let entry = try? OutboxEntry.make(kind: kind, target: target, aboutText: aboutText, text: trimmed,
                                                    device: device, key: Data(repeating: 0, count: 32)) else {
                sendError = "That cannot be sent."
                return false
            }
            record(entry, label: label)
            simulateReply(id: entry.id)
            return true
        }
        guard let folderURL, let key else {
            sendError = "Choose the folder and pair with your Mac first."
            return false
        }
        do {
            let entry = try OutboxEntry.make(kind: kind, target: target, aboutText: aboutText, text: trimmed,
                                             device: device, key: key)
            let store = RelayStore(folder: folderURL)
            try await Task.detached(priority: .userInitiated) { try store.writeOutbox(entry) }.value
            record(entry, label: label)
            return true
        } catch {
            sendError = error.localizedDescription
            return false
        }
    }

    private func record(_ entry: OutboxEntry, label: String) {
        var list = pending
        list.append(PendingAction(id: entry.id, kind: entry.kind, target: entry.target, label: label,
                                  text: entry.text, created: Date(), outcome: nil))
        setPending(list)
    }

    /// Fixture mode has no Mac: the reply comes back from here after a moment.
    private func simulateReply(id: String) {
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(1.2))
            self?.apply(SentResult(id: id, ok: true, via: "fixture"))
        }
    }

    private func collectSent(_ store: RelayStore) async {
        let waiting = Set(pending.filter(\.isWaiting).map(\.id))
        guard !waiting.isEmpty else { return }
        let results = await Task.detached(priority: .utility) { store.readSent(ids: waiting) }.value
        for result in results { apply(result) }
        // The result is stored on the phone first; only then is the Mac's file removed.
        await Task.detached(priority: .utility) { for result in results { store.deleteSent(id: result.id) } }.value
    }

    private func apply(_ result: SentResult) {
        var list = pending
        guard let index = list.firstIndex(where: { $0.id == result.id }) else { return }
        list[index].outcome = .init(ok: result.ok, via: result.via, detail: result.detail)
        setPending(list)
    }

    /// Removes a shown result (or a stuck entry) from the phone.
    func dismiss(_ id: String) {
        setPending(pending.filter { $0.id != id })
    }

    private func prune() {
        let now = Date()
        let kept = pending.filter { action in
            let age = now.timeIntervalSince(action.created)
            return action.isWaiting ? age < 7 * 86_400 : age < 86_400
        }
        if kept.count != pending.count { setPending(kept) }
    }

    private func setPending(_ list: [PendingAction]) {
        pending = list
        pendingStore.save(list)
    }

    // MARK: Derived

    /// Questions with the result of an answer sent from this phone kept visible.
    var asks: [Ask] { snapshot?.asks ?? [] }

    var syncDate: Date? { snapshot.flatMap(PhoneFormat.syncDate(of:)) }

    /// Products a new task can go to: a name the relay accepts as a `target`.
    var dispatchTargets: [Product] {
        (snapshot?.products ?? []).filter { OutboxEntry.isTarget($0.name) }
    }
}

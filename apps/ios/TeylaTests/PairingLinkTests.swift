import XCTest

/// The Mac's QR code is `teyla-pair:v1:<key>`; the system Camera opens it in the app as a URL.
@MainActor
final class PairingLinkTests: XCTestCase {
    private final class MemoryKeyStore: KeyStore, @unchecked Sendable {
        private let lock = NSLock()
        private var stored: Data?
        init(_ key: Data? = nil) { stored = key }
        func load() -> Data? { lock.withLock { stored } }
        func save(_ key: Data) throws { lock.withLock { stored = key } }
        func delete() { lock.withLock { stored = nil } }
    }

    /// A stored key behind a Keychain that does not answer until `available` is set.
    private final class LockedKeyStore: KeyStore, @unchecked Sendable {
        private let lock = NSLock()
        private let stored: Data
        private var _available = false
        private var _saves = 0
        init(_ key: Data) { stored = key }
        var available: Bool {
            get { lock.withLock { _available } }
            set { lock.withLock { _available = newValue } }
        }
        var saves: Int { lock.withLock { _saves } }
        func load() -> Data? { lock.withLock { _available ? stored : nil } }
        func save(_ key: Data) throws { lock.withLock { _saves += 1 } }
        func delete() {}
        func isKnownEmpty() -> Bool { false }
    }

    private let keyA = Data(0..<32)
    private let keyB = Data((0..<32).map { UInt8(255 - $0) })

    private func link(_ key: Data) -> URL {
        let body = key.base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
        return URL(string: RelayCrypto.pairingPrefix + body)!
    }

    private func model(keyStore: MemoryKeyStore) -> AppModel {
        AppModel(environment: [:], defaults: UserDefaults(suiteName: "PairingLinkTests-\(UUID().uuidString)")!,
                 keyStore: keyStore)
    }

    private func chooseFolder(_ model: AppModel) throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("teyla-pair-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        model.chooseFolder(folder)
    }

    func testTheLinkHelperBuildsAStringTheAppParses() {
        XCTAssertEqual(RelayCrypto.parsePairing(link(keyA).absoluteString), keyA)
    }

    func testALinkWithNoKeyStoredPairs() {
        let store = MemoryKeyStore()
        let model = model(keyStore: store)
        XCTAssertEqual(model.setupStep, 0)
        XCTAssertEqual(model.handlePairingLink(link(keyA)), .paired)
        XCTAssertTrue(model.hasKey)
        XCTAssertEqual(store.load(), keyA)
        XCTAssertNil(model.pendingPairing)
        XCTAssertNil(model.pairingError)
    }

    func testTheSameKeyChangesNothing() {
        let store = MemoryKeyStore(keyA)
        let model = model(keyStore: store)
        XCTAssertEqual(model.handlePairingLink(link(keyA)), .unchanged)
        XCTAssertNil(model.pendingPairing, "nothing to confirm")
        XCTAssertNil(model.pairingError)
        XCTAssertEqual(store.load(), keyA)
    }

    func testADifferentKeyNeverReplacesTheStoredOneUntilConfirmed() {
        let store = MemoryKeyStore(keyA)
        let model = model(keyStore: store)
        XCTAssertEqual(model.handlePairingLink(link(keyB)), .needsConfirmation)
        XCTAssertEqual(store.load(), keyA, "still the old key")
        XCTAssertEqual(model.pendingPairing, keyB)
        model.cancelPendingPairing()
        XCTAssertNil(model.pendingPairing)
        XCTAssertEqual(store.load(), keyA, "declined: the old key stays")

        XCTAssertEqual(model.handlePairingLink(link(keyB)), .needsConfirmation)
        model.confirmPendingPairing()
        XCTAssertEqual(store.load(), keyB, "confirmed: the new key replaces it")
        XCTAssertNil(model.pendingPairing)
        XCTAssertTrue(model.hasKey)
    }

    func testALinkThatIsNotAPairingCodeShowsTheExistingError() {
        let store = MemoryKeyStore(keyA)
        let model = model(keyStore: store)
        let bad = [
            "teyla-pair:v1:AAECAw",                       // not 32 bytes
            "teyla-pair:v2:" + link(keyB).absoluteString.dropFirst(14),
            "teyla-pair:v1:",
            "https://example.com/teyla-pair:v1:" + link(keyB).absoluteString.dropFirst(14),
            "other:v1:" + link(keyB).absoluteString.dropFirst(14),
        ]
        for string in bad {
            model.pairingError = nil
            XCTAssertEqual(model.handlePairingLink(URL(string: string)!), .invalid, string)
            XCTAssertEqual(model.pairingError, "That is not a Teyla pairing string.", string)
        }
        XCTAssertNil(model.pendingPairing)
        XCTAssertEqual(store.load(), keyA)
    }

    func testAKeyBeforeTheFolderGivesTheFolderStepThenDone() throws {
        let model = model(keyStore: MemoryKeyStore())
        XCTAssertEqual(model.setupStep, 0)
        XCTAssertEqual(model.handlePairingLink(link(keyA)), .paired)
        XCTAssertEqual(model.setupStep, 0, "paired, but the folder is still to choose")
        XCTAssertTrue(model.hasKey)
        XCTAssertFalse(model.hasFolder)
        try chooseFolder(model)
        XCTAssertEqual(model.setupStep, 2, "folder chosen: nothing left but the done screen")
        model.finishSetup()
        XCTAssertEqual(model.setupStep, 3)
    }

    func testTheFolderBeforeTheKeyStillGivesThePairStep() throws {
        let model = model(keyStore: MemoryKeyStore())
        try chooseFolder(model)
        XCTAssertEqual(model.setupStep, 1)
        XCTAssertEqual(model.handlePairingLink(link(keyA)), .paired)
        XCTAssertEqual(model.setupStep, 2)
    }

    func testALinkDoesNotReplaceAKeyThatCouldNotBeRead() {
        let store = LockedKeyStore(keyA)
        let model = AppModel(environment: [:], defaults: UserDefaults(suiteName: "PairingLinkTests-\(UUID().uuidString)")!,
                             keyStore: store)
        XCTAssertFalse(model.hasKey, "the launch could not read the key")
        XCTAssertEqual(model.handlePairingLink(link(keyB)), .unreadable)
        XCTAssertEqual(store.saves, 0)
        XCTAssertNotNil(model.pairingError)
    }

    func testALinkReadsTheKeyAgainWhenTheLaunchCouldNot() {
        let store = LockedKeyStore(keyA)
        let model = AppModel(environment: [:], defaults: UserDefaults(suiteName: "PairingLinkTests-\(UUID().uuidString)")!,
                             keyStore: store)
        store.available = true
        XCTAssertEqual(model.handlePairingLink(link(keyB)), .needsConfirmation)
        XCTAssertEqual(store.saves, 0)
        XCTAssertTrue(model.hasKey)
    }

    func testThePickerStartsInTheTeylaFolderOfICloudDrive() {
        XCTAssertEqual(FolderBookmark.suggestedFolder.lastPathComponent, "Teyla")
        XCTAssertTrue(FolderBookmark.suggestedFolder.path.hasSuffix("/com~apple~CloudDocs/Teyla"))
    }
}

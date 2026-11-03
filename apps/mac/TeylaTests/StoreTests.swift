import XCTest

// Logic of the sandboxed store build: the signed relay folder as a data source, the simulated sample,
// and the settings move from the old bundle id. tests/fixtures/relay-vector.json is the contract with the Mac.

private struct Vector: Decodable {
    struct Entry: Decodable {
        var v: Int
        var id: String
        var kind: String
        var target: String
        var about: String
        var created: String
        var device: String
        var text: String
        var sig: String
    }

    var key_hex: String
    var question: String
    var state_json: String
    var state_file: String
    var entry: Entry
    var entry_message: String
}

private func repoFile(_ path: String) throws -> Data {
    // apps/mac/TeylaTests/StoreTests.swift -> the repository root is three levels up.
    var url = URL(fileURLWithPath: #filePath)
    for _ in 0..<4 { url = url.deletingLastPathComponent() }
    return try Data(contentsOf: url.appendingPathComponent(path))
}

private func macFile(_ path: String) throws -> Data {
    var url = URL(fileURLWithPath: #filePath)
    for _ in 0..<2 { url = url.deletingLastPathComponent() }
    return try Data(contentsOf: url.appendingPathComponent(path))
}

private func loadVector() throws -> Vector {
    try JSONDecoder().decode(Vector.self, from: repoFile("tests/fixtures/relay-vector.json"))
}

private func keyData(_ hex: String) -> Data { RelayCrypto.decodeHex(Array(hex.utf8))! }

private let testKey = Data((0..<32).map { UInt8($0) })

/// A signed `state.teyla`: the signature line, a newline, then the JSON.
private func signedState(_ json: Data, key: Data = testKey) -> Data {
    let sig = RelayCrypto.hmacHex(key: key, message: Data(RelayCrypto.stateDomain.utf8) + json)
    return Data((sig + "\n").utf8) + json
}

private func sampleJSON() throws -> Data { try macFile("Teyla/Store/sample.v3.json") }

private func temporaryFolder() throws -> URL {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent("teyla-store-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    return url
}

final class StoreSnapshotTests: XCTestCase {
    func testSignedSampleDecodesAsVersion3() throws {
        let snapshot = try StoreBackend.snapshot(from: signedState(sampleJSON()), key: testKey)
        XCTAssertEqual(snapshot.version, 3)
        XCTAssertFalse(snapshot.asks.isEmpty, "Home needs questions")
        XCTAssertFalse(snapshot.running.isEmpty)
        XCTAssertFalse(snapshot.done.isEmpty)
        XCTAssertFalse(snapshot.products.isEmpty)
        XCTAssertNotNil(snapshot.portfolio, "Portfolio needs the version 3 block")
    }

    func testSignatureFromAnotherKeyShowsNothing() throws {
        let other = Data((0..<32).map { UInt8(255 - $0) })
        XCTAssertThrowsError(try StoreBackend.snapshot(from: signedState(sampleJSON(), key: other), key: testKey)) {
            XCTAssertEqual($0 as? StoreError, .untrusted)
        }
    }

    func testChangedJSONShowsNothing() throws {
        var file = try signedState(sampleJSON())
        // One byte of the JSON changes after signing.
        let index = file.index(file.endIndex, offsetBy: -3)
        file[index] = file[index] == UInt8(ascii: "x") ? UInt8(ascii: "y") : UInt8(ascii: "x")
        XCTAssertThrowsError(try StoreBackend.snapshot(from: file, key: testKey)) {
            XCTAssertEqual($0 as? StoreError, .untrusted)
        }
    }

    func testFileWithoutSignatureShowsNothing() throws {
        XCTAssertThrowsError(try StoreBackend.snapshot(from: sampleJSON(), key: testKey)) {
            XCTAssertEqual($0 as? StoreError, .untrusted)
        }
        XCTAssertThrowsError(try StoreBackend.snapshot(from: Data(), key: testKey))
    }

    func testVectorStateFileVerifies() throws {
        let v = try loadVector()
        // The vector's state is a version 2 snapshot with no asks: it still decodes, signed with the vector key.
        let snapshot = try StoreBackend.snapshot(from: Data(v.state_file.utf8), key: keyData(v.key_hex))
        XCTAssertEqual(snapshot.version, 2)
        XCTAssertTrue(snapshot.asks.isEmpty)
    }

    func testBackendReadsTheRelayFolderAndRejectsABadOne() async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let backend = StoreBackend()

        do { _ = try await backend.state(); XCTFail("no source yet") } catch {
            XCTAssertEqual(error as? StoreError, .notConnected)
        }

        backend.useRelay(folder: folder, key: testKey)
        do { _ = try await backend.state(); XCTFail("no state.teyla yet") } catch {
            XCTAssertEqual(error as? StoreError, .waiting)
        }

        try signedState(sampleJSON()).write(to: folder.appendingPathComponent("state.teyla"))
        let snapshot = try await backend.state()
        XCTAssertEqual(snapshot.version, 3)

        let other = Data((0..<32).map { UInt8(100 + $0) })
        backend.useRelay(folder: folder, key: other)
        do { _ = try await backend.state(); XCTFail("signed with another key") } catch {
            XCTAssertEqual(error as? StoreError, .untrusted)
            XCTAssertTrue((error as? StoreError)?.clearsSnapshot ?? false, "the window must drop what it showed")
        }
    }

    func testAnUntrustedFileForgetsTheCachedQuestions() async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let backend = StoreBackend()
        backend.useRelay(folder: folder, key: testKey)
        try signedState(sampleJSON()).write(to: folder.appendingPathComponent("state.teyla"))
        let first = try await backend.state().asks.first
        let ask = try XCTUnwrap(first)

        try Data("not signed".utf8).write(to: folder.appendingPathComponent("state.teyla"))
        do { _ = try await backend.state(); XCTFail("a broken file") } catch {
            XCTAssertEqual(error as? StoreError, .untrusted)
        }
        do { _ = try await backend.answer(id: ask.id, text: "Yes"); XCTFail("answered from a stale cache") } catch {
            guard case .gone = error as? StoreError else { return XCTFail("expected .gone, got \(error)") }
        }
    }
}

final class StoreSigningTests: XCTestCase {
    func testOutboxEntryMatchesTheVector() throws {
        let v = try loadVector()
        let entry = try OutboxEntry.make(
            kind: .answer, target: v.entry.target, aboutText: v.question, text: v.entry.text,
            device: v.entry.device, key: keyData(v.key_hex), id: v.entry.id, created: v.entry.created)
        XCTAssertEqual(entry.message, v.entry_message)
        XCTAssertEqual(entry.about, v.entry.about)
        XCTAssertEqual(entry.sig, v.entry.sig)
    }

    /// A real send through the backend: the entry in `outbox/` is signed, names the question, and the Mac's
    /// `sent/<id>.json` becomes the result the window shows.
    func testAnswerWritesASignedEntryAndReadsTheMacsReply() async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let backend = StoreBackend(timing: .init(poll: .milliseconds(50), reply: .seconds(5), simulated: .milliseconds(1)),
                                   deviceName: { "Test Mac" })
        backend.useRelay(folder: folder, key: testKey)
        try signedState(sampleJSON()).write(to: folder.appendingPathComponent("state.teyla"))
        let snapshot = try await backend.state()
        let ask = try XCTUnwrap(snapshot.asks.first)

        // Plays the Mac: waits for the entry, checks it, and answers.
        let mac = Task.detached { () -> OutboxEntry? in
            let outbox = folder.appendingPathComponent("outbox")
            for _ in 0..<100 {
                try await Task.sleep(for: .milliseconds(20))
                guard let name = try? FileManager.default.contentsOfDirectory(atPath: outbox.path).first(where: { $0.hasSuffix(".json") && !$0.hasPrefix(".") }),
                      let data = try? Data(contentsOf: outbox.appendingPathComponent(name)),
                      let entry = try? JSONDecoder().decode(OutboxEntry.self, from: data) else { continue }
                let sent = folder.appendingPathComponent("sent")
                try FileManager.default.createDirectory(at: sent, withIntermediateDirectories: true)
                let reply = #"{"id":"\#(entry.id)","ok":true,"via":"claude-queue","detail":"Queued","done_at":"2026-10-26T10:00:00Z"}"#
                try Data(reply.utf8).write(to: sent.appendingPathComponent("\(entry.id).json"))
                return entry
            }
            return nil
        }

        let result = try await backend.answer(id: ask.id, text: "  Ship it.  ")
        XCTAssertTrue(result.ok)
        XCTAssertEqual(result.via, "claude-queue")
        let received = try await mac.value
        let entry = try XCTUnwrap(received)
        XCTAssertEqual(entry.kind, .answer)
        XCTAssertEqual(entry.target, ask.id)
        XCTAssertEqual(entry.about, RelayCrypto.sha256Hex(ask.question))
        XCTAssertEqual(entry.text, "Ship it.", "the text is trimmed before it is signed")
        XCTAssertEqual(entry.device, "Test Mac")
        let again = try OutboxEntry.make(kind: .answer, target: ask.id, aboutText: ask.question, text: "Ship it.",
                                         device: "Test Mac", key: testKey, id: entry.id, created: entry.created)
        XCTAssertEqual(entry.sig, again.sig, "the signature is the one the Mac recomputes")
        XCTAssertFalse(FileManager.default.fileExists(atPath: folder.appendingPathComponent("sent/\(entry.id).json").path),
                       "the result is read once and its file removed")
    }

    func testMacRefusalBecomesAnError() async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let backend = StoreBackend(timing: .init(poll: .milliseconds(50), reply: .seconds(5), simulated: .milliseconds(1)))
        backend.useRelay(folder: folder, key: testKey)
        try signedState(sampleJSON()).write(to: folder.appendingPathComponent("state.teyla"))
        let snapshot = try await backend.state()
        let ask = try XCTUnwrap(snapshot.asks.first)
        let mac = Task.detached {
            let outbox = folder.appendingPathComponent("outbox")
            for _ in 0..<100 {
                try await Task.sleep(for: .milliseconds(20))
                guard let name = try? FileManager.default.contentsOfDirectory(atPath: outbox.path).first(where: { $0.hasSuffix(".json") && !$0.hasPrefix(".") }),
                      let entry = try? JSONDecoder().decode(OutboxEntry.self, from: Data(contentsOf: outbox.appendingPathComponent(name))) else { continue }
                let sent = folder.appendingPathComponent("sent")
                try FileManager.default.createDirectory(at: sent, withIntermediateDirectories: true)
                let reply = #"{"id":"\#(entry.id)","ok":false,"via":"","detail":"The question has changed","done_at":"2026-10-26T10:00:00Z"}"#
                try Data(reply.utf8).write(to: sent.appendingPathComponent("\(entry.id).json"))
                return
            }
        }
        do { _ = try await backend.answer(id: ask.id, text: "Yes"); XCTFail("the Mac said no") } catch {
            XCTAssertTrue("\(error.localizedDescription)".contains("The question has changed"))
        }
        _ = try await mac.value
    }

    func testNoReplyIsReportedNotAssumed() async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let backend = StoreBackend(timing: .init(poll: .milliseconds(20), reply: .milliseconds(150), simulated: .milliseconds(1)))
        backend.useRelay(folder: folder, key: testKey)
        try signedState(sampleJSON()).write(to: folder.appendingPathComponent("state.teyla"))
        let loaded = try await backend.state()
        let ask = try XCTUnwrap(loaded.asks.first)
        do { _ = try await backend.answer(id: ask.id, text: "Yes"); XCTFail("nobody answered") } catch {
            XCTAssertEqual(error as? StoreError, .noReply)
        }
    }
}

final class StoreSampleTests: XCTestCase {
    private func sampleBackend() throws -> StoreBackend {
        let data = try sampleJSON()
        let backend = StoreBackend(timing: .init(poll: .milliseconds(10), reply: .seconds(1), simulated: .milliseconds(1)),
                                   sampleData: { data })
        backend.useSample()
        return backend
    }

    func testSampleSendsAreSimulatedAndWriteNothing() async throws {
        let backend = try sampleBackend()
        XCTAssertTrue(backend.usesFixture)
        let snapshot = try await backend.state()
        let ask = try XCTUnwrap(snapshot.asks.first)

        let answered = try await backend.answer(id: ask.id, text: "Yes")
        XCTAssertTrue(answered.ok)
        XCTAssertEqual(answered.via, "sample")
        XCTAssertEqual(answered.detail, "Sample: nothing was sent")

        let said = try await backend.say(ref: "anything", text: "Use the second option")
        XCTAssertEqual(said.via, "sample")
        let started = try await backend.dispatch(product: "lens", harness: .claude, text: "Add a dark mode")
        XCTAssertEqual(started.via, "sample")
    }

    func testSampleLinesSayNothingWasSent() {
        XCTAssertEqual(Format.sentLine(via: "sample"), "Sample: nothing was sent")
        XCTAssertEqual(Format.startedLine(via: "sample", worktree: ""), "Sample: nothing was sent")
    }

    func testEveryScreenHasContent() async throws {
        let snapshot = try await sampleBackend().state()
        XCTAssertGreaterThanOrEqual(snapshot.asks.count, 3)
        XCTAssertFalse(snapshot.running.isEmpty)
        XCTAssertFalse(snapshot.done.isEmpty)
        let portfolio = try XCTUnwrap(snapshot.portfolio)
        XCTAssertFalse(portfolio.products.isEmpty)
        // A product page can be built for each product the sidebar lists.
        for product in snapshot.products {
            let page = StoreBackend.page(for: product.name, in: snapshot, quick: false)
            XCTAssertEqual(page.product.id, product.name)
            XCTAssertFalse(page.product.name.isEmpty)
        }
        XCTAssertTrue(snapshot.products.contains { !(StoreBackend.page(for: $0.name, in: snapshot, quick: false).sessions ?? []).isEmpty })
        XCTAssertTrue(snapshot.products.contains { !StoreBackend.page(for: $0.name, in: snapshot, quick: false).asks.isEmpty })
    }

    func testDisconnectedBackendSendsNothing() async {
        let backend = StoreBackend()
        do { _ = try await backend.answer(id: "x", text: "y"); XCTFail("not connected") } catch {
            XCTAssertNotNil(error as? StoreError)
        }
    }
}

final class StoreCapabilitiesTests: XCTestCase {
    func testStoreHidesWhatNeedsTheCommandLine() {
        let store = Capabilities.store
        XCTAssertFalse(store.notes)
        XCTAssertFalse(store.pairPhone)
        XCTAssertFalse(store.chooseHarness)
        XCTAssertFalse(store.editProducts)
        XCTAssertFalse(store.diagnosis)
        XCTAssertFalse(store.spendDetail)
        let full = Capabilities.full
        XCTAssertTrue(full.notes && full.pairPhone && full.chooseHarness && full.editProducts)
    }
}

final class DefaultsMigrationTests: XCTestCase {
    private func freshDefaults() -> UserDefaults {
        let name = "teyla-migration-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defaults.removePersistentDomain(forName: name)
        return defaults
    }

    func testCopiesTheOldSettingsOnce() {
        let defaults = freshDefaults()
        let old: [String: Any] = ["teylaBinaryPath": "/opt/bin/teyla", "selectedProduct": "lens",
                                  "voiceLocale": "es-ES", "somethingElse": 1]
        let copied = DefaultsMigration.run(into: defaults, old: old)
        XCTAssertEqual(Set(copied), ["teylaBinaryPath", "selectedProduct", "voiceLocale"])
        XCTAssertEqual(defaults.string(forKey: "teylaBinaryPath"), "/opt/bin/teyla")
        XCTAssertEqual(defaults.string(forKey: "selectedProduct"), "lens")
        XCTAssertNil(defaults.object(forKey: "somethingElse"), "only the keys the app uses are copied")
        XCTAssertNotNil(defaults.string(forKey: DefaultsMigration.doneKey))

        // A setting removed afterwards does not come back.
        defaults.removeObject(forKey: "selectedProduct")
        XCTAssertEqual(DefaultsMigration.run(into: defaults, old: old), [])
        XCTAssertNil(defaults.object(forKey: "selectedProduct"))
    }

    func testNeverOverwritesANewSetting() {
        let defaults = freshDefaults()
        defaults.set("/new/teyla", forKey: "teylaBinaryPath")
        let copied = DefaultsMigration.run(into: defaults, old: ["teylaBinaryPath": "/old/teyla", "voiceLocale": "en-US"])
        XCTAssertEqual(copied, ["voiceLocale"])
        XCTAssertEqual(defaults.string(forKey: "teylaBinaryPath"), "/new/teyla")
    }

    func testNothingToCopyStillMarksItDone() {
        let defaults = freshDefaults()
        XCTAssertEqual(DefaultsMigration.run(into: defaults, old: [:]), [])
        XCTAssertNotNil(defaults.string(forKey: DefaultsMigration.doneKey))
    }
}

@MainActor
final class StoreSessionTests: XCTestCase {
    private final class MemoryKeys: KeyStore, @unchecked Sendable {
        var key: Data?
        func load() -> Data? { key }
        func save(_ key: Data) throws { self.key = key }
        func delete() { key = nil }
    }

    /// A stored key behind a Keychain that does not answer until `available` is set.
    private final class LockedKeys: KeyStore, @unchecked Sendable {
        let stored: Data
        var available = false
        var saves = 0
        init(_ key: Data) { stored = key }
        func load() -> Data? { available ? stored : nil }
        func save(_ key: Data) throws { saves += 1 }
        func delete() {}
        func isKnownEmpty() -> Bool { false }
    }

    private final class Marks: @unchecked Sendable {
        var url: URL?
    }

    private func session(keys: KeyStore = MemoryKeys(), marks: Marks = Marks()) -> (StoreSession, UserDefaults) {
        let name = "teyla-session-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defaults.removePersistentDomain(forName: name)
        let bookmark = BookmarkStore(save: { url, _ in marks.url = url }, resolve: { _ in marks.url }, clear: { _ in marks.url = nil })
        return (StoreSession(backend: StoreBackend(), defaults: defaults, keyStore: keys, bookmark: bookmark), defaults)
    }

    func testStartsInSetupAndNeedsBothFolderAndKey() throws {
        let (session, _) = session()
        XCTAssertEqual(session.mode, .setup)
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        session.chooseFolder(folder)
        XCTAssertEqual(session.mode, .setup, "a folder alone is not a connection")
        XCTAssertFalse(session.pair(with: "not a pairing string"))
        XCTAssertNotNil(session.notice)
        XCTAssertTrue(session.pair(with: "teyla-pair:v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"))
        XCTAssertEqual(session.mode, .connected)
        XCTAssertNil(session.notice)
    }

    // MARK: Pairing by link (`teyla relay connect` opens teyla-pair:v1:<key>)

    private static let keyA = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    private static let keyB = "_-ECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
    private func link(_ key: String) -> URL { URL(string: "teyla-pair:v1:\(key)")! }

    func testLinkWithNoKeyPairsAndLeavesTheSample() throws {
        let keys = MemoryKeys()
        let (session, defaults) = session(keys: keys)
        session.useSample()
        XCTAssertEqual(session.mode, .sample)
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .paired)
        XCTAssertEqual(keys.key, RelayCrypto.parsePairing("teyla-pair:v1:" + Self.keyA))
        XCTAssertTrue(session.hasKey)
        XCTAssertFalse(defaults.bool(forKey: StoreSession.sampleKey), "the sample is left")
        XCTAssertEqual(session.mode, .setup, "a key alone is not a connection: the folder is next")
        XCTAssertFalse(session.hasPendingPairing)
    }

    func testTheSameKeyChangesNothing() throws {
        let keys = MemoryKeys()
        let (session, _) = session(keys: keys)
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        session.chooseFolder(folder)
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .paired)
        var folderAsked = 0
        session.requestFolder = { folderAsked += 1 }
        let before = keys.key
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .unchanged)
        XCTAssertEqual(keys.key, before)
        XCTAssertFalse(session.hasPendingPairing)
        XCTAssertEqual(session.mode, .connected)
        XCTAssertEqual(folderAsked, 0, "a folder is chosen: nothing to ask")
    }

    func testALinkDoesNotReplaceAKeyThatCouldNotBeRead() throws {
        let keys = LockedKeys(try XCTUnwrap(RelayCrypto.parsePairing("teyla-pair:v1:" + Self.keyA)))
        let (session, _) = session(keys: keys)
        XCTAssertFalse(session.hasKey, "the launch could not read the key")
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .unreadable)
        XCTAssertEqual(keys.saves, 0)
        XCTAssertNotNil(session.notice)
    }

    func testALinkReadsTheKeyAgainWhenTheLaunchCouldNot() throws {
        let keys = LockedKeys(try XCTUnwrap(RelayCrypto.parsePairing("teyla-pair:v1:" + Self.keyA)))
        let (session, _) = session(keys: keys)
        keys.available = true
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation)
        XCTAssertEqual(keys.saves, 0)
        XCTAssertTrue(session.hasKey)
    }

    func testASecondLinkCannotSwapTheKeyAwaitingConfirmation() throws {
        let keys = MemoryKeys()
        let (session, _) = session(keys: keys)
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .paired)
        let stored = try XCTUnwrap(keys.key)
        let keyC = "AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation)
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation, "the same link again changes nothing")
        XCTAssertEqual(session.receive(url: link(keyC)), .conflicting)
        XCTAssertTrue(session.hasPendingPairing, "the alert stays until the owner answers")
        XCTAssertNotNil(session.notice)
        session.confirmPendingPairing()
        XCTAssertEqual(keys.key, stored, "a Replace click after the swap stores nothing")
        XCTAssertFalse(session.hasPendingPairing)
        XCTAssertNotNil(session.notice, "the owner is told why nothing changed")
    }

    func testLinksInOneBatchCannotReplaceTheKeyUnderAnOpenAlert() throws {
        let keys = MemoryKeys()
        let (session, _) = session(keys: keys)
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .paired)
        let stored = try XCTUnwrap(keys.key)
        let keyC = "AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation)
        XCTAssertEqual(session.receive(url: link(keyC)), .conflicting)
        XCTAssertEqual(session.receive(url: link(keyC)), .conflicting, "the next link must not take the waiting place")
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .unchanged, "the stored key clears nothing")
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .conflicting, "the first link again does not undo the conflict")
        session.confirmPendingPairing()
        XCTAssertEqual(keys.key, stored)

        // The owner answered, so the next link asks afresh.
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation)
        session.confirmPendingPairing()
        XCTAssertEqual(keys.key, RelayCrypto.parsePairing("teyla-pair:v1:" + Self.keyB))
    }

    func testTheStoredKeyDoesNotClearAWaitingOne() throws {
        let keys = MemoryKeys()
        let (session, _) = session(keys: keys)
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .paired)
        let keyC = "AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation)
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .unchanged)
        XCTAssertTrue(session.hasPendingPairing)
        XCTAssertEqual(session.receive(url: link(keyC)), .conflicting)
        session.declinePendingPairing()
        XCTAssertFalse(session.hasPendingPairing)
        XCTAssertEqual(session.receive(url: link(keyC)), .needsConfirmation, "a no ends the conflict")
    }

    func testADifferentKeyNeverReplacesTheStoredOneUntilConfirmed() throws {
        let keys = MemoryKeys()
        let (session, _) = session(keys: keys)
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        session.chooseFolder(folder)
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .paired)
        let stored = try XCTUnwrap(keys.key)

        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation)
        XCTAssertTrue(session.hasPendingPairing)
        XCTAssertEqual(keys.key, stored, "the stored key stays until the owner says yes")
        XCTAssertEqual(session.mode, .connected)

        // No: the pending key goes, the stored one stays.
        session.declinePendingPairing()
        XCTAssertFalse(session.hasPendingPairing)
        XCTAssertEqual(keys.key, stored)

        // Yes: it replaces the key, and the folder stays chosen.
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation)
        session.confirmPendingPairing()
        XCTAssertEqual(keys.key, RelayCrypto.parsePairing("teyla-pair:v1:" + Self.keyB))
        XCTAssertFalse(session.hasPendingPairing)
        XCTAssertTrue(session.hasFolder)
        XCTAssertEqual(session.mode, .connected)
    }

    func testABadLinkIsRejectedAndChangesNothing() throws {
        let keys = MemoryKeys()
        let (session, _) = session(keys: keys)
        for text in ["https://example.com/teyla-pair:v1:" + Self.keyA,
                     "teyla-pair:v1:short",
                     "teyla-pair:v2:" + Self.keyA,
                     "teyla-pair:v1:" + Self.keyA + "AAAA",
                     "teyla-pair:v1:" + String(repeating: "!", count: 43),
                     "teyla-pair:"] {
            let url = try XCTUnwrap(URL(string: text), text)
            XCTAssertEqual(session.receive(url: url), .rejected, text)
        }
        XCTAssertNil(keys.key)
        XCTAssertFalse(session.hasKey)
        XCTAssertFalse(session.hasPendingPairing)
        XCTAssertNotNil(session.notice)
        XCTAssertNil(StoreSession.pairingKey(from: try XCTUnwrap(URL(string: "other:v1:" + Self.keyA))), "only the teyla-pair scheme")
    }

    func testTheFolderPanelIsRequestedAfterAKeyArrivesWithNoFolder() throws {
        let (session, _) = session()
        var asked = 0
        session.requestFolder = { asked += 1 }
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .paired)
        XCTAssertEqual(asked, 1, "no folder yet: the panel opens at once")

        // The same link again, with the folder still missing, asks again (a cancelled panel is not stranded).
        XCTAssertEqual(session.receive(url: link(Self.keyA)), .unchanged)
        XCTAssertEqual(asked, 2)

        // A different key, confirmed, with no folder: asked again.
        XCTAssertEqual(session.receive(url: link(Self.keyB)), .needsConfirmation)
        XCTAssertEqual(asked, 2, "nothing is asked before the owner confirms")
        session.confirmPendingPairing()
        XCTAssertEqual(asked, 3)

        // With a folder chosen, a new key asks for nothing.
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        session.chooseFolder(folder)
        let (other, _) = self.session()
        other.chooseFolder(folder)
        var otherAsked = 0
        other.requestFolder = { otherAsked += 1 }
        XCTAssertEqual(other.receive(url: link(Self.keyA)), .paired)
        XCTAssertEqual(otherAsked, 0)
        XCTAssertEqual(other.mode, .connected)
    }

    func testAPastedKeyPairsBeforeOrAfterTheFolder() throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let string = "teyla-pair:v1:" + Self.keyA

        let (keyFirst, _) = session()
        XCTAssertTrue(keyFirst.pair(with: string))
        XCTAssertEqual(keyFirst.mode, .setup)
        keyFirst.chooseFolder(folder)
        XCTAssertEqual(keyFirst.mode, .connected)

        let (folderFirst, _) = session()
        folderFirst.chooseFolder(folder)
        XCTAssertEqual(folderFirst.mode, .setup)
        XCTAssertTrue(folderFirst.pair(with: string))
        XCTAssertEqual(folderFirst.mode, .connected)
    }

    func testAChosenFolderWithoutASnapshotIsKeptWithAPlainNotice() throws {
        let (session, _) = session()
        let empty = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: empty) }
        session.chooseFolder(empty)
        XCTAssertTrue(session.hasFolder, "the folder is not refused")
        XCTAssertEqual(session.notice, FolderPanelPlan.emptyFolderNotice)
        XCTAssertTrue(FolderPanelPlan.emptyFolderNotice.contains("teyla relay connect"))

        let written = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: written) }
        try Data("x".utf8).write(to: written.appendingPathComponent("state.teyla"))
        session.chooseFolder(written)
        XCTAssertNil(session.notice, "the Mac has written here")
    }

    func testTheStoreBackendOffersTheStoredKeyToAPhone() async throws {
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        let backend = StoreBackend()
        do { _ = try await backend.relayPair(); XCTFail("not connected") } catch {
            XCTAssertEqual(error as? StoreError, .notConnected)
        }
        let key = Data((0..<32).map { UInt8(200 - $0) })
        backend.useRelay(folder: folder, key: key)
        let text = try await backend.relayPair()
        XCTAssertEqual(RelayCrypto.parsePairing(text), key)
        XCTAssertTrue(Pairing.isValid(text), "the Mac's QR check accepts it too")
    }

    func testSampleAndBackToSetup() {
        let (session, _) = session()
        session.useSample()
        XCTAssertEqual(session.mode, .sample)
        XCTAssertTrue(session.backend.usesFixture)
        session.leaveSample()
        XCTAssertEqual(session.mode, .setup)
        XCTAssertFalse(session.backend.usesFixture)
    }

    func testForgetMacClearsKeyAndFolder() throws {
        let keys = MemoryKeys()
        let (session, _) = session(keys: keys)
        let folder = try temporaryFolder()
        defer { try? FileManager.default.removeItem(at: folder) }
        session.chooseFolder(folder)
        XCTAssertTrue(session.pair(with: "teyla-pair:v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"))
        session.forgetMac()
        XCTAssertEqual(session.mode, .setup)
        XCTAssertNil(keys.key)
        XCTAssertFalse(session.hasFolder)
    }
}

final class FolderPanelPlanTests: XCTestCase {
    private let home = URL(fileURLWithPath: "/Users/someone", isDirectory: true)

    func testOpensOnTheTeylaFolderWhenItExists() {
        let teyla = FolderPanelPlan.teylaFolder(home: home)
        let plan = FolderPanelPlan.make(home: home, exists: { $0 == teyla })
        XCTAssertEqual(plan.directory, teyla)
        XCTAssertTrue(plan.directory.path.hasSuffix("com~apple~CloudDocs/Teyla"))
        XCTAssertEqual(plan.prompt, "Use this folder")
        XCTAssertTrue(plan.message.contains("only click"), plan.message)
        XCTAssertFalse(plan.canCreateDirectories)
        XCTAssertTrue(plan.opensOnTeyla)
    }

    func testOpensOnICloudDriveAndAllowsANewFolderWhenItDoesNot() {
        let plan = FolderPanelPlan.make(home: home, exists: { _ in false })
        XCTAssertEqual(plan.directory, FolderPanelPlan.iCloudDrive(home: home))
        XCTAssertTrue(plan.directory.path.hasSuffix("com~apple~CloudDocs"))
        XCTAssertTrue(plan.canCreateDirectories)
        XCTAssertFalse(plan.opensOnTeyla)
        XCTAssertTrue(plan.message.contains("named Teyla"), plan.message)
        XCTAssertTrue(plan.message.lowercased().contains("create"), plan.message)
    }
}

final class PairingEncoderTests: XCTestCase {
    func testRoundTripsEveryKeyShape() throws {
        let keys: [Data] = [
            Data((0..<32).map { UInt8($0) }),
            Data(repeating: 0, count: 32),
            Data(repeating: 255, count: 32),
            Data((0..<32).map { UInt8(($0 * 37 + 11) % 256) }),   // bytes whose base64 uses "+" and "/"
            Data((0..<32).map { UInt8(248 - $0 * 3) }),
        ]
        for key in keys {
            let text = try XCTUnwrap(RelayCrypto.pairingString(for: key))
            XCTAssertEqual(RelayCrypto.parsePairing(text), key)
            XCTAssertTrue(text.hasPrefix(RelayCrypto.pairingPrefix))
            XCTAssertEqual(text.count, RelayCrypto.pairingPrefix.count + 43, "no padding")
            XCTAssertFalse(text.contains("="))
            XCTAssertFalse(text.contains("+") || text.contains("/"), "base64url")
            XCTAssertTrue(Pairing.isValid(text), "the QR check on the Mac accepts it")
        }
    }

    func testMatchesTheStringTheMacCommandPrints() throws {
        let v = try loadVector()
        let key = keyData(v.key_hex)
        // tests/fixtures/relay-vector.json holds the string `teyla relay pair` prints for this key.
        let expected = try pairingFromVector()
        XCTAssertEqual(RelayCrypto.pairingString(for: key), expected)
        XCTAssertEqual(RelayCrypto.parsePairing(expected), key)
    }

    func testOnlyA32ByteKeyBecomesAString() {
        XCTAssertNil(RelayCrypto.pairingString(for: Data()))
        XCTAssertNil(RelayCrypto.pairingString(for: Data(repeating: 1, count: 31)))
        XCTAssertNil(RelayCrypto.pairingString(for: Data(repeating: 1, count: 33)))
    }

    private func pairingFromVector() throws -> String {
        struct Pair: Decodable { var pairing: String }
        return try JSONDecoder().decode(Pair.self, from: repoFile("tests/fixtures/relay-vector.json")).pairing
    }
}

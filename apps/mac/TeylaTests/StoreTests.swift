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
        XCTAssertFalse(snapshot.asks.isEmpty, "Today needs questions")
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

    private final class Marks: @unchecked Sendable {
        var url: URL?
    }

    private func session(keys: MemoryKeys = MemoryKeys(), marks: Marks = Marks()) -> (StoreSession, UserDefaults) {
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

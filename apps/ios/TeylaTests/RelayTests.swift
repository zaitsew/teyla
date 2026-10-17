import XCTest

/// tests/fixtures/relay-vector.json is the contract between the Mac and the phone: both reproduce it.
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
    var pairing: String
    var question: String
    var state_json: String
    var state_sig: String
    var state_file: String
    var entry: Entry
    var entry_message: String
}

private func fixtureData(_ name: String) throws -> Data {
    let here = URL(fileURLWithPath: #filePath)
    let url = here.deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("tests/fixtures/\(name)")
    return try Data(contentsOf: url)
}

private func loadVector() throws -> Vector {
    try JSONDecoder().decode(Vector.self, from: fixtureData("relay-vector.json"))
}

private func keyData(_ hex: String) -> Data { RelayCrypto.decodeHex(Array(hex.utf8))! }

final class RelayVectorTests: XCTestCase {
    func testPairingStringGivesTheKey() throws {
        let v = try loadVector()
        XCTAssertEqual(RelayCrypto.parsePairing(v.pairing), keyData(v.key_hex))
        XCTAssertEqual(RelayCrypto.parsePairing("  \(v.pairing)\n"), keyData(v.key_hex))
    }

    func testRejectsBadPairingStrings() {
        XCTAssertNil(RelayCrypto.parsePairing(""))
        XCTAssertNil(RelayCrypto.parsePairing("teyla-pair:v2:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"))
        XCTAssertNil(RelayCrypto.parsePairing("teyla-pair:v1:"))
        XCTAssertNil(RelayCrypto.parsePairing("teyla-pair:v1:AAECAw"), "a key that is not 32 bytes")
        XCTAssertNil(RelayCrypto.parsePairing("teyla-pair:v1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=!"))
    }

    func testStateSignatureMatchesTheVector() throws {
        let v = try loadVector()
        let message = Data(RelayCrypto.stateDomain.utf8) + Data(v.state_json.utf8)
        XCTAssertEqual(RelayCrypto.hmacHex(key: keyData(v.key_hex), message: message), v.state_sig)
    }

    func testAboutIsTheHashOfTheQuestion() throws {
        let v = try loadVector()
        XCTAssertEqual(RelayCrypto.sha256Hex(v.question), v.entry.about)
    }

    func testEntryMessageAndSignatureMatchTheVector() throws {
        let v = try loadVector()
        let entry = try OutboxEntry.make(
            kind: .answer, target: v.entry.target, aboutText: v.question, text: v.entry.text,
            device: v.entry.device, key: keyData(v.key_hex), id: v.entry.id, created: v.entry.created)
        XCTAssertEqual(entry.message, v.entry_message)
        XCTAssertEqual(entry.about, v.entry.about)
        XCTAssertEqual(entry.sig, v.entry.sig)
        XCTAssertEqual(entry.v, v.entry.v)
    }

    func testEntryJSONRoundTripKeepsTheSignedText() throws {
        let v = try loadVector()
        let entry = try OutboxEntry.make(
            kind: .answer, target: v.entry.target, aboutText: v.question, text: v.entry.text,
            device: v.entry.device, key: keyData(v.key_hex), id: v.entry.id, created: v.entry.created)
        let decoded = try JSONDecoder().decode(OutboxEntry.self, from: entry.jsonData())
        XCTAssertEqual(decoded, entry)
        XCTAssertEqual(decoded.message, v.entry_message)
        // The JSON on disk carries exactly the documented fields.
        let object = try JSONSerialization.jsonObject(with: entry.jsonData()) as? [String: Any]
        XCTAssertEqual(Set(object?.keys.map { $0 } ?? []),
                       ["v", "id", "kind", "target", "about", "text", "created", "device", "sig"])
    }
}

final class FieldPatternTests: XCTestCase {
    private let key = Data(repeating: 7, count: 32)

    private func make(kind: OutboxKind = .answer, target: String = "7c222b3d", about: String = "question",
                      text: String = "Yes", device: String = "iPhone",
                      id: String = "6f1c2a54-9a1e-4c3b-8d0f-2b7e1f0c9a11",
                      created: String = "2026-10-17T21:45:00Z") throws -> OutboxEntry {
        try OutboxEntry.make(kind: kind, target: target, aboutText: about, text: text, device: device,
                             key: key, id: id, created: created)
    }

    func testAcceptsAnOrdinaryEntry() throws {
        let entry = try make()
        XCTAssertEqual(entry.sig.count, 64)
    }

    func testTextMayContainNewlinesAndAnyScript() throws {
        let entry = try make(text: "line one\nline two\n\u{00BF}Vale? \u{0414}\u{0430}.")
        XCTAssertTrue(entry.message.hasSuffix("line one\nline two\n\u{00BF}Vale? \u{0414}\u{0430}."))
    }

    func testNewlineInDeviceIsRejectedBeforeSigning() {
        XCTAssertThrowsError(try make(device: "iPhone\nattacker")) {
            XCTAssertEqual($0 as? RelayError, .invalidField("device"))
        }
        XCTAssertThrowsError(try make(device: "iPhone\n")) { error in
            XCTAssertEqual(error as? RelayError, .invalidField("device"), "a trailing newline is a line break too")
        }
    }

    func testEveryOtherFieldRejectsLineBreaksAndBadValues() {
        XCTAssertThrowsError(try make(target: "7c22\n2b3d"))
        XCTAssertThrowsError(try make(target: "7c222b3d\n"))
        XCTAssertThrowsError(try make(target: "has space"))
        XCTAssertThrowsError(try make(target: ""))
        XCTAssertThrowsError(try make(target: String(repeating: "a", count: 201)))
        XCTAssertThrowsError(try make(id: "6f1c2a54-9a1e-4c3b-8d0f-2b7e1f0c9a11\n"))
        XCTAssertThrowsError(try make(id: "not-a-uuid"))
        XCTAssertThrowsError(try make(created: "2026-10-17T21:45:00Z\nx"))
        XCTAssertThrowsError(try make(created: "yesterday"))
        XCTAssertThrowsError(try make(device: ""))
        XCTAssertThrowsError(try make(device: String(repeating: "d", count: 65)))
        XCTAssertThrowsError(try make(device: "Pat's iPhone"), "an apostrophe is outside the pattern")
    }

    func testTextLimits() throws {
        XCTAssertThrowsError(try make(text: "   \n ")) { XCTAssertEqual($0 as? RelayError, .textEmpty) }
        XCTAssertThrowsError(try make(text: String(repeating: "x", count: 8001))) {
            XCTAssertEqual($0 as? RelayError, .textTooLong)
        }
        XCTAssertNoThrow(try make(text: String(repeating: "x", count: 8000)))
    }

    func testPatternHelpersAcceptTheDocumentedShapes() {
        XCTAssertTrue(OutboxEntry.isTarget("pr:example/lens#14"))
        XCTAssertTrue(OutboxEntry.isTarget("local_00000000-0000-0000-0000-000000000004"))
        XCTAssertTrue(OutboxEntry.isDevice("iPhone 15 Pro_Max.1-b"))
        XCTAssertTrue(OutboxEntry.isISOTime("2026-10-17T21:45:00Z"))
        XCTAssertTrue(OutboxEntry.isISOTime("2026-10-17T21:45:00.123+02:00"))
        XCTAssertTrue(OutboxEntry.isHex64(String(repeating: "ab", count: 32)))
        XCTAssertFalse(OutboxEntry.isHex64(String(repeating: "ab", count: 31) + "zz"))
    }

    func testDeviceNameIsCleaned() {
        XCTAssertEqual(RelayCrypto.sanitizedDevice("Pat's iPhone"), "Pat-s iPhone")
        XCTAssertEqual(RelayCrypto.sanitizedDevice(""), "iPhone")
        XCTAssertEqual(RelayCrypto.sanitizedDevice("line\nbreak"), "line-break")
        XCTAssertTrue(OutboxEntry.isDevice(RelayCrypto.sanitizedDevice(String(repeating: "\u{00E9}", count: 90))))
    }

    func testChangingAnyFieldChangesTheSignature() throws {
        let base = try make()
        XCTAssertNotEqual(try make(text: "No").sig, base.sig)
        XCTAssertNotEqual(try make(target: "7c222b3e").sig, base.sig)
        XCTAssertNotEqual(try make(about: "another question").sig, base.sig)
        XCTAssertNotEqual(try make(kind: .say).sig, base.sig)
        XCTAssertNotEqual(try make(device: "iPad").sig, base.sig)
        XCTAssertNotEqual(try make(created: "2026-10-17T21:46:00Z").sig, base.sig)
    }
}

final class StateFileTests: XCTestCase {
    func testAValidFileGivesTheSignedBytes() throws {
        let v = try loadVector()
        let verdict = RelayCrypto.verifyStateFile(Data(v.state_file.utf8), key: keyData(v.key_hex))
        XCTAssertEqual(verdict, .valid(Data(v.state_json.utf8)))
    }

    func testABadSignatureIsRefused() throws {
        let v = try loadVector()
        let key = keyData(v.key_hex)
        // One flipped character in the signature.
        var flipped = Array(v.state_file.utf8)
        flipped[0] = flipped[0] == UInt8(ascii: "0") ? UInt8(ascii: "1") : UInt8(ascii: "0")
        XCTAssertEqual(RelayCrypto.verifyStateFile(Data(flipped), key: key), .badSignature)
        // One changed byte in the snapshot.
        let tampered = v.state_file.replacingOccurrences(of: "asks", with: "aska")
        XCTAssertEqual(RelayCrypto.verifyStateFile(Data(tampered.utf8), key: key), .badSignature)
        // The right file, the wrong key.
        XCTAssertEqual(RelayCrypto.verifyStateFile(Data(v.state_file.utf8), key: Data(repeating: 1, count: 32)),
                       .badSignature)
    }

    func testAFileWithoutASignatureLineIsMalformed() throws {
        let v = try loadVector()
        let key = keyData(v.key_hex)
        XCTAssertEqual(RelayCrypto.verifyStateFile(Data(v.state_json.utf8), key: key), .malformed)
        XCTAssertEqual(RelayCrypto.verifyStateFile(Data(), key: key), .malformed)
        XCTAssertEqual(RelayCrypto.verifyStateFile(Data("short\n{}".utf8), key: key), .malformed)
        let nonHex = String(repeating: "g", count: 64) + "\n{}"
        XCTAssertEqual(RelayCrypto.verifyStateFile(Data(nonHex.utf8), key: key), .malformed)
        // A signature with no snapshot after it.
        XCTAssertEqual(RelayCrypto.verifyStateFile(Data((v.state_sig + "\n").utf8), key: key), .malformed)
    }
}

final class RelayStoreTests: XCTestCase {
    private var folder: URL!

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appending(path: "teyla-relay-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: folder)
    }

    func testMissingAndPresentState() throws {
        let store = RelayStore(folder: folder)
        XCTAssertEqual(store.readState(), .missing)
        let v = try loadVector()
        try Data(v.state_file.utf8).write(to: store.stateURL)
        XCTAssertEqual(store.readState(), .data(Data(v.state_file.utf8)))
    }

    func testOutboxIsWrittenAtomicallyAndLeavesNoTemporaryFile() throws {
        let store = RelayStore(folder: folder)
        let v = try loadVector()
        let entry = try OutboxEntry.make(kind: .answer, target: "7c222b3d", aboutText: v.question, text: "Swap to 1.1",
                                         device: "iPhone", key: keyData(v.key_hex))
        try store.writeOutbox(entry)
        XCTAssertTrue(store.outboxExists(id: entry.id))
        let names = try FileManager.default.contentsOfDirectory(atPath: store.outboxURL.path)
        XCTAssertEqual(names, ["\(entry.id).json"])
        let data = try Data(contentsOf: store.outboxURL.appending(path: "\(entry.id).json"))
        XCTAssertEqual(try JSONDecoder().decode(OutboxEntry.self, from: data), entry)
    }

    func testSentResultsAreReadForOwnIdsAndDeleted() throws {
        let store = RelayStore(folder: folder)
        try FileManager.default.createDirectory(at: store.sentURL, withIntermediateDirectories: true)
        let mine = "6f1c2a54-9a1e-4c3b-8d0f-2b7e1f0c9a11"
        let other = "11111111-2222-3333-4444-555555555555"
        for id in [mine, other] {
            let json = "{\"id\":\"\(id)\",\"ok\":true,\"via\":\"codex-resume\",\"detail\":\"started\",\"done_at\":\"2026-10-17T21:46:00Z\"}"
            try Data(json.utf8).write(to: store.sentURL.appending(path: "\(id).json"))
        }
        let results = store.readSent(ids: [mine])
        XCTAssertEqual(results, [SentResult(id: mine, ok: true, via: "codex-resume", detail: "started",
                                            doneAt: "2026-10-17T21:46:00Z")])
        store.deleteSent(id: mine)
        XCTAssertFalse(FileManager.default.fileExists(atPath: store.sentURL.appending(path: "\(mine).json").path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: store.sentURL.appending(path: "\(other).json").path),
                      "another phone's result is left alone")
    }

    func testASentFileWhoseIdDiffersFromItsNameIsIgnored() throws {
        let store = RelayStore(folder: folder)
        try FileManager.default.createDirectory(at: store.sentURL, withIntermediateDirectories: true)
        let mine = "6f1c2a54-9a1e-4c3b-8d0f-2b7e1f0c9a11"
        let json = "{\"id\":\"11111111-2222-3333-4444-555555555555\",\"ok\":true}"
        try Data(json.utf8).write(to: store.sentURL.appending(path: "\(mine).json"))
        XCTAssertTrue(store.readSent(ids: [mine]).isEmpty)
    }
}

import XCTest

final class SnapshotDecodingTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let here = URL(fileURLWithPath: #filePath)
        let url = here.deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("tests/fixtures/\(name)")
        return try Data(contentsOf: url)
    }

    func testDecodesVersion2Fixture() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(fixture("state.v2.json"))
        XCTAssertEqual(snapshot.version, 2)
        XCTAssertEqual(snapshot.asks.map(\.id), ["7c222b3d", "b6b78de8", "cf075610"])
        XCTAssertEqual(snapshot.asks[0].options, ["Keep iPhone 1.0", "Swap to 1.1"])
        XCTAssertEqual(snapshot.tasks.map(\.kind), ["merge", "task"])
        XCTAssertEqual(snapshot.done.map(\.status), ["done", "needs_you"])
        XCTAssertEqual(snapshot.done[1].needs, "Add a tester email in the Play Console")
        XCTAssertEqual(snapshot.products.map(\.name), ["atlas", "cellar", "teyla", "lens"])
        XCTAssertEqual(snapshot.products.first { $0.name == "lens" }?.prsWaiting, 1)
        XCTAssertEqual(snapshot.running.map(\.correct), ["open", "open", "codex-queue"])
        XCTAssertEqual(snapshot.running.last?.ref, "00000000-0000-0000-0000-000000000008")
        XCTAssertEqual(snapshot.totals.tasks, 2)
        XCTAssertEqual(snapshot.totals.spentTodayUSD, 4.1)
        XCTAssertEqual(snapshot.relay, Relay())
    }

    func testFixtureTargetsAreAllValidForTheRelay() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(fixture("state.v2.json"))
        XCTAssertTrue(snapshot.asks.allSatisfy { OutboxEntry.isTarget($0.id) })
        XCTAssertTrue(snapshot.products.allSatisfy { OutboxEntry.isTarget($0.name) })
        XCTAssertTrue(snapshot.running.allSatisfy { OutboxEntry.isTarget($0.ref) })
    }

    func testTheSnapshotInsideASignedFileDecodes() throws {
        // A signed file, as the Mac writes it, round-trips through verification and decoding.
        let key = Data(repeating: 9, count: 32)
        let json = try fixture("state.v2.json")
        let sig = RelayCrypto.hmacHex(key: key, message: Data(RelayCrypto.stateDomain.utf8) + json)
        let file = Data(sig.utf8) + Data([0x0A]) + json
        guard case .valid(let verified) = RelayCrypto.verifyStateFile(file, key: key) else {
            return XCTFail("expected a valid file")
        }
        XCTAssertEqual(try PhoneFormat.decodeSnapshot(verified).asks.count, 3)
    }
}

final class PhoneFormatTests: XCTestCase {
    func testSyncedLine() {
        XCTAssertEqual(PhoneFormat.synced(secondsAgo: 5), "Mac synced just now")
        XCTAssertEqual(PhoneFormat.synced(secondsAgo: 240), "Mac synced 4 min ago")
        XCTAssertEqual(PhoneFormat.synced(secondsAgo: 7300), "Mac synced 2 h ago")
        XCTAssertEqual(PhoneFormat.synced(secondsAgo: -3), "Mac synced just now")
    }

    func testStaleAfterTenMinutes() {
        XCTAssertFalse(PhoneFormat.isStale(secondsAgo: 600))
        XCTAssertTrue(PhoneFormat.isStale(secondsAgo: 601))
    }

    func testSyncDateUsesRelaySyncedThenGenerated() {
        var snapshot = Snapshot(generated: "2026-10-17T21:40:00Z")
        XCTAssertEqual(PhoneFormat.syncDate(of: snapshot), ISODate.parse("2026-10-17T21:40:00Z"))
        snapshot.relay = Relay(on: true, paired: true, folder: "x", synced: "2026-10-17T21:41:30Z")
        XCTAssertEqual(PhoneFormat.syncDate(of: snapshot), ISODate.parse("2026-10-17T21:41:30Z"))
    }

    func testOnlyWebLinksOpenOnThePhone() {
        XCTAssertNotNil(PhoneFormat.webURL("https://github.com/example/lens/pull/14"))
        XCTAssertNil(PhoneFormat.webURL("claude://claude.ai/epitaxy/local_1"))
        XCTAssertNil(PhoneFormat.webURL("codex://threads/1"))
        XCTAssertNil(PhoneFormat.webURL("claude --resume abc"))
        XCTAssertNil(PhoneFormat.webURL(""))
    }

    func testOutcomeLines() {
        XCTAssertEqual(PhoneFormat.outcomeLine(.init(ok: true, via: "codex-resume", detail: "")),
                       "Sent to the session via codex-resume")
        XCTAssertEqual(PhoneFormat.outcomeLine(.init(ok: false, via: "", detail: "needs the Mac")), "needs the Mac")
        XCTAssertEqual(PhoneFormat.outcomeLine(.init(ok: false, via: "", detail: "")),
                       "The Mac could not deliver this")
    }

    func testAgeAddsTimeSinceTheSnapshot() throws {
        let snapshot = Snapshot(generated: "2026-10-17T21:40:00Z")
        let now = try XCTUnwrap(ISODate.parse("2026-10-17T21:50:00Z"))
        XCTAssertEqual(PhoneFormat.age(60, snapshot: snapshot, now: now), 660)
        XCTAssertEqual(PhoneFormat.ago(30), "just now")
        XCTAssertEqual(PhoneFormat.ago(660), "11 min ago")
    }
}

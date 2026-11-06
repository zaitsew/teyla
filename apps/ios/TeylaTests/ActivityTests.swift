import XCTest

final class ActivitySnapshotTests: XCTestCase {
    private func sampleData() throws -> Data {
        let apps = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        return try Data(contentsOf: apps.appendingPathComponent("Teyla/Resources/sample-state.json"))
    }

    private func repoFixture(_ name: String) throws -> Data {
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        return try Data(contentsOf: root.appendingPathComponent("tests/fixtures/\(name)"))
    }

    func testTheSampleCarriesTheActivityBlock() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(sampleData())
        let activity = try XCTUnwrap(snapshot.activity)
        XCTAssertEqual(activity.days.count, 117)                  // 17 ISO weeks up to Friday
        XCTAssertEqual(activity.today, "2026-11-06")
        XCTAssertEqual(activity.start, "2026-07-13")
        XCTAssertEqual(activity.todayCount, 6)
        XCTAssertEqual(activity.streak, 5)
        XCTAssertEqual(activity.longest, 6)
        XCTAssertEqual(activity.total, 719)                       // the year's total, not the 17 weeks'
        XCTAssertEqual(activity.kinds.count, 11)
        XCTAssertEqual(ActivityLogic.columns(activity.days, weeks: 17).count, 17)
        XCTAssertEqual(activity.spoken, "Activity: 6 today, streak 5 days, 719 this year")
    }

    func testTheBlockHoldsCountsOnly() throws {
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: sampleData()) as? [String: Any])
        let block = try XCTUnwrap(object["activity"] as? [String: Any])
        XCTAssertEqual(Set(block.keys), ["today", "start", "days", "today_count", "week_count", "total", "streak", "longest", "kinds"])
        let days = try XCTUnwrap(block["days"] as? [[String: Any]])
        XCTAssertTrue(days.allSatisfy { Set($0.keys) == ["day", "count", "level"] })
    }

    func testASnapshotWithoutActivityHidesTheCard() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(repoFixture("state.v2.json"))
        XCTAssertNil(snapshot.activity)
    }

    func testABrokenBlockDoesNotBreakTheSnapshot() throws {
        let json = #"{"version": 3, "generated": "2026-11-06T09:00:00Z", "activity": "not an object"}"#
        let snapshot = try PhoneFormat.decodeSnapshot(Data(json.utf8))
        XCTAssertNil(snapshot.activity)
        XCTAssertEqual(snapshot.version, 3)
    }

    func testAMinimalBlockTakesDefaults() throws {
        let json = #"{"version": 3, "activity": {"days": [{"day": "2026-11-05", "count": 2}, {"day": "2026-11-06", "count": 1}], "unknown": 1}}"#
        let snapshot = try PhoneFormat.decodeSnapshot(Data(json.utf8))
        let activity = try XCTUnwrap(snapshot.activity)
        XCTAssertEqual(activity.today, "2026-11-06")
        XCTAssertEqual(activity.total, 3)
        XCTAssertEqual(activity.streak, 0)
        XCTAssertEqual(activity.kinds, ActivityKind.all)
    }
}

final class ActivityOutboxTests: XCTestCase {
    private let key = Data(repeating: 7, count: 32)
    private let id = "11111111-2222-4333-8444-555555555555"
    private let created = "2026-11-06T09:00:00Z"

    private func entry(kind: String = "comment") throws -> OutboxEntry {
        try OutboxEntry.make(kind: .activity, target: kind, aboutText: kind, text: "+1", device: "iPhone", key: key, id: id, created: created)
    }

    func testTheEntryHasTheAgreedShape() throws {
        let e = try entry()
        XCTAssertEqual(e.kind, .activity)
        XCTAssertEqual(e.target, "comment")
        XCTAssertEqual(e.text, "+1")
        XCTAssertEqual(e.about, RelayCrypto.sha256Hex("comment"))
        XCTAssertEqual(e.about.count, 64)
        XCTAssertEqual(e.about, e.about.lowercased())
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: e.jsonData()) as? [String: Any])
        XCTAssertEqual(json["kind"] as? String, "activity")
        XCTAssertEqual(Set(json.keys), ["v", "id", "kind", "target", "about", "text", "created", "device", "sig"])
    }

    func testTheSignatureCoversTheSameLinesAsEveryOtherKind() throws {
        let e = try entry(kind: "icp-meeting")
        let lines = ["teyla-outbox-v1", "1", id, "activity", "icp-meeting", RelayCrypto.sha256Hex("icp-meeting"), created, "iPhone", "+1"]
        XCTAssertEqual(e.message, lines.joined(separator: "\n"))
        XCTAssertEqual(e.sig, RelayCrypto.hmacHex(key: key, message: Data(lines.joined(separator: "\n").utf8)))
        XCTAssertEqual(e.sig.count, 64)
    }

    func testEveryListedKindMakesAnEntry() throws {
        for kind in ActivityKind.all { XCTAssertNoThrow(try entry(kind: kind), kind) }
    }

    func testFreeTextOrAWrongTextNeverMakesAnEntry() {
        for target in ["tweet", "post --count 50", "--all", "Post", "", "post\ncomment"] {
            XCTAssertThrowsError(try OutboxEntry.make(kind: .activity, target: target, aboutText: target, text: "+1",
                                                      device: "iPhone", key: key, id: id, created: created), target)
        }
        for text in ["+50", "log", "+1 --count 50", " "] {
            XCTAssertThrowsError(try OutboxEntry.make(kind: .activity, target: "post", aboutText: "post", text: text,
                                                      device: "iPhone", key: key, id: id, created: created), text)
        }
    }

    func testAnOlderMacWouldCallItMalformed() throws {
        // The Mac checks `kind` against its list before anything else; the phone shows its reason as it is.
        XCTAssertEqual(ActivityLogic.resultWords(label: "Comment", ok: false, detail: "malformed entry: kind"), "Comment: malformed entry: kind")
        XCTAssertTrue(OutboxKind.allCases.contains(.activity))
    }
}

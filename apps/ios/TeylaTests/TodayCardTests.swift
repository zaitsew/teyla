import XCTest

final class TodayCardDecodingTests: XCTestCase {
    func testASnapshotWithoutGtmHidesTheCard() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(Data(#"{"version": 3, "generated": "2026-11-07T09:00:00Z"}"#.utf8))
        XCTAssertNil(snapshot.gtm)
    }

    func testTheRelayShapeDecodes() throws {
        let json = #"""
        {"version": 3, "gtm": {"day": "2026-11-07", "approve": 6, "send": 5, "reply": 2, "follow_up": 1,
         "distribution": {"today": 3, "target": 10, "week": 21}, "outcomes_week": 9, "has_goals": true,
         "goals": [{"id": "g", "title": "Activated testers", "days_left": 38, "targets": [{"stage": "activated", "count": 4, "target": 10}]}],
         "next": [{"kind": "reply", "count": 2}, {"kind": "distribute", "count": 7}], "unknown": 1}}
        """#
        let gtm = try XCTUnwrap(PhoneFormat.decodeSnapshot(Data(json.utf8)).gtm)
        XCTAssertEqual(gtm.waitingTotal, 14)
        XCTAssertEqual(gtm.distribution.target, 10)
        XCTAssertEqual(gtm.goals.first?.daysLeft, 38)
        XCTAssertEqual(gtm.goals.first?.targets, [GtmGlimpse.Target(stage: "activated", count: 4, target: 10)])
        XCTAssertEqual(gtm.next.map(\.kind), ["reply", "distribute"])
        XCTAssertEqual(gtm.distributionFigure, "3 of 10")
        XCTAssertEqual(gtm.waitingSpoken, "6 drafts to approve, 5 items to send, 2 replies to answer, 1 follow-up due.")
    }

    func testANullTargetAndAMinimalBlockTakeDefaults() throws {
        let json = #"{"version": 3, "gtm": {"day": "2026-11-07", "distribution": {"today": 2, "target": null}}}"#
        let gtm = try XCTUnwrap(PhoneFormat.decodeSnapshot(Data(json.utf8)).gtm)
        XCTAssertNil(gtm.distribution.target)
        XCTAssertEqual(gtm.distributionFigure, "2")
        XCTAssertEqual(gtm.waitingSpoken, "Nothing waits for you.")
        XCTAssertTrue(gtm.goals.isEmpty)
        XCTAssertNil(gtm.distributionFraction)
    }

    func testABrokenBlockDoesNotBreakTheSnapshot() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(Data(#"{"version": 3, "gtm": "not an object"}"#.utf8))
        XCTAssertNil(snapshot.gtm)
        XCTAssertEqual(snapshot.version, 3)
    }
}

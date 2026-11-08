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
        XCTAssertEqual(gtm.goals.first?.targets, [GtmGlimpse.Target(stage: "activated", count: 4, target: 10, counter: "outcomes")])
        XCTAssertEqual(gtm.next.map(\.kind), ["reply", "distribute"])
        XCTAssertEqual(gtm.distributionFigure, "3 of 10")
        XCTAssertEqual(gtm.waitingSpoken, "6 drafts to approve, 5 items to send, 2 replies to answer, 1 follow-up due.")
    }

    func testTheLeadGoalsDraftsShapeTheNextLine() throws {
        let json = #"""
        {"version": 3, "gtm": {"day": "2026-11-07", "approve": 22, "reply": 2, "has_goals": true, "untagged_drafts": 11,
         "goals": [{"id": "a", "title": "Lead", "short": 9, "drafts": 8, "targets": [{"stage": "conversation", "count": 0, "target": 9}]}],
         "next": [{"kind": "reply", "count": 2}, {"kind": "approve", "count": 22}]}}
        """#
        let gtm = try XCTUnwrap(PhoneFormat.decodeSnapshot(Data(json.utf8)).gtm)
        XCTAssertEqual(gtm.goals.first?.drafts, 8)
        XCTAssertEqual(gtm.untaggedDrafts, 11)
        XCTAssertEqual(gtm.nextTitle, "2 replies to answer, then 8 drafts for this goal")
        XCTAssertEqual(gtm.untaggedLine, "11 drafts have no goal.")
        let old = try XCTUnwrap(PhoneFormat.decodeSnapshot(Data(#"{"version": 3, "gtm": {"day": "d", "reply": 2, "next": [{"kind": "reply", "count": 2}], "goals": [{"id": "a", "title": "T"}]}}"#.utf8)).gtm)
        XCTAssertEqual(old.nextTitle, "2 replies to answer")
        XCTAssertNil(old.untaggedLine)
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

    func testTheGoalFirstFieldsDecodeAndAnOlderMacStillWorks() throws {
        let json = #"""
        {"version": 3, "gtm": {"day": "2026-11-07", "approve": 22, "reply": 2, "distribution": {"today": 3, "target": 10, "week": 21},
         "has_goals": true,
         "goals": [{"id": "a", "title": "Small", "short": 3, "targets": [{"stage": "intro", "count": 0, "target": 3, "counter": "outcomes"}]},
                   {"id": "b", "title": "Big", "done_when": "A sale", "days_left": 114, "weeks_left": 16, "short": 14,
                    "targets": [{"stage": "approached", "count": 21, "target": 60, "counter": "distribution"},
                                {"stage": "conversation", "count": 1, "target": 15, "counter": "outcomes"}]}],
         "next": [{"kind": "distribute", "count": 7}, {"kind": "reply", "count": 2}]}}
        """#
        let gtm = try XCTUnwrap(PhoneFormat.decodeSnapshot(Data(json.utf8)).gtm)
        XCTAssertEqual(gtm.goals[1].weeksLeft, 16)
        XCTAssertEqual(gtm.goals[1].short, 14)
        XCTAssertEqual(gtm.lead?.id, "b")
        XCTAssertEqual(gtm.lead?.outcomeTargets.map(\.stage), ["conversation"])
        XCTAssertEqual(gtm.nextTitle, "2 replies to answer")
        XCTAssertEqual(gtm.cameBack, 2)
        XCTAssertEqual(gtm.stripSpoken, "Sent 3 of 10 today. 2 that came back are waiting. 22 prepared.")

        let old = try XCTUnwrap(PhoneFormat.decodeSnapshot(Data(#"{"version": 3, "gtm": {"day": "2026-11-07", "goals": [{"id": "g", "targets": [{"stage": "intro", "count": 1, "target": 3}]}]}}"#.utf8)).gtm)
        XCTAssertEqual(old.goals[0].targets[0].counter, "outcomes")
        XCTAssertEqual(old.goals[0].short, 0)
        XCTAssertNil(old.nextTitle)
    }
}

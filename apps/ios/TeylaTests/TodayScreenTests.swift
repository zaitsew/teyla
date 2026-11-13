import XCTest

final class TodayScreenTests: XCTestCase {
    private func ask(_ id: String, kind: String = "question", age: Double = 0) -> Ask {
        let json = #"{"id": "\#(id)", "kind": "\#(kind)", "question": "Q \#(id)", "age_s": \#(age)}"#
        return try! JSONDecoder().decode(Ask.self, from: Data(json.utf8))
    }

    private func build(_ product: String, _ day: String, _ number: String = "1") -> TodayBuild {
        TodayBuild(product: product, platform: "iOS", build: number, uploaded: day)
    }

    func testAnOlderMacSnapshotWithoutTodayDecodes() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(Data(#"{"version": 3, "asks": []}"#.utf8))
        XCTAssertNil(snapshot.today)
        XCTAssertEqual(PhoneToday.buildsCaption(snapshot.today), "This Mac sends no build list. Update Teyla on the Mac.")
        XCTAssertTrue(PhoneToday.builds(snapshot.today).isEmpty)
    }

    func testBuildsDecodeWithTheirCountAndDropAMalformedRow() throws {
        let json = #"{"version": 3, "today": {"builds_to_try": {"value": 2, "builds": [{"product": "sample-app", "platform": "iOS", "build": "42", "uploaded": "2026-11-12"}, 7, {"product": "sample-tool", "platform": "macOS", "build": "7", "uploaded": "2026-11-13"}]}}}"#
        let today = try XCTUnwrap(PhoneFormat.decodeSnapshot(Data(json.utf8)).today)
        XCTAssertEqual(today.buildsToTry?.count, 2)
        XCTAssertNil(PhoneToday.buildsCaption(today))
        XCTAssertEqual(PhoneToday.builds(today).map(\.product), ["sample-tool", "sample-app"])
    }

    func testNotMeasuredShowsTheReasonAndNoRows() throws {
        let json = #"{"version": 3, "today": {"builds_to_try": {"value": "not_measured", "reason": "run `teyla testflight` once"}}}"#
        let today = try XCTUnwrap(PhoneFormat.decodeSnapshot(Data(json.utf8)).today)
        XCTAssertNil(today.buildsToTry?.count)
        XCTAssertEqual(PhoneToday.buildsCaption(today), "Builds are not measured: run `teyla testflight` once.")
        XCTAssertTrue(PhoneToday.builds(today).isEmpty)
    }

    func testTopThreeDecisions() {
        let owner = (1...5).map { ask("a\($0)") }
        XCTAssertEqual(PhoneToday.decisions(owner).map(\.id), ["a1", "a2", "a3"])
    }

    func testNextIsTheOldestCriticalDecisionFirst() {
        let owner = [ask("n1", age: 900), ask("b1", kind: "blocked", age: 100), ask("b2", kind: "blocked", age: 500)]
        XCTAssertEqual(PhoneToday.next(owner: owner, contentDue: true, builds: [build("x", "2026-11-12")]), .decision(owner[2]))
    }

    func testNextIsThePostWhenOneIsDue() {
        XCTAssertEqual(PhoneToday.next(owner: [ask("n1")], contentDue: true, builds: [build("x", "2026-11-12")]), .content)
    }

    func testNextIsTheNewestBuildThenTheTopDecisionThenNothing() {
        let builds = [build("old", "2026-11-09"), build("new", "2026-11-12")]
        XCTAssertEqual(PhoneToday.next(owner: [ask("n1")], contentDue: false, builds: builds), .build(builds[1]))
        XCTAssertEqual(PhoneToday.next(owner: [ask("n1")], contentDue: false, builds: []), .decision(ask("n1")))
        XCTAssertEqual(PhoneToday.next(owner: [], contentDue: false, builds: []), .nothing)
    }

    func testBuildWordsAreSpoken() {
        let b = build("sample-app", "2026-11-12", "42")
        XCTAssertEqual(PhoneToday.buildTitle(b), "Sample App")
        XCTAssertEqual(PhoneToday.buildDetail(b), "iOS \u{00B7} build 42")
        XCTAssertTrue(PhoneToday.buildSpoken(b).hasPrefix("Sample App, iOS, build 42. Uploaded "))
    }

    func testTheLabSwitchDefaultsToOff() {
        XCTAssertEqual(TodayVariant.from(stored: ""), .off)
        XCTAssertEqual(TodayVariant.from(stored: "a"), .a)
        XCTAssertEqual(TodayVariant.from(stored: "b"), .b)
        XCTAssertEqual(TodayVariant.from(stored: "zzz"), .off)
    }
}

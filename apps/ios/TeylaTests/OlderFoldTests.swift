import XCTest

final class OlderFoldTests: XCTestCase {
    private let generated = "2026-10-25T09:00:00Z"
    private var now: Date { ISODate.parse(generated)! }

    private func ask(_ id: String, days: Double) -> Ask {
        Ask(id: id, product: "sample-app", ageSeconds: days * 86_400)
    }

    func testQuestionsOlderThanAWeekFoldAndTheRestKeepTheirOrder() {
        let asks = [ask("a", days: 1), ask("b", days: 9), ask("c", days: 0.1), ask("d", days: 30), ask("e", days: 6.9)]
        let snapshot = Snapshot(generated: generated, asks: asks)
        let split = PhoneFormat.splitAsks(asks, snapshot: snapshot, now: now)
        XCTAssertEqual(split.fresh.map(\.id), ["a", "c", "e"])
        XCTAssertEqual(split.older.map(\.id), ["b", "d"])
    }

    func testTheAgeGrowsWithTheTimeSinceTheSnapshotWasWritten() {
        let asks = [ask("a", days: 6.5)]
        let snapshot = Snapshot(generated: generated, asks: asks)
        XCTAssertEqual(PhoneFormat.splitAsks(asks, snapshot: snapshot, now: now).older.count, 0)
        // Fourteen hours later the same question has waited more than 7 days.
        let later = now.addingTimeInterval(14 * 3600)
        XCTAssertEqual(PhoneFormat.splitAsks(asks, snapshot: snapshot, now: later).older.map(\.id), ["a"])
    }

    func testNothingFoldsWhenEverythingIsFresh() {
        let asks = [ask("a", days: 2), ask("b", days: 3)]
        let split = PhoneFormat.splitAsks(asks, snapshot: Snapshot(generated: generated, asks: asks), now: now)
        XCTAssertEqual(split.fresh.count, 2)
        XCTAssertTrue(split.older.isEmpty)
    }
}

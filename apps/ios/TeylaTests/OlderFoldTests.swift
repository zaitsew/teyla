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

/// Home's Next line, tapped when the question it names sits in the closed Older fold.
@MainActor
final class NextLineRevealTests: XCTestCase {
    private struct NoKeyStore: KeyStore {
        func load() -> Data? { nil }
        func save(_ key: Data) throws {}
        func delete() {}
    }

    private let generated = "2026-10-25T09:00:00Z"
    private var now: Date { ISODate.parse(generated)! }

    private func model() -> AppModel {
        AppModel(environment: [:], defaults: UserDefaults(suiteName: "NextLineRevealTests-\(UUID().uuidString)")!,
                 keyStore: NoKeyStore())
    }

    private func lists(_ days: [Double]) -> DecisionLists {
        let asks = days.enumerated().map { Ask(id: "q\($0.offset)", product: "sample-app", ageSeconds: $0.element * 86_400) }
        return DecisionLists(asks: asks, snapshot: Snapshot(generated: generated, asks: asks), now: now)
    }

    func testNextOpensTheFoldWhenEveryOpenQuestionIsOlderThanAWeek() {
        let model = model()
        let all = lists([9, 12, 30])
        XCTAssertTrue(all.fresh.isEmpty)
        XCTAssertTrue(PhoneHome.nextRevealsOlder(all))
        XCTAssertFalse(PhoneHome.olderFoldStartsOpen(reveals: model.olderReveals, launchOpen: false), "closed before the tap")
        model.openNext(revealingOlder: PhoneHome.nextRevealsOlder(all))
        XCTAssertEqual(model.olderReveals, 1)
        XCTAssertTrue(PhoneHome.olderFoldStartsOpen(reveals: model.olderReveals, launchOpen: false), "open after the tap")
    }

    func testEachTapCountsSoAFoldTheOwnerClosedOpensAgain() {
        let model = model()
        model.openNext(revealingOlder: true)
        model.openNext(revealingOlder: true)
        XCTAssertEqual(model.olderReveals, 2)
    }

    func testNextLeavesTheFoldClosedWhenAFreshQuestionIsFirst() {
        let model = model()
        let mixed = lists([2, 12])
        XCTAssertFalse(PhoneHome.nextRevealsOlder(mixed))
        model.openNext(revealingOlder: PhoneHome.nextRevealsOlder(mixed))
        XCTAssertEqual(model.olderReveals, 0)
        XCTAssertFalse(PhoneHome.olderFoldStartsOpen(reveals: model.olderReveals, launchOpen: false))
    }

    func testNothingOpensWhenNoQuestionWaits() {
        XCTAssertFalse(PhoneHome.nextRevealsOlder(lists([])))
    }

    func testTheLaunchOptionOpensTheFoldForScreenshots() {
        XCTAssertTrue(PhoneHome.olderFoldStartsOpen(reveals: 0, launchOpen: true))
    }
}

import XCTest

final class AskFoldTests: XCTestCase {
    func testPartitionKeepsRankOrderAndSplitsAtSevenDays() {
        let day = 86_400.0
        let ages: [(String, Double)] = [("a", 9 * day), ("b", 1 * day), ("c", 7 * day), ("d", 7 * day + 1), ("e", 30 * day), ("f", 0)]
        let split = AskFold.partition(ages) { $0.1 }
        XCTAssertEqual(split.fresh.map(\.0), ["b", "c", "f"])
        XCTAssertEqual(split.older.map(\.0), ["a", "d", "e"])
    }

    func testPartitionOfNothing() {
        let split = AskFold.partition([Double]()) { $0 }
        XCTAssertTrue(split.fresh.isEmpty && split.older.isEmpty)
        XCTAssertEqual(AskFold.heading(count: 15), "Older · 15")
    }
}

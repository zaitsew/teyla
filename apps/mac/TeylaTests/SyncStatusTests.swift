import XCTest

final class SyncStatusTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private var utc: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }

    private func indicator(fetched: TimeInterval? = 10, generated: TimeInterval? = nil, refreshing: Bool = false,
                           pageLoading: Bool = false, error: String? = nil, portfolio: Bool = false,
                           stores: TimeInterval? = nil, github: TimeInterval? = nil) -> SyncIndicator {
        SyncStatus.indicator(
            now: now,
            fetchedAt: fetched.map { now.addingTimeInterval(-$0) },
            generated: generated.map { now.addingTimeInterval(-$0) },
            refreshing: refreshing, pageLoading: pageLoading, error: error,
            checkedStores: stores.map { now.addingTimeInterval(-$0) },
            checkedGitHub: github.map { now.addingTimeInterval(-$0) },
            hasPortfolio: portfolio, calendar: utc)
    }

    func testFreshSnapshotIsUpToDate() {
        let i = indicator(fetched: 30)
        XCTAssertEqual(i.state, .upToDate)
        XCTAssertEqual(i.label, "Up to date")
    }

    func testStaleAfterTwoMinutes() {
        XCTAssertEqual(indicator(fetched: 119).state, .upToDate)
        let i = indicator(fetched: 120)
        XCTAssertEqual(i.state, .stale)
        XCTAssertEqual(i.label, "Stale · 2 min")
        XCTAssertEqual(indicator(fetched: 3 * 3600 + 5).label, "Stale · 3 h")
    }

    func testOldGeneratedTimeMakesItStaleEvenIfJustRead() {
        let i = indicator(fetched: 5, generated: 600)
        XCTAssertEqual(i.state, .stale)
        XCTAssertEqual(i.label, "Stale · 10 min")
    }

    func testGeneratedInTheFutureIsIgnored() {
        XCTAssertEqual(indicator(fetched: 5, generated: -400).state, .upToDate)
    }

    func testUpdatingWinsWhileRefreshingOrPageLoads() {
        XCTAssertEqual(indicator(fetched: 5, refreshing: true).state, .updating)
        XCTAssertEqual(indicator(fetched: 5, pageLoading: true).label, "Updating…")
        XCTAssertEqual(indicator(fetched: 900, refreshing: true, error: "x").state, .updating)
    }

    func testErrorIsOfflineWithTheErrorInTheTooltip() {
        let i = indicator(fetched: 5, error: "teyla exited with 1")
        XCTAssertEqual(i.state, .offline)
        XCTAssertEqual(i.label, "Offline")
        XCTAssertTrue(i.tooltip.contains("teyla exited with 1"))
    }

    func testNothingReadYetIsUpdating() {
        XCTAssertEqual(indicator(fetched: nil).state, .updating)
    }

    func testTooltipShowsStoreAndGitHubAges() {
        let i = indicator(fetched: 5, portfolio: true, stores: 3 * 3600, github: 20 * 60)
        XCTAssertTrue(i.tooltip.contains("Stores checked 3 h ago · GitHub 20 min ago"))
        let none = indicator(fetched: 5, portfolio: true)
        XCTAssertTrue(none.tooltip.contains("Stores checked never · GitHub never"))
        XCTAssertFalse(indicator(fetched: 5).tooltip.contains("Stores checked"))
    }

    func testTooltipHasExactTimes() {
        let i = indicator(fetched: 5, generated: 7)
        XCTAssertTrue(i.tooltip.contains("Read by the app at "))
        XCTAssertTrue(i.tooltip.contains("Snapshot made at "))
    }

    func testElapsedAndAgo() {
        XCTAssertEqual(Format.elapsed(seconds: 45), "45 s")
        XCTAssertEqual(Format.elapsed(seconds: 90_000), "1 d")
        XCTAssertEqual(Format.ago(seconds: 20), "just now")
        XCTAssertEqual(Format.ago(seconds: 1200), "20 min ago")
    }
}

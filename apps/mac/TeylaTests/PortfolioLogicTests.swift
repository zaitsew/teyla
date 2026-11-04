import XCTest

final class PortfolioLogicTests: XCTestCase {
    private func fixture() throws -> Snapshot {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/state.sample.v3.json")
        return try JSONDecoder().decode(Snapshot.self, from: Data(contentsOf: url))
    }

    func testPlatformChipText() throws {
        let portfolio = try XCTUnwrap(fixture().portfolio)
        let app = try XCTUnwrap(portfolio.product("sample-app"))
        XCTAssertEqual(app.platforms.map(PortfolioText.chip),
                       ["iOS 1.4.0 (52) · current", "Android 1.3.0 (14) · behind", "Web · live"])
    }

    func testChipWithoutVersionOrWithOnlyBuild() {
        XCTAssertEqual(PortfolioText.chip(PlatformStatus(platform: "macos", state: "none")), "macOS · no build")
        XCTAssertEqual(PortfolioText.chip(PlatformStatus(platform: "watch", build: "7", state: "in_review")),
                       "Watch (7) · in review")
        XCTAssertEqual(PortfolioText.chip(PlatformStatus(platform: "android", version: "2.0", state: "blocked")),
                       "Android 2.0 · blocked")
        XCTAssertEqual(PortfolioText.chip(PlatformStatus(platform: "ios", state: "weird")), "iOS · unchecked")
    }

    func testSymbolsFallBackInOrder() {
        XCTAssertEqual(PortfolioText.symbols(for: "android"), ["smartphone", "apps.iphone"])
        XCTAssertEqual(PortfolioText.symbols(for: "iOS"), ["iphone"])
        XCTAssertEqual(PortfolioText.symbols(for: "web"), ["globe"])
    }

    func testChannelNames() {
        XCTAssertEqual(PortfolioText.channelName("testflight"), "TestFlight")
        XCTAssertEqual(PortfolioText.channelName("play"), "Google Play")
        XCTAssertEqual(PortfolioText.channelName(""), "")
    }

    func testSummaryLeavesOutZeros() {
        XCTAssertEqual(PortfolioText.summary(HealthCounts(onTrack: 14, atRisk: 3, offTrack: 2, parked: 0)),
                       "2 off track · 3 at risk · 14 on track")
        XCTAssertEqual(PortfolioText.summary(HealthCounts(onTrack: 1, parked: 2)), "1 on track · 2 parked")
        XCTAssertEqual(PortfolioText.summary(HealthCounts()), "No products yet")
    }

    func testCheckedAges() {
        let now = ISODate.parse("2026-10-25T09:00:00Z")!
        XCTAssertEqual(PortfolioText.checked(stores: "2026-10-25T06:00:00Z", github: "2026-10-25T08:40:00Z", now: now),
                       "Stores checked 3 h ago · GitHub 20 min ago")
        XCTAssertEqual(PortfolioText.checked(stores: "", github: "2026-10-25T08:59:30Z", now: now),
                       "Stores checked never · GitHub just now")
    }

    func testFiguresText() {
        XCTAssertEqual(PortfolioText.prDetail(PRCounts(open: 3, waiting: 1, merged7d: 14, unreviewed7d: 0)), "14 merged in 7 days")
        XCTAssertEqual(PortfolioText.prDetail(PRCounts(open: 1, merged7d: 4, unreviewed7d: 2)), "4 merged in 7 days · 2 unreviewed")
        XCTAssertEqual(PortfolioText.oldestWait(PortfolioProduct(id: "a")), "")
        XCTAssertEqual(PortfolioText.oldestWait(PortfolioProduct(id: "a", waiting: 3, oldestWaitDays: 9.4)), "oldest 9 d")
        XCTAssertEqual(PortfolioText.oldestWait(PortfolioProduct(id: "a", waiting: 1, oldestWaitDays: 0.2)), "")
        let now = ISODate.parse("2026-10-25T09:00:00Z")!
        XCTAssertEqual(PortfolioText.lastActivity(Activity(last: "2026-10-25T07:00:00Z"), now: now), "Active 2 h ago")
        XCTAssertEqual(PortfolioText.lastActivity(Activity(), now: now), "No sessions yet")
    }

    func testHealthWordsAndIcons() {
        XCTAssertEqual(Health.offTrack.title, "Off track")
        XCTAssertEqual(Health.offTrack.symbol, "exclamationmark.octagon")
        XCTAssertEqual(Health.atRisk.symbol, "exclamationmark.triangle")
        XCTAssertEqual(Health.onTrack.symbol, "checkmark.circle")
        XCTAssertEqual(Health.parked.symbol, "pause.circle")
        XCTAssertEqual(Set([Health.offTrack, .atRisk, .onTrack, .parked].map(\.symbol)).count, 4)
    }

    func testFilter() {
        let products = [
            PortfolioProduct(id: "a", health: "off_track"),
            PortfolioProduct(id: "b", health: "at_risk"),
            PortfolioProduct(id: "c", health: "on_track"),
            PortfolioProduct(id: "d", health: "parked"),
        ]
        XCTAssertEqual(PortfolioFilter.all.apply(products, showParked: false).map(\.id), ["a", "b", "c"])
        XCTAssertEqual(PortfolioFilter.all.apply(products, showParked: true).map(\.id), ["a", "b", "c", "d"])
        XCTAssertEqual(PortfolioFilter.needsAttention.apply(products, showParked: true).map(\.id), ["a", "b"])
    }
}

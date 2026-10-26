import XCTest

final class PortfolioFormatTests: XCTestCase {
    private func sample() throws -> Snapshot {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("apps/mac/TeylaTests/Fixtures/state.sample.v3.json")
        return try PhoneFormat.decodeSnapshot(Data(contentsOf: url))
    }

    private func product(_ id: String, _ health: String) -> PortfolioProduct {
        PortfolioProduct(id: id, title: id, health: health)
    }

    func testTheHeadlineListsOnlyThePartsThatHaveProducts() {
        let counts = HealthCounts(onTrack: 14, atRisk: 3, offTrack: 2, parked: 0)
        XCTAssertEqual(PortfolioFormat.headline(for: Portfolio(counts: counts)),
                       "2 off track \u{00B7} 3 at risk \u{00B7} 14 on track")
        XCTAssertEqual(PortfolioFormat.headline(for: Portfolio(counts: HealthCounts(onTrack: 4, parked: 1))),
                       "4 on track \u{00B7} 1 parked")
        XCTAssertEqual(PortfolioFormat.headline(for: Portfolio()), "No products are registered yet")
    }

    func testTheHeadlineFallsBackToTheRowsWhenTheCountsAreMissing() {
        let rows = [product("a", "off_track"), product("b", "on_track"), product("c", "on_track")]
        XCTAssertEqual(PortfolioFormat.headline(for: Portfolio(products: rows)), "1 off track \u{00B7} 2 on track")
    }

    func testNeedsAttentionIsOffTrackAndAtRiskInTheSentOrder() {
        let rows = [product("a", "off_track"), product("b", "at_risk"), product("c", "on_track"), product("d", "parked")]
        XCTAssertEqual(PortfolioFormat.visible(rows, filter: .attention).map(\.id), ["a", "b"])
        XCTAssertEqual(PortfolioFormat.visible(rows, filter: .all).map(\.id), ["a", "b", "c", "d"])
    }

    func testEveryHealthHasAWordAndASymbol() {
        for health in [Health.offTrack, .atRisk, .onTrack, .parked] {
            XCTAssertFalse(PortfolioFormat.healthLabel(health).isEmpty)
            XCTAssertFalse(PortfolioFormat.healthSymbol(health).isEmpty)
        }
        XCTAssertEqual(PortfolioFormat.healthSymbol(.offTrack), "exclamationmark.octagon")
        XCTAssertEqual(PortfolioFormat.healthSymbol(.atRisk), "exclamationmark.triangle")
        XCTAssertEqual(PortfolioFormat.healthSymbol(.onTrack), "checkmark.circle")
        XCTAssertEqual(PortfolioFormat.healthSymbol(.parked), "pause.circle")
    }

    func testThePlatformLine() {
        XCTAssertEqual(PortfolioFormat.platformLine(PlatformStatus(platform: "ios", version: "1.4.0", build: "52", state: "current")),
                       "iOS 1.4.0 (52) \u{00B7} current")
        XCTAssertEqual(PortfolioFormat.platformLine(PlatformStatus(platform: "web", state: "live")), "Web \u{00B7} live")
        XCTAssertEqual(PortfolioFormat.platformLine(PlatformStatus(platform: "android", version: "1.3.0", state: "bogus")),
                       "Android 1.3.0 \u{00B7} not checked")
    }

    func testTheSampleSnapshotDrivesTheTab() throws {
        let portfolio = try XCTUnwrap(sample().portfolio)
        XCTAssertEqual(portfolio.products.map(\.id), ["sample-app", "sample-tool"])
        XCTAssertEqual(PortfolioFormat.headline(for: portfolio), "1 at risk \u{00B7} 1 on track")
        XCTAssertEqual(PortfolioFormat.visible(portfolio.products, filter: .attention).map(\.id), ["sample-app"])
        XCTAssertEqual(portfolio.products[0].platforms.map(PortfolioFormat.platformLine),
                       ["iOS 1.4.0 (52) \u{00B7} current", "Android 1.3.0 (14) \u{00B7} behind", "Web \u{00B7} live"])
    }

    func testCheckedLines() {
        let now = ISODate.parse("2026-10-25T09:00:00Z")!
        XCTAssertEqual(PortfolioFormat.checkedAgo("2026-10-25T06:00:00Z", now: now), "checked 3h ago")
        XCTAssertNil(PortfolioFormat.checkedAgo("", now: now))
        let portfolio = Portfolio(checkedStores: "2026-10-25T06:00:00Z", checkedGitHub: "")
        XCTAssertEqual(PortfolioFormat.checkedLine(portfolio, now: now), "Stores checked 3h ago \u{00B7} GitHub not checked yet")
    }

    func testQuestionsOfOneProduct() {
        let asks = [Ask(id: "a1", product: "sample-app"), Ask(id: "a2", product: "other"), Ask(id: "a3", product: "sample-app")]
        let row = product("sample-app", "at_risk")
        XCTAssertEqual(PortfolioFormat.questions(for: row, in: asks).map(\.id), ["a1", "a3"])
    }

    func testLaunchOptionsReadTheEnvironment() {
        let defaults = UserDefaults(suiteName: "LaunchOptionsTests-\(UUID().uuidString)")!
        let options = LaunchOptions(environment: ["TEYLA_TAB": "portfolio", "TEYLA_OPEN": "sample-app"], defaults: defaults)
        XCTAssertEqual(options.tab, "portfolio")
        XCTAssertEqual(options.openProduct, "sample-app")
        XCTAssertNil(LaunchOptions(environment: [:], defaults: defaults).tab)
    }
}

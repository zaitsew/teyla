import XCTest

final class PortfolioDecodeTests: XCTestCase {
    private func fixture(_ name: String) throws -> Data {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/\(name)")
        return try Data(contentsOf: url)
    }

    func testVersion3Fixture() throws {
        let snapshot = try JSONDecoder().decode(Snapshot.self, from: fixture("state.sample.v3.json"))
        XCTAssertEqual(snapshot.version, 3)
        let portfolio = try XCTUnwrap(snapshot.portfolio)
        XCTAssertEqual(portfolio.checkedStores, "2026-10-25T06:00:00Z")
        XCTAssertEqual(portfolio.counts.atRisk, 1)
        XCTAssertEqual(portfolio.products.map(\.id), ["sample-app", "sample-tool", "sample-old"])
        let app = try XCTUnwrap(portfolio.product("sample-app"))
        XCTAssertEqual(app.health, .atRisk)
        XCTAssertEqual(app.reasons.count, 2)
        XCTAssertEqual(app.platforms.map(\.state), [.current, .behind, .live])
        XCTAssertTrue(app.platforms[0].isPrimary)
        XCTAssertEqual(app.prs.merged7d, 14)
        XCTAssertEqual(app.activity.spend7dUSD, 210.5, accuracy: 0.001)
    }

    func testOlderSnapshotHasNoPortfolio() throws {
        let snapshot = try JSONDecoder().decode(Snapshot.self, from: fixture("state.sample.v2.json"))
        XCTAssertNil(snapshot.portfolio)
    }

    func testUnknownValuesFallBack() throws {
        let json = #"{"id":"x","health":"melting","platforms":[{"platform":"ios","state":"exploded"},{"nope":1}]}"#
        let product = try JSONDecoder().decode(PortfolioProduct.self, from: Data(json.utf8))
        XCTAssertEqual(product.health, .onTrack)
        XCTAssertEqual(product.platforms.count, 1)
        XCTAssertEqual(product.platforms[0].state, .unknown)
    }

    // MARK: Home sections and metrics

    func testHomeAndMetricsDecode() throws {
        let portfolio = try XCTUnwrap(JSONDecoder().decode(Snapshot.self, from: fixture("state.sample.v3.json")).portfolio)
        XCTAssertEqual(portfolio.home?.sections.map(\.id), ["users", "building", "quiet"])
        XCTAssertEqual(portfolio.home?.sections.map(\.ids), [["sample-app"], ["sample-tool"], ["sample-old"]])
        let app = try XCTUnwrap(portfolio.product("sample-app"))
        XCTAssertEqual(app.summary, "A sample app that plans a trip with a few friends.")
        XCTAssertFalse(app.iconJPEG.isEmpty)
        XCTAssertEqual(app.metrics.users.total, 12)
        XCTAssertEqual(app.metrics.users.active.d7, 4)
        XCTAssertEqual(app.metrics.users.active.d30, 6)
        XCTAssertEqual(app.metrics.users.new.d365, 9)
        XCTAssertEqual(app.metrics.commits.counts.d7, 21)
        XCTAssertEqual(app.metrics.commits.counts[.year], 640)
        XCTAssertEqual(app.metrics.commits.weeks.count, 12)
        XCTAssertEqual(app.metrics.commits.weeks.last, 21)
        XCTAssertEqual(try XCTUnwrap(app.metrics.spendUSD.d30), 2900.0, accuracy: 0.001)
        XCTAssertFalse(app.metrics.money.enabled)
        XCTAssertNil(app.metrics.money.mrrUSD)
        XCTAssertNil(app.metrics.money.revenueUSD.d7)
    }

    func testAnOlderStateHasNoHomeAndEveryMetricIsNotCounted() throws {
        // The made-up CLI output before this field: a portfolio with products and nothing about Home.
        let json = #"{"version":1,"products":[{"id":"x","title":"X","stage":"live"}],"core":["x"],"core_source":"star"}"#
        let portfolio = try JSONDecoder().decode(Portfolio.self, from: Data(json.utf8))
        XCTAssertNil(portfolio.home)
        let product = try XCTUnwrap(portfolio.product("x"))
        XCTAssertEqual(product.summary, "")
        XCTAssertEqual(product.iconJPEG, "")
        XCTAssertEqual(product.metrics, ProductMetrics())
        XCTAssertNil(product.metrics.users.total)
        XCTAssertNil(product.metrics.commits.counts.d7)
        XCTAssertTrue(product.metrics.commits.weeks.isEmpty)
        XCTAssertFalse(product.metrics.money.enabled)
        guard case .legacy(let cards) = HomeSections.layout(portfolio) else { return XCTFail("expected the core fallback") }
        XCTAssertEqual(cards.map(\.id), ["x"])
    }

    func testNullMetricsStayNilAndShowADash() throws {
        let json = #"""
        {"id":"x","metrics":{"users":{"total":null,"active":{"7d":null,"30d":null,"365d":null},
         "new":{"7d":2,"30d":null,"365d":null}},
         "commits":{"7d":null,"30d":null,"365d":null,"weeks":[]},
         "spend_usd":{"7d":null,"30d":null,"365d":null},
         "money":{"enabled":false,"mrr_usd":null,"paying":null,"revenue_usd":{"7d":null,"30d":null,"365d":null}}}}
        """#
        let product = try JSONDecoder().decode(PortfolioProduct.self, from: Data(json.utf8))
        let facts = HomeFactsBuilder.facts(product, period: .week)
        XCTAssertEqual(facts.active, "\u{2014}")
        XCTAssertEqual(facts.new, "2")
        XCTAssertEqual(facts.total, "\u{2014}")
        XCTAssertEqual(facts.commitsCount, "\u{2014}")
        XCTAssertEqual(facts.spend, "Agent spend: not counted yet")
        XCTAssertEqual(facts.money, "Off")
        XCTAssertFalse(facts.spoken.contains(" 0 "), "a count nobody made is never zero")
    }

    func testEmptyWeeksDrawNoSparkline() throws {
        let json = #"{"id":"x","metrics":{"commits":{"7d":0,"30d":0,"365d":0,"weeks":[]}}}"#
        let product = try JSONDecoder().decode(PortfolioProduct.self, from: Data(json.utf8))
        XCTAssertEqual(product.metrics.commits.counts.d7, 0, "a counted zero is a zero")
        XCTAssertTrue(product.metrics.commits.weeks.isEmpty)
        let facts = HomeFactsBuilder.facts(product, period: .week)
        XCTAssertNil(facts.sparkLabel)
        XCTAssertTrue(facts.sparkHeights.isEmpty)
        XCTAssertEqual(facts.commitsCount, "0")
    }

    func testBadMetricValuesDoNotFailTheRow() throws {
        let json = #"{"id":"x","summary":7,"icon_jpeg":null,"metrics":{"users":"many","commits":{"7d":"lots","weeks":[1,"a"]}},"#
            + #""home_note":1}"#
        let product = try JSONDecoder().decode(PortfolioProduct.self, from: Data(json.utf8))
        XCTAssertEqual(product.id, "x")
        XCTAssertEqual(product.summary, "")
        XCTAssertNil(product.metrics.users.total)
        XCTAssertNil(product.metrics.commits.counts.d7)
        let home = try JSONDecoder().decode(Portfolio.self, from: Data(#"{"home":{"sections":[{"id":"users","ids":["a"]},{"nope":1}]}}"#.utf8))
        XCTAssertEqual(home.home?.sections.map(\.id), ["users"])
    }

    func testTheSwitchNeverReordersASection() throws {
        let portfolio = try XCTUnwrap(JSONDecoder().decode(Snapshot.self, from: fixture("state.sample.home.json")).portfolio)
        guard case .sections(let sections) = HomeSections.layout(portfolio) else { return XCTFail("expected sections") }
        let before = sections.map { $0.products.map(\.id) }
        for period in HomePeriod.allCases {
            let ids = sections.map { section in section.products.map { HomeFactsBuilder.facts($0, period: period).id } }
            XCTAssertEqual(ids, before, "\(period) changed the order")
        }
        XCTAssertEqual(before, [["sample-app", "sample-tool", "sample-notes"],
                                ["sample-web", "sample-lab", "sample-kit"],
                                ["sample-watch", "sample-old", "sample-play"]])
    }
}

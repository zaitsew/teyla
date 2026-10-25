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
        XCTAssertEqual(portfolio.products.map(\.id), ["sample-app", "sample-tool"])
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
}

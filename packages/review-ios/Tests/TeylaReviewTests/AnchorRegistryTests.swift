import CoreGraphics
import XCTest
@testable import TeylaReview

final class AnchorRegistryTests: XCTestCase {
    private func register(_ r: AnchorRegistry, _ token: UUID, _ id: String, _ rect: CGRect?, screen: String? = nil,
                          parent: String? = nil, strings: [String] = []) {
        r.register(token: token, id: id, screen: screen, parent: parent, role: .button, strings: strings,
                   file: "SampleApp/ListView.swift", line: 7, bounds: { rect })
    }

    func testRegisteredAnchorCarriesEveryField() {
        let r = AnchorRegistry()
        register(r, UUID(), "sample.list.addButton", CGRect(x: 300, y: 752, width: 60, height: 60),
                 screen: "sample.list", parent: "sample.list.footer", strings: ["list.add"])
        let a = r.snapshot()
        XCTAssertEqual(a.count, 1)
        XCTAssertEqual(a[0].id, "sample.list.addButton")
        XCTAssertEqual(a[0].screen, "sample.list")
        XCTAssertEqual(a[0].parent, "sample.list.footer")
        XCTAssertEqual(a[0].role, .button)
        XCTAssertEqual(a[0].bounds, CGRect(x: 300, y: 752, width: 60, height: 60))
        XCTAssertEqual(a[0].strings, ["list.add"])
        XCTAssertEqual(a[0].file, "SampleApp/ListView.swift")
        XCTAssertEqual(a[0].line, 7)
    }

    func testTwoViewsWithOneIdAreBothKept() {
        let r = AnchorRegistry()
        register(r, UUID(), "sample.list.row", CGRect(x: 0, y: 0, width: 100, height: 40))
        register(r, UUID(), "sample.list.row", CGRect(x: 0, y: 40, width: 100, height: 40))
        XCTAssertEqual(r.snapshot().count, 2)
    }

    func testRegisteringAgainUnderTheSameTokenReplacesAndKeepsTheOrder() {
        let r = AnchorRegistry()
        let t = UUID()
        register(r, t, "a.one", CGRect(x: 0, y: 0, width: 10, height: 10))
        register(r, UUID(), "a.two", CGRect(x: 0, y: 0, width: 10, height: 10))
        register(r, t, "a.renamed", CGRect(x: 0, y: 0, width: 10, height: 10))
        XCTAssertEqual(r.snapshot().map(\.id), ["a.renamed", "a.two"])
    }

    func testBoundsAreReadAtSnapshotTime() {
        let r = AnchorRegistry()
        var rect = CGRect(x: 0, y: 100, width: 50, height: 50)
        r.register(token: UUID(), id: "a.b", screen: nil, parent: nil, role: .cell, strings: [], file: "F.swift", line: 1, bounds: { rect })
        XCTAssertEqual(r.snapshot()[0].bounds.minY, 100)
        rect.origin.y = 40                     // the list scrolled
        XCTAssertEqual(r.snapshot()[0].bounds.minY, 40)
    }

    func testEmptyBoundsAreLeftOutAndGoneViewsAreDropped() {
        let r = AnchorRegistry()
        register(r, UUID(), "a.hidden", CGRect.zero)
        register(r, UUID(), "a.gone", nil)
        register(r, UUID(), "a.shown", CGRect(x: 0, y: 0, width: 5, height: 5))
        XCTAssertEqual(r.snapshot().map(\.id), ["a.shown"])
        XCTAssertEqual(r.snapshot().count, 1)
    }

    func testRemoveByToken() {
        let r = AnchorRegistry()
        let t = UUID()
        register(r, t, "a.b", CGRect(x: 0, y: 0, width: 5, height: 5))
        r.remove(token: t)
        XCTAssertTrue(r.snapshot().isEmpty)
    }

    func testScreenResolution() {
        XCTAssertEqual(AnchorRegistry.resolveScreen(id: "trip.timeline.addButton", environment: "trip.other", current: "x"), "trip.other")
        XCTAssertEqual(AnchorRegistry.resolveScreen(id: "trip.timeline.addButton", environment: nil, current: "x"), "trip.timeline")
        XCTAssertEqual(AnchorRegistry.resolveScreen(id: "addButton", environment: nil, current: "trip.timeline"), "trip.timeline")
        XCTAssertNil(AnchorRegistry.resolveScreen(id: "addButton", environment: nil, current: nil))
    }

    func testCurrentScreen() {
        let r = AnchorRegistry()
        XCTAssertNil(r.currentScreen)
        r.setScreen("trip.timeline")
        XCTAssertEqual(r.currentScreen, "trip.timeline")
        r.reset()
        XCTAssertNil(r.currentScreen)
    }
}

final class HitTestTests: XCTestCase {
    private let footer = Fixtures.anchor("sample.list.footer", CGRect(x: 0, y: 732, width: 390, height: 112), seq: 1, role: .container)
    private let button = Fixtures.anchor("sample.list.addButton", CGRect(x: 300, y: 752, width: 60, height: 60), seq: 2, parent: "sample.list.footer")

    func testTheSmallestAnchorUnderThePointWins() {
        XCTAssertEqual(HitTester.hit(x: 331.5, y: 782, in: [footer, button])?.id, "sample.list.addButton")
        XCTAssertEqual(HitTester.hit(x: 331.5, y: 782, in: [button, footer])?.id, "sample.list.addButton")
    }

    func testThePointOutsideTheChildFallsBackToTheParent() {
        XCTAssertEqual(HitTester.hit(x: 20, y: 760, in: [footer, button])?.id, "sample.list.footer")
    }

    func testNothingUnderThePoint() {
        XCTAssertNil(HitTester.hit(x: 20, y: 100, in: [footer, button]))
        XCTAssertNil(HitTester.hit(x: 1, y: 1, in: []))
    }

    func testEdges() {
        XCTAssertNotNil(HitTester.hit(x: 300, y: 752, in: [button]))           // left/top edge is inside
        XCTAssertNil(HitTester.hit(x: 360, y: 782, in: [button]))              // right edge is outside
        XCTAssertNil(HitTester.hit(x: 330, y: 812, in: [button]))              // bottom edge is outside
    }

    func testEqualAreaTieGoesToTheLaterRegistration() {
        let a = Fixtures.anchor("a.under", CGRect(x: 0, y: 0, width: 50, height: 50), seq: 1)
        let b = Fixtures.anchor("a.over", CGRect(x: 10, y: 10, width: 50, height: 50), seq: 2)
        XCTAssertEqual(HitTester.hit(x: 20, y: 20, in: [a, b])?.id, "a.over")
        XCTAssertEqual(HitTester.hit(x: 20, y: 20, in: [b, a])?.id, "a.over")
    }

    func testEmptyAnchorsAreIgnored() {
        let empty = Fixtures.anchor("a.empty", CGRect(x: 10, y: 10, width: 0, height: 0), seq: 3)
        XCTAssertNil(HitTester.hit(x: 10, y: 10, in: [empty]))
    }

    func testScreenChoice() {
        XCTAssertEqual(HitTester.screen(current: "trip.timeline", hit: button, anchors: [button]), "trip.timeline")
        XCTAssertEqual(HitTester.screen(current: nil, hit: button, anchors: []), "sample.list")
        let other = Fixtures.anchor("b.x", CGRect(x: 0, y: 0, width: 5, height: 5), screen: "b")
        let two = Fixtures.anchor("b.y", CGRect(x: 0, y: 0, width: 5, height: 5), seq: 2, screen: "b")
        XCTAssertEqual(HitTester.screen(current: nil, hit: nil, anchors: [footer, other, two]), "b")
        XCTAssertNil(HitTester.screen(current: nil, hit: nil, anchors: []))
    }
}

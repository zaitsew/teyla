import AppKit
import XCTest

@MainActor
final class ProductIconsTests: XCTestCase {
    override func setUp() {
        super.setUp()
        ProductIcons.reset()
    }

    /// A small JPEG of the given side, made here so no real icon sits in the repo. Another side is another string.
    private func jpeg(side: Int) throws -> String {
        let rep = try XCTUnwrap(NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: side, pixelsHigh: side, bitsPerSample: 8,
                                                 samplesPerPixel: 3, hasAlpha: false, isPlanar: false,
                                                 colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
        for x in 0..<side { for y in 0..<side { rep.setColor(NSColor(white: CGFloat(x + y) / CGFloat(2 * side), alpha: 1), atX: x, y: y) } }
        let data = try XCTUnwrap(rep.representation(using: .jpeg, properties: [:]))
        return data.base64EncodedString()
    }

    func testAnIconIsDecodedOncePerProductNoMatterHowOftenHomeRedraws() throws {
        let icon = try jpeg(side: 8)
        let first = try XCTUnwrap(ProductIcons.image(id: "a", base64: icon))
        for _ in 0..<50 { XCTAssertTrue(ProductIcons.image(id: "a", base64: icon) === first) }
        XCTAssertEqual(ProductIcons.decodeCount, 1)
        XCTAssertNotNil(ProductIcons.image(id: "b", base64: icon))
        XCTAssertEqual(ProductIcons.decodeCount, 2)
    }

    func testANewIconForTheSameProductIsDecodedAgain() throws {
        _ = ProductIcons.image(id: "a", base64: try jpeg(side: 8))
        _ = ProductIcons.image(id: "a", base64: try jpeg(side: 16))
        XCTAssertEqual(ProductIcons.decodeCount, 2)
    }

    func testNoIconAndABrokenIconBothMeanAMonogram() {
        XCTAssertNil(ProductIcons.image(id: "a", base64: ""))
        XCTAssertEqual(ProductIcons.decodeCount, 0, "an empty string is not worth a decode")
        XCTAssertNil(ProductIcons.image(id: "a", base64: "not base64 at all!"))
        XCTAssertNil(ProductIcons.image(id: "a", base64: "not base64 at all!"))
        XCTAssertEqual(ProductIcons.decodeCount, 1, "a broken icon is remembered as broken")
    }

    func testTheSampleIconsDecode() throws {
        let url = SampleFiles.url("state.sample.home.json")
        let snapshot = try TeylaCLI.decodeSnapshot(Data(contentsOf: url))
        let portfolio = try XCTUnwrap(snapshot.portfolio)
        let app = try XCTUnwrap(portfolio.product("sample-app"))
        XCTAssertNotNil(ProductIcons.image(id: app.id, base64: app.iconJPEG))
    }
}

import CoreGraphics
import ImageIO
import XCTest
@testable import TeylaReview

final class ReviewBitmapTests: XCTestCase {
    /// A solid picture of `width` x `height` pixels.
    private func solid(_ width: Int, _ height: Int, red: CGFloat = 1, green: CGFloat = 1, blue: CGFloat = 1, alpha: CGFloat = 1) -> CGImage {
        let ctx = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8, bytesPerRow: width * 4,
                            space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)!
        ctx.setFillColor(CGColor(red: red, green: green, blue: blue, alpha: alpha))
        ctx.fill(CGRect(x: 0, y: 0, width: width, height: height))
        return ctx.makeImage()!
    }

    private func isBlack(_ p: ReviewBitmap.Pixels, _ x: Int, _ y: Int) -> Bool {
        let c = p.rgba(x: x, y: y)
        return c.r == 0 && c.g == 0 && c.b == 0 && c.a == 255
    }

    // MARK: painting the private areas

    func testAPrivateRectangleIsBlackWhereTheCaptureCountsFromTheTop() throws {
        let image = try XCTUnwrap(ReviewBitmap.blackOut(solid(20, 10), rects: [CGRect(x: 4, y: 1, width: 6, height: 3)], scale: 1))
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: image))
        XCTAssertTrue(isBlack(p, 4, 1)); XCTAssertTrue(isBlack(p, 9, 3))          // inside, top row of the picture first
        XCTAssertFalse(isBlack(p, 3, 1)); XCTAssertFalse(isBlack(p, 10, 1))       // left and right of it
        XCTAssertFalse(isBlack(p, 4, 0)); XCTAssertFalse(isBlack(p, 4, 4))        // above and below it
        XCTAssertFalse(isBlack(p, 4, 9))                                          // the bottom is untouched
    }

    func testTheRectangleIsInPointsAndTheBitmapInPixels() throws {
        let image = try XCTUnwrap(ReviewBitmap.blackOut(solid(40, 20), rects: [CGRect(x: 4, y: 1, width: 6, height: 3)], scale: 2))
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: image))
        XCTAssertTrue(isBlack(p, 8, 2)); XCTAssertTrue(isBlack(p, 19, 7))
        XCTAssertFalse(isBlack(p, 7, 2)); XCTAssertFalse(isBlack(p, 20, 2)); XCTAssertFalse(isBlack(p, 8, 8))
    }

    func testAFractionalRectangleIsGrownOutwardToWholePixels() throws {
        let image = try XCTUnwrap(ReviewBitmap.blackOut(solid(10, 10), rects: [CGRect(x: 2.4, y: 2.4, width: 1.2, height: 1.2)], scale: 1))
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: image))
        XCTAssertTrue(isBlack(p, 2, 2)); XCTAssertTrue(isBlack(p, 3, 3))
        XCTAssertFalse(isBlack(p, 4, 4))
    }

    func testARectangleThatIsNotANumberHidesTheWholePicture() throws {
        for bad in [CGRect(x: CGFloat.nan, y: 0, width: 4, height: 4), CGRect(x: 0, y: 0, width: CGFloat.infinity, height: 4),
                    CGRect(x: 0, y: CGFloat.infinity, width: 4, height: 4), .null] {
            let image = try XCTUnwrap(ReviewBitmap.blackOut(solid(8, 8), rects: [bad], scale: 1))
            let p = try XCTUnwrap(ReviewBitmap.pixels(of: image))
            XCTAssertTrue((0..<8).allSatisfy { y in (0..<8).allSatisfy { isBlack(p, $0, y) } }, "\(bad) must hide everything")
        }
    }

    func testARectangleOutsideThePictureChangesNothing() throws {
        let image = try XCTUnwrap(ReviewBitmap.blackOut(solid(8, 8), rects: [CGRect(x: 100, y: 100, width: 5, height: 5)], scale: 1))
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: image))
        XCTAssertFalse(isBlack(p, 0, 0)); XCTAssertFalse(isBlack(p, 7, 7))
    }

    func testTheBackgroundFillsTransparentHolesButNotThePainting() throws {
        let hole = solid(6, 6, alpha: 0)
        let image = try XCTUnwrap(ReviewBitmap.blackOut(hole, rects: [], scale: 1, background: CGColor(red: 1, green: 1, blue: 1, alpha: 1)))
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: image))
        XCTAssertEqual(p.rgba(x: 3, y: 3).a, 255)
        XCTAssertEqual(p.rgba(x: 3, y: 3).r, 255)
    }

    // MARK: a picture that came out empty

    func testATransparentPictureIsBlank() throws {
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: solid(100, 80, alpha: 0)))
        let all = CGRect(x: 0, y: 0, width: 100, height: 80)
        XCTAssertTrue(ReviewBitmap.isTransparent(p, rect: all, scale: 1))
        XCTAssertTrue(ReviewBitmap.isBlank(p, rect: all, scale: 1))
    }

    func testAPictureWithContentIsNotBlankAndAFlatWindowIsNotTransparent() throws {
        // Left half white, right half red-to-blue stripes.
        let ctx = CGContext(data: nil, width: 100, height: 80, bitsPerComponent: 8, bytesPerRow: 400, space: CGColorSpace(name: CGColorSpace.sRGB)!,
                            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)!
        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: 50, height: 80))
        for x in stride(from: 50, to: 100, by: 5) {
            ctx.setFillColor(CGColor(red: CGFloat(x - 50) / 50, green: 0.2, blue: 1 - CGFloat(x - 50) / 50, alpha: 1))
            ctx.fill(CGRect(x: x, y: 0, width: 5, height: 80))
        }
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: ctx.makeImage()!))
        XCTAssertFalse(ReviewBitmap.isBlank(p, rect: CGRect(x: 0, y: 0, width: 100, height: 80), scale: 1))
        XCTAssertTrue(ReviewBitmap.isBlank(p, rect: CGRect(x: 0, y: 0, width: 40, height: 80), scale: 1))      // the flat white half
        XCTAssertFalse(ReviewBitmap.isTransparent(p, rect: CGRect(x: 0, y: 0, width: 100, height: 80), scale: 1))
    }

    func testARegionOutsideThePictureIsNotCalledBlank() throws {
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: solid(10, 10, alpha: 0)))
        XCTAssertFalse(ReviewBitmap.isTransparent(p, rect: CGRect(x: 50, y: 50, width: 5, height: 5), scale: 1))
        XCTAssertEqual(ReviewBitmap.emptyFraction(p, rect: CGRect(x: 50, y: 50, width: 5, height: 5), scale: 1), 0)
    }

    // MARK: the PNG

    func testThePNGDecodesToTheSameSizeAndKeepsThePainting() throws {
        let painted = try XCTUnwrap(ReviewBitmap.blackOut(solid(30, 20), rects: [CGRect(x: 0, y: 0, width: 10, height: 10)], scale: 1))
        let data = try XCTUnwrap(ReviewBitmap.pngData(painted))
        XCTAssertEqual(Array(data.prefix(8)), [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])
        let source = try XCTUnwrap(CGImageSourceCreateWithData(data as CFData, nil))
        let decoded = try XCTUnwrap(CGImageSourceCreateImageAtIndex(source, 0, nil))
        XCTAssertEqual(decoded.width, 30); XCTAssertEqual(decoded.height, 20)
        let p = try XCTUnwrap(ReviewBitmap.pixels(of: decoded))
        XCTAssertTrue(isBlack(p, 2, 2)); XCTAssertFalse(isBlack(p, 20, 15))
    }
}

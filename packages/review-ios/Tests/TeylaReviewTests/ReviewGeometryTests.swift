import CoreGraphics
import XCTest
@testable import TeylaReview

final class ReviewGeometryTests: XCTestCase {
    private let window = CGSize(width: 400, height: 800)

    func testTheWholeWindowFitsAndKeepsItsProportions() {
        XCTAssertEqual(ReviewGeometry.fit(window, in: CGSize(width: 400, height: 400)), 0.5)
        XCTAssertEqual(ReviewGeometry.fit(window, in: CGSize(width: 100, height: 800)), 0.25)
    }

    func testThePictureNeverGrowsAndNeverInverts() {
        XCTAssertEqual(ReviewGeometry.fit(window, in: CGSize(width: 2000, height: 2000)), 1)
        XCTAssertEqual(ReviewGeometry.fit(window, in: CGSize(width: -10, height: 100)), 0)
        XCTAssertEqual(ReviewGeometry.fit(.zero, in: window), 1)
    }

    func testAPointOnTheShrunkenPictureIsAWindowPoint() {
        XCTAssertEqual(ReviewGeometry.toWindow(CGPoint(x: 50, y: 100), scale: 0.5, window: window), CGPoint(x: 100, y: 200))
    }

    func testAPointIsKeptInsideTheWindow() {
        XCTAssertEqual(ReviewGeometry.toWindow(CGPoint(x: -5, y: 900), scale: 0.5, window: window), CGPoint(x: 0, y: 800))
        XCTAssertEqual(ReviewGeometry.toWindow(CGPoint(x: 5, y: 5), scale: 0, window: window), .zero)
    }

    /// The area a finger drew through these points on the picture, at half scale.
    private func area(_ points: [(CGFloat, CGFloat)]) -> CGRect? {
        let start = CGRect(x: points[0].0, y: points[0].1, width: 0, height: 0)
        let stroke = points.reduce(start) { ReviewGeometry.grow($0, with: CGPoint(x: $1.0, y: $1.1)) }
        return ReviewGeometry.region(stroke: stroke, scale: 0.5, window: window)
    }

    func testAShortDragIsATap() {
        XCTAssertNil(area([(10, 10), (15, 18)]))
    }

    func testADragInAnyDirectionIsTheSameAreaInWindowPoints() {
        let expected = CGRect(x: 20, y: 40, width: 100, height: 200)
        XCTAssertEqual(area([(10, 20), (60, 120)]), expected)
        XCTAssertEqual(area([(60, 120), (10, 20)]), expected)
    }

    func testAClosedCircleIsTheAreaItEncloses() {
        // The finger ends where it began, so only the points between say how big the circle was.
        XCTAssertEqual(area([(35, 20), (60, 70), (35, 120), (10, 70), (35, 21)]), CGRect(x: 20, y: 40, width: 100, height: 200))
    }

    func testADragPastTheEdgeStopsAtTheWindow() {
        XCTAssertEqual(area([(150, 350), (300, 600)]), CGRect(x: 300, y: 700, width: 100, height: 100))
    }

    func testARegionIsLeftOutOfTheCaptureWhenThereIsNone() throws {
        let plain = try CaptureCoding.encoder().encode(Fixtures.record())
        XCTAssertFalse(String(decoding: plain, as: UTF8.self).contains("\"region\""))
    }

    func testARegionIsWrittenInWindowPoints() throws {
        var record = Fixtures.record()
        record.region = Rect(CGRect(x: 20, y: 40, width: 100, height: 200))
        let data = try CaptureCoding.encoder().encode(record)
        let again = try CaptureCoding.decoder().decode(CaptureRecord.self, from: data)
        XCTAssertEqual(again.region, Rect(x: 20, y: 40, width: 100, height: 200))
    }
}

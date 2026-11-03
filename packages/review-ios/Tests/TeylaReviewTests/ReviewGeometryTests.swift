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

    func testAShortDragIsATap() {
        XCTAssertNil(ReviewGeometry.region(from: CGPoint(x: 10, y: 10), to: CGPoint(x: 15, y: 18), scale: 0.5, window: window))
    }

    func testADragInAnyDirectionIsTheSameAreaInWindowPoints() {
        let expected = CGRect(x: 20, y: 40, width: 100, height: 200)
        XCTAssertEqual(ReviewGeometry.region(from: CGPoint(x: 10, y: 20), to: CGPoint(x: 60, y: 120), scale: 0.5, window: window), expected)
        XCTAssertEqual(ReviewGeometry.region(from: CGPoint(x: 60, y: 120), to: CGPoint(x: 10, y: 20), scale: 0.5, window: window), expected)
    }

    func testADragPastTheEdgeStopsAtTheWindow() {
        let area = ReviewGeometry.region(from: CGPoint(x: 150, y: 350), to: CGPoint(x: 300, y: 600), scale: 0.5, window: window)
        XCTAssertEqual(area, CGRect(x: 300, y: 700, width: 100, height: 100))
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

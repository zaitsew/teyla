#if TEYLA_REVIEW && os(macOS)
import AppKit
import XCTest
@testable import TeylaReview

/// SEC-9: secure text fields are masked in every picture without `.reviewPrivate()`, as on the web. The AppKit side runs
/// here on the Mac (a view tree needs no window). The UIKit twin (`SensitiveFields`) cannot compile for macOS: it is only
/// type-checked against the iOS SDK.
@MainActor
final class MacSensitiveFieldsTests: XCTestCase {
    private func content() -> NSView { NSView(frame: NSRect(x: 0, y: 0, width: 300, height: 200)) }

    func testASecureTextFieldIsMaskedAndAPlainOneIsNot() {
        let root = content()
        let secure = NSSecureTextField(frame: NSRect(x: 10, y: 20, width: 100, height: 30))
        let plain = NSTextField(frame: NSRect(x: 10, y: 100, width: 100, height: 30))
        root.addSubview(secure)
        root.addSubview(plain)
        // AppKit counts from the bottom: y 20..50 is 150..180 from the top of a 200-point content view.
        XCTAssertEqual(MacProbe.sensitiveFrames(under: root), [CGRect(x: 10, y: 150, width: 100, height: 30)])
    }

    func testAFieldWithAPasswordOrCardContentTypeIsMasked() {
        let root = content()
        for type in [NSTextContentType.password, .oneTimeCode, .creditCardNumber] {
            let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 50, height: 20))
            field.contentType = type
            root.addSubview(field)
        }
        XCTAssertEqual(MacProbe.sensitiveFrames(under: root).count, 3)
    }

    func testANestedHiddenOrInvisibleSecureFieldIsFoundOrSkippedAsItIs() {
        let root = content()
        let box = NSView(frame: NSRect(x: 50, y: 50, width: 200, height: 100))
        let inner = NSSecureTextField(frame: NSRect(x: 5, y: 5, width: 80, height: 20))
        box.addSubview(inner)
        root.addSubview(box)
        XCTAssertEqual(MacProbe.sensitiveFrames(under: root), [CGRect(x: 55, y: 125, width: 80, height: 20)])
        inner.isHidden = true
        XCTAssertTrue(MacProbe.sensitiveFrames(under: root).isEmpty)
        inner.isHidden = false
        box.isHidden = true
        XCTAssertTrue(MacProbe.sensitiveFrames(under: root).isEmpty)
    }

    func testSensitiveFramesBecomeMasksNextToThePrivateOnes() {
        let root = content()
        root.addSubview(NSSecureTextField(frame: NSRect(x: 10, y: 20, width: 100, height: 30)))
        let masks = ReviewMasking.rects(for: [CGRect(x: 200, y: 10, width: 20, height: 20)] + MacProbe.sensitiveFrames(under: root),
                                        in: CGRect(origin: .zero, size: root.bounds.size), scale: 2)
        XCTAssertEqual(masks.count, 2)
        XCTAssertTrue(masks.contains { $0.contains(CGPoint(x: 60, y: 165)) })
    }
}
#endif

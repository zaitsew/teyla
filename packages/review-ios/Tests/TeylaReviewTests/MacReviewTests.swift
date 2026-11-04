import CoreGraphics
import XCTest
@testable import TeylaReview

final class MacReviewTests: XCTestCase {
    // MARK: the frozen masks against the live window

    func testMasksInTheSamePlaceAreUnchanged() {
        let a = CGRect(x: 10, y: 20, width: 50, height: 30), b = CGRect(x: 10, y: 80, width: 50, height: 30)
        XCTAssertTrue(ReviewRedaction.masksUnchanged(frozen: [a, b], live: [b, a.offsetBy(dx: 0.5, dy: 0.5)]))
        XCTAssertTrue(ReviewRedaction.masksUnchanged(frozen: [], live: []))
    }

    func testAScrolledMaskIsAChange() {
        let a = CGRect(x: 10, y: 20, width: 50, height: 30)
        XCTAssertFalse(ReviewRedaction.masksUnchanged(frozen: [a], live: [a.offsetBy(dx: 0, dy: 40)]))
    }

    func testAMaskThatAppearedOrLeftIsAChange() {
        let a = CGRect(x: 10, y: 20, width: 50, height: 30)
        XCTAssertFalse(ReviewRedaction.masksUnchanged(frozen: [], live: [a]))
        XCTAssertFalse(ReviewRedaction.masksUnchanged(frozen: [a], live: []))
    }

    // MARK: which screen a window is on

    func testTheWindowsOwnAnchorsNameItsScreen() {
        let r = CGRect(x: 0, y: 0, width: 10, height: 10)
        let anchors = [Fixtures.anchor("a", r, screen: "first"), Fixtures.anchor("b", r, screen: "second"), Fixtures.anchor("c", r, screen: "second")]
        XCTAssertEqual(AnchorRegistry.screen(of: anchors, otherwise: "other.window"), "second")
    }

    func testAWindowWithNoAnchorsFallsBack() {
        XCTAssertEqual(AnchorRegistry.screen(of: [], otherwise: "registry"), "registry")
        let unnamed = Fixtures.anchor("a", CGRect(x: 0, y: 0, width: 10, height: 10), screen: nil)
        XCTAssertEqual(AnchorRegistry.screen(of: [unnamed], otherwise: "registry"), "registry")
    }

    // MARK: AppKit counts from the bottom

    func testAFrameFromTheBottomLeftBecomesATopLeftFrame() {
        let r = MacGeometry.topLeft(CGRect(x: 10, y: 20, width: 50, height: 30), containerHeight: 200, flipped: false)
        XCTAssertEqual(r, CGRect(x: 10, y: 150, width: 50, height: 30))
    }

    func testAFlippedViewAlreadyCountsFromTheTop() {
        let r = CGRect(x: 10, y: 20, width: 50, height: 30)
        XCTAssertEqual(MacGeometry.topLeft(r, containerHeight: 200, flipped: true), r)
    }

    func testAPointRoundTripsBetweenTheTwoOrigins() {
        let p = CGPoint(x: 12, y: 40)
        let view = MacGeometry.viewPoint(fromTopLeft: p, containerHeight: 200, flipped: false)
        XCTAssertEqual(view, CGPoint(x: 12, y: 160))
        XCTAssertEqual(MacGeometry.viewPoint(fromTopLeft: view, containerHeight: 200, flipped: false), p)
        XCTAssertEqual(MacGeometry.viewPoint(fromTopLeft: p, containerHeight: 200, flipped: true), p)
    }

    func testAScreenFrameIsPlacedInTheWindowContent() {
        let content = CGRect(x: 100, y: 300, width: 400, height: 200)        // screen coordinates, origin bottom left
        let element = CGRect(x: 120, y: 450, width: 80, height: 20)          // 30 points under the content's top edge
        XCTAssertEqual(MacGeometry.topLeft(inScreen: element, content: content), CGRect(x: 20, y: 30, width: 80, height: 20))
    }

    // MARK: a view that cannot say where it is

    func testAFrameThatIsNotANumberBecomesTheWholeWindow() {
        let window = CGRect(x: 0, y: 0, width: 800, height: 600)
        XCTAssertEqual(MacGeometry.maskFrame(CGRect(x: CGFloat.nan, y: 0, width: 10, height: 10), container: window), window)
        XCTAssertEqual(MacGeometry.maskFrame(CGRect(x: 0, y: 0, width: CGFloat.infinity, height: 10), container: window), window)
        XCTAssertEqual(MacGeometry.maskFrame(.infinite, container: window), window)
        XCTAssertEqual(MacGeometry.maskFrame(CGRect(x: 5, y: 5, width: 10, height: 10), container: window), CGRect(x: 5, y: 5, width: 10, height: 10))
        XCTAssertEqual(MacGeometry.maskFrame(CGRect(x: 0, y: CGFloat.infinity, width: 10, height: 10), container: window), window)
        XCTAssertEqual(MacGeometry.maskFrame(.null, container: window), window, "no frame at all hides everything")
    }

    func testTheWholeWindowFrameSurvivesTheMaskingRules() {
        let window = CGRect(x: 0, y: 0, width: 800, height: 600)
        let frame = MacGeometry.maskFrame(CGRect(x: CGFloat.nan, y: 0, width: 1, height: 1), container: window)
        let masks = ReviewMasking.rects(for: [frame], in: window, scale: 2)
        XCTAssertEqual(masks, [window])
        // The tap on anything is then private: no identifier or label is kept.
        let pointed = ReviewRedaction.pointed(hit: nil, identifier: "settings.name", label: "Name", point: CGPoint(x: 400, y: 300),
                                              region: nil, frames: masks)
        XCTAssertNil(pointed.identifier); XCTAssertNil(pointed.label)
    }

    // MARK: the review window

    func testTheReviewWindowFitsTheScreenAndKeepsTheFormBeside() {
        let big = MacLayout.windowSize(for: CGSize(width: 3000, height: 2000), visible: CGSize(width: 1440, height: 900))
        XCTAssertLessThanOrEqual(big.width, 1440 * 0.9); XCTAssertLessThanOrEqual(big.height, 900 * 0.9)
        let small = MacLayout.windowSize(for: CGSize(width: 300, height: 200), visible: CGSize(width: 1440, height: 900))
        XCTAssertGreaterThanOrEqual(small.width, MacLayout.minimum.width); XCTAssertGreaterThanOrEqual(small.height, MacLayout.minimum.height)
        XCTAssertEqual(MacLayout.windowSize(for: .zero, visible: CGSize(width: 1000, height: 800)).width, MacLayout.minimum.width)
    }

    // MARK: the shortcut

    func testTheMacShortcutIsControlOptionCommandF() {
        let s = ReviewShortcut.mac
        XCTAssertEqual(s.key, "f")
        XCTAssertTrue(s.control && s.option && s.command)
        XCTAssertFalse(s.shift)
        XCTAssertEqual(s.display, "⌃⌥⌘F")
    }

    func testTheMacShortcutIsNotAKnownSystemOrAppShortcut() {
        XCTAssertFalse(ReviewShortcut.knownClashes.contains(ReviewShortcut.mac))
        // Every known clash uses fewer modifiers than ours, or shift: ours is the only one with all three.
        XCTAssertTrue(ReviewShortcut.knownClashes.allSatisfy { !($0.control && $0.option && $0.command) })
    }

    // MARK: the second lock on the Mac

    func testOnlyTheStoreEnvironmentRefusesTheForm() {
        func permits(_ e: BuildChannel.StoreEnvironment?, debug: Bool = false) -> Bool {
            BuildChannel.detectMac(isDebug: debug, environment: e).permitsReview
        }
        XCTAssertTrue(permits(.xcode))
        XCTAssertTrue(permits(.sandbox))
        XCTAssertFalse(permits(.production))
        XCTAssertFalse(permits(nil), "an error or an unknown answer refuses the form")
        XCTAssertTrue(permits(nil, debug: true), "a debug build never asks StoreKit")
        XCTAssertTrue(BuildChannel.debug.permitsReview && BuildChannel.local.permitsReview && BuildChannel.testflight.permitsReview)
        XCTAssertFalse(BuildChannel.appStore.permitsReview)
    }

    // MARK: the record a Mac capture writes

    private func session(frames: [CGRect] = []) -> ReviewSession {
        let env = EnvironmentInfo(os: "macOS 15.1", model: "Mac15,6", locale: "en_US", language: "en", appearance: "light",
                                  dynamicType: "unspecified", screen: ScreenSize(width: 1200, height: 800, scale: 2))
        return ReviewSession(device: AppProbe.sanitizeDevice("Mac"), app: Fixtures.app, environment: env, currentScreen: "trip.map",
                             anchors: [Fixtures.anchor("trip.map.pin", CGRect(x: 100, y: 100, width: 40, height: 40), strings: ["map.pin"])],
                             privateFrames: frames, png: Data([1, 2, 3]), pixelWidth: 2400, pixelHeight: 1600, scale: 2,
                             microphone: MicrophoneInfo(hostAudioInUse: false, category: nil))
    }

    func testAMacCaptureIsTextWithNoMicrophoneCategoryAndStaysVersion1() throws {
        let draft = ReviewDraft(tap: CGPoint(x: 110, y: 110), region: nil, hit: Fixtures.anchor("trip.map.pin", CGRect(x: 100, y: 100, width: 40, height: 40)),
                                accessibilityIdentifier: "map.pin.ax", accessibilityLabel: "Pin", text: "Pin is in the sea", input: .text)
        let record = session().record(for: draft)
        XCTAssertEqual(record.v, 1)
        XCTAssertEqual(record.device, "Mac")
        XCTAssertEqual(record.comment.input, .text)
        XCTAssertEqual(record.screenshot.width, 2400); XCTAssertEqual(record.screenshot.scale, 2)
        XCTAssertEqual(record.element?.id, "trip.map.pin")
        let json = try String(decoding: CaptureCoding.encoder().encode(record), as: UTF8.self)
        XCTAssertTrue(json.contains("\"input\" : \"text\""))
        XCTAssertFalse(json.contains("\"category\""), "no audio session on a Mac")
    }

    func testAClickOnAPrivateAreaOnTheMacRecordsNoElementIdentifierOrLabel() {
        let frame = CGRect(x: 90, y: 90, width: 100, height: 100)
        let draft = ReviewDraft(tap: CGPoint(x: 110, y: 110), region: nil, hit: Fixtures.anchor("trip.map.pin", CGRect(x: 100, y: 100, width: 40, height: 40)),
                                accessibilityIdentifier: "friend.name", accessibilityLabel: "Anna K.", text: "Wrong", input: .text)
        let record = session(frames: [frame]).record(for: draft)
        XCTAssertNil(record.element)
        XCTAssertNil(record.tap?.accessibilityIdentifier)
        XCTAssertNil(record.tap?.accessibilityLabel)
    }
}

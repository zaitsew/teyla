import CoreGraphics
import Foundation

/// What the tester entered in the overlay.
struct ReviewDraft {
    var tap: CGPoint?
    var region: CGRect?
    var hit: Anchor?
    var accessibilityIdentifier: String?
    var accessibilityLabel: String?
    var text: String
    var input: CommentInfo.Input
}

/// Everything one review mode opening froze when it opened: the picture, the anchors, the private
/// frames. It turns the tester's draft into the capture record. Both platforms build their record
/// here, so the privacy rules (`ReviewRedaction`) are written once. No UIKit or AppKit.
struct ReviewSession {
    /// One id for every send attempt, so a retry overwrites the failed one.
    var captureID = UUID()
    var device: String
    var app: AppInfo
    var environment: EnvironmentInfo
    var currentScreen: String?
    /// Already free of the string keys that overlap a private frame (`ReviewRedaction.anchors`).
    var anchors: [Anchor]
    /// The rectangles painted black in the picture, in window points.
    var privateFrames: [CGRect]
    var png: Data
    var pixelWidth: Int
    var pixelHeight: Int
    var scale: Double
    var microphone: MicrophoneInfo

    func record(for draft: ReviewDraft, now: Date = Date()) -> CaptureRecord {
        // A tap or circle on a private view records no element, identifier or label.
        let pointed = ReviewRedaction.pointed(
            hit: draft.hit, identifier: draft.accessibilityIdentifier, label: draft.accessibilityLabel,
            point: draft.tap, region: draft.region, frames: privateFrames)
        let screen = HitTester.screen(current: currentScreen, hit: pointed.hit, anchors: anchors)
        let tap = draft.tap.map {
            TapInfo(x: Double($0.x).rounded2, y: Double($0.y).rounded2,
                    accessibilityIdentifier: pointed.identifier, accessibilityLabel: pointed.label)
        }
        return CaptureBuilder.make(
            id: captureID, now: now, device: device, app: app, environment: environment, screen: screen, tap: tap,
            region: draft.region.map(Rect.init), element: pointed.hit, accessibilityElementID: pointed.identifier,
            anchors: anchors, text: draft.text, input: draft.input, language: environment.language,
            pngSHA256: ReviewSigner.sha256Hex(png), pixelWidth: pixelWidth, pixelHeight: pixelHeight,
            scale: scale, microphone: microphone)
    }
}

extension MicrophoneState {
    var asInfo: MicrophoneInfo { MicrophoneInfo(hostAudioInUse: hostAudioInUse, category: category) }
}

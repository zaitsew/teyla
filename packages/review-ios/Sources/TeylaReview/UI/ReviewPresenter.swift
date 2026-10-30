#if TEYLA_REVIEW && canImport(UIKit)
import SwiftUI
import UIKit

/// What the owner entered in the overlay.
struct ReviewDraft {
    var tap: CGPoint?
    var hit: Anchor?
    var accessibilityIdentifier: String?
    var accessibilityLabel: String?
    var text: String
    var input: CommentInfo.Input
}

/// Holds the hosting controller weakly, so the overlay's callbacks can dismiss it without keeping
/// it (and the screenshot it shows) alive after it closes.
@MainActor
private final class OverlayHandle {
    weak var controller: UIViewController?
    var finished = false
}

@MainActor
enum ReviewPresenter {
    private static var isPresenting = false
    private static var mic: MicrophoneGuard?

    static func present() {
        guard !isPresenting, let window = DeviceProbe.keyWindow(),
              let top = DeviceProbe.topViewController(from: window.rootViewController) else { return }
        let config = TeylaReview.configuration
        config.willBegin?()
        let guardian = MicrophoneGuard(session: SystemAudioSession(), hostAudioInUse: config.hostAudioInUse)
        let micState = guardian.begin()
        guard let shot = DeviceProbe.screenshot(of: window) else {
            guardian.end()
            config.didEnd?()
            return
        }
        mic = guardian
        isPresenting = true

        let anchors = AnchorRegistry.shared.snapshot()
        let environment = DeviceProbe.environment(window: window)
        let app = AppProbe.current()
        let currentScreen = AnchorRegistry.shared.currentScreen
        let windowSize = window.bounds.size
        let captureID = UUID()                    // one id for every send attempt, so a retry overwrites the failed one
        let speech = SpeechCapture()
        let handle = OverlayHandle()

        // Runs once. Stops the recognizer before the guard restores the audio session, so a
        // dictation that was still starting cannot take the microphone after it is given back.
        let finish: () -> Void = {
            guard !handle.finished else { return }
            handle.finished = true
            speech.shutdown()
            handle.controller?.dismiss(animated: false)
            handle.controller = nil
            mic?.end()
            mic = nil
            isPresenting = false
            TeylaReview.configuration.didEnd?()
        }
        let overlay = ReviewOverlay(
            image: UIImage(data: shot.png) ?? UIImage(), size: windowSize, anchors: anchors,
            probe: { [weak window, weak handle] point in
                // The overlay sits in the same window: skip it, or an unanchored control resolves to the overlay.
                guard let window else { return (nil, nil) }
                return DeviceProbe.accessibility(at: point, in: window, excluding: handle?.controller?.view)
            },
            speechEnabled: config.speech, microphone: guardian, speech: speech,
            onCancel: finish,
            onSend: { draft, failed in
                let screen = HitTester.screen(current: currentScreen, hit: draft.hit, anchors: anchors)
                let tap = draft.tap.map {
                    TapInfo(x: Double($0.x).rounded2, y: Double($0.y).rounded2,
                            accessibilityIdentifier: draft.accessibilityIdentifier, accessibilityLabel: draft.accessibilityLabel)
                }
                let record = CaptureBuilder.make(
                    id: captureID, now: Date(), device: DeviceProbe.deviceClass(), app: app, environment: environment, screen: screen, tap: tap,
                    element: draft.hit, accessibilityElementID: draft.accessibilityIdentifier, anchors: anchors,
                    text: draft.text, input: draft.input, language: environment.language,
                    pngSHA256: ReviewSigner.sha256Hex(shot.png), pixelWidth: shot.pixelWidth, pixelHeight: shot.pixelHeight,
                    scale: shot.scale, microphone: micState.asInfo)
                let png = shot.png
                // The overlay closes only after the capture is on the phone. A failed save keeps it open.
                Task { @MainActor in
                    let failure = await Task.detached(priority: .userInitiated) { ReviewDelivery.save(record: record, png: png) }.value
                    if let failure { failed(failure) } else { finish() }
                }
            })
        let host = UIHostingController(rootView: overlay)
        host.modalPresentationStyle = .overFullScreen
        host.view.backgroundColor = .black
        handle.controller = host
        top.present(host, animated: false)
    }
}

extension MicrophoneState {
    var asInfo: MicrophoneInfo { MicrophoneInfo(hostAudioInUse: hostAudioInUse, category: category) }
}
#endif

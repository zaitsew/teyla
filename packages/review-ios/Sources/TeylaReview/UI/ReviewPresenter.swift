#if TEYLA_REVIEW && canImport(UIKit)
import SwiftUI
import UIKit

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

        // The frames painted black, and the anchors with their string keys removed where they overlap one.
        let privateFrames = shot.privateFrames
        let anchors = ReviewRedaction.anchors(AnchorRegistry.shared.snapshot(), frames: privateFrames)
        let environment = DeviceProbe.environment(window: window)
        let app = AppProbe.current()
        let currentScreen = AnchorRegistry.shared.currentScreen
        let windowSize = window.bounds.size
        let session = ReviewSession(
            device: DeviceProbe.deviceClass(), app: app, environment: environment, currentScreen: currentScreen,
            anchors: anchors, privateFrames: privateFrames, png: shot.png, pixelWidth: shot.pixelWidth,
            pixelHeight: shot.pixelHeight, scale: shot.scale, microphone: micState.asInfo)
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
                return DeviceProbe.accessibility(at: point, in: window, excluding: handle?.controller?.view, avoiding: privateFrames)
            },
            speechEnabled: config.speech, microphone: guardian, speech: speech, strings: config.strings(),
            noticeNeeded: { ReviewNotice.isNeeded(sendsToServer: TeylaReview.sendsToServer) },
            acceptNotice: { ReviewNotice.accept() },
            requiresHealthConsent: config.requiresHealthConsent,
            onClose: finish,
            onSend: { draft, report in
                let record = session.record(for: draft)
                let png = shot.png
                // The overlay stays open to say what became of the capture. A failed save keeps the text.
                Task { @MainActor in
                    report(await Task.detached(priority: .userInitiated) { await ReviewDelivery.save(record: record, png: png) }.value)
                }
            })
        let host = UIHostingController(rootView: overlay)
        host.modalPresentationStyle = .overFullScreen
        host.view.backgroundColor = .black
        handle.controller = host
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        top.present(host, animated: false)
    }
}
#endif

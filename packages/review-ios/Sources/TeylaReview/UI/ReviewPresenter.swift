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

        var host: UIHostingController<ReviewOverlay>!
        let finish: () -> Void = {
            host.dismiss(animated: false)
            mic?.end()
            mic = nil
            isPresenting = false
            TeylaReview.configuration.didEnd?()
        }
        let overlay = ReviewOverlay(
            image: UIImage(data: shot.png) ?? UIImage(), size: windowSize, anchors: anchors,
            probe: { DeviceProbe.accessibility(at: $0, in: window) },
            speechEnabled: config.speech, microphone: guardian,
            onCancel: finish,
            onSend: { draft in
                let screen = HitTester.screen(current: currentScreen, hit: draft.hit, anchors: anchors)
                let tap = draft.tap.map {
                    TapInfo(x: Double($0.x).rounded2, y: Double($0.y).rounded2,
                            accessibilityIdentifier: draft.accessibilityIdentifier, accessibilityLabel: draft.accessibilityLabel)
                }
                let record = CaptureBuilder.make(
                    now: Date(), device: DeviceProbe.deviceClass(), app: app, environment: environment, screen: screen, tap: tap,
                    element: draft.hit, accessibilityElementID: draft.accessibilityIdentifier, anchors: anchors,
                    text: draft.text, input: draft.input, language: environment.language,
                    pngSHA256: ReviewSigner.sha256Hex(shot.png), pixelWidth: shot.pixelWidth, pixelHeight: shot.pixelHeight,
                    scale: shot.scale, microphone: micState.asInfo)
                finish()
                Task.detached(priority: .utility) { ReviewDelivery.save(record: record, png: shot.png) }
            })
        host = UIHostingController(rootView: overlay)
        host.modalPresentationStyle = .overFullScreen
        host.view.backgroundColor = .black
        top.present(host, animated: false)
    }
}

extension MicrophoneState {
    var asInfo: MicrophoneInfo { MicrophoneInfo(hostAudioInUse: hostAudioInUse, category: category) }
}

/// Save on the phone first; then, if there is a key and a folder, copy to the relay outbox.
enum ReviewDelivery {
    static func save(record: CaptureRecord, png: Data) {
        let store = CaptureStore(root: CaptureStore.defaultRoot())
        let key = TeylaReview.keyStore.load()
        guard (try? store.save(record: record, png: png, key: key)) != nil else { return }
        guard key != nil else { return }                       // unsigned: it stays on the phone
        _ = TeylaReview.relayFolder.withAccess { try? store.copyToRelay(id: record.id, relayRoot: $0) }
    }

    /// Copies every saved, signed capture that has not reached the relay. Call it when the app
    /// becomes active, or after the owner picks the folder.
    static func retryPending() {
        let store = CaptureStore(root: CaptureStore.defaultRoot())
        guard TeylaReview.keyStore.load() != nil else { return }
        for id in store.list() where store.readLocalStatus(id: id)?.relayCopied == nil {
            _ = TeylaReview.relayFolder.withAccess { try? store.copyToRelay(id: id, relayRoot: $0) }
        }
    }
}
#endif

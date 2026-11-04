#if TEYLA_REVIEW && os(macOS)
import AppKit
import SwiftUI

/// The window that holds the frozen picture and the form. It is a window of its own, so the app's
/// window stays exactly as the tester left it, and closing it (the red button, Escape, Exit or Done)
/// returns to the app with nothing sent.
@MainActor
private final class ReviewWindowDelegate: NSObject, NSWindowDelegate {
    var onClose: (() -> Void)?
    func windowWillClose(_ notification: Notification) { onClose?() }
}

@MainActor
enum ReviewPresenter {
    private static var isPresenting = false
    private static var panel: NSWindow?
    private static var delegate: ReviewWindowDelegate?

    static func present() {
        guard !isPresenting, let window = MacProbe.keyWindow() else { return }
        let config = TeylaReview.configuration
        config.willBegin?()
        let hostAudio = config.hostAudioInUse?() ?? false

        MacCapture.window = window
        defer { MacCapture.window = nil }
        guard let shot = MacProbe.screenshot(of: window) else {
            config.didEnd?()
            return
        }
        isPresenting = true

        let privateFrames = shot.privateFrames
        let anchors = ReviewRedaction.anchors(AnchorRegistry.shared.snapshot(), frames: privateFrames)
        let environment = MacProbe.environment(window: window)
        let size = window.contentView?.bounds.size ?? .zero
        let strings = config.strings()
        let session = ReviewSession(
            device: MacProbe.deviceClass(), app: AppProbe.current(), environment: environment,
            currentScreen: AnchorRegistry.screen(of: anchors, otherwise: AnchorRegistry.shared.currentScreen),
            anchors: anchors, privateFrames: privateFrames,
            png: shot.png, pixelWidth: shot.pixelWidth, pixelHeight: shot.pixelHeight, scale: shot.scale,
            microphone: MicrophoneInfo(hostAudioInUse: hostAudio, category: nil))
        let speech = SpeechCapture()
        let guardian = MicrophoneGuard(session: NoAudioSession())
        let note = (shot.blankAreas.isEmpty && !shot.windowBlank) ? nil : strings.blankNote

        var finished = false
        let finish: () -> Void = {
            guard !finished else { return }
            finished = true
            speech.shutdown()
            let closing = panel
            panel = nil
            delegate?.onClose = nil
            delegate = nil
            closing?.close()
            isPresenting = false
            TeylaReview.configuration.didEnd?()
        }

        let overlay = ReviewOverlay(
            image: ReviewPlatform.image(png: shot.png, size: size), size: size, anchors: anchors,
            probe: { [weak window] point in
                guard let window else { return (nil, nil) }
                // The picture is frozen but the app's window is not. If a private view moved, the
                // frozen rectangles no longer cover it, so the window lends nothing to the capture.
                guard ReviewRedaction.masksUnchanged(frozen: privateFrames, live: MacProbe.livePrivateFrames(of: window, scale: shot.scale)) else {
                    return (nil, nil)
                }
                return MacProbe.accessibility(at: point, in: window, avoiding: privateFrames)
            },
            speechEnabled: false, microphone: guardian, speech: speech, strings: strings, pictureNote: note,
            noticeNeeded: { ReviewNotice.isNeeded(sendsToServer: TeylaReview.sendsToServer) },
            acceptNotice: { ReviewNotice.accept() },
            requiresHealthConsent: config.requiresHealthConsent,
            onClose: finish,
            onSend: { draft, report in
                let record = session.record(for: draft)
                let png = shot.png
                Task { @MainActor in
                    report(await Task.detached(priority: .userInitiated) { await ReviewDelivery.save(record: record, png: png) }.value)
                }
            })

        let host = NSHostingController(rootView: overlay)
        let review = NSWindow(contentViewController: host)
        review.title = strings.windowTitle
        review.styleMask = [.titled, .closable, .resizable]
        review.setContentSize(MacLayout.windowSize(for: size, visible: (window.screen ?? NSScreen.main)?.visibleFrame.size
                                                    ?? CGSize(width: 1440, height: 900)))
        review.contentMinSize = NSSize(width: 760, height: 520)
        review.isReleasedWhenClosed = false
        review.center()
        let watcher = ReviewWindowDelegate()
        watcher.onClose = finish
        review.delegate = watcher
        delegate = watcher
        panel = review
        NSApp.activate(ignoringOtherApps: true)
        review.makeKeyAndOrderFront(nil)
    }
}
#endif

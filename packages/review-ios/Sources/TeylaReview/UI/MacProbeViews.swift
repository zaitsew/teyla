#if TEYLA_REVIEW && os(macOS)
import AppKit
import SwiftUI

/// A hidden view behind a SwiftUI view. It reads its own frame when a capture is taken, so a scrolled
/// list reports where its rows are now. Frames are in window points from the top left of the content
/// of the window being captured (`MacCapture.window`); a view in any other window reports nothing.
final class MacFrameView: NSView {
    var onRemove: (() -> Void)?

    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override func isAccessibilityElement() -> Bool { false }

    /// Read on the main thread, when the picture is taken.
    func currentFrame() -> CGRect? {
        MainActor.assumeIsolated {
            guard let window, window === MacCapture.window, let content = window.contentView else { return .zero }
            let rect = MacGeometry.topLeft(convert(bounds, to: content), containerHeight: content.bounds.height, flipped: content.isFlipped)
            // A frame that is not a number hides the whole window instead of nothing.
            return MacGeometry.maskFrame(rect, container: content.bounds)
        }
    }
}

private struct MacFrameProbe: NSViewRepresentable {
    let register: (MacFrameView) -> Void

    func makeNSView(context: Context) -> MacFrameView {
        let view = MacFrameView()
        register(view)
        return view
    }

    func updateNSView(_ view: MacFrameView, context: Context) { register(view) }

    static func dismantleNSView(_ view: MacFrameView, coordinator: ()) { view.onRemove?() }
}

/// On the Mac the registrations are made whenever the plist key turns review mode on, not only when
/// the install channel is known to be a test build: StoreKit answers after the first views appear.
/// Nothing is recorded into a capture until `present()` has checked the channel.
struct ReviewPrivateModifier: ViewModifier {
    @State private var token = UUID()

    func body(content: Content) -> some View {
        content.background(
            MacFrameProbe { view in
                guard TeylaReview.isEnabled else { return }
                let token = token
                view.onRemove = { PrivateRegistry.shared.remove(token: token) }
                PrivateRegistry.shared.register(token: token, bounds: { [weak view] in
                    guard let view else { return nil }
                    return view.currentFrame()
                })
            }
            .allowsHitTesting(false)
            .accessibilityHidden(true))
    }
}

struct ReviewAnchorModifier: ViewModifier {
    let id: String
    let role: ReviewRole
    let strings: [String]
    let file: String
    let line: Int

    @Environment(\.reviewScreenID) private var screen
    @Environment(\.reviewParentID) private var parent
    @State private var token = UUID()

    func body(content: Content) -> some View {
        content
            .background(
                MacFrameProbe { view in
                    guard TeylaReview.isEnabled else { return }
                    let token = token
                    view.onRemove = { AnchorRegistry.shared.remove(token: token) }
                    let resolved = AnchorRegistry.resolveScreen(id: id, environment: screen, current: AnchorRegistry.shared.currentScreen)
                    AnchorRegistry.shared.register(
                        token: token, id: id, screen: resolved, parent: parent, role: role, strings: strings, file: file, line: line,
                        bounds: { [weak view] in
                            guard let view else { return nil }
                            return view.currentFrame()
                        })
                }
                .allowsHitTesting(false)
                .accessibilityHidden(true)
            )
            .environment(\.reviewParentID, id)
    }
}

/// Retries captures that did not go out when the app comes to the front.
enum ReviewLifecycle {
    private static var installed = false

    static func installOnce() {
        guard !installed else { return }
        installed = true
        NotificationCenter.default.addObserver(forName: NSApplication.didBecomeActiveNotification, object: nil, queue: .main) { _ in
            guard TeylaReview.isActive else { return }
            Task.detached(priority: .utility) { await ReviewDelivery.retryPending() }
        }
    }
}
#endif

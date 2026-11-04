#if TEYLA_REVIEW && canImport(UIKit)
import SwiftUI
import UIKit

/// Registers the view's frame in `PrivateRegistry`. Built like `ReviewAnchorModifier`: a hidden view
/// behind the content has its frame, read in window coordinates when the picture is taken.
struct ReviewPrivateModifier: ViewModifier {
    @State private var token = UUID()

    func body(content: Content) -> some View {
        content.background(PrivateProbe(token: token).allowsHitTesting(false).accessibilityHidden(true))
    }
}

private final class PrivateProbeView: UIView {
    var token: UUID?

    override init(frame: CGRect) {
        super.init(frame: frame)
        isUserInteractionEnabled = false
        backgroundColor = .clear
        isAccessibilityElement = false
    }

    @available(*, unavailable) required init?(coder: NSCoder) { fatalError("not used") }

    var windowBounds: CGRect {
        guard window != nil else { return .zero }
        return convert(bounds, to: nil)
    }
}

private struct PrivateProbe: UIViewRepresentable {
    let token: UUID

    func makeUIView(context: Context) -> UIView {
        let view = PrivateProbeView()
        view.token = token
        register(view)
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        if let view = uiView as? PrivateProbeView { register(view) }
    }

    static func dismantleUIView(_ uiView: UIView, coordinator: ()) {
        if let token = (uiView as? PrivateProbeView)?.token { PrivateRegistry.shared.remove(token: token) }
    }

    private func register(_ view: PrivateProbeView) {
        guard TeylaReview.isActive else { return }       // review mode is off: nothing is recorded
        PrivateRegistry.shared.register(token: token, bounds: { [weak view] in view?.windowBounds })
    }
}
#endif

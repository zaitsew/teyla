#if TEYLA_REVIEW && canImport(UIKit)
import SwiftUI
import UIKit

/// Registers the view under its own token. The probe view sits behind the content and has its frame,
/// so its bounds in window coordinates are the element's bounds, read when a capture is taken.
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
                AnchorProbe(token: token, id: id, screen: screen, parent: parent, role: role, strings: strings, file: file, line: line)
                    .allowsHitTesting(false)
                    .accessibilityHidden(true)
            )
            .environment(\.reviewParentID, id)
    }
}

private final class ProbeView: UIView {
    override init(frame: CGRect) {
        super.init(frame: frame)
        isUserInteractionEnabled = false
        backgroundColor = .clear
        isAccessibilityElement = false
    }

    @available(*, unavailable) required init?(coder: NSCoder) { fatalError("not used") }

    var token: UUID?

    var windowBounds: CGRect {
        guard window != nil else { return .zero }
        return convert(bounds, to: nil)
    }
}

private struct AnchorProbe: UIViewRepresentable {
    let token: UUID
    let id: String
    let screen: String?
    let parent: String?
    let role: ReviewRole
    let strings: [String]
    let file: String
    let line: Int

    func makeUIView(context: Context) -> UIView {
        let view = ProbeView()
        view.token = token
        register(view)
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        if let view = uiView as? ProbeView { register(view) }
    }

    static func dismantleUIView(_ uiView: UIView, coordinator: ()) {
        if let token = (uiView as? ProbeView)?.token { AnchorRegistry.shared.remove(token: token) }
    }

    private func register(_ view: ProbeView) {
        guard TeylaReview.isActive else { return }       // review mode is off in this build: nothing is recorded
        let resolved = AnchorRegistry.resolveScreen(id: id, environment: screen, current: AnchorRegistry.shared.currentScreen)
        AnchorRegistry.shared.register(
            token: token, id: id, screen: resolved, parent: parent, role: role, strings: strings, file: file, line: line,
            bounds: { [weak view] in view?.windowBounds })
    }
}
#endif

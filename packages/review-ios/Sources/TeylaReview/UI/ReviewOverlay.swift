#if TEYLA_REVIEW && canImport(UIKit)
import SwiftUI
import UIKit

/// The frozen screen. The picture is the window at its own size, so a point in the picture is a
/// point in the window and the anchors' bounds line up with it.
struct ReviewOverlay: View {
    let image: UIImage
    let size: CGSize
    let anchors: [Anchor]
    let probe: (CGPoint) -> (identifier: String?, label: String?)
    let speechEnabled: Bool
    let microphone: MicrophoneGuard
    let onCancel: () -> Void
    let onSend: (ReviewDraft) -> Void

    @State private var tap: CGPoint?
    @State private var hit: Anchor?
    @State private var identifier: String?
    @State private var label: String?
    @State private var text = ""
    @State private var input: CommentInfo.Input = .text
    @State private var listening = false
    @State private var speech = SpeechCapture()
    @FocusState private var focused: Bool

    var body: some View {
        ZStack(alignment: .bottom) {
            picture
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .ignoresSafeArea(.all)
            panel
        }
        .background(Color.black)
        .onDisappear { stopListening() }
    }

    private var picture: some View {
        ZStack(alignment: .topLeading) {
            Image(uiImage: image)
                .resizable()
                .frame(width: size.width, height: size.height)
                .gesture(DragGesture(minimumDistance: 0).onEnded { select($0.location) })
                .accessibilityHidden(true)
            if let r = hit?.bounds {
                Rectangle()
                    .stroke(Color.accentColor, lineWidth: 2)
                    .background(Color.accentColor.opacity(0.12))
                    .frame(width: r.width, height: r.height)
                    .position(x: r.midX, y: r.midY)
                    .allowsHitTesting(false)
            }
            if let p = tap {
                Circle()
                    .fill(Color.accentColor)
                    .frame(width: 14, height: 14)
                    .position(p)
                    .allowsHitTesting(false)
            }
        }
        .frame(width: size.width, height: size.height, alignment: .topLeading)
    }

    private var selection: String {
        if let hit { return hit.id }
        if let identifier { return identifier }
        return tap == nil ? "Tap an element, or just describe the screen" : "No element here"
    }

    private var panel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(selection)
                .font(.footnote.monospaced())
                .foregroundStyle(.secondary)
                .lineLimit(1)
            TextField("Say it or type it", text: $text, axis: .vertical)
                .lineLimit(1...4)
                .textFieldStyle(.roundedBorder)
                .focused($focused)
                .accessibilityIdentifier("teyla.review.comment")
            if speechEnabled, speech.isAvailable {
                Button(listening ? "Stop" : "Dictate on device") { toggleListening() }
                    .font(.footnote)
            }
            HStack {
                Button("Cancel", role: .cancel, action: onCancel)
                Spacer()
                Button("Send") { send() }
                    .buttonStyle(.borderedProminent)
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityIdentifier("teyla.review.send")
            }
        }
        .padding(16)
        .background(.regularMaterial)
    }

    private func select(_ point: CGPoint) {
        focused = false
        tap = point
        hit = HitTester.hit(x: Double(point.x), y: Double(point.y), in: anchors)
        let found = probe(point)
        identifier = found.identifier
        label = found.label
    }

    private func toggleListening() {
        if listening { stopListening(); return }
        speech.onText = { heard in
            text = heard
            input = .speech
        }
        Task {
            listening = await speech.start(microphone: microphone)
        }
    }

    private func stopListening() {
        guard listening else { return }
        speech.stop()
        listening = false
    }

    private func send() {
        stopListening()
        let comment = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !comment.isEmpty else { return }
        onSend(ReviewDraft(tap: tap, hit: hit, accessibilityIdentifier: identifier, accessibilityLabel: label, text: comment, input: input))
    }
}
#endif

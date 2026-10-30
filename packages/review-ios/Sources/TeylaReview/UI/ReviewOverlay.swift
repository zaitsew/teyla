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
    let speech: SpeechCapture
    let onCancel: () -> Void
    /// Saves the draft. While it runs the overlay is in the saving state and accepts no edits.
    /// Calls `failed` with a message when it could not be saved: the overlay becomes editable
    /// again with the text kept. On success the presenter closes the overlay and never calls it.
    let onSend: (ReviewDraft, @escaping (String) -> Void) -> Void

    @State private var tap: CGPoint?
    @State private var hit: Anchor?
    @State private var identifier: String?
    @State private var label: String?
    @State private var text = ""
    @State private var input: CommentInfo.Input = .text
    @State private var listening = false
    @State private var speechTask: Task<Void, Never>?
    @State private var sending = false
    @State private var failure: String?
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
                .gesture(DragGesture(minimumDistance: 0).onEnded { if !sending { select($0.location) } })
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
                .disabled(sending)
                .accessibilityIdentifier("teyla.review.comment")
            if let failure {
                Text(failure)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .accessibilityIdentifier("teyla.review.error")
            }
            if speechEnabled, speech.isAvailable {
                Button(listening ? "Stop" : "Dictate on device") { toggleListening() }
                    .font(.footnote)
                    .disabled(sending)
            }
            HStack {
                Button("Cancel", role: .cancel, action: onCancel)
                    .disabled(sending)
                Spacer()
                if sending {
                    ProgressView()
                        .accessibilityIdentifier("teyla.review.saving")
                }
                Button(sending ? "Saving" : (failure == nil ? "Send" : "Retry")) { send() }
                    .buttonStyle(.borderedProminent)
                    .disabled(sending || text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
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
            guard !sending else { return }      // a late result must not change the text being saved
            text = heard
            input = .speech
        }
        speechTask?.cancel()
        speechTask = Task {
            let started = await speech.start(microphone: microphone)
            if Task.isCancelled { speech.stop(); return }
            listening = started
        }
    }

    /// Also cancels a start that is still waiting for a permission answer, so recording cannot
    /// begin after the owner left the overlay.
    private func stopListening() {
        speechTask?.cancel()
        speechTask = nil
        guard listening else { return }
        speech.stop()
        listening = false
    }

    private func send() {
        stopListening()
        let comment = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !comment.isEmpty, !sending else { return }
        sending = true
        focused = false
        failure = nil
        onSend(ReviewDraft(tap: tap, hit: hit, accessibilityIdentifier: identifier, accessibilityLabel: label, text: comment, input: input)) { message in
            sending = false
            failure = message
        }
    }
}
#endif

import SwiftUI

/// A microphone button for a text field. Hold it to talk and release to stop, or click once to
/// start and click again to stop. The words go into the field; nothing is sent.
struct MicButton: View {
    let target: String
    @Binding var text: String

    @State private var talk = PushToTalk()
    @State private var pressed = false

    private let dictation = Dictation.shared

    var body: some View {
        let listening = dictation.isListening(target)
        Image(systemName: listening ? "mic.fill" : "mic")
            .font(Typo.body)
            .foregroundStyle(listening ? Palette.danger : Palette.textSecondary)
            .frame(width: Space.xl + Space.xs, height: Space.xl + Space.xs)
            .background(listening ? Palette.danger.opacity(0.14) : Color.clear, in: Circle())
            .contentShape(Circle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { _ in
                        guard !pressed else { return }
                        pressed = true
                        perform(talk.press(at: Date(), listening: dictation.isListening(target)))
                    }
                    .onEnded { _ in
                        pressed = false
                        perform(talk.release(at: Date()))
                    }
            )
            .help("Hold to talk, or click to start and stop. Recognised on this Mac; \(dictation.localeName).")
            .accessibilityLabel(listening ? "Stop voice input" : "Start voice input")
            .accessibilityAddTraits(.isButton)
            .accessibilityAction {
                if dictation.isListening(target) { dictation.stop() } else { begin() }
            }
            .contextMenu {
                ForEach(Voice.locales) { locale in
                    Button(locale.name) { Voice.remember(locale) }
                }
            }
            .onDisappear {
                if dictation.isListening(target) { dictation.stop() }
            }
    }

    private func perform(_ action: PushToTalk.Action) {
        switch action {
        case .start: begin()
        case .stop: dictation.stop()
        case .none: break
        }
    }

    private func begin() {
        let binding = $text
        dictation.start(target: target, current: text) { binding.wrappedValue = $0 }
    }
}

/// The line under a field that has a microphone: what is being heard, or why it cannot be.
struct DictationNote: View {
    let target: String
    private let dictation = Dictation.shared

    var body: some View {
        if let problem = dictation.problem(for: target) {
            Label(problem, systemImage: "exclamationmark.triangle.fill")
                .font(Typo.caption)
                .foregroundStyle(Palette.danger)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        } else if dictation.isListening(target) {
            Label("Listening in \(dictation.localeName). Nothing is sent until you press Send.", systemImage: "waveform")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
        }
    }
}

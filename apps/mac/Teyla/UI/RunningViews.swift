import SwiftUI

/// A session that is active now. A Codex session takes a one-line correction; any other opens.
struct RunningRow: View {
    @Environment(AppModel.self) private var model
    let session: RunningSession

    @State private var draft = ""

    private var canCorrect: Bool { session.correct == "codex-queue" && !session.ref.isEmpty }
    private var status: CardStatus? { model.cards[session.ref] }

    var body: some View {
        let seconds = ISODate.parse(session.since).map { model.clock().timeIntervalSince($0) }
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(title).font(Typo.body).lineLimit(1)
                    Text(model.notes[session.id] ?? detail(seconds: seconds))
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)
                }
                Spacer(minLength: Space.s)
                if !canCorrect {
                    Button("Open") { model.openSession(session.link, noteKey: session.id) }
                        .disabled(session.link.isEmpty)
                }
            }
            if canCorrect { correction }
        }
        .padding(.vertical, Space.s)
        .overlay(alignment: .bottom) { Divider() }
        .contextMenu {
            Button("Open session") { model.openSession(session.link, noteKey: session.id) }
                .disabled(session.link.isEmpty)
        }
        .onChange(of: status) { _, new in
            if case .done = new { draft = "" }
        }
    }

    private var correction: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            switch status {
            case .sending(let text):
                HStack(spacing: Space.s) {
                    ProgressView().controlSize(.small)
                    Text(text).font(Typo.body).foregroundStyle(Palette.textSecondary)
                }
            case .done(let text):
                Label(text, systemImage: "checkmark.circle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.success)
                    .fixedSize(horizontal: false, vertical: true)
            case .failed(let message):
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.danger)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Button("Back") { model.dismissCorrectionError(session) }
            case nil:
                HStack(spacing: Space.xs) {
                    TextField("Correct this session", text: $draft)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit(send)
                    MicButton(target: "say:\(session.ref)", text: $draft)
                    Button("Send", action: send)
                        .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                DictationNote(target: "say:\(session.ref)")
            }
        }
    }

    private func send() {
        model.say(session, text: draft)
    }

    private var title: String {
        let product = Format.product(session.product)
        return product.isEmpty ? session.title : "\(product) · \(session.title)"
    }

    private func detail(seconds: Double?) -> String {
        var parts: [String] = []
        if !session.model.isEmpty { parts.append(Format.model(session.model)) }
        if let seconds { parts.append(Format.duration(seconds: seconds)) }
        return parts.joined(separator: " · ")
    }
}

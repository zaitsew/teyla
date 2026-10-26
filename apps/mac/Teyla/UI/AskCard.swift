import SwiftUI

struct AskCard: View {
    @Environment(AppModel.self) private var model
    let ask: Ask
    /// A question that waited more than a week sits in the "Older" fold; it offers a one-click close.
    var older = false

    @State private var composing = false
    @State private var draft = ""
    @FocusState private var fieldFocused: Bool

    private var status: CardStatus? { model.cards[ask.id] }

    static let closeLabel = "Close — no longer needed"

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            header
            Text(ask.question)
                .font(Typo.lead)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if !ask.unblocks.isEmpty {
                Text("Unblocks \(ask.unblocks)")
                    .font(Typo.caption.weight(.medium))
                    .foregroundStyle(Palette.accent)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !ask.context.isEmpty {
                Text(ask.context)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let note = model.notes[ask.id] {
                Label(note, systemImage: "doc.on.clipboard")
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
            }
            switch status {
            case .sending(let text):
                HStack(spacing: Space.s) {
                    ProgressView().controlSize(.small)
                    Text(text).foregroundStyle(Palette.textSecondary)
                }
            case .done(let text):
                Label(text, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Palette.success)
            case .failed(let message):
                failure(message)
            case nil:
                actions
            }
        }
        .card(highlighted: model.focusedAskID == ask.id)
        .id(ask.id)
        .contextMenu {
            Button("Snooze 1 day") { model.snooze(ask, days: 1) }
            Button(older ? Self.closeLabel : "Mark done") { model.markDone(ask) }
            Divider()
            Button("Open session") { model.openSession(ask.link, noteKey: ask.id) }
                .disabled(ask.link.isEmpty)
            Button("Copy question") { model.copyQuestion(ask) }
        }
        .onChange(of: status) { _, new in
            if case .done = new { composing = false; draft = "" }
        }
        .accessibilityElement(children: .contain)
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            HStack(spacing: 0) {
                if model.hasPage(ask.product) {
                    Button(Format.product(ask.product)) { model.openProduct(ask.product) }
                        .buttonStyle(.plain)
                        .foregroundStyle(Palette.primary)
                        .help("Open the \(Format.product(ask.product)) page")
                } else {
                    Text(Format.product(ask.product))
                }
                Text(" · \(Format.age(seconds: model.age(of: ask)))")
            }
            .font(Typo.caption)
            .foregroundStyle(Palette.textSecondary)
            Spacer(minLength: Space.m)
            if older, status == nil {
                Button(Self.closeLabel) { model.markDone(ask) }
                    .buttonStyle(.borderless)
                    .controlSize(.small)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .help("Close this question without answering it")
            }
        }
    }

    private var actions: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            FlowLayout(spacing: Space.s) {
                ForEach(Array(ask.options.enumerated()), id: \.offset) { index, option in
                    if index == 0 && !composing {
                        Button(option) { model.answer(ask, text: option) }
                            .buttonStyle(.borderedProminent)
                    } else {
                        Button(option) { model.answer(ask, text: option) }
                            .buttonStyle(.bordered)
                    }
                }
                if !composing {
                    // With no options the written answer is the only action, so it leads.
                    if ask.options.isEmpty {
                        Button("Answer…", action: beginComposing).buttonStyle(.borderedProminent)
                    } else {
                        Button("Answer…", action: beginComposing).buttonStyle(.bordered)
                    }
                }
            }
            .controlSize(.regular)
            if composing { composer }
        }
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(spacing: Space.s) {
                TextField("Write an answer", text: $draft, axis: .vertical)
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(1...5)
                    .focused($fieldFocused)
                    .onSubmit(send)
                    .onExitCommand { composing = false; draft = "" }
                MicButton(target: dictationTarget, text: $draft)
                Button("Send", action: send)
                    .buttonStyle(.borderedProminent)
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("Cancel") { composing = false; draft = "" }
                    .buttonStyle(.borderless)
                    .foregroundStyle(Palette.textSecondary)
            }
            DictationNote(target: dictationTarget)
        }
        .onAppear { fieldFocused = true }
    }

    private var dictationTarget: String { "answer:\(ask.id)" }

    private func beginComposing() {
        composing = true
        fieldFocused = true
    }

    private func send() {
        let text = draft
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        // The draft stays until `teyla answer` succeeds, so a failed delivery loses nothing.
        // "Back" on the error returns to the composer with the text still in it.
        model.answer(ask, text: text)
    }

    private func failure(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Label(message, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(Palette.danger)
                .font(Typo.body)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            HStack(spacing: Space.s) {
                Button("Open session") { model.openSession(ask.link, noteKey: ask.id) }
                    .buttonStyle(.borderedProminent)
                    .disabled(ask.link.isEmpty)
                Button("Back") { model.dismissError(ask) }
                    .buttonStyle(.bordered)
            }
        }
    }
}

/// Lays children out left to right and wraps to a new row when the width runs out.
struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(width: proposal.width ?? .infinity, subviews: subviews).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(width: bounds.width, subviews: subviews)
        for (index, origin) in result.origins.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + origin.x, y: bounds.minY + origin.y),
                                  proposal: .unspecified)
        }
    }

    private func arrange(width: CGFloat, subviews: Subviews) -> (size: CGSize, origins: [CGPoint]) {
        var origins: [CGPoint] = []
        var x: CGFloat = 0, y: CGFloat = 0, rowHeight: CGFloat = 0, maxX: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0, x + size.width > width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            origins.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
            maxX = max(maxX, x - spacing)
        }
        return (CGSize(width: maxX, height: y + rowHeight), origins)
    }
}

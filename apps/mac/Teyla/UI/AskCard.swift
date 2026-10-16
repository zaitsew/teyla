import SwiftUI

struct AskCard: View {
    @Environment(AppModel.self) private var model
    let ask: Ask

    @State private var composing = false
    @State private var draft = ""
    @FocusState private var fieldFocused: Bool

    private var status: CardStatus? { model.cards[ask.id] }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            Text(ask.question)
                .font(.system(size: 16, weight: .medium))
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if !ask.context.isEmpty {
                Text(ask.context)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            switch status {
            case .sending(let text):
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(text).foregroundStyle(.secondary)
                }
            case .done(let text):
                Label(text, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            case .failed(let message):
                failure(message)
            case nil:
                actions
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color(nsColor: .separatorColor)))
        .contextMenu {
            Button("Snooze 1 day") { model.snooze(ask, days: 1) }
            Button("Mark done") { model.markDone(ask) }
            Divider()
            Button("Open session") { model.openSession(ask.link) }
                .disabled(ask.link.isEmpty)
            Button("Copy question") { model.copyQuestion(ask) }
        }
        .accessibilityElement(children: .contain)
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text("\(Format.product(ask.product)) · \(Format.age(seconds: model.age(of: ask)))")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer(minLength: 12)
            if !ask.unblocks.isEmpty {
                Text("unblocks \(ask.unblocks)")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(Color.accentColor)
                    .multilineTextAlignment(.trailing)
            }
        }
    }

    private var actions: some View {
        VStack(alignment: .leading, spacing: 10) {
            FlowLayout(spacing: 8) {
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
        HStack(spacing: 8) {
            TextField("Write an answer", text: $draft, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...5)
                .focused($fieldFocused)
                .onSubmit(send)
                .onExitCommand { composing = false; draft = "" }
            Button("Send", action: send)
                .buttonStyle(.borderedProminent)
                .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Button("Cancel") { composing = false; draft = "" }
                .buttonStyle(.borderless)
                .foregroundStyle(.secondary)
        }
        .onAppear { fieldFocused = true }
    }

    private func beginComposing() {
        composing = true
        fieldFocused = true
    }

    private func send() {
        let text = draft
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        model.answer(ask, text: text)
        composing = false
        draft = ""
    }

    private func failure(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(message, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(.red)
                .font(.callout)
                .lineLimit(4)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            HStack(spacing: 8) {
                Button("Open session") { model.openSession(ask.link) }
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

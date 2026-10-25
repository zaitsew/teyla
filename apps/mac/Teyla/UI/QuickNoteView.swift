import SwiftUI

/// The quick-note panel: a text area, the product it will be filed under, and what the keys do.
struct QuickNoteView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let note = model.quickNote
        VStack(alignment: .leading, spacing: Space.m) {
            NoteTextView(text: Bindable(note).draft,
                         placeholder: "An idea, in your own words",
                         focusToken: note.focusToken,
                         isEditable: !note.isSaving,
                         onEdit: { note.draftChanged() },
                         onSubmit: { note.save() },
                         onCancel: { model.closeQuickNote() },
                         onDigit: { note.choose(digit: $0) })
                .frame(height: Space.captureFieldHeight)

            products(note)
            Text(howLine(note))
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(1)

            outcome(note)

            Divider()
            HStack(spacing: Space.l) {
                Hint(key: "⏎", text: "save")
                Hint(key: "⇧⏎", text: "new line")
                Hint(key: "⌘1–9", text: "product")
                Hint(key: "Esc", text: "close")
                Spacer(minLength: Space.s)
                Text("Kept on this Mac")
            }
            .font(Typo.caption)
            .foregroundStyle(Palette.textSecondary)
        }
        .padding(Space.l)
        .frame(width: Space.capturePanelWidth, height: Space.capturePanelHeight, alignment: .topLeading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: Radius.panel))
        .overlay(RoundedRectangle(cornerRadius: Radius.panel).strokeBorder(Palette.border, lineWidth: 1))
    }

    private func products(_ note: QuickNoteModel) -> some View {
        let split = Notes.split(note.candidates)
        return FlowLayout(spacing: Space.s) {
            ProductChip(label: "Inbox", key: "0", selected: note.product == NoteItem.inbox) {
                note.choose(NoteItem.inbox)
            }
            ForEach(Array(split.numbered.enumerated()), id: \.element) { index, id in
                ProductChip(label: Notes.productLabel(id), key: String(index + 1), selected: note.product == id) {
                    note.choose(id)
                }
            }
            if !split.more.isEmpty {
                Menu {
                    ForEach(split.more, id: \.self) { id in
                        Button(Notes.productLabel(id)) { note.choose(id) }
                    }
                } label: {
                    Text(split.more.contains(note.product) ? Notes.productLabel(note.product) : "More…")
                }
                .menuStyle(.button)
                .fixedSize()
            }
        }
    }

    private func howLine(_ note: QuickNoteModel) -> String {
        "\(Notes.productLabel(note.product)) · \(Notes.howLabel(note.linkedBy, product: note.product))"
    }

    @ViewBuilder private func outcome(_ note: QuickNoteModel) -> some View {
        switch note.status {
        case .sending(let text):
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text(text).foregroundStyle(Palette.textSecondary)
            }
        case .done(let text):
            Label(text, systemImage: "checkmark.circle.fill").foregroundStyle(Palette.success)
        case .failed(let message):
            Label(message, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(Palette.danger)
                .fixedSize(horizontal: false, vertical: true)
                .lineLimit(3)
                .textSelection(.enabled)
        case nil:
            EmptyView()
        }
    }
}

private struct ProductChip: View {
    let label: String
    let key: String
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: Space.xs) {
                Text(label).font(Typo.body.weight(selected ? .semibold : .regular))
                Text("⌘\(key)").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            .padding(.horizontal, Space.m)
            .padding(.vertical, Space.xs + Space.xxs)
            .background(selected ? Palette.accent.opacity(0.18) : Palette.surface, in: Capsule())
            .overlay(Capsule().strokeBorder(selected ? Palette.accent : Palette.border, lineWidth: 1))
            .contentShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(label), command \(key)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }
}

private struct Hint: View {
    let key: String
    let text: String

    var body: some View {
        HStack(spacing: Space.xs) {
            Text(key)
                .font(Typo.caption.weight(.medium))
                .padding(.horizontal, Space.xs + Space.xxs)
                .padding(.vertical, Space.xxs)
                .background(Palette.surface, in: RoundedRectangle(cornerRadius: Space.xs))
            Text(text)
        }
    }
}

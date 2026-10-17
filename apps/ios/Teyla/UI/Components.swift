import SwiftUI

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
            let size = subview.sizeThatFits(ProposedViewSize(width: width, height: nil))
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

struct SectionLabel: View {
    let text: String
    init(_ text: String) { self.text = text }

    var body: some View {
        Text(text)
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityAddTraits(.isHeader)
    }
}

extension View {
    /// A grouped card, the same in light and dark.
    func card() -> some View {
        padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

struct Pill: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 9)
            .padding(.vertical, 3)
            .background(color.opacity(0.14), in: Capsule())
            .fixedSize()
    }
}

/// The state of something sent from the phone, under the card it belongs to.
struct OutcomeView: View {
    let action: PendingAction
    var onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let outcome = action.outcome {
                Label(PhoneFormat.outcomeLine(outcome),
                      systemImage: outcome.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(outcome.ok ? Color.green : Color.red)
                    .fixedSize(horizontal: false, vertical: true)
                Text(action.text)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
                Button(outcome.ok ? "Dismiss" : "Dismiss and try again", action: onDismiss)
                    .font(.callout.weight(.medium))
            } else {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Waiting for the Mac").foregroundStyle(.secondary)
                }
                .font(.callout)
                Text(action.text)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
        }
        .accessibilityElement(children: .combine)
    }
}

/// Push-to-talk. A tap starts and stops; a long press picks the language.
struct MicButton: View {
    @Binding var text: String
    let field: String
    @Environment(Dictation.self) private var dictation
    @AppStorage("dictationLanguage") private var languageID = DictationLanguage.english.rawValue

    private var language: DictationLanguage { DictationLanguage(rawValue: languageID) ?? .english }

    var body: some View {
        let recording = dictation.isRecording(field)
        Menu {
            Picker("Language", selection: $languageID) {
                ForEach(DictationLanguage.allCases) { Text($0.title).tag($0.rawValue) }
            }
        } label: {
            ZStack(alignment: .bottomTrailing) {
                Image(systemName: recording ? "stop.circle.fill" : "mic.fill")
                    .font(.system(size: 20))
                    .foregroundStyle(recording ? Color.red : Color.accentColor)
                    .frame(width: 44, height: 44)
                Text(language.code)
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.secondary)
                    .offset(x: -2, y: -4)
            }
        } primaryAction: {
            dictation.toggle(field: field, language: language, current: text) { text = $0 }
        }
        .accessibilityLabel(recording ? "Stop dictation" : "Dictate in \(language.title)")
        .accessibilityHint("Touch and hold to change the language")
    }
}

/// One text field with a mic and a Send button. Nothing is sent until Send is tapped.
struct Composer: View {
    @Binding var text: String
    let field: String
    let placeholder: String
    var sendLabel = "Send"
    /// True while the last send is still being written: the button waits, so one tap is one entry.
    var isSending = false
    var onSend: () -> Void
    @FocusState private var focused: Bool

    private var canSend: Bool { !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            HStack(spacing: 0) {
                TextField(placeholder, text: $text, axis: .vertical)
                    .lineLimit(1...5)
                    .focused($focused)
                    .submitLabel(.return)
                    .padding(.leading, 12)
                    .padding(.vertical, 10)
                MicButton(text: $text, field: field)
            }
            .background(Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
            Button(sendLabel) {
                focused = false
                onSend()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!canSend || isSending)
        }
    }
}

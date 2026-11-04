import SwiftUI

/// Lays children out left to right and wraps to a new row when the width runs out.
struct FlowLayout: Layout {
    var spacing = Space.s

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

/// A collapsed group under a list: a chevron, a title and what it holds when opened.
struct Fold<Content: View>: View {
    let title: String
    /// Quiet words after the title.
    var detail = ""
    /// What VoiceOver reads; the title when empty.
    var spokenTitle = ""
    @ViewBuilder var content: Content
    @State private var open: Bool

    init(title: String, detail: String = "", spokenTitle: String = "", startsOpen: Bool = false,
         @ViewBuilder content: () -> Content) {
        self.title = title
        self.detail = detail
        self.spokenTitle = spokenTitle
        self.content = content()
        _open = State(initialValue: startsOpen)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Button {
                withAnimation(.easeOut(duration: 0.2)) { open.toggle() }
            } label: {
                HStack(spacing: Space.s) {
                    Text(title).font(Typo.body.weight(.semibold))
                    if !detail.isEmpty {
                        Text(detail).font(Typo.caption).fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer(minLength: Space.s)
                    Image(systemName: open ? "chevron.up" : "chevron.down")
                        .font(Typo.caption.weight(.semibold))
                }
                .foregroundStyle(Palette.textSecondary)
                .frame(minHeight: Space.touchMin)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(spokenTitle.isEmpty ? title : spokenTitle)
            .accessibilityAddTraits(.isHeader)
            .accessibilityValue(open ? "expanded" : "collapsed")
            if open { content }
        }
    }
}

extension View {
    /// A grouped card, the same in light and dark.
    func card() -> some View {
        padding(Space.l)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: Radius.panel, style: .continuous))
    }
}

struct Pill: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(Typo.caption.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, Space.s)
            .padding(.vertical, Space.xxs)
            .background(color.chipTint, in: Capsule())
            .fixedSize()
    }
}

/// The state of something sent from the phone, under the card it belongs to.
struct OutcomeView: View {
    let action: PendingAction
    var onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            if let outcome = action.outcome {
                let simulated = outcome.via == SampleData.via
                Label(PhoneFormat.outcomeLine(outcome),
                      systemImage: simulated ? "info.circle.fill"
                          : outcome.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                    .font(Typo.body)
                    .foregroundStyle(simulated ? Palette.textSecondary : outcome.ok ? Palette.saving : Palette.danger)
                    .fixedSize(horizontal: false, vertical: true)
                Text(action.text)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(3)
                Button(outcome.ok ? "Dismiss" : "Dismiss and try again", action: onDismiss)
                    .font(Typo.body.weight(.medium))
            } else {
                HStack(spacing: Space.s) {
                    ProgressView().controlSize(.small)
                    Text("Waiting for the Mac").foregroundStyle(Palette.textSecondary)
                }
                .font(Typo.body)
                Text(action.text)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
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
                    .font(Glyph.mic)
                    .foregroundStyle(recording ? Palette.danger : Palette.primary)
                    .frame(width: Space.touchMin, height: Space.touchMin)
                Text(language.code)
                    .font(Glyph.badge)
                    .foregroundStyle(Palette.textSecondary)
                    .offset(x: -Space.xxs, y: -Space.xs)
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
        HStack(alignment: .center, spacing: Space.s) {
            HStack(spacing: 0) {
                TextField(placeholder, text: $text, axis: .vertical)
                    .lineLimit(1...5)
                    .focused($focused)
                    .submitLabel(.return)
                    .padding(.leading, Space.m)
                    .padding(.vertical, Space.s)
                MicButton(text: $text, field: field)
            }
            .background(Palette.track, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
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

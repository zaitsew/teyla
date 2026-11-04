import SwiftUI

/// One question: the text, the context, the options as chips, and an answer field.
/// A chip fills the field; nothing is sent until Send.
struct QuestionCard: View {
    @Environment(AppModel.self) private var model
    let ask: Ask
    let ageSeconds: Double
    private var draft: String {
        get { model.drafts[ask.id] ?? "" }
        nonmutating set { model.drafts[ask.id] = newValue.isEmpty ? nil : newValue }
    }
    private var draftBinding: Binding<String> {
        Binding(get: { draft }, set: { draft = $0 })
    }

    private var action: PendingAction? { model.action(for: .answer, target: ask.id) }

    private var productLine: some View {
        Text("\(Format.product(ask.product)) \u{00B7} \(Format.age(seconds: ageSeconds))")
            .font(Typo.caption)
            .foregroundStyle(Palette.textSecondary)
    }

    @ViewBuilder private var unblocksNote: some View {
        if !ask.unblocks.isEmpty {
            Text("unblocks \(ask.unblocks)")
                .font(Typo.caption.weight(.medium))
                .foregroundStyle(Palette.primary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            // One line when it fits; the "unblocks" note drops under the product at large text sizes.
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline) {
                    productLine
                    Spacer(minLength: Space.s)
                    unblocksNote.multilineTextAlignment(.trailing)
                }
                VStack(alignment: .leading, spacing: Space.xxs) {
                    productLine
                    unblocksNote
                }
            }
            Text(ask.question)
                .font(Typo.cardTitle)
                .fixedSize(horizontal: false, vertical: true)
            if !ask.context.isEmpty {
                Text(ask.context)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let action {
                OutcomeView(action: action) { model.dismiss(action.id) }
            } else {
                answering
            }
        }
        .card()
        .accessibilityElement(children: .contain)
    }

    /// Teyla's proposed answer, and why. A payment shows it as information only.
    @ViewBuilder private var proposal: some View {
        if let proposed = ask.proposedAnswer {
            VStack(alignment: .leading, spacing: Space.xxs) {
                (Text("Proposed: ").foregroundStyle(Palette.textSecondary) + Text(proposed))
                    .font(Typo.body)
                    .fixedSize(horizontal: false, vertical: true)
                if let why = ask.triage?.why, !why.isEmpty {
                    Text(why).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var answering: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            proposal
            if let proposed = ask.proposedAnswer, ask.canUseProposedAnswer {
                // One tap sends the proposed answer to its session, as on the Mac. Never for a payment.
                Button("Use default") {
                    Task {
                        await model.send(kind: .answer, target: ask.id, aboutText: ask.question,
                                         label: ask.title.isEmpty ? Format.product(ask.product) : ask.title,
                                         text: proposed)
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(model.isSending(.answer, target: ask.id))
                .accessibilityHint("Sends the proposed answer")
            }
            if !ask.options.isEmpty {
                FlowLayout(spacing: Space.s) {
                    ForEach(Array(ask.options.enumerated()), id: \.offset) { _, option in
                        Button(option) { draft = option }
                            .buttonStyle(.bordered)
                            .tint(draft == option ? Palette.primary : Palette.textSecondary)
                            .controlSize(.regular)
                    }
                }
            }
            Composer(text: draftBinding, field: "ask-\(ask.id)", placeholder: "Write an answer",
                     isSending: model.isSending(.answer, target: ask.id)) {
                let text = draft
                Task {
                    if await model.send(kind: .answer, target: ask.id, aboutText: ask.question,
                                        label: ask.title.isEmpty ? Format.product(ask.product) : ask.title,
                                        text: text), draft == text {
                        draft = ""            // words typed or dictated during the write stay
                    }
                }
            }
        }
    }
}

/// Something only the owner can do: a PR to merge or an issue assigned to them.
struct TaskRow: View {
    @Environment(\.openURL) private var openURL
    let task: OwnerTask
    let ageSeconds: Double

    var body: some View {
        let url = PhoneFormat.webURL(task.link)
        Button {
            if let url { openURL(url) }
        } label: {
            HStack(alignment: .top, spacing: Space.m) {
                Image(systemName: task.kind == "merge" ? "arrow.triangle.merge" : "checklist")
                    .font(Typo.section)
                    .foregroundStyle(Palette.primary)
                    .frame(width: Space.glyph)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text("\(Format.product(task.product)) \u{00B7} \(Format.age(seconds: ageSeconds))")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                    Text(task.title)
                        .font(Typo.body.weight(.medium))
                        .foregroundStyle(Palette.text)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                    if !task.detail.isEmpty {
                        Text(task.detail)
                            .font(Typo.body)
                            .foregroundStyle(Palette.textSecondary)
                            .multilineTextAlignment(.leading)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                if url != nil {
                    Image(systemName: "arrow.up.right")
                        .font(Typo.caption.weight(.semibold))
                        .foregroundStyle(Palette.textTertiary)
                        .padding(.top, Space.xs)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(url == nil)
        .card()
        .accessibilityHint(url == nil ? "" : "Opens the link")
    }
}

/// A session that ended a turn in the last 24 hours.
struct DoneCard: View {
    @Environment(\.openURL) private var openURL
    let item: DoneItem
    let agoSeconds: Double?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline) {
                Text(headline)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                Spacer(minLength: Space.s)
                Pill(text: Self.statusLabel(item.status), color: Self.statusColor(item.status))
            }
            Text(item.title)
                .font(Typo.cardTitle)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(Array(item.result.prefix(3).enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(Typo.body)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !item.needs.isEmpty {
                Label(item.needs, systemImage: "hand.raised.fill")
                    .font(Typo.body.weight(.medium))
                    .foregroundStyle(Palette.needsYou)
                    .fixedSize(horizontal: false, vertical: true)
            }
            let urls = item.links.compactMap(PhoneFormat.webURL)
            if !urls.isEmpty {
                FlowLayout(spacing: Space.s) {
                    ForEach(urls, id: \.absoluteString) { url in
                        Button { openURL(url) } label: {
                            Label(PhoneFormat.linkLabel(url), systemImage: "link")
                                .lineLimit(1)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                    }
                }
            }
        }
        .card()
        .accessibilityElement(children: .contain)
    }

    private var headline: String {
        let product = Format.product(item.product)
        guard let agoSeconds else { return product }
        return "\(product) \u{00B7} \(PhoneFormat.ago(agoSeconds))"
    }

    static func statusLabel(_ status: String) -> String {
        switch status {
        case "done": return "Done"
        case "needs_you": return "Needs you"
        case "blocked": return "Blocked"
        case "failed": return "Failed"
        case "review_ready": return "Review ready"
        default: return status.replacingOccurrences(of: "_", with: " ").capitalized
        }
    }

    static func statusColor(_ status: String) -> Color {
        switch status {
        case "done": return Palette.saving
        case "needs_you": return Palette.needsYou
        case "blocked", "failed": return Palette.danger
        case "review_ready": return Palette.primary
        default: return Palette.textSecondary
        }
    }
}

/// A running session. Only a Codex session can take a correction; the rest are read-only.
struct RunningCard: View {
    @Environment(AppModel.self) private var model
    let session: RunningSession
    let runningSeconds: Double?
    @State private var correcting = false
    @State private var draft = ""

    private var canCorrect: Bool { session.correct == "codex-queue" && !session.ref.isEmpty && OutboxEntry.isTarget(session.ref) }
    private var action: PendingAction? { canCorrect ? model.action(for: .say, target: session.ref) : nil }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                Circle().fill(Palette.saving).frame(width: Space.dot, height: Space.dot).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(session.title).font(Typo.body.weight(.medium)).fixedSize(horizontal: false, vertical: true)
                    Text(detail).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
                Spacer(minLength: Space.s)
                if canCorrect, !correcting, action == nil {
                    Button("Correct") { correcting = true }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                }
            }
            if let action {
                OutcomeView(action: action) { model.dismiss(action.id) }
            } else if canCorrect, correcting {
                Composer(text: $draft, field: "say-\(session.ref)", placeholder: "Correct this session", sendLabel: "Send",
                         isSending: model.isSending(.say, target: session.ref)) {
                    let text = draft
                    Task {
                        if await model.send(kind: .say, target: session.ref, aboutText: session.title,
                                            label: session.title, text: text) {
                            if draft == text { draft = "" }
                            correcting = false
                        }
                    }
                }
            }
        }
        .card()
        .accessibilityElement(children: .contain)
    }

    private var detail: String {
        var parts = [Format.product(session.product)]
        if !session.model.isEmpty { parts.append(Format.model(session.model)) }
        if let runningSeconds { parts.append(Format.duration(seconds: runningSeconds)) }
        return parts.joined(separator: " \u{00B7} ")
    }
}

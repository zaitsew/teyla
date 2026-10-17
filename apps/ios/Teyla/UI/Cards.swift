import SwiftUI

/// One question: the text, the context, the options as chips, and an answer field.
/// A chip fills the field; nothing is sent until Send.
struct QuestionCard: View {
    @Environment(AppModel.self) private var model
    let ask: Ask
    let ageSeconds: Double
    @State private var draft = ""

    private var action: PendingAction? { model.action(for: .answer, target: ask.id) }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("\(Format.product(ask.product)) \u{00B7} \(Format.age(seconds: ageSeconds))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                if !ask.unblocks.isEmpty {
                    Text("unblocks \(ask.unblocks)")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(Color.accentColor)
                        .multilineTextAlignment(.trailing)
                }
            }
            Text(ask.question)
                .font(.headline)
                .fixedSize(horizontal: false, vertical: true)
            if !ask.context.isEmpty {
                Text(ask.context)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
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

    private var answering: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !ask.options.isEmpty {
                FlowLayout(spacing: 8) {
                    ForEach(Array(ask.options.enumerated()), id: \.offset) { _, option in
                        Button(option) { draft = option }
                            .buttonStyle(.bordered)
                            .tint(draft == option ? Color.accentColor : Color.secondary)
                            .controlSize(.regular)
                    }
                }
            }
            Composer(text: $draft, field: "ask-\(ask.id)", placeholder: "Write an answer",
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
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: task.kind == "merge" ? "arrow.triangle.merge" : "checklist")
                    .font(.title3)
                    .foregroundStyle(Color.accentColor)
                    .frame(width: 26)
                VStack(alignment: .leading, spacing: 3) {
                    Text("\(Format.product(task.product)) \u{00B7} \(Format.age(seconds: ageSeconds))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text(task.title)
                        .font(.body.weight(.medium))
                        .foregroundStyle(.primary)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                    if !task.detail.isEmpty {
                        Text(task.detail)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.leading)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                if url != nil {
                    Image(systemName: "arrow.up.right")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(.tertiary)
                        .padding(.top, 4)
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
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text(headline)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer(minLength: 8)
                Pill(text: Self.statusLabel(item.status), color: Self.statusColor(item.status))
            }
            Text(item.title)
                .font(.headline)
                .fixedSize(horizontal: false, vertical: true)
            ForEach(Array(item.result.prefix(3).enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(.subheadline)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !item.needs.isEmpty {
                Label(item.needs, systemImage: "hand.raised.fill")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Color.orange)
                    .fixedSize(horizontal: false, vertical: true)
            }
            let urls = item.links.compactMap(PhoneFormat.webURL)
            if !urls.isEmpty {
                FlowLayout(spacing: 8) {
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
        case "done": return .green
        case "needs_you": return .orange
        case "blocked", "failed": return .red
        case "review_ready": return .blue
        default: return .secondary
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
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Circle().fill(Color.green).frame(width: 8, height: 8).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                    Text(session.title).font(.body.weight(.medium)).fixedSize(horizontal: false, vertical: true)
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
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

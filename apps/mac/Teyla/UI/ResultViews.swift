import SwiftUI

/// One session that ended a turn: what it did, what it needs from the owner, and where to look.
struct DoneCard: View {
    @Environment(AppModel.self) private var model
    let item: DoneItem

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                Chip(text: Format.statusLabel(item.status), color: Self.color(for: item.status))
                Text(meta)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
                Spacer(minLength: 0)
            }
            Text(item.title)
                .font(Typo.lead)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            ForEach(Array(item.result.prefix(3).enumerated()), id: \.offset) { _, line in
                Text(line)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            if !item.needs.isEmpty {
                Text("Needs: \(item.needs)")
                    .font(Typo.body.weight(.medium))
                    .foregroundStyle(item.status == "done" ? Palette.textSecondary : Color.primary)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                FlowLayout(spacing: Space.m) {
                    ForEach(item.links, id: \.self) { link in
                        LinkLabel(link: link)
                    }
                }
                Spacer(minLength: Space.s)
                Button("Open session") { model.openSession(item.link, noteKey: item.id) }
                    .disabled(item.link.isEmpty)
            }
            if let note = model.notes[item.id] {
                Label(note, systemImage: "doc.on.clipboard")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
        .card()
        .accessibilityElement(children: .contain)
    }

    private var meta: String {
        var parts = [Format.product(item.product)]
        if let ended = ISODate.parse(item.ended) {
            parts.append(Format.age(seconds: model.clock().timeIntervalSince(ended)))
        }
        return parts.joined(separator: " · ")
    }

    static func color(for status: String) -> Color {
        switch status {
        case "done": return Palette.success
        case "needs_you": return Palette.warning
        case "blocked", "failed": return Palette.danger
        case "review_ready": return Palette.info
        default: return Palette.textSecondary
        }
    }
}

/// A link on a result card. Only web links open; anything else is shown as text.
private struct LinkLabel: View {
    let link: String

    var body: some View {
        if let url = URL(string: link), ["https", "http"].contains(url.scheme?.lowercased() ?? "") {
            Link(Format.linkLabel(link), destination: url)
                .font(Typo.body)
                .lineLimit(1)
                .help(link)
        } else {
            Text(link)
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(1)
        }
    }
}

/// A thing only the owner can do that is not a question: a PR to merge or an assigned issue.
struct TaskRow: View {
    @Environment(AppModel.self) private var model
    let task: OwnerTask

    var body: some View {
        HStack(alignment: .top, spacing: Space.m) {
            VStack(alignment: .leading, spacing: Space.xs) {
                HStack(spacing: Space.s) {
                    Chip(text: Format.taskKind(task.kind), color: task.kind == "merge" ? Palette.info : Palette.warning)
                    Text(meta)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)
                }
                Text(task.title)
                    .font(Typo.body.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                if !task.detail.isEmpty {
                    Text(task.detail)
                        .font(Typo.body)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            Spacer(minLength: Space.s)
            Button("Open") { model.openSession(task.link, noteKey: task.id) }
                .disabled(task.link.isEmpty)
        }
        .padding(.vertical, Space.m)
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .contain)
    }

    private var meta: String {
        "\(Format.product(task.product)) · \(Format.age(seconds: model.age(plus: task.ageSeconds)))"
    }
}

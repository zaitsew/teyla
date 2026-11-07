import AppKit
import SwiftUI

// Two sections of the Growth page (docs/GROWTH.md):
// - Ready to publish: approved items, each with "Publish to connected networks" (`teyla growth publish <id> --json`).
//   The owner approved the text first; this second click sends it. The result shows per network.
// - Engage: today's posts worth a reply. The app opens a post; the owner writes the reply on the network himself and marks
//   it done. Nothing here writes, sends or posts a reply, likes or follows.

/// Approved items waiting to go out.
struct ReadyToPublish: View {
    @Environment(AppModel.self) private var model
    @State private var confirming: [GrowthDraft] = []

    var body: some View {
        let queue = model.growth
        if queue.isRead, !queue.ready.isEmpty || !queue.published.isEmpty || queue.publishFailure != nil {
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: "Ready to publish",
                              note: "You approved these. Publishing posts each one where its network is connected; the rest get a packet to post by hand.",
                              count: queue.ready.count)
                if let why = queue.publishFailure {
                    HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                        Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Palette.danger)
                        ClampedText(text: why, lines: 3, font: Typo.caption, color: Palette.text)
                        Spacer(minLength: Space.s)
                        Button("Dismiss") { queue.clearPublishFailure() }.buttonStyle(.plain).font(Typo.caption).foregroundStyle(Palette.primary)
                    }
                }
                ForEach(queue.ready) { item in
                    ReadyRow(item: item, results: queue.published[item.id] ?? [], busy: queue.publishing.contains(item.id)) {
                        confirming = [item]
                    }
                }
                // Results of items that already left the list (published now).
                ForEach(queue.published.keys.sorted().filter { id in !queue.ready.contains { $0.id == id } }, id: \.self) { id in
                    PublishResults(results: queue.published[id] ?? [])
                }
            }
            .confirmationDialog(confirmTitle, isPresented: Binding(get: { !confirming.isEmpty }, set: { if !$0 { confirming = [] } })) {
                Button("Publish") {
                    model.growth.publish(confirming)
                    confirming = []
                }
                Button("Cancel", role: .cancel) { confirming = [] }
            } message: {
                Text("It goes out now, under your name, on every network that is connected. A network that is not connected gets a packet instead.")
            }
        }
    }

    private var confirmTitle: String {
        guard let item = confirming.first else { return "" }
        return "Publish \(GrowthLogic.channelName(platform: item.platform, language: item.language)) post?"
    }
}

private struct ReadyRow: View {
    let item: GrowthDraft
    let results: [PublishResult]
    let busy: Bool
    let publish: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(GrowthLogic.draftTitle(item)).font(Typo.cardTitle).foregroundStyle(Palette.text).lineLimit(2)
                    Text(GrowthLogic.draftDetail(item)).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                }
                Spacer(minLength: Space.s)
                if busy {
                    ProgressView().controlSize(.small)
                    Text("Publishing…").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                } else {
                    Button("Publish to connected networks", action: publish)
                        .buttonStyle(.borderedProminent)
                        .help("teyla growth publish \(item.id)")
                }
            }
            if !item.body.isEmpty {
                Text(item.body).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(2)
            }
            PublishResults(results: results)
        }
        .surface()
    }
}

/// One line per network: live (with its link), a packet to post by hand, or what went wrong.
private struct PublishResults: View {
    let results: [PublishResult]

    var body: some View {
        if !results.isEmpty {
            VStack(alignment: .leading, spacing: Space.xxs) {
                ForEach(results) { result in
                    HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                        Image(systemName: symbol(result)).foregroundStyle(color(result))
                        Text(GrowthLogic.channelName(platform: result.network, language: "")).font(Typo.caption.weight(.semibold))
                        if let url = result.link {
                            Button { NSWorkspace.shared.open(url) } label: {
                                Text(result.url).font(Typo.caption).lineLimit(1).truncationMode(.middle)
                            }
                            .buttonStyle(.plain)
                            .foregroundStyle(Palette.primary)
                        } else {
                            ClampedText(text: result.message.isEmpty ? result.status : result.message, lines: 2, font: Typo.caption)
                        }
                    }
                    if !result.warning.isEmpty {
                        Text(result.warning).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }

    private func symbol(_ r: PublishResult) -> String {
        r.isLive ? "checkmark.circle.fill" : (r.needsOwner ? "exclamationmark.triangle.fill" : "shippingbox")
    }

    private func color(_ r: PublishResult) -> Color {
        r.isLive ? Palette.saving : (r.needsOwner ? Palette.danger : Palette.textSecondary)
    }
}

// MARK: Engage

/// Today's posts worth a reply. Keyboard: ↑ and ↓ move, Return opens the post, D marks it done.
struct EngageSection: View {
    @Environment(AppModel.self) private var model
    @State private var selected: Int?
    @FocusState private var focused: Bool

    var body: some View {
        let growth = model.growth
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Engage", note: "Posts worth a reply today, each with an angle. You write every reply yourself; then mark it done.",
                          count: growth.engage.map { $0.total - $0.done }) {
                HStack(spacing: Space.s) {
                    if growth.engageLoading { ProgressView().controlSize(.small) }
                    Button("Find today's posts") { growth.loadEngage(scan: true) }
                        .disabled(growth.engageLoading)
                        .help("teyla growth engage: one cached scan a day")
                }
            }
            if let why = growth.engageFailure {
                ErrorRow(section: "the engage list", message: why) { growth.loadEngage() }
            }
            content(growth)
        }
        .onAppear { if growth.engage == nil { growth.loadEngage() } }
    }

    @ViewBuilder
    private func content(_ growth: GrowthModel) -> some View {
        if let doc = growth.engage {
            if doc.rows.isEmpty {
                EmptyState(symbol: "bubble.left.and.bubble.right", title: emptyTitle(doc), detail: emptyDetail(doc))
            } else {
                Text("\(doc.done) of \(doc.total) replied · goal \(doc.goal) a day").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                VStack(alignment: .leading, spacing: Space.s) {
                    ForEach(doc.rows) { row in
                        EngageRowView(row: row, selected: selected == row.n, busy: growth.marking.contains(row.n),
                                      open: { open(row) }, done: { growth.markDone(row) })
                            .onTapGesture { selected = row.n; focused = true }
                    }
                }
                .focusable()
                .focused($focused)
                .focusEffectDisabled()
                .onKeyPress(.downArrow) { move(doc, 1) }
                .onKeyPress(.upArrow) { move(doc, -1) }
                .onKeyPress(.return) {
                    guard let row = current(doc) else { return .ignored }
                    open(row)
                    return .handled
                }
                .onKeyPress(characters: CharacterSet(charactersIn: "dD")) { _ in
                    guard let row = current(doc) else { return .ignored }
                    growth.markDone(row)
                    // Step to the next open row, so open → reply → D flows down the list.
                    selected = doc.rows.first { $0.n > row.n && !$0.done }?.n ?? row.n
                    return .handled
                }
            }
        } else if growth.engageLoading {
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text("Reading today's list…").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        }
    }

    private func current(_ doc: EngageReport) -> EngageRow? {
        if let selected, let row = doc.rows.first(where: { $0.n == selected }) { return row }
        return doc.nextOpen
    }

    private func move(_ doc: EngageReport, _ step: Int) -> KeyPress.Result {
        guard !doc.rows.isEmpty else { return .ignored }
        let index = doc.rows.firstIndex { $0.n == current(doc)?.n } ?? 0
        selected = doc.rows[min(max(index + step, 0), doc.rows.count - 1)].n
        return .handled
    }

    private func open(_ row: EngageRow) {
        selected = row.n
        if let url = row.link { NSWorkspace.shared.open(url) }
    }

    private func emptyTitle(_ doc: EngageReport) -> String {
        if !doc.targetsExist { return "No targets yet." }
        return doc.sources.values.contains { $0.contains("not scanned today") } ? "Not scanned today." : "Nothing worth a reply today."
    }

    private func emptyDetail(_ doc: EngageReport) -> String {
        if !doc.targetsExist { return "Run `teyla growth engage init`, then put real handles and feeds in ~/.teyla/growth/targets.toml." }
        return doc.sources.sorted { $0.key < $1.key }.map { "\($0.key): \($0.value)" }.joined(separator: "\n")
    }
}

private struct EngageRowView: View {
    let row: EngageRow
    let selected: Bool
    let busy: Bool
    let open: () -> Void
    let done: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Space.m) {
            Text("\(row.n)").font(Typo.caption.monospacedDigit()).foregroundStyle(Palette.textSecondary).frame(minWidth: Space.l, alignment: .trailing)
            VStack(alignment: .leading, spacing: Space.xxs) {
                HStack(spacing: Space.s) {
                    Text(row.author.isEmpty ? row.source : row.author).font(Typo.body.weight(.semibold))
                    if !row.group.isEmpty { Chip(text: row.group, color: Palette.primary) }
                }
                if !row.text.isEmpty { ClampedText(text: row.text, lines: 2, font: Typo.caption, color: Palette.text) }
                if !row.angle.isEmpty {
                    Text("Angle: \(row.angle)").font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
                }
                if !row.why.isEmpty {
                    Text(row.why).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                }
            }
            Spacer(minLength: Space.s)
            Button("Open", action: open).disabled(row.link == nil)
            if row.done {
                Chip(text: "Done", color: Palette.saving, symbol: "checkmark")
            } else if busy {
                ProgressView().controlSize(.small)
            } else {
                Button("Done", action: done).help("I replied: teyla growth engage done \(row.n)")
            }
        }
        .padding(Space.s)
        .background(selected ? Palette.primaryTint : Color.clear, in: RoundedRectangle(cornerRadius: Radius.control))
        .foregroundStyle(row.done ? Palette.textTertiary : Palette.text)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("\(row.n). \(row.author). \(row.angle)")
    }
}

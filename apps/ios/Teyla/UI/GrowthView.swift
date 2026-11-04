import SwiftUI

/// Growth: did every channel get its post today? Posts against the target, what waits for you, the gaps, the queue.
/// The drafts themselves stay on the Mac: the phone reads the relay in iCloud Drive, which Apple can read.
struct GrowthView: View {
    @Binding var tab: AppTab

    var body: some View {
        NavigationStack {
            ConsoleScreen(page: ConsoleText.growth, pick: { $0.growth }) { growth in
                GrowthContent(growth: growth, tab: $tab)
            }
            .navigationTitle(ConsoleText.growth.title)
            .navigationBarTitleDisplayMode(.large)
        }
    }
}

private struct GrowthContent: View {
    @Environment(AppModel.self) private var model
    let growth: GrowthCompact
    @Binding var tab: AppTab

    var body: some View {
        ConsoleTiles(tiles: PhoneConsole.growthTiles(growth))
        channels
        if (growth.pipeline?.review ?? 0) > 0 || growth.pipeline == nil {
            OnMacNote(title: PhoneConsole.draftsLine(growth), detail: PhoneConsole.draftsStayHome)
        }
        ConsoleRows(title: "Queue", rows: PhoneConsole.queueRows(growth))
        ConsoleRows(title: "Pipeline", note: "Where each idea is on its way to a channel.", rows: PhoneConsole.pipelineRows(growth))
        selling
    }

    @ViewBuilder
    private var channels: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Today by channel", note: "Channels still waiting for a post come first.")
            let rows = PhoneConsole.channelRows(growth)
            if rows.isEmpty {
                EmptyState(symbol: "tray", title: "No channel is set up", detail: "Set the channels up on your Mac; they show here.")
            } else {
                RowGroup {
                    ForEach(rows, id: \.row.id) { entry in
                        RowCard(title: entry.name, detail: entry.done ? "Posted" : "Waiting for a post", wraps: true) {
                            HStack(spacing: Space.s) {
                                Text(entry.words)
                                    .font(Typo.body.monospacedDigit())
                                    .foregroundStyle(Palette.textSecondary)
                                Image(systemName: entry.done ? "checkmark.circle.fill" : "circle.dotted")
                                    .foregroundStyle(entry.done ? Palette.saving : Palette.needsYou)
                                    .accessibilityHidden(true)
                            }
                        }
                        .accessibilityElement(children: .combine)
                    }
                }
            }
        }
    }

    /// Products nobody has tried to sell yet: they get the next post, and Products lists them.
    @ViewBuilder
    private var selling: some View {
        if let products = model.snapshot?.portfolio?.products,
           let none = PhoneConsole.notTried(.data(growth), products: products) {
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: "Not tried to sell yet",
                              note: "Nobody posted, ran marketing or met a person who fits. They get the next post.", count: none.next.count)
                Button {
                    tab = .products
                } label: {
                    RowCard(title: none.next.isEmpty ? "Every product has been tried" : "See them in Products",
                            detail: none.parked.isEmpty ? "" : "\(none.parked.count) more are parked.", wraps: true) {
                        Image(systemName: "chevron.right").font(Typo.caption).foregroundStyle(Palette.textTertiary)
                    }
                    .surface(padding: Space.l)
                }
                .buttonStyle(.plain)
                .accessibilityHint("Opens Products")
            }
        }
    }
}

import SwiftUI

// The pieces every admin screen on the phone is made of. A screen sits on `Page`, leads with a `StatStrip`, and shows
// only what the compact snapshot carries (`PhoneConsole`). Long text wraps; nothing is cut off.

/// A screen of the console: waits while there is no snapshot, says why a section has no data, and otherwise shows `content`.
struct ConsoleScreen<Value: Equatable & Sendable, Content: View>: View {
    @Environment(AppModel.self) private var model
    let page: ConsoleText.Page
    let pick: (ConsoleCompact) -> ConsoleLoad<Value>
    /// Shown above the section whatever the console holds (Growth's activity card).
    var leading: AnyView?
    @ViewBuilder var content: (Value) -> Content

    var body: some View {
        if let snapshot = model.snapshot {
            let load = snapshot.console.map { pick($0.compact) } ?? .missing
            Page {
                VStack(alignment: .leading, spacing: Space.xs) {
                    Text(page.question)
                        .font(Typo.body)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    SyncLine()
                }
                if let leading { leading }
                switch load {
                case .data(let value):
                    content(value)
                case .failed(let why):
                    ErrorRow(section: page.title, message: why) { Task { await model.refresh() } }
                case .missing:
                    EmptyState(symbol: "arrow.triangle.2.circlepath", title: "\(page.title) is not in this update yet",
                               detail: "Update Teyla on your Mac, then pull down to check again.")
                }
            }
            .refreshable { await model.refresh() }
        } else {
            ScrollView { WaitingView().padding(Space.page) }
                .background(Palette.background)
        }
    }
}

/// The figures of a screen: tiles in two columns on a phone.
struct ConsoleTiles: View {
    let tiles: [ConsoleTile]

    var body: some View {
        StatStrip {
            ForEach(tiles) { tile in
                StatTile(label: tile.label, value: tile.value, detail: tile.detail, tone: tile.tone)
            }
        }
    }
}

/// A list of figures: the name and its note on the left, the figure on the right (a dash when the phone has none).
struct ConsoleRows: View {
    let title: String
    var note = ""
    let rows: [ConsoleRow]

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: title, note: note)
            RowGroup {
                ForEach(rows) { row in
                    RowCard(title: row.title, detail: row.note, wraps: true) {
                        Text(row.value ?? Format.dash)
                            .font(Typo.body.weight(.semibold).monospacedDigit())
                            .foregroundStyle(row.value == nil ? Palette.textTertiary : Palette.text)
                            .multilineTextAlignment(.trailing)
                    }
                }
            }
        }
    }
}

/// A short note about what stays on the Mac, with the reason.
struct OnMacNote: View {
    let title: String
    let detail: String

    var body: some View {
        EmptyState(symbol: "desktopcomputer", title: title, detail: detail)
            .surface(padding: Space.m)
            .accessibilityElement(children: .combine)
    }
}

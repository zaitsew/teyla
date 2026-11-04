import SwiftUI

/// More: the admin screens that are not a tab of their own (Money, Operations, Playbook) and Settings.
/// Each row shows its live figure, so the list says something before a row is opened.
struct MoreView: View {
    @Environment(AppModel.self) private var model
    @State private var path: [PhoneConsole.MoreItem]

    init(options: LaunchOptions = LaunchOptions()) {
        _path = State(initialValue: options.more.map { [$0] } ?? [])
    }

    var body: some View {
        NavigationStack(path: $path) {
            Page {
                VStack(alignment: .leading, spacing: Space.xs) {
                    Text("The rest of your admin, and this phone's settings.")
                        .font(Typo.body)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    SyncLine()
                }
                RowGroup {
                    ForEach(PhoneConsole.MoreItem.allCases) { item in
                        NavigationLink(value: item) {
                            RowCard(title: item.title, detail: line(item), wraps: true,
                                    leading: { icon(item) },
                                    trailing: { chevron })
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .refreshable { await model.refresh() }
            .navigationTitle("More")
            .navigationBarTitleDisplayMode(.large)
            .navigationDestination(for: PhoneConsole.MoreItem.self) { item in
                destination(item)
            }
        }
    }

    private func line(_ item: PhoneConsole.MoreItem) -> String {
        PhoneConsole.moreLine(item, console: model.snapshot?.console?.compact, status: Self.statusText(model.connection))
    }

    private func icon(_ item: PhoneConsole.MoreItem) -> some View {
        Image(systemName: item.symbol)
            .font(Typo.body)
            .foregroundStyle(Palette.textSecondary)
            .frame(width: Space.glyph)
            .accessibilityHidden(true)
    }

    private var chevron: some View {
        Image(systemName: "chevron.right")
            .font(Typo.caption.weight(.semibold))
            .foregroundStyle(Palette.textTertiary)
            .accessibilityHidden(true)
    }

    @ViewBuilder
    private func destination(_ item: PhoneConsole.MoreItem) -> some View {
        switch item {
        case .money: MoneyScreen()
        case .operations: OperationsScreen()
        case .playbook: PlaybookScreen()
        case .settings: SettingsView()
        }
    }

    static func statusText(_ connection: Connection) -> String {
        switch connection {
        case .live: return "Connected"
        case .fixture: return "Preview data"
        case .sample: return "Sample data"
        case .syncing: return "Syncing"
        case .waiting: return "Waiting for the Mac"
        case .reading: return "Reading"
        }
    }
}

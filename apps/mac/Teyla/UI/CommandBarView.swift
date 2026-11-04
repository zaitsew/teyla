import SwiftUI

/// The ⌘K sheet: type, move with the arrow keys, Return chooses, Escape closes. The list is fixed and matched as plain text.
struct CommandBarView: View {
    @Environment(AppModel.self) private var model
    @FocusState private var focused: Bool

    var body: some View {
        let bar = model.commandBar
        let results = bar.results
        VStack(spacing: 0) {
            TextField("Go to a page, a product or an action", text: Bindable(bar).query)
                .textFieldStyle(.plain)
                .font(Typo.cardTitle)
                .padding(Space.l)
                .focused($focused)
                .onSubmit { if let entry = bar.highlighted { model.choose(entry) } }
                .onKeyPress(.downArrow) { bar.move(by: 1); return .handled }
                .onKeyPress(.upArrow) { bar.move(by: -1); return .handled }
                .accessibilityLabel("Command bar")
            Divider()
            if results.isEmpty {
                Text("Nothing matches. This list is fixed: pages, products, New task, Refresh and the actions on Tools.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .padding(Space.l)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                ScrollViewReader { reader in
                    ScrollView {
                        VStack(spacing: Space.xxs) {
                            ForEach(Array(results.enumerated()), id: \.element.id) { index, entry in
                                Row(entry: entry, selected: index == bar.selection)
                                    .id(entry.id)
                                    .contentShape(Rectangle())
                                    .onTapGesture { model.choose(entry) }
                            }
                        }
                        .padding(Space.s)
                    }
                    .onChange(of: bar.selection) { _, index in
                        if results.indices.contains(index) { reader.scrollTo(results[index].id) }
                    }
                }
                .frame(height: Space.commandBarList)
            }
        }
        .frame(width: Space.commandBarWidth)
        .background(Palette.surface)
        .onExitCommand { bar.close() }
        .onAppear { focused = true }
    }

    private struct Row: View {
        let entry: CommandEntry
        let selected: Bool

        var body: some View {
            HStack(spacing: Space.m) {
                Image(systemName: entry.symbol)
                    .frame(width: Space.glyph)
                    .foregroundStyle(Palette.textSecondary)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(entry.title).font(Typo.body)
                    Text(entry.changesState ? entry.detail + " · asks before it runs" : entry.detail)
                        .font(entry.changesState ? Typo.code : Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, Space.m)
            .padding(.vertical, Space.s)
            .background(selected ? Palette.primaryTint : Color.clear, in: RoundedRectangle(cornerRadius: Radius.card))
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(selected ? .isSelected : [])
        }
    }
}

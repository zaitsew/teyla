import SwiftUI

struct MenuBarLabel: View {
    let model: AppModel

    var body: some View {
        let count = model.visibleAsks.count
        HStack(spacing: Space.xs) {
            Image(systemName: count > 0 ? "bubble.left.fill" : "bubble.left")
            if count > 0 { Text("\(count)") }
        }
        .accessibilityLabel(count == 0 ? "Teyla, no questions" : "Teyla, \(count) questions")
    }
}

struct MenuBarContent: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Text(model.briefLine)
                .font(.headline)
                .fixedSize(horizontal: false, vertical: true)

            let top = Array(model.visibleAsks.prefix(3))
            if !top.isEmpty {
                Divider()
                ForEach(top) { ask in
                    Button {
                        model.focus(askID: ask.id)
                    } label: {
                        VStack(alignment: .leading, spacing: Space.xxs) {
                            Text(Format.product(ask.product))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text(ask.question)
                                .lineLimit(2)
                                .multilineTextAlignment(.leading)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }

            Divider()
            Button {
                model.openQuickNote()
            } label: {
                Text(QuickNoteShortcut.menuTitle(model.quickNoteActive))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            HStack {
                Button("Open Teyla", action: show)
                Button("New task") { model.openNewTask() }
                Spacer()
                Button("Quit") { NSApp.terminate(nil) }
                    .keyboardShortcut("q")
            }
        }
        .padding(Space.l)
        .frame(width: Space.menuWidth)
        .onAppear { model.openMainWindow = { openWindow(id: "main") } }
    }

    private func show() {
        openWindow(id: "main")
        NSApp.activate(ignoringOtherApps: true)
    }
}

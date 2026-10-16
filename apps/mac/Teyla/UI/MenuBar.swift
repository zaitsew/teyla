import SwiftUI

struct MenuBarLabel: View {
    let model: AppModel

    var body: some View {
        let count = model.visibleAsks.count
        HStack(spacing: 3) {
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
        VStack(alignment: .leading, spacing: 10) {
            Text(model.briefLine)
                .font(.headline)
                .fixedSize(horizontal: false, vertical: true)

            let top = Array(model.visibleAsks.prefix(3))
            if !top.isEmpty {
                Divider()
                ForEach(top) { ask in
                    Button {
                        show()
                    } label: {
                        VStack(alignment: .leading, spacing: 1) {
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
            HStack {
                Button("Open Teyla", action: show)
                Spacer()
                Button("Quit") { NSApp.terminate(nil) }
                    .keyboardShortcut("q")
            }
        }
        .padding(14)
        .frame(width: 320)
        .onAppear { model.openMainWindow = { openWindow(id: "main") } }
    }

    private func show() {
        openWindow(id: "main")
        NSApp.activate()
    }
}

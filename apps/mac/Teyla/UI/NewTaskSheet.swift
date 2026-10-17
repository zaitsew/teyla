import SwiftUI

/// Starts a new session in a fresh worktree: pick the product and the tool, say what to do.
struct NewTaskSheet: View {
    @Environment(AppModel.self) private var model
    @AppStorage(Voice.defaultsKey) private var localeID = Voice.locales[0].id
    @FocusState private var fieldFocused: Bool

    var body: some View {
        let task = model.newTask
        let products = NewTask.products(model.snapshot?.products ?? [])
        VStack(alignment: .leading, spacing: Space.l) {
            Text("New task").font(Typo.lead)

            HStack(spacing: Space.l) {
                Picker("Product", selection: Bindable(task).product) {
                    ForEach(products) { product in
                        Text(Format.product(product.name)).tag(Optional(product.name))
                    }
                }
                .fixedSize()
                Spacer(minLength: Space.s)
                Picker("Run with", selection: Bindable(task).harness) {
                    ForEach(Harness.allCases) { harness in
                        Text(harness.label).tag(harness)
                    }
                }
                .pickerStyle(.segmented)
                .fixedSize()
            }
            .disabled(task.isSending)

            VStack(alignment: .leading, spacing: Space.xs) {
                HStack(alignment: .top, spacing: Space.s) {
                    TextField("What should it do?", text: Bindable(task).draft, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(4...10)
                        .focused($fieldFocused)
                        .disabled(task.isSending)
                    MicButton(target: NewTaskModel.dictationTarget, text: Bindable(task).draft)
                }
                HStack(spacing: Space.s) {
                    Picker("Voice language", selection: $localeID) {
                        ForEach(Voice.locales) { locale in
                            Text(locale.name).tag(locale.id)
                        }
                    }
                    .fixedSize()
                    Text("⌥⌘Space talks from any app.")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                }
                DictationNote(target: NewTaskModel.dictationTarget)
            }

            outcome

            HStack {
                Spacer()
                switch task.status {
                case .done:
                    if let link = task.result?.link, !link.isEmpty {
                        Button("Open session") { model.openSession(link, noteKey: "new-task") }
                    }
                    Button("Close") { task.dismiss() }
                        .buttonStyle(.borderedProminent)
                        .keyboardShortcut(.defaultAction)
                default:
                    Button("Cancel") { task.dismiss() }
                        .keyboardShortcut(.cancelAction)
                    Button("Send") { task.send() }
                        .buttonStyle(.borderedProminent)
                        .keyboardShortcut(.return, modifiers: .command)
                        .disabled(!NewTask.canSend(product: task.product, text: task.draft) || task.isSending)
                }
            }
        }
        .padding(Space.xl)
        .frame(width: 520)
        .onAppear { fieldFocused = true }
        .onChange(of: task.draft) { _, new in
            if case .done = task.status, !new.isEmpty { task.resetResult() }
        }
    }

    @ViewBuilder private var outcome: some View {
        let task = model.newTask
        switch task.status {
        case .sending(let text):
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text(text).foregroundStyle(Palette.textSecondary)
            }
        case .done(let text):
            Label(text, systemImage: "checkmark.circle.fill")
                .foregroundStyle(Palette.success)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        case .failed(let message):
            Label(message, systemImage: "exclamationmark.triangle.fill")
                .foregroundStyle(Palette.danger)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
        case nil:
            if products(task).isEmpty {
                Text("No product can take a task yet.").foregroundStyle(Palette.textSecondary)
            }
        }
    }

    private func products(_ task: NewTaskModel) -> [Product] {
        NewTask.products(model.snapshot?.products ?? [])
    }
}

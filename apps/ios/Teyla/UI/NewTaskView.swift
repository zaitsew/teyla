import SwiftUI

/// Starts a new session in a product: pick the product, say or write what to do, Send.
struct NewTaskView: View {
    @Environment(AppModel.self) private var model
    @Environment(Dictation.self) private var dictation
    @Environment(\.dismiss) private var dismiss
    @State private var product = ""
    @State private var text = ""
    @State private var sending = false
    @FocusState private var focused: Bool

    private var canSend: Bool {
        !product.isEmpty && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !sending
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("Product", selection: $product) {
                        Text("Choose a product").tag("")
                        ForEach(model.dispatchTargets) { Text(Format.product($0.name)).tag($0.name) }
                    }
                    .pickerStyle(.menu)
                }
                Section {
                    TextField("What should it do?", text: $text, axis: .vertical)
                        .lineLimit(5...12)
                        .focused($focused)
                    HStack {
                        MicButton(text: $text, field: "new-task")
                        Text(dictation.isRecording("new-task") ? "Listening on this iPhone" : "Dictate")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        Spacer()
                    }
                } header: {
                    Text("Task")
                } footer: {
                    Text("The Mac starts it in a fresh worktree. Nothing is sent until you tap Send.")
                }
                if let message = dictation.message ?? model.sendError {
                    Section { Text(message).font(.footnote).foregroundStyle(.red) }
                }
            }
            .scrollDismissesKeyboard(.interactively)
            .navigationTitle("New task")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dictation.stop(); dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send") { send() }
                        .fontWeight(.semibold)
                        .disabled(!canSend)
                }
            }
        }
        .onAppear { model.sendError = nil }
        .onDisappear { dictation.stop() }
    }

    private func send() {
        dictation.stop()
        model.sendError = nil
        sending = true
        let target = product
        let body = text
        Task {
            let ok = await model.send(kind: .dispatch, target: target, aboutText: target, label: target, text: body)
            sending = false
            if ok { dismiss() }
        }
    }
}

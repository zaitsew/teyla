import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @AppStorage("dictationLanguage") private var languageID = DictationLanguage.english.rawValue
    @State private var confirmForget = false
    @State private var showFolderPicker = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Mac") {
                    LabeledContent("Status", value: statusText)
                    if let folder = model.folderName {
                        LabeledContent("Folder", value: folder)
                    }
                    if let date = model.syncDate {
                        LabeledContent("Last update") {
                            Text(date, format: .dateTime.month().day().hour().minute())
                        }
                    }
                    if !model.isFixture {
                        Button("Choose another folder") { showFolderPicker = true }
                        Button("Pair again") {
                            model.restartPairing()
                            dismiss()
                        }
                        Button("Forget this Mac", role: .destructive) { confirmForget = true }
                    }
                }
                Section {
                    Picker("Language", selection: $languageID) {
                        ForEach(DictationLanguage.allCases) { Text($0.title).tag($0.rawValue) }
                    }
                } header: {
                    Text("Voice")
                } footer: {
                    Text("Speech is recognised on this iPhone only. No audio leaves it, and nothing is sent until you tap Send.")
                }
                Section("About") {
                    LabeledContent("Version", value: Self.version)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .confirmationDialog("Forget this Mac?", isPresented: $confirmForget, titleVisibility: .visible) {
                Button("Forget", role: .destructive) {
                    model.forgetMac()
                    dismiss()
                }
            } message: {
                Text("Teyla deletes the shared key and the folder. Anything not yet delivered is dropped from this iPhone.")
            }
            .sheet(isPresented: $showFolderPicker) {
                FolderPicker { url in
                    showFolderPicker = false
                    if let url { model.chooseFolder(url) }
                }
                .ignoresSafeArea()
            }
        }
    }

    private var statusText: String {
        switch model.connection {
        case .live: return "Connected"
        case .fixture: return "Preview data"
        case .syncing: return "Syncing"
        case .waiting: return "Waiting for the Mac"
        case .reading: return "Reading"
        }
    }

    private static var version: String {
        let info = Bundle.main.infoDictionary
        let short = info?["CFBundleShortVersionString"] as? String ?? "0"
        let build = info?["CFBundleVersion"] as? String ?? "0"
        return "\(short) (\(build))"
    }
}

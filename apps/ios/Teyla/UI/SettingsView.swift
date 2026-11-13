import SwiftUI

/// Settings, pushed from More: the Mac this phone reads, the dictation language, and what travels. On `Page` like the
/// other screens; the buttons are rows, so a long folder name wraps instead of being cut.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @AppStorage("dictationLanguage") private var languageID = DictationLanguage.english.rawValue
    @AppStorage(MorningCardLogic.labKey) private var morningCardOn = false
    @AppStorage(TodayVariant.storageKey) private var todayVariant = TodayVariant.off.rawValue
    @State private var confirmForget = false
    @State private var showFolderPicker = false

    var body: some View {
        Page {
            macBlock
            voiceBlock
            labBlock
            travelsBlock
            aboutBlock
        }
        .navigationTitle("Settings")
        .navigationBarTitleDisplayMode(.large)
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

    // MARK: Blocks

    private var macBlock: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Your Mac")
            RowGroup {
                fact("Status", MoreView.statusText(model.connection))
                if let folder = model.folderName { fact("Folder", folder) }
                if let date = model.syncDate {
                    RowCard(title: "Last update", wraps: true) {
                        Text(date, format: .dateTime.month().day().hour().minute())
                            .font(Typo.body)
                            .foregroundStyle(Palette.textSecondary)
                    }
                }
                if model.isSample {
                    action("Pair with your Mac") { model.leaveSample() }
                } else if !model.isFixture {
                    action("Choose another folder") { showFolderPicker = true }
                    action("Pair again") { model.restartPairing() }
                    action("Forget this Mac", destructive: true) { confirmForget = true }
                }
            }
        }
    }

    private var voiceBlock: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Voice",
                          note: "Speech is recognised on this iPhone only. No audio leaves it.")
            RowGroup {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text("Dictation language").font(Typo.body.weight(.semibold))
                    Picker("Dictation language", selection: $languageID) {
                        ForEach(DictationLanguage.allCases) { Text($0.title).tag($0.rawValue) }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.vertical, Space.s)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var labBlock: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Lab",
                          note: "One question each morning, one post in your words. Drafts stay on this iPhone. The Today screen replaces Home.")
            RowGroup {
                Toggle("Morning post card", isOn: $morningCardOn)
                    .font(Typo.body.weight(.semibold))
                    .padding(.vertical, Space.s)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text("Today screen").font(Typo.body.weight(.semibold))
                    Picker("Today screen", selection: $todayVariant) {
                        ForEach(TodayVariant.allCases) { Text($0.title).tag($0.rawValue) }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(.vertical, Space.s)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
    }

    private var travelsBlock: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "What this phone gets")
            OnMacNote(title: "Counts and headlines, not your drafts",
                      detail: "Your Mac shares figures and product names through iCloud Drive. Apple can read that folder, so the text of your posts stays on the Mac. Nothing is sent until you tap Send.")
        }
    }

    private var aboutBlock: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "About")
            RowGroup { fact("Version", Self.version) }
        }
    }

    // MARK: Rows

    private func fact(_ title: String, _ value: String) -> some View {
        RowCard(title: title, wraps: true) {
            Text(value)
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.trailing)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }

    private func action(_ title: String, destructive: Bool = false, run: @escaping () -> Void) -> some View {
        Button(action: run) {
            RowCard(title: title, wraps: true) { EmptyView() }
                .foregroundStyle(destructive ? Palette.danger : Palette.primary)
        }
        .buttonStyle(.plain)
    }

    private static var version: String {
        let info = Bundle.main.infoDictionary
        let short = info?["CFBundleShortVersionString"] as? String ?? "0"
        let build = info?["CFBundleVersion"] as? String ?? "0"
        return "\(short) (\(build))"
    }
}

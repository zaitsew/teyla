import AppKit
import SwiftUI

// The store build's own screens: the setup, the sample banner and the Mac section of Settings.
// They exist only in the TeylaStore target.

/// The commands of the setup, one place so the Copy buttons and the text cannot differ.
enum StoreSetup {
    static let install = "uv tool install --python 3.12 git+https://github.com/zaitsew/teyla"
    static let relayOn = "teyla relay on"
    static let relayPair = "teyla relay pair"
    static let bannerText = "Sample data — connect to see yours"

    @MainActor
    static func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    /// The open panel for the relay folder. It starts in iCloud Drive when the sandbox lets it.
    @MainActor
    static func chooseFolder(_ then: (URL) -> Void) {
        let panel = NSOpenPanel()
        panel.message = "Choose the Teyla folder in iCloud Drive"
        panel.prompt = "Choose"
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.canCreateDirectories = false
        panel.allowsMultipleSelection = false
        if let home = getpwuid(getuid()).flatMap({ $0.pointee.pw_dir }).map({ String(cString: $0) }) {
            panel.directoryURL = URL(fileURLWithPath: home)
                .appendingPathComponent("Library/Mobile Documents/com~apple~CloudDocs/Teyla", isDirectory: true)
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        then(url)
    }
}

/// "Connect Teyla on this Mac": what to run on the Mac, which folder to choose, where to paste the pairing
/// string, and a sample for anyone who wants to look first (App Review included).
struct StoreSetupView: View {
    @Environment(AppModel.self) private var model
    @State private var pairing = ""
    @State private var copied: String?

    var body: some View {
        let store = model.store
        ScrollView {
            VStack(spacing: Space.xl) {
                BrandLockup()
                VStack(spacing: Space.s) {
                    Text("Connect Teyla on this Mac")
                        .font(Typo.brief)
                    Text("Teyla shows what needs you across your AI coding sessions. This version cannot run commands, "
                         + "so it reads what the teyla command writes to a folder in iCloud Drive, and sends your answers back the same way.")
                        .foregroundStyle(Palette.textSecondary)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: Space.readingWidth)

                VStack(spacing: Space.s) {
                    Button {
                        store.useSample()
                    } label: {
                        Label("See a sample", systemImage: "play.rectangle")
                            .padding(.horizontal, Space.m)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    Text("Every screen, with made-up data. Nothing is read or sent.")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                }

                VStack(alignment: .leading, spacing: Space.l) {
                    Text("Or connect your Mac")
                        .font(Typo.lead)
                    step(1, "Install the teyla command", "In Terminal, on the Mac whose sessions you want to see.") {
                        commandRow(StoreSetup.install)
                    }
                    step(2, "Turn on the relay and pair", "The second command prints a pairing string. Keep it for step 3.") {
                        commandRow(StoreSetup.relayOn)
                        commandRow(StoreSetup.relayPair)
                    }
                    step(3, "Choose the folder and paste the pairing string",
                         "The folder is Teyla in iCloud Drive. Teyla keeps access to it, and keeps the key in your Keychain.") {
                        folderRow(store)
                        HStack(spacing: Space.s) {
                            TextField("teyla-pair:v1:…", text: $pairing)
                                .textFieldStyle(.roundedBorder)
                                .font(.system(.body, design: .monospaced))
                                .onSubmit(connect)
                            Button("Connect", action: connect)
                                .buttonStyle(.borderedProminent)
                                .disabled(!store.hasFolder || pairing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                        if let notice = store.notice {
                            Label(notice, systemImage: "exclamationmark.triangle.fill")
                                .font(Typo.caption)
                                .foregroundStyle(Palette.danger)
                                .fixedSize(horizontal: false, vertical: true)
                                .textSelection(.enabled)
                        }
                    }
                }
                .frame(maxWidth: Space.readingWidth, alignment: .leading)
            }
            .padding(Space.xxl)
            .frame(maxWidth: .infinity)
        }
        .background(Palette.background)
        .navigationTitle("Teyla")
    }

    private func connect() {
        guard model.store.hasFolder else { return }
        if model.store.pair(with: pairing) { pairing = "" }
    }

    private func step<Content: View>(_ number: Int, _ title: String, _ detail: String,
                                     @ViewBuilder content: () -> Content) -> some View {
        HStack(alignment: .top, spacing: Space.m) {
            Text("\(number)")
                .font(Typo.lead)
                .foregroundStyle(Palette.onPrimary)
                .frame(width: Space.xl, height: Space.xl)
                .background(Palette.primary, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Space.s) {
                Text(title).font(Typo.lead)
                Text(detail)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                content()
            }
        }
        .accessibilityElement(children: .contain)
    }

    private func commandRow(_ command: String) -> some View {
        HStack(spacing: Space.m) {
            Text(command)
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: Space.s)
            Button {
                StoreSetup.copy(command)
                copied = command
                Task {
                    try? await Task.sleep(for: .seconds(2))
                    if copied == command { copied = nil }
                }
            } label: {
                Label(copied == command ? "Copied" : "Copy", systemImage: copied == command ? "checkmark" : "doc.on.doc")
            }
            .controlSize(.small)
        }
        .padding(Space.m)
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: Radius.card))
        .overlay(RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Palette.border, lineWidth: 1))
    }

    private func folderRow(_ store: StoreSession) -> some View {
        HStack(spacing: Space.m) {
            Button("Choose folder…") { StoreSetup.chooseFolder(store.chooseFolder) }
            if let name = store.folderName {
                Label(name, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Palette.success)
            } else {
                Text("No folder chosen").foregroundStyle(Palette.textSecondary)
            }
        }
    }
}

/// The bar above the window while the sample is shown. It stays until the owner connects a Mac.
struct SampleBanner: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: Space.s) {
            Image(systemName: "info.circle.fill")
                .foregroundStyle(Palette.primary)
                .accessibilityHidden(true)
            Text(StoreSetup.bannerText)
                .font(Typo.body.weight(.medium))
            Spacer(minLength: Space.s)
            Button("Connect") { model.store.leaveSample() }
                .controlSize(.small)
        }
        .padding(.horizontal, Space.l)
        .padding(.vertical, Space.s)
        .background(Palette.primary.opacity(0.12))
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .combine)
    }
}

/// Settings: which Mac this Teyla reads, and how to change it.
struct StoreSettingsSection: View {
    @Environment(AppModel.self) private var model
    @State private var pairing = ""
    @State private var repairing = false

    var body: some View {
        let store = model.store
        Section("Mac") {
            switch store.mode {
            case .sample:
                Text("Showing sample data. Nothing is read or sent.")
                    .foregroundStyle(Palette.textSecondary)
                Button("Connect a Mac…") { store.leaveSample() }
            case .setup:
                Text("Not connected to a Mac.").foregroundStyle(Palette.textSecondary)
            case .connected:
                LabeledContent("Folder") { Text(store.folderName ?? "—").foregroundStyle(Palette.textSecondary) }
                LabeledContent("Status") {
                    TimelineView(.periodic(from: .now, by: 30)) { context in
                        Text(status(at: context.date)).foregroundStyle(Palette.textSecondary)
                    }
                }
                HStack(spacing: Space.s) {
                    Button("Choose another folder…") { StoreSetup.chooseFolder(store.chooseFolder) }
                    Button("Pair again…") { repairing.toggle() }
                    Button("Forget this Mac", role: .destructive) { store.forgetMac() }
                }
                if repairing {
                    HStack(spacing: Space.s) {
                        TextField("teyla-pair:v1:…", text: $pairing)
                            .textFieldStyle(.roundedBorder)
                            .font(.system(.body, design: .monospaced))
                        Button("Pair") {
                            if store.pair(with: pairing) { pairing = ""; repairing = false }
                        }
                        .disabled(pairing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    Text("Run teyla relay pair on the Mac to print the string.")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                }
                if let notice = store.notice {
                    Label(notice, systemImage: "exclamationmark.triangle.fill")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.danger)
                        .textSelection(.enabled)
                }
            }
            Text("iCloud Drive holds the snapshot and your answers as readable text, and Apple can read them unless "
                 + "you turn on Advanced Data Protection. The pairing key stays in your Keychain, and nobody can "
                 + "send an action without it.")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private func status(at now: Date) -> String {
        guard let written = model.snapshot?.generatedDate else { return "Waiting for the Mac" }
        let ago = Format.age(seconds: max(0, now.timeIntervalSince(written)))
        return ago == "just now" ? "Mac synced just now" : "Mac synced \(ago) ago"
    }
}

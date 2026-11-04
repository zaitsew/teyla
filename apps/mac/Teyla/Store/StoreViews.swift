import AppKit
import SwiftUI

// The store build's own screens: the setup, the sample banner and the Mac section of Settings.
// They exist only in the TeylaStore target.

/// The commands of the setup, one place so the Copy buttons and the text cannot differ.
enum StoreSetup {
    static let install = "uv tool install --python 3.12 git+https://github.com/zaitsew/teyla"
    /// Turns the relay on, makes the key, runs one sync and hands the key to this app by a `teyla-pair:` link.
    static let connect = "teyla relay connect"
    static let relayOn = "teyla relay on"
    static let relayPair = "teyla relay pair"
    static let bannerText = "Sample data — connect to see yours"
    /// The one line the owner pastes in Terminal.
    static let oneCommand = "\(install) && \(connect)"
    /// One sentence for a coding agent that has a terminal on this Mac. It names no model provider.
    static let agentPrompt = "Install Teyla on this Mac and connect it to the Teyla app by running this command in a terminal, "
        + "then tell me when it has finished: \(oneCommand)"
    static let terminalBundleID = "com.apple.Terminal"

    @MainActor
    static func copy(_ text: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
    }

    /// Opens Terminal. The sandbox lets the app launch another app; it cannot type into it, so the command is copied.
    @MainActor @discardableResult
    static func openTerminal() -> Bool {
        guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: terminalBundleID) else { return false }
        NSWorkspace.shared.openApplication(at: url, configuration: NSWorkspace.OpenConfiguration())
        return true
    }

    /// The open panel for the relay folder. It opens on the Teyla folder in iCloud Drive when that exists
    /// (one click), else on iCloud Drive with New Folder allowed (`FolderPanelPlan`).
    @MainActor
    static func chooseFolder(_ then: (URL) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = false
        panel.canChooseDirectories = true
        panel.allowsMultipleSelection = false
        if let home = FolderPanelPlan.realHome() {
            let plan = FolderPanelPlan.make(home: home, exists: FolderPanelPlan.directoryExists)
            panel.directoryURL = plan.directory
            panel.prompt = plan.prompt
            panel.message = plan.message
            panel.canCreateDirectories = plan.canCreateDirectories
        } else {
            panel.prompt = "Use this folder"
            panel.message = "Choose the Teyla folder in iCloud Drive"
            panel.canCreateDirectories = true
        }
        guard panel.runModal() == .OK, let url = panel.url else { return }
        then(url)
    }
}

/// "Connect Teyla on this Mac": one paste in Terminal, or a prompt for a coding agent, or a sample for anyone who
/// wants to look first (App Review included). The manual path sits behind "Connect by hand".
struct StoreSetupView: View {
    @Environment(AppModel.self) private var model
    @State private var pairing = ""
    @State private var copied: String?
    @State private var terminalOpened = false
    @State private var commandShown = false
    @State private var agentCopied = false
    @State private var byHand: Bool
    /// Another session, for a preview of a state this Mac's Keychain is not in.
    private let override: StoreSession?

    init(store: StoreSession? = nil, expanded: Bool = false) {
        override = store
        _byHand = State(initialValue: expanded)
    }

    var body: some View {
        let store = override ?? model.store
        ScrollView {
            VStack(spacing: Space.xl) {
                BrandLockup()
                VStack(spacing: Space.s) {
                    Text("Connect Teyla on this Mac")
                        .font(Typo.pageTitle)
                    Text("Teyla shows what needs you across your AI coding sessions. It reads what the teyla command writes "
                         + "to a folder in iCloud Drive, and sends your answers back the same way.")
                        .foregroundStyle(Palette.textSecondary)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: Space.readingWidth)

                if store.hasKey && !store.hasFolder {
                    folderPrompt(store)
                } else {
                    automatic
                }
                if let notice = store.notice {
                    Label(notice, systemImage: "exclamationmark.triangle.fill")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.danger)
                        .fixedSize(horizontal: false, vertical: true)
                        .textSelection(.enabled)
                        .frame(maxWidth: Space.readingWidth, alignment: .leading)
                }

                VStack(spacing: Space.s) {
                    Button {
                        store.useSample()
                    } label: {
                        Label("See a sample", systemImage: "play.rectangle")
                            .padding(.horizontal, Space.m)
                    }
                    .controlSize(.large)
                    Text("Every screen, with made-up data. Nothing is read or sent.")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                }

                DisclosureGroup("Connect by hand", isExpanded: $byHand) {
                    manual(store)
                        .padding(.top, Space.m)
                }
                .frame(maxWidth: Space.readingWidth, alignment: .leading)
            }
            .padding(Space.xxl)
            .frame(maxWidth: .infinity)
        }
        .background(Palette.background)
        .navigationTitle("Teyla")
    }

    // MARK: The automatic way

    private var automatic: some View {
        VStack(spacing: Space.m) {
            Button {
                StoreSetup.copy(StoreSetup.oneCommand)
                terminalOpened = StoreSetup.openTerminal()
                commandShown = true
            } label: {
                Label("Copy command and open Terminal", systemImage: "terminal")
                    .padding(.horizontal, Space.m)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            if commandShown {
                VStack(spacing: Space.s) {
                    Text(terminalOpened
                         ? "Paste it in Terminal and press Return. Teyla connects by itself."
                         : "The command is copied. Open Terminal, paste it and press Return. Teyla connects by itself.")
                        .font(Typo.cardTitle)
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                    commandRow(StoreSetup.oneCommand)
                }
                .frame(maxWidth: Space.readingWidth)
            }
            Button {
                StoreSetup.copy(StoreSetup.agentPrompt)
                agentCopied = true
            } label: {
                Label(agentCopied ? "Copied. Paste it to your coding agent." : "Let your coding agent do it",
                      systemImage: agentCopied ? "checkmark" : "sparkles")
            }
            .controlSize(.large)
            Text("Copies one sentence for an agent that has a terminal on this Mac.")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
        }
    }

    /// The key is in the Keychain and the folder is not chosen: one click finishes it.
    private func folderPrompt(_ store: StoreSession) -> some View {
        VStack(spacing: Space.m) {
            Label("The Mac is paired. One more step.", systemImage: "checkmark.circle.fill")
                .font(Typo.cardTitle)
                .foregroundStyle(Palette.saving)
            Text("Choose the Teyla folder in iCloud Drive. The panel opens on it.")
                .foregroundStyle(Palette.textSecondary)
            Button {
                StoreSetup.chooseFolder(store.chooseFolder)
            } label: {
                Label("Choose folder…", systemImage: "folder")
                    .padding(.horizontal, Space.m)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }

    // MARK: By hand

    private func manual(_ store: StoreSession) -> some View {
        VStack(alignment: .leading, spacing: Space.l) {
            step(1, "Install the teyla command", "In Terminal, on the Mac whose sessions you want to see.") {
                commandRow(StoreSetup.install)
            }
            step(2, "Turn on the relay and pair", "The second command prints a pairing string. Keep it for step 3.") {
                commandRow(StoreSetup.relayOn)
                commandRow(StoreSetup.relayPair)
            }
            step(3, "Paste the pairing string and choose the folder",
                 "Do them in either order. The folder is Teyla in iCloud Drive. Teyla keeps access to it, and keeps the key in your Keychain.") {
                folderRow(store)
                HStack(spacing: Space.s) {
                    TextField("teyla-pair:v1:…", text: $pairing)
                        .textFieldStyle(.roundedBorder)
                        .font(Typo.code)
                        .onSubmit(connect)
                    Button(store.hasKey ? "Replace key" : "Pair", action: connect)
                        .buttonStyle(.borderedProminent)
                        .disabled(pairing.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                if store.hasKey {
                    Label("Key saved", systemImage: "checkmark.circle.fill")
                        .foregroundStyle(Palette.saving)
                }
            }
        }
    }

    private func connect() {
        if (override ?? model.store).pair(with: pairing) { pairing = "" }
    }

    private func step<Content: View>(_ number: Int, _ title: String, _ detail: String,
                                     @ViewBuilder content: () -> Content) -> some View {
        HStack(alignment: .top, spacing: Space.m) {
            Text("\(number)")
                .font(Typo.cardTitle)
                .foregroundStyle(Palette.onPrimary)
                .frame(width: Space.xl, height: Space.xl)
                .background(Palette.primary, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: Space.s) {
                Text(title).font(Typo.cardTitle)
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
                .font(Typo.code)
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
        .overlay(RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Palette.border, lineWidth: Space.hairline))
    }

    private func folderRow(_ store: StoreSession) -> some View {
        HStack(spacing: Space.m) {
            Button("Choose folder…") { StoreSetup.chooseFolder(store.chooseFolder) }
            if let name = store.folderName {
                Label(name, systemImage: "checkmark.circle.fill")
                    .foregroundStyle(Palette.saving)
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
        .background(Palette.primaryTint)
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
                            .font(Typo.code)
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

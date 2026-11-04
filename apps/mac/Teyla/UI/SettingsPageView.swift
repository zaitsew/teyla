import AppKit
import SwiftUI

/// Settings: how Teyla is set up on this Mac. Top to bottom: four figures, Teyla's own settings file in plain groups,
/// the environment names it passes on (never their values), this app's switches, and the file itself for everything
/// the groups do not list. The page only reads the file; no secret is ever shown.
struct SettingsPageView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let page = model.settingsPage
        Page {
            PageHeader(title: "Settings", context: "How Teyla is set up on this Mac. Grey values are defaults.") {
                Button("Read again") { page.load(force: true) }
            }
            if let config = page.config {
                figures(config)
                ForEach(ConfigLogic.groups(config)) { group in
                    GroupSection(group: group)
                }
                EnvironmentSection(config: config)
            } else if let failure = page.failure {
                ErrorRow(section: "the settings file", message: failure) { page.load(force: true) }
            } else {
                EmptyState(symbol: "ellipsis.circle", title: "Reading the settings file.")
            }
            AppSection()
            FileSection(config: page.config)
        }
        .navigationTitle("Settings")
        .onAppear { page.load() }
    }

    private func figures(_ config: TeylaConfig) -> some View {
        let rows = ConfigLogic.groups(config).flatMap(\.rows)
        func value(_ key: String) -> String { rows.first { $0.key == key }?.value ?? Format.dash }
        return StatStrip {
            StatTile(label: "Keys set", value: config.exists ? "\(ConfigLogic.keysSet(config))" : "0",
                     detail: config.exists ? "In the settings file." : "No file yet. Teyla uses its defaults.")
            StatTile(label: "Work mode", value: value("safe.enabled"), detail: "No network, no self-update.",
                     tone: value("safe.enabled") == "On" ? .needsYou : .neutral)
            StatTile(label: "Automatic clean-up", value: value("storage.auto_clean"), detail: "Finished worktrees and build output.")
            StatTile(label: "Updates", value: value("update.channel") == "Never automatic" ? "Off" : "On",
                     detail: value("update.pin") == "Not pinned" ? "Follows published releases." : "Pinned to \(value("update.pin")).")
        }
    }
}

/// One group of settings: the rule that says what they do, then a row each. A value the file does not set is greyed
/// and reads as the default.
private struct GroupSection: View {
    let group: ConfigGroup

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: group.title, note: group.note)
            RowGroup {
                ForEach(group.rows) { row in
                    RowCard(title: row.label, detail: row.hint) {
                        Text(row.value)
                            .font(Typo.body)
                            .foregroundStyle(row.isDefault ? Palette.textTertiary : Palette.text)
                            .multilineTextAlignment(.trailing)
                            .frame(maxWidth: Space.valueColumn, alignment: .trailing)
                            .textSelection(.enabled)
                            .help(row.isDefault ? "Not set in the file: this is the default." : "Set in the file.")
                            .accessibilityLabel(row.isDefault ? "\(row.value), the default" : row.value)
                    }
                }
            }
        }
    }
}

/// The names of the variables Teyla passes to its own commands. Their values can be keys or proxy logins, so the page
/// never holds them.
private struct EnvironmentSection: View {
    let config: TeylaConfig

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Environment", note: "Variables Teyla passes to its own commands. Values are never shown.")
            RowGroup {
                RowCard(title: "Variables set", detail: ConfigLogic.environmentLine(config)) {
                    Text("\(config.environmentNames.count)")
                        .font(Typo.body.weight(.semibold).monospacedDigit())
                        .foregroundStyle(config.environmentNames.isEmpty ? Palette.textTertiary : Palette.text)
                }
            }
        }
    }
}

/// This app's own switches, the same ones as the Settings window (⌘,).
private struct AppSection: View {
    @Environment(AppModel.self) private var model
    @AppStorage(Voice.defaultsKey) private var localeID = Voice.locales[0].id

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "This app", note: "Voice, the quick-note shortcut and the iPhone.")
            RowGroup {
                RowCard(title: "Voice language", detail: "Speech is recognised on this Mac. No audio leaves it.") {
                    Picker("Voice language", selection: $localeID) {
                        ForEach(Voice.locales) { locale in
                            Text(locale.name).tag(locale.id)
                        }
                    }
                    .labelsHidden()
                    .fixedSize()
                }
                if model.capabilities.notes {
                    RowCard(title: "Quick-note shortcut", detail: "A note is kept as typed and filed under a product.") {
                        ShortcutRecorder()
                    }
                }
                if model.canConnectPhone {
                    RowCard(title: "iPhone", detail: "Shows a code your iPhone's camera reads.") {
                        Button("Connect iPhone…") { model.openConnectPhone() }
                    }
                }
            }
        }
    }
}

/// The file itself: where it is, and how many keys the groups above do not list.
private struct FileSection: View {
    let config: TeylaConfig?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "The settings file", note: "Everything the groups above do not list is in the file.")
            RowGroup {
                RowCard(title: "Settings file", detail: config?.path ?? "~/.teyla/config.toml") {
                    Button("Show in Finder") { reveal() }
                }
                if let config {
                    let others = ConfigLogic.otherKeys(config)
                    RowCard(title: "Other keys",
                            detail: others == 0 ? "The groups above list every key the file sets."
                                : "\(others) more key\(others == 1 ? " is" : "s are") set; open the file to read \(others == 1 ? "it" : "them").") {
                        Text("\(others)")
                            .font(Typo.body.weight(.semibold).monospacedDigit())
                            .foregroundStyle(others == 0 ? Palette.textTertiary : Palette.text)
                    }
                    if config.unread > 0 {
                        RowCard(title: "Lines not read",
                                detail: "\(config.unread) line\(config.unread == 1 ? "" : "s") in the file could not be read here.") {
                            Text("\(config.unread)").font(Typo.body.weight(.semibold).monospacedDigit())
                        }
                    }
                }
            }
        }
    }

    /// Selects the file in Finder, or opens its folder when the file is not there yet.
    private func reveal() {
        let path = ((config?.path ?? "~/.teyla/config.toml") as NSString).expandingTildeInPath
        let url = URL(fileURLWithPath: path)
        if FileManager.default.fileExists(atPath: path) {
            NSWorkspace.shared.activateFileViewerSelecting([url])
        } else {
            NSWorkspace.shared.open(url.deletingLastPathComponent())
        }
    }
}

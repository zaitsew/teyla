import SwiftUI

/// Settings: voice language and shortcut, the quick-note shortcut, and the iPhone relay with its "Connect iPhone" button.
struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @AppStorage(Voice.defaultsKey) private var localeID = Voice.locales[0].id

    var body: some View {
        let relay = model.relay
        Form {
            Section("Voice") {
                Picker("Language", selection: $localeID) {
                    ForEach(Voice.locales) { locale in
                        Text(locale.name).tag(locale.id)
                    }
                }
                Text("Speech is recognised on this Mac. No audio leaves it.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                Text(model.hotKeyLine)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            }
            if model.capabilities.notes {
            Section("Quick note") {
                LabeledContent("Shortcut") { ShortcutRecorder() }
                Text("A note is kept as typed, filed under a product, and passed on as your own words.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            }
            if model.canConnectPhone {
            Section("iPhone") {
                if model.capabilities.pairPhone {
                    Toggle("iPhone relay", isOn: Binding(
                        get: { relay.isOn(snapshot: model.snapshot?.relay) },
                        set: { relay.setOn($0) }
                    ))
                    .disabled(relay.busy)
                    LabeledContent("Status") {
                        TimelineView(.periodic(from: .now, by: 30)) { context in
                            Text(statusLine(at: context.date))
                                .foregroundStyle(Palette.textSecondary)
                        }
                    }
                    if let error = relay.error {
                        Label(error, systemImage: "exclamationmark.triangle.fill")
                            .font(Typo.caption)
                            .foregroundStyle(Palette.danger)
                            .textSelection(.enabled)
                    }
                }
                // One button: it turns the relay on first when it is off, then shows the code.
                Button("Connect iPhone…") { model.openConnectPhone() }
                Text(model.capabilities.pairPhone
                     ? "iCloud Drive holds the snapshot and your answers as readable text. "
                         + "Nobody can send an action without the key in the QR code."
                     : "Shows a code your iPhone's camera reads. The code is the key you paired this Mac with. "
                         + "Nobody can send an action without it.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            }
            #if STORE
            StoreSettingsSection()
            #endif
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
    }

    private func statusLine(at now: Date) -> String {
        var shown = model.snapshot?.relay ?? Relay()
        shown.on = model.relay.isOn(snapshot: model.snapshot?.relay)
        return Format.relayLine(shown, now: model.clock(at: now))
    }
}

import SwiftUI

/// Settings: voice language and shortcut, and the iPhone relay with its pairing QR code.
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
            Section("iPhone") {
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
                pairing(relay)
                Text("iCloud Drive holds the snapshot and your answers as readable text. "
                     + "Nobody can send an action without the key in the QR code.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .formStyle(.grouped)
        .frame(width: 460)
        .fixedSize(horizontal: false, vertical: true)
        .onDisappear { relay.clearPairing() }
        .onAppear { Preview.settingsShown(model: model) }
    }

    private func statusLine(at now: Date) -> String {
        var shown = model.snapshot?.relay ?? Relay()
        shown.on = model.relay.isOn(snapshot: model.snapshot?.relay)
        return Format.relayLine(shown, now: model.clock(at: now))
    }

    @ViewBuilder private func pairing(_ relay: RelayModel) -> some View {
        switch relay.pairing {
        case .idle:
            Button("Pair iPhone") { relay.pair() }
                .disabled(!relay.isOn(snapshot: model.snapshot?.relay))
        case .working:
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text("Creating the key…").foregroundStyle(Palette.textSecondary)
            }
        case .ready(let text):
            VStack(alignment: .leading, spacing: Space.s) {
                if let image = Pairing.qrImage(for: text) {
                    Image(nsImage: image)
                        .interpolation(.none)
                        .frame(width: image.size.width, height: image.size.height)
                        .accessibilityLabel("Pairing QR code")
                } else {
                    Text("Could not draw the QR code.").foregroundStyle(Palette.danger)
                }
                Text("On the iPhone: open Teyla, choose Pair, and scan this code.")
                    .font(Typo.body)
                Button("Hide QR code") { relay.clearPairing() }
            }
        case .failed(let message):
            VStack(alignment: .leading, spacing: Space.s) {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.danger)
                    .textSelection(.enabled)
                Button("Try again") { relay.pair() }
            }
        }
    }
}

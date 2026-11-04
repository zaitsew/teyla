import AppKit
import SwiftUI

/// "Connect iPhone": a large QR code and two steps. The iPhone's camera opens Teyla on its own, because Teyla on the
/// iPhone registers the same `teyla-pair:` link the code holds. The code is the key: it hides after 5 minutes and
/// when the sheet closes. Both builds use this sheet; only where the key comes from differs (the command, or the Keychain).
struct ConnectPhoneSheet: View {
    @Environment(AppModel.self) private var model
    @State private var copied = false

    var body: some View {
        let relay = model.relay
        VStack(alignment: .leading, spacing: Space.l) {
            Text("Connect iPhone").font(Typo.section)
            VStack(alignment: .leading, spacing: Space.s) {
                step(1, "Install Teyla on your iPhone from TestFlight.")
                step(2, "Point the iPhone camera at this code.")
            }
            HStack {
                Spacer(minLength: 0)
                code(relay)
                Spacer(minLength: 0)
            }
            Text("The code is the key to your Mac's questions. Show it only to your own iPhone. It hides after 5 minutes.")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: Space.s) {
                if case .ready(let text) = relay.pairing {
                    Button(copied ? "Copied" : "Copy pairing string") {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(text, forType: .string)
                        copied = true
                        Task {
                            try? await Task.sleep(for: .seconds(2))
                            copied = false
                        }
                    }
                    .buttonStyle(.link)
                    .font(Typo.caption)
                }
                Spacer()
                Button("Done") { model.relay.dismiss() }
                    .keyboardShortcut(.defaultAction)
            }
        }
        .padding(Space.xl)
        .frame(width: Space.sheetWidth)
        .background(Palette.background)
    }

    private func step(_ number: Int, _ text: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            Text("\(number)")
                .font(Typo.body.weight(.semibold))
                .foregroundStyle(Palette.onPrimary)
                .frame(width: Space.glyph, height: Space.glyph)
                .background(Palette.primary, in: Circle())
                .accessibilityHidden(true)
            Text(text).font(Typo.cardTitle)
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder private func code(_ relay: RelayModel) -> some View {
        switch relay.pairing {
        case .idle:
            VStack(spacing: Space.s) {
                Text("The code is hidden.").foregroundStyle(Palette.textSecondary)
                Button("Show the code again") { relay.connectPhone(turnOn: model.phoneNeedsRelayOn) }
            }
            .frame(width: Space.qrCode, height: Space.qrCode)
        case .working:
            VStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text(model.phoneNeedsRelayOn ? "Turning on the relay and making the key…" : "Making the code…")
                    .foregroundStyle(Palette.textSecondary)
            }
            .frame(width: Space.qrCode, height: Space.qrCode)
        case .ready(let text):
            if let image = Pairing.qrImage(for: text, points: Space.qrCode) {
                Image(nsImage: image)
                    .interpolation(.none)
                    .frame(width: image.size.width, height: image.size.height)
                    .clipShape(RoundedRectangle(cornerRadius: Radius.card))
                    .accessibilityLabel("Pairing QR code")
            } else {
                Text("Could not draw the QR code.").foregroundStyle(Palette.danger)
            }
        case .failed(let message):
            VStack(alignment: .leading, spacing: Space.s) {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.danger)
                    .textSelection(.enabled)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Try again") { relay.connectPhone(turnOn: model.phoneNeedsRelayOn) }
            }
            .frame(width: Space.qrCode, alignment: .leading)
        }
    }
}

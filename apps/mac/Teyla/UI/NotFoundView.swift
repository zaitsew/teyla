import SwiftUI

/// The teyla command is not installed (or not where the app looks): the exact command to run, and two ways
/// to tell the app where it is.
struct NotFoundView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: Space.xl) {
            BrandLockup()
            VStack(spacing: Space.s) {
                Text("Install the teyla command")
                    .font(Typo.brief)
                Text("Teyla for Mac shows what the teyla command reads from your sessions. It is not on this Mac yet. Paste this line in Terminal:")
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: Space.readingWidth)
            command
            HStack(spacing: Space.m) {
                Button {
                    model.recheckBinary()
                } label: {
                    if model.recheckingBinary {
                        HStack(spacing: Space.s) {
                            ProgressView().controlSize(.small)
                            Text("Checking…")
                        }
                    } else {
                        Text("Check again")
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(model.recheckingBinary)
                .keyboardShortcut(.defaultAction)
                Button("Choose…") { model.chooseBinary() }
                    .controlSize(.large)
                    .help("Pick the teyla file yourself; the app tries it first from then on")
            }
            VStack(spacing: Space.xs) {
                if model.recheckFailed && !model.recheckingBinary {
                    Label("Still not found.", systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(Palette.warning)
                }
                Text("Needs uv (astral.sh/uv). The app looks in the PATH of your login shell, then ~/.local/bin, /opt/homebrew/bin and /usr/local/bin.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                if let chosen = TeylaBinary.chosenPath() {
                    Text("Chosen file: \(chosen)")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .textSelection(.enabled)
                }
            }
            .frame(maxWidth: Space.readingWidth)
        }
        .padding(Space.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Palette.background)
        .navigationTitle("Teyla")
    }

    private var command: some View {
        HStack(spacing: Space.m) {
            Text(TeylaBinary.installCommand)
                .font(.system(.body, design: .monospaced))
                .textSelection(.enabled)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: Space.s)
            Button {
                model.copyInstallCommand()
            } label: {
                Label(model.installCopied ? "Copied" : "Copy", systemImage: model.installCopied ? "checkmark" : "doc.on.doc")
            }
            .controlSize(.small)
        }
        .padding(Space.m)
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: Radius.card))
        .overlay(RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Palette.border, lineWidth: 1))
        .frame(maxWidth: Space.readingWidth)
    }
}

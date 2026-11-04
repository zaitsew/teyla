import SwiftUI
import UIKit
import UniformTypeIdentifiers
import VisionKit

/// Three steps: pick the iCloud Drive "Teyla" folder, pair with the Mac, done. The first two work in either
/// order: a pairing code scanned with the Camera can arrive before the folder is chosen.
struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var showFolderPicker = false
    @State private var showScanner = false
    @State private var pasted = ""
    @State private var pasteError = false
    @State private var pasteOpen = !DataScannerViewController.isSupported

    private var step: Int { min(model.setupStep, 2) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.xl) {
                Spacer(minLength: Space.l)
                VStack(alignment: .leading, spacing: Space.xs) {
                    Text("Teyla")
                        .font(Typo.pageTitle)
                    Text("Your Mac's coordinator, on your iPhone.")
                        .font(Typo.section)
                        .foregroundStyle(Palette.textSecondary)
                }
                StepDots(step: step)
                Group {
                    switch step {
                    case 0: folderStep
                    case 1: pairStep
                    default: doneStep
                    }
                }
                .transition(.opacity)
                if step < 2 { sampleOffer }
            }
            .padding(Space.xl)
            .frame(maxWidth: Space.readingCard, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Palette.background)
        .animation(.easeOut(duration: 0.2), value: step)
        .sheet(isPresented: $showFolderPicker) {
            FolderPicker { url in
                showFolderPicker = false
                if let url { model.chooseFolder(url) }
            }
            .ignoresSafeArea()
        }
        // Paired first (the Camera opened Teyla): there is only the folder left, so ask for it at once.
        .onAppear { if step == 0 && model.hasKey { showFolderPicker = true } }
        .onChange(of: model.hasKey) { _, paired in
            if paired && step == 0 { showFolderPicker = true }
        }
        .fullScreenCover(isPresented: $showScanner) {
            ScannerSheet { code in
                showScanner = false
                if let code { handle(code) }
            }
        }
    }

    // MARK: Steps

    private var folderStep: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            StepHeader(number: 1, title: "Choose the Teyla folder")
            if model.hasKey {
                Label("Paired with your Mac", systemImage: "checkmark.circle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.saving)
            }
            Text("Your Mac created the Teyla folder in iCloud Drive. Choose it.")
                .foregroundStyle(Palette.textSecondary)
            Button {
                showFolderPicker = true
            } label: {
                Label("Choose folder", systemImage: "folder")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            Text("No folder yet? On your Mac, run `teyla relay connect`.")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
            Text("Teyla keeps access to this folder only. It reads the Mac's update there and leaves your answers for the Mac to pick up.")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
        }
    }

    private var pairStep: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            StepHeader(number: 2, title: "Pair with your Mac")
            if let name = model.folderName {
                Label("Folder: \(name)", systemImage: "checkmark.circle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.saving)
            }
            Text("In Teyla on your Mac, choose Connect iPhone, then scan the code.")
                .foregroundStyle(Palette.textSecondary)
            if DataScannerViewController.isSupported {
                Button {
                    showScanner = true
                } label: {
                    Label("Scan QR code", systemImage: "qrcode.viewfinder")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                Text("The iPhone Camera works too: point it at the code and tap the banner.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            }
            DisclosureGroup("Paste the pairing string", isExpanded: $pasteOpen) {
                pasteField.padding(.top, Space.s)
            }
            Button("Choose another folder") { showFolderPicker = true }
                .font(Typo.caption)
        }
    }

    private var pasteField: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("No camera, or no code on screen? Run `teyla relay pair` on the Mac and paste what it prints.")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
            TextField("teyla-pair:v1:\u{2026}", text: $pasted)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .font(Typo.code)
                .padding(Space.m)
                .background(Palette.surface, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
                .submitLabel(.done)
                .onSubmit { handle(pasted) }
            if DataScannerViewController.isSupported {
                Button("Pair with this string") { handle(pasted) }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                    .disabled(pasted.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            } else {
                Button("Pair with this string") { handle(pasted) }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(pasted.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            if pasteError {
                Label("That is not a Teyla pairing string.", systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.danger)
            }
        }
    }

    private var doneStep: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            StepHeader(number: 3, title: "You are set")
            Text("Teyla now reads what your Mac writes to \(model.folderName ?? "the folder"). Every answer you send is signed with the key you just shared.")
                .foregroundStyle(Palette.textSecondary)
            Button {
                model.finishSetup()
            } label: {
                Text("Open Teyla").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
    }

    /// No Mac yet, or an app reviewer: the whole app with made-up data. Nothing is sent from it.
    private var sampleOffer: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Divider()
            Text("No Mac yet?").font(Typo.body.weight(.semibold))
            Text("Try every screen with made-up data. Nothing is read from iCloud or sent.")
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
            Button {
                model.startSample()
            } label: {
                Label("See a sample", systemImage: "eye").frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
        }
    }

    private func handle(_ code: String) {
        pasteError = !model.pair(with: code)
        if !pasteError { pasted = "" }
    }
}

private struct StepHeader: View {
    let number: Int
    let title: String

    var body: some View {
        HStack(spacing: Space.s) {
            Text("\(number)")
                .font(Typo.body.weight(.semibold))
                .foregroundStyle(Palette.onPrimary)
                .frame(width: Space.stepBadge, height: Space.stepBadge)
                .background(Palette.primary, in: Circle())
            Text(title).font(Typo.section)
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

private struct StepDots: View {
    let step: Int

    var body: some View {
        HStack(spacing: Space.xs) {
            ForEach(0..<3) { index in
                Capsule()
                    .fill(index <= step ? Palette.primary : Palette.textTertiary)
                    .frame(width: index == step ? Space.stepBadge : Space.m, height: Space.dot)
            }
        }
        .accessibilityElement()
        .accessibilityLabel("Step \(step + 1) of 3")
    }
}

// MARK: - Pickers

/// The system document picker, for one folder.
struct FolderPicker: UIViewControllerRepresentable {
    var onPick: (URL?) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.folder])
        picker.allowsMultipleSelection = false
        // Best effort: open in iCloud Drive/Teyla. When iOS ignores it, the picker opens where it last was.
        picker.directoryURL = FolderBookmark.suggestedFolder
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL?) -> Void
        init(onPick: @escaping (URL?) -> Void) { self.onPick = onPick }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            onPick(urls.first)
        }

        func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) { onPick(nil) }
    }
}

private struct ScannerSheet: View {
    var onResult: (String?) -> Void

    var body: some View {
        ZStack(alignment: .topTrailing) {
            QRScanner(onCode: { onResult($0) })
                .ignoresSafeArea()
            Button("Cancel") { onResult(nil) }
                .buttonStyle(.borderedProminent)
                .tint(Palette.scrim)
                .padding()
        }
    }
}

/// VisionKit's live scanner, reading QR codes only. It reports the first Teyla pairing string.
struct QRScanner: UIViewControllerRepresentable {
    var onCode: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onCode: onCode) }

    func makeUIViewController(context: Context) -> DataScannerViewController {
        let scanner = DataScannerViewController(recognizedDataTypes: [.barcode(symbologies: [.qr])],
                                                qualityLevel: .balanced, recognizesMultipleItems: false,
                                                isHighFrameRateTrackingEnabled: false, isPinchToZoomEnabled: true,
                                                isGuidanceEnabled: true, isHighlightingEnabled: true)
        scanner.delegate = context.coordinator
        return scanner
    }

    func updateUIViewController(_ scanner: DataScannerViewController, context: Context) {
        if !scanner.isScanning { try? scanner.startScanning() }
    }

    final class Coordinator: NSObject, DataScannerViewControllerDelegate {
        let onCode: (String) -> Void
        private var done = false
        init(onCode: @escaping (String) -> Void) { self.onCode = onCode }

        func dataScanner(_ dataScanner: DataScannerViewController, didAdd addedItems: [RecognizedItem],
                         allItems: [RecognizedItem]) {
            guard !done else { return }
            for case .barcode(let code) in addedItems {
                if let value = code.payloadStringValue, value.hasPrefix(RelayCrypto.pairingPrefix) {
                    done = true
                    dataScanner.stopScanning()
                    onCode(value)
                    return
                }
            }
        }
    }
}

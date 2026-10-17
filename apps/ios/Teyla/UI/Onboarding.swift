import SwiftUI
import UIKit
import UniformTypeIdentifiers
import VisionKit

/// Three steps: pick the iCloud Drive "Teyla" folder, pair with the Mac, done.
struct OnboardingView: View {
    @Environment(AppModel.self) private var model
    @State private var showFolderPicker = false
    @State private var showScanner = false
    @State private var pasted = ""
    @State private var pasteError = false

    private var step: Int { min(model.setupStep, 2) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Spacer(minLength: 16)
                VStack(alignment: .leading, spacing: 6) {
                    Text("Teyla")
                        .font(.system(.largeTitle, weight: .bold))
                    Text("Your Mac's coordinator, on your iPhone.")
                        .font(.title3)
                        .foregroundStyle(.secondary)
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
            }
            .padding(24)
            .frame(maxWidth: 520, alignment: .leading)
            .frame(maxWidth: .infinity)
        }
        .scrollDismissesKeyboard(.interactively)
        .background(Color(.systemGroupedBackground))
        .animation(.easeOut(duration: 0.2), value: step)
        .sheet(isPresented: $showFolderPicker) {
            FolderPicker { url in
                showFolderPicker = false
                if let url { model.chooseFolder(url) }
            }
            .ignoresSafeArea()
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
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(number: 1, title: "Choose the Teyla folder")
            Text("On your Mac, run `teyla relay on`. It creates the folder Teyla in iCloud Drive. Open it here once.")
                .foregroundStyle(.secondary)
            Button {
                showFolderPicker = true
            } label: {
                Label("Choose folder", systemImage: "folder")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            Text("Teyla keeps access to this folder only. It reads the Mac's update there and leaves your answers for the Mac to pick up.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
    }

    private var pairStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(number: 2, title: "Pair with your Mac")
            if let name = model.folderName {
                Label("Folder: \(name)", systemImage: "checkmark.circle.fill")
                    .font(.subheadline)
                    .foregroundStyle(.green)
            }
            Text(LocalizedStringKey(DataScannerViewController.isSupported
                 ? "On your Mac, run `teyla relay pair` or open the pairing code in the Teyla window. Scan the code, or paste the pairing string."
                 : "On your Mac, run `teyla relay pair` and paste the pairing string it prints."))
                .foregroundStyle(.secondary)
            if DataScannerViewController.isSupported {
                Button {
                    showScanner = true
                } label: {
                    Label("Scan QR code", systemImage: "qrcode.viewfinder")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            VStack(alignment: .leading, spacing: 8) {
                TextField("teyla-pair:v1:\u{2026}", text: $pasted)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.system(.body, design: .monospaced))
                    .padding(12)
                    .background(Color(.secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
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
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
            }
            Button("Choose another folder") { showFolderPicker = true }
                .font(.footnote)
        }
    }

    private var doneStep: some View {
        VStack(alignment: .leading, spacing: 16) {
            StepHeader(number: 3, title: "You are set")
            Text("Teyla now reads what your Mac writes to \(model.folderName ?? "the folder"). Every answer you send is signed with the key you just shared.")
                .foregroundStyle(.secondary)
            Button {
                model.finishSetup()
            } label: {
                Text("Open Teyla").frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
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
        HStack(spacing: 10) {
            Text("\(number)")
                .font(.subheadline.weight(.bold))
                .foregroundStyle(.white)
                .frame(width: 28, height: 28)
                .background(Color.accentColor, in: Circle())
            Text(title).font(.title2.weight(.semibold))
        }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}

private struct StepDots: View {
    let step: Int

    var body: some View {
        HStack(spacing: 6) {
            ForEach(0..<3) { index in
                Capsule()
                    .fill(index <= step ? Color.accentColor : Color(.tertiaryLabel))
                    .frame(width: index == step ? 28 : 14, height: 5)
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
                .tint(.black.opacity(0.6))
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

#if TEYLA_REVIEW && canImport(UIKit)
import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Pairing, the relay folder and the list of captures with their status. Put it in a debug menu:
/// `NavigationLink("Review settings") { ReviewSettingsView() }`.
public struct ReviewSettingsView: View {
    @State private var pairing = ""
    @State private var paired = TeylaReview.isPaired
    @State private var pairingFailed = false
    @State private var pickingFolder = false
    @State private var folderChosen = TeylaReview.relayFolder.isChosen
    @State private var rows: [(id: String, status: ReviewStatus)] = []

    public init() {}

    public var body: some View {
        Group {
            if TeylaReview.isActive { content }
        }
    }

    private var content: some View {
        List {
            Section("Pairing") {
                if paired {
                    Label("Paired with the Mac", systemImage: "checkmark.circle")
                } else {
                    TextField("teyla-pair:v1:…", text: $pairing)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("Pair") {
                        paired = TeylaReview.pair(pairing)
                        pairingFailed = !paired
                        pairing = ""
                    }
                    if pairingFailed { Text("That is not a pairing string.").foregroundStyle(.red) }
                }
            }
            Section("Relay folder") {
                Button(folderChosen ? "Change the Teyla folder" : "Choose the Teyla folder in iCloud Drive") { pickingFolder = true }
            }
            Section("Captures") {
                if rows.isEmpty { Text("None yet").foregroundStyle(.secondary) }
                ForEach(rows, id: \.id) { row in
                    HStack {
                        Text(String(row.id.prefix(8))).font(.footnote.monospaced())
                        Spacer()
                        Text(row.status.title)
                    }
                }
            }
        }
        .navigationTitle("Review")
        .onAppear(perform: reload)
        .sheet(isPresented: $pickingFolder) {
            FolderPicker { url in
                try? TeylaReview.setRelayFolder(url)
                folderChosen = TeylaReview.relayFolder.isChosen
                DispatchQueue.global(qos: .utility).async { ReviewDelivery.retryPending() }
            }
        }
    }

    private func reload() {
        let store = CaptureStore(root: CaptureStore.defaultRoot())
        rows = store.list().map { ($0, TeylaReview.status(of: $0)) }
    }
}

struct FolderPicker: UIViewControllerRepresentable {
    let onPick: (URL) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.folder])
        picker.allowsMultipleSelection = false
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL) -> Void
        init(onPick: @escaping (URL) -> Void) { self.onPick = onPick }
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            if let url = urls.first { onPick(url) }
        }
    }
}
#endif

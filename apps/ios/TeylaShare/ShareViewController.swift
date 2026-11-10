import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Teyla in the iOS share sheet: a link or a picture, one optional sentence, like or dislike. It saves a request into
/// the App Group queue and closes; the Teyla app signs and sends it to the Mac the next time it is open. The extension
/// holds no key and writes nowhere else.
final class ShareViewController: UIViewController {
    private let model = ShareModel()

    override func viewDidLoad() {
        super.viewDidLoad()
        let root = ShareView(model: model,
                             save: { [weak self] in self?.save() },
                             cancel: { [weak self] in self?.finish(cancelled: true) })
        let host = UIHostingController(rootView: root)
        addChild(host)
        host.view.frame = view.bounds
        host.view.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        view.addSubview(host.view)
        host.didMove(toParent: self)
        Task { await model.load(from: extensionContext?.inputItems as? [NSExtensionItem] ?? []) }
    }

    private func save() {
        guard model.canSave else { return }
        do {
            try model.enqueue()
            finish(cancelled: false)
        } catch {
            model.error = "Could not save this. Open Teyla once and try again."
        }
    }

    private func finish(cancelled: Bool) {
        if cancelled {
            extensionContext?.cancelRequest(withError: NSError(domain: NSCocoaErrorDomain, code: NSUserCancelledError))
        } else {
            extensionContext?.completeRequest(returningItems: nil)
        }
    }
}

@MainActor
final class ShareModel: ObservableObject {
    enum Subject {
        case loading
        case link(String)
        case picture(Data)
        case unsupported
    }

    @Published var subject = Subject.loading
    @Published var verdict = "like"
    @Published var sentence = ""
    @Published var error: String?

    var canSave: Bool {
        switch subject {
        case .link, .picture: return true
        case .loading, .unsupported: return false
        }
    }

    func load(from items: [NSExtensionItem]) async {
        let providers = items.flatMap { $0.attachments ?? [] }
        // A link first: Safari and most apps share one. Then a picture, then plain text that holds a link.
        for p in providers where p.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            if let url = await Self.url(p), let link = TasteInput.link(from: url.absoluteString) {
                subject = .link(link)
                return
            }
        }
        for p in providers where p.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
            if let data = await Self.data(p, UTType.image.identifier), let jpeg = TasteInput.jpeg(from: data) {
                subject = .picture(jpeg)
                return
            }
        }
        for p in providers where p.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
            if let text = await Self.text(p), let link = TasteInput.firstLink(inText: text) {
                subject = .link(link)
                return
            }
        }
        subject = .unsupported
    }

    func enqueue() throws {
        guard let queue = TasteQueue.shared() else { throw CocoaError(.fileNoSuchFile) }
        let id = UUID().uuidString.lowercased()
        var request = TasteRequest(id: id, created: TasteInput.now(), verdict: verdict, url: nil, imageFile: nil,
                                   sentence: String(sentence.trimmingCharacters(in: .whitespacesAndNewlines)
                                       .unicodeScalars.prefix(TasteInput.maxSentence)))
        var image: Data?
        switch subject {
        case .link(let l): request.url = l
        case .picture(let d):
            request.imageFile = TasteInput.imageName
            image = d
        case .loading, .unsupported: return
        }
        try queue.enqueue(request, image: image)
    }

    private static func url(_ p: NSItemProvider) async -> URL? {
        await withCheckedContinuation { cont in
            _ = p.loadObject(ofClass: URL.self) { url, _ in cont.resume(returning: url) }
        }
    }

    private static func text(_ p: NSItemProvider) async -> String? {
        await withCheckedContinuation { cont in
            _ = p.loadObject(ofClass: NSString.self) { s, _ in cont.resume(returning: s as? String) }
        }
    }

    private static func data(_ p: NSItemProvider, _ type: String) async -> Data? {
        await withCheckedContinuation { cont in
            _ = p.loadDataRepresentation(forTypeIdentifier: type) { data, _ in cont.resume(returning: data) }
        }
    }
}

private struct ShareView: View {
    @ObservedObject var model: ShareModel
    let save: () -> Void
    let cancel: () -> Void
    @FocusState private var typing: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section("Shared") { subject }
                Section {
                    Picker("Verdict", selection: $model.verdict) {
                        Text("Like").tag("like")
                        Text("Dislike").tag("dislike")
                    }
                    .pickerStyle(.segmented)
                }
                Section {
                    TextField("Why? (optional, tap the keyboard's mic to dictate)", text: $model.sentence, axis: .vertical)
                        .lineLimit(2...6)
                        .focused($typing)
                } footer: {
                    Text("It goes to your Mac the next time you open Teyla. With a sentence it waits for your yes; without one it stays raw.")
                }
                if let error = model.error {
                    Section { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("Taste")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", action: cancel) }
                ToolbarItem(placement: .confirmationAction) { Button("Save", action: save).disabled(!model.canSave) }
            }
        }
    }

    @ViewBuilder private var subject: some View {
        switch model.subject {
        case .loading:
            ProgressView()
        case .link(let link):
            Text(link).font(.callout).lineLimit(3).textSelection(.enabled)
        case .picture(let data):
            if let image = UIImage(data: data) {
                Image(uiImage: image).resizable().scaledToFit().frame(maxHeight: 180)
            } else {
                Text("Picture")
            }
        case .unsupported:
            Text("Teyla takes a link or a picture.").foregroundStyle(.secondary)
        }
    }
}

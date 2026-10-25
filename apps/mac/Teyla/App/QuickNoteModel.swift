import Observation
import SwiftUI

/// State of the quick-note panel. The draft lives here, not in the view, so Esc keeps it until the next open.
@MainActor
@Observable
final class QuickNoteModel {
    static let debounce = Duration.milliseconds(300)
    static let confirmation = Duration.seconds(1)

    var draft = ""
    private(set) var product = NoteItem.inbox
    private(set) var linkedBy = ""
    private(set) var candidates: [String] = []
    private(set) var status: CardStatus?
    /// Bumped each time the panel opens, so the text field takes focus again.
    private(set) var focusToken = 0
    /// True once the owner picked a product: the suggestion no longer moves it.
    private(set) var chosen = false

    /// Closes the panel; set by the panel controller.
    @ObservationIgnored var close: (() -> Void)?
    @ObservationIgnored var productNames: () -> [String] = { [] }
    @ObservationIgnored var saved: (NoteItem) -> Void = { _ in }
    @ObservationIgnored var learnedCandidates: ([String]) -> Void = { _ in }
    @ObservationIgnored private let cli: TeylaCLI
    @ObservationIgnored private var suggestTask: Task<Void, Never>?
    @ObservationIgnored private var closeTask: Task<Void, Never>?

    init(cli: TeylaCLI) {
        self.cli = cli
    }

    var isSaving: Bool {
        if case .sending = status { return true }
        return false
    }

    var canSave: Bool { Notes.canSave(draft) && !isSaving }

    /// The panel opened: ask for a suggestion for what is already in the draft, without waiting.
    func opened() {
        focusToken += 1
        closeTask?.cancel()
        if case .done = status { status = nil }
        if case .failed = status { status = nil }
        suggest(after: .zero)
    }

    /// The text changed: suggest a product again after the owner stops typing for 300 ms.
    func draftChanged() {
        closeTask?.cancel()
        if case .done = status { status = nil }
        if case .failed = status { status = nil }
        suggest(after: Self.debounce)
    }

    func choose(_ id: String) {
        product = id
        linkedBy = "owner"
        chosen = true
    }

    /// ⌘0–⌘9 over the inbox and the numbered candidates. True when the key was used.
    @discardableResult
    func choose(digit: Int) -> Bool {
        guard let id = Notes.product(forDigit: digit, candidates: candidates) else { return false }
        choose(id)
        return true
    }

    func save() {
        guard canSave else { return }
        let text = draft
        let target = product
        status = .sending("Saving…")
        Task {
            do {
                let note = try await cli.saveNote(text: text, product: target)
                // Text typed while the save ran stays: only the saved text is cleared.
                if draft == text { draft = "" }
                chosen = false
                product = NoteItem.inbox
                linkedBy = ""
                status = .done("Saved to \(Notes.productLabel(note.product))")
                saved(note)
                closeTask?.cancel()
                closeTask = Task {
                    try? await Task.sleep(for: Self.confirmation)
                    guard !Task.isCancelled else { return }
                    if case .done = status { status = nil }
                    close?()
                }
            } catch {
                // The panel stays open and the text stays as typed.
                status = .failed(error.localizedDescription)
            }
        }
    }

    private func suggest(after delay: Duration) {
        suggestTask?.cancel()
        let text = draft
        let products = productNames()
        suggestTask = Task {
            if delay > .zero { try? await Task.sleep(for: delay) }
            guard !Task.isCancelled else { return }
            guard let found = try? await cli.suggestNote(text: text, products: products) else { return }
            // A result for text that has changed since is stale.
            guard !Task.isCancelled, text == draft else { return }
            if !found.candidates.isEmpty {
                candidates = found.candidates
                learnedCandidates(found.candidates)
            }
            if !chosen {
                product = found.product
                linkedBy = found.linkedBy
            }
        }
    }
}

import Observation
import SwiftUI

/// The open text notes the window lists: the Inbox count, the newest five, and the Link and Drop actions.
/// The data is `teyla notes --json`; the app keeps no copy beyond what is on screen.
@MainActor
@Observable
final class NotesModel {
    private(set) var items: [NoteItem] = []
    private(set) var loaded = false
    private(set) var error: String?
    /// The products a note can be linked to, as the CLI lists them (focus first).
    private(set) var candidates: [String] = []
    /// What each note's row is doing (linking, dropping, or a failure to show).
    private(set) var rows: [String: CardStatus] = [:]

    @ObservationIgnored private let cli: TeylaCLI
    @ObservationIgnored var productNames: () -> [String] = { [] }
    /// Called after a note was saved, linked or dropped, so an open product page re-reads.
    @ObservationIgnored var changed: () -> Void = {}
    @ObservationIgnored private var refreshing = false
    @ObservationIgnored private var refreshQueued = false

    init(cli: TeylaCLI) {
        self.cli = cli
    }

    var inbox: Int { Notes.inboxCount(items) }
    var open: Int { Notes.openCount(items) }
    var newest: [NoteItem] { Notes.newestOpen(items) }
    /// The Link menu's products: the CLI's list, else the products of the last snapshot.
    var linkTargets: [String] { candidates.isEmpty ? productNames() : candidates }
    var hiddenCount: Int { max(0, open - Notes.shownInWindow) }

    /// Re-reads the notes. With a fixture the sample is read once: link and drop change it locally, and a
    /// later refresh must not bring a dropped note back.
    func refresh() {
        if cli.usesFixture && loaded { return }
        if refreshing {
            refreshQueued = true
            return
        }
        refreshing = true
        Task {
            defer {
                refreshing = false
                if refreshQueued {
                    refreshQueued = false
                    refresh()
                }
            }
            do {
                items = try await cli.notes()
                error = nil
                loaded = true
                if candidates.isEmpty { await loadCandidates() }
            } catch {
                self.error = error.localizedDescription
            }
        }
    }

    func loadCandidates() async {
        if let found = try? await cli.suggestNote(text: "", products: productNames()) {
            candidates = found.candidates
        }
    }

    func setCandidates(_ list: [String]) {
        if !list.isEmpty { candidates = list }
    }

    /// A note just saved from the panel shows at once; the next read confirms it.
    func saved(_ note: NoteItem) {
        items.removeAll { $0.id == note.id }
        items.insert(note, at: 0)
        loaded = true
        changed()
        if !cli.usesFixture { refresh() }
    }

    func link(_ note: NoteItem, to product: String) {
        guard !isBusy(note), note.product != product else { return }
        rows[note.id] = .sending("Linking…")
        Task {
            do {
                try await cli.linkNote(id: note.id, product: product)
                if let at = items.firstIndex(where: { $0.id == note.id }) {
                    items[at].product = product
                    items[at].linkedBy = "owner"
                }
                rows[note.id] = nil
                changed()
                if !cli.usesFixture { refresh() }
            } catch {
                rows[note.id] = .failed(error.localizedDescription)
            }
        }
    }

    func drop(_ note: NoteItem) {
        guard !isBusy(note) else { return }
        rows[note.id] = .sending("Dropping…")
        Task {
            do {
                try await cli.dropNote(id: note.id)
                withAnimation(.easeOut(duration: 0.2)) { items.removeAll { $0.id == note.id } }
                rows[note.id] = nil
                changed()
                if !cli.usesFixture { refresh() }
            } catch {
                rows[note.id] = .failed(error.localizedDescription)
            }
        }
    }

    func dismissError(_ note: NoteItem) {
        if case .failed = rows[note.id] { rows[note.id] = nil }
    }

    private func isBusy(_ note: NoteItem) -> Bool {
        if case .sending = rows[note.id] { return true }
        return false
    }
}

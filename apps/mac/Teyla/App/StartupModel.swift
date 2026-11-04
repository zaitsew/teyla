import Foundation
import Observation

/// The startup page's two reads that are not in the snapshot: which product leads the Products screen, and the YC sheet.
/// Both come from the `teyla` command (docs/STARTUP.md), so the store build never creates one that reads anything.
///
/// The YC answers are customer text. They live here only while the sheet is open, and are cleared when it closes.
/// They are never put in `state`, on the relay or in a file of the app's own: `teyla startup yc answer` writes them to
/// `~/.teyla/startup/`.
@MainActor
@Observable
final class StartupModel {
    // MARK: The focus product

    /// The product the startup page leads with; nil when there is none or it was not read.
    private(set) var focus: String?
    private(set) var focusRead = false

    // MARK: The YC sheet

    var presented = false
    private(set) var productID: String?
    private(set) var title = ""
    private(set) var sheet: YCSheet?
    private(set) var phase: ConsolePhase = .idle
    /// What is typed in each text box, by box id. Seeded from the saved answer.
    var drafts: [String: String] = [:]
    /// The boxes being saved now.
    private(set) var saving: Set<String> = []
    /// Why the last save of a box failed.
    private(set) var failures: [String: String] = [:]

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var focusReadAt: Date?
    @ObservationIgnored private var focusTask: Task<Void, Never>?
    @ObservationIgnored private var generation = 0
    /// Raised when the sheet closes or changes product. A save that finishes after that leaves the new sheet alone.
    @ObservationIgnored private var session = 0
    /// The newest write. Each write waits for the one before it and each read waits for the writes, so the last text
    /// saved lands last, even across a close and a reopen.
    @ObservationIgnored private var lastWrite: Task<Void, Never>?
    /// Called after an answer was saved, so the count on the product page is read again.
    @ObservationIgnored var changed: () -> Void = {}

    static let focusStaleAfter: TimeInterval = 120

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    // MARK: Focus

    /// The Products screen opened: read the focus when it was never read or the last read is old.
    func loadFocus(force: Bool = false) {
        if !force, let focusReadAt, Date().timeIntervalSince(focusReadAt) < Self.focusStaleAfter { return }
        guard focusTask == nil else { return }
        focusReadAt = Date()
        focusTask = Task {
            defer { focusTask = nil }
            do {
                focus = try await cli.startupFocus()
                focusRead = true
            } catch {
                // The screen is complete without a lead product; a failed read just leaves it out, and the next open tries again.
                focus = nil
                focusReadAt = nil
            }
        }
    }

    // MARK: Sheet

    var isLoading: Bool { phase == .loading }

    var failure: String? {
        if case .failed(let why) = phase { return why }
        return nil
    }

    func open(id: String, title: String) {
        guard ProductCommands.isProductID(id) else { return }
        if productID != id {
            session += 1
            productID = id
            sheet = nil
            drafts = [:]
            failures = [:]
            saving = []
            phase = .idle
        }
        self.title = title
        presented = true
        reload()
    }

    /// Closes the sheet and forgets every answer it held.
    func close() {
        generation += 1
        session += 1
        presented = false
        productID = nil
        sheet = nil
        drafts = [:]
        failures = [:]
        saving = []
        phase = .idle
    }

    func reload() {
        guard let id = productID else { return }
        generation += 1
        let mine = generation
        phase = .loading
        let writes = lastWrite
        Task {
            await writes?.value
            do {
                let next = try await cli.ycSheet(id: id)
                guard mine == generation else { return }
                merge(next)
                phase = .ready
            } catch {
                guard mine == generation else { return }
                // A sheet that was on screen stays, marked as old; a failed read never looks like an empty sheet.
                phase = .failed(error.localizedDescription)
            }
        }
    }

    /// Takes the new sheet in. A box the owner is editing keeps what was typed; every other box shows its saved answer.
    private func merge(_ next: YCSheet) {
        for box in next.boxes where !box.auto {
            let saved = box.answer?.text ?? ""
            let old = sheet?.boxes.first { $0.id == box.id }?.answer?.text ?? ""
            if drafts[box.id] == nil || drafts[box.id] == old { drafts[box.id] = saved }
        }
        sheet = next
    }

    func save(box id: String) {
        guard let productID, let sheet, let box = sheet.boxes.first(where: { $0.id == id }), !saving.contains(id) else { return }
        let text = (drafts[id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard YCText.canSave(box, draft: text) else { return }
        saving.insert(id)
        failures[id] = nil
        let target = productID
        let mine = session
        let previous = lastWrite
        lastWrite = Task {
            await previous?.value
            do {
                try await cli.ycAnswer(id: target, box: id, text: text)
                guard session == mine else { return }
                saving.remove(id)
                // The saved text is now the answer; read the sheet again so the box shows whether it is checked.
                // Text typed while the save ran is newer than what was saved, so it stays.
                if (drafts[id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines) == text { drafts[id] = text }
                reload()
                changed()
            } catch {
                guard session == mine else { return }
                saving.remove(id)
                failures[id] = error.localizedDescription
            }
        }
    }

    func isSaving(_ id: String) -> Bool { saving.contains(id) }
}

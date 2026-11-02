import Foundation
import Observation

/// One action on one card.
struct ToolKey: Hashable, Sendable {
    let item: String
    let action: String
}

/// The Tools page: `teyla attention --json`, and the actions on its cards. An action goes preview, then confirm,
/// then run, then the list is read again; `ToolCommands` decides what may run at all.
@MainActor
@Observable
final class ToolsModel {
    private(set) var report: AttentionReport?
    private(set) var phase: AttentionPhase = .idle
    private(set) var readAt: Date?
    /// Where each action is, by `runKey`. An action with no entry is idle.
    private(set) var runs: [ToolKey: ToolRun] = [:]
    /// The card the command bar pointed at; the page scrolls to it and marks it for a moment.
    private(set) var focusedItemID: String?
    /// What the last action printed, kept after its card is gone (a forgotten task has no card to say "done" on).
    private(set) var notice: String?

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var reading: Task<Void, Never>?
    @ObservationIgnored private var queued = false
    /// Called after an action ran, so the window reads its state again (a forgotten task, an applied offer).
    @ObservationIgnored var changed: () -> Void = {}

    /// A report older than this is read again when the page opens.
    static let staleAfter: TimeInterval = 600

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    var isLoading: Bool { phase == .loading }

    /// The sidebar badge: items that need the owner. A failed read shows "!" instead, never a quiet zero.
    var badge: String? {
        if case .failed = phase { return "!" }
        guard let count = report?.actCount, count > 0 else { return nil }
        return String(count)
    }

    var failure: String? {
        if case .failed(let why) = phase { return why }
        return nil
    }

    func runKey(item: AttentionItem, action: ToolAction) -> ToolKey { ToolKey(item: item.id, action: action.id) }

    func run(for item: AttentionItem, action: ToolAction) -> ToolRun? { runs[runKey(item: item, action: action)] }

    // MARK: Reading

    /// Reads the report. A read that is already running is not started twice; one asked for while it runs follows it.
    func refresh(force: Bool = true) {
        if !force, let readAt, Date().timeIntervalSince(readAt) < Self.staleAfter, phase == .ready { return }
        if isLoading {
            queued = true
            return
        }
        phase = .loading
        reading = Task {
            defer {
                if queued {
                    queued = false
                    refresh()
                }
            }
            do {
                let next = try await cli.attention()
                report = next
                readAt = Date()
                phase = .ready
                let ids = Set(next.items.map(\.id))
                runs = runs.filter { key, _ in ids.contains(key.item) }
            } catch {
                // The last report stays on screen, marked as old, so a failed read never looks like a clean one.
                phase = .failed(error.localizedDescription)
            }
        }
    }

    /// The page opened: read when there is nothing yet or the report is old.
    func opened() { refresh(force: false) }

    // MARK: Actions

    /// A click on an action.
    func begin(item: AttentionItem, action: ToolAction) {
        let key = runKey(item: item, action: action)
        guard ToolFlow.canBegin(runs[key]) else { return }
        focusedItemID = item.id
        guard let first = ToolFlow.begin(action) else {
            execute(key: key, action: action)
            return
        }
        runs[key] = first
        if first == .previewing, let preview = action.preview { runPreview(key: key, preview: preview) }
    }

    /// The confirm button: it runs only the command that was shown.
    func confirm(item: AttentionItem, action: ToolAction) {
        let key = runKey(item: item, action: action)
        guard ToolFlow.canConfirm(runs[key]) else { return }
        execute(key: key, action: action)
    }

    func cancel(item: AttentionItem, action: ToolAction) {
        let key = runKey(item: item, action: action)
        guard !(runs[key]?.isBusy ?? false) else { return }
        runs[key] = nil
    }

    /// The command bar chose an action: show its card at the first step. Nothing runs here.
    func point(at itemID: String, action: ToolAction) {
        guard let item = report?.items.first(where: { $0.id == itemID }) else { return }
        begin(item: item, action: action)
    }

    func clearFocus() { focusedItemID = nil }

    func dismissNotice() { notice = nil }

    private func runPreview(key: ToolKey, preview: [String]) {
        Task {
            do {
                let out = try await cli.runTool(preview)
                runs[key] = .preview(ToolCommands.trimmed(out.isEmpty ? "The preview printed nothing." : out))
            } catch {
                runs[key] = .failed(error.localizedDescription)
            }
        }
    }

    private func execute(key: ToolKey, action: ToolAction) {
        runs[key] = .running
        Task {
            do {
                let out = try await cli.runTool(action.command)
                let text = ToolCommands.trimmed(out.isEmpty ? "Done." : out)
                runs[key] = .done(text)
                notice = "\(action.label): \(ToolCommands.display(action.command))\n\(text)"
                changed()
                refresh()
            } catch {
                runs[key] = .failed(error.localizedDescription)
            }
        }
    }
}

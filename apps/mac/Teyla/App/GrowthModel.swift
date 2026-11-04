import Foundation
import Observation

/// Where the one action on a draft is: running, finished (with what the command said), or failed (with why).
enum GrowthAct: Equatable, Sendable {
    case running(String)
    case failed(String)

    var isBusy: Bool {
        if case .running = self { return true }
        return false
    }
}

/// The review queue of the Growth page: the drafts waiting for the owner, and approve, reject and edit.
/// Reading changes nothing. Each action runs `teyla growth ...` (the allow-list is `GrowthActions`), reads the queue again
/// and asks the console to rebuild its counts. Nothing here posts, sends or publishes anything: an approved draft is
/// only marked, and the owner posts it by hand from its packet.
@MainActor
@Observable
final class GrowthModel {
    private(set) var drafts: [GrowthDraft] = []
    private(set) var skipped = 0
    private(set) var phase: ConsolePhase = .idle
    /// What each draft's last action did, by item id. A draft with no entry is idle.
    private(set) var acts: [String: GrowthAct] = [:]
    /// What the last finished action said, kept after the draft left the queue.
    private(set) var notice: String?

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var reading: Task<Void, Never>?
    @ObservationIgnored private var queued = false
    @ObservationIgnored private(set) var readAt: Date?
    /// Called after an action finished, so the console counts are read again.
    @ObservationIgnored var changed: () -> Void = {}

    static let staleAfter: TimeInterval = 120

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    var isLoading: Bool { phase == .loading }

    var failure: String? {
        if case .failed(let why) = phase { return why }
        return nil
    }

    /// True once the queue has been read at least once.
    var isRead: Bool { readAt != nil }

    func act(for id: String) -> GrowthAct? { acts[id] }

    /// The page opened: read when nothing was read yet or the last read is old.
    func opened() { refresh(force: false) }

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
                let read = try await cli.growthDrafts()
                drafts = GrowthDrafts.waiting(read.drafts)
                skipped = read.skipped
                readAt = Date()
                phase = .ready
                let ids = Set(drafts.map(\.id))
                acts = acts.filter { ids.contains($0.key) }
            } catch {
                // The last queue stays on screen, marked as old: a failed read never looks like an empty queue.
                phase = .failed(error.localizedDescription)
            }
        }
    }

    // MARK: Actions

    func approve(_ draft: GrowthDraft) {
        run(draft, argv: GrowthActions.approve(draft.id), busy: "Approving…",
            done: "Approved \(GrowthLogic.channelName(platform: draft.platform, language: draft.language)). It is marked approved; nothing was posted.")
    }

    func reject(_ draft: GrowthDraft, reason: String) {
        guard GrowthLogic.canReject(reason: reason) else { return }
        run(draft, argv: GrowthActions.reject(draft.id, reason: reason), busy: "Rejecting…",
            done: "Rejected. Your reason goes to the next draft.")
    }

    func edit(_ draft: GrowthDraft, body: String, hook: String) {
        guard GrowthLogic.canSave(body: body, original: draft.body, hook: hook, originalHook: draft.hook) else { return }
        let newHook = hook.trimmingCharacters(in: .whitespacesAndNewlines)
        run(draft, argv: GrowthActions.edit(draft.id, body: body, hook: newHook == draft.hook.trimmingCharacters(in: .whitespacesAndNewlines) ? nil : newHook),
            busy: "Saving…", done: "Saved. The voice and leak checks ran again.")
    }

    func dismissNotice() { notice = nil }

    private func run(_ draft: GrowthDraft, argv: [String], busy: String, done: String) {
        guard !(acts[draft.id]?.isBusy ?? false) else { return }
        acts[draft.id] = .running(busy)
        Task {
            do {
                _ = try await cli.runTool(argv)
                acts[draft.id] = nil
                notice = done
                refresh()
                changed()
            } catch {
                acts[draft.id] = .failed(error.localizedDescription)
            }
        }
    }
}

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
/// and asks the console to rebuild its counts. Approving only marks a draft. Publishing is a second, separate click on an
/// approved item: `teyla growth publish <id> --json` posts it to the networks the owner connected, and gives a packet for the rest.
/// The engage list only opens posts and records the replies the owner wrote himself.
@MainActor
@Observable
final class GrowthModel {
    private(set) var drafts: [GrowthDraft] = []
    /// Approved items that can go out (`GrowthEngage.ready`).
    private(set) var ready: [GrowthDraft] = []
    /// Item ids with a publish running.
    private(set) var publishing: Set<String> = []
    /// What the last publish of each item said, per network, by item id; kept after the item left the list.
    private(set) var published: [String: [PublishResult]] = [:]
    private(set) var publishFailure: String?

    /// Today's engage list. nil until read.
    private(set) var engage: EngageReport?
    private(set) var engageLoading = false
    private(set) var engageFailure: String?
    /// Rows a `done` is running for.
    private(set) var marking: Set<Int> = []
    private(set) var skipped = 0
    private(set) var phase: ConsolePhase = .idle
    /// What each draft's last action did, by item id. A draft with no entry is idle.
    private(set) var acts: [String: GrowthAct] = [:]
    /// What the last finished action said, kept after the draft left the queue.
    private(set) var notice: String?

    /// What was done to sell each product, read from the growth ledger for the product page. nil until read.
    private(set) var sales: SaleLedger.Read?
    private(set) var salesFailure: String?

    /// The activity graph (`teyla growth activity`). nil until read, or while the command cannot say.
    private(set) var activity: ActivityReport?
    /// Why there is no graph: an older command ("Update the teyla command to see activity."), or a failed read.
    private(set) var activityNote: String?
    private(set) var activityOutdated = false
    /// A "+1" is running, or what the last one said when it failed.
    private(set) var logging = false
    private(set) var logFailure: String?

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var activityGate = CoalescedRead()
    @ObservationIgnored private var salesReadAt: Date?
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
        if force { loadActivity() }   // activity logged from the command line shows up with the page's own refresh
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
                ready = GrowthEngage.ready(read.drafts)
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

    /// A product page opened: read the ledger when it was never read or the last read is old.
    func loadSales() {
        if let salesReadAt, Date().timeIntervalSince(salesReadAt) < Self.staleAfter, sales != nil { return }
        salesReadAt = Date()
        Task {
            do {
                sales = try await cli.saleAttempts()
                salesFailure = nil
            } catch {
                // The page hides older counts while the failure stands; a failed read is never "not tried yet".
                salesFailure = error.localizedDescription
                salesReadAt = nil
            }
        }
    }

    // MARK: Activity

    /// The card opened or the layout changed: read the graph. `weeks` is 53 whatever the layout, so switching never reads twice.
    func loadActivity() {
        guard activityGate.request() else { return }
        Task {
            defer { if activityGate.finish() { readActivityAgain() } }
            do {
                activity = try await cli.activity(weeks: 53)
                activityNote = nil
                activityOutdated = false
            } catch TeylaError.unavailable(let why) {
                activity = nil
                activityOutdated = true
                activityNote = why
            } catch {
                // The last graph stays on screen while the read fails.
                activityOutdated = false
                activityNote = error.localizedDescription
            }
        }
    }

    /// A request came in while a read ran: the gate is still busy, so read once more.
    private func readActivityAgain() {
        activityGate = CoalescedRead()
        loadActivity()
    }

    /// "+1": `teyla growth log --kind <kind> [--product P] [--count N]`, then the graph is read again. `done` is told whether it worked,
    /// so the popover closes only on success and the command's own error text stays visible on failure.
    func logActivity(kind: String, product: String?, count: Int, done: @escaping @MainActor (Bool) -> Void = { _ in }) {
        guard !logging, ActivityKind.isKnown(kind), ActivityLog.countRange.contains(count) else { return }
        logging = true
        logFailure = nil
        Task {
            do {
                _ = try await cli.runTool(ActivityLog.argv(kind: kind, product: product, count: count))
                logging = false
                loadActivity()
                changed()
                done(true)
            } catch {
                logging = false
                logFailure = error.localizedDescription
                done(false)
            }
        }
    }

    func clearLogFailure() { logFailure = nil }

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

    // MARK: Publish

    /// "Publish to connected networks": the CLI posts each approved item where a network is connected, writes a packet
    /// for the rest, and records each URL in the ledger. A second click on a published item does nothing new (idempotent).
    func publish(_ items: [GrowthDraft]) {
        let ids = items.map(\.id).filter { !publishing.contains($0) }
        guard !ids.isEmpty, ids.count <= GrowthEngage.maxPublish else { return }
        publishing.formUnion(ids)
        publishFailure = nil
        Task {
            defer { publishing.subtract(ids) }
            do {
                let text = try await cli.runTool(GrowthEngage.publish(ids))
                if let report = try? PublishReport.decode(Data(text.utf8)) {
                    for id in ids { published[id] = report.results.filter { $0.itemID == id } }
                    notice = report.summary
                } else {
                    notice = text.trimmingCharacters(in: .whitespacesAndNewlines)
                }
                refresh()
                changed()
            } catch {
                // Exit 1 means at least one network failed; the CLI's line says which. Read the queue again either way.
                publishFailure = error.localizedDescription
                refresh()
                changed()
            }
        }
    }

    func clearPublishFailure() { publishFailure = nil }

    // MARK: Engage

    /// Read today's list. `scan` lets the CLI run the day's one cached scan; the page opening reads the cache only.
    func loadEngage(scan: Bool = false) {
        guard !engageLoading else { return }
        engageLoading = true
        Task {
            defer { engageLoading = false }
            do {
                let text = try await cli.runTool(GrowthEngage.list(scan: scan))
                engage = try EngageReport.decode(Data(text.utf8))
                engageFailure = nil
            } catch {
                engageFailure = error.localizedDescription
            }
        }
    }

    /// The owner replied on the network: record it (`teyla growth engage done <n>`, an activity row by the owner).
    func markDone(_ row: EngageRow) {
        guard !row.done, !marking.contains(row.n) else { return }
        marking.insert(row.n)
        Task {
            defer { marking.remove(row.n) }
            do {
                _ = try await cli.runTool(GrowthEngage.done([row.n]))
                if var doc = engage, let i = doc.rows.firstIndex(where: { $0.n == row.n }) {
                    doc.rows[i].done = true
                    doc.done = doc.rows.filter(\.done).count
                    engage = doc
                }
                engageFailure = nil
                loadActivity()
                changed()
            } catch {
                engageFailure = error.localizedDescription
            }
        }
    }

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

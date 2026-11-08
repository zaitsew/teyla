import Foundation
import Observation

/// The Today screen's data: one read of `teyla gtm today --json`. Reading changes nothing and sends nothing. The drafts and
/// their approve, reject and edit belong to `GrowthModel`; this model only holds the numbers and the order of what is next.
@MainActor
@Observable
final class TodayModel {
    private(set) var today: GtmToday?
    /// Why there is no report: an older command ("Update the teyla command to see Today."), or a failed read.
    private(set) var note: String?
    private(set) var outdated = false
    private(set) var isLoading = false
    @ObservationIgnored private(set) var readAt: Date?
    /// A goal write is running (the form shows a spinner and disables its button).
    private(set) var goalBusy = false
    @ObservationIgnored private var releaseAfterRead = false
    /// A goal was added in this session; the first run keeps Create off until Today shows it, even when the read fails.
    private(set) var goalCreated = false
    /// The command's own words when the last goal write failed; nil otherwise. Nothing changed when this is set.
    private(set) var goalFailure: String?

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var gate = CoalescedRead()

    static let staleAfter: TimeInterval = 120

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    /// The screen opened: read when nothing was read yet or the last read is old.
    func opened() { refresh(force: false) }

    func refresh(force: Bool = true) {
        if !force, let readAt, Date().timeIntervalSince(readAt) < Self.staleAfter, today != nil { return }
        guard gate.request() else { return }
        isLoading = true
        Task {
            defer {
                if gate.finish() {
                    gate = CoalescedRead()
                    refresh()
                } else {
                    isLoading = false
                    if releaseAfterRead {
                        releaseAfterRead = false
                        goalBusy = false
                    }
                }
            }
            do {
                today = try await cli.gtmToday()
                note = nil
                outdated = false
                readAt = Date()
            } catch TeylaError.unavailable(let why) {
                today = nil
                outdated = true
                note = why
            } catch {
                // The last report stays on screen while the read fails.
                outdated = false
                note = error.localizedDescription
            }
        }
    }

    // MARK: Goals

    /// `teyla gtm goal add`, then Today is read again. `done` is told whether it worked, so a form closes only on success.
    func addGoal(title: String, weekly: [GtmWeeklyNumber], deadline: String?, doneWhen: String?, perDay: Int?,
                 done: @escaping @MainActor (Bool) -> Void = { _ in }) {
        write(done: done) { [cli] in
            try await cli.gtmGoalAdd(title: title, weekly: weekly, deadline: deadline, doneWhen: doneWhen, perDay: perDay)
            await MainActor.run { self.goalCreated = true }
        }
    }

    /// `teyla gtm goal set <id> --weekly stage=N`, then Today is read again.
    func setWeekly(goalID: String, stage: String, count: Int, replacing old: String? = nil,
                   done: @escaping @MainActor (Bool) -> Void = { _ in }) {
        write(done: done) { [cli] in
            try await cli.gtmGoalSet(id: goalID, weekly: TodayLogic.weeklyChange(stage: stage, count: count, replacing: old),
                                     title: nil, deadline: nil, doneWhen: nil)
        }
    }

    func clearGoalFailure() { goalFailure = nil }

    private func write(done: @escaping @MainActor (Bool) -> Void, _ action: @escaping @Sendable () async throws -> Void) {
        guard !goalBusy else { return }
        goalBusy = true
        goalFailure = nil
        Task {
            do {
                try await action()
                // Stay busy until Today is read again, so a second click cannot write the same goal twice.
                releaseAfterRead = true
                refresh()
                done(true)
            } catch {
                goalBusy = false
                goalFailure = error.localizedDescription
                done(false)
            }
        }
    }
}

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
}

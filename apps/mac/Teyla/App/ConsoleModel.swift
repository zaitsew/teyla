import Foundation
import Observation

/// What the admin sections are doing: nothing yet, reading, a report, or a failure.
enum ConsolePhase: Equatable, Sendable {
    case idle
    case loading
    case ready
    case failed(String)
}

/// The report behind Growth, Money, Operations and Playbook (`teyla console --json`). It never blocks a page: the last
/// report stays on screen while the next one is read, and a failed read keeps the old report, marked as old. A section
/// whose source failed shows its own error; the others load.
@MainActor
@Observable
final class ConsoleModel {
    private(set) var report: ConsoleReport?
    private(set) var phase: ConsolePhase = .idle
    /// When this window got the report, not when the CLI built it (`report.generated`).
    private(set) var readAt: Date?

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var reading: Task<Void, Never>?
    @ObservationIgnored private var queued: Bool?
    @ObservationIgnored private var triedCache = false

    /// A report younger than this is not read again when a page opens. The CLI keeps its own cache for 30 minutes.
    static let staleAfter: TimeInterval = 300

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    var isLoading: Bool { phase == .loading }

    var failure: String? {
        if case .failed(let why) = phase { return why }
        return nil
    }

    /// The sidebar badge of Operations: failures that need the owner, or "!" when the section could not be read.
    var operationsBadge: String? {
        switch report?.operations {
        case .failed: return "!"
        case .data(let ops):
            guard let count = ops.headline?.number, count > 0 else { return nil }
            return String(Int(count))
        default: return nil
        }
    }

    /// Reads the report. `rebuild` asks the CLI to rebuild its cache now; a read that is running is not started twice,
    /// and one asked for while it runs follows it (a rebuild wins over a cached read).
    func refresh(force: Bool = true, rebuild: Bool = false) {
        if !force, let readAt, Date().timeIntervalSince(readAt) < Self.staleAfter, phase == .ready { return }
        if isLoading {
            queued = (queued ?? false) || rebuild
            return
        }
        phase = .loading
        reading = Task {
            // The first paint comes from the CLI's own cache file, so a page is not empty while the command runs.
            if report == nil, !triedCache {
                triedCache = true
                if let cached = await cli.consoleCached(), report == nil { report = cached }
            }
            do {
                let next = try await cli.console(refresh: rebuild)
                report = next
                readAt = Date()
                phase = .ready
            } catch {
                phase = .failed(error.localizedDescription)
            }
            if let again = queued {
                queued = nil
                refresh(force: true, rebuild: again)
            }
        }
    }

    /// A console page opened: read when there is nothing yet or the report is old.
    func opened() { refresh(force: false) }
}

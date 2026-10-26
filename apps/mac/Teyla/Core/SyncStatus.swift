import Foundation

/// What the toolbar indicator says about the data on screen. Pure, so it can be tested.
enum SyncState: Equatable, Sendable {
    case updating
    case upToDate
    case stale
    case offline
}

struct SyncIndicator: Equatable, Sendable {
    var state: SyncState
    var label: String
    var tooltip: String
}

enum SyncStatus {
    /// A snapshot older than this is "stale": the 60 s timer missed at least one beat (a sleep, a hung command).
    static let staleAfter: TimeInterval = 120

    /// Rules, first match wins:
    /// 1. A refresh or the open product page is loading: "Updating…".
    /// 2. The last refresh failed: "Offline".
    /// 3. Nothing was read yet: "Updating…".
    /// 4. The data is older than `staleAfter`: "Stale · N min".
    /// 5. Otherwise "Up to date".
    /// The data's age counts from the earlier of the snapshot's own `generated` time and the time the app read it,
    /// so a CLI that serves an old snapshot does not look fresh.
    static func indicator(now: Date, fetchedAt: Date?, generated: Date?, refreshing: Bool, pageLoading: Bool,
                          error: String?, checkedStores: Date?, checkedGitHub: Date?, hasPortfolio: Bool,
                          calendar: Calendar = .current) -> SyncIndicator {
        let reference = [fetchedAt, generated].compactMap { $0 }.min()
        let age = reference.map { max(0, now.timeIntervalSince($0)) }
        let state: SyncState
        let label: String
        if refreshing || pageLoading {
            state = .updating
            label = "Updating…"
        } else if error != nil {
            state = .offline
            label = "Offline"
        } else if let age {
            if age >= staleAfter {
                state = .stale
                label = "Stale · \(Format.elapsed(seconds: age))"
            } else {
                state = .upToDate
                label = "Up to date"
            }
        } else {
            state = .updating
            label = "Updating…"
        }

        var lines: [String] = []
        if let error { lines.append("Could not read state: \(error)") }
        if pageLoading { lines.append("The product page is still reading sessions.") }
        if let fetchedAt { lines.append("Read by the app at \(clock(fetchedAt, calendar))") }
        if let generated { lines.append("Snapshot made at \(clock(generated, calendar))") }
        if hasPortfolio {
            lines.append("Stores checked \(since(checkedStores, now: now)) · GitHub \(since(checkedGitHub, now: now))")
        }
        lines.append("Teyla re-reads when sessions change, every minute, and when the Mac wakes.")
        return SyncIndicator(state: state, label: label, tooltip: lines.joined(separator: "\n"))
    }

    private static func since(_ date: Date?, now: Date) -> String {
        guard let date else { return "never" }
        return Format.ago(seconds: now.timeIntervalSince(date))
    }

    private static func clock(_ date: Date, _ calendar: Calendar) -> String {
        var style = Date.FormatStyle(date: .omitted, time: .standard)
        style.calendar = calendar
        style.timeZone = calendar.timeZone
        return date.formatted(style)
    }
}

import Foundation

/// What the main window's detail pane shows.
enum AppRoute: Hashable, Sendable {
    /// Home: the core products, the top decisions, and what runs.
    case home
    /// Every question that waits on the owner, then what agents handle, tasks, notes and finished work.
    case decisions
    /// All products, with health (`portfolio` in the snapshot).
    case portfolio
    case diagnosis
    case product(String)
}

/// Whether the window shows its sidebar (Home, Decisions, All products, Diagnosis) or only the welcome.
/// A machine with no data and no finished diagnosis gets the welcome alone: one button, nothing else to read.
enum Shell {
    static func showsWelcomeOnly(snapshot: Snapshot?, diagnosis: DiagnosisPhase, teylaMissing: Bool) -> Bool {
        guard !teylaMissing, let snapshot else { return false }
        if case .ready = diagnosis { return false }
        return snapshot.isEmpty
    }
}

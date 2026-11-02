import Foundation

/// What the main window's detail pane shows.
enum AppRoute: Hashable, Sendable {
    /// Home: the core products, the top decisions, and what runs.
    case home
    /// Every question that waits on the owner, then what agents handle, tasks, notes and finished work.
    case decisions
    /// All products, with health (`portfolio` in the snapshot).
    case portfolio
    /// The first-run diagnosis. Reached from the Tools page; the sidebar keeps Tools selected while it shows.
    case diagnosis
    /// What is wrong on this Mac's backend now (`teyla attention`), its actions, and the diagnosis link.
    case tools
    case product(String)
}

/// Whether the window shows its sidebar (Home, Decisions, All products, Tools) or only the welcome.
/// A machine with no data and no finished diagnosis gets the welcome alone: one button, nothing else to read.
enum Shell {
    static func showsWelcomeOnly(snapshot: Snapshot?, diagnosis: DiagnosisPhase, teylaMissing: Bool) -> Bool {
        guard !teylaMissing, let snapshot else { return false }
        if case .ready = diagnosis { return false }
        return snapshot.isEmpty
    }
}

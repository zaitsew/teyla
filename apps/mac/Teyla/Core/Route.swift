import Foundation

/// What the main window's detail pane shows.
enum AppRoute: Hashable, Sendable {
    case today
    case diagnosis
    case product(String)
}

/// Whether the window shows its sidebar (Today, Diagnosis, Products) or only the welcome.
/// A machine with no data and no finished diagnosis gets the welcome alone: one button, nothing else to read.
enum Shell {
    static func showsWelcomeOnly(snapshot: Snapshot?, diagnosis: DiagnosisPhase, teylaMissing: Bool) -> Bool {
        guard !teylaMissing, let snapshot else { return false }
        if case .ready = diagnosis { return false }
        return snapshot.isEmpty
    }
}

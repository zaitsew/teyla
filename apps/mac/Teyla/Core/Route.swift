import Foundation

/// What the main window's detail pane shows.
enum AppRoute: Hashable, Sendable {
    /// Home: the core products, the top decisions, and what runs.
    case home
    /// Every question that waits on the owner, then what agents handle, tasks, notes and finished work.
    case decisions
    /// Products, with health (`portfolio` in the snapshot).
    case portfolio
    /// The first-run diagnosis. Reached from Operations; the sidebar keeps Operations selected while it shows.
    case diagnosis
    /// The content factory: posts against the target, the review queue, the pipeline (`console.growth`).
    case growth
    /// What leaves the owner's accounts (`console.money`).
    case money
    /// What failed or needs capacity: the machine, failures, schedules, harnesses (`console.operations`).
    case operations
    /// What has been learned and standardized (`console.playbook`).
    case playbook
    /// Teyla's settings in plain groups, and this app's own switches. The Settings window (⌘,) stays.
    case settings
    case product(String)

    /// The four admin sections that read `teyla console`.
    var isConsole: Bool {
        switch self {
        case .growth, .money, .operations, .playbook: return true
        default: return false
        }
    }
}

extension ConsoleText {
    /// The words of the admin section a route opens. Kept here, not in `ConsoleLogic.swift`, so the iPhone app can
    /// compile that file without the Mac's routes.
    static func page(for route: AppRoute) -> Page? {
        switch route {
        case .growth: return growth
        case .money: return money
        case .operations: return operations
        case .playbook: return playbook
        default: return nil
        }
    }
}

/// Whether the window shows its sidebar (Home, Decisions, Products, Growth, Money, Operations, Playbook) or only the welcome.
/// A machine with no data and no finished diagnosis gets the welcome alone: one button, nothing else to read.
enum Shell {
    static func showsWelcomeOnly(snapshot: Snapshot?, diagnosis: DiagnosisPhase, teylaMissing: Bool) -> Bool {
        guard !teylaMissing, let snapshot else { return false }
        if case .ready = diagnosis { return false }
        return snapshot.isEmpty
    }
}

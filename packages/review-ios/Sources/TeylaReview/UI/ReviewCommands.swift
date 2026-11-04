#if os(macOS)
import Combine
import SwiftUI

/// Whether the Mac entry points show themselves. Review mode is allowed only once StoreKit has said
/// this is not an App Store install (`BuildChannel.detectMac`), which happens a moment after launch,
/// so the menu item follows the answer instead of reading it once.
@MainActor
final class ReviewAvailability: ObservableObject {
    static let shared = ReviewAvailability()

    @Published private(set) var active = TeylaReview.isActive
    private var observer: NSObjectProtocol?

    private init() {
        // The menu item may be the first thing to ask, in an app that never calls configure.
        if TeylaReview.isEnabled { MacStoreEnvironment.refreshOnce() }
        observer = NotificationCenter.default.addObserver(forName: .teylaReviewChannelChanged, object: nil, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated { self?.refresh() }
        }
    }

    func refresh() { active = TeylaReview.isActive }
}

extension ReviewShortcut {
    var keyEquivalent: KeyEquivalent { KeyEquivalent(key) }

    var eventModifiers: EventModifiers {
        var out: EventModifiers = []
        if control { out.insert(.control) }
        if option { out.insert(.option) }
        if command { out.insert(.command) }
        if shift { out.insert(.shift) }
        return out
    }
}

/// The Mac's way in: a Help menu item with Control-Option-Command-F.
///
///     WindowGroup { ContentView() }
///         .commands { ReviewCommands() }
///
/// Add `ReviewMenuButton()` to a Settings pane as well. Both draw nothing until review mode is on for
/// this install, so a store build shows neither.
public struct ReviewCommands: Commands {
    #if TEYLA_REVIEW
    @ObservedObject private var availability = ReviewAvailability.shared
    #endif

    public init() {}

    public var body: some Commands {
        #if TEYLA_REVIEW
        CommandGroup(after: .help) {
            if availability.active {
                Button(TeylaReview.configuration.strings().reportProblem) {
                    TeylaReview.present()
                }
                .keyboardShortcut(ReviewShortcut.mac.keyEquivalent, modifiers: ReviewShortcut.mac.eventModifiers)
            }
        }
        #else
        CommandGroup(after: .help) {}
        #endif
    }
}
#endif

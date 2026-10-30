import Foundation
import SwiftUI

/// The package's entry points. Every call does nothing unless the product turned review mode on
/// for this build (`isEnabled`), so a product can call them unconditionally. The overlay also
/// refuses to open in an App Store build, whatever the setting says.
public enum TeylaReview {
    /// Settings a product may change once, at launch: `TeylaReview.configure { $0.shake = true }`.
    public struct Configuration {
        /// Open review mode on a shake, as a shortcut. The explicit button is always the way in.
        public var shake = false
        /// Offer on-device speech recognition inside the overlay. Off by default: the keyboard's
        /// own microphone key is the first dictation path. Needs NSSpeechRecognitionUsageDescription
        /// and NSMicrophoneUsageDescription in the product's Info.plist.
        public var speech = false
        /// True while the product itself is recording or in a voice session.
        public var hostAudioInUse: (() -> Bool)?
        /// Called before review mode opens, so the product can pause its voice session.
        public var willBegin: (() -> Void)?
        /// Called after review mode closes, so the product can resume it.
        public var didEnd: (() -> Void)?
        public init() {}
    }

    public private(set) static var configuration = Configuration()
    static var keyStore: RelayKeyStoring = KeychainKeyStore()
    static var relayFolder = RelayFolder()

    /// Info.plist key that switches review mode on. A product sets it to `$(TEYLA_REVIEW_ENABLED)`
    /// and defines `TEYLA_REVIEW_ENABLED = YES` only in the Debug and TestFlight configurations.
    /// Absent, empty or anything but YES / true / 1 means off, so the App Store configuration
    /// needs no change beyond leaving the build setting undefined.
    static let enabledInfoKey = "TeylaReviewEnabled"

    /// Tests set this; a product has no reason to. `nil` reads the Info.plist.
    static var enabledOverride: Bool?

    static func parseEnabled(_ value: Any?) -> Bool {
        switch value {
        case let flag as Bool: return flag
        case let text as String: return ["yes", "true", "1"].contains(text.trimmingCharacters(in: .whitespaces).lowercased())
        case let number as NSNumber: return number.intValue == 1
        default: return false
        }
    }

    /// True when the product's build settings turned review mode on for this build.
    public static var isEnabled: Bool {
        enabledOverride ?? parseEnabled(Bundle.main.object(forInfoDictionaryKey: enabledInfoKey))
    }

    /// True when review mode is on for this build and this is not an App Store build.
    public static var isActive: Bool {
        isEnabled && BuildChannel.current != .appStore
    }

    public static func configure(_ change: (inout Configuration) -> Void) {
        change(&configuration)
        #if TEYLA_REVIEW && canImport(UIKit)
        ShakeShortcut.shared.set(enabled: configuration.shake && isActive)
        if isActive { ReviewLifecycle.installOnce() }
        #endif
    }

    /// Registers the screen that is showing, for example "trip.timeline". Anchors without a
    /// `.reviewScreen` above them are filed under it.
    public static func screen(_ id: String) {
        #if TEYLA_REVIEW
        guard isEnabled else { return }
        AnchorRegistry.shared.setScreen(id)
        #endif
    }

    /// Stores the pairing string `teyla relay pair` prints. Returns false for a string that is not one.
    @discardableResult
    public static func pair(_ pairingString: String) -> Bool {
        guard let key = RelayKey(pairing: pairingString), keyStore.save(key) else { return false }
        // Captures saved before pairing have no signature yet: sign them and copy what can be copied.
        if isActive { DispatchQueue.global(qos: .utility).async { ReviewDelivery.retryPending() } }
        return true
    }

    /// True once a key is stored.
    public static var isPaired: Bool { keyStore.load() != nil }

    /// Remembers the iCloud Drive `Teyla` folder the owner picked.
    public static func setRelayFolder(_ url: URL) throws { try relayFolder.remember(url) }

    /// Opens review mode: freezes the screen and shows the overlay. Call it from a debug-menu button.
    @MainActor
    public static func present() {
        #if TEYLA_REVIEW && canImport(UIKit)
        guard isActive else { return }
        ReviewPresenter.present()
        #endif
    }

    /// The status the owner sees for a capture, from the phone's own record and the Mac's signed answer.
    public static func status(of captureID: String) -> ReviewStatus {
        let store = CaptureStore(root: CaptureStore.defaultRoot())
        let key = keyStore.load()
        return relayFolder.withAccess { store.status(id: captureID, relayRoot: $0, key: key) }
            ?? store.status(id: captureID, relayRoot: nil, key: nil)
    }
}

// MARK: view modifiers

private struct ReviewScreenKey: EnvironmentKey { static let defaultValue: String? = nil }
private struct ReviewParentKey: EnvironmentKey { static let defaultValue: String? = nil }

extension EnvironmentValues {
    var reviewScreenID: String? {
        get { self[ReviewScreenKey.self] }
        set { self[ReviewScreenKey.self] = newValue }
    }
    var reviewParentID: String? {
        get { self[ReviewParentKey.self] }
        set { self[ReviewParentKey.self] = newValue }
    }
}

public extension View {
    /// Marks this view as an element a reviewer can point at. `id` is "screen.element", for example
    /// "trip.timeline.addButton". `strings` are the localization keys of the text it shows.
    /// The source file and line are filled in by the compiler.
    func reviewAnchor(
        _ id: String, role: ReviewRole = .other, strings: [String] = [],
        file: String = #fileID, line: Int = #line
    ) -> some View {
        #if TEYLA_REVIEW && canImport(UIKit)
        return modifier(ReviewAnchorModifier(id: id, role: role, strings: strings, file: file, line: line))
        #else
        return self
        #endif
    }

    /// Marks the screen: anchors below it are filed under `id`, and `TeylaReview.screen(id)` is
    /// called when it appears.
    func reviewScreen(_ id: String) -> some View {
        #if TEYLA_REVIEW
        return environment(\.reviewScreenID, id).onAppear { TeylaReview.screen(id) }
        #else
        return self
        #endif
    }
}

/// A button for a debug menu: "Review this screen".
public struct ReviewMenuButton: View {
    public init() {}

    public var body: some View {
        #if TEYLA_REVIEW
        if TeylaReview.isActive {
            Button {
                TeylaReview.present()
            } label: {
                Label("Review this screen", systemImage: "text.bubble")
            }
            .accessibilityIdentifier("teyla.review.open")
        }
        #else
        EmptyView()
        #endif
    }
}

#if !(TEYLA_REVIEW && canImport(UIKit))
/// Present so a product can reference it unconditionally; it shows nothing when the overlay is not compiled in.
public struct ReviewSettingsView: View {
    public init() {}
    public var body: some View { EmptyView() }
}
#endif

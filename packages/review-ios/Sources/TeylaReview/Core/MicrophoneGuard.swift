import Foundation

/// What the guard needs from AVAudioSession, as plain values, so the logic is tested without audio.
protocol AudioSessionControlling {
    var categoryName: String { get }
    var modeName: String { get }
    var optionsRaw: UInt { get }
    func restore(category: String, mode: String, options: UInt) throws
    func setActive(_ active: Bool) throws
}

struct MicrophoneState: Equatable {
    var hostAudioInUse: Bool
    var category: String
    var mode: String
    var options: UInt
}

/// The microphone belongs to the product first (a voice mode, a recorder). The guard records the
/// session before review mode touches it and puts it back afterwards.
///
/// AVAudioSession cannot say "another part of the app is recording right now", so the product
/// says it: `TeylaReview.configure { $0.hostAudioInUse = { voice.isRunning } }`. Without that
/// closure the guard assumes a record-capable category means the product is using the microphone.
final class MicrophoneGuard {
    private let session: AudioSessionControlling
    private let hostAudioInUse: (() -> Bool)?
    private(set) var saved: MicrophoneState?
    private var taken = false

    init(session: AudioSessionControlling, hostAudioInUse: (() -> Bool)? = nil) {
        self.session = session
        self.hostAudioInUse = hostAudioInUse
    }

    static let recordCategories: Set<String> = ["AVAudioSessionCategoryPlayAndRecord", "AVAudioSessionCategoryRecord"]

    /// Records the state. Call it before the overlay opens; the state goes into the capture.
    @discardableResult
    func begin() -> MicrophoneState {
        let state = MicrophoneState(
            hostAudioInUse: hostAudioInUse?() ?? Self.recordCategories.contains(session.categoryName),
            category: session.categoryName, mode: session.modeName, options: session.optionsRaw)
        saved = state
        taken = false
        return state
    }

    /// Call it right before review mode takes the microphone itself (speech capture).
    func markTaken() { taken = true }

    /// Puts the category, mode and options back. When review mode took the microphone, it also
    /// leaves the session active if the product was using it, and deactivates it if not.
    /// Returns false if the system refused.
    @discardableResult
    func end() -> Bool {
        defer { saved = nil; taken = false }
        guard let state = saved else { return true }
        let changed = session.categoryName != state.category || session.modeName != state.mode || session.optionsRaw != state.options
        guard taken || changed else { return true }
        do {
            try session.restore(category: state.category, mode: state.mode, options: state.options)
            try session.setActive(state.hostAudioInUse)
            return true
        } catch {
            return false
        }
    }

    var info: MicrophoneInfo? { saved.map { MicrophoneInfo(hostAudioInUse: $0.hostAudioInUse, category: $0.category) } }
}

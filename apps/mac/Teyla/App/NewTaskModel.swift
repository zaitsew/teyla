import Observation
import SwiftUI

/// State of the "New task" sheet. The draft lives here, not in the view, so the global shortcut
/// can fill it before the sheet is on screen, and a closed sheet keeps what was typed.
@MainActor
@Observable
final class NewTaskModel {
    static let dictationTarget = "new-task"

    var presented = false
    var draft = ""
    var product: String?
    var harness: Harness = .codex
    private(set) var status: CardStatus?
    private(set) var result: AnswerResult?

    @ObservationIgnored private let cli: any TeylaBackend

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    var isSending: Bool {
        if case .sending = status { return true }
        return false
    }

    /// Picks the product when the sheet opens: the selected one, else the one chosen before, else the first.
    func prepare(products: [Product], selected: String?) {
        let names = NewTask.products(products).map(\.name)
        if let selected, names.contains(selected) {
            product = selected
        } else if let product, names.contains(product) {
            // keep the earlier choice
        } else {
            product = names.first
        }
        if case .failed = status { status = nil }
    }

    func send() {
        guard NewTask.canSend(product: product, text: draft), !isSending, let product else { return }
        Dictation.shared.stop()             // later results must not refill the draft after it is sent
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let harness = harness
        status = .sending("Starting…")
        result = nil
        Task {
            do {
                let started = try await cli.dispatch(product: product, harness: harness, text: text)
                result = started
                status = .done(Format.startedLine(via: started.via, worktree: started.worktree))
                draft = ""
            } catch {
                // The draft stays, so a failed start loses nothing.
                status = .failed(error.localizedDescription)
            }
        }
    }

    /// Forgets the last result once the owner starts a new draft.
    func resetResult() {
        if case .sending = status { return }
        status = nil
        result = nil
    }

    func dismiss() {
        Dictation.shared.stop()
        presented = false
        if case .done = status { resetResult() }
    }
}

/// State of the iPhone relay controls in Settings. In fixture mode the toggle is simulated.
@MainActor
@Observable
final class RelayModel {
    enum PairingState: Equatable {
        case idle
        case working
        case ready(String)
        case failed(String)
    }

    private(set) var pairing: PairingState = .idle
    private(set) var busy = false
    private(set) var error: String?
    /// The switch as the owner set it, until the next snapshot confirms it.
    private(set) var pendingOn: Bool?

    @ObservationIgnored private let cli: any TeylaBackend
    @ObservationIgnored private var clearTask: Task<Void, Never>?

    init(cli: any TeylaBackend) {
        self.cli = cli
    }

    func isOn(snapshot relay: Relay?) -> Bool { pendingOn ?? relay?.on ?? false }

    func setOn(_ on: Bool) {
        guard !busy else { return }
        busy = true
        error = nil
        pendingOn = on
        Task {
            do {
                try await cli.setRelay(on: on)
                if !on { clearPairing() }
                AppModel.shared.refresh()
            } catch {
                pendingOn = nil
                self.error = error.localizedDescription
            }
            busy = false
        }
    }

    func pair() {
        guard pairing != .working else { return }
        pairing = .working
        error = nil
        Task {
            do {
                let text = try await cli.relayPair()
                pairing = .ready(text)
                scheduleClear()
            } catch {
                pairing = .failed(error.localizedDescription)
            }
        }
    }

    /// The key is on screen only while the owner pairs: it is cleared after 5 minutes and when Settings closes.
    func clearPairing() {
        clearTask?.cancel()
        pairing = .idle
    }

    private func scheduleClear() {
        clearTask?.cancel()
        clearTask = Task {
            try? await Task.sleep(for: .seconds(300))
            if !Task.isCancelled { pairing = .idle }
        }
    }

    /// A real snapshot is the truth about the switch; a fixture never changes, so its simulated switch stays.
    func reconcile(with relay: Relay?, usesFixture: Bool) {
        if !usesFixture { pendingOn = nil }
    }
}

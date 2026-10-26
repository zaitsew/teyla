import Foundation

enum TeylaError: LocalizedError, Equatable {
    case binaryNotFound
    case fixtureUnreadable(String)
    case failed(code: Int32, message: String)
    case badOutput(String)
    case timedOut
    /// The build or the data source cannot do this (the store build has no `teyla` command to run).
    case unavailable(String)

    var errorDescription: String? {
        switch self {
        case .binaryNotFound:
            return "The teyla command was not found. Install Teyla, or choose the file."
        case .fixtureUnreadable(let path):
            return "Could not read the state fixture at \(path)."
        case .failed(let code, let message):
            let text = message.trimmingCharacters(in: .whitespacesAndNewlines)
            return text.isEmpty ? "teyla exited with status \(code)." : text
        case .badOutput(let why):
            return "teyla printed something the app could not read (\(why))."
        case .timedOut:
            return "teyla did not answer in time."
        case .unavailable(let what):
            return what
        }
    }
}

/// Where the window gets its data and sends its actions. The full app runs the `teyla` command
/// (`TeylaCLI`); the store build, which is sandboxed, reads and writes the signed relay folder
/// (`StoreBackend`). Only the first five are the relay's contract (docs/APP.md); every other call is the
/// command's and, in the store build, throws `unavailable` — its control is hidden (`Capabilities`).
protocol TeylaBackend: Sendable {
    /// True for sample data: the clock stays at the snapshot's own time and every write is simulated.
    var usesFixture: Bool { get }

    func state() async throws -> Snapshot
    func answer(id: String, text: String) async throws -> AnswerResult
    func say(ref: String, text: String) async throws -> AnswerResult
    func dispatch(product: String, harness: Harness, text: String) async throws -> AnswerResult
    /// The product page; the store build builds it from the snapshot.
    func productPage(id: String, quick: Bool) async throws -> ProductPageData

    // The command's alone.
    func binaryPath() async -> String?
    func forgetBinary()
    func snooze(id: String, days: Int) async throws
    func markDone(id: String) async throws
    func setStage(id: String, stage: ProductStage) async throws
    func setFocus(id: String, focus: Bool) async throws
    func start() async throws -> StartReport
    func apply(offerID: String) async throws -> String
    func notes() async throws -> [NoteItem]
    func suggestNote(text: String, products: [String]) async throws -> NoteSuggestion
    func saveNote(text: String, product: String) async throws -> NoteItem
    func linkNote(id: String, product: String) async throws
    func dropNote(id: String) async throws
    func setRelay(on: Bool) async throws
    func relayPair() async throws -> String
}

extension TeylaBackend {
    private static var none: TeylaError { .unavailable("This needs the teyla command, which this version of Teyla does not run.") }

    func binaryPath() async -> String? { nil }
    func forgetBinary() {}
    func snooze(id: String, days: Int) async throws { throw Self.none }
    func markDone(id: String) async throws { throw Self.none }
    func setStage(id: String, stage: ProductStage) async throws { throw Self.none }
    func setFocus(id: String, focus: Bool) async throws { throw Self.none }
    func start() async throws -> StartReport { throw Self.none }
    func apply(offerID: String) async throws -> String { throw Self.none }
    func notes() async throws -> [NoteItem] { throw Self.none }
    func suggestNote(text: String, products: [String]) async throws -> NoteSuggestion { throw Self.none }
    func saveNote(text: String, product: String) async throws -> NoteItem { throw Self.none }
    func linkNote(id: String, product: String) async throws { throw Self.none }
    func dropNote(id: String) async throws { throw Self.none }
    func setRelay(on: Bool) async throws { throw Self.none }
    func relayPair() async throws -> String { throw Self.none }
}

/// What the window offers. The full app does everything; the store build offers what the relay can carry
/// (an answer, a correction, a new task) and hides the rest, so no control is ever shown that cannot work.
struct Capabilities: Equatable, Sendable {
    /// Snooze, and "Mark done" on a question.
    var closeQuestions = true
    /// The Codex / Claude choice of a new task (the relay lets the Mac choose).
    var chooseHarness = true
    /// Notes, the quick-note panel and its shortcut.
    var notes = true
    /// The first-run diagnosis and its offers.
    var diagnosis = true
    /// Stage and focus of a product.
    var editProducts = true
    /// The iPhone relay switch and the pairing QR code.
    var pairPhone = true
    /// The product page's sessions and spend come from the command; the store build shows recent work from the snapshot.
    var spendDetail = true

    static let full = Capabilities()
    static let store = Capabilities(closeQuestions: false, chooseHarness: false, notes: false, diagnosis: false,
                                    editProducts: false, pairPhone: false, spendDetail: false)

    /// The set for this build.
    static var current: Capabilities {
        #if STORE
        return .store
        #else
        return .full
        #endif
    }
}

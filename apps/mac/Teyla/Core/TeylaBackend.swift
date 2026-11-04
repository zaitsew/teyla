import Foundation

/// Where the window gets its data and sends its actions. The full app runs the `teyla` command
/// (`TeylaCLI`); the store build, which is sandboxed, reads and writes the signed relay folder
/// (`StoreBackend`). Only the first five are the relay's contract (docs/APP.md), and `relayPair`, which the store build
/// answers from the stored key; every other call is the command's and, in the store build, throws `unavailable` —
/// its control is hidden (`Capabilities`).
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
    /// `teyla product core`: exactly these products are starred (none: every star is cleared).
    func setCore(ids: [String]) async throws
    /// `teyla product set <id> type=<type>`: the owner chooses the type of a product. Teyla never infers it.
    func setType(id: String, type: StartupType) async throws
    /// `teyla startup --json`, read for its `focus`: the product the startup page leads with; nil when there is none.
    func startupFocus() async throws -> String?
    /// `teyla startup yc <id> --json`: the YC sheet with its boxes and the owner's answers.
    func ycSheet(id: String) async throws -> YCSheet
    /// `teyla startup yc answer <id> <box> <text>`.
    func ycAnswer(id: String, box: String, text: String) async throws
    /// `teyla asks undo`: reopens a question Teyla closed on its own.
    func undoAsk(id: String) async throws
    /// `teyla asks accept-close`: the owner accepts Teyla's suggestion to close these questions.
    func acceptClose(ids: [String]) async throws
    func start() async throws -> StartReport
    /// `teyla attention --json`: what is wrong on this Mac's backend now.
    func attention() async throws -> AttentionReport
    /// `teyla console --json`: the admin sections. The CLI keeps its own cache for 30 minutes; `refresh` rebuilds it now.
    func console(refresh: Bool) async throws -> ConsoleReport
    /// The CLI's last cached report, read from disk without running anything; nil when there is none.
    func consoleCached() async -> ConsoleReport?
    /// The drafts waiting for review, read from `~/.teyla/growth/items` (no command runs). Nothing is changed by reading.
    func growthDrafts() async throws -> GrowthDrafts.Read
    /// What was done to sell each product, counted from the growth ledger (no command runs).
    func saleAttempts() async throws -> SaleLedger.Read
    /// Teyla's settings file, read as it is (no command runs).
    func teylaConfig() async throws -> TeylaConfig
    /// Runs one command of the Tools page and returns what it printed. Only commands `ToolCommands` allows are run.
    func runTool(_ argv: [String]) async throws -> String
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

    func forgetBinary() {}
    func snooze(id: String, days: Int) async throws { throw Self.none }
    func markDone(id: String) async throws { throw Self.none }
    func setStage(id: String, stage: ProductStage) async throws { throw Self.none }
    func setFocus(id: String, focus: Bool) async throws { throw Self.none }
    func setCore(ids: [String]) async throws { throw Self.none }
    func setType(id: String, type: StartupType) async throws { throw Self.none }
    func startupFocus() async throws -> String? { throw Self.none }
    func ycSheet(id: String) async throws -> YCSheet { throw Self.none }
    func ycAnswer(id: String, box: String, text: String) async throws { throw Self.none }
    func undoAsk(id: String) async throws { throw Self.none }
    func acceptClose(ids: [String]) async throws { throw Self.none }
    func start() async throws -> StartReport { throw Self.none }
    func attention() async throws -> AttentionReport { throw Self.none }
    func console(refresh: Bool) async throws -> ConsoleReport { throw Self.none }
    func consoleCached() async -> ConsoleReport? { nil }
    func growthDrafts() async throws -> GrowthDrafts.Read { throw Self.none }
    func saleAttempts() async throws -> SaleLedger.Read { throw Self.none }
    func teylaConfig() async throws -> TeylaConfig { throw Self.none }
    func runTool(_ argv: [String]) async throws -> String { throw Self.none }
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
    /// Snooze, and "Mark done" on a question, and Undo on a question Teyla closed.
    var closeQuestions = true
    /// The Codex / Claude choice of a new task (the relay lets the Mac choose).
    var chooseHarness = true
    /// Notes, the quick-note panel and its shortcut.
    var notes = true
    /// The first-run diagnosis and its offers.
    var diagnosis = true
    /// Stage and focus of a product, and the star that sets the core list on Home.
    var editProducts = true
    /// The iPhone relay switch and the pairing QR code.
    var pairPhone = true
    /// The product page's sessions and spend come from the command; the store build shows recent work from the snapshot.
    var spendDetail = true
    /// The YC sheet and its answers live in `~/.teyla/startup/` and are read and written by the command. The relay is signed,
    /// not encrypted, so the store build never has them: it shows the count from the snapshot and nothing else.
    var startupSheet = true
    /// The Operations page's actions and the command bar's: they run the command, which the store build does not have.
    var tools = true
    /// Growth, Money, Operations and Playbook read `teyla console`, which the store build cannot run.
    var console = true

    static let full = Capabilities()
    static let store = Capabilities(closeQuestions: false, chooseHarness: false, notes: false, diagnosis: false,
                                    editProducts: false, pairPhone: false, spendDetail: false, startupSheet: false, tools: false, console: false)

    /// The set for this build.
    static var current: Capabilities {
        #if STORE
        return .store
        #else
        return .full
        #endif
    }
}

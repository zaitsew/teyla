import XCTest
import os

private func report(_ name: String = "attention.v1.json") throws -> AttentionReport {
    try AttentionReport.decode(SampleFiles.data(name))
}

private func decode(_ json: String) throws -> AttentionReport {
    try AttentionReport.decode(Data(json.utf8))
}

final class AttentionDecodingTests: XCTestCase {
    func testTheSampleReportDecodesWithItsKindsActionsAndFacts() throws {
        let r = try report()
        XCTAssertEqual(r.items.count, 7)
        XCTAssertEqual(r.items.map(\.kind), ["disk", "schedule", "schedule", "p1", "offer", "doctor", "unknown"])
        XCTAssertEqual(r.actCount, 4)
        let disk = try XCTUnwrap(r.items.first)
        XCTAssertEqual(disk.actions.first?.command, ["storage", "sweep"])
        XCTAssertEqual(disk.actions.first?.preview, ["storage", "sweep", "--dry"])
        XCTAssertEqual(disk.actions.first?.destructive, true)
        let offer = try XCTUnwrap(r.items.first { $0.kind == "offer" })
        XCTAssertEqual(offer.facts.map(\.label), ["Trade-off", "Undo"])
        XCTAssertFalse(offer.needsYou)
        XCTAssertNil(r.items.first { $0.id == "schedule:claude-desktop:old-digest" }?.actions.first?.preview)
    }

    func testTheQuietLineNamesWhatWasCheckedAndIsFine() throws {
        let line = try report().quietLine
        XCTAssertEqual(line, "14 scheduled tasks fine · 3 not verifiable · 5 builds current · disk 9.2 GB free · machine ok · doctor 2 to look at · offers 1")
    }

    func testAnEmptyReportIsReadAsEmptyAndSaysSo() throws {
        let r = try report("attention.empty.v1.json")
        XCTAssertTrue(r.items.isEmpty)
        XCTAssertEqual(ToolsPage.headline(report: r, phase: .ready), "Nothing needs you here.")
        XCTAssertTrue(r.quietLine.contains("doctor ok"))
    }

    func testAReportWithoutAnItemsKeyIsRefusedNotShownAsCalm() {
        XCTAssertThrowsError(try decode(#"{"version":1,"quiet":{"schedules":3}}"#))
        XCTAssertThrowsError(try decode("[]"))
        XCTAssertThrowsError(try decode(#"{"items":"none"}"#))
    }

    func testAnItemTheAppCannotReadBecomesARowNotASmallerList() throws {
        let r = try decode(#"{"items":[{"id":"a","title":"One"},{"title":"No id"}]}"#)
        XCTAssertEqual(r.items.map(\.id), ["a", "unknown:app"])
        XCTAssertEqual(r.items.last?.kind, "unknown")
        XCTAssertNotEqual(ToolsPage.headline(report: r, phase: .ready), "Nothing needs you here.")
    }

    func testUnknownValuesReadAsTheCarefulAnswer() throws {
        let r = try decode(#"""
        {"items":[{"id":"a","title":"One","kind":"weather","severity":"loud",
                   "actions":[{"command":["storage","sweep"]},{"label":"No command"}]}]}
        """#)
        let item = try XCTUnwrap(r.items.first)
        XCTAssertEqual(item.kind, "unknown")
        XCTAssertEqual(item.severity, "act")
        XCTAssertEqual(item.actions.count, 1)                     // the action without a command is dropped
        XCTAssertEqual(item.actions.first?.destructive, true)     // no flag means: ask
        XCTAssertEqual(item.actions.first?.label, "Run")
    }

    func testAnEmptyPreviewReadsAsNoPreview() throws {
        let action = try JSONDecoder().decode(ToolAction.self, from: Data(#"{"label":"Go","command":["portfolio","--refresh"],"preview":[]}"#.utf8))
        XCTAssertNil(action.preview)
    }

    func testQuietValuesMayBeNumbersWordsOrBooleans() throws {
        let r = try decode(#"{"items":[],"quiet":{"schedules":4,"disk":"7 GB free","guard":true,"other":2.5}}"#)
        XCTAssertEqual(r.quiet["schedules"], "4")
        XCTAssertEqual(r.quiet["guard"], "yes")
        XCTAssertEqual(r.quiet["other"], "2.5")
        XCTAssertTrue(r.quietLine.hasPrefix("4 scheduled tasks fine"))
    }
}

final class ToolsPageTests: XCTestCase {
    func testHeadlineCountsWhatNeedsYouAndWhatIsOnlyToLookAt() throws {
        let r = try report()
        XCTAssertEqual(ToolsPage.headline(report: r, phase: .ready), "4 things need you and 3 more to look at.")
        let one = AttentionReport(items: [AttentionItem(id: "a", title: "A")])
        XCTAssertEqual(ToolsPage.headline(report: one, phase: .ready), "1 thing needs you.")
        let info = AttentionReport(items: [AttentionItem(id: "a", title: "A", severity: "info")])
        XCTAssertEqual(ToolsPage.headline(report: info, phase: .ready), "1 thing to look at.")
    }

    func testAFailedReadIsNeverCalm() throws {
        XCTAssertEqual(ToolsPage.headline(report: nil, phase: .failed("x")), "Teyla could not read what is wrong on this Mac.")
        XCTAssertEqual(ToolsPage.headline(report: try report("attention.empty.v1.json"), phase: .failed("x")),
                       "The last read failed. This list may be out of date.")
        XCTAssertEqual(ToolsPage.headline(report: nil, phase: .loading), "Reading what is wrong on this Mac…")
    }

    func testTheAgeLine() {
        let now = Date()
        XCTAssertEqual(ToolsPage.ageLine(readAt: nil, now: now), "")
        XCTAssertEqual(ToolsPage.ageLine(readAt: now.addingTimeInterval(-10), now: now), "Read just now")
        XCTAssertEqual(ToolsPage.ageLine(readAt: now.addingTimeInterval(-300), now: now), "Read 5 min ago")
        XCTAssertEqual(ToolsPage.ageLine(readAt: now.addingTimeInterval(-7300), now: now), "Read 2 h ago")
        XCTAssertEqual(ToolsPage.ageLine(readAt: now.addingTimeInterval(-3 * 86_400), now: now), "Read 3 d ago")
    }
}

final class ToolCommandsTests: XCTestCase {
    func testTheAllowListNamesEveryCommandThePageMayRun() {
        let allowed: [[String]] = [
            ["storage", "sweep"], ["storage", "sweep", "--dry"], ["portfolio", "--refresh"],
            ["apply", "O3", "--yes"], ["apply", "O12", "--dry"],
            ["schedules", "forget", "claude-desktop:old-digest"], ["schedules", "forget", "launchd:com.example.job", "routines:app:job"],
            ["schedules", "forget", "github:example/app:weekly"],
        ]
        for argv in allowed { XCTAssertEqual(ToolCommands.check(argv), .allowed, argv.joined(separator: " ")) }
    }

    func testAnythingElseIsRefusedAndNamed() {
        let refused: [[String]] = [
            [], ["rm", "-rf", "/"], ["storage"], ["storage", "sweep", "--temp"], ["storage", "sweep", "extra"],
            ["apply", "O1"], ["apply", "O1", "--force"], ["apply", "../O1", "--yes"], ["apply", "1", "--yes"], ["apply", "O", "--yes"],
            ["schedules", "forget"], ["schedules", "forget", "-all"], ["schedules", "forget", "a b"], ["schedules", "forget", "a;b"],
            ["schedules", "forget", "$(x)"], ["schedules", "pause", "x"],
            ["testflight", "release"], ["release"], ["deploy"], ["send"], ["answer", "q1", "--", "yes"], ["dispatch", "app"],
            ["portfolio"], ["portfolio", "--refresh", "--allow-network"], ["attention", "--json"], ["relay", "on"],
        ]
        for argv in refused {
            guard case .refused(let why) = ToolCommands.check(argv) else { return XCTFail("allowed: \(argv)") }
            XCTAssertFalse(why.isEmpty)
        }
    }

    func testTooManyOrOverlongTaskIdsAreRefused() {
        XCTAssertEqual(ToolCommands.check(["schedules", "forget"] + Array(repeating: "a", count: 20)), .allowed)
        XCTAssertNotEqual(ToolCommands.check(["schedules", "forget"] + Array(repeating: "a", count: 21)), .allowed)
        XCTAssertFalse(ToolCommands.isTaskKey(String(repeating: "a", count: 201)))
        XCTAssertFalse(ToolCommands.isTaskKey(""))
        XCTAssertFalse(ToolCommands.isTaskKey("é"))
    }

    func testAPreviewMustBeAnAllowedDryRun() {
        XCTAssertEqual(ToolCommands.checkPreview(["storage", "sweep", "--dry"]), .allowed)
        XCTAssertEqual(ToolCommands.checkPreview(["apply", "O2", "--dry"]), .allowed)
        for argv in [["storage", "sweep"], ["apply", "O2", "--yes"], ["portfolio", "--refresh"], ["schedules", "forget", "x"], ["rm", "-rf", "x", "--dry"]] {
            XCTAssertNotEqual(ToolCommands.checkPreview(argv), .allowed, argv.joined(separator: " "))
        }
    }

    func testEffects() {
        XCTAssertEqual(ToolCommands.effect(["portfolio", "--refresh"]), .reads)
        XCTAssertEqual(ToolCommands.effect(["storage", "sweep", "--dry"]), .previews)
        XCTAssertEqual(ToolCommands.effect(["apply", "O1", "--dry"]), .previews)
        XCTAssertEqual(ToolCommands.effect(["storage", "sweep"]), .changes)
        XCTAssertEqual(ToolCommands.effect(["schedules", "forget", "x"]), .changes)
    }

    func testDisplayShowsTheCommandAsTypedAndQuotesWhatNeedsIt() {
        XCTAssertEqual(ToolCommands.display(["storage", "sweep", "--dry"]), "teyla storage sweep --dry")
        XCTAssertEqual(ToolCommands.display(["schedules", "forget", "a b"]), "teyla schedules forget 'a b'")
        XCTAssertEqual(ToolCommands.display(["x", "it's"]), "teyla x 'it'\\''s'")
    }

    func testLongOutputKeepsItsLastLines() {
        let long = (1...40).map { "line \($0)" }.joined(separator: "\n")
        let out = ToolCommands.trimmed(long, lines: 5)
        XCTAssertEqual(out, "…\nline 36\nline 37\nline 38\nline 39\nline 40")
        XCTAssertEqual(ToolCommands.trimmed("  one\n"), "one")
        XCTAssertLessThanOrEqual(ToolCommands.trimmed(String(repeating: "x", count: 5000), characters: 100).count, 101)
    }
}

final class ToolFlowTests: XCTestCase {
    private func action(_ command: [String], preview: [String]? = nil, destructive: Bool = false) -> ToolAction {
        ToolAction(label: "Do", command: command, preview: preview, destructive: destructive)
    }

    func testAnActionWithAPreviewReadsItFirst() {
        XCTAssertEqual(ToolFlow.begin(action(["storage", "sweep"], preview: ["storage", "sweep", "--dry"], destructive: true)), .previewing)
        XCTAssertEqual(ToolFlow.begin(action(["apply", "O2", "--yes"], preview: ["apply", "O2", "--dry"])), .previewing)
    }

    func testAnActionWithoutAPreviewAsksWithTheExactCommand() {
        XCTAssertEqual(ToolFlow.begin(action(["schedules", "forget", "x"], destructive: true)), .confirming)
    }

    func testOnlyTheReadOnlyRefreshRunsAtOnce() {
        XCTAssertNil(ToolFlow.begin(action(["portfolio", "--refresh"])))
        // ...unless the report says it is destructive: the careful flag wins.
        XCTAssertEqual(ToolFlow.begin(action(["portfolio", "--refresh"], destructive: true)), .confirming)
    }

    func testARefusedCommandOrPreviewNeverStarts() {
        guard case .refused = ToolFlow.begin(action(["rm", "-rf", "/"])) else { return XCTFail("started") }
        guard case .refused = ToolFlow.begin(action(["storage", "sweep"], preview: ["storage", "sweep"])) else { return XCTFail("a non-dry preview ran") }
        guard case .refused = ToolFlow.begin(action(["storage", "sweep"], preview: ["testflight", "--dry"])) else { return XCTFail("started") }
    }

    func testConfirmIsOpenOnlyAfterAPreviewOrWhereNoneExists() {
        XCTAssertTrue(ToolFlow.canConfirm(.preview("out")))
        XCTAssertTrue(ToolFlow.canConfirm(.confirming))
        for run: ToolRun? in [nil, .previewing, .running, .done("x"), .failed("x"), .refused("x")] {
            XCTAssertFalse(ToolFlow.canConfirm(run), "\(String(describing: run))")
        }
    }

    func testTheButtonAndTheStepsDoNotShowTogether() {
        XCTAssertTrue(ToolFlow.showsButton(nil))
        XCTAssertTrue(ToolFlow.showsButton(.done("x")))
        XCTAssertFalse(ToolFlow.showsButton(.preview("x")))
        XCTAssertFalse(ToolFlow.showsButton(.confirming))
        XCTAssertFalse(ToolFlow.canBegin(.running))
        XCTAssertFalse(ToolFlow.canBegin(.previewing))
        XCTAssertTrue(ToolFlow.canBegin(.failed("x")))
    }

    func testEverySampleActionStartsAtAStepThatShowsTheCommandFirst() throws {
        for item in try report().items {
            for action in item.actions {
                guard let run = ToolFlow.begin(action) else {
                    XCTAssertEqual(ToolCommands.effect(action.command), .reads, "\(action.id) ran at once")
                    continue
                }
                switch run {
                case .previewing, .confirming: break
                default: XCTFail("\(action.id) started at \(run)")
                }
            }
        }
    }
}

final class CommandBarTests: XCTestCase {
    private let products = [(id: "sample-app", name: "sample-app"), (id: "sample-tool", name: "sample-tool")]

    private func entries(tools: Bool = true, report: AttentionReport? = nil) -> [CommandEntry] {
        CommandBar.entries(products: products, report: report, capabilities: tools ? .full : .store)
    }

    func testTheFixedEntriesComeFirstAndOnlyThoseExist() {
        let ids = entries().map(\.id)
        XCTAssertEqual(ids, ["go:home", "go:decisions", "go:portfolio", "go:growth", "go:money", "go:operations", "go:playbook", "go:settings",
                             "product:sample-app", "product:sample-tool", "new-task", "refresh"])
    }

    func testTheStoreBuildHasNoAdminSectionsAndNoActions() throws {
        let store = entries(tools: false, report: try report())
        XCTAssertEqual(store.map(\.id).prefix(3), ["go:home", "go:decisions", "go:portfolio"])
        XCTAssertFalse(store.contains { ["go:growth", "go:money", "go:operations", "go:playbook"].contains($0.id) })
        XCTAssertFalse(store.contains { if case .tool = $0.kind { return true } else { return false } })
    }

    func testEveryActionOnThePageIsAnEntryWithItsExactCommand() throws {
        let list = entries(report: try report())
        let sweep = try XCTUnwrap(list.first { $0.title == "Free space: Disk is low: 9.2 GB free" })
        XCTAssertEqual(sweep.detail, "teyla storage sweep")
        XCTAssertTrue(sweep.changesState)
        let tools = list.filter { if case .tool = $0.kind { return true } else { return false } }
        XCTAssertEqual(tools.count, 4)
        let refresh = try XCTUnwrap(tools.first { $0.detail == "teyla portfolio --refresh" })
        XCTAssertFalse(refresh.changesState)
    }

    func testAnActionTheAllowListRefusesIsNotOffered() {
        let item = AttentionItem(id: "x", kind: "disk", title: "T",
                                 actions: [ToolAction(label: "Deploy", command: ["deploy", "now"]), ToolAction(label: "Forget", command: ["schedules", "forget", "a"])])
        let list = CommandBar.entries(products: [], report: AttentionReport(items: [item]), capabilities: .full)
        XCTAssertEqual(list.filter { if case .tool = $0.kind { return true } else { return false } }.count, 1)
        XCTAssertFalse(list.contains { $0.title.contains("Deploy") })
    }

    func testAProductWithoutAUsableIdIsLeftOut() {
        let list = CommandBar.entries(products: [(id: "(none)", name: "(none)"), (id: "-x", name: "-x"), (id: "ok", name: "ok")], report: nil, capabilities: .full)
        XCTAssertEqual(list.filter { $0.id.hasPrefix("product:") }.map(\.id), ["product:ok"])
    }

    func testPlainMatching() {
        let list = entries()
        XCTAssertEqual(CommandBar.filter(list, query: "").count, list.count)
        XCTAssertEqual(CommandBar.filter(list, query: "dec").first?.id, "go:decisions")
        XCTAssertEqual(CommandBar.filter(list, query: "TOOLS").first?.id, "go:operations")
        XCTAssertEqual(CommandBar.filter(list, query: "cash").first?.id, "go:money")
        XCTAssertEqual(CommandBar.filter(list, query: "sample-t").map(\.id), ["product:sample-tool"])
        XCTAssertEqual(CommandBar.filter(list, query: "new").first?.id, "new-task")
        XCTAssertEqual(CommandBar.filter(list, query: "all prod").first?.id, "go:portfolio")
        XCTAssertTrue(CommandBar.filter(list, query: "zzz").isEmpty)
        XCTAssertTrue(CommandBar.filter(list, query: "delete everything").isEmpty)
    }

    func testAKeywordFindsAnEntryButAWordInTheTitleRanksFirst() {
        let list = entries()
        XCTAssertEqual(CommandBar.filter(list, query: "reload").map(\.id), ["refresh"])
        // "home" starts the title word of Home; "core" is only a keyword of it.
        XCTAssertEqual(CommandBar.filter(list, query: "core").map(\.id), ["go:home"])
    }

    func testAnActionIsFoundByItsLabelOrItsItem() throws {
        let list = entries(report: try report())
        XCTAssertEqual(CommandBar.filter(list, query: "forget old").first?.detail, "teyla schedules forget claude-desktop:old-digest")
        XCTAssertEqual(CommandBar.filter(list, query: "sweep").map(\.detail), ["teyla storage sweep"])     // found by its command too
        XCTAssertEqual(CommandBar.filter(list, query: "free space").count, 1)
    }

    func testTheHighlightStopsAtTheEnds() {
        XCTAssertEqual(CommandBar.moved(0, by: -1, count: 5), 0)
        XCTAssertEqual(CommandBar.moved(4, by: 1, count: 5), 4)
        XCTAssertEqual(CommandBar.moved(1, by: 1, count: 5), 2)
        XCTAssertEqual(CommandBar.moved(3, by: 1, count: 0), 0)
        XCTAssertEqual(CommandBar.clamped(9, count: 3), 2)
        XCTAssertEqual(CommandBar.clamped(-2, count: 3), 0)
    }
}

/// A backend that answers from memory: the Tools model's steps run against it with no process and no fixture sleep.
private final class StubBackend: TeylaBackend, @unchecked Sendable {
    private struct State {
        var ran: [[String]] = []
        var reports: [AttentionReport]
        var failRead = false
        var failRun: String?
    }

    private let box: OSAllocatedUnfairLock<State>

    init(reports: [AttentionReport]) { box = OSAllocatedUnfairLock(initialState: State(reports: reports)) }

    var usesFixture: Bool { false }
    var commands: [[String]] { box.withLock { $0.ran } }
    var failRead: Bool {
        get { box.withLock { $0.failRead } }
        set { box.withLock { $0.failRead = newValue } }
    }
    var failRun: String? {
        get { box.withLock { $0.failRun } }
        set { box.withLock { $0.failRun = newValue } }
    }

    func attention() async throws -> AttentionReport {
        let (fail, next) = box.withLock { s -> (Bool, AttentionReport) in
            (s.failRead, s.reports.count > 1 ? s.reports.removeFirst() : s.reports[0])
        }
        if fail { throw TeylaError.failed(code: 1, message: "attention failed") }
        return next
    }

    func runTool(_ argv: [String]) async throws -> String {
        let fail = box.withLock { s -> String? in
            s.ran.append(argv)
            return s.failRun
        }
        if let fail { throw TeylaError.failed(code: 1, message: fail) }
        return argv.last == "--dry" ? "would remove 3 items" : "removed 3 items"
    }

    func state() async throws -> Snapshot { throw TeylaError.unavailable("stub") }
    func answer(id: String, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func say(ref: String, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func dispatch(product: String, harness: Harness, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func productPage(id: String, quick: Bool) async throws -> ProductPageData { throw TeylaError.unavailable("stub") }
    func binaryPath() async -> String? { "stub" }
}

@MainActor
final class ToolsModelTests: XCTestCase {
    private func until(_ what: String, _ condition: @MainActor () -> Bool) async throws {
        for _ in 0..<200 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("timed out waiting for \(what)")
    }

    private func sweepItem() -> AttentionItem {
        AttentionItem(id: "disk:free", kind: "disk", title: "Disk is low", actions: [
            ToolAction(label: "Free space", command: ["storage", "sweep"], preview: ["storage", "sweep", "--dry"], destructive: true)])
    }

    func testTheFirstReadFillsTheReportAndTheBadge() async throws {
        let backend = StubBackend(reports: [AttentionReport(items: [sweepItem(), AttentionItem(id: "o", kind: "offer", title: "Offer", severity: "info")])])
        let model = ToolsModel(cli: backend)
        XCTAssertNil(model.badge)
        model.refresh()
        try await until("the report") { model.phase == .ready }
        XCTAssertEqual(model.badge, "1")
        XCTAssertEqual(model.report?.items.count, 2)
    }

    func testAFailedReadShowsABangAndKeepsTheLastReport() async throws {
        let backend = StubBackend(reports: [AttentionReport(items: [sweepItem()])])
        let model = ToolsModel(cli: backend)
        model.refresh()
        try await until("the report") { model.phase == .ready }
        backend.failRead = true
        model.refresh()
        try await until("the failure") { model.failure != nil }
        XCTAssertEqual(model.badge, "!")
        XCTAssertNotNil(model.report)
        XCTAssertEqual(model.failure, "attention failed")
    }

    func testAnActionGoesPreviewThenConfirmThenRunThenReadsAgain() async throws {
        let item = sweepItem()
        let backend = StubBackend(reports: [AttentionReport(items: [item]), AttentionReport(items: [])])
        let model = ToolsModel(cli: backend)
        var changed = 0
        model.changed = { changed += 1 }
        model.refresh()
        try await until("the report") { model.phase == .ready }
        let action = try XCTUnwrap(item.actions.first)

        model.begin(item: item, action: action)
        try await until("the preview") { if case .preview = model.run(for: item, action: action) { return true } else { return false } }
        XCTAssertEqual(backend.commands, [["storage", "sweep", "--dry"]])         // only the dry run so far
        XCTAssertEqual(model.run(for: item, action: action), .preview("would remove 3 items"))

        model.confirm(item: item, action: action)
        try await until("the result") { model.notice != nil }
        XCTAssertEqual(backend.commands, [["storage", "sweep", "--dry"], ["storage", "sweep"]])
        XCTAssertEqual(changed, 1)
        try await until("the second read") { model.report?.items.isEmpty == true }
        XCTAssertTrue(model.notice?.contains("teyla storage sweep") == true)
        XCTAssertTrue(model.runs.isEmpty)                                          // the card is gone, so is its step
    }

    func testConfirmDoesNothingBeforeAPreviewPrinted() async throws {
        let item = sweepItem()
        let backend = StubBackend(reports: [AttentionReport(items: [item])])
        let model = ToolsModel(cli: backend)
        let action = try XCTUnwrap(item.actions.first)
        model.confirm(item: item, action: action)
        model.begin(item: item, action: action)
        model.confirm(item: item, action: action)                                   // still previewing
        try await until("the preview") { if case .preview = model.run(for: item, action: action) { return true } else { return false } }
        XCTAssertEqual(backend.commands, [["storage", "sweep", "--dry"]])
    }

    func testCancelLeavesNothingRunning() async throws {
        let item = AttentionItem(id: "s", kind: "schedule", title: "Gone", actions: [ToolAction(label: "Forget", command: ["schedules", "forget", "a:b"], destructive: true)])
        let backend = StubBackend(reports: [AttentionReport(items: [item])])
        let model = ToolsModel(cli: backend)
        let action = try XCTUnwrap(item.actions.first)
        model.begin(item: item, action: action)
        XCTAssertEqual(model.run(for: item, action: action), .confirming)
        model.cancel(item: item, action: action)
        XCTAssertNil(model.run(for: item, action: action))
        XCTAssertTrue(backend.commands.isEmpty)
    }

    func testARefusedCommandNeverReachesTheBackend() async throws {
        let item = AttentionItem(id: "x", kind: "disk", title: "T", actions: [ToolAction(label: "Deploy", command: ["deploy", "now"])])
        let backend = StubBackend(reports: [AttentionReport(items: [item])])
        let model = ToolsModel(cli: backend)
        let action = try XCTUnwrap(item.actions.first)
        model.begin(item: item, action: action)
        guard case .refused = model.run(for: item, action: action) else { return XCTFail("not refused") }
        model.confirm(item: item, action: action)
        XCTAssertTrue(backend.commands.isEmpty)
    }

    func testAFailedRunShowsItsMessageAndDoesNotRefreshAsIfFine() async throws {
        let item = AttentionItem(id: "s", kind: "schedule", title: "Gone", actions: [ToolAction(label: "Forget", command: ["schedules", "forget", "a:b"], destructive: true)])
        let backend = StubBackend(reports: [AttentionReport(items: [item])])
        backend.failRun = "task still exists"
        let model = ToolsModel(cli: backend)
        let action = try XCTUnwrap(item.actions.first)
        model.begin(item: item, action: action)
        model.confirm(item: item, action: action)
        try await until("the failure") { if case .failed = model.run(for: item, action: action) { return true } else { return false } }
        XCTAssertEqual(model.run(for: item, action: action), .failed("task still exists"))
        XCTAssertNil(model.notice)
    }

    func testTheReadOnlyRefreshRunsAtOnceAndNeedsNoConfirm() async throws {
        let item = AttentionItem(id: "u", kind: "unknown", title: "Never read", severity: "info", actions: [ToolAction(label: "Check now", command: ["portfolio", "--refresh"], destructive: false)])
        let backend = StubBackend(reports: [AttentionReport(items: [item])])
        let model = ToolsModel(cli: backend)
        let action = try XCTUnwrap(item.actions.first)
        model.begin(item: item, action: action)
        try await until("the run") { !backend.commands.isEmpty }
        XCTAssertEqual(backend.commands, [["portfolio", "--refresh"]])
    }

    func testTheStoreBackendHasNoTools() async {
        struct NoTools: TeylaBackend {
            var usesFixture: Bool { false }
            func state() async throws -> Snapshot { throw TeylaError.unavailable("x") }
            func answer(id: String, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("x") }
            func say(ref: String, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("x") }
            func dispatch(product: String, harness: Harness, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("x") }
            func productPage(id: String, quick: Bool) async throws -> ProductPageData { throw TeylaError.unavailable("x") }
            func binaryPath() async -> String? { nil }
        }
        let backend = NoTools()
        do { _ = try await backend.attention(); XCTFail("read") } catch { XCTAssertTrue(error is TeylaError) }
        do { _ = try await backend.runTool(["storage", "sweep"]); XCTFail("ran") } catch { XCTAssertTrue(error is TeylaError) }
        XCTAssertFalse(Capabilities.store.tools)
        XCTAssertTrue(Capabilities.full.tools)
        XCTAssertFalse(Capabilities.store.console)
        XCTAssertTrue(Capabilities.full.console)
    }
}

final class ToolsFixtureBackendTests: XCTestCase {
    private func cli() -> TeylaCLI {
        TeylaCLI(env: ["TEYLA_STATE_FIXTURE": SampleFiles.url("state.sample.home.json").path], home: "/nonexistent")
    }

    func testTheFixtureBackendReadsTheSampleBesideTheState() async throws {
        let r = try await cli().attention()
        XCTAssertEqual(r.items.count, 7)
    }

    func testTheFixtureBackendRunsNothingAndRefusesWhatIsNotListed() async throws {
        let backend = cli()
        let preview = try await backend.runTool(["storage", "sweep", "--dry"])
        XCTAssertTrue(preview.hasPrefix("Simulated preview"))
        let ran = try await backend.runTool(["schedules", "forget", "claude-desktop:old-digest"])
        XCTAssertTrue(ran.hasPrefix("Simulated"))
        do {
            _ = try await backend.runTool(["testflight", "release"])
            XCTFail("a command that is not listed was accepted")
        } catch let error as TeylaError {
            guard case .failed(let code, _) = error else { return XCTFail("\(error)") }
            XCTAssertEqual(code, 2)
        }
    }

    func testTheAttentionCommandLine() {
        XCTAssertEqual(TeylaCLI.attentionArguments, ["attention", "--json"])
    }
}

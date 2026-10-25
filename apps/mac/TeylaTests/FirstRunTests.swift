import XCTest

/// The JSON samples in Fixtures/ come from the real CLI (Tools/make_fixtures.py), run on a made-up HOME.
enum SampleFiles {
    static var directory: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().appendingPathComponent("Fixtures")
    }

    static func url(_ name: String) -> URL { directory.appendingPathComponent(name) }

    static func data(_ name: String) throws -> Data { try Data(contentsOf: url(name)) }
}

final class StartReportTests: XCTestCase {
    private func report() throws -> StartReport { try StartDecoding.decode(SampleFiles.data("start.v1.json")) }

    func testDecodesTheDiagnosis() throws {
        let d = try report().diagnosis
        XCTAssertFalse(d.empty)
        XCTAssertEqual(d.days, 30)
        XCTAssertGreaterThan(d.totalUSD, 0)
        XCTAssertEqual(d.sessions, 3)
        XCTAssertEqual(d.scope, "3 sessions on 1 day")
        XCTAssertTrue(d.lines.contains { $0.contains("re-reading and storing context") })
        XCTAssertTrue(d.lines.contains { $0.hasPrefix("3 sessions ran past 250k tokens") })
    }

    func testSplitsOffersByWhetherTheyApply() throws {
        let r = try report()
        XCTAssertEqual(r.offers.count, 7)
        XCTAssertEqual(r.applicable.map(\.id), ["O1", "O2", "O3", "O5", "O6", "O7"])
        XCTAssertEqual(r.skipped.map(\.id), ["O4"])
        XCTAssertFalse(r.skipped[0].reason.isEmpty)
    }

    func testAnOfferWithASaving() throws {
        let o1 = try XCTUnwrap(report().offers.first { $0.id == "O1" })
        XCTAssertTrue(o1.hasSaving)
        XCTAssertTrue(o1.gain.hasPrefix("About $"), o1.gain)
        XCTAssertTrue(o1.gain.hasSuffix("a month at API list price"), o1.gain)
        XCTAssertFalse(o1.tradeoff.isEmpty)
        XCTAssertTrue(o1.undo.contains("teyla undo O1"))
        XCTAssertFalse(o1.undoIsUninstall)
        XCTAssertEqual(o1.change.kind, "json")
        XCTAssertEqual(o1.change.key, "autoCompactWindow")
    }

    func testTheConfirmTextNamesTheFileAndTheKey() throws {
        let o1 = try XCTUnwrap(report().offers.first { $0.id == "O1" })
        XCTAssertEqual(o1.willChange, "Teyla will change autoCompactWindow in ~/.claude/settings.json.")
        XCTAssertTrue(o1.safety.hasPrefix("Teyla copies the file to a backup first."))
        XCTAssertTrue(o1.safety.contains("teyla undo O1"))
    }

    func testAnOfferWhoseUndoIsUninstallSaysSo() throws {
        let o5 = try XCTUnwrap(report().offers.first { $0.id == "O5" })
        XCTAssertEqual(o5.change.kind, "command")
        XCTAssertTrue(o5.undoIsUninstall)
        XCTAssertEqual(o5.willChange, "Teyla will run teyla policy sync.")
        XCTAssertTrue(o5.safety.contains("teyla uninstall"))
        XCTAssertFalse(o5.hasSaving)
        XCTAssertEqual(o5.gain, o5.benefit)
        XCTAssertFalse(o5.gain.isEmpty)
    }

    func testAnEmptyMachine() throws {
        let r = try StartDecoding.decode(SampleFiles.data("start.empty.v1.json"))
        XCTAssertTrue(r.diagnosis.empty)
        XCTAssertEqual(r.diagnosis.totalUSD, 0)
    }

    func testAnUnreadableAnswerIsAnError() {
        XCTAssertThrowsError(try StartDecoding.decode(Data("not json".utf8))) { error in
            XCTAssertEqual(error as? TeylaError, .badOutput("not a diagnosis"))
        }
    }

    func testUnknownFieldsAndBrokenOffersAreIgnored() throws {
        let json = #"{"summary_text": "x", "extra": 1, "offers": [{"id": "O9", "title": "T", "applies": true, "new_field": 2}, {"title": "no id"}]}"#
        let r = try StartDecoding.decode(Data(json.utf8))
        XCTAssertEqual(r.offers.map(\.id), ["O9"])
        XCTAssertTrue(r.diagnosis.empty)
    }

    func testAppliedLinesAreTheOnesAfterChanged() {
        let out = "Applied O1.\nChanged:\n  ~/.claude/settings.json: autoCompactWindow = 335000\nBackup: ~/.claude/settings.json.teyla-bak-1\n"
        XCTAssertEqual(StartDecoding.appliedLines(out), "~/.claude/settings.json: autoCompactWindow = 335000\nBackup: ~/.claude/settings.json.teyla-bak-1")
        XCTAssertEqual(StartDecoding.appliedLines("Done.\n"), "Done.")
    }
}

final class ApplyArgumentsTests: XCTestCase {
    func testApplyAsksNothingMore() {
        XCTAssertEqual(FirstRun.applyArguments(offerID: "O1"), ["apply", "O1", "--yes"])
        XCTAssertEqual(FirstRun.startArguments, ["start", "--json"])
    }

    func testOnlyOfferIDsReachTheCommandLine() {
        XCTAssertTrue(FirstRun.isOfferID("O1"))
        XCTAssertTrue(FirstRun.isOfferID("O12"))
        for bad in ["", "O", "o1", "--yes", "O1 ; rm", "1", "O-1"] {
            XCTAssertFalse(FirstRun.isOfferID(bad), bad)
        }
    }

    func testTheProductCommands() {
        XCTAssertEqual(ProductCommands.showArguments(id: "sample-app", quick: false), ["product", "show", "sample-app", "--json"])
        XCTAssertEqual(ProductCommands.showArguments(id: "sample-app", quick: true), ["product", "show", "sample-app", "--json", "--quick"])
        XCTAssertEqual(ProductCommands.stageArguments(id: "sample-app", stage: .live), ["product", "set", "sample-app", "stage=live"])
        XCTAssertEqual(ProductCommands.stageArguments(id: "sample-app", stage: .parked), ["product", "set", "sample-app", "stage=parked"])
        XCTAssertEqual(ProductCommands.focusArguments(id: "sample-app", focus: true), ["product", "set", "sample-app", "focus=true"])
        XCTAssertEqual(ProductCommands.focusArguments(id: "sample-app", focus: false), ["product", "set", "sample-app", "focus=false"])
    }

    func testOnlyProductIDsReachTheCommandLine() {
        XCTAssertTrue(ProductCommands.isProductID("sample-app"))
        XCTAssertTrue(ProductCommands.isProductID("unassigned"))
        for bad in ["", "-x", "--json", "two words"] {
            XCTAssertFalse(ProductCommands.isProductID(bad), bad)
        }
    }

    func testEveryStageHasATitle() {
        XCTAssertEqual(ProductStage.allCases.map(\.rawValue), ["idea", "building", "beta", "live", "parked"])
        XCTAssertEqual(ProductStage.beta.title, "Beta")
    }
}

final class ProductPageDecodingTests: XCTestCase {
    func testDecodesTheFullPage() throws {
        let page = try ProductPageData.decode(SampleFiles.data("product.v1.json"))
        XCTAssertEqual(page.version, 1)
        XCTAssertEqual(page.product.id, "sample-app")
        XCTAssertEqual(page.product.name, "Sample App")
        XCTAssertEqual(page.product.stageValue, .beta)
        XCTAssertTrue(page.product.focus)
        XCTAssertEqual(page.product.primary, "ios")
        XCTAssertTrue(page.product.registered)
        XCTAssertEqual(page.asks.count, 1)
        XCTAssertFalse(page.asks[0].critical)
        XCTAssertTrue(page.asks[0].question.hasSuffix("?"))
        XCTAssertEqual(page.notes.map(\.text), ["Dark mode for the settings screen"])
        let sessions = try XCTUnwrap(page.sessions)
        XCTAssertEqual(sessions.count, 2)
        XCTAssertEqual(sessions[0].title, "Fix the settings crash")
        XCTAssertEqual(sessions[0].harness, "claude-code")
        XCTAssertEqual(sessions[0].modelName, "Opus")
        XCTAssertNotNil(sessions[0].date)
        let spend = try XCTUnwrap(page.spend)
        XCTAssertEqual(spend.days7, sessions.map(\.costUSD).reduce(0, +), accuracy: 0.011)
        XCTAssertGreaterThanOrEqual(spend.days30, spend.days7)
    }

    func testAQuickPageHasNoSessionsAndNoSpend() throws {
        let json = #"{"version": 1, "generated": "2026-10-25T09:00:00Z", "product": {"id": "p", "name": "P"}, "asks": [], "notes": [], "sessions": null, "spend": null}"#
        let page = try ProductPageData.decode(Data(json.utf8))
        XCTAssertNil(page.sessions)
        XCTAssertNil(page.spend)
        XCTAssertEqual(page.product.stage, "")
    }

    func testACriticalAsk() throws {
        let json = #"{"product": {"id": "p"}, "asks": [{"id": "a1", "severity": "critical", "age_s": 90, "question": "Q?"}]}"#
        let page = try ProductPageData.decode(Data(json.utf8))
        XCTAssertTrue(page.asks[0].critical)
        XCTAssertEqual(page.asks[0].ageSeconds, 90)
        XCTAssertEqual(page.product.name, "P")
    }

    func testANoteBecomesTheSameRowTheNotesSectionUses() throws {
        let page = try ProductPageData.decode(SampleFiles.data("product.v1.json"))
        let item = page.notes[0].item(product: "sample-app")
        XCTAssertEqual(item.product, "sample-app")
        XCTAssertFalse(item.isInbox)
        XCTAssertEqual(item.text, "Dark mode for the settings screen")
    }

    func testAnUnreadablePageIsAnError() {
        XCTAssertThrowsError(try ProductPageData.decode(Data("{}".utf8))) { error in
            XCTAssertEqual(error as? TeylaError, .badOutput("not a product page"))
        }
    }
}

final class RegistryInSnapshotTests: XCTestCase {
    func testTheStateSampleCarriesTheRegistry() throws {
        let snapshot = try TeylaCLI.decodeSnapshot(SampleFiles.data("state.sample.v2.json"))
        let app = try XCTUnwrap(snapshot.products.first { $0.name == "sample-app" })
        XCTAssertEqual(app.title, "Sample App")
        XCTAssertEqual(app.stage, "beta")
        XCTAssertTrue(app.focus)
        XCTAssertEqual(app.primary, "ios")
        XCTAssertTrue(app.registered)
        XCTAssertTrue(app.hasPage)
        XCTAssertFalse(snapshot.isEmpty)
    }

    func testABareRepoHasNoPageButUnassignedHasOne() {
        XCTAssertFalse(Product(name: "scratch-repo").hasPage)
        XCTAssertTrue(Product(name: "unassigned").hasPage)
        XCTAssertTrue(Product(name: "p", registered: true).hasPage)
        XCTAssertEqual(Product(name: "wine-cellar").title, "Wine Cellar")
    }

    func testAnEmptySnapshot() throws {
        XCTAssertTrue(try TeylaCLI.decodeSnapshot(SampleFiles.data("state.empty.v1.json")).isEmpty)
        XCTAssertFalse(Snapshot(asks: [Ask(id: "a")]).isEmpty)
        XCTAssertFalse(Snapshot(products: [Product(name: "p")]).isEmpty)
    }

    func testTheWelcomeShowsAloneUntilADiagnosisIsReady() throws {
        let empty = try TeylaCLI.decodeSnapshot(SampleFiles.data("state.empty.v1.json"))
        let busy = Snapshot(asks: [Ask(id: "a")])
        let report = StartReport()
        XCTAssertTrue(Shell.showsWelcomeOnly(snapshot: empty, diagnosis: .idle, teylaMissing: false))
        XCTAssertTrue(Shell.showsWelcomeOnly(snapshot: empty, diagnosis: .running, teylaMissing: false))
        XCTAssertTrue(Shell.showsWelcomeOnly(snapshot: empty, diagnosis: .failed("x"), teylaMissing: false))
        XCTAssertFalse(Shell.showsWelcomeOnly(snapshot: empty, diagnosis: .ready(report), teylaMissing: false))
        XCTAssertFalse(Shell.showsWelcomeOnly(snapshot: busy, diagnosis: .idle, teylaMissing: false))
        XCTAssertFalse(Shell.showsWelcomeOnly(snapshot: nil, diagnosis: .idle, teylaMissing: false))
        XCTAssertFalse(Shell.showsWelcomeOnly(snapshot: empty, diagnosis: .idle, teylaMissing: true))
    }
}

final class BinarySearchOrderTests: XCTestCase {
    func testTheChosenFileComesFirstThenTheLoginShellThenTheFixedPaths() {
        let list = TeylaBinary.candidates(env: ["TEYLA_BIN": "/env/teyla"], home: "/h", chosen: "/picked/teyla", shellPath: "/shell/teyla")
        XCTAssertEqual(list, ["/picked/teyla", "/env/teyla", "/shell/teyla",
                             "/h/.local/bin/teyla", "/opt/homebrew/bin/teyla", "/usr/local/bin/teyla"])
    }

    func testTheChosenFileWinsWhenItRuns() {
        var asked = false
        let found = TeylaBinary.locate(env: [:], home: "/h", chosen: "/picked/teyla",
                                       shellPath: { asked = true; return "/shell/teyla" }, isExecutable: { _ in true })
        XCTAssertEqual(found, "/picked/teyla")
        XCTAssertFalse(asked, "the login shell is not started when the owner already named the file")
    }

    func testAChosenFileThatIsGoneFallsThroughToTheShell() {
        let found = TeylaBinary.locate(env: [:], home: "/h", chosen: "/picked/teyla",
                                       shellPath: { "/shell/teyla" }, isExecutable: { $0 == "/shell/teyla" })
        XCTAssertEqual(found, "/shell/teyla")
    }

    func testTheShellBeatsTheFixedPaths() {
        let found = TeylaBinary.locate(env: [:], home: "/h", shellPath: { "/nix/teyla" },
                                       isExecutable: { $0 == "/nix/teyla" || $0 == "/opt/homebrew/bin/teyla" })
        XCTAssertEqual(found, "/nix/teyla")
    }

    func testTheFixedPathsAreTheLastResort() {
        let found = TeylaBinary.locate(env: [:], home: "/h", shellPath: { nil },
                                       isExecutable: { $0 == "/usr/local/bin/teyla" })
        XCTAssertEqual(found, "/usr/local/bin/teyla")
        XCTAssertNil(TeylaBinary.locate(env: [:], home: "/h", shellPath: { nil }, isExecutable: { _ in false }))
    }

    func testTheShellAnswerIsOnlyAnAbsolutePath() {
        XCTAssertEqual(TeylaBinary.parseShellOutput("/opt/example/.local/bin/teyla\n"), "/opt/example/.local/bin/teyla")
        XCTAssertEqual(TeylaBinary.parseShellOutput("Last login...\n/opt/bin/teyla\n"), "/opt/bin/teyla")
        XCTAssertNil(TeylaBinary.parseShellOutput("alias teyla='uv run teyla'\n"))
        XCTAssertNil(TeylaBinary.parseShellOutput(""))
        XCTAssertNil(TeylaBinary.parseShellOutput("teyla not found\n"))
    }

    func testTheChosenPathIsStoredAndForgotten() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "teyla-tests-\(UUID().uuidString)"))
        XCTAssertNil(TeylaBinary.chosenPath(defaults: defaults))
        TeylaBinary.choose("/picked/teyla", defaults: defaults)
        XCTAssertEqual(TeylaBinary.chosenPath(defaults: defaults), "/picked/teyla")
        TeylaBinary.choose(nil, defaults: defaults)
        XCTAssertNil(TeylaBinary.chosenPath(defaults: defaults))
    }

    func testTheInstallCommandIsExact() {
        XCTAssertEqual(TeylaBinary.installCommand, "uv tool install git+https://github.com/zaitsew/teyla")
    }
}

final class FirstRunFixtureModeTests: XCTestCase {
    private func cli(_ extra: [String: String] = [:]) -> TeylaCLI {
        var env = ["TEYLA_STATE_FIXTURE": SampleFiles.url("state.sample.v2.json").path, "TEYLA_PREVIEW_START_DELAY": "0"]
        env.merge(extra) { $1 }
        return TeylaCLI(env: env, home: "/nonexistent", chosen: { nil }, shellPath: { nil })
    }

    func testTheDiagnosisComesFromTheSampleBesideTheState() async throws {
        let report = try await cli().start()
        XCTAssertEqual(report.offers.count, 7)
    }

    func testApplyIsSimulatedAndRefusesABadID() async throws {
        let lines = try await cli().apply(offerID: "O1")
        XCTAssertTrue(lines.hasPrefix("Simulated"))
        do {
            _ = try await cli().apply(offerID: "--yes")
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? TeylaError, .failed(code: 2, message: "--yes is not an offer id."))
        }
    }

    func testTheProductPageComesFromTheSampleAndQuickLeavesOutTheSessions() async throws {
        let full = try await cli().productPage(id: "sample-app", quick: false)
        XCTAssertEqual(full.sessions?.count, 2)
        let quick = try await cli().productPage(id: "sample-app", quick: true)
        XCTAssertNil(quick.sessions)
        XCTAssertNil(quick.spend)
        XCTAssertEqual(quick.notes.count, 1)
    }

    func testSettingTheStageAndFocusIsSimulated() async throws {
        try await cli().setStage(id: "sample-app", stage: .live)
        try await cli().setFocus(id: "sample-app", focus: false)
        do {
            try await cli().setStage(id: "-bad", stage: .live)
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? TeylaError, .failed(code: 2, message: "-bad is not a product id."))
        }
    }

    func testThePreviewCanPretendTheCommandIsMissing() async {
        let missing = cli(["TEYLA_PREVIEW_NO_BINARY": "1"])
        do {
            _ = try await missing.state()
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? TeylaError, .binaryNotFound)
        }
        let found = await missing.binaryPath()
        XCTAssertNil(found)
        let present = await cli().binaryPath()
        XCTAssertNotNil(present)
    }
}

final class ReviewFixTests: XCTestCase {
    func testAFailedOfferCanBeAskedAgain() {
        XCTAssertTrue(OfferStatus.allowsConfirmation(nil))
        XCTAssertTrue(OfferStatus.allowsConfirmation(.failed("no")))
        XCTAssertFalse(OfferStatus.allowsConfirmation(.applying))
        XCTAssertFalse(OfferStatus.allowsConfirmation(.applied("done")))
    }

    func testAWriteForAnotherProductLeavesThePageAlone() {
        var page = ProductPageData(product: ProductHeader(id: "b", stage: "idea"))
        let applied = page.applyWrite(to: "a") { $0.stage = "live" }
        XCTAssertFalse(applied)
        XCTAssertEqual(page.product.stage, "idea")
    }

    func testAWriteForThisProductChangesIt() {
        var page = ProductPageData(product: ProductHeader(id: "a", stage: "idea"))
        XCTAssertTrue(page.applyWrite(to: "a") { $0.focus = true })
        XCTAssertTrue(page.product.focus)
    }

    func testTheNotesFollowTheWindowListOnceItIsRead() {
        let first = ProductNote(id: "n1", text: "old")
        let list = [
            NoteItem(id: "n2", text: "added later", product: "a"),
            NoteItem(id: "n1", text: "old", product: "a"),
            NoteItem(id: "n3", text: "elsewhere", product: "b"),
            NoteItem(id: "n4", text: "gone", product: "a", dropped: true),
        ]
        let shown = ProductNotes.shown(productID: "a", page: [first], list: list, listLoaded: true)
        XCTAssertEqual(shown.map(\.id), ["n2", "n1"])
    }

    func testTheNotesFallBackToThePageBeforeTheListIsRead() {
        let shown = ProductNotes.shown(productID: "a", page: [ProductNote(id: "n1", text: "x")], list: [], listLoaded: false)
        XCTAssertEqual(shown.map(\.id), ["n1"])
        XCTAssertEqual(shown.first?.product, "a")
    }

    func testALinkedNoteLeavesThePage() {
        let list = [NoteItem(id: "n1", text: "x", product: "b")]
        XCTAssertTrue(ProductNotes.shown(productID: "a", page: [ProductNote(id: "n1")], list: list, listLoaded: true).isEmpty)
    }
}

import XCTest
import os

private func decodeProduct(_ json: String) throws -> PortfolioProduct {
    try JSONDecoder().decode(PortfolioProduct.self, from: Data(json.utf8))
}

private func sampleBlock() throws -> StartupBlock {
    let snapshot = try JSONDecoder().decode(Snapshot.self, from: SampleFiles.data("state.sample.v3.json"))
    return try XCTUnwrap(snapshot.portfolio?.product("sample-app")?.startup)
}

final class StartupDecodeTests: XCTestCase {
    func testTheSampleProductCarriesItsStageLadderAndMetrics() throws {
        let block = try sampleBlock()
        XCTAssertEqual(block.stage, "built")
        XCTAssertEqual(block.stageTitle, "Built")
        XCTAssertEqual(block.type, "venture")
        XCTAssertFalse(block.typeSet)
        XCTAssertEqual(block.next?.rung, "tried")
        XCTAssertEqual(block.rungs.map(\.id), ["built", "tried", "used", "retained", "paid", "repeating", "growing"])
        XCTAssertEqual(block.rungs.map(\.status), ["met", "missing", "met", "missing", "not_applicable", "not_applicable", "unknown"])
        XCTAssertEqual(block.metrics.usage.external, 24)
        XCTAssertTrue(block.metrics.usage.externalAssumed)
        XCTAssertNil(block.metrics.money.paying)
        XCTAssertEqual(block.metrics.money.aiCost30dUSD, 12.5)
        XCTAssertNil(block.metrics.growth.weeklyPct)
        XCTAssertEqual(block.yc, StartupYCSummary(eligible: true, checked: 3, total: 15, nextBox: "customer"))
    }

    func testAProductWithNoBlockOrANullBlockStillDecodes() throws {
        let snapshot = try JSONDecoder().decode(Snapshot.self, from: SampleFiles.data("state.sample.v3.json"))
        let tool = try XCTUnwrap(snapshot.portfolio?.product("sample-tool"))
        XCTAssertNil(tool.startup)
        let old = try XCTUnwrap(snapshot.portfolio?.product("sample-old"))
        XCTAssertNil(old.startup)
        XCTAssertNil(try decodeProduct(#"{"id": "x", "startup": null}"#).startup)
    }

    func testABlockWithoutATypeIsAbsentNotGuessed() throws {
        XCTAssertNil(try decodeProduct(#"{"id": "x", "startup": {"stage": "built"}}"#).startup)
        XCTAssertNil(try decodeProduct(#"{"id": "x", "startup": "oops"}"#).startup)
    }

    func testAnUnknownFigureIsNilAndAnAbsentGroupIsAllUnknown() throws {
        let product = try decodeProduct(#"{"id": "x", "startup": {"type": "indie", "type_set": true, "stage": "none", "stage_title": "Not built"}}"#)
        let block = try XCTUnwrap(product.startup)
        XCTAssertNil(block.asOf)
        XCTAssertNil(block.next)
        XCTAssertTrue(block.rungs.isEmpty)
        XCTAssertNil(block.metrics.usage.external)
        XCTAssertNil(block.metrics.marketing.posts)
    }

    func testABadRungIsSkippedAndTheRestKept() throws {
        let product = try decodeProduct("""
        {"id": "x", "startup": {"type": "venture", "rungs": [{"title": "no id"}, {"id": "built", "title": "Built", "status": "met", "detail": "ok"}]}}
        """)
        XCTAssertEqual(product.startup?.rungs.map(\.id), ["built"])
    }
}

final class StartupTextTests: XCTestCase {
    private let now = ISODate.parse("2026-10-25T09:00:00Z")!

    func testTheSentenceIsTheNextFact() throws {
        let block = try sampleBlock()
        XCTAssertEqual(StartupText.sentence(block), "Nobody has tried to sell it yet.")
        XCTAssertEqual(StartupText.sentence(StartupBlock(next: nil)), "Every step of this ladder is met.")
    }

    func testATypeNobodyChoseIsSaidInWords() throws {
        var block = try sampleBlock()
        XCTAssertEqual(StartupText.typeWord(block), "Type not chosen")
        XCTAssertNotNil(StartupText.typeNote(block))
        block.typeSet = true
        XCTAssertEqual(StartupText.typeWord(block), "Venture")
        XCTAssertNil(StartupText.typeNote(block))
        XCTAssertEqual(StartupType.title(of: "open-source"), "Open source")
        XCTAssertEqual(StartupType.title(of: "studio"), "Studio")
    }

    func testTheAsOfTimeIsVisibleAndStaleIsSaid() throws {
        var block = try sampleBlock()
        XCTAssertEqual(StartupText.asOf(block, now: now), "Usage was read 1 h ago.")
        block.stale = true
        block.asOf = "2026-10-10T09:00:00Z"
        XCTAssertTrue(StartupText.asOf(block, now: now).contains("stale"))
        XCTAssertTrue(StartupText.asOf(block, now: now).contains("earn nothing"))
        block.asOf = nil
        block.stale = false
        XCTAssertTrue(StartupText.asOf(block, now: now).hasPrefix("No usage probe has reported"))
    }

    func testTheNextRungIsMarked() throws {
        let block = try sampleBlock()
        XCTAssertEqual(block.rungs.filter { StartupText.isNext($0, in: block) }.map(\.id), ["tried"])
    }

    func testAnUnknownFigureIsADashWithAReasonNeverZero() throws {
        let groups = StartupText.groups(try sampleBlock())
        let money = try XCTUnwrap(groups.first { $0.id == "money" })
        let payers = try XCTUnwrap(money.tiles.first { $0.label == "Payers" })
        XCTAssertNil(payers.value)
        XCTAssertEqual(payers.detail, "Monetization is off.")
        XCTAssertEqual(money.tiles.first { $0.label == "Charging" }?.value, "Off")
        XCTAssertEqual(money.tiles.first { $0.label == "AI cost, 30 days" }?.value, "$12.50")
        let growth = try XCTUnwrap(groups.first { $0.id == "growth" })
        XCTAssertNil(growth.tiles[0].value)
        XCTAssertEqual(growth.tiles[0].detail, "Needs 4 weeks of snapshots, has 0.")
        XCTAssertEqual(growth.tiles[1].value, "0")
    }

    func testAChargingProductWithNoProbeSaysNoProbe() {
        var block = StartupBlock()
        block.metrics.money = StartupMoney(enabled: true)
        let money = StartupText.groups(block).first { $0.id == "money" }
        let payers = money?.tiles.first { $0.label == "Payers" }
        XCTAssertNil(payers?.value)
        XCTAssertEqual(payers?.detail, "No usage probe reports this.")
    }

    func testRealZerosStayZeros() throws {
        let groups = StartupText.groups(try sampleBlock())
        let marketing = try XCTUnwrap(groups.first { $0.id == "marketing" })
        XCTAssertEqual(marketing.tiles.map(\.value), ["0", "0", "0"])
        XCTAssertEqual(marketing.tiles[0].detail, "Not tried yet.")
        XCTAssertFalse(groups.flatMap(\.tiles).contains { $0.detail.lowercased().contains("clos") })
    }

    func testAssumedOutsideCountsAreSaidInWords() throws {
        let usage = try XCTUnwrap(StartupText.groups(try sampleBlock()).first { $0.id == "usage" })
        let outside = try XCTUnwrap(usage.tiles.first { $0.label == "People outside" })
        XCTAssertEqual(outside.value, "24")
        XCTAssertEqual(outside.detail, "Assumed: accounts minus yours.")
    }

    func testAgentClaimsAreNamedAndNotCounted() throws {
        let sales = try XCTUnwrap(StartupText.groups(try sampleBlock()).first { $0.id == "sales" })
        XCTAssertEqual(sales.note, "1 attempt was logged by an agent and is not counted. Log it yourself to count it.")
        XCTAssertEqual(sales.tiles[0].value, "0")
        XCTAssertEqual(sales.tiles[2].value, "None yet")
        XCTAssertEqual(StartupText.claimed(0), "")
        XCTAssertTrue(StartupText.claimed(3).hasPrefix("3 attempts were logged by agents"))
    }

    func testAPersonalProductHasNoSaleGroups() {
        var block = StartupBlock(type: "personal")
        block.metrics.usage = StartupUsage(external: nil, wau: 1)
        let ids = StartupText.groups(block).map(\.id)
        XCTAssertEqual(ids, ["usage", "money", "growth"])
        XCTAssertEqual(StartupText.groups(StartupBlock()).map(\.id), ["marketing", "sales", "usage", "money", "growth"])
    }

    func testGrowthShowsASignedRate() {
        var block = StartupBlock()
        block.metrics.growth = StartupGrowth(weeklyPct: 6.25, weeks: 5, on: "revenue")
        let growth = StartupText.groups(block).first { $0.id == "growth" }
        XCTAssertEqual(growth?.tiles[0].value, "+6.2%")
        XCTAssertEqual(growth?.tiles[0].detail, "A week, on revenue, over 5 weeks.")
    }

    func testTheYCCountIsPlainAndNotAPercent() {
        XCTAssertEqual(StartupText.ycCount(StartupYCSummary(eligible: true, checked: 2, total: 15)), "2 of 15 boxes checked.")
    }

    func testCommandsAreArgvAndAnAnswerCannotBecomeAnOption() {
        XCTAssertEqual(StartupCommands.typeArguments(id: "a", type: .openSource), ["product", "set", "a", "type=open-source"])
        XCTAssertEqual(StartupCommands.sheetArguments(id: "a"), ["startup", "yc", "a", "--json"])
        XCTAssertEqual(StartupCommands.answerArguments(id: "a", box: "building", text: "--json x"),
                       ["startup", "yc", "--", "answer", "a", "building", "--json x"])
        XCTAssertTrue(StartupCommands.isBoxID("why_you"))
        XCTAssertFalse(StartupCommands.isBoxID("-x"))
        XCTAssertFalse(StartupCommands.isBoxID("a b"))
        XCTAssertFalse(StartupCommands.isBoxID(""))
    }

    func testTheFocusIsReadFromTheStartupReport() {
        XCTAssertEqual(StartupCommands.focus(from: Data(#"{"focus": "sample-app", "counts": {}}"#.utf8)), "sample-app")
        XCTAssertNil(StartupCommands.focus(from: Data(#"{"focus": null}"#.utf8)))
        XCTAssertNil(StartupCommands.focus(from: Data(#"{"focus": "-x"}"#.utf8)))
        XCTAssertNil(StartupCommands.focus(from: Data("not json".utf8)))
    }

    func testTheStoreBuildHasNoSheetAndTheFullAppHasOne() {
        XCTAssertTrue(Capabilities.full.startupSheet)
        XCTAssertFalse(Capabilities.store.startupSheet)
    }
}

final class YCSheetTests: XCTestCase {
    private func sheet() throws -> YCSheet { try YCSheet.decode(SampleFiles.data("yc.v1.json")) }

    func testTheSheetDecodesFifteenBoxesAndThreeChecked() throws {
        let sheet = try sheet()
        XCTAssertEqual(sheet.boxes.count, 15)
        XCTAssertEqual(sheet.checked, 3)
        XCTAssertEqual(YCText.count(sheet), "3 of 15")
        XCTAssertEqual(sheet.nextBox, "customer")
        XCTAssertFalse(YCText.canApply(sheet))
        XCTAssertEqual(YCText.lead(sheet), "Next: Pick one customer")
        XCTAssertEqual(sheet.facts.read, "2026-11-04")
        XCTAssertEqual(sheet.facts.lines.count, 4)
    }

    func testTheCountComesFromTheBoxesWhateverTheSummarySays() throws {
        var json = try XCTUnwrap(try JSONSerialization.jsonObject(with: SampleFiles.data("yc.v1.json")) as? [String: Any])
        json["checked"] = 15
        json["verdict"] = "apply"
        let sheet = try YCSheet.decode(JSONSerialization.data(withJSONObject: json))
        XCTAssertEqual(sheet.checked, 3)
        XCTAssertFalse(YCText.canApply(sheet))
    }

    func testApplyShowsOnlyWhenEveryBoxIsChecked() throws {
        var json = try XCTUnwrap(try JSONSerialization.jsonObject(with: SampleFiles.data("yc.v1.json")) as? [String: Any])
        var boxes = try XCTUnwrap(json["boxes"] as? [[String: Any]])
        for index in boxes.indices { boxes[index]["checked"] = true }
        json["boxes"] = boxes
        json["verdict"] = "apply"
        let sheet = try YCSheet.decode(JSONSerialization.data(withJSONObject: json))
        XCTAssertEqual(YCText.count(sheet), "15 of 15")
        XCTAssertTrue(YCText.canApply(sheet))
        XCTAssertEqual(YCText.applyURL.absoluteString, "https://www.ycombinator.com/apply")
        XCTAssertEqual(YCText.lead(sheet), "All boxes are checked. You can apply.")
    }

    func testAnUncheckedBoxIsNeverABar() {
        XCTAssertEqual(YCText.notABar, "An unchecked box does not mean you may not apply.")
        XCTAssertTrue(YCText.neverSubmits.contains("never submits"))
    }

    func testTheStatusOfABoxSaysWhatIsMissing() throws {
        let sheet = try sheet()
        func box(_ id: String) throws -> YCBox { try XCTUnwrap(sheet.boxes.first { $0.id == id }) }
        XCTAssertEqual(YCText.status(try box("building")), "Checked. You confirmed this answer.")
        XCTAssertEqual(YCText.status(try box("customer")), "A draft, not confirmed. It checks nothing yet.")
        XCTAssertEqual(YCText.status(try box("does")), "Needs: An answer.")
        XCTAssertTrue(YCText.status(try box("using")).hasPrefix("24 outside people"))
        XCTAssertEqual(YCText.status(try box("talked")), "Needs: One ICP conversation you logged yourself.")
    }

    func testThePlaceholderIsTheHintInTheCommand() throws {
        let sheet = try sheet()
        let does = try XCTUnwrap(sheet.boxes.first { $0.id == "does" })
        XCTAssertEqual(YCText.hint(for: does), "The job it does for that customer")
        XCTAssertEqual(YCText.hint(for: YCBox(id: "x")), "Your answer")
    }

    func testSavingNeedsRealNewTextAndADraftIsConfirmedBySavingItUnchanged() throws {
        let sheet = try sheet()
        let building = try XCTUnwrap(sheet.boxes.first { $0.id == "building" })
        let customer = try XCTUnwrap(sheet.boxes.first { $0.id == "customer" })
        let does = try XCTUnwrap(sheet.boxes.first { $0.id == "does" })
        let using = try XCTUnwrap(sheet.boxes.first { $0.id == "using" })
        XCTAssertFalse(YCText.canSave(does, draft: "   "))
        XCTAssertTrue(YCText.canSave(does, draft: "It plans trips."))
        XCTAssertFalse(YCText.canSave(does, draft: String(repeating: "a", count: StartupCommands.maxAnswer + 1)))
        XCTAssertFalse(YCText.canSave(building, draft: building.answer?.text ?? ""), "an unchanged confirmed answer has nothing to save")
        XCTAssertTrue(YCText.canSave(building, draft: "A different sentence."))
        XCTAssertTrue(YCText.canSave(customer, draft: customer.answer?.text ?? ""))
        XCTAssertEqual(YCText.saveLabel(customer, draft: customer.answer?.text ?? ""), "Confirm")
        XCTAssertEqual(YCText.saveLabel(customer, draft: "Another"), "Save answer")
        XCTAssertFalse(YCText.canSave(using, draft: "typed"), "a box filled from records has no text to save")
    }

    func testFactsWarnWhenTheyAreOld() {
        XCTAssertNil(YCText.staleFacts(YCFacts(read: "2026-11-04", ageDays: 3, stale: false)))
        XCTAssertEqual(YCText.staleFacts(YCFacts(read: "2026-08-01", ageDays: 95, stale: true)),
                       "These facts are 95 days old. Check ycombinator.com before you apply.")
        XCTAssertEqual(YCText.factsHeader(YCFacts(read: "2026-11-04")), "YC facts, read on 2026-11-04")
    }
}

private final class YCStub: TeylaBackend, @unchecked Sendable {
    private struct State {
        var sheets: [YCSheet]
        var failRead: String?
        var failWrite: String?
        var written: [(String, String, String)] = []
    }
    private let box: OSAllocatedUnfairLock<State>

    init(sheets: [YCSheet]) { box = OSAllocatedUnfairLock(initialState: State(sheets: sheets)) }

    var usesFixture: Bool { false }
    var written: [(String, String, String)] { box.withLock { $0.written } }
    var failWrite: String? {
        get { box.withLock { $0.failWrite } }
        set { box.withLock { $0.failWrite = newValue } }
    }

    func ycSheet(id: String) async throws -> YCSheet {
        try await Task.sleep(for: .milliseconds(10))
        return try box.withLock { s -> YCSheet in
            if let why = s.failRead { throw TeylaError.failed(code: 1, message: why) }
            return s.sheets.count > 1 ? s.sheets.removeFirst() : s.sheets[0]
        }
    }

    func ycAnswer(id: String, box boxID: String, text: String) async throws {
        try box.withLock { s in
            if let why = s.failWrite { throw TeylaError.failed(code: 1, message: why) }
            s.written.append((id, boxID, text))
        }
    }

    func startupFocus() async throws -> String? { "alpha" }

    func state() async throws -> Snapshot { throw TeylaError.unavailable("stub") }
    func answer(id: String, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func say(ref: String, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func dispatch(product: String, harness: Harness, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func productPage(id: String, quick: Bool) async throws -> ProductPageData { throw TeylaError.unavailable("stub") }
    func binaryPath() async -> String? { "stub" }
}

@MainActor
final class StartupModelTests: XCTestCase {
    private func until(_ what: String, _ condition: @MainActor () -> Bool) async throws {
        for _ in 0..<300 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("timed out waiting for \(what)")
    }

    private func sheet() throws -> YCSheet { try YCSheet.decode(SampleFiles.data("yc.v1.json")) }

    func testOpeningReadsTheSheetAndSeedsTheTextBoxesFromSavedAnswers() async throws {
        let model = StartupModel(cli: YCStub(sheets: [try sheet()]))
        model.open(id: "sample-app", title: "Sample App")
        XCTAssertTrue(model.presented)
        try await until("the sheet") { model.sheet != nil }
        XCTAssertEqual(model.drafts["building"], "A planner that turns a trip idea into a booked itinerary.")
        XCTAssertEqual(model.drafts["does"], "")
        XCTAssertNil(model.drafts["using"], "a box filled from records has no text")
    }

    func testSavingWritesOneAnswerThenReadsTheSheetAgain() async throws {
        let stub = YCStub(sheets: [try sheet()])
        let model = StartupModel(cli: stub)
        var changed = 0
        model.changed = { changed += 1 }
        model.open(id: "sample-app", title: "Sample App")
        try await until("the sheet") { model.sheet != nil }
        model.drafts["does"] = "  It plans trips.  "
        model.save(box: "does")
        try await until("the write") { !stub.written.isEmpty && !model.isSaving("does") }
        XCTAssertEqual(stub.written.count, 1)
        XCTAssertEqual(stub.written[0].0, "sample-app")
        XCTAssertEqual(stub.written[0].1, "does")
        XCTAssertEqual(stub.written[0].2, "It plans trips.")
        try await until("the count refresh") { changed == 1 }
    }

    func testAnEmptyAnswerIsNeverWritten() async throws {
        let stub = YCStub(sheets: [try sheet()])
        let model = StartupModel(cli: stub)
        model.open(id: "sample-app", title: "Sample App")
        try await until("the sheet") { model.sheet != nil }
        model.drafts["does"] = "   "
        model.save(box: "does")
        model.save(box: "using")
        try await Task.sleep(for: .milliseconds(50))
        XCTAssertTrue(stub.written.isEmpty)
    }

    func testAFailedWriteIsShownOnItsBoxAndKeepsTheText() async throws {
        let stub = YCStub(sheets: [try sheet()])
        stub.failWrite = "the demo answer is a link: https://..."
        let model = StartupModel(cli: stub)
        model.open(id: "sample-app", title: "Sample App")
        try await until("the sheet") { model.sheet != nil }
        model.drafts["demo"] = "not a link"
        model.save(box: "demo")
        try await until("the failure") { model.failures["demo"] != nil }
        XCTAssertEqual(model.failures["demo"], "the demo answer is a link: https://...")
        XCTAssertEqual(model.drafts["demo"], "not a link")
        XCTAssertFalse(model.isSaving("demo"))
    }

    func testClosingForgetsEveryAnswer() async throws {
        let model = StartupModel(cli: YCStub(sheets: [try sheet()]))
        model.open(id: "sample-app", title: "Sample App")
        try await until("the sheet") { model.sheet != nil }
        model.close()
        XCTAssertFalse(model.presented)
        XCTAssertNil(model.sheet)
        XCTAssertTrue(model.drafts.isEmpty)
        XCTAssertNil(model.productID)
    }

    func testTheFocusIsReadOnce() async throws {
        let model = StartupModel(cli: YCStub(sheets: [try sheet()]))
        model.loadFocus()
        try await until("the focus") { model.focusRead }
        XCTAssertEqual(model.focus, "alpha")
    }
}

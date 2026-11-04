import XCTest

final class StartupTests: XCTestCase {
    private func fixtureData() throws -> Data {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("tests/fixtures/state.v3.json")
        return try Data(contentsOf: url)
    }

    private func decode(_ json: String) throws -> PhoneStartup {
        try JSONDecoder().decode(PhoneStartup.self, from: Data(json.utf8))
    }

    private func block(_ s: PhoneStartup, _ group: String, _ row: String) -> ConsoleRow? {
        StartupFormat.groups(s).first { $0.title == group }?.rows.first { $0.title == row }
    }

    // MARK: Decoding

    func testTheV3FixtureBlockDecodes() throws {
        let blocks = PhoneStartupIndex.decode(try fixtureData())
        let s = try XCTUnwrap(blocks["sample-app"])
        XCTAssertEqual(s.stageTitle, "Built")
        XCTAssertEqual(s.next?.text, "Nobody has tried to sell it yet.")
        XCTAssertEqual(s.rungs.first?.status, "met")
        XCTAssertEqual(s.usage.external, 24)
        XCTAssertTrue(s.usage.externalAssumed)
        XCTAssertNil(s.money.paying)
        XCTAssertEqual(s.money.aiCost30dUSD, 12.5)
        XCTAssertEqual(s.yc, PhoneStartup.YC(eligible: true, checked: 3, total: 15, nextBox: "building"))
        XCTAssertNil(blocks["sample-tool"], "a product with no block is not in the index")
    }

    func testAnOlderRelayFileHasNoBlocks() throws {
        let old = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("tests/fixtures/state.v2.json")
        XCTAssertTrue(PhoneStartupIndex.decode(try Data(contentsOf: old)).isEmpty)
        XCTAssertTrue(PhoneStartupIndex.decode(Data("not json".utf8)).isEmpty)
        XCTAssertTrue(PhoneStartupIndex.decode(Data(#"{"portfolio":{"products":[{"id":"a","startup":null},{"id":"b"}]}}"#.utf8)).isEmpty)
    }

    func testTheSnapshotStillDecodesWithTheBlockPresent() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(fixtureData())
        XCTAssertNotNil(snapshot.portfolio?.product("sample-app"))
    }

    func testABadBlockIsDroppedAndTheOthersStay() {
        let json = #"""
        {"portfolio":{"products":[
          {"id":"a","startup":{"stage_title":"Built","rungs":[{"id":"built","status":"met"},{"status":"met"}]}},
          {"id":"b","startup":"oops"},
          {"id":"c","startup":{"stage_title":"Used"}}]}}
        """#
        let blocks = PhoneStartupIndex.decode(Data(json.utf8))
        XCTAssertEqual(Set(blocks.keys), ["a", "c"])
        XCTAssertEqual(blocks["a"]?.rungs.map(\.id), ["built"], "a rung without an id is dropped, not fatal")
        XCTAssertNil(blocks["c"]?.next)
        XCTAssertEqual(blocks["c"]?.typeSet, true, "an absent type_set is not read as 'not chosen'")
    }

    // MARK: A null is a dash

    func testANullIsADashWithItsReasonAndNeverZero() throws {
        let s = try decode(#"""
        {"type":"venture","stage_title":"Built","metrics":{"usage":{"external":null,"wau":null},
         "money":{"enabled":null,"paying":null,"mrr_usd":null},"growth":{"weekly_pct":null,"weeks":2,"on":"wau"}}}
        """#)
        for group in StartupFormat.groups(s) where group.title == "Usage" || group.title == "Monetization" || group.title == "Growth" {
            for row in group.rows {
                XCTAssertNil(row.value, "\(group.title) / \(row.title) must be a dash")
                XCTAssertFalse(row.note.isEmpty, "\(row.title) says why")
            }
        }
        XCTAssertEqual(block(s, "Growth", "Weekly growth")?.note, "Needs 4 weeks of snapshots. 2 weeks so far.")
    }

    func testAZeroFromTheLedgerIsAZero() throws {
        let s = try decode(#"{"type":"venture","metrics":{"marketing":{"posts":0,"posts_7d":0,"ads_outreach":0},"sales":{"icp_meetings":0,"icp_meetings_30d":0,"last":""}}}"#)
        XCTAssertEqual(block(s, "Marketing", "Posts in total")?.value, "0")
        XCTAssertEqual(block(s, "Marketing", "Posts in total")?.note, "Not tried yet.")
        XCTAssertNil(block(s, "Sales", "Last attempt")?.value)
        XCTAssertEqual(block(s, "Sales", "Last attempt")?.note, "No attempt yet.")
    }

    func testAPersonalProductIsNeverNotTriedYet() throws {
        let s = try decode(#"{"type":"personal","metrics":{"marketing":{"posts":0,"posts_7d":0,"ads_outreach":0},"sales":{"icp_meetings":0,"icp_meetings_30d":0,"last":""}}}"#)
        XCTAssertEqual(block(s, "Marketing", "Posts in total")?.note, "")
        XCTAssertEqual(block(s, "Sales", "Last attempt")?.note, "Not used for this type.")
    }

    func testAssumedIsSaidInWords() throws {
        let s = try decode(#"{"metrics":{"usage":{"external":24,"external_assumed":true,"wau":7,"retained_7d":2,"new_7d":2}}}"#)
        XCTAssertEqual(block(s, "Usage", "External people")?.value, "24")
        XCTAssertEqual(block(s, "Usage", "External people")?.note, StartupFormat.assumedNote)
        XCTAssertTrue(StartupFormat.assumedNote.hasPrefix("Assumed"))
        XCTAssertEqual(block(s, "Usage", "New in 7 days")?.note, "")
    }

    func testMoneyAndGrowthFigures() throws {
        let s = try decode(#"""
        {"metrics":{"money":{"enabled":true,"paying":1,"mrr_usd":4.99,"revenue_30d_usd":4.99,"ai_cost_30d_usd":12.5},
         "growth":{"weekly_pct":6.3,"weeks":4,"on":"revenue"}}}
        """#)
        XCTAssertEqual(block(s, "Monetization", "MRR")?.value, "$4.99")
        XCTAssertEqual(block(s, "Monetization", "AI cost, last 30 days")?.value, "$12.50")
        XCTAssertEqual(block(s, "Monetization", "Monetization")?.value, "On")
        XCTAssertEqual(block(s, "Growth", "Weekly growth")?.value, "+6.3%")
        XCTAssertEqual(block(s, "Growth", "Weekly growth")?.note, "Over 4 weeks, on revenue.")
    }

    func testMonetizationOffSaysSo() throws {
        let s = try decode(#"{"metrics":{"money":{"enabled":false,"paying":null,"mrr_usd":null,"ai_cost_30d_usd":12.5}}}"#)
        XCTAssertEqual(block(s, "Monetization", "Monetization")?.value, "Off")
        XCTAssertNil(block(s, "Monetization", "MRR")?.value)
        XCTAssertEqual(block(s, "Monetization", "MRR")?.note, "Monetization is off, so nothing is reported.")
    }

    func testTheFiveGroupsAreInTheContractOrder() throws {
        XCTAssertEqual(StartupFormat.groups(try decode("{}")).map(\.title), ["Marketing", "Sales", "Usage", "Monetization", "Growth"])
    }

    func testAgentRowsAreNamedAsNotCounted() throws {
        let s = try decode(#"{"metrics":{"sales":{"icp_meetings":0,"icp_meetings_30d":0,"last":"","claimed":2}}}"#)
        XCTAssertEqual(block(s, "Sales", "ICP conversations")?.note, "2 logged by agents, not counted.")
    }

    // MARK: Header, rungs, stale

    func testTheHeadlineNamesStageAndType() throws {
        XCTAssertEqual(StartupFormat.headline(try decode(#"{"type":"venture","type_set":true,"stage_title":"Built"}"#)), "Built \u{00B7} Venture")
        XCTAssertEqual(StartupFormat.headline(try decode(#"{"type":"venture","type_set":false,"stage_title":"Built"}"#)), "Built \u{00B7} Type not chosen")
        XCTAssertEqual(StartupFormat.headline(try decode(#"{"type":"open-source","stage_title":"Used","parked":true}"#)), "Used \u{00B7} Open source \u{00B7} Parked")
    }

    func testTheNextSentenceLeads() throws {
        let s = try decode(#"{"next":{"rung":"tried","text":"Nobody has tried to sell it yet.","command":"teyla growth"}}"#)
        XCTAssertEqual(StartupFormat.nextSentence(s), "Nobody has tried to sell it yet.")
        let done = try decode(#"{"next":null,"rungs":[{"id":"built","status":"met"},{"id":"tried","status":"not_applicable"}]}"#)
        XCTAssertEqual(StartupFormat.nextSentence(done), "Every rung of this ladder is met.")
        XCTAssertNil(StartupFormat.nextSentence(try decode("{}")))
    }

    func testEveryStatusHasAWordAndASymbol() {
        for status in ["met", "missing", "unknown", "stale", "not_applicable", "bogus"] {
            XCTAssertFalse(StartupFormat.statusWord(status).isEmpty)
            XCTAssertFalse(StartupFormat.statusSymbol(status).isEmpty)
        }
        XCTAssertEqual(StartupFormat.statusWord("bogus"), "Unknown")
        XCTAssertEqual(Set(["met", "missing", "unknown", "stale", "not_applicable"].map(StartupFormat.statusWord)).count, 5)
    }

    func testTheNextRungIsMarked() {
        let next = PhoneStartup.Next(rung: "tried", text: "")
        let tried = PhoneStartup.Rung(id: "tried", title: "Tried", status: "missing", detail: "")
        let used = PhoneStartup.Rung(id: "used", title: "Used", status: "missing", detail: "")
        XCTAssertEqual(StartupFormat.rungWord(tried, next: next), "Not yet \u{00B7} next")
        XCTAssertEqual(StartupFormat.rungWord(used, next: next), "Not yet")
    }

    func testTheAsOfTimeAndStaleAreVisible() throws {
        let now = ISODate.parse("2026-11-04T12:00:00Z")!
        let fresh = try decode(#"{"as_of":"2026-11-04T10:00:00Z","stale":false}"#)
        XCTAssertEqual(StartupFormat.asOfLine(fresh, now: now), "As of 2h ago")
        let stale = try decode(#"{"as_of":"2026-10-23T12:00:00Z","stale":true}"#)
        XCTAssertTrue(StartupFormat.asOfLine(stale, now: now).hasPrefix("Stale:"))
        XCTAssertTrue(StartupFormat.asOfLine(stale, now: now).contains("As of"))
        XCTAssertEqual(StartupFormat.asOfLine(try decode("{}"), now: now), "As-of time not known")
    }

    // MARK: YC

    func testEveryBoxHasAFixedQuestion() {
        let ids = ["building", "customer", "does", "using", "pay", "why_you", "custom", "goal", "who", "talked", "sell",
                   "demo", "first_live", "need", "commit"]
        XCTAssertEqual(Set(StartupFormat.boxQuestions.keys), Set(ids))
        XCTAssertEqual(StartupFormat.boxQuestions["customer"], "Pick one customer")
    }

    func testTheYCLineIsACountAndAQuestionNeverAPercent() {
        let yc = PhoneStartup.YC(eligible: true, checked: 2, total: 15, nextBox: "customer")
        XCTAssertEqual(StartupFormat.ycHeadline(yc), "2 of 15 boxes")
        XCTAssertEqual(StartupFormat.ycNextQuestion(yc), "Pick one customer")
        XCTAssertTrue(StartupFormat.ycOnMac.contains("Mac"))
        for text in [StartupFormat.ycHeadline(yc), StartupFormat.ycOnMac, StartupFormat.ycNextQuestion(yc) ?? ""] {
            XCTAssertFalse(text.contains("%"))
        }
    }

    func testAnUnknownBoxOrAFullSheetAsksNothing() {
        XCTAssertNil(StartupFormat.ycNextQuestion(PhoneStartup.YC(eligible: true, checked: 2, total: 15, nextBox: "future_box")))
        let full = PhoneStartup.YC(eligible: true, checked: 15, total: 15, nextBox: "building")
        XCTAssertNil(StartupFormat.ycNextQuestion(full))
        XCTAssertEqual(StartupFormat.ycHeadline(full), "All 15 boxes are checked.")
    }

    // MARK: Products list

    func testTheRowLineShowsTheEarnedStageBesideTheSellingLine() throws {
        let s = try decode(#"{"stage_title":"Built"}"#)
        XCTAssertEqual(StartupFormat.rowLine(s, selling: "Not tried to sell yet"), "Built \u{00B7} Not tried to sell yet")
        XCTAssertEqual(StartupFormat.rowLine(s, selling: nil), "Built")
        XCTAssertEqual(StartupFormat.rowLine(nil, selling: "Not tried to sell yet"), "Not tried to sell yet")
        XCTAssertNil(StartupFormat.rowLine(nil, selling: nil))
    }

    // MARK: The sample and the model

    func testTheSampleCarriesBlocksOfEveryKind() throws {
        let data = try XCTUnwrap(try? Data(contentsOf: URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Teyla/Resources/sample-state.json")))
        let shifted = try XCTUnwrap(SampleData.shifted(data))
        let blocks = PhoneStartupIndex.decode(shifted)
        XCTAssertEqual(Set(blocks.keys), ["sample-app", "sample-tool", "sample-web", "sample-watch", "basalt"])
        XCTAssertEqual(blocks["sample-web"]?.stale, true)
        XCTAssertEqual(blocks["sample-web"]?.typeSet, false)
        XCTAssertNil(blocks["basalt"]?.usage.external)
        for block in blocks.values { XCTAssertEqual(StartupFormat.groups(block).count, 5) }
        let snapshot = try PhoneFormat.decodeSnapshot(shifted)
        XCTAssertEqual(snapshot.portfolio?.products.count, 18)
    }

    private struct NoKeyStore: KeyStore {
        func load() -> Data? { nil }
        func save(_ key: Data) throws {}
        func delete() {}
    }

    private var repoRoot: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
    }

    @MainActor
    func testTheModelServesTheBlocksOfTheSnapshotItReads() async throws {
        let fixture = repoRoot.appendingPathComponent("tests/fixtures/state.v3.json").path
        let model = AppModel(environment: ["TEYLA_STATE_FIXTURE": fixture],
                             defaults: UserDefaults(suiteName: "startup-tests-\(UUID().uuidString)")!, keyStore: NoKeyStore())
        XCTAssertNil(model.startup(for: "sample-app"), "nothing is served before a snapshot is read")
        await model.refresh()
        XCTAssertEqual(model.startup(for: "sample-app")?.stageTitle, "Built")
        XCTAssertNil(model.startup(for: "sample-tool"), "a product the Mac sent no block for has none")
    }

    @MainActor
    func testSampleModeCarriesBlocksWithTimesMovedToNow() async throws {
        let sample = repoRoot.appendingPathComponent("apps/ios/Teyla/Resources/sample-state.json")
        let model = AppModel(environment: ["TEYLA_SAMPLE": "1"],
                             defaults: UserDefaults(suiteName: "startup-tests-\(UUID().uuidString)")!, keyStore: NoKeyStore(),
                             sampleData: { try? Data(contentsOf: sample) })
        await model.refresh()
        let tool = try XCTUnwrap(model.startup(for: "sample-tool"))
        XCTAssertEqual(tool.stageTitle, "Paid")
        let age = try XCTUnwrap(PhoneFormat.secondsSince(tool.asOf, now: Date()))
        XCTAssertLessThan(age, 3 * 3600, "the as-of time moved with the sample")
        let web = try XCTUnwrap(model.startup(for: "sample-web"))
        XCTAssertTrue(web.stale)
    }
}

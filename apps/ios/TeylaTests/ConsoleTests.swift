import XCTest

/// The phone's admin screens: what the compact part of the snapshot parses to, and what each screen says about it.
final class ConsoleTests: XCTestCase {
    private func sampleConsole() throws -> (raw: Data, compact: ConsoleCompact) {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Teyla/Resources/sample-state.json")
        let all = try JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any]
        let raw = try JSONSerialization.data(withJSONObject: try XCTUnwrap(all?["console"]))
        return (raw, try JSONDecoder().decode(Console.self, from: raw).compact)
    }

    private func console(_ json: String) throws -> ConsoleCompact {
        try JSONDecoder().decode(Console.self, from: Data(json.utf8)).compact
    }

    // MARK: Parsing

    func testTheSampleConsoleParsesAllFourSections() throws {
        let compact = try sampleConsole().compact
        XCTAssertFalse(compact.allMissing)
        let growth = try XCTUnwrap(compact.growth.value)
        XCTAssertEqual(PhoneConsole.postsToday(growth), "4/6")
        XCTAssertEqual(growth.gaps, 1)
        XCTAssertEqual(growth.pipeline?.review, 3)
        XCTAssertEqual(growth.notTried?.count, 4)
        let money = try XCTUnwrap(compact.money.value)
        XCTAssertEqual(money.monthlyUSD, 214.0)
        XCTAssertEqual(money.unpriced, 1)
        XCTAssertEqual(money.nextRenewal?.days, 5)
        let ops = try XCTUnwrap(compact.operations.value)
        XCTAssertEqual(ops.failures.count, 2)
        XCTAssertEqual(ops.leaveOK, true)
        let book = try XCTUnwrap(compact.playbook.value)
        XCTAssertEqual(book.modelsToLook, 3)
        XCTAssertEqual(book.knowledge?.wiki.value?.pages, 12)
    }

    func testTheSampleConsoleStaysSmall() throws {
        // It travels in iCloud Drive on every update; a screen that needs more must say so in the Mac's compact().
        XCTAssertLessThan(try sampleConsole().raw.count, 2_500)
    }

    func testAnOlderMacThatSendsNoConsoleLeavesEverySectionMissing() throws {
        let compact = try console("{}")
        XCTAssertTrue(compact.allMissing)
        XCTAssertEqual(compact.growth, .missing)
    }

    func testASectionWhoseSourceFailedKeepsItsReasonAndTheOthersLoad() throws {
        let compact = try console(#"{"growth": {"error": "The ledger could not be read."}, "money": {"monthly_usd": 20}}"#)
        XCTAssertEqual(compact.growth.error, "The ledger could not be read.")
        XCTAssertEqual(compact.money.value?.monthlyUSD, 20)
        XCTAssertEqual(compact.operations, .missing)
    }

    func testANullAndAWrongTypeAreADashNotAZero() throws {
        let compact = try console(#"{"growth": {"gaps": null, "qualified_week": "many", "today": []}}"#)
        let growth = try XCTUnwrap(compact.growth.value)
        XCTAssertNil(growth.gaps)
        XCTAssertNil(growth.qualifiedWeek)
        let tiles = PhoneConsole.growthTiles(growth)
        XCTAssertNil(tiles.first { $0.label == "Slots with no draft" }?.value)
        XCTAssertEqual(tiles.first { $0.label == "Slots with no draft" }?.detail, PhoneConsole.onMac)
    }

    func testFailuresThatThePhoneWasNotSentAreNotSaidToBeNone() throws {
        let compact = try console(#"{"operations": {"headline": {"label": "Unresolved failures", "value": 3}}}"#)
        let ops = try XCTUnwrap(compact.operations.value)
        XCTAssertFalse(ops.failuresRead)
        XCTAssertEqual(ops.failuresNotShown, 3)
        XCTAssertEqual(PhoneConsole.moreFailures(ops), "3 more failures are on your Mac.")
    }

    // MARK: Words

    func testGrowthTilesNameTheTargetAndWhatWaits() throws {
        let growth = try XCTUnwrap(sampleConsole().compact.growth.value)
        let tiles = PhoneConsole.growthTiles(growth)
        XCTAssertEqual(tiles.map(\.label), ["Posts today", "Conversations", "Waiting for you", "Slots with no draft", "Replies today"])
        XCTAssertEqual(tiles[0].value, "4/6")
        XCTAssertEqual(tiles[0].tone, .needsYou, "two channels still wait for a post")
        XCTAssertEqual(tiles[2].value, "3")
        XCTAssertEqual(PhoneConsole.draftsLine(growth), "3 drafts wait for you on your Mac.")
        XCTAssertTrue(PhoneConsole.draftsStayHome.contains("nothing is posted from here"))
    }

    func testTheEngageTileCountsRepliesAndIsADashWithoutAList() throws {
        let compact = try console(#"{"growth": {"today": [], "engage": {"day": "2026-11-07", "scanned": true, "total": 20, "done": 3, "goal": 20}}}"#)
        let growth = try XCTUnwrap(compact.growth.value)
        let tile = PhoneConsole.engageTile(growth.engage)
        XCTAssertEqual(tile.value, "3/20")
        XCTAssertEqual(tile.tone, .needsYou)
        XCTAssertNil(PhoneConsole.engageTile(nil).value)
        XCTAssertNil(PhoneConsole.engageTile(GrowthEngageCount(day: "2026-11-07")).value)
        XCTAssertEqual(PhoneConsole.engageTile(GrowthEngageCount(scanned: true, total: 4, done: 4)).tone, .saving)
    }

    func testChannelsStillWaitingForAPostComeFirst() throws {
        let growth = try XCTUnwrap(sampleConsole().compact.growth.value)
        let rows = PhoneConsole.channelRows(growth)
        XCTAssertEqual(rows.count, 6)
        XCTAssertEqual(rows.map(\.done), [false, false, true, true, true, true])
    }

    func testMoneyIsCashAndTheAIFigureIsNeverCalledCash() throws {
        let money = try XCTUnwrap(sampleConsole().compact.money.value)
        let tiles = PhoneConsole.moneyTiles(money)
        XCTAssertEqual(tiles.map(\.label), ["Cash per month", "AI at list price", "Next renewal"])
        XCTAssertEqual(tiles[1].detail, "Last 7 days. Not cash.")
        XCTAssertEqual(tiles[0].detail, "1 listed with no price")
    }

    func testMoneyWithoutAnyFigureIsADashAndSaysWhy() throws {
        let tiles = PhoneConsole.moneyTiles(MoneyCompact())
        XCTAssertNil(tiles[0].value)
        XCTAssertNil(tiles[1].value)
        XCTAssertEqual(tiles[1].detail, PhoneConsole.onMac)
        XCTAssertEqual(tiles[2].detail, "None listed")
    }

    func testOperationsTilesShowFailuresDiskAndTheLid() throws {
        let ops = try XCTUnwrap(sampleConsole().compact.operations.value)
        let tiles = PhoneConsole.operationsTiles(ops)
        XCTAssertEqual(tiles.map(\.label), ["Failures", "Disk free", "Close the lid"])
        XCTAssertEqual(tiles[0].value, "2")
        XCTAssertEqual(tiles[0].tone, .danger)
        XCTAssertEqual(tiles[1].value, "48 GB")
        XCTAssertEqual(tiles[2].value, "Yes")
        XCTAssertEqual(PhoneConsole.lid(nil).detail, PhoneConsole.onMac)
    }

    func testPlaybookCountsTheModelsAndNamesWhatIsKnown() throws {
        let book = try XCTUnwrap(sampleConsole().compact.playbook.value)
        let tiles = PhoneConsole.playbookTiles(book)
        XCTAssertEqual(tiles[1].value, "3")
        XCTAssertEqual(tiles[1].detail, "1 drift \u{00B7} 2 new")
        let rows = PhoneConsole.knowledgeRows(book)
        XCTAssertEqual(rows.map(\.title), ["Wiki pages", "Your own words", "Corrections", "Design decisions"])
        XCTAssertEqual(rows[0].value, "12")
        XCTAssertEqual(PhoneConsole.knowledgeRows(PlaybookCompact()).map(\.value), [nil, nil, nil, nil])
    }

    func testNoLabelOnAnyScreenIsACommandName() throws {
        let compact = try sampleConsole().compact
        var words: [String] = []
        if let growth = compact.growth.value {
            words += PhoneConsole.growthTiles(growth).flatMap { [$0.label, $0.detail] }
            words += (PhoneConsole.queueRows(growth) + PhoneConsole.pipelineRows(growth)).flatMap { [$0.title, $0.note] }
        }
        if let money = compact.money.value { words += PhoneConsole.moneyTiles(money).flatMap { [$0.label, $0.detail] } }
        if let ops = compact.operations.value { words += PhoneConsole.operationsTiles(ops).flatMap { [$0.label, $0.detail] } }
        if let book = compact.playbook.value { words += PhoneConsole.playbookTiles(book).flatMap { [$0.label, $0.detail] } }
        for word in words {
            XCTAssertFalse(word.lowercased().contains("teyla "), word)
            XCTAssertFalse(word.contains("--"), word)
        }
    }

    // MARK: Products and More

    func testProductsNobodyTriedToSellAreNamedAndParkedOnesAreApart() throws {
        let growth = try XCTUnwrap(sampleConsole().compact.growth)
        XCTAssertEqual(PhoneConsole.sellingLine(productID: "pebble", growth: .data(try XCTUnwrap(growth.value)), parked: false),
                       "Not tried to sell yet")
        XCTAssertEqual(PhoneConsole.sellingLine(productID: "pebble", growth: growth, parked: true),
                       "Not tried to sell yet \u{00B7} parked")
        XCTAssertNil(PhoneConsole.sellingLine(productID: "sample-app", growth: growth, parked: false))
        XCTAssertNil(PhoneConsole.sellingLine(productID: "pebble", growth: .missing, parked: false),
                     "an older Mac did not say, so the phone says nothing")
    }

    func testMoreShowsAFigureUnderEachRowAndSaysWhenItHasNone() throws {
        let compact = try sampleConsole().compact
        XCTAssertEqual(PhoneConsole.moreLine(.money, console: compact, status: "Connected"), "$214 a month in subscriptions")
        XCTAssertEqual(PhoneConsole.moreLine(.operations, console: compact, status: "Connected"), "Machine fine \u{00B7} 2 failing")
        XCTAssertEqual(PhoneConsole.moreLine(.playbook, console: compact, status: "Connected"), "1 rule came back")
        XCTAssertEqual(PhoneConsole.moreLine(.settings, console: compact, status: "Connected"), "Connected")
        XCTAssertEqual(PhoneConsole.moreLine(.money, console: nil, status: "Connected"), "Not read yet")
        XCTAssertEqual(PhoneConsole.moreLine(.money, console: ConsoleCompact(), status: "Connected"), "Not in this update")
    }
}

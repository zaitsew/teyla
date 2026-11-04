import XCTest

private func playbook(_ json: String) throws -> PlaybookReport {
    try JSONDecoder().decode(PlaybookReport.self, from: Data(json.utf8))
}

private func sample() throws -> PlaybookReport {
    guard let report = try ConsoleReport.decode(SampleFiles.data("console.v1.json")).playbook.value else {
        throw TeylaError.badOutput("no playbook in the sample")
    }
    return report
}

final class PlaybookParsingTests: XCTestCase {
    func testTheSampleHoldsEverySection() throws {
        let report = try sample()
        XCTAssertEqual(report.headline?.number, 2)
        XCTAssertEqual(report.guidelines.count, 6)
        XCTAssertEqual(report.guidelines.last?.count, 6)
        XCTAssertNotNil(report.guidelines.first?.updated)
        let models = try XCTUnwrap(report.models.value)
        XCTAssertEqual(models.ladder.count, 3)
        XCTAssertEqual(models.ladder[0].volume.count, 2)
        XCTAssertEqual(models.drift.count, 2, "a drift row is a dictionary or only a sentence")
        XCTAssertEqual(models.drift[0].entry, "claude-opus-5")
        XCTAssertNil(models.drift[1].entry)
        XCTAssertEqual(models.drift[1].detail, "sample-model-5 is used in 2 routes but not on the ladder")
        XCTAssertEqual(models.new.first?.modelID, "sample-model-6")
        XCTAssertEqual(models.new.first?.price, "$1/$5")
        XCTAssertEqual(models.arena?.top.count, 3)
        XCTAssertNil(models.arena?.top.last?.cost, "no cost stays nil, never zero")
        XCTAssertEqual(models.arena?.top.first?.inLadder, true)
        let knowledge = try XCTUnwrap(report.knowledge.value)
        XCTAssertEqual(knowledge.intent.value?.entries, 317)
        XCTAssertEqual(knowledge.corrections.value?.last30, 21)
        XCTAssertEqual(knowledge.wiki.value?.pages, 40)
        XCTAssertEqual(knowledge.taste.value?.total, 12)
        let you = try XCTUnwrap(report.you.value)
        XCTAssertTrue(you.available)
        XCTAssertEqual(you.quotes.count, 2)
        XCTAssertEqual(you.insights.count, 2)
        XCTAssertEqual(you.insights[0].value, "29.5", "a number is shown as text")
        XCTAssertEqual(you.insights[1].value, "9")
        XCTAssertNil(you.postcard)
        XCTAssertEqual(you.delegation.count, 2)
        XCTAssertEqual(you.contradictions?.rules.count, 2)
        XCTAssertEqual(you.localOnly, true)
    }

    func testAnEmptyObjectIsAnEmptyReport() throws {
        let report = try playbook("{}")
        XCTAssertNil(report.headline)
        XCTAssertTrue(report.guidelines.isEmpty)
        XCTAssertEqual(report.models, .missing)
        XCTAssertEqual(report.knowledge, .missing)
        XCTAssertEqual(report.you, .missing)
    }

    func testNullsAndWrongTypesLeaveNilNotZero() throws {
        let report = try playbook("""
        {"guidelines": [{"title": "A", "exists": "yes", "updated": 5, "count": "x"}],
         "models": {"ladder": null, "drift": null, "new": [{"provider": "x"}], "arena": {"top": null, "as_of": 3}},
         "knowledge": {"wiki": {"pages": null}, "intent": {"entries": "many"}},
         "you": {"quotes": null, "insights": [{"label": "L", "value": null}], "delegation": null}}
        """)
        XCTAssertNil(report.guidelines[0].exists)
        XCTAssertNil(report.guidelines[0].updated)
        XCTAssertNil(report.guidelines[0].count)
        let models = try XCTUnwrap(report.models.value)
        XCTAssertTrue(models.ladder.isEmpty)
        XCTAssertTrue(models.new.isEmpty, "a new model without an id is skipped")
        XCTAssertNil(models.arena?.asOf)
        XCTAssertTrue(models.arena?.top.isEmpty ?? false)
        let knowledge = try XCTUnwrap(report.knowledge.value)
        XCTAssertNil(knowledge.wiki.value?.pages)
        XCTAssertNil(knowledge.intent.value?.entries)
        XCTAssertEqual(knowledge.corrections, .missing)
        XCTAssertNil(try XCTUnwrap(report.you.value).insights[0].value)
    }

    func testOneUnreadableRowIsSkippedNotTheList() throws {
        let report = try playbook("""
        {"guidelines": [{"title": "A"}, {"summary": "no title"}, 7, {"title": "B"}],
         "models": {"ladder": [{"provider": "a"}, {"label": "no provider"}], "drift": ["one", 4, {"detail": "two"}]},
         "you": {"quotes": [{"text": "q1"}, {"day": "2026-01-01"}]}}
        """)
        XCTAssertEqual(report.guidelines.map(\.title), ["A", "B"])
        XCTAssertEqual(report.models.value?.ladder.map(\.provider), ["a"])
        XCTAssertEqual(report.models.value?.drift.compactMap(\.detail), ["one", "two"])
        XCTAssertEqual(report.you.value?.quotes.map(\.text), ["q1"])
    }

    func testAPartErrorStaysItsOwn() throws {
        let report = try playbook("""
        {"models": {"error": "catalogue missing"},
         "knowledge": {"wiki": {"error": "no wiki folder"}, "intent": {"entries": 4}},
         "you": {"available": false, "reason": "not installed in this build"}}
        """)
        XCTAssertEqual(report.models, .failed("catalogue missing"))
        XCTAssertEqual(report.knowledge.value?.wiki, .failed("no wiki folder"))
        XCTAssertEqual(report.knowledge.value?.intent.value?.entries, 4)
        XCTAssertEqual(report.you.value?.available, false)
        XCTAssertEqual(report.you.value?.reason, "not installed in this build")
    }

    func testTheGuidelinesCanFailOnTheirOwn() throws {
        let failed = try playbook(#"{"guidelines": {"error": "no repo root"}}"#)
        XCTAssertEqual(failed.guidelineList, .failed("no repo root"))
        XCTAssertTrue(failed.guidelines.isEmpty)
        XCTAssertEqual(try playbook(#"{"guidelines": []}"#).guidelineList, .data(PlaybookGuidelineList()), "an empty list is not an error")
    }

    func testTwoReposCanHoldTheSameRule() throws {
        let rules = try XCTUnwrap(try playbook("""
        {"you": {"contradictions": {"rules": [{"repo": "a", "rule": "r"}, {"repo": "b", "rule": "r"}]}}}
        """).you.value?.contradictions?.rules)
        XCTAssertEqual(Set(rules.map(\.id)).count, 2)
    }

    func testASectionErrorStaysItsOwn() throws {
        let all = try ConsoleReport.decode(Data(#"{"version": 1, "playbook": {"error": "no repo root"}}"#.utf8))
        XCTAssertEqual(all.playbook, .failed("no repo root"))
    }

    func testThePostcardReadsThenAndNow() throws {
        let card = try JSONDecoder().decode(PlaybookPostcard.self, from: Data("""
        {"week": "2026-W45", "then": {"text": "Earlier words", "day": "2026-10-09", "product": "a"},
         "now": {"commits": 2030, "tags": 3, "latest_tag": "v1"}}
        """.utf8))
        XCTAssertEqual(card.then?.text, "Earlier words")
        XCTAssertEqual(card.commits, 2030)
        XCTAssertEqual(card.latestTag, "v1")
    }
}

final class PlaybookLogicTests: XCTestCase {
    func testGuidelinesOpenOnlyWhenTheFileIsThere() throws {
        let rows = try sample().guidelines
        let url = try XCTUnwrap(PlaybookLogic.openable(rows[0]))
        XCTAssertFalse(url.path.hasPrefix("~"), "the home folder is expanded")
        XCTAssertNil(PlaybookLogic.openable(PlaybookGuideline(id: "x", title: "X", path: "/tmp/x", exists: false)))
        XCTAssertNil(PlaybookLogic.openable(PlaybookGuideline(id: "x", title: "X", path: nil, exists: true)))
        XCTAssertNil(PlaybookLogic.openable(PlaybookGuideline(id: "x", title: "X", path: "", exists: nil)))
        XCTAssertEqual(PlaybookLogic.guidelineDetail(PlaybookGuideline(id: "x", title: "X", exists: false)), "The file is missing.")
        XCTAssertEqual(PlaybookLogic.guidelineDetail(rows[0]), "updated 30 Oct")
        XCTAssertEqual(PlaybookLogic.guidelineDetail(rows[5]), "6 files, updated 3 Nov")
    }

    func testBackticksAreDropped() {
        XCTAssertEqual(PlaybookLogic.plain("run `teyla ux check` first"), "run teyla ux check first")
        XCTAssertEqual(PlaybookLogic.tier(["GPT-6 Astra (`-m gpt-6-astra`)"]), "GPT-6 Astra (-m gpt-6-astra)")
    }

    func testLadderTiersAreDashesWhenEmpty() {
        XCTAssertEqual(PlaybookLogic.tier([]), Format.dash)
        XCTAssertEqual(PlaybookLogic.tier(["A", "B"]), "A · B")
    }

    func testDriftAndNewModelWords() throws {
        let models = try XCTUnwrap(try sample().models.value)
        XCTAssertTrue(PlaybookLogic.driftText(models.drift[0]).hasPrefix("claude-opus-5 is still named"))
        XCTAssertEqual(PlaybookLogic.driftText(PlaybookDrift(flag: nil, provider: "a", entry: "b")), "a · b")
        XCTAssertEqual(PlaybookLogic.driftText(PlaybookDrift()), "The ladder differs from the catalogue.")
        XCTAssertEqual(PlaybookLogic.newModelDetail(models.new[0]), "OpenAI · $1/$5 · replaces Sol · seen 3 Nov")
        XCTAssertEqual(PlaybookLogic.modelsToLook(models), 3)
        XCTAssertNil(PlaybookLogic.modelsToLook(nil))
    }

    func testEveryArenaRowIsACandidate() throws {
        let board = try XCTUnwrap(try sample().models.value?.arena)
        for row in board.top { XCTAssertEqual(PlaybookLogic.arenaStatus(row, board: board), "candidate, not a decision") }
        let bare = PlaybookArenaRow(model: "M")
        XCTAssertEqual(PlaybookLogic.arenaStatus(bare, board: PlaybookArena()), "candidate, not a decision", "the words are there even when the report has none")
        XCTAssertEqual(PlaybookLogic.arenaDetail(board.top[0]), "score 1,510 · cost 0.35 · best for its cost · on the ladder")
        XCTAssertEqual(PlaybookLogic.arenaDetail(board.top[2]), "score 1,470 · not on the ladder")
        XCTAssertEqual(PlaybookLogic.arenaDetail(bare), "No figures.")
        XCTAssertTrue(PlaybookLogic.arenaNote(board).contains("Candidates, not decisions."))
        XCTAssertEqual(PlaybookLogic.arenaNote(PlaybookArena(note: "paste a snapshot")), "paste a snapshot")
    }

    func testKnowledgeWords() throws {
        let knowledge = try XCTUnwrap(try sample().knowledge.value)
        XCTAssertEqual(PlaybookLogic.count(317), "317")
        XCTAssertNil(PlaybookLogic.count(nil))
        XCTAssertEqual(PlaybookLogic.wikiDetail(try XCTUnwrap(knowledge.wiki.value)), "3 draft · 30 confirmed · 7 stale · 2 in the inbox")
        XCTAssertEqual(PlaybookLogic.wikiDetail(PlaybookWiki(path: NSHomeDirectory() + "/ops/wiki", pages: 0)), "No page yet in ~/ops/wiki.")
        XCTAssertEqual(PlaybookLogic.correctionsDetail(try XCTUnwrap(knowledge.corrections.value)), "21 in the last 30 days · 10 repos")
        XCTAssertEqual(PlaybookLogic.tasteDetail(try XCTUnwrap(knowledge.taste.value)), "5 fix · 4 rule · 3 reject")
        XCTAssertEqual(PlaybookLogic.intentDetail(PlaybookIntent(products: 1)), "1 product")
    }

    func testQuotesAndChores() throws {
        let you = try XCTUnwrap(try sample().you.value)
        XCTAssertEqual(PlaybookLogic.attribution(try XCTUnwrap(you.quoteOfTheDay)), "3 Oct · sample-app")
        XCTAssertEqual(PlaybookLogic.attribution(PlaybookQuote(text: "x")), "")
        XCTAssertEqual(PlaybookLogic.sentence("handed off"), "Handed off")
        XCTAssertEqual(PlaybookLogic.sentence(""), "")
        let others = PlaybookLogic.otherQuotes(you)
        XCTAssertEqual(others.count, 2)
        XCTAssertEqual(others[0].score, 5, "the best quote first")
        let order = PlaybookLogic.choresInOrder(you.delegation)
        XCTAssertEqual(order[0].status, "open", "an open chore is first")
        XCTAssertEqual(PlaybookLogic.choreDetail(order[0]), "asked 16 times · last 1 Nov · sample-app, sample-web")
        XCTAssertEqual(PlaybookLogic.contradictionRow(try XCTUnwrap(you.contradictions?.rules.first)), "3 corrections since · rule written 1 Oct · last 28 Oct · sample-app")
    }

    func testTheSameQuoteIsNotShownTwice() {
        let day = PlaybookQuote(text: "same", score: 5)
        let you = PlaybookYou(quoteOfTheDay: day, quotes: [day, PlaybookQuote(text: "other", score: 3)])
        XCTAssertEqual(PlaybookLogic.otherQuotes(you).map(\.text), ["other"])
    }
}

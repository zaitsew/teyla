import XCTest

final class MorningCardTests: XCTestCase {
    // MARK: Prompt

    private func snapshot(_ products: [(String, String, [String])]) -> Snapshot {
        var list: [PortfolioProduct] = []
        for (name, last, titles) in products {
            list.append(PortfolioProduct(id: name, activity: Activity(last: last),
                                         progress: ProductProgress(shippedPRs: titles.count, shippedTop: titles)))
        }
        return Snapshot(portfolio: Portfolio(products: list))
    }

    func testPromptUsesTheNewestShippedTitle() {
        let s = snapshot([("a", "2026-11-05T10:00:00Z", ["Old one"]), ("b", "2026-11-08T10:00:00Z", ["Fresh one", "Second"])])
        XCTAssertEqual(MorningCardLogic.prompt(snapshot: s), "Yesterday you shipped \u{201C}Fresh one\u{201D}. What surprised you?")
    }

    func testPromptSkipsProductsWithNoTitles() {
        let s = snapshot([("a", "2026-11-08T10:00:00Z", []), ("b", "2026-11-01T10:00:00Z", ["Only one"])])
        XCTAssertEqual(MorningCardLogic.shippedTitle(in: s), "Only one")
    }

    func testPromptFallsBackWithoutTitles() {
        XCTAssertEqual(MorningCardLogic.prompt(snapshot: nil), "What did you ship or learn yesterday?")
        XCTAssertEqual(MorningCardLogic.prompt(snapshot: snapshot([("a", "", [])])), "What did you ship or learn yesterday?")
    }

    func testPromptTruncatesLongTitles() {
        let long = String(repeating: "word ", count: 30)
        let t = MorningCardLogic.truncated(long)
        XCTAssertLessThanOrEqual(t.count, 80)
        XCTAssertTrue(t.hasSuffix("\u{2026}"))
        XCTAssertEqual(MorningCardLogic.truncated("Short"), "Short")
    }

    // MARK: Days

    func testNewDayStartsFreshAndKeepsOnlyThePostedRecord() {
        var s = MorningCardState(day: "2026-11-08")
        s.answer = "text"
        s.linkedIn = "a"; s.x = "b"
        s.markCopied(.x)
        s.markPosted()
        let next = s.rolled(to: "2026-11-09")
        XCTAssertEqual(next.answer, "")
        XCTAssertFalse(next.hasDrafts)
        XCTAssertNil(next.posted)
        XCTAssertEqual(next.previous?.day, "2026-11-08")
        XCTAssertEqual(next.previous?.networks, ["x"])
    }

    func testLinkAskOnlyOnALaterDay() {
        var s = MorningCardState(day: "2026-11-08")
        s.markCopied(.linkedIn)
        s.markPosted()
        XCTAssertNil(s.linkAsk)
        XCTAssertNotNil(s.rolled(to: "2026-11-09").linkAsk)
        XCTAssertNotNil(s.rolled(to: "2026-11-12").linkAsk)
    }

    func testNoPostMeansNoLinkAskAndSkipOrSaveClearsIt() {
        XCTAssertNil(MorningCardState(day: "2026-11-08").rolled(to: "2026-11-09").linkAsk)
        var s = MorningCardState(day: "2026-11-08"); s.markPosted()
        var a = s.rolled(to: "2026-11-09")
        a.skipLink()
        XCTAssertNil(a.linkAsk)
        var b = s.rolled(to: "2026-11-09")
        XCTAssertTrue(b.saveLink("https://www.linkedin.com/posts/x"))
        XCTAssertNil(b.linkAsk)
        XCTAssertNil(b.rolled(to: "2026-11-10").linkAsk?.url)
    }

    func testStateRoundTripsThroughDefaults() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "morning-card-test"))
        defaults.removePersistentDomain(forName: "morning-card-test")
        var s = MorningCardState(day: MorningCardLogic.dayKey(Date()))
        s.answer = "kept"
        MorningCardLogic.save(s, defaults: defaults)
        XCTAssertEqual(MorningCardLogic.load(defaults: defaults).answer, "kept")
        let later = Calendar.current.date(byAdding: .day, value: 1, to: Date())!
        XCTAssertEqual(MorningCardLogic.load(defaults: defaults, now: later).answer, "")
    }

    // MARK: URLs

    func testURLValidation() {
        XCTAssertNotNil(MorningCardLogic.validPostURL("https://www.linkedin.com/posts/abc"))
        XCTAssertNotNil(MorningCardLogic.validPostURL("https://x.com/me/status/1"))
        XCTAssertNotNil(MorningCardLogic.validPostURL("https://twitter.com/me/status/1"))
        XCTAssertNil(MorningCardLogic.validPostURL("http://x.com/me/status/1"))
        XCTAssertNil(MorningCardLogic.validPostURL("https://example.com/x.com"))
        XCTAssertNil(MorningCardLogic.validPostURL("https://notx.com/a"))
        XCTAssertNil(MorningCardLogic.validPostURL("x.com/a"))
    }

    func testXIntentIsPercentEncoded() throws {
        let url = try XCTUnwrap(MorningCardLogic.xIntentURL(text: "a b&c #1"))
        XCTAssertEqual(url.absoluteString, "https://x.com/intent/post?text=a%20b%26c%20%231")
    }

    func testPostedRecordsTheCopiedNetworks() {
        var s = MorningCardState(day: "2026-11-08")
        s.markCopied(.linkedIn); s.markCopied(.x); s.markCopied(.linkedIn)
        s.markPosted()
        XCTAssertEqual(s.posted?.networks, ["linkedin", "x"])
    }

    // MARK: Post rules

    func testXVersionStaysWithinTheLimitAndKeepsFirstAndLast() {
        let mid = String(repeating: "m", count: 120) + "."
        let x = PostCutter.xVersion(["First one.", mid, mid, "Last one."])
        XCTAssertLessThanOrEqual(x.count, 280)
        XCTAssertTrue(x.hasPrefix("First one."))
        XCTAssertTrue(x.hasSuffix("Last one."))
    }

    func testXVersionTruncatesALongFirstSentence() {
        let long = (0..<100).map { _ in "word" }.joined(separator: " ") + "."
        let x = PostCutter.xVersion([long])
        XCTAssertLessThanOrEqual(x.count, 280)
        XCTAssertTrue(x.hasSuffix("\u{2026}"))
    }

    func testPrepareStripsTagsAndLinks() {
        XCTAssertEqual(PostRules.prepare("Shipped it #buildinpublic today"), "Shipped it today")
        XCTAssertEqual(PostRules.prepare("Fixed the sync (github.com/x/y) today."), "Fixed the sync today.")
        XCTAssertEqual(PostRules.prepare("Merged https://github.com/x/y/pull/42 today"), "Merged PR #42 today")
        XCTAssertEqual(PostRules.prepare("We built it in github.com/x/y."), "We built it.")
    }

    func testFindings() {
        let note = "We shipped 3 fixes."
        XCTAssertTrue(PostRules.findings("A #tag here", note: note).contains("hashtag"))
        XCTAssertTrue(PostRules.findings("See https://a.com", note: note).contains("link"))
        XCTAssertTrue(PostRules.findings("We shipped 5 fixes.", note: note).contains("number not in note: 5"))
        XCTAssertTrue(PostRules.findings("A seamless fix.", note: note).contains("banned: seamless"))
        XCTAssertTrue(PostRules.findings("We shipped 3 fixes.", note: note).isEmpty)
    }
}

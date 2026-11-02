import XCTest

private func homeSnapshot() throws -> Snapshot {
    try TeylaCLI.decodeSnapshot(SampleFiles.data("state.sample.home.json"))
}

private func ask(_ id: String, bucket: String? = nil, action: String = "", proposed: String = "") -> Ask {
    Ask(id: id, product: "sample-app", question: "Question \(id)?",
        triage: bucket.map { Triage(bucket: $0, action: action, proposed: proposed) })
}

final class HomeDecodingTests: XCTestCase {
    func testTriageCoreAndAutoClosedDecode() throws {
        let snapshot = try homeSnapshot()
        let triaged = try XCTUnwrap(snapshot.asks.first)
        XCTAssertEqual(triaged.triage?.actionRaw, "pay")
        XCTAssertEqual(triaged.triage?.proposed, "Renew")
        XCTAssertEqual(snapshot.autoClosed?.count, 3)
        XCTAssertEqual(snapshot.autoClosed?.items.first?.id, "c0000001")
        let portfolio = try XCTUnwrap(snapshot.portfolio)
        XCTAssertEqual(portfolio.core, ["sample-app", "sample-tool", "sample-web", "sample-watch"])
        XCTAssertEqual(portfolio.coreSource, "star")
        let progress = try XCTUnwrap(portfolio.product("sample-app")?.progress)
        XCTAssertEqual(progress.shippedPRs, 14)
        XCTAssertEqual(progress.shippedTop.first, "Add the privacy screen")
        XCTAssertEqual(progress.users?.label, "4 active this week, 12 total")
        XCTAssertEqual(progress.canInstall.count, 3)
    }

    func testOlderSnapshotsStillDecode() throws {
        for name in ["state.sample.v2.json", "state.sample.v3.json"] {
            let snapshot = try TeylaCLI.decodeSnapshot(SampleFiles.data(name))
            XCTAssertNil(snapshot.autoClosed, name)
            XCTAssertTrue(snapshot.asks.allSatisfy { $0.triage == nil }, name)
            XCTAssertTrue(snapshot.asks.allSatisfy(\.isOwnerAsk), name)
            XCTAssertEqual(snapshot.portfolio?.core ?? [], [], name)
            XCTAssertEqual(snapshot.portfolio?.coreSource ?? "", "", name)
            XCTAssertNil(snapshot.portfolio?.products.first?.progress, name)
        }
    }

    func testUnknownTriageValuesReadAsOwnerDecisions() throws {
        let json = #"{"id":"x","product":"p","question":"q","triage":{"bucket":"later","action":"ponder"}}"#
        let decoded = try JSONDecoder().decode(Ask.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.bucket, .owner)
        XCTAssertEqual(decoded.decisionGroup, .decide)
        XCTAssertNil(decoded.proposedAnswer)
    }

    func testAMalformedAutoClosedItemIsSkipped() throws {
        let json = #"{"count":2,"items":[{"id":"a","title":"One"},{"title":"No id"}]}"#
        let closed = try JSONDecoder().decode(AutoClosed.self, from: Data(json.utf8))
        XCTAssertEqual(closed.count, 2)
        XCTAssertEqual(closed.items.map(\.id), ["a"])
    }
}

final class DecisionsLogicTests: XCTestCase {
    func testSplitSeparatesOwnerAgentAndClosed() throws {
        let split = Decisions.split(try homeSnapshot().asks)
        XCTAssertEqual(split.owner.count, 7)
        XCTAssertEqual(split.agent.count, 2)
        XCTAssertEqual(split.close.count, 1)
    }

    func testASuggestionToCloseStaysOnThePageUntilAccepted() throws {
        let close = Decisions.split(try homeSnapshot().asks).close
        XCTAssertEqual(Decisions.closeLine(count: close.count), "Teyla suggests closing 1")
        XCTAssertNil(Decisions.closeLine(count: 0))
        XCTAssertEqual(HomeCommands.acceptCloseArguments(ids: ["c0000001", "c0000002"]),
                       ["asks", "accept-close", "c0000001", "c0000002"])
        XCTAssertNil(HomeCommands.acceptCloseArguments(ids: []))
        XCTAssertNil(HomeCommands.acceptCloseArguments(ids: ["--all"]))
    }

    func testWithoutTriageEveryQuestionIsTheOwners() {
        let asks = [ask("a"), ask("b")]
        XCTAssertFalse(Decisions.hasTriage(asks))
        XCTAssertEqual(Decisions.split(asks).owner.count, 2)
    }

    func testGroupsFollowPayDecideDoAndKeepRank() {
        let asks = [ask("1", bucket: "owner", action: "do"), ask("2", bucket: "owner", action: "decide"),
                    ask("3", bucket: "owner", action: "pay"), ask("4", bucket: "owner", action: "decide")]
        let groups = Decisions.grouped(asks)
        XCTAssertEqual(groups.map(\.kind), [.pay, .decide, .doIt])
        XCTAssertEqual(groups.map(\.heading), ["Pay · 1", "Decide · 2", "Do · 1"])
        XCTAssertEqual(groups[1].asks.map(\.id), ["2", "4"])
    }

    func testAnEmptyGroupIsLeftOut() {
        XCTAssertEqual(Decisions.grouped([ask("1", bucket: "owner", action: "decide")]).map(\.kind), [.decide])
        XCTAssertTrue(Decisions.grouped([]).isEmpty)
    }

    func testHomeShowsFiveAndOffersTheRest() {
        let asks = (1...8).map { ask("\($0)") }
        XCTAssertEqual(Decisions.homeList(asks).map(\.id), ["1", "2", "3", "4", "5"])
        XCTAssertEqual(Decisions.seeAll(total: 8, shown: 5), "See all 8")
        XCTAssertNil(Decisions.seeAll(total: 5, shown: 5))
        XCTAssertNil(Decisions.seeAll(total: 0, shown: 0))
    }

    func testAPaymentCannotBeAnsweredWithOneClick() {
        XCTAssertFalse(ask("1", bucket: "owner", action: "pay", proposed: "Renew").canUseProposedAnswer)
        XCTAssertTrue(ask("2", bucket: "owner", action: "decide", proposed: "Yes").canUseProposedAnswer)
        XCTAssertFalse(ask("3", bucket: "owner", action: "decide", proposed: "  ").canUseProposedAnswer)
        XCTAssertFalse(ask("4").canUseProposedAnswer)
    }

    func testLines() {
        XCTAssertEqual(Decisions.agentLine(count: 20), "Agents can settle 20")
        XCTAssertNil(Decisions.agentLine(count: 0))
        XCTAssertEqual(Decisions.summary(count: 0), "Nothing waits on you.")
        XCTAssertEqual(Decisions.summary(count: 1), "1 decision waits on you.")
        XCTAssertEqual(Decisions.summary(count: 7), "7 decisions wait on you, best first.")
        XCTAssertEqual(AutoClosedText.heading(count: 1), "Teyla closed 1 question")
        XCTAssertEqual(AutoClosedText.heading(count: 3), "Teyla closed 3 questions")
    }

    func testUndoRemovesAnItemAndOneFromTheCount() {
        let closed = AutoClosed(count: 3, items: [AutoClosedItem(id: "a"), AutoClosedItem(id: "b")])
        let left = closed.remaining(undone: ["a"])
        XCTAssertEqual(left.count, 2)
        XCTAssertEqual(left.items.map(\.id), ["b"])
        XCTAssertEqual(closed.remaining(undone: []).count, 3)
        XCTAssertEqual(closed.remaining(undone: ["a", "b", "zzz"]).count, 1)
    }
}

final class HomeTextTests: XCTestCase {
    func testCaptionLabelsTheSpendAsApiEquivalent() {
        XCTAssertEqual(HomeText.caption(decisions: 2, running: 3, spend: (2127, "this week")),
                       "2 decisions waiting · 3 sessions running · $2,127 API-equivalent this week")
        XCTAssertEqual(HomeText.caption(decisions: 1, running: 1, spend: (4.1, "today")),
                       "1 decision waiting · 1 session running · $4.10 API-equivalent today")
        XCTAssertEqual(HomeText.caption(decisions: 0, running: 0, spend: nil),
                       "No decisions waiting · 0 sessions running")
    }

    func testSpendPrefersTheWeekAndFallsBackToToday() throws {
        let portfolio = try XCTUnwrap(try homeSnapshot().portfolio)
        let week = try XCTUnwrap(HomeText.spend(portfolio: portfolio, todayUSD: 5))
        XCTAssertEqual(week.window, "this week")
        XCTAssertEqual(week.usd, 860.5 + 18 + 240 + 0 + 12, accuracy: 0.001)
        let today = try XCTUnwrap(HomeText.spend(portfolio: nil, todayUSD: 5))
        XCTAssertEqual(today.window, "today")
        XCTAssertNil(HomeText.spend(portfolio: nil, todayUSD: nil))
    }

    func testCoreNoteOnlyWhenPickedByRule() {
        XCTAssertNil(HomeText.coreNote(source: "star", canStar: true))
        XCTAssertEqual(HomeText.coreNote(source: "rule", canStar: true), "Picked by usage and spend. A star sets the list by hand.")
        XCTAssertEqual(HomeText.coreNote(source: "rule", canStar: false), "Picked by usage and spend.")
    }

    func testNoPortfolioNamesTheNextStep() {
        XCTAssertTrue(HomeText.noPortfolio.contains("Update the teyla command"))
    }
}

final class CoreCardTests: XCTestCase {
    private func card(_ id: String) throws -> CoreCard {
        let portfolio = try XCTUnwrap(try homeSnapshot().portfolio)
        return CoreCards.card(try XCTUnwrap(portfolio.product(id)))
    }

    func testCardsFollowTheCoreList() throws {
        let portfolio = try XCTUnwrap(try homeSnapshot().portfolio)
        XCTAssertEqual(CoreCards.cards(portfolio).map(\.id), portfolio.core)
        var other = portfolio
        other.core = ["missing", "sample-tool"]
        XCTAssertEqual(CoreCards.cards(other).map(\.id), ["sample-tool"])
    }

    func testOnlyCurrentAndLiveBuildsAreInstallable() throws {
        let app = try card("sample-app")
        XCTAssertEqual(app.install.installable, ["iOS 1.4.0 (52)", "Web"])
        XCTAssertEqual(app.install.pending.count, 1)
        XCTAssertTrue(app.install.pending[0].hasPrefix("Android 1.3.0 (14)"))
        XCTAssertTrue(app.install.pending[0].hasSuffix("behind"))

        let tool = try card("sample-tool")
        XCTAssertEqual(tool.install.installable.count, 1)
        XCTAssertTrue(tool.install.pending[0].hasSuffix("in review"), tool.install.pending[0])

        let watch = try card("sample-watch")
        XCTAssertTrue(watch.install.installable.isEmpty)
        XCTAssertEqual(watch.install.pending.count, 1)
    }

    func testRowsWithoutABuildAreLeftOut() {
        let rows = [PlatformStatus(platform: "ios", state: "none"), PlatformStatus(platform: "web", state: "unknown")]
        XCTAssertTrue(InstallSummary(rows).isEmpty)
    }

    func testShippedUsesPluralsAndZero() throws {
        XCTAssertEqual(try card("sample-app").shipped, "14 PRs merged in 7 days")
        XCTAssertEqual(CoreCards.shippedText(prs: 1), "1 PR merged in 7 days")
        XCTAssertEqual(try card("sample-watch").shipped, "Nothing merged in 7 days")
        XCTAssertEqual(try card("sample-app").latest, "Add the privacy screen")
    }

    func testUsersShowOnlyWhenKnown() throws {
        XCTAssertEqual(try card("sample-app").users, "4 active this week, 12 total")
        XCTAssertNil(try card("sample-tool").users)
        XCTAssertNil(try card("sample-web").users, "an empty label is not a number")
    }

    func testBlockerShowsOnlyWhenNotEmpty() throws {
        XCTAssertEqual(try card("sample-app").blocker, "Developer membership lapses in 9 days")
        XCTAssertNil(try card("sample-tool").blocker)
    }

    func testQuietShowsFromFourteenDays() throws {
        XCTAssertEqual(try card("sample-watch").quiet, "Quiet for 21 days")
        XCTAssertNil(try card("sample-tool").quiet, "2 days is not quiet")
        var progress = ProductProgress(quietDays: 13, line: "x")
        var product = PortfolioProduct(id: "p")
        product.progress = progress
        XCTAssertNil(CoreCards.card(product).quiet)
        progress.quietDays = 14
        product.progress = progress
        XCTAssertEqual(CoreCards.card(product).quiet, "Quiet for 14 days")
    }

    func testTheMilestoneIsNotRepeatedWhenTheLineIsIt() throws {
        let web = try card("sample-web")
        XCTAssertEqual(web.line, "Launch page is 3 of 5 sections in.")
        XCTAssertEqual(web.milestone, "launch page: 3 of 5 sections written")
        var product = PortfolioProduct(id: "p")
        product.progress = ProductProgress(milestone: "2 of 9 left", line: "2 of 9 left")
        XCTAssertNil(CoreCards.card(product).milestone)
    }

    func testACardWithoutProgressFallsBackToTheOlderFields() {
        var product = PortfolioProduct(id: "sample-lab")
        product.milestone = "first build"
        product.prs.merged7d = 2
        let card = CoreCards.card(product)
        XCTAssertEqual(card.line, "first build")
        XCTAssertEqual(card.shipped, "2 PRs merged in 7 days")
        XCTAssertNil(card.milestone)
        XCTAssertNil(card.blocker)
    }

    func testColumnsClampBetweenOneAndThree() {
        XCTAssertEqual(CoreCards.columns(width: 0, minCard: 240, spacing: 12), 1)
        XCTAssertEqual(CoreCards.columns(width: 300, minCard: 240, spacing: 12), 1)
        XCTAssertEqual(CoreCards.columns(width: 500, minCard: 240, spacing: 12), 2)
        XCTAssertEqual(CoreCards.columns(width: 760, minCard: 240, spacing: 12), 3)
        XCTAssertEqual(CoreCards.columns(width: 2000, minCard: 240, spacing: 12), 3)
    }
}

final class CoreEditTests: XCTestCase {
    private func portfolio() throws -> Portfolio { try XCTUnwrap(try homeSnapshot().portfolio) }

    func testUnstarringRemovesOnlyThatProduct() throws {
        XCTAssertEqual(CoreEdit.toggled("sample-tool", in: try portfolio()), ["sample-app", "sample-web", "sample-watch"])
    }

    func testStarringAddsToTheStarredList() throws {
        XCTAssertEqual(CoreEdit.toggled("sample-lab", in: try portfolio()),
                       ["sample-app", "sample-tool", "sample-web", "sample-watch", "sample-lab"])
    }

    func testPickedByRulePinsTheListOnScreen() throws {
        var rule = try portfolio()
        for index in rule.products.indices { rule.products[index].focus = false }
        rule.coreSource = "rule"
        rule.core = ["sample-app", "sample-tool"]
        XCTAssertEqual(CoreEdit.toggled("sample-tool", in: rule), ["sample-app", "sample-tool"],
                       "starring a product already shown keeps the list")
        XCTAssertEqual(CoreEdit.toggled("sample-lab", in: rule), ["sample-app", "sample-tool", "sample-lab"])
    }

    func testTheListHoldsSixAndAStarCanAlwaysComeOff() throws {
        var full = try portfolio()
        full.products = (1...7).map { index in
            var product = PortfolioProduct(id: "p\(index)")
            product.focus = index <= 6
            return product
        }
        full.core = (1...6).map { "p\($0)" }
        XCTAssertFalse(CoreEdit.canToggle("p7", in: full))
        XCTAssertTrue(CoreEdit.canToggle("p6", in: full))
        XCTAssertEqual(CoreEdit.help(starred: false, source: "star", canToggle: false), CoreEdit.fullHelp)
        XCTAssertEqual(CoreEdit.help(starred: true, source: "star", canToggle: true), "Unpin from the front of its section")
        XCTAssertEqual(CoreEdit.help(starred: false, source: "rule", canToggle: true), "Pin to the front of its section")
        XCTAssertEqual(CoreEdit.help(starred: false, source: "star", canToggle: true), "Pin to the front of its section")
    }

    func testApplyingTheEditUpdatesStarsAndCoreAtOnce() throws {
        let before = try portfolio()
        let after = CoreEdit.applying(["sample-app", "sample-lab"], to: before)
        XCTAssertEqual(after.products.filter(\.focus).map(\.id), ["sample-app", "sample-lab"])
        XCTAssertEqual(after.core, ["sample-app", "sample-lab"])
        XCTAssertEqual(after.coreSource, "star")
        let cleared = CoreEdit.applying([], to: before)
        XCTAssertTrue(cleared.products.allSatisfy { !$0.focus })
        XCTAssertEqual(cleared.coreSource, "rule")
    }

    func testCommandArguments() {
        XCTAssertEqual(HomeCommands.coreArguments(ids: ["a", "b"]), ["product", "core", "a", "b"])
        XCTAssertEqual(HomeCommands.coreArguments(ids: []), ["product", "core", "--clear"])
        XCTAssertNil(HomeCommands.coreArguments(ids: ["a", "--clear"]))
        XCTAssertNil(HomeCommands.coreArguments(ids: ["has space"]))
        XCTAssertEqual(HomeCommands.undoArguments(id: "c0000001"), ["asks", "undo", "c0000001"])
        XCTAssertNil(HomeCommands.undoArguments(id: "-x"))
    }
}

// MARK: Home sections

final class HomePeriodTests: XCTestCase {
    func testThePeriodsAndTheirWords() {
        XCTAssertEqual(HomePeriod.allCases.map(\.rawValue), ["7d", "30d", "365d"])
        XCTAssertEqual(HomePeriod.allCases.map(\.label), ["Week", "Month", "Year"])
        XCTAssertEqual(HomePeriod.allCases.map(\.phrase), ["this week", "this month", "this year"])
    }

    func testAStoredValueThisBuildDoesNotKnowReadsAsWeek() {
        XCTAssertEqual(HomePeriod.from(stored: "30d"), .month)
        XCTAssertEqual(HomePeriod.from(stored: "quarter"), .week)
        XCTAssertEqual(HomePeriod.from(stored: ""), .week)
    }

    func testTheSectionTitlesAreTheOwnersWords() {
        XCTAssertEqual(HomeSectionKind.allCases.map(\.title), ["People use these", "Being built", "Quiet"])
        XCTAssertEqual(HomeSectionKind.building.note, "5 or more commits this week, no users counted yet. Most commits first")
        XCTAssertEqual(HomeSectionKind.quiet.note, "Under 5 commits this week and no new users")
    }
}

final class HomeNumbersTests: XCTestCase {
    private let dash = "\u{2014}"

    func testANumberThatIsNotCountedIsADashNeverZero() {
        XCTAssertEqual(HomeNumbers.count(nil), dash)
        XCTAssertEqual(HomeNumbers.count(0), "0")
        XCTAssertEqual(HomeNumbers.dollars(nil), dash)
        XCTAssertEqual(HomeNumbers.dollars(0), "$0")
        XCTAssertEqual(HomeNumbers.commits(nil), "\(dash) commits")
    }

    func testCountsGroupThousandsAndGoCompactFromTenThousand() {
        XCTAssertEqual(HomeNumbers.count(999), "999")
        XCTAssertEqual(HomeNumbers.count(1_010), "1,010")
        XCTAssertEqual(HomeNumbers.count(9_999), "9,999")
        XCTAssertEqual(HomeNumbers.count(10_000), "10k")
        XCTAssertEqual(HomeNumbers.count(10_400), "10.4k")
        XCTAssertEqual(HomeNumbers.count(120_000), "120k")
        XCTAssertEqual(HomeNumbers.count(1_000_000), "1M")
        XCTAssertEqual(HomeNumbers.count(1_250_000), "1.3M")
    }

    func testSpendIsWholeDollars() {
        XCTAssertEqual(HomeNumbers.dollars(957.4), "$957")
        XCTAssertEqual(HomeNumbers.dollars(2_127.5), "$2,128")
        XCTAssertEqual(HomeNumbers.dollars(4.3), "$4")
        XCTAssertEqual(HomeNumbers.dollars(12_345.67), "$12,346")
    }

    func testCommitsPluralise() {
        XCTAssertEqual(HomeNumbers.commits(1), "1 commit")
        XCTAssertEqual(HomeNumbers.commits(0), "0 commits")
        XCTAssertEqual(HomeNumbers.commits(222), "222 commits")
    }
}

final class SparklineTests: XCTestCase {
    func testNoWeeksMeansNoChart() {
        XCTAssertTrue(Sparkline.heights(weeks: []).isEmpty)
        XCTAssertNil(Sparkline.label(weeks: []))
    }

    func testTwelveRealZerosAreFlatAtTheBaseline() {
        let weeks = Array(repeating: 0, count: 12)
        XCTAssertEqual(Sparkline.heights(weeks: weeks), Array(repeating: 0.0, count: 12))
        XCTAssertEqual(Sparkline.label(weeks: weeks), "Commits per week, last 12 weeks: 0 this week")
    }

    func testBarsScaleToTheBusiestWeek() {
        XCTAssertEqual(Sparkline.heights(weeks: [0, 5, 10, 2]), [0, 0.5, 1, 0.2])
        XCTAssertEqual(Sparkline.heights(weeks: [3]), [1])
        XCTAssertEqual(Sparkline.heights(weeks: [-4, 4]), [0, 1], "a negative count reads as 0")
    }

    func testTheLabelNamesTheLatestWeek() {
        let weeks = [0, 0, 0, 10, 13, 28, 58, 60, 44, 34, 21, 135]
        XCTAssertEqual(Sparkline.label(weeks: weeks), "Commits per week, last 12 weeks: 135 this week")
    }
}

final class MonogramTests: XCTestCase {
    func testTheFirstLetterOfTheName() {
        XCTAssertEqual(Monogram.letter(for: "harbor"), "H")
        XCTAssertEqual(Monogram.letter(for: "  Sample Kit"), "S")
        XCTAssertEqual(Monogram.letter(for: "\u{00E9}cole"), "\u{00C9}")
        XCTAssertEqual(Monogram.letter(for: "42 things"), "4")
        XCTAssertEqual(Monogram.letter(for: "...x"), "X", "punctuation is skipped")
        XCTAssertEqual(Monogram.letter(for: ""), "?")
    }
}

final class HomeSectionsTests: XCTestCase {
    private func portfolio() throws -> Portfolio { try XCTUnwrap(try homeSnapshot().portfolio) }

    private func ids(_ layout: HomeLayout) -> [[String]]? {
        guard case .sections(let sections) = layout else { return nil }
        return sections.map { $0.products.map(\.id) }
    }

    func testAllThreeSectionsComeInOrderAndKeepTheCLIsRanking() throws {
        guard case .sections(let sections) = HomeSections.layout(try portfolio()) else { return XCTFail("expected sections") }
        XCTAssertEqual(sections.map(\.kind), [.users, .building, .quiet])
        XCTAssertEqual(sections.map { $0.products.map(\.id) }, [["sample-app", "sample-tool", "sample-notes"],
                                                                 ["sample-web", "sample-lab", "sample-kit"],
                                                                 ["sample-watch", "sample-old", "sample-play"]])
    }

    func testTheOrderIsTheHomeListNotTheProductListNorTheNumbers() throws {
        var other = try portfolio()
        other.products.reverse()
        other.home = PortfolioHome(sections: [HomeSectionIDs(id: "users", ids: ["sample-play", "sample-app"]),
                                              HomeSectionIDs(id: "quiet", ids: ["sample-kit"])])
        XCTAssertEqual(ids(HomeSections.layout(other)), [["sample-play", "sample-app"], [], ["sample-kit"]])
    }

    func testAnIdWithoutAProductRowIsSkipped() throws {
        var other = try portfolio()
        other.home = PortfolioHome(sections: [HomeSectionIDs(id: "users", ids: ["ghost", "sample-app"]),
                                              HomeSectionIDs(id: "building", ids: ["sample-lab", "gone"])])
        XCTAssertEqual(ids(HomeSections.layout(other)), [["sample-app"], ["sample-lab"], []])
    }

    func testAnIdInTwoSectionsStaysInTheFirst() throws {
        var other = try portfolio()
        other.home = PortfolioHome(sections: [HomeSectionIDs(id: "users", ids: ["sample-app"]),
                                              HomeSectionIDs(id: "quiet", ids: ["sample-app", "sample-old"])])
        XCTAssertEqual(ids(HomeSections.layout(other)), [["sample-app"], [], ["sample-old"]])
    }

    func testAnUnknownSectionIsIgnoredAndAMissingOneIsEmpty() throws {
        var other = try portfolio()
        other.home = PortfolioHome(sections: [HomeSectionIDs(id: "favourites", ids: ["sample-app"])])
        XCTAssertEqual(ids(HomeSections.layout(other)), [[], [], []])
        XCTAssertTrue(HomeSections.layout(other).isEmpty)
    }

    func testWithoutHomeTheCoreListIsTheFallback() throws {
        var other = try portfolio()
        other.home = nil
        guard case .legacy(let cards) = HomeSections.layout(other) else { return XCTFail("expected the fallback") }
        XCTAssertEqual(cards.map(\.id), other.core)
    }

    func testCountsNameTheNonEmptySections() throws {
        guard case .sections(let sections) = HomeSections.layout(try portfolio()) else { return XCTFail("expected sections") }
        XCTAssertEqual(HomeSections.counts(sections), "3 users, 3 building, 3 quiet")
        XCTAssertEqual(HomeSections.counts([HomeSection(kind: .users, products: []), sections[2]]), "3 quiet")
    }
}

final class HomeFactsTests: XCTestCase {
    private func product(_ id: String) throws -> PortfolioProduct {
        try XCTUnwrap(try XCTUnwrap(try homeSnapshot().portfolio).product(id))
    }

    func testAHeroReadsTheChosenPeriodAndTheTotalStaysTheTotal() throws {
        let app = try product("sample-app")
        let week = HomeFactsBuilder.facts(app, period: .week)
        XCTAssertEqual([week.active, week.new, week.total, week.commitsCount], ["4", "1", "12", "21"])
        XCTAssertEqual(week.commits, "21 commits")
        XCTAssertEqual(week.spend, "$861 agent spend this week")
        let month = HomeFactsBuilder.facts(app, period: .month)
        XCTAssertEqual([month.active, month.new, month.total, month.commitsCount], ["6", "3", "12", "80"])
        XCTAssertEqual(month.spend, "$2,900 agent spend this month")
        let year = HomeFactsBuilder.facts(app, period: .year)
        XCTAssertEqual([year.active, year.new, year.total, year.commitsCount], ["9", "9", "12", "640"])
        XCTAssertEqual(year.spend, "$9,800 agent spend this year")
    }

    func testTheSparklineAlwaysShowsTwelveWeeksWhateverThePeriod() throws {
        let app = try product("sample-app")
        let week = HomeFactsBuilder.facts(app, period: .week)
        let year = HomeFactsBuilder.facts(app, period: .year)
        XCTAssertEqual(week.sparkHeights, year.sparkHeights)
        XCTAssertEqual(week.sparkHeights.count, 12)
        XCTAssertEqual(week.sparkLabel, "Commits per week, last 12 weeks: 21 this week")
    }

    func testMonetizationReadsOffUntilItIsOn() {
        XCTAssertEqual(HomeFactsBuilder.money(MoneyMetrics()), "Off")
        XCTAssertEqual(HomeFactsBuilder.money(MoneyMetrics(enabled: false, mrrUSD: 900, paying: 4)), "Off",
                       "a disabled product shows no money even if a number slipped in")
        XCTAssertEqual(HomeFactsBuilder.money(MoneyMetrics(enabled: true, mrrUSD: 1_200, paying: 14)),
                       "$1,200 MRR \u{00B7} 14 paying")
        XCTAssertEqual(HomeFactsBuilder.money(MoneyMetrics(enabled: true)), "\u{2014} MRR \u{00B7} \u{2014} paying")
    }

    func testTheNameFallsBackToTheIdAndTheSummaryToTheProgressLine() {
        var bare = PortfolioProduct(id: "sample-lab")
        XCTAssertEqual(HomeFactsBuilder.name(bare), Format.product("sample-lab"))
        XCTAssertEqual(HomeFactsBuilder.summary(bare), "")
        bare.progress = ProductProgress(line: "Beta works.")
        XCTAssertEqual(HomeFactsBuilder.summary(bare), "Beta works.")
        bare.summary = "  Plans a race.  "
        XCTAssertEqual(HomeFactsBuilder.summary(bare), "Plans a race.")
    }

    func testAQuietRowAlwaysShowsTheSevenDayCount() throws {
        let watch = try product("sample-watch")
        XCTAssertEqual(HomeFactsBuilder.quietCommits(watch), "3 commits this week")
        XCTAssertEqual(HomeFactsBuilder.quietCommits(try product("sample-play")), "\u{2014} commits this week")
        var one = watch
        one.metrics.commits.counts.d7 = 1
        XCTAssertEqual(HomeFactsBuilder.quietCommits(one), "1 commit this week")
    }

    func testTheSpokenCardHoldsNameNumbersAndCommits() throws {
        let spoken = HomeFactsBuilder.facts(try product("sample-app"), period: .week).spoken
        XCTAssertTrue(spoken.hasPrefix("Sample App, Beta."), spoken)
        XCTAssertTrue(spoken.contains("Active users 4, new 1, 12 in total"), spoken)
        XCTAssertTrue(spoken.contains("21 commits this week"), spoken)
        XCTAssertTrue(spoken.contains("Monetization Off"), spoken)
        XCTAssertTrue(spoken.contains("Commits per week, last 12 weeks: 21 this week"), spoken)
    }

    func testNothingOnHomeShowsAPercent() throws {
        let portfolio = try XCTUnwrap(try homeSnapshot().portfolio)
        for product in portfolio.products {
            for period in HomePeriod.allCases {
                let facts = HomeFactsBuilder.facts(product, period: period)
                let text = [facts.active, facts.new, facts.total, facts.commits, facts.spend, facts.money, facts.spoken].joined()
                XCTAssertFalse(text.contains("%"), "\(product.id) \(period)")
            }
        }
    }
}

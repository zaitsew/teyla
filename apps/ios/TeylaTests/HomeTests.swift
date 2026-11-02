import UIKit
import XCTest

private func homeSnapshot(now: Date? = nil) throws -> Snapshot {
    let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Teyla/Resources/sample-state.json")
    let data = try Data(contentsOf: url)
    return try XCTUnwrap(SampleData.snapshot(from: data, now: now ?? Date()))
}

private func action(_ kind: OutboxKind, _ target: String, ok: Bool? = nil, via: String = "mac", detail: String = "") -> PendingAction {
    PendingAction(id: UUID().uuidString, kind: kind, target: target, label: target, text: "",
                  created: Date(), outcome: ok.map { .init(ok: $0, via: via, detail: detail) })
}

final class DecisionListsTests: XCTestCase {
    func testTheSampleSplitsIntoOwnerAgentAndCloseWithOneOlderQuestion() throws {
        let now = Date()
        let snapshot = try homeSnapshot(now: now)
        let lists = DecisionLists(asks: snapshot.asks, snapshot: snapshot, now: now)
        XCTAssertTrue(lists.hasTriage)
        XCTAssertEqual(lists.owner.count, 7)
        XCTAssertEqual(lists.fresh.count, 6)
        XCTAssertEqual(lists.older.map(\.id), ["a0000007"])
        XCTAssertEqual(lists.agent.map(\.id), ["a0000008", "a0000009"])
        XCTAssertEqual(lists.close.map(\.id), ["a0000010"])
    }

    func testTheOwnersQuestionsAreGroupedPayDecideDo() throws {
        let now = Date()
        let snapshot = try homeSnapshot(now: now)
        let lists = DecisionLists(asks: snapshot.asks, snapshot: snapshot, now: now)
        let groups = Decisions.grouped(lists.fresh)
        XCTAssertEqual(groups.map(\.heading).count, 3)
        XCTAssertEqual(groups.first?.asks.map(\.id), ["a0000001", "a0000002"])
    }

    func testNothingIsHiddenWhenTheMacSendsNoTriage() {
        let asks = [Ask(id: "a", product: "p", question: "A?"), Ask(id: "b", product: "p", question: "B?", ageSeconds: 20 * 86_400)]
        let snapshot = Snapshot(generated: "2026-11-02T09:00:00Z", asks: asks)
        let lists = DecisionLists(asks: asks, snapshot: snapshot, now: ISODate.parse("2026-11-02T09:00:00Z")!)
        XCTAssertFalse(lists.hasTriage)
        XCTAssertEqual(lists.fresh.map(\.id), ["a"])
        XCTAssertEqual(lists.older.map(\.id), ["b"])
        XCTAssertTrue(lists.agent.isEmpty)
        XCTAssertTrue(lists.close.isEmpty)
    }

    func testTheHomeListShowsFiveOfTheFreshOnes() throws {
        let now = Date()
        let snapshot = try homeSnapshot(now: now)
        let lists = DecisionLists(asks: snapshot.asks, snapshot: snapshot, now: now)
        XCTAssertEqual(Decisions.homeList(lists.fresh).count, 5)
        XCTAssertEqual(Decisions.seeAll(total: lists.owner.count, shown: 5), "See all 7")
    }

    func testAPayQuestionNeverOffersTheDefault() throws {
        let snapshot = try homeSnapshot()
        let pay = try XCTUnwrap(snapshot.asks.first { $0.id == "a0000001" })
        XCTAssertEqual(pay.decisionGroup, .pay)
        XCTAssertFalse(pay.canUseProposedAnswer)
        let decide = try XCTUnwrap(snapshot.asks.first { $0.id == "a0000003" })
        XCTAssertTrue(decide.canUseProposedAnswer)
        XCTAssertEqual(decide.proposedAnswer, "Yes")
    }
}

/// The sample state as JSON, for tests that change it before it is decoded.
private func sampleObject() throws -> [String: Any] {
    let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Teyla/Resources/sample-state.json")
    return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [String: Any])
}

/// What a Mac before 0.36 sends: a portfolio with no `home`, and no `summary`, `icon_jpeg` or `metrics` on a product.
private func stateFromAnOlderMac() throws -> Snapshot {
    var root = try sampleObject()
    var portfolio = try XCTUnwrap(root["portfolio"] as? [String: Any])
    portfolio["home"] = nil
    portfolio["products"] = try XCTUnwrap(portfolio["products"] as? [[String: Any]]).map { product in
        var product = product
        for key in ["summary", "icon_jpeg", "metrics"] { product[key] = nil }
        return product
    }
    root["portfolio"] = portfolio
    return try PhoneFormat.decodeSnapshot(JSONSerialization.data(withJSONObject: root))
}

final class PhoneHomeTests: XCTestCase {
    func testAnOlderMacWithNoHomeSectionsAsksForAnUpdate() throws {
        XCTAssertTrue(PhoneHome.needsMacUpdate(nil))
        XCTAssertTrue(PhoneHome.needsMacUpdate(Portfolio()))
        XCTAssertNil(PhoneHome.sections(nil))
        let old = try stateFromAnOlderMac()
        let portfolio = try XCTUnwrap(old.portfolio)
        XCTAssertEqual(portfolio.products.count, 18, "the products still decode")
        XCTAssertTrue(portfolio.products.allSatisfy { $0.summary.isEmpty && $0.iconJPEG.isEmpty })
        XCTAssertTrue(PhoneHome.needsMacUpdate(portfolio), "a Teyla before the sections sends no portfolio.home")
        XCTAssertNil(PhoneHome.sections(portfolio), "and the phone ranks nothing itself")
    }

    func testAnOlderMacStillGetsItsDecisionsAndItsCardsFacts() throws {
        // Nothing but the products' numbers is missing: every card reads "—", never zero, and never fails.
        let old = try XCTUnwrap(stateFromAnOlderMac().portfolio)
        let facts = HomeFactsBuilder.facts(try XCTUnwrap(old.product("sample-app")), period: .week)
        XCTAssertEqual([facts.active, facts.new, facts.total], ["\u{2014}", "\u{2014}", "\u{2014}"])
        XCTAssertEqual(facts.money, "Off")
        XCTAssertNil(facts.sparkLabel)
    }

    func testANewerMacIsNotAnUpdateProblem() throws {
        let portfolio = try XCTUnwrap(homeSnapshot().portfolio)
        XCTAssertFalse(PhoneHome.needsMacUpdate(portfolio))
        // A Mac that sends the sections with nobody in them is up to date; Home says there are no products.
        let empty = Portfolio(home: PortfolioHome(sections: []))
        XCTAssertFalse(PhoneHome.needsMacUpdate(empty))
        XCTAssertTrue(try XCTUnwrap(PhoneHome.sections(empty)).allSatisfy { $0.products.isEmpty })
    }

    func testTheSampleHasAllThreeSectionsInTheOrderTheMacSent() throws {
        let portfolio = try XCTUnwrap(homeSnapshot().portfolio)
        let sections = try XCTUnwrap(PhoneHome.sections(portfolio))
        XCTAssertEqual(sections.map(\.kind), [.users, .building, .quiet])
        XCTAssertEqual(sections.map(\.products.count), [3, 8, 7])
        XCTAssertEqual(sections.map { $0.kind.title }, ["People use these", "Being built", "Quiet"])
        // The phone never re-ranks: the ids are exactly the ones in portfolio.home, in that order.
        let sent = try XCTUnwrap(portfolio.home).sections.map(\.ids)
        XCTAssertEqual(sections.map { $0.products.map(\.id) }, sent)
        // Every product sits in exactly one section.
        XCTAssertEqual(sections.flatMap { $0.products.map(\.id) }.count, portfolio.products.count)
        XCTAssertEqual(Set(sections.flatMap { $0.products.map(\.id) }).count, portfolio.products.count)
    }

    func testTheSectionNotesAreTheRulesThatPutAProductThere() {
        XCTAssertEqual(HomeSectionKind.building.note, "5 or more commits this week, no users counted yet. Most commits first")
        XCTAssertEqual(HomeSectionKind.quiet.note, "Under 5 commits this week and no new users")
        XCTAssertEqual(PhoneHome.decisionsNote, "Only you can answer these")
    }

    func testTheBriefIsTheMacsSentenceOrACount() throws {
        let snapshot = try homeSnapshot()
        XCTAssertEqual(PhoneHome.briefLine(snapshot), "7 decisions wait for you. Two of them are payments that block the next store upload.")
        let bare = Snapshot(generated: "2026-11-02T09:00:00Z", asks: [Ask(id: "a", product: "p", question: "A?")])
        XCTAssertEqual(PhoneHome.briefLine(bare), "1 question needs you.")
        XCTAssertEqual(PhoneHome.briefLine(Snapshot(generated: "2026-11-02T09:00:00Z")), "Nothing needs you right now.")
    }
}

final class HomeSectionsOnThePhoneTests: XCTestCase {
    private func sections() throws -> [HomeSection] {
        try XCTUnwrap(PhoneHome.sections(XCTUnwrap(homeSnapshot().portfolio)))
    }

    private func products(_ kind: HomeSectionKind) throws -> [PortfolioProduct] {
        try XCTUnwrap(sections().first { $0.kind == kind }).products
    }

    func testBeingBuiltShowsSixThenAllAndQuietShowsFiveThenAll() throws {
        let building = try products(.building)
        let quiet = try products(.quiet)
        XCTAssertEqual(HomeFold.visible(building, kind: .building, expanded: false).count, 6)
        XCTAssertEqual(HomeFold.visible(building, kind: .building, expanded: true).count, building.count)
        XCTAssertEqual(HomeFold.visible(quiet, kind: .quiet, expanded: false).count, 5)
        XCTAssertEqual(HomeFold.visible(quiet, kind: .quiet, expanded: true).count, quiet.count)
        // The first rows are the same folded or open: opening only adds.
        XCTAssertEqual(HomeFold.visible(building, kind: .building, expanded: true).prefix(6).map(\.id),
                       HomeFold.visible(building, kind: .building, expanded: false).map(\.id))
    }

    func testTheButtonSaysTheRealCount() throws {
        let building = try products(.building)
        let quiet = try products(.quiet)
        XCTAssertEqual(HomeFold.toggleLabel(kind: .building, total: building.count, expanded: false), "Show all 8")
        XCTAssertEqual(HomeFold.toggleLabel(kind: .quiet, total: quiet.count, expanded: false), "Show all 7")
        XCTAssertEqual(HomeFold.toggleLabel(kind: .building, total: 15, expanded: false), "Show all 15")
        XCTAssertEqual(HomeFold.toggleLabel(kind: .quiet, total: 20, expanded: false), "Show all 20")
        XCTAssertEqual(HomeFold.toggleLabel(kind: .quiet, total: 20, expanded: true), "Show fewer")
    }

    func testNoButtonWhenNothingIsHidden() {
        XCTAssertNil(HomeFold.toggleLabel(kind: .building, total: 6, expanded: false))
        XCTAssertNil(HomeFold.toggleLabel(kind: .quiet, total: 5, expanded: false))
        XCTAssertNil(HomeFold.toggleLabel(kind: .quiet, total: 0, expanded: true))
        XCTAssertNil(HomeFold.toggleLabel(kind: .users, total: 40, expanded: false), "heroes are never folded")
        XCTAssertEqual(HomeFold.visible(Array(repeating: PortfolioProduct(id: "p"), count: 9), kind: .users, expanded: false).count, 9)
    }

    func testTheSwitchNeverMovesAProduct() throws {
        let before = try sections().map { $0.products.map(\.id) }
        for period in HomePeriod.allCases {
            for section in try sections() {
                for product in section.products { _ = HomeFactsBuilder.facts(product, period: period) }
            }
            XCTAssertEqual(try sections().map { $0.products.map(\.id) }, before, "\(period.label) reordered the page")
        }
        // The numbers do change with the period; that is all the switch does.
        let hero = try XCTUnwrap(products(.users).first)
        let week = HomeFactsBuilder.facts(hero, period: .week)
        let year = HomeFactsBuilder.facts(hero, period: .year)
        XCTAssertNotEqual(week.commitsCount, year.commitsCount)
        XCTAssertNotEqual(week.active, year.active)
        XCTAssertEqual(week.total, year.total, "users in total do not depend on the period")
    }

    func testAStoredPeriodThatThisBuildDoesNotKnowReadsAsWeek() {
        XCTAssertEqual(HomePeriod.from(stored: "7d"), .week)
        XCTAssertEqual(HomePeriod.from(stored: "365d"), .year)
        XCTAssertEqual(HomePeriod.from(stored: "quarter"), .week)
        XCTAssertEqual(HomePeriod.from(stored: ""), .week)
    }

    func testANumberNobodyCountedShowsADashNeverZero() throws {
        let dash = "\u{2014}"
        let all = try sections().flatMap(\.products)
        let blank = try XCTUnwrap(all.first { $0.id == "basalt" })
        let facts = HomeFactsBuilder.facts(blank, period: .week)
        XCTAssertEqual([facts.active, facts.new, facts.total, facts.commitsCount], [dash, dash, dash, dash])
        XCTAssertEqual(facts.commits, "\(dash) commits")
        XCTAssertEqual(HomeFactsBuilder.quietCommits(blank), "\(dash) commits this week")
        XCTAssertEqual(facts.spend, "Agent spend: not counted yet")
        XCTAssertNil(facts.sparkLabel, "no weeks, no chart")
        XCTAssertTrue(facts.sparkHeights.isEmpty)
        // One missing number does not hide the others: sample-web has users but no count of new ones.
        let web = HomeFactsBuilder.facts(try XCTUnwrap(all.first { $0.id == "sample-web" }), period: .week)
        XCTAssertEqual(web.new, dash)
        XCTAssertEqual(web.active, "1")
    }

    func testAZeroThatWasCountedStaysZero() throws {
        let all = try sections().flatMap(\.products)
        let tool = HomeFactsBuilder.facts(try XCTUnwrap(all.first { $0.id == "sample-tool" }), period: .week)
        XCTAssertEqual(tool.new, "0")
        let quiet = HomeFactsBuilder.facts(try XCTUnwrap(all.first { $0.id == "thistle" }), period: .week)
        XCTAssertEqual(quiet.commitsCount, "0")
        XCTAssertEqual(quiet.sparkHeights, Array(repeating: 0, count: 12), "twelve real zeros are twelve flat bars")
    }

    func testMonetizationReadsOffForEveryProductInTheSample() throws {
        for product in try sections().flatMap(\.products) {
            let facts = HomeFactsBuilder.facts(product, period: .month)
            XCTAssertEqual(facts.money, "Off", product.id)
            XCTAssertFalse(facts.moneyEnabled)
        }
        var paid = try XCTUnwrap(products(.users).first)
        paid.metrics.money = MoneyMetrics(enabled: true, mrrUSD: 1_200, paying: 14)
        XCTAssertEqual(HomeFactsBuilder.facts(paid, period: .week).money, "$1,200 MRR \u{00B7} 14 paying")
    }

    func testNothingOnHomeShowsAPercentOrAHealthWord() throws {
        for product in try sections().flatMap(\.products) {
            let facts = HomeFactsBuilder.facts(product, period: .week)
            let text = [facts.spoken, facts.spend, facts.commits, facts.money, facts.stage, facts.summary,
                        HomeFactsBuilder.quietCommits(product)].joined(separator: " ")
            XCTAssertFalse(text.contains("%"), product.id)
            for word in ["on track", "at risk", "off track", "parked"] { XCTAssertFalse(text.lowercased().contains(word), "\(product.id): \(word)") }
        }
    }

    func testAnIdWithoutAProductAndAnIdListedTwiceAreHandledByTheSharedLogic() {
        let rows = [PortfolioProduct(id: "a"), PortfolioProduct(id: "b")]
        let home = PortfolioHome(sections: [HomeSectionIDs(id: "users", ids: ["a", "ghost"]),
                                            HomeSectionIDs(id: "building", ids: ["a", "b"])])
        let sections = PhoneHome.sections(Portfolio(products: rows, home: home))
        XCTAssertEqual(sections?.map { $0.products.map(\.id) }, [["a"], ["b"], []])
    }
}

@MainActor
final class ProductIconsOnThePhoneTests: XCTestCase {
    override func setUp() {
        super.setUp()
        ProductIcons.reset()
    }

    /// A small JPEG of the given side, made here so no real icon sits in the repo. Another side is another string.
    private func jpeg(side: Int) throws -> String {
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        let image = UIGraphicsImageRenderer(size: CGSize(width: side, height: side), format: format).image { context in
            UIColor.systemIndigo.setFill()
            context.fill(CGRect(x: 0, y: 0, width: side, height: side))
        }
        return try XCTUnwrap(image.jpegData(compressionQuality: 0.8)).base64EncodedString()
    }

    func testAnIconIsDecodedOncePerProductNoMatterHowOftenHomeRedraws() throws {
        let icon = try jpeg(side: 8)
        let first = try XCTUnwrap(ProductIcons.image(id: "a", base64: icon))
        for _ in 0..<50 { XCTAssertTrue(ProductIcons.image(id: "a", base64: icon) === first) }
        XCTAssertEqual(ProductIcons.decodeCount, 1)
        XCTAssertNotNil(ProductIcons.image(id: "b", base64: icon))
        XCTAssertEqual(ProductIcons.decodeCount, 2)
    }

    func testANewIconForTheSameProductIsDecodedAgain() throws {
        _ = ProductIcons.image(id: "a", base64: try jpeg(side: 8))
        _ = ProductIcons.image(id: "a", base64: try jpeg(side: 16))
        XCTAssertEqual(ProductIcons.decodeCount, 2)
    }

    func testNoIconAndABrokenIconBothMeanAMonogram() {
        XCTAssertNil(ProductIcons.image(id: "a", base64: ""))
        XCTAssertEqual(ProductIcons.decodeCount, 0, "an empty string is not worth a decode")
        XCTAssertNil(ProductIcons.image(id: "a", base64: "not base64 at all!"))
        XCTAssertNil(ProductIcons.image(id: "a", base64: "not base64 at all!"))
        XCTAssertEqual(ProductIcons.decodeCount, 1, "a broken icon is remembered as broken")
    }

    func testTheSampleIconsDecodeAndTheRestGetAMonogram() throws {
        let portfolio = try XCTUnwrap(homeSnapshot().portfolio)
        let withIcon = portfolio.products.filter { !$0.iconJPEG.isEmpty }
        XCTAssertGreaterThanOrEqual(withIcon.count, 4)
        XCTAssertTrue(withIcon.allSatisfy { ProductIcons.image(id: $0.id, base64: $0.iconJPEG) != nil })
        XCTAssertEqual(ProductIcons.decodeCount, withIcon.count)
        XCTAssertLessThan(withIcon.count, portfolio.products.count, "some products show their first letter")
    }
}

final class CloseTrackingTests: XCTestCase {
    func testAWaitingCloseIsNotClosed() {
        let progress = CloseTracking.progress([action(.close, "a"), action(.close, "b")])
        XCTAssertEqual(progress.waiting, 2)
        XCTAssertTrue(progress.closed.isEmpty)
        XCTAssertEqual(CloseTracking.line(progress), "Closing 2\u{2026}")
    }

    func testAcceptedClosesCanBeUndoneAndAReopenTakesThemBack() {
        let closed = CloseTracking.progress([action(.close, "a", ok: true), action(.close, "b", ok: true)])
        XCTAssertEqual(closed.closed, ["a", "b"])
        XCTAssertEqual(CloseTracking.line(closed), "Closed 2")

        let partly = CloseTracking.progress([action(.close, "a", ok: true), action(.close, "b", ok: true),
                                             action(.reopen, "a", ok: true)])
        XCTAssertEqual(partly.closed, ["b"])
        let reopening = CloseTracking.progress([action(.close, "a", ok: true), action(.reopen, "a")])
        XCTAssertEqual(reopening.reopening, 1)
        XCTAssertEqual(CloseTracking.line(reopening), "Reopening 1\u{2026}")
    }

    func testAReopenOfTeylasOwnCloseIsNotCountedHere() {
        let progress = CloseTracking.progress([action(.reopen, "c0000001")])
        XCTAssertTrue(progress.isEmpty)
    }

    func testAFailureIsShownInWords() {
        let progress = CloseTracking.progress([action(.close, "a", ok: false, detail: "no such question")])
        XCTAssertNotNil(progress.failure)
        XCTAssertTrue(progress.closed.isEmpty)
    }

    func testAnOldMacThatRefusesTheKindIsToldToUpdate() {
        let outcome = PendingAction.Outcome(ok: false, via: "mac", detail: "malformed entry: kind")
        XCTAssertEqual(CloseTracking.failureLine(outcome), "This Mac's Teyla cannot do that yet. Update Teyla on your Mac.")
    }

    func testASampleCloseIsSimulatedNotClosed() {
        let progress = CloseTracking.progress([action(.close, "a", ok: true, via: SampleData.via)])
        XCTAssertTrue(progress.simulated)
        XCTAssertTrue(progress.closed.isEmpty)
    }
}

final class CloseEntryTests: XCTestCase {
    private func entry(_ kind: OutboxKind, target: String) throws -> OutboxEntry {
        try OutboxEntry.make(kind: kind, target: target, aboutText: target, text: "close", device: "phone",
                             key: Data(repeating: 7, count: 32))
    }

    func testCloseAndReopenNameOneQuestion() {
        XCTAssertEqual(try entry(.close, target: "7c222b3d").kind, .close)
        XCTAssertEqual(try entry(.reopen, target: "7c222b3d").kind, .reopen)
    }

    func testATargetThatLooksLikeAnOptionIsRefused() {
        XCTAssertThrowsError(try entry(.close, target: "--all"))
        XCTAssertThrowsError(try entry(.reopen, target: "-x"))
        XCTAssertThrowsError(try entry(.close, target: ".hidden"))
    }
}

@MainActor
final class CloseFlowTests: XCTestCase {
    private struct NoKeyStore: KeyStore {
        func load() -> Data? { nil }
        func save(_ key: Data) throws {}
        func delete() {}
    }

    private func model() -> AppModel {
        let defaults = UserDefaults(suiteName: "CloseFlowTests-\(UUID().uuidString)")!
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Teyla/Resources/sample-state.json")
        return AppModel(environment: ["TEYLA_SAMPLE": "1"], defaults: defaults, keyStore: NoKeyStore(),
                        sampleData: { try? Data(contentsOf: url) })
    }

    func testClosingAndReopeningNeverAppearAsLooseSentCards() async throws {
        let model = model()
        await model.refresh()
        let snapshot = try XCTUnwrap(model.snapshot)
        let ask = try XCTUnwrap(snapshot.asks.first { $0.id == "a0000010" })
        await model.acceptClose([ask])
        _ = await model.reopen(id: ask.id, label: ask.title)
        XCTAssertTrue(model.sentWithoutCard(in: snapshot).isEmpty)
    }

    func testOneRequestPerQuestionAndNoSecondRequestWhileOneWaits() async throws {
        let model = model()
        await model.refresh()
        let snapshot = try XCTUnwrap(model.snapshot)
        let ask = try XCTUnwrap(snapshot.asks.first { $0.id == "a0000010" })
        await model.acceptClose([ask])
        await model.acceptClose([ask])
        XCTAssertEqual(model.pending.filter { $0.kind == .close }.count, 1)
    }

    func testTeylasOwnClosesStayListedInTheSample() async throws {
        let model = model()
        await model.refresh()
        XCTAssertEqual(model.autoClosed.count, 3)
        _ = await model.reopen(id: "c0000001", label: "Is the beta build installable?")
        XCTAssertEqual(model.autoClosed.count, 3, "a sample reopen changes nothing")
    }
}

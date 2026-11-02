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

final class PhoneHomeTests: XCTestCase {
    func testAnOlderMacWithNoCoreListAsksForAnUpdate() throws {
        XCTAssertTrue(PhoneHome.needsMacUpdate(nil))
        XCTAssertTrue(PhoneHome.needsMacUpdate(Portfolio()))
        let old = try PhoneFormat.decodeSnapshot(Data(contentsOf: URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("mac/TeylaTests/Fixtures/state.sample.v3.json")))
        XCTAssertTrue(PhoneHome.needsMacUpdate(old.portfolio), "a Teyla before core products sends no core list")
    }

    func testANewerMacWithNoCoreProductsYetIsNotAnUpdateProblem() {
        XCTAssertFalse(PhoneHome.needsMacUpdate(Portfolio(core: [], coreSource: "auto")))
    }

    func testTheSampleHasFourCoreCardsWithFacts() throws {
        let snapshot = try homeSnapshot()
        let portfolio = try XCTUnwrap(snapshot.portfolio)
        XCTAssertFalse(PhoneHome.needsMacUpdate(portfolio))
        let cards = CoreCards.cards(portfolio)
        XCTAssertEqual(cards.map(\.id), ["sample-app", "sample-tool", "sample-web", "sample-watch"])
    }

    func testTheBriefIsTheMacsSentenceOrACount() throws {
        let snapshot = try homeSnapshot()
        XCTAssertEqual(PhoneHome.briefLine(snapshot), "7 decisions wait for you. Two of them are payments that block the next store upload.")
        let bare = Snapshot(generated: "2026-11-02T09:00:00Z", asks: [Ask(id: "a", product: "p", question: "A?")])
        XCTAssertEqual(PhoneHome.briefLine(bare), "1 question needs you.")
        XCTAssertEqual(PhoneHome.briefLine(Snapshot(generated: "2026-11-02T09:00:00Z")), "Nothing needs you right now.")
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

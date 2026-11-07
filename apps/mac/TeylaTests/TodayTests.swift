import XCTest

final class GtmDecodingTests: XCTestCase {
    private func full() throws -> GtmToday { try GtmToday.decode(SampleFiles.data("gtm-today.v1.json")) }

    func testDecodesTheFixture() throws {
        let today = try full()
        XCTAssertEqual(today.version, 1)
        XCTAssertEqual(today.day, "2026-11-07")
        XCTAssertEqual(today.week, "2026-W45")
        XCTAssertTrue(today.hasGoals)
        XCTAssertEqual(today.approve.total, 6)
        XCTAssertEqual(today.approve.bySource["growth"], 4)
        XCTAssertEqual(today.reply.links["outreach"], "https://example.com/outreach/inbox")
        XCTAssertEqual(today.followUp.total, 1)
        XCTAssertEqual(today.distribution.today, 3)
        XCTAssertEqual(today.distribution.target, 10)
        XCTAssertEqual(today.distribution.week, 21)
        XCTAssertEqual(today.distribution.claimedByAgents, 1)
        XCTAssertEqual(today.preparationWeek, 283)
        XCTAssertEqual(today.outcomesWeek, 9)
        XCTAssertEqual(today.goals.count, 2)
        XCTAssertEqual(today.goals[0].daysLeft, 114)
        XCTAssertEqual(today.goals[0].targets.map(\.stage), ["approached", "conversation", "intro"])
        XCTAssertEqual(today.next.map(\.kind), ["reply", "approve", "send", "follow_up", "distribute"])
        XCTAssertEqual(today.next[1].command, "teyla growth review")
        XCTAssertEqual(today.sources.count, 3)
        XCTAssertEqual(today.doctor.count, 1)
    }

    func testANullTargetAndMissingFieldsTakeDefaults() throws {
        let json = #"""
        {"version": 1, "day": "2026-11-07", "distribution": {"today": 2, "target": null},
         "goals": [{"id": "g", "deadline": null, "days_left": null, "targets": [{"stage": "intro"}]}],
         "next": [{"kind": "reply"}], "somethingNew": [1, 2]}
        """#
        let today = try GtmToday.decode(Data(json.utf8))
        XCTAssertNil(today.distribution.target)
        XCTAssertEqual(today.distribution.today, 2)
        XCTAssertEqual(today.distribution.week, 0)
        XCTAssertFalse(today.hasGoals)
        XCTAssertEqual(today.approve, GtmWaiting())
        XCTAssertEqual(today.outcomesWeek, 0)
        XCTAssertEqual(today.goals[0].title, "g")
        XCTAssertNil(today.goals[0].daysLeft)
        XCTAssertEqual(today.goals[0].targets, [GtmTarget(stage: "intro", count: 0, target: 0)])
        XCTAssertEqual(today.next[0].label, "reply")
        XCTAssertTrue(today.doctor.isEmpty)
    }

    func testAWaitingTotalFallsBackToTheSourceSum() throws {
        let json = #"{"approve": {"by_source": {"a": 2, "b": 3}}}"#
        XCTAssertEqual(try GtmToday.decode(Data(json.utf8)).approve.total, 5)
    }

    func testADamagedGoalIsSkippedNotFatal() throws {
        let json = #"{"goals": [{"title": "no id"}, {"id": "ok", "title": "Fine"}]}"#
        XCTAssertEqual(try GtmToday.decode(Data(json.utf8)).goals.map(\.id), ["ok"])
    }

    func testNotJSONIsABadOutputError() {
        XCTAssertThrowsError(try GtmToday.decode(Data("usage: teyla gtm".utf8))) { error in
            guard case TeylaError.badOutput = error else { return XCTFail("\(error)") }
        }
    }

    func testNothingOnTheContractCountsCommits() throws {
        let text = String(decoding: try SampleFiles.data("gtm-today.v1.json"), as: UTF8.self).lowercased()
        XCTAssertFalse(text.contains("commit"))
    }

    func testSourcesAreSortedBiggestFirst() throws {
        XCTAssertEqual(try full().approve.sources.map(\.id), ["growth", "outreach"])
    }
}

final class GtmBackendTests: XCTestCase {
    func testAPreviewReadsTheFixtureBesideTheStateSample() async throws {
        let cli = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": SampleFiles.url("state.sample.v3.json").path])
        let today = try await cli.gtmToday()
        XCTAssertEqual(today.distribution.target, 10)
    }

    func testTheFixtureVariableWins() async throws {
        let cli = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": SampleFiles.url("state.sample.v3.json").path,
                                 "TEYLA_GTM_FIXTURE": SampleFiles.url("gtm-today.v1.json").path])
        let today = try await cli.gtmToday()
        XCTAssertEqual(today.goals.count, 2)
    }

    func testAnOlderCommandReadsAsUpdateNotAsFailure() async {
        // A preview with no sample file answers as a `teyla` without `gtm` would.
        let cli = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": SampleFiles.url("state.sample.v3.json").path,
                                 "TEYLA_GTM_FIXTURE": SampleFiles.url("does-not-exist.json").path])
        do {
            _ = try await cli.gtmToday()
            XCTFail("expected unavailable")
        } catch {
            XCTAssertEqual(error as? TeylaError, .unavailable("Update the teyla command to see Today."))
            XCTAssertEqual(error.localizedDescription, "Update the teyla command to see Today.")
        }
    }
}

final class TodayRouteTests: XCTestCase {
    func testTheAdminBuildOpensOnTodayAndTheStoreBuildOnHome() {
        XCTAssertEqual(AppRoute.initial(capabilities: .full), .today)
        XCTAssertEqual(AppRoute.initial(capabilities: .store), .home)
    }

    func testTodayIsNotAConsoleSection() {
        XCTAssertFalse(AppRoute.today.isConsole)
    }

    func testTheLayoutDefaultsToQueue() {
        XCTAssertEqual(TodayLayout.stored(nil), .queue)
        XCTAssertEqual(TodayLayout.stored("board"), .board)
        XCTAssertEqual(TodayLayout.stored("nonsense"), .queue)
        XCTAssertEqual(TodayLayout.key, "teyla.today.layout")
    }
}

final class TodayLogicTests: XCTestCase {
    func testLettersMapToActionsInEitherCase() {
        XCTAssertEqual(TodayLogic.action(for: "a"), .approve)
        XCTAssertEqual(TodayLogic.action(for: "A"), .approve)
        XCTAssertEqual(TodayLogic.action(for: "s"), .skip)
        XCTAssertEqual(TodayLogic.action(for: "o"), .open)
        XCTAssertEqual(TodayLogic.action(for: "j"), .next)
        XCTAssertEqual(TodayLogic.action(for: "k"), .previous)
        XCTAssertNil(TodayLogic.action(for: "x"))
        XCTAssertNil(TodayLogic.action(for: ""))
        XCTAssertNil(TodayLogic.action(for: "r"), "R alone does nothing: only ⌘R refreshes")
    }

    func testMovingStaysInsideTheList() {
        XCTAssertEqual(TodayLogic.moved(0, by: 1, count: 3), 1)
        XCTAssertEqual(TodayLogic.moved(2, by: 1, count: 3), 2)
        XCTAssertEqual(TodayLogic.moved(0, by: -1, count: 3), 0)
        XCTAssertEqual(TodayLogic.moved(nil, by: 1, count: 3), 0)
        XCTAssertEqual(TodayLogic.moved(nil, by: -1, count: 3), 2)
        XCTAssertNil(TodayLogic.moved(0, by: 1, count: 0))
    }

    func testSkipMovesOnAndNeverChangesTheDraft() {
        XCTAssertEqual(TodayLogic.skipped(0, count: 3), 1)
        XCTAssertEqual(TodayLogic.skipped(2, count: 3), 2)
        XCTAssertNil(TodayLogic.skipped(0, count: 0))
    }

    func testSelectionStaysOnTheSameDraftWhenOthersLeave() {
        XCTAssertEqual(TodayLogic.settled(selected: "b", old: ["a", "b", "c"], new: ["b", "c"]), "b")
    }

    func testAnApprovedDraftHandsTheSelectionToTheOneThatTookItsPlace() {
        XCTAssertEqual(TodayLogic.settled(selected: "b", old: ["a", "b", "c"], new: ["a", "c"]), "c")
        XCTAssertEqual(TodayLogic.settled(selected: "c", old: ["a", "b", "c"], new: ["a", "b"]), "b")
        XCTAssertEqual(TodayLogic.settled(selected: nil, old: [], new: ["a", "b"]), "a")
        XCTAssertNil(TodayLogic.settled(selected: "a", old: ["a"], new: []))
    }

    func testOnlyWebLinksOpen() {
        XCTAssertNotNil(TodayLogic.webLink("https://example.com/q"))
        XCTAssertNotNil(TodayLogic.webLink("http://example.com"))
        XCTAssertNil(TodayLogic.webLink("file:///etc/passwd"))
        XCTAssertNil(TodayLogic.webLink("javascript:alert(1)"))
        XCTAssertNil(TodayLogic.webLink("not a link"))
        XCTAssertNil(TodayLogic.webLink(nil))
    }

    func testTheDistributionReadsWithAndWithoutATarget() {
        XCTAssertEqual(TodayLogic.distributionFigure(GtmDistribution(today: 3, target: 10)), "3 of 10")
        XCTAssertEqual(TodayLogic.distributionFigure(GtmDistribution(today: 3, target: nil)), "3")
        XCTAssertNil(TodayLogic.distributionFraction(GtmDistribution(today: 3, target: nil)))
        XCTAssertEqual(TodayLogic.distributionFraction(GtmDistribution(today: 20, target: 10)), 1)
        XCTAssertTrue(TodayLogic.distributionSpoken(GtmDistribution(today: 3, target: nil)).contains("no daily target"))
        XCTAssertTrue(TodayLogic.distributionDetail(GtmDistribution(today: 3, target: 10, week: 21, claimedByAgents: 2)).contains("claimed by agents"))
    }

    func testCountsReadAsSentences() throws {
        let today = try GtmToday.decode(SampleFiles.data("gtm-today.v1.json"))
        XCTAssertEqual(TodayLogic.waitingTotal(today), 14)
        XCTAssertEqual(TodayLogic.waitingWords("reply", count: 1), "1 reply to answer")
        XCTAssertEqual(TodayLogic.waitingWords("reply", count: 2), "2 replies to answer")
        XCTAssertEqual(TodayLogic.waitingSpoken(today), "14 items wait for you: 6 drafts to approve, 5 items to send, 2 replies to answer, 1 follow-up due.")
        XCTAssertEqual(TodayLogic.outcomesSpoken(today), "9 outcomes this week, 1 today.")
        XCTAssertEqual(TodayLogic.waitingSpoken(GtmToday()), "Nothing waits for you.")
    }

    func testGoalsReadWithDaysLeft() throws {
        let goal = try GtmToday.decode(SampleFiles.data("gtm-today.v1.json")).goals[1]
        XCTAssertEqual(TodayLogic.daysLeftWords(38), "38 days left")
        XCTAssertEqual(TodayLogic.daysLeftWords(1), "1 day left")
        XCTAssertEqual(TodayLogic.daysLeftWords(0), "Due today")
        XCTAssertEqual(TodayLogic.daysLeftWords(-3), "Past the deadline")
        XCTAssertNil(TodayLogic.daysLeftWords(nil))
        XCTAssertEqual(TodayLogic.goalSpoken(goal), "Activated testers. 12 of 20 signed up, 4 of 10 activated this week. 38 days left")
        XCTAssertEqual(TodayLogic.fraction(GtmTarget(stage: "x", count: 5, target: 0)), 0)
        XCTAssertEqual(TodayLogic.fraction(GtmTarget(stage: "x", count: 30, target: 15)), 1)
    }

    func testTheOpenTargetIsTheFirstWebSource() throws {
        let boxes = try JSONDecoder().decode([LossyBox<GrowthDraft>].self, from: SampleFiles.data("growth.v1.json"))
        let drafts = boxes.compactMap(\.value)
        XCTAssertEqual(TodayLogic.openTarget(drafts[0])?.absoluteString, "https://example.com/sample-app/pull/12")
        // A source that is only a reference (no web address) opens nothing.
        let session = try XCTUnwrap(drafts.first { $0.sources.first?.link == "session-0412" })
        XCTAssertNil(TodayLogic.openTarget(session))
    }
}

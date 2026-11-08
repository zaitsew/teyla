import XCTest

final class GtmDecodingTests: XCTestCase {
    private func full() throws -> GtmToday { try GtmToday.decode(SampleFiles.data("gtm-today.v1.json")) }

    func testDecodesTheFixture() throws {
        let today = try full()
        XCTAssertEqual(today.version, 1)
        XCTAssertEqual(today.day, "2026-11-07")
        XCTAssertEqual(today.week, "2026-W45")
        XCTAssertTrue(today.hasGoals)
        XCTAssertEqual(today.weekEnd, "2026-11-08")
        XCTAssertEqual(today.approve.total, 22)
        XCTAssertEqual(today.approve.bySource["growth"], 20)
        XCTAssertEqual(today.reply.links["outreach"], "https://example.com/outreach/inbox")
        XCTAssertEqual(today.followUp.total, 0)
        XCTAssertEqual(today.distribution.today, 3)
        XCTAssertEqual(today.distribution.target, 10)
        XCTAssertEqual(today.distribution.week, 21)
        XCTAssertEqual(today.distribution.claimedByAgents, 1)
        XCTAssertEqual(today.preparationWeek, 283)
        XCTAssertEqual(today.outcomesWeek, 1)
        XCTAssertEqual(today.goals.count, 3)
        XCTAssertEqual(today.goals[0].daysLeft, 114)
        XCTAssertEqual(today.goals[0].targets.map(\.stage), ["approached", "conversation", "intro", "proposal"])
        XCTAssertEqual(today.next.map(\.kind), ["reply", "approve", "send", "distribute"])
        XCTAssertEqual(today.next[1].command, "teyla growth review")
        XCTAssertEqual(today.sources.count, 4)
        XCTAssertEqual(today.doctor.count, 2)
    }

    func testDecodesTheGoalFirstFields() throws {
        let goal = try full().goals[0]
        XCTAssertEqual(goal.doneWhen, "A consulting deal or a product sale")
        XCTAssertEqual(goal.weeksLeft, 16)
        XCTAssertEqual(goal.short, 18)
        XCTAssertEqual(goal.fedBy, ["growth", "outreach"])
        XCTAssertEqual(goal.unfed, ["contacts"])
        XCTAssertEqual(goal.targets.map(\.counter), ["distribution", "outcomes", "outcomes", "outcomes"])
        XCTAssertEqual(goal.outcomeTargets.map(\.stage), ["conversation", "intro", "proposal"])
        let history = goal.targets[1].history
        XCTAssertEqual(history.count, 8)
        XCTAssertEqual(history.first, GtmWeek(week: "2026-W38", count: nil))
        XCTAssertEqual(history.last, GtmWeek(week: "2026-W45", count: 1))
    }

    func testOldJSONWithoutTheNewFieldsStillDecodes() throws {
        let json = #"""
        {"version": 1, "day": "2026-11-07", "has_goals": true,
         "goals": [{"id": "g", "title": "Old goal", "deadline": "2027-03-01", "days_left": 114,
                    "targets": [{"stage": "conversation", "count": 6, "target": 15}]}]}
        """#
        let today = try GtmToday.decode(Data(json.utf8))
        XCTAssertEqual(today.weekEnd, "")
        let goal = today.goals[0]
        XCTAssertNil(goal.doneWhen)
        XCTAssertNil(goal.weeksLeft)
        XCTAssertEqual(goal.short, 0)
        XCTAssertEqual(goal.fedBy, [])
        XCTAssertEqual(goal.unfed, [])
        XCTAssertEqual(goal.targets[0].counter, "outcomes", "no counter reads as an outcome")
        XCTAssertEqual(goal.targets[0].history, [])
    }

    func testADamagedHistoryEntryIsSkippedNotFatal() throws {
        let json = #"""
        {"goals": [{"id": "g", "targets": [{"stage": "intro", "count": 1, "target": 3,
                    "history": [{"week": "2026-W44", "count": 1}, {"count": 2}, {"week": "2026-W45", "count": "x"}]}]}]}
        """#
        let history = try GtmToday.decode(Data(json.utf8)).goals[0].targets[0].history
        XCTAssertEqual(history, [GtmWeek(week: "2026-W44", count: 1), GtmWeek(week: "2026-W45", count: nil)])
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
                                 "TEYLA_GTM_FIXTURE": SampleFiles.url("gtm-today.empty.v1.json").path])
        let today = try await cli.gtmToday()
        XCTAssertTrue(today.goals.isEmpty, "the named file wins over the one beside the state sample")
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

}

final class TodayLogicTests: XCTestCase {
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
    }

    func testCountsReadAsSentences() throws {
        let today = try GtmToday.decode(SampleFiles.data("gtm-today.v1.json"))
        XCTAssertEqual(TodayLogic.waitingTotal(today), 29)
        XCTAssertEqual(TodayLogic.waitingWords("reply", count: 1), "1 reply to answer")
        XCTAssertEqual(TodayLogic.waitingWords("reply", count: 2), "2 replies to answer")
        XCTAssertEqual(TodayLogic.waitingSpoken(today), "29 items wait for you: 22 drafts to approve, 5 items to send, 2 replies to answer.")
        XCTAssertEqual(TodayLogic.outcomesSpoken(today), "1 outcome this week, 0 today.")
        XCTAssertEqual(TodayLogic.waitingSpoken(GtmToday()), "Nothing waits for you.")
    }

    func testGoalsReadWithDaysLeft() throws {
        let goal = try GtmToday.decode(SampleFiles.data("gtm-today.v1.json")).goals[1]
        XCTAssertEqual(TodayLogic.daysLeftWords(38), "38 days left")
        XCTAssertEqual(TodayLogic.daysLeftWords(1), "1 day left")
        XCTAssertEqual(TodayLogic.daysLeftWords(0), "Due today")
        XCTAssertEqual(TodayLogic.daysLeftWords(-3), "Past the deadline")
        XCTAssertNil(TodayLogic.daysLeftWords(nil))
        XCTAssertEqual(TodayLogic.goalSpoken(goal), "Activated testers on two focus products. 0 of 12 activated this week.")
        XCTAssertEqual(TodayLogic.fraction(GtmTarget(stage: "x", count: 5, target: 0)), 0)
        XCTAssertEqual(TodayLogic.fraction(GtmTarget(stage: "x", count: 30, target: 15)), 1)
    }
}

final class GoalFirstLogicTests: XCTestCase {
    private func full() throws -> GtmToday { try GtmToday.decode(SampleFiles.data("gtm-today.v1.json")) }

    private func goal(_ id: String, short: Int, counters: [String] = ["outcomes"]) -> GtmGoal {
        GtmGoal(id: id, title: id, short: short,
                targets: counters.enumerated().map { GtmTarget(stage: "s\($0.offset)", count: 0, target: 5, counter: $0.element) })
    }

    func testChangingTheStageClearsTheOldNumber() {
        XCTAssertEqual(TodayLogic.weeklyChange(stage: "intro", count: 3, replacing: "conversation"),
                       [GtmWeeklyNumber(stage: "intro", count: 3), GtmWeeklyNumber(stage: "conversation", count: 0)])
        XCTAssertEqual(TodayLogic.weeklyChange(stage: "intro", count: 3, replacing: "intro"), [GtmWeeklyNumber(stage: "intro", count: 3)])
        XCTAssertEqual(TodayLogic.weeklyChange(stage: "intro", count: 3, replacing: nil), [GtmWeeklyNumber(stage: "intro", count: 3)])
    }

    func testStagesAreHumanised() {
        let expected = ["conversation": "Conversations", "intro": "Intros", "offer_fit": "Offer fit", "activated": "Activated",
                        "signed_up": "Sign-ups", "replied": "Replies", "proposal": "Proposals", "paid": "Paying",
                        "approached": "Approached", "my_stage": "My stage"]
        for (stage, label) in expected { XCTAssertEqual(TodayLogic.stageLabel(stage), label, stage) }
        XCTAssertEqual(TodayLogic.stageNoun("conversation"), "conversations")
    }

    func testTheFeaturedGoalIsTheOneFurthestBehind() throws {
        let today = try full()
        XCTAssertEqual(TodayLogic.featured(today.goals)?.id, "relationships")
        XCTAssertEqual(TodayLogic.others(today.goals).map(\.id), ["testers", "investors"])
    }

    func testATieGoesToTheFirstInTheFile() {
        let goals = [goal("a", short: 4), goal("b", short: 9), goal("c", short: 9)]
        XCTAssertEqual(TodayLogic.featured(goals)?.id, "b")
        XCTAssertEqual(TodayLogic.others(goals).map(\.id), ["a", "c"])
    }

    func testAGoalWithNoOutcomeTargetIsSkippedUnlessNoneHasOne() {
        let goals = [goal("send-only", short: 50, counters: ["distribution"]), goal("real", short: 1)]
        XCTAssertEqual(TodayLogic.featured(goals)?.id, "real")
        let none = [goal("a", short: 0, counters: []), goal("b", short: 0, counters: ["distribution"])]
        XCTAssertEqual(TodayLogic.featured(none)?.id, "a")
        XCTAssertNil(TodayLogic.featured([]))
        XCTAssertEqual(TodayLogic.others([]).count, 0)
    }

    func testPaceReadsBehindOrOnPace() throws {
        let goals = try full().goals
        XCTAssertEqual(TodayLogic.pace(goals[0]), .behind(18))
        XCTAssertEqual(TodayLogic.paceWords(.behind(18)), "Behind this week · 18 short")
        XCTAssertEqual(TodayLogic.paceWords(.onPace), "On pace this week")
        XCTAssertEqual(TodayLogic.pace(goal("a", short: 0)), .onPace)
        XCTAssertNil(TodayLogic.pace(goals[2]), "a goal with no outcome target has no pace")
    }

    func testCirclesFillOnlyToTheNumberAndBecomeABarAboveThirty() {
        XCTAssertEqual(TodayLogic.beads(GtmTarget(stage: "x", count: 1, target: 15)), .circles(total: 15, filled: 1))
        XCTAssertEqual(TodayLogic.beads(GtmTarget(stage: "x", count: 40, target: 15)), .circles(total: 15, filled: 15))
        XCTAssertEqual(TodayLogic.beads(GtmTarget(stage: "x", count: 5, target: 30)), .circles(total: 30, filled: 5))
        XCTAssertEqual(TodayLogic.beads(GtmTarget(stage: "x", count: 15, target: 60)), .bar(fraction: 0.25))
        XCTAssertEqual(TodayLogic.beads(GtmTarget(stage: "x", count: 0, target: 0)), .circles(total: 0, filled: 0))
    }

    func testARowIsSpokenAsOneSentence() {
        XCTAssertEqual(TodayLogic.beadsSpoken(GtmTarget(stage: "conversation", count: 1, target: 15)), "1 of 15 conversations this week")
        XCTAssertEqual(TodayLogic.beadsSpoken(GtmTarget(stage: "offer_fit", count: 0, target: 2)), "0 of 2 offer fit this week")
    }

    func testDatesReadWithoutATimeZone() {
        XCTAssertEqual(TodayLogic.deadlineWords("2027-03-01"), "1 March")
        XCTAssertEqual(TodayLogic.deadlineWords("2026-12-31"), "31 December")
        XCTAssertNil(TodayLogic.deadlineWords("soon"))
        XCTAssertNil(TodayLogic.deadlineWords(nil))
        XCTAssertEqual(TodayLogic.dayWords("2026-11-07"), "Saturday, 7 November")
        XCTAssertEqual(TodayLogic.dayWords("2026-11-09"), "Monday, 9 November")
    }

    func testTheWeekEndReadsTodayTomorrowOrInDays() {
        XCTAssertEqual(TodayLogic.weekEndWords(day: "2026-11-08", weekEnd: "2026-11-08"), "week ends today")
        XCTAssertEqual(TodayLogic.weekEndWords(day: "2026-11-07", weekEnd: "2026-11-08"), "week ends tomorrow")
        XCTAssertEqual(TodayLogic.weekEndWords(day: "2026-11-04", weekEnd: "2026-11-08"), "week ends in 4 days")
        XCTAssertNil(TodayLogic.weekEndWords(day: "2026-11-04", weekEnd: ""))
    }

    func testTheHeaderLine() throws {
        XCTAssertEqual(TodayLogic.contextLine(try full()), "Saturday, 7 November · week ends tomorrow")
        XCTAssertEqual(TodayLogic.contextLine(nil), "")
    }

    func testAGoalMetaJoinsWhatItKnows() throws {
        let goals = try full().goals
        XCTAssertEqual(TodayLogic.goalMeta(goals[0]), "A consulting deal or a product sale · 1 March · 16 weeks left")
        XCTAssertEqual(TodayLogic.goalMeta(goals[1]), "No deadline")
        XCTAssertEqual(TodayLogic.weeksLeftWords(weeks: 1, days: 6), "1 week left")
        XCTAssertEqual(TodayLogic.weeksLeftWords(weeks: 0, days: 2), "Last week")
        XCTAssertEqual(TodayLogic.weeksLeftWords(weeks: 3, days: -1), "Past the deadline")
        XCTAssertNil(TodayLogic.weeksLeftWords(weeks: nil, days: nil))
    }

    func testTheTicksOfSentAreCappedAtTwenty() {
        XCTAssertTrue(TodayLogic.sentTicks(GtmDistribution(today: 3, target: 10))! == (10, 3))
        XCTAssertTrue(TodayLogic.sentTicks(GtmDistribution(today: 14, target: 10))! == (10, 10))
        XCTAssertTrue(TodayLogic.sentTicks(GtmDistribution(today: 30, target: 60))! == (20, 10))
        XCTAssertTrue(TodayLogic.sentTicks(GtmDistribution(today: 1, target: 60))! == (20, 1))
        XCTAssertNil(TodayLogic.sentTicks(GtmDistribution(today: 3, target: nil)))
    }

    func testTheQuietStrip() throws {
        let today = try full()
        XCTAssertEqual(TodayLogic.cameBack(today), 2)
        XCTAssertEqual(TodayLogic.cameBackWords(today), "2 waiting")
        XCTAssertEqual(TodayLogic.cameBackWords(GtmToday()), "none waiting")
        XCTAssertEqual(TodayLogic.prepared(today), 22)
        XCTAssertEqual(TodayLogic.stripSpoken(today), "Sent 3 of 10 today. 2 that came back are waiting. 22 prepared.")
    }

    func testNextForTheGoalIsTheFirstActionableKind() throws {
        let today = try full()
        let step = try XCTUnwrap(TodayLogic.nextStep(today))
        XCTAssertEqual(step.kind, "reply")
        XCTAssertEqual(step.title, "Answer 2 replies")
        XCTAssertEqual(step.button, "Answer replies")
        XCTAssertEqual(step.link?.absoluteString, "https://example.com/outreach/inbox")
        XCTAssertEqual(step.detail, "Replies first: they are conversations already started.")

        var drafts = today
        drafts.next = today.next.filter { $0.kind != "reply" }
        let approve = try XCTUnwrap(TodayLogic.nextStep(drafts))
        XCTAssertEqual(approve.kind, "approve")
        XCTAssertEqual(approve.button, "Review drafts")
        XCTAssertNil(approve.link, "review goes to Growth")
        XCTAssertEqual(approve.detail, "Approve or skip; nothing is sent from Teyla.")

        var only = today
        only.next = today.next.filter { $0.kind == "distribute" }
        XCTAssertNil(TodayLogic.nextStep(only), "a gap in the daily target is not a step for a goal")
    }

    func testAReplyWithNoLinkHasNoLinkSoTheButtonGoesToGrowth() throws {
        var today = try full()
        today.reply = GtmWaiting(total: 2, bySource: ["outreach": 2], links: [:])
        XCTAssertNil(TodayLogic.nextStep(today)?.link)
    }

    func testOtherGoalRows() throws {
        let goals = try full().goals
        let testers = goals[1]
        let target = try XCTUnwrap(TodayLogic.rowTarget(testers))
        XCTAssertEqual(TodayLogic.rowCount(testers, target: target), "0 of 12 · source not connected")
        XCTAssertNil(TodayLogic.rowTarget(goals[2]))
        var fed = testers
        fed.fedBy = ["growth"]
        XCTAssertEqual(TodayLogic.rowCount(fed, target: target), "0 of 12")
    }

    func testTheFooterCountsSourcesThatDidNotAnswerCleanly() throws {
        let today = try full()
        XCTAssertEqual(TodayLogic.sourcesNotOK(today), 2)
        XCTAssertEqual(TodayLogic.sourcesWords(2), "2 sources not connected")
        XCTAssertEqual(TodayLogic.sourcesWords(1), "1 source not connected")
    }

    func testGoalDetailHelpers() {
        XCTAssertEqual(TodayLogic.weekSquares(weeksLeft: 16), 17)
        XCTAssertEqual(TodayLogic.weekSquares(weeksLeft: 200), 52)
        XCTAssertEqual(TodayLogic.weekSquares(weeksLeft: 0), 1)
        XCTAssertNil(TodayLogic.weekSquares(weeksLeft: nil))
        XCTAssertEqual(TodayLogic.weekShort("2026-W45"), "W45")
        XCTAssertNil(TodayLogic.cellLevel(count: nil, target: 15), "a week no run saved is an empty cell")
        XCTAssertEqual(TodayLogic.cellLevel(count: 0, target: 15), 0)
        XCTAssertEqual(TodayLogic.cellLevel(count: 3, target: 15), 1)
        XCTAssertEqual(TodayLogic.cellLevel(count: 8, target: 15), 2)
        XCTAssertEqual(TodayLogic.cellLevel(count: 15, target: 15), 3)
        XCTAssertEqual(TodayLogic.stageOptions(current: "conversation"), GtmGoalCommands.stages)
        XCTAssertEqual(TodayLogic.stageOptions(current: "offer_fit").first, "offer_fit")
    }

    func testTheEmptyFixtureIsTheFirstRun() throws {
        let today = try GtmToday.decode(SampleFiles.data("gtm-today.empty.v1.json"))
        XCTAssertFalse(today.hasGoals)
        XCTAssertTrue(today.goals.isEmpty)
        XCTAssertNil(today.distribution.target)
    }

    func testTheStartersPickAStage() {
        XCTAssertEqual(TodayLogic.starters.map(\.name), ["Conversations", "Testers", "Customers", "Investors"])
        XCTAssertEqual(TodayLogic.starters.map(\.stage), ["conversation", "activated", "paid", "conversation"])
        XCTAssertEqual(TodayLogic.defaultWeekly, 5)
        XCTAssertEqual(TodayLogic.defaultPerDay, 10)
    }
}

final class GtmGoalCommandsTests: XCTestCase {
    func testAddBuildsAnArgumentArrayNeverAShellString() {
        let argv = GtmGoalCommands.addArguments(title: "  Conversations; rm -rf  ", weekly: [GtmWeeklyNumber(stage: "conversation", count: 15)],
                                                deadline: "2027-03-01", doneWhen: "A sale", perDay: 10)
        XCTAssertEqual(argv, ["gtm", "goal", "add", "--title=Conversations; rm -rf", "--weekly=conversation=15", "--deadline=2027-03-01",
                              "--done-when=A sale", "--per-day=10", "--json"])
    }

    func testATitleThatStartsWithADashIsAValueNotAFlag() {
        let argv = GtmGoalCommands.addArguments(title: "--json", weekly: [], deadline: nil, doneWhen: nil, perDay: nil)
        XCTAssertEqual(argv, ["gtm", "goal", "add", "--title=--json", "--json"])
    }

    func testAddRefusesWhatItCannotWrite() {
        let weekly = [GtmWeeklyNumber(stage: "conversation", count: 5)]
        XCTAssertNil(GtmGoalCommands.addArguments(title: "   ", weekly: weekly, deadline: nil, doneWhen: nil, perDay: nil))
        XCTAssertNil(GtmGoalCommands.addArguments(title: "x", weekly: [GtmWeeklyNumber(stage: "Bad Stage", count: 5)], deadline: nil, doneWhen: nil, perDay: nil))
        XCTAssertNil(GtmGoalCommands.addArguments(title: "x", weekly: [GtmWeeklyNumber(stage: "intro", count: 0)], deadline: nil, doneWhen: nil, perDay: nil))
        XCTAssertNil(GtmGoalCommands.addArguments(title: "x", weekly: weekly, deadline: "1 March", doneWhen: nil, perDay: nil))
        XCTAssertNil(GtmGoalCommands.addArguments(title: "x", weekly: weekly, deadline: nil, doneWhen: nil, perDay: 0))
    }

    func testSetBuildsTheWeeklyFlag() {
        XCTAssertEqual(GtmGoalCommands.setArguments(id: "relationships", weekly: [GtmWeeklyNumber(stage: "signed_up", count: 12)]),
                       ["gtm", "goal", "set", "relationships", "--weekly=signed_up=12", "--json"])
        XCTAssertNil(GtmGoalCommands.setArguments(id: "--evil", weekly: []))
        XCTAssertNil(GtmGoalCommands.setArguments(id: "a b", weekly: []))
        XCTAssertNil(GtmGoalCommands.setArguments(id: "g", weekly: [], title: "  "))
    }

    func testDatesAndLines() {
        XCTAssertTrue(GtmGoalCommands.isDate("2027-03-01"))
        XCTAssertFalse(GtmGoalCommands.isDate("2027-13-01"))
        XCTAssertFalse(GtmGoalCommands.isDate("27-3-1"))
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let date = calendar.date(from: DateComponents(year: 2027, month: 3, day: 1, hour: 9))!
        XCTAssertEqual(GtmGoalCommands.dateString(date, calendar: calendar), "2027-03-01")
        XCTAssertEqual(GtmGoalCommands.line("a\nb"), "a b")
        XCTAssertNil(GtmGoalCommands.line(nil))
        XCTAssertEqual(GtmGoalCommands.line(String(repeating: "x", count: 500))?.count, GtmGoalCommands.titleLimit)
    }

    func testAPreviewSimulatesTheWrite() async throws {
        let cli = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": SampleFiles.url("state.sample.v3.json").path])
        try await cli.gtmGoalAdd(title: "A goal", weekly: [GtmWeeklyNumber(stage: "intro", count: 3)], deadline: nil, doneWhen: nil, perDay: 10)
        try await cli.gtmGoalSet(id: "relationships", weekly: [GtmWeeklyNumber(stage: "intro", count: 4)], title: nil, deadline: nil, doneWhen: nil)
        do {
            try await cli.gtmGoalAdd(title: "", weekly: [], deadline: nil, doneWhen: nil, perDay: nil)
            XCTFail("an empty title is refused")
        } catch {
            XCTAssertTrue(error.localizedDescription.contains("cannot write"))
        }
    }
}

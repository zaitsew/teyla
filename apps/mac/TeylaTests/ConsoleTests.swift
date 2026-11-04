import XCTest
import os

private func report(_ name: String = "console.v1.json") throws -> ConsoleReport {
    try ConsoleReport.decode(SampleFiles.data(name))
}

private func decode(_ json: String) throws -> ConsoleReport {
    try ConsoleReport.decode(Data(json.utf8))
}

final class ConsoleReportTests: XCTestCase {
    func testTheSampleReportHasFourSectionsWithHeadlines() throws {
        let r = try report()
        XCTAssertEqual(r.operations.value?.headline?.display, "3")
        XCTAssertEqual(r.money.value?.headline?.display, "335")
        XCTAssertEqual(r.playbook.value?.headline?.display, "2")
        XCTAssertEqual(r.growth.value?.headline?.display, "2/6")
        XCTAssertNotNil(r.generated)
        XCTAssertFalse(r.allMissing)
    }

    func testASectionThatFailedKeepsItsReasonAndTheOthersLoad() throws {
        let r = try decode(#"""
        {"version":1,"generated":1793750000,
         "operations":{"error":"OSError: disk gone"},
         "money":{"headline":{"label":"Cash per month","value":null,"detail":"no subscriptions listed"}},
         "playbook":{"error":""}}
        """#)
        XCTAssertEqual(r.operations, .failed("OSError: disk gone"))
        XCTAssertEqual(r.money.value?.headline?.label, "Cash per month")
        XCTAssertNil(r.money.value?.headline?.display)
        XCTAssertEqual(r.playbook, .failed("The source gave no reason."))
        XCTAssertEqual(r.growth, .missing)
    }

    func testANullSectionOrAMissingKeyIsMissingNotZero() throws {
        let r = try decode(#"{"version":1,"operations":null,"money":{"headline":null}}"#)
        XCTAssertEqual(r.operations, .missing)
        XCTAssertEqual(r.growth, .missing)
        XCTAssertNil(r.money.value?.headline)
        XCTAssertNil(r.generated)
    }

    func testASectionOfTheWrongTypeIsAFailureNotACrash() throws {
        let r = try decode(#"{"version":1,"operations":"broken","money":[1,2],"growth":{"headline":{"label":5}}}"#)
        XCTAssertNotNil(r.operations.error)
        XCTAssertNotNil(r.money.error)
        // A headline whose label is not text still reads: the label falls back to empty.
        XCTAssertNotNil(r.growth.value)
    }

    func testAReportThatIsNotAnObjectIsRefused() {
        XCTAssertThrowsError(try decode("[]"))
        XCTAssertThrowsError(try decode("not json"))
        XCTAssertTrue(ConsoleReport().allMissing)
    }

    func testAHeadlineFigureKeepsItsTextAndDropsAWholeNumbersPoint() throws {
        let r = try decode(#"{"growth":{"headline":{"label":"Posts today","value":"0/6"}},"money":{"headline":{"label":"c","value":420.0}},"operations":{"headline":{"label":"f","value":7.5}}}"#)
        XCTAssertEqual(r.growth.value?.headline?.display, "0/6")
        XCTAssertEqual(r.money.value?.headline?.display, "420")
        XCTAssertEqual(r.operations.value?.headline?.display, "7.5")
    }
}

final class ConsoleTextTests: XCTestCase {
    func testEachSectionHasItsQuestion() {
        XCTAssertEqual(ConsoleText.page(for: .growth)?.title, "Growth")
        XCTAssertEqual(ConsoleText.page(for: .money)?.question, "What leaves your accounts?")
        XCTAssertEqual(ConsoleText.page(for: .operations)?.title, "Operations")
        XCTAssertEqual(ConsoleText.page(for: .playbook)?.title, "Playbook")
        XCTAssertNil(ConsoleText.page(for: .home))
        XCTAssertTrue(AppRoute.money.isConsole)
        XCTAssertFalse(AppRoute.portfolio.isConsole)
    }

    func testTheUpdatedLineUsesTheReportsOwnTimeAndSaysNothingBeforeOne() {
        let now = Date(timeIntervalSince1970: 10_000)
        XCTAssertEqual(ConsoleText.updated(generated: nil, readAt: nil, now: now), "")
        XCTAssertEqual(ConsoleText.updated(generated: now.addingTimeInterval(-20), readAt: nil, now: now), "Updated just now")
        XCTAssertEqual(ConsoleText.updated(generated: now.addingTimeInterval(-600), readAt: now, now: now), "Updated 10 min ago")
        XCTAssertEqual(ConsoleText.updated(generated: nil, readAt: now.addingTimeInterval(-7_300), now: now), "Updated 2 h ago")
    }
}

private final class ConsoleStub: TeylaBackend, @unchecked Sendable {
    private struct State {
        var results: [Result<ConsoleReport, Error>]
        var calls: [Bool] = []
        var cached: ConsoleReport?
    }
    private let box: OSAllocatedUnfairLock<State>

    init(_ results: [Result<ConsoleReport, Error>], cached: ConsoleReport? = nil) {
        box = OSAllocatedUnfairLock(initialState: State(results: results, cached: cached))
    }

    var usesFixture: Bool { false }
    var calls: [Bool] { box.withLock { $0.calls } }

    func console(refresh: Bool) async throws -> ConsoleReport {
        try await Task.sleep(for: .milliseconds(20))
        let next = box.withLock { s -> Result<ConsoleReport, Error> in
            s.calls.append(refresh)
            return s.results.count > 1 ? s.results.removeFirst() : s.results[0]
        }
        return try next.get()
    }

    func consoleCached() async -> ConsoleReport? { box.withLock { $0.cached } }

    func state() async throws -> Snapshot { throw TeylaError.unavailable("stub") }
    func answer(id: String, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func say(ref: String, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func dispatch(product: String, harness: Harness, text: String) async throws -> AnswerResult { throw TeylaError.unavailable("stub") }
    func productPage(id: String, quick: Bool) async throws -> ProductPageData { throw TeylaError.unavailable("stub") }
    func binaryPath() async -> String? { "stub" }
}

@MainActor
final class ConsoleModelTests: XCTestCase {
    private func until(_ what: String, _ condition: @MainActor () -> Bool) async throws {
        for _ in 0..<300 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("timed out waiting for \(what)")
    }

    func testTheFirstPaintComesFromTheCacheAndTheReadReplacesIt() async throws {
        let cached = ConsoleReport(version: 1, operations: .failed("old"))
        let fresh = try report()
        let model = ConsoleModel(cli: ConsoleStub([.success(fresh)], cached: cached))
        model.refresh()
        try await until("cache") { model.report != nil }
        try await until("read") { model.phase == .ready }
        XCTAssertEqual(model.report, fresh)
        XCTAssertNotNil(model.readAt)
    }

    func testAFailedReadKeepsTheLastReportAndSaysSo() async throws {
        let fresh = try report()
        let model = ConsoleModel(cli: ConsoleStub([.success(fresh), .failure(TeylaError.timedOut)]))
        model.refresh()
        try await until("first") { model.phase == .ready }
        model.refresh()
        try await until("failure") { model.failure != nil }
        XCTAssertEqual(model.report, fresh)
        XCTAssertEqual(model.failure, "teyla did not answer in time.")
    }

    func testAPageThatOpensWhileTheReportIsFreshDoesNotReadAgain() async throws {
        let stub = ConsoleStub([.success(try report())])
        let model = ConsoleModel(cli: stub)
        model.refresh()
        try await until("first") { model.phase == .ready }
        model.opened()
        try await Task.sleep(for: .milliseconds(80))
        XCTAssertEqual(stub.calls, [false])
    }

    func testARebuildAskedForWhileAReadRunsFollowsIt() async throws {
        let stub = ConsoleStub([.success(try report())])
        let model = ConsoleModel(cli: stub)
        model.refresh()
        model.refresh(rebuild: true)
        try await until("both reads") { stub.calls.count == 2 && model.phase == .ready }
        XCTAssertEqual(stub.calls, [false, true])
    }

    func testTheBadgeCountsFailuresAndShowsABangForASectionThatFailed() async throws {
        let model = ConsoleModel(cli: ConsoleStub([.success(try report())]))
        XCTAssertNil(model.operationsBadge)
        model.refresh()
        try await until("read") { model.phase == .ready }
        XCTAssertEqual(model.operationsBadge, "3")
        let broken = ConsoleModel(cli: ConsoleStub([.success(try decode(#"{"operations":{"error":"x"}}"#))]))
        broken.refresh()
        try await until("read") { broken.phase == .ready }
        XCTAssertEqual(broken.operationsBadge, "!")
    }
}

final class ConsoleFixtureBackendTests: XCTestCase {
    func testThePreviewReadsTheConsoleSampleBesideTheStateSample() async throws {
        let cli = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": SampleFiles.url("state.sample.home.json").path], home: "/nonexistent")
        let r = try await cli.console(refresh: false)
        XCTAssertNotNil(r.operations.value)
        let cached = await cli.consoleCached()
        XCTAssertNil(cached, "a preview has no cache file")
    }

    func testTheCachedReportIsReadFromTheTeylaHome() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("console-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        try SampleFiles.data("console.v1.json").write(to: dir.appendingPathComponent("console-cache.json"))
        let cli = TeylaCLI(env: ["TEYLA_HOME": dir.path], home: "/nonexistent")
        let cached = await cli.consoleCached()
        XCTAssertEqual(cached?.growth.value?.headline?.display, "2/6")
        let none = await TeylaCLI(env: ["TEYLA_HOME": dir.appendingPathComponent("none").path], home: "/nonexistent").consoleCached()
        XCTAssertNil(none)
    }

    func testTheArgumentsAskForARebuildOnlyWhenTold() {
        XCTAssertEqual(TeylaCLI.consoleArguments(refresh: false), ["console", "--json"])
        XCTAssertEqual(TeylaCLI.consoleArguments(refresh: true), ["console", "--json", "--refresh"])
    }
}

import XCTest

final class ActivityDecodingTests: XCTestCase {
    private func full() throws -> ActivityReport { try ActivityReport.decode(SampleFiles.data("activity.v1.json")) }

    func testDecodesTheFullReport() throws {
        let report = try full()
        XCTAssertEqual(report.today, "2026-11-06")
        XCTAssertEqual(report.start, "2025-11-03")
        XCTAssertEqual(report.days.count, 369)
        XCTAssertEqual(report.days.first?.day, "2025-11-03")
        XCTAssertEqual(report.days.last?.day, "2026-11-06")
        XCTAssertEqual(report.todayCount, 6)
        XCTAssertEqual(report.streak, 5)
        XCTAssertEqual(report.longest, 6)
        XCTAssertEqual(report.claimed, 2)
        XCTAssertEqual(report.meetings, 88)
        XCTAssertEqual(report.responses, 51)
        XCTAssertEqual(report.kinds.count, 11)
        XCTAssertEqual(report.days.last?.kinds["comment"], 2)
    }

    func testAMinimalReportTakesDefaultsAndUnknownFieldsAreIgnored() throws {
        let json = #"{"version": 1, "days": [{"day": "2026-11-05"}, {"day": "2026-11-06", "count": 2, "future": true}], "somethingNew": [1, 2]}"#
        let report = try ActivityReport.decode(Data(json.utf8))
        XCTAssertEqual(report.days.map(\.count), [0, 2])
        XCTAssertEqual(report.today, "2026-11-06")
        XCTAssertEqual(report.start, "2026-11-05")
        XCTAssertEqual(report.streak, 0)
        XCTAssertEqual(report.meetings, 0)
        XCTAssertEqual(report.claimed, 0)
        XCTAssertEqual(report.kinds, ActivityKind.all)
    }

    func testADamagedDayIsSkippedNotFatal() throws {
        let json = #"{"days": [{"day": "2026-11-05", "count": 1}, {"count": 3}, {"day": "2026-11-06", "count": "x"}]}"#
        let report = try ActivityReport.decode(Data(json.utf8))
        XCTAssertEqual(report.days.map(\.day), ["2026-11-05", "2026-11-06"])
        XCTAssertEqual(report.days.map(\.count), [1, 0])
    }

    func testNotJSONIsABadOutputError() {
        XCTAssertThrowsError(try ActivityReport.decode(Data("usage: teyla growth".utf8)))
    }

    func testThePickerOffersOnlyKindsTheAppMayLog() throws {
        var report = ActivityReport()
        report.kinds = ["post", "rm -rf", "response"]
        XCTAssertEqual(report.loggableKinds, ["post", "response"])
        report.kinds = ["nothing-we-know"]
        XCTAssertEqual(report.loggableKinds, ActivityKind.all)
    }

    func testTheLayoutDefaultsToTheYear() {
        XCTAssertEqual(ActivityLayout.stored(nil), .year)
        XCTAssertEqual(ActivityLayout.stored("quarter"), .quarter)
        XCTAssertEqual(ActivityLayout.stored("nonsense"), .year)
        XCTAssertEqual(ActivityLayout.year.weeks, 53)
        XCTAssertEqual(ActivityLayout.quarter.weeks, 17)
    }

    func testAnOlderCommandReadsAsUpdateNotAsFailure() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("teyla-activity-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let script = dir.appendingPathComponent("teyla")
        try "#!/bin/sh\necho \"teyla growth: error: argument action: invalid choice: 'activity'\" >&2\nexit 2\n"
            .write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let cli = TeylaCLI(env: ["TEYLA_BIN": script.path], home: dir.path)
        do {
            _ = try await cli.activity(weeks: 53)
            XCTFail("an old command must throw")
        } catch TeylaError.unavailable(let why) {
            XCTAssertEqual(why, "Update the teyla command to see activity.")
        }
    }

    func testTheCommandIsCalledWithTheWeeksAndItsOutputIsRead() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("teyla-activity-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let script = dir.appendingPathComponent("teyla")
        let argsFile = dir.appendingPathComponent("args.txt")
        try """
        #!/bin/sh
        printf '%s\\n' "$@" > '\(argsFile.path)'
        cat '\(SampleFiles.url("activity.v1.json").path)'
        """.write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let cli = TeylaCLI(env: ["TEYLA_BIN": script.path], home: dir.path)
        let report = try await cli.activity(weeks: 53)
        XCTAssertEqual(report.streak, 5)
        let args = try String(contentsOf: argsFile, encoding: .utf8).split(separator: "\n").map(String.init)
        XCTAssertEqual(args, ["growth", "activity", "--json", "--weeks", "53"])
    }

    func testAFixturePreviewWithoutAnActivityFileAnswersLikeAnOlderCommand() async throws {
        let cli = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": SampleFiles.url("state.sample.home.json").path,
                                 "TEYLA_ACTIVITY_FIXTURE": "/nonexistent/activity.json"], home: "/nonexistent")
        do {
            _ = try await cli.activity(weeks: 53)
            XCTFail("expected unavailable")
        } catch TeylaError.unavailable(let why) {
            XCTAssertEqual(why, ActivityLogic.updateMessage)
        }
    }

    func testTheSnapshotCarriesAnOptionalActivityBlock() throws {
        let with = #"{"version": 3, "activity": {"today": "2026-11-06", "days": [{"day": "2026-11-06", "count": 2, "level": 2}], "today_count": 2, "streak": 4, "longest": 9, "week_count": 7, "kinds": ["post"], "total": 120}}"#
        let snapshot = try JSONDecoder().decode(Snapshot.self, from: Data(with.utf8))
        XCTAssertEqual(snapshot.activity?.todayCount, 2)
        XCTAssertEqual(snapshot.activity?.streak, 4)
        XCTAssertEqual(snapshot.activity?.total, 120)
        XCTAssertEqual(snapshot.activity?.days.first?.level, 2)
        let without = try JSONDecoder().decode(Snapshot.self, from: Data(#"{"version": 3}"#.utf8))
        XCTAssertNil(without.activity)
    }
}

final class ActivityLogicTests: XCTestCase {
    private func cell(_ column: ActivityColumn?, _ row: Int) -> String? { column?.days[row]?.day }

    func testTheTooltipNamesTheDayTheCountAndTheKinds() {
        let day = ActivityDay(day: "2026-11-06", count: 3, level: 2, kinds: ["comment": 2, "email": 1])
        XCTAssertEqual(ActivityLogic.tooltip(day), "Fri 6 Nov: 3 — 2 comments, 1 email")
        let thursday = ActivityDay(day: "2026-11-05", count: 1, level: 1, kinds: ["reply": 1])
        XCTAssertEqual(ActivityLogic.tooltip(thursday), "Thu 5 Nov: 1 — 1 reply")
    }

    func testTheTooltipOfAQuietDay() {
        XCTAssertEqual(ActivityLogic.tooltip(ActivityDay(day: "2026-11-01")), "Sun 1 Nov: No activity")
    }

    func testTheTooltipPluralsAndOrder() {
        let day = ActivityDay(day: "2026-11-03", count: 6, level: 3,
                              kinds: ["response": 2, "icp-meeting": 1, "reply": 2, "dm": 1])
        XCTAssertEqual(ActivityLogic.tooltip(day), "Tue 3 Nov: 6 — 2 replies, 1 DM, 1 ICP meeting, 2 responses")
    }

    func testACountWithoutKindsStillShowsTheCount() {
        XCTAssertEqual(ActivityLogic.tooltip(ActivityDay(day: "2026-11-03", count: 4, level: 2)), "Tue 3 Nov: 4")
    }

    func testTheGridHasMondayFirstColumnsAndTheNewestWeekLast() throws {
        let report = try ActivityReport.decode(SampleFiles.data("activity.v1.json"))
        let columns = ActivityLogic.columns(report.days, weeks: 53)
        XCTAssertEqual(columns.count, 53)
        XCTAssertEqual(cell(columns.first, 0), "2025-11-03")        // a Monday
        XCTAssertEqual(cell(columns.last, 4), "2026-11-06")                      // Friday
        XCTAssertNil(cell(columns.last, 5))                                       // Saturday has not come yet
        XCTAssertEqual(columns.last?.days.count, 7)
    }

    func testAStartInTheMiddleOfAWeekIsPaddedAndTheQuarterTakesTheLast17Weeks() throws {
        let days = [ActivityDay(day: "2026-11-04"), ActivityDay(day: "2026-11-05")]      // Wed, Thu
        let columns = ActivityLogic.columns(days, weeks: 17)
        XCTAssertEqual(columns.count, 1)
        XCTAssertNil(cell(columns[0], 0))
        XCTAssertNil(cell(columns[0], 1))
        XCTAssertEqual(cell(columns[0], 2), "2026-11-04")
        let report = try ActivityReport.decode(SampleFiles.data("activity.v1.json"))
        XCTAssertEqual(ActivityLogic.columns(report.days, weeks: 17).count, 17)
    }

    func testMonthLabelsSitAtTheFirstColumnOfAMonthAndNeverCrowd() throws {
        let report = try ActivityReport.decode(SampleFiles.data("activity.v1.json"))
        let labels = ActivityLogic.monthLabels(ActivityLogic.columns(report.days, weeks: 53))
        XCTAssertEqual(labels.last?.name, "Nov")
        XCTAssertTrue(labels.count >= 11 && labels.count <= 13)
        for pair in zip(labels, labels.dropFirst()) { XCTAssertGreaterThanOrEqual(pair.1.column - pair.0.column, 3) }
        XCTAssertEqual(labels.map(\.name).filter { $0 == "Nov" }.count, 2)
    }

    func testTheSummaryLines() throws {
        let report = try ActivityReport.decode(SampleFiles.data("activity.v1.json"))
        XCTAssertEqual(ActivityLogic.summary(report), "719 in the last year · today 6 · streak 5 days (longest 6)")
        XCTAssertEqual(ActivityLogic.outcomes(report), "Meetings held 88 · Responses 51")
        XCTAssertEqual(ActivityLogic.claimedNote(report), "2 logged by an agent, not counted")
        var none = report
        none.claimed = 0
        XCTAssertNil(ActivityLogic.claimedNote(none))
        XCTAssertEqual(ActivityLogic.spoken(report), "Activity: 6 today, streak 5 days, 719 this year")
        none.streak = 1
        XCTAssertEqual(ActivityLogic.spoken(none), "Activity: 6 today, streak 1 day, 719 this year")
    }

    func testKindLabels() {
        XCTAssertEqual(ActivityKind.label("response"), "Got a response")
        XCTAssertEqual(ActivityKind.label("icp-meeting"), "ICP meeting")
        XCTAssertEqual(ActivityKind.all.count, 11)
    }

    func testThePhoneShowsWhatTheMacSaid() {
        XCTAssertEqual(ActivityLogic.resultWords(label: "Post", ok: nil, detail: ""), "Post: waiting for your Mac.")
        XCTAssertEqual(ActivityLogic.resultWords(label: "Post", ok: true, detail: "logged"), "Post: logged on your Mac.")
        XCTAssertEqual(ActivityLogic.resultWords(label: "Post", ok: false, detail: "malformed entry: kind"), "Post: malformed entry: kind")
        XCTAssertEqual(ActivityLogic.resultWords(label: "Post", ok: false, detail: " "), "Post: your Mac could not log it.")
    }
}

final class ActivityLogCommandTests: XCTestCase {
    func testTheCommandIsBuiltFromAKnownKindOnly() {
        XCTAssertEqual(ActivityLog.argv(kind: "comment", product: nil, count: 1), ["growth", "log", "--kind", "comment"])
        XCTAssertEqual(ActivityLog.argv(kind: "post", product: "sample-app", count: 3),
                       ["growth", "log", "--kind", "post", "--product", "sample-app", "--count", "3"])
    }

    func testTheAllowListAcceptsLogCommands() {
        for kind in ActivityKind.all {
            XCTAssertEqual(ToolCommands.check(["growth", "log", "--kind", kind]), .allowed, kind)
        }
        XCTAssertEqual(ToolCommands.check(ActivityLog.argv(kind: "email", product: "sample-app", count: 50)), .allowed)
        XCTAssertEqual(ToolCommands.effect(["growth", "log", "--kind", "post"]), .changes)
    }

    func testTheAllowListRefusesAnythingElse() {
        let refused: [[String]] = [
            ["growth", "log"], ["growth", "log", "--kind"], ["growth", "log", "--kind", "tweet"],
            ["growth", "log", "--kind", "post; rm -rf ~"], ["growth", "log", "--kind", "--all"],
            ["growth", "log", "--kind", "post", "--count", "0"], ["growth", "log", "--kind", "post", "--count", "51"],
            ["growth", "log", "--kind", "post", "--count", "-1"], ["growth", "log", "--kind", "post", "--count", "1e3"],
            ["growth", "log", "--kind", "post", "--product", "--help"], ["growth", "log", "--kind", "post", "--product", "a b"],
            ["growth", "log", "--kind", "post", "--note", "free text"], ["growth", "log", "--kind", "post", "--count", "2", "--count", "3"],
            ["growth", "log", "--kind", "post", "extra"],
        ]
        for argv in refused {
            XCTAssertFalse(ToolCommands.check(argv).isAllowed, argv.joined(separator: " "))
        }
    }
}

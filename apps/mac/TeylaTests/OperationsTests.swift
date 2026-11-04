import XCTest

private func operations(_ json: String) throws -> OperationsReport {
    try JSONDecoder().decode(OperationsReport.self, from: Data(json.utf8))
}

private func sample() throws -> OperationsReport {
    guard let report = try ConsoleReport.decode(SampleFiles.data("console.v1.json")).operations.value else {
        throw TeylaError.badOutput("no operations in the sample")
    }
    return report
}

final class OperationsParsingTests: XCTestCase {
    func testTheSampleHoldsEverySection() throws {
        let report = try sample()
        XCTAssertEqual(report.headline?.number, 3)
        XCTAssertEqual(report.leave?.ok, false)
        XCTAssertEqual(report.leave?.blockers.count, 2)
        XCTAssertEqual(report.machine?.verdict, "BUSY")
        XCTAssertEqual(report.machine?.diskFreeGB, 22.4)
        XCTAssertEqual(report.machine?.agents["claude"], 6)
        XCTAssertEqual(report.machine?.diskSeries.count, 96)
        XCTAssertEqual(report.machine?.swapSeries.count, 96)
        XCTAssertEqual(report.failures.count, 4)
        XCTAssertEqual(report.failures.first?.action, "teyla storage sweep")
        XCTAssertNil(report.failures[1].action)
        XCTAssertEqual(report.schedules?.rows.count, 10)
        XCTAssertEqual(report.harnesses.count, 5)
        XCTAssertEqual(report.policySync?.status, "drift")
        XCTAssertEqual(report.policySync?.drift.first?.harness, "grok")
        XCTAssertEqual(report.policySync?.repos?.toFix, ["sample-lab", "sample-watch"])
        XCTAssertEqual(report.security?.depsVulns, 12)
        XCTAssertNil(report.security?.shieldIssues, "no shield result stays nil, never zero")
        XCTAssertNotNil(report.security?.leakAsOf)
    }

    func testAnEmptyObjectIsAnEmptyReport() throws {
        let report = try operations("{}")
        XCTAssertNil(report.headline)
        XCTAssertNil(report.leave)
        XCTAssertNil(report.machine)
        XCTAssertTrue(report.failures.isEmpty)
        XCTAssertNil(report.schedules)
        XCTAssertTrue(report.harnesses.isEmpty)
        XCTAssertNil(report.policySync)
        XCTAssertNil(report.security)
    }

    func testNullsAndWrongTypesLeaveNilNotZero() throws {
        let report = try operations("""
        {"leave": {"ok": null, "blockers": null},
         "machine": {"verdict": null, "disk_free_gb": "lots", "swap_used_gb": null, "series": {"disk": null, "swap": [[1, 2]]}},
         "security": {"leak_findings": null, "deps_vulns": "many", "as_of": null},
         "policy_sync": {"status": null, "drift": null, "last_sync": "not a date"}}
        """)
        XCTAssertNil(report.leave?.ok)
        XCTAssertEqual(report.leave?.blockers, [])
        XCTAssertNil(report.machine?.verdict)
        XCTAssertNil(report.machine?.diskFreeGB)
        XCTAssertNil(report.machine?.swapUsedGB)
        XCTAssertEqual(report.machine?.diskSeries.count, 0)
        XCTAssertEqual(report.machine?.swapSeries.count, 1)
        XCTAssertNil(report.security?.leakFindings)
        XCTAssertNil(report.security?.depsVulns)
        XCTAssertNil(report.security?.leakAsOf)
        XCTAssertNil(report.policySync?.status)
        XCTAssertEqual(report.policySync?.drift.count, 0)
        XCTAssertNil(report.policySync?.lastSync)
    }

    func testOneUnreadableRowIsSkippedNotTheList() throws {
        let report = try operations("""
        {"failures": [{"title": "Disk is low"}, {"detail": "no title"}, 7, {"title": "Two", "severity": "info"}],
         "schedules": {"rows": [{"name": "a", "state": "OK"}, {"state": "OK"}], "counts": {"ok": 1}},
         "harnesses": [{"name": "codex", "installed": true}, {"installed": true}],
         "machine": {"series": {"disk": [[1, 2], "bad", [3, 4]]}, "top": [{"name": "App", "gb": 1.5}, {"gb": 2}]}}
        """)
        XCTAssertEqual(report.failures.map(\.title), ["Disk is low", "Two"])
        XCTAssertEqual(report.schedules?.rows.map(\.name), ["a"])
        XCTAssertEqual(report.harnesses.map(\.name), ["codex"])
        XCTAssertEqual(report.machine?.diskSeries.count, 2)
        XCTAssertEqual(report.machine?.top.map(\.name), ["App"])
    }

    func testASectionErrorStaysItsOwn() throws {
        let report = try ConsoleReport.decode(Data(#"{"version":1,"operations":{"error":"disk read failed"}}"#.utf8))
        XCTAssertEqual(report.operations.error, "disk read failed")
        XCTAssertNil(report.operations.value)
    }

    func testAnUnknownSeverityNeedsTheOwner() throws {
        let report = try operations(#"{"failures": [{"title": "A", "severity": "weird"}, {"title": "B", "severity": "info"}]}"#)
        XCTAssertTrue(report.failures[0].needsYou)
        XCTAssertFalse(report.failures[1].needsYou)
    }

    func testAnEmptyActionIsNoAction() throws {
        let report = try operations(#"{"failures": [{"title": "A", "action": ""}]}"#)
        XCTAssertNil(report.failures[0].action)
    }

    func testSeriesAreSortedByTime() throws {
        let report = try operations(#"{"machine": {"series": {"disk": [[200, 1.0], [100, 2.0]]}}}"#)
        XCTAssertEqual(report.machine?.diskSeries.map(\.value), [2.0, 1.0])
    }
}

final class OperationsLogicTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_793_700_000)

    func testTheLidFigure() {
        XCTAssertNil(OperationsLogic.lidFigure(nil).value)
        XCTAssertNil(OperationsLogic.lidFigure(OpsLeave(ok: nil)).value)
        XCTAssertEqual(OperationsLogic.lidFigure(OpsLeave(ok: true)).value, "Yes")
        let blocked = OperationsLogic.lidFigure(OpsLeave(ok: false, blockers: ["a", "b"]))
        XCTAssertEqual(blocked.value, "Not yet")
        XCTAssertEqual(blocked.detail, "2 things are still running.")
        XCTAssertTrue(blocked.needsYou)
        XCTAssertEqual(OperationsLogic.lidFigure(OpsLeave(ok: false, blockers: ["a"])).detail, "1 thing is still running.")
    }

    func testFiguresAreDashesWhenUnknown() {
        XCTAssertNil(OperationsLogic.gb(nil))
        XCTAssertEqual(OperationsLogic.gb(34.44), "34.4 GB")
        XCTAssertEqual(OperationsLogic.diskDetail(nil), "The report has no disk figure.")
        XCTAssertEqual(OperationsLogic.diskDetail(OpsMachine(diskFreeGB: 23, diskTotalGB: 460)), "5% of 460 GB")
        XCTAssertEqual(OperationsLogic.diskDetail(OpsMachine(diskFreeGB: 23, diskTotalGB: 0)), "The report has no disk figure.")
        XCTAssertNil(OperationsLogic.count(nil))
        XCTAssertEqual(OperationsLogic.count(0), "0")
    }

    func testSchedulesComeWorstFirstAndSplit() {
        let rows = [
            OpsScheduleRow(name: "b-ok", state: "OK"),
            OpsScheduleRow(name: "a-off", state: "DISABLED"),
            OpsScheduleRow(name: "late", state: "STALE"),
            OpsScheduleRow(name: "mystery", state: "SOMETHING NEW"),
            OpsScheduleRow(name: "gone", state: "VANISHED"),
            OpsScheduleRow(name: "never", state: "NEVER RAN"),
            OpsScheduleRow(name: "unloaded", state: "UNREGISTERED"),
            OpsScheduleRow(name: "a-ok", state: "OK"),
        ]
        XCTAssertEqual(OperationsLogic.schedulesWorstFirst(rows).map(\.name),
                       ["late", "gone", "unloaded", "never", "mystery", "a-ok", "b-ok", "a-off"])
        let split = OperationsLogic.scheduleSplit(rows)
        XCTAssertEqual(split.look.map(\.name), ["late", "gone", "unloaded", "never"])
        XCTAssertEqual(split.rest.map(\.name), ["mystery", "a-ok", "b-ok", "a-off"])
        XCTAssertEqual(OperationsLogic.scheduleNote(rows), "4 late or missing · 1 not readable")
        XCTAssertEqual(OperationsLogic.scheduleNote([]), "")
        XCTAssertEqual(OperationsLogic.scheduleNote([OpsScheduleRow(name: "a", state: "OK")]), "None late")
        XCTAssertTrue(OperationsLogic.needsAction("STALE"))
        XCTAssertFalse(OperationsLogic.needsAction("OK"))
        XCTAssertFalse(OperationsLogic.needsAction("UNKNOWN"))
    }

    func testScheduleWords() {
        XCTAssertEqual(OperationsLogic.stateWord("STALE"), "Late")
        XCTAssertEqual(OperationsLogic.stateWord("NEVER RAN"), "Never ran")
        XCTAssertEqual(OperationsLogic.stateWord("odd thing"), "Odd Thing")
        let row = OpsScheduleRow(name: "x", state: "STALE", cadence: "1d", lastRun: now.addingTimeInterval(-3 * 86_400))
        XCTAssertEqual(OperationsLogic.scheduleDetail(row, now: now), "every 1d · last run 3 d ago")
        XCTAssertEqual(OperationsLogic.scheduleDetail(OpsScheduleRow(name: "x", state: "OK"), now: now), "no run on record")
        XCTAssertEqual(OperationsLogic.scheduleDetail(OpsScheduleRow(name: "x", state: "OK", note: "not loaded"), now: now), "not loaded")
    }

    func testFailuresKeepTheOwnersFirst() {
        let all = [OpsFailure(title: "a", severity: "info"), OpsFailure(title: "b"), OpsFailure(title: "c", severity: "act"),
                   OpsFailure(title: "d", severity: "info")]
        let groups = OperationsLogic.failuresInOrder(all)
        XCTAssertEqual(groups.act.map(\.title), ["b", "c"])
        XCTAssertEqual(groups.info.map(\.title), ["a", "d"])
    }

    func testHarnessWords() {
        XCTAssertEqual(OperationsLogic.policyWord(OpsHarness(name: "x", installed: false)), "Not installed")
        XCTAssertEqual(OperationsLogic.policyWord(OpsHarness(name: "x", policy: nil)), "Unknown")
        XCTAssertEqual(OperationsLogic.policyWord(OpsHarness(name: "x", policy: "synced")), "In sync")
        XCTAssertEqual(OperationsLogic.policyWord(OpsHarness(name: "x", policy: "not wired")), "Not wired")
        XCTAssertTrue(OperationsLogic.policyOK(OpsHarness(name: "x", policy: "synced")))
        XCTAssertFalse(OperationsLogic.policyOK(OpsHarness(name: "x", installed: false, policy: "synced")))
    }

    func testTheSyncLine() {
        XCTAssertEqual(OperationsLogic.syncLine(nil, now: now), "The report does not say whether the AGENTS.md copies match.")
        XCTAssertEqual(OperationsLogic.syncLine(OpsPolicySync(status: "ok"), now: now), "Every harness copy matches the policy.")
        let drift = OpsPolicySync(status: "drift", drift: [OpsDrift(harness: "g", why: "w")], lastSync: now.addingTimeInterval(-7_200))
        XCTAssertEqual(OperationsLogic.syncLine(drift, now: now), "1 copy differs from the policy. Last sync 2 h ago.")
        XCTAssertEqual(OperationsLogic.syncLine(OpsPolicySync(status: nil), now: now), "The sync state is not known.")
        XCTAssertNil(OperationsLogic.repoLine(OpsPolicyRepos(ok: 5, differ: 0, missing: 0)))
        XCTAssertEqual(OperationsLogic.repoLine(OpsPolicyRepos(differ: 1, missing: 2, toFix: ["a", "b", "c", "d"])),
                       "Repos: 1 differ, 2 missing (a, b, c)")
    }

    func testAgentsLine() {
        XCTAssertEqual(OperationsLogic.agentsLine([:]), "No agent sessions running.")
        XCTAssertEqual(OperationsLogic.agentsLine(["claude": 6, "codex": 2, "grok": 0]), "claude 6 · codex 2")
    }

    func testSeriesScaling() {
        let points = [OpsPoint(time: now, value: 10), OpsPoint(time: now.addingTimeInterval(3_600), value: 20),
                      OpsPoint(time: now.addingTimeInterval(7_200), value: 15)]
        XCTAssertEqual(OperationsLogic.scaled(points), [0, 1, 0.5])
        XCTAssertEqual(OperationsLogic.scaled([OpsPoint(time: now, value: 1), OpsPoint(time: now, value: 1)]), [0.5, 0.5])
        XCTAssertEqual(OperationsLogic.scaled([OpsPoint(time: now, value: 1)]), [])
        XCTAssertEqual(OperationsLogic.seriesRange(points, unit: "GB"), "10 to 20 GB over the last 2 h")
        XCTAssertEqual(OperationsLogic.seriesRange([], unit: "GB"), "Not enough readings for a line yet.")
    }

    func testVerdictWords() {
        XCTAssertNil(OperationsLogic.verdictWord(nil))
        XCTAssertEqual(OperationsLogic.verdictWord("OK"), "Fine")
        XCTAssertEqual(OperationsLogic.verdictWord("busy"), "Busy")
        XCTAssertEqual(OperationsLogic.verdictWord("WARM"), "Warm")
    }

    func testAsOf() {
        XCTAssertEqual(OperationsLogic.asOf(nil, now: now), "no date on record")
        XCTAssertEqual(OperationsLogic.asOf(now.addingTimeInterval(-86_400 * 3), now: now), "as of 3 d ago")
    }
}

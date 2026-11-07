import XCTest

private func growth(_ json: String) throws -> GrowthReport {
    try JSONDecoder().decode(GrowthReport.self, from: Data(json.utf8))
}

private func sample() throws -> GrowthReport {
    guard let report = try ConsoleReport.decode(SampleFiles.data("console.v1.json")).growth.value else {
        throw TeylaError.badOutput("no growth in the sample")
    }
    return report
}

private func draftItems() throws -> [GrowthDraft] {
    let boxes = try JSONDecoder().decode([LossyBox<GrowthDraft>].self, from: SampleFiles.data("growth.v1.json"))
    return boxes.compactMap(\.value)
}

final class GrowthParsingTests: XCTestCase {
    func testTheSampleHoldsEverySection() throws {
        let report = try sample()
        XCTAssertEqual(report.headline?.display, "2/6")
        XCTAssertEqual(report.targetPerChannel, 1)
        XCTAssertEqual(report.today.count, 6)
        XCTAssertEqual(report.today[0].posted, 1)
        XCTAssertEqual(report.lastPublicDays, 2)
        XCTAssertEqual(report.queueDays, 4.5)
        XCTAssertEqual(report.gaps, 2)
        XCTAssertEqual(report.pipeline?.ideas, 66)
        XCTAssertEqual(report.pipeline?.live, 5)
        XCTAssertEqual(report.episodes.count, 2)
        XCTAssertEqual(report.episodes[0].idea, "Building a focus timer in one night")
        XCTAssertEqual(report.episodes[0].clips, 3)
        XCTAssertNil(report.episodes[1].minutes, "no minutes stays nil, never zero")
        XCTAssertEqual(report.nextRide?.title, "Ship day: sample-app 1.2")
        XCTAssertEqual(report.trends.count, 2)
        XCTAssertEqual(report.trends[0].score, 24)
        XCTAssertEqual(report.outreach?.sentWeek, 3)
        XCTAssertEqual(report.outreach?.sources.count, 2)
        XCTAssertEqual(report.channels.count, 3)
        XCTAssertNil(report.channels[2].lastPost)
        XCTAssertEqual(report.qualifiedWeek, 1)
    }

    func testAnEmptyObjectIsAnEmptyReport() throws {
        let report = try growth("{}")
        XCTAssertNil(report.headline)
        XCTAssertNil(report.targetPerChannel)
        XCTAssertTrue(report.today.isEmpty)
        XCTAssertNil(report.lastPublicDays, "no figure is nil, never zero")
        XCTAssertNil(report.queueDays)
        XCTAssertNil(report.pipeline)
        XCTAssertNil(report.nextRide)
        XCTAssertNil(report.outreach)
        XCTAssertTrue(report.trends.isEmpty)
    }

    func testNullsAndWrongTypesLeaveNilNotZero() throws {
        let report = try growth("""
        {"headline": null, "target": "many", "today": {"x": 1}, "last_public_days": "soon", "queue_days": null,
         "pipeline": {"ideas": "lots", "review": null, "ready": 3}, "episodes": 5, "next_ride": null,
         "trends": null, "outreach": {"drafts": null, "sources": "none"}, "channels": [{"platform": 4}], "qualified_week": []}
        """)
        XCTAssertNil(report.targetPerChannel)
        XCTAssertTrue(report.today.isEmpty)
        XCTAssertNil(report.lastPublicDays)
        XCTAssertNil(report.pipeline?.ideas)
        XCTAssertNil(report.pipeline?.review)
        XCTAssertEqual(report.pipeline?.ready, 3)
        XCTAssertTrue(report.episodes.isEmpty)
        XCTAssertNil(report.nextRide)
        XCTAssertNil(report.outreach?.drafts)
        XCTAssertEqual(report.outreach?.sources.count, 0)
        XCTAssertTrue(report.channels.isEmpty)
        XCTAssertNil(report.qualifiedWeek)
    }

    func testABadRowCostsOnlyItself() throws {
        let report = try growth("""
        {"today": [{"platform": "x", "language": "en", "posted": 1, "target": 1}, {"language": "es"}, 7],
         "trends": [{"title": "One", "score": 20}, {"score": 3}],
         "episodes": [{"id": "e1", "idea": "A"}, {"idea": "no id"}]}
        """)
        XCTAssertEqual(report.today.count, 1)
        XCTAssertEqual(report.trends.map(\.title), ["One"])
        XCTAssertEqual(report.episodes.map(\.id), ["e1"])
    }

    func testTheNextRideIsASentenceOrAnObject() throws {
        XCTAssertEqual(try growth(#"{"next_ride": "Film the ship day"}"#).nextRide?.title, "Film the ship day")
        let object = try growth(#"{"next_ride": {"question": "Does it ship?", "job": "Ship it"}}"#).nextRide
        XCTAssertEqual(object?.title, "Ship it")
    }

    func testASectionErrorStaysItsOwn() throws {
        let report = try ConsoleReport.decode(Data(#"{"version": 1, "growth": {"error": "no config"}}"#.utf8))
        XCTAssertEqual(report.growth, .failed("no config"))
    }
}

final class GrowthDraftTests: XCTestCase {
    func testTheWaitingQueueKeepsOnlyWhatWaits() throws {
        let all = try draftItems()
        XCTAssertEqual(all.count, 6)
        let waiting = GrowthDrafts.waiting(all)
        XCTAssertEqual(waiting.map(\.id), ["g1104-a1b2", "g1104-c3d4", "g1103-e5f6"],
                       "the best editor score first, a draft with no score after the scored ones; a held draft, an episode and an approved one stay out")
    }

    func testADraftReadsItsFields() throws {
        let draft = try XCTUnwrap(try draftItems().first)
        XCTAssertEqual(draft.platform, "x")
        XCTAssertEqual(draft.editorScore, 4.6)
        XCTAssertEqual(draft.facts.count, 2)
        XCTAssertEqual(draft.sources.first?.link, "https://example.com/sample-app/pull/12")
        XCTAssertTrue(draft.canApprove)
        XCTAssertTrue(draft.critique.hasPrefix("Concrete"))
    }

    func testAFailedCheckBlocksApproveAndSaysWhy() throws {
        let failed = try XCTUnwrap(try draftItems().first { $0.id == "g1103-e5f6" })
        XCTAssertFalse(failed.canApprove)
        XCTAssertEqual(failed.voiceOK, false)
        XCTAssertEqual(failed.checkNotes, ["banned-word: uses \"seamless\""])
        XCTAssertTrue(try XCTUnwrap(GrowthLogic.approveBlock(failed)).contains("banned-word"))
    }

    func testACheckThatNeverRanBlocksApprove() throws {
        let json = #"{"id": "g1104-zzzz", "status": "review", "kind": "post", "platform": "x", "body": "Text"}"#
        let draft = try JSONDecoder().decode(GrowthDraft.self, from: Data(json.utf8))
        XCTAssertNil(draft.voiceOK)
        XCTAssertFalse(draft.canApprove)
        XCTAssertTrue(try XCTUnwrap(GrowthLogic.approveBlock(draft)).contains("have not run"))
    }

    func testAnIdTheCliWouldRefuseIsNotADraft() {
        for id in ["../x", "g11-abcd", "G1104-abcd", "g1104-ab", "g1104-abcdefghi", "g1104-ab/cd", ""] {
            XCTAssertFalse(GrowthDrafts.isItemID(id), id)
            let json = #"{"id": "\#(id)", "status": "review"}"#
            XCTAssertThrowsError(try JSONDecoder().decode(GrowthDraft.self, from: Data(json.utf8)), id)
        }
        XCTAssertTrue(GrowthDrafts.isItemID("g1104-a1b2"))
        XCTAssertTrue(GrowthDrafts.isItemID("g0101-abcd1234"))
    }

    func testReadingAFolderCountsWhatItCannotRead() throws {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("growth-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: folder) }
        try SampleFiles.data("growth.v1.json").write(to: folder.appendingPathComponent("unused.txt"))
        let items = try JSONSerialization.jsonObject(with: SampleFiles.data("growth.v1.json")) as? [[String: Any]] ?? []
        for item in items {
            let id = item["id"] as? String ?? "x"
            try JSONSerialization.data(withJSONObject: item).write(to: folder.appendingPathComponent("\(id).json"))
        }
        try Data("{ not json".utf8).write(to: folder.appendingPathComponent("broken.json"))
        try Data(#"{"id": "nope", "status": "review"}"#.utf8).write(to: folder.appendingPathComponent("badid.json"))
        let read = try GrowthDrafts.read(directory: folder)
        XCTAssertEqual(read.drafts.count, 6)
        XCTAssertEqual(read.skipped, 1, "a file that is valid JSON but not a draft is counted; a file that is not JSON is not an item")
    }

    func testAMissingFolderIsNoDraftsNotAnError() throws {
        let read = try GrowthDrafts.read(directory: FileManager.default.temporaryDirectory.appendingPathComponent("none-\(UUID().uuidString)"))
        XCTAssertEqual(read, GrowthDrafts.Read(drafts: [], skipped: 0))
    }

    func testTheFolderFollowsTeylaHome() {
        XCTAssertEqual(GrowthDrafts.directory(home: "/Users/someone", env: [:]).path, "/Users/someone/.teyla/growth/items")
        XCTAssertEqual(GrowthDrafts.directory(home: "/Users/someone", env: ["TEYLA_HOME": "/tmp/t"]).path, "/tmp/t/growth/items")
    }
}

final class GrowthActionTests: XCTestCase {
    func testApproveRejectAndEditAreOnTheList() {
        XCTAssertEqual(ToolCommands.check(GrowthActions.approve("g1104-a1b2")), .allowed)
        XCTAssertEqual(ToolCommands.check(GrowthActions.reject("g1104-a1b2", reason: "Too salesy")), .allowed)
        XCTAssertEqual(ToolCommands.check(GrowthActions.edit("g1104-a1b2", body: "New text")), .allowed)
        XCTAssertEqual(ToolCommands.check(GrowthActions.edit("g1104-a1b2", body: "New text", hook: "New hook")), .allowed)
    }

    func testAValueThatStartsWithADashStaysAValue() {
        XCTAssertEqual(GrowthActions.reject("g1104-a1b2", reason: "-x is not a flag"),
                       ["growth", "reject", "g1104-a1b2", "--reason=-x is not a flag"])
        XCTAssertEqual(GrowthActions.edit("g1104-a1b2", body: "  --file /etc/passwd  "),
                       ["growth", "edit", "g1104-a1b2", "--body=--file /etc/passwd"])
    }

    func testAnythingElseOnGrowthIsRefused() {
        let refused: [[String]] = [
            ["growth", "approve", "--all"],
            ["growth", "approve", "g1104-a1b2", "g1104-c3d4"],
            ["growth", "approve", "../etc"],
            ["growth", "publish", "g1104-a1b2"],
            ["growth", "published", "g1104-a1b2", "https://example.com"],
            ["growth", "draft"],
            ["growth", "reject", "g1104-a1b2"],
            ["growth", "reject", "g1104-a1b2", "--reason="],
            ["growth", "reject", "g1104-a1b2", "--reason=   "],
            ["growth", "reject", "g1104-a1b2", "--reason", "too long, separate"],
            ["growth", "edit", "g1104-a1b2", "--file=/etc/passwd"],
            ["growth", "edit", "g1104-a1b2", "--body="],
            ["growth", "edit", "g1104-a1b2", "--body=ok", "--file=x"],
            ["growth"],
        ]
        for argv in refused {
            if case .refused = ToolCommands.check(argv) { continue }
            XCTFail("\(argv) must be refused")
        }
    }

    func testTheLimitsAreHeld() {
        let longReason = String(repeating: "a", count: GrowthActions.reasonLimit + 1)
        XCTAssertFalse(ToolCommands.check(GrowthActions.reject("g1104-a1b2", reason: longReason)).isAllowed)
        let longBody = String(repeating: "a", count: GrowthActions.bodyLimit + 1)
        XCTAssertFalse(ToolCommands.check(GrowthActions.edit("g1104-a1b2", body: longBody)).isAllowed)
        XCTAssertFalse(GrowthLogic.canReject(reason: "   "))
        XCTAssertTrue(GrowthLogic.canReject(reason: "Wrong fact"))
    }

    func testSaveNeedsAChange() {
        XCTAssertFalse(GrowthLogic.canSave(body: "Same", original: "Same"))
        XCTAssertFalse(GrowthLogic.canSave(body: " Same ", original: "Same"), "spaces around are not a change")
        XCTAssertTrue(GrowthLogic.canSave(body: "New", original: "Same"))
        XCTAssertTrue(GrowthLogic.canSave(body: "Same", original: "Same", hook: "New hook", originalHook: "Old"))
        XCTAssertFalse(GrowthLogic.canSave(body: "", original: "Same", hook: "New hook", originalHook: "Old"), "an item needs a body")
    }
}

final class GrowthLogicTests: XCTestCase {
    func testNamesReadAsWords() {
        XCTAssertEqual(GrowthLogic.platformName("linkedin"), "LinkedIn")
        XCTAssertEqual(GrowthLogic.platformName("mastodon"), "Mastodon")
        XCTAssertEqual(GrowthLogic.channelName(platform: "x", language: "es"), "X · Spanish")
        XCTAssertEqual(GrowthLogic.channelName(platform: "x", language: ""), "X")
        XCTAssertEqual(GrowthLogic.formatName("true-vibe-coding"), "True vibe coding")
    }

    func testSlotsCountOnlyWhatWasFilled() {
        let rows = [GrowthToday(platform: "x", posted: 1, target: 1), GrowthToday(platform: "tiktok", posted: 3, target: 1),
                    GrowthToday(platform: "youtube", posted: 0, target: 2)]
        let slots = GrowthLogic.slots(rows)
        XCTAssertEqual(slots?.posted, 2, "a channel that posted over its target does not cover another one")
        XCTAssertEqual(slots?.target, 4)
        XCTAssertNil(GrowthLogic.slots([]), "no channel is a dash, not 0 of 0")
        XCTAssertEqual(GrowthLogic.open(rows).map(\.platform), ["youtube"])
        XCTAssertEqual(GrowthLogic.slotWords(rows[1]), "1 of 1")
        XCTAssertEqual(GrowthLogic.fraction(rows[2]), 0)
    }

    func testFiguresAreDashesWhenUnknown() {
        XCTAssertNil(GrowthLogic.queueFigure(nil))
        XCTAssertEqual(GrowthLogic.queueFigure(4.5), "4.5")
        XCTAssertEqual(GrowthLogic.queueFigure(2), "2")
        XCTAssertNil(GrowthLogic.sinceFigure(nil))
        XCTAssertEqual(GrowthLogic.sinceFigure(0), "Today")
        XCTAssertEqual(GrowthLogic.sinceFigure(1), "1 day")
        XCTAssertEqual(GrowthLogic.sinceFigure(5), "5 days")
        XCTAssertTrue(GrowthLogic.queueDetail(nil, gaps: nil).contains("cannot tell"))
        XCTAssertTrue(GrowthLogic.queueDetail(0.5, gaps: 2).contains("runs dry"))
    }

    func testTheWaitingFigureNeverClaimsAnEmptyQueueItDidNotRead() {
        XCTAssertEqual(GrowthLogic.waitingDetail(count: nil, skipped: 0, why: nil), "Not read yet.")
        XCTAssertEqual(GrowthLogic.waitingDetail(count: nil, skipped: 0, why: "The folder is not readable."), "The folder is not readable.")
        XCTAssertTrue(GrowthLogic.waitingDetail(count: 0, skipped: 2, why: nil).contains("2 item files could not be read"))
        XCTAssertTrue(GrowthLogic.waitingDetail(count: 3, skipped: 0, why: nil).contains("Nothing is posted from here"))
    }

    func testThePipelineStagesKeepTheirOrderAndTheirGaps() {
        let stages = GrowthLogic.stages(GrowthPipeline(ideas: 66, review: 4))
        XCTAssertEqual(stages.map(\.label), ["Ideas", "Filming", "Cutting", "In review", "Ready to post", "Posted this week"])
        XCTAssertEqual(stages[0].count, 66)
        XCTAssertNil(stages[1].count)
        XCTAssertNil(GrowthLogic.stages(nil)[0].count)
    }

    func testLastPostAndRideReadAsDays() {
        XCTAssertEqual(GrowthLogic.lastPostWords(GrowthChannel(platform: "x", lastPost: "2026-11-04")), "Last post 4 Nov")
        XCTAssertEqual(GrowthLogic.lastPostWords(GrowthChannel(platform: "x", lastPost: nil)), "No post yet")
        XCTAssertEqual(GrowthLogic.lastPostWords(nil), "No post yet")
        XCTAssertEqual(GrowthLogic.rideDetail(GrowthRide(title: "Ship", when: "2026-11-06")), "6 Nov")
        XCTAssertEqual(GrowthLogic.rideDetail(GrowthRide(title: "Ship", when: nil)), "")
    }

    func testEpisodeAndTrendWords() {
        XCTAssertEqual(GrowthLogic.episodeDetail(GrowthEpisode(id: "e", idea: "A", minutes: nil, footage: 2, clips: 1)), "1 clip · 2 footage files")
        XCTAssertEqual(GrowthLogic.episodeDetail(GrowthEpisode(id: "e", idea: "A")), "")
        XCTAssertEqual(GrowthLogic.trendScore(24), "24 of 30")
        XCTAssertNil(GrowthLogic.trendScore(nil))
        XCTAssertEqual(GrowthLogic.outreachLine(GrowthOutreach(sentWeek: 3, repliesWeek: 1, callsWeek: 0)), "3 sent · 1 reply · 0 calls this week")
        XCTAssertEqual(GrowthLogic.outreachLine(GrowthOutreach()), "No outreach count in the report.")
    }

    func testADraftTitleFallsBackToItsText() {
        XCTAssertEqual(GrowthLogic.draftTitle(GrowthDraft(id: "g1104-abcd", idea: "  ", body: "First line\nSecond")), "First line")
        XCTAssertEqual(GrowthLogic.draftTitle(GrowthDraft(id: "g1104-abcd")), "Untitled draft")
        XCTAssertEqual(GrowthLogic.draftDetail(GrowthDraft(id: "g1104-abcd", platform: "x", language: "en", format: "lesson", product: "sample-app")),
                       "X · English · Lesson · sample-app")
        XCTAssertEqual(GrowthLogic.editorWords(GrowthDraft(id: "g1104-abcd", editorScore: 4.6)), "Editor 4.6 of 5")
        XCTAssertNil(GrowthLogic.editorWords(GrowthDraft(id: "g1104-abcd")))
    }
}

// MARK: Publish and engage

final class GrowthEngageTests: XCTestCase {
    func testOnlyTheAppsOwnEngageAndPublishCommandsPass() {
        let allowed: [[String]] = [
            GrowthEngage.list(scan: true),
            GrowthEngage.list(scan: false),
            GrowthEngage.done([1]),
            GrowthEngage.done([3, 40]),
            GrowthEngage.done(EngageRow(n: 4, url: "https://x.com/a/status/1")),
            GrowthEngage.publish(["g1104-a1b2"]),
            GrowthEngage.publish(["g1104-a1b2", "g1104-c3d4"]),
        ]
        for argv in allowed { XCTAssertTrue(ToolCommands.check(argv).isAllowed, "\(argv)") }
        let refused: [[String]] = [
            ["growth", "publish", "g1104-a1b2"],
            ["growth", "publish", "--day", "2026-11-07", "--json"],
            ["growth", "publish", "g1104-a1b2", "--retry", "--json"],
            ["growth", "publish", "g1104-a1b2", "g1104-a1b2", "--json"],
            ["growth", "publish", "../etc", "--json"],
            GrowthEngage.publish((1...7).map { "g1104-aaa\($0)" }),
            ["growth", "connect", "linkedin"],
            ["growth", "engage"],
            ["growth", "engage", "init"],
            ["growth", "engage", "open", "1"],
            ["growth", "engage", "done"],
            ["growth", "engage", "done", "0"],
            ["growth", "engage", "done", "41"],
            ["growth", "engage", "done", "01"],
            ["growth", "engage", "done", "-1"],
            ["growth", "engage", "done", "1", "--force"],
            ["growth", "engage", "done", "1", "--url=http://x.com/a"],
            ["growth", "engage", "done", "1", "2", "--url=https://x.com/a"],
            ["growth", "engage", "done", "--url=https://x.com/a"],
            ["growth", "engage", "--json", "--refresh"],
        ]
        for argv in refused {
            if case .refused = ToolCommands.check(argv) { continue }
            XCTFail("\(argv) must be refused")
        }
    }

    func testTheEngageListDecodesAndDropsALinkThatIsNotHTTPS() throws {
        let json = #"""
        {"version": 1, "day": "2026-11-07", "goal": 20, "total": 2, "done": 1,
         "rows": [{"n": 1, "url": "https://x.com/a/status/1", "author": "@a", "group": "founders", "why": "w", "angle": "ask", "source": "x", "done": true},
                  {"n": 2, "url": "javascript:alert(1)", "author": "@b"},
                  {"n": 3, "url": "https://b.example.com/p/1", "author": "B", "source": "rss"}],
         "sources": {"x": "1 scan", "rss": "1 feed"}, "notes": [], "targets": {"exists": true, "x": 2, "rss": 1}}
        """#
        let doc = try EngageReport.decode(Data(json.utf8))
        XCTAssertEqual(doc.rows.map(\.n), [1, 3])
        XCTAssertEqual(doc.nextOpen?.n, 3)
        XCTAssertTrue(doc.targetsExist)
        XCTAssertEqual(doc.targetHandles, 3)
        XCTAssertEqual(doc.sources["x"], "1 scan")
    }

    func testAPublishReportSaysWhatWentLiveAndWhatNeedsTheOwner() throws {
        let json = #"""
        {"version": 1, "published": 1, "already": 0, "packets": 1, "failed": 1,
         "results": [{"id": "g1104-a1b2", "network": "linkedin", "status": "published", "url": "https://www.linkedin.com/feed/update/urn:li:share:1"},
                     {"id": "g1104-a1b2", "network": "x", "status": "packet", "message": "X stays manual"},
                     {"id": "g1104-c3d4", "network": "threads", "status": "unknown", "message": "check threads"}]}
        """#
        let report = try PublishReport.decode(Data(json.utf8))
        XCTAssertEqual(report.results.count, 3)
        XCTAssertTrue(report.results[0].isLive)
        XCTAssertNotNil(report.results[0].link)
        XCTAssertTrue(report.results[2].needsOwner)
        XCTAssertEqual(report.summary, "1 published, 1 to post by hand from the packet, 1 need you.")
    }

    func testOnlyApprovedItemsOnANetworkAreReady() {
        let items = [
            GrowthDraft(id: "g1104-aaaa", status: "approved", platform: "linkedin", updated: "2026-11-02"),
            GrowthDraft(id: "g1104-bbbb", status: "ready", platform: "threads", updated: "2026-11-01"),
            GrowthDraft(id: "g1104-cccc", status: "approved", platform: "master"),
            GrowthDraft(id: "g1104-dddd", status: "approved", kind: "episode", platform: "youtube"),
            GrowthDraft(id: "g1104-eeee", status: "review", platform: "x"),
            GrowthDraft(id: "g1104-ffff", status: "published", platform: "x"),
        ]
        XCTAssertEqual(GrowthEngage.ready(items).map(\.id), ["g1104-bbbb", "g1104-aaaa"])
    }

    func testTheConsoleCarriesTheEngageCount() throws {
        let json = #"{"today": [], "engage": {"day": "2026-11-07", "scanned": true, "total": 20, "done": 4, "goal": 20}}"#
        let report = try JSONDecoder().decode(GrowthReport.self, from: Data(json.utf8))
        XCTAssertEqual(report.engage, GrowthEngageCount(day: "2026-11-07", scanned: true, total: 20, done: 4, goal: 20))
        XCTAssertNil(try JSONDecoder().decode(GrowthReport.self, from: Data(#"{"today": []}"#.utf8)).engage)
    }
}

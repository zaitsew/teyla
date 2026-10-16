import XCTest

final class ModelDecodingTests: XCTestCase {
    /// tests/fixtures/state.json is the shared contract fixture at the repo root.
    private func fixtureData() throws -> Data {
        let here = URL(fileURLWithPath: #filePath)
        let url = here.deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("tests/fixtures/state.json")
        return try Data(contentsOf: url)
    }

    func testDecodesFixture() throws {
        let snapshot = try TeylaCLI.decodeSnapshot(fixtureData())
        XCTAssertEqual(snapshot.version, 1)
        XCTAssertEqual(snapshot.totals.questions, 3)
        XCTAssertEqual(snapshot.totals.spentTodayUSD, 4.1)
        XCTAssertEqual(snapshot.brief?.source, "rules")
        XCTAssertEqual(snapshot.asks.map(\.rank), [1, 2, 3])
        XCTAssertEqual(snapshot.asks[0].options, ["Keep iPhone 1.0", "Swap to 1.1"])
        XCTAssertEqual(snapshot.asks[0].unblocks, "the iPhone release")
        XCTAssertEqual(snapshot.asks[2].delivery, "codex")
        XCTAssertEqual(snapshot.asks[0].ageSeconds, 25200)
        XCTAssertEqual(snapshot.products.map(\.state), [.waiting, .waiting, .shipped, .quiet])
        XCTAssertEqual(snapshot.running.count, 2)
        XCTAssertNotNil(snapshot.generatedDate)
    }

    func testToleratesNullsMissingAndUnknownFields() throws {
        let json = """
        {"version": 2, "generated": null, "brief": null, "future_field": {"a": 1},
         "totals": {"questions": 1, "running": null, "spent_today_usd": null},
         "asks": [{"id": "x1", "question": null, "options": null, "age_s": 5, "extra": true},
                  {"question": "no id, dropped"}],
         "products": [{"name": "p", "state": "something-new"}],
         "running": null}
        """
        let snapshot = try TeylaCLI.decodeSnapshot(Data(json.utf8))
        XCTAssertNil(snapshot.brief)
        XCTAssertNil(snapshot.totals.spentTodayUSD)
        XCTAssertEqual(snapshot.asks.count, 1)
        XCTAssertEqual(snapshot.asks[0].question, "")
        XCTAssertEqual(snapshot.asks[0].options, [])
        XCTAssertEqual(snapshot.products[0].state, .quiet)
        XCTAssertEqual(snapshot.running, [])
    }

    func testGarbageIsAnError() {
        XCTAssertThrowsError(try TeylaCLI.decodeSnapshot(Data("not json".utf8)))
    }

    func testAnswerResult() throws {
        let data = Data(#"{"ok": true, "via": "claude-bg", "detail": "", "id": "7c222b3d"}"#.utf8)
        let result = try JSONDecoder().decode(AnswerResult.self, from: data)
        XCTAssertTrue(result.ok)
        XCTAssertEqual(Format.sentLine(via: result.via), "Sent to the session via claude-bg")
    }

    func testFormatting() {
        XCTAssertEqual(Format.product("cellar"), "Cellar")
        XCTAssertEqual(Format.age(seconds: 25200), "7h")
        XCTAssertEqual(Format.age(seconds: 30), "just now")
        XCTAssertEqual(Format.model("claude-sonnet-5-5"), "Sonnet")
        XCTAssertEqual(Format.subline(questions: 3, running: 2, spentUSD: 4.1),
                       "3 questions · 2 sessions running · $4.10 spent today")
        XCTAssertEqual(Format.subline(questions: 1, running: 1, spentUSD: nil), "1 question · 1 session running")
    }
}

final class AnswerAndLinkTests: XCTestCase {
    func testAnswerTextFollowsDoubleDash() {
        XCTAssertEqual(TeylaCLI.answerArguments(id: "7c222b3d", text: "-1, keep it"),
                       ["answer", "7c222b3d", "--json", "--", "-1, keep it"])
    }

    func testLinkKinds() {
        XCTAssertEqual(SessionLink("claude://claude.ai/epitaxy/local_1"),
                       .url(URL(string: "claude://claude.ai/epitaxy/local_1")!))
        XCTAssertEqual(SessionLink("codex://threads/0000"), .url(URL(string: "codex://threads/0000")!))
        XCTAssertEqual(SessionLink("claude --resume abc-123"), .command("claude --resume abc-123"))
        XCTAssertEqual(SessionLink("  "), .none)
        XCTAssertEqual(SessionLink(""), .none)
    }
}

final class BinaryLookupTests: XCTestCase {
    func testOrder() {
        let list = TeylaBinary.candidates(env: ["TEYLA_BIN": "/custom/teyla"], home: "/h")
        XCTAssertEqual(list, ["/custom/teyla", "/h/.local/bin/teyla", "/opt/homebrew/bin/teyla", "/usr/local/bin/teyla"])
    }

    func testEmptyEnvIsIgnored() {
        let list = TeylaBinary.candidates(env: ["TEYLA_BIN": ""], home: "/h")
        XCTAssertEqual(list.first, "/h/.local/bin/teyla")
    }

    func testFirstExecutableWins() {
        let found = TeylaBinary.locate(env: [:], home: "/h") { $0 == "/opt/homebrew/bin/teyla" || $0 == "/usr/local/bin/teyla" }
        XCTAssertEqual(found, "/opt/homebrew/bin/teyla")
    }

    func testExplicitOverrideBeatsEverything() {
        let found = TeylaBinary.locate(env: ["TEYLA_BIN": "/x/teyla"], home: "/h") { _ in true }
        XCTAssertEqual(found, "/x/teyla")
    }

    func testNoneFound() {
        XCTAssertNil(TeylaBinary.locate(env: [:], home: "/h") { _ in false })
    }
}

final class FixtureModeTests: XCTestCase {
    func testStateComesFromFixtureAndWritesAreSimulated() async throws {
        let here = URL(fileURLWithPath: #filePath)
        let path = here.deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("tests/fixtures/state.json").path
        let cli = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": path], home: "/nonexistent")
        let snapshot = try await cli.state()
        XCTAssertEqual(snapshot.asks.count, 3)
        let result = try await cli.answer(id: "7c222b3d", text: "Swap to 1.1")
        XCTAssertEqual(result.via, "fixture")
    }

    func testMissingBinaryIsReported() async {
        let cli = TeylaCLI(env: ["PATH": ""], home: "/nonexistent-home")
        // Only meaningful where no system-wide teyla exists; skip otherwise.
        guard TeylaBinary.locate(env: [:], home: "/nonexistent-home") == nil else { return }
        do {
            _ = try await cli.state()
            XCTFail("expected an error")
        } catch {
            XCTAssertEqual(error as? TeylaError, .binaryNotFound)
        }
    }
}

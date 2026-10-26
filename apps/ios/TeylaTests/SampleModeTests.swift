import XCTest

@MainActor
final class SampleModeTests: XCTestCase {
    private struct NoKeyStore: KeyStore {
        func load() -> Data? { nil }
        func save(_ key: Data) throws {}
        func delete() {}
    }

    private static func sampleJSON() -> Data? {
        let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Teyla/Resources/sample-state.json")
        return try? Data(contentsOf: url)
    }

    private func model(environment: [String: String] = [:], defaults: UserDefaults? = nil) -> AppModel {
        let defaults = defaults ?? UserDefaults(suiteName: "SampleModeTests-\(UUID().uuidString)")!
        return AppModel(environment: environment, defaults: defaults, keyStore: NoKeyStore(),
                        sampleData: { Self.sampleJSON() })
    }

    func testTheBundledSampleDecodesWithAPortfolioAndAnOlderQuestion() throws {
        let now = Date()
        let snapshot = try XCTUnwrap(SampleData.snapshot(from: XCTUnwrap(Self.sampleJSON()), now: now))
        XCTAssertEqual(snapshot.version, 3)
        XCTAssertEqual(snapshot.portfolio?.products.count, 5)
        XCTAssertEqual(snapshot.portfolio.map(PortfolioFormat.headline),
                       "1 off track \u{00B7} 1 at risk \u{00B7} 2 on track \u{00B7} 1 parked")
        // The sample never looks stale: it was "written" now.
        let generated = try XCTUnwrap(snapshot.generatedDate)
        XCTAssertLessThan(abs(generated.timeIntervalSince(now)), 2)
        let split = PhoneFormat.splitAsks(snapshot.asks, snapshot: snapshot, now: now)
        XCTAssertEqual(split.older.count, 2)
        XCTAssertEqual(split.fresh.count, 3)
        // Every id the phone could send to is a valid relay target.
        XCTAssertTrue(snapshot.asks.allSatisfy { OutboxEntry.isTarget($0.id) })
        XCTAssertTrue(snapshot.products.allSatisfy { OutboxEntry.isTarget($0.name) })
    }

    func testTimestampsMoveWithTheSnapshot() throws {
        let then = ISODate.parse("2026-10-25T09:15:54Z")!
        let later = then.addingTimeInterval(3 * 86_400)
        let snapshot = try XCTUnwrap(SampleData.snapshot(from: XCTUnwrap(Self.sampleJSON()), now: later))
        let portfolio = try XCTUnwrap(snapshot.portfolio)
        XCTAssertEqual(portfolio.checkedStores, "2026-10-28T06:00:00Z")
    }

    func testSampleModeSkipsOnboardingAndShowsTheSample() async throws {
        let model = model(environment: ["TEYLA_SAMPLE": "1"])
        XCTAssertTrue(model.isSample)
        XCTAssertEqual(model.setupStep, 3)
        await model.refresh()
        XCTAssertEqual(model.connection, .sample)
        XCTAssertNotNil(model.snapshot?.portfolio)
    }

    func testWithoutAPairedMacTheAppStartsInOnboardingAndTheSampleIsOptional() async throws {
        let model = model()
        XCTAssertFalse(model.isSample)
        XCTAssertEqual(model.setupStep, 0)
        model.startSample()
        XCTAssertTrue(model.isSample)
        XCTAssertEqual(model.setupStep, 3)
        XCTAssertNotNil(model.snapshot)
        model.leaveSample()
        XCTAssertFalse(model.isSample)
        XCTAssertEqual(model.setupStep, 0)
        XCTAssertNil(model.snapshot)
    }

    func testTheChoiceSurvivesARelaunchUntilThePairButtonIsTapped() {
        let defaults = UserDefaults(suiteName: "SampleModeTests-\(UUID().uuidString)")!
        model(defaults: defaults).startSample()
        let relaunched = model(defaults: defaults)
        XCTAssertTrue(relaunched.isSample)
        relaunched.leaveSample()
        XCTAssertFalse(model(defaults: defaults).isSample)
    }

    func testEverySendIsSimulatedAndSaysNothingWasSent() async throws {
        let model = model(environment: ["TEYLA_SAMPLE": "1"])
        await model.refresh()
        let snapshot = try XCTUnwrap(model.snapshot)
        let ask = try XCTUnwrap(snapshot.asks.first)
        let sent = await model.send(kind: .answer, target: ask.id, aboutText: ask.question, label: "Answer", text: "Ship now")
        XCTAssertTrue(sent)
        let action = try XCTUnwrap(model.action(for: .answer, target: ask.id))
        let outcome = try XCTUnwrap(action.outcome, "the result is there at once, no Mac to wait for")
        XCTAssertEqual(PhoneFormat.outcomeLine(outcome), "Sample: nothing was sent")

        let product = try XCTUnwrap(model.dispatchTargets.first)
        let task = await model.send(kind: .dispatch, target: product.name, aboutText: "", label: product.name, text: "Add a tester")
        XCTAssertTrue(task)
        XCTAssertEqual(model.sentWithoutCard(in: snapshot).map(\.kind), [.dispatch])
    }

    func testLeavingTheSampleDropsWhatWasSentInIt() async throws {
        let model = model(environment: ["TEYLA_SAMPLE": "1"])
        await model.refresh()
        let ask = try XCTUnwrap(model.snapshot?.asks.first)
        _ = await model.send(kind: .answer, target: ask.id, aboutText: "", label: "A", text: "Yes")
        XCTAssertEqual(model.pending.count, 1)
        model.leaveSample()
        XCTAssertTrue(model.pending.isEmpty)
    }

    func testBadSampleDataShowsTheWaitingScreenNotACrash() async {
        let defaults = UserDefaults(suiteName: "SampleModeTests-\(UUID().uuidString)")!
        let model = AppModel(environment: ["TEYLA_SAMPLE": "1"], defaults: defaults, keyStore: NoKeyStore(),
                             sampleData: { Data("not json".utf8) })
        await model.refresh()
        XCTAssertEqual(model.connection, .waiting)
        XCTAssertNil(model.snapshot)
    }
}

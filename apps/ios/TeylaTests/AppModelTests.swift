import XCTest

@MainActor
final class AppModelTests: XCTestCase {
    private struct NoKeyStore: KeyStore {
        func load() -> Data? { nil }
        func save(_ key: Data) throws {}
        func delete() {}
    }

    private func fixtureURL() -> URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("tests/fixtures/state.v2.json")
    }

    private func model() -> AppModel {
        let defaults = UserDefaults(suiteName: "AppModelTests-\(UUID().uuidString)")!
        return AppModel(environment: ["TEYLA_STATE_FIXTURE": fixtureURL().path], defaults: defaults,
                        keyStore: NoKeyStore())
    }

    func testAnAnswerWhoseQuestionTheMacDroppedKeepsItsResultVisible() async throws {
        let model = model()
        await model.refresh()
        var snapshot = try XCTUnwrap(model.snapshot)
        let ask = try XCTUnwrap(snapshot.asks.first)
        let sent = await model.send(kind: .answer, target: ask.id, aboutText: ask.question, label: "Answer", text: "Keep it")
        XCTAssertTrue(sent)
        XCTAssertTrue(model.sentWithoutCard(in: snapshot).isEmpty, "the question is still on its card")
        snapshot.asks.removeAll { $0.id == ask.id }
        XCTAssertEqual(model.sentWithoutCard(in: snapshot).map(\.target), [ask.id])
    }

    func testACorrectionStaysVisibleOnceItsSessionStopsRunning() async throws {
        let model = model()
        await model.refresh()
        var snapshot = try XCTUnwrap(model.snapshot)
        let session = try XCTUnwrap(snapshot.running.first { $0.correct == "codex-queue" })
        _ = await model.send(kind: .say, target: session.ref, aboutText: session.title, label: session.title, text: "Use the cache")
        XCTAssertTrue(model.sentWithoutCard(in: snapshot).isEmpty)
        snapshot.running.removeAll { $0.ref == session.ref }
        XCTAssertEqual(model.sentWithoutCard(in: snapshot).map(\.kind), [.say])
    }

    func testANewTaskIsAlwaysListedApart() async throws {
        let model = model()
        await model.refresh()
        let snapshot = try XCTUnwrap(model.snapshot)
        let product = try XCTUnwrap(model.dispatchTargets.first)
        _ = await model.send(kind: .dispatch, target: product.name, aboutText: "", label: product.name, text: "Add a tester")
        XCTAssertEqual(model.sentWithoutCard(in: snapshot).map(\.kind), [.dispatch])
    }

    func testNothingIsSendingOnceASendHasReturned() async throws {
        let model = model()
        await model.refresh()
        let ask = try XCTUnwrap(model.snapshot?.asks.first)
        XCTAssertFalse(model.isSending(.answer, target: ask.id))
        _ = await model.send(kind: .answer, target: ask.id, aboutText: ask.question, label: "A", text: "Yes")
        XCTAssertFalse(model.isSending(.answer, target: ask.id))
    }
}

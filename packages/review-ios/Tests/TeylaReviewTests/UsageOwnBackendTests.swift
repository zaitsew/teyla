import XCTest
@testable import TeylaReview

/// The `deliverUsage` closure: a product with its own backend sends usage batches itself, with no channel key.
private final class Calls: @unchecked Sendable {
    private let lock = NSLock()
    private var answers: [Bool]
    private(set) var batches: [ReviewUsageBatch] = []
    init(answers: [Bool] = []) { self.answers = answers }
    func take(_ batch: ReviewUsageBatch) -> Bool {
        lock.lock(); defer { lock.unlock() }
        batches.append(batch)
        return answers.isEmpty ? true : answers.removeFirst()
    }
}

final class UsageOwnBackendTests: XCTestCase {
    private let channel = ChannelConfig(url: "https://channel.example.invalid", key: "test-key")!

    private func filled(_ n: Int = 3) -> UsageStore {
        let store = UsageStore(url: nil)
        for i in 0..<n { store.append(UsageEvent(t: 1_793_400_000 + i, k: .action, id: "plan.save", r: "done", ms: nil, b: "212", d: nil)) }
        return store
    }

    private func sender(
        store: UsageStore, owner: Bool = false, consent: UsageConsent.State, deliverUsage: ReviewUsageDeliver?,
        channel: ChannelConfig? = nil
    ) -> UsageSender {
        UsageSender(
            store: store, isActive: { true }, isOwnerDevice: { owner }, consent: { consent },
            appInfo: { Fixtures.app }, declared: { UsageAllowList(screens: [], actions: ["plan.save"], tasks: []) },
            install: { "0b8f5c1e-7a2d-4e63-9d10-6c4a8e2f1b57" },
            transport: { UsageDelivery.transport(deliverUsage: deliverUsage, channel: channel) },
            now: { Date(timeIntervalSince1970: 1_793_400_100) })
    }

    func testTheClosureGetsTheBatchIdAndTheEncodedBytes() async throws {
        let calls = Calls()
        let store = filled()
        let sent = await sender(store: store, consent: .allowed, deliverUsage: { calls.take($0) ? true : false }).sendPending()
        XCTAssertEqual(sent, 3)
        XCTAssertEqual(store.count, 0)
        let batch = try XCTUnwrap(calls.batches.first)
        XCTAssertTrue(ChannelDelivery.isValidID(batch.id))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: batch.json) as? [String: Any])
        XCTAssertEqual(object["id"] as? String, batch.id)
        XCTAssertEqual(object["kind"] as? String, "usage")
        XCTAssertEqual(Set(object.keys), UsageDelivery.payloadKeys)
    }

    func testTheClosureWinsOverTheInfoPlistChannel() async {
        let calls = Calls()
        let store = filled()
        // A channel is configured too; the closure still takes the batch.
        let sent = await sender(store: store, consent: .allowed, deliverUsage: { calls.take($0) }, channel: channel).sendPending()
        XCTAssertEqual(sent, 3)
        XCTAssertEqual(calls.batches.count, 1)
        XCTAssertEqual(store.count, 0)
    }

    func testWithoutAClosureTheChannelIsStillTheRoute() {
        XCTAssertNotNil(UsageDelivery.transport(deliverUsage: nil, channel: channel))
        XCTAssertNil(UsageDelivery.transport(deliverUsage: nil, channel: nil))
        XCTAssertNotNil(UsageDelivery.transport(deliverUsage: { _ in true }, channel: nil))
    }

    func testAFalseAnswerKeepsTheBatchAndRetriesWithTheSameId() async {
        let calls = Calls(answers: [false, true])
        let store = filled()
        let s = sender(store: store, consent: .allowed, deliverUsage: { calls.take($0) })
        let first = await s.sendPending()
        XCTAssertEqual(first, 0)
        XCTAssertEqual(store.count, 3)
        let second = await s.sendPending()
        XCTAssertEqual(second, 3)
        XCTAssertEqual(store.count, 0)
        XCTAssertEqual(calls.batches.count, 2)
        XCTAssertEqual(calls.batches[0].id, calls.batches[1].id)
    }

    func testNothingIsSentBeforeConsent() async {
        let calls = Calls()
        let store = filled()
        let sent = await sender(store: store, consent: .unset, deliverUsage: { calls.take($0) }).sendPending()
        XCTAssertEqual(sent, 0)
        XCTAssertTrue(calls.batches.isEmpty)
        XCTAssertEqual(store.count, 3)
    }

    func testNothingIsSentAfterNotNow() async {
        let calls = Calls()
        let sent = await sender(store: filled(), consent: .declined, deliverUsage: { calls.take($0) }).sendPending()
        XCTAssertEqual(sent, 0)
        XCTAssertTrue(calls.batches.isEmpty)
    }

    func testAProductWithTheClosureAndNoPairingIsAskedOnce() {
        let s = sender(store: filled(), consent: .unset, deliverUsage: { _ in true })
        XCTAssertTrue(s.transportAvailable)
        XCTAssertTrue(UsageConsent.noticeNeeded(isOwnerDevice: false, state: .unset))
        XCTAssertFalse(UsageConsent.noticeNeeded(isOwnerDevice: false, state: .allowed))
    }

    func testTheConfigurationHoldsTheClosureNextToDeliver() {
        var configuration = TeylaReview.Configuration()
        XCTAssertNil(configuration.deliverUsage)
        configuration.deliverUsage = { _ in true }
        XCTAssertNotNil(configuration.deliverUsage)
    }
}

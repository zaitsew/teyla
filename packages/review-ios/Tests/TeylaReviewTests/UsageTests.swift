import XCTest
@testable import TeylaReview

/// A clock the tests move by hand.
private final class Clock {
    var date = Date(timeIntervalSince1970: 1_793_400_000)
    func advance(_ seconds: TimeInterval) { date = date.addingTimeInterval(seconds) }
    func now() -> Date { date }
}

private final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private(set) var ids: [String] = []
    private(set) var bodies: [Data] = []
    func add(_ id: String, _ body: Data) { lock.lock(); ids.append(id); bodies.append(body); lock.unlock() }
}

final class UsageTests: XCTestCase {
    private let screens = ["trip.timeline", "trip.detail", "settings.main", "never.opened"]
    private let actions = ["trip.addButton", "trip.row", "plan.save"]
    private let tasks = ["plan.day", "add.trip"]

    private func defaults() -> UserDefaults { UserDefaults(suiteName: "teyla.usage.tests." + UUID().uuidString)! }

    private func recorder(
        clock: Clock = Clock(), store: UsageStore = UsageStore(url: nil), active: Bool = true, mayRecord: Bool = true
    ) -> (UsageRecorder, UsageStore, Clock) {
        let r = UsageRecorder(store: store, isActive: { active }, mayRecord: { mayRecord }, now: clock.now, build: { "212" })
        r.configure(screens: screens, actions: actions, tasks: tasks)
        return (r, store, clock)
    }

    // MARK: store builds record nothing

    func testAStoreBuildRecordsNothingAndWritesNoFile() {
        let url = Fixtures.tempDir().appendingPathComponent("usage.json")
        let storeBuild = BuildChannel.detect(isDebug: false, receiptName: "receipt", receiptExists: true)
        XCTAssertEqual(storeBuild, .appStore)
        XCTAssertFalse(storeBuild.permitsReview)
        // The same rule `TeylaReview.isActive` applies: review mode on AND not an App Store install.
        let store = UsageStore(url: url)
        let clock = Clock()
        let r = UsageRecorder(store: store, isActive: { true && storeBuild.permitsReview }, now: clock.now, build: { "212" })
        r.configure(screens: screens, actions: actions, tasks: tasks)
        r.appBecameActive()
        r.screen("trip.timeline")
        clock.advance(0.5)
        r.screen("trip.detail")
        r.action("trip.addButton", result: .done)
        for _ in 0..<3 { r.tap("trip.addButton") }
        r.task("plan.day", .start)
        r.task("plan.day", .success)
        r.sheetDismissed("trip.detail", changed: false)
        r.setVariant(decision: "nav", variant: "bottom")
        r.appWentToBackground()
        r.appWillTerminate()
        store.flush()
        XCTAssertEqual(store.count, 0)
        XCTAssertFalse(FileManager.default.fileExists(atPath: url.path))
    }

    func testThePublicEntryPointsDoNothingWhenReviewModeIsOff() {
        #if TEYLA_REVIEW
        TeylaReview.enabledOverride = false
        defer { TeylaReview.enabledOverride = nil }
        XCTAssertFalse(TeylaReview.isActive)
        TeylaUsage.configure(screens: screens, actions: actions, tasks: tasks)
        TeylaUsage.screen("trip.timeline")
        TeylaUsage.action("trip.addButton", result: .done)
        TeylaUsage.task("plan.day", .start)
        XCTAssertNil(TeylaUsage.engine)
        XCTAssertFalse(TeylaUsage.consentNeeded)
        #endif
    }

    // MARK: allow-lists and ids

    func testAnIdOffTheAllowListIsDropped() {
        let (r, store, _) = recorder()
        r.screen("secret.screen")
        r.action("delete.everything", result: .done)
        r.task("not.a.task", .start)
        r.tap("unknown.button")
        r.sheetDismissed("secret.screen", changed: false)
        XCTAssertEqual(store.count, 0)
        r.screen("trip.timeline")
        r.action("plan.save", result: .done)
        r.task("plan.day", .start)
        XCTAssertEqual(store.events.map(\.k), [.screen, .action, .task])
    }

    func testAnEmptyAllowListRecordsNothing() {
        let store = UsageStore(url: nil)
        let r = UsageRecorder(store: store, isActive: { true }, now: Clock().now, build: { "1" })
        r.screen("trip.timeline")
        r.action("plan.save", result: .done)
        XCTAssertEqual(store.count, 0)
    }

    func testATitleOrSentenceCannotBeDeclaredAsAnId() {
        let store = UsageStore(url: nil)
        let r = UsageRecorder(store: store, isActive: { true }, now: Clock().now, build: { "1" })
        r.configure(screens: ["Trip to Lisbon with Ana", "trip.timeline"], actions: ["", "a b"], tasks: ["plan.day"])
        r.screen("Trip to Lisbon with Ana")
        r.screen("trip.timeline")
        r.action("a b", result: .done)
        XCTAssertEqual(store.events.map(\.id), ["trip.timeline"])
    }

    func testTheDynamicSuffixIsStripped() {
        let cases: [(String, String)] = [
            ("trip.row.3F2A9C10-5B7E-4D0A-9C1E-2A6B8D4F0E11", "trip.row"),
            ("trip.row.12", "trip.row"),
            ("trip.row.12.34", "trip.row"),
            ("trip.row-12", "trip.row"),
            ("trip.row_12", "trip.row"),
            ("trip.row:7", "trip.row"),
            ("trip.row-3F2A9C10-5B7E-4D0A-9C1E-2A6B8D4F0E11", "trip.row"),
            ("trip.row_3f2a9c105b7e", "trip.row"),
            ("trip.addButton", "trip.addButton"),
            ("step2.next", "step2.next"),
            ("trip.deadbeef", "trip.deadbeef"),          // hex letters only: a word, not an id
            ("plan.save-and-close", "plan.save-and-close"),
        ]
        for (raw, expected) in cases { XCTAssertEqual(UsageID.normalize(raw), expected, raw) }
    }

    func testAnActionWithADynamicSuffixIsRecordedUnderItsBaseId() {
        let (r, store, _) = recorder()
        r.action("trip.row.3F2A9C10-5B7E-4D0A-9C1E-2A6B8D4F0E11", result: .undone)
        XCTAssertEqual(store.events.first?.id, "trip.row")
        XCTAssertEqual(store.events.first?.r, "undone")
    }

    // MARK: dead ends and repeat taps, with an injected clock

    func testAScreenLeftWithinTwoSecondsIsADeadEnd() {
        let (r, store, clock) = recorder()
        r.screen("trip.timeline")
        clock.advance(5)
        r.screen("trip.detail")
        clock.advance(1.5)
        r.screen("settings.main")
        XCTAssertEqual(store.events.map(\.k), [.screen, .screen, .deadEnd, .screen])
        let dead = store.events[2]
        XCTAssertEqual(dead.id, "trip.detail")
        XCTAssertEqual(dead.r, "screen")
        XCTAssertEqual(dead.ms, 1500)
    }

    func testAScreenLeftAfterMoreThanTwoSecondsIsNot() {
        let (r, store, clock) = recorder()
        r.screen("trip.timeline")
        clock.advance(2.1)
        r.screen("trip.detail")
        XCTAssertFalse(store.events.contains { $0.k == .deadEnd })
    }

    func testTheSameScreenAppearingAgainIsNotRecordedTwice() {
        let (r, store, clock) = recorder()
        r.screen("trip.timeline")
        clock.advance(0.2)
        r.screen("trip.timeline")
        XCTAssertEqual(store.events.map(\.k), [.screen])
    }

    func testAScreenOpenWhileTheAppWasAwayIsNotADeadEnd() {
        let (r, store, clock) = recorder()
        r.appBecameActive()
        r.screen("trip.timeline")
        clock.advance(1)
        r.appWentToBackground()
        clock.advance(60)
        r.appBecameActive()
        clock.advance(0.5)
        r.screen("trip.detail")
        XCTAssertFalse(store.events.contains { $0.k == .deadEnd })
    }

    func testASheetDismissedWithNothingChangedIsADeadEnd() {
        let (r, store, _) = recorder()
        r.sheetDismissed("trip.detail", changed: true)
        XCTAssertEqual(store.count, 0)
        r.sheetDismissed("trip.detail", changed: false)
        XCTAssertEqual(store.events.first?.k, .deadEnd)
        XCTAssertEqual(store.events.first?.r, "sheet")
        XCTAssertEqual(store.events.first?.id, "trip.detail")
    }

    func testThreeTapsInOneSecondIsARepeatTap() {
        let (r, store, clock) = recorder()
        r.tap("trip.addButton"); clock.advance(0.3)
        r.tap("trip.addButton"); clock.advance(0.3)
        XCTAssertEqual(store.count, 0)
        r.tap("trip.addButton")
        XCTAssertEqual(store.events.map(\.k), [.repeatTap])
        XCTAssertEqual(store.events.first?.id, "trip.addButton")
        // The burst is spent: a fourth tap starts a new count.
        clock.advance(0.1)
        r.tap("trip.addButton")
        XCTAssertEqual(store.count, 1)
    }

    func testSlowTapsAndTapsOnDifferentElementsAreNotRepeatTaps() {
        let (r, store, clock) = recorder()
        for _ in 0..<5 { r.tap("trip.addButton"); clock.advance(0.6) }
        r.tap("plan.save"); clock.advance(0.1)
        r.tap("trip.addButton"); clock.advance(0.1)
        r.tap("trip.row.12")
        XCTAssertFalse(store.events.contains { $0.k == .repeatTap && $0.id == "plan.save" })
        XCTAssertEqual(store.events.filter { $0.k == .repeatTap }.count, 0)
    }

    // MARK: tasks and sessions

    func testATaskCarriesItsDuration() {
        let (r, store, clock) = recorder()
        r.task("plan.day", .start)
        clock.advance(42.5)
        r.task("plan.day", .success)
        r.task("add.trip", .start)
        clock.advance(3)
        r.task("add.trip", .cancel)
        XCTAssertEqual(store.events.map { $0.r }, ["start", "success", "start", "cancel"])
        XCTAssertEqual(store.events[1].ms, 42_500)
        XCTAssertEqual(store.events[3].ms, 3_000)
        XCTAssertNil(store.events[0].ms)
    }

    func testIdleTimeInTheBackgroundIsNotCounted() {
        let (r, store, clock) = recorder()
        r.appBecameActive()
        clock.advance(100)
        r.appWentToBackground()
        clock.advance(3 * 3600)
        r.appBecameActive()
        let rows = store.events.filter { $0.k == .session }
        XCTAssertEqual(rows.map { $0.r }, ["start", "background", "end", "start"])
        // The old session ends where it went to the background, not when the app came back.
        XCTAssertEqual(rows[2].t, rows[1].t)
        XCTAssertEqual(rows[1].t - rows[0].t, 100)
    }

    func testAShortAbsenceDoesNotEndTheSession() {
        let (r, store, clock) = recorder()
        r.appBecameActive()
        clock.advance(10)
        r.appWentToBackground()
        clock.advance(120)
        r.appBecameActive()
        XCTAssertEqual(store.events.map { $0.r }, ["start", "background", "start"])
    }

    func testEveryEventCarriesTheBuildAndTheVariants() {
        let (r, store, _) = recorder()
        r.setVariant(decision: "nav", variant: "bottom-bar")
        r.setVariant(decision: "density", variant: "compact")
        r.screen("trip.timeline")
        r.clearVariant(decision: "density")
        r.action("plan.save", result: .done)
        XCTAssertEqual(store.events.map(\.b), ["212", "212"])
        XCTAssertEqual(store.events[0].d, ["nav": "bottom-bar", "density": "compact"])
        XCTAssertEqual(store.events[1].d, ["nav": "bottom-bar"])
    }

    func testAVariantThatIsNotAPlainTokenIsIgnored() {
        let (r, store, _) = recorder()
        r.setVariant(decision: "Nav Bar", variant: "bottom")
        r.setVariant(decision: "nav", variant: "a long sentence a tester typed")
        r.screen("trip.timeline")
        XCTAssertNil(store.events.first?.d)
    }

    // MARK: the ring buffer

    func testTheRingBufferKeepsTheNewestEvents() {
        let store = UsageStore(url: nil, maxEvents: 10)
        let (r, _, clock) = recorder(store: store)
        for i in 0..<25 {
            r.task("plan.day", .start)
            clock.advance(Double(i + 1) * 0.001)
        }
        XCTAssertEqual(store.count, 10)
        XCTAssertEqual(store.events.map(\.t), store.events.map(\.t).sorted())
    }

    func testTheRingBufferDropsTheOldestFirst() {
        let store = UsageStore(url: nil, maxEvents: 3)
        for n in 0..<7 { store.append(UsageEvent(t: n, k: .screen, id: "trip.timeline", r: nil, ms: nil, b: "1", d: nil)) }
        XCTAssertEqual(store.events.map(\.t), [4, 5, 6])
    }

    func testThePendingBatchCountsAgainstTheCap() {
        let store = UsageStore(url: nil, maxEvents: 5)
        for n in 0..<5 { store.append(UsageEvent(t: n, k: .screen, id: "trip.timeline", r: nil, ms: nil, b: "1", d: nil)) }
        _ = store.nextBatch(maxEvents: 3, maxBytes: 100_000)
        for n in 5..<9 { store.append(UsageEvent(t: n, k: .screen, id: "trip.timeline", r: nil, ms: nil, b: "1", d: nil)) }
        XCTAssertEqual(store.count, 5)
        XCTAssertEqual(store.events.map(\.t), [7, 8])                 // the newest are kept
        XCTAssertEqual(store.pending?.events.map(\.t), [0, 1, 2])     // the batch in flight is dropped last
    }

    func testANewBatchIsOnDiskBeforeTheUploadSoARelaunchReusesItsId() {
        let url = Fixtures.tempDir().appendingPathComponent("usage.json")
        let first = UsageStore(url: url)
        for n in 0..<3 { first.append(UsageEvent(t: n, k: .screen, id: "trip.timeline", r: nil, ms: nil, b: "1", d: nil)) }
        let batch = first.nextBatch(maxEvents: 10, maxBytes: 100_000, makeID: { "batch-one" })
        XCTAssertEqual(batch?.id, "batch-one")
        // The app dies here: no confirm, no flush. A new launch reads the file.
        let relaunched = UsageStore(url: url)
        XCTAssertEqual(relaunched.pending?.id, "batch-one")
        let again = relaunched.nextBatch(maxEvents: 10, maxBytes: 100_000, makeID: { "another-id" })
        XCTAssertEqual(again?.id, "batch-one")
        XCTAssertEqual(again?.events.map(\.t), [0, 1, 2])
    }

    func testTheDefaultStoragePathIsScopedByBundleId() {
        let a = UsageStore.defaultURL(bundleID: "com.example.alpha")
        let b = UsageStore.defaultURL(bundleID: "com.example.beta")
        XCTAssertNotEqual(a, b)
        XCTAssertTrue(a.path.contains("com.example.alpha"))
        XCTAssertEqual(a.lastPathComponent, "usage.json")
        XCTAssertFalse(UsageStore.defaultURL(bundleID: "../evil/x").pathComponents.contains(".."))
        XCTAssertTrue(UsageStore.defaultURL(bundleID: nil).path.contains("unknown-app"))
    }

    func testTheFileStaysUnderTheByteCap() {
        let url = Fixtures.tempDir().appendingPathComponent("usage.json")
        let store = UsageStore(url: url, maxEvents: 5_000, maxBytes: 4_000)
        for n in 0..<400 { store.append(UsageEvent(t: n, k: .action, id: "plan.save", r: "done", ms: nil, b: "212", d: nil)) }
        store.flush()
        let size = (try? Data(contentsOf: url).count) ?? Int.max
        XCTAssertLessThanOrEqual(size, 4_000)
        XCTAssertEqual(store.events.last?.t, 399)
        let reopened = UsageStore(url: url, maxEvents: 5_000, maxBytes: 4_000)
        XCTAssertEqual(reopened.events.last?.t, 399)
    }

    func testTheDefaultCapIsFiveThousandEventsAndOneMegabyte() {
        XCTAssertEqual(UsageStore.defaultMaxEvents, 5_000)
        XCTAssertEqual(UsageStore.defaultMaxBytes, 1_000_000)
    }

    // MARK: who may send

    private func sender(
        store: UsageStore, owner: Bool, consent: UsageConsent.State, counter: Counter, active: Bool = true,
        results: [ChannelResult] = []
    ) -> UsageSender {
        let queue = ResultQueue(results)
        return UsageSender(
            store: store, isActive: { active }, isOwnerDevice: { owner }, consent: { consent },
            appInfo: { Fixtures.app }, declared: { UsageAllowList(screens: Set(self.screens), actions: Set(self.actions), tasks: Set(self.tasks)) },
            install: { "0b8f5c1e-7a2d-4e63-9d10-6c4a8e2f1b57" },
            transport: { { body, id in counter.add(id, body); return queue.next() } },
            now: { Date(timeIntervalSince1970: 1_793_400_100) })
    }

    private func filled(_ n: Int = 3) -> UsageStore {
        let store = UsageStore(url: nil)
        for i in 0..<n { store.append(UsageEvent(t: 1_793_400_000 + i, k: .action, id: "plan.save", r: "done", ms: nil, b: "212", d: ["nav": "bottom"])) }
        return store
    }

    func testATesterWhoHasNotAnsweredSendsNothing() async {
        let counter = Counter()
        let store = filled()
        let sent = await sender(store: store, owner: false, consent: .unset, counter: counter).sendPending()
        XCTAssertEqual(sent, 0)
        XCTAssertTrue(counter.ids.isEmpty)
        XCTAssertEqual(store.count, 3)
    }

    func testATesterWhoPressedNotNowSendsNothingEvenAfterPairing() async {
        let counter = Counter()
        let store = filled()
        let sent = await sender(store: store, owner: true, consent: .declined, counter: counter).sendPending()
        XCTAssertEqual(sent, 0)
        XCTAssertTrue(counter.ids.isEmpty)
    }

    func testATesterWhoPressedAllowSends() async {
        let counter = Counter()
        let store = filled()
        let sent = await sender(store: store, owner: false, consent: .allowed, counter: counter).sendPending()
        XCTAssertEqual(sent, 3)
        XCTAssertEqual(counter.ids.count, 1)
        XCTAssertEqual(store.count, 0)
    }

    func testTheOwnersDeviceSendsWithoutBeingAsked() async {
        let counter = Counter()
        let store = filled()
        let sent = await sender(store: store, owner: true, consent: .unset, counter: counter).sendPending()
        XCTAssertEqual(sent, 3)
        XCTAssertFalse(UsageConsent.noticeNeeded(isOwnerDevice: true, state: .unset))
    }

    func testAStoreBuildSendsNothingEvenForTheOwner() async {
        let counter = Counter()
        let store = filled()
        let sent = await sender(store: store, owner: true, consent: .allowed, counter: counter, active: false).sendPending()
        XCTAssertEqual(sent, 0)
        XCTAssertTrue(counter.ids.isEmpty)
    }

    func testTheNoticeIsOnlyForANonOwnerWhoHasNotAnswered() {
        XCTAssertTrue(UsageConsent.noticeNeeded(isOwnerDevice: false, state: .unset))
        XCTAssertFalse(UsageConsent.noticeNeeded(isOwnerDevice: false, state: .allowed))
        XCTAssertFalse(UsageConsent.noticeNeeded(isOwnerDevice: false, state: .declined))
        XCTAssertFalse(UsageConsent.maySend(isOwnerDevice: false, state: .unset))
        XCTAssertFalse(UsageConsent.maySend(isOwnerDevice: true, state: .declined))
        XCTAssertTrue(UsageConsent.mayRecord(state: .unset))
        XCTAssertFalse(UsageConsent.mayRecord(state: .declined))
    }

    func testNotNowStopsRecording() {
        let (r, store, _) = recorder(mayRecord: UsageConsent.mayRecord(state: .declined))
        r.screen("trip.timeline")
        r.appBecameActive()
        XCTAssertEqual(store.count, 0)
    }

    func testTheConsentAnswerIsKeptInTheDefaults() {
        let d = defaults()
        XCTAssertEqual(UsageConsent.state(defaults: d), .unset)
        UsageConsent.set(.declined, defaults: d)
        XCTAssertEqual(UsageConsent.state(defaults: d), .declined)
    }

    func testAFailedSendKeepsTheBatchAndItsIdForTheRetry() async {
        let counter = Counter()
        let store = filled()
        let s = sender(store: store, owner: true, consent: .unset, counter: counter, results: [.retryLater, .delivered])
        let first = await s.sendPending()
        XCTAssertEqual(first, 0)
        XCTAssertEqual(store.count, 3)
        let second = await s.sendPending()
        XCTAssertEqual(second, 3)
        XCTAssertEqual(counter.ids.count, 2)
        XCTAssertEqual(counter.ids[0], counter.ids[1])
        XCTAssertTrue(ChannelDelivery.isValidID(counter.ids[0]))
    }

    func testARefusedBatchIsDroppedNotRetriedForever() async {
        let counter = Counter()
        let store = filled()
        let sent = await sender(store: store, owner: true, consent: .unset, counter: counter, results: [.refused]).sendPending()
        XCTAssertEqual(sent, 0)
        XCTAssertEqual(store.count, 0)
    }

    func testABigBufferGoesOutInBatchesUnderTheServerLimit() async {
        let counter = Counter()
        let store = UsageStore(url: nil)
        for i in 0..<2_500 {
            store.append(UsageEvent(t: 1_793_400_000 + i, k: .action, id: "trip.addButton", r: "done", ms: nil, b: "212",
                                    d: ["nav": "bottom-bar", "density": "compact"]))
        }
        let sent = await sender(store: store, owner: true, consent: .unset, counter: counter).sendPending()
        XCTAssertEqual(sent, 2_500)
        XCTAssertGreaterThan(counter.bodies.count, 1)
        for body in counter.bodies { XCTAssertLessThan(body.count, 256 * 1024) }
        XCTAssertEqual(Set(counter.ids).count, counter.ids.count)
    }

    // MARK: the payload

    func testThePayloadHasNoFreeTextFields() throws {
        let clock = Clock()
        let (r, store, _) = recorder(clock: clock)
        r.setVariant(decision: "nav", variant: "bottom-bar")
        r.appBecameActive()
        r.screen("trip.timeline")
        clock.advance(0.5)
        r.screen("trip.detail")
        r.action("trip.row.3F2A9C10-5B7E-4D0A-9C1E-2A6B8D4F0E11", result: .cancelled)
        for _ in 0..<3 { r.tap("trip.addButton") }
        r.task("plan.day", .start)
        clock.advance(4)
        r.task("plan.day", .success)
        r.sheetDismissed("trip.detail", changed: false)
        r.appWentToBackground()
        let batch = try XCTUnwrap(store.nextBatch(maxEvents: 800, maxBytes: 180_000))
        let body = try UsageDelivery.encode(batch: batch, install: UsageInstall.id(defaults: defaults()), app: Fixtures.app,
                                            declared: UsageAllowList(screens: Set(screens), actions: Set(actions), tasks: Set(tasks)),
                                            now: Date(timeIntervalSince1970: 1_793_400_100))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertEqual(Set(json.keys), UsageDelivery.payloadKeys)
        XCTAssertEqual(json["kind"] as? String, "usage")
        XCTAssertEqual(json["v"] as? Int, 1)
        XCTAssertEqual(json["id"] as? String, batch.id)
        let app = try XCTUnwrap(json["app"] as? [String: Any])
        XCTAssertTrue(Set(app.keys).isSubset(of: UsageDelivery.appKeys))
        let declared = try XCTUnwrap(json["declared"] as? [String: [String]])
        XCTAssertEqual(Set(declared.keys), ["screens", "actions", "tasks"])
        XCTAssertEqual(declared["screens"], screens.sorted())
        let events = try XCTUnwrap(json["events"] as? [[String: Any]])
        XCTAssertEqual(events.count, batch.events.count)
        let kinds = Set(UsageEvent.Kind.allCases.map(\.rawValue))
        let results: Set<String> = ["start", "background", "end", "done", "cancelled", "error", "undone", "success", "cancel", "screen", "sheet"]
        let ids = Set(screens + actions + tasks)
        for event in events {
            XCTAssertTrue(Set(event.keys).isSubset(of: UsageEvent.allowedKeys), "\(event.keys)")
            XCTAssertTrue(kinds.contains(event["k"] as! String))
            if let id = event["id"] as? String { XCTAssertTrue(ids.contains(id), id) }
            if let r = event["r"] as? String { XCTAssertTrue(results.contains(r), r) }
            for (key, value) in event {
                switch key {
                case "t", "ms": XCTAssertTrue(value is Int)
                case "d":
                    let map = try XCTUnwrap(value as? [String: String])
                    for (decision, variant) in map { XCTAssertTrue(UsageID.isToken(decision) && UsageID.isToken(variant)) }
                default: XCTAssertTrue(value is String)
                }
            }
        }
        // No comment, no title, no name, no device name, no identifier of the person.
        let text = String(decoding: body, as: UTF8.self)
        for banned in ["comment", "title", "name", "email", "text", "label", "idfa", "vendor"] {
            XCTAssertFalse(text.lowercased().contains("\"" + banned + "\""), banned)
        }
    }

    func testTheInstallIdIsRandomStableAndNotADeviceId() {
        let d1 = defaults(), d2 = defaults()
        let a = UsageInstall.id(defaults: d1)
        XCTAssertEqual(UsageInstall.id(defaults: d1), a)
        XCTAssertNotEqual(UsageInstall.id(defaults: d2), a)
        XCTAssertNotNil(UUID(uuidString: a))
        XCTAssertEqual(a, a.lowercased())
    }

    func testTheUsageNoticeSaysWhatWhoWhyHowLongAndWhatNotNowMeans() {
        let text = ReviewStrings().usageNoticeMessage
        for part in ["What is recorded", "Who gets it", "Why:", "How long", "180 days", "Not now"] {
            XCTAssertTrue(text.contains(part), part)
        }
        XCTAssertEqual(ReviewStrings().usageAllow, "Allow")
        XCTAssertEqual(ReviewStrings().usageNotNow, "Not now")
    }

    func testTheUsageUploadGoesToTheUsagePathOfTheChannel() throws {
        let config = try XCTUnwrap(ChannelConfig(url: "https://review.example.com", key: "k"))
        let url = UsageDelivery.url(config, id: "3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11")
        XCTAssertEqual(url.absoluteString, "https://review.example.com/v1/captures/3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11/usage.json")
    }
}

private final class ResultQueue: @unchecked Sendable {
    private let lock = NSLock()
    private var items: [ChannelResult]
    init(_ items: [ChannelResult]) { self.items = items }
    func next() -> ChannelResult {
        lock.lock(); defer { lock.unlock() }
        return items.isEmpty ? .delivered : items.removeFirst()
    }
}

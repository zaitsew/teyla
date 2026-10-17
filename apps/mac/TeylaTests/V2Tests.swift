import CoreImage
import XCTest

final class FormatV2Tests: XCTestCase {
    func testCounts() {
        XCTAssertEqual(Format.counts(issues: 3, prsWaiting: 1), "3 issues · 1 PR waiting")
        XCTAssertEqual(Format.counts(issues: 1, prsWaiting: 0), "1 issue")
        XCTAssertEqual(Format.counts(issues: 0, prsWaiting: 2), "2 PRs waiting")
        XCTAssertEqual(Format.counts(issues: 0, prsWaiting: 0), "")
    }

    func testStatusAndKindLabels() {
        XCTAssertEqual(["done", "needs_you", "blocked", "failed", "review_ready"].map(Format.statusLabel),
                       ["Done", "Needs you", "Blocked", "Failed", "Ready for review"])
        XCTAssertEqual(Format.statusLabel("waiting_on_phone"), "Waiting on phone")
        XCTAssertEqual(Format.taskKind("merge"), "Merge")
        XCTAssertEqual(Format.taskKind("task"), "Task")
    }

    func testLinkLabel() {
        XCTAssertEqual(Format.linkLabel("https://github.com/example/atlas/pull/301"), "example/atlas#301")
        XCTAssertEqual(Format.linkLabel("https://github.com/example/atlas/issues/9"), "example/atlas#9")
        XCTAssertEqual(Format.linkLabel("https://example.com/a/b"), "example.com/a/b")
        XCTAssertEqual(Format.linkLabel("https://example.com/"), "example.com")
        XCTAssertEqual(Format.linkLabel("not a url"), "not a url")
    }

    func testRelayLine() {
        let now = ISODate.parse("2026-10-17T12:00:00Z")!
        XCTAssertEqual(Format.relayLine(nil, now: now), "Relay is off.")
        XCTAssertEqual(Format.relayLine(Relay(on: false, paired: true), now: now), "Relay is off.")
        XCTAssertEqual(Format.relayLine(Relay(on: true), now: now), "Relay is on. No iPhone is paired.")
        XCTAssertEqual(Format.relayLine(Relay(on: true, paired: true), now: now), "Paired · not synced yet")
        XCTAssertEqual(Format.relayLine(Relay(on: true, paired: true, synced: "2026-10-17T11:58:00Z"), now: now),
                       "Paired · synced 2 min ago")
        XCTAssertEqual(Format.relayLine(Relay(on: true, paired: true, synced: "2026-10-17T11:59:50Z"), now: now),
                       "Paired · synced just now")
    }

    func testResultLines() {
        XCTAssertEqual(Format.saidLine(via: "codex-queue"), "Queued: Codex reads it after the current turn")
        XCTAssertEqual(Format.saidLine(via: "opened"), "Copied to the clipboard and opened the session")
        XCTAssertEqual(Format.startedLine(via: "codex-exec", worktree: "~/.worktrees/atlas/x"), "Started in ~/.worktrees/atlas/x")
        XCTAssertEqual(Format.startedLine(via: "claude-bg", worktree: ""), "Started")
        XCTAssertTrue(Format.startedLine(via: "fixture", worktree: "w").contains("preview only"))
    }

    func testProductsWithAWaitingPRAreShown() {
        let products = [Product(name: "lens", state: "quiet", prsWaiting: 1), Product(name: "idle", state: "quiet")]
        let split = Format.splitProducts(products, running: [])
        XCTAssertEqual(split.shown.map(\.name), ["lens"])
        XCTAssertEqual(split.rest, 1)
    }
}

final class CommandArgumentTests: XCTestCase {
    func testSayPutsTextAfterDoubleDash() {
        XCTAssertEqual(TeylaCLI.sayArguments(ref: "r1", text: "--stop and use Sol"),
                       ["say", "r1", "--json", "--", "--stop and use Sol"])
    }

    func testDispatchPutsTextAfterDoubleDash() {
        let args = TeylaCLI.dispatchArguments(product: "atlas", harness: .codex, text: "-x: fix the --harness flag")
        XCTAssertEqual(args, ["dispatch", "atlas", "--harness", "codex", "--json", "--", "-x: fix the --harness flag"])
        XCTAssertEqual(TeylaCLI.dispatchArguments(product: "atlas", harness: .claude, text: "t")[3], "claude")
        XCTAssertEqual(args.firstIndex(of: "--"), args.count - 2)
    }

    func testRelayArguments() {
        XCTAssertEqual(TeylaCLI.relayArguments(on: true), ["relay", "on"])
        XCTAssertEqual(TeylaCLI.relayArguments(on: false), ["relay", "off"])
        XCTAssertEqual(TeylaCLI.relayPairArguments, ["relay", "pair", "--json"])
    }

    func testDefaultHarnessIsCodex() {
        XCTAssertEqual(Harness.allCases.first, .codex)
    }
}

final class FixtureWritesV2Tests: XCTestCase {
    private func cli() -> TeylaCLI {
        let here = URL(fileURLWithPath: #filePath)
        let path = here.deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("tests/fixtures/state.v2.json").path
        return TeylaCLI(env: ["TEYLA_STATE_FIXTURE": path], home: "/nonexistent")
    }

    func testSayDispatchAndRelayAreSimulated() async throws {
        let cli = cli()
        let snapshot = try await cli.state()
        XCTAssertEqual(snapshot.version, 2)
        let said = try await cli.say(ref: "00000000-0000-0000-0000-000000000008", text: "use the new API")
        XCTAssertEqual(said.via, "fixture")
        XCTAssertEqual(said.id, "00000000-0000-0000-0000-000000000008")
        let started = try await cli.dispatch(product: "atlas", harness: .codex, text: "write the tests")
        XCTAssertEqual(started.via, "fixture")
        XCTAssertEqual(started.worktree, "~/.worktrees/atlas/preview")
        XCTAssertFalse(started.link.isEmpty)
        try await cli.setRelay(on: true)
        let pairing = try await cli.relayPair()
        XCTAssertTrue(Pairing.isValid(pairing))
    }
}

final class PairingTests: XCTestCase {
    private let key = "teyla-pair:v1:" + String(repeating: "A", count: 43)

    func testValidation() {
        XCTAssertTrue(Pairing.isValid(key))
        XCTAssertFalse(Pairing.isValid("teyla-pair:v1:short"))
        XCTAssertFalse(Pairing.isValid(key + "="))
        XCTAssertFalse(Pairing.isValid("teyla-pair:v2:" + String(repeating: "A", count: 43)))
        XCTAssertFalse(Pairing.isValid(key + "\nextra"))
    }

    func testExtractsFromJSONUnderAnyKeyOrFromPlainText() {
        XCTAssertEqual(Pairing.extract(from: Data(#"{"ok": true, "pairing": "\#(key)"}"#.utf8)), key)
        XCTAssertEqual(Pairing.extract(from: Data(#"{"ok": true, "pair": {"string": "\#(key)"}}"#.utf8)), key)
        XCTAssertEqual(Pairing.extract(from: Data("Scan this:\n\(key)\n".utf8)), key)
        XCTAssertNil(Pairing.extract(from: Data(#"{"ok": true}"#.utf8)))
        XCTAssertNil(Pairing.extract(from: Data(#"{"pairing": "teyla-pair:v1:bad"}"#.utf8)))
    }

    func testQRCodeReadsBack() throws {
        let image = try XCTUnwrap(Pairing.qrImage(for: key))
        let cg = try XCTUnwrap(image.cgImage(forProposedRect: nil, context: nil, hints: nil))
        let detector = try XCTUnwrap(CIDetector(ofType: CIDetectorTypeQRCode, context: nil,
                                                options: [CIDetectorAccuracy: CIDetectorAccuracyHigh]))
        let found = detector.features(in: CIImage(cgImage: cg)).compactMap { ($0 as? CIQRCodeFeature)?.messageString }
        XCTAssertEqual(found, [key])
    }
}

final class VoiceTests: XCTestCase {
    func testLocales() {
        XCTAssertEqual(Voice.locales.map(\.id), ["en-US", "es-ES", "ru-RU"])
    }

    func testRememberedLocale() throws {
        let defaults = try XCTUnwrap(UserDefaults(suiteName: "teyla.tests.voice.\(UUID().uuidString)"))
        XCTAssertEqual(Voice.stored(in: defaults).id, "en-US")
        Voice.remember(Voice.locales[2], in: defaults)
        XCTAssertEqual(Voice.stored(in: defaults).id, "ru-RU")
        defaults.set("xx-XX", forKey: Voice.defaultsKey)
        XCTAssertEqual(Voice.stored(in: defaults).id, "en-US")
    }

    func testNoOnDeviceSupportExplainsTheFixAndNeverFallsBack() throws {
        let russian = Voice.locales[2]
        let why = try XCTUnwrap(Voice.problem(for: russian, hasRecognizer: true, supportsOnDevice: false, isAvailable: true))
        XCTAssertTrue(why.contains("System Settings → Keyboard → Dictation: add the language"))
        XCTAssertTrue(why.contains("never sends audio to a server"))
        XCTAssertNotNil(Voice.problem(for: russian, hasRecognizer: false, supportsOnDevice: false, isAvailable: false))
        XCTAssertNotNil(Voice.problem(for: russian, hasRecognizer: true, supportsOnDevice: true, isAvailable: false))
        XCTAssertNil(Voice.problem(for: russian, hasRecognizer: true, supportsOnDevice: true, isAvailable: true))
    }

    func testMergedTextKeepsWhatWasTyped() {
        XCTAssertEqual(Voice.merged(base: "", heard: " hello "), "hello")
        XCTAssertEqual(Voice.merged(base: "Fix the build.", heard: "then run the tests"), "Fix the build. then run the tests")
        XCTAssertEqual(Voice.merged(base: "typed", heard: ""), "typed")
    }

    func testWordsTypedWhileListeningAreKeptAndOnlyNewSpeechIsAppended() {
        var text = DictationText(base: "Fix")
        XCTAssertEqual(text.text(heard: "the build", field: "Fix"), "Fix the build")
        // nothing typed: the next result replaces the previous one
        XCTAssertEqual(text.text(heard: "the build now", field: "Fix the build"), "Fix the build now")
        // the owner types a correction in the field, then more speech arrives
        XCTAssertEqual(text.text(heard: "the build now and test", field: "Fix the build now, please"),
                       "Fix the build now, please and test")
        // and once more, with nothing typed in between
        XCTAssertEqual(text.text(heard: "the build now and test it", field: "Fix the build now, please and test"),
                       "Fix the build now, please and test it")
    }

    func testTapStartsAndAnotherTapStops() {
        var talk = PushToTalk()
        let t0 = Date(timeIntervalSince1970: 1000)
        XCTAssertEqual(talk.press(at: t0, listening: false), .start)
        XCTAssertEqual(talk.release(at: t0.addingTimeInterval(0.2)), .none)   // a tap keeps listening
        XCTAssertEqual(talk.press(at: t0.addingTimeInterval(5), listening: true), .stop)
        XCTAssertEqual(talk.release(at: t0.addingTimeInterval(5.1)), .none)
    }

    func testHoldStopsOnRelease() {
        var talk = PushToTalk()
        let t0 = Date(timeIntervalSince1970: 1000)
        XCTAssertEqual(talk.press(at: t0, listening: false), .start)
        XCTAssertEqual(talk.press(at: t0.addingTimeInterval(0.1), listening: true), .none)   // key repeat
        XCTAssertEqual(talk.release(at: t0.addingTimeInterval(1.5)), .stop)
    }
}

final class NewTaskTests: XCTestCase {
    private let products = [Product(name: "atlas"), Product(name: "(no repo)"), Product(name: "cellar"), Product(name: "")]

    func testOnlyRealProductsCanTakeTasks() {
        XCTAssertEqual(NewTask.products(products).map(\.name), ["atlas", "cellar"])
    }

    func testDefaultIsTheSelectedProductElseTheFirst() {
        XCTAssertEqual(NewTask.defaultProduct(selected: "cellar", among: products), "cellar")
        XCTAssertEqual(NewTask.defaultProduct(selected: "gone", among: products), "atlas")
        XCTAssertEqual(NewTask.defaultProduct(selected: nil, among: products), "atlas")
        XCTAssertNil(NewTask.defaultProduct(selected: nil, among: []))
    }

    func testCanSend() {
        XCTAssertTrue(NewTask.canSend(product: "atlas", text: "do it"))
        XCTAssertFalse(NewTask.canSend(product: "atlas", text: "  \n "))
        XCTAssertFalse(NewTask.canSend(product: nil, text: "do it"))
        XCTAssertFalse(NewTask.canSend(product: "", text: "do it"))
    }
}

final class AskTrackerTests: XCTestCase {
    func testFirstSnapshotNotifiesNothingAndEachNewAskOnce() {
        var tracker = AskTracker()
        let a = Ask(id: "a"), b = Ask(id: "b"), c = Ask(id: "c")
        XCTAssertTrue(tracker.fresh(in: [a], hidden: []).isEmpty)
        XCTAssertEqual(tracker.fresh(in: [a, b], hidden: []).map(\.id), ["b"])
        XCTAssertTrue(tracker.fresh(in: [a, b], hidden: []).isEmpty)          // the same ask is not announced twice
        XCTAssertTrue(tracker.fresh(in: [a], hidden: []).isEmpty)             // b went away
        XCTAssertTrue(tracker.fresh(in: [a, b], hidden: []).isEmpty)          // and came back: still once
        XCTAssertTrue(tracker.fresh(in: [a, b, c], hidden: ["c"]).isEmpty)    // an ask the owner already closed
        XCTAssertTrue(tracker.fresh(in: [a, b, c], hidden: []).isEmpty)
    }
}

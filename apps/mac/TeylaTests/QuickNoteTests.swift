import AppKit
import Carbon.HIToolbox
import XCTest

private func repoFile(_ path: String) -> URL {
    URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent(path)
}

final class NoteCommandTests: XCTestCase {
    func testSaveSendsTheTextOnStdinAndTheProductAsAFlag() {
        XCTAssertEqual(Notes.saveArguments(product: "cellar"), ["note", "-", "--product", "cellar", "--json"])
        // Nothing the owner types can reach the argument list: the builder takes no text.
    }

    func testSuggestReadsStdinAndNamesTheDirectory() {
        XCTAssertEqual(Notes.suggestArguments(cwd: "/Users/someone"),
                       ["note", "--suggest", "-", "--json", "--cwd", "/Users/someone"])
    }

    func testLinkDropAndListArguments() {
        XCTAssertEqual(Notes.linkArguments(id: "nabc234", product: "lens"), ["note", "link", "nabc234", "lens", "--json"])
        XCTAssertEqual(Notes.linkArguments(id: "nabc234", product: "inbox"), ["note", "link", "nabc234", "inbox", "--json"])
        XCTAssertEqual(Notes.dropArguments(id: "nabc234"), ["note", "drop", "nabc234", "--json"])
        XCTAssertEqual(Notes.listArguments, ["notes", "--json"])
    }

    func testAFakeCLIReceivesTheTextOnStdinNeverInArguments() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("teyla-note-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let script = dir.appendingPathComponent("teyla")
        let argsFile = dir.appendingPathComponent("args.txt")
        let stdinFile = dir.appendingPathComponent("stdin.txt")
        try """
        #!/bin/sh
        printf '%s\\n' "$@" > '\(argsFile.path)'
        cat > '\(stdinFile.path)'
        echo '{"id":"nabc234","text":"kept","product":"cellar","source":"owner","created":"2026-10-17T21:00:00Z","updated":"2026-10-17T21:00:00Z","linked_by":"owner","dropped":false}'
        """.write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let cli = TeylaCLI(env: ["TEYLA_BIN": script.path], home: dir.path)

        let text = "--product inbox -rf\nsecond line, with \"quotes\" and ünïcode"
        let note = try await cli.saveNote(text: text, product: "cellar")

        XCTAssertEqual(note.id, "nabc234")
        XCTAssertEqual(try String(contentsOf: stdinFile, encoding: .utf8), text)
        let args = try String(contentsOf: argsFile, encoding: .utf8).split(separator: "\n").map(String.init)
        XCTAssertEqual(args, ["note", "-", "--product", "cellar", "--json"])
    }

    func testAFailedSaveThrowsTheCLIsLineWithoutItsPrefix() async throws {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("teyla-note-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let script = dir.appendingPathComponent("teyla")
        try "#!/bin/sh\ncat > /dev/null\necho 'teyla: the notes store is locked by another process; nothing was saved, try again' >&2\nexit 1\n"
            .write(to: script, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: script.path)
        let cli = TeylaCLI(env: ["TEYLA_BIN": script.path], home: dir.path)
        do {
            _ = try await cli.saveNote(text: "an idea", product: "inbox")
            XCTFail("a failing CLI must throw")
        } catch {
            XCTAssertEqual(error.localizedDescription, "the notes store is locked by another process; nothing was saved, try again")
        }
    }
}

final class NoteDecodingTests: XCTestCase {
    func testDecodesTheSuggestion() throws {
        let json = #"{"product": "cellar", "linked_by": "text", "candidates": ["atlas", "cellar", "lens"]}"#
        let found = try Notes.decodeSuggestion(Data(json.utf8))
        XCTAssertEqual(found, NoteSuggestion(product: "cellar", linkedBy: "text", candidates: ["atlas", "cellar", "lens"]))
    }

    func testASuggestionWithMissingFieldsFallsBackToTheInbox() throws {
        let found = try Notes.decodeSuggestion(Data("{}".utf8))
        XCTAssertEqual(found, NoteSuggestion(product: "inbox", linkedBy: "", candidates: []))
        XCTAssertThrowsError(try Notes.decodeSuggestion(Data("[1]".utf8)))
    }

    func testDecodesTheNotesFixture() throws {
        let notes = try Notes.decodeNotes(Data(contentsOf: repoFile("tests/fixtures/notes.v1.json")))
        XCTAssertEqual(notes.count, 7)
        XCTAssertEqual(Notes.inboxCount(notes), 2)
        XCTAssertEqual(notes[0].linkedBy, "text")
        XCTAssertTrue(notes[2].text.contains("\n"))
        XCTAssertEqual(notes[0].createdDate, ISODate.parse("2026-10-17T21:22:00Z"))
    }

    func testTheKeysOfNotesJsonAreTheOnesTheCLIPrints() throws {
        // The shape of `teyla notes --json` (tests/test_notes.py pins the same eight keys).
        let json = """
        [{"id": "nabc234", "text": "an idea", "product": "cellar", "source": "owner", "created": "2026-10-17T21:00:00Z",
          "updated": "2026-10-17T21:05:00Z", "linked_by": "owner", "dropped": false}]
        """
        let note = try XCTUnwrap(Notes.decodeNotes(Data(json.utf8)).first)
        XCTAssertEqual(note, NoteItem(id: "nabc234", text: "an idea", product: "cellar", source: "owner",
                                      created: "2026-10-17T21:00:00Z", updated: "2026-10-17T21:05:00Z", linkedBy: "owner"))
    }

    func testAMalformedNoteIsSkippedAndMissingFieldsGetDefaults() throws {
        let json = #"[{"text": "no id"}, {"id": "nxyz789"}, 4]"#
        let notes = try Notes.decodeNotes(Data(json.utf8))
        XCTAssertEqual(notes.map(\.id), ["nxyz789"])
        XCTAssertEqual(notes[0].product, "inbox")
        XCTAssertFalse(notes[0].dropped)
        XCTAssertThrowsError(try Notes.decodeNotes(Data(#"{"id": "n1"}"#.utf8)))
    }

    func testStateStillDecodesWithAndWithoutTheNotesBlock() throws {
        // The snapshot is unchanged by this feature: the old fixtures decode as before.
        for name in ["state.json", "state.v2.json"] {
            let data = try Data(contentsOf: repoFile("tests/fixtures/\(name)"))
            XCTAssertNoThrow(try TeylaCLI.decodeSnapshot(data), name)
        }
    }
}

final class NoteListTests: XCTestCase {
    private func note(_ id: String, _ product: String, _ created: String, dropped: Bool = false) -> NoteItem {
        NoteItem(id: id, text: id, product: product, created: created, dropped: dropped)
    }

    func testNewestFiveOpenNotesAndTheInboxCount() {
        let notes = [
            note("n1", "inbox", "2026-10-01T10:00:00Z"),
            note("n2", "cellar", "2026-10-02T10:00:00Z"),
            note("n3", "inbox", "2026-10-03T10:00:00Z", dropped: true),
            note("n4", "lens", "2026-10-04T10:00:00Z"),
            note("n5", "atlas", "2026-10-05T10:00:00Z"),
            note("n6", "inbox", "2026-10-06T10:00:00Z"),
            note("n7", "atlas", "2026-10-07T10:00:00Z"),
        ]
        XCTAssertEqual(Notes.newestOpen(notes).map(\.id), ["n7", "n6", "n5", "n4", "n2"])
        XCTAssertEqual(Notes.inboxCount(notes), 2)
        XCTAssertEqual(Notes.openCount(notes), 6)
        XCTAssertEqual(Notes.newestOpen(notes, limit: 2).map(\.id), ["n7", "n6"])
    }

    func testTiesKeepTheCLIsOrder() {
        let notes = [note("na", "inbox", "2026-10-01T10:00:00Z"), note("nb", "inbox", "2026-10-01T10:00:00Z")]
        XCTAssertEqual(Notes.newestOpen(notes).map(\.id), ["na", "nb"])
    }

    func testLabels() {
        XCTAssertEqual(Notes.productLabel("inbox"), "Inbox")
        XCTAssertEqual(Notes.productLabel("wine-cellar"), "Wine Cellar")
        XCTAssertEqual(Notes.howLabel("text", product: "cellar"), "named in the text")
        XCTAssertEqual(Notes.howLabel("cwd", product: "cellar"), "from this directory")
        XCTAssertEqual(Notes.howLabel("owner", product: "cellar"), "chosen by you")
        XCTAssertEqual(Notes.howLabel("", product: "inbox"), "from Inbox")
    }

    func testCanSaveNeedsNonBlankText() {
        XCTAssertFalse(Notes.canSave(""))
        XCTAssertFalse(Notes.canSave(" \n\t "))
        XCTAssertTrue(Notes.canSave(" a "))
    }
}

final class NotePickerTests: XCTestCase {
    private let eleven = (1...11).map { "p\($0)" }

    func testTheFirstNineAreNumberedAndTheRestFold() {
        let split = Notes.split(eleven)
        XCTAssertEqual(split.numbered, Array(eleven.prefix(9)))
        XCTAssertEqual(split.more, ["p10", "p11"])
        XCTAssertEqual(Notes.split(["a"]).more, [])
    }

    func testCommandDigitsPickTheInboxAndTheNumberedCandidates() {
        XCTAssertEqual(Notes.product(forDigit: 0, candidates: eleven), "inbox")
        XCTAssertEqual(Notes.product(forDigit: 1, candidates: eleven), "p1")
        XCTAssertEqual(Notes.product(forDigit: 9, candidates: eleven), "p9")
        XCTAssertNil(Notes.product(forDigit: 10, candidates: eleven))
        XCTAssertNil(Notes.product(forDigit: 3, candidates: ["a", "b"]))
        XCTAssertNil(Notes.product(forDigit: -1, candidates: eleven))
        XCTAssertEqual(Notes.product(forDigit: 0, candidates: []), "inbox")
    }

    func testThePreviewSuggestionMatchesOneNamedProductOnly() {
        let products = ["atlas", "cellar", "lens"]
        XCTAssertEqual(Notes.simulate(text: "Cellar needs a dark icon", products: products),
                       NoteSuggestion(product: "cellar", linkedBy: "text", candidates: products))
        XCTAssertEqual(Notes.simulate(text: "atlas and lens together", products: products).product, "inbox")
        XCTAssertEqual(Notes.simulate(text: "cellars are not cellar", products: products).product, "cellar")
        XCTAssertEqual(Notes.simulate(text: "wine cellars", products: products).product, "inbox")
        XCTAssertEqual(Notes.simulate(text: "", products: products).linkedBy, "")
    }

    func testThePreviewCLIReadsTheSampleBesideTheStateFixture() async throws {
        let state = repoFile("tests/fixtures/state.v2.json").path
        let cli = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": state], home: "/Users/someone")
        let notes = try await cli.notes()
        XCTAssertEqual(notes.count, 7)
        let saved = try await cli.saveNote(text: "a preview note", product: "lens")
        XCTAssertEqual(saved.product, "lens")
        let found = try await cli.suggestNote(text: "lens first", products: ["lens", "atlas"])
        XCTAssertEqual(found.product, "lens")
        // Without a sample beside the state file there are simply no notes.
        let alone = TeylaCLI(env: ["TEYLA_STATE_FIXTURE": "/nonexistent/state.json"], home: "/Users/someone")
        let none = try await alone.notes()
        XCTAssertEqual(none, [])
    }
}

final class ShortcutKeymapTests: XCTestCase {
    func testDisplayOrderIsControlOptionShiftCommand() {
        XCTAssertEqual(Shortcut.quickNoteDefault.display, "⌥Space")
        XCTAssertEqual(Shortcut.pushToTalk.display, "⌥⌘Space")
        XCTAssertEqual(Shortcut(keyCode: UInt32(kVK_Space), modifiers: Shortcut.control | Shortcut.option).display, "⌃⌥Space")
        XCTAssertEqual(Shortcut(keyCode: 40, modifiers: Shortcut.command | Shortcut.shift).display, "⇧⌘K")
        XCTAssertEqual(Shortcut(keyCode: 126, modifiers: Shortcut.control).display, "⌃↑")
        XCTAssertEqual(Shortcut(keyCode: 122, modifiers: Shortcut.option).display, "⌥F1")
        XCTAssertEqual(Shortcut(keyCode: 200, modifiers: Shortcut.command).display, "⌘Key 200")
    }

    func testCarbonModifiersFromAppKitFlags() {
        XCTAssertEqual(Shortcut.carbonModifiers(from: [.option]), UInt32(optionKey))
        XCTAssertEqual(Shortcut.carbonModifiers(from: [.option, .command]), Shortcut.pushToTalk.modifiers)
        XCTAssertEqual(Shortcut.carbonModifiers(from: [.control, .shift, .command, .option]),
                       UInt32(controlKey | shiftKey | cmdKey | optionKey))
        // Caps Lock, Fn and the numeric pad are not part of a shortcut.
        XCTAssertEqual(Shortcut.carbonModifiers(from: [.option, .capsLock, .function, .numericPad]), UInt32(optionKey))
        XCTAssertEqual(Shortcut.carbonModifiers(from: []), 0)
    }

    func testAKeyNeedsCommandOptionOrControl() {
        guard case .refused(let reason) = ShortcutRules.check(keyCode: 40, modifiers: 0) else { return XCTFail() }
        XCTAssertTrue(reason.contains("⌘, ⌥ or ⌃"))
        guard case .refused = ShortcutRules.check(keyCode: 40, modifiers: Shortcut.shift) else { return XCTFail() }
        XCTAssertEqual(ShortcutRules.check(keyCode: 40, modifiers: Shortcut.control), .accepted(Shortcut(keyCode: 40, modifiers: Shortcut.control)))
        XCTAssertEqual(ShortcutRules.check(keyCode: 49, modifiers: Shortcut.control | Shortcut.option),
                       .accepted(Shortcut(keyCode: 49, modifiers: Shortcut.control | Shortcut.option)))
    }

    func testEscapeCancelsUnlessItIsPartOfAChord() {
        XCTAssertEqual(ShortcutRules.check(keyCode: UInt32(kVK_Escape), modifiers: 0), .cancelled)
        XCTAssertEqual(ShortcutRules.check(keyCode: UInt32(kVK_Escape), modifiers: Shortcut.shift), .cancelled)
        XCTAssertEqual(ShortcutRules.check(keyCode: UInt32(kVK_Escape), modifiers: Shortcut.command),
                       .accepted(Shortcut(keyCode: UInt32(kVK_Escape), modifiers: Shortcut.command)))
    }

    func testPushToTalkIsRefusedWithTheReason() {
        let result = ShortcutRules.check(keyCode: UInt32(kVK_Space), modifiers: Shortcut.option | Shortcut.command)
        XCTAssertEqual(result, .refused("⌥⌘Space is push-to-talk. Pick another combination."))
        // The same key with another modifier set is a different shortcut.
        XCTAssertEqual(ShortcutRules.check(keyCode: UInt32(kVK_Space), modifiers: Shortcut.option | Shortcut.command | Shortcut.shift),
                       .accepted(Shortcut(keyCode: UInt32(kVK_Space), modifiers: Shortcut.option | Shortcut.command | Shortcut.shift)))
    }

    func testTheDefaultIsNotPushToTalk() {
        XCTAssertNotEqual(Shortcut.quickNoteDefault, Shortcut.pushToTalk)
        XCTAssertEqual(ShortcutRules.check(keyCode: Shortcut.quickNoteDefault.keyCode, modifiers: Shortcut.quickNoteDefault.modifiers),
                       .accepted(.quickNoteDefault))
    }
}

final class ShortcutStoreTests: XCTestCase {
    private var suite: String!
    private var defaults: UserDefaults!
    private var store: ShortcutStore { ShortcutStore(defaults: defaults) }

    override func setUp() {
        suite = "teyla.tests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite)
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
    }

    func testNothingStoredMeansTheDefault() {
        XCTAssertEqual(store.load(), .quickNoteDefault)
    }

    func testARecordedShortcutRoundTrips() {
        let recorded = Shortcut(keyCode: UInt32(kVK_Space), modifiers: Shortcut.control | Shortcut.option)
        store.save(recorded)
        XCTAssertEqual(store.load(), recorded)
        XCTAssertEqual(defaults.string(forKey: ShortcutStore.key), "49:6144")
        let other = Shortcut(keyCode: 45, modifiers: Shortcut.command | Shortcut.shift)
        store.save(other)
        XCTAssertEqual(store.load(), other)
    }

    func testClearingTurnsItOffAndStaysOffUntilRecordedAgain() {
        store.save(nil)
        XCTAssertNil(store.load())
        XCTAssertEqual(defaults.string(forKey: ShortcutStore.key), "off")
        store.save(.quickNoteDefault)
        XCTAssertEqual(store.load(), .quickNoteDefault)
    }

    func testAnUnreadableValueFallsBackToTheDefault() {
        for bad in ["", "garbage", "49", "49:", "a:b", "49:2048:1", "-1:2048"] {
            defaults.set(bad, forKey: ShortcutStore.key)
            XCTAssertEqual(store.load(), .quickNoteDefault, bad)
        }
    }
}

final class ShortcutLabelTests: XCTestCase {
    func testTheSettingsLineSaysWhyARegistrationFailed() {
        XCTAssertEqual(QuickNoteShortcut.describe(.quickNoteDefault, status: noErr), "⌥Space opens a quick note from any app.")
        XCTAssertEqual(QuickNoteShortcut.describe(.quickNoteDefault, status: OSStatus(eventHotKeyExistsErr)),
                       "⌥Space is taken by another app, so the shortcut is off. Record another one.")
        XCTAssertTrue(QuickNoteShortcut.describe(.quickNoteDefault, status: -9999).contains("error -9999"))
        XCTAssertEqual(QuickNoteShortcut.describe(nil, status: nil), "No shortcut. The menu-bar item still opens the quick note.")
    }

    func testTheMenuTitleFollowsTheShortcutThatIsActive() {
        XCTAssertEqual(QuickNoteShortcut.menuTitle(.quickNoteDefault), "Quick note ⌥Space")
        XCTAssertEqual(QuickNoteShortcut.menuTitle(Shortcut(keyCode: 45, modifiers: Shortcut.control)), "Quick note ⌃N")
        XCTAssertEqual(QuickNoteShortcut.menuTitle(nil), "Quick note")
    }
}

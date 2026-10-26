import Foundation

private final class DataBox: @unchecked Sendable {
    private let lock = NSLock()
    private var stored = Data()
    var data: Data {
        get { lock.lock(); defer { lock.unlock() }; return stored }
        set { lock.lock(); stored = newValue; lock.unlock() }
    }
}

/// Runs the Teyla CLI. With `TEYLA_STATE_FIXTURE` set, state is read from that JSON file and
/// every write (answer, say, dispatch, relay, snooze, done) is simulated, so a preview never touches a real session.
actor TeylaCLI: TeylaBackend {
    private let env: [String: String]
    private let home: String
    private let fixtureURL: URL?
    private let notesFixtureURL: URL?
    private let startFixtureURL: URL?
    private let productFixtureURL: URL?
    /// The file the owner picked with "Choose…", and what a login shell finds. Injected so a test never runs the real ones.
    private let chosen: @Sendable () -> String?
    private let shellPath: @Sendable () -> String?

    init(env: [String: String] = ProcessInfo.processInfo.environment, home: String = NSHomeDirectory(),
         chosen: @escaping @Sendable () -> String? = { TeylaBinary.chosenPath() },
         shellPath: @escaping @Sendable () -> String? = { TeylaBinary.loginShellPath() }) {
        self.env = env
        self.home = home
        self.chosen = chosen
        self.shellPath = shellPath
        if let path = env["TEYLA_STATE_FIXTURE"], !path.isEmpty {
            fixtureURL = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
        } else {
            fixtureURL = nil
        }
        if let path = env["TEYLA_NOTES_FIXTURE"], !path.isEmpty {
            notesFixtureURL = URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
        } else {
            // The notes sample sits beside the state sample, when there is one.
            notesFixtureURL = fixtureURL?.deletingLastPathComponent().appendingPathComponent("notes.v1.json")
        }
        // The diagnosis and the product page have samples beside the state sample too.
        startFixtureURL = Self.fixtureURL(env["TEYLA_START_FIXTURE"], beside: fixtureURL, named: "start.v1.json")
        productFixtureURL = Self.fixtureURL(env["TEYLA_PRODUCT_FIXTURE"], beside: fixtureURL, named: "product.v1.json")
    }

    private static func fixtureURL(_ path: String?, beside state: URL?, named name: String) -> URL? {
        if let path, !path.isEmpty { return URL(fileURLWithPath: (path as NSString).expandingTildeInPath) }
        return state?.deletingLastPathComponent().appendingPathComponent(name)
    }

    /// Where `teyla` is, or nil. A fixture preview answers "found" without looking, unless `TEYLA_PREVIEW_NO_BINARY` is set.
    func binaryPath() -> String? {
        if fixtureURL != nil && env["TEYLA_PREVIEW_NO_BINARY"] == nil { return "fixture" }
        return TeylaBinary.locate(env: env, home: home, chosen: chosen(), shellPath: shellPath)
    }

    /// "Check again": the login shell is asked afresh.
    nonisolated func forgetBinary() { TeylaBinary.forgetShellAnswer() }

    nonisolated var usesFixture: Bool { fixtureURL != nil }

    func state() async throws -> Snapshot {
        if fixtureURL != nil && env["TEYLA_PREVIEW_NO_BINARY"] != nil { throw TeylaError.binaryNotFound }
        if let url = fixtureURL {
            guard let data = try? Data(contentsOf: url) else {
                throw TeylaError.fixtureUnreadable(url.path)
            }
            return try Self.decodeSnapshot(data)
        }
        let out = try await run(["state", "--json"], timeout: 60)
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: out.stderrText) }
        return try Self.decodeSnapshot(out.stdout)
    }

    func answer(id: String, text: String) async throws -> AnswerResult {
        if fixtureURL != nil {
            try? await Task.sleep(for: .milliseconds(700))
            return AnswerResult(ok: true, via: "fixture", detail: "Simulated: the fixture is read-only", id: id)
        }
        return try await deliver(Self.answerArguments(id: id, text: text), timeout: 180)
    }

    /// `teyla say`: a correction for a running session.
    func say(ref: String, text: String) async throws -> AnswerResult {
        if fixtureURL != nil {
            try? await Task.sleep(for: .milliseconds(700))
            return AnswerResult(ok: true, via: "fixture", detail: "Simulated: the fixture is read-only", id: ref)
        }
        return try await deliver(Self.sayArguments(ref: ref, text: text), timeout: 60)
    }

    /// `teyla dispatch`: starts a new session in a fresh worktree.
    func dispatch(product: String, harness: Harness, text: String) async throws -> AnswerResult {
        if fixtureURL != nil {
            try? await Task.sleep(for: .milliseconds(900))
            return AnswerResult(ok: true, via: "fixture", detail: "Simulated: the fixture is read-only", id: "preview",
                                worktree: "~/.worktrees/\(product)/preview", link: "https://example.com/teyla-preview")
        }
        return try await deliver(Self.dispatchArguments(product: product, harness: harness, text: text), timeout: 180)
    }

    // MARK: First run (docs/START.md)

    /// `teyla start --json`: the read-only diagnosis. It reads 30 days of sessions and can take up to a minute.
    func start() async throws -> StartReport {
        if fixtureURL != nil {
            let seconds = Double(env["TEYLA_PREVIEW_START_DELAY"] ?? "") ?? 1.5
            try? await Task.sleep(for: .milliseconds(Int(max(0, seconds) * 1000)))
            guard let url = startFixtureURL, let data = try? Data(contentsOf: url) else {
                throw TeylaError.fixtureUnreadable(startFixtureURL?.path ?? "start.v1.json")
            }
            return try StartDecoding.decode(data)
        }
        let out = try await run(FirstRun.startArguments, timeout: 180)
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: Self.oneLine(out.stderrText)) }
        return try StartDecoding.decode(out.stdout)
    }

    /// `teyla apply <id> --yes`: makes one change and prints what it changed. Returns those lines.
    func apply(offerID: String) async throws -> String {
        guard FirstRun.isOfferID(offerID) else { throw TeylaError.failed(code: 2, message: "\(offerID) is not an offer id.") }
        if fixtureURL != nil {
            try? await Task.sleep(for: .milliseconds(700))
            return "Simulated: the fixture is read-only"
        }
        let out = try await run(FirstRun.applyArguments(offerID: offerID), timeout: 120)
        guard out.status == 0 else {
            let why = out.stderrText.isEmpty ? String(decoding: out.stdout, as: UTF8.self) : out.stderrText
            throw TeylaError.failed(code: out.status, message: Self.oneLine(why))
        }
        return StartDecoding.appliedLines(String(decoding: out.stdout, as: UTF8.self))
    }

    // MARK: Product page (docs/PRODUCTS.md)

    /// `teyla product show <id> --json`. `quick` leaves out the sessions and the spend.
    func productPage(id: String, quick: Bool) async throws -> ProductPageData {
        guard ProductCommands.isProductID(id) else { throw TeylaError.failed(code: 2, message: "\(id) is not a product id.") }
        if fixtureURL != nil {
            guard let url = productFixtureURL, let data = try? Data(contentsOf: url) else {
                throw TeylaError.fixtureUnreadable(productFixtureURL?.path ?? "product.v1.json")
            }
            var page = try ProductPageData.decode(data)
            if quick { page.sessions = nil; page.spend = nil }
            return page
        }
        let out = try await run(ProductCommands.showArguments(id: id, quick: quick), timeout: quick ? 30 : 180)
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: Self.oneLine(out.stderrText)) }
        return try ProductPageData.decode(out.stdout)
    }

    /// `teyla product set <id> stage=<stage>`.
    func setStage(id: String, stage: ProductStage) async throws {
        guard ProductCommands.isProductID(id) else { throw TeylaError.failed(code: 2, message: "\(id) is not a product id.") }
        try await simpleCommand(ProductCommands.stageArguments(id: id, stage: stage))
    }

    /// `teyla product set <id> focus=true|false`.
    func setFocus(id: String, focus: Bool) async throws {
        guard ProductCommands.isProductID(id) else { throw TeylaError.failed(code: 2, message: "\(id) is not a product id.") }
        try await simpleCommand(ProductCommands.focusArguments(id: id, focus: focus))
    }

    // MARK: Notes (docs/NOTES.md)

    /// `teyla notes --json`: the open notes, newest first. With a fixture, the sample beside it (none is an empty list).
    func notes() async throws -> [NoteItem] {
        if fixtureURL != nil {
            guard let url = notesFixtureURL, let data = try? Data(contentsOf: url) else { return [] }
            return try Notes.decodeNotes(data)
        }
        let out = try await run(Notes.listArguments, timeout: 30)
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: Self.oneLine(out.stderrText)) }
        return try Notes.decodeNotes(out.stdout)
    }

    /// `teyla note --suggest`: the product the text would get and the picker's list. Writes nothing.
    /// With a fixture, `products` stand in for the registry.
    func suggestNote(text: String, products: [String]) async throws -> NoteSuggestion {
        if fixtureURL != nil { return Notes.simulate(text: text, products: products) }
        let out = try await run(Notes.suggestArguments(cwd: home), timeout: 15, stdin: Data(text.utf8))
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: Self.oneLine(out.stderrText)) }
        return try Notes.decodeSuggestion(out.stdout)
    }

    /// `teyla note - --product <id> --json` with the text on stdin. Returns the saved note.
    func saveNote(text: String, product: String) async throws -> NoteItem {
        if fixtureURL != nil {
            try? await Task.sleep(for: .milliseconds(300))
            return NoteItem(id: "nfixture", text: text, product: product,
                            created: ISODate.format(Date()), updated: ISODate.format(Date()), linkedBy: "owner")
        }
        let out = try await run(Notes.saveArguments(product: product), timeout: 30, stdin: Data(text.utf8))
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: Self.oneLine(out.stderrText)) }
        return try Notes.decodeNote(out.stdout)
    }

    /// `teyla note link <id> <product>`.
    func linkNote(id: String, product: String) async throws {
        try await simpleCommand(Notes.linkArguments(id: id, product: product))
    }

    /// `teyla note drop <id>`.
    func dropNote(id: String) async throws {
        try await simpleCommand(Notes.dropArguments(id: id))
    }

    /// The CLI's refusal is one line that starts with "teyla: "; the window shows the rest.
    static func oneLine(_ stderr: String) -> String {
        let text = stderr.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.hasPrefix("teyla: ") ? String(text.dropFirst("teyla: ".count)) : text
    }

    /// `teyla relay on|off`. Output is not used: the next `state` carries the new `relay` block.
    func setRelay(on: Bool) async throws {
        try await simpleCommand(Self.relayArguments(on: on))
    }

    /// `teyla relay pair --json`: creates the shared key and returns the pairing string.
    func relayPair() async throws -> String {
        if fixtureURL != nil {
            try? await Task.sleep(for: .milliseconds(500))
            // A well-formed string with an all-zero key: a preview never creates a real key.
            return Pairing.prefix + String(repeating: "A", count: 43)
        }
        let out = try await run(Self.relayPairArguments, timeout: 60)
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: out.stderrText) }
        guard let pairing = Pairing.extract(from: out.stdout) else { throw TeylaError.badOutput("no pairing string") }
        return pairing
    }

    /// Runs a delivering command (`answer`, `say`, `dispatch`) and reads its `{ok, via, detail, id}` verdict.
    private func deliver(_ args: [String], timeout: TimeInterval) async throws -> AnswerResult {
        let out = try await run(args, timeout: timeout)
        // These commands may print a JSON verdict even when they fail; prefer that over stderr.
        if !out.stdout.isEmpty, let result = try? JSONDecoder().decode(AnswerResult.self, from: out.stdout) {
            if result.ok && out.status == 0 { return result }
            let why = result.detail.isEmpty ? out.stderrText : result.detail
            throw TeylaError.failed(code: out.status, message: why)
        }
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: out.stderrText) }
        throw TeylaError.badOutput("not JSON")
    }

    /// `--` ends option parsing, so an answer that starts with "-" is not read as a flag.
    static func answerArguments(id: String, text: String) -> [String] {
        ["answer", id, "--json", "--", text]
    }

    static func sayArguments(ref: String, text: String) -> [String] {
        ["say", ref, "--json", "--", text]
    }

    static func dispatchArguments(product: String, harness: Harness, text: String) -> [String] {
        ["dispatch", product, "--harness", harness.rawValue, "--json", "--", text]
    }

    static func relayArguments(on: Bool) -> [String] {
        ["relay", on ? "on" : "off"]
    }

    static let relayPairArguments = ["relay", "pair", "--json"]

    func snooze(id: String, days: Int) async throws {
        try await simpleCommand(["asks", "snooze", id, String(days)])
    }

    func markDone(id: String) async throws {
        try await simpleCommand(["asks", "done", id])
    }

    private func simpleCommand(_ args: [String]) async throws {
        if fixtureURL != nil {
            try? await Task.sleep(for: .milliseconds(400))
            return
        }
        let out = try await run(args, timeout: 60)
        guard out.status == 0 else { throw TeylaError.failed(code: out.status, message: Self.oneLine(out.stderrText)) }
    }

    static func decodeSnapshot(_ data: Data) throws -> Snapshot {
        do {
            return try JSONDecoder().decode(Snapshot.self, from: data)
        } catch {
            throw TeylaError.badOutput("not a state snapshot")
        }
    }

    // MARK: Process

    struct Output: Sendable {
        var status: Int32
        var stdout: Data
        var stderr: Data
        var stderrText: String { String(decoding: stderr, as: UTF8.self) }
    }

    private func childEnvironment() -> [String: String] {
        var e = env
        // A Finder-launched app has a bare PATH, but `teyla answer` needs `claude` and `codex`.
        let extra = ["\(home)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
        let existing = (e["PATH"] ?? "").split(separator: ":").map(String.init)
        e["PATH"] = (extra + existing.filter { !extra.contains($0) }).joined(separator: ":")
        return e
    }

    private func run(_ args: [String], timeout: TimeInterval, stdin: Data? = nil) async throws -> Output {
        guard let bin = TeylaBinary.locate(env: env, home: home, chosen: chosen(), shellPath: shellPath) else {
            throw TeylaError.binaryNotFound
        }
        let environment = childEnvironment()
        return try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Output, Error>) in
            DispatchQueue.global(qos: .userInitiated).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: bin)
                process.arguments = args
                process.environment = environment
                let inPipe = stdin == nil ? nil : Pipe()
                process.standardInput = inPipe ?? FileHandle.nullDevice
                let outPipe = Pipe()
                let errPipe = Pipe()
                process.standardOutput = outPipe
                process.standardError = errPipe
                do { try process.run() } catch {
                    cont.resume(throwing: error)
                    return
                }
                if let inPipe, let stdin {
                    // Written off this thread so a long text cannot fill the pipe and stall the read below.
                    // A child that exits early closes the pipe; the write then fails quietly instead of raising SIGPIPE.
                    signal(SIGPIPE, SIG_IGN)
                    DispatchQueue.global().async {
                        try? inPipe.fileHandleForWriting.write(contentsOf: stdin)
                        try? inPipe.fileHandleForWriting.close()
                    }
                }
                let timedOut = DataBox()
                let killer = DispatchWorkItem {
                    timedOut.data = Data([1])
                    process.terminate()
                }
                DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: killer)
                // Drain stderr on its own thread so a chatty child cannot fill the pipe and stall.
                let errBox = DataBox()
                let group = DispatchGroup()
                group.enter()
                DispatchQueue.global().async {
                    errBox.data = errPipe.fileHandleForReading.readDataToEndOfFile()
                    group.leave()
                }
                let outData = outPipe.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                group.wait()
                killer.cancel()
                if !timedOut.data.isEmpty {
                    cont.resume(throwing: TeylaError.timedOut)
                } else {
                    cont.resume(returning: Output(status: process.terminationStatus, stdout: outData, stderr: errBox.data))
                }
            }
        }
    }
}

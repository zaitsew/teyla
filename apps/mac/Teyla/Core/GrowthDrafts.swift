import Foundation

// The drafts waiting for the owner: `~/.teyla/growth/items/*.json`, read as they are (docs/GROWTH.md). `teyla console`
// carries counts only, so the review queue has no report to read: the app reads the item files itself, never changes
// one, and acts only through `teyla growth approve | reject | edit`. Nothing here posts, sends or publishes: approving
// marks a draft, and the owner posts it by hand from its packet.
// The iPhone app can compile this file by path, so keep it free of UI.

/// A source a draft stands on: a PR, a release, a session. The report names it by URL or by a reference.
struct GrowthDraftSource: Decodable, Equatable, Sendable, Identifiable {
    var kind: String
    var link: String

    var id: String { "\(kind)|\(link)" }

    enum CodingKeys: String, CodingKey { case kind, url, ref }

    init(kind: String, link: String) {
        self.kind = kind
        self.link = link
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = c.lenient(.kind, "")
        let url: String? = c.optional(.url)
        let ref: String? = c.optional(.ref)
        link = [url, ref].compactMap { $0 }.first { !$0.isEmpty } ?? ""
    }
}

/// One draft on its way to a channel.
struct GrowthDraft: Decodable, Equatable, Sendable, Identifiable {
    var id: String
    var status: String
    var kind: String
    var platform: String
    var language: String
    var format: String
    var product: String
    var idea: String
    var hook: String
    var body: String
    var firstComment: String
    var facts: [String]
    var sources: [GrowthDraftSource]
    /// The editor's score out of 5; nil when no editor pass ran.
    var editorScore: Double?
    var critique: String
    /// nil when the check never ran.
    var voiceOK: Bool?
    var leakOK: Bool?
    /// What each failed check said, one line each.
    var checkNotes: [String]
    var holdReason: String?
    var updated: String

    enum CodingKeys: String, CodingKey {
        case id, status, kind, platform, language, format, product, idea, hook, body, facts, sources, editor, updated, created
        case firstComment = "first_comment", voiceCheck = "voice_check", leakCheck = "leak_check", holdReason = "hold_reason"
    }

    private struct Editor: Decodable {
        var score: Double?
        var critique: String

        enum CodingKeys: String, CodingKey { case score, critique }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            score = c.optional(.score)
            critique = c.lenient(.critique, "")
        }
    }

    /// `voice_check` is `{ok, findings: [{level, rule, message}]}`, `leak_check` is `{ok, kinds: []}`.
    private struct Check: Decodable {
        var ok: Bool?
        var notes: [String]

        enum CodingKeys: String, CodingKey { case ok, findings, kinds }

        private struct Finding: Decodable {
            var level: String
            var rule: String
            var message: String

            enum CodingKeys: String, CodingKey { case level, rule, message }

            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: CodingKeys.self)
                level = c.lenient(.level, "")
                rule = c.lenient(.rule, "")
                message = c.lenient(.message, "")
            }
        }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            ok = c.optional(.ok)
            let findings: [LossyBox<Finding>] = c.lenient(.findings, [])
            let kinds: [String] = c.lenient(.kinds, [])
            notes = findings.compactMap(\.value).filter { $0.level == "fail" }
                .map { $0.message.isEmpty ? $0.rule : "\($0.rule): \($0.message)" }
                + (kinds.isEmpty ? [] : ["blocked: \(kinds.joined(separator: ", "))"])
        }
    }

    init(id: String, status: String = "review", kind: String = "post", platform: String = "x", language: String = "en",
         format: String = "", product: String = "", idea: String = "", hook: String = "", body: String = "",
         firstComment: String = "", facts: [String] = [], sources: [GrowthDraftSource] = [], editorScore: Double? = nil,
         critique: String = "", voiceOK: Bool? = true, leakOK: Bool? = true, checkNotes: [String] = [],
         holdReason: String? = nil, updated: String = "") {
        self.id = id
        self.status = status
        self.kind = kind
        self.platform = platform
        self.language = language
        self.format = format
        self.product = product
        self.idea = idea
        self.hook = hook
        self.body = body
        self.firstComment = firstComment
        self.facts = facts
        self.sources = sources
        self.editorScore = editorScore
        self.critique = critique
        self.voiceOK = voiceOK
        self.leakOK = leakOK
        self.checkNotes = checkNotes
        self.holdReason = holdReason
        self.updated = updated
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        guard GrowthDrafts.isItemID(id) else {
            throw DecodingError.dataCorruptedError(forKey: .id, in: c, debugDescription: "not an item id")
        }
        status = try c.decode(String.self, forKey: .status)
        kind = c.lenient(.kind, "")
        platform = c.lenient(.platform, "")
        language = c.lenient(.language, "")
        format = c.lenient(.format, "")
        product = c.lenient(.product, "")
        idea = c.lenient(.idea, "")
        hook = c.lenient(.hook, "")
        body = c.lenient(.body, "")
        firstComment = c.lenient(.firstComment, "")
        facts = c.lenient(.facts, [])
        let sources: [LossyBox<GrowthDraftSource>] = c.lenient(.sources, [])
        self.sources = sources.compactMap(\.value).filter { !$0.link.isEmpty }
        let editor: Editor? = c.optional(.editor)
        editorScore = editor?.score
        critique = editor?.critique ?? ""
        let voice: Check? = c.optional(.voiceCheck)
        let leak: Check? = c.optional(.leakCheck)
        voiceOK = voice?.ok
        leakOK = leak?.ok
        checkNotes = (voice?.notes ?? []) + (leak?.notes ?? [])
        let hold: String? = c.optional(.holdReason)
        holdReason = hold
        let touched: String? = c.optional(.updated)
        let made: String? = c.optional(.created)
        updated = touched ?? made ?? ""
    }

    /// The CLI approves only a draft whose voice check and leak check both passed.
    var canApprove: Bool { voiceOK == true && leakOK == true }
}

enum GrowthDrafts {
    /// The ids the CLI accepts: `g` and four digits, a dash, four to eight lowercase letters or digits.
    static func isItemID(_ text: String) -> Bool {
        text.range(of: #"^g[0-9]{4}-[a-z0-9]{4,8}$"#, options: .regularExpression) != nil
    }

    /// What waits for the owner: a checked draft in review, not an episode, not a master idea, not held by the editor.
    /// The best editor score first; a draft with no score after the scored ones; then the newest.
    static func waiting(_ items: [GrowthDraft]) -> [GrowthDraft] {
        items
            .filter { ["review", "checked"].contains($0.status) && $0.kind != "episode" && $0.platform != "master" && ($0.holdReason ?? "").isEmpty }
            .sorted { a, b in
                switch (a.editorScore, b.editorScore) {
                case let (x?, y?) where x != y: return x > y
                case (.some, nil): return true
                case (nil, .some): return false
                default: return a.updated != b.updated ? a.updated > b.updated : a.id < b.id
                }
            }
    }

    struct Read: Equatable, Sendable {
        var drafts: [GrowthDraft]
        /// Item files that could not be read as a draft (not counted as waiting).
        var skipped: Int
    }

    /// Reads every `*.json` in the folder. A missing folder is no drafts yet, not an error; a folder that cannot be listed is.
    static func read(directory: URL) throws -> Read {
        let manager = FileManager.default
        guard manager.fileExists(atPath: directory.path) else { return Read(drafts: [], skipped: 0) }
        let files = try manager.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)
            .filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        var drafts: [GrowthDraft] = []
        var skipped = 0
        for file in files {
            guard let data = try? Data(contentsOf: file) else {
                skipped += 1
                continue
            }
            if let draft = try? JSONDecoder().decode(GrowthDraft.self, from: data) {
                drafts.append(draft)
            } else if (try? JSONSerialization.jsonObject(with: data)) != nil {
                // An item the app cannot read as a draft: an old shape, or an id the CLI would refuse.
                skipped += 1
            }
        }
        return Read(drafts: drafts, skipped: skipped)
    }

    /// `~/.teyla/growth/items`, or under `TEYLA_HOME` when that is set.
    static func directory(home: String, env: [String: String]) -> URL {
        let base = env["TEYLA_HOME"].map { ($0 as NSString).expandingTildeInPath }
            ?? (home as NSString).appendingPathComponent(".teyla")
        return URL(fileURLWithPath: (base as NSString).appendingPathComponent("growth")).appendingPathComponent("items")
    }
}

/// The three things the app does to a draft, and the command each one runs. Only these are allowed; `ToolCommands`
/// refuses any other `growth` command. Values go in as `--flag=value` so a text that starts with a dash is never read as a flag.
enum GrowthActions {
    static let reasonLimit = 500
    static let hookLimit = 500
    static let bodyLimit = 20_000

    static func approve(_ id: String) -> [String] { ["growth", "approve", id] }

    static func reject(_ id: String, reason: String) -> [String] {
        ["growth", "reject", id, "--reason=\(reason.trimmingCharacters(in: .whitespacesAndNewlines))"]
    }

    /// The new text, and the hook when it changed.
    static func edit(_ id: String, body: String, hook: String? = nil) -> [String] {
        var argv = ["growth", "edit", id, "--body=\(body.trimmingCharacters(in: .whitespacesAndNewlines))"]
        if let hook { argv.append("--hook=\(hook.trimmingCharacters(in: .whitespacesAndNewlines))") }
        return argv
    }

    /// `teyla growth tag <id> --goal=<goal id | none>`: which goal a draft counts for. `nil` means "no goal".
    static func tag(_ id: String, goal: String?) -> [String] { ["growth", "tag", id, "--goal=\(goal ?? "none")"] }

    /// The allow-list's answer for a `growth` command.
    static func check(_ argv: [String]) -> ToolCommands.Check {
        guard argv.count >= 3, argv[0] == "growth", GrowthDrafts.isItemID(argv[2]) else {
            return .refused("Teyla does not run this from the app: \(ToolCommands.display(argv)).")
        }
        func value(_ flag: String, _ text: String) -> String? {
            text.hasPrefix(flag) ? String(text.dropFirst(flag.count)) : nil
        }
        switch (argv[1], argv.count) {
        case ("approve", 3):
            return .allowed
        case ("reject", 4):
            guard let reason = value("--reason=", argv[3]), !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  reason.count <= reasonLimit else { return .refused("A reason of 1 to \(reasonLimit) characters is needed.") }
            return .allowed
        case ("tag", 4):
            guard let goal = value("--goal=", argv[3]), goal == "none" || GtmGoalCommands.isGoalID(goal) else {
                return .refused("A goal id, or none, is needed.")
            }
            return .allowed
        case ("edit", 4), ("edit", 5):
            guard let body = value("--body=", argv[3]), !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  body.count <= bodyLimit else { return .refused("The text must be 1 to \(bodyLimit) characters.") }
            if argv.count == 5 {
                guard let hook = value("--hook=", argv[4]), hook.count <= hookLimit else { return .refused("The hook must be at most \(hookLimit) characters.") }
            }
            return .allowed
        default:
            return .refused("Teyla does not run this from the app: \(ToolCommands.display(argv)).")
        }
    }
}

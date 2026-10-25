import Foundation

// The first run: `teyla start --json` is the read-only diagnosis (docs/START.md), `teyla apply <id> --yes`
// makes one change. The app decodes the report and holds nothing of it beyond what is on screen.

enum FirstRun {
    /// The one-line promise, word for word what `teyla` prints under its name (`PROMISE` in src/teyla/__init__.py).
    /// tests/test_mac_first_run.py fails when the two differ.
    static let promise = "Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's waiting on you, and fixes the waste. Nothing about your sessions leaves your Mac unless you turn it on."

    /// What sits under the Run button.
    static let runNote = "Reads the session files on this Mac and changes nothing. It can take up to a minute."

    static let startArguments = ["start", "--json"]

    /// Offer ids are `O` and a number. Anything else never reaches the command line, so an id cannot be read as a flag.
    static func isOfferID(_ id: String) -> Bool {
        id.count >= 2 && id.first == "O" && id.dropFirst().allSatisfy(\.isNumber)
    }

    static func applyArguments(offerID: String) -> [String] {
        ["apply", offerID, "--yes"]
    }
}

/// `teyla start --json`: `{summary_text, diagnosis, offers}`.
struct StartReport: Decodable, Equatable, Sendable {
    var summaryText: String
    var diagnosis: Diagnosis
    var offers: [StartOffer]

    enum CodingKeys: String, CodingKey {
        case summaryText = "summary_text"
        case diagnosis, offers
    }

    init(summaryText: String = "", diagnosis: Diagnosis = Diagnosis(), offers: [StartOffer] = []) {
        self.summaryText = summaryText
        self.diagnosis = diagnosis
        self.offers = offers
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        summaryText = c.lenient(.summaryText, "")
        diagnosis = c.lenient(.diagnosis, Diagnosis())
        let boxes: [LossyBox<StartOffer>] = c.lenient(.offers, [])
        offers = boxes.compactMap(\.value)
    }

    /// The offers the owner can act on.
    var applicable: [StartOffer] { offers.filter(\.applies) }
    /// The others, each with the reason it is left out.
    var skipped: [StartOffer] { offers.filter { !$0.applies } }
}

struct Diagnosis: Decodable, Equatable, Sendable {
    var days: Int
    var empty: Bool
    var totalUSD: Double
    var contextUSD: Double
    var contextShare: Double
    var longSessions: Int
    var longSessionsUSD: Double
    var longContextTokens: Int
    var subagentUSD: Double
    var subagentOpusShare: Double
    var waitingAsks: Int
    var sessions: Int
    var activeDays: Int
    var note: String

    enum CodingKeys: String, CodingKey {
        case days, empty, sessions, note
        case totalUSD = "total_usd"
        case contextUSD = "context_usd"
        case contextShare = "context_share"
        case longSessions = "long_sessions"
        case longSessionsUSD = "long_sessions_usd"
        case longContextTokens = "long_context_tokens"
        case subagentUSD = "subagent_usd"
        case subagentOpusShare = "subagent_opus_share"
        case waitingAsks = "waiting_asks"
        case activeDays = "active_days"
    }

    init(days: Int = 30, empty: Bool = true, totalUSD: Double = 0, contextUSD: Double = 0, contextShare: Double = 0,
         longSessions: Int = 0, longSessionsUSD: Double = 0, longContextTokens: Int = 250_000, subagentUSD: Double = 0,
         subagentOpusShare: Double = 0, waitingAsks: Int = 0, sessions: Int = 0, activeDays: Int = 0, note: String = "") {
        self.days = days
        self.empty = empty
        self.totalUSD = totalUSD
        self.contextUSD = contextUSD
        self.contextShare = contextShare
        self.longSessions = longSessions
        self.longSessionsUSD = longSessionsUSD
        self.longContextTokens = longContextTokens
        self.subagentUSD = subagentUSD
        self.subagentOpusShare = subagentOpusShare
        self.waitingAsks = waitingAsks
        self.sessions = sessions
        self.activeDays = activeDays
        self.note = note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        days = c.lenient(.days, 30)
        empty = c.lenient(.empty, false)
        totalUSD = c.lenient(.totalUSD, 0)
        contextUSD = c.lenient(.contextUSD, 0)
        contextShare = c.lenient(.contextShare, 0)
        longSessions = c.lenient(.longSessions, 0)
        longSessionsUSD = c.lenient(.longSessionsUSD, 0)
        longContextTokens = c.lenient(.longContextTokens, 250_000)
        subagentUSD = c.lenient(.subagentUSD, 0)
        subagentOpusShare = c.lenient(.subagentOpusShare, 0)
        waitingAsks = c.lenient(.waitingAsks, 0)
        sessions = c.lenient(.sessions, 0)
        activeDays = c.lenient(.activeDays, 0)
        note = c.lenient(.note, "")
    }

    /// "3 sessions on 1 day", the line under the big number.
    var scope: String {
        "\(sessions) \(sessions == 1 ? "session" : "sessions") on \(activeDays) \(activeDays == 1 ? "day" : "days")"
    }

    /// The facts under the total, numbers first (the same ones the terminal card prints).
    var lines: [String] {
        var out: [String] = []
        if contextUSD > 0 {
            out.append("\(Self.percent(contextShare)) of it (\(Format.spent(contextUSD))) went on re-reading and storing context.")
        }
        if longSessions > 0 {
            out.append("\(longSessions) \(longSessions == 1 ? "session" : "sessions") ran past \(longContextTokens / 1000)k tokens of context and cost \(Format.spent(longSessionsUSD)).")
        }
        if subagentUSD > 0 {
            out.append("Subagents cost \(Format.spent(subagentUSD)); Opus ran \(Self.percent(subagentOpusShare)) of that.")
        }
        if waitingAsks > 0 {
            out.append("\(waitingAsks) \(waitingAsks == 1 ? "question is" : "questions are") waiting on you.")
        }
        return out
    }

    static func percent(_ share: Double) -> String {
        "\(Int((share * 100).rounded()))%"
    }
}

/// What an offer would change: a key in a JSON or TOML file, a file Teyla creates, or a command it runs.
struct OfferChange: Decodable, Equatable, Sendable {
    var kind: String
    var file: String
    var keyPath: [String]
    var command: String
    var summary: String

    enum CodingKeys: String, CodingKey {
        case kind, file, command, summary
        case keyPath = "key_path"
    }

    init(kind: String = "", file: String = "", keyPath: [String] = [], command: String = "", summary: String = "") {
        self.kind = kind
        self.file = file
        self.keyPath = keyPath
        self.command = command
        self.summary = summary
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        kind = c.lenient(.kind, "")
        file = c.lenient(.file, "")
        keyPath = c.lenient(.keyPath, [])
        command = c.lenient(.command, "")
        summary = c.lenient(.summary, "")
    }

    var key: String { keyPath.joined(separator: ".") }
}

struct StartOffer: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var title: String
    var change: OfferChange
    var savingLow: Double?
    var savingHigh: Double?
    var basis: String
    var benefit: String
    var tradeoff: String
    var undo: String
    var applies: Bool
    var reason: String
    var explain: String

    enum CodingKeys: String, CodingKey {
        case id, title, change, basis, benefit, tradeoff, undo, applies, reason, explain
        case saving = "saving_usd_month"
    }

    private struct Saving: Decodable {
        var low: Double
        var high: Double
    }

    init(id: String, title: String = "", change: OfferChange = OfferChange(), savingLow: Double? = nil, savingHigh: Double? = nil,
         basis: String = "", benefit: String = "", tradeoff: String = "", undo: String = "", applies: Bool = true,
         reason: String = "", explain: String = "") {
        self.id = id
        self.title = title
        self.change = change
        self.savingLow = savingLow
        self.savingHigh = savingHigh
        self.basis = basis
        self.benefit = benefit
        self.tradeoff = tradeoff
        self.undo = undo
        self.applies = applies
        self.reason = reason
        self.explain = explain
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        title = c.lenient(.title, id)
        change = c.lenient(.change, OfferChange())
        let saving: Saving? = c.optional(.saving)
        savingLow = saving?.low
        savingHigh = saving?.high
        basis = c.lenient(.basis, "")
        benefit = c.lenient(.benefit, "")
        tradeoff = c.lenient(.tradeoff, "")
        undo = c.lenient(.undo, "")
        applies = c.lenient(.applies, false)
        reason = c.lenient(.reason, "")
        explain = c.lenient(.explain, "")
    }

    /// "About $4.91-$9.81 a month at API list price", or what the change brings when no honest figure exists.
    var gain: String {
        if let low = savingLow, let high = savingHigh, high > 0 {
            let range = Format.spent(low) == Format.spent(high) ? Format.spent(high) : "\(Format.spent(low))-\(Format.spent(high))"
            return "About \(range) a month at API list price"
        }
        return benefit
    }

    var hasSaving: Bool { (savingHigh ?? 0) > 0 }

    /// Offers O5 to O7 run an existing sync: `teyla undo` does not reverse them, and `teyla uninstall` does.
    var undoIsUninstall: Bool { change.kind == "command" && undo.contains("teyla uninstall") }

    /// The confirm sheet's first sentence: the file and the key, or the command.
    var willChange: String {
        switch change.kind {
        case "command":
            return "Teyla will run \(change.command.isEmpty ? "a command" : change.command)."
        default:
            let where_ = change.file.isEmpty ? "a file" : change.file
            return change.keyPath.isEmpty
                ? "Teyla will create \(where_)."
                : "Teyla will change \(change.key) in \(where_)."
        }
    }

    /// The confirm sheet's second sentence: what is saved first, and how to take it back.
    var safety: String {
        if change.kind == "command" {
            return undoIsUninstall
                ? "This cannot be undone one step at a time. `teyla uninstall` removes all of Teyla's hooks, links and data."
                : undo
        }
        if change.keyPath.isEmpty { return undo }
        return "Teyla copies the file to a backup first. \(undo)"
    }
}

/// How one offer is doing after the owner pressed Apply.
enum OfferStatus: Equatable {
    case applying
    case applied(String)
    case failed(String)

    /// Whether the confirm sheet may open for an offer in this state: a new offer, or one whose last try failed.
    static func allowsConfirmation(_ status: OfferStatus?) -> Bool {
        switch status {
        case nil, .failed: return true
        case .applying, .applied: return false
        }
    }
}

/// Where the diagnosis is.
enum DiagnosisPhase: Equatable {
    case idle
    case running
    case ready(StartReport)
    case failed(String)
}

extension Snapshot {
    /// No question, product, session, task or result: a machine Teyla has not seen at work yet.
    var isEmpty: Bool {
        asks.isEmpty && products.isEmpty && running.isEmpty && tasks.isEmpty && done.isEmpty
    }
}

enum StartDecoding {
    static func decode(_ data: Data) throws -> StartReport {
        do {
            return try JSONDecoder().decode(StartReport.self, from: data)
        } catch {
            throw TeylaError.badOutput("not a diagnosis")
        }
    }

    /// The lines `teyla apply` printed after "Changed:"; with none, the first lines it printed.
    static func appliedLines(_ stdout: String) -> String {
        let lines = stdout.split(whereSeparator: \.isNewline).map(String.init)
        if let at = lines.firstIndex(where: { $0.trimmingCharacters(in: .whitespaces) == "Changed:" }) {
            return lines[(at + 1)...].prefix(3).map { $0.trimmingCharacters(in: .whitespaces) }.joined(separator: "\n")
        }
        return lines.prefix(3).map { $0.trimmingCharacters(in: .whitespaces) }.joined(separator: "\n")
    }
}

import Foundation

// What `teyla state` carries for the admin sections (`console` in the snapshot, docs/CONSOLE.md): the compact part of
// each section, as `compact()` in `src/teyla/console_*.py` and `growth.py` writes it. The iPhone has no `~/.teyla`, so
// its Growth, Money, Operations and Playbook screens read only this. Each part reuses the full report's parser for the
// keys the two have in common, so a number is read the same way on both devices; a key the compact part does not carry
// stays nil and the phone says "On your Mac" instead of showing a made-up figure.
// The iPhone app compiles this file by path, so keep it free of UI.

/// Growth: the same keys as the full report, fewer of them (no episodes, trends, outreach, ads or draft text).
typealias GrowthCompact = GrowthReport

/// Money: the cash total, the unpriced rows counted, the week at API list price, and the next renewal.
struct MoneyCompact: Decodable, Equatable, Sendable, ConsoleSectionData {
    var headline: ConsoleHeadline?
    var monthlyUSD: Double?
    /// How many listed rows have no price.
    var unpriced: Int?
    /// The last 7 days at API list prices. Never cash.
    var listUSD7d: Double?
    var nextRenewal: MoneyRenewal?

    enum CodingKeys: String, CodingKey {
        case headline, unpriced
        case monthlyUSD = "monthly_usd", listUSD7d = "list_usd_7d", nextRenewal = "next_renewal"
    }

    init(headline: ConsoleHeadline? = nil, monthlyUSD: Double? = nil, unpriced: Int? = nil, listUSD7d: Double? = nil,
         nextRenewal: MoneyRenewal? = nil) {
        self.headline = headline
        self.monthlyUSD = monthlyUSD
        self.unpriced = unpriced
        self.listUSD7d = listUSD7d
        self.nextRenewal = nextRenewal
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
        monthlyUSD = c.optional(.monthlyUSD)
        unpriced = c.optional(.unpriced)
        listUSD7d = c.optional(.listUSD7d)
        nextRenewal = c.optional(.nextRenewal)
    }
}

/// Operations: the headline, the machine's verdict and free disk, whether the lid can close, the top failures.
struct OperationsCompact: Decodable, Equatable, Sendable, ConsoleSectionData {
    var headline: ConsoleHeadline?
    var machine: OpsMachine?
    /// Can the owner close the lid and go; nil when the machine could not be read.
    var leaveOK: Bool?
    var failures: [OpsFailure]
    /// False when the compact part carried no failure list at all: "nothing is failing" must not be said then.
    var failuresRead: Bool

    enum CodingKeys: String, CodingKey { case headline, machine, failures, leaveOK = "leave_ok" }

    init(headline: ConsoleHeadline? = nil, machine: OpsMachine? = nil, leaveOK: Bool? = nil, failures: [OpsFailure] = [],
         failuresRead: Bool = true) {
        self.headline = headline
        self.machine = machine
        self.leaveOK = leaveOK
        self.failures = failures
        self.failuresRead = failuresRead
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
        machine = c.optional(.machine)
        leaveOK = c.optional(.leaveOK)
        let rows: [LossyBox<OpsFailure>]? = c.optional(.failures)
        failures = (rows ?? []).compactMap(\.value)
        failuresRead = rows != nil
    }

    /// How many failures the headline counts beyond the ones carried here.
    var failuresNotShown: Int {
        guard let total = headline?.number, total > Double(failures.filter(\.needsYou).count) else { return 0 }
        return Int(total) - failures.filter(\.needsYou).count
    }
}

/// Playbook: the headline, counts of models to look at, and the knowledge counts. The quote and the chore count come
/// only when the owner set `[you] relay = true`.
struct PlaybookCompact: Decodable, Equatable, Sendable, ConsoleSectionData {
    var headline: ConsoleHeadline?
    /// Places where the model ladder and the catalogue disagree.
    var modelsDrift: Int?
    /// Catalogue models nobody has acknowledged.
    var modelsNew: Int?
    /// The day the arena snapshot is from.
    var arenaAsOf: Date?
    var knowledge: PlaybookKnowledge?
    var quote: String?
    var choresOpen: Int?

    enum CodingKeys: String, CodingKey { case headline, models, knowledge, you }

    private struct Models: Decodable {
        var drift: Int?
        var new: Int?
        var arenaAsOf: String?

        enum CodingKeys: String, CodingKey { case drift, new, arenaAsOf = "arena_as_of" }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            drift = c.optional(.drift)
            new = c.optional(.new)
            arenaAsOf = c.optional(.arenaAsOf)
        }
    }

    private struct You: Decodable {
        var quote: String?
        var choresOpen: Int?

        enum CodingKeys: String, CodingKey { case quote, choresOpen = "chores_open" }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            if let text: String = c.optional(.quote) {
                quote = text
            } else if let object: PlaybookQuote = c.optional(.quote) {
                quote = object.text
            }
            choresOpen = c.optional(.choresOpen)
        }
    }

    init(headline: ConsoleHeadline? = nil, modelsDrift: Int? = nil, modelsNew: Int? = nil, arenaAsOf: Date? = nil,
         knowledge: PlaybookKnowledge? = nil, quote: String? = nil, choresOpen: Int? = nil) {
        self.headline = headline
        self.modelsDrift = modelsDrift
        self.modelsNew = modelsNew
        self.arenaAsOf = arenaAsOf
        self.knowledge = knowledge
        self.quote = quote
        self.choresOpen = choresOpen
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
        let models: Models? = c.optional(.models)
        modelsDrift = models?.drift
        modelsNew = models?.new
        arenaAsOf = models?.arenaAsOf.flatMap(MoneyLogic.day)
        knowledge = c.optional(.knowledge)
        let you: You? = c.optional(.you)
        quote = you?.quote
        choresOpen = you?.choresOpen
    }

    /// Models to look at: drift plus new; nil when the compact part carries neither.
    var modelsToLook: Int? {
        guard modelsDrift != nil || modelsNew != nil else { return nil }
        return (modelsDrift ?? 0) + (modelsNew ?? 0)
    }
}

/// The four sections as the phone reads them. A section the Mac did not send is `.missing`; one whose source failed is
/// `.failed` with the reason, and the other sections still load.
struct ConsoleCompact: Decodable, Equatable, Sendable {
    var growth: ConsoleLoad<GrowthCompact>
    var money: ConsoleLoad<MoneyCompact>
    var operations: ConsoleLoad<OperationsCompact>
    var playbook: ConsoleLoad<PlaybookCompact>

    enum CodingKeys: String, CodingKey { case growth, money, operations, playbook }

    init(growth: ConsoleLoad<GrowthCompact> = .missing, money: ConsoleLoad<MoneyCompact> = .missing,
         operations: ConsoleLoad<OperationsCompact> = .missing, playbook: ConsoleLoad<PlaybookCompact> = .missing) {
        self.growth = growth
        self.money = money
        self.operations = operations
        self.playbook = playbook
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        growth = c.load(.growth)
        money = c.load(.money)
        operations = c.load(.operations)
        playbook = c.load(.playbook)
    }

    /// True when the snapshot's console holds no section at all.
    var allMissing: Bool {
        growth == .missing && money == .missing && operations == .missing && playbook == .missing
    }
}

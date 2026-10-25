import Foundation

// The product page (docs/PRODUCTS.md, `teyla product show <id> --json`). The app holds none of it:
// the CLI reads the registry, the asks, the notes and the sessions, and the window shows what comes back.

/// A product's stage in the registry, in the order the picker lists them.
enum ProductStage: String, CaseIterable, Sendable {
    case idea, building, beta, live, parked

    var title: String { rawValue.capitalized }
}

enum ProductCommands {
    /// An id comes from the registry or from `teyla state`; this keeps one that starts with "-" or holds a space
    /// from reaching the command line as a flag.
    static func isProductID(_ id: String) -> Bool {
        guard let first = id.first, first != "-" else { return false }
        return id.allSatisfy { !$0.isWhitespace }
    }

    /// `--quick` leaves out the sessions and the spend, which need a full read of 30 days of sessions.
    static func showArguments(id: String, quick: Bool) -> [String] {
        ["product", "show", id, "--json"] + (quick ? ["--quick"] : [])
    }

    static func stageArguments(id: String, stage: ProductStage) -> [String] {
        ["product", "set", id, "stage=\(stage.rawValue)"]
    }

    static func focusArguments(id: String, focus: Bool) -> [String] {
        ["product", "set", id, "focus=\(focus ? "true" : "false")"]
    }
}

struct ProductHeader: Decodable, Equatable, Sendable {
    var id: String
    var name: String
    var stage: String
    var focus: Bool
    var primary: String
    var repos: [String]
    var aliases: [String]
    var registered: Bool

    enum CodingKeys: String, CodingKey {
        case id, name, stage, focus, primary, repos, aliases, registered
    }

    init(id: String, name: String = "", stage: String = "", focus: Bool = false, primary: String = "",
         repos: [String] = [], aliases: [String] = [], registered: Bool = true) {
        self.id = id
        self.name = name.isEmpty ? Format.product(id) : name
        self.stage = stage
        self.focus = focus
        self.primary = primary
        self.repos = repos
        self.aliases = aliases
        self.registered = registered
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let id: String = try c.decode(String.self, forKey: .id)
        self.init(id: id, name: c.lenient(.name, ""), stage: c.lenient(.stage, ""), focus: c.lenient(.focus, false),
                  primary: c.lenient(.primary, ""), repos: c.lenient(.repos, []), aliases: c.lenient(.aliases, []),
                  registered: c.lenient(.registered, true))
    }

    var stageValue: ProductStage? { ProductStage(rawValue: stage) }
}

struct ProductAsk: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var ageSeconds: Double
    var critical: Bool
    var question: String
    var link: String

    enum CodingKeys: String, CodingKey {
        case id, severity, question, link
        case ageSeconds = "age_s"
    }

    init(id: String, ageSeconds: Double = 0, critical: Bool = false, question: String = "", link: String = "") {
        self.id = id
        self.ageSeconds = ageSeconds
        self.critical = critical
        self.question = question
        self.link = link
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        ageSeconds = c.lenient(.ageSeconds, 0)
        critical = c.lenient(.severity, "normal") == "critical"
        question = c.lenient(.question, "")
        link = c.lenient(.link, "")
    }
}

struct ProductNote: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var text: String
    var created: String

    enum CodingKeys: String, CodingKey { case id, text, created }

    init(id: String, text: String = "", created: String = "") {
        self.id = id
        self.text = text
        self.created = created
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        text = c.lenient(.text, "")
        created = c.lenient(.created, "")
    }

    /// The note as the Notes section knows it, so its row (Link, Drop) is the same one.
    func item(product: String) -> NoteItem {
        NoteItem(id: id, text: text, product: product, created: created, updated: created, linkedBy: "owner")
    }
}

struct ProductSession: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var at: String
    var harness: String
    var model: String
    var costUSD: Double
    var title: String

    enum CodingKeys: String, CodingKey {
        case id, at, harness, model, title
        case costUSD = "cost_usd"
    }

    init(id: String, at: String = "", harness: String = "", model: String = "", costUSD: Double = 0, title: String = "") {
        self.id = id
        self.at = at
        self.harness = harness
        self.model = model
        self.costUSD = costUSD
        self.title = title
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        at = c.lenient(.at, "")
        harness = c.lenient(.harness, "")
        model = c.lenient(.model, "")
        costUSD = c.lenient(.costUSD, 0)
        title = c.lenient(.title, "")
    }

    var date: Date? { ISODate.parse(at) }

    /// "Sonnet", or "" when the model is unknown.
    var modelName: String { model.isEmpty ? "" : Format.model(model) }
}

struct ProductSpend: Decodable, Equatable, Sendable {
    var days7: Double
    var days30: Double

    enum CodingKeys: String, CodingKey {
        case days7 = "days_7"
        case days30 = "days_30"
    }

    init(days7: Double = 0, days30: Double = 0) {
        self.days7 = days7
        self.days30 = days30
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        days7 = c.lenient(.days7, 0)
        days30 = c.lenient(.days30, 0)
    }
}

/// `teyla product show <id> --json`, version 1. `sessions` and `spend` are nil for a `--quick` read.
struct ProductPageData: Decodable, Equatable, Sendable {
    var version: Int
    var generated: String
    var product: ProductHeader
    var asks: [ProductAsk]
    var notes: [ProductNote]
    var sessions: [ProductSession]?
    var spend: ProductSpend?

    enum CodingKeys: String, CodingKey {
        case version, generated, product, asks, notes, sessions, spend
    }

    init(product: ProductHeader, asks: [ProductAsk] = [], notes: [ProductNote] = [],
         sessions: [ProductSession]? = nil, spend: ProductSpend? = nil, version: Int = 1, generated: String = "") {
        self.version = version
        self.generated = generated
        self.product = product
        self.asks = asks
        self.notes = notes
        self.sessions = sessions
        self.spend = spend
    }

    /// Applies a finished stage or focus write, only if this page is still the product it was written for.
    @discardableResult
    mutating func applyWrite(to productID: String, _ edit: (inout ProductHeader) -> Void) -> Bool {
        guard product.id == productID else { return false }
        edit(&product)
        return true
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = c.lenient(.version, 1)
        generated = c.lenient(.generated, "")
        product = try c.decode(ProductHeader.self, forKey: .product)
        let asks: [LossyBox<ProductAsk>] = c.lenient(.asks, [])
        let notes: [LossyBox<ProductNote>] = c.lenient(.notes, [])
        self.asks = asks.compactMap(\.value)
        self.notes = notes.compactMap(\.value)
        if c.contains(.sessions), (try? c.decodeNil(forKey: .sessions)) == false {
            let rows: [LossyBox<ProductSession>] = c.lenient(.sessions, [])
            sessions = rows.compactMap(\.value)
        } else {
            sessions = nil
        }
        spend = c.optional(.spend)
    }

    static func decode(_ data: Data) throws -> ProductPageData {
        do {
            return try JSONDecoder().decode(ProductPageData.self, from: data)
        } catch {
            throw TeylaError.badOutput("not a product page")
        }
    }
}

enum ProductNotes {
    /// The notes of one product page. Once the window's note list is read it is the truth (a note added or linked
    /// here after the page loaded shows; one dropped or linked elsewhere leaves). Before that, the page's own notes.
    static func shown(productID: String, page: [ProductNote], list: [NoteItem], listLoaded: Bool) -> [NoteItem] {
        if listLoaded {
            return list.filter { $0.product == productID && !$0.dropped }
        }
        return page.map { $0.item(product: productID) }
    }
}

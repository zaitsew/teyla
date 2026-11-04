import Foundation

// `teyla console --json` (docs/CONSOLE.md): the full report behind the admin sections. Decoding is lenient like the
// snapshot's. A section whose source failed arrives as `{"error": "..."}` and reads as `.failed`; the other sections
// still load. A figure the source does not know is nil and the screen shows a dash with the reason.
// The iPhone app compiles this file by path, so keep it free of UI.

/// One section of the report: its data, the error its source gave, or nothing at all (the key is missing or null).
enum ConsoleLoad<Value: Equatable & Sendable>: Equatable, Sendable {
    case data(Value)
    case failed(String)
    case missing

    var value: Value? {
        if case .data(let value) = self { return value }
        return nil
    }

    var error: String? {
        if case .failed(let why) = self { return why }
        return nil
    }
}

extension ConsoleLoad: Decodable where Value: Decodable {
    init(from decoder: Decoder) throws {
        if let why = (try? ConsoleErrorProbe(from: decoder))?.error {
            self = .failed(why.isEmpty ? "The source gave no reason." : why)
            return
        }
        do {
            self = .data(try Value(from: decoder))
        } catch {
            self = .failed("Teyla printed something this app could not read.")
        }
    }
}

/// `{"error": "..."}`, the shape of a section or a part that failed.
struct ConsoleErrorProbe: Decodable {
    var error: String?

    enum CodingKeys: String, CodingKey { case error }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

extension KeyedDecodingContainer {
    /// A section or a part: `missing` when the key is absent or null, `failed` when it holds an error or cannot be read.
    func load<V: Decodable & Equatable & Sendable>(_ key: Key, as type: V.Type = V.self) -> ConsoleLoad<V> {
        guard contains(key), (try? decodeNil(forKey: key)) == false else { return .missing }
        return (try? decode(ConsoleLoad<V>.self, forKey: key)) ?? .failed("Teyla printed something this app could not read.")
    }
}

/// What every section carries.
protocol ConsoleSectionData: Equatable, Sendable {
    var headline: ConsoleHeadline? { get }
}

struct ConsoleReport: Decodable, Equatable, Sendable {
    var version: Int
    /// Epoch seconds the CLI built the report.
    var generated: Date?
    var operations: ConsoleLoad<OperationsReport>
    var money: ConsoleLoad<MoneyReport>
    var playbook: ConsoleLoad<PlaybookReport>
    var growth: ConsoleLoad<GrowthReport>

    enum CodingKeys: String, CodingKey { case version, generated, operations, money, playbook, growth }

    init(version: Int = 1, generated: Date? = nil, operations: ConsoleLoad<OperationsReport> = .missing,
         money: ConsoleLoad<MoneyReport> = .missing, playbook: ConsoleLoad<PlaybookReport> = .missing,
         growth: ConsoleLoad<GrowthReport> = .missing) {
        self.version = version
        self.generated = generated
        self.operations = operations
        self.money = money
        self.playbook = playbook
        self.growth = growth
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = c.lenient(.version, 1)
        let epoch: Double? = c.optional(.generated)
        generated = epoch.map { Date(timeIntervalSince1970: $0) }
        operations = c.load(.operations)
        money = c.load(.money)
        playbook = c.load(.playbook)
        growth = c.load(.growth)
    }

    /// A report must be an object; anything else is refused, not shown as an empty console.
    static func decode(_ data: Data) throws -> ConsoleReport {
        do {
            return try JSONDecoder().decode(ConsoleReport.self, from: data)
        } catch {
            throw TeylaError.badOutput("not a console report")
        }
    }

    /// True when the report holds no section at all, which is not a report the pages can use.
    var allMissing: Bool {
        operations == .missing && money == .missing && playbook == .missing && growth == .missing
    }
}

extension ConsoleHeadline {
    /// The headline's figure as text: "4/6" stays as sent, a number loses its ".0". Nil is a dash.
    var display: String? {
        if let text, !text.isEmpty { return text }
        return number.map { $0 == $0.rounded() ? "\(Int($0))" : "\($0)" }
    }
}

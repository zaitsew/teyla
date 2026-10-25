import Foundation

// Text notes (docs/NOTES.md). The app holds none of them: `teyla note` and `teyla notes` do.

/// One note from `teyla notes --json`.
struct NoteItem: Decodable, Equatable, Identifiable, Sendable {
    static let inbox = "inbox"

    var id: String
    var text: String
    /// A registry id, or `inbox`.
    var product: String
    var source: String
    var created: String
    var updated: String
    /// `owner`, `text`, `cwd` or "".
    var linkedBy: String
    var dropped: Bool

    enum CodingKeys: String, CodingKey {
        case id, text, product, source, created, updated, dropped
        case linkedBy = "linked_by"
    }

    init(id: String, text: String = "", product: String = NoteItem.inbox, source: String = "owner",
         created: String = "", updated: String = "", linkedBy: String = "", dropped: Bool = false) {
        self.id = id
        self.text = text
        self.product = product
        self.source = source
        self.created = created
        self.updated = updated
        self.linkedBy = linkedBy
        self.dropped = dropped
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        text = c.lenient(.text, "")
        product = c.lenient(.product, NoteItem.inbox)
        source = c.lenient(.source, "owner")
        created = c.lenient(.created, "")
        updated = c.lenient(.updated, "")
        linkedBy = c.lenient(.linkedBy, "")
        dropped = c.lenient(.dropped, false)
    }

    var isInbox: Bool { product == Self.inbox }
    var createdDate: Date? { ISODate.parse(created) }
}

/// `teyla note --suggest --json`: `{product, linked_by, candidates}`.
struct NoteSuggestion: Decodable, Equatable, Sendable {
    var product: String
    var linkedBy: String
    var candidates: [String]

    enum CodingKeys: String, CodingKey {
        case product, candidates
        case linkedBy = "linked_by"
    }

    init(product: String, linkedBy: String = "", candidates: [String] = []) {
        self.product = product
        self.linkedBy = linkedBy
        self.candidates = candidates
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        product = c.lenient(.product, NoteItem.inbox)
        linkedBy = c.lenient(.linkedBy, "")
        candidates = c.lenient(.candidates, [])
    }
}

enum Notes {
    /// The notes shown in the window.
    static let shownInWindow = 5
    /// The picker numbers the first nine candidates ⌘1–⌘9; ⌘0 is the inbox.
    static let numbered = 9

    // MARK: Commands

    /// The text goes on stdin (`-`), never in an argument: it can start with "-" and can be long.
    static func saveArguments(product: String) -> [String] {
        ["note", "-", "--product", product, "--json"]
    }

    static func suggestArguments(cwd: String) -> [String] {
        ["note", "--suggest", "-", "--json", "--cwd", cwd]
    }

    static func linkArguments(id: String, product: String) -> [String] {
        ["note", "link", id, product, "--json"]
    }

    static func dropArguments(id: String) -> [String] {
        ["note", "drop", id, "--json"]
    }

    static let listArguments = ["notes", "--json"]

    // MARK: Decoding

    static func decodeNotes(_ data: Data) throws -> [NoteItem] {
        guard let boxes = try? JSONDecoder().decode([LossyBox<NoteItem>].self, from: data) else {
            throw TeylaError.badOutput("not a list of notes")
        }
        return boxes.compactMap(\.value)
    }

    static func decodeNote(_ data: Data) throws -> NoteItem {
        guard let note = try? JSONDecoder().decode(NoteItem.self, from: data) else {
            throw TeylaError.badOutput("not a note")
        }
        return note
    }

    static func decodeSuggestion(_ data: Data) throws -> NoteSuggestion {
        guard let found = try? JSONDecoder().decode(NoteSuggestion.self, from: data) else {
            throw TeylaError.badOutput("not a suggestion")
        }
        return found
    }

    // MARK: Window

    /// Open notes, newest first (by `created`; the CLI already sorts, this keeps the app right if it did not).
    static func newestOpen(_ notes: [NoteItem], limit: Int = shownInWindow) -> [NoteItem] {
        let open = notes.filter { !$0.dropped }
        let sorted = open.enumerated().sorted { a, b in
            let (x, y) = (a.element.createdDate ?? .distantPast, b.element.createdDate ?? .distantPast)
            return x == y ? a.offset < b.offset : x > y
        }
        return sorted.prefix(limit).map(\.element)
    }

    static func inboxCount(_ notes: [NoteItem]) -> Int {
        notes.filter { !$0.dropped && $0.isInbox }.count
    }

    static func openCount(_ notes: [NoteItem]) -> Int {
        notes.filter { !$0.dropped }.count
    }

    /// The product chip on a note: "Inbox", or the product name as the rest of the window writes it.
    static func productLabel(_ product: String) -> String {
        product == NoteItem.inbox ? "Inbox" : Format.product(product)
    }

    // MARK: Panel

    static func canSave(_ text: String) -> Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// How the product was chosen, in the words under the chip.
    static func howLabel(_ linkedBy: String, product: String) -> String {
        switch linkedBy {
        case "owner": return "chosen by you"
        case "text": return "named in the text"
        case "cwd": return "from this directory"
        default: return product == NoteItem.inbox ? "from Inbox" : "suggested"
        }
    }

    /// The candidates the picker numbers (⌘1–⌘9) and the rest it folds into a menu.
    static func split(_ candidates: [String]) -> (numbered: [String], more: [String]) {
        (Array(candidates.prefix(numbered)), Array(candidates.dropFirst(numbered)))
    }

    /// The product behind ⌘n: 0 is the inbox, 1–9 are the numbered candidates; nil when there is none.
    static func product(forDigit digit: Int, candidates: [String]) -> String? {
        if digit == 0 { return NoteItem.inbox }
        let list = split(candidates).numbered
        return digit >= 1 && digit <= list.count ? list[digit - 1] : nil
    }

    /// What the CLI would suggest, worked out from the products in a preview snapshot: the one product the text
    /// names as a whole word, else the inbox. Used only with `TEYLA_STATE_FIXTURE`.
    static func simulate(text: String, products: [String]) -> NoteSuggestion {
        let lowered = text.lowercased()
        let named = products.filter { name in
            let pattern = "(?<![\\p{L}\\p{N}_])" + NSRegularExpression.escapedPattern(for: name.lowercased()) + "(?![\\p{L}\\p{N}_])"
            return lowered.range(of: pattern, options: .regularExpression) != nil
        }
        if named.count == 1 { return NoteSuggestion(product: named[0], linkedBy: "text", candidates: products) }
        return NoteSuggestion(product: NoteItem.inbox, linkedBy: "", candidates: products)
    }
}

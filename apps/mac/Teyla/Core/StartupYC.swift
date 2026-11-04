import Foundation

// The YC sheet (docs/STARTUP.md, "The YC sheet"): `teyla startup yc <id> --json`. Fifteen boxes, each one a question
// the owner can answer honestly with evidence. A box does not say a number is good, and an unchecked box does not mean
// the owner may not apply. The count is "2 of 15", never a percent. Teyla never submits an application.
// The answers are customer text: they are read here from the command, kept in memory while the sheet is open, and never
// put in `state` or on the relay.

struct YCSheet: Decodable, Equatable, Sendable {
    var id: String
    var eligible: Bool
    var checked: Int
    var total: Int
    /// `apply` when every box is checked, else `keep going`.
    var verdict: String
    var nextBox: String?
    var facts: YCFacts
    var boxes: [YCBox]

    enum CodingKeys: String, CodingKey {
        case id, eligible, checked, total, verdict, facts, boxes
        case nextBox = "next_box"
    }

    init(id: String, eligible: Bool = true, checked: Int = 0, total: Int = 15, verdict: String = "keep going",
         nextBox: String? = nil, facts: YCFacts = YCFacts(), boxes: [YCBox] = []) {
        self.id = id
        self.eligible = eligible
        self.checked = checked
        self.total = total
        self.verdict = verdict
        self.nextBox = nextBox
        self.facts = facts
        self.boxes = boxes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        let boxes: [LossyBox<YCBox>] = c.lenient(.boxes, [])
        self.boxes = boxes.compactMap(\.value)
        eligible = c.lenient(.eligible, true)
        // The count is the boxes that say they are checked, whatever the summary says: the two cannot disagree on screen.
        checked = self.boxes.filter(\.checked).count
        total = self.boxes.isEmpty ? c.lenient(.total, 15) : self.boxes.count
        verdict = c.lenient(.verdict, "keep going")
        nextBox = c.optional(.nextBox)
        facts = c.lenient(.facts, YCFacts())
    }

    static func decode(_ data: Data) throws -> YCSheet {
        do {
            return try JSONDecoder().decode(YCSheet.self, from: data)
        } catch {
            throw TeylaError.badOutput("not a YC sheet")
        }
    }
}

struct YCFacts: Decodable, Equatable, Sendable {
    /// The day the facts were read on ycombinator.com (YYYY-MM-DD).
    var read: String
    var ageDays: Int
    /// True when they are older than 90 days.
    var stale: Bool
    var lines: [String]

    enum CodingKeys: String, CodingKey {
        case read, stale, lines
        case ageDays = "age_days"
    }

    init(read: String = "", ageDays: Int = 0, stale: Bool = false, lines: [String] = []) {
        self.read = read
        self.ageDays = ageDays
        self.stale = stale
        self.lines = lines
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        read = c.lenient(.read, "")
        ageDays = c.lenient(.ageDays, 0)
        stale = c.lenient(.stale, false)
        lines = c.lenient(.lines, [])
    }
}

struct YCAnswer: Decodable, Equatable, Sendable {
    var text: String
    /// `confirmed`, or `draft` when an agent wrote it. A draft checks nothing.
    var status: String
    var by: String

    var isDraft: Bool { status != "confirmed" }

    init(text: String, status: String = "confirmed", by: String = "owner") {
        self.text = text
        self.status = status
        self.by = by
    }

    enum CodingKeys: String, CodingKey { case text, status, by }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        text = c.lenient(.text, "")
        status = c.lenient(.status, "draft")
        by = c.lenient(.by, "")
    }
}

struct YCBox: Decodable, Equatable, Identifiable, Sendable {
    var id: String
    var question: String
    var checked: Bool
    /// What is missing, in words; "" when the box is checked.
    var need: String
    /// The command that fills it, as the CLI prints it.
    var command: String
    /// `founder list`, or `teyla` for a box we added.
    var origin: String
    /// True when records fill the box (usage, money, the growth ledger), so there is no text to type.
    var auto: Bool
    var answer: YCAnswer?
    /// For an auto box: the sentence the records give.
    var evidence: String?

    enum CodingKeys: String, CodingKey { case id, question, checked, need, command, origin, auto, answer, evidence }

    init(id: String, question: String = "", checked: Bool = false, need: String = "", command: String = "",
         origin: String = "founder list", auto: Bool = false, answer: YCAnswer? = nil, evidence: String? = nil) {
        self.id = id
        self.question = question
        self.checked = checked
        self.need = need
        self.command = command
        self.origin = origin
        self.auto = auto
        self.answer = answer
        self.evidence = evidence
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let id: String = try c.decode(String.self, forKey: .id)
        self.init(id: id, question: c.lenient(.question, id), checked: c.lenient(.checked, false), need: c.lenient(.need, ""),
                  command: c.lenient(.command, ""), origin: c.lenient(.origin, ""), auto: c.lenient(.auto, false),
                  answer: c.optional(.answer), evidence: c.optional(.evidence))
    }
}

enum YCText {
    static let applyURL = URL(string: "https://www.ycombinator.com/apply")!

    /// "2 of 15". A count, never a percent.
    static func count(_ sheet: YCSheet) -> String { "\(sheet.checked) of \(sheet.total)" }

    /// All boxes are checked and the CLI says apply. Only then does the sheet offer the link.
    static func canApply(_ sheet: YCSheet) -> Bool {
        sheet.verdict == "apply" && !sheet.boxes.isEmpty && sheet.checked == sheet.total
    }

    /// The line under the count: the next box by its question, or the way to the application.
    static func lead(_ sheet: YCSheet) -> String {
        if canApply(sheet) { return "All boxes are checked. You can apply." }
        if let id = sheet.nextBox, let box = sheet.boxes.first(where: { $0.id == id }) { return "Next: \(box.question)" }
        return "Answer the boxes you can answer honestly."
    }

    /// Said beside the count on every sheet, so an unchecked box never reads as a reason not to apply.
    static let notABar = "An unchecked box does not mean you may not apply."
    static let neverSubmits = "Teyla never submits an application. You apply yourself."

    static func factsHeader(_ facts: YCFacts) -> String {
        facts.read.isEmpty ? "YC facts" : "YC facts, read on \(facts.read)"
    }

    /// The warning when the facts are old; nil when they are fresh.
    static func staleFacts(_ facts: YCFacts) -> String? {
        facts.stale ? "These facts are \(facts.ageDays) days old. Check ycombinator.com before you apply." : nil
    }

    /// The placeholder of a text field: the hint inside `<...>` in the command the CLI prints
    /// (`teyla startup yc answer sample-app building "<one plain sentence>"`), else a plain prompt.
    static func hint(for box: YCBox) -> String {
        if let open = box.command.range(of: "\"<"), let close = box.command.range(of: ">\"", range: open.upperBound..<box.command.endIndex) {
            let text = String(box.command[open.upperBound..<close.lowerBound])
            if !text.isEmpty { return text.prefix(1).uppercased() + text.dropFirst() }
        }
        return "Your answer"
    }

    /// What a box says under its question, in one line.
    static func status(_ box: YCBox) -> String {
        if box.auto {
            if box.checked { return box.evidence ?? "Checked from your records." }
            return box.need.isEmpty ? "Not ready." : "Needs: \(box.need)."
        }
        if box.checked { return "Checked. You confirmed this answer." }
        if let answer = box.answer, answer.isDraft { return "A draft, not confirmed. It checks nothing yet." }
        return box.need.isEmpty ? "Needs an answer." : "Needs: \(box.need)."
    }

    /// The button of a text box. A draft whose text is unchanged is confirmed by saving it: the owner wrote it or reads it as his.
    static func saveLabel(_ box: YCBox, draft: String) -> String {
        guard let answer = box.answer else { return "Save answer" }
        if answer.isDraft && draft == answer.text { return "Confirm" }
        return "Save answer"
    }

    /// Whether the save button is live: the text is not empty, is not too long, and differs from what is saved (or is a draft).
    static func canSave(_ box: YCBox, draft: String) -> Bool {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !box.auto, !text.isEmpty, text.count <= StartupCommands.maxAnswer else { return false }
        guard let answer = box.answer else { return true }
        return answer.isDraft || text != answer.text
    }
}

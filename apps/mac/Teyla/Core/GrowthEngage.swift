import Foundation

// Two Growth jobs the admin runs through the CLI (docs/GROWTH.md):
// - Engage: `teyla growth engage --json` lists today's posts worth a reply, each with an angle. The owner writes every
//   reply on the network himself; the app opens the post and marks it done (`teyla growth engage done <n>`).
// - Publish: `teyla growth publish <id..> --json` posts approved items to the networks the owner connected
//   (`teyla growth connect`). An item on a network that is not connected gets a packet to post by hand.
// Nothing here replies, likes, follows or sends a message. Keep this file free of UI.

/// One post worth a reply.
struct EngageRow: Decodable, Equatable, Sendable, Identifiable {
    var n: Int
    var url: String
    var author: String
    var group: String
    var why: String
    /// One angle for the reply, never the reply itself. Empty when the scan gave none worth keeping.
    var angle: String
    var source: String
    var text: String
    var done: Bool

    var id: Int { n }

    enum CodingKeys: String, CodingKey { case n, url, author, group, why, angle, source, text, done }

    init(n: Int, url: String, author: String = "", group: String = "", why: String = "", angle: String = "",
         source: String = "x", text: String = "", done: Bool = false) {
        self.n = n
        self.url = url
        self.author = author
        self.group = group
        self.why = why
        self.angle = angle
        self.source = source
        self.text = text
        self.done = done
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        n = try c.decode(Int.self, forKey: .n)
        url = try c.decode(String.self, forKey: .url)
        guard GrowthEngage.isOpenable(url) else {
            throw DecodingError.dataCorruptedError(forKey: .url, in: c, debugDescription: "not an https link")
        }
        author = c.lenient(.author, "")
        group = c.lenient(.group, "")
        why = c.lenient(.why, "")
        angle = c.lenient(.angle, "")
        source = c.lenient(.source, "")
        text = c.lenient(.text, "")
        done = c.lenient(.done, false)
    }

    var link: URL? { URL(string: url) }
}

/// `teyla growth engage --json`.
struct EngageReport: Decodable, Equatable, Sendable {
    var day: String
    var goal: Int
    var total: Int
    var done: Int
    var rows: [EngageRow]
    /// One line per source ("x", "rss"): what the scan did or why it did not run.
    var sources: [String: String]
    var notes: [String]
    var targetsExist: Bool
    var targetHandles: Int

    enum CodingKeys: String, CodingKey { case day, goal, total, done, rows, sources, notes, targets }

    private struct Targets: Decodable {
        var exists: Bool
        var x: Int
        var rss: Int

        enum CodingKeys: String, CodingKey { case exists, x, rss }

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            exists = c.lenient(.exists, false)
            x = c.lenient(.x, 0)
            rss = c.lenient(.rss, 0)
        }
    }

    init(day: String = "", goal: Int = 20, rows: [EngageRow] = [], sources: [String: String] = [:], notes: [String] = [],
         targetsExist: Bool = true, targetHandles: Int = 0) {
        self.day = day
        self.goal = goal
        self.rows = rows
        self.total = rows.count
        self.done = rows.filter(\.done).count
        self.sources = sources
        self.notes = notes
        self.targetsExist = targetsExist
        self.targetHandles = targetHandles
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        day = c.lenient(.day, "")
        goal = max(1, c.lenient(.goal, 20))
        let rows: [LossyBox<EngageRow>] = c.lenient(.rows, [])
        self.rows = rows.compactMap(\.value)
        total = c.lenient(.total, self.rows.count)
        done = c.lenient(.done, self.rows.filter(\.done).count)
        sources = c.lenient(.sources, [:])
        notes = c.lenient(.notes, [])
        let targets: Targets? = c.optional(.targets)
        targetsExist = targets?.exists ?? false
        targetHandles = (targets?.x ?? 0) + (targets?.rss ?? 0)
    }

    static func decode(_ data: Data) throws -> EngageReport {
        try JSONDecoder().decode(EngageReport.self, from: data)
    }

    /// The first row not marked done, from the top.
    var nextOpen: EngageRow? { rows.first { !$0.done } }
}

/// One line of `teyla growth publish --json`: an item on one network.
struct PublishResult: Decodable, Equatable, Sendable, Identifiable {
    var itemID: String
    var network: String
    /// published, already, packet, failed, unknown, refused.
    var status: String
    var url: String
    var message: String
    var warning: String

    var id: String { "\(itemID)|\(network)" }

    enum CodingKeys: String, CodingKey { case id, network, status, url, message, warning }

    init(itemID: String, network: String, status: String, url: String = "", message: String = "", warning: String = "") {
        self.itemID = itemID
        self.network = network
        self.status = status
        self.url = url
        self.message = message
        self.warning = warning
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        itemID = c.lenient(.id, "")
        network = c.lenient(.network, "")
        status = c.lenient(.status, "")
        url = c.lenient(.url, "")
        message = c.lenient(.message, "")
        warning = c.lenient(.warning, "")
    }

    /// The post went live, now or earlier.
    var isLive: Bool { ["published", "already"].contains(status) }
    /// Something the owner must look at: a refusal, a failure, or a post that may or may not be live.
    var needsOwner: Bool { ["failed", "unknown", "refused"].contains(status) }
    var link: URL? { GrowthEngage.isOpenable(url) ? URL(string: url) : nil }
}

struct PublishReport: Decodable, Equatable, Sendable {
    var results: [PublishResult]
    var published: Int
    var already: Int
    var packets: Int
    var failed: Int

    enum CodingKeys: String, CodingKey { case results, published, already, packets, failed }

    init(results: [PublishResult]) {
        self.results = results
        published = results.filter { $0.status == "published" }.count
        already = results.filter { $0.status == "already" }.count
        packets = results.filter { $0.status == "packet" }.count
        failed = results.filter(\.needsOwner).count
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let rows: [LossyBox<PublishResult>] = c.lenient(.results, [])
        results = rows.compactMap(\.value)
        published = c.lenient(.published, 0)
        already = c.lenient(.already, 0)
        packets = c.lenient(.packets, 0)
        failed = c.lenient(.failed, 0)
    }

    static func decode(_ data: Data) throws -> PublishReport {
        try JSONDecoder().decode(PublishReport.self, from: data)
    }

    /// One line for the notice: "2 live, 1 packet to post by hand".
    var summary: String {
        var parts: [String] = []
        if published > 0 { parts.append("\(published) published") }
        if already > 0 { parts.append("\(already) already live") }
        if packets > 0 { parts.append("\(packets) to post by hand from the packet") }
        if failed > 0 { parts.append("\(failed) need you") }
        return parts.isEmpty ? "Nothing to publish." : parts.joined(separator: ", ") + "."
    }
}

enum GrowthEngage {
    /// Rows the CLI lists in a day: 20, with room to spare.
    static let maxRow = 40
    /// Rows one `done` may mark at once.
    static let maxDone = 20
    /// Items one publish may carry from the app.
    static let maxPublish = 6

    /// The app opens only https links.
    static func isOpenable(_ text: String) -> Bool {
        guard let url = URL(string: text), url.scheme?.lowercased() == "https", let host = url.host, !host.isEmpty else { return false }
        return true
    }

    /// Read today's list. `scan` lets the CLI run its one cached scan a day; without it only the cache is read.
    static func list(scan: Bool) -> [String] {
        scan ? ["growth", "engage", "--json"] : ["growth", "engage", "--json", "--no-scan"]
    }

    static func done(_ rows: [Int]) -> [String] {
        ["growth", "engage", "done"] + rows.map(String.init)
    }

    /// One row, with the post it must still be: the CLI refuses when a new day or a refresh renumbered the list.
    static func done(_ row: EngageRow) -> [String] {
        ["growth", "engage", "done", String(row.n), "--url=\(row.url)"]
    }

    static func publish(_ ids: [String]) -> [String] {
        ["growth", "publish"] + ids + ["--json"]
    }

    /// The allow-list's answer for `growth engage ...` and `growth publish ...`; nil for any other growth command.
    static func check(_ argv: [String]) -> ToolCommands.Check? {
        guard argv.count >= 2, argv[0] == "growth" else { return nil }
        let refused = ToolCommands.Check.refused("Teyla does not run this from the app: \(ToolCommands.display(argv)).")
        switch argv[1] {
        case "engage":
            if argv == list(scan: true) || argv == list(scan: false) { return .allowed }
            guard argv.count >= 4, argv[2] == "done" else { return refused }
            var numbers = argv.dropFirst(3)
            if let last = numbers.last, last.hasPrefix("--") {
                guard numbers.count == 2, last.hasPrefix("--url="), isOpenable(String(last.dropFirst("--url=".count))) else {
                    return .refused("Mark one row with --url=<its https link>.")
                }
                numbers = numbers.dropLast()
            }
            guard numbers.count <= maxDone, numbers.allSatisfy({ text in
                text.allSatisfy(\.isASCII) && Int(text).map { (1...maxRow).contains($0) && String($0) == text } == true
            }) else { return .refused("Mark 1 to \(maxDone) rows, each a number from 1 to \(maxRow).") }
            return .allowed
        case "publish":
            guard argv.count >= 4, argv.last == "--json" else { return refused }
            let ids = argv.dropFirst(2).dropLast()
            guard ids.count <= maxPublish, ids.allSatisfy(GrowthDrafts.isItemID), Set(ids).count == ids.count else {
                return .refused("Publish 1 to \(maxPublish) approved items by id.")
            }
            return .allowed
        default:
            return nil
        }
    }

    /// What can go out: approved items on a network, not an episode, not a master idea. The oldest first, so the queue drains in order.
    static func ready(_ items: [GrowthDraft]) -> [GrowthDraft] {
        items
            .filter { ["approved", "ready"].contains($0.status) && $0.kind != "episode" && $0.platform != "master" }
            .sorted { $0.updated != $1.updated ? $0.updated < $1.updated : $0.id < $1.id }
    }
}

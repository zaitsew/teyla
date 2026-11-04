import Foundation

// What the iPhone's admin screens say. The parsers and most of the words are the Mac's (`ConsoleCompact.swift`,
// `GrowthLogic.swift`, `ConsoleMoney.swift`); this file only chooses, for each figure, what the phone has and what it
// does not. A figure the compact snapshot does not carry is a dash and "On your Mac", never a made-up number.
// No UI types here, so the tests can reach it.

/// One figure of a `StatStrip`: the label, the number (nil is a dash) and one small line.
struct ConsoleTile: Equatable, Identifiable, Sendable {
    var label: String
    var value: String?
    var detail: String
    var tone = StatTone.neutral

    var id: String { label }
}

/// A row of a list on an admin screen: a label, a figure (nil is a dash) and a note.
struct ConsoleRow: Equatable, Identifiable, Sendable {
    var title: String
    var value: String?
    var note: String

    var id: String { title }
}

enum PhoneConsole {
    /// Where a figure is when the phone does not get it.
    static let onMac = "On your Mac"

    // MARK: More

    /// The rows of the More tab, in order.
    enum MoreItem: String, CaseIterable, Identifiable, Hashable, Sendable {
        case money, operations, playbook, settings

        var id: String { rawValue }

        var title: String {
            switch self {
            case .money: return ConsoleText.money.title
            case .operations: return ConsoleText.operations.title
            case .playbook: return ConsoleText.playbook.title
            case .settings: return "Settings"
            }
        }

        var symbol: String {
            switch self {
            case .money: return ConsoleText.money.symbol
            case .operations: return ConsoleText.operations.symbol
            case .playbook: return ConsoleText.playbook.symbol
            case .settings: return "gearshape"
            }
        }
    }

    // MARK: Growth

    /// "4/6", the headline as the Mac sent it; else the slots counted from the channels; else nil.
    static func postsToday(_ growth: GrowthCompact) -> String? {
        if let text = growth.headline?.display { return text }
        return GrowthLogic.slots(growth.today).map { "\($0.posted)/\($0.target)" }
    }

    static func growthTiles(_ growth: GrowthCompact) -> [ConsoleTile] {
        let target = growth.targetPerChannel.map { "Target \($0) a day on each channel" } ?? (growth.today.isEmpty ? "No channel is set up" : onMac)
        let open = GrowthLogic.open(growth.today).count
        let waiting = growth.pipeline?.review
        return [
            ConsoleTile(label: "Posts today", value: postsToday(growth), detail: target, tone: open > 0 ? .needsYou : .saving),
            ConsoleTile(label: "Conversations", value: growth.qualifiedWeek.map(String.init),
                        detail: growth.qualifiedWeek == nil ? onMac : "Qualified, this week"),
            ConsoleTile(label: "Waiting for you", value: waiting.map(String.init),
                        detail: waiting == nil ? onMac : waiting == 0 ? "No draft to review" : "Drafts, on your Mac",
                        tone: (waiting ?? 0) > 0 ? .needsYou : .neutral),
            ConsoleTile(label: "Slots with no draft", value: growth.gaps.map(String.init),
                        detail: growth.gaps == nil ? onMac : "Today",
                        tone: (growth.gaps ?? 0) > 0 ? .needsYou : .neutral),
        ]
    }

    /// The channels, those still waiting for today's post first.
    static func channelRows(_ growth: GrowthCompact) -> [(row: GrowthToday, name: String, words: String, done: Bool)] {
        let ordered = GrowthLogic.open(growth.today) + growth.today.filter(GrowthLogic.isDone)
        let rest = growth.today.filter { row in !ordered.contains(where: { $0.id == row.id }) }
        return (ordered + rest).map {
            ($0, GrowthLogic.channelName(platform: $0.platform, language: $0.language), GrowthLogic.slotWords($0), GrowthLogic.isDone($0))
        }
    }

    /// What the queue and the last post say: the figure, or a dash with where it is.
    static func queueRows(_ growth: GrowthCompact) -> [ConsoleRow] {
        [ConsoleRow(title: "Last public post", value: GrowthLogic.sinceFigure(growth.lastPublicDays),
                    note: growth.lastPublicDays == nil ? "Nothing has gone public yet." : GrowthLogic.sinceDetail(growth.lastPublicDays)),
         ConsoleRow(title: "Drafts ready ahead", value: GrowthLogic.queueFigure(growth.queueDays).map { "\($0) days" },
                    note: growth.queueDays == nil ? onMac : "Approved drafts waiting for a slot.")]
    }

    static func pipelineRows(_ growth: GrowthCompact) -> [ConsoleRow] {
        GrowthLogic.stages(growth.pipeline).map {
            ConsoleRow(title: $0.label, value: $0.count.map(String.init), note: $0.count == nil ? onMac : $0.note)
        }
    }

    /// Why the phone shows no draft, in two short sentences.
    static let draftsStayHome = "Drafts stay on your Mac. Approve or reject them there; nothing is posted from here."

    /// The line under the waiting count: how many wait, and where.
    static func draftsLine(_ growth: GrowthCompact) -> String {
        guard let waiting = growth.pipeline?.review else { return "How many drafts wait is on your Mac." }
        if waiting == 0 { return "No draft waits for you." }
        return waiting == 1 ? "1 draft waits for you on your Mac." : "\(waiting) drafts wait for you on your Mac."
    }

    // MARK: Products

    /// The products nobody has tried to sell, among the ones this phone lists, parked ones apart. nil when the Mac did
    /// not say (an older Teyla, or a registry it could not read).
    static func notTried(_ growth: ConsoleLoad<GrowthCompact>, products: [PortfolioProduct]) -> (next: [String], parked: [String])? {
        guard let ids = growth.value?.notTried else { return nil }
        let known = products.filter { ids.contains($0.id) }
        return (known.filter { $0.health != .parked }.map(\.id), known.filter { $0.health == .parked }.map(\.id))
    }

    /// "Not tried to sell yet" for a product on the list; nil when it was tried or the Mac did not say.
    static func sellingLine(productID: String, growth: ConsoleLoad<GrowthCompact>, parked: Bool) -> String? {
        guard let ids = growth.value?.notTried, ids.contains(productID) else { return nil }
        return parked ? "Not tried to sell yet \u{00B7} parked" : "Not tried to sell yet"
    }

    // MARK: Money

    static func moneyTiles(_ money: MoneyCompact) -> [ConsoleTile] {
        let cash = MoneyLogic.usd(money.monthlyUSD ?? money.headline?.number)
        let cashDetail: String
        if cash != nil {
            cashDetail = money.unpriced.map { $0 > 0 ? "\($0) listed with no price" : "The subscriptions you list" } ?? "The subscriptions you list"
        } else {
            cashDetail = money.headline?.detail.isEmpty == false ? PlaybookLogic.plain(money.headline?.detail ?? "") : "Nothing is listed yet"
        }
        let list = MoneyLogic.usd(money.listUSD7d)
        let renewal = money.nextRenewal
        return [
            ConsoleTile(label: "Cash per month", value: cash, detail: cashDetail),
            ConsoleTile(label: "AI at list price", value: list, detail: list == nil ? onMac : "Last 7 days. Not cash."),
            ConsoleTile(label: "Next renewal", value: renewal?.days.map { MoneyLogic.inDays($0).capitalizedFirst },
                        detail: renewal.map { renewalDetail($0) } ?? "None listed",
                        tone: (renewal?.days ?? 99) <= 3 ? .needsYou : .neutral),
        ]
    }

    static func renewalDetail(_ renewal: MoneyRenewal) -> String {
        if let day = renewal.renews { return "\(renewal.name) \u{00B7} \(MoneyLogic.shortDay(day))" }
        return renewal.name
    }

    // MARK: Operations

    static func operationsTiles(_ operations: OperationsCompact) -> [ConsoleTile] {
        let failures = operations.headline?.number.map { Int($0) }
        let verdict = OperationsLogic.verdictWord(operations.machine?.verdict)
        let disk = operations.machine?.diskFreeGB
        let critical = operations.machine?.verdict?.uppercased() == "CRITICAL"
        return [
            ConsoleTile(label: "Failures", value: failures.map(String.init),
                        detail: failures == nil ? onMac : failures == 0 ? "Nothing is failing" : "Need a look",
                        tone: (failures ?? 0) > 0 ? .danger : .neutral),
            ConsoleTile(label: "Disk free", value: disk.map { "\(Int($0.rounded())) GB" },
                        detail: disk == nil ? onMac : verdict.map { "Machine \($0.lowercased())" } ?? "",
                        tone: critical ? .danger : .neutral),
            ConsoleTile(label: "Close the lid", value: lid(operations.leaveOK).value, detail: lid(operations.leaveOK).detail,
                        tone: operations.leaveOK == false ? .needsYou : .neutral),
        ]
    }

    static func lid(_ ok: Bool?) -> (value: String?, detail: String) {
        switch ok {
        case true?: return ("Yes", "Nothing running needs the lid open")
        case false?: return ("Not yet", "Something is still running")
        case nil: return (nil, onMac)
        }
    }

    /// "Needs you" or "Worth a look".
    static func severityWord(_ failure: OpsFailure) -> String { failure.needsYou ? "Needs you" : "Worth a look" }

    static func moreFailures(_ operations: OperationsCompact) -> String? {
        let n = operations.failuresNotShown
        return n > 0 ? (n == 1 ? "1 more failure is on your Mac." : "\(n) more failures are on your Mac.") : nil
    }

    // MARK: Playbook

    static func playbookTiles(_ playbook: PlaybookCompact) -> [ConsoleTile] {
        let contradictions = playbook.headline?.number.map { Int($0) }
        let models = playbook.modelsToLook
        return [
            ConsoleTile(label: "Contradictions", value: contradictions.map(String.init),
                        detail: contradictions == nil ? "Not counted yet" : contradictions == 0 ? "No rule came back" : "A rule came back",
                        tone: (contradictions ?? 0) > 0 ? .needsYou : .neutral),
            ConsoleTile(label: "Models to look at", value: models.map(String.init),
                        detail: models == nil ? onMac : "\(playbook.modelsDrift ?? 0) drift \u{00B7} \(playbook.modelsNew ?? 0) new"),
        ]
    }

    /// Wiki, intent, corrections and design decisions, in the Mac's words; a part the Mac did not count is a dash.
    static func knowledgeRows(_ playbook: PlaybookCompact) -> [ConsoleRow] {
        let k = playbook.knowledge
        let wiki = k?.wiki.value, intent = k?.intent.value, corrections = k?.corrections.value, taste = k?.taste.value
        return [
            ConsoleRow(title: "Wiki pages", value: PlaybookLogic.count(wiki?.pages), note: wiki.map(PlaybookLogic.wikiDetail) ?? onMac),
            ConsoleRow(title: "Your own words", value: PlaybookLogic.count(intent?.entries), note: intent.map(PlaybookLogic.intentDetail) ?? onMac),
            ConsoleRow(title: "Corrections", value: PlaybookLogic.count(corrections?.total), note: corrections.map(PlaybookLogic.correctionsDetail) ?? onMac),
            ConsoleRow(title: "Design decisions", value: PlaybookLogic.count(taste?.total), note: taste.map(PlaybookLogic.tasteDetail) ?? onMac),
        ]
    }

    // MARK: A line for each row of More

    /// The live figure under a row's name; "Not read yet" before the Mac sent the section.
    static func moreLine(_ item: MoreItem, console: ConsoleCompact?, status: String) -> String {
        guard let console else { return item == .settings ? status : "Not read yet" }
        switch item {
        case .money:
            guard let money = console.money.value else { return fallback(console.money) }
            return MoneyLogic.perMonth(money.monthlyUSD ?? money.headline?.number).map { "\($0) in subscriptions" } ?? "No subscription total"
        case .operations:
            guard let ops = console.operations.value else { return fallback(console.operations) }
            let failures = ops.headline?.number.map { Int($0) }
            let machine = OperationsLogic.verdictWord(ops.machine?.verdict).map { "Machine \($0.lowercased())" }
            let failing = failures.map { $0 == 0 ? "nothing failing" : "\($0) failing" }
            let parts = [machine, failing].compactMap { $0 }
            return parts.isEmpty ? "Not read yet" : parts.joined(separator: " \u{00B7} ")
        case .playbook:
            guard let book = console.playbook.value else { return fallback(console.playbook) }
            guard let n = book.headline?.number.map({ Int($0) }) else { return "Contradictions not counted yet" }
            return n == 0 ? "No rule has come back" : n == 1 ? "1 rule came back" : "\(n) rules came back"
        case .settings:
            return status
        }
    }

    private static func fallback<V: Equatable & Sendable>(_ load: ConsoleLoad<V>) -> String {
        if case .failed = load { return "Could not be read" }
        return "Not in this update"
    }
}

extension String {
    /// "in 8 days" as "In 8 days".
    var capitalizedFirst: String { prefix(1).uppercased() + dropFirst() }
}

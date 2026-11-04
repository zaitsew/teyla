import Foundation

// The Money section of `teyla console --json` (docs/CONSOLE.md): what leaves the owner's accounts.
// Two kinds of money are kept apart on purpose. Cash is the sum of the subscriptions the owner lists, with no estimate.
// List price is what the local AI sessions would cost at API prices: a subscription bills differently, so it is never
// added to cash. A price the report does not carry is nil, and the page shows a dash with the reason.

struct MoneyRenewal: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var renews: Date?
    var days: Int?
    var monthlyUSD: Double?

    var id: String { name }

    enum CodingKeys: String, CodingKey { case name, renews, days, monthlyUSD = "monthly_usd" }

    init(name: String, renews: Date? = nil, days: Int? = nil, monthlyUSD: Double? = nil) {
        self.name = name
        self.renews = renews
        self.days = days
        self.monthlyUSD = monthlyUSD
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        let day: String? = c.optional(.renews)
        renews = day.flatMap(MoneyLogic.day)
        days = c.optional(.days)
        monthlyUSD = c.optional(.monthlyUSD)
    }
}

struct MoneyForecast: Decodable, Equatable, Sendable {
    var monthlyUSD: Double?
    var priced: Int?
    var unpriced: [String]
    var byCategory: [String: Double]
    var renewals: [MoneyRenewal]

    enum CodingKeys: String, CodingKey {
        case priced, unpriced, renewals
        case monthlyUSD = "monthly_usd", byCategory = "by_category"
    }

    init(monthlyUSD: Double? = nil, priced: Int? = nil, unpriced: [String] = [], byCategory: [String: Double] = [:],
         renewals: [MoneyRenewal] = []) {
        self.monthlyUSD = monthlyUSD
        self.priced = priced
        self.unpriced = unpriced
        self.byCategory = byCategory
        self.renewals = renewals
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        monthlyUSD = c.optional(.monthlyUSD)
        priced = c.optional(.priced)
        unpriced = c.lenient(.unpriced, [])
        byCategory = c.lenient(.byCategory, [:])
        let rows: [LossyBox<MoneyRenewal>] = c.lenient(.renewals, [])
        renewals = rows.compactMap(\.value)
    }
}

struct MoneySubscription: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var monthlyUSD: Double?
    var category: String?
    var renews: Date?
    var creditsUSD: Double?
    var note: String?

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, category, renews, note
        case monthlyUSD = "monthly_usd", creditsUSD = "credits_usd"
    }

    init(name: String, monthlyUSD: Double? = nil, category: String? = nil, renews: Date? = nil, creditsUSD: Double? = nil,
         note: String? = nil) {
        self.name = name
        self.monthlyUSD = monthlyUSD
        self.category = category
        self.renews = renews
        self.creditsUSD = creditsUSD
        self.note = note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        monthlyUSD = c.optional(.monthlyUSD)
        category = c.optional(.category)
        let day: String? = c.optional(.renews)
        renews = day.flatMap(MoneyLogic.day)
        creditsUSD = c.optional(.creditsUSD)
        note = c.optional(.note)
    }
}

/// One window of local AI sessions at API list price. `billedUSD` is what a provider's admin API billed, nil without a key.
struct MoneyWindow: Decodable, Equatable, Sendable {
    var listUSD: Double?
    var subUSD: Double?
    var sessions: Int?
    var billedUSD: Double?

    enum CodingKeys: String, CodingKey {
        case sessions
        case listUSD = "list_usd", subUSD = "sub_usd", billedUSD = "billed_usd"
    }

    init(listUSD: Double? = nil, subUSD: Double? = nil, sessions: Int? = nil, billedUSD: Double? = nil) {
        self.listUSD = listUSD
        self.subUSD = subUSD
        self.sessions = sessions
        self.billedUSD = billedUSD
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        listUSD = c.optional(.listUSD)
        subUSD = c.optional(.subUSD)
        sessions = c.optional(.sessions)
        billedUSD = c.optional(.billedUSD)
    }
}

struct MoneySpend: Decodable, Equatable, Sendable {
    var label: String
    var asOf: Date?
    var days7: MoneyWindow?
    var days30: MoneyWindow?

    enum CodingKeys: String, CodingKey { case label, days7, days30, asOf = "as_of" }

    init(label: String = "", asOf: Date? = nil, days7: MoneyWindow? = nil, days30: MoneyWindow? = nil) {
        self.label = label
        self.asOf = asOf
        self.days7 = days7
        self.days30 = days30
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        label = c.lenient(.label, "")
        let seconds: Double? = c.optional(.asOf)
        asOf = seconds.map { Date(timeIntervalSince1970: $0) }
        days7 = c.optional(.days7)
        days30 = c.optional(.days30)
    }
}

/// A product, or a model, with its list-price spend in the two windows.
struct MoneyShare: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var days7USD: Double?
    var days30USD: Double?
    var sessions: Int?

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, model, sessions
        case days7USD = "days7_usd", days30USD = "days30_usd"
    }

    init(name: String, days7USD: Double? = nil, days30USD: Double? = nil, sessions: Int? = nil) {
        self.name = name
        self.days7USD = days7USD
        self.days30USD = days30USD
        self.sessions = sessions
    }

    /// A product row is keyed `name`, a model row `model`.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        if let name = try? c.decode(String.self, forKey: .name) {
            self.name = name
        } else {
            name = try c.decode(String.self, forKey: .model)
        }
        days7USD = c.optional(.days7USD)
        days30USD = c.optional(.days30USD)
        sessions = c.optional(.sessions)
    }
}

struct MoneyDay: Decodable, Equatable, Sendable, Identifiable {
    var day: Date
    var listUSD: Double?
    var subUSD: Double?

    var id: Date { day }

    enum CodingKeys: String, CodingKey { case day, listUSD = "list_usd", subUSD = "sub_usd" }

    init(day: Date, listUSD: Double? = nil, subUSD: Double? = nil) {
        self.day = day
        self.listUSD = listUSD
        self.subUSD = subUSD
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let text = try c.decode(String.self, forKey: .day)
        guard let parsed = MoneyLogic.day(text) else {
            throw DecodingError.dataCorruptedError(forKey: .day, in: c, debugDescription: "not a day")
        }
        day = parsed
        listUSD = c.optional(.listUSD)
        subUSD = c.optional(.subUSD)
    }
}

struct MoneyCredit: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var creditsUSD: Double?
    var monthlyUSD: Double?

    var id: String { name }

    enum CodingKeys: String, CodingKey { case name, creditsUSD = "credits_usd", monthlyUSD = "monthly_usd" }

    init(name: String, creditsUSD: Double? = nil, monthlyUSD: Double? = nil) {
        self.name = name
        self.creditsUSD = creditsUSD
        self.monthlyUSD = monthlyUSD
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        creditsUSD = c.optional(.creditsUSD)
        monthlyUSD = c.optional(.monthlyUSD)
    }
}

/// What one provider billed in 30 days, or why the number is not known (no admin key).
struct MoneyProvider: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var billedUSD30: Double?
    var reason: String?

    var id: String { name }

    enum CodingKeys: String, CodingKey { case reason, billed = "billed_usd_30d" }

    init(name: String, billedUSD30: Double? = nil, reason: String? = nil) {
        self.name = name
        self.billedUSD30 = billedUSD30
        self.reason = reason
    }

    /// `name` is the key of the object this was read from; `MoneyReport` fills it in.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = ""
        billedUSD30 = c.optional(.billed)
        reason = c.optional(.reason)
    }
}

struct MoneyCloud: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var kind: String?
    var monthlyUSD: Double?
    var meteredUSD: Double?
    var detail: String?

    var id: String { name }

    enum CodingKeys: String, CodingKey {
        case name, kind, detail
        case monthlyUSD = "monthly_usd", meteredUSD = "metered_usd"
    }

    init(name: String, kind: String? = nil, monthlyUSD: Double? = nil, meteredUSD: Double? = nil, detail: String? = nil) {
        self.name = name
        self.kind = kind
        self.monthlyUSD = monthlyUSD
        self.meteredUSD = meteredUSD
        self.detail = detail
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        kind = c.optional(.kind)
        monthlyUSD = c.optional(.monthlyUSD)
        meteredUSD = c.optional(.meteredUSD)
        detail = c.optional(.detail)
    }
}

struct MoneyActionsAccount: Decodable, Equatable, Sendable, Identifiable {
    var account: String
    var plan: String?
    var minutes: Double?
    var included: Double?
    var share: Double?
    var paidUSD: Double?
    var topRepos: [String]

    var id: String { account }

    enum CodingKeys: String, CodingKey {
        case account, plan, minutes, included, share
        case paidUSD = "paid_usd", topRepos = "top_repos"
    }

    init(account: String, plan: String? = nil, minutes: Double? = nil, included: Double? = nil, share: Double? = nil,
         paidUSD: Double? = nil, topRepos: [String] = []) {
        self.account = account
        self.plan = plan
        self.minutes = minutes
        self.included = included
        self.share = share
        self.paidUSD = paidUSD
        self.topRepos = topRepos
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        account = try c.decode(String.self, forKey: .account)
        plan = c.optional(.plan)
        minutes = c.optional(.minutes)
        included = c.optional(.included)
        share = c.optional(.share)
        paidUSD = c.optional(.paidUSD)
        topRepos = c.lenient(.topRepos, [])
    }
}

struct MoneyActions: Decodable, Equatable, Sendable {
    var minutesUsed: Double?
    var minutesIncluded: Double?
    var paidUSD: Double?
    var accounts: [MoneyActionsAccount]

    enum CodingKeys: String, CodingKey {
        case accounts
        case minutesUsed = "minutes_used", minutesIncluded = "minutes_included", paidUSD = "paid_usd"
    }

    init(minutesUsed: Double? = nil, minutesIncluded: Double? = nil, paidUSD: Double? = nil, accounts: [MoneyActionsAccount] = []) {
        self.minutesUsed = minutesUsed
        self.minutesIncluded = minutesIncluded
        self.paidUSD = paidUSD
        self.accounts = accounts
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        minutesUsed = c.optional(.minutesUsed)
        minutesIncluded = c.optional(.minutesIncluded)
        paidUSD = c.optional(.paidUSD)
        let rows: [LossyBox<MoneyActionsAccount>] = c.lenient(.accounts, [])
        accounts = rows.compactMap(\.value)
    }
}

struct MoneyReport: Decodable, Equatable, Sendable, ConsoleSectionData {
    var headline: ConsoleHeadline?
    var forecast: MoneyForecast?
    var subscriptions: [MoneySubscription]
    var spend: MoneySpend?
    var byProduct: [MoneyShare]
    var byModel: [MoneyShare]
    var byDay: [MoneyDay]
    var credits: [MoneyCredit]
    var creditsTotalUSD: Double?
    var providers: [MoneyProvider]
    var cloud: [MoneyCloud]
    var actions: MoneyActions?
    /// Where the subscriptions are listed, for the line that says how to change a price.
    var file: String?

    enum CodingKeys: String, CodingKey {
        case headline, forecast, subscriptions, spend, credits, providers, cloud, actions, file
        case byProduct = "by_product", byModel = "by_model", byDay = "by_day", creditsTotalUSD = "credits_total_usd"
    }

    init(headline: ConsoleHeadline? = nil, forecast: MoneyForecast? = nil, subscriptions: [MoneySubscription] = [],
         spend: MoneySpend? = nil, byProduct: [MoneyShare] = [], byModel: [MoneyShare] = [], byDay: [MoneyDay] = [],
         credits: [MoneyCredit] = [], creditsTotalUSD: Double? = nil, providers: [MoneyProvider] = [],
         cloud: [MoneyCloud] = [], actions: MoneyActions? = nil, file: String? = nil) {
        self.headline = headline
        self.forecast = forecast
        self.subscriptions = subscriptions
        self.spend = spend
        self.byProduct = byProduct
        self.byModel = byModel
        self.byDay = byDay
        self.credits = credits
        self.creditsTotalUSD = creditsTotalUSD
        self.providers = providers
        self.cloud = cloud
        self.actions = actions
        self.file = file
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
        forecast = c.optional(.forecast)
        let subs: [LossyBox<MoneySubscription>] = c.lenient(.subscriptions, [])
        subscriptions = subs.compactMap(\.value)
        spend = c.optional(.spend)
        let products: [LossyBox<MoneyShare>] = c.lenient(.byProduct, [])
        byProduct = products.compactMap(\.value)
        let models: [LossyBox<MoneyShare>] = c.lenient(.byModel, [])
        byModel = models.compactMap(\.value)
        let days: [LossyBox<MoneyDay>] = c.lenient(.byDay, [])
        byDay = days.compactMap(\.value).sorted { $0.day < $1.day }
        let credit: [LossyBox<MoneyCredit>] = c.lenient(.credits, [])
        credits = credit.compactMap(\.value)
        creditsTotalUSD = c.optional(.creditsTotalUSD)
        // The providers come as an object keyed by name; a provider that cannot be read is skipped.
        let raw: [String: LossyBox<MoneyProvider>] = c.lenient(.providers, [:])
        providers = raw.compactMap { key, box in box.value.map { MoneyProvider(name: key, billedUSD30: $0.billedUSD30, reason: $0.reason) } }
            .sorted { $0.name < $1.name }
        let clouds: [LossyBox<MoneyCloud>] = c.lenient(.cloud, [])
        cloud = clouds.compactMap(\.value)
        actions = c.optional(.actions)
        file = c.optional(.file)
    }
}

// MARK: What the page says

enum MoneyLogic {
    /// "2026-11-12" as a day in UTC, so the same day reads the same wherever the app runs.
    static func day(_ text: String) -> Date? {
        let parts = text.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        return calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2]))
    }

    /// "12 Nov", for a renewal or a day on a line.
    static func shortDay(_ date: Date) -> String {
        var style = Date.FormatStyle().day().month(.abbreviated)
        style.locale = Locale(identifier: "en_GB")
        style.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        return date.formatted(style)
    }

    /// Dollars: whole above 100 and for a round amount, two decimals otherwise, a dash (nil) for no figure. Money is never rounded to zero:
    /// a positive amount under one cent reads "less than $0.01".
    static func usd(_ value: Double?) -> String? {
        guard let value else { return nil }
        if value > 0, value < 0.005 { return "less than $0.01" }
        let sign = value < 0 ? "-" : ""
        let amount = abs(value)
        if amount >= 100 || amount == amount.rounded() { return sign + "$" + amount.formatted(.number.precision(.fractionLength(0)).locale(Locale(identifier: "en_US"))) }
        return sign + "$" + amount.formatted(.number.precision(.fractionLength(2)).locale(Locale(identifier: "en_US")))
    }

    /// "$200 a month", or nil.
    static func perMonth(_ value: Double?) -> String? { usd(value).map { "\($0) a month" } }

    /// The cash figure and why it is what it is: from the forecast, never from list price.
    static func cash(_ report: MoneyReport) -> (value: String?, detail: String) {
        let detail = report.headline?.detail ?? ""
        if let monthly = report.forecast?.monthlyUSD { return (usd(monthly), detail.isEmpty ? "The subscriptions you list." : detail) }
        return (nil, detail.isEmpty ? "The report has no subscription total." : detail)
    }

    /// The subscriptions by price, the dearest first, the unpriced last (by name), so no row hides behind a dash.
    static func subscriptionsInOrder(_ rows: [MoneySubscription]) -> [MoneySubscription] {
        rows.sorted {
            switch ($0.monthlyUSD, $1.monthlyUSD) {
            case let (a?, b?): return a != b ? a > b : $0.name < $1.name
            case (_?, nil): return true
            case (nil, _?): return false
            case (nil, nil): return $0.name < $1.name
            }
        }
    }

    /// A subscription row's price, or why there is none.
    static func priceText(_ row: MoneySubscription) -> (text: String, known: Bool) {
        if let text = perMonth(row.monthlyUSD) { return (text, true) }
        let why = (row.note?.isEmpty ?? true) ? "no price listed" : row.note ?? ""
        return (why, false)
    }

    /// "AI · renews 21 Nov · billed yearly", whatever of it is known.
    static func subscriptionDetail(_ row: MoneySubscription) -> String {
        var parts: [String] = []
        if let category = row.category, !category.isEmpty { parts.append(category.capitalized == "Ai" ? "AI" : category.capitalized) }
        if let renews = row.renews { parts.append("renews \(shortDay(renews))") }
        if row.monthlyUSD != nil, let note = row.note, !note.isEmpty { parts.append(note) }
        return parts.joined(separator: " · ")
    }

    /// The next renewal: the soonest of those with a day count, never a past one.
    static func nextRenewal(_ forecast: MoneyForecast?) -> MoneyRenewal? {
        forecast?.renewals.filter { ($0.days ?? -1) >= 0 }.min { ($0.days ?? .max) < ($1.days ?? .max) }
    }

    /// "in 8 days", "today", "tomorrow".
    static func inDays(_ days: Int) -> String {
        switch days {
        case 0: return "today"
        case 1: return "tomorrow"
        default: return "in \(days) days"
        }
    }

    /// The list-price window the owner picked.
    enum Window: String, CaseIterable, Sendable {
        case week, month

        var label: String { self == .week ? "7 days" : "30 days" }
    }

    static func window(_ spend: MoneySpend?, _ window: Window) -> MoneyWindow? {
        window == .week ? spend?.days7 : spend?.days30
    }

    /// A product or model's amount in the window.
    static func amount(_ share: MoneyShare, _ window: Window) -> Double? {
        window == .week ? share.days7USD : share.days30USD
    }

    /// Rows by amount in the window, the largest first; a row with no amount goes last.
    static func shares(_ rows: [MoneyShare], window: Window) -> [MoneyShare] {
        rows.sorted {
            switch (amount($0, window), amount($1, window)) {
            case let (a?, b?): return a != b ? a > b : $0.name < $1.name
            case (_?, nil): return true
            case (nil, _?): return false
            case (nil, nil): return $0.name < $1.name
            }
        }
    }

    /// A row's share of the largest row, 0...1, for a bar. Nil without an amount; the biggest row fills the bar.
    static func fraction(_ share: MoneyShare, of rows: [MoneyShare], window: Window) -> Double? {
        guard let value = amount(share, window), let top = rows.compactMap({ amount($0, window) }).max(), top > 0 else { return nil }
        return min(1, max(0, value / top))
    }

    /// The last days as bar heights 0...1, scaled to the largest, for the list-price chart. Fewer than two days: none.
    static func dayHeights(_ days: [MoneyDay], last count: Int) -> [Double] {
        let recent = Array(days.suffix(count))
        guard recent.count >= 2, let top = recent.compactMap(\.listUSD).max(), top > 0 else { return [] }
        return recent.map { ($0.listUSD ?? 0) / top }
    }

    /// "Peak 365 on 30 Oct": what the bars show, in words.
    static func dayCaption(_ days: [MoneyDay], last count: Int) -> String {
        let recent = Array(days.suffix(count))
        guard recent.count >= 2, let peak = recent.max(by: { ($0.listUSD ?? 0) < ($1.listUSD ?? 0) }), let value = usd(peak.listUSD) else {
            return "Not enough days for a chart yet."
        }
        return "Last \(recent.count) days at list price. Highest: \(value) on \(shortDay(peak.day))."
    }

    /// What a provider billed, or the reason it did not say.
    static func providerLine(_ provider: MoneyProvider) -> (value: String?, why: String) {
        if let billed = provider.billedUSD30 { return (usd(billed), "billed in the last 30 days") }
        let why = provider.reason ?? ""
        return (nil, why.isEmpty ? "no billing figure from this provider" : why)
    }

    /// The provider's name as people write it.
    static func providerName(_ key: String) -> String {
        switch key.lowercased() {
        case "openai": return "OpenAI"
        case "anthropic": return "Anthropic"
        default: return key.capitalized
        }
    }

    /// "25 of 2,000 minutes", or the part that is known.
    static func minutesLine(_ account: MoneyActionsAccount) -> String {
        let used = account.minutes.map { $0.formatted(.number.precision(.fractionLength(0)).locale(Locale(identifier: "en_US"))) }
        let included = account.included.map { $0.formatted(.number.precision(.fractionLength(0)).locale(Locale(identifier: "en_US"))) }
        switch (used, included) {
        case let (u?, i?): return "\(u) of \(i) minutes"
        case let (u?, nil): return "\(u) minutes"
        default: return "no minutes figure"
        }
    }

    /// A cloud row's price: the listed monthly price, else what was metered, else why there is none.
    static func cloudPrice(_ row: MoneyCloud) -> (text: String, known: Bool) {
        if let monthly = perMonth(row.monthlyUSD) { return (monthly, true) }
        if let metered = row.meteredUSD { return (metered == 0 ? "$0 so far" : "\(usd(metered) ?? "") so far", true) }
        return ("no price", false)
    }

    /// The listed file as the owner would type it: the home folder shown as ~.
    static func fileLine(_ path: String?) -> String? {
        guard let path, !path.isEmpty else { return nil }
        return NSString(string: path).abbreviatingWithTildeInPath
    }

    /// Rows shown before "Show all" on the product and model lists.
    static let foldAt = 6

    /// "ai" as "AI", "cloud" as "Cloud".
    static func categoryName(_ key: String) -> String { key.lowercased() == "ai" ? "AI" : key.capitalized }

    /// What the list-price section is, in the report's own words when it has them.
    static func spendNote(_ spend: MoneySpend?) -> String {
        let label = spend?.label ?? ""
        if label.isEmpty { return "Not cash. What local AI sessions would cost at API prices." }
        return label.lowercased().contains("not cash") ? label : label + " Not cash."
    }

    /// Whole minutes: "47".
    static func minutes(_ value: Double?) -> String? {
        value.map { $0.formatted(.number.precision(.fractionLength(0)).locale(Locale(identifier: "en_US"))) }
    }

    /// "of 5,000 included · $0.00 paid", whatever of it is known.
    static func actionsDetail(_ actions: MoneyActions?) -> String {
        guard let actions else { return "The report has no Actions figures." }
        var parts: [String] = []
        if let included = minutes(actions.minutesIncluded) { parts.append("of \(included) included") }
        if let paid = usd(actions.paidUSD) { parts.append("\(paid) paid") }
        return parts.isEmpty ? "The report gave no allowance." : parts.joined(separator: " · ")
    }

    /// Cloud rows that no other row already says: not a subscription listed above, not a GitHub Actions account
    /// (those have their own rows with minutes).
    static func cloudRows(_ rows: [MoneyCloud], subscriptions: [MoneySubscription], actions: MoneyActions?) -> [MoneyCloud] {
        let listed = Set(subscriptions.map { $0.name.lowercased() })
        let hasAccounts = !(actions?.accounts.isEmpty ?? true)
        return rows.filter { row in
            !listed.contains(row.name.lowercased()) && !(hasAccounts && row.name.hasPrefix("GitHub Actions"))
        }
    }

    /// "25 of 2,000 minutes · free plan · most use: dremo, qupa".
    static func accountDetail(_ account: MoneyActionsAccount) -> String {
        var parts = [minutesLine(account)]
        if let plan = account.plan, !plan.isEmpty { parts.append("\(plan) plan") }
        if !account.topRepos.isEmpty { parts.append("most use: \(account.topRepos.prefix(3).joined(separator: ", "))") }
        return parts.joined(separator: " · ")
    }

    /// "$0.00 paid", or a dash.
    static func paidText(_ value: Double?) -> String { usd(value).map { "\($0) paid" } ?? Format.dash }
}

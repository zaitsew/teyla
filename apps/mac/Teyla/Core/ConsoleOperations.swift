import Foundation

// The Operations section of `teyla console --json` (docs/CONSOLE.md): can the lid close, how the machine is, what failed,
// which scheduled tasks are late, which harnesses are wired, whether AGENTS.md copies match, what security last found.
// Decoding is lenient: a key that is missing, null or of another type leaves a nil or an empty list, and the page shows
// a dash with the reason. A figure the report does not carry is never turned into a zero.

/// Can the Mac be left alone: `ok` is nil when the report does not say.
struct OpsLeave: Decodable, Equatable, Sendable {
    var ok: Bool?
    var blockers: [String]

    enum CodingKeys: String, CodingKey { case ok, blockers }

    init(ok: Bool? = nil, blockers: [String] = []) {
        self.ok = ok
        self.blockers = blockers
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = c.optional(.ok)
        blockers = c.lenient(.blockers, [])
    }
}

/// One reading of a series: when and how much.
struct OpsPoint: Decodable, Equatable, Sendable {
    var time: Date
    var value: Double

    init(time: Date, value: Double) {
        self.time = time
        self.value = value
    }

    /// The report sends `[epoch seconds, value]`.
    init(from decoder: Decoder) throws {
        var c = try decoder.unkeyedContainer()
        time = Date(timeIntervalSince1970: try c.decode(Double.self))
        value = try c.decode(Double.self)
    }
}

struct OpsApp: Decodable, Equatable, Sendable {
    var name: String
    var gb: Double?

    enum CodingKeys: String, CodingKey { case name, gb }

    init(name: String, gb: Double? = nil) {
        self.name = name
        self.gb = gb
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        gb = c.optional(.gb)
    }
}

struct OpsMachine: Decodable, Equatable, Sendable {
    var verdict: String?
    var reason: String
    var ramGB: Double?
    var swapUsedGB: Double?
    var swapTotalGB: Double?
    var compressorGB: Double?
    var diskFreeGB: Double?
    var diskTotalGB: Double?
    var cpuLoad: Double?
    var cores: Int?
    var sims: Int?
    var builds: Int?
    var lanes: Int?
    /// Running agent sessions by harness.
    var agents: [String: Int]
    var top: [OpsApp]
    var diskSeries: [OpsPoint]
    var swapSeries: [OpsPoint]

    enum CodingKeys: String, CodingKey {
        case verdict, reason, cores, sims, builds, lanes, agents, top, series
        case ramGB = "ram_gb", swapUsedGB = "swap_used_gb", swapTotalGB = "swap_total_gb", compressorGB = "compressor_gb"
        case diskFreeGB = "disk_free_gb", diskTotalGB = "disk_total_gb", cpuLoad = "cpu_load"
    }

    init(verdict: String? = nil, reason: String = "", ramGB: Double? = nil, swapUsedGB: Double? = nil,
         swapTotalGB: Double? = nil, compressorGB: Double? = nil, diskFreeGB: Double? = nil, diskTotalGB: Double? = nil,
         cpuLoad: Double? = nil, cores: Int? = nil, sims: Int? = nil, builds: Int? = nil, lanes: Int? = nil,
         agents: [String: Int] = [:], top: [OpsApp] = [], diskSeries: [OpsPoint] = [], swapSeries: [OpsPoint] = []) {
        self.verdict = verdict
        self.reason = reason
        self.ramGB = ramGB
        self.swapUsedGB = swapUsedGB
        self.swapTotalGB = swapTotalGB
        self.compressorGB = compressorGB
        self.diskFreeGB = diskFreeGB
        self.diskTotalGB = diskTotalGB
        self.cpuLoad = cpuLoad
        self.cores = cores
        self.sims = sims
        self.builds = builds
        self.lanes = lanes
        self.agents = agents
        self.top = top
        self.diskSeries = diskSeries
        self.swapSeries = swapSeries
    }

    private struct Series: Decodable {
        var disk: [LossyBox<OpsPoint>]?
        var swap: [LossyBox<OpsPoint>]?
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        verdict = c.optional(.verdict)
        reason = c.lenient(.reason, "")
        ramGB = c.optional(.ramGB)
        swapUsedGB = c.optional(.swapUsedGB)
        swapTotalGB = c.optional(.swapTotalGB)
        compressorGB = c.optional(.compressorGB)
        diskFreeGB = c.optional(.diskFreeGB)
        diskTotalGB = c.optional(.diskTotalGB)
        cpuLoad = c.optional(.cpuLoad)
        cores = c.optional(.cores)
        sims = c.optional(.sims)
        builds = c.optional(.builds)
        lanes = c.optional(.lanes)
        agents = c.lenient(.agents, [:])
        let apps: [LossyBox<OpsApp>] = c.lenient(.top, [])
        top = apps.compactMap(\.value)
        let series: Series? = c.optional(.series)
        diskSeries = (series?.disk ?? []).compactMap(\.value).sorted { $0.time < $1.time }
        swapSeries = (series?.swap ?? []).compactMap(\.value).sorted { $0.time < $1.time }
    }
}

/// One thing that failed. `action` is the command the report names, a line of text; the app runs it only when the
/// Attention report holds the same item with an action on the allow-list.
struct OpsFailure: Decodable, Equatable, Sendable, Identifiable {
    var title: String
    var detail: String
    /// `act` needs the owner, `info` is worth a look. Anything else reads as `act`.
    var severity: String
    var product: String
    var kind: String
    var action: String?

    var id: String { kind + "|" + title }
    var needsYou: Bool { severity != "info" }

    enum CodingKeys: String, CodingKey { case title, detail, severity, product, kind, action }

    init(title: String, detail: String = "", severity: String = "act", product: String = "", kind: String = "unknown",
         action: String? = nil) {
        self.title = title
        self.detail = detail
        self.severity = severity
        self.product = product
        self.kind = kind
        self.action = action
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = try c.decode(String.self, forKey: .title)
        detail = c.lenient(.detail, "")
        severity = c.lenient(.severity, "act")
        product = c.lenient(.product, "")
        kind = c.lenient(.kind, "unknown")
        let line: String? = c.optional(.action)
        action = (line?.isEmpty ?? true) ? nil : line
    }
}

struct OpsScheduleRow: Decodable, Equatable, Sendable, Identifiable {
    var source: String
    var name: String
    var state: String
    var cadence: String?
    var lastRun: Date?
    var note: String?

    var id: String { source + "|" + name }

    enum CodingKeys: String, CodingKey { case source, name, state, cadence, note, lastRun = "last_run" }

    init(source: String = "", name: String, state: String, cadence: String? = nil, lastRun: Date? = nil, note: String? = nil) {
        self.source = source
        self.name = name
        self.state = state
        self.cadence = cadence
        self.lastRun = lastRun
        self.note = note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        source = c.lenient(.source, "")
        state = c.lenient(.state, "UNKNOWN")
        cadence = c.optional(.cadence)
        note = c.optional(.note)
        let when: String? = c.optional(.lastRun)
        lastRun = when.flatMap(ISODate.parse)
    }
}

struct OpsSchedules: Decodable, Equatable, Sendable {
    var counts: [String: Int]
    var rows: [OpsScheduleRow]

    enum CodingKeys: String, CodingKey { case counts, rows }

    init(counts: [String: Int] = [:], rows: [OpsScheduleRow] = []) {
        self.counts = counts
        self.rows = rows
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        counts = c.lenient(.counts, [:])
        let boxes: [LossyBox<OpsScheduleRow>] = c.lenient(.rows, [])
        rows = boxes.compactMap(\.value)
    }
}

struct OpsHarness: Decodable, Equatable, Sendable, Identifiable {
    var name: String
    var installed: Bool
    var version: String?
    /// `synced`, `not wired` or another word the command uses; nil when the harness is not installed.
    var policy: String?
    var note: String?

    var id: String { name }

    enum CodingKeys: String, CodingKey { case name, installed, version, policy, note }

    init(name: String, installed: Bool = true, version: String? = nil, policy: String? = nil, note: String? = nil) {
        self.name = name
        self.installed = installed
        self.version = version
        self.policy = policy
        self.note = note
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        name = try c.decode(String.self, forKey: .name)
        installed = c.lenient(.installed, false)
        version = c.optional(.version)
        policy = c.optional(.policy)
        note = c.optional(.note)
    }
}

/// One copy of AGENTS.md that differs from the policy, and the command that fixes it.
struct OpsDrift: Decodable, Equatable, Sendable, Identifiable {
    var harness: String
    var why: String
    var fix: String?

    var id: String { harness + "|" + why }

    enum CodingKeys: String, CodingKey { case harness, why, fix }

    init(harness: String, why: String, fix: String? = nil) {
        self.harness = harness
        self.why = why
        self.fix = fix
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        harness = c.lenient(.harness, "")
        why = c.lenient(.why, "A copy differs from the policy.")
        fix = c.optional(.fix)
    }
}

struct OpsPolicyRepos: Decodable, Equatable, Sendable {
    var ok: Int?
    var differ: Int?
    var missing: Int?
    var none: Int?
    var toFix: [String]

    enum CodingKeys: String, CodingKey { case ok, differ, missing, none, toFix = "to_fix" }

    init(ok: Int? = nil, differ: Int? = nil, missing: Int? = nil, none: Int? = nil, toFix: [String] = []) {
        self.ok = ok
        self.differ = differ
        self.missing = missing
        self.none = none
        self.toFix = toFix
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        ok = c.optional(.ok)
        differ = c.optional(.differ)
        missing = c.optional(.missing)
        none = c.optional(.none)
        toFix = c.lenient(.toFix, [])
    }
}

struct OpsPolicySync: Decodable, Equatable, Sendable {
    /// `ok`, `drift` or another word; nil when the report does not say.
    var status: String?
    var drift: [OpsDrift]
    var inbox: Int?
    var repos: OpsPolicyRepos?
    var lastSync: Date?

    enum CodingKeys: String, CodingKey { case status, drift, inbox, repos, lastSync = "last_sync" }

    init(status: String? = nil, drift: [OpsDrift] = [], inbox: Int? = nil, repos: OpsPolicyRepos? = nil, lastSync: Date? = nil) {
        self.status = status
        self.drift = drift
        self.inbox = inbox
        self.repos = repos
        self.lastSync = lastSync
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        status = c.optional(.status)
        let rows: [LossyBox<OpsDrift>] = c.lenient(.drift, [])
        drift = rows.compactMap(\.value)
        inbox = c.optional(.inbox)
        repos = c.optional(.repos)
        let when: String? = c.optional(.lastSync)
        lastSync = when.flatMap(ISODate.parse)
    }
}

struct OpsSecurity: Decodable, Equatable, Sendable {
    var shieldIssues: Int?
    var leakFindings: Int?
    var depsVulns: Int?
    var unreviewedPRs: Int?
    var leakAsOf: Date?
    var depsAsOf: Date?
    var reviewsAsOf: Date?
    var notes: [String]

    enum CodingKeys: String, CodingKey {
        case notes
        case shieldIssues = "shield_issues", leakFindings = "leak_findings", depsVulns = "deps_vulns"
        case unreviewedPRs = "unreviewed_prs", asOf = "as_of"
    }

    private struct AsOf: Decodable {
        var leak: String?
        var deps: String?
        var reviews: String?
    }

    init(shieldIssues: Int? = nil, leakFindings: Int? = nil, depsVulns: Int? = nil, unreviewedPRs: Int? = nil,
         leakAsOf: Date? = nil, depsAsOf: Date? = nil, reviewsAsOf: Date? = nil, notes: [String] = []) {
        self.shieldIssues = shieldIssues
        self.leakFindings = leakFindings
        self.depsVulns = depsVulns
        self.unreviewedPRs = unreviewedPRs
        self.leakAsOf = leakAsOf
        self.depsAsOf = depsAsOf
        self.reviewsAsOf = reviewsAsOf
        self.notes = notes
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        shieldIssues = c.optional(.shieldIssues)
        leakFindings = c.optional(.leakFindings)
        depsVulns = c.optional(.depsVulns)
        unreviewedPRs = c.optional(.unreviewedPRs)
        let asOf: AsOf? = c.optional(.asOf)
        leakAsOf = asOf?.leak.flatMap(ISODate.parse)
        depsAsOf = asOf?.deps.flatMap(ISODate.parse)
        reviewsAsOf = asOf?.reviews.flatMap(ISODate.parse)
        notes = c.lenient(.notes, [])
    }
}

struct OperationsReport: Decodable, Equatable, Sendable, ConsoleSectionData {
    var headline: ConsoleHeadline?
    var leave: OpsLeave?
    var machine: OpsMachine?
    var failures: [OpsFailure]
    /// False when the report carried no failure list at all (null or missing): "nothing is failing" must not be said then.
    var failuresRead: Bool
    var schedules: OpsSchedules?
    var harnesses: [OpsHarness]
    var policySync: OpsPolicySync?
    var security: OpsSecurity?

    enum CodingKeys: String, CodingKey {
        case headline, leave, machine, failures, schedules, harnesses, security
        case policySync = "policy_sync"
    }

    init(headline: ConsoleHeadline? = nil, leave: OpsLeave? = nil, machine: OpsMachine? = nil, failures: [OpsFailure] = [],
         failuresRead: Bool = true, schedules: OpsSchedules? = nil, harnesses: [OpsHarness] = [], policySync: OpsPolicySync? = nil,
         security: OpsSecurity? = nil) {
        self.headline = headline
        self.leave = leave
        self.machine = machine
        self.failures = failures
        self.failuresRead = failuresRead
        self.schedules = schedules
        self.harnesses = harnesses
        self.policySync = policySync
        self.security = security
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
        leave = c.optional(.leave)
        machine = c.optional(.machine)
        let failureRows: [LossyBox<OpsFailure>]? = c.optional(.failures)
        failures = (failureRows ?? []).compactMap(\.value)
        failuresRead = failureRows != nil
        schedules = c.optional(.schedules)
        let harnessRows: [LossyBox<OpsHarness>] = c.lenient(.harnesses, [])
        harnesses = harnessRows.compactMap(\.value)
        policySync = c.optional(.policySync)
        security = c.optional(.security)
    }
}

// MARK: What the page says

/// The words and the order of the Operations page, kept out of the views so tests read them.
enum OperationsLogic {
    /// "Safe to close the lid", "Not yet", or a dash-style line when the report does not say.
    static func lidFigure(_ leave: OpsLeave?) -> (value: String?, detail: String, needsYou: Bool) {
        guard let ok = leave?.ok else { return (nil, "The report does not say whether the Mac can be left.", false) }
        if ok { return ("Yes", "Nothing is running that the lid would stop.", false) }
        let n = leave?.blockers.count ?? 0
        return ("Not yet", n == 1 ? "1 thing is still running." : "\(n) things are still running.", true)
    }

    /// "34.4 GB", one decimal, or a dash.
    static func gb(_ value: Double?) -> String? {
        guard let value else { return nil }
        return String(format: "%.1f GB", value)
    }

    /// Disk free as a share of the disk: "7% of 460 GB", or why there is none.
    static func diskDetail(_ machine: OpsMachine?) -> String {
        guard let free = machine?.diskFreeGB, let total = machine?.diskTotalGB, total > 0 else {
            return "The report has no disk figure."
        }
        return "\(Int((free / total * 100).rounded()))% of \(Int(total.rounded())) GB"
    }

    static func swapDetail(_ machine: OpsMachine?) -> String {
        guard let total = machine?.swapTotalGB, total > 0 else { return "The report has no swap size." }
        return "of \(gb(total) ?? Format.dash) swap file"
    }

    /// The machine's verdict as a word for people. An unknown word is shown as it is.
    static func verdictWord(_ verdict: String?) -> String? {
        guard let verdict, !verdict.isEmpty else { return nil }
        switch verdict.uppercased() {
        case "OK": return "Fine"
        case "BUSY": return "Busy"
        case "CRITICAL": return "Critical"
        default: return verdict.capitalized
        }
    }

    /// The word a schedule state is shown as.
    static func stateWord(_ state: String) -> String {
        switch state.uppercased() {
        case "OK": return "On time"
        case "STALE": return "Late"
        case "UNREGISTERED": return "Not loaded"
        case "VANISHED": return "Gone"
        case "NEVER RAN": return "Never ran"
        case "UNKNOWN": return "Unknown"
        case "DISABLED": return "Off"
        case "DONE": return "Done"
        default: return state.capitalized
        }
    }

    /// How urgent a state is: lower comes first. A state the app does not know sorts with the unknown ones, before the calm ones.
    static func stateRank(_ state: String) -> Int {
        switch state.uppercased() {
        case "STALE": return 0
        case "VANISHED": return 1
        case "UNREGISTERED": return 2
        case "NEVER RAN": return 3
        case "OK": return 6
        case "DONE": return 7
        case "DISABLED": return 8
        default: return 4
        }
    }

    /// True for a state that is late, gone or not loaded: a row the owner may have to act on.
    static func needsAction(_ state: String) -> Bool { stateRank(state) <= 3 }

    /// Worst first, then by name, so the list does not shuffle between reads.
    static func schedulesWorstFirst(_ rows: [OpsScheduleRow]) -> [OpsScheduleRow] {
        rows.sorted {
            let (a, b) = (stateRank($0.state), stateRank($1.state))
            return a != b ? a < b : $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
        }
    }

    /// The rows shown at once (late, gone, not loaded, never ran) and the rest behind "Show all". A task whose state
    /// the command could not read is in the rest: dozens of those would hide the ones that are late.
    static func scheduleSplit(_ rows: [OpsScheduleRow]) -> (look: [OpsScheduleRow], rest: [OpsScheduleRow]) {
        let sorted = schedulesWorstFirst(rows)
        return (sorted.filter { needsAction($0.state) }, sorted.filter { !needsAction($0.state) })
    }

    /// "4 late or missing · 11 unknown", from the rows; nothing when the report has no rows.
    static func scheduleNote(_ rows: [OpsScheduleRow]) -> String {
        guard !rows.isEmpty else { return "" }
        let late = rows.filter { needsAction($0.state) }.count
        let unknown = rows.filter { stateRank($0.state) == 4 }.count
        var parts = [late == 0 ? "None late" : "\(late) late or missing"]
        if unknown > 0 { parts.append("\(unknown) not readable") }
        return parts.joined(separator: " · ")
    }

    /// "Daily 07:30 · last run 2 d ago", whatever of it is known.
    static func scheduleDetail(_ row: OpsScheduleRow, now: Date) -> String {
        var parts: [String] = []
        if let cadence = row.cadence, !cadence.isEmpty { parts.append("every \(cadence)") }
        if let last = row.lastRun { parts.append("last run \(Format.ago(seconds: now.timeIntervalSince(last)))") }
        else if let note = row.note, !note.isEmpty { parts.append(note) }
        else { parts.append("no run on record") }
        return parts.joined(separator: " · ")
    }

    /// The failures that need the owner first, the calm ones after; the order inside a group is the report's.
    static func failuresInOrder(_ failures: [OpsFailure]) -> (act: [OpsFailure], info: [OpsFailure]) {
        (failures.filter(\.needsYou), failures.filter { !$0.needsYou })
    }

    /// "synced", "not wired" and the rest as short words; an uninstalled harness says so.
    static func policyWord(_ harness: OpsHarness) -> String {
        guard harness.installed else { return "Not installed" }
        guard let policy = harness.policy, !policy.isEmpty else { return "Unknown" }
        switch policy.lowercased() {
        case "synced": return "In sync"
        case "not wired": return "Not wired"
        default: return policy.capitalized
        }
    }

    static func policyOK(_ harness: OpsHarness) -> Bool { harness.installed && harness.policy?.lowercased() == "synced" }

    /// One line on the AGENTS.md copies: matching, drifting, or unknown.
    static func syncLine(_ sync: OpsPolicySync?, now: Date) -> String {
        guard let sync else { return "The report does not say whether the AGENTS.md copies match." }
        let when = sync.lastSync.map { " Last sync \(Format.ago(seconds: now.timeIntervalSince($0)))." } ?? ""
        switch sync.status?.lowercased() {
        case "ok": return "Every harness copy matches the policy." + when
        case "drift":
            let n = sync.drift.count
            return (n == 1 ? "1 copy differs from the policy." : "\(n) copies differ from the policy.") + when
        default: return "The sync state is not known." + when
        }
    }

    /// Repos whose AGENTS.md differs or is missing, as a short line; nil when all match or the report has none.
    static func repoLine(_ repos: OpsPolicyRepos?) -> String? {
        guard let repos else { return nil }
        let differ = repos.differ ?? 0, missing = repos.missing ?? 0
        guard differ + missing > 0 else { return nil }
        var parts: [String] = []
        if differ > 0 { parts.append("\(differ) differ") }
        if missing > 0 { parts.append("\(missing) missing") }
        let names = repos.toFix.prefix(3).joined(separator: ", ")
        return "Repos: " + parts.joined(separator: ", ") + (names.isEmpty ? "" : " (\(names))")
    }

    /// A count as text, or nil (a dash) when the source has no result.
    static func count(_ value: Int?) -> String? { value.map(String.init) }

    /// "as of 3 d ago", or why the age is unknown.
    static func asOf(_ date: Date?, now: Date) -> String {
        guard let date else { return "no date on record" }
        return "as of \(Format.ago(seconds: now.timeIntervalSince(date)))"
    }

    /// The shield result is not kept between runs: a nil count says so and names what to run.
    static let shieldWhy = "Teyla Shield keeps no result between runs."

    /// The agents line: "claude 6 · codex 2", with the harnesses that run nothing left out.
    static func agentsLine(_ agents: [String: Int]) -> String {
        let running = agents.filter { $0.value > 0 }.sorted { $0.key < $1.key }
        guard !running.isEmpty else { return "No agent sessions running." }
        return running.map { "\($0.key) \($0.value)" }.joined(separator: " · ")
    }

    /// Series points scaled to 0...1 for drawing; a flat series sits in the middle. Empty for fewer than two points.
    static func scaled(_ points: [OpsPoint]) -> [Double] {
        guard points.count >= 2, let low = points.map(\.value).min(), let high = points.map(\.value).max() else { return [] }
        guard high > low else { return points.map { _ in 0.5 } }
        return points.map { ($0.value - low) / (high - low) }
    }

    /// "22 to 39 GB over the last 24 h", the range the line covers; why there is no line otherwise.
    static func seriesRange(_ points: [OpsPoint], unit: String) -> String {
        guard points.count >= 2, let low = points.map(\.value).min(), let high = points.map(\.value).max(),
              let first = points.first?.time, let last = points.last?.time else {
            return "Not enough readings for a line yet."
        }
        let hours = max(1, Int((last.timeIntervalSince(first) / 3600).rounded()))
        return String(format: "%.0f to %.0f %@ over the last %d h", low, high, unit, hours)
    }
}

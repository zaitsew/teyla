import Foundation

/// Every command the Tools page and the command bar can run goes through this allow-list. The report's
/// `command` and `preview` come from the CLI, but a command the list does not name is refused and shown as refused:
/// a newer CLI, a damaged file or a hostile one can print anything, and none of it reaches a process.
///
/// What is on the list: approve, reject or edit one growth draft (`GrowthActions`), publish up to six items the owner
/// already approved to the networks he connected, read today's engage list and mark its rows done (`GrowthEngage`), forget a task that vanished, sweep what agents left on the disk (and its dry run), apply one
/// offer (and its dry run), and read the stores and GitHub again. Nothing that charges money, sends a message, replies,
/// deploys or submits to a store is, and nothing is ever added by the CLI's output.
enum ToolCommands {
    enum Check: Equatable, Sendable {
        case allowed
        case refused(String)

        var isAllowed: Bool { self == .allowed }
    }

    /// What a command does to the machine, as far as the confirm step is concerned.
    enum Effect: Equatable, Sendable {
        /// Changes nothing but a cache: runs without a confirm.
        case reads
        /// A dry run: prints what would happen and writes nothing.
        case previews
        /// Changes something: shown with its exact command and confirmed first.
        case changes
    }

    /// The offer ids `teyla apply` takes ("O1" to "O99").
    static func isOfferID(_ s: String) -> Bool { FirstRun.isOfferID(s) }

    /// A task id from `teyla schedules --json` ("claude-desktop:my-task", "launchd:com.example.job",
    /// "github:owner/repo:workflow"). It starts with an ASCII letter or digit, so it can never be read as a flag, and holds only
    /// ASCII letters, digits and `: . _ / @ + -`. A task whose id has other characters is refused, not forgotten.
    static func isTaskKey(_ s: String) -> Bool {
        guard !s.isEmpty, s.count <= 200 else { return false }
        let scalars = Array(s.unicodeScalars)
        func ascii(_ u: Unicode.Scalar) -> Bool {
            (u.value >= 48 && u.value <= 57) || (u.value >= 65 && u.value <= 90) || (u.value >= 97 && u.value <= 122)
        }
        guard ascii(scalars[0]) else { return false }
        let extra = Set(":._/@+-".unicodeScalars)
        return scalars.allSatisfy { ascii($0) || extra.contains($0) }
    }

    static func check(_ argv: [String]) -> Check {
        switch argv {
        case ["storage", "sweep"], ["storage", "sweep", "--dry"], ["portfolio", "--refresh"]:
            return .allowed
        case _ where argv.count == 3 && argv[0] == "apply" && ["--yes", "--dry"].contains(argv[2]):
            return isOfferID(argv[1]) ? .allowed : .refused("\(argv[1]) is not an offer id.")
        case _ where argv.count >= 3 && argv[0] == "schedules" && argv[1] == "forget":
            let keys = Array(argv.dropFirst(2))
            guard keys.count <= 20, keys.allSatisfy(isTaskKey) else { return .refused("A task id is not valid.") }
            return .allowed
        case _ where argv.count >= 2 && argv[0] == "growth" && argv[1] == "log":
            return ActivityLog.check(argv)
        case _ where argv.first == "growth":
            return GrowthEngage.check(argv) ?? GrowthActions.check(argv)
        default:
            return .refused("Teyla does not run this from the app: \(display(argv)).")
        }
    }

    static func effect(_ argv: [String]) -> Effect {
        if argv == ["portfolio", "--refresh"] { return .reads }
        if argv.last == "--dry" { return .previews }
        return .changes
    }

    /// A preview must be on the list and must be a dry run: a `preview` that changes something is refused.
    static func checkPreview(_ argv: [String]) -> Check {
        let basic = check(argv)
        guard basic.isAllowed else { return basic }
        return effect(argv) == .previews ? .allowed : .refused("A preview must be a dry run: \(display(argv)).")
    }

    /// The command as the owner would type it.
    static func display(_ argv: [String]) -> String {
        "teyla " + argv.map(quote).joined(separator: " ")
    }

    private static func quote(_ s: String) -> String {
        s.range(of: #"^[A-Za-z0-9_.:/@+=,-]+$"#, options: .regularExpression) != nil ? s : "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    /// The most output a card shows: the last lines of a long preview.
    static func trimmed(_ output: String, lines: Int = 14, characters: Int = 1500) -> String {
        let all = output.trimmingCharacters(in: .whitespacesAndNewlines).split(separator: "\n", omittingEmptySubsequences: false)
        var text = all.suffix(lines).joined(separator: "\n")
        if all.count > lines { text = "…\n" + text }
        if text.count > characters { text = "…" + String(text.suffix(characters)) }
        return text
    }
}

/// Where an action is on its way from the click to the result. One per action, kept by the Tools model.
enum ToolRun: Equatable, Sendable {
    /// The preview is running.
    case previewing
    /// The preview printed this; the exact command waits for a yes.
    case preview(String)
    /// No preview exists: the exact command waits for a yes.
    case confirming
    case running
    case done(String)
    case failed(String)
    /// The allow-list refused the command; the text says which.
    case refused(String)

    var isBusy: Bool {
        switch self {
        case .previewing, .running: return true
        default: return false
        }
    }
}

/// The steps between a click and a result, with no UI and no process in them.
enum ToolFlow {
    /// What a click on an action starts. `nil` for the allowed read-only command means "run it now".
    static func begin(_ action: ToolAction) -> ToolRun? {
        let command = ToolCommands.check(action.command)
        if case .refused(let why) = command { return .refused(why) }
        if let preview = action.preview, case .refused(let why) = ToolCommands.checkPreview(preview) { return .refused(why) }
        if action.preview != nil { return .previewing }
        if ToolCommands.effect(action.command) == .reads && !action.destructive { return nil }
        return .confirming
    }

    /// Whether the confirm button may run: only after a preview printed, or directly when none exists.
    static func canConfirm(_ run: ToolRun?) -> Bool {
        switch run {
        case .preview, .confirming: return true
        default: return false
        }
    }

    /// The action's button shows when the action is idle or finished; during a step the step's own buttons take its place.
    static func showsButton(_ run: ToolRun?) -> Bool {
        switch run {
        case nil: return true
        case .done: return true
        default: return false
        }
    }

    /// Whether a new click on the action is welcome: not while it runs, and not on a finished one without reopening.
    static func canBegin(_ run: ToolRun?) -> Bool { !(run?.isBusy ?? false) }
}

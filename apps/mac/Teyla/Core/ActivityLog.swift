import Foundation

/// The one command the "+1" control runs: `teyla growth log --kind <kind> [--product <id>] [--count <n>]`.
enum ActivityLog {
    static let countRange = 1 ... 50

    static func argv(kind: String, product: String?, count: Int) -> [String] {
        var argv = ["growth", "log", "--kind", kind]
        if let product, !product.isEmpty { argv += ["--product", product] }
        if count != 1 { argv += ["--count", String(count)] }
        return argv
    }

    /// The allow-list's answer for a `growth log` command: a known kind, an optional product that cannot be read as a flag,
    /// and an optional count from 1 to 50. Nothing else is run.
    static func check(_ argv: [String]) -> ToolCommands.Check {
        let refuse = ToolCommands.Check.refused("Teyla does not run this from the app: \(ToolCommands.display(argv)).")
        guard argv.count >= 4, argv[0] == "growth", argv[1] == "log", argv[2] == "--kind", ActivityKind.isKnown(argv[3]) else { return refuse }
        var rest = Array(argv.dropFirst(4))
        var seen: Set<String> = []
        while !rest.isEmpty {
            guard rest.count >= 2, !seen.contains(rest[0]) else { return refuse }
            seen.insert(rest[0])
            switch rest[0] {
            case "--product":
                guard ProductCommands.isProductID(rest[1]) else { return refuse }
            case "--count":
                guard rest[1].allSatisfy({ $0.isASCII && $0.isNumber }), let n = Int(rest[1]), countRange.contains(n) else { return refuse }
            default:
                return refuse
            }
            rest.removeFirst(2)
        }
        return .allowed
    }
}

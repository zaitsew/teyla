import Foundation

// Teyla's own settings file, `~/.teyla/config.toml`, read the way `teyla config` reads it and shown in plain groups.
// The app only reads it. A value whose key says it is a secret (key, token, secret, password) and every value under
// `[env]` is dropped while the file is parsed, so it can never reach a screen. The iPhone app can compile this file by
// path, so keep it free of UI.

enum ConfigValue: Equatable, Sendable {
    case text(String)
    case number(Double)
    case flag(Bool)
    case list([String])
    /// A value that exists but is never kept: a secret, or anything under `[env]`.
    case hidden
}

struct TeylaConfig: Equatable, Sendable {
    /// The file, with the home folder written as `~`.
    var path: String
    var exists: Bool
    /// `table.key`, or the bare key at the top of the file.
    var values: [String: ConfigValue]
    /// Lines the parser could not read; they are counted, not guessed.
    var unread: Int

    /// The names under `[env]`, sorted. Values are never kept.
    var environmentNames: [String] {
        values.keys.filter { $0.hasPrefix("env.") }.map { String($0.dropFirst(4)) }.sorted()
    }
}

enum ConfigFile {
    /// `~/.teyla/config.toml`, or under `TEYLA_HOME` when that is set.
    static func file(home: String, env: [String: String]) -> URL {
        let base = env["TEYLA_HOME"].map { ($0 as NSString).expandingTildeInPath }
            ?? (home as NSString).appendingPathComponent(".teyla")
        return URL(fileURLWithPath: (base as NSString).appendingPathComponent("config.toml"))
    }

    /// A file that does not exist is the defaults, not an error. Any other failure throws, so a file that cannot be read
    /// never reads as "everything is at its default".
    static func read(file: URL, home: String) throws -> TeylaConfig {
        let text: String
        do {
            text = try String(contentsOf: file, encoding: .utf8)
        } catch let error as NSError where error.domain == NSCocoaErrorDomain && error.code == NSFileReadNoSuchFileError {
            return TeylaConfig(path: shown(file.path, home: home), exists: false, values: [:], unread: 0)
        }
        var config = parse(text)
        config.path = shown(file.path, home: home)
        return config
    }

    static func shown(_ path: String, home: String) -> String {
        path.hasPrefix(home + "/") ? "~" + path.dropFirst(home.count) : path
    }

    /// Whether a key names a secret. Matched on the last part of the key, so `update.token` and `token` both count.
    static func isSecret(_ key: String) -> Bool {
        let name = (key.split(separator: ".").last.map(String.init) ?? key).lowercased()
        return ["key", "token", "secret", "password", "passwd", "credential"].contains { name.contains($0) }
    }

    /// The TOML Teyla writes: `[table]` headers, `key = value` with a string, number, true/false or a list on one or more
    /// lines. Anything else on a line is counted in `unread`.
    static func parse(_ text: String) -> TeylaConfig {
        var values: [String: ConfigValue] = [:]
        var unread = 0
        var table = ""
        var lines = text.split(omittingEmptySubsequences: false, whereSeparator: \.isNewline).map(String.init)[...]
        while let raw = lines.popFirst() {
            let line = stripComment(raw).trimmingCharacters(in: .whitespaces)
            if line.isEmpty { continue }
            if line.hasPrefix("[[") {
                table = ""
                unread += 1
                continue
            }
            if line.hasPrefix("[") && line.hasSuffix("]") && !line.contains("=") {
                table = String(line.dropFirst().dropLast()).trimmingCharacters(in: .whitespaces)
                continue
            }
            guard let equals = firstEquals(line) else {
                unread += 1
                continue
            }
            let name = unquote(String(line[..<equals]).trimmingCharacters(in: .whitespaces))
            var rest = String(line[line.index(after: equals)...]).trimmingCharacters(in: .whitespaces)
            // A list may run over several lines: take lines until the brackets balance.
            while rest.hasPrefix("[") && depth(rest) > 0, let next = lines.popFirst() {
                rest += " " + stripComment(next).trimmingCharacters(in: .whitespaces)
            }
            let key = table.isEmpty ? name : table + "." + name
            guard let value = value(rest) else {
                unread += 1
                continue
            }
            values[key] = (table == "env" || isSecret(key)) ? .hidden : value
        }
        return TeylaConfig(path: "", exists: true, values: values, unread: unread)
    }

    // MARK: Pieces

    private static func value(_ text: String) -> ConfigValue? {
        if text.hasPrefix("\"") || text.hasPrefix("'") { return quoted(text).map(ConfigValue.text) }
        if text == "true" { return .flag(true) }
        if text == "false" { return .flag(false) }
        if text.hasPrefix("[") && text.hasSuffix("]") {
            let inner = String(text.dropFirst().dropLast())
            var items: [String] = []
            for part in splitList(inner) {
                let item = part.trimmingCharacters(in: .whitespaces)
                if item.isEmpty { continue }
                if let words = quoted(item) { items.append(words) } else { items.append(item) }
            }
            return .list(items)
        }
        if let number = Double(text.replacingOccurrences(of: "_", with: "")) { return .number(number) }
        return nil
    }

    /// The text inside one pair of quotes, with the basic escapes; nil when the quote does not close.
    private static func quoted(_ text: String) -> String? {
        guard let quote = text.first, quote == "\"" || quote == "'" else { return nil }
        var out = ""
        var escaped = false
        for character in text.dropFirst() {
            if quote == "\"" && escaped {
                switch character {
                case "n": out.append("\n")
                case "t": out.append("\t")
                default: out.append(character)
                }
                escaped = false
            } else if quote == "\"" && character == "\\" {
                escaped = true
            } else if character == quote {
                return out
            } else {
                out.append(character)
            }
        }
        return nil
    }

    private static func unquote(_ text: String) -> String { quoted(text) ?? text }

    /// The line without a `#` comment; a `#` inside quotes stays.
    private static func stripComment(_ line: String) -> String {
        var quote: Character?
        var escaped = false
        for (offset, character) in line.enumerated() {
            if let open = quote {
                if open == "\"" && escaped { escaped = false } else if open == "\"" && character == "\\" { escaped = true } else if character == open { quote = nil }
            } else if character == "\"" || character == "'" {
                quote = character
            } else if character == "#" {
                return String(line.prefix(offset))
            }
        }
        return line
    }

    private static func firstEquals(_ line: String) -> String.Index? {
        var quote: Character?
        for index in line.indices {
            let character = line[index]
            if let open = quote {
                if character == open { quote = nil }
            } else if character == "\"" || character == "'" {
                quote = character
            } else if character == "=" {
                return index
            }
        }
        return nil
    }

    /// How many `[` are still open at the end of the text, outside quotes.
    private static func depth(_ text: String) -> Int {
        var quote: Character?
        var open = 0
        for character in text {
            if let q = quote {
                if character == q { quote = nil }
            } else if character == "\"" || character == "'" {
                quote = character
            } else if character == "[" {
                open += 1
            } else if character == "]" {
                open -= 1
            }
        }
        return open
    }

    private static func splitList(_ text: String) -> [String] {
        var parts: [String] = []
        var current = ""
        var quote: Character?
        for character in text {
            if let q = quote {
                current.append(character)
                if character == q { quote = nil }
            } else if character == "\"" || character == "'" {
                quote = character
                current.append(character)
            } else if character == "," {
                parts.append(current)
                current = ""
            } else {
                current.append(character)
            }
        }
        parts.append(current)
        return parts
    }
}

// MARK: The groups on the page

struct ConfigRow: Equatable, Sendable, Identifiable {
    var id: String { key }
    var key: String
    var label: String
    var hint: String
    /// What the value reads as, in plain words.
    var value: String
    /// True when the file does not set the key and the default shows.
    var isDefault: Bool
}

struct ConfigGroup: Equatable, Sendable, Identifiable {
    var id: String { title }
    var title: String
    var note: String
    var rows: [ConfigRow]
}

enum ConfigLogic {
    private enum Kind {
        case text, path, flag, count(String), limit, list(none: String), choice([String: String]), money
    }

    private struct Spec {
        var key: String
        var label: String
        var hint: String
        var kind: Kind
        /// What the product does when the file does not set the key.
        var fallback: String
    }

    private static let catalog: [(title: String, note: String, specs: [Spec])] = [
        ("Folders", "Where Teyla looks for code and files its reports.", [
            Spec(key: "code_root", label: "Code folder", hint: "Where your repositories live.", kind: .path, fallback: "~/repos"),
            Spec(key: "ops_root", label: "Ops folder", hint: "Everything that is not a code repository.", kind: .path, fallback: "~/ops"),
            Spec(key: "runs_root", label: "Reports folder", hint: "Where the weekly reports are filed.", kind: .path, fallback: "Inside the ops folder"),
        ]),
        ("Updates", "How Teyla keeps itself current.", [
            Spec(key: "update.channel", label: "Updates", hint: "Which releases the daily check installs.",
                 kind: .choice(["release": "Published releases", "none": "Never automatic"]), fallback: "Published releases"),
            Spec(key: "update.repo", label: "Update source", hint: "The GitHub repository releases come from.", kind: .text, fallback: "zaitsew/teyla"),
            Spec(key: "update.pin", label: "Pinned version", hint: "Updates stop at this version.", kind: .text, fallback: "Not pinned"),
            Spec(key: "safe.enabled", label: "Work mode", hint: "No network, no self-update, no code from repositories.", kind: .flag, fallback: "Off"),
            Spec(key: "safe.auto_update", label: "Update in work mode", hint: "The daily check may reach GitHub for a release.", kind: .flag, fallback: "Off"),
        ]),
        ("Machine guard", "What keeps parallel agents from overloading this Mac.", [
            Spec(key: "guard.enabled", label: "Guard", hint: "Makes heavy work wait when the Mac is busy.", kind: .flag, fallback: "On"),
            Spec(key: "guard.max_sims", label: "Simulators at once", hint: "More than this reads as busy. 0 means no limit.", kind: .limit, fallback: "2"),
            Spec(key: "guard.max_builds", label: "Builds at once", hint: "More than this reads as busy. 0 means no limit.", kind: .limit, fallback: "2"),
            Spec(key: "guard.max_lanes", label: "Agent lanes at once", hint: "Headless agent runs; 0 means no limit.", kind: .limit, fallback: "No limit"),
            Spec(key: "guard.agent", label: "Check every minute", hint: "A background agent records the load.", kind: .flag, fallback: "Off"),
            Spec(key: "guard.disk_warn_gb", label: "Low disk warning", hint: "Free space below this reads as busy.", kind: .count(" GB"), fallback: "25 GB"),
            Spec(key: "guard.disk_crit_gb", label: "Critical disk", hint: "Free space below this stops heavy work.", kind: .count(" GB"), fallback: "10 GB"),
        ]),
        ("Disk clean-up", "What the daily routine removes by itself.", [
            Spec(key: "storage.auto_clean", label: "Automatic clean-up", hint: "Finished worktrees and old build output.", kind: .flag, fallback: "Off"),
            Spec(key: "storage.idle_days", label: "Finished worktree after", hint: "A clean, pushed worktree untouched this long.", kind: .count(" days"), fallback: "3 days"),
            Spec(key: "storage.sim_max_booted", label: "Simulators kept booted", hint: "Idle ones above this are shut down.", kind: .count(""), fallback: "3"),
            Spec(key: "storage.sweep_urgent_free_gb", label: "Urgent clean-up below", hint: "Free space that starts a full sweep.", kind: .count(" GB"), fallback: "20 GB"),
        ]),
        ("What Teyla keeps", "Notes about your work, and whether a model reads them.", [
            Spec(key: "corrections.store", label: "Corrections are kept", hint: "Where each correction you make is stored.",
                 kind: .choice(["home": "In the Teyla folder", "repo": "In each repository"]), fallback: "In the Teyla folder"),
            Spec(key: "intent.enabled", label: "Long prompts, word for word", hint: "Kept per product as your own words.", kind: .flag, fallback: "On"),
            Spec(key: "intent.min_chars", label: "Counts as long from", hint: "Shorter prompts are not kept.", kind: .count(" characters"), fallback: "400 characters"),
            Spec(key: "state.model_brief", label: "Model-written brief", hint: "Sends the open questions to a model.", kind: .flag, fallback: "Off"),
            Spec(key: "hooks.context_budget", label: "Hand-off before a long session ends", hint: "The model writes a note when context runs short.", kind: .flag, fallback: "Off"),
            Spec(key: "growth.daily", label: "Daily content run", hint: "Plans and drafts posts at 06:30. Publishes nothing.", kind: .flag, fallback: "Off"),
        ]),
        ("Products and agents", "What Teyla looks at, and what it leaves alone.", [
            Spec(key: "products.repos", label: "Repositories it measures", hint: "The only repos whose usage it reads.", kind: .list(none: "Every repository"), fallback: "Every repository"),
            Spec(key: "harness.disabled", label: "Agents left alone", hint: "No health line, no fixes, no sync.", kind: .list(none: "None turned off"), fallback: "None turned off"),
            Spec(key: "relay.folder", label: "iPhone relay folder", hint: "The iCloud Drive folder shared with the phone.", kind: .path, fallback: "iCloud Drive / Teyla"),
            Spec(key: "spend.daily_budget_usd", label: "Daily AI budget", hint: "A day over this is flagged. 0 turns it off.", kind: .money, fallback: "Off"),
        ]),
    ]

    /// The groups that have something to say: every row shows the file's value or the default.
    static func groups(_ config: TeylaConfig) -> [ConfigGroup] {
        catalog.map { group in
            ConfigGroup(title: group.title, note: group.note, rows: group.specs.map { row($0, config) })
        }
    }

    private static func row(_ spec: Spec, _ config: TeylaConfig) -> ConfigRow {
        let value = config.values[spec.key]
        let shown = value.flatMap { display($0, spec.kind) }
        return ConfigRow(key: spec.key, label: spec.label, hint: spec.hint, value: shown ?? spec.fallback, isDefault: shown == nil)
    }

    private static func display(_ value: ConfigValue, _ kind: Kind) -> String? {
        switch (value, kind) {
        case (.hidden, _):
            return "Set. Not shown."
        case (.flag(let on), _):
            return on ? "On" : "Off"
        case (.text(let text), .flag):
            switch text.lowercased() {
            case "true", "yes", "on", "1": return "On"
            case "false", "no", "off", "0": return "Off"
            default: return text.isEmpty ? nil : text
            }
        case (.text(let text), .choice(let names)):
            return text.isEmpty ? nil : (names[text] ?? text)
        case (.text(let text), .path), (.text(let text), .text):
            return text.isEmpty ? nil : text
        case (.text(let text), .count(let unit)):
            return Double(text).map { number($0) + unit }
        case (.number(let n), .count(let unit)):
            return number(n) + unit
        case (.number(let n), .limit):
            return n == 0 ? "No limit" : number(n)
        case (.number(let n), .money):
            return n == 0 ? "Off" : Format.spent(n)
        case (.list(let items), .list(let none)):
            return items.isEmpty ? none : items.joined(separator: ", ")
        case (.text(let text), .list(let none)):
            return text.isEmpty ? none : text
        case (.number(let n), _):
            return number(n)
        case (.text(let text), _):
            return text.isEmpty ? nil : text
        case (.list(let items), _):
            return items.isEmpty ? nil : items.joined(separator: ", ")
        }
    }

    private static func number(_ n: Double) -> String {
        n == n.rounded() ? "\(Int(n))" : String(format: "%g", n)
    }

    /// Keys the file sets that no row on the page shows (the secrets stay hidden and are counted as set).
    static func otherKeys(_ config: TeylaConfig) -> Int {
        let listed = Set(catalog.flatMap { $0.specs.map(\.key) })
        return config.values.keys.filter { !listed.contains($0) && !$0.hasPrefix("env.") }.count
    }

    /// The figure of the first tile: how many keys the file sets.
    static func keysSet(_ config: TeylaConfig) -> Int { config.values.count }

    static func environmentLine(_ config: TeylaConfig) -> String {
        let names = config.environmentNames
        if names.isEmpty { return "None set." }
        let shownNames = names.prefix(6).joined(separator: ", ")
        return names.count > 6 ? "\(shownNames) and \(names.count - 6) more." : shownNames + "."
    }
}

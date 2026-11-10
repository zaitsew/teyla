import Foundation

/// One usage event. No content: an id from the app's own allow-list, a fixed result word, a duration,
/// the build and the design variants switched on. There is no field that can hold free text.
struct UsageEvent: Codable, Equatable {
    enum Kind: String, Codable, CaseIterable {
        case session, screen, action, task
        case deadEnd = "dead_end"
        case repeatTap = "repeat_tap"
    }

    /// Unix seconds.
    var t: Int
    var k: Kind
    /// A screen route, an action id (dynamic suffix stripped) or a task name. Allow-listed, or nil for `session`.
    var id: String?
    /// session: start | background | end. action: done | cancelled | error | undone.
    /// task: start | success | cancel. dead_end: screen | sheet.
    var r: String?
    /// Milliseconds: a task's duration, or how long a dead-end screen was open.
    var ms: Int?
    /// The build number (CFBundleVersion).
    var b: String
    /// Open design decision -> active variant. Omitted when none.
    var d: [String: String]?

    /// The only keys an event may encode. A test holds the encoded payload to this list.
    static let allowedKeys: Set<String> = ["t", "k", "id", "r", "ms", "b", "d"]
}

enum UsageActionResult: String, Sendable { case done, cancelled, error, undone }
enum UsageTaskPhase: String, Sendable { case start, success, cancel }

/// What the app declared at setup. Anything else is dropped.
struct UsageAllowList: Equatable {
    var screens: Set<String> = []
    var actions: Set<String> = []
    var tasks: Set<String> = []
}

enum UsageID {
    /// Letters, digits, dot, dash and underscore, at most 80, starting with a letter or digit. A title or a
    /// sentence has spaces and never passes, so an app cannot declare one by mistake.
    static func isValid(_ text: String) -> Bool {
        let bytes = Array(text.utf8)
        guard (1...80).contains(bytes.count), isAlnum(bytes[0]) else { return false }
        return bytes.allSatisfy { isAlnum($0) || $0 == 46 || $0 == 45 || $0 == 95 }
    }

    /// A decision id or a variant name: lowercase, at most 40.
    static func isToken(_ text: String) -> Bool {
        let bytes = Array(text.utf8)
        guard (1...40).contains(bytes.count), let first = bytes.first, (first >= 97 && first <= 122) || (first >= 48 && first <= 57) else { return false }
        return bytes.allSatisfy { ($0 >= 97 && $0 <= 122) || ($0 >= 48 && $0 <= 57) || $0 == 45 || $0 == 46 || $0 == 95 }
    }

    private static func isAlnum(_ b: UInt8) -> Bool { (b >= 48 && b <= 57) || (b >= 65 && b <= 90) || (b >= 97 && b <= 122) }
    private static func isDigit(_ c: Character) -> Bool { c.isASCII && c.isNumber }
    private static func isHex(_ c: Character) -> Bool { c.isASCII && c.isHexDigit }

    /// A part that changes per item: all digits, a UUID, or a hex run of 8 or more with a digit in it.
    static func isDynamic(_ part: Substring) -> Bool {
        if part.isEmpty { return false }
        if part.allSatisfy(isDigit) { return true }
        if part.count == 36, UUID(uuidString: String(part)) != nil { return true }
        return part.count >= 8 && part.allSatisfy(isHex) && part.contains(where: isDigit)
    }

    /// "trip.row.3F2A..." -> "trip.row"; "task.row-12" -> "task.row"; "list.item_<uuid>" -> "list.item".
    /// A suffix is dynamic when it follows a dot, a dash, an underscore or a colon and is a number, a UUID or a hex run.
    static func normalize(_ raw: String) -> String {
        var parts = raw.split(separator: ".", omittingEmptySubsequences: false)
        while parts.count > 1, let last = parts.last, isDynamic(last) { parts.removeLast() }
        guard var last = parts.last else { return raw }
        if last.count > 37 {
            let tail = last.suffix(36)
            let sep = last[last.index(last.endIndex, offsetBy: -37)]
            if UUID(uuidString: String(tail)) != nil, "-_:".contains(sep) { last = last.dropLast(37) }
        } else {
            for sep in ["-", "_", ":"] as [Character] {
                if let at = last.lastIndex(of: sep), at != last.startIndex, isDynamic(last[last.index(after: at)...]) {
                    last = last[..<at]
                    break
                }
            }
        }
        parts[parts.count - 1] = last
        return parts.joined(separator: ".")
    }
}

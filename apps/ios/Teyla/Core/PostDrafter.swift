// PostDrafter: one LinkedIn post and one X post from the owner's own note.
//
// Runs on the device only: Apple's on-device model (FoundationModels) when it is available,
// otherwise a deterministic cutter. Nothing leaves the phone, and nothing goes through the relay.
// The same file compiles into `scripts/post-drafter-eval` on the Mac, so the eval uses the same rules.

import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

public struct PostDraft: Equatable, Sendable {
    public enum Source: String, Sendable { case model, cutter }
    public var linkedIn: String
    public var x: String
    public var source: Source
}

public enum PostRules {
    public static let xLimit = 280
    /// POLICY §16 banned filler, plus what reads as machine-written in a post.
    public static let banned = [
        "delve", "comprehensive", "robust", "seamless", "leverage", "it's important to note",
        "i hope this helps", "great question", "game-changer", "game changer", "unlock", "journey",
        "in today's", "let's dive", "here's the thing",
    ]

    public static let instructions = "You are a careful copy editor. You never add facts, words of praise or feelings. You fix grammar and cut."

    /// The one task the on-device model is given. Single, plain tasks keep its output faithful;
    /// a list of style rules made it return the note unchanged (eval, 2026-11-09).
    public static let editTask = """
    Fix the spelling and grammar of this text. \
    Then split it into short paragraphs of one or two sentences, with a blank line between them. \
    Return only the edited text.


    """

    /// Share of the draft's words that the note does not contain. Grammar fixes add a few; a rewrite adds many.
    public static func addedShare(_ text: String, note: String) -> Double {
        func words(_ s: String) -> [String] {
            s.lowercased().components(separatedBy: CharacterSet.letters.inverted).filter { $0.count > 2 }
        }
        let have = Set(words(note).map(stem))
        let w = words(text)
        guard !w.isEmpty else { return 1 }
        let grammar: Set<String> = ["the", "and", "that", "this", "for", "with", "you", "your", "are", "was", "have", "has", "but", "into", "from"]
        let added = w.filter { !have.contains(stem($0)) && !grammar.contains($0) }
        return Double(added.count) / Double(w.count)
    }

    static func stem(_ w: String) -> String {
        for suf in ["ing", "ed", "es", "s", "t"] where w.count > suf.count + 3 && w.hasSuffix(suf) { return String(w.dropLast(suf.count)) }
        return w
    }

    /// The note without what is not post text: `#tags`, and links (a pull request link becomes "PR #n";
    /// a link in parentheses goes; any other link goes).
    public static func prepare(_ note: String) -> String {
        var t = note
        let subs: [(String, String)] = [
            (#"\s*#[A-Za-z][\w-]*"#, ""),
            (#"\(\s*(https?://)?(www\.)?[a-z0-9-]+\.(com|ai|dev|io|app|org)[^\s)]*\s*\)"#, ""),
            (#"(https?://)?(www\.)?github\.com/[\w.-]+/[\w.-]+/pull/(\d+)"#, "PR #$3"),
            (#"\s+(in|at|on|see|via|from)\s+(https?://)?(www\.)?[a-z0-9-]+\.(com|ai|dev|io|app|org)(/[^\s]*[^\s.,;:!?)])?"#, ""),
            (#"(https?://)?(www\.)?[a-z0-9-]+\.(com|ai|dev|io|app|org)(/[^\s]*[^\s.,;:!?)])?"#, ""),
            (#"[ \t]{2,}"#, " "),
            (#"\s+([.,;:])"#, "$1"),
        ]
        for (pattern, template) in subs {
            t = t.replacingOccurrences(of: pattern, with: template, options: [.regularExpression, .caseInsensitive])
        }
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    /// What breaks a rule in `text`, given the owner's `note`. Empty means it passes.
    public static func findings(_ text: String, note: String, limit: Int? = nil) -> [String] {
        var out: [String] = []
        let lower = text.lowercased()
        if text.range(of: #"(^|\s)#[A-Za-z]"#, options: .regularExpression) != nil { out.append("hashtag") }
        if lower.range(of: #"https?://|www\.|\b[a-z0-9-]+\.(com|ai|dev|io|app)\b"#, options: .regularExpression) != nil { out.append("link") }
        for w in banned where lower.contains(w) { out.append("banned: \(w)") }
        let noteNums = Set(numbers(in: note))
        for n in numbers(in: text) where !noteNums.contains(n) { out.append("number not in note: \(n)") }
        if let limit, text.count > limit { out.append("over \(limit) characters") }
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { out.append("empty") }
        return out
    }

    static func numbers(in s: String) -> [String] {
        guard let re = try? NSRegularExpression(pattern: #"\d+(?:[.,]\d+)?"#) else { return [] }
        let ns = s as NSString
        return re.matches(in: s, range: NSRange(location: 0, length: ns.length)).map { ns.substring(with: $0.range).replacingOccurrences(of: ",", with: ".") }
    }
}

/// The fallback: keeps the owner's sentences in order, drops filler, adds nothing.
public enum PostCutter {
    static let filler = [#"\bum+\b,?"#, #"\buh+\b,?"#, #"\byou know,?\s*"#, #"\bbasically,?\s*"#, #"\bkind of\s+"#, #"\bsort of\s+"#, #"\bI mean,?\s*"#]

    public static func sentences(_ note: String) -> [String] {
        var s = note.replacingOccurrences(of: "\r", with: "")
        for f in filler { s = s.replacingOccurrences(of: f, with: "", options: [.regularExpression, .caseInsensitive]) }
        var out: [String] = []
        s.enumerateSubstrings(in: s.startIndex..., options: .bySentences) { sub, _, _, _ in
            guard var t = sub?.trimmingCharacters(in: .whitespacesAndNewlines), !t.isEmpty else { return }
            t = t.replacingOccurrences(of: #"\s{2,}"#, with: " ", options: .regularExpression)
            out.append(t.prefix(1).uppercased() + t.dropFirst())
        }
        return out
    }

    public static func draft(note: String) -> PostDraft {
        let parts = sentences(note)
        return PostDraft(linkedIn: parts.joined(separator: "\n\n"), x: xVersion(parts), source: .cutter)
    }

    /// The X version: whole sentences of the post, in order, within the limit. It keeps the first
    /// sentence (the problem) and the last (the call to action) when both fit.
    public static func xVersion(_ parts: [String]) -> String {
        let limit = PostRules.xLimit
        guard let first = parts.first else { return "" }
        if first.count > limit {
            var x = ""
            for w in first.split(separator: " ") {
                let next = x.isEmpty ? String(w) : x + " " + w
                if next.count > limit - 1 { break }
                x = next
            }
            return x + "…"
        }
        let last = parts.count > 1 ? parts[parts.count - 1] : nil
        var chosen = [first]
        let reserve = last.map { $0.count + 1 } ?? 0
        if let last, first.count + reserve > limit { _ = last; return first }
        for p in parts.dropFirst().dropLast() {
            let len = chosen.joined(separator: " ").count + 1 + p.count + reserve
            if len <= limit { chosen.append(p) }
        }
        if let last { chosen.append(last) }
        return chosen.joined(separator: " ")
    }
}

public enum PostDrafter {
    /// True when the on-device model can draft on this device right now.
    public static var modelAvailable: Bool {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, macOS 26.0, *) {
            if case .available = SystemLanguageModel.default.availability { return true }
        }
        #endif
        return false
    }

    /// One LinkedIn and one X version of `note`. The model only copy-edits; the X version is cut
    /// from that edit by rule. An edit that breaks a rule or adds too many words is redone once,
    /// then the cutter's version is used.
    public static func draft(note raw: String) async -> PostDraft {
        let note = PostRules.prepare(raw)
        let cut = PostCutter.draft(note: note)
        #if canImport(FoundationModels)
        if #available(iOS 26.0, macOS 26.0, *), modelAvailable {
            for _ in 0..<2 {
                guard let edited = try? await LanguageModelSession(instructions: PostRules.instructions)
                    .respond(to: PostRules.editTask + note, options: GenerationOptions(temperature: 0.3)).content
                else { break }
                let li = clean(edited)
                guard PostRules.findings(li, note: note).isEmpty, PostRules.addedShare(li, note: note) <= 0.15 else { continue }
                let paragraphs = li.components(separatedBy: "\n").map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
                let sentences = paragraphs.flatMap { PostCutter.sentences($0) }
                return PostDraft(linkedIn: paragraphs.joined(separator: "\n\n"), x: PostCutter.xVersion(sentences), source: .model)
            }
        }
        #endif
        return cut
    }

    static func clean(_ s: String) -> String {
        var t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        t = t.replacingOccurrences(of: "\u{2014}", with: ", ").replacingOccurrences(of: "\u{2013}", with: ", ")
        t = t.replacingOccurrences(of: " ,", with: ",").replacingOccurrences(of: ",,", with: ",")
        t = t.replacingOccurrences(of: "\u{2019}", with: "'")
        return t
    }
}

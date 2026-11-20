import Foundation

/// What a report may not carry out of the app. The TypeScript, Kotlin and Python implementations (`scrub.ts`,
/// `Scrub.kt`, `packages/review-channel/server.py`) run the same rules against the same test vectors
/// (`packages/review-channel/test-vectors/scrub.json`). Placeholders are never matched by a rule, so scrubbing twice
/// gives the same text. No UIKit, so the tests run on the Mac.
enum ReviewScrub {
    static let labelCap = 200

    private static func make(_ pattern: String, ignoreCase: Bool = false) -> NSRegularExpression {
        // The patterns are constants, so a failure here is a programming error caught by the tests.
        // swiftlint:disable:next force_try
        try! NSRegularExpression(pattern: pattern, options: ignoreCase ? [.caseInsensitive] : [])
    }

    private static let urlParam = make(#"([?&;][A-Za-z0-9_.\-]*(?:token|key|secret|password|passwd|pwd|auth|code|sig)[A-Za-z0-9_.\-]*=)[^&#\s]+"#, ignoreCase: true)
    private static let jwt = make(#"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]{4,}\.[A-Za-z0-9_\-]*"#)
    private static let bearer = make(#"(?<![A-Za-z0-9])Bearer[ \t]+[A-Za-z0-9._~+/=\-]{12,}"#, ignoreCase: true)
    private static let apiKey = make(
        #"(?<![A-Za-z0-9_\-])(?:(?:sk|pk|rk)[_\-][A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}"#
            + #"|xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|AIza[A-Za-z0-9_\-]{30,})"#)
    private static let email = make(#"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+"#)
    private static let iban = make(#"(?<![A-Za-z0-9])[A-Z]{2}[0-9]{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?(?![A-Za-z0-9])"#)
    private static let card = make(#"(?<![0-9])[0-9](?:[ \-]?[0-9]){12,18}(?![0-9])"#)
    private static let phone = make(#"(?<![A-Za-z0-9+])(?![0-9]{4}-[0-9]{2}-[0-9]{2})\+?[0-9(][0-9 .()\-]{6,}[0-9](?![A-Za-z0-9])"#)

    /// Every match replaced by what `transform` returns for it (the whole match and its first group).
    private static func replace(_ regex: NSRegularExpression, in text: String, _ transform: (String, String) -> String) -> String {
        let ns = text as NSString
        var out = ""
        var last = 0
        for match in regex.matches(in: text, range: NSRange(location: 0, length: ns.length)) {
            out += ns.substring(with: NSRange(location: last, length: match.range.location - last))
            let whole = ns.substring(with: match.range)
            let head = match.numberOfRanges > 1 && match.range(at: 1).location != NSNotFound ? ns.substring(with: match.range(at: 1)) : ""
            out += transform(whole, head)
            last = match.range.location + match.range.length
        }
        return out + ns.substring(from: last)
    }

    private static func digits(_ text: String) -> String { text.filter { $0 >= "0" && $0 <= "9" } }

    private static func luhn(_ digits: String) -> Bool {
        var total = 0
        for (i, ch) in digits.reversed().enumerated() {
            var n = Int(ch.asciiValue ?? 48) - 48
            if i % 2 == 1 {
                n *= 2
                if n > 9 { n -= 9 }
            }
            total += n
        }
        return total % 10 == 0
    }

    /// E-mail addresses, phone numbers, card numbers, IBANs, bearer tokens, API keys, JWTs and the values of secret
    /// URL parameters, each replaced by a placeholder.
    static func scrub(_ text: String) -> String {
        var out = replace(urlParam, in: text) { _, head in head + "[token]" }
        out = replace(jwt, in: out) { _, _ in "[token]" }
        out = replace(bearer, in: out) { _, _ in "Bearer [token]" }
        out = replace(apiKey, in: out) { _, _ in "[token]" }
        out = replace(email, in: out) { _, _ in "[email]" }
        out = replace(iban, in: out) { _, _ in "[iban]" }
        out = replace(card, in: out) { whole, _ in
            let d = digits(whole)
            return (13...19).contains(d.count) && luhn(d) ? "[card]" : whole
        }
        return replace(phone, in: out) { whole, _ in phoneOrSplit(whole) }
    }

    /// One number, or several separated by spaces: the longest run of space-separated groups that fits in
    /// 15 digits is one number, repeatedly; a short tail joins the last run.
    private static func phoneOrSplit(_ m: String) -> String {
        let n = digits(m).count
        let low = m.hasPrefix("+") ? 8 : 9
        if (low...15).contains(n) { return "[phone]" }
        if n <= 15 { return m }
        let tokens = m.split(separator: " ", omittingEmptySubsequences: false).map(String.init)
        var out: [String] = []
        var i = 0
        while i < tokens.count {
            let floor = tokens[i].hasPrefix("+") ? 8 : 9
            var best = -1
            var total = 0
            var j = i
            while j < tokens.count {
                total += digits(tokens[j]).count
                if total > 15 { break }
                if total >= floor { best = j }
                j += 1
            }
            if best >= 0 {
                out.append("[phone]")
                i = best + 1
            } else if out.last == "[phone]" {
                i += 1
            } else {
                out.append(tokens[i])
                i += 1
            }
        }
        return out.joined(separator: " ")
    }

    /// An accessibility label: scrubbed first, then at most 200 characters.
    static func scrubLabel(_ text: String) -> String { String(scrub(text).prefix(labelCap)) }

    /// A short name or key: scrubbed first, then cut to `limit` characters, so a cut never leaves half a secret.
    static func clip(_ text: String, to limit: Int = 200) -> String { String(scrub(text).prefix(limit)) }
}

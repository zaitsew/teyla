import Foundation

// What was done to sell each product: posts, marketing (ads and outreach) and ICP meetings, counted from the growth
// ledger `~/.teyla/growth/ledger.jsonl` the same way `teyla growth sale-attempts` does (`growth.attempt_rows`). No command
// prints this as JSON, so the app reads the ledger itself, read-only. Zero attempts means "not tried yet", which is an
// invitation to sell it, never a reason to close it (POLICY section 19).
// The iPhone app can compile this file by path, so keep it free of UI.

struct SaleAttempts: Equatable, Sendable {
    var posts = 0
    var marketing = 0
    var icpMeetings = 0
    /// The newest day (YYYY-MM-DD) of any attempt; "" when there is none.
    var last = ""

    var total: Int { posts + marketing + icpMeetings }
    var tried: Bool { total > 0 }
}

enum SaleLedger {
    struct Read: Equatable, Sendable {
        var byProduct: [String: SaleAttempts]
        /// Ledger lines that were not a JSON object; they count for nothing.
        var skipped: Int

        func attempts(for product: String) -> SaleAttempts { byProduct[product] ?? SaleAttempts() }
    }

    /// `~/.teyla/growth/ledger.jsonl`, or under `TEYLA_HOME` when that is set.
    static func file(home: String, env: [String: String]) -> URL {
        let base = env["TEYLA_HOME"].map { ($0 as NSString).expandingTildeInPath }
            ?? (home as NSString).appendingPathComponent(".teyla")
        return URL(fileURLWithPath: (base as NSString).appendingPathComponent("growth")).appendingPathComponent("ledger.jsonl")
    }

    /// A missing ledger is no attempts yet, not an error; a ledger that cannot be read is.
    static func read(file: URL) throws -> Read {
        guard FileManager.default.fileExists(atPath: file.path) else { return Read(byProduct: [:], skipped: 0) }
        return parse(try String(contentsOf: file, encoding: .utf8))
    }

    static func parse(_ text: String) -> Read {
        var rows: [String: SaleAttempts] = [:]
        var skipped = 0
        for line in text.split(whereSeparator: \.isNewline) {
            guard let data = line.data(using: .utf8), let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else {
                skipped += 1
                continue
            }
            guard let product = object["product"] as? String, !product.isEmpty else { continue }
            let event = object["ev"] as? String
            let kind = object["kind"] as? String
            var row = rows[product] ?? SaleAttempts()
            if event == "published" || (event == "attempt" && kind == "post") {
                row.posts += 1
            } else if event == "attempt", kind == "ad" || kind == "outreach" {
                row.marketing += 1
            } else if event == "attempt", kind == "icp-meeting" {
                row.icpMeetings += 1
            } else {
                continue
            }
            if let day = object["day"] as? String { row.last = max(row.last, day) }
            rows[product] = row
        }
        return Read(byProduct: rows, skipped: skipped)
    }
}

/// The words of the selling block on a product page.
enum SaleLogic {
    /// The figure: how many attempts, as a number. Zero is a real zero, and the detail says "not tried yet".
    static func figure(_ attempts: SaleAttempts) -> String { "\(attempts.total)" }

    static func detail(_ attempts: SaleAttempts, parked: Bool) -> String {
        if attempts.tried { return "Posts, marketing and ICP meetings." }
        return parked ? "Not tried yet. Parked." : "Not tried yet. Next in line."
    }

    /// "3 Nov", or "No attempt yet".
    static func lastWords(_ attempts: SaleAttempts) -> String {
        guard attempts.tried, let date = MoneyLogic.day(attempts.last) else { return "No attempt yet" }
        return MoneyLogic.shortDay(date)
    }

    static func rows(_ attempts: SaleAttempts) -> [(label: String, count: Int, note: String)] {
        [("Posts", attempts.posts, "Published on a channel"),
         ("Marketing", attempts.marketing, "Ads and outreach"),
         ("ICP meetings", attempts.icpMeetings, "Conversations with a person who fits")]
    }
}

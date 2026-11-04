import Foundation

/// The Playbook section of `teyla console --json` (docs/CONSOLE.md).
struct PlaybookReport: Decodable, ConsoleSectionData {
    var headline: ConsoleHeadline?

    enum CodingKeys: String, CodingKey { case headline }

    init(headline: ConsoleHeadline? = nil) {
        self.headline = headline
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headline = c.optional(.headline)
    }
}

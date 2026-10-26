import Foundation

/// The sample mode's data: a bundled snapshot with made-up products, shown when no Mac is paired
/// (first launch, App Review). Nothing in it is real, and nothing sent from sample mode leaves the phone.
enum SampleData {
    /// `via` of the result a simulated send gets.
    static let via = "sample"
    /// What the card says after a simulated send.
    static let notice = "Sample: nothing was sent"
    static let bannerText = "Sample data \u{2014} pair with your Mac to see yours"

    /// The bundled `sample-state.json`.
    static func bundled(in bundle: Bundle = .main) -> Data? {
        bundle.url(forResource: "sample-state", withExtension: "json").flatMap { try? Data(contentsOf: $0) }
    }

    /// The snapshot with every timestamp moved so that `generated` is `now`: ages stay what the file says,
    /// and the sample never looks stale.
    static func snapshot(from data: Data, now: Date = Date()) -> Snapshot? {
        guard let root = try? JSONSerialization.jsonObject(with: data),
              let object = root as? [String: Any],
              let generated = (object["generated"] as? String).flatMap(ISODate.parse)
        else { return nil }
        let delta = now.timeIntervalSince(generated)
        guard let shifted = try? JSONSerialization.data(withJSONObject: shift(object, by: delta)) else { return nil }
        return try? PhoneFormat.decodeSnapshot(shifted)
    }

    private static func shift(_ value: Any, by delta: TimeInterval) -> Any {
        switch value {
        case let text as String:
            guard looksLikeTimestamp(text), let date = ISODate.parse(text) else { return text }
            return ISODate.format(date.addingTimeInterval(delta))
        case let list as [Any]:
            return list.map { shift($0, by: delta) }
        case let object as [String: Any]:
            return object.mapValues { shift($0, by: delta) }
        default:
            return value
        }
    }

    private static func looksLikeTimestamp(_ text: String) -> Bool {
        text.count >= 20 && text.range(of: #"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d"#, options: .regularExpression) != nil
    }
}

import Foundation

/// Questions that waited longer than a week fold into "Older" under the fresh ones.
enum AskFold {
    static let olderAfter: TimeInterval = 7 * 86_400

    /// Splits `items` into fresh and older, each in its original order (the rank order is kept).
    /// `age` gives an item's age in seconds.
    static func partition<T>(_ items: [T], age: (T) -> Double) -> (fresh: [T], older: [T]) {
        var fresh: [T] = []
        var older: [T] = []
        for item in items {
            if age(item) > olderAfter { older.append(item) } else { fresh.append(item) }
        }
        return (fresh, older)
    }

    /// The fold's heading: "Older · 15".
    static func heading(count: Int) -> String { "Older · \(count)" }
}

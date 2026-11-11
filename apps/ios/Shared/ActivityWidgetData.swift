import Foundation

// What the home-screen widget draws (docs/APP.md, "The activity widget"). This file is compiled into the app, the widget
// extension and the tests, and depends on nothing else. The app writes `activity-widget.json` into the App Group container
// each time it reads a signed snapshot from the Mac; the widget only reads it. The widget never holds the relay key and
// never touches the iCloud folder.

/// One grid: a level 0...4 per day from `start` (a Monday) to the snapshot's day, today's count and the streak.
struct WidgetSeries: Codable, Equatable, Sendable {
    var start: String
    var levels: [Int]
    var todayCount: Int
    var streak: Int
}

struct ActivityWidgetData: Codable, Equatable, Sendable {
    var version = 1
    /// The Mac's day of the snapshot (`YYYY-MM-DD`). Its "today" numbers are today's only on that day.
    var day: String
    /// When the Mac wrote the snapshot.
    var generated: Date
    var growth: WidgetSeries?
    var github: WidgetSeries?
}

enum ActivityWidgetStore {
    static let appGroup = "group.com.zaitsew.teyla"
    static let fileName = "activity-widget.json"
    /// The widget kind; the app asks WidgetKit to reload it after a write.
    static let kind = "TeylaActivity"

    static func url() -> URL? {
        FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroup)?.appendingPathComponent(fileName)
    }

    static func encode(_ data: ActivityWidgetData) -> Data? {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .secondsSince1970
        encoder.outputFormatting = .sortedKeys
        return try? encoder.encode(data)
    }

    static func decode(_ data: Data) -> ActivityWidgetData? {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .secondsSince1970
        guard let value = try? decoder.decode(ActivityWidgetData.self, from: data), value.version == 1 else { return nil }
        return value
    }

    /// Writes when the content changed; true when it wrote (the caller then reloads the widget).
    @discardableResult
    static func write(_ value: ActivityWidgetData, to url: URL? = url()) -> Bool {
        guard let url, let bytes = encode(value) else { return false }
        if let old = try? Data(contentsOf: url), old == bytes { return false }
        return (try? bytes.write(to: url, options: .atomic)) != nil
    }

    static func read(from url: URL? = url()) -> ActivityWidgetData? {
        guard let url, let bytes = try? Data(contentsOf: url) else { return nil }
        return decode(bytes)
    }
}

enum ActivityWidgetLogic {
    private static var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC") ?? .gmt
        return calendar
    }

    private static func date(_ day: String) -> Date? {
        let parts = day.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        return calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2]))
    }

    /// The phone's own day, `YYYY-MM-DD`, in its time zone.
    static func localDay(_ now: Date, timeZone: TimeZone = .current) -> String {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let c = local.dateComponents([.year, .month, .day], from: now)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    /// The grid: one column per week, Monday first, the newest week last, at most `weeks` columns. A day before `start` or
    /// after the last day is nil.
    static func columns(_ series: WidgetSeries, weeks: Int) -> [[Int?]] {
        guard weeks > 0, let first = date(series.start), !series.levels.isEmpty else { return [] }
        let lead = (calendar.component(.weekday, from: first) + 5) % 7     // Monday = 0
        var slots: [Int?] = Array(repeating: nil, count: lead) + series.levels.map { Optional(min(max($0, 0), 4)) }
        while slots.count % 7 != 0 { slots.append(nil) }
        let all = stride(from: 0, to: slots.count, by: 7).map { Array(slots[$0 ..< $0 + 7]) }
        return Array(all.suffix(weeks))
    }

    /// Today's number as the widget shows it: the count when the snapshot is from today, else "–" (the Mac has not
    /// written since midnight, so today's number is unknown, not zero).
    static func today(_ series: WidgetSeries?, data: ActivityWidgetData, now: Date, timeZone: TimeZone = .current) -> String {
        guard let series else { return "–" }
        return data.day == localDay(now, timeZone: timeZone) ? compact(series.todayCount) : "–"
    }

    /// 999, 1.2k, 12k: a number that fits beside a small grid.
    static func compact(_ n: Int) -> String {
        if n < 1000 { return "\(max(n, 0))" }
        if n < 10_000 {
            let tenths = n / 100
            return tenths % 10 == 0 ? "\(tenths / 10)k" : "\(tenths / 10).\(tenths % 10)k"
        }
        return "\(n / 1000)k"
    }

    /// "Updated 10:49", or "Updated Tue" when the snapshot is from an earlier day.
    static func updated(_ data: ActivityWidgetData, now: Date, timeZone: TimeZone = .current) -> String {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        var style: Date.FormatStyle = local.isDate(data.generated, inSameDayAs: now)
            ? Date.FormatStyle().hour(.twoDigits(amPM: .omitted)).minute(.twoDigits)
            : Date.FormatStyle().weekday(.abbreviated)
        style.locale = Locale(identifier: "en_GB")
        style.timeZone = timeZone
        return "Updated " + data.generated.formatted(style)
    }

    /// The start of the next local day: the widget redraws then, so yesterday's number never shows as today's.
    static func nextMidnight(after now: Date, timeZone: TimeZone = .current) -> Date {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = timeZone
        let start = local.startOfDay(for: now)
        return local.date(byAdding: .day, value: 1, to: start) ?? now.addingTimeInterval(86_400)
    }

    /// What VoiceOver reads: "GitHub 128 today, streak 90 days. Growth 3 today, streak 2 days."
    static func spoken(_ data: ActivityWidgetData, now: Date, timeZone: TimeZone = .current) -> String {
        var parts: [String] = []
        for (name, series) in [("GitHub", data.github), ("Growth", data.growth)] {
            guard let series else { continue }
            let number = today(series, data: data, now: now, timeZone: timeZone)
            let todayWords = number == "–" ? "not known today" : "\(series.todayCount) today"
            parts.append("\(name) \(todayWords), streak \(series.streak == 1 ? "1 day" : "\(series.streak) days").")
        }
        return parts.isEmpty ? "No activity yet. Open Teyla once." : parts.joined(separator: " ")
    }
}

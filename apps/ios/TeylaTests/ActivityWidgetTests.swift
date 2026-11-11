import XCTest

final class ActivityWidgetTests: XCTestCase {
    private let utc = TimeZone(identifier: "UTC")!

    private func at(_ iso: String) -> Date { ISO8601DateFormatter().date(from: iso)! }

    private func snapshotJSON(github: Bool) -> Data {
        let days = (0 ..< 10).map { i in #"{"day":"2026-11-\#(String(format: "%02d", 3 + i))","count":\#(i),"level":\#(i % 5)}"# }
        let gh = github ? #","github":{"start":"2026-11-02","days":[{"day":"2026-11-02","count":4,"level":1},{"day":"2026-11-12","count":128,"level":4}],"today_count":128,"streak":90}"# : ""
        let text = #"{"version":2,"generated":"2026-11-12T09:30:00Z","activity":{"today":"2026-11-12","start":"2026-11-03","days":[\#(days.joined(separator: ","))],"today_count":9,"streak":2\#(gh)}}"#
        return Data(text.utf8)
    }

    func testTheBridgeCarriesBothGridsAndTodaysNumbers() throws {
        let snapshot = try PhoneFormat.decodeSnapshot(snapshotJSON(github: true))
        let data = try XCTUnwrap(WidgetBridge.data(from: snapshot))
        XCTAssertEqual(data.day, "2026-11-12")
        XCTAssertEqual(data.growth?.todayCount, 9)
        XCTAssertEqual(data.growth?.levels.count, 10)
        XCTAssertEqual(data.github?.todayCount, 128)
        XCTAssertEqual(data.github?.streak, 90)
        XCTAssertEqual(data.github?.start, "2026-11-02")
    }

    func testAMacWithoutGhSendsNoGithubGrid() throws {
        let data = try XCTUnwrap(WidgetBridge.data(from: PhoneFormat.decodeSnapshot(snapshotJSON(github: false))))
        XCTAssertNil(data.github)
        XCTAssertEqual(ActivityWidgetLogic.today(data.github, data: data, now: at("2026-11-12T12:00:00Z"), timeZone: utc), "–")
    }

    func testTodaysNumberShowsOnlyOnTheSnapshotsDay() throws {
        let data = try XCTUnwrap(WidgetBridge.data(from: PhoneFormat.decodeSnapshot(snapshotJSON(github: true))))
        XCTAssertEqual(ActivityWidgetLogic.today(data.github, data: data, now: at("2026-11-12T23:59:00Z"), timeZone: utc), "128")
        XCTAssertEqual(ActivityWidgetLogic.today(data.github, data: data, now: at("2026-11-13T00:01:00Z"), timeZone: utc), "–")
        XCTAssertEqual(ActivityWidgetLogic.spoken(data, now: at("2026-11-12T12:00:00Z"), timeZone: utc),
                       "GitHub 128 today, streak 90 days. Growth 9 today, streak 2 days.")
    }

    func testColumnsStartOnMondayAndKeepTheNewestWeeks() {
        // 2026-11-04 is a Wednesday: two empty slots lead the first column.
        let series = WidgetSeries(start: "2026-11-04", levels: [1, 2, 3, 4, 9, -1, 0, 1], todayCount: 0, streak: 0)
        let columns = ActivityWidgetLogic.columns(series, weeks: 17)
        XCTAssertEqual(columns.count, 2)
        XCTAssertEqual(columns[0], [nil, nil, 1, 2, 3, 4, 4])
        XCTAssertEqual(columns[1], [0, 0, 1, nil, nil, nil, nil])
        XCTAssertEqual(ActivityWidgetLogic.columns(series, weeks: 1).count, 1)
        XCTAssertEqual(ActivityWidgetLogic.columns(WidgetSeries(start: "x", levels: [1], todayCount: 0, streak: 0), weeks: 3), [])
    }

    func testCompactNumbersFitBesideTheGrid() {
        XCTAssertEqual(ActivityWidgetLogic.compact(0), "0")
        XCTAssertEqual(ActivityWidgetLogic.compact(999), "999")
        XCTAssertEqual(ActivityWidgetLogic.compact(1000), "1k")
        XCTAssertEqual(ActivityWidgetLogic.compact(1250), "1.2k")
        XCTAssertEqual(ActivityWidgetLogic.compact(18_418), "18k")
    }

    func testTheStoreWritesOnlyWhenTheContentChanged() throws {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("widget-\(UUID().uuidString).json")
        defer { try? FileManager.default.removeItem(at: url) }
        let data = ActivityWidgetData(day: "2026-11-12", generated: at("2026-11-12T09:30:00Z"),
                                      growth: WidgetSeries(start: "2026-11-09", levels: [0, 1, 2, 3], todayCount: 3, streak: 1), github: nil)
        XCTAssertTrue(ActivityWidgetStore.write(data, to: url))
        XCTAssertFalse(ActivityWidgetStore.write(data, to: url))
        XCTAssertEqual(ActivityWidgetStore.read(from: url), data)
        var newer = data
        newer.growth?.todayCount = 4
        XCTAssertTrue(ActivityWidgetStore.write(newer, to: url))
        XCTAssertNil(ActivityWidgetStore.decode(Data(#"{"version":2,"day":"x","generated":0}"#.utf8)))
    }

    func testNextMidnightIsTheStartOfTomorrow() {
        XCTAssertEqual(ActivityWidgetLogic.nextMidnight(after: at("2026-11-12T15:00:00Z"), timeZone: utc), at("2026-11-13T00:00:00Z"))
    }
}

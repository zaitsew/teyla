import Foundation

/// Turns the signed snapshot's activity into what the home-screen widget draws. Counts and levels only: nothing else from the
/// snapshot reaches the App Group container. nil when the Mac sent no activity.
enum WidgetBridge {
    static func data(from snapshot: Snapshot) -> ActivityWidgetData? {
        guard let glimpse = snapshot.activity, !glimpse.days.isEmpty, let generated = snapshot.generatedDate else { return nil }
        let growth = WidgetSeries(start: glimpse.start.isEmpty ? glimpse.days[0].day : glimpse.start,
                                  levels: glimpse.days.map(\.level), todayCount: glimpse.todayCount, streak: glimpse.streak)
        var github: WidgetSeries?
        if let g = glimpse.github, !g.days.isEmpty {
            github = WidgetSeries(start: g.start.isEmpty ? g.days[0].day : g.start, levels: g.days.map(\.level),
                                  todayCount: g.todayCount, streak: g.streak)
        }
        let day = glimpse.today.isEmpty ? (glimpse.days.last?.day ?? "") : glimpse.today
        return ActivityWidgetData(day: day, generated: generated, growth: growth, github: github)
    }
}

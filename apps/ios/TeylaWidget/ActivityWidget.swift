import SwiftUI
import WidgetKit

// The activity widget (docs/APP.md, "The activity widget"): GitHub contributions and growth activity as two small grids, with
// today's number beside each. It reads `activity-widget.json` from the App Group, which the app writes after each signed
// snapshot; it reads nothing else and sends nothing.

struct ActivityEntry: TimelineEntry {
    let date: Date
    let data: ActivityWidgetData?
}

struct ActivityProvider: TimelineProvider {
    func placeholder(in context: Context) -> ActivityEntry { ActivityEntry(date: .now, data: .preview) }

    func getSnapshot(in context: Context, completion: @escaping (ActivityEntry) -> Void) {
        completion(ActivityEntry(date: .now, data: ActivityWidgetStore.read() ?? (context.isPreview ? .preview : nil)))
    }

    /// Now, and again at midnight: after midnight a snapshot from yesterday shows "–" for today, never yesterday's number.
    func getTimeline(in context: Context, completion: @escaping (Timeline<ActivityEntry>) -> Void) {
        let now = Date.now
        let data = ActivityWidgetStore.read()
        let midnight = ActivityWidgetLogic.nextMidnight(after: now)
        completion(Timeline(entries: [ActivityEntry(date: now, data: data), ActivityEntry(date: midnight, data: data)],
                            policy: .atEnd))
    }
}

struct ActivityWidget: Widget {
    var body: some WidgetConfiguration {
        StaticConfiguration(kind: ActivityWidgetStore.kind, provider: ActivityProvider()) { entry in
            ActivityWidgetView(entry: entry)
        }
        .configurationDisplayName("Activity")
        .description("GitHub contributions and growth activity, with today's number.")
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular, .accessoryInline])
    }
}

@main
struct TeylaWidgetBundle: WidgetBundle {
    var body: some Widget { ActivityWidget() }
}

// MARK: - Views

private enum Look {
    static let accent = Color(uiColor: UIColor { $0.userInterfaceStyle == .dark
        ? UIColor(red: 0x9A / 255, green: 0xA7 / 255, blue: 0xF2 / 255, alpha: 1)
        : UIColor(red: 0x3A / 255, green: 0x4A / 255, blue: 0xA8 / 255, alpha: 1) })
    static let empty = Color(uiColor: .tertiarySystemFill)
    static let opacities: [Double] = [0, 0.3, 0.5, 0.75, 1]

    static func fill(_ level: Int, accented: Bool) -> Color {
        guard level > 0 else { return accented ? Color.primary.opacity(0.15) : empty }
        let o = opacities[min(level, 4)]
        return accented ? Color.primary.opacity(0.25 + 0.75 * o) : accent.opacity(o)
    }
}

struct ActivityWidgetView: View {
    @Environment(\.widgetFamily) private var family
    @Environment(\.widgetRenderingMode) private var renderingMode
    let entry: ActivityEntry

    var body: some View {
        content
            .containerBackground(for: .widget) { Color(uiColor: .systemBackground) }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(entry.data.map { ActivityWidgetLogic.spoken($0, now: entry.date) } ?? "No activity yet. Open Teyla once.")
    }

    @ViewBuilder private var content: some View {
        if let data = entry.data {
            switch family {
            case .accessoryInline: inline(data)
            case .accessoryRectangular: rectangular(data)
            case .systemSmall: small(data)
            default: medium(data)
            }
        } else {
            empty
        }
    }

    private var empty: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Activity").font(.caption.weight(.semibold))
            Text("Open Teyla once to fill this widget.").font(.caption2).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func rows(_ data: ActivityWidgetData) -> [(name: String, series: WidgetSeries?)] {
        [("GitHub", data.github), ("Growth", data.growth)]
    }

    private func inline(_ data: ActivityWidgetData) -> some View {
        let gh = ActivityWidgetLogic.today(data.github, data: data, now: entry.date)
        let gr = ActivityWidgetLogic.today(data.growth, data: data, now: entry.date)
        return Text("GitHub \(gh) · Growth \(gr)")
    }

    private func rectangular(_ data: ActivityWidgetData) -> some View {
        VStack(alignment: .leading, spacing: 1) {
            Text("Today").font(.headline).widgetAccentable()
            ForEach(rows(data), id: \.name) { row in
                HStack {
                    Text(row.name)
                    Spacer()
                    Text(ActivityWidgetLogic.today(row.series, data: data, now: entry.date)).monospacedDigit().fontWeight(.semibold)
                }
                .font(.subheadline)
            }
        }
    }

    private func small(_ data: ActivityWidgetData) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(rows(data), id: \.name) { row in
                VStack(alignment: .leading, spacing: 3) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(row.name).font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
                        Spacer(minLength: 4)
                        Text(ActivityWidgetLogic.today(row.series, data: data, now: entry.date))
                            .font(.system(.title3, design: .rounded).weight(.semibold)).monospacedDigit()
                            .minimumScaleFactor(0.6).lineLimit(1)
                    }
                    grid(row.series, weeks: 10)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func medium(_ data: ActivityWidgetData) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(rows(data), id: \.name) { row in
                HStack(alignment: .center, spacing: 10) {
                    grid(row.series, weeks: 17)
                    VStack(alignment: .trailing, spacing: 0) {
                        Text(ActivityWidgetLogic.today(row.series, data: data, now: entry.date))
                            .font(.system(size: 26, weight: .semibold, design: .rounded)).monospacedDigit()
                            .minimumScaleFactor(0.5).lineLimit(1)
                        Text("\(row.name) today").font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                        if let series = row.series {
                            Text("streak \(series.streak)").font(.caption2).foregroundStyle(.tertiary).lineLimit(1)
                        }
                    }
                    .frame(minWidth: 70, alignment: .trailing)
                }
            }
            Text(ActivityWidgetLogic.updated(data, now: entry.date)).font(.system(size: 9)).foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    /// Seven rows, Monday at the top, the newest week at the right. The squares fill the height they get.
    @ViewBuilder private func grid(_ series: WidgetSeries?, weeks: Int) -> some View {
        let accented = renderingMode == .accented || renderingMode == .vibrant
        if let series {
            let columns = ActivityWidgetLogic.columns(series, weeks: weeks)
            GeometryReader { proxy in
                let gap: CGFloat = 1.5
                let byHeight = (proxy.size.height - gap * 6) / 7
                let byWidth = (proxy.size.width - gap * CGFloat(max(columns.count - 1, 0))) / CGFloat(max(columns.count, 1))
                let cell = max(min(byHeight, byWidth), 2)
                HStack(spacing: gap) {
                    ForEach(Array(columns.enumerated()), id: \.offset) { _, column in
                        VStack(spacing: gap) {
                            ForEach(0 ..< 7, id: \.self) { row in
                                RoundedRectangle(cornerRadius: cell * 0.22)
                                    .fill(column[row].map { Look.fill($0, accented: accented) } ?? .clear)
                                    .frame(width: cell, height: cell)
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
            }
        } else {
            Text("Not connected").font(.caption2).foregroundStyle(.tertiary)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        }
    }
}

extension ActivityWidgetData {
    /// The gallery preview: made-up numbers, never written anywhere.
    static var preview: ActivityWidgetData {
        let day = ActivityWidgetLogic.localDay(.now)
        func series(_ seed: Int, today: Int, streak: Int) -> WidgetSeries {
            var levels: [Int] = []
            for i in 0 ..< 17 * 7 { levels.append((i * seed + i / 5) % 5) }
            return WidgetSeries(start: "2026-07-20", levels: levels, todayCount: today, streak: streak)
        }
        return ActivityWidgetData(day: day, generated: .now, growth: series(3, today: 4, streak: 6),
                                  github: series(7, today: 128, streak: 90))
    }
}

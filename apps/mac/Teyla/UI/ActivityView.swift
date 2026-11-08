import SwiftUI

/// The activity graph at the top of Growth: the contribution graph GitHub shows, for posts, comments, emails and meetings.
/// Two layouts to compare on the device: `year` (53 weeks, small squares) and `quarter` (17 weeks, large squares, the streak as a
/// big number). Pick one with `defaults write com.zaitsew.teyla.local teyla.activity.layout quarter`.
/// The squares are decorative; VoiceOver reads the card as one line.
struct ActivityCard: View {
    @Environment(AppModel.self) private var model
    @AppStorage(ActivityLayout.key) private var layoutName = ActivityLayout.year.rawValue

    private var layout: ActivityLayout { ActivityLayout.stored(layoutName) }

    var body: some View {
        let growth = model.growth
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Activity", note: "Every post, comment, email and meeting counts as +1.") {
                ActivityPlusOne()
            }
            if let report = growth.activity {
                ActivityBody(report: report, layout: layout)
                if let why = growth.activityNote {
                    Text("The last read failed: \(why)").font(Typo.caption).foregroundStyle(Palette.danger)
                }
            } else if growth.activityOutdated {
                Text(growth.activityNote ?? ActivityLogic.updateMessage).font(Typo.body).foregroundStyle(Palette.textSecondary)
            } else if let why = growth.activityNote {
                ErrorRow(section: "the activity", message: why) { growth.loadActivity() }
            } else {
                ProgressView().controlSize(.small)
            }
        }
        .card()
        .onAppear { growth.loadActivity() }
    }
}

/// The "+1" button and its popover, with ⌘L. The Growth page and Today both show it, so ⌘L logs from either screen.
struct ActivityPlusOne: View {
    @Environment(AppModel.self) private var model
    @State private var showLog = false

    var body: some View {
        Button { showLog = true } label: { Label("+1", systemImage: "plus") }
            .keyboardShortcut("l", modifiers: .command)
            .disabled(model.growth.activityOutdated)
            .help("Log one activity (⌘L)")
            .accessibilityLabel("Log one activity")
            .popover(isPresented: $showLog, arrowEdge: .bottom) { ActivityLogForm(isPresented: $showLog) }
            .onAppear { model.growth.loadActivity() }
    }
}

private struct ActivityBody: View {
    let report: ActivityReport
    let layout: ActivityLayout

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            switch layout {
            case .year:
                ActivityGrid(report: report, layout: layout)
            case .quarter:
                HStack(alignment: .top, spacing: Space.xl) {
                    VStack(alignment: .leading, spacing: Space.xxs) {
                        Text("\(report.streak)").font(Typo.number)
                        Text("day streak").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                        Text("Today \(report.todayCount)").font(Typo.body).padding(.top, Space.s)
                    }
                    ActivityGrid(report: report, layout: layout)
                }
            }
            ActivityLegend()
            VStack(alignment: .leading, spacing: Space.xs) {
                Text(ActivityLogic.summary(report)).font(Typo.body)
                Text(ActivityLogic.outcomes(report)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                if let note = ActivityLogic.claimedNote(report) {
                    Text(note).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(ActivityLogic.spoken(report))
        }
    }
}

private struct ActivityGrid: View {
    let report: ActivityReport
    let layout: ActivityLayout

    var body: some View {
        let large = layout == .quarter
        let cell = large ? Space.activityCellLarge : Space.activityCell
        let gap = large ? Space.activityGapLarge : Space.activityGap
        let step = cell + gap
        let columns = ActivityLogic.columns(report.days, weeks: layout.weeks)
        let labels = ActivityLogic.monthLabels(columns, gap: large ? 2 : 3)
        let weekdayLabels = [0: "Mon", 2: "Wed", 4: "Fri"]
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(alignment: .top, spacing: Space.s) {
                VStack(alignment: .leading, spacing: gap) {
                    Color.clear.frame(width: Space.activityLabelColumn, height: Space.activityMonthRow)
                    ForEach(0 ..< 7, id: \.self) { row in
                        Color.clear.frame(width: Space.activityLabelColumn, height: cell)
                            .overlay(alignment: .leading) {
                                if let name = weekdayLabels[row] {
                                    Text(name).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize()
                                }
                            }
                    }
                }
                VStack(alignment: .leading, spacing: gap) {
                    ZStack(alignment: .topLeading) {
                        Color.clear.frame(height: Space.activityMonthRow)
                        ForEach(labels, id: \.column) { label in
                            Text(label.name).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize()
                                .offset(x: CGFloat(label.column) * step)
                        }
                    }
                    HStack(spacing: gap) {
                        ForEach(Array(columns.enumerated()), id: \.offset) { _, column in
                            VStack(spacing: gap) {
                                ForEach(0 ..< 7, id: \.self) { row in
                                    square(column.days[row], size: cell)
                                }
                            }
                        }
                    }
                }
            }
        }
        .defaultScrollAnchor(.trailing)
        .accessibilityHidden(true)
    }

    @ViewBuilder private func square(_ day: ActivityDay?, size: CGFloat) -> some View {
        if let day {
            RoundedRectangle(cornerRadius: Radius.bar)
                .fill(Palette.activityLevels[min(max(day.level, 0), Palette.activityLevels.count - 1)])
                .frame(width: size, height: size)
                .help(ActivityLogic.tooltip(day, kindOrder: report.kinds))
        } else {
            Color.clear.frame(width: size, height: size)
        }
    }
}

private struct ActivityLegend: View {
    var body: some View {
        HStack(spacing: Space.xs) {
            Text("Less").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            ForEach(0 ..< Palette.activityLevels.count, id: \.self) { level in
                RoundedRectangle(cornerRadius: Radius.bar).fill(Palette.activityLevels[level])
                    .frame(width: Space.activityCell, height: Space.activityCell)
            }
            Text("More").font(Typo.caption).foregroundStyle(Palette.textSecondary)
        }
        .accessibilityHidden(true)
    }
}

/// The "+1" popover: what kind, for which product, how many. Log runs `teyla growth log` and the graph is read again.
struct ActivityLogForm: View {
    @Environment(AppModel.self) private var model
    @Binding var isPresented: Bool
    @State private var kind: String
    @State private var product = ""
    @State private var count = 1

    /// `kind` is the one the form opens on; "Log a conversation" on Today opens it on "meeting".
    init(isPresented: Binding<Bool>, kind: String = "post") {
        _isPresented = isPresented
        _kind = State(initialValue: ActivityKind.isKnown(kind) ? kind : "post")
    }

    var body: some View {
        let growth = model.growth
        let kinds = growth.activity?.loggableKinds ?? ActivityKind.all
        let products = (model.snapshot?.products ?? []).map(\.name).filter(ProductCommands.isProductID)
        VStack(alignment: .leading, spacing: Space.m) {
            Text("Log activity").font(Typo.cardTitle)
            Picker("Kind", selection: $kind) {
                ForEach(kinds, id: \.self) { Text(ActivityKind.label($0)).tag($0) }
            }
            Picker("Product", selection: $product) {
                Text("No product").tag("")
                ForEach(products, id: \.self) { Text($0).tag($0) }
            }
            Stepper(value: $count, in: ActivityLog.countRange) { Text("Count: \(count)").font(Typo.body) }
            if let why = growth.logFailure {
                Text(why).font(Typo.caption).foregroundStyle(Palette.danger).fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: Space.s) {
                Spacer(minLength: Space.s)
                Button("Cancel") { isPresented = false }.keyboardShortcut(.cancelAction)
                Button("Log") {
                    growth.logActivity(kind: kind, product: product.isEmpty ? nil : product, count: count) { ok in
                        if ok { isPresented = false }
                    }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(growth.logging)
            }
        }
        .padding(Space.l)
        .frame(width: Space.logPopoverWidth)
        .onAppear {
            growth.clearLogFailure()
            if !kinds.contains(kind), let first = kinds.first { kind = first }
        }
    }
}

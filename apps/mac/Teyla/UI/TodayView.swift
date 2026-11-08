import AppKit
import SwiftUI

/// Today, the admin build's first screen, goal first: which outcome you work toward, how many real events came back this week
/// against its number, and the one thing to do next. It reads `teyla gtm today --json`.
///
/// Top to bottom: a quiet strip (Sent, Came back, Prepared), the goal that is furthest behind as a large card with one row of
/// circles per outcome target, the other goals as thin rows, then the activity graph, then the source checks. A circle fills
/// only for a real outcome that came back; a draft or a send never fills one. With no goal yet the page asks for one outcome
/// and one weekly number. Teyla never posts or sends from here: a button opens a page, or runs `teyla gtm goal`.
/// Keys: ⏎ does the primary action, ⌘R reads again, ⌘L logs a "+1".
struct TodayView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let page = model.todayPage
        Page {
            if let today = page.today {
                if today.goals.isEmpty {
                    TodayFirstRun(today: today, page: page)
                } else {
                    TodayHeader(page: page, today: today)
                    // A read that failed after a good one keeps the last report on screen; say so, with a retry.
                    if let why = page.note, !page.outdated {
                        ErrorRow(section: "Today", message: "\(why) The numbers below are from the last read.") { page.refresh() }
                    }
                    if let lead = TodayLogic.featured(today.goals) {
                        FeaturedGoalCard(today: today, goal: lead, page: page)
                    }
                    let others = TodayLogic.others(today.goals)
                    if !others.isEmpty { OtherGoalsCard(goals: others, page: page) }
                    ActivityCard()
                    TodayFooter(today: today)
                }
            } else {
                TodayHeader(page: page, today: nil)
                if page.outdated {
                    Text(page.note ?? TodayLogic.updateMessage).font(Typo.body).foregroundStyle(Palette.textSecondary)
                } else if let why = page.note {
                    ErrorRow(section: "Today", message: why) { page.refresh() }
                } else {
                    HStack(spacing: Space.s) {
                        ProgressView().controlSize(.small)
                        Text("Reading Today…").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    }
                }
            }
        }
        .navigationTitle("Today")
        .onAppear { model.todayPage.opened() }
    }
}

// MARK: Header and the quiet strip

private struct TodayHeader: View {
    @Environment(AppModel.self) private var model
    let page: TodayModel
    let today: GtmToday?

    private var controls: some View {
        HStack(spacing: Space.m) {
            if page.isLoading { ProgressView().controlSize(.small) }
            ActivityPlusOne()
            Button { page.refresh(); model.growth.refresh() } label: { Label("Refresh", systemImage: "arrow.clockwise") }
                .keyboardShortcut("r", modifiers: .command)
                .disabled(page.isLoading)
                .help("Read again (⌘R)")
                .accessibilityLabel("Refresh Today")
        }
    }

    var body: some View {
        let context = TodayLogic.contextLine(today)
        ViewThatFits(in: .horizontal) {
            PageHeader(title: "Today", context: context) {
                HStack(spacing: Space.xl) {
                    if let today { TodayStrip(today: today) }
                    controls
                }
            }
            VStack(alignment: .leading, spacing: Space.m) {
                PageHeader(title: "Today", context: context) { controls }
                if let today { TodayStrip(today: today) }
            }
        }
    }
}

/// Sent today as ticks, what came back and waits, what agents prepared. One quiet line; Prepared is agent work, so it is never
/// drawn in the accent colour.
private struct TodayStrip: View {
    let today: GtmToday

    var body: some View {
        HStack(spacing: Space.l) {
            HStack(spacing: Space.s) {
                Text("Sent")
                if let ticks = TodayLogic.sentTicks(today.distribution) {
                    HStack(spacing: Space.xxs) {
                        ForEach(0 ..< ticks.total, id: \.self) { index in
                            RoundedRectangle(cornerRadius: Radius.bar)
                                .fill(index < ticks.filled ? Palette.text : Palette.track)
                                .frame(width: Space.tick, height: Space.tick)
                        }
                    }
                }
                Text(TodayLogic.distributionFigure(today.distribution)).fontWeight(.semibold).foregroundStyle(Palette.text)
            }
            rule
            HStack(spacing: Space.xs) {
                Text("Came back")
                Text(TodayLogic.cameBackWords(today)).fontWeight(.semibold).foregroundStyle(Palette.text)
            }
            rule
            HStack(spacing: Space.xs) {
                Text("Prepared")
                Text("\(TodayLogic.prepared(today))").fontWeight(.semibold)
            }
        }
        .font(Typo.caption.monospacedDigit())
        .foregroundStyle(Palette.textSecondary)
        .lineLimit(1)
        .fixedSize()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(TodayLogic.stripSpoken(today))
    }

    private var rule: some View {
        Rectangle().fill(Palette.border).frame(width: Space.hairline, height: Space.l)
    }
}

// MARK: The featured goal

/// The goal furthest behind this week: its title, how it stands, one row of circles per outcome target, and what to do next.
private struct FeaturedGoalCard: View {
    @Environment(AppModel.self) private var model
    let today: GtmToday
    let goal: GtmGoal
    let page: TodayModel
    @State private var showLog = false
    @State private var showDetail = false

    var body: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            HStack(alignment: .top, spacing: Space.xl) {
                VStack(alignment: .leading, spacing: Space.xs) {
                    Button { showDetail = true } label: {
                        Text(goal.title).font(Typo.section).multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityHint("Shows the goal's weeks and where its counts come from")
                    .help("Open this goal")
                    Text(TodayLogic.goalMeta(goal)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
                Spacer(minLength: Space.m)
                if let pace = TodayLogic.pace(goal) { PaceChip(pace: pace) }
            }
            if goal.outcomeTargets.isEmpty {
                Text("No weekly number is set for this goal.").font(Typo.body).foregroundStyle(Palette.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: Space.s) {
                    ForEach(goal.outcomeTargets, id: \.stage) { target in BeadRow(target: target) }
                }
            }
            Divider()
            next
        }
        .surface(radius: Radius.panel, padding: Space.xl)
        .accessibilityElement(children: .contain)
        .sheet(isPresented: $showDetail) { GoalSheet(goal: goal, page: page) }
    }

    @ViewBuilder private var next: some View {
        let step = TodayLogic.nextStep(today)
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: Space.l) {
                nextText(step)
                Spacer(minLength: Space.m)
                actions(step)
            }
            VStack(alignment: .leading, spacing: Space.m) {
                nextText(step)
                HStack(spacing: Space.l) { actions(step) }
            }
        }
    }

    private func nextText(_ step: TodayLogic.NextStep?) -> some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text("Next for this goal").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            if let step {
                Text(step.title).font(Typo.cardTitle).fixedSize(horizontal: false, vertical: true)
                if let detail = step.detail { Text(detail).font(Typo.caption).foregroundStyle(Palette.textSecondary) }
            } else {
                Text("Nothing waits for you.").font(Typo.cardTitle)
                Text("Log a conversation when one happens; it fills a circle.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        }
    }

    @ViewBuilder private func actions(_ step: TodayLogic.NextStep?) -> some View {
        Button("Log a conversation") { showLog = true }
            .buttonStyle(.link)
            .help("Log a meeting as +1 (it fills a circle when the goal counts conversations)")
            .popover(isPresented: $showLog, arrowEdge: .bottom) { ActivityLogForm(isPresented: $showLog, kind: "meeting") }
        if let step {
            Button { perform(step) } label: { KeyLabel(title: step.button, key: "⏎") }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .keyboardShortcut(.defaultAction)
                .help(step.link == nil ? "Open Growth" : "Open the page of the source")
        }
    }

    private func perform(_ step: TodayLogic.NextStep) {
        if let link = step.link { NSWorkspace.shared.open(link) } else { model.go(.growth) }
    }
}

/// One outcome target: its name, one circle per unit, and "1 of 15". VoiceOver reads the row as one sentence.
private struct BeadRow: View {
    let target: GtmTarget

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.l) {
            Text(TodayLogic.stageLabel(target.stage)).font(Typo.body).frame(width: Space.beadLabel, alignment: .leading)
            GoalBeads(target: target).frame(maxWidth: .infinity, alignment: .leading)
            Text(TodayLogic.targetWords(target)).font(Typo.body.weight(.semibold).monospacedDigit())
                .frame(width: Space.beadCount, alignment: .trailing)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(TodayLogic.beadsSpoken(target))
    }
}

/// "KeyLabel": a button title with its key as a small cap.
private struct KeyLabel: View {
    let title: String
    let key: String

    var body: some View {
        HStack(spacing: Space.s) {
            Text(title)
            Text(key)
                .font(Typo.caption.weight(.semibold).monospaced())
                .padding(.horizontal, Space.xs)
                .background(Palette.onPrimary.opacity(0.22), in: RoundedRectangle(cornerRadius: Radius.bar))
                .accessibilityHidden(true)
        }
    }
}

// MARK: The other goals

/// The other goals as thin rows: circles for the first outcome target, or a question when there is no number yet.
private struct OtherGoalsCard: View {
    let goals: [GtmGoal]
    let page: TodayModel

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(goals.enumerated()), id: \.element.id) { index, goal in
                if index > 0 { Divider() }
                OtherGoalRow(goal: goal, page: page)
            }
        }
        .padding(.horizontal, Space.xl)
        .surface(padding: 0)
    }
}

private struct OtherGoalRow: View {
    let goal: GtmGoal
    let page: TodayModel
    @State private var setting = false

    var body: some View {
        HStack(alignment: .center, spacing: Space.l) {
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(goal.title).font(Typo.cardTitle).lineLimit(2)
                Text(TodayLogic.goalMeta(goal)).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
            }
            .frame(maxWidth: Space.goalTitleColumn, alignment: .leading)
            if let target = TodayLogic.rowTarget(goal) {
                GoalBeads(target: target).frame(maxWidth: .infinity, alignment: .leading)
                Text(TodayLogic.rowCount(goal, target: target)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.trailing)
                    .frame(maxWidth: Space.goalCountColumn, alignment: .trailing)
            } else {
                Text("What would count as progress this week?").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button("Set a number") { setting = true }
                    .popover(isPresented: $setting, arrowEdge: .bottom) { SetNumberForm(goal: goal, page: page, isPresented: $setting) }
            }
        }
        .frame(minHeight: Space.thinRow)
        .accessibilityElement(children: TodayLogic.rowTarget(goal) == nil ? .contain : .ignore)
        .accessibilityLabel(rowSpoken)
    }

    private var rowSpoken: String {
        guard let target = TodayLogic.rowTarget(goal) else { return "\(goal.title). No weekly number yet." }
        return "\(goal.title). \(TodayLogic.beadsSpoken(target))\(goal.fedBy.isEmpty && !goal.unfed.isEmpty ? ", source not connected" : "")."
    }
}

/// The small form behind "Set a number" and "Change numbers": which stage counts, and how many a week. It runs
/// `teyla gtm goal set <id> --weekly stage=N`.
private struct SetNumberForm: View {
    let goal: GtmGoal
    let page: TodayModel
    @Binding var isPresented: Bool
    @State private var stage: String
    @State private var count: Int

    init(goal: GtmGoal, page: TodayModel, isPresented: Binding<Bool>) {
        self.goal = goal
        self.page = page
        _isPresented = isPresented
        let target = TodayLogic.rowTarget(goal)
        _stage = State(initialValue: target?.stage ?? "conversation")
        _count = State(initialValue: target.map { max($0.target, GtmGoalCommands.countRange.lowerBound) } ?? TodayLogic.defaultWeekly)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Text("A weekly number").font(Typo.cardTitle)
            Text(goal.title).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(2)
            Picker("What counts", selection: $stage) {
                ForEach(TodayLogic.stageOptions(current: stage), id: \.self) { Text(TodayLogic.stageLabel($0)).tag($0) }
            }
            Stepper(value: $count, in: GtmGoalCommands.countRange) { Text("\(count) a week").font(Typo.body.monospacedDigit()) }
            if let why = page.goalFailure {
                Text(why).font(Typo.caption).foregroundStyle(Palette.danger).fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: Space.s) {
                if page.goalBusy { ProgressView().controlSize(.small) }
                Spacer(minLength: Space.s)
                Button("Cancel") { isPresented = false }.keyboardShortcut(.cancelAction)
                Button("Save") {
                    // A different stage replaces the old number; `goal set` merges, so the old one is sent as 0.
                    let old = TodayLogic.rowTarget(goal)?.stage
                    page.setWeekly(goalID: goal.id, stage: stage, count: count, replacing: old) { ok in if ok { isPresented = false } }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(page.goalBusy)
            }
        }
        .padding(Space.l)
        .frame(width: Space.numberPopoverWidth)
        .onAppear { page.clearGoalFailure() }
    }
}

// MARK: The goal's detail

/// A goal in full: the weeks to its deadline, the last eight weeks of each outcome, and where the counts come from.
private struct GoalSheet: View {
    @Environment(\.dismiss) private var dismiss
    let goal: GtmGoal
    let page: TodayModel
    @State private var changing = false

    var body: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xs) {
                    Text(goal.title).font(Typo.section).fixedSize(horizontal: false, vertical: true).accessibilityAddTraits(.isHeader)
                    Text(TodayLogic.goalMeta(goal)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
                Spacer(minLength: Space.m)
                Button("Change numbers") { changing = true }
                    .popover(isPresented: $changing, arrowEdge: .bottom) { SetNumberForm(goal: goal, page: page, isPresented: $changing) }
                Button("Done") { dismiss() }.keyboardShortcut(.cancelAction)
            }
            weeks
            if !goal.outcomeTargets.isEmpty { history }
            sources
        }
        .padding(Space.xl)
        .frame(width: Space.goalSheetWidth)
    }

    @ViewBuilder private var weeks: some View {
        if let count = TodayLogic.weekSquares(weeksLeft: goal.weeksLeft) {
            VStack(alignment: .leading, spacing: Space.s) {
                if let words = TodayLogic.weeksToWords(goal) { Text(words).font(Typo.caption).foregroundStyle(Palette.textSecondary) }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: Space.tick, maximum: Space.tick), spacing: Space.xs)], alignment: .leading, spacing: Space.xs) {
                    ForEach(0 ..< count, id: \.self) { index in
                        RoundedRectangle(cornerRadius: Radius.bar).fill(index == 0 ? Palette.text : Palette.track)
                            .frame(width: Space.tick, height: Space.tick)
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(TodayLogic.weeksToWords(goal).map { "\($0), this week is the first" } ?? "Weeks left")
                Text("Outlook not assessed: weekly counts cannot predict a deal.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        } else {
            Text("Outlook not assessed: weekly counts cannot predict a deal.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
        }
    }

    private var history: some View {
        let weeks = goal.outcomeTargets.first?.history ?? []
        return VStack(alignment: .leading, spacing: Space.s) {
            HStack {
                Text("Last 8 weeks").font(Typo.cardTitle)
                Spacer(minLength: Space.m)
                Text("Darker means closer to the weekly number.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            if weeks.isEmpty {
                Text("This version of the teyla command sends no history.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            } else {
                Grid(alignment: .center, horizontalSpacing: Space.xs, verticalSpacing: Space.xs) {
                    GridRow {
                        Color.clear.frame(width: Space.historyWeekLabel, height: 0)
                        ForEach(Array(weeks.enumerated()), id: \.offset) { _, week in
                            Text(TodayLogic.weekShort(week.week)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                        }
                        Text("target").font(Typo.caption).foregroundStyle(Palette.textSecondary).gridColumnAlignment(.trailing)
                    }
                    ForEach(goal.outcomeTargets, id: \.stage) { target in
                        GridRow {
                            Text(TodayLogic.stageLabel(target.stage)).font(Typo.body).frame(width: Space.historyWeekLabel, alignment: .leading)
                            ForEach(Array(target.history.enumerated()), id: \.offset) { index, week in
                                cell(week, target: target, current: index == target.history.count - 1)
                            }
                            Text("\(target.target)").font(Typo.caption.monospacedDigit()).foregroundStyle(Palette.textSecondary)
                        }
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(spoken(target))
                    }
                }
            }
        }
        .surface(padding: Space.l)
    }

    private func cell(_ week: GtmWeek, target: GtmTarget, current: Bool) -> some View {
        let level = TodayLogic.cellLevel(count: week.count, target: target.target)
        let fill: Color = switch level {
        case nil: Palette.activityLevels[0]
        case 0: Palette.activityLevels[0]
        case 1: Palette.activityLevels[1]
        case 2: Palette.activityLevels[2]
        default: Palette.activityLevels[4]
        }
        return Text(week.count.map(String.init) ?? "–")
            .font(Typo.caption.weight(.semibold).monospacedDigit())
            .foregroundStyle(level == 3 ? Palette.onPrimary : level == nil ? Palette.textSecondary : Palette.text)
            .frame(maxWidth: .infinity, minHeight: Space.historyCell)
            .background(fill, in: RoundedRectangle(cornerRadius: Radius.bar))
            .overlay {
                if current { RoundedRectangle(cornerRadius: Radius.bar).strokeBorder(Palette.text, lineWidth: Space.hairline) }
            }
    }

    private func spoken(_ target: GtmTarget) -> String {
        let counts = target.history.map { $0.count.map(String.init) ?? "no run saved" }.joined(separator: ", ")
        return "\(TodayLogic.stageLabel(target.stage)), the last eight weeks: \(counts). The weekly number is \(target.target)."
    }

    private var sources: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Where counts come from").font(Typo.cardTitle)
            if goal.fedBy.isEmpty && goal.unfed.isEmpty {
                Text("No source is named for this goal. Log by hand with +1.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            ForEach(goal.fedBy, id: \.self) { id in
                HStack {
                    Text(TodayLogic.sourceName(id)).font(Typo.body)
                    Spacer(minLength: Space.m)
                    Text("feeding this goal").font(Typo.caption).foregroundStyle(Palette.saving)
                }
            }
            ForEach(goal.unfed, id: \.self) { id in
                HStack {
                    Text(TodayLogic.sourceName(id)).font(Typo.body)
                    Spacer(minLength: Space.m)
                    Text("not connected").font(Typo.caption).foregroundStyle(Palette.needsYou)
                }
            }
        }
        .surface(padding: Space.l)
    }
}

// MARK: First run

/// With no goal: one outcome, one weekly number, and a note that sources can wait. It runs `teyla gtm goal add`.
private struct TodayFirstRun: View {
    let today: GtmToday
    let page: TodayModel
    @State private var step = 1
    @State private var title = ""
    @State private var stage = "conversation"
    @State private var doneWhen = ""
    @State private var hasDeadline = false
    @State private var deadline = Calendar.current.date(byAdding: .month, value: 4, to: Date()) ?? Date()
    @State private var weekly = TodayLogic.defaultWeekly
    @State private var perDay = TodayLogic.defaultPerDay

    private var titleOK: Bool { GtmGoalCommands.line(title) != nil }
    private var deadlineText: String? { hasDeadline ? GtmGoalCommands.dateString(deadline) : nil }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            VStack(alignment: .leading, spacing: Space.xs) {
                Text("What should this work lead to?").font(Typo.pageTitle).accessibilityAddTraits(.isHeader)
                Text("Name one outcome and one weekly number. Today will then show how close you are and what moves it.")
                    .font(Typo.body).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
            }
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: Space.xl) {
                    form.frame(minWidth: Space.setupFormMin, maxWidth: .infinity)
                    preview.frame(minWidth: Space.setupPreviewMin, maxWidth: .infinity)
                }
                VStack(alignment: .leading, spacing: Space.xl) {
                    form
                    preview
                }
            }
        }
    }

    // MARK: The steps

    private var form: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            steps
            VStack(alignment: .leading, spacing: Space.m) {
                switch step {
                case 1: outcomeStep
                case 2: numberStep
                default: sourcesStep
                }
            }
            .surface(radius: Radius.panel, padding: Space.xl)
        }
    }

    private var steps: some View {
        HStack(spacing: Space.l) {
            ForEach(Array(["Outcome", "Weekly number", "Sources"].enumerated()), id: \.offset) { index, name in
                let current = index + 1 == step
                HStack(spacing: Space.s) {
                    Text("\(index + 1)")
                        .font(Typo.caption.weight(.semibold))
                        .foregroundStyle(current ? Palette.onPrimary : Palette.text)
                        .frame(width: Space.stepBadge, height: Space.stepBadge)
                        .background(current ? Palette.primary : Palette.track, in: Circle())
                    Text(name).font(Typo.body.weight(current ? .semibold : .regular))
                        .foregroundStyle(current ? Palette.text : Palette.textSecondary)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Step \(index + 1) of 3: \(name)\(current ? ", current" : "")")
            }
        }
    }

    private var outcomeStep: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Text("The outcome, in your words").font(Typo.cardTitle)
            TextField("For example: conversations that lead to paying customers", text: $title)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("The outcome, in your words")
            HStack(spacing: Space.s) {
                Text("Or start from").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                ForEach(TodayLogic.starters) { starter in
                    Button(starter.name) { title = starter.title; stage = starter.stage }
                        .buttonStyle(.bordered)
                        .tint(title == starter.title ? Palette.primary : nil)
                        .controlSize(.small)
                }
            }
            HStack(alignment: .bottom, spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xs) {
                    Text("Done when (optional)").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    TextField("What reaching it means", text: $doneWhen).textFieldStyle(.roundedBorder)
                        .accessibilityLabel("Done when, optional")
                }
                VStack(alignment: .leading, spacing: Space.xs) {
                    Toggle("By (optional)", isOn: $hasDeadline).font(Typo.caption).toggleStyle(.checkbox)
                    DatePicker("Deadline", selection: $deadline, in: Date()..., displayedComponents: .date)
                        .labelsHidden()
                        .disabled(!hasDeadline)
                }
            }
            HStack(spacing: Space.m) {
                Button("Continue") { step = 2 }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
                    .disabled(!titleOK)
                Text("Step 2 asks for one weekly count. Step 3 can wait: you can log by hand.")
                    .font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var numberStep: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Text("One weekly number").font(Typo.cardTitle)
            Text("What should come back each week? Count only real events that came back, not drafts or sends.")
                .font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
            Picker("What counts", selection: $stage) {
                ForEach(TodayLogic.stageOptions(current: stage), id: \.self) { Text(TodayLogic.stageLabel($0)).tag($0) }
            }
            Stepper(value: $weekly, in: GtmGoalCommands.countRange) { Text("\(weekly) a week").font(Typo.body.monospacedDigit()) }
            if !today.hasGoals {
                Divider()
                Text("Daily send target").font(Typo.cardTitle)
                Text("How many posts or approaches you aim to send each day. It fills the Sent ticks.")
                    .font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
                Stepper(value: $perDay, in: GtmGoalCommands.perDayRange) { Text("\(perDay) a day").font(Typo.body.monospacedDigit()) }
            }
            HStack(spacing: Space.m) {
                Button("Back") { step = 1 }
                Button("Continue") { step = 3 }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
            }
        }
    }

    private var sourcesStep: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            Text("Sources").font(Typo.cardTitle)
            Text("You can connect sources later. Until then, log by hand with +1; the sources are described in docs/GTM.md.")
                .font(Typo.body).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
            if let why = page.goalFailure {
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Palette.danger)
                    VStack(alignment: .leading, spacing: Space.xxs) {
                        Text("That did not work. Nothing changed.").font(Typo.body.weight(.semibold))
                        ClampedText(text: why, lines: 4, font: Typo.caption)
                    }
                }
            }
            HStack(spacing: Space.m) {
                Button("Back") { step = 2 }.disabled(page.goalBusy)
                Button { create() } label: { Text("Create goal") }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
                    .disabled(page.goalBusy || page.goalCreated || !titleOK)
                if page.goalBusy { ProgressView().controlSize(.small) }
            }
        }
        .onAppear { page.clearGoalFailure() }
    }

    private func create() {
        page.addGoal(title: title, weekly: [GtmWeeklyNumber(stage: stage, count: weekly)], deadline: deadlineText,
                     doneWhen: doneWhen, perDay: today.hasGoals ? nil : perDay)
    }

    // MARK: The preview

    private var preview: some View {
        let goal = GtmGoal(id: "new", title: GtmGoalCommands.line(title) ?? "Your outcome", doneWhen: GtmGoalCommands.line(doneWhen),
                           deadline: deadlineText)
        return VStack(alignment: .leading, spacing: Space.s) {
            Text("Preview on Today").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            VStack(alignment: .leading, spacing: Space.m) {
                Text(goal.title).font(Typo.cardTitle).fixedSize(horizontal: false, vertical: true)
                Text(TodayLogic.goalMeta(goal)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                HStack(alignment: .firstTextBaseline, spacing: Space.l) {
                    Text(TodayLogic.stageLabel(stage)).font(Typo.body).frame(width: Space.beadLabel, alignment: .leading)
                    if step >= 2 {
                        GoalBeads(target: GtmTarget(stage: stage, count: 0, target: weekly)).frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        Spacer(minLength: Space.s)
                    }
                    Text(step >= 2 ? "0 of \(weekly)" : "0 of ?").font(Typo.body.weight(.semibold).monospacedDigit())
                }
                Text("Each circle is one real event that came back: a conversation, an intro, a sign-up. Drafts and sends never fill one.")
                    .font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
            }
            .surface(radius: Radius.panel, padding: Space.xl)
            .accessibilityElement(children: .combine)
        }
    }
}

// MARK: The footer

/// Sources that did not answer cleanly, and the folded checks behind them.
private struct TodayFooter: View {
    let today: GtmToday

    var body: some View {
        let down = TodayLogic.sourcesNotOK(today)
        VStack(alignment: .leading, spacing: Space.s) {
            if down > 0 {
                HStack(spacing: Space.s) {
                    Circle().fill(Palette.needsYou).frame(width: Space.dot, height: Space.dot).accessibilityHidden(true)
                    Text(TodayLogic.sourcesWords(down)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
                .accessibilityElement(children: .combine)
            }
            TodayDoctor(today: today)
        }
    }
}

/// The source and goals-file problems, folded: they matter when a number looks wrong, not every day.
private struct TodayDoctor: View {
    let today: GtmToday
    @State private var open = false

    var body: some View {
        let problems = today.sources.filter { $0.state != "ok" }
        if !today.doctor.isEmpty || !problems.isEmpty {
            DisclosureGroup(isExpanded: $open) {
                VStack(alignment: .leading, spacing: Space.xs) {
                    ForEach(today.doctor, id: \.self) { line in
                        Text(line).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
                    }
                    ForEach(problems) { source in
                        Text("\(TodayLogic.sourceName(source.id)): \(TodayLogic.sourceState(source.state)). \(source.line)")
                            .font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(.top, Space.s)
                .frame(maxWidth: .infinity, alignment: .leading)
            } label: {
                Text("Checks · \(today.doctor.count + problems.count)").font(Typo.cardTitle)
            }
            .accessibilityLabel("Source checks, \(today.doctor.count + problems.count) lines. \(open ? "Expanded" : "Folded")")
        }
    }
}

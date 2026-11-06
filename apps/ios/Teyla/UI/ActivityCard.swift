import SwiftUI

/// The activity graph on the Growth tab: the last 17 weeks the Mac sent (counts only), today and the streak, and a "+1" that asks the
/// Mac to log one. The squares are decorative; VoiceOver reads the card as "Activity: N today, streak S days, T this year".
/// An older Mac sends no `activity`, and the card is hidden.
struct ActivityCard: View {
    @Environment(AppModel.self) private var model
    @State private var picking = false

    var body: some View {
        if let glimpse = model.snapshot?.activity, !glimpse.days.isEmpty {
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: "Activity", note: "Every post, comment, email and meeting counts as +1.") {
                    Button { picking = true } label: { Label("+1", systemImage: "plus") }
                        .buttonStyle(.bordered)
                        .frame(minHeight: Space.touchMin)
                        .accessibilityLabel("Log one activity")
                }
                VStack(alignment: .leading, spacing: Space.m) {
                    ActivityGridView(glimpse: glimpse)
                    HStack(alignment: .firstTextBaseline, spacing: Space.l) {
                        figure("\(glimpse.todayCount)", "today")
                        figure("\(glimpse.streak)", "day streak")
                        figure("\(glimpse.total)", "this year")
                    }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(glimpse.spoken)
                if let result = model.activityResult {
                    ActivityResultRow(action: result)
                }
            }
            .card()
            .sheet(isPresented: $picking) { ActivityKindPicker(kinds: glimpse.loggableKinds, isPresented: $picking) }
        }
    }

    private func figure(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(value).font(Typo.number)
            Text(label).font(Typo.caption).foregroundStyle(Palette.textSecondary)
        }
    }
}

/// 17 columns of 7 squares, Monday first, the newest week last. The square size follows the width the card has.
private struct ActivityGridView: View {
    let glimpse: ActivityGlimpse
    @State private var width: CGFloat = 0

    var body: some View {
        let columns = ActivityLogic.columns(glimpse.days, weeks: 17)
        let gap = Space.activityGap
        let count = CGFloat(max(columns.count, 1))
        let room = width - Space.activityLabelColumn - gap * count
        let cell = min(max(room / count, Space.activityCellMin), Space.activityCellMax)
        let step = cell + gap
        let labels = ActivityLogic.monthLabels(columns, gap: 3)
        let weekdayLabels = [0: "Mon", 2: "Wed", 4: "Fri"]
        VStack(alignment: .leading, spacing: gap) {
            HStack(alignment: .top, spacing: gap) {
                VStack(alignment: .leading, spacing: gap) {
                    Color.clear.frame(width: Space.activityLabelColumn, height: Space.activityMonthRow)
                    ForEach(0 ..< 7, id: \.self) { row in
                        Color.clear.frame(width: Space.activityLabelColumn, height: cell)
                            .overlay(alignment: .leading) {
                                if let name = weekdayLabels[row] {
                                    Text(name).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize()
                                        .minimumScaleFactor(0.7)
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
            HStack(spacing: Space.xs) {
                Text("Less").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                ForEach(0 ..< Palette.activityLevels.count, id: \.self) { level in
                    RoundedRectangle(cornerRadius: Radius.bar).fill(Palette.activityLevels[level])
                        .frame(width: Space.activityLegend, height: Space.activityLegend)
                }
                Text("More").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .onGeometryChange(for: CGFloat.self, of: \.size.width) { width = $0 }
        .accessibilityHidden(true)
    }

    @ViewBuilder private func square(_ day: ActivityDay?, size: CGFloat) -> some View {
        if let day {
            RoundedRectangle(cornerRadius: Radius.bar)
                .fill(Palette.activityLevels[min(max(day.level, 0), Palette.activityLevels.count - 1)])
                .frame(width: size, height: size)
        } else {
            Color.clear.frame(width: size, height: size)
        }
    }
}

/// What the Mac said about the last "+1": waiting, done, or the reason it refused (an older Mac says "malformed entry").
private struct ActivityResultRow: View {
    @Environment(AppModel.self) private var model
    let action: PendingAction

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            Image(systemName: symbol).foregroundStyle(tone).accessibilityHidden(true)
            Text(words).font(Typo.caption).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: Space.s)
            if action.outcome != nil {
                Button("Dismiss") { model.dismiss(action.id) }.font(Typo.caption)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var symbol: String {
        guard let outcome = action.outcome else { return "clock" }
        return outcome.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
    }

    private var tone: Color {
        guard let outcome = action.outcome else { return Palette.textSecondary }
        return outcome.ok ? Palette.saving : Palette.danger
    }

    private var words: String { ActivityLogic.resultWords(label: action.label, ok: action.outcome?.ok, detail: action.outcome?.detail ?? "") }
}

/// The kinds, one tap each. The entry is signed and written to the relay folder; the Mac logs it on its next pass.
private struct ActivityKindPicker: View {
    @Environment(AppModel.self) private var model
    let kinds: [String]
    @Binding var isPresented: Bool

    var body: some View {
        NavigationStack {
            List(kinds, id: \.self) { kind in
                Button {
                    Task {
                        if await model.logActivity(kind: kind) { isPresented = false }
                    }
                } label: {
                    Text(ActivityKind.label(kind)).font(Typo.body).frame(maxWidth: .infinity, minHeight: Space.touchMin, alignment: .leading)
                }
                .disabled(model.isSending(.activity, target: kind))
            }
            .navigationTitle("Log activity")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { isPresented = false } } }
            .safeAreaInset(edge: .bottom) {
                if let why = model.sendError {
                    Text(why).font(Typo.caption).foregroundStyle(Palette.danger).padding(Space.l)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

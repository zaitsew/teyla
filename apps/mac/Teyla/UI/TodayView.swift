import AppKit
import SwiftUI

/// Today, the admin build's first screen: what waits for you, did enough go out, which goal moved.
/// It reads `teyla gtm today --json` and the drafts the Growth page already reads. It never posts or sends: Approve only
/// marks a draft, and Open hands you to the item's own page. No commit count appears here.
///
/// Two layouts to compare on the device (STANDARD R18); pick one with
/// `defaults write com.zaitsew.teyla.local teyla.today.layout queue|board`.
///   queue  the next item is the screen: the selected draft large, the next actions beside it, the numbers in a strip.
///   board  the numbers are the screen: three counters, goal progress, the queue as a list below.
/// Keys: ↑/↓ or K/J move the selected draft, A approves, S skips, O opens, ⌘R reads again, ⌘L logs a "+1".
struct TodayView: View {
    @Environment(AppModel.self) private var model
    @AppStorage(TodayLayout.key) private var layoutName = TodayLayout.queue.rawValue
    @State private var selected: String?
    @FocusState private var focused: Bool

    private var layout: TodayLayout { TodayLayout.stored(layoutName) }
    private var drafts: [GrowthDraft] { model.growth.drafts }
    private var ids: [String] { drafts.map(\.id) }
    private var current: GrowthDraft? { drafts.first { $0.id == selected } ?? drafts.first }

    var body: some View {
        let page = model.todayPage
        Page {
            header(page)
            if let today = page.today {
                switch layout {
                case .queue: QueueLayout(today: today, selection: $selected)
                case .board: BoardLayout(today: today, selection: $selected)
                }
                TodayDoctor(today: today)
            } else if page.outdated {
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
        .navigationTitle("Today")
        .focusable()
        .focusEffectDisabled()
        .focused($focused)
        .onKeyPress(phases: .down) { press in handle(press) }
        .onAppear {
            focused = true
            model.todayPage.opened()
            model.growth.opened()
            selected = TodayLogic.settled(selected: selected, old: ids, new: ids)
        }
        .onChange(of: ids) { old, new in selected = TodayLogic.settled(selected: selected, old: old, new: new) }
    }

    private func header(_ page: TodayModel) -> some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            PageHeader(title: "Today", context: contextLine(page, now: context.date)) {
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
        }
    }

    private func contextLine(_ page: TodayModel, now: Date) -> String {
        let day = page.today.map { $0.day.isEmpty ? "" : $0.day } ?? ""
        let updated = TodayLogic.updated(readAt: page.readAt, now: now)
        return day.isEmpty ? updated : "\(day) · \(updated)"
    }

    // MARK: Keys

    private func handle(_ press: KeyPress) -> KeyPress.Result {
        // ⌘R and ⌘L are menu-style shortcuts of their own buttons; the letters work bare.
        guard press.modifiers.isEmpty || press.modifiers == .shift else { return .ignored }
        let action: TodayAction?
        switch press.key {
        case .upArrow: action = .previous
        case .downArrow: action = .next
        default: action = TodayLogic.action(for: press.characters)
        }
        guard let action else { return .ignored }
        switch action {
        case .previous, .next:
            let at = current.flatMap { draft in ids.firstIndex(of: draft.id) }
            selected = TodayLogic.moved(at, by: action == .next ? 1 : -1, count: ids.count).map { ids[$0] } ?? selected
        case .approve:
            if let draft = current, draft.canApprove, !(model.growth.act(for: draft.id)?.isBusy ?? false) { model.growth.approve(draft) }
        case .skip:
            let at = current.flatMap { draft in ids.firstIndex(of: draft.id) }
            selected = TodayLogic.skipped(at, count: ids.count).map { ids[$0] } ?? selected
        case .open:
            if let draft = current { TodayActions.open(draft, model: model) }
        }
        return .handled
    }
}

/// What the buttons and keys do, once, so both layouts agree.
@MainActor
enum TodayActions {
    /// Opens the draft's own page when it stands on one; otherwise the Growth page, which holds the full draft.
    static func open(_ draft: GrowthDraft, model: AppModel) {
        if let url = TodayLogic.openTarget(draft) { NSWorkspace.shared.open(url) } else { model.go(.growth) }
    }

    static func skip(_ draft: GrowthDraft, ids: [String], selection: inout String?) {
        let at = ids.firstIndex(of: draft.id)
        selection = TodayLogic.skipped(at, count: ids.count).map { ids[$0] } ?? selection
    }
}

// MARK: Queue layout

/// The next item is the screen.
private struct QueueLayout: View {
    @Environment(AppModel.self) private var model
    let today: GtmToday
    @Binding var selection: String?

    var body: some View {
        let drafts = model.growth.drafts
        let draft = drafts.first { $0.id == selection } ?? drafts.first
        VStack(alignment: .leading, spacing: Space.xl) {
            NumbersStrip(today: today)
            ViewThatFits(in: .horizontal) {
                HStack(alignment: .top, spacing: Space.xl) {
                    primary(drafts: drafts, draft: draft).frame(minWidth: Space.todayMainMin)
                    NextActions(today: today).frame(width: Space.sideColumn)
                }
                VStack(alignment: .leading, spacing: Space.xl) {
                    primary(drafts: drafts, draft: draft)
                    NextActions(today: today)
                }
            }
            WaitingBySource(today: today)
            TodayGoals(goals: today.goals, hasGoals: today.hasGoals, bars: false)
        }
    }

    private func primary(drafts: [GrowthDraft], draft: GrowthDraft?) -> some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Next up", note: "Approve only marks a draft; you post it yourself.", count: drafts.isEmpty ? nil : drafts.count)
            if let draft {
                let index = drafts.firstIndex { $0.id == draft.id } ?? 0
                LargeDraft(draft: draft, position: "\(index + 1) of \(drafts.count)", ids: drafts.map(\.id), selection: $selection)
                if drafts.count > 1 {
                    VStack(spacing: Space.xs) {
                        ForEach(drafts.filter { $0.id != draft.id }) { other in
                            DraftRow(draft: other, selected: false) { selection = other.id }
                        }
                    }
                }
            } else if model.growth.isRead {
                EmptyState(title: "No draft waits for you.",
                           detail: today.next.first.map { "Next: \($0.label)." } ?? "New drafts appear here once the factory writes them.")
                    .surface()
            } else if let why = model.growth.failure {
                ErrorRow(section: "the drafts", message: why) { model.growth.refresh() }
            } else {
                HStack(spacing: Space.s) {
                    ProgressView().controlSize(.small)
                    Text("Reading the drafts…").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            }
        }
    }
}

/// The selected draft, large, with Approve, Skip, Reject and Open.
private struct LargeDraft: View {
    @Environment(AppModel.self) private var model
    let draft: GrowthDraft
    let position: String
    let ids: [String]
    @Binding var selection: String?

    var body: some View {
        let act = model.growth.act(for: draft.id)
        VStack(alignment: .leading, spacing: Space.m) {
            HStack(spacing: Space.s) {
                Chip(text: position, color: Palette.primary)
                if let editor = GrowthLogic.editorWords(draft) { Chip(text: editor, color: Palette.primary) }
                if !draft.canApprove { Chip(text: "Check failed", color: Palette.danger, symbol: "exclamationmark.triangle") }
                Spacer(minLength: 0)
            }
            Text(GrowthLogic.draftTitle(draft)).font(Typo.section).fixedSize(horizontal: false, vertical: true)
            Text(GrowthLogic.draftDetail(draft)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            ClampedText(text: draft.body.isEmpty ? "This draft has no text yet." : draft.body, lines: 10, font: Typo.body, color: Palette.text)
            if !draft.hook.isEmpty { Labelled(label: "Hook", text: draft.hook) }
            if !draft.critique.isEmpty { Labelled(label: "The editor said", text: draft.critique) }
            TodayDraftActions(draft: draft, ids: ids, selection: $selection, compact: false)
            if let why = GrowthLogic.approveBlock(draft) {
                Text(why).font(Typo.caption).foregroundStyle(Palette.textSecondary).fixedSize(horizontal: false, vertical: true)
            }
            ActStatus(act: act)
        }
        .surface(highlighted: true)
        .accessibilityElement(children: .contain)
    }
}

private struct Labelled: View {
    let label: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(label).font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
            ClampedText(text: text, lines: 3, font: Typo.caption, color: Palette.text)
        }
    }
}

private struct ActStatus: View {
    let act: GrowthAct?

    var body: some View {
        switch act {
        case .running(let word)?:
            HStack(spacing: Space.s) {
                ProgressView().controlSize(.small)
                Text(word).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        case .failed(let why)?:
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(Palette.danger)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text("That did not work. Nothing changed.").font(Typo.body.weight(.semibold))
                    ClampedText(text: why, lines: 3, font: Typo.caption)
                }
            }
        case nil:
            EmptyView()
        }
    }
}

/// Approve, Skip, Reject (it needs a reason, so it opens a small form) and Open. Each shows its key.
private struct TodayDraftActions: View {
    @Environment(AppModel.self) private var model
    let draft: GrowthDraft
    let ids: [String]
    @Binding var selection: String?
    let compact: Bool
    @State private var rejecting = false
    @State private var reason = ""

    var body: some View {
        let busy = model.growth.act(for: draft.id)?.isBusy ?? false
        HStack(spacing: Space.s) {
            Button { model.growth.approve(draft) } label: { KeyLabel(title: "Approve", key: "A") }
                .buttonStyle(.borderedProminent)
                .disabled(!draft.canApprove || busy)
                .help("Approve (A). It only marks the draft.")
                .accessibilityLabel("Approve this draft. Shortcut A.")
            Button { var next = selection; TodayActions.skip(draft, ids: ids, selection: &next); selection = next } label: { KeyLabel(title: "Skip", key: "S") }
                .help("Skip to the next draft (S). The draft does not change.")
                .accessibilityLabel("Skip to the next draft. Shortcut S.")
            Button { rejecting = true } label: { Text("Reject") }
                .disabled(busy)
                .help("Reject with a reason")
                .accessibilityLabel("Reject this draft with a reason")
                .popover(isPresented: $rejecting, arrowEdge: .bottom) { rejectForm }
            Button { TodayActions.open(draft, model: model) } label: { KeyLabel(title: "Open", key: "O") }
                .help("Open its source page, or the full draft on Growth (O)")
                .accessibilityLabel("Open this draft's page. Shortcut O.")
            Spacer(minLength: 0)
        }
        .controlSize(compact ? .small : .regular)
    }

    private var rejectForm: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text("Why? The next draft learns from your answer.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            TextField("For example: too salesy, wrong fact, not our voice", text: $reason, axis: .vertical)
                .lineLimit(2...4)
                .textFieldStyle(.roundedBorder)
                .font(Typo.body)
            HStack(spacing: Space.s) {
                Spacer(minLength: 0)
                Button("Cancel") { rejecting = false; reason = "" }.keyboardShortcut(.cancelAction)
                Button("Reject draft", role: .destructive) {
                    model.growth.reject(draft, reason: reason)
                    rejecting = false
                    reason = ""
                }
                .disabled(!GrowthLogic.canReject(reason: reason))
            }
        }
        .padding(Space.l)
        .frame(width: Space.todayRejectWidth)
    }
}

/// A button title with its key as a small cap.
private struct KeyLabel: View {
    let title: String
    let key: String

    var body: some View {
        HStack(spacing: Space.xs) {
            Text(title)
            Text(key)
                .font(Typo.caption.weight(.semibold).monospaced())
                .padding(.horizontal, Space.xs)
                .background(Palette.track, in: RoundedRectangle(cornerRadius: Radius.bar))
                .accessibilityHidden(true)
        }
    }
}

/// One draft as a row: its title and where it goes. A click selects it.
private struct DraftRow: View {
    let draft: GrowthDraft
    let selected: Bool
    let select: () -> Void

    var body: some View {
        Button(action: select) {
            HStack(spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(GrowthLogic.draftTitle(draft)).font(Typo.body.weight(.semibold)).lineLimit(1)
                    Text(GrowthLogic.draftDetail(draft)).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                }
                Spacer(minLength: Space.s)
                if let editor = GrowthLogic.editorWords(draft) {
                    Text(editor).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                }
                if !draft.canApprove { Image(systemName: "exclamationmark.triangle").foregroundStyle(Palette.danger).imageScale(.small) }
            }
            .padding(.horizontal, Space.m)
            .padding(.vertical, Space.s)
            .frame(maxWidth: .infinity, minHeight: Space.touchMin, alignment: .leading)
            .background(selected ? Palette.primaryTint : Palette.surface, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: Radius.card, style: .continuous)
                .strokeBorder(selected ? Palette.primary : Palette.border, lineWidth: Space.hairline))
            .contentShape(RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(GrowthLogic.draftTitle(draft)). \(GrowthLogic.draftDetail(draft)).\(selected ? " Selected." : "")")
        .accessibilityAddTraits(selected ? [.isButton, .isSelected] : .isButton)
    }
}

/// The numbers as one compact strip, with one spoken sentence.
private struct NumbersStrip: View {
    let today: GtmToday

    var body: some View {
        HStack(spacing: Space.xl) {
            item("Sent today", TodayLogic.distributionFigure(today.distribution))
            item("Outcomes this week", "\(today.outcomesWeek)")
            item("Waiting for you", "\(TodayLogic.waitingTotal(today))")
            Spacer(minLength: 0)
        }
        .padding(.horizontal, Space.l)
        .padding(.vertical, Space.m)
        .surface(padding: 0)
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel([TodayLogic.distributionSpoken(today.distribution), TodayLogic.outcomesSpoken(today),
                             TodayLogic.waitingSpoken(today)].joined(separator: " "))
    }

    private func item(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            Text(value).font(Typo.section.monospacedDigit())
            Text(label).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
        }
    }
}

// MARK: Next actions and waiting

/// The ordered list the command computed: replies, approvals, sends, follow-ups, then the distribution gap.
private struct NextActions: View {
    let today: GtmToday

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Do next", note: "In this order.", count: today.next.isEmpty ? nil : today.next.count)
            if today.next.isEmpty {
                EmptyState(title: "Nothing to do next.", detail: "Replies, approvals and sends all clear.")
            } else {
                RowGroup {
                    ForEach(Array(today.next.enumerated()), id: \.element.id) { index, next in
                        NextRow(index: index + 1, next: next, today: today)
                    }
                }
            }
        }
    }
}

private struct NextRow: View {
    let index: Int
    let next: GtmNext
    let today: GtmToday

    var body: some View {
        let waiting = today.waiting(next.kind)
        let link = next.sources.lazy.compactMap { TodayLogic.link(waiting, source: $0) }.first
        RowCard(title: next.label,
                detail: next.command.map { "Run: \($0)" } ?? next.sources.map(TodayLogic.sourceName).joined(separator: ", "),
                leading: {
            Text("\(index)").font(Typo.caption.weight(.semibold).monospacedDigit())
                .frame(width: Space.glyph, height: Space.glyph)
                .background(Palette.primaryTint, in: Circle())
                .accessibilityHidden(true)
        }, trailing: {
            if let link {
                Button("Open") { NSWorkspace.shared.open(link) }
                    .accessibilityLabel("Open the page for: \(next.label)")
            }
        })
        .accessibilityElement(children: .contain)
    }
}

/// To send, replies and follow-ups per source, each with the source's own page when it has one.
private struct WaitingBySource: View {
    let today: GtmToday

    private struct WaitingGroup {
        var kind: String
        var waiting: GtmWaiting
        var rows: [WaitingRow]
    }

    private struct WaitingRow: Hashable {
        var id: String
        var count: Int
    }

    private var groups: [WaitingGroup] {
        var out: [WaitingGroup] = []
        for kind in ["reply", "send", "follow_up", "approve"] {
            let waiting = today.waiting(kind)
            // The growth drafts are the queue above; other sources' approvals are listed here.
            let rows = waiting.sources.filter { !(kind == "approve" && $0.id == "growth") }.map { WaitingRow(id: $0.id, count: $0.count) }
            if !rows.isEmpty { out.append(WaitingGroup(kind: kind, waiting: waiting, rows: rows)) }
        }
        return out
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Waiting in other places", note: "Counts per source. Open goes to the source's own page.")
            if groups.isEmpty {
                EmptyState(title: "Nothing waits to be sent or answered.")
            } else {
                RowGroup {
                    ForEach(groups, id: \.kind) { group in
                        ForEach(group.rows, id: \.id) { row in
                            RowCard(title: TodayLogic.sourceName(row.id), detail: TodayLogic.waitingWords(group.kind, count: row.count)) {
                                if let url = TodayLogic.link(group.waiting, source: row.id) {
                                    Button("Open") { NSWorkspace.shared.open(url) }
                                        .accessibilityLabel("Open \(TodayLogic.sourceName(row.id)): \(TodayLogic.waitingWords(group.kind, count: row.count))")
                                } else {
                                    Text("\(row.count)").font(Typo.body.weight(.semibold).monospacedDigit()).foregroundStyle(Palette.textSecondary)
                                        .accessibilityHidden(true)
                                }
                            }
                            .accessibilityElement(children: .combine)
                        }
                    }
                }
            }
        }
    }
}

// MARK: Goals and doctor

/// This week's outcomes against the targets, per goal, with the days left to its deadline.
/// `bars` draws a progress bar per target (the board layout); otherwise one line per target.
private struct TodayGoals: View {
    let goals: [GtmGoal]
    let hasGoals: Bool
    let bars: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Goals this week", note: "What came back, against each weekly target.", count: goals.isEmpty ? nil : goals.count)
            if goals.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: hasGoals ? "No goal has a weekly target." : "No goals yet.",
                           detail: "Run `teyla gtm init` in a terminal to write the goals file, then edit it.")
            } else {
                VStack(spacing: Space.m) {
                    ForEach(goals) { goal in GoalCard(goal: goal, bars: bars) }
                }
            }
        }
    }
}

private struct GoalCard: View {
    let goal: GtmGoal
    let bars: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                Text(goal.title).font(Typo.cardTitle).lineLimit(2)
                Spacer(minLength: Space.s)
                if let left = TodayLogic.daysLeftWords(goal.daysLeft) {
                    Chip(text: left, color: (goal.daysLeft ?? 1) <= 14 ? Palette.needsYou : Palette.primary)
                }
            }
            if goal.targets.isEmpty {
                Text("No weekly target is set for this goal.").font(Typo.caption).foregroundStyle(Palette.textSecondary)
            } else if bars {
                ForEach(goal.targets, id: \.stage) { target in
                    VStack(alignment: .leading, spacing: Space.xs) {
                        HStack {
                            Text(TodayLogic.stageName(target.stage).capitalized).font(Typo.body)
                            Spacer(minLength: Space.s)
                            Text(TodayLogic.targetWords(target)).font(Typo.body.weight(.semibold).monospacedDigit())
                        }
                        ProgressView(value: TodayLogic.fraction(target))
                            .progressViewStyle(.linear)
                            .tint(target.count >= target.target ? Palette.saving : Palette.primaryMuted)
                            .accessibilityHidden(true)
                    }
                }
            } else {
                Text(goal.targets.map { "\(TodayLogic.targetWords($0)) \(TodayLogic.stageName($0.stage))" }.joined(separator: "  ·  "))
                    .font(Typo.body.monospacedDigit())
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .surface(padding: Space.m)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(TodayLogic.goalSpoken(goal))
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

// MARK: Board layout

/// The numbers are the screen.
private struct BoardLayout: View {
    @Environment(AppModel.self) private var model
    let today: GtmToday
    @Binding var selection: String?

    var body: some View {
        let drafts = model.growth.drafts
        VStack(alignment: .leading, spacing: Space.xl) {
            StatStrip {
                StatTile(label: "Sent today", value: TodayLogic.distributionFigure(today.distribution),
                         detail: TodayLogic.distributionDetail(today.distribution),
                         tone: gap ? .needsYou : .neutral)
                StatTile(label: "Outcomes this week", value: "\(today.outcomesWeek)", detail: TodayLogic.outcomesDetail(today))
                StatTile(label: "Waiting for you", value: "\(TodayLogic.waitingTotal(today))", detail: TodayLogic.waitingDetail(today),
                         tone: TodayLogic.waitingTotal(today) > 0 ? .needsYou : .neutral)
            }
            TodayGoals(goals: today.goals, hasGoals: today.hasGoals, bars: true)
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: "Queue", note: "Approve only marks a draft; you post it yourself.", count: model.growth.isRead ? drafts.count : nil)
                if drafts.isEmpty {
                    EmptyState(title: model.growth.isRead ? "No draft waits for you." : "Reading the drafts…").surface()
                } else {
                    VStack(spacing: Space.xs) {
                        ForEach(drafts) { draft in
                            if draft.id == (selection ?? drafts.first?.id) {
                                VStack(alignment: .leading, spacing: Space.s) {
                                    DraftRow(draft: draft, selected: true) {}
                                    ClampedText(text: draft.body, lines: 4, font: Typo.caption, color: Palette.text)
                                        .padding(.horizontal, Space.m)
                                    TodayDraftActions(draft: draft, ids: drafts.map(\.id), selection: $selection, compact: true)
                                        .padding(.horizontal, Space.m)
                                    ActStatus(act: model.growth.act(for: draft.id)).padding(.horizontal, Space.m)
                                }
                            } else {
                                DraftRow(draft: draft, selected: false) { selection = draft.id }
                            }
                        }
                    }
                }
            }
            NextActions(today: today)
            WaitingBySource(today: today)
        }
    }

    private var gap: Bool {
        guard let target = today.distribution.target else { return false }
        return today.distribution.today < target
    }
}

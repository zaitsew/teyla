import SwiftUI

/// Decisions: every question that waits on the owner, then what Teyla suggests closing, what agents can settle,
/// what Teyla closed, the tasks only the owner can do and what got done. With triage the questions are grouped
/// Pay, Decide, Do; without it they are one ranked list. Nothing that is open is left out.
struct DecisionsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    // Not lazy: a few dozen cards at most, and the "Older" fold must exist to be scrolled to.
                    VStack(alignment: .leading, spacing: 28) {
                        if let snapshot = model.snapshot {
                            Content(snapshot: snapshot)
                        } else {
                            WaitingView()
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
                    .padding(.bottom, 32)
                    .frame(maxWidth: 640)
                    .frame(maxWidth: .infinity)
                }
                .task {
                    // Screenshots: `-TEYLA_OLDER open` also scrolls the fold into view.
                    guard LaunchOptions().olderOpen else { return }
                    try? await Task.sleep(for: .milliseconds(800))
                    withAnimation { proxy.scrollTo("older", anchor: .top) }
                }
                .scrollDismissesKeyboard(.interactively)
                .background(Color(.systemGroupedBackground))
                .refreshable { await model.refresh() }
            }
            .navigationTitle("Decisions")
            .navigationBarTitleDisplayMode(.large)
        }
    }
}

private struct Content: View {
    @Environment(AppModel.self) private var model
    let snapshot: Snapshot

    var body: some View {
        let now = Date()
        let lists = DecisionLists(asks: snapshot.asks, snapshot: snapshot, now: now)
        Text(Decisions.summary(count: lists.owner.count))
            .font(.subheadline)
            .foregroundStyle(.secondary)
            .accessibilityAddTraits(.isHeader)
            .padding(.top, -16)

        SentFromPhone(snapshot: snapshot)
        Questions(lists: lists, snapshot: snapshot, now: now)
        CloseSuggestions(asks: lists.close)
        AgentsFold(asks: lists.agent, snapshot: snapshot, now: now)
        AutoClosedFold()
        OnlyYou(snapshot: snapshot, now: now)
        DoneFold(snapshot: snapshot, now: now)
    }
}

// MARK: The owner's questions

private struct Questions: View {
    let lists: DecisionLists
    let snapshot: Snapshot
    let now: Date

    var body: some View {
        if lists.hasTriage {
            ForEach(Decisions.grouped(lists.fresh)) { group in
                VStack(alignment: .leading, spacing: 12) {
                    SectionLabel(group.heading)
                    ForEach(group.asks) { card($0) }
                }
            }
        } else if !lists.fresh.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionLabel("Needs you \u{2014} ordered by what it unblocks")
                ForEach(lists.fresh) { card($0) }
            }
        }
        if !lists.older.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                Color.clear.frame(height: 0).id("older")
                Fold(title: AskFold.heading(count: lists.older.count), detail: "waiting more than 7 days",
                     spokenTitle: "Older questions, \(lists.older.count)", startsOpen: LaunchOptions().olderOpen) {
                    ForEach(lists.older) { card($0) }
                }
            }
        }
    }

    private func card(_ ask: Ask) -> some View {
        QuestionCard(ask: ask, ageSeconds: PhoneFormat.age(ask.ageSeconds, snapshot: snapshot, now: now))
    }
}

/// "Older · 15", the same words as the Mac.
private enum AskFold {
    static func heading(count: Int) -> String { "Older \u{00B7} \(count)" }
}

// MARK: Teyla suggests closing

/// "Teyla suggests closing 3": still open until the owner accepts. Nothing here closes on its own, and each
/// accepted question is one signed request that the Mac carries out.
private struct CloseSuggestions: View {
    @Environment(AppModel.self) private var model
    let asks: [Ask]

    var body: some View {
        let progress = model.closeProgress
        let open = asks.filter { model.action(for: .close, target: $0.id) == nil }
        VStack(alignment: .leading, spacing: 12) {
            if let line = Decisions.closeLine(count: asks.count) {
                Fold(title: line) {
                    ForEach(asks) { ask in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(ask.question).font(.subheadline).fixedSize(horizontal: false, vertical: true)
                            Text(detail(ask)).font(.footnote).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(.leading, 16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                if !open.isEmpty {
                    Button("Accept these \(open.count)") {
                        Task { await model.acceptClose(open) }
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                }
            }
            if !progress.isEmpty { status(progress) }
        }
    }

    @ViewBuilder private func status(_ progress: CloseProgress) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            if progress.simulated {
                Label(SampleData.notice, systemImage: "info.circle.fill")
                    .font(.callout).foregroundStyle(.secondary)
            }
            if let line = CloseTracking.line(progress) {
                HStack(spacing: 8) {
                    if progress.waiting > 0 || progress.reopening > 0 {
                        ProgressView().controlSize(.small)
                        Text("\(line) Waiting for the Mac").foregroundStyle(.secondary)
                    } else {
                        Text(line).foregroundStyle(.secondary)
                        Button("Undo") { Task { await model.undoAcceptedClose() } }
                            .buttonStyle(.bordered)
                            .controlSize(.large)
                    }
                }
                .font(.callout)
            }
            if let failure = progress.failure {
                Label(failure, systemImage: "exclamationmark.triangle.fill")
                    .font(.callout)
                    .foregroundStyle(Color.brandDanger)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if progress.waiting == 0 && progress.reopening == 0 {
                Button("Dismiss") { model.dismissCloseResults() }
                    .font(.callout.weight(.medium))
                    .frame(minHeight: 44)
            }
        }
    }

    private func detail(_ ask: Ask) -> String {
        var parts = [Format.product(ask.product)]
        if let why = ask.triage?.why, !why.isEmpty { parts.append(why) }
        return parts.joined(separator: " \u{00B7} ")
    }
}

// MARK: Agents can settle

/// "Agents can settle 20": each is a full card, and "Use default" sends the proposed answer to its session.
/// There is no bulk send: each answer resumes a session.
private struct AgentsFold: View {
    let asks: [Ask]
    let snapshot: Snapshot
    let now: Date

    var body: some View {
        if let line = Decisions.agentLine(count: asks.count) {
            Fold(title: line) {
                ForEach(asks) { ask in
                    QuestionCard(ask: ask, ageSeconds: PhoneFormat.age(ask.ageSeconds, snapshot: snapshot, now: now))
                }
            }
        }
    }
}

// MARK: Teyla closed

/// "Teyla closed 3 questions", with the reason for each and an Undo.
private struct AutoClosedFold: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let closed = model.autoClosed
        if closed.count > 0 {
            Fold(title: AutoClosedText.heading(count: closed.count)) {
                ForEach(closed.items) { item in
                    AutoClosedRow(item: item)
                }
            }
        }
    }
}

private struct AutoClosedRow: View {
    @Environment(AppModel.self) private var model
    let item: AutoClosedItem

    var body: some View {
        let action = model.action(for: .reopen, target: item.id)
        VStack(alignment: .leading, spacing: 8) {
            Text(item.title).font(.subheadline).fixedSize(horizontal: false, vertical: true)
            Text(detail).font(.footnote).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            if let action {
                if let outcome = action.outcome {
                    Label(outcome.ok ? PhoneFormat.outcomeLine(outcome) : CloseTracking.failureLine(outcome),
                          systemImage: outcome.ok ? "info.circle.fill" : "exclamationmark.triangle.fill")
                        .font(.callout)
                        .foregroundStyle(outcome.ok ? Color.secondary : Color.brandDanger)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(outcome.ok ? "Dismiss" : "Dismiss and try again") { model.dismiss(action.id) }
                        .font(.callout.weight(.medium))
                        .frame(minHeight: 44)
                } else {
                    HStack(spacing: 8) {
                        ProgressView().controlSize(.small)
                        Text("Waiting for the Mac").foregroundStyle(.secondary)
                    }
                    .font(.callout)
                }
            } else {
                Button("Undo") { Task { await model.reopen(id: item.id, label: item.title) } }
                    .buttonStyle(.bordered)
                    .controlSize(.large)
                    .disabled(model.isSending(.reopen, target: item.id))
                    .accessibilityHint("Reopens the question")
            }
        }
        .padding(.leading, 16)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var detail: String {
        [Format.product(item.product), item.reason].filter { !$0.isEmpty }.joined(separator: " \u{00B7} ")
    }
}

// MARK: Only you, and done

/// Things only the owner can do that are not questions: a PR to merge, an issue assigned to the owner.
private struct OnlyYou: View {
    let snapshot: Snapshot
    let now: Date

    var body: some View {
        if !snapshot.tasks.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                SectionLabel("Only you")
                ForEach(snapshot.tasks) { task in
                    TaskRow(task: task, ageSeconds: PhoneFormat.age(task.ageSeconds, snapshot: snapshot, now: now))
                }
            }
        }
    }
}

/// "Done since yesterday", folded: four results, and the rest one tap away.
private struct DoneFold: View {
    let snapshot: Snapshot
    let now: Date
    @State private var showAll = false

    private static let collapsed = 4

    var body: some View {
        let items = snapshot.done
        if !items.isEmpty {
            Fold(title: "Done since yesterday \u{00B7} \(items.count)") {
                ForEach(showAll ? items : Array(items.prefix(Self.collapsed))) { item in
                    DoneCard(item: item, agoSeconds: PhoneFormat.secondsSince(item.ended, now: now))
                }
                if items.count > Self.collapsed {
                    Button(showAll ? "Show fewer" : "Show all \(items.count)") { showAll.toggle() }
                        .font(.body.weight(.medium))
                        .frame(minHeight: 44)
                }
            }
        }
    }
}

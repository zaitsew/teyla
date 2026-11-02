import SwiftUI

/// Decisions: every question that waits on the owner, then what agents handle, the tasks only the owner can do,
/// notes and what got done. With triage the questions are grouped Pay, Decide, Do; without it they are one ranked list.
struct DecisionsView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollViewReader { reader in
            ScrollView {
                VStack(alignment: .leading, spacing: Space.xl) {
                    header
                    if model.snapshot == nil {
                        SnapshotEmptyView()
                    } else {
                        questions
                        AgentsFold()
                        OnlyYou()
                        if model.capabilities.notes { NotesSection() }
                        DoneFold()
                    }
                }
                .padding(.horizontal, Space.xl + Space.xs)
                .padding(.vertical, Space.xl)
                .readingWidth()
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .onChange(of: model.focusedAskID) { _, id in
                guard let id else { return }
                withAnimation(.easeOut(duration: 0.25)) { reader.scrollTo(id, anchor: .top) }
            }
        }
        .background(Palette.background)
        .navigationTitle("Decisions")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Space.xs + Space.xxs) {
            Text("Decisions").font(Typo.brief)
            if model.snapshot != nil {
                Text(Decisions.summary(count: model.ownerAsks.count))
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
    }

    @ViewBuilder private var questions: some View {
        let owner = model.ownerAsks
        let asks = AskFold.partition(owner) { model.age(of: $0) }
        VStack(alignment: .leading, spacing: Space.xl) {
            if Decisions.hasTriage(model.visibleAsks) {
                ForEach(Decisions.grouped(asks.fresh)) { group in
                    VStack(alignment: .leading, spacing: Space.m) {
                        SectionLabel(group.heading)
                        ForEach(group.asks) { ask in
                            AskCard(ask: ask)
                                .transition(.opacity.combined(with: .scale(scale: 0.97)))
                        }
                    }
                }
            } else if !asks.fresh.isEmpty {
                VStack(alignment: .leading, spacing: Space.m) {
                    SectionLabel("Needs you — ordered by what it unblocks")
                    ForEach(asks.fresh) { ask in
                        AskCard(ask: ask)
                            .transition(.opacity.combined(with: .scale(scale: 0.97)))
                    }
                }
            }
            if !asks.older.isEmpty {
                OlderGroup(count: asks.older.count, revealsFocus: asks.older.contains { $0.id == model.focusedAskID }) {
                    ForEach(asks.older) { ask in
                        AskCard(ask: ask, older: true)
                            .transition(.opacity.combined(with: .scale(scale: 0.97)))
                    }
                }
            }
        }
        .animation(.easeOut(duration: 0.25), value: owner.map(\.id))
    }
}

/// "Agents are handling 20": the questions a session settles with Teyla's proposed default, one line until opened.
private struct AgentsFold: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let agents = model.agentAsks
        if let line = Decisions.agentLine(count: agents.count) {
            Fold(title: line) {
                VStack(alignment: .leading, spacing: Space.s) {
                    ForEach(agents) { ask in
                        VStack(alignment: .leading, spacing: Space.xxs) {
                            Text(ask.question).font(Typo.body).fixedSize(horizontal: false, vertical: true)
                            Text(detail(ask)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(.leading, Space.l)
                    }
                }
            }
        }
    }

    private func detail(_ ask: Ask) -> String {
        var parts = [Format.product(ask.product)]
        if let proposed = ask.proposedAnswer { parts.append("Default: \(proposed)") }
        return parts.joined(separator: " · ")
    }
}

/// Things only the owner can do that are not questions: a PR to merge, an issue assigned to the owner.
private struct OnlyYou: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let tasks = model.snapshot?.tasks ?? []
        if !tasks.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                SectionLabel("Only you")
                ForEach(tasks) { task in
                    TaskRow(task: task)
                }
            }
        }
    }
}

/// "Done since yesterday", folded: four results, and the rest one click away.
private struct DoneFold: View {
    @Environment(AppModel.self) private var model
    @State private var showAll = false

    private static let collapsed = 4

    var body: some View {
        let items = model.snapshot?.done ?? []
        if !items.isEmpty {
            Fold(title: "Done since yesterday · \(items.count)") {
                VStack(alignment: .leading, spacing: Space.m) {
                    ForEach(showAll ? items : Array(items.prefix(Self.collapsed))) { item in
                        DoneCard(item: item)
                    }
                    if items.count > Self.collapsed {
                        Button(showAll ? "Show fewer" : "Show all \(items.count)") { showAll.toggle() }
                            .buttonStyle(.link)
                    }
                }
            }
        }
    }
}

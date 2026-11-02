import SwiftUI

/// Home: one sentence, the core products and how far each has got, the top decisions, and what runs.
/// Health, tasks, finished work and the questions agents can settle live on the Decisions and Products tabs.
struct HomeView: View {
    @Environment(AppModel.self) private var model
    @Binding var tab: AppTab
    @Binding var showNewTask: Bool
    @Binding var showSettings: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 28) {
                    if let snapshot = model.snapshot {
                        HomeContent(snapshot: snapshot, tab: $tab)
                    } else {
                        WaitingView()
                    }
                }
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 32)
                // A comfortable measure: cards stop at 640 pt however wide the screen is.
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color(.systemGroupedBackground))
            .refreshable { await model.refresh() }
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(for: ProductRoute.self) { route in
                PortfolioDetailView(productID: route.id)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button { showSettings = true } label: { Label("Settings", systemImage: "gearshape") }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNewTask = true } label: { Text("New task").fontWeight(.semibold) }
                        .disabled(model.snapshot == nil)
                }
            }
        }
    }
}

private struct HomeContent: View {
    @Environment(AppModel.self) private var model
    let snapshot: Snapshot
    @Binding var tab: AppTab

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(PhoneHome.briefLine(snapshot))
                .font(.title2.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
            Text(HomeText.caption(decisions: model.ownerAsks.count, running: snapshot.running.count,
                                  spend: HomeText.spend(portfolio: snapshot.portfolio, todayUSD: snapshot.totals.spentTodayUSD)))
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            SyncLine()
        }

        SentFromPhone(snapshot: snapshot)
        CoreProducts(portfolio: snapshot.portfolio, tab: $tab)
        HomeDecisions(snapshot: snapshot, tab: $tab)
        RunningFold(snapshot: snapshot)
    }
}

/// What this phone sent that no card shows any more: new tasks, and answers whose question the Mac dropped.
struct SentFromPhone: View {
    @Environment(AppModel.self) private var model
    let snapshot: Snapshot

    var body: some View {
        let sent = model.sentWithoutCard(in: snapshot)
        if !sent.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                SectionLabel("Sent from this iPhone")
                ForEach(sent) { action in
                    VStack(alignment: .leading, spacing: 6) {
                        Text(heading(of: action)).font(.subheadline.weight(.semibold))
                        OutcomeView(action: action) { model.dismiss(action.id) }
                    }
                    .card()
                }
            }
        }
    }

    private func heading(of action: PendingAction) -> String {
        switch action.kind {
        case .dispatch: return "New task \u{00B7} \(Format.product(action.label))"
        case .answer: return "Answer \u{00B7} \(action.label)"
        case .say: return "Correction \u{00B7} \(action.label)"
        case .close: return "Close \u{00B7} \(action.label)"
        case .reopen: return "Reopen \u{00B7} \(action.label)"
        }
    }
}

// MARK: Core products

private struct CoreProducts: View {
    let portfolio: Portfolio?
    @Binding var tab: AppTab

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                SectionLabel("Core products")
                Button("All products") { tab = .products }
                    .font(.subheadline)
                    .frame(minHeight: 44)
            }
            if PhoneHome.needsMacUpdate(portfolio) {
                UpdateMacCard()
            } else if let portfolio {
                let cards = CoreCards.cards(portfolio)
                if let note = PhoneHome.coreNote(source: portfolio.coreSource) {
                    Text(note).font(.footnote).foregroundStyle(.secondary)
                }
                if cards.isEmpty {
                    Label(PhoneHome.coreEmpty, systemImage: "star")
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                ForEach(cards) { card in
                    NavigationLink(value: ProductRoute(id: card.id)) {
                        CoreProductCard(card: card)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }
}

/// Shown instead of the grid when the Mac's Teyla is too old to send the core list. Never an empty grid.
private struct UpdateMacCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Label(PhoneHome.updateTitle, systemImage: "arrow.triangle.2.circlepath")
                .font(.headline)
            Text(PhoneHome.updateText)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .card()
        .accessibilityElement(children: .combine)
    }
}

/// One core product: where it stands, in facts. No health and no percentage. A tap opens its page.
private struct CoreProductCard: View {
    let card: CoreCard

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(card.title)
                    .font(.headline)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer(minLength: 4)
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .accessibilityHidden(true)
            }
            if !card.line.isEmpty {
                Text(card.line)
                    .font(.subheadline)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let blocker = card.blocker {
                Label(blocker, systemImage: "hand.raised")
                    .font(.subheadline)
                    .foregroundStyle(Color.brandAmber)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: 3) {
                if !card.install.installable.isEmpty {
                    FactLine(label: "Install", value: card.install.installable.joined(separator: " \u{00B7} "))
                }
                if !card.install.pending.isEmpty {
                    FactLine(label: "Not installable", value: card.install.pending.joined(separator: " \u{00B7} "))
                }
                FactLine(label: "Shipped", value: [card.shipped, card.latest].compactMap { $0 }.joined(separator: " \u{00B7} "))
                if let users = card.users { FactLine(label: "Users", value: users) }
                if let milestone = card.milestone { FactLine(label: "Milestone", value: milestone) }
                if let quiet = card.quiet { FactLine(label: "", value: quiet) }
            }
        }
        .card()
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens the product page")
    }
}

/// "Install  iOS 1.4.0 (52)": a quiet label and its value, wrapping together.
private struct FactLine: View {
    let label: String
    let value: String

    var body: some View {
        (label.isEmpty ? Text(value) : Text(label + " ").foregroundStyle(.secondary) + Text(value))
            .font(.footnote)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: Decisions

private struct HomeDecisions: View {
    @Environment(AppModel.self) private var model
    let snapshot: Snapshot
    @Binding var tab: AppTab

    var body: some View {
        let lists = DecisionLists(asks: snapshot.asks, snapshot: snapshot, now: Date())
        let shown = Decisions.homeList(lists.fresh)
        VStack(alignment: .leading, spacing: 12) {
            SectionLabel("Decisions")
            if lists.owner.isEmpty {
                Label("Nothing waits on you.", systemImage: "checkmark.circle")
                    .foregroundStyle(.secondary)
            } else if shown.isEmpty {
                Text("Nothing new. The rest waited more than 7 days.").foregroundStyle(.secondary)
            }
            ForEach(shown) { ask in
                QuestionCard(ask: ask, ageSeconds: PhoneFormat.age(ask.ageSeconds, snapshot: snapshot, now: Date()))
            }
            if let label = Decisions.seeAll(total: lists.owner.count, shown: shown.count) {
                Button(label) { tab = .decisions }
                    .font(.body.weight(.medium))
                    .frame(minHeight: 44)
            }
        }
    }
}

// MARK: Running

/// "Running now (3)", folded: the sessions active in the last 10 minutes.
private struct RunningFold: View {
    let snapshot: Snapshot

    var body: some View {
        if !snapshot.running.isEmpty {
            Fold(title: "Running now (\(snapshot.running.count))",
                 spokenTitle: "Running now, \(snapshot.running.count) sessions") {
                ForEach(snapshot.running) { session in
                    RunningCard(session: session,
                                runningSeconds: PhoneFormat.secondsSince(session.since, now: Date()))
                }
            }
        }
    }
}

/// "Mac synced 4 min ago", orange once it is older than 10 minutes.
struct SyncLine: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        TimelineView(.periodic(from: .now, by: 20)) { context in
            if model.connection == .sample {
                // The banner above every tab already says "Sample data".
                EmptyView()
            } else if model.connection == .fixture {
                Label("Preview data", systemImage: "eye")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else if model.connection == .syncing {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini)
                    Text("Syncing").font(.footnote).foregroundStyle(.secondary)
                }
            } else if let date = model.syncDate {
                let seconds = max(0, context.date.timeIntervalSince(date))
                let stale = PhoneFormat.isStale(secondsAgo: seconds)
                Label(PhoneFormat.synced(secondsAgo: seconds) + (stale ? ". The Mac may be asleep." : ""),
                      systemImage: stale ? "exclamationmark.triangle.fill" : "checkmark.icloud")
                    .font(.footnote)
                    .foregroundStyle(stale ? Color.orange : Color.secondary)
            }
        }
    }
}

/// Shown instead of the data: no file, a file that failed the signature check, or a download.
struct WaitingView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: 14) {
            Spacer(minLength: 80)
            if model.connection == .syncing || model.connection == .reading {
                ProgressView()
                Text(model.connection == .syncing ? "Syncing" : "Reading").font(.title3.weight(.semibold))
                Text("iCloud is bringing the Mac's latest update.")
                    .font(.subheadline).foregroundStyle(.secondary)
            } else {
                Image(systemName: "desktopcomputer")
                    .font(.system(size: 40))
                    .foregroundStyle(.secondary)
                Text("Waiting for the Mac").font(.title3.weight(.semibold))
                Text("Pull down to check again. Wrong key? Pair again in Settings.")
                    .font(.subheadline).foregroundStyle(.secondary)
            }
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

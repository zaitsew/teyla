import SwiftUI

/// Home: the pulse strip, the Next line, a Week / Month / Year switch, the products people use, the top decisions, the products being
/// built, the quiet ones, and what runs. Health, tasks, finished work and the questions agents can settle live on the
/// Decisions and Products tabs.
struct HomeView: View {
    @Environment(AppModel.self) private var model
    @Binding var tab: AppTab
    @Binding var showNewTask: Bool
    @Binding var showSettings: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                // Lazy: a long Home builds the rows that scroll into view, not all 40 products at once.
                LazyVStack(alignment: .leading, spacing: Space.xl) {
                    if let snapshot = model.snapshot {
                        HomeContent(snapshot: snapshot, tab: $tab)
                    } else {
                        WaitingView()
                    }
                }
                .padding(.horizontal, Space.l)
                .padding(.top, Space.s)
                .padding(.bottom, Space.xxl)
                // A comfortable measure: cards stop at 640 pt however wide the screen is.
                .frame(maxWidth: Space.readingCard)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Palette.background)
            .refreshable { await model.refresh() }
            .navigationTitle("Home")
            .navigationBarTitleDisplayMode(.large)
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
    /// One period for the whole page, remembered. It changes numbers only, never who sits where.
    @AppStorage("teyla.home.period") private var storedPeriod = HomePeriod.week.rawValue
    @AppStorage(HomeHeaderStyle.storageKey) private var storedStyle = HomeHeaderStyle.pulse.rawValue

    private var period: HomePeriod { HomePeriod.from(stored: storedPeriod) }
    /// The first fresh decision, in rank order; else the oldest one still open, as on the Mac.
    private var lists: DecisionLists { DecisionLists(asks: model.asks, snapshot: snapshot, now: Date()) }
    private var topDecision: Ask? { lists.fresh.first ?? lists.older.first }

    var body: some View {
        switch HomeHeaderStyle.from(stored: storedStyle) {
        case .pulse:
            StatStrip {
                ForEach(HomePulse.tiles(decisions: model.ownerAsks, running: snapshot.running.count,
                                        spend: HomeText.spend(portfolio: snapshot.portfolio, todayUSD: snapshot.totals.spentTodayUSD),
                                        console: snapshot.console)) { tile in
                    StatTile(label: tile.label, value: tile.value, detail: tile.detail, tone: tile.tone,
                             action: tile.kind == .decisions ? { tab = .decisions } : nil)
                }
            }
            NextLineButton(line: HomeNext.line(brief: snapshot.brief, top: topDecision, rankFirst: model.ownerAsks.first),
                           revealsOlder: lists.fresh.isEmpty, tab: $tab)
        case .sentence:
            Text(HomeNext.sentence(brief: snapshot.brief, decisions: model.ownerAsks.count, top: topDecision,
                              rankFirst: model.ownerAsks.first))
                .font(Typo.section)
                .lineLimit(2)
        }
        SyncLine()
        DailyQuoteSlot(quote: nil)

        SentFromPhone(snapshot: snapshot)
        if let sections = PhoneHome.sections(snapshot.portfolio) {
            PeriodSwitch(period: Binding(get: { period }, set: { storedPeriod = $0.rawValue }))
            if sections.allSatisfy({ $0.products.isEmpty }) {
                Text(PhoneHome.noProducts).foregroundStyle(Palette.textSecondary)
            }
            section(sections, .users)
            HomeDecisions(snapshot: snapshot, tab: $tab)
            section(sections, .building)
            section(sections, .quiet)
        } else {
            UpdateMacCard()
            HomeDecisions(snapshot: snapshot, tab: $tab)
        }
        RunningFold(snapshot: snapshot)
    }

    /// A product section, or nothing when the Mac put no product in it.
    @ViewBuilder
    private func section(_ sections: [HomeSection], _ kind: HomeSectionKind) -> some View {
        if let section = sections.first(where: { $0.kind == kind }), !section.products.isEmpty {
            VStack(alignment: .leading, spacing: Space.m) {
                SectionHeader(title: kind.title, note: kind.note)
                switch kind {
                case .users: HeroList(products: section.products, period: period)
                case .building: BuiltList(products: section.products, period: period)
                case .quiet: QuietList(products: section.products)
                }
            }
        }
    }
}

/// One line that names the top decision. The Decisions tab lists it first, so the tab is where it opens.
private struct NextLineButton: View {
    @Environment(AppModel.self) private var model
    let line: HomeNextLine
    /// Every open question is older than 7 days, so the one named here sits in the closed fold.
    let revealsOlder: Bool
    @Binding var tab: AppTab

    var body: some View {
        if line.askID != nil {
            Button {
                if revealsOlder { model.olderReveals += 1 }
                tab = .decisions
            } label: {
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    Text("Next").font(Typo.body.weight(.semibold)).foregroundStyle(Palette.primary)
                    Text(line.text).font(Typo.body).foregroundStyle(Palette.text).lineLimit(2)
                        .multilineTextAlignment(.leading)
                    Spacer(minLength: 0)
                    Image(systemName: "chevron.right").font(Typo.caption).foregroundStyle(Palette.textTertiary)
                }
                .frame(minHeight: Space.touchMin)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Next: \(line.text)")
            .accessibilityHint("Opens Decisions")
        } else {
            Label(line.text, systemImage: "checkmark.circle")
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
        }
    }
}

/// A place for the day's quote. Nothing draws until the content lane fills it.
private struct DailyQuoteSlot: View {
    let quote: String?

    var body: some View {
        if let quote, !quote.isEmpty {
            Text(quote).font(Typo.body).italic().foregroundStyle(Palette.textSecondary).lineLimit(3)
        }
    }
}

/// What this phone sent that no card shows any more: new tasks, and answers whose question the Mac dropped.
struct SentFromPhone: View {
    @Environment(AppModel.self) private var model
    let snapshot: Snapshot

    var body: some View {
        let sent = model.sentWithoutCard(in: snapshot)
        if !sent.isEmpty {
            VStack(alignment: .leading, spacing: Space.s) {
                SectionHeader(title: "Sent from this iPhone")
                ForEach(sent) { action in
                    VStack(alignment: .leading, spacing: Space.xs) {
                        Text(heading(of: action)).font(Typo.body.weight(.semibold))
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

// MARK: Older Mac

/// Shown instead of the sections when the Mac's Teyla is too old to send `portfolio.home`. Never an empty page.
private struct UpdateMacCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Label(PhoneHome.updateTitle, systemImage: "arrow.triangle.2.circlepath")
                .font(Typo.cardTitle)
            Text(PhoneHome.updateText)
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .card()
        .accessibilityElement(children: .combine)
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
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Decisions", note: PhoneHome.decisionsNote)
            if lists.owner.isEmpty {
                Label("Nothing waits on you.", systemImage: "checkmark.circle")
                    .foregroundStyle(Palette.textSecondary)
            } else if shown.isEmpty {
                Text("Nothing new. The rest waited more than 7 days.").foregroundStyle(Palette.textSecondary)
            }
            ForEach(shown) { ask in
                QuestionCard(ask: ask, ageSeconds: PhoneFormat.age(ask.ageSeconds, snapshot: snapshot, now: Date()))
            }
            if let label = Decisions.seeAll(total: lists.owner.count, shown: shown.count) {
                Button(label) { tab = .decisions }
                    .font(Typo.body.weight(.medium))
                    .frame(minHeight: Space.touchMin)
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
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            } else if model.connection == .syncing {
                HStack(spacing: Space.xs) {
                    ProgressView().controlSize(.mini)
                    Text("Syncing").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            } else if let date = model.syncDate {
                let seconds = max(0, context.date.timeIntervalSince(date))
                let stale = PhoneFormat.isStale(secondsAgo: seconds)
                Label(PhoneFormat.synced(secondsAgo: seconds) + (stale ? ". The Mac may be asleep." : ""),
                      systemImage: stale ? "exclamationmark.triangle.fill" : "checkmark.icloud")
                    .font(Typo.caption)
                    .foregroundStyle(stale ? Palette.needsYou : Palette.textSecondary)
            }
        }
    }
}

/// Shown instead of the data: no file, a file that failed the signature check, or a download.
struct WaitingView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(spacing: Space.m) {
            Spacer(minLength: Space.xxl)
            if model.connection == .syncing || model.connection == .reading {
                ProgressView()
                Text(model.connection == .syncing ? "Syncing" : "Reading").font(Typo.section)
                Text("iCloud is bringing the Mac's latest update.")
                    .font(Typo.body).foregroundStyle(Palette.textSecondary)
            } else {
                Image(systemName: "desktopcomputer")
                    .font(Glyph.empty)
                    .foregroundStyle(Palette.textSecondary)
                Text("Waiting for the Mac").font(Typo.section)
                Text("Pull down to check again. Wrong key? Pair again in Settings.")
                    .font(Typo.body).foregroundStyle(Palette.textSecondary)
            }
        }
        .multilineTextAlignment(.center)
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

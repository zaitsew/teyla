import SwiftUI

/// Home: one sentence, a period switch, the products in three sections (people use these, being built, quiet),
/// the top decisions, and what runs. Health, notes, finished work and the status column live on their own pages.
struct HomeView: View {
    var body: some View {
        ScrollView {
            HomeContent()
                .padding(.horizontal, Space.xl + Space.xs)
                .padding(.vertical, Space.xl)
                .frame(maxWidth: Space.homeMax, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Palette.background)
        .navigationTitle("Home")
    }
}

/// The page without its scroll view, so a screenshot can draw all of it at once.
struct HomeContent: View {
    @Environment(AppModel.self) private var model
    /// A screenshot has no scroll view to make a lazy stack draw what is below the fold, so it asks for a plain one.
    var eager = false
    @AppStorage("teyla.home.period") private var storedPeriod = HomePeriod.week.rawValue

    private var period: HomePeriod { HomePeriod.from(stored: storedPeriod) }

    var body: some View {
        if eager {
            VStack(alignment: .leading, spacing: Space.xl) { page }
        } else {
            LazyVStack(alignment: .leading, spacing: Space.xl) { page }
        }
    }

    @ViewBuilder
    private var page: some View {
        header
        if let snapshot = model.snapshot {
            products(snapshot.portfolio)
            if model.autoClosed.count > 0 { AutoClosedRow() }
            RunningFold()
        } else {
            SnapshotEmptyView()
        }
    }

    /// The products and, between "People use these" and "Being built", the top decisions.
    @ViewBuilder
    private func products(_ portfolio: Portfolio?) -> some View {
        switch portfolio.map(HomeSections.layout) {
        case nil:
            Text(HomeText.noPortfolio).foregroundStyle(Palette.textSecondary)
            HomeDecisionsSection()
        case .legacy(let cards):
            VStack(alignment: .leading, spacing: Space.m) {
                HomeSectionHeader(title: "Products", note: "Update the teyla command to rank them by users and activity.")
                if cards.isEmpty {
                    Text("No products yet.").foregroundStyle(Palette.textSecondary)
                } else {
                    LegacyList(cards: cards)
                }
            }
            HomeDecisionsSection()
        case .sections(let sections):
            PeriodSwitch(period: Binding(get: { period }, set: { storedPeriod = $0.rawValue }))
            if sections.allSatisfy({ $0.products.isEmpty }) {
                Text("No products yet.").foregroundStyle(Palette.textSecondary)
            }
            section(sections, .users)
            HomeDecisionsSection()
            section(sections, .building)
            section(sections, .quiet)
        }
    }

    @ViewBuilder
    private func section(_ sections: [HomeSection], _ kind: HomeSectionKind) -> some View {
        if let section = sections.first(where: { $0.kind == kind }), !section.products.isEmpty {
            VStack(alignment: .leading, spacing: Space.m + Space.xxs) {
                HomeSectionHeader(title: kind.title, note: kind.note)
                switch kind {
                case .users: HeroGrid(products: section.products, period: period)
                case .building: BuiltGrid(products: section.products, period: period)
                case .quiet: QuietList(products: section.products)
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Space.xs + Space.xxs) {
            Text(model.briefLine)
                .font(Typo.brief)
                .lineSpacing(Space.xxs)
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            if let snapshot = model.snapshot {
                Text(HomeText.caption(decisions: model.ownerAsks.count, running: snapshot.running.count,
                                      spend: HomeText.spend(portfolio: snapshot.portfolio, todayUSD: snapshot.totals.spentTodayUSD)))
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
    }
}

/// Week / Month / Year. One switch for the whole page; it changes numbers and nothing else.
struct PeriodSwitch: View {
    @Binding var period: HomePeriod

    var body: some View {
        HStack(spacing: Space.xxs) {
            ForEach(HomePeriod.allCases) { option in
                Button {
                    period = option
                } label: {
                    Text(option.label)
                        .font(Typo.body.weight(.semibold))
                        .foregroundStyle(period == option ? Palette.text : Palette.textSecondary)
                        .padding(.horizontal, Space.xl - Space.xs)
                        .frame(minHeight: Space.touchMin - 2 * Space.xs)
                        .background(period == option ? Palette.surface : Color.clear,
                                    in: RoundedRectangle(cornerRadius: Radius.card - Space.xxs))
                        .contentShape(RoundedRectangle(cornerRadius: Radius.card - Space.xxs))
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(period == option ? .isSelected : [])
            }
        }
        .padding(Space.xs)
        .background(Palette.track, in: RoundedRectangle(cornerRadius: Radius.card))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Period")
    }
}

/// What the window shows before the first snapshot arrives, or when reading it failed.
struct SnapshotEmptyView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            if let error = model.lastError {
                Label("Could not read state", systemImage: "exclamationmark.triangle")
                    .font(Typo.lead)
                    .foregroundStyle(Palette.warning)
                Text(error)
                    .foregroundStyle(Palette.textSecondary)
                    .textSelection(.enabled)
                Button("Try again") { model.refresh() }
            } else {
                HStack(spacing: Space.s) {
                    ProgressView().controlSize(.small)
                    Text("Reading your sessions…").foregroundStyle(Palette.textSecondary)
                }
            }
        }
        .padding(.top, Space.s)
    }
}

/// The star on a product. With the CLI it sets the core list; without it (the store build) a starred product only shows its star.
struct StarButton: View {
    @Environment(AppModel.self) private var model
    let id: String
    let starred: Bool

    var body: some View {
        if model.capabilities.editProducts, let portfolio = model.snapshot?.portfolio {
            let allowed = CoreEdit.canToggle(id, in: portfolio)
            let help = CoreEdit.help(starred: starred, source: portfolio.coreSource, canToggle: allowed)
            Button {
                model.toggleStar(id)
            } label: {
                star
            }
            .buttonStyle(.plain)
            .disabled(model.isChangingCore || !allowed)
            .help(help)
            .accessibilityLabel(starred ? "In the core list" : "Not in the core list")
            .accessibilityHint(help)
        } else if starred {
            star.accessibilityLabel("In the core list")
        }
    }

    private var star: some View {
        Image(systemName: starred ? "star.fill" : "star")
            .font(Typo.lead)
            .foregroundStyle(starred ? Palette.warning : Palette.textSecondary)
            .frame(width: Space.starTarget, height: Space.starTarget)
            .contentShape(Rectangle())
    }
}

// MARK: Decisions

private struct HomeDecisionsSection: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let owner = model.ownerAsks
        let fresh = AskFold.partition(owner) { model.age(of: $0) }.fresh
        let shown = Decisions.homeList(fresh)
        VStack(alignment: .leading, spacing: Space.m) {
            HomeSectionHeader(title: "Decisions", note: "Only you can answer these")
            if owner.isEmpty {
                Label("Nothing waits on you.", systemImage: "checkmark.circle")
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.vertical, Space.s)
            } else {
                if shown.isEmpty {
                    Text("Nothing new. The rest waited more than 7 days.")
                        .foregroundStyle(Palette.textSecondary)
                }
                ForEach(shown) { ask in
                    AskCard(ask: ask)
                        .transition(.opacity.combined(with: .scale(scale: 0.97)))
                }
                if let label = Decisions.seeAll(total: owner.count, shown: shown.count) {
                    Button(label) { model.go(.decisions) }
                        .buttonStyle(.link)
                }
            }
        }
        .animation(.easeOut(duration: 0.25), value: shown.map(\.id))
    }
}

// MARK: What Teyla closed

/// "Teyla closed 3 questions", with the reasons one click away and an Undo for each.
private struct AutoClosedRow: View {
    @Environment(AppModel.self) private var model
    @State private var open = false

    var body: some View {
        let closed = model.autoClosed
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(spacing: Space.s) {
                Image(systemName: "checkmark.circle").foregroundStyle(Palette.textSecondary)
                Text(AutoClosedText.heading(count: closed.count)).font(Typo.body)
                Spacer(minLength: Space.s)
                if !closed.items.isEmpty {
                    Button(open ? "Hide" : "Review") {
                        withAnimation(.easeOut(duration: 0.2)) { open.toggle() }
                    }
                    .buttonStyle(.link)
                    .accessibilityValue(open ? "Expanded" : "Collapsed")
                }
            }
            if open {
                ForEach(closed.items) { item in
                    AutoClosedItemRow(item: item)
                }
            }
        }
        .padding(.vertical, Space.s)
        .overlay(alignment: .top) { Divider() }
    }
}

private struct AutoClosedItemRow: View {
    @Environment(AppModel.self) private var model
    let item: AutoClosedItem

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(item.title).font(Typo.body).fixedSize(horizontal: false, vertical: true)
                    Text(detail).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: Space.s)
                if model.capabilities.closeQuestions {
                    switch model.cards[item.id] {
                    case .sending:
                        ProgressView().controlSize(.small)
                    default:
                        Button("Undo") { model.undoClosed(item) }
                    }
                }
            }
            if case .failed(let message) = model.cards[item.id] {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.danger)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Button("Back") { model.dismissUndoError(item) }
                    .buttonStyle(.borderless)
            }
        }
        .padding(.leading, Space.l)
    }

    private var detail: String {
        [Format.product(item.product), item.reason].filter { !$0.isEmpty }.joined(separator: " · ")
    }
}

// MARK: Running

/// "Running now (3)", folded: the sessions active in the last 10 minutes, each with its correction field.
private struct RunningFold: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let running = model.snapshot?.running ?? []
        if !running.isEmpty {
            Fold(title: "Running now (\(running.count))", spokenTitle: "Running now, \(running.count) sessions") {
                VStack(alignment: .leading, spacing: Space.xs) {
                    ForEach(running) { session in
                        RunningRow(session: session)
                    }
                }
            }
        }
    }
}

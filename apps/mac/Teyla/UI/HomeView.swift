import SwiftUI

/// Home: one sentence, the core products and how far each has got, the top decisions, and what runs.
/// Health, notes, finished work and the status column live on their own pages.
struct HomeView: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.xl) {
                header
                if model.snapshot == nil {
                    SnapshotEmptyView()
                } else {
                    CoreProductsSection()
                    HomeDecisionsSection()
                    if model.autoClosed.count > 0 { AutoClosedRow() }
                    RunningFold()
                }
            }
            .padding(.horizontal, Space.xl + Space.xs)
            .padding(.vertical, Space.xl)
            .frame(maxWidth: Space.homeMax, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Palette.background)
        .navigationTitle("Home")
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

// MARK: Core products

private struct CoreProductsSection: View {
    @Environment(AppModel.self) private var model
    @State private var width: CGFloat = 0

    var body: some View {
        let portfolio = model.snapshot?.portfolio
        let cards = portfolio.map(CoreCards.cards) ?? []
        let canStar = model.capabilities.editProducts
        VStack(alignment: .leading, spacing: Space.m) {
            HStack(alignment: .firstTextBaseline) {
                SectionLabel("Core products")
                Spacer(minLength: Space.s)
                Button("All products") { model.go(.portfolio) }
                    .buttonStyle(.link)
            }
            if let note = HomeText.coreNote(source: portfolio?.coreSource ?? "", canStar: canStar) {
                Text(note).font(Typo.body).foregroundStyle(Palette.textSecondary)
            }
            if case .failed(let message) = model.coreChange {
                Label(message, systemImage: "exclamationmark.triangle.fill")
                    .font(Typo.body)
                    .foregroundStyle(Palette.danger)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
                Button("Back") { model.dismissCoreError() }
                    .buttonStyle(.borderless)
            }
            if cards.isEmpty {
                Text(HomeText.coreEmpty(hasPortfolio: portfolio != nil, canStar: canStar))
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.vertical, Space.s)
            } else {
                let count = CoreCards.columns(width: width, minCard: Space.coreCardMin, spacing: Space.l)
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: Space.l, alignment: .top), count: count),
                          alignment: .leading, spacing: Space.l) {
                    ForEach(cards) { card in
                        CoreProductCard(card: card)
                    }
                }
            }
        }
        .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
    }
}

/// One core product: where it stands in facts. A click opens its page; the star sets the core list.
private struct CoreProductCard: View {
    @Environment(AppModel.self) private var model
    let card: CoreCard

    var body: some View {
        Button {
            model.go(.product(card.id))
        } label: {
            VStack(alignment: .leading, spacing: Space.s) {
                Text(card.title)
                    .font(Typo.lead)
                    .lineLimit(1)
                    .padding(.trailing, Space.xl)
                if !card.line.isEmpty {
                    Text(card.line)
                        .font(Typo.body)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let blocker = card.blocker {
                    Label(blocker, systemImage: "hand.raised")
                        .font(Typo.body)
                        .foregroundStyle(Palette.needsYou)
                        .fixedSize(horizontal: false, vertical: true)
                }
                VStack(alignment: .leading, spacing: Space.xs) {
                    if !card.install.installable.isEmpty {
                        Fact(label: "Install", value: card.install.installable.joined(separator: " · "))
                    }
                    if !card.install.pending.isEmpty {
                        Fact(label: "Not installable", value: card.install.pending.joined(separator: " · "))
                    }
                    Fact(label: "Shipped", value: [card.shipped, card.latest].compactMap { $0 }.joined(separator: " · "))
                    if let users = card.users { Fact(label: "Users", value: users) }
                    if let milestone = card.milestone { Fact(label: "Milestone", value: milestone) }
                    if let quiet = card.quiet { Fact(label: "", value: quiet) }
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .card()
            .contentShape(RoundedRectangle(cornerRadius: Radius.card))
        }
        .buttonStyle(.plain)
        .overlay(alignment: .topTrailing) {
            StarButton(id: card.id, starred: card.starred)
                .padding(Space.m)
        }
        .help("Open the \(card.title) page")
        .accessibilityHint("Opens the product page")
    }
}

/// "Install  iOS 1.4.0 (52)": a quiet label and its value, wrapping together.
private struct Fact: View {
    let label: String
    let value: String

    var body: some View {
        (label.isEmpty ? Text(value) : Text(label + " ").foregroundStyle(Palette.textSecondary) + Text(value))
            .font(Typo.body)
            .fixedSize(horizontal: false, vertical: true)
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
            SectionLabel("Decisions")
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
        .readingWidth()
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
        .readingWidth()
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
            .readingWidth()
        }
    }
}

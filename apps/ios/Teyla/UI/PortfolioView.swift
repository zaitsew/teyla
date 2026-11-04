import SwiftUI

/// Where every product stands: a count line, then one row per product, worst first.
struct PortfolioView: View {
    @Environment(AppModel.self) private var model
    @Binding var showNewTask: Bool
    @State private var filter: PortfolioFilter = .all
    @State private var path: [ProductRoute]

    init(showNewTask: Binding<Bool>, options: LaunchOptions = LaunchOptions()) {
        _showNewTask = showNewTask
        _path = State(initialValue: options.openProduct.map { [ProductRoute(id: $0)] } ?? [])
    }

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Space.m) {
                    if let snapshot = model.snapshot {
                        if let portfolio = snapshot.portfolio {
                            Header(portfolio: portfolio, filter: $filter)
                            list(portfolio)
                        } else {
                            NoPortfolioView()
                        }
                    } else {
                        WaitingView()
                    }
                }
                .padding(.horizontal, Space.l)
                .padding(.top, Space.s)
                .padding(.bottom, Space.xxl)
                .frame(maxWidth: Space.readingCard)
                .frame(maxWidth: .infinity)
            }
            .background(Palette.background)
            .refreshable { await model.refresh() }
            .navigationTitle("All products")
            .navigationBarTitleDisplayMode(.large)
            .navigationDestination(for: ProductRoute.self) { route in
                PortfolioDetailView(productID: route.id)
            }
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showNewTask = true } label: { Text("New task").fontWeight(.semibold) }
                        .disabled(model.snapshot == nil)
                }
            }
        }
    }

    @ViewBuilder
    private func list(_ portfolio: Portfolio) -> some View {
        let shown = PortfolioFormat.visible(portfolio.products, filter: filter)
        if portfolio.products.isEmpty {
            Label("No products are registered on your Mac yet.", systemImage: "tray")
                .foregroundStyle(Palette.textSecondary)
        } else if shown.isEmpty {
            Label("Nothing needs attention.", systemImage: "checkmark.circle")
                .foregroundStyle(Palette.textSecondary)
        }
        ForEach(shown) { product in
            NavigationLink(value: ProductRoute(id: product.id)) {
                PortfolioRow(product: product)
            }
            .buttonStyle(.plain)
        }
    }
}

struct ProductRoute: Hashable {
    let id: String
}

/// "2 off track \u{00B7} 3 at risk \u{00B7} 14 on track", when the stores were read, and the filter.
private struct Header: View {
    let portfolio: Portfolio
    @Binding var filter: PortfolioFilter

    @ViewBuilder private var chips: some View {
        ForEach(PortfolioFilter.allCases) { option in
            Button {
                filter = option
            } label: {
                Label(option.title, systemImage: filter == option ? "checkmark" : "line.3.horizontal.decrease")
                    .lineLimit(1)
            }
            .buttonStyle(.bordered)
            .tint(filter == option ? Palette.primary : Palette.textSecondary)
            .accessibilityAddTraits(filter == option ? .isSelected : [])
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Text(PortfolioFormat.headline(for: portfolio))
                .font(Typo.section)
                .fixedSize(horizontal: false, vertical: true)
            Text(PortfolioFormat.checkedLine(portfolio, now: Date()))
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            SyncLine()
            ViewThatFits(in: .horizontal) {
                HStack(spacing: Space.s) { chips }
                VStack(alignment: .leading, spacing: Space.s) { chips }
            }
            .padding(.top, Space.xs)
        }
        .padding(.bottom, Space.xs)
    }
}

/// Shown when the Mac's Teyla is older than version 3 and sends no portfolio.
private struct NoPortfolioView: View {
    var body: some View {
        VStack(spacing: Space.m) {
            Spacer(minLength: Space.xxl)
            Image(systemName: "arrow.triangle.2.circlepath")
                .font(Glyph.empty)
                .foregroundStyle(Palette.textSecondary)
            Text("Update Teyla on your Mac to see the portfolio.")
                .font(Typo.section)
                .multilineTextAlignment(.center)
            Text("The portfolio needs the Mac to send snapshot version 3.")
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
    }
}

struct HealthPill: View {
    let health: Health

    var body: some View {
        Label(PortfolioFormat.healthLabel(health), systemImage: PortfolioFormat.healthSymbol(health))
            .font(Typo.caption.weight(.semibold))
            .foregroundStyle(health.color)
            .padding(.horizontal, Space.s)
            .padding(.vertical, Space.xxs)
            .background(health.color.chipTint, in: Capsule())
            .fixedSize()
    }
}

private struct PlatformChip: View {
    let platform: PlatformStatus

    var body: some View {
        Label {
            Text(PortfolioFormat.platformLine(platform))
                .fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: PortfolioFormat.platformSymbol(platform.platform))
        }
        .font(Typo.caption)
        .foregroundStyle(platform.state.color)
    }
}

private struct PortfolioRow: View {
    let product: PortfolioProduct

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                FlowLayout(spacing: Space.s) {
                    HealthPill(health: product.health)
                    let stage = PortfolioFormat.stageLine(product)
                    if !stage.isEmpty {
                        Text(stage).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    }
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(Typo.caption.weight(.semibold))
                    .foregroundStyle(Palette.textTertiary)
                    .accessibilityHidden(true)
            }
            Text(PortfolioFormat.title(product))
                .font(Typo.cardTitle)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
            if let reason = product.reasons.first {
                Text(reason)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !product.platforms.isEmpty {
                FlowLayout(spacing: Space.m) {
                    ForEach(product.platforms) { PlatformChip(platform: $0) }
                }
            }
            if product.waiting > 0 {
                Label(PortfolioFormat.waitingLine(product.waiting), systemImage: "hourglass")
                    .font(Typo.caption.weight(.semibold))
                    .foregroundStyle(Palette.needsYou)
            }
        }
        .card()
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens the product")
    }
}

// MARK: - Detail

/// One product: why it is where it is, every platform, pull requests, activity, the next step and its questions.
struct PortfolioDetailView: View {
    @Environment(AppModel.self) private var model
    let productID: String

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: Space.l) {
                if let product = model.snapshot?.portfolio?.product(productID), let snapshot = model.snapshot {
                    Content(product: product, snapshot: snapshot)
                } else {
                    Label("This product is no longer in the portfolio.", systemImage: "questionmark.circle")
                        .foregroundStyle(Palette.textSecondary)
                }
            }
            .padding(.horizontal, Space.l)
            .padding(.top, Space.s)
            .padding(.bottom, Space.xxl)
            .frame(maxWidth: Space.readingCard)
            .frame(maxWidth: .infinity)
        }
        .background(Palette.background)
        .refreshable { await model.refresh() }
        .navigationBarTitleDisplayMode(.inline)
    }

    private struct Content: View {
        let product: PortfolioProduct
        let snapshot: Snapshot

        var body: some View {
            let now = Date()
            VStack(alignment: .leading, spacing: Space.s) {
                HealthPill(health: product.health)
                Text(PortfolioFormat.title(product))
                    .font(Typo.pageTitle)
                    .fixedSize(horizontal: false, vertical: true)
                let stage = PortfolioFormat.stageLine(product)
                if !stage.isEmpty {
                    Text(stage).font(Typo.body).foregroundStyle(Palette.textSecondary)
                }
            }
            .accessibilityElement(children: .combine)

            Group {
                SectionLabel("Why")
                if product.reasons.isEmpty {
                    Text(product.health == .parked ? "This product is parked." : "Nothing is holding it back.")
                        .foregroundStyle(Palette.textSecondary)
                } else {
                    VStack(alignment: .leading, spacing: Space.s) {
                        ForEach(Array(product.reasons.enumerated()), id: \.offset) { _, reason in
                            Label {
                                Text(reason).fixedSize(horizontal: false, vertical: true)
                            } icon: {
                                Image(systemName: PortfolioFormat.healthSymbol(product.health))
                                    .foregroundStyle(product.health.color)
                            }
                        }
                    }
                    .card()
                }
            }

            if !product.milestone.isEmpty || !product.next.isEmpty {
                VStack(alignment: .leading, spacing: Space.s) {
                    if !product.milestone.isEmpty { Fact(title: "Milestone", text: product.milestone) }
                    if !product.next.isEmpty { Fact(title: "Next step", text: product.next) }
                }
                .card()
            }

            Group {
                SectionLabel("Platforms")
                if product.platforms.isEmpty {
                    Text("No platform is registered for this product.").foregroundStyle(Palette.textSecondary)
                }
                ForEach(product.platforms) { PlatformCard(platform: $0, now: now) }
            }

            Group {
                SectionLabel("Pull requests")
                HStack(alignment: .top, spacing: Space.l) {
                    Number(value: product.prs.open, label: "open")
                    Number(value: product.prs.waiting, label: "wait on you", highlight: product.prs.waiting > 0)
                    Number(value: product.prs.merged7d, label: "merged, 7 days")
                    Number(value: product.prs.unreviewed7d, label: "merged unreviewed",
                           highlight: product.prs.unreviewed7d > 0)
                }
                .card()
            }

            Group {
                SectionLabel("Activity")
                VStack(alignment: .leading, spacing: Space.s) {
                    Text(PortfolioFormat.sessionsLine(product.activity, now: now))
                    Text(PortfolioFormat.spendLine(product.activity)).foregroundStyle(Palette.textSecondary)
                }
                .font(Typo.body)
                .fixedSize(horizontal: false, vertical: true)
                .card()
            }

            let asks = PortfolioFormat.questions(for: product, in: snapshot.asks)
            if !asks.isEmpty {
                Group {
                    SectionLabel("Needs you")
                    ForEach(asks) { ask in
                        QuestionCard(ask: ask, ageSeconds: PhoneFormat.age(ask.ageSeconds, snapshot: snapshot, now: now))
                    }
                }
            } else if product.waiting > 0 {
                Label("\(PortfolioFormat.waitingLine(product.waiting)) on your Mac.", systemImage: "hourglass")
                    .foregroundStyle(Palette.needsYou)
            }
        }
    }
}

private struct Fact: View {
    let title: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(title).font(Typo.caption.weight(.semibold)).foregroundStyle(Palette.textSecondary)
            Text(text).font(Typo.body).fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

private struct Number: View {
    let value: Int
    let label: String
    var highlight = false

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text("\(value)")
                .font(Typo.section)
                .monospacedDigit()
                .foregroundStyle(highlight ? Palette.needsYou : Palette.text)
            Text(label).font(Typo.caption).foregroundStyle(Palette.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
}

private struct PlatformCard: View {
    @Environment(\.openURL) private var openURL
    let platform: PlatformStatus
    let now: Date

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                Image(systemName: PortfolioFormat.platformSymbol(platform.platform))
                    .foregroundStyle(Palette.textSecondary)
                Text(PortfolioFormat.platformName(platform.platform)).font(Typo.cardTitle)
                if platform.isPrimary {
                    Text("primary").font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            }
            Text(PortfolioFormat.platformLine(platform))
                .font(Typo.body.weight(.medium))
                .foregroundStyle(platform.state == .blocked || platform.state == .behind ? platform.state.color : Palette.text)
            if !platform.detail.isEmpty {
                Text(platform.detail)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let checked = PortfolioFormat.checkedAgo(platform.asOf, now: now) {
                Text(checked).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
            if let url = PhoneFormat.webURL(platform.link) {
                Button { openURL(url) } label: {
                    Label(PhoneFormat.linkLabel(url), systemImage: "link").lineLimit(1)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
        .card()
        .accessibilityElement(children: .contain)
    }
}

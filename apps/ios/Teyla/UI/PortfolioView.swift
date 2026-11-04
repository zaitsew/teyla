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
                            Header(portfolio: portfolio, filter: $filter, selling: sellingLine(portfolio))
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

    private func sellingLine(_ portfolio: Portfolio) -> String? {
        let growth = model.snapshot?.console?.compact.growth ?? .missing
        guard let none = PhoneConsole.notTried(growth, products: portfolio.products), !none.next.isEmpty else { return nil }
        return none.next.count == 1 ? "1 product has not been tried to sell yet." : "\(none.next.count) products have not been tried to sell yet."
    }

    @ViewBuilder
    private func list(_ portfolio: Portfolio) -> some View {
        let growth = model.snapshot?.console?.compact.growth ?? .missing
        let shown = PortfolioFormat.visible(portfolio.products, filter: filter)
        if portfolio.products.isEmpty {
            Label("No products are registered on your Mac yet.", systemImage: "tray")
                .foregroundStyle(Palette.textSecondary)
        } else if shown.isEmpty {
            Label("Nothing needs attention.", systemImage: "checkmark.circle")
                .foregroundStyle(Palette.textSecondary)
        }
        if !shown.isEmpty {
            RowGroup {
                ForEach(shown) { product in
                    NavigationLink(value: ProductRoute(id: product.id)) {
                        PortfolioRow(product: product,
                                     selling: PhoneConsole.sellingLine(
                                         productID: product.id, growth: growth, parked: product.health == .parked),
                                     startup: model.startup(for: product.id))
                    }
                    .buttonStyle(.plain)
                }
            }
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
    /// "3 products are not tried to sell yet", when the Mac said which.
    var selling: String?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Text(PortfolioFormat.headline(for: portfolio))
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
            Text(PortfolioFormat.checkedLine(portfolio, now: Date()))
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(2)
            if let selling { Text(selling).font(Typo.caption).foregroundStyle(Palette.primary).fixedSize(horizontal: false, vertical: true) }
            SyncLine()
            SegmentSwitch(options: PortfolioFilter.allCases.map { ($0, $0.title) }, selection: $filter,
                          spokenLabel: "Show", fills: true)
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
    /// "Not tried to sell yet", when the Mac says nobody posted, ran marketing or met a person who fits.
    var selling: String?
    /// The earned stage (docs/STARTUP.md), when the Mac sent it.
    var startup: PhoneStartup?

    private var name: String { PortfolioFormat.title(product) }
    private var line: String {
        if let line = ProductLine.text(product) { return line }
        let summary = HomeFactsBuilder.summary(product)
        return summary.isEmpty ? HomeFactsBuilder.noSummary : summary
    }
    /// "Beta · testers · 3 questions wait": the stage shares a line with the reason, so the name keeps the top line.
    private var subtitle: String {
        [PortfolioFormat.stageLine(product), line].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(spacing: Space.m) {
                ProductIcon(product: product, monogram: Monogram.letter(for: name), size: Space.iconRow, radius: Radius.iconRow)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(name).font(Typo.cardTitle).lineLimit(1)
                    Text(subtitle)
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(2)
                        .multilineTextAlignment(.leading)
                    // "Built · Not tried to sell yet": the stage the evidence shows, then the push it needs.
                    if let stageLine = StartupFormat.rowLine(startup, selling: selling) {
                        Label(stageLine, systemImage: selling == nil ? "flag" : "megaphone")
                            .font(Typo.caption.weight(.medium))
                            .foregroundStyle(selling == nil ? Palette.textSecondary : Palette.primary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
                // "On track" on every row is noise: the pill appears when there is something to say.
                if product.health != .onTrack { HealthPill(health: product.health) }
                Image(systemName: "chevron.right")
                    .font(Typo.caption.weight(.semibold))
                    .foregroundStyle(Palette.textTertiary)
                    .accessibilityHidden(true)
            }
            HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                platforms
                Spacer(minLength: 0)
                spark.frame(width: Space.tableSpark, alignment: .trailing)
                figure("\(product.prs.open)", "PRs")
                figure("\(product.waiting)", "Waiting", tone: product.waiting > 0 ? Palette.needsYou : nil)
                figure(HomeNumbers.dollars(product.activity.spend7dUSD), "7 days")
                    .accessibilityLabel("Spend over 7 days: \(HomeNumbers.dollars(product.activity.spend7dUSD))")
            }
        }
        .padding(.vertical, Space.m)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens the product")
    }

    private var platforms: some View {
        HStack(spacing: Space.xs) {
            ForEach(product.platforms) { platform in
                Image(systemName: PortfolioFormat.platformSymbol(platform.platform))
                    .font(Typo.caption)
                    .foregroundStyle(platform.state.color)
                    .accessibilityLabel(PortfolioFormat.platformLine(platform))
            }
        }
    }

    @ViewBuilder
    private var spark: some View {
        let facts = HomeFactsBuilder.facts(product, period: .week)
        if let label = facts.sparkLabel {
            SparklineView(heights: facts.sparkHeights, label: label)
        }
    }

    private func figure(_ value: String, _ label: String, tone: Color? = nil) -> some View {
        VStack(alignment: .trailing, spacing: Space.xxs) {
            Text(value).font(Typo.body.weight(.semibold)).monospacedDigit().foregroundStyle(tone ?? Palette.text).lineLimit(1)
            Text(label).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
        }
        .frame(width: Space.tableFigure, alignment: .trailing)
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
                    Content(product: product, snapshot: snapshot, startup: model.startup(for: productID))
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
        let startup: PhoneStartup?

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

            if let startup { StartupSummary(startup: startup, now: now) }

            // The startup sentence already says "nobody has tried to sell it" when that is the next fact.
            if startup?.next?.rung != "tried",
               let selling = PhoneConsole.sellingLine(productID: product.id, growth: snapshot.console?.compact.growth ?? .missing,
                                                      parked: product.health == .parked) {
                Label {
                    Text(product.health == .parked ? selling : selling + ". It gets the next post.").fixedSize(horizontal: false, vertical: true)
                } icon: {
                    Image(systemName: "megaphone")
                }
                .font(Typo.body)
                .foregroundStyle(Palette.primary)
            }

            Group {
                SectionHeader(title: "Why")
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

            if !product.milestone.isEmpty || ProductLine.shortEnglish(product.next) != nil {
                VStack(alignment: .leading, spacing: Space.s) {
                    if !product.milestone.isEmpty { Fact(title: "Milestone", text: product.milestone) }
                    if let next = ProductLine.shortEnglish(product.next) { Fact(title: "Next step", text: next) }
                }
                .card()
            }

            Group {
                SectionHeader(title: "Platforms")
                if product.platforms.isEmpty {
                    Text("No platform is registered for this product.").foregroundStyle(Palette.textSecondary)
                }
                ForEach(product.platforms) { PlatformCard(platform: $0, now: now) }
            }

            Group {
                SectionHeader(title: "Pull requests")
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
                SectionHeader(title: "Activity")
                VStack(alignment: .leading, spacing: Space.s) {
                    Text(PortfolioFormat.sessionsLine(product.activity, now: now))
                    Text(PortfolioFormat.spendLine(product.activity)).foregroundStyle(Palette.textSecondary)
                }
                .font(Typo.body)
                .fixedSize(horizontal: false, vertical: true)
                .card()
            }

            if let startup {
                StartupLadder(startup: startup)
                StartupMetricGroups(startup: startup)
                if let yc = startup.yc, yc.eligible { StartupYCLine(yc: yc) }
            }

            let asks = PortfolioFormat.questions(for: product, in: snapshot.asks)
            if !asks.isEmpty {
                Group {
                    SectionHeader(title: "Needs you")
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

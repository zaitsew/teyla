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
                LazyVStack(alignment: .leading, spacing: 12) {
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
                .padding(.horizontal, 16)
                .padding(.top, 8)
                .padding(.bottom, 32)
                .frame(maxWidth: 640)
                .frame(maxWidth: .infinity)
            }
            .background(Color(.systemGroupedBackground))
            .refreshable { await model.refresh() }
            .navigationTitle("Portfolio")
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
                .foregroundStyle(.secondary)
        } else if shown.isEmpty {
            Label("Nothing needs attention.", systemImage: "checkmark.circle")
                .foregroundStyle(.secondary)
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

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(PortfolioFormat.headline(for: portfolio))
                .font(.title3.weight(.semibold))
                .fixedSize(horizontal: false, vertical: true)
            Text(PortfolioFormat.checkedLine(portfolio, now: Date()))
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            SyncLine()
            FlowLayout(spacing: 8) {
                ForEach(PortfolioFilter.allCases) { option in
                    Button {
                        filter = option
                    } label: {
                        Label(option.title, systemImage: filter == option ? "checkmark" : "line.3.horizontal.decrease")
                            .labelStyle(.titleAndIcon)
                    }
                    .buttonStyle(.bordered)
                    .tint(filter == option ? Color.brandPrimary : Color.secondary)
                    .accessibilityAddTraits(filter == option ? .isSelected : [])
                }
            }
            .padding(.top, 6)
        }
        .padding(.bottom, 4)
    }
}

/// Shown when the Mac's Teyla is older than version 3 and sends no portfolio.
private struct NoPortfolioView: View {
    var body: some View {
        VStack(spacing: 12) {
            Spacer(minLength: 80)
            Image(systemName: "arrow.triangle.2.circlepath")
                .font(.system(size: 40))
                .foregroundStyle(.secondary)
            Text("Update Teyla on your Mac to see the portfolio.")
                .font(.title3.weight(.semibold))
                .multilineTextAlignment(.center)
            Text("The portfolio needs the Mac to send snapshot version 3.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
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
            .font(.caption.weight(.semibold))
            .foregroundStyle(health.color)
            .padding(.horizontal, 9)
            .padding(.vertical, 3)
            .background(health.color.opacity(0.14), in: Capsule())
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
        .font(.caption)
        .foregroundStyle(platform.state.color)
    }
}

private struct PortfolioRow: View {
    let product: PortfolioProduct

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                FlowLayout(spacing: 8) {
                    HealthPill(health: product.health)
                    let stage = PortfolioFormat.stageLine(product)
                    if !stage.isEmpty {
                        Text(stage).font(.caption).foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.tertiary)
                    .accessibilityHidden(true)
            }
            Text(PortfolioFormat.title(product))
                .font(.headline)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
            if let reason = product.reasons.first {
                Text(reason)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !product.platforms.isEmpty {
                FlowLayout(spacing: 12) {
                    ForEach(product.platforms) { PlatformChip(platform: $0) }
                }
            }
            if product.waiting > 0 {
                Label(PortfolioFormat.waitingLine(product.waiting), systemImage: "hourglass")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Color.brandAmber)
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
            LazyVStack(alignment: .leading, spacing: 20) {
                if let product = model.snapshot?.portfolio?.product(productID), let snapshot = model.snapshot {
                    Content(product: product, snapshot: snapshot)
                } else {
                    Label("This product is no longer in the portfolio.", systemImage: "questionmark.circle")
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 32)
            .frame(maxWidth: 640)
            .frame(maxWidth: .infinity)
        }
        .background(Color(.systemGroupedBackground))
        .refreshable { await model.refresh() }
        .navigationBarTitleDisplayMode(.inline)
    }

    private struct Content: View {
        let product: PortfolioProduct
        let snapshot: Snapshot

        var body: some View {
            let now = Date()
            VStack(alignment: .leading, spacing: 8) {
                HealthPill(health: product.health)
                Text(PortfolioFormat.title(product))
                    .font(.largeTitle.weight(.bold))
                    .fixedSize(horizontal: false, vertical: true)
                let stage = PortfolioFormat.stageLine(product)
                if !stage.isEmpty {
                    Text(stage).font(.subheadline).foregroundStyle(.secondary)
                }
            }
            .accessibilityElement(children: .combine)

            Group {
                SectionLabel("Why")
                if product.reasons.isEmpty {
                    Text(product.health == .parked ? "This product is parked." : "Nothing is holding it back.")
                        .foregroundStyle(.secondary)
                } else {
                    VStack(alignment: .leading, spacing: 8) {
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
                VStack(alignment: .leading, spacing: 10) {
                    if !product.milestone.isEmpty { Fact(title: "Milestone", text: product.milestone) }
                    if !product.next.isEmpty { Fact(title: "Next step", text: product.next) }
                }
                .card()
            }

            Group {
                SectionLabel("Platforms")
                if product.platforms.isEmpty {
                    Text("No platform is registered for this product.").foregroundStyle(.secondary)
                }
                ForEach(product.platforms) { PlatformCard(platform: $0, now: now) }
            }

            Group {
                SectionLabel("Pull requests")
                HStack(alignment: .top, spacing: 16) {
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
                VStack(alignment: .leading, spacing: 8) {
                    Text(PortfolioFormat.sessionsLine(product.activity, now: now))
                    Text(PortfolioFormat.spendLine(product.activity)).foregroundStyle(.secondary)
                }
                .font(.subheadline)
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
                    .foregroundStyle(Color.brandAmber)
            }
        }
    }
}

private struct Fact: View {
    let title: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            Text(text).font(.subheadline).fixedSize(horizontal: false, vertical: true)
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
        VStack(alignment: .leading, spacing: 2) {
            Text("\(value)")
                .font(.title2.weight(.semibold))
                .monospacedDigit()
                .foregroundStyle(highlight ? Color.brandAmber : Color.primary)
            Text(label).font(.caption).foregroundStyle(.secondary)
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
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: PortfolioFormat.platformSymbol(platform.platform))
                    .foregroundStyle(.secondary)
                Text(PortfolioFormat.platformName(platform.platform)).font(.headline)
                if platform.isPrimary {
                    Text("primary").font(.caption).foregroundStyle(.secondary)
                }
            }
            Text(PortfolioFormat.platformLine(platform))
                .font(.subheadline.weight(.medium))
                .foregroundStyle(platform.state == .blocked || platform.state == .behind ? platform.state.color : Color.primary)
            if !platform.detail.isEmpty {
                Text(platform.detail)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let checked = PortfolioFormat.checkedAgo(platform.asOf, now: now) {
                Text(checked).font(.caption).foregroundStyle(.secondary)
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

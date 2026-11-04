import SwiftUI

/// Money: what leaves the owner's accounts. Top to bottom: the figures, the subscriptions, what AI providers billed,
/// the list-price spend of local sessions (labelled as not cash), the cloud and the Actions minutes.
/// Cash and list price never share a figure or a total. A price the report lacks is a dash with the reason.
struct MoneyView: View {
    var body: some View {
        Page {
            ConsoleHeader(page: ConsoleText.money)
            ConsoleBlock(name: ConsoleText.money.title, pick: { $0.money }) { report in
                MoneyBody(report: report)
            }
        }
        .navigationTitle(ConsoleText.money.title)
    }
}

private struct MoneyBody: View {
    let report: MoneyReport

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            figures
            SubscriptionsSection(report: report)
            ProvidersSection(providers: report.providers)
            SpendSection(report: report)
            CloudSection(cloud: report.cloud, actions: report.actions)
        }
    }

    private var figures: some View {
        let cash = MoneyLogic.cash(report)
        let next = MoneyLogic.nextRenewal(report.forecast)
        return StatStrip {
            StatTile(label: "Cash per month", value: cash.value, detail: cash.detail)
            StatTile(label: "Next renewal", value: next?.days.map(MoneyLogic.inDays),
                     detail: next.map { "\($0.name)\($0.monthlyUSD.flatMap(MoneyLogic.usd).map { " · \($0) a month" } ?? "")" }
                         ?? "No renewal date is listed.")
            StatTile(label: "Credits included", value: MoneyLogic.usd(report.creditsTotalUSD),
                     detail: report.credits.isEmpty ? "No subscription lists credits." : "From \(report.credits.count) subscription\(report.credits.count == 1 ? "" : "s"), each month.")
            StatTile(label: "Actions minutes", value: MoneyLogic.minutes(report.actions?.minutesUsed),
                     detail: MoneyLogic.actionsDetail(report.actions))
        }
    }
}

// MARK: Subscriptions

private struct SubscriptionsSection: View {
    let report: MoneyReport

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Subscriptions", note: note, count: report.subscriptions.count)
            if report.subscriptions.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "No subscription is listed.",
                           detail: MoneyLogic.fileLine(report.file).map { "List them in \($0)." } ?? "")
            } else {
                RowGroup {
                    ForEach(MoneyLogic.subscriptionsInOrder(report.subscriptions)) { row in
                        let price = MoneyLogic.priceText(row)
                        RowCard(title: row.name, detail: price.known ? MoneyLogic.subscriptionDetail(row) : price.text) {
                            Text(price.known ? price.text : Format.dash)
                                .font(Typo.body.weight(.semibold))
                                .foregroundStyle(price.known ? Palette.text : Palette.textTertiary)
                                .lineLimit(1)
                        }
                    }
                }
                if let line = MoneyLogic.fileLine(report.file) {
                    Text("Prices come from \(line). Edit that file to change one.")
                        .font(Typo.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    private var note: String {
        guard let forecast = report.forecast else { return "" }
        let split = forecast.byCategory.sorted { $0.value > $1.value }
            .compactMap { key, value in MoneyLogic.usd(value).map { "\(MoneyLogic.categoryName(key)) \($0)" } }
        return split.joined(separator: " · ")
    }
}

// MARK: Providers

private struct ProvidersSection: View {
    let providers: [MoneyProvider]

    var body: some View {
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Billed by AI providers", note: "API charges in the last 30 days. This is cash, on top of the subscriptions.")
            if providers.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "The report lists no provider.")
            } else {
                RowGroup {
                    ForEach(providers) { provider in
                        let line = MoneyLogic.providerLine(provider)
                        RowCard(title: MoneyLogic.providerName(provider.name), detail: line.why) {
                            Text(line.value ?? Format.dash)
                                .font(Typo.body.weight(.semibold))
                                .foregroundStyle(line.value == nil ? Palette.textTertiary : Palette.text)
                                .lineLimit(1)
                        }
                    }
                }
            }
        }
    }
}

// MARK: Spend at list price

private struct SpendSection: View {
    let report: MoneyReport
    @State private var window = MoneyLogic.Window.month
    @State private var allProducts = false
    @State private var allModels = false

    var body: some View {
        let spend = MoneyLogic.window(report.spend, window)
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "AI sessions at list price", note: MoneyLogic.spendNote(report.spend))
            SegmentSwitch(options: MoneyLogic.Window.allCases.map { ($0, $0.label) }, selection: $window, spokenLabel: "Period")
            if let spend {
                StatStrip {
                    StatTile(label: "At list price", value: MoneyLogic.usd(spend.listUSD), detail: sessions(spend))
                    StatTile(label: "Of which subagents", value: MoneyLogic.usd(spend.subUSD),
                             detail: spend.subUSD == nil ? "The report gave no subagent figure." : "Work done by helper sessions.")
                    StatTile(label: "Billed by the API", value: MoneyLogic.usd(spend.billedUSD),
                             detail: spend.billedUSD == nil ? "No provider billing was read." : "What providers charged. This one is cash.")
                }
            } else {
                EmptyState(symbol: "questionmark.circle", title: "The report has no spend for this period.")
            }
            days
            shares(title: "By product", rows: report.byProduct, expanded: $allProducts)
            shares(title: "By model", rows: report.byModel, expanded: $allModels)
        }
    }

    private func sessions(_ spend: MoneyWindow) -> String {
        guard let count = spend.sessions else { return "The report gave no session count." }
        return "\(count.formatted()) session\(count == 1 ? "" : "s"), priced as if paid per call."
    }

    @ViewBuilder private var days: some View {
        let heights = MoneyLogic.dayHeights(report.byDay, last: 30)
        if !heights.isEmpty {
            VStack(alignment: .leading, spacing: Space.s) {
                SparklineView(heights: heights, label: MoneyLogic.dayCaption(report.byDay, last: 30),
                              height: Space.sparkHeroHeight, barWidth: Space.sparkHeroBar)
                Text(MoneyLogic.dayCaption(report.byDay, last: 30))
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .surface(padding: Space.m)
        }
    }

    @ViewBuilder private func shares(title: String, rows: [MoneyShare], expanded: Binding<Bool>) -> some View {
        let sorted = MoneyLogic.shares(rows, window: window)
        let shown = expanded.wrappedValue ? sorted : Array(sorted.prefix(MoneyLogic.foldAt))
        VStack(alignment: .leading, spacing: Space.s) {
            Text(title).font(Typo.cardTitle)
            if sorted.isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "The report has no rows for \(title.lowercased()).")
            } else {
                RowGroup {
                    ForEach(shown) { row in
                        ShareRow(row: row, fraction: MoneyLogic.fraction(row, of: sorted, window: window),
                                 amount: MoneyLogic.usd(MoneyLogic.amount(row, window)))
                    }
                }
                if sorted.count > MoneyLogic.foldAt {
                    Button(expanded.wrappedValue ? "Show fewer" : "Show all \(sorted.count)") { expanded.wrappedValue.toggle() }
                        .buttonStyle(.link)
                }
            }
        }
    }
}

/// A name, its amount at list price and a bar against the largest row.
private struct ShareRow: View {
    let row: MoneyShare
    let fraction: Double?
    let amount: String?

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            HStack(alignment: .firstTextBaseline, spacing: Space.m) {
                Text(row.name)
                    .font(Typo.body)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .help(row.name)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Text(amount ?? Format.dash)
                    .font(Typo.body.weight(.semibold).monospacedDigit())
                    .foregroundStyle(amount == nil ? Palette.textTertiary : Palette.text)
                    .lineLimit(1)
            }
            ProgressView(value: fraction ?? 0)
                .progressViewStyle(.linear)
                .tint(Palette.primaryMuted)
                .accessibilityHidden(true)
        }
        .padding(.vertical, Space.s)
        .accessibilityElement(children: .combine)
    }
}

// MARK: Cloud and Actions

private struct CloudSection: View {
    let cloud: [MoneyCloud]
    let actions: MoneyActions?

    var body: some View {
        let others = MoneyLogic.cloudWithoutActions(cloud, actions: actions)
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Cloud and Actions", note: "Minutes beyond the plan are billed.")
            if others.isEmpty, (actions?.accounts ?? []).isEmpty {
                EmptyState(symbol: "questionmark.circle", title: "The report lists no cloud cost and no Actions use.")
            } else {
                RowGroup {
                    ForEach(others) { row in
                        let price = MoneyLogic.cloudPrice(row)
                        RowCard(title: row.name, detail: row.detail ?? "") {
                            Text(price.known ? price.text : Format.dash)
                                .font(Typo.body.weight(.semibold))
                                .foregroundStyle(price.known ? Palette.text : Palette.textTertiary)
                                .lineLimit(1)
                        }
                    }
                    ForEach(actions?.accounts ?? []) { account in
                        RowCard(title: "GitHub Actions · \(account.account)", detail: MoneyLogic.accountDetail(account)) {
                            Text(MoneyLogic.paidText(account.paidUSD))
                                .font(Typo.body.weight(.semibold))
                                .foregroundStyle(account.paidUSD == nil ? Palette.textTertiary : Palette.text)
                                .lineLimit(1)
                        }
                    }
                }
            }
        }
    }
}

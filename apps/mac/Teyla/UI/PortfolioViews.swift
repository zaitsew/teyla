import AppKit
import SwiftUI

// The Portfolio screen and the pieces the product page and the Today column share: the health pill,
// the platform strip and the platform details.

extension Health {
    var color: Color {
        switch self {
        case .offTrack: return Palette.danger
        case .atRisk: return Palette.needsYou
        case .onTrack: return Palette.primary
        case .parked: return Palette.textSecondary
        }
    }
}

extension PlatformState {
    /// Green is for money saved, so a healthy platform is neutral; the state word carries the meaning.
    var color: Color {
        switch self {
        case .blocked: return Palette.danger
        case .behind: return Palette.needsYou
        case .inReview: return Palette.primary
        case .live, .current, .none, .unknown: return Palette.textSecondary
        }
    }
}

/// The platform's SF Symbol: the first name in the list that this macOS has.
enum PlatformSymbol {
    static func name(for platform: String) -> String {
        PortfolioText.symbols(for: platform).first {
            NSImage(systemSymbolName: $0, accessibilityDescription: nil) != nil
        } ?? "square.dashed"
    }
}

/// Health as a word and an icon, never colour alone.
struct HealthPill: View {
    let health: Health

    var body: some View {
        Chip(text: health.title, color: health.color, symbol: health.symbol)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(health.title)
    }
}

/// One compact chip per platform: "iOS 1.4.0 (52) · current".
struct PlatformStrip: View {
    let platforms: [PlatformStatus]

    var body: some View {
        if platforms.isEmpty {
            Text("No platform data yet").font(Typo.caption).foregroundStyle(Palette.textSecondary)
        } else {
            FlowLayout(spacing: Space.s) {
                ForEach(platforms) { platform in
                    Chip(text: PortfolioText.chip(platform), color: platform.state.color,
                         symbol: PlatformSymbol.name(for: platform.platform))
                        .help(tooltip(platform))
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel(PortfolioText.chip(platform))
                }
            }
        }
    }

    private func tooltip(_ platform: PlatformStatus) -> String {
        var lines = [platform.detail].filter { !$0.isEmpty }
        if let date = ISODate.parse(platform.asOf) {
            lines.append("Checked \(Format.ago(seconds: Date().timeIntervalSince(date)))")
        }
        return lines.isEmpty ? PortfolioText.chip(platform) : lines.joined(separator: "\n")
    }
}

// MARK: The Portfolio screen

struct PortfolioView: View {
    @Environment(AppModel.self) private var model
    @State private var filter: PortfolioFilter = .all
    @State private var showParked = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Space.xl) {
                if let portfolio = model.snapshot?.portfolio {
                    header(portfolio)
                    controls(portfolio)
                    rows(portfolio)
                } else {
                    VStack(alignment: .leading, spacing: Space.xs) {
                        Text("Portfolio").font(Typo.brief)
                        emptyState
                    }
                }
            }
            .padding(.horizontal, Space.xl + Space.xs)
            .padding(.vertical, Space.xl)
            .frame(maxWidth: Space.portfolioMax, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Palette.background)
        .navigationTitle("Portfolio")
    }

    private func header(_ portfolio: Portfolio) -> some View {
        VStack(alignment: .leading, spacing: Space.xs + Space.xxs) {
            Text("Portfolio").font(Typo.brief)
            Text(PortfolioText.summary(portfolio.counts)).font(Typo.lead)
            TimelineView(.periodic(from: .now, by: 30)) { context in
                Text(PortfolioText.checked(stores: portfolio.checkedStores, github: portfolio.checkedGitHub,
                                           now: context.date))
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
    }

    private func controls(_ portfolio: Portfolio) -> some View {
        HStack(spacing: Space.l) {
            Picker("Show", selection: $filter) {
                ForEach(PortfolioFilter.allCases) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .fixedSize()
            if portfolio.counts.parked > 0, filter == .all {
                Toggle("Show parked (\(portfolio.counts.parked))", isOn: $showParked)
                    .toggleStyle(.checkbox)
            }
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private func rows(_ portfolio: Portfolio) -> some View {
        let shown = filter.apply(portfolio.products, showParked: showParked)
        if shown.isEmpty {
            Label(filter == .needsAttention ? "Nothing needs attention." : "No products to show.",
                  systemImage: "checkmark.circle")
                .foregroundStyle(Palette.textSecondary)
        } else {
            VStack(spacing: Space.s) {
                ForEach(shown) { product in
                    PortfolioRow(product: product)
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            Label("Update the teyla command to see the portfolio (needs 0.32)", systemImage: "arrow.down.circle")
                .font(Typo.lead)
            Text("This screen reads the portfolio from `teyla state`. Your current command is older.")
                .foregroundStyle(Palette.textSecondary)
        }
        .padding(.top, Space.s)
    }
}

private struct PortfolioRow: View {
    @Environment(AppModel.self) private var model
    let product: PortfolioProduct

    var body: some View {
        Button {
            model.go(.product(product.id))
        } label: {
            HStack(alignment: .top, spacing: Space.xl) {
                VStack(alignment: .leading, spacing: Space.s) {
                    titleRow
                    if let line = summaryLine {
                        Text(line)
                            .font(Typo.body)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    PlatformStrip(platforms: product.platforms)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                figures
                    .frame(width: Space.portfolioFigures, alignment: .leading)
            }
            .card()
            .contentShape(RoundedRectangle(cornerRadius: Radius.card))
        }
        .buttonStyle(.plain)
        .help("Open the \(product.title) page")
        .accessibilityHint("Opens the product page")
    }

    private var titleRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            HealthPill(health: product.health)
            Text(product.title).font(Typo.lead)
            if product.focus {
                Image(systemName: "star.fill")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.warning)
                    .accessibilityLabel("In focus")
            }
            if !product.stage.isEmpty {
                Text(product.stage.capitalized).font(Typo.caption).foregroundStyle(Palette.textSecondary)
            }
        }
    }

    /// The first reason; for a healthy product, the next step or milestone.
    private var summaryLine: String? {
        if let reason = product.reasons.first { return reason }
        if !product.next.isEmpty { return "Next: \(product.next)" }
        return product.milestone.isEmpty ? nil : product.milestone
    }

    private var figures: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Label(PortfolioText.prs(product.prs), systemImage: "arrow.triangle.pull")
            Label(PortfolioText.waiting(product), systemImage: "bubble.left")
                .foregroundStyle(product.waiting > 0 ? Color.primary : Palette.textSecondary)
            TimelineView(.periodic(from: .now, by: 60)) { context in
                Label(PortfolioText.lastActivity(product.activity, now: context.date), systemImage: "clock")
            }
            Label(PortfolioText.spend(product.activity), systemImage: "dollarsign.circle")
                .monospacedDigit()
        }
        .font(Typo.caption)
        .foregroundStyle(Palette.textSecondary)
        .labelStyle(FigureLabelStyle())
    }
}

/// An icon and a line of text, aligned on the first line.
private struct FigureLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.xs) {
            configuration.icon.imageScale(.small).frame(width: Space.l)
            configuration.title.fixedSize(horizontal: false, vertical: true)
        }
    }
}

// MARK: The product page

/// Under the title on a product page: health, why, and the platform strip.
struct ProductStatusBlock: View {
    let product: PortfolioProduct

    var body: some View {
        VStack(alignment: .leading, spacing: Space.s) {
            HStack(spacing: Space.s) {
                HealthPill(health: product.health)
                if !product.milestone.isEmpty {
                    Text(product.milestone).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            }
            ForEach(Array(product.reasons.enumerated()), id: \.offset) { _, reason in
                Label(reason, systemImage: "circle.fill")
                    .labelStyle(BulletLabelStyle())
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
            }
            PlatformStrip(platforms: product.platforms)
        }
    }
}

private struct BulletLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: Space.s) {
            configuration.icon.font(.system(size: 4)).offset(y: -Space.xxs)
            configuration.title.fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// The side column of a product page on a wide window: one row per platform with its detail, then the work figures.
struct ProductFiguresColumn: View {
    @Environment(AppModel.self) private var model
    let product: PortfolioProduct

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xl) {
            VStack(alignment: .leading, spacing: Space.xs) {
                SectionLabel("Platforms")
                ForEach(product.platforms) { platform in
                    platformRow(platform)
                }
                if product.platforms.isEmpty {
                    Text("No platform data yet").foregroundStyle(Palette.textSecondary)
                }
            }
            VStack(alignment: .leading, spacing: Space.xs) {
                SectionLabel("Work")
                Label(PortfolioText.prs(product.prs), systemImage: "arrow.triangle.pull")
                Label(PortfolioText.waiting(product), systemImage: "bubble.left")
                Label(PortfolioText.lastActivity(product.activity, now: Date()), systemImage: "clock")
                Label(PortfolioText.spend(product.activity), systemImage: "dollarsign.circle").monospacedDigit()
                if !product.next.isEmpty {
                    Label("Next: \(product.next)", systemImage: "arrow.right.circle")
                }
            }
            .font(Typo.body)
            .foregroundStyle(Palette.textSecondary)
            .labelStyle(FigureLabelStyle())
        }
    }

    private func platformRow(_ platform: PlatformStatus) -> some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            HStack(spacing: Space.s) {
                Image(systemName: PlatformSymbol.name(for: platform.platform)).foregroundStyle(Palette.textSecondary)
                Text(PortfolioText.platformName(platform.platform)).font(Typo.body.weight(.semibold))
                let channel = PortfolioText.channelName(platform.channel)
                if !channel.isEmpty, channel != PortfolioText.platformName(platform.platform) { Text(channel).font(Typo.caption).foregroundStyle(Palette.textSecondary) }
                Spacer(minLength: Space.s)
                Chip(text: PortfolioText.stateWord(platform.state), color: platform.state.color)
            }
            let build = PortfolioText.build(platform)
            if !build.isEmpty {
                Text(build).font(Typo.body).foregroundStyle(Palette.textSecondary).monospacedDigit()
            }
            // The link line already says the address; do not repeat it as detail.
            if !platform.detail.isEmpty, platform.detail != Format.linkLabel(platform.link) {
                Text(platform.detail)
                    .font(Typo.body)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let date = ISODate.parse(platform.asOf) {
                Text("Checked \(Format.ago(seconds: Date().timeIntervalSince(date)))")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            }
            if let url = URL(string: platform.link), ["https", "http"].contains(url.scheme?.lowercased() ?? "") {
                Link(Format.linkLabel(platform.link), destination: url).font(Typo.caption)
            }
        }
        .padding(.vertical, Space.s)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .combine)
    }
}

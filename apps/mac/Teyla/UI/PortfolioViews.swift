import AppKit
import SwiftUI

// The All products screen and the pieces the product page shares: the health pill, the platform strip and
// the platform details.

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

// MARK: The All products screen

struct PortfolioView: View {
    @Environment(AppModel.self) private var model
    @State private var filter: PortfolioFilter = .all
    @State private var showParked = false

    var body: some View {
        Page {
            if let portfolio = model.snapshot?.portfolio {
                header(portfolio)
                StartupFocusBlock(portfolio: portfolio)
                controls(portfolio)
                rows(portfolio)
            } else {
                PageHeader(title: "All products")
                emptyState
            }
        }
        .navigationTitle("All products")
    }

    private func header(_ portfolio: Portfolio) -> some View {
        TimelineView(.periodic(from: .now, by: 30)) { context in
            PageHeader(title: "All products",
                       context: PortfolioText.summary(portfolio.counts) + " · "
                           + PortfolioText.checked(stores: portfolio.checkedStores, github: portfolio.checkedGitHub,
                                                   now: context.date))
        }
    }

    private func controls(_ portfolio: Portfolio) -> some View {
        HStack(spacing: Space.l) {
            SegmentSwitch(options: PortfolioFilter.allCases.map { ($0, $0.title) }, selection: $filter, spokenLabel: "Show")
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
            EmptyState(symbol: "checkmark.circle",
                       title: filter == .needsAttention ? "Nothing needs attention." : "No products to show.",
                       detail: "")
        } else {
            ProductTable(products: shown)
        }
    }

    private var emptyState: some View {
        EmptyState(symbol: "arrow.down.circle", title: "Update the teyla command to see products (needs 0.32).",
                   detail: "This screen reads the products from `teyla state`.")
    }
}

/// The product the startup page leads with: the one with the most outside weekly users, its stage and the one sentence about
/// what it is missing. Absent when the CLI names none (every product is parked or personal) or in the store build, which has no command.
private struct StartupFocusBlock: View {
    @Environment(AppModel.self) private var model
    let portfolio: Portfolio

    var body: some View {
        if let id = model.startup.focus, let product = portfolio.product(id), let block = product.startup {
            let name = HomeFactsBuilder.name(product)
            VStack(alignment: .leading, spacing: Space.s) {
                SectionHeader(title: "Focus", note: "The product with the most outside weekly users.")
                RowGroup {
                    Button {
                        model.go(.product(product.id))
                    } label: {
                        RowCard(title: name, detail: StartupText.sentence(block), wraps: true) {
                            ProductIcon(product: product, monogram: Monogram.letter(for: name), size: Space.iconRow, radius: Radius.iconRow)
                        } trailing: {
                            HStack(spacing: Space.s) {
                                Chip(text: block.stageTitle, color: Palette.primary)
                                Chip(text: StartupText.typeWord(block), color: block.typeSet ? Palette.textSecondary : Palette.needsYou)
                            }
                        }
                        .padding(.vertical, Space.xs)
                    }
                    .buttonStyle(.plain)
                    .help("Open the \(name) page")
                    .accessibilityHint("Opens the product page")
                }
            }
        }
    }
}

/// The products as one table: a header row, then one row each, with every figure in its own aligned column.
private struct ProductTable: View {
    let products: [PortfolioProduct]
    @State private var width: CGFloat = Space.pageMax

    private var compact: Bool { width < Space.tableCompact }

    var body: some View {
        RowGroup {
            ProductTableHeader(compact: compact)
            ForEach(products) { product in
                ProductTableRow(product: product, compact: compact)
            }
        }
        .onGeometryChange(for: CGFloat.self, of: \.size.width) { width = $0 }
    }
}

private struct ProductTableHeader: View {
    let compact: Bool

    var body: some View {
        HStack(spacing: Space.m) {
            Text("Product").frame(maxWidth: .infinity, alignment: .leading)
            if !compact { Text("Commits").frame(width: Space.tableSpark, alignment: .leading) }
            Text("Platforms").frame(width: Space.tablePlatforms, alignment: .leading)
            Text("PRs").frame(width: Space.tableFigure, alignment: .trailing)
            Text("Waiting").frame(width: Space.tableFigure, alignment: .trailing)
            Text("Spend 7d").frame(width: Space.tableFigure, alignment: .trailing)
            if !compact { Text("Active").frame(width: Space.tableFigure, alignment: .trailing) }
        }
        .font(Typo.caption)
        .foregroundStyle(Palette.textSecondary)
        .lineLimit(1)
        .padding(.vertical, Space.s)
        .accessibilityHidden(true)
    }
}

private struct ProductTableRow: View {
    @Environment(AppModel.self) private var model
    let product: PortfolioProduct
    let compact: Bool

    private var name: String { HomeFactsBuilder.name(product) }
    private var line: String {
        if let line = ProductLine.text(product) { return line }
        let summary = HomeFactsBuilder.summary(product)
        return summary.isEmpty ? HomeFactsBuilder.noSummary : summary
    }

    var body: some View {
        Button {
            model.go(.product(product.id))
        } label: {
            HStack(spacing: Space.m) {
                identity.frame(maxWidth: .infinity, alignment: .leading)
                if !compact { spark.frame(width: Space.tableSpark, alignment: .leading) }
                PlatformIcons(platforms: product.platforms).frame(width: Space.tablePlatforms, alignment: .leading)
                figure("\(product.prs.open)", dim: product.prs.open == 0)
                figure("\(product.waiting)", dim: product.waiting == 0, tone: product.waiting > 0 ? Palette.needsYou : nil)
                figure(HomeNumbers.dollars(product.activity.spend7dUSD), dim: product.activity.spend7dUSD == 0)
                if !compact {
                    TimelineView(.periodic(from: .now, by: 60)) { context in
                        figure(PortfolioText.lastActiveShort(product.activity, now: context.date), dim: false)
                    }
                }
            }
            .padding(.vertical, Space.s)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("Open the \(name) page")
        .accessibilityHint("Opens the product page")
    }

    private var identity: some View {
        HStack(spacing: Space.m) {
            StarButton(id: product.id, starred: product.focus)
            ProductIcon(product: product, monogram: Monogram.letter(for: name), size: Space.iconRow, radius: Radius.iconRow)
            VStack(alignment: .leading, spacing: Space.xxs) {
                HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                    Text(name).font(Typo.body.weight(.semibold)).lineLimit(1)
                    if !product.stage.isEmpty {
                        Text(product.stage.capitalized).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
                    }
                    // The stage the evidence shows (docs/STARTUP.md), beside the registry stage the owner set.
                    if let startup = product.startup {
                        Chip(text: startup.stageTitle, color: Palette.textSecondary)
                            .help("Earned stage. \(StartupText.sentence(startup))")
                    }
                    // "On track" on every row is noise: the pill appears when there is something to say.
                    if product.health != .onTrack { HealthPill(health: product.health).fixedSize() }
                }
                Text(line)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .help(line)
            }
        }
    }

    @ViewBuilder
    private var spark: some View {
        let facts = HomeFactsBuilder.facts(product, period: .week)
        if let label = facts.sparkLabel {
            SparklineView(heights: facts.sparkHeights, label: label)
        } else {
            Text(Format.dash).font(Typo.caption).foregroundStyle(Palette.textTertiary)
        }
    }

    private func figure(_ text: String, dim: Bool, tone: Color? = nil) -> some View {
        Text(text)
            .font(Typo.body)
            .monospacedDigit()
            .foregroundStyle(tone ?? (dim ? Palette.textTertiary : Palette.text))
            .lineLimit(1)
            .frame(width: Space.tableFigure, alignment: .trailing)
    }
}

/// One small icon per platform, coloured by its state. The tooltip and VoiceOver say the build and the state, so
/// colour never carries the meaning alone.
struct PlatformIcons: View {
    let platforms: [PlatformStatus]

    var body: some View {
        HStack(spacing: Space.xs) {
            if platforms.isEmpty {
                Text(Format.dash).font(Typo.caption).foregroundStyle(Palette.textTertiary)
            }
            ForEach(platforms) { platform in
                if platform.isDirectory, platform.id == platforms.first(where: \.isDirectory)?.id {
                    Divider().frame(height: Space.m)          // devices on the left, AI directories on the right
                }
                Image(systemName: PlatformSymbol.name(for: platform.platform))
                    .font(Typo.caption)
                    .foregroundStyle(platform.state.color)
                    .help(PortfolioText.chip(platform))
                    .accessibilityLabel(PortfolioText.chip(platform))
            }
        }
        .lineLimit(1)
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
            configuration.icon.font(Glyph.bullet).offset(y: -Space.xxs)
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
                SectionHeader(title: "Platforms")
                ForEach(product.platforms) { platform in
                    platformRow(platform)
                }
                if product.platforms.isEmpty {
                    Text("No platform data yet").foregroundStyle(Palette.textSecondary)
                }
            }
            VStack(alignment: .leading, spacing: Space.xs) {
                SectionHeader(title: "Work")
                Group {
                    Label(PortfolioText.lastActivity(product.activity, now: Date()), systemImage: "clock")
                    if let next = ProductLine.shortEnglish(product.next) {
                        Label("Next: \(next)", systemImage: "arrow.right.circle")
                    }
                }
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .labelStyle(FigureLabelStyle())
            }
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
                ClampedText(text: platform.detail, lines: 2)
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

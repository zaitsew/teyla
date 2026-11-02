import SwiftUI

// The product part of Home on the phone: a Week / Month / Year switch, then three sections ranked by the CLI.
// "People use these" are hero cards, "Being built" is one list with the commit count, "Quiet" is a plainer list.
// What each card says comes from `HomeLogic.swift`, which the Mac app shares; this file only places it.
// The visual spec is the owner's board (variant A, "Scoreboard"), 390 pt wide.

/// Sizes taken from the board. Views use these names, not loose numbers.
private enum HomeMetric {
    static let heroIcon: CGFloat = 48
    static let heroIconRadius: CGFloat = 11
    static let builtIcon: CGFloat = 34
    static let builtIconRadius: CGFloat = 8
    static let quietIcon: CGFloat = 26
    static let quietIconRadius: CGFloat = 6
    static let touchMin: CGFloat = 44
    static let listRadius: CGFloat = 14
    static let listInset: CGFloat = 14
    static let rowGap: CGFloat = 11
    static let sparkHeight: CGFloat = 28
    static let sparkBar: CGFloat = 5
    static let sparkGap: CGFloat = 2
    static let barRadius: CGFloat = 2
    static let switchRadius: CGFloat = 10
    static let switchInset: CGFloat = 3
}

/// The selected segment of the period switch: white on light, a step above the track on dark.
private let selectedSegment = Color.brand(light: 0xFFFFFF, dark: 0x3A3A3C)

// MARK: Pieces

/// A section title and, under it, the rule that put a product there. The same for every section of Home,
/// Decisions included.
struct HomeSectionHeader: View {
    let title: String
    let note: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.title3.weight(.semibold))
                .accessibilityAddTraits(.isHeader)
            Text(note)
                .font(.footnote)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Week / Month / Year. One switch for the whole page; it changes numbers and nothing else.
struct PeriodSwitch: View {
    @Binding var period: HomePeriod

    var body: some View {
        HStack(spacing: HomeMetric.sparkGap) {
            ForEach(HomePeriod.allCases) { option in
                let selected = period == option
                Button {
                    period = option
                } label: {
                    Text(option.label)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(selected ? Color.primary : Color.secondary)
                        .frame(maxWidth: .infinity, minHeight: HomeMetric.touchMin)
                        .background(selected ? selectedSegment : Color.clear,
                                    in: RoundedRectangle(cornerRadius: HomeMetric.builtIconRadius, style: .continuous))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .padding(HomeMetric.switchInset)
        .background(Color(.tertiarySystemFill), in: RoundedRectangle(cornerRadius: HomeMetric.switchRadius, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Period")
    }
}

/// The first letter of a name on a tint. A product with users gets the brand tint, a quiet one a neutral grey.
private struct MonogramTile: View {
    let letter: String
    let size: CGFloat
    let quiet: Bool

    var body: some View {
        Text(letter)
            .font(.system(size: size * 0.44, weight: .bold))
            .foregroundStyle(quiet ? Color.secondary : Color.brandPrimary)
            .frame(width: size, height: size)
            .background(quiet ? Color(.tertiarySystemFill) : Color.brandPrimary.opacity(0.14))
    }
}

/// The icon from the CLI, decoded once and kept, or the first letter of the name.
private struct ProductIcon: View {
    let product: PortfolioProduct
    let monogram: String
    let size: CGFloat
    let radius: CGFloat
    var quiet = false

    var body: some View {
        Group {
            if let image = ProductIcons.image(id: product.id, base64: product.iconJPEG) {
                Image(uiImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFill()
            } else {
                MonogramTile(letter: monogram, size: size, quiet: quiet)
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: radius, style: .continuous))
        .accessibilityHidden(true)
    }
}

/// Commits per week as small bars; the newest week stands out. Nothing is drawn for a product with no weeks.
private struct SparklineView: View {
    let heights: [Double]
    let label: String

    var body: some View {
        HStack(alignment: .bottom, spacing: HomeMetric.sparkGap) {
            ForEach(heights.indices, id: \.self) { index in
                RoundedRectangle(cornerRadius: HomeMetric.barRadius)
                    .fill(color(index))
                    .frame(width: HomeMetric.sparkBar, height: max(HomeMetric.sparkGap, HomeMetric.sparkHeight * heights[index]))
            }
        }
        .frame(height: HomeMetric.sparkHeight, alignment: .bottom)
        .accessibilityElement()
        .accessibilityLabel(label)
    }

    private func color(_ index: Int) -> Color {
        if index == heights.count - 1 { return Color.brandPrimary }
        return heights[index] > 0 ? Color.brandPrimary.opacity(0.35) : Color(.quaternarySystemFill)
    }
}

/// One tappable product. The whole card or row is one element for VoiceOver, with `spoken` as its label.
private struct ProductLink<Content: View>: View {
    let id: String
    let spoken: String
    @ViewBuilder var content: Content

    var body: some View {
        NavigationLink(value: ProductRoute(id: id)) {
            content
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
        .accessibilityHint("Opens the product page")
        .accessibilityAddTraits(.isButton)
    }
}

/// "Show all 15" / "Show fewer", at the foot of a long list. At least 44 pt high.
private struct FoldButton: View {
    let label: String
    let expanded: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Color.brandPrimary)
                .frame(maxWidth: .infinity, minHeight: HomeMetric.touchMin)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityValue(expanded ? "expanded" : "collapsed")
    }
}

/// The white (dark: raised) panel that holds the rows of a list.
private struct ListPanel<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        VStack(spacing: 0) { content }
            .padding(.horizontal, HomeMetric.listInset)
            .frame(maxWidth: .infinity)
            .background(Color(.secondarySystemGroupedBackground),
                        in: RoundedRectangle(cornerRadius: HomeMetric.listRadius, style: .continuous))
    }
}

// MARK: People use these

struct HeroList: View {
    let products: [PortfolioProduct]
    let period: HomePeriod

    var body: some View {
        VStack(spacing: 12) {
            ForEach(products) { product in
                HeroCard(product: product, facts: HomeFactsBuilder.facts(product, period: period))
            }
        }
    }
}

private struct HeroCard: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let product: PortfolioProduct
    let facts: HomeFacts

    var body: some View {
        ProductLink(id: product.id, spoken: facts.spoken) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 12) {
                    ProductIcon(product: product, monogram: facts.monogram,
                                size: HomeMetric.heroIcon, radius: HomeMetric.heroIconRadius)
                    VStack(alignment: .leading, spacing: 2) {
                        title
                        Text(facts.summary.isEmpty ? HomeFactsBuilder.noSummary : facts.summary)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                figures
                Divider()
                commitsRow
                MonetizationRow(text: facts.money)
            }
            .card()
        }
    }

    /// The name, then the stage on the same line while it fits.
    private var title: Text {
        let name = Text(facts.name).font(.title3.weight(.bold))
        guard !facts.stage.isEmpty else { return name }
        return Text("\(name)  \(Text(facts.stage).font(.caption).foregroundStyle(.secondary))")
    }

    /// Three columns; at the accessibility sizes one under another, so a big number never clips.
    private var figures: some View {
        let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: 10))
                                                  : AnyLayout(HStackLayout(alignment: .top, spacing: 8))
        return layout {
            Figure(value: facts.active, label: "active")
            Figure(value: facts.new, label: "new")
            Figure(value: facts.total, label: "total")
        }
    }

    private var commitsRow: some View {
        let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: 10))
                                                  : AnyLayout(HStackLayout(alignment: .bottom, spacing: 10))
        return layout {
            VStack(alignment: .leading, spacing: 2) {
                Text(facts.commits).font(.subheadline.weight(.semibold)).monospacedDigit()
                Text(facts.spend).font(.caption).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !typeSize.isAccessibilitySize { Spacer(minLength: 8) }
            if let label = facts.sparkLabel {
                SparklineView(heights: facts.sparkHeights, label: label)
            }
        }
    }
}

/// A big number and what it counts.
private struct Figure: View {
    let value: String
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(value)
                .font(.title.weight(.bold))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.5)
            Text(label).font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// "Monetization   Off". Every product has it; today every one is off.
private struct MonetizationRow: View {
    let text: String

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) { label; Spacer(minLength: 8); value }
            VStack(alignment: .leading, spacing: 2) { label; value }
        }
        .font(.subheadline)
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(.systemGroupedBackground), in: RoundedRectangle(cornerRadius: HomeMetric.switchRadius, style: .continuous))
    }

    private var label: some View { Text("Monetization").foregroundStyle(.secondary) }
    private var value: some View { Text(text).fontWeight(.semibold).foregroundStyle(.secondary).monospacedDigit() }
}

// MARK: Being built

struct BuiltList: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let products: [PortfolioProduct]
    let period: HomePeriod
    @State private var expanded = false

    var body: some View {
        let shown = HomeFold.visible(products, kind: .building, expanded: expanded)
        ListPanel {
            ForEach(Array(shown.enumerated()), id: \.element.id) { index, product in
                BuiltRow(product: product, facts: HomeFactsBuilder.facts(product, period: period),
                         period: period, roomy: typeSize.isAccessibilitySize)
                if index < shown.count - 1 || foldLabel != nil { Divider() }
            }
            if let label = foldLabel {
                FoldButton(label: label, expanded: expanded) {
                    withAnimation(.easeOut(duration: 0.2)) { expanded.toggle() }
                }
            }
        }
    }

    private var foldLabel: String? {
        HomeFold.toggleLabel(kind: .building, total: products.count, expanded: expanded)
    }
}

private struct BuiltRow: View {
    let product: PortfolioProduct
    let facts: HomeFacts
    let period: HomePeriod
    let roomy: Bool

    var body: some View {
        let summary = facts.summary.isEmpty ? HomeFactsBuilder.noSummary : facts.summary
        ProductLink(id: product.id, spoken: "\(facts.name). \(summary). \(facts.commits) \(period.phrase).") {
            HStack(spacing: HomeMetric.rowGap) {
                ProductIcon(product: product, monogram: facts.monogram,
                            size: HomeMetric.builtIcon, radius: HomeMetric.builtIconRadius)
                VStack(alignment: .leading, spacing: 1) {
                    Text(facts.name).font(.subheadline.weight(.semibold)).lineLimit(roomy ? 3 : 1)
                    Text(summary).font(.caption).foregroundStyle(.secondary).lineLimit(roomy ? 4 : 1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .trailing, spacing: 0) {
                    Text(facts.commitsCount).font(.subheadline.weight(.semibold)).monospacedDigit()
                    Text(facts.commitsCount == "1" ? "commit" : "commits")
                        .font(.caption2).foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 6)
            .frame(minHeight: HomeMetric.touchMin)
        }
    }
}

// MARK: Quiet

struct QuietList: View {
    @Environment(\.dynamicTypeSize) private var typeSize
    let products: [PortfolioProduct]
    @State private var expanded = false

    var body: some View {
        let shown = HomeFold.visible(products, kind: .quiet, expanded: expanded)
        ListPanel {
            ForEach(Array(shown.enumerated()), id: \.element.id) { index, product in
                QuietRow(product: product, roomy: typeSize.isAccessibilitySize)
                if index < shown.count - 1 || foldLabel != nil { Divider() }
            }
            if let label = foldLabel {
                FoldButton(label: label, expanded: expanded) {
                    withAnimation(.easeOut(duration: 0.2)) { expanded.toggle() }
                }
            }
        }
    }

    private var foldLabel: String? {
        HomeFold.toggleLabel(kind: .quiet, total: products.count, expanded: expanded)
    }
}

private struct QuietRow: View {
    let product: PortfolioProduct
    let roomy: Bool

    var body: some View {
        let name = HomeFactsBuilder.name(product)
        let summary = HomeFactsBuilder.summary(product)
        ProductLink(id: product.id,
                    spoken: "\(name). \(summary.isEmpty ? "No description yet" : summary). \(HomeFactsBuilder.quietCommits(product)).") {
            HStack(spacing: HomeMetric.rowGap) {
                ProductIcon(product: product, monogram: Monogram.letter(for: name),
                            size: HomeMetric.quietIcon, radius: HomeMetric.quietIconRadius, quiet: true)
                VStack(alignment: .leading, spacing: 1) {
                    Text(name).font(.subheadline.weight(.medium)).lineLimit(roomy ? 3 : 1)
                    Text(summary.isEmpty ? HomeFactsBuilder.noSummary : summary)
                        .font(.caption).foregroundStyle(.secondary).lineLimit(roomy ? 4 : 1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                // "4 commits" over "this week": the same words as the Mac's row, on two short lines.
                VStack(alignment: .trailing, spacing: 0) {
                    Text(HomeFactsBuilder.quietCount(product)).monospacedDigit()
                    Text(HomePeriod.week.phrase)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.trailing)
            }
            .padding(.vertical, 6)
            .frame(minHeight: HomeMetric.touchMin)
        }
    }
}

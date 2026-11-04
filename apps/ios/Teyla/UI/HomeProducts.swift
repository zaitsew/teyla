import SwiftUI

// The product part of Home on the phone: a Week / Month / Year switch, then three sections ranked by the CLI.
// "People use these" are hero cards, "Being built" is one list with the commit count, "Quiet" is a plainer list.
// What each card says comes from `HomeLogic.swift`, which the Mac app shares; this file only places it.
// The visual spec is the owner's board (variant A, "Scoreboard"), 390 pt wide.

// MARK: Pieces

/// A section title and, under it, the rule that put a product there. The same for every section of Home,
/// Decisions included.
struct HomeSectionHeader: View {
    let title: String
    let note: String

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(title)
                .font(Typo.section)
                .accessibilityAddTraits(.isHeader)
            Text(note)
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// Week / Month / Year. One switch for the whole page; it changes numbers and nothing else.
struct PeriodSwitch: View {
    @Binding var period: HomePeriod

    var body: some View {
        HStack(spacing: Space.xxs) {
            ForEach(HomePeriod.allCases) { option in
                let selected = period == option
                Button {
                    period = option
                } label: {
                    Text(option.label)
                        .font(Typo.body.weight(.semibold))
                        .foregroundStyle(selected ? Palette.text : Palette.textSecondary)
                        .frame(maxWidth: .infinity, minHeight: Space.touchMin)
                        .background(selected ? Palette.selectedSegment : Color.clear,
                                    in: RoundedRectangle(cornerRadius: Radius.iconCard, style: .continuous))
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .padding(Space.xxs)
        .background(Palette.track, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
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
            .font(Typo.monogram(side: size))
            .foregroundStyle(quiet ? Palette.textSecondary : Palette.primary)
            .frame(width: size, height: size)
            .background(quiet ? Palette.track : Palette.primaryTint)
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
        HStack(alignment: .bottom, spacing: Space.xxs) {
            ForEach(heights.indices, id: \.self) { index in
                RoundedRectangle(cornerRadius: Radius.bar)
                    .fill(color(index))
                    .frame(width: Space.sparkBar, height: max(Space.xxs, Space.sparkHeight * heights[index]))
            }
        }
        .frame(height: Space.sparkHeight, alignment: .bottom)
        .accessibilityElement()
        .accessibilityLabel(label)
    }

    private func color(_ index: Int) -> Color {
        if index == heights.count - 1 { return Palette.primary }
        return heights[index] > 0 ? Palette.primaryMuted : Palette.border
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
                .font(Typo.body.weight(.semibold))
                .foregroundStyle(Palette.primary)
                .frame(maxWidth: .infinity, minHeight: Space.touchMin)
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
            .padding(.horizontal, Space.m)
            .frame(maxWidth: .infinity)
            .background(Palette.surface,
                        in: RoundedRectangle(cornerRadius: Radius.panel, style: .continuous))
    }
}

// MARK: People use these

struct HeroList: View {
    let products: [PortfolioProduct]
    let period: HomePeriod

    var body: some View {
        VStack(spacing: Space.m) {
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
            VStack(alignment: .leading, spacing: Space.m) {
                HStack(alignment: .top, spacing: Space.m) {
                    ProductIcon(product: product, monogram: facts.monogram,
                                size: Space.iconHero, radius: Radius.iconHero)
                    VStack(alignment: .leading, spacing: Space.xxs) {
                        title
                        Text(facts.summary.isEmpty ? HomeFactsBuilder.noSummary : facts.summary)
                            .font(Typo.caption)
                            .foregroundStyle(Palette.textSecondary)
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
        let name = Text(facts.name).font(Typo.section)
        guard !facts.stage.isEmpty else { return name }
        return Text("\(name)  \(Text(facts.stage).font(Typo.caption).foregroundStyle(Palette.textSecondary))")
    }

    /// Three columns; at the accessibility sizes one under another, so a big number never clips.
    private var figures: some View {
        let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: Space.s))
                                                  : AnyLayout(HStackLayout(alignment: .top, spacing: Space.s))
        return layout {
            Figure(value: facts.active, label: "active")
            Figure(value: facts.new, label: "new")
            Figure(value: facts.total, label: "total")
        }
    }

    private var commitsRow: some View {
        let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading, spacing: Space.s))
                                                  : AnyLayout(HStackLayout(alignment: .bottom, spacing: Space.s))
        return layout {
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(facts.commits).font(Typo.body.weight(.semibold)).monospacedDigit()
                Text(facts.spend).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if !typeSize.isAccessibilitySize { Spacer(minLength: Space.s) }
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
        VStack(alignment: .leading, spacing: Space.xs) {
            Text(value)
                .font(Typo.number)
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.5)
            Text(label).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// "Monetization   Off". Every product has it; today every one is off.
private struct MonetizationRow: View {
    let text: String

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: Space.s) { label; Spacer(minLength: Space.s); value }
            VStack(alignment: .leading, spacing: Space.xxs) { label; value }
        }
        .font(Typo.body)
        .padding(.horizontal, Space.m)
        .padding(.vertical, Space.s)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.background, in: RoundedRectangle(cornerRadius: Radius.card, style: .continuous))
    }

    private var label: some View { Text("Monetization").foregroundStyle(Palette.textSecondary) }
    private var value: some View { Text(text).fontWeight(.semibold).foregroundStyle(Palette.textSecondary).monospacedDigit() }
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
            HStack(spacing: Space.m) {
                ProductIcon(product: product, monogram: facts.monogram,
                            size: Space.iconCard, radius: Radius.iconCard)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(facts.name).font(Typo.body.weight(.semibold)).lineLimit(roomy ? 3 : 1)
                    Text(summary).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(roomy ? 4 : 1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .trailing, spacing: 0) {
                    Text(facts.commitsCount).font(Typo.body.weight(.semibold)).monospacedDigit()
                    Text(facts.commitsCount == "1" ? "commit" : "commits")
                        .font(Typo.caption).foregroundStyle(Palette.textSecondary)
                }
            }
            .padding(.vertical, Space.xs)
            .frame(minHeight: Space.touchMin)
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
            HStack(spacing: Space.m) {
                ProductIcon(product: product, monogram: Monogram.letter(for: name),
                            size: Space.iconRow, radius: Radius.iconRow, quiet: true)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(name).font(Typo.body.weight(.medium)).lineLimit(roomy ? 3 : 1)
                    Text(summary.isEmpty ? HomeFactsBuilder.noSummary : summary)
                        .font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(roomy ? 4 : 1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                // "4 commits" over "this week": the same words as the Mac's row, on two short lines.
                VStack(alignment: .trailing, spacing: 0) {
                    Text(HomeFactsBuilder.quietCount(product)).monospacedDigit()
                    Text(HomePeriod.week.phrase)
                }
                .font(Typo.caption)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.trailing)
            }
            .padding(.vertical, Space.xs)
            .frame(minHeight: Space.touchMin)
        }
    }
}

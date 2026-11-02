import SwiftUI

// The product part of Home: three sections, ranked by the CLI. A hero card for products people use, a smaller
// card for products being built, a plain row for the rest. Each opens the product page.

// MARK: Pieces

/// A section title and the rule that put a product in it.
struct HomeSectionHeader: View {
    let title: String
    let note: String

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xxs) {
            Text(title)
                .font(Typo.section)
                .accessibilityAddTraits(.isHeader)
            Text(note)
                .font(Typo.note)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// The icon from the CLI, or the first letter of the name on a tint of the primary colour.
struct ProductIcon: View {
    let product: PortfolioProduct
    let monogram: String
    let size: CGFloat
    let radius: CGFloat

    var body: some View {
        Group {
            if let image = ProductIcons.image(id: product.id, base64: product.iconJPEG) {
                Image(nsImage: image)
                    .resizable()
                    .interpolation(.high)
                    .scaledToFill()
            } else {
                MonogramTile(letter: monogram, size: size)
            }
        }
        .frame(width: size, height: size)
        .clipShape(RoundedRectangle(cornerRadius: radius))
        .accessibilityHidden(true)
    }
}

/// The first letter of a name on a tint of the primary colour.
struct MonogramTile: View {
    let letter: String
    let size: CGFloat

    var body: some View {
        Text(letter)
            .font(Typo.monogram(side: size))
            .foregroundStyle(Palette.primary)
            .frame(width: size, height: size)
            .background(Palette.primaryTint)
    }
}

/// Commits per week as small bars; the newest week stands out. Nothing is drawn for a product with no weeks.
struct SparklineView: View {
    let heights: [Double]
    let label: String
    let height: CGFloat
    let barWidth: CGFloat

    var body: some View {
        HStack(alignment: .bottom, spacing: Space.xxs) {
            ForEach(heights.indices, id: \.self) { index in
                RoundedRectangle(cornerRadius: Radius.bar)
                    .fill(color(index))
                    .frame(width: barWidth, height: max(Space.xxs, height * heights[index]))
            }
        }
        .frame(height: height, alignment: .bottom)
        .accessibilityElement()
        .accessibilityLabel(label)
    }

    private func color(_ index: Int) -> Color {
        if index == heights.count - 1 { return Palette.primary }
        return heights[index] > 0 ? Palette.primaryMuted : Palette.border
    }
}

/// The surface of a card: white on light, raised on dark, with a hairline border.
private struct CardSurface: ViewModifier {
    let radius: CGFloat
    let padding: CGFloat

    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Palette.surface, in: RoundedRectangle(cornerRadius: radius))
            .overlay(RoundedRectangle(cornerRadius: radius).strokeBorder(Palette.border, lineWidth: 1))
            .contentShape(RoundedRectangle(cornerRadius: radius))
    }
}

private extension View {
    func cardSurface(radius: CGFloat, padding: CGFloat) -> some View {
        modifier(CardSurface(radius: radius, padding: padding))
    }
}

/// A product opens from any of the three shapes the same way.
private struct OpensProduct: ViewModifier {
    @Environment(AppModel.self) private var model
    let id: String
    let name: String
    let spoken: String

    func body(content: Content) -> some View {
        Button {
            model.go(.product(id))
        } label: {
            content
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
        .accessibilityHint("Opens the product page")
        .accessibilityAddTraits(.isButton)
        .help("Open the \(name) page")
    }
}

private extension View {
    func opensProduct(id: String, name: String, spoken: String) -> some View {
        modifier(OpensProduct(id: id, name: name, spoken: spoken))
    }
}

// MARK: People use these

struct HeroGrid: View {
    let products: [PortfolioProduct]
    let period: HomePeriod

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: Space.heroCardMin), spacing: Space.l, alignment: .top)],
                  alignment: .leading, spacing: Space.l) {
            ForEach(products) { product in
                HeroCard(product: product, facts: HomeFactsBuilder.facts(product, period: period))
            }
        }
    }
}

private struct HeroCard: View {
    let product: PortfolioProduct
    let facts: HomeFacts

    var body: some View {
        VStack(alignment: .leading, spacing: Space.l) {
            HStack(alignment: .top, spacing: Space.m + Space.xxs) {
                ProductIcon(product: product, monogram: facts.monogram, size: Space.iconHero, radius: Radius.iconHero)
                VStack(alignment: .leading, spacing: Space.xxs) {
                    HStack(alignment: .firstTextBaseline, spacing: Space.s) {
                        Text(facts.name).font(Typo.cardTitle).lineLimit(1)
                        if !facts.stage.isEmpty {
                            Text(facts.stage).font(Typo.note).foregroundStyle(Palette.textSecondary).lineLimit(1)
                        }
                    }
                    Text(facts.summary.isEmpty ? HomeFactsBuilder.noSummary : facts.summary)
                        .font(Typo.body)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            HStack(alignment: .top, spacing: Space.m) {
                Figure(value: facts.active, label: "active users")
                Figure(value: facts.new, label: "new users")
                Figure(value: facts.total, label: "users in total")
            }
            Spacer(minLength: 0)
            Divider()
            HStack(alignment: .bottom, spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(facts.commits).font(Typo.lead.weight(.semibold)).monospacedDigit()
                    Text(facts.spend).font(Typo.note).foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: Space.s)
                if let label = facts.sparkLabel {
                    SparklineView(heights: facts.sparkHeights, label: label,
                                  height: Space.sparkHeroHeight, barWidth: Space.sparkHeroBar)
                }
            }
            MonetizationChip(text: facts.money)
        }
        .cardSurface(radius: Radius.panel, padding: Space.l + Space.xs)
        .opensProduct(id: product.id, name: facts.name, spoken: facts.spoken)
    }
}

/// A big number and what it counts.
private struct Figure: View {
    let value: String
    let label: String

    var body: some View {
        VStack(alignment: .leading, spacing: Space.xs) {
            Text(value)
                .font(Typo.heroNumber)
                .lineLimit(1)
                .minimumScaleFactor(0.6)
            Text(label).font(Typo.note).foregroundStyle(Palette.textSecondary).lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

/// "Monetization   Off". Every product has it; today every one is off.
private struct MonetizationChip: View {
    let text: String

    var body: some View {
        HStack(spacing: Space.s) {
            Text("Monetization").foregroundStyle(Palette.textSecondary)
            Spacer(minLength: Space.s)
            Text(text).fontWeight(.semibold).foregroundStyle(Palette.textSecondary).monospacedDigit()
        }
        .font(Typo.body)
        .padding(.horizontal, Space.m)
        .padding(.vertical, Space.s + Space.xxs)
        .background(Palette.background, in: RoundedRectangle(cornerRadius: Radius.card))
    }
}

// MARK: Being built

struct BuiltGrid: View {
    let products: [PortfolioProduct]
    let period: HomePeriod

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: Space.builtCardMin), spacing: Space.m, alignment: .top)],
                  alignment: .leading, spacing: Space.m) {
            ForEach(products) { product in
                BuiltCard(product: product, facts: HomeFactsBuilder.facts(product, period: period))
            }
        }
    }
}

private struct BuiltCard: View {
    let product: PortfolioProduct
    let facts: HomeFacts

    var body: some View {
        HStack(alignment: .center, spacing: Space.m) {
            ProductIcon(product: product, monogram: facts.monogram, size: Space.iconCard, radius: Radius.iconCard)
            VStack(alignment: .leading, spacing: Space.xxs) {
                Text(facts.name).font(Typo.lead.weight(.semibold)).lineLimit(1)
                Text(facts.summary.isEmpty ? HomeFactsBuilder.noSummary : facts.summary)
                    .font(Typo.note)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Space.s)
            VStack(alignment: .trailing, spacing: Space.xxs) {
                Text(facts.commitsCount).font(Typo.cardNumber)
                Text(facts.commitsCount == "1" ? "commit" : "commits")
                    .font(Typo.caption).foregroundStyle(Palette.textSecondary)
                if let label = facts.sparkLabel {
                    SparklineView(heights: facts.sparkHeights, label: label,
                                  height: Space.sparkCardHeight, barWidth: Space.sparkCardBar)
                        .padding(.top, Space.xxs)
                }
            }
        }
        .cardSurface(radius: Radius.card, padding: Space.m + Space.xxs)
        .opensProduct(id: product.id, name: facts.name, spoken: facts.spoken)
    }
}

// MARK: Quiet

struct QuietList: View {
    let products: [PortfolioProduct]

    var body: some View {
        LazyVStack(spacing: 0) {
            ForEach(Array(products.enumerated()), id: \.element.id) { index, product in
                QuietRow(product: product)
                if index < products.count - 1 { Divider() }
            }
        }
        .padding(.horizontal, Space.l)
        .padding(.vertical, Space.xs)
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: Radius.card))
        .overlay(RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Palette.border, lineWidth: 1))
    }
}

private struct QuietRow: View {
    let product: PortfolioProduct

    var body: some View {
        let name = HomeFactsBuilder.name(product)
        let summary = HomeFactsBuilder.summary(product)
        let commits = HomeFactsBuilder.quietCommits(product)
        HStack(spacing: Space.m) {
            ProductIcon(product: product, monogram: Monogram.letter(for: name), size: Space.iconRow, radius: Radius.iconRow)
            Text(name)
                .font(Typo.body.weight(.semibold))
                .lineLimit(1)
                .frame(width: Space.quietName, alignment: .leading)
            Text(summary.isEmpty ? HomeFactsBuilder.noSummary : summary)
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(commits)
                .font(Typo.body)
                .foregroundStyle(Palette.textSecondary)
                .monospacedDigit()
                .lineLimit(1)
        }
        .frame(minHeight: Space.touchMin)
        .contentShape(Rectangle())
        .opensProduct(id: product.id, name: name, spoken: "\(name). \(summary.isEmpty ? "No description yet" : summary). \(commits).")
    }
}

// MARK: A teyla command before the Home sections

/// The core list as plain rows, for a teyla command that does not send `portfolio.home` yet.
struct LegacyList: View {
    @Environment(AppModel.self) private var model
    let cards: [CoreCard]

    var body: some View {
        LazyVStack(spacing: 0) {
            ForEach(Array(cards.enumerated()), id: \.element.id) { index, card in
                Button {
                    model.go(.product(card.id))
                } label: {
                    HStack(spacing: Space.m) {
                        MonogramTile(letter: Monogram.letter(for: card.title), size: Space.iconRow)
                            .clipShape(RoundedRectangle(cornerRadius: Radius.iconRow))
                            .accessibilityHidden(true)
                        Text(card.title).font(Typo.body.weight(.semibold)).lineLimit(1)
                            .frame(width: Space.quietName, alignment: .leading)
                        Text(card.line).font(Typo.body).foregroundStyle(Palette.textSecondary).lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(minHeight: Space.touchMin)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityHint("Opens the product page")
                if index < cards.count - 1 { Divider() }
            }
        }
        .padding(.horizontal, Space.l)
        .padding(.vertical, Space.xs)
        .background(Palette.surface, in: RoundedRectangle(cornerRadius: Radius.card))
        .overlay(RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Palette.border, lineWidth: 1))
    }
}

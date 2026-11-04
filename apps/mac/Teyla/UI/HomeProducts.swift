import SwiftUI

// The product part of Home: three sections, ranked by the CLI. A hero card for products people use, a smaller
// card for products being built, a plain row for the rest. Each opens the product page.

// MARK: Pieces

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
        Scorecard(title: facts.name, badge: facts.stage,
                  summary: facts.summary.isEmpty ? HomeFactsBuilder.noSummary : facts.summary,
                  numbers: [ScoreNumber(value: facts.active, label: "active users"),
                            ScoreNumber(value: facts.new, label: "new users"),
                            ScoreNumber(value: facts.total, label: "users in total")]) {
            ProductIcon(product: product, monogram: facts.monogram, size: Space.iconHero, radius: Radius.iconHero)
        } footer: {
            HStack(alignment: .bottom, spacing: Space.m) {
                VStack(alignment: .leading, spacing: Space.xxs) {
                    Text(facts.commits).font(Typo.cardTitle).monospacedDigit().lineLimit(1)
                    Text(facts.spend).font(Typo.caption).foregroundStyle(Palette.textSecondary).lineLimit(2)
                }
                Spacer(minLength: Space.s)
                if let label = facts.sparkLabel {
                    SparklineView(heights: facts.sparkHeights, label: label,
                                  height: Space.sparkHeroHeight, barWidth: Space.sparkHeroBar)
                }
            }
            MonetizationChip(text: facts.money)
        }
        .opensProduct(id: product.id, name: facts.name, spoken: facts.spoken)
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
        .padding(.vertical, Space.s)
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
                Text(facts.name).font(Typo.cardTitle).lineLimit(1)
                Text(facts.summary.isEmpty ? HomeFactsBuilder.noSummary : facts.summary)
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: Space.s)
            VStack(alignment: .trailing, spacing: Space.xxs) {
                Text(facts.commitsCount).font(Typo.cardTitle)
                Text(facts.commitsCount == "1" ? "commit" : "commits")
                    .font(Typo.caption).foregroundStyle(Palette.textSecondary)
                if let label = facts.sparkLabel {
                    SparklineView(heights: facts.sparkHeights, label: label,
                                  height: Space.sparkCardHeight, barWidth: Space.sparkCardBar)
                        .padding(.top, Space.xxs)
                }
            }
        }
        .surface(padding: Space.m)
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
        .overlay(RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Palette.border, lineWidth: Space.hairline))
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
        .overlay(RoundedRectangle(cornerRadius: Radius.card).strokeBorder(Palette.border, lineWidth: Space.hairline))
    }
}

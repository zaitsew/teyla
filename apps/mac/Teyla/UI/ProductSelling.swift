import SwiftUI

/// Users and selling on a product page. One number each, first: active users, sale attempts, what shipped this week, and
/// the feedback, reviews and crashes no source feeds yet. A figure the app does not have is a dash with the reason.
/// Zero sale attempts reads "not tried yet" and points at the next marketing slot; this page never suggests closing the product.
struct ProductSellingSection: View {
    @Environment(AppModel.self) private var model
    let productID: String
    let parked: Bool
    let portfolio: PortfolioProduct?

    var body: some View {
        let growth = model.growth
        let attempts = growth.sales?.attempts(for: productID)
        VStack(alignment: .leading, spacing: Space.m) {
            SectionHeader(title: "Users and selling", note: "What people do with it, and what was done to sell it.")
            StatStrip {
                usersTile
                StatTile(label: "Sale attempts",
                         value: attempts.map(SaleLogic.figure),
                         detail: attempts.map { SaleLogic.detail($0, parked: parked) }
                             ?? (growth.salesFailure ?? "Reading the growth ledger."),
                         tone: (attempts.map { !$0.tried } ?? false) && !parked ? .needsYou : .neutral)
                shippedTile
                StatTile(label: "Feedback and crashes", value: nil,
                         detail: "No source reports these yet.")
            }
            if let attempts, attempts.tried {
                RowGroup {
                    ForEach(SaleLogic.rows(attempts), id: \.label) { row in
                        RowCard(title: row.label, detail: row.note) {
                            Text("\(row.count)")
                                .font(Typo.body.weight(.semibold).monospacedDigit())
                                .foregroundStyle(row.count == 0 ? Palette.textTertiary : Palette.text)
                        }
                    }
                    RowCard(title: "Last attempt", detail: "From the growth ledger") {
                        Text(SaleLogic.lastWords(attempts)).font(Typo.caption).foregroundStyle(Palette.textSecondary)
                    }
                }
            }
            if let skipped = growth.sales?.skipped, skipped > 0 {
                Text("\(skipped) ledger line\(skipped == 1 ? "" : "s") could not be read and \(skipped == 1 ? "is" : "are") not counted.")
                    .font(Typo.caption)
                    .foregroundStyle(Palette.textSecondary)
            }
        }
        .onAppear { growth.loadSales() }
    }

    private var usersTile: some View {
        let users = portfolio?.progress?.users
        let detail: String
        if let users {
            detail = users.label.isEmpty ? "\(users.total) in total." : users.label + "."
        } else if portfolio == nil {
            detail = "The portfolio report has not loaded."
        } else {
            detail = "This product has no usage counter."
        }
        return StatTile(label: "Active users, week", value: users.map { "\($0.weekly)" }, detail: detail)
    }

    private var shippedTile: some View {
        let progress = portfolio?.progress
        let detail: String
        if let progress {
            detail = progress.shippedTop.first ?? "No pull request merged in 7 days."
        } else {
            detail = "The portfolio report has not loaded."
        }
        return StatTile(label: "Shipped, 7 days", value: progress.map { "\($0.shippedPRs)" }, detail: detail)
    }
}

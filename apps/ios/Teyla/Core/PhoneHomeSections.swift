import Foundation

// How the phone folds the long sections of Home. The sections and their order come from `HomeSections.layout`
// (the CLI's ranking, shared with the Mac); this only decides how many rows show before "Show all N".

enum HomeFold {
    /// Rows shown before the button, or nil when the section always shows everything.
    static func limit(_ kind: HomeSectionKind) -> Int? {
        switch kind {
        case .users: return nil
        case .building: return 6
        case .quiet: return 5
        }
    }

    /// The products on screen: the first `limit` while folded, all of them once opened. The order never changes.
    static func visible(_ products: [PortfolioProduct], kind: HomeSectionKind, expanded: Bool) -> [PortfolioProduct] {
        guard let limit = limit(kind), !expanded else { return products }
        return Array(products.prefix(limit))
    }

    /// "Show all 15" while folded, "Show fewer" once opened; nil when nothing is hidden, so there is no button.
    static func toggleLabel(kind: HomeSectionKind, total: Int, expanded: Bool) -> String? {
        guard let limit = limit(kind), total > limit else { return nil }
        return expanded ? "Show fewer" : "Show all \(total)"
    }
}

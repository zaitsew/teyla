import Foundation

// The one rule of Today that needs a draft. Kept out of `TodayLogic.swift` so the iPhone app can compile that file
// without the growth drafts.

extension TodayLogic {
    /// What the O key opens for a draft: the first web source it stands on. nil: no link, so the page shows the detail.
    static func openTarget(_ draft: GrowthDraft) -> URL? {
        draft.sources.lazy.compactMap { webLink($0.link) }.first
    }
}

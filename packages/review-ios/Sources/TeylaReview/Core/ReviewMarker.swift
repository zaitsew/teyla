#if TEYLA_REVIEW
/// A string that exists only when the overlay is compiled in (`TEYLA_REVIEW` defined). `present()`
/// stores it, so the linker keeps it through dead stripping whenever the entry point is called.
/// `teyla review store-check` looks for these bytes in a store archive's executable and frameworks
/// (docs/REVIEW.md). Do not shorten it: Swift inlines strings of 15 bytes or fewer, and an inlined
/// string leaves nothing to find.
enum ReviewMarker {
    static let overlay = "TEYLA_REVIEW_IOS_ACTIVE"

    @MainActor static var lastEntry = ""
}
#endif

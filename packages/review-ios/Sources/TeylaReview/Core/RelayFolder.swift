import Foundation

/// The iCloud Drive folder `Teyla/` that the Mac syncs. A product cannot see another app's iCloud
/// folder, so the owner picks it once with the document picker; the package keeps a bookmark.
struct RelayFolder {
    private let defaults: UserDefaults
    private let key = "teyla.review.relayFolderBookmark"

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    var isChosen: Bool { defaults.data(forKey: key) != nil }

    func remember(_ url: URL) throws {
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        defaults.set(try url.bookmarkData(), forKey: key)
    }

    func forget() { defaults.removeObject(forKey: key) }

    /// Runs `body` with access to the folder. Returns nil when no folder is chosen or the bookmark is dead.
    func withAccess<T>(_ body: (URL) throws -> T) rethrows -> T? {
        guard let data = defaults.data(forKey: key) else { return nil }
        var stale = false
        guard let url = try? URL(resolvingBookmarkData: data, bookmarkDataIsStale: &stale) else { return nil }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        if stale, let fresh = try? url.bookmarkData() { defaults.set(fresh, forKey: key) }
        return try body(url)
    }
}

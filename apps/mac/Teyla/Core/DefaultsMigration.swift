import Foundation

/// The full app used to share the bundle id `com.zaitsew.teyla` with the store build; it is now
/// `com.zaitsew.teyla.local`. Its first launch copies the old settings over, once, so nobody loses
/// the chosen `teyla` file, the shortcuts, the voice language or the default product.
enum DefaultsMigration {
    static let oldDomain = "com.zaitsew.teyla"
    /// Written when the migration has run, so a setting the owner removes later does not come back.
    static let doneKey = "defaultsMigratedFrom"
    /// Everything the app persists: the `teyla` file (TeylaBinary.defaultsKey), the default product,
    /// the voice language (Voice.defaultsKey) and the quick-note shortcut (ShortcutStore.key).
    static let keys = ["teylaBinaryPath", "selectedProduct", "voiceLocale", "quickNoteShortcut"]

    /// Copies each key the old domain has and the new one lacks. Returns the keys it copied.
    /// `old` is the old domain's contents; by default they are read from the preferences of `oldDomain`.
    @discardableResult
    static func run(into defaults: UserDefaults = .standard, old: [String: Any]? = nil) -> [String] {
        guard defaults.string(forKey: doneKey) == nil else { return [] }
        let source = old ?? defaults.persistentDomain(forName: oldDomain) ?? [:]
        var copied: [String] = []
        for key in keys where defaults.object(forKey: key) == nil {
            guard let value = source[key] else { continue }
            defaults.set(value, forKey: key)
            copied.append(key)
        }
        defaults.set(oldDomain, forKey: doneKey)
        return copied
    }
}
